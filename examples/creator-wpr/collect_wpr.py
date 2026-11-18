"""Read-only synthetic collector: emit candidates without editing review history."""
import argparse
import datetime as dt
import json
from pathlib import Path


def stamp(raw):
    value = dt.datetime.fromisoformat(raw.replace("Z", "+00:00"))
    if value.utcoffset() is None:
        raise ValueError("Every timestamp needs an explicit UTC offset")
    return value


def collect(capture, as_of):
    start, end = stamp(capture["period_start_exclusive"]), stamp(capture["period_end_inclusive"])
    if end <= start:
        raise ValueError("The period must end after it starts")
    captured, coverage = stamp(capture["captured_at"]), stamp(capture["coverage_through"])
    as_of = stamp(as_of)
    if captured > as_of or coverage > captured:
        raise ValueError("Capture and coverage timestamps cannot postdate the observation time")
    closed = as_of >= end and captured >= end and coverage >= end
    state = "unavailable" if not capture.get("available", True) else ("stale" if coverage < end and as_of >= end else ("verified" if closed else "preview"))
    def in_period(event):
        return start < stamp(event["at"]) <= min(end, captured)
    events = [event for event in capture.get("events", []) if in_period(event)]
    counts = {
        "pieces": sum(e["kind"] == "publish-original" for e in events),
        "attempts": sum(e["kind"] in {"attempt", "bounced-attempt", "resend"} for e in events),
        "responses": len({e["person_id"] for e in events if e["kind"] == "substantive-response"}),
        "meetings": len({e["meeting_id"] for e in events if e["kind"] == "meeting-confirmed"}),
        "outcomes": len({e["outcome_id"] for e in events if e["kind"] == "outcome-accepted"}),
    }
    for mid in ("weekly_reach", "weekly_visitors"):
        observation = capture.get("account", {}).get(mid)
        counts[mid] = observation["value"] if observation and observation["period_start_exclusive"] == capture["period_start_exclusive"] and observation["period_end_inclusive"] == capture["period_end_inclusive"] else None
    article = capture.get("article_counter", {})
    counts["article_growth"] = None
    if article.get("prior_at") == capture["period_start_exclusive"] and article.get("current_at") == capture["period_end_inclusive"] and stamp(article["current_at"]) <= captured:
        prior, current = article.get("prior"), article.get("current")
        if prior is not None and current is not None and current >= prior:
            counts["article_growth"] = current - prior
    records = []
    for mid, observed in counts.items():
        numeric = observed if state == "verified" else None
        metric_state = "unavailable" if observed is None else ("verified-zero" if state == "verified" and observed == 0 else state)
        records.append({"metric_id": mid, "value": numeric, "observed": observed, "state": metric_state,
                        "unit": "count", "scope": "tracked-article" if mid == "article_growth" else ("account" if mid.startswith("weekly_") else "dated-events"),
                        "source": "synthetic capture", "source_label": mid,
                        "reason": "" if metric_state in {"verified", "verified-zero"} else ("Missing comparable source window or counter snapshots" if observed is None else {"preview": "Reporting period is open", "stale": "Source coverage ends before the cutoff", "unavailable": "Source access unavailable"}[state])})
    result = {key: capture[key] for key in ("period_start_exclusive", "period_end_inclusive", "captured_at", "coverage_through", "time_zone", "comparison_group")}
    result.update(records=records, writes_history=False)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=Path(__file__).with_name("capture.example.json"))
    parser.add_argument("--as-of", help="Offset-aware timestamp; defaults to current UTC time")
    args = parser.parse_args()
    capture = json.loads(args.input.read_text(encoding="utf-8"))
    print(json.dumps(collect(capture, args.as_of or dt.datetime.now(dt.timezone.utc).isoformat()), indent=2))


if __name__ == "__main__":
    main()
