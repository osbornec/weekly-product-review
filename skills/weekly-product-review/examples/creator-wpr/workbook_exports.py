"""Reference adapter for a synthetic creator workbook. Browser interaction stays with the caller."""
import argparse
import copy
import datetime as dt
import hashlib
import io
import json
from pathlib import Path
import re
import sys
import xml.etree.ElementTree as ET
import zipfile


DAILY_METRICS = ("impressions", "export_engagements", "new_followers")


def timestamp(value):
    parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.utcoffset() is None:
        raise ValueError("A capture timestamp needs a UTC offset")
    return parsed


def days_first_to_last(first, last):
    if last < first:
        raise ValueError("The date range ends before it starts")
    return [first + dt.timedelta(days=offset) for offset in range((last - first).days + 1)]


def count(raw, signed=False):
    if not re.fullmatch(r"-?(?:\d+|\d{1,3}(?:,\d{3})+)", raw.strip()):
        raise ValueError("Expected a whole number")
    value = int(raw.replace(",", ""))
    if value < 0 and not signed:
        raise ValueError("This count cannot be negative")
    return value


def parse_workbook(data, read_sheets, account, first, last):
    """Validate the declared account and range against the actual worksheet rows."""
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        if archive.testzip() is not None:
            raise ValueError("Workbook failed its integrity check")
    sheets = dict(read_sheets(io.BytesIO(data), lambda name: name in ("Export info", "Daily")))
    metadata = {row[0]: row[1] for row in sheets["Export info"] if len(row) >= 2 and row[0]}
    if (metadata.get("account"), metadata.get("first_utc_day"), metadata.get("last_utc_day")) != (
            account, first.isoformat(), last.isoformat()):
        raise ValueError("Workbook account or selected dates do not match the attempt")
    daily = sheets["Daily"]
    header = daily[0]
    if any(header.count(key) != 1 for key in ("utc_day", *DAILY_METRICS)):
        raise ValueError("Workbook daily headers are missing or ambiguous")
    dates = []
    rows = {}
    for row in daily[1:]:
        if not any(row):
            continue
        day = dt.date.fromisoformat(row[header.index("utc_day")])
        dates.append(day)
        if day.isoformat() in rows:
            raise ValueError("Workbook repeats a UTC day")
        rows[day.isoformat()] = {key: count(row[header.index(key)], signed=key == "export_engagements")
                                 for key in DAILY_METRICS}
    if sorted(dates) != days_first_to_last(first, last):
        raise ValueError("Workbook has missing or unexpected UTC dates")
    if sum(row["impressions"] for row in rows.values()) != count(metadata["range_impressions"]):
        raise ValueError("Daily impressions do not reconcile to the selected range")
    distinct = metadata.get("range_unique_members")
    return rows, count(distinct) if distinct else None


def inspect_download(directory, filename, request_at, as_of, account, first, last, read_sheets,
                     waiting_for_save=False, browser_event="unknown"):
    """Return a saved workbook receipt or a pending state. This function never imports."""
    requested, checked = timestamp(request_at), timestamp(as_of)
    if checked < requested or last > checked.astimezone(dt.timezone.utc).date():
        raise ValueError("The attempt contains future dates or timestamps")
    if Path(filename).name != filename or Path(filename).suffix.lower() != ".xlsx":
        raise ValueError("Provide an XLSX filename without a path")
    pattern = re.compile(re.escape(Path(filename).stem) + r"(?: \(\d+\))?\.xlsx", re.I)
    status = {"state": "waiting-for-save" if waiting_for_save else "requested", "requested_at": request_at,
              "browser_event": browser_event, "rejected": []}
    directory = Path(directory)
    if not directory.is_dir():
        status["rejected"].append({"reason": "Configured download directory is unavailable"})
        return status
    candidates = sorted(p for p in directory.iterdir() if pattern.fullmatch(p.name) and p.is_file())
    verified = []
    for path in candidates:
        try:
            before = path.stat()
            saved_at = dt.datetime.fromtimestamp(before.st_mtime, dt.timezone.utc)
            if not requested <= saved_at <= checked:
                raise ValueError("File timestamp is outside the attempt")
            raw = path.read_bytes()
            rows, distinct = parse_workbook(raw, read_sheets, account, first, last)
            after = path.stat()
            if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
                raise ValueError("Workbook changed while being inspected")
        except (OSError, ValueError, KeyError, IndexError, zipfile.BadZipFile, ET.ParseError) as error:
            status["rejected"].append({"file": path.name, "reason": str(error)})
            continue
        verified.append(dict(status, state="saved", file=path.name, saved_at=saved_at.isoformat(),
                             sha256=hashlib.sha256(raw).hexdigest(), account=account,
                             first_utc_day=first.isoformat(), last_utc_day=last.isoformat(),
                             rows=rows, range_unique_members=distinct))
    if not verified:
        return status
    if len({receipt["sha256"] for receipt in verified}) > 1:
        status["rejected"].append({"reason": "Multiple different workbooks match this attempt"})
        return status
    return max(verified, key=lambda receipt: receipt["saved_at"])


