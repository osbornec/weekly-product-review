"""One-shot local scheduler probe. Models destinations; never calls a service."""
import argparse
import datetime as dt
import json
import os
from pathlib import Path
import subprocess
import sys
import traceback


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", required=True, type=Path)
    parser.add_argument("--skill-root", required=True, type=Path)
    args = parser.parse_args()
    if args.workspace.exists() and any(args.workspace.iterdir()):
        parser.error("Use a fresh empty workspace for the scheduled failure/recovery scenario")
    args.workspace.mkdir(parents=True, exist_ok=True)
    report = {"started_at": dt.datetime.now(dt.timezone.utc).isoformat(), "pid": os.getpid(),
              "working_directory": str(Path.cwd()), "runtime": sys.version, "cloud_writes": False}
    try:
        script = Path(__file__).with_name("recovery_rehearsal.py")
        command = [sys.executable, "-B", str(script), "--workspace", str(args.workspace / "synthetic project"),
                   "--skill-root", str(args.skill_root)]
        returns = []
        for failure in ("doc-unavailable", "none", "none"):
            completed = subprocess.run(command + ["--failure", failure], capture_output=True,
                                       text=True, encoding="utf-8", timeout=30)
            returns.append(completed.returncode)
            if completed.returncode not in (0, 2):
                raise RuntimeError(completed.stdout + completed.stderr)
        if returns != [2, 0, 0]:
            raise AssertionError("Partial failure, recovery and no-op run must return 2, 0, 0")
        for name in ("sheet", "doc"):
            live = json.loads((args.workspace / "synthetic project" / (name + "-destination.json")).read_text(encoding="utf-8"))
            if live["writes"] != 1 or len(live["periods"]) != 2:
                raise AssertionError("Scheduled retries duplicated a date or a successful write")
        report.update(passed=True, return_codes=returns, destination_writes={"sheet": 1, "doc": 1})
    except Exception:
        report.update(passed=False, error=traceback.format_exc())
    report["finished_at"] = dt.datetime.now(dt.timezone.utc).isoformat()
    (args.workspace / "scheduled-result.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
