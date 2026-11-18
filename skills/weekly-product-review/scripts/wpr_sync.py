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
import ast
import csv
import datetime as dt
import difflib
import hashlib
import html
import json
import math
import os
import re
import sys
import tempfile
import zipfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from decimal import Decimal, ROUND_HALF_UP, localcontext
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from xml.sax.saxutils import escape as xml_escape
from urllib.parse import quote, unquote, urlsplit, urlunsplit


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
    period_state: str = "closed"
    comparison_group: str = ""


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
        return (val / 100.0 if is_pct else val) if math.isfinite(val) else None
    except ValueError:
        return None


def _markdown_cell_spans(line: str) -> List[Tuple[int, int]]:
    """Locate pipe-delimited cells, retaining escaped pipes inside a cell."""
    delimiters = []
    for idx, char in enumerate(line):
        if char != "|":
            continue
        previous = idx - 1
        while previous >= 0 and line[previous] == "\\":
            previous -= 1
        if (idx - previous - 1) % 2 == 0:
            delimiters.append(idx)
    return [(left + 1, right) for left, right in zip(delimiters, delimiters[1:])]


def _markdown_cells(line: str) -> List[str]:
    return [line[start:end].strip() for start, end in _markdown_cell_spans(line)]


def _metric_table_start(lines: List[str]) -> Optional[int]:
    required = {"ID", "Metric", "Value", "Status", "Note"}
    return next((idx for idx, line in enumerate(lines) if required.issubset(_markdown_cells(line))), None)


def parse_markdown_table(lines: List[str]) -> List[Dict[str, str]]:
    """Parse the first Markdown pipe table found in `lines` into a list of row dicts."""
    rows: List[List[str]] = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("|") and stripped.endswith("|"):
            parts = _markdown_cells(stripped)
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
            section_lines = lines[i + 1 : j]
            table_start = _metric_table_start(section_lines)
            table_rows = parse_markdown_table(section_lines[table_start:]) if table_start is not None else []
            entry = WeekEntry(week_date=wdate)
            for section_line in section_lines:
                state = re.match(r"^- Period State:\s*(\S+)", section_line, re.I)
                group = re.match(r"^- Comparison Group:\s*(.*)", section_line, re.I)
                if state:
                    entry.period_state = state[1].lower()
                if group:
                    entry.comparison_group = group[1].strip()
            for row in table_rows:
                mid = row.get("ID", "").strip()
                if not mid:
                    continue
                if mid in entry.cells:
                    raise ValueError(f"Duplicate metric row '{mid}' in week {wdate}")
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


def _metric_cell_fields(cell: WeekCell) -> Dict[str, str]:
    return {"ID": cell.metric_id, "Metric": cell.metric_name, "Value": cell.value_raw,
            "Status": cell.status, "Note": cell.note}


def _metric_table(entry: WeekEntry, cfg: WPRConfig, newline: str) -> str:
    lines = ["| ID | Metric | Value | Status | Note |",
             "| :--- | :--- | :--- | :--- | :--- |"]
    cells = dict(entry.cells)
    for mdef in cfg.metrics:
        cell = cells.pop(mdef.metric_id, None)
        if cell is None:
            cell = WeekCell(mdef.metric_id, mdef.name, "", None, mdef.mtype,
                            mdef.source_eta if mdef.mtype == "not-collected" else "")
        lines.append("| " + " | ".join(_metric_cell_fields(cell).values()) + " |")
    for cell in cells.values():
        lines.append("| " + " | ".join(_metric_cell_fields(cell).values()) + " |")
    return newline.join(lines) + newline + newline


def _render_week(entry: WeekEntry, cfg: WPRConfig, newline: str) -> str:
    q = (entry.week_date.month - 1) // 3 + 1
    q_start = dt.date(entry.week_date.year, 3 * q - 2, 1)
    woq = (entry.week_date - q_start).days // 7 + 1
    yy = str(entry.week_date.year)[-2:]
    heading = (f"## Week {entry.week_date.isoformat()}{newline}"
               f"- Quarter: Q{q} {yy} | Week of Quarter: {woq} | "
               f"Week of Year: {entry.week_date.isocalendar()[1]}{newline}{newline}")
    if entry.period_state != "closed" or entry.comparison_group:
        heading = heading.rstrip("\r\n") + newline + f"- Period State: {entry.period_state}" + newline
        if entry.comparison_group:
            heading += f"- Comparison Group: {entry.comparison_group}" + newline
        heading += newline
    return heading + _metric_table(entry, cfg, newline)


