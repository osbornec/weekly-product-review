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


def merge_snapshots(retained, incoming):
    """Keep separate captures; refuse a conflicting value for an identical observation."""
    def key(row):
        return (row["item_id"], row["metric_id"], row["window"], stamp(row["period_start_exclusive"]),
                stamp(row["period_end_inclusive"]), stamp(row["captured_at"]), row["source"])

    known = {key(row): row for row in retained}
    for row in incoming:
        identity = key(row)
        if identity in known and (known[identity]["value"], known[identity].get("state")) != (
                row["value"], row.get("state")):
            raise ValueError("Conflicting values for the same item snapshot")
        known.setdefault(identity, row)
    return list(known.values())


def item_snapshots(capture, as_of):
    items = {item["id"]: item for item in capture.get("items", [])}
    aliases = {}
    for alias in capture.get("aliases", []):
        if alias.get("evidence") and alias.get("verified") and alias["item_id"] in items:
            aliases.setdefault((alias["source"], alias["alias"]), set()).add(alias["item_id"])
    rows, unresolved = [], []
    for row in capture.get("observations", []):
        captured = stamp(row["captured_at"])
        if captured > as_of:
            raise ValueError("A source observation cannot be later than the observation time")
        candidates = ({row["item_id"]} if row.get("item_id")
                      else aliases.get((row["source"], row.get("item_alias")), set()))
        if not candidates and "item_alias" not in row:
            continue  # Account observations and legacy diagnostic rows remain in their original scope.
        if len(candidates) != 1 or not candidates <= items.keys():
            unresolved.append(row)
            continue
        if not stamp(row["period_start_exclusive"]) < stamp(row["period_end_inclusive"]) <= captured:
            raise ValueError("Item snapshot bounds must end by its capture time")
        rows.append(dict(row, item_id=next(iter(candidates))))
    return merge_snapshots([], rows), unresolved


EVENT_KINDS = {
    "pieces": {"publish-original"},
    "attempts": {"attempt", "bounced-attempt", "resend"},
    "responses": {"substantive-response"},
    "meetings": {"meeting-confirmed"},
    "outcomes": {"outcome-accepted"},
}
UNIQUE_EVENT_IDS = {"responses": "person_id", "meetings": "meeting_id", "outcomes": "outcome_id"}


def collect_events(capture, start, end, as_of):
    all_events = sorted(capture.get("events", []), key=lambda event: stamp(event["at"]))
    first_confirmations = {}
    for event in all_events:
        if event["kind"] == "meeting-confirmed":
            first_confirmations.setdefault(event["meeting_id"], event)

    counts, reasons = {}, {}
    for metric, kinds in EVENT_KINDS.items():
        source = capture.get("event_sources", {}).get(metric, {})
        _, coverage = source_timing(capture, source, as_of)
        cutoff = min(end, stamp(coverage))
        relevant = first_confirmations.values() if metric == "meetings" else all_events
        selected = []
        ambiguous = False
        for event in relevant:
            if event["kind"] not in kinds:
                continue
            observed = stamp(event["at"])
            if event.get("precision") == "minute" and observed <= cutoff < observed + dt.timedelta(minutes=1):
                policy = capture.get("cutoff_minute")
                if policy not in {"include", "exclude"}:
                    ambiguous = True
                if policy != "include":
                    continue
            if start < observed <= cutoff:
                selected.append(event)
        identity = UNIQUE_EVENT_IDS.get(metric)
        counts[metric] = len({event[identity] for event in selected}) if identity else len(selected)
        if ambiguous:
            counts[metric] = None
            reasons[metric] = "Cutoff-minute event needs a reporting rule"
    return counts, reasons


def collect(capture, as_of):
    start, end = stamp(capture["period_start_exclusive"]), stamp(capture["period_end_inclusive"])
    if end <= start:
        raise ValueError("The period must end after it starts")
    as_of = stamp(as_of)
    counts, reasons = collect_events(capture, start, end, as_of)
    sources = dict(capture.get("event_sources", {}))
    source_windows = {}
    for mid in ("weekly_reach", "weekly_visitors"):
        observation = capture.get("account", {}).get(mid)
        window = capture.get("source_windows", {}).get(mid, capture)
        window_start, window_end = stamp(window["period_start_exclusive"]), stamp(window["period_end_inclusive"])
        if window_end <= window_start:
            raise ValueError("The source window must end after it starts")
        source_windows[mid] = window
        if observation:
            sources[mid] = observation
        matches = (observation and stamp(observation["period_start_exclusive"]) == window_start
                   and stamp(observation["period_end_inclusive"]) == window_end)
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
    elif (prior is None or not article.get("prior_at") or stamp(article["prior_at"]) != start
          or article.get("prior_item_id", article.get("item_id")) != article.get("current_item_id", article.get("item_id"))):
        reasons["article_growth"] = "Missing comparable baseline"
    elif current < prior:
        reasons["article_growth"] = "Counter decreased; review needed"
    else:
        counts["article_growth"] = current - prior
    records = []
    for mid, observed in counts.items():
        source = sources.get(mid, {})
        window = source_windows.get(mid, capture)
        captured_at, coverage_through = source_timing(capture, source, as_of)
        if not capture.get("available", True) or not source.get("available", True):
            state, reason = "unavailable", "Source unavailable"
        elif observed is None:
            state, reason = "unavailable", reasons[mid]
        elif as_of < end:
            state, reason = "preview", "Reporting period is open"
        elif stamp(coverage_through) < stamp(window["period_end_inclusive"]):
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
                        "period_start_exclusive": source.get("period_start_exclusive", window["period_start_exclusive"]),
                        "period_end_inclusive": source.get("period_end_inclusive", window["period_end_inclusive"]),
                        "time_zone": window.get("time_zone", capture["time_zone"]),
                        "captured_at": captured_at, "coverage_through": coverage_through})
    result = {key: capture[key] for key in ("period_start_exclusive", "period_end_inclusive", "captured_at", "coverage_through", "time_zone", "comparison_group")}
    snapshots, unresolved = item_snapshots(capture, as_of)
    result.update(records=records, observations=capture.get("observations", []),
                  item_snapshots=snapshots, unresolved_item_observations=unresolved,
                  event_evidence=capture.get("events", []), attribution_evidence=capture.get("attribution_evidence", []),
                  writes_history=False)
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