def reconcile_daily(ledger, receipt, restatement_reason=""):
    """Stage complete UTC days. Preserve accepted values while revisions await corroboration."""
    if receipt["state"] != "saved":
        raise ValueError("A validated saved workbook is required")
    if ledger.get("account", receipt["account"]) != receipt["account"]:
        raise ValueError("Workbook account differs from the ledger account")
    staged = copy.deepcopy(ledger)
    staged["account"] = receipt["account"]
    rows = staged.setdefault("days", {})
    pending = staged.setdefault("pending", {})
    receipts = staged.setdefault("receipts", {})
    digest = receipt["sha256"]
    result = {"state": "imported", "added": 0, "matched": 0, "held": 0, "restated": 0,
              "open_days": [], "ledger": staged}
    if digest in receipts:
        return result
    utc_today = timestamp(receipt["saved_at"]).astimezone(dt.timezone.utc).date().isoformat()
    changes = staged.setdefault("restatements", [])
    for day, observations in receipt["rows"].items():
        if day >= utc_today:
            result["open_days"].append(day)
            continue
        if day not in rows:
            rows[day] = dict(observations)
            result["added"] += 1
            continue
        if observations == rows[day]:
            result["matched"] += 1
        for metric, value in observations.items():
            if value == rows[day][metric]:
                continue
            key = day + "/" + metric
            prior = pending.get(key)
            corroborated = prior and prior["value"] == value and prior["sha256"] != digest
            if restatement_reason.strip() and corroborated:
                changes.append({"day": day, "metric": metric, "previous": rows[day][metric], "value": value,
                                "receipts": [prior["sha256"], digest], "reason": restatement_reason.strip()})
                rows[day][metric] = value
                del pending[key]
                result["restated"] += 1
            else:
                if not prior or prior["value"] != value:
                    pending[key] = {"value": value, "sha256": digest}
                result["held"] += 1
    receipts[digest] = {key: receipt[key] for key in (
        "file", "requested_at", "saved_at", "first_utc_day", "last_utc_day", "range_unique_members")}
    return result


def verify_import(result, readback):
    if result["state"] != "imported" or result["ledger"] != readback:
        raise ValueError("Imported workbook ledger did not match readback")
    return dict(result, state="verified")


def weekly_totals(ledger, end_exclusive):
    """Compute each additive series over seven complete UTC days before its configured bound."""
    days = [d.isoformat() for d in days_first_to_last(end_exclusive - dt.timedelta(days=7),
                                                     end_exclusive - dt.timedelta(days=1))]
    actual, pending = ledger.get("days", {}), ledger.get("pending", {})
    gaps = {metric: [day for day in days if metric not in actual.get(day, {}) or day + "/" + metric in pending]
            for metric in DAILY_METRICS}
    return {"days": days, "gaps": gaps,
            "values": {metric: None if gaps[metric] else sum(actual[day][metric] for day in days)
                       for metric in DAILY_METRICS}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--downloads", required=True, type=Path)
    parser.add_argument("--filename", required=True)
    parser.add_argument("--requested-at", required=True)
    parser.add_argument("--as-of", required=True)
    parser.add_argument("--account", required=True)
    parser.add_argument("--first-day", required=True, type=dt.date.fromisoformat)
    parser.add_argument("--last-day", required=True, type=dt.date.fromisoformat)
    parser.add_argument("--waiting-for-save", action="store_true")
    parser.add_argument("--browser-event", default="unknown")
    args = parser.parse_args()
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
    from wpr_sync import read_xlsx_sheets
    receipt = inspect_download(args.downloads, args.filename, args.requested_at, args.as_of, args.account,
                               args.first_day, args.last_day, read_xlsx_sheets, args.waiting_for_save,
                               args.browser_event)
    print(json.dumps(receipt, indent=2))
    return 0 if receipt["state"] == "saved" else 2


if __name__ == "__main__":
    sys.exit(main())