def _update_week_table(section: str, entry: WeekEntry, cfg: WPRConfig, newline: str) -> str:
    """Patch the existing metric cells without regenerating surrounding Markdown."""
    lines = section.splitlines(keepends=True)
    for name, value, default in (("Period State", entry.period_state, "closed"), ("Comparison Group", entry.comparison_group, "")):
        metadata_idx = next((i for i, line in enumerate(lines) if re.match(r"^- " + name + r":", line, re.I)), None)
        current = lines[metadata_idx].split(":", 1)[1].strip() if metadata_idx is not None else default
        if current != value:
            if metadata_idx is None:
                lines.insert(1, f"- {name}: {value}{newline}")
            else:
                lines[metadata_idx] = f"- {name}: {value}{newline}"
    table_start = _metric_table_start(lines)
    if table_start is None:
        if not entry.cells:
            return section
        return section + (newline if section.endswith(newline) else newline * 2) + _metric_table(entry, cfg, newline)

    headers = _markdown_cells(lines[table_start])
    seen = set()
    table_end = table_start + 1
    for idx in range(table_start + 1, len(lines)):
        line = lines[idx]
        if not line.strip().startswith("|") or not line.strip().endswith("|"):
            break
        table_end = idx + 1
        fields = _markdown_cells(line)
        if not fields or all(re.fullmatch(r":?-+:?", c.replace(" ", "")) for c in fields):
            continue
        mid_idx = headers.index("ID")
        if mid_idx >= len(fields):
            raise ValueError(f"Incomplete metric row in week {entry.week_date}")
        mid = fields[mid_idx]
        if mid in seen:
            raise ValueError(f"Duplicate metric row '{mid}' in week {entry.week_date}; source left unchanged")
        seen.add(mid)
        cell = entry.cells.get(mid)
        if cell is None:
            continue
        spans = _markdown_cell_spans(line)
        desired = _metric_cell_fields(cell)
        for col in range(len(headers) - 1, -1, -1):
            if headers[col] not in desired:
                continue
            if col >= len(spans):
                raise ValueError(f"Incomplete metric row '{mid}' in week {entry.week_date}")
            start, end = spans[col]
            raw = line[start:end]
            value = desired[headers[col]]
            current = raw.strip().lower() if headers[col] == "Status" else raw.strip()
            if current != value:
                padding = re.fullmatch(r"(\s*)(.*?)(\s*)", raw)
                line = line[:start] + padding[1] + value + padding[3] + line[end:]
        lines[idx] = line

    additions = []
    for mid, cell in entry.cells.items():
        if mid not in seen:
            fields = _metric_cell_fields(cell)
            additions.append("| " + " | ".join(fields.get(h, "") for h in headers) + " |" + newline)
    if additions and table_end and not lines[table_end - 1].endswith(("\n", "\r")):
        lines[table_end - 1] += newline
    lines[table_end:table_end] = additions
    return "".join(lines)


def save_metrics_data(path: Path, cfg: WPRConfig, entries: List[WeekEntry], dry_run: bool = False) -> bool:
    """Preserve unrelated text; replace a changed file atomically, or print a dry-run diff."""
    original = path.read_bytes() if path.exists() else b""
    bom = b"\xef\xbb\xbf" if original.startswith(b"\xef\xbb\xbf") else b""
    text = original.decode("utf-8-sig")
    newline_match = re.search(r"\r\n|\n|\r", text)
    newline = newline_match[0] if newline_match else "\n"
    matches = list(re.finditer(r"^[ \t]*##[ \t]+Week[ \t]+(\d{4}-\d{2}-\d{2})\b[^\r\n]*", text, re.M))
    sections = []
    by_date = {entry.week_date: entry for entry in entries}
    if len(by_date) != len(entries):
        raise ValueError("Duplicate week dates; source left unchanged")
    seen = set()
    for idx, match in enumerate(matches):
        date = dt.date.fromisoformat(match[1])
        if date in seen:
            raise ValueError(f"Duplicate week {date}; source left unchanged")
        seen.add(date)
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(text)
        section = text[match.start():end]
        if date in by_date:
            section = _update_week_table(section, by_date[date], cfg, newline)
        sections.append((date, section))
    for entry in sorted(entries, key=lambda e: e.week_date, reverse=True):
        if entry.week_date in seen:
            continue
        insertion = next((i for i, (date, _) in enumerate(sections) if date < entry.week_date), len(sections))
        sections.insert(insertion, (entry.week_date, _render_week(entry, cfg, newline)))

    prefix = text[:matches[0].start()] if matches else text
    if not original:
        prefix = "# Weekly Metrics Data" + newline * 2
    new_dates = set(by_date) - seen
    rendered = prefix
    for date, section in sections:
        if date in new_dates and rendered and not rendered.endswith(("\n\n", "\r\n\r\n", "\r\r")):
            rendered += newline if rendered.endswith(("\n", "\r")) else newline * 2
        rendered += section
    updated = bom + rendered.encode("utf-8")
    if updated == original:
        return False
    if dry_run:
        diff = difflib.unified_diff(text.splitlines(keepends=True), rendered.splitlines(keepends=True),
                                    fromfile=path.name, tofile=path.name + " (proposed)")
        sys.stdout.write("".join(diff))
        return True

    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="wb", dir=path.parent, prefix="." + path.name + ".",
                                         suffix=".tmp", delete=False) as handle:
            temporary = Path(handle.name)
            handle.write(updated)
            handle.flush()
            os.fsync(handle.fileno())
        if path.exists():
            os.chmod(temporary, path.stat().st_mode & 0o777)
        os.replace(temporary, path)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()
    return True


