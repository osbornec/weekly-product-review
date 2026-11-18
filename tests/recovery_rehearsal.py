"""Development-only rehearsal of the connector guide, using local JSON destinations.

Runs the real collector, Markdown reconciler, validator, builder and sync planner.
The durable checkpoints and fake destinations model agent-owned orchestration;
they are not an unattended executor shipped with the Skill. No network access.
"""
import argparse
import contextlib
import datetime as dt
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys


DEFAULT_SKILL = Path(__file__).resolve().parents[1] / "skills/weekly-product-review"
STEPS = ("collection", "reconciliation", "build", "sheet", "doc")


def read(path, default=None):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default


def write(path, value):
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    os.replace(str(temporary), str(path))


def fingerprint(paths):
    result = hashlib.sha256()
    for path in paths:
        if path.is_file():
            result.update(path.name.encode("utf-8"))
            result.update(path.read_bytes())
    return result.hexdigest()


def load_engine(skill):
    spec = importlib.util.spec_from_file_location("rehearsal_wpr", skill / "scripts/wpr_sync.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def run(workspace, skill=DEFAULT_SKILL, failure="none"):
    workspace, skill = workspace.resolve(), skill.resolve()
    marker = workspace / "synthetic-rehearsal.json"
    if not marker.exists():
        workspace.mkdir(parents=True, exist_ok=True)
        if any(workspace.iterdir()):
            raise ValueError("A fresh rehearsal needs an empty workspace")
        write(marker, {"synthetic_only": True})
        shutil.copytree(skill / "examples/creator-wpr", workspace / "wpr")
    if read(marker) != {"synthetic_only": True}:
        raise ValueError("Not a synthetic rehearsal workspace")
    project = workspace / "wpr"
    engine = load_engine(skill)
    state_path = workspace / "run-state.json"
    state = read(state_path, {"attempts": 0, "steps": {name: "pending" for name in STEPS}})
    state["attempts"] += 1
    capture_path = project / "capture.example.json"
    capture = read(capture_path)
    candidate_input = dict(capture)
    if failure == "collection-unavailable":
        candidate_input["available"] = False
    elif failure == "collection-stale":
        candidate_input["coverage_through"] = capture["period_start_exclusive"]
    staged = workspace / "capture-input.json"
    write(staged, candidate_input)
    # One collector attempt per invocation. Never loop on failed access.
    command = [sys.executable, "-B", str(skill / "examples/creator-wpr/collect_wpr.py"),
               "--input", str(staged), "--as-of", capture["captured_at"]]
    result = subprocess.run(command, cwd=str(workspace), capture_output=True, text=True,
                            encoding="utf-8", timeout=30)
    candidates = json.loads(result.stdout) if result.returncode == 0 else {"records": []}
    records = candidates["records"]
    if not records or any(row["state"] not in {"verified", "verified-zero"} for row in records):
        state["steps"]["collection"] = "pending"
        state["complete"] = False
        state["pending"] = ["collection"]
        write(state_path, state)
        return state

    source_paths = [capture_path, project / "wpr-config.md", project / "metrics-data.md"]
    source_paths += sorted((project / "reviews").glob("*.md"))
    revision = fingerprint(source_paths)
    if revision != state.get("source_revision"):
        state["steps"] = {name: "pending" for name in STEPS}
    state["steps"]["collection"] = "verified"
    date = capture["period_end_inclusive"][:10]
    if state["steps"]["reconciliation"] != "verified":
        cfg = engine.load_config(project / "wpr-config.md")
        entries = engine.load_metrics_data(project / "metrics-data.md")
        entry = next(item for item in entries if item.week_date == dt.date.fromisoformat(date))
        for row in records:
            cell = entry.cells[row["metric_id"]]
            cell.value_raw, cell.value_num = str(row["value"]), row["value"]
            cell.status = "verified-zero" if row["state"] == "verified-zero" else "automated"
        entry.period_state = "closed"
        engine.save_metrics_data(project / "metrics-data.md", cfg, entries)
        state["steps"]["reconciliation"] = "verified"
    if state["steps"]["build"] != "verified":
        errors, _ = engine.validate_wpr(project)
        if errors:
            raise ValueError("; ".join(errors))
        with contextlib.redirect_stdout(io.StringIO()):
            engine.cmd_build(argparse.Namespace(wpr_dir=str(project), out_dir=str(workspace / "output"),
                                                active_tab_first=True, overwrite_review=False))
        state["steps"]["build"] = "verified"
    source_paths = [capture_path, project / "wpr-config.md", project / "metrics-data.md"]
    source_paths += sorted((project / "reviews").glob("*.md"))
    state["source_revision"] = fingerprint(source_paths)
    payload = read(workspace / "output/sheets-payload.json")
    previous_path = workspace / "verified-sheet-payload.json"
    plan = engine.plan_sync(payload, read(previous_path), date)
    # Compare destination content rather than requests: catalog requests disappear
    # from the plan after verification, even though the intended catalog is stable.
    sheet = {}
    for title, tab in payload["tabs"].items():
        if not (title.startswith("Q") or title.startswith("Full Year")):
            continue
        column = tab["week_columns"].get(date)
        index = engine._col_ref_to_idx(column + "1")[1] - 1 if column else None
        sheet[title] = {"catalog": [row[:2] for row in tab["values"]],
                        "period": [[row[index]] for row in tab["values"]] if index is not None else None}
    desired = {"sheet": sheet, "doc": (workspace / "output/wpr-review-brief.md").read_text(encoding="utf-8")}
    state["date"] = date
    state["complete"] = False
    state["pending"] = [name for name in STEPS if state["steps"][name] != "verified"]
    write(state_path, state)
    for destination in ("sheet", "doc"):
        path = workspace / (destination + "-destination.json")
        live = read(path, {"periods": {"2027-02-05": "prior-review-sentinel"}, "writes": 0,
                           "custom": {"chart": 73, "comment": "retain", "note": "retain"}, "revision": 1})
        # Recover a lost acknowledgement by reading before resubmitting a write.
        if live["periods"].get(date) != desired[destination]:
            state["steps"][destination] = "pending"
            state["pending"] = [name for name in STEPS if state["steps"][name] != "verified"]
            write(state_path, state)
            if failure == destination + "-unavailable" or (destination == "doc" and failure == "revision-conflict"):
                continue
            live["periods"][date] = desired[destination]
            live["writes"] += 1
            live["revision"] += 1
            write(path, live)
            if failure == destination + "-crash-after-write":
                # Emulate process exit after server commit, before local receipt.
                raise SystemExit(86)
        if failure == destination + "-readback":
            state["steps"][destination] = "pending"
            continue
        actual = read(path)
        if actual["periods"].get(date) != desired[destination]:
            raise AssertionError("Destination readback differs")
        state["steps"][destination] = "verified"
        if destination == "sheet":
            write(previous_path, payload)
        write(state_path, state)
    state["pending"] = [name for name in STEPS if state["steps"][name] != "verified"]
    state["complete"] = not state["pending"]
    write(state_path, state)
    return state


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", required=True, type=Path)
    parser.add_argument("--skill-root", type=Path, default=DEFAULT_SKILL)
    parser.add_argument("--failure", default="none", choices=["none", "collection-unavailable", "collection-stale",
                        "sheet-unavailable", "doc-unavailable", "sheet-readback", "doc-readback",
                        "sheet-crash-after-write", "doc-crash-after-write", "revision-conflict"])
    args = parser.parse_args()
    result = run(args.workspace, args.skill_root, args.failure)
    print(json.dumps(result, indent=2))
    return 0 if result["complete"] else 2


if __name__ == "__main__":
    sys.exit(main())
