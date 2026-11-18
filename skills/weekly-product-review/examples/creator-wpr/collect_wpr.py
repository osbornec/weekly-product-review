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


def source_timing(capture, source, as_of):
    captured_at = source.get("captured_at", capture["captured_at"])
    coverage_through = source.get("coverage_through", capture["coverage_through"])
    captured, coverage = stamp(captured_at), stamp(coverage_through)
    if captured > as_of or coverage > captured:
        raise ValueError("Capture cannot follow the observation time and coverage cannot follow capture")
    return captured_at, coverage_through


def collect(capture, as_of):
    start, end = stamp(capture["period_start_exclusive"]), stamp(capture["period_end_inclusive"])
    if end <= start:
        raise ValueError("The period must end after it starts")
    as_of = stamp(as_of)
    _, event_coverage = source_timing(capture, {}, as_of)
    event_cutoff = min(end, stamp(event_coverage))

    def in_period(event):
        return start < stamp(event["at"]) <= event_cutoff

    events = [event for event in capture.get("events", []) if in_period(event)]
    counts = {
        "pieces": sum(e["kind"] == "publish-original" for e in events),
        "attempts": sum(e["kind"] in {"attempt", "bounced-attempt", "resend"} for e in events),
        "responses": len({e["person_id"] for e in events if e["kind"] == "substantive-response"}),
        "meetings": len({e["meeting_id"] for e in events if e["kind"] == "meeting-confirmed"}),
        "outcomes": len({e["outcome_id"] for e in events if e["kind"] == "outcome-accepted"}),
    }
    sources, reasons = {}, {}
    for mid in ("weekly_reach", "weekly_visitors"):
        observation = capture.get("account", {}).get(mid)
        if observation:
            sources[mid] = observation
        matches = (observation and stamp(observation["period_start_exclusive"]) == start
                   and stamp(observation["period_end_inclusive"]) == end)
        counts[mid] = observation["value"] if matches else None
        reasons[mid] = "Source window does not match" if observation and not matches else "Source unavailable"
    article = capture.get("article_counter", {})
    sources["article_growth"] = article
    prior, current = article.get("prior"), article.get("current")
    counts["article_growth"] = None
    if current is None or not article.get("current_at"):
        reasons["article_growth"] = "Source unavailable"
    elif stamp(article["current_at"]) != end or stamp(article["current_at"]) > stamp(article.get("captured_at", capture["captured_at"])):
        reasons["article_growth"] = "Source window does not match"
    elif prior is None or not article.get("prior_at") or stamp(article["prior_at"]) != start:
        reasons["article_growth"] = "Missing comparable baseline"
    elif current < prior:
        reasons["article_growth"] = "Counter decreased; review needed"
    else:
        counts["article_growth"] = current - prior
    records = []
    for mid, observed in counts.items():
        source = sources.get(mid, {})
        captured_at, coverage_through = source_timing(capture, source, as_of)
        if not capture.get("available", True) or not source.get("available", True):
            state, reason = "unavailable", "Source unavailable"
        elif observed is None:
            state, reason = "unavailable", reasons[mid]
        elif as_of < end:
            state, reason = "preview", "Reporting period is open"
        elif stamp(coverage_through) < end:
            state, reason = "stale", "Source coverage ends before the cutoff"
        else:
            state, reason = ("verified-zero" if observed == 0 else "verified"), ""
        if mid == "article_growth":
            scope, default_source = "tracked-article", "Synthetic article analytics"
        elif mid.startswith("weekly_"):
            scope, default_source = "account", "Synthetic account dashboard"
        else:
            scope, default_source = "dated-events", "Synthetic activity log"
        records.append({"metric_id": mid, "value": observed if state in {"verified", "verified-zero"} else None,
                        "observed": observed, "state": state, "unit": "count", "scope": scope,
                        "source": source.get("source", default_source),
                        "source_label": source.get("source_label", mid), "reason": reason,
                        "period_start_exclusive": source.get("period_start_exclusive", capture["period_start_exclusive"]),
                        "period_end_inclusive": source.get("period_end_inclusive", capture["period_end_inclusive"]),
                        "captured_at": captured_at, "coverage_through": coverage_through})
    result = {key: capture[key] for key in ("period_start_exclusive", "period_end_inclusive", "captured_at", "coverage_through", "time_zone", "comparison_group")}
    observations = capture.get("observations", [])
    for observation in observations:
        if stamp(observation["captured_at"]) > as_of:
            raise ValueError("A source observation cannot be later than the observation time")
    result.update(records=records, observations=observations, writes_history=False)
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