def validate_wpr(wpr_dir: Path) -> Tuple[List[str], List[str]]:
    errors: List[str] = []
    warnings: List[str] = []

    cfg = load_config(wpr_dir / "wpr-config.md")
    if cfg.week_ending_day.lower() not in WEEKDAY_MAP:
        errors.append(f"Invalid Week Ending Day: {cfg.week_ending_day}")
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
        seen_dates = set()
        catalog = {m.metric_id: m for m in cfg.metrics}
        for entry in entries:
            if entry.week_date in seen_dates:
                errors.append(f"Duplicate week {entry.week_date}")
            seen_dates.add(entry.week_date)
            if entry.week_date.weekday() != WEEKDAY_MAP.get(cfg.week_ending_day.lower(), 4):
                errors.append(f"Week {entry.week_date} does not end on {cfg.week_ending_day}")
            if entry.period_state not in {"closed", "preview"}:
                errors.append(f"Invalid Period State '{entry.period_state}' for {entry.week_date}")
            for mid, cell in entry.cells.items():
                if mid not in catalog:
                    warnings.append(f"Uncatalogued metric '{mid}' retained for {entry.week_date}")
                    continue
                issue = input_error(catalog[mid], cell.value_raw)
                if issue:
                    errors.append(f"{entry.week_date} / {mid}: {issue}")
                if cell.status not in VALID_TYPES | {"preview", "stale", "unavailable", "verified-zero", ""}:
                    errors.append(f"Invalid cell status '{cell.status}' for {entry.week_date} / {mid}")
                if cell.status == "verified-zero" and cell.value_num != 0:
                    errors.append(f"verified-zero requires numeric zero for {entry.week_date} / {mid}")
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


def input_error(metric: MetricDef, raw: str) -> str:
    if not raw.strip():
        return ""
    cleaned = raw.strip()
    if metric.fmt == "currency":
        cleaned = re.sub(r"[$€£]", "", cleaned).strip()
    if metric.fmt == "percent" and cleaned.endswith("%"):
        cleaned = cleaned[:-1].strip()
    numeric = re.fullmatch(r"[+-]?(?:\d{1,3}(?:,\d{3})+|\d+|\.\d+)(?:\.\d*)?(?:[eE][+-]?\d+)?", cleaned)
    value = parse_number(raw)
    if not numeric or value is None:
        return f"Invalid {metric.fmt} value: {raw!r}"
    if metric.fmt == "int" and not value.is_integer():
        return f"Integer metric cannot contain a fraction: {raw!r}"
    return ""


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
    row_ids = {}
    row = 8
    section = None
    for metric in cfg.metrics:
        if metric.section != section:
            row += 1
            section = metric.section
        row_ids[row] = metric.metric_id
        row += 2 + len(metric.analyses)
    catalog = {metric.metric_id: metric for metric in cfg.metrics}
    for entry in entries_asc:
        d = entry.week_date
        resolving = set()
        def resolve(mid):
            if (d, mid) in vals:
                return vals[d, mid]
            if mid in resolving or mid not in catalog:
                return None
            resolving.add(mid)
            m = catalog[mid]
            cell = entry.cells.get(m.metric_id)
            if entry.period_state != "closed" or (cell and cell.status in {"preview", "stale", "unavailable", "not-collected"}):
                value = None
            elif cell and cell.value_num is not None:
                value = cell.value_num
            elif m.mtype == "calculated" and m.formula:
                if m.formula.startswith("cumsum:"):
                    src_id = m.formula.split(":", 1)[1].strip()
                    source = resolve(src_id)
                    value = running_sums.get(src_id, 0) + source if source is not None else None
                elif m.formula.startswith("ratio:"):
                    num_id, den_id = [x.strip() for x in m.formula.split(":", 1)[1].split("/")]
                    num, den = resolve(num_id), resolve(den_id)
                    value = num / den if num is not None and den not in (None, 0) else None
                elif m.formula.startswith("diff:"):
                    a_id, b_id = [x.strip() for x in m.formula.split(":", 1)[1].split("-")]
                    a, b = resolve(a_id), resolve(b_id)
                    value = a - b if a is not None and b is not None else None
                else:
                    value = safe_arithmetic(m.formula, lambda row: resolve(row_ids.get(row, "")))
            else:
                value = None
            resolving.remove(mid)
            vals[d, mid] = value
            return value
        for metric in cfg.metrics:
            resolve(metric.metric_id)
        for metric in cfg.metrics:
            value = vals.get((d, metric.metric_id))
            if value is not None:
                running_sums[metric.metric_id] = running_sums.get(metric.metric_id, 0) + value
    return vals


def safe_arithmetic(formula, row_value):
    """Evaluate only numeric constants, metric-cell references and basic arithmetic; never eval code."""
    expression = re.sub(r"\{col\}(\d+)", r"_r\1", formula.lstrip("="))
    def calculate(node):
        if isinstance(node, ast.Constant) and type(node.value) in (int, float):
            return node.value
        if isinstance(node, ast.Name) and re.fullmatch(r"_r\d+", node.id):
            value = row_value(int(node.id[2:]))
            if value is None:
                raise ValueError("Missing referenced value")
            return value
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd)):
            value = calculate(node.operand)
            return -value if isinstance(node.op, ast.USub) else value
        if isinstance(node, ast.BinOp):
            a, b = calculate(node.left), calculate(node.right)
            if isinstance(node.op, ast.Add): return a + b
            if isinstance(node.op, ast.Sub): return a - b
            if isinstance(node.op, ast.Mult): return a * b
            if isinstance(node.op, ast.Div): return a / b
        raise ValueError("Unsupported formula syntax")
    try:
        value = calculate(ast.parse(expression, mode="eval").body)
        return value if math.isfinite(value) else None
    except (ValueError, SyntaxError, ZeroDivisionError, OverflowError, RecursionError):
        return None


