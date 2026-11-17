#!/usr/bin/env python3
"""
Weekly Product Review (WPR) Sync Engine — zero external dependencies (Python 3.8+ stdlib).

Reads the Markdown source of truth (`wpr/wpr-config.md`, `wpr/metrics-data.md`,
and `wpr/reviews/*.md`) and supports:
  - `validate`    : Validates config, quarter-scoped targets, formulas, week dates, and data hygiene.
  - `add-week`    : Prepends a new week entry to `wpr/metrics-data.md`.
  - `import-csv`  : Reconciles manual metric values from a single-tab CSV export into `wpr/metrics-data.md`.
  - `import-xlsx` : Reconciles manual metric values from all quarter tabs of an `.xlsx` export into `wpr/metrics-data.md`.
  - `build`       : Generates a multi-year, styled `.xlsx` workbook (active quarter tab selected,
                    YoY/QoQ/WoW/rolling averages, carryover cumsum), a Google-Doc-ready `.md`/`.html`
                    weekly review brief + running `wpr-review-archive.md`, a starter
                    `wpr/reviews/<date>-wpr.md` if missing, and `sheets-payload.json` with `row_signature`.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import html
import json
import re
import sys
import zipfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from xml.sax.saxutils import escape as xml_escape


WEEKDAY_MAP = {
    "monday": 0,
    "tuesday": 1,
    "wednesday": 2,
    "thursday": 3,
    "friday": 4,
    "saturday": 5,
    "sunday": 6,
}

VALID_TYPES = {"manual", "calculated", "automated", "not-collected"}
VALID_FORMATS = {"int", "float", "currency", "percent"}
VALID_ANALYSES = {"wow", "rolling_4w", "qtd_sum", "vs_target", "vs_prior_q", "yoy"}

# Swiss Precision Grid ARGB palette
FILL_NONE = 0
FILL_ZINC_CALC = 2       # #FAFAFA (calculated / automated)
FILL_ICE_MANUAL = 3      # #EFF6FF (manual weekly input)
FILL_AMBER_PENDING = 4   # #FFEDD5 (not collected / N/A)
FILL_SLATE_SECTION = 5   # #F1F5F9 (section divider & calendar strip)
FILL_LEGEND_BG = 6       # #F8FAFC (subtle legend row)
FILL_MIDNIGHT_HEADER = 7 # #09090B (Row 5 header bar)

EXCEL_EPOCH = dt.date(1899, 12, 30)
XLSX_NS = {
    "m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
}


@dataclass
class MetricDef:
    section: str
    metric_id: str
    name: str
    mtype: str
    fmt: str
    target_raw: str
    analyses: List[str]
    formula: str
    owner: str
    source_eta: str

    def target_for_tab(self, tab_name: str) -> Tuple[str, Optional[float]]:
        """Resolve quarter-scoped targets like 'Q1: 20; Q2 26: 30; 35' for `tab_name`."""
        raw = self.target_raw.strip()
        if not raw:
            return "", None
        if ";" not in raw and ":" not in raw:
            return raw, parse_number(raw)

        tab_norm = tab_name.strip().lower()
        q_only = tab_norm.split()[0] if tab_norm.startswith("q") else ""
        default_val = ""
        exact_match = None
        q_match = None

        for part in raw.split(";"):
            p = part.strip()
            if not p:
                continue
            if ":" in p:
                k, v = [x.strip() for x in p.split(":", 1)]
                kl = k.lower()
                if kl == tab_norm:
                    exact_match = v
                elif q_only and kl == q_only:
                    q_match = v
                elif tab_norm.startswith("full year") and kl in {"fy", "full year", tab_norm}:
                    exact_match = v
            else:
                default_val = p

        chosen = exact_match if exact_match is not None else (q_match if q_match is not None else default_val)
        return chosen, parse_number(chosen)

    @property
    def target_num(self) -> Optional[float]:
        _, num = self.target_for_tab("")
        return num


@dataclass
class WPRConfig:
    product_name: str = "My Product"
    year: int = dt.date.today().year
    week_ending_day: str = "Friday"
    meeting_cadence: str = ""
    owners: str = ""
    style: str = "standard"
    sheet_id: str = ""
    doc_id: str = ""
    sheet_url: str = ""
    doc_url: str = ""
    metrics: List[MetricDef] = field(default_factory=list)
    changelog: List[Dict[str, str]] = field(default_factory=list)

    @property
    def no_em_dash(self) -> bool:
        return "no-em-dash" in self.style.lower()

    @property
    def dash(self) -> str:
        return "-" if self.no_em_dash else "—"


@dataclass
class WeekCell:
    metric_id: str
    metric_name: str
    value_raw: str
    value_num: Optional[float]
    status: str
    note: str


@dataclass
class WeekEntry:
    week_date: dt.date
    cells: Dict[str, WeekCell] = field(default_factory=dict)


def parse_number(raw: str) -> Optional[float]:
    if raw is None:
        return None
    s = raw.strip()
    if not s or s.upper() in {"N/A", "NA", "-", "--", "TBD"}:
        return None
    is_pct = s.endswith("%")
    cleaned = s.replace(",", "").replace("$", "").replace("€", "").replace("£", "").rstrip("%").strip()
    try:
        val = float(cleaned)
        return val / 100.0 if is_pct else val
    except ValueError:
        return None


def parse_markdown_table(lines: List[str]) -> List[Dict[str, str]]:
    """Parse the first Markdown pipe table found in `lines` into a list of row dicts."""
    rows: List[List[str]] = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("|") and stripped.endswith("|"):
            parts = [p.strip() for p in stripped[1:-1].split("|")]
            rows.append(parts)
        elif rows:
            break
    if len(rows) < 2:
        return []
    headers = rows[0]
    data_rows: List[Dict[str, str]] = []
    for row in rows[1:]:
        if all(re.fullmatch(r":?-+:?", cell.replace(" ", "")) for cell in row if cell != ""):
            continue
        padded = row + [""] * (len(headers) - len(row))
        data_rows.append({headers[i]: padded[i] for i in range(len(headers))})
    return data_rows


def load_config(path: Path) -> WPRConfig:
    if not path.exists():
        raise FileNotFoundError(f"Missing config file: {path}")
    text = path.read_text(encoding="utf-8")
    cfg = WPRConfig()

    meta_patterns = {
        "product / program name": "product_name",
        "product name": "product_name",
        "program name": "product_name",
        "business name": "product_name",
        "year": "year",
        "week ending day": "week_ending_day",
        "meeting cadence": "meeting_cadence",
        "owners / attendees": "owners",
        "style": "style",
        "google sheet id": "sheet_id",
        "google doc id": "doc_id",
        "google sheet url": "sheet_url",
        "google doc url": "doc_url",
    }
    for line in text.splitlines():
        m = re.match(r"^\s*-\s*\*\*(.+?)\*\*\s*:\s*(.*)$", line)
        if not m:
            continue
        key = m.group(1).strip().lower()
        val = m.group(2).strip()
        if key in meta_patterns and val:
            attr = meta_patterns[key]
            if attr == "year":
                try:
                    setattr(cfg, attr, int(val))
                except ValueError:
                    pass
            else:
                setattr(cfg, attr, val)

    lines = text.splitlines()
    cat_idx = None
    chg_idx = None
    for idx, line in enumerate(lines):
        if re.match(r"^\s*##\s+Metric Catalog", line, re.IGNORECASE):
            cat_idx = idx
        elif re.match(r"^\s*##\s+Metric\s*&\s*Target\s+Changelog", line, re.IGNORECASE):
            chg_idx = idx
    if cat_idx is None:
        raise ValueError("Could not find '## Metric Catalog' section in wpr-config.md")

    for row in parse_markdown_table(lines[cat_idx + 1 :]):
        metric_id = row.get("ID", "").strip()
        name = row.get("Metric", "").strip()
        if not metric_id or not name:
            continue
        analyses_raw = row.get("Analyses", "").strip()
        analyses = [a.strip().lower() for a in analyses_raw.split(",") if a.strip()]
        cfg.metrics.append(
            MetricDef(
                section=row.get("Section", "General").strip() or "General",
                metric_id=metric_id,
                name=name,
                mtype=(row.get("Type", "manual").strip().lower() or "manual"),
                fmt=(row.get("Format", "int").strip().lower() or "int"),
                target_raw=row.get("Target", "").strip(),
                analyses=analyses,
                formula=row.get("Formula", "").strip(),
                owner=row.get("Owner", "").strip(),
                source_eta=row.get("Source / ETA", "").strip(),
            )
        )

    if chg_idx is not None:
        for row in parse_markdown_table(lines[chg_idx + 1 :]):
            if any(v.strip() for v in row.values()):
                cfg.changelog.append(row)

    return cfg


def load_metrics_data(path: Path) -> List[WeekEntry]:
    if not path.exists():
        raise FileNotFoundError(f"Missing metrics data file: {path}")
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()

    entries: List[WeekEntry] = []
    i = 0
    while i < len(lines):
        m = re.match(r"^\s*##\s+Week\s+(\d{4}-\d{2}-\d{2})\b", lines[i])
        if m:
            wdate = dt.date.fromisoformat(m.group(1))
            j = i + 1
            while j < len(lines) and not re.match(r"^\s*##\s+Week\s+\d{4}-\d{2}-\d{2}\b", lines[j]):
                j += 1
            table_rows = parse_markdown_table(lines[i + 1 : j])
            entry = WeekEntry(week_date=wdate)
            for row in table_rows:
                mid = row.get("ID", "").strip()
                if not mid:
                    continue
                vraw = row.get("Value", "").strip()
                entry.cells[mid] = WeekCell(
                    metric_id=mid,
                    metric_name=row.get("Metric", "").strip(),
                    value_raw=vraw,
                    value_num=parse_number(vraw),
                    status=row.get("Status", "").strip().lower(),
                    note=row.get("Note", "").strip(),
                )
            entries.append(entry)
            i = j
        else:
            i += 1

    entries.sort(key=lambda e: e.week_date, reverse=True)
    return entries


def save_metrics_data(path: Path, cfg: WPRConfig, entries: List[WeekEntry]) -> None:
    entries_sorted = sorted(entries, key=lambda e: e.week_date, reverse=True)
    out: List[str] = ["# Weekly Metrics Data", ""]
    for entry in entries_sorted:
        q = (entry.week_date.month - 1) // 3 + 1
        q_start = dt.date(entry.week_date.year, 3 * q - 2, 1)
        woq = (entry.week_date - q_start).days // 7 + 1
        yy = str(entry.week_date.year)[-2:]
        out.append(f"## Week {entry.week_date.isoformat()}")
        out.append(f"- Quarter: Q{q} {yy} | Week of Quarter: {woq} | Week of Year: {entry.week_date.isocalendar()[1]}")
        out.append("")
        out.append("| ID | Metric | Value | Status | Note |")
        out.append("| :--- | :--- | :--- | :--- | :--- |")
        for mdef in cfg.metrics:
            cell = entry.cells.get(mdef.metric_id)
            vraw = cell.value_raw if cell else ""
            status = (cell.status if cell and cell.status else mdef.mtype)
            note = cell.note if cell else (mdef.source_eta if mdef.mtype == "not-collected" else "")
            out.append(f"| {mdef.metric_id} | {mdef.name} | {vraw} | {status} | {note} |")
        out.append("")
    path.write_text("\n".join(out), encoding="utf-8")


def validate_wpr(wpr_dir: Path) -> Tuple[List[str], List[str]]:
    errors: List[str] = []
    warnings: List[str] = []

    cfg = load_config(wpr_dir / "wpr-config.md")
    if not cfg.metrics:
        errors.append("Metric Catalog is empty in wpr-config.md.")
        return errors, warnings

    id_set = {m.metric_id for m in cfg.metrics}
    seen_ids = set()
    for m in cfg.metrics:
        if m.metric_id in seen_ids:
            errors.append(f"Duplicate metric ID: {m.metric_id}")
        seen_ids.add(m.metric_id)
        if m.mtype not in VALID_TYPES:
            errors.append(f"Metric '{m.metric_id}' has invalid Type '{m.mtype}' (expected one of {sorted(VALID_TYPES)}).")
        if m.fmt not in VALID_FORMATS:
            errors.append(f"Metric '{m.metric_id}' has invalid Format '{m.fmt}' (expected one of {sorted(VALID_FORMATS)}).")
        for a in m.analyses:
            if a not in VALID_ANALYSES:
                errors.append(f"Metric '{m.metric_id}' has unknown analysis '{a}' (expected one of {sorted(VALID_ANALYSES)}).")
        if m.formula.startswith("cumsum:"):
            ref = m.formula.split(":", 1)[1].strip()
            if ref not in id_set:
                errors.append(f"Metric '{m.metric_id}' cumsum references unknown ID '{ref}'.")
        elif m.formula.startswith("ratio:"):
            expr = m.formula.split(":", 1)[1].strip()
            parts = expr.split("/")
            if len(parts) != 2 or any(p.strip() not in id_set for p in parts):
                errors.append(f"Metric '{m.metric_id}' ratio formula '{m.formula}' must reference two valid metric IDs.")
        elif m.formula.startswith("diff:"):
            expr = m.formula.split(":", 1)[1].strip()
            parts = expr.split("-")
            if len(parts) != 2 or any(p.strip() not in id_set for p in parts):
                errors.append(f"Metric '{m.metric_id}' diff formula '{m.formula}' must reference two valid metric IDs.")

    if len(cfg.metrics) < 5:
        warnings.append(f"Only {len(cfg.metrics)} metrics defined; 7-10 is recommended for most teams.")
    elif len(cfg.metrics) > 25:
        warnings.append(f"{len(cfg.metrics)} metrics defined; consider trimming to 7-20 so weekly reviews stay focused.")

    data_path = wpr_dir / "metrics-data.md"
    if data_path.exists():
        entries = load_metrics_data(data_path)
        if not entries:
            warnings.append("metrics-data.md has no week entries yet.")
        else:
            newest = entries[0]
            for m in cfg.metrics:
                c = newest.cells.get(m.metric_id)
                if m.mtype == "manual" and (not c or not c.value_raw):
                    warnings.append(f"Newest week {newest.week_date}: manual metric '{m.metric_id}' is blank.")
    else:
        warnings.append("metrics-data.md does not exist yet.")

    return errors, warnings


def col_letter(idx_1based: int) -> str:
    res = []
    n = idx_1based
    while n > 0:
        n, rem = divmod(n - 1, 26)
        res.append(chr(65 + rem))
    return "".join(reversed(res))


def excel_serial(d: dt.date) -> int:
    return (d - EXCEL_EPOCH).days


def dates_for_year(year: int, ending_day: str) -> Dict[int, List[dt.date]]:
    """Return {quarter: [dates newest-first]} for the given calendar year."""
    target_wd = WEEKDAY_MAP.get(ending_day.strip().lower(), 4)
    d = dt.date(year, 1, 1)
    while d.weekday() != target_wd:
        d += dt.timedelta(days=1)
    quarters: Dict[int, List[dt.date]] = {1: [], 2: [], 3: [], 4: []}
    while d.year == year:
        q = (d.month - 1) // 3 + 1
        quarters[q].append(d)
        d += dt.timedelta(days=7)
    for q in quarters:
        quarters[q].sort(reverse=True)
    return quarters


def evaluate_metric_series(
    cfg: WPRConfig,
    entries_asc: List[WeekEntry],
) -> Dict[Tuple[dt.date, str], Optional[float]]:
    """Compute numeric values (including calculated metrics with cross-quarter/year cumsum) chronologically."""
    vals: Dict[Tuple[dt.date, str], Optional[float]] = {}
    running_sums: Dict[str, float] = {}
    for entry in entries_asc:
        d = entry.week_date
        for m in cfg.metrics:
            cell = entry.cells.get(m.metric_id)
            if cell and cell.value_num is not None:
                vals[(d, m.metric_id)] = cell.value_num
                running_sums[m.metric_id] = running_sums.get(m.metric_id, 0.0) + cell.value_num
                continue
            if m.mtype == "calculated" and m.formula:
                if m.formula.startswith("cumsum:"):
                    src_id = m.formula.split(":", 1)[1].strip()
                    if vals.get((d, src_id)) is None:
                        vals[(d, m.metric_id)] = None
                    else:
                        vals[(d, m.metric_id)] = running_sums.get(src_id, 0.0)
                elif m.formula.startswith("ratio:"):
                    num_id, den_id = [x.strip() for x in m.formula.split(":", 1)[1].split("/")]
                    num = vals.get((d, num_id))
                    den = vals.get((d, den_id))
                    vals[(d, m.metric_id)] = (num / den) if (num is not None and den not in (None, 0.0)) else None
                elif m.formula.startswith("diff:"):
                    a_id, b_id = [x.strip() for x in m.formula.split(":", 1)[1].split("-")]
                    a = vals.get((d, a_id))
                    b = vals.get((d, b_id))
                    vals[(d, m.metric_id)] = (a - b) if (a is not None and b is not None) else None
                else:
                    vals[(d, m.metric_id)] = None
            else:
                vals[(d, m.metric_id)] = None
    return vals


def compute_row_signature(cfg: WPRConfig) -> str:
    """Stable hash of metric row layout (used to detect whether column-only Sheets sync is safe)."""
    layout = [
        {
            "section": m.section,
            "id": m.metric_id,
            "analyses": m.analyses,
            "formula": m.formula,
        }
        for m in cfg.metrics
    ]
    raw = json.dumps(layout, sort_keys=True).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:16]


def build_sheet_grid(
    cfg: WPRConfig,
    tab_name: str,
    week_dates_desc: List[dt.date],
    entries_by_date: Dict[dt.date, WeekEntry],
    prior_q_tab: Optional[str],
    prior_q_dates: Optional[List[dt.date]],
    prior_year_tab: Optional[str],
    prior_year_dates: Optional[List[dt.date]],
    prior_cumsum_tabs: List[Tuple[str, int]],
    latest_note_by_date: Dict[dt.date, str],
) -> Tuple[List[List[dict]], Dict[str, int]]:
    """Build a 2D grid of cell dicts for a quarter or Full Year sheet."""
    ncols = 2 + len(week_dates_desc)
    oldest_col_idx = ncols
    oldest_col_let = col_letter(oldest_col_idx)

    row_cursor = 8
    metric_row_map: Dict[str, int] = {}
    last_section = None
    for m in cfg.metrics:
        if m.section != last_section:
            last_section = m.section
            row_cursor += 1
        metric_row_map[m.metric_id] = row_cursor
        row_cursor += 1 + len(m.analyses) + 1

    grid: List[List[dict]] = []

    def blank_row() -> List[dict]:
        return [{"v": None, "f": None, "fill": 0, "fmt": 0, "bold": False, "font": 0, "border": 0, "align": None} for _ in range(ncols)]

    # Rows 1-4: Compact calendar metadata strip (Cool Slate)
    r1 = blank_row()
    r1[0] = {"v": "Quarter", "f": None, "fill": FILL_SLATE_SECTION, "fmt": 0, "bold": False, "font": 3, "border": 1, "align": "left"}
    r1[1] = {"v": None, "f": None, "fill": FILL_SLATE_SECTION, "fmt": 0, "bold": False, "font": 3, "border": 1, "align": None}
    r2 = blank_row()
    r2[0] = {"v": "Week of Quarter", "f": None, "fill": FILL_SLATE_SECTION, "fmt": 0, "bold": False, "font": 3, "border": 1, "align": "left"}
    r2[1] = {"v": None, "f": None, "fill": FILL_SLATE_SECTION, "fmt": 0, "bold": False, "font": 3, "border": 1, "align": None}
    r3 = blank_row()
    r3[0] = {"v": "Week of Year", "f": None, "fill": FILL_SLATE_SECTION, "fmt": 0, "bold": False, "font": 3, "border": 1, "align": "left"}
    r3[1] = {"v": None, "f": None, "fill": FILL_SLATE_SECTION, "fmt": 0, "bold": False, "font": 3, "border": 1, "align": None}
    r4 = blank_row()
    r4[0] = {"v": cfg.week_ending_day, "f": None, "fill": FILL_SLATE_SECTION, "fmt": 0, "bold": True, "font": 1, "border": 1, "align": "left"}
    r4[1] = {"v": None, "f": None, "fill": FILL_SLATE_SECTION, "fmt": 0, "bold": False, "font": 3, "border": 1, "align": None}

    for i, wd in enumerate(week_dates_desc):
        c_idx = 3 + i
        cl = col_letter(c_idx)
        r1[2 + i] = {"v": None, "f": f"ROUNDUP(MONTH({cl}4)/3,0)", "fill": FILL_SLATE_SECTION, "fmt": 1, "bold": False, "font": 3, "border": 1, "align": "right"}
        r2[2 + i] = {"v": None, "f": f"INT(({cl}4-DATE(YEAR({cl}4),3*{cl}1-2,1))/7)+1", "fill": FILL_SLATE_SECTION, "fmt": 1, "bold": False, "font": 3, "border": 1, "align": "right"}
        r3[2 + i] = {"v": None, "f": f"WEEKNUM({cl}4)", "fill": FILL_SLATE_SECTION, "fmt": 1, "bold": False, "font": 3, "border": 1, "align": "right"}
        if i == len(week_dates_desc) - 1:
            r4[2 + i] = {"v": excel_serial(wd), "f": None, "fill": FILL_SLATE_SECTION, "fmt": 5, "bold": False, "font": 3, "border": 1, "align": "right"}
        else:
            next_cl = col_letter(c_idx + 1)
            r4[2 + i] = {"v": None, "f": f"{next_cl}4+7", "fill": FILL_SLATE_SECTION, "fmt": 5, "bold": False, "font": 3, "border": 1, "align": "right"}

    # Row 5: Midnight header bar (Metric | Target | Week Dates)
    r5 = [{"v": None, "f": None, "fill": FILL_MIDNIGHT_HEADER, "fmt": 0, "bold": True, "font": 2, "border": 2, "align": "right"} for _ in range(ncols)]
    r5[0]["v"] = "Metric"
    r5[0]["align"] = "left"
    r5[1]["v"] = "Target"
    for i in range(len(week_dates_desc)):
        cl = col_letter(3 + i)
        r5[2 + i]["f"] = f"{cl}4"
        r5[2 + i]["fmt"] = 6  # mmm dd

    # Row 6: Subtle Legend strip
    r6 = [{"v": None, "f": None, "fill": FILL_LEGEND_BG, "fmt": 0, "bold": False, "font": 3, "border": 1, "align": "left"} for _ in range(ncols)]
    r6[0]["v"] = "Legend"
    r6[2 if ncols > 2 else 1]["v"] = "Ice Blue = manual input | Zinc = calculated or automated | Amber = not yet instrumented or N/A"

    grid.extend([r1, r2, r3, r4, r5, r6])
    grid.append(blank_row())  # Row 7 spacer

    fmt_map = {"int": 1, "float": 2, "currency": 3, "percent": 4}
    today_d = max(entries_by_date.keys()) if entries_by_date else dt.date.today()

    last_section = None
    for m in cfg.metrics:
        if m.section != last_section:
            last_section = m.section
            srow = [{"v": None, "f": None, "fill": FILL_SLATE_SECTION, "fmt": 0, "bold": True, "font": 1, "border": 2, "align": "left"} for _ in range(ncols)]
            srow[0]["v"] = m.section
            grid.append(srow)

        mrow_num = metric_row_map[m.metric_id]
        mrow = blank_row()
        mrow[0] = {"v": m.name, "f": None, "fill": 0, "fmt": 0, "bold": True, "font": 1, "border": 1, "align": "left"}
        traw, tnum = m.target_for_tab(tab_name)
        mrow[1] = {
            "v": tnum if tnum is not None else (traw or None),
            "f": None,
            "fill": 0,
            "fmt": fmt_map.get(m.fmt, 1) if tnum is not None else 0,
            "bold": False,
            "font": 3,
            "border": 1,
            "align": "right",
        }

        m_fill = FILL_ICE_MANUAL if m.mtype == "manual" else (FILL_AMBER_PENDING if m.mtype == "not-collected" else FILL_ZINC_CALC)
        m_font = 4 if m.mtype == "manual" else (5 if m.mtype == "not-collected" else 0)
        m_fmt = fmt_map.get(m.fmt, 1)

        for i, wd in enumerate(week_dates_desc):
            c_idx = 3 + i
            cl = col_letter(c_idx)
            entry = entries_by_date.get(wd)
            wcell = entry.cells.get(m.metric_id) if entry else None

            if m.mtype == "not-collected":
                eta_text = m.source_eta if (wd <= today_d and i == 0 and m.source_eta) else None
                mrow[2 + i] = {"v": eta_text, "f": None, "fill": FILL_AMBER_PENDING, "fmt": 0, "bold": False, "font": 5, "border": 1, "align": "right"}
            elif m.mtype == "calculated" and m.formula:
                formula_str = None
                if m.formula.startswith("cumsum:"):
                    src_id = m.formula.split(":", 1)[1].strip()
                    sr = metric_row_map[src_id]
                    base_sum = f"SUM({cl}{sr}:${oldest_col_let}{sr})"
                    if prior_cumsum_tabs:
                        carry = "+".join(
                            f"SUM('{ptab}'!$C{sr}:${col_letter(p_oldest_idx)}{sr})"
                            for ptab, p_oldest_idx in prior_cumsum_tabs
                        )
                        formula_str = f'IF(ISBLANK({cl}{sr}),"",{base_sum}+{carry})'
                    else:
                        formula_str = f'IF(ISBLANK({cl}{sr}),"",{base_sum})'
                elif m.formula.startswith("ratio:"):
                    a_id, b_id = [x.strip() for x in m.formula.split(":", 1)[1].split("/")]
                    ar, br = metric_row_map[a_id], metric_row_map[b_id]
                    formula_str = f'IF(OR(ISBLANK({cl}{ar}),ISBLANK({cl}{br})),"",IFERROR({cl}{ar}/{cl}{br},"N/A"))'
                elif m.formula.startswith("diff:"):
                    a_id, b_id = [x.strip() for x in m.formula.split(":", 1)[1].split("-")]
                    ar, br = metric_row_map[a_id], metric_row_map[b_id]
                    formula_str = f'IF(OR(ISBLANK({cl}{ar}),ISBLANK({cl}{br})),"",{cl}{ar}-{cl}{br})'
                else:
                    formula_str = m.formula.replace("{col}", cl).lstrip("=")
                mrow[2 + i] = {"v": None, "f": formula_str, "fill": FILL_ZINC_CALC, "fmt": m_fmt, "bold": False, "font": 0, "border": 1, "align": "right"}
            else:
                val = wcell.value_num if (wcell and wcell.value_num is not None) else (wcell.value_raw if (wcell and wcell.value_raw) else None)
                mrow[2 + i] = {"v": val, "f": None, "fill": m_fill, "fmt": m_fmt, "bold": False, "font": m_font, "border": 1, "align": "right"}
        grid.append(mrow)

        # Analysis sub-rows
        for analysis in m.analyses:
            arow = blank_row()
            label_map = {
                "wow": "WoW Change",
                "rolling_4w": "4-Week Avg",
                "qtd_sum": "YTD Total" if tab_name.startswith("Full Year") else "QTD Total",
                "vs_target": "Target Delta",
                "vs_prior_q": "QoQ Delta",
                "yoy": "YoY Delta",
            }
            arow[0] = {"v": f"  {label_map[analysis]}", "f": None, "fill": 0, "fmt": 0, "bold": False, "font": 3, "border": 1, "align": "left"}
            arow[1] = {"v": None, "f": None, "fill": 0, "fmt": 0, "bold": False, "font": 3, "border": 1, "align": "right"}
            for i, wd in enumerate(week_dates_desc):
                c_idx = 3 + i
                cl = col_letter(c_idx)
                remaining_right = len(week_dates_desc) - 1 - i

                if analysis == "wow":
                    if remaining_right < 1:
                        arow[2 + i] = {"v": "N/A", "f": None, "fill": FILL_AMBER_PENDING, "fmt": 0, "bold": False, "font": 5, "border": 1, "align": "right"}
                    else:
                        next_cl = col_letter(c_idx + 1)
                        arow[2 + i] = {"v": None, "f": f'IF(ISBLANK({cl}{mrow_num}),"",IFERROR({cl}{mrow_num}/{next_cl}{mrow_num}-1,"N/A"))', "fill": FILL_ZINC_CALC, "fmt": 4, "bold": False, "font": 3, "border": 1, "align": "right"}
                elif analysis == "rolling_4w":
                    if remaining_right < 3:
                        arow[2 + i] = {"v": "N/A", "f": None, "fill": FILL_AMBER_PENDING, "fmt": 0, "bold": False, "font": 5, "border": 1, "align": "right"}
                    else:
                        end_cl = col_letter(c_idx + 3)
                        arow[2 + i] = {"v": None, "f": f'IF(ISBLANK({cl}{mrow_num}),"",AVERAGE({cl}{mrow_num}:{end_cl}{mrow_num}))', "fill": FILL_ZINC_CALC, "fmt": 2 if m_fmt == 1 else m_fmt, "bold": False, "font": 3, "border": 1, "align": "right"}
                elif analysis == "qtd_sum":
                    arow[2 + i] = {"v": None, "f": f'IF(ISBLANK({cl}{mrow_num}),"",SUM({cl}{mrow_num}:${oldest_col_let}{mrow_num}))', "fill": FILL_ZINC_CALC, "fmt": m_fmt, "bold": False, "font": 3, "border": 1, "align": "right"}
                elif analysis == "vs_target":
                    arow[2 + i] = {"v": None, "f": f'IF(OR(ISBLANK({cl}{mrow_num}),ISBLANK($B{mrow_num})),"",IFERROR({cl}{mrow_num}/$B{mrow_num}-1,"N/A"))', "fill": FILL_ZINC_CALC, "fmt": 4, "bold": False, "font": 3, "border": 1, "align": "right"}
                elif analysis == "vs_prior_q":
                    if not prior_q_tab or not prior_q_dates or remaining_right >= len(prior_q_dates):
                        arow[2 + i] = {"v": "N/A", "f": None, "fill": FILL_AMBER_PENDING, "fmt": 0, "bold": False, "font": 5, "border": 1, "align": "right"}
                    else:
                        prev_i = len(prior_q_dates) - 1 - remaining_right
                        prev_cl = col_letter(3 + prev_i)
                        arow[2 + i] = {"v": None, "f": f"IF(OR(ISBLANK({cl}{mrow_num}),ISBLANK('{prior_q_tab}'!{prev_cl}{mrow_num})),\"\",IFERROR({cl}{mrow_num}/'{prior_q_tab}'!{prev_cl}{mrow_num}-1,\"N/A\"))", "fill": FILL_ZINC_CALC, "fmt": 4, "bold": False, "font": 3, "border": 1, "align": "right"}
                elif analysis == "yoy":
                    if not prior_year_tab or not prior_year_dates or remaining_right >= len(prior_year_dates):
                        arow[2 + i] = {"v": "N/A", "f": None, "fill": FILL_AMBER_PENDING, "fmt": 0, "bold": False, "font": 5, "border": 1, "align": "right"}
                    else:
                        py_i = len(prior_year_dates) - 1 - remaining_right
                        py_cl = col_letter(3 + py_i)
                        arow[2 + i] = {"v": None, "f": f"IF(OR(ISBLANK({cl}{mrow_num}),ISBLANK('{prior_year_tab}'!{py_cl}{mrow_num})),\"\",IFERROR({cl}{mrow_num}/'{prior_year_tab}'!{py_cl}{mrow_num}-1,\"N/A\"))", "fill": FILL_ZINC_CALC, "fmt": 4, "bold": False, "font": 3, "border": 1, "align": "right"}
            grid.append(arow)

        grid.append(blank_row())

    notes_hdr = blank_row()
    notes_hdr[0] = {"v": "Notes", "f": None, "fill": FILL_SLATE_SECTION, "fmt": 0, "bold": True, "font": 1, "border": 2, "align": "left"}
    for c_i in range(1, ncols):
        notes_hdr[c_i]["fill"] = FILL_SLATE_SECTION
        notes_hdr[c_i]["border"] = 2
    grid.append(notes_hdr)

    notes_row = blank_row()
    notes_row[0] = {"v": "Weekly Highlights / Doc", "f": None, "fill": 0, "fmt": 0, "bold": False, "font": 3, "border": 1, "align": "left"}
    notes_row[1] = {"v": None, "f": None, "fill": 0, "fmt": 0, "bold": False, "font": 3, "border": 1, "align": None}
    for i, wd in enumerate(week_dates_desc):
        if wd in latest_note_by_date:
            notes_row[2 + i] = {"v": latest_note_by_date[wd], "f": None, "fill": 0, "fmt": 0, "bold": False, "font": 0, "border": 1, "align": "left"}
    grid.append(notes_row)

    return grid, metric_row_map


def write_xlsx(sheets: List[Tuple[str, List[List[dict]]]], out_path: Path, active_tab_idx: int = 0) -> None:
    """Write a styled multi-sheet OOXML .xlsx workbook using Python stdlib only."""
    shared_strings: List[str] = []
    ss_index: Dict[str, int] = {}

    def intern_str(s: str) -> int:
        if s not in ss_index:
            ss_index[s] = len(shared_strings)
            shared_strings.append(s)
        return ss_index[s]

    fmt_code_map = {0: 0, 1: 3, 2: 167, 3: 165, 4: 166, 5: 164, 6: 168}
    # (fill_id, font_id, numFmtId, border_id, align_key)
    xf_list: List[Tuple[int, int, int, int, str]] = [(0, 0, 0, 0, "")]
    xf_map: Dict[Tuple[int, int, int, int, str], int] = {(0, 0, 0, 0, ""): 0}

    def get_xf(cell: dict) -> int:
        fill_id = cell["fill"]
        font_id = cell.get("font", 1 if cell["bold"] else 0)
        num_fmt_id = fmt_code_map.get(cell["fmt"], 0)
        border_id = cell.get("border", 0)
        align_key = cell.get("align") or ""
        key = (fill_id, font_id, num_fmt_id, border_id, align_key)
        if key not in xf_map:
            xf_map[key] = len(xf_list)
            xf_list.append(key)
        return xf_map[key]

    sheet_xmls: List[str] = []
    for s_idx_zero, (_, grid) in enumerate(sheets):
        ncols = max((len(r) for r in grid), default=3)
        cols_xml = [
            '<col min="1" max="1" width="34" customWidth="1"/>',
            '<col min="2" max="2" width="14" customWidth="1"/>',
        ]
        if ncols > 2:
            cols_xml.append(f'<col min="3" max="{ncols}" width="15" customWidth="1"/>')

        rows_xml: List[str] = []
        for r_idx, row in enumerate(grid, start=1):
            c_xml: List[str] = []
            for c_idx, cell in enumerate(row, start=1):
                v = cell["v"]
                f = cell["f"]
                xf = get_xf(cell)
                if v is None and f is None and xf == 0:
                    continue
                ref = f"{col_letter(c_idx)}{r_idx}"
                if f is not None:
                    c_xml.append(f'<c r="{ref}" s="{xf}"><f>{xml_escape(f)}</f></c>')
                elif isinstance(v, (int, float)) and not isinstance(v, bool):
                    c_xml.append(f'<c r="{ref}" s="{xf}"><v>{v}</v></c>')
                elif v is not None:
                    s_idx = intern_str(str(v))
                    c_xml.append(f'<c r="{ref}" t="s" s="{xf}"><v>{s_idx}</v></c>')
                else:
                    c_xml.append(f'<c r="{ref}" s="{xf}"/>')
            if c_xml:
                if r_idx == 5:
                    ht = 28
                elif r_idx in (1, 2, 3, 4):
                    ht = 18
                elif r_idx == 6:
                    ht = 19
                elif any(cell.get("fill") == FILL_SLATE_SECTION for cell in row):
                    ht = 24
                else:
                    ht = 21
                rows_xml.append(f'<row r="{r_idx}" ht="{ht}" customHeight="1">{"".join(c_xml)}</row>')
            elif r_idx == 7:
                rows_xml.append(f'<row r="{r_idx}" ht="10" customHeight="1"/>')

        tab_sel = "1" if s_idx_zero == active_tab_idx else "0"
        max_row = max(len(grid), 8)
        last_col = col_letter(max(ncols, 3))
        cf_xml = (
            f'<conditionalFormatting sqref="C8:{last_col}{max_row}">'
            '<cfRule type="cellIs" dxfId="0" priority="1" operator="equal">'
            '<formula>"N/A"</formula>'
            '</cfRule></conditionalFormatting>'
        )
        ws = (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
            f'<sheetViews><sheetView tabSelected="{tab_sel}" workbookViewId="0">'
            '<pane xSplit="2" ySplit="5" topLeftCell="C6" activePane="bottomRight" state="frozen"/>'
            '</sheetView></sheetViews>'
            f'<cols>{"".join(cols_xml)}</cols>'
            f'<sheetData>{"".join(rows_xml)}</sheetData>'
            f'{cf_xml}'
            '</worksheet>'
        )
        sheet_xmls.append(ws)

    xfs_parts = []
    for fill_id, font_id, nfmt, border_id, align_key in xf_list:
        align_xml = f'<alignment horizontal="{align_key}" vertical="center"/>' if align_key else '<alignment vertical="center"/>'
        xfs_parts.append(
            f'<xf numFmtId="{nfmt}" fontId="{font_id}" fillId="{fill_id}" borderId="{border_id}" xfId="0"'
            f' applyNumberFormat="{"1" if nfmt else "0"}" applyFont="1"'
            f' applyFill="{"1" if fill_id else "0"}" applyBorder="{"1" if border_id else "0"}" applyAlignment="1">'
            f'{align_xml}</xf>'
        )
    xfs_xml = "".join(xfs_parts)
    styles_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        '<numFmts count="5">'
        '<numFmt numFmtId="164" formatCode="yyyy-mm-dd"/>'
        '<numFmt numFmtId="165" formatCode="$#,##0"/>'
        '<numFmt numFmtId="166" formatCode="0.0%"/>'
        '<numFmt numFmtId="167" formatCode="#,##0.0"/>'
        '<numFmt numFmtId="168" formatCode="mmm dd"/>'
        '</numFmts>'
        '<fonts count="6">'
        '<font><sz val="10"/><color rgb="FF09090B"/><name val="Inter"/></font>'
        '<font><b/><sz val="10"/><color rgb="FF0F172A"/><name val="Inter"/></font>'
        '<font><b/><sz val="10"/><color rgb="FFFAFAFA"/><name val="Inter"/></font>'
        '<font><sz val="10"/><color rgb="FF52525B"/><name val="Inter"/></font>'
        '<font><sz val="10"/><color rgb="FF1E3A8A"/><name val="Inter"/></font>'
        '<font><sz val="10"/><color rgb="FF9A3412"/><name val="Inter"/></font>'
        '</fonts>'
        '<fills count="8">'
        '<fill><patternFill patternType="none"/></fill>'
        '<fill><patternFill patternType="gray125"/></fill>'
        '<fill><patternFill patternType="solid"><fgColor rgb="FFFAFAFA"/></patternFill></fill>'
        '<fill><patternFill patternType="solid"><fgColor rgb="FFEFF6FF"/></patternFill></fill>'
        '<fill><patternFill patternType="solid"><fgColor rgb="FFFFEDD5"/></patternFill></fill>'
        '<fill><patternFill patternType="solid"><fgColor rgb="FFF1F5F9"/></patternFill></fill>'
        '<fill><patternFill patternType="solid"><fgColor rgb="FFF8FAFC"/></patternFill></fill>'
        '<fill><patternFill patternType="solid"><fgColor rgb="FF09090B"/></patternFill></fill>'
        '</fills>'
        '<borders count="3">'
        '<border><left/><right/><top/><bottom/><diagonal/></border>'
        '<border>'
        '<left style="thin"><color rgb="FFE2E8F0"/></left>'
        '<right style="thin"><color rgb="FFE2E8F0"/></right>'
        '<top style="thin"><color rgb="FFE2E8F0"/></top>'
        '<bottom style="thin"><color rgb="FFE2E8F0"/></bottom>'
        '<diagonal/></border>'
        '<border>'
        '<left style="thin"><color rgb="FFE2E8F0"/></left>'
        '<right style="thin"><color rgb="FFE2E8F0"/></right>'
        '<top style="thin"><color rgb="FFE2E8F0"/></top>'
        '<bottom style="medium"><color rgb="FF94A3B8"/></bottom>'
        '<diagonal/></border>'
        '</borders>'
        '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
        f'<cellXfs count="{len(xf_list)}">{xfs_xml}</cellXfs>'
        '<dxfs count="1"><dxf><font><color rgb="FF9A3412"/><name val="Inter"/></font><fill><patternFill patternType="solid"><fgColor rgb="FFFFEDD5"/><bgColor rgb="FFFFEDD5"/></patternFill></fill></dxf></dxfs>'
        '</styleSheet>'
    )

    ss_items = "".join(f"<si><t>{xml_escape(s)}</t></si>" for s in shared_strings)
    shared_strings_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" count="{len(shared_strings)}" uniqueCount="{len(shared_strings)}">'
        f"{ss_items}</sst>"
    )

    sheets_wb = "".join(
        f'<sheet name="{xml_escape(name)}" sheetId="{idx}" r:id="rId{idx}"/>'
        for idx, (name, _) in enumerate(sheets, start=1)
    )
    workbook_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        f'<bookViews><workbookView activeTab="{active_tab_idx}"/></bookViews>'
        f"<sheets>{sheets_wb}</sheets></workbook>"
    )

    wb_rels = "".join(
        f'<Relationship Id="rId{idx}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet{idx}.xml"/>'
        for idx in range(1, len(sheets) + 1)
    )
    s_rid = len(sheets) + 1
    ss_rid = len(sheets) + 2
    wb_rels_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        f"{wb_rels}"
        f'<Relationship Id="rId{s_rid}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>'
        f'<Relationship Id="rId{ss_rid}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/sharedStrings" Target="sharedStrings.xml"/>'
        '</Relationships>'
    )

    root_rels_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
        '</Relationships>'
    )

    sheet_overrides = "".join(
        f'<Override PartName="/xl/worksheets/sheet{idx}.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
        for idx in range(1, len(sheets) + 1)
    )
    content_types_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
        '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
        '<Override PartName="/xl/sharedStrings.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sharedStrings+xml"/>'
        f"{sheet_overrides}</Types>"
    )

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", content_types_xml)
        z.writestr("_rels/.rels", root_rels_xml)
        z.writestr("xl/workbook.xml", workbook_xml)
        z.writestr("xl/_rels/workbook.xml.rels", wb_rels_xml)
        z.writestr("xl/styles.xml", styles_xml)
        z.writestr("xl/sharedStrings.xml", shared_strings_xml)
        for idx, ws in enumerate(sheet_xmls, start=1):
            z.writestr(f"xl/worksheets/sheet{idx}.xml", ws)


def format_val(val: Optional[float], fmt: str, dash: str = "—") -> str:
    if val is None:
        return dash
    if fmt == "percent":
        return f"{val * 100:.1f}%"
    if fmt == "currency":
        return f"${val:,.0f}"
    if fmt == "float":
        return f"{val:,.1f}"
    return f"{val:,.0f}"


def generate_review_brief(
    cfg: WPRConfig,
    entries_desc: List[WeekEntry],
    eval_vals: Dict[Tuple[dt.date, str], Optional[float]],
    reviews_dir: Path,
) -> Tuple[str, str]:
    """Return (markdown_brief, html_brief) for the newest week."""
    dash = cfg.dash
    if not entries_desc:
        md = f"# Weekly Product Review {dash} {cfg.product_name}\n\nNo weekly data captured yet."
        return md, f"<html><body><h1>{html.escape(cfg.product_name)} Weekly Product Review</h1><p>No weekly data captured yet.</p></body></html>"

    newest = entries_desc[0]
    prior = entries_desc[1] if len(entries_desc) > 1 else None
    q = (newest.week_date.month - 1) // 3 + 1
    q_start = dt.date(newest.week_date.year, 3 * q - 2, 1)
    woq = (newest.week_date - q_start).days // 7 + 1
    woy = newest.week_date.isocalendar()[1]
    yy = str(newest.week_date.year)[-2:]
    active_tab_name = f"Q{q} {yy}"

    carry_rows: List[str] = []
    if reviews_dir.exists():
        rev_files = sorted(reviews_dir.glob("*-wpr.md"), reverse=True)
        for rf in rev_files:
            if rf.name.startswith(newest.week_date.isoformat()):
                continue
            for line in rf.read_text(encoding="utf-8-sig").splitlines():
                if line.strip().startswith("|") and ("Open" in line or "In Progress" in line):
                    cols = [c.strip() for c in line.strip()[1:-1].split("|")]
                    if len(cols) >= 3:
                        carry_rows.append(f"| {cols[0]} | {cols[1]} | {cols[2]} | Open | From {rf.stem[:10]} |")
            break

    md_lines = [
        f"# {cfg.product_name} {dash} Weekly Product Review ({newest.week_date.isoformat()}, Q{q} W{woq} / W{woy})",
        "",
        f"- **Cadence:** {cfg.meeting_cadence or 'Weekly (60 mins)'}",
        f"- **Attendees:** {cfg.owners or 'Product, Engineering, Growth & Metric Owners'}",
    ]
    if cfg.sheet_url:
        md_lines.append(f"- **Review Sheet:** {cfg.sheet_url}")
    if cfg.doc_url:
        md_lines.append(f"- **Review Doc:** {cfg.doc_url}")

    md_lines.extend([
        "",
        "## 1. Metric Highlights & Anomalies",
        "| Section | Metric | This Week | Prior Week | WoW % | 4-Wk Avg | Target | Signal |",
        "| :--- | :--- | ---: | ---: | ---: | ---: | ---: | :--- |",
    ])

    anomalies: List[str] = []
    restatements: List[str] = []
    for e in entries_desc[:6]:
        for cid, wcell in e.cells.items():
            if wcell.note and "[restated" in wcell.note.lower():
                restatements.append(f"- **{e.week_date.isoformat()} / {wcell.metric_name or cid}:** {wcell.note}")

    for m in cfg.metrics:
        cur = eval_vals.get((newest.week_date, m.metric_id))
        prv = eval_vals.get((prior.week_date, m.metric_id)) if prior else None
        wow_str = dash
        wow_pct = None
        if cur is not None and prv not in (None, 0.0):
            wow_pct = cur / prv - 1.0
            wow_str = f"{wow_pct * 100:+.1f}%"
        last4 = [eval_vals.get((e.week_date, m.metric_id)) for e in entries_desc[:4]]
        last4_nums = [x for x in last4 if x is not None]
        avg4 = sum(last4_nums) / len(last4_nums) if len(last4_nums) == 4 else None

        traw, tnum = m.target_for_tab(active_tab_name)
        if m.mtype == "not-collected":
            signal = m.source_eta or "Planned"
        elif m.mtype == "manual" and cur is None:
            signal = "Pending input"
        elif tnum is not None and cur is not None:
            signal = "Below target" if cur < tnum else "At/above target"
        else:
            signal = "On track"

        if wow_pct is not None and abs(wow_pct) >= 0.20:
            signal = f"Notable move ({wow_str})"
            anomalies.append(
                f"**{m.name}** moved **{wow_str}** WoW ({format_val(prv, m.fmt, dash)} -> {format_val(cur, m.fmt, dash)})."
            )

        target_disp = format_val(tnum, m.fmt, dash) if tnum is not None else (traw or dash)
        md_lines.append(
            f"| {m.section} | {m.name} | {format_val(cur, m.fmt, dash)} | {format_val(prv, m.fmt, dash)} | "
            f"{wow_str} | {format_val(avg4, 'float' if m.fmt == 'int' else m.fmt, dash)} | "
            f"{target_disp} | {signal} |"
        )

    if anomalies:
        md_lines.extend(["", "**Auto-Flagged Questions for the Room:**"])
        for a in anomalies:
            md_lines.append(f"- {a} *(Expected or unexpected? Signal or noise vs. 4-wk avg?)*")

    if restatements:
        md_lines.extend(["", "**Historical Restatements Logged:**"])
        md_lines.extend(restatements)

    md_lines.extend([
        "",
        "## 2. Carry-Over Actions Review",
        "| Action | Owner | Due | Status | Update |",
        "| :--- | :--- | :--- | :--- | :--- |",
    ])
    if carry_rows:
        md_lines.extend(carry_rows)
    else:
        md_lines.append("| *(No open carry-over actions logged)* | | | | |")

    md_lines.extend([
        "",
        "## 3. Customer, Sales & Support Anecdotes",
        "*(Log 1-3 specific user, support, or sales verbatims from this week that explain why numbers moved or expose a cohort gap.)*",
        "- **Customer / Support:** ",
        "- **Sales / User Feedback:** ",
        "",
        "## 4. Discussion & Root-Cause Notes",
        "- **Expected vs. Unexpected:** ",
        "- **Signal vs. Noise:** ",
        "- **Drivers & Controllability:** ",
        "- **Splits Needed (size / country / industry / feature):** ",
        "",
        "## 5. Decisions & Actions",
        "### Improve the Spreadsheet",
        "| Action | Owner | Due Date | Status |",
        "| :--- | :--- | :--- | :--- |",
        "| | | | Open |",
        "",
        "### Change the Product or Workflow",
        "| Action | Owner | Due Date | Status |",
        "| :--- | :--- | :--- | :--- |",
        "| | | | Open |",
    ])

    md_text = "\n".join(md_lines) + "\n"
    if cfg.no_em_dash:
        md_text = md_text.replace("—", "-")

    title = f"{cfg.product_name} Weekly Product Review - {newest.week_date.isoformat()}"
    return md_text, render_brief_html(title, md_text)


def render_brief_html(title: str, md_text: str) -> str:
    """Render a Weekly Product Review Markdown brief into Swiss Precision Grid HTML."""
    html_parts = [
        "<!DOCTYPE html><html lang='en'><head><meta charset='utf-8'>",
        f"<title>{html.escape(title)}</title>",
        "<link rel='preconnect' href='https://fonts.googleapis.com'><link rel='preconnect' href='https://fonts.gstatic.com' crossorigin>",
        "<link href='https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700&display=swap' rel='stylesheet'>",
        "<style>"
        "body{font-family:'Inter',system-ui,-apple-system,'Segoe UI',Arial,sans-serif;background:#F8FAFC;color:#09090B;max-width:960px;margin:2.5rem auto;padding:0 1.5rem;line-height:1.55}"
        "h1{font-size:1.85rem;font-weight:700;color:#09090B;letter-spacing:-0.02em;margin-bottom:.35rem}"
        "h2{font-size:1.2rem;font-weight:700;color:#09090B;border-bottom:1px solid #E2E8F0;padding-bottom:.35rem;margin-top:2rem}"
        "h3{font-size:1rem;font-weight:700;color:#1E3A8A;margin-top:1.25rem}"
        "table{border-collapse:collapse;width:100%;margin:1rem 0;background:#FFFFFF;border:1px solid #E2E8F0;font-variant-numeric:tabular-nums}"
        "th{background:#09090B;color:#FAFAFA;font-weight:600;padding:10px 12px;text-align:left;font-size:.875rem}"
        "td{border-top:1px solid #E2E8F0;padding:8px 12px;text-align:left;font-size:.9rem}"
        "tr:nth-child(even) td{background:#FAFAFA}"
        ".badge{display:inline-block;padding:2px 8px;border-radius:4px;font-size:.8rem;font-weight:600}"
        ".b-ok{background:#DBEAFE;color:#1E40AF}.b-warn{background:#FFEDD5;color:#9A3412}"
        ".b-move{background:#EFF6FF;color:#1D4ED8}.b-muted{background:#F4F4F5;color:#52525B}"
        "@media print{body{background:#FFF;margin:0;max-width:none}table{page-break-inside:avoid}}"
        "</style></head><body>",
    ]
    in_table = False
    in_list = False
    for line in md_text.splitlines():
        if line.startswith("|"):
            if re.fullmatch(r"[\|\s:\-]+", line):
                continue
            cells = [c.strip() for c in line.strip()[1:-1].split("|")]
            if not in_table:
                in_table = True
                html_parts.append("<table><thead><tr>" + "".join(f"<th>{html.escape(c)}</th>" for c in cells) + "</tr></thead><tbody>")
            else:
                tds = []
                for idx_c, c in enumerate(cells):
                    esc = html.escape(c)
                    if idx_c == len(cells) - 1 and c:
                        low_c = c.lower()
                        if "above target" in low_c:
                            esc = f"<span class='badge b-ok'>{esc}</span>"
                        elif "below target" in low_c or "eta:" in low_c:
                            esc = f"<span class='badge b-warn'>{esc}</span>"
                        elif "notable" in low_c:
                            esc = f"<span class='badge b-move'>{esc}</span>"
                        elif "pending" in low_c:
                            esc = f"<span class='badge b-muted'>{esc}</span>"
                    tds.append(f"<td>{esc}</td>")
                html_parts.append("<tr>" + "".join(tds) + "</tr>")
            continue
        if in_table:
            html_parts.append("</tbody></table>")
            in_table = False
        if line.startswith("- "):
            if not in_list:
                in_list = True
                html_parts.append("<ul>")
            txt = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", html.escape(line[2:]))
            html_parts.append(f"<li>{txt}</li>")
            continue
        if in_list:
            html_parts.append("</ul>")
            in_list = False
        if line.startswith("# "):
            html_parts.append(f"<h1>{html.escape(line[2:])}</h1>")
        elif line.startswith("## "):
            html_parts.append(f"<h2>{html.escape(line[3:])}</h2>")
        elif line.startswith("### "):
            html_parts.append(f"<h3>{html.escape(line[4:])}</h3>")
        elif line.strip():
            txt = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", html.escape(line))
            html_parts.append(f"<p>{txt}</p>")
    if in_table:
        html_parts.append("</tbody></table>")
    if in_list:
        html_parts.append("</ul>")
    html_parts.append("</body></html>")
    return "\n".join(html_parts)


def grid_to_payload(grid: List[List[dict]], week_dates_desc: List[dt.date]) -> dict:
    values: List[List[str]] = []
    fills: List[Tuple[str, str]] = []
    fill_hex = {
        FILL_ZINC_CALC: "#FAFAFA",
        FILL_ICE_MANUAL: "#EFF6FF",
        FILL_AMBER_PENDING: "#FFEDD5",
        FILL_SLATE_SECTION: "#F1F5F9",
        FILL_LEGEND_BG: "#F8FAFC",
        FILL_MIDNIGHT_HEADER: "#09090B",
    }
    for r_idx, row in enumerate(grid, start=1):
        row_vals: List[str] = []
        for c_idx, cell in enumerate(row, start=1):
            if cell["f"] is not None:
                row_vals.append("=" + cell["f"])
            elif cell["v"] is not None:
                if cell["fmt"] == 5 and isinstance(cell["v"], int):
                    row_vals.append((EXCEL_EPOCH + dt.timedelta(days=cell["v"])).isoformat())
                else:
                    row_vals.append(str(cell["v"]))
            else:
                row_vals.append("")
            if cell["fill"] in fill_hex:
                fills.append((f"{col_letter(c_idx)}{r_idx}", fill_hex[cell["fill"]]))
        values.append(row_vals)
    week_cols = {wd.isoformat(): col_letter(3 + idx) for idx, wd in enumerate(week_dates_desc)}
    return {"values": values, "cell_fills": fills, "week_columns": week_cols}


def cmd_build(args: argparse.Namespace) -> int:
    wpr_dir = Path(args.wpr_dir)
    out_dir = Path(args.out_dir)
    errors, warnings = validate_wpr(wpr_dir)
    for w in warnings:
        print(f"[WARN] {w}", file=sys.stderr)
    if errors:
        for e in errors:
            print(f"[ERROR] {e}", file=sys.stderr)
        return 1

    cfg = load_config(wpr_dir / "wpr-config.md")
    data_path = wpr_dir / "metrics-data.md"
    entries_desc = load_metrics_data(data_path) if data_path.exists() else []
    entries_by_date = {e.week_date: e for e in entries_desc}
    entries_asc = list(reversed(entries_desc))
    eval_vals = evaluate_metric_series(cfg, entries_asc)

    latest_note_by_date: Dict[dt.date, str] = {}
    for e in entries_desc:
        notes = [c.note for c in e.cells.values() if c.note and not c.note.startswith("ETA:")]
        if notes:
            latest_note_by_date[e.week_date] = "; ".join(notes[:2])

    years = sorted({e.week_date.year for e in entries_desc} | {cfg.year})
    year_q_dates = {y: dates_for_year(y, cfg.week_ending_day) for y in years}

    anchor_date = entries_desc[0].week_date if entries_desc else dt.date.today()
    anchor_q = (anchor_date.month - 1) // 3 + 1
    active_tab_name = f"Q{anchor_q} {str(anchor_date.year)[-2:]}"

    sheets_out: List[Tuple[str, List[List[dict]]]] = []
    payload_tabs: Dict[str, dict] = {}
    cumulative_q_tabs: List[Tuple[str, int]] = []
    cumulative_fy_tabs: List[Tuple[str, int]] = []

    prev_q_tab: Optional[str] = None
    prev_q_dates: Optional[List[dt.date]] = None

    for y_idx, y in enumerate(years):
        yy = str(y)[-2:]
        q_dates = year_q_dates[y]
        prev_y = years[y_idx - 1] if y_idx > 0 and years[y_idx - 1] == y - 1 else None

        for q in (1, 2, 3, 4):
            tname = f"Q{q} {yy}"
            py_tab = f"Q{q} {str(prev_y)[-2:]}" if prev_y else None
            py_dates = year_q_dates[prev_y][q] if prev_y else None
            grid, _ = build_sheet_grid(
                cfg=cfg,
                tab_name=tname,
                week_dates_desc=q_dates[q],
                entries_by_date=entries_by_date,
                prior_q_tab=prev_q_tab,
                prior_q_dates=prev_q_dates,
                prior_year_tab=py_tab,
                prior_year_dates=py_dates,
                prior_cumsum_tabs=list(cumulative_q_tabs),
                latest_note_by_date=latest_note_by_date,
            )
            sheets_out.append((tname, grid))
            payload_tabs[tname] = grid_to_payload(grid, q_dates[q])
            prev_q_tab = tname
            prev_q_dates = q_dates[q]
            cumulative_q_tabs.append((tname, 2 + len(q_dates[q])))

        all_dates_desc = sorted([d for q in (1, 2, 3, 4) for d in q_dates[q]], reverse=True)
        fy_name = f"Full Year {y}"
        py_fy_tab = f"Full Year {prev_y}" if prev_y else None
        py_fy_dates = (
            sorted([d for q in (1, 2, 3, 4) for d in year_q_dates[prev_y][q]], reverse=True)
            if prev_y
            else None
        )
        fy_grid, _ = build_sheet_grid(
            cfg=cfg,
            tab_name=fy_name,
            week_dates_desc=all_dates_desc,
            entries_by_date=entries_by_date,
            prior_q_tab=None,
            prior_q_dates=None,
            prior_year_tab=py_fy_tab,
            prior_year_dates=py_fy_dates,
            prior_cumsum_tabs=list(cumulative_fy_tabs),
            latest_note_by_date=latest_note_by_date,
        )
        sheets_out.append((fy_name, fy_grid))
        payload_tabs[fy_name] = grid_to_payload(fy_grid, all_dates_desc)
        cumulative_fy_tabs.append((fy_name, 2 + len(all_dates_desc)))

    active_idx = next((idx for idx, (nm, _) in enumerate(sheets_out) if nm == active_tab_name), 0)
    if args.active_tab_first and active_idx != 0:
        sheets_out.insert(0, sheets_out.pop(active_idx))
        active_idx = 0

    out_dir.mkdir(parents=True, exist_ok=True)
    xlsx_path = out_dir / "wpr-workbook.xlsx"
    write_xlsx(sheets_out, xlsx_path, active_tab_idx=active_idx)

    reviews_dir = wpr_dir / "reviews"
    md_brief, html_brief = generate_review_brief(cfg, entries_desc, eval_vals, reviews_dir)

    if entries_desc:
        reviews_dir.mkdir(parents=True, exist_ok=True)
        rev_path = reviews_dir / f"{entries_desc[0].week_date.isoformat()}-wpr.md"
        if not rev_path.exists() or args.overwrite_review:
            rev_path.write_text(md_brief, encoding="utf-8")
            print(f"Created review draft: {rev_path}")
        else:
            rev_text = rev_path.read_text(encoding="utf-8-sig")
            html_title = f"{cfg.product_name} Weekly Product Review - {entries_desc[0].week_date.isoformat()}"
            html_brief = render_brief_html(html_title, rev_text)

    (out_dir / "wpr-review-brief.md").write_text(md_brief, encoding="utf-8")
    (out_dir / "wpr-review-brief.html").write_text(html_brief, encoding="utf-8")

    archive_parts: List[str] = []
    if reviews_dir.exists():
        for rf in sorted(reviews_dir.glob("*-wpr.md"), reverse=True):
            archive_parts.append(rf.read_text(encoding="utf-8-sig").strip())
    if not archive_parts:
        archive_parts.append(md_brief.strip())
    archive_md = "\n\n---\n\n".join(archive_parts) + "\n"
    if cfg.no_em_dash:
        archive_md = archive_md.replace("—", "-")
    archive_path = out_dir / "wpr-review-archive.md"
    archive_path.write_text(archive_md, encoding="utf-8")

    row_sig = compute_row_signature(cfg)
    payload_path = out_dir / "sheets-payload.json"
    payload_obj = {
        "product": cfg.product_name,
        "years": years,
        "active_tab": active_tab_name,
        "row_signature": row_sig,
        "tabs": payload_tabs,
    }
    payload_path.write_text(json.dumps(payload_obj, indent=2), encoding="utf-8")

    print(f"Built workbook:     {xlsx_path} (active tab: {active_tab_name})")
    print(f"Built review brief: {out_dir / 'wpr-review-brief.md'}")
    print(f"Built review arch:  {archive_path}")
    print(f"Built sheets JSON:  {payload_path} (row_signature: {row_sig})")
    return 0


def cmd_validate(args: argparse.Namespace) -> int:
    errors, warnings = validate_wpr(Path(args.wpr_dir))
    for w in warnings:
        print(f"[WARN] {w}")
    for e in errors:
        print(f"[ERROR] {e}", file=sys.stderr)
    if not errors:
        print("Validation passed.")
        return 0
    return 1


def cmd_add_week(args: argparse.Namespace) -> int:
    wpr_dir = Path(args.wpr_dir)
    cfg = load_config(wpr_dir / "wpr-config.md")
    data_path = wpr_dir / "metrics-data.md"
    entries = load_metrics_data(data_path) if data_path.exists() else []

    if args.date:
        new_date = dt.date.fromisoformat(args.date)
    elif entries:
        new_date = entries[0].week_date + dt.timedelta(days=7)
    else:
        target_wd = WEEKDAY_MAP.get(cfg.week_ending_day.lower(), 4)
        d = dt.date.today()
        while d.weekday() != target_wd:
            d -= dt.timedelta(days=1)
        new_date = d

    if any(e.week_date == new_date for e in entries) and not args.force:
        print(f"Week {new_date.isoformat()} already exists in {data_path}. Use --force to overwrite.", file=sys.stderr)
        return 1

    entries = [e for e in entries if e.week_date != new_date]
    new_entry = WeekEntry(week_date=new_date)
    for m in cfg.metrics:
        new_entry.cells[m.metric_id] = WeekCell(
            metric_id=m.metric_id,
            metric_name=m.name,
            value_raw="",
            value_num=None,
            status=m.mtype,
            note=m.source_eta if m.mtype == "not-collected" else "",
        )
    entries.append(new_entry)
    save_metrics_data(data_path, cfg, entries)
    print(f"Added week {new_date.isoformat()} to {data_path}")
    return 0


def _reconcile_rows_into_entries(
    cfg: WPRConfig,
    rows: List[List[str]],
    by_date: Dict[dt.date, WeekEntry],
) -> int:
    date_row = None
    for row in rows[:6]:
        if row and row[0].strip().lower() in WEEKDAY_MAP:
            date_row = row
            break
    if not date_row:
        return 0

    col_dates: Dict[int, dt.date] = {}
    for c_idx in range(2, len(date_row)):
        raw_d = date_row[c_idx].strip()
        if not raw_d:
            continue
        parsed_d = None
        if re.fullmatch(r"\d+(\.\d+)?", raw_d):
            try:
                parsed_d = EXCEL_EPOCH + dt.timedelta(days=int(float(raw_d)))
            except Exception:
                parsed_d = None
        else:
            try:
                parsed_d = dt.date.fromisoformat(raw_d[:10])
            except ValueError:
                parsed_d = None
        if parsed_d:
            col_dates[c_idx] = parsed_d

    name_to_metric = {m.name.lower(): m for m in cfg.metrics}
    updated = 0
    for row in rows[6:]:
        if not row:
            continue
        mname = row[0].strip().lower()
        mdef = name_to_metric.get(mname)
        if not mdef or mdef.mtype != "manual":
            continue
        for c_idx, wd in col_dates.items():
            if c_idx >= len(row):
                continue
            val_raw = row[c_idx].strip()
            if not val_raw:
                continue
            if mdef.fmt == "int" and re.fullmatch(r"-?\d+\.0+", val_raw):
                val_raw = val_raw.split(".")[0]
            entry = by_date.setdefault(wd, WeekEntry(week_date=wd))
            existing = entry.cells.get(mdef.metric_id)
            if not existing or existing.value_raw != val_raw:
                entry.cells[mdef.metric_id] = WeekCell(
                    metric_id=mdef.metric_id,
                    metric_name=mdef.name,
                    value_raw=val_raw,
                    value_num=parse_number(val_raw),
                    status="manual",
                    note=existing.note if existing else "",
                )
                updated += 1
    return updated


def cmd_import_csv(args: argparse.Namespace) -> int:
    wpr_dir = Path(args.wpr_dir)
    cfg = load_config(wpr_dir / "wpr-config.md")
    data_path = wpr_dir / "metrics-data.md"
    entries = load_metrics_data(data_path) if data_path.exists() else []
    by_date = {e.week_date: e for e in entries}

    with open(args.csv, "r", encoding="utf-8-sig", newline="") as fh:
        rows = list(csv.reader(fh))

    if not any(row and row[0].strip().lower() in WEEKDAY_MAP for row in rows[:6]):
        print("Could not find week-ending date row (e.g. 'Friday') in CSV.", file=sys.stderr)
        return 1

    updated = _reconcile_rows_into_entries(cfg, rows, by_date)
    save_metrics_data(data_path, cfg, list(by_date.values()))
    print(f"Imported/updated {updated} manual metric cells from {args.csv}")
    return 0


def _col_ref_to_idx(ref: str) -> Tuple[int, int]:
    m = re.match(r"^([A-Z]+)(\d+)$", ref)
    if not m:
        return 1, 1
    col_str, row_str = m.groups()
    c_idx = 0
    for ch in col_str:
        c_idx = c_idx * 26 + (ord(ch) - 64)
    return int(row_str), c_idx


def cmd_import_xlsx(args: argparse.Namespace) -> int:
    """Import manual metric values across all quarter tabs of an .xlsx export (stdlib only)."""
    wpr_dir = Path(args.wpr_dir)
    cfg = load_config(wpr_dir / "wpr-config.md")
    data_path = wpr_dir / "metrics-data.md"
    entries = load_metrics_data(data_path) if data_path.exists() else []
    by_date = {e.week_date: e for e in entries}

    updated = 0
    with zipfile.ZipFile(args.xlsx) as z:
        strings: List[str] = []
        if "xl/sharedStrings.xml" in z.namelist():
            sroot = ET.fromstring(z.read("xl/sharedStrings.xml"))
            for si in sroot.findall("m:si", XLSX_NS):
                strings.append("".join(t.text or "" for t in si.iter("{http://schemas.openxmlformats.org/spreadsheetml/2006/main}t")))

        wb_root = ET.fromstring(z.read("xl/workbook.xml"))
        rels_root = ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))
        rel_map = {rel.attrib["Id"]: rel.attrib["Target"] for rel in rels_root}

        for sheet in wb_root.findall(".//m:sheet", XLSX_NS):
            sname = sheet.attrib["name"]
            if sname.lower().startswith("full year"):
                continue
            rid = sheet.attrib["{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"]
            target = "xl/" + rel_map[rid].lstrip("/")
            if target.startswith("xl/xl/"):
                target = target[3:]
            ws_root = ET.fromstring(z.read(target))
            rows_dict: Dict[int, Dict[int, str]] = {}
            max_r = 0
            max_c = 0
            for c_el in ws_root.findall(".//m:sheetData/m:row/m:c", XLSX_NS):
                r_num, c_num = _col_ref_to_idx(c_el.attrib["r"])
                t_attr = c_el.attrib.get("t")
                v_el = c_el.find("m:v", XLSX_NS)
                is_el = c_el.find("m:is", XLSX_NS)
                val = ""
                if v_el is not None and v_el.text is not None:
                    val = strings[int(v_el.text)] if t_attr == "s" else v_el.text
                elif is_el is not None:
                    val = "".join(el.text or "" for el in is_el.iter("{http://schemas.openxmlformats.org/spreadsheetml/2006/main}t"))
                rows_dict.setdefault(r_num, {})[c_num] = val
                max_r = max(max_r, r_num)
                max_c = max(max_c, c_num)

            rows_grid: List[List[str]] = []
            for r in range(1, max_r + 1):
                row_map = rows_dict.get(r, {})
                rows_grid.append([row_map.get(c, "") for c in range(1, max_c + 1)])

            updated += _reconcile_rows_into_entries(cfg, rows_grid, by_date)

    save_metrics_data(data_path, cfg, list(by_date.values()))
    print(f"Imported/updated {updated} manual metric cells from {args.xlsx}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Weekly Product Review Markdown Sync Tool")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_val = sub.add_parser("validate", help="Validate wpr-config.md and metrics-data.md")
    p_val.add_argument("--wpr-dir", default="wpr")

    p_add = sub.add_parser("add-week", help="Prepend a new week entry to metrics-data.md")
    p_add.add_argument("--wpr-dir", default="wpr")
    p_add.add_argument("--date", default=None, help="Week ending date YYYY-MM-DD")
    p_add.add_argument("--force", action="store_true")

    p_imp = sub.add_parser("import-csv", help="Import manual metric values from a single-tab CSV export")
    p_imp.add_argument("--wpr-dir", default="wpr")
    p_imp.add_argument("--csv", required=True)

    p_ix = sub.add_parser("import-xlsx", help="Import manual metric values across all quarter tabs of an .xlsx export")
    p_ix.add_argument("--wpr-dir", default="wpr")
    p_ix.add_argument("--xlsx", required=True)

    p_bld = sub.add_parser("build", help="Build multi-year .xlsx workbook, review brief/archive, and sheets-payload.json")
    p_bld.add_argument("--wpr-dir", default="wpr")
    p_bld.add_argument("--out-dir", default="wpr-output")
    p_bld.add_argument("--overwrite-review", action="store_true")
    p_bld.add_argument("--active-tab-first", action="store_true", help="Move the active quarter tab to position 0")

    args = parser.parse_args()
    if args.cmd == "validate":
        return cmd_validate(args)
    if args.cmd == "add-week":
        return cmd_add_week(args)
    if args.cmd == "import-csv":
        return cmd_import_csv(args)
    if args.cmd == "import-xlsx":
        return cmd_import_xlsx(args)
    if args.cmd == "build":
        return cmd_build(args)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