def period_statistics(entries: Dict[dt.date, WeekEntry], values: dict, date: dt.date, metric_id: str):
    """Compare exact adjacent periods; never substitute an older observation for a missing week."""
    current = entries.get(date)
    dates = [date - dt.timedelta(days=7 * offset) for offset in range(4)]
    def comparable(other):
        return (current is not None and other is not None and current.period_state == other.period_state == "closed"
                and current.comparison_group == other.comparison_group)
    prior = values.get((dates[1], metric_id)) if comparable(entries.get(dates[1])) else None
    cur = values.get((date, metric_id))
    wow = cur / prior - 1 if cur is not None and prior not in (None, 0) else None
    window = [values.get((d, metric_id)) if comparable(entries.get(d)) else None for d in dates]
    average = sum(window) / 4 if all(value is not None for value in window) else None
    return prior, wow, average


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


def compute_catalog_signature(cfg: WPRConfig) -> str:
    fields = [(m.metric_id, m.name, m.mtype, m.fmt, m.target_raw) for m in cfg.metrics]
    return hashlib.sha256(json.dumps(fields).encode("utf-8")).hexdigest()[:16]


def plan_sync(payload: dict, previous: Optional[dict], date: str) -> dict:
    """Plan bounded, date-keyed writes; never execute network operations or replace a workbook."""
    dt.date.fromisoformat(date)
    if previous and previous.get("row_signature") != payload["row_signature"]:
        raise ValueError("Metric row layout changed: reconcile live rows and chart references before column sync")
    catalog_changed = not previous or previous.get("catalog_signature") != payload.get("catalog_signature")
    if not any(date in tab["week_columns"] for tab in payload["tabs"].values()):
        raise ValueError(f"No workbook column for {date}")
    plans = []
    for title, tab in payload["tabs"].items():
        if not re.fullmatch(r"Q[1-4] \d{2}|Full Year \d{4}", title):
            continue
        column = tab["week_columns"].get(date)
        if not column and not catalog_changed:
            continue
        values = tab["values"]
        writes = []
        if column:
            idx = _col_ref_to_idx(column + "1")[1] - 1
            writes.append({"range": f"{column}1:{column}{len(values)}", "values": [[row[idx]] for row in values]})
        if catalog_changed:
            writes.append({"range": f"A1:B{len(values)}", "values": [row[:2] for row in values]})
        plans.append({"tab": title, "date": date, "expected_column": column, "writes": writes})
    if not plans:
        raise ValueError(f"No workbook column for {date}")
    return {"date": date, "catalog_changed": catalog_changed, "row_signature": payload["row_signature"],
            "catalog_signature": payload.get("catalog_signature"), "tabs": plans,
            "precondition": "Read live metadata, row 4 dates, labels, targets and current target cells; remap columns by date if needed",
            "network_writes": False}


def cmd_plan_sync(args):
    payload = json.loads(Path(args.payload).read_text(encoding="utf-8"))
    previous = json.loads(Path(args.previous).read_text(encoding="utf-8")) if args.previous else None
    plan = plan_sync(payload, previous, args.date)
    Path(args.out).write_text(json.dumps(plan, indent=2), encoding="utf-8")
    print(f"Wrote bounded sync plan: {args.out}")
    return 0


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
    def period_refs(date, count, row, metric_id):
        refs = []
        current = entries_by_date.get(date)
        for offset in range(count):
            target = date - dt.timedelta(days=offset * 7)
            entry = entries_by_date.get(target)
            cell = entry.cells.get(metric_id) if entry else None
            if entry and (entry.period_state != "closed" or (cell and cell.status in {"preview", "stale", "unavailable", "not-collected"})):
                return []
            if current and entry and current.comparison_group != entry.comparison_group:
                return []
            if target in week_dates_desc:
                refs.append(f"{col_letter(3 + week_dates_desc.index(target))}{row}")
            elif prior_q_tab and prior_q_dates and target in prior_q_dates:
                refs.append(f"'{prior_q_tab}'!{col_letter(3 + prior_q_dates.index(target))}{row}")
            elif prior_year_tab and prior_year_dates and target in prior_year_dates:
                refs.append(f"'{prior_year_tab}'!{col_letter(3 + prior_year_dates.index(target))}{row}")
            else:
                return []
        return refs

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
            r4[2 + i] = {"v": excel_serial(wd), "f": f"{next_cl}4+7", "fill": FILL_SLATE_SECTION, "fmt": 5, "bold": False, "font": 3, "border": 1, "align": "right"}

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
    r6[0]["v"] = "Blue: manual | Grey: calculated / automated\nAmber: pending / N/A"
    r6[0]["align"] = "left_wrap"

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
            excluded = entry and (entry.period_state != "closed" or (wcell and wcell.status in {"preview", "stale", "unavailable"}))

            if excluded:
                mrow[2 + i] = {"v": None, "f": None, "fill": FILL_AMBER_PENDING, "fmt": m_fmt, "bold": False, "font": 5, "border": 1, "align": "right"}
            elif m.mtype == "not-collected":
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
                future = wd > today_d and val is None
                mrow[2 + i] = {"v": val, "f": None, "fill": FILL_LEGEND_BG if future else m_fill, "fmt": m_fmt, "bold": False, "font": 3 if future else m_font, "border": 1, "align": "right"}
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
                if wd > today_d:
                    arow[2 + i] = {"v": None, "f": None, "fill": FILL_LEGEND_BG, "fmt": 0, "bold": False, "font": 3, "border": 1, "align": "right"}
                    continue

                if analysis == "wow":
                    refs = period_refs(wd, 2, mrow_num, m.metric_id)
                    if not refs:
                        arow[2 + i] = {"v": "N/A", "f": None, "fill": FILL_AMBER_PENDING, "fmt": 0, "bold": False, "font": 5, "border": 1, "align": "right"}
                    else:
                        arow[2 + i] = {"v": None, "f": f'IF(COUNT({",".join(refs)})<>2,"N/A",IFERROR({refs[0]}/{refs[1]}-1,"N/A"))', "fill": FILL_ZINC_CALC, "fmt": 4, "bold": False, "font": 3, "border": 1, "align": "right"}
                elif analysis == "rolling_4w":
                    refs = period_refs(wd, 4, mrow_num, m.metric_id)
                    if not refs:
                        arow[2 + i] = {"v": "N/A", "f": None, "fill": FILL_AMBER_PENDING, "fmt": 0, "bold": False, "font": 5, "border": 1, "align": "right"}
                    else:
                        args = ",".join(refs)
                        arow[2 + i] = {"v": None, "f": f'IF(COUNT({args})<>4,"N/A",AVERAGE({args}))', "fill": FILL_ZINC_CALC, "fmt": 2 if m_fmt == 1 else m_fmt, "bold": False, "font": 3, "border": 1, "align": "right"}
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

    # A hidden identity column keeps imports independent of editable display labels.
    identity_rows = {row: mid for mid, row in metric_row_map.items()}
    for row_idx, row in enumerate(grid, start=1):
        row.append({"v": "Metric ID" if row_idx == 5 else identity_rows.get(row_idx), "f": None,
                    "fill": 0, "fmt": 0, "bold": False, "font": 0, "border": 0, "align": None})

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
            has_ids = len(grid) >= 5 and grid[4][-1].get("v") == "Metric ID"
            cols_xml.append(f'<col min="3" max="{ncols - 1 if has_ids else ncols}" width="15" customWidth="1"/>')
            if has_ids:
                cols_xml.append(f'<col min="{ncols}" max="{ncols}" width="15" hidden="1" customWidth="1"/>')

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
                    cached = f"<v>{v}</v>" if isinstance(v, (int, float)) else ""
                    c_xml.append(f'<c r="{ref}" s="{xf}"><f>{xml_escape(f)}</f>{cached}</c>')
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
                    ht = 36
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
            + ('<mergeCells count="1"><mergeCell ref="A6:B6"/></mergeCells>' if len(grid) > 5 and str(grid[5][0].get("v", "")).startswith("Blue:") else '') +
            f'{cf_xml}'
            '</worksheet>'
        )
        sheet_xmls.append(ws)

    xfs_parts = []
    for fill_id, font_id, nfmt, border_id, align_key in xf_list:
        wrap = ' wrapText="1"' if align_key.endswith("_wrap") else ''
        horizontal = align_key.replace("_wrap", "")
        align_xml = f'<alignment horizontal="{horizontal}" vertical="center"{wrap}/>' if horizontal else '<alignment vertical="center"/>'
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
    with localcontext() as context:
        context.prec = 350
        number = Decimal(str(val)) * (100 if fmt == "percent" else 1)
        places = 1 if fmt in {"percent", "float"} else 0
        rounded = number.quantize(Decimal("0.1") if places else Decimal("1"), rounding=ROUND_HALF_UP)
        if fmt == "percent": return f"{rounded:.1f}%"
        if fmt == "currency": return f"${rounded:,.0f}"
        return f"{rounded:,.{places}f}"


def decision_rows(text: str) -> List[Dict[str, str]]:
    lines = text.splitlines()
    start = next((i for i, line in enumerate(lines) if re.match(r"^##\s+(?:5\.\s*)?Decisions(?:\s|$)", line, re.I)), None)
    if start is None:
        return []
    end = next((i for i in range(start + 1, len(lines)) if lines[i].startswith("## ")), len(lines))
    rows = []
    for idx in range(start + 1, end):
        if "Action" in _markdown_cells(lines[idx]) and "Status" in _markdown_cells(lines[idx]):
            rows.extend(parse_markdown_table(lines[idx:end]))
    return [row for row in rows if row.get("Action", "").strip()]


def reviewed_summary(text: str) -> str:
    explicit = re.search(r"^- \*\*Reviewed Summary:\*\*[ \t]*([^\r\n]+)$", text, re.M)
    if explicit and explicit[1].strip():
        return explicit[1].strip()
    actions = [row["Action"] for row in decision_rows(text)]
    return "; ".join(actions[:2])


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
    entries_by_date = {entry.week_date: entry for entry in entries_desc}
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
            if rf.name[:10] >= newest.week_date.isoformat():
                continue
            seen_actions = set()
            for row in decision_rows(rf.read_text(encoding="utf-8-sig")):
                if row.get("Status", "").lower() not in {"open", "in progress", "blocked", "pending"}:
                    continue
                action, owner, due = row["Action"], row.get("Owner", ""), row.get("Due Date", row.get("Due", ""))
                key = (action, owner, due)
                if key not in seen_actions:
                    carry_rows.append(f"| {action} | {owner} | {due} | {row['Status']} | From {rf.stem[:10]} |")
                    seen_actions.add(key)
            break

    md_lines = [
        f"# {cfg.product_name} {dash} Weekly Product Review ({newest.week_date.isoformat()}, Q{q} W{woq} / W{woy})",
        "",
        f"- **Cadence:** {cfg.meeting_cadence or 'Weekly (60 mins)'}",
        f"- **Attendees:** {cfg.owners or 'Product, Engineering, Growth & Metric Owners'}",
        "- **Reviewed Summary:** ",
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
        prv, wow_pct, avg4 = period_statistics(entries_by_date, eval_vals, newest.week_date, m.metric_id)
        wow_str = dash
        if wow_pct is not None:
            wow_str = f"{wow_pct * 100:+.1f}%"

        traw, tnum = m.target_for_tab(active_tab_name)
        if newest.period_state != "closed":
            signal = "Preview: period not closed"
        elif m.mtype == "not-collected":
            signal = m.source_eta or "Planned"
        elif cur is None:
            signal = "Pending input" if m.mtype == "manual" else "Unavailable"
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
        "*(Log 1-3 specific customer quotes or feedback items from this week that explain movements or expose a cohort gap.)*",
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


def rebase_markdown_links(text: str, source_dir: Path, destination_dir: Path) -> str:
    """Keep local inline-link targets stable when exporting a Markdown source."""
    source_dir, destination_dir = source_dir.resolve(), destination_dir.resolve()
    if source_dir == destination_dir:
        return text

    def replace(match):
        if match[1] is not None:  # Inline code is source text, not a link.
            return match[0]
        try:
            target = urlsplit(match[4])
        except ValueError:
            return match[0]
        if target.scheme or target.netloc or not target.path or target.path.startswith(("/", "\\")):
            return match[0]
        absolute = (source_dir / unquote(target.path)).resolve()
        try:
            relative = Path(os.path.relpath(str(absolute), str(destination_dir))).as_posix()
        except ValueError as error:
            raise ValueError("Export local evidence links to the same drive as their source") from error
        url = urlunsplit(("", "", quote(relative, safe="/"), target.query, target.fragment))
        return match[3] + url + match[5]

    pattern = r"(`+)(.*?)\1|(!?\[[^\]\n]+\]\()([^\s)]+)(\))"
    output, fence = [], None
    for line in text.splitlines(keepends=True):
        marker = re.match(r"^ {0,3}(`{3,}|~{3,})(.*)$", line)
        if fence:
            output.append(line)
            if marker and marker[1][0] == fence[0] and len(marker[1]) >= len(fence) and not marker[2].strip():
                fence = None
        elif marker:
            fence = marker[1]
            output.append(line)
        else:
            output.append(re.sub(pattern, replace, line))
    return "".join(output)


def _render_inline(text: str, depth: int = 0) -> str:
    """Render the documented inline subset; escape HTML and reject executable URL schemes."""
    if depth > 8:
        return html.escape(text)
    pattern = r"`([^`]+)`|\[([^\]]+)\]\(([^)\s]+)\)|\*\*([^*]+)\*\*|\*([^*]+)\*"
    output = []
    position = 0
    for match in re.finditer(pattern, text):
        output.append(html.escape(text[position:match.start()].replace(r"\|", "|")))
        if match[1] is not None:
            output.append("<code>" + html.escape(match[1]) + "</code>")
        elif match[2] is not None:
            label, url = _render_inline(match[2], depth + 1), html.unescape(match[3])
            try:
                safe = (urlsplit(url).scheme.lower() in {"", "https", "http", "mailto"}
                        and not url.startswith(("//", "\\")) and not any(ord(c) < 32 for c in url))
            except ValueError:
                safe = False
            output.append(f'<a href="{html.escape(url, quote=True)}">{label}</a>' if safe else label)
        else:
            tag, content = ("strong", match[4]) if match[4] is not None else ("em", match[5])
            output.append(f"<{tag}>" + _render_inline(content, depth + 1) + f"</{tag}>")
        position = match.end()
    output.append(html.escape(text[position:].replace(r"\|", "|")))
    return "".join(output)


def render_brief_html(title: str, md_text: str) -> str:
    """Render a Weekly Product Review Markdown brief into Swiss Precision Grid HTML."""
    html_parts = [
        "<!DOCTYPE html><html lang='en'><head><meta charset='utf-8'>",
        f"<title>{html.escape(title)}</title>",
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
            if in_list:
                html_parts.append("</ul>")
                in_list = False
            if re.fullmatch(r"[\|\s:\-]+", line):
                continue
            cells = _markdown_cells(line)
            if not in_table:
                in_table = True
                html_parts.append("<table><thead><tr>" + "".join(f"<th>{_render_inline(c)}</th>" for c in cells) + "</tr></thead><tbody>")
            else:
                tds = []
                for idx_c, c in enumerate(cells):
                    esc = _render_inline(c)
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
            txt = _render_inline(line[2:])
            html_parts.append(f"<li>{txt}</li>")
            continue
        if in_list:
            html_parts.append("</ul>")
            in_list = False
        if line.startswith("# "):
            html_parts.append(f"<h1>{_render_inline(line[2:])}</h1>")
        elif line.startswith("## "):
            html_parts.append(f"<h2>{_render_inline(line[3:])}</h2>")
        elif line.startswith("### "):
            html_parts.append(f"<h3>{_render_inline(line[4:])}</h3>")
        elif line.strip():
            txt = _render_inline(line)
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
        review_path = wpr_dir / "reviews" / f"{e.week_date.isoformat()}-wpr.md"
        if review_path.exists():
            summary = reviewed_summary(review_path.read_text(encoding="utf-8-sig"))
            latest_note_by_date[e.week_date] = rebase_markdown_links(summary, review_path.parent, out_dir)

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
    md_brief, _ = generate_review_brief(cfg, entries_desc, eval_vals, reviews_dir)
    (out_dir / "wpr-review-draft.md").write_text(rebase_markdown_links(md_brief, reviews_dir, out_dir), encoding="utf-8")

    if entries_desc:
        reviews_dir.mkdir(parents=True, exist_ok=True)
        rev_path = reviews_dir / f"{entries_desc[0].week_date.isoformat()}-wpr.md"
        if not rev_path.exists() or args.overwrite_review:
            rev_path.write_text(md_brief, encoding="utf-8")
            print(f"Created review draft: {rev_path}")
        else:
            rev_text = rev_path.read_text(encoding="utf-8-sig")
            md_brief = rev_text

    md_brief = rebase_markdown_links(md_brief, reviews_dir, out_dir)
    html_title = f"{cfg.product_name} Weekly Product Review" + (f" - {entries_desc[0].week_date.isoformat()}" if entries_desc else "")
    html_brief = render_brief_html(html_title, md_brief)

    (out_dir / "wpr-review-brief.md").write_text(md_brief, encoding="utf-8")
    (out_dir / "wpr-review-brief.html").write_text(html_brief, encoding="utf-8")

    archive_parts: List[str] = []
    if reviews_dir.exists():
        for rf in sorted(reviews_dir.glob("*-wpr.md"), reverse=True):
            archive_parts.append(rebase_markdown_links(rf.read_text(encoding="utf-8-sig"), rf.parent, out_dir).strip())
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
        "catalog_signature": compute_catalog_signature(cfg),
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
    _preflight_mutation(wpr_dir)
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

    if cfg.week_ending_day.lower() not in WEEKDAY_MAP or new_date.weekday() != WEEKDAY_MAP[cfg.week_ending_day.lower()]:
        raise ValueError(f"Date {new_date} must be a {cfg.week_ending_day}")

    if any(e.week_date == new_date for e in entries) and not args.force:
        print(f"Week {new_date.isoformat()} already exists in {data_path}. Use --force to overwrite.", file=sys.stderr)
        return 1

    existing_week = next((e for e in entries if e.week_date == new_date), None)
    entries = [e for e in entries if e.week_date != new_date]
    new_entry = WeekEntry(week_date=new_date, period_state="preview", comparison_group=existing_week.comparison_group if existing_week else "")
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
    dry_run = getattr(args, "dry_run", False)
    save_metrics_data(data_path, cfg, entries, dry_run=dry_run)
    print(f"{'Would add' if dry_run else 'Added'} week {new_date.isoformat()} to {data_path}")
    return 0


def _reconcile_rows_into_entries(
    cfg: WPRConfig,
    rows: List[List[str]],
    by_date: Dict[dt.date, WeekEntry],
    report: Optional[dict] = None,
) -> int:
    if report is None:
        report = {"unmatched_rows": [], "uncomputed_headers": []}
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
            if parsed_d.weekday() != WEEKDAY_MAP[cfg.week_ending_day.lower()]:
                raise ValueError(f"Import date {parsed_d} must be a {cfg.week_ending_day}")
            col_dates[c_idx] = parsed_d
        else:
            report["uncomputed_headers"].append(f"Column {col_letter(c_idx + 1)}: uncomputed or invalid date")

    name_to_metric = {m.name.lower(): m for m in cfg.metrics}
    id_to_metric = {m.metric_id: m for m in cfg.metrics}
    id_column = next((i for row in rows[:6] for i, value in enumerate(row) if value.strip() == "Metric ID"), None)
    updated = 0
    for row in rows[6:]:
        if not row:
            continue
        mname = row[0].strip().lower()
        mid = row[id_column].strip() if id_column is not None and id_column < len(row) else ""
        mdef = id_to_metric.get(mid) if mid else name_to_metric.get(mname)
        if not mdef or mdef.mtype != "manual":
            analysis_labels = {"wow change", "4-week avg", "qtd total", "ytd total", "target delta", "qoq delta", "yoy delta", "weekly highlights / doc"}
            if not mdef and mname and mname not in analysis_labels and any(c < len(row) and row[c].strip() for c in col_dates):
                report["unmatched_rows"].append(f"Unmatched metric: {mid or row[0].strip()}")
            continue
        for c_idx, wd in col_dates.items():
            if c_idx >= len(row):
                continue
            val_raw = row[c_idx].strip()
            if not val_raw:
                continue
            issue = input_error(mdef, val_raw)
            if issue:
                raise ValueError(f"Import {wd} / {mdef.metric_id}: {issue}; source left unchanged")
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


def _print_import_report(report):
    for key, messages in report.items():
        print(f"{key}: {len(messages)}")
        for message in messages:
            print(f"[WARN] {message}")


def _preflight_mutation(wpr_dir):
    errors, _ = validate_wpr(wpr_dir)
    if errors:
        raise ValueError("; ".join(errors) + "; source left unchanged")


def cmd_import_csv(args: argparse.Namespace) -> int:
    wpr_dir = Path(args.wpr_dir)
    _preflight_mutation(wpr_dir)
    cfg = load_config(wpr_dir / "wpr-config.md")
    data_path = wpr_dir / "metrics-data.md"
    entries = load_metrics_data(data_path) if data_path.exists() else []
    by_date = {e.week_date: e for e in entries}

    with open(args.csv, "r", encoding="utf-8-sig", newline="") as fh:
        rows = list(csv.reader(fh))

    if not any(row and row[0].strip().lower() in WEEKDAY_MAP for row in rows[:6]):
        print("Could not find week-ending date row (e.g. 'Friday') in CSV.", file=sys.stderr)
        return 1

    report = {"unmatched_rows": [], "uncomputed_headers": []}
    updated = _reconcile_rows_into_entries(cfg, rows, by_date, report)
    _print_import_report(report)
    dry_run = getattr(args, "dry_run", False)
    if updated:
        save_metrics_data(data_path, cfg, list(by_date.values()), dry_run=dry_run)
    print(f"{'Would import/update' if dry_run else 'Imported/updated'} {updated} manual metric cells from {args.csv}")
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
    _preflight_mutation(wpr_dir)
    cfg = load_config(wpr_dir / "wpr-config.md")
    data_path = wpr_dir / "metrics-data.md"
    entries = load_metrics_data(data_path) if data_path.exists() else []
    by_date = {e.week_date: e for e in entries}

    updated = 0
    report = {"unmatched_rows": [], "uncomputed_headers": []}
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
                elif c_el.find("m:f", XLSX_NS) is not None:
                    val = "=UNCOMPUTED"
                rows_dict.setdefault(r_num, {})[c_num] = val
                max_r = max(max_r, r_num)
                max_c = max(max_c, c_num)

            rows_grid: List[List[str]] = []
            for r in range(1, max_r + 1):
                row_map = rows_dict.get(r, {})
                rows_grid.append([row_map.get(c, "") for c in range(1, max_c + 1)])

            updated += _reconcile_rows_into_entries(cfg, rows_grid, by_date, report)

    _print_import_report(report)
    dry_run = getattr(args, "dry_run", False)
    if updated:
        save_metrics_data(data_path, cfg, list(by_date.values()), dry_run=dry_run)
    print(f"{'Would import/update' if dry_run else 'Imported/updated'} {updated} manual metric cells from {args.xlsx}")
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
    p_add.add_argument("--dry-run", action="store_true", help="Print the proposed diff without writing")

    p_imp = sub.add_parser("import-csv", help="Import manual metric values from a single-tab CSV export")
    p_imp.add_argument("--wpr-dir", default="wpr")
    p_imp.add_argument("--csv", required=True)
    p_imp.add_argument("--dry-run", action="store_true", help="Print the proposed diff without writing")

    p_ix = sub.add_parser("import-xlsx", help="Import manual metric values across all quarter tabs of an .xlsx export")
    p_ix.add_argument("--wpr-dir", default="wpr")
    p_ix.add_argument("--xlsx", required=True)
    p_ix.add_argument("--dry-run", action="store_true", help="Print the proposed diff without writing")

    p_bld = sub.add_parser("build", help="Build multi-year .xlsx workbook, review brief/archive, and sheets-payload.json")
    p_bld.add_argument("--wpr-dir", default="wpr")
    p_bld.add_argument("--out-dir", default="wpr-output")
    p_bld.add_argument("--overwrite-review", action="store_true")
    p_bld.add_argument("--active-tab-first", action="store_true", help="Move the active quarter tab to position 0")

    p_plan = sub.add_parser("plan-sync", help="Plan date-keyed Sheet writes without network access")
    p_plan.add_argument("--payload", required=True)
    p_plan.add_argument("--previous")
    p_plan.add_argument("--date", required=True)
    p_plan.add_argument("--out", required=True)

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
    if args.cmd == "plan-sync":
        return cmd_plan_sync(args)
    return 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ValueError, OSError, zipfile.BadZipFile, ET.ParseError) as error:
        print(f"[ERROR] {error}", file=sys.stderr)
        raise SystemExit(1)
