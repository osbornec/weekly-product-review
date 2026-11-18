"""Verify an isolated local Skill installation using an existing Skills CLI."""
import argparse
import csv
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
from urllib.parse import unquote, urlsplit


REPO = Path(__file__).resolve().parents[1]
SKILL_PATH = Path("skills") / "weekly-product-review"
RUNTIME_FILES = {
    "SKILL.md", "LICENSE", "scripts/wpr_sync.py",
    "references/collector-contract.md", "references/connector-sync.md",
    "references/integrations.md", "references/markdown-schema.md",
    "references/metric-discovery.md", "references/sheet-template-spec.md",
    "references/wpr-methodology.md",
    "assets/templates/metrics-data.template.md", "assets/templates/weekly-review.template.md",
    "assets/templates/wpr-config.template.md",
    "examples/creator-wpr/README.md", "examples/creator-wpr/capture.example.json",
    "examples/creator-wpr/capture.partial-close.example.json",
    "examples/creator-wpr/collect_wpr.py", "examples/creator-wpr/metrics-data.md",
    "examples/creator-wpr/wpr-config.md",
}
OUTPUTS = {"wpr-workbook.xlsx", "wpr-review-draft.md", "wpr-review-brief.md",
           "wpr-review-brief.html", "wpr-review-archive.md", "sheets-payload.json"}


def files_at(root):
    return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in root.rglob("*") if p.is_file()}


def run(args, cwd, env):
    completed = subprocess.run([str(arg) for arg in args], cwd=cwd, env=env,
                               capture_output=True, text=True, encoding="utf-8", timeout=60)
    if completed.returncode:
        raise RuntimeError(completed.stdout + completed.stderr)
    return completed.stdout


def verify_links(installed):
    checked = 0
    for path in installed.rglob("*.md"):
        text = path.read_text(encoding="utf-8")
        for match in re.finditer(r"\[[^\]]+\]\(([^)\s]+)\)", text):
            target = urlsplit(match[1])
            if target.scheme or target.netloc or not target.path:
                continue
            resolved = (path.parent / unquote(target.path)).resolve()
            if not resolved.is_relative_to(installed.resolve()) or not resolved.exists():
                raise AssertionError("Broken or external package link in " + path.relative_to(installed).as_posix())
            checked += 1
    text = (installed / "SKILL.md").read_text(encoding="utf-8")
    for target in re.findall(r"`((?:scripts|references|assets|examples)/[^`\s]+)`", text):
        if not (installed / target).exists():
            raise AssertionError("Missing Skill resource: " + target)
        checked += 1
    return checked


def verify(cli, runtime_python=None):
    runtime_python = runtime_python or sys.executable
    node = shutil.which("node")
    if not node:
        raise RuntimeError("Node.js is required to run the supplied Skills CLI")
    env = dict(os.environ, DISABLE_TELEMETRY="1", DO_NOT_TRACK="1", CI="1",
               PYTHONDONTWRITEBYTECODE="1", PYTHONUTF8="1")
    if (REPO / "SKILL.md").exists():
        raise AssertionError("A root SKILL.md would make the repository the installable package")
    source_manifest = files_at(REPO / SKILL_PATH)
    if set(source_manifest) != RUNTIME_FILES:
        raise AssertionError("Runtime manifest differs from the explicit package boundary")
    if (REPO / "LICENSE").read_bytes() != (REPO / SKILL_PATH / "LICENSE").read_bytes():
        raise AssertionError("The runtime licence must match the repository licence")
    with tempfile.TemporaryDirectory(prefix="wpr-installed-skill-") as temporary:
        base = Path(temporary).resolve()
        if not base.is_relative_to(Path(tempfile.gettempdir()).resolve()):
            raise AssertionError("Verification must stay inside its temporary workspace")
        snapshot, workspace = base / "repository", base / "workspace"
        snapshot.mkdir()
        workspace.mkdir()
        names = subprocess.check_output(
            ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"], cwd=REPO
        ).decode("utf-8").split("\0")
        for name in filter(None, names):
            source = REPO / name
            if not source.is_file():
                continue
            if not source.resolve().is_relative_to(REPO):
                raise AssertionError("Repository file escapes the source tree")
            target = snapshot / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
        # Synthetic sentinels expose accidental copying of repository-only files.
        for name in (".local/private-marker.txt", "tests/exclusion-marker.txt",
                     "docs/exclusion-marker.txt", "assets/exclusion-marker.txt"):
            target = snapshot / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("Invented packaging sentinel.\n", encoding="utf-8")
        run([node, cli, "add", snapshot, "--agent", "codex", "--copy", "--yes"], workspace, env)
        entries = list(workspace.rglob("SKILL.md"))
        if len(entries) != 1:
            raise AssertionError("Expected exactly one discovered and installed Skill")
        installed = entries[0].parent
        if installed.name != "weekly-product-review" or not re.search(
                r"^name: weekly-product-review$", entries[0].read_text(encoding="utf-8"), re.M):
            raise AssertionError("The installed Skill identity changed")
        installed_manifest = files_at(installed)
        if installed_manifest != source_manifest:
            raise AssertionError("Installed files differ from the runtime source manifest")
        links = verify_links(installed)
        engine = installed / "scripts/wpr_sync.py"
        project = workspace / "synthetic user project"
        project.mkdir()
        creator = project / "creator"
        shutil.copytree(installed / "examples/creator-wpr", creator)
        capture = json.loads((creator / "capture.example.json").read_text(encoding="utf-8"))
        candidate = json.loads(run([runtime_python, "-B", installed / "examples/creator-wpr/collect_wpr.py",
                                   "--input", creator / "capture.example.json", "--as-of", capture["captured_at"]], project, env))
        records = {r["metric_id"]: r for r in candidate["records"]}
        if len(records) != 8 or records["weekly_reach"]["value"] != 640 or records["article_growth"]["value"] != 27:
            raise AssertionError("Installed collector returned incorrect synthetic candidates")
        if candidate["writes_history"]:
            raise AssertionError("Collection must not write review history")
        run([runtime_python, "-B", engine, "validate", "--wpr-dir", creator], project, env)
        creator_output = project / "creator-output"
        run([runtime_python, "-B", engine, "build", "--wpr-dir", creator,
             "--out-dir", creator_output, "--active-tab-first"], project, env)
        if {p.name for p in creator_output.iterdir()} != OUTPUTS:
            raise AssertionError("Installed creator build did not produce the six expected outputs")
        manual = project / "manual"
        manual.mkdir()
        for filename in ("wpr-config", "metrics-data"):
            shutil.copy2(installed / "assets/templates" / (filename + ".template.md"), manual / (filename + ".md"))
        data = manual / "metrics-data.md"
        data.write_text(data.read_text(encoding="utf-8").replace("- Period State: preview", "- Period State: closed", 1), encoding="utf-8")
        date = re.search(r"^## Week (\d{4}-\d{2}-\d{2})", data.read_text(encoding="utf-8"), re.M)[1]
        csv_path = project / "manual-input.csv"
        with csv_path.open("w", newline="", encoding="utf-8") as handle:
            csv.writer(handle).writerows([["Friday", "", date], [], [], [], [], [], ["New Users", "", "7"]])
        run([runtime_python, "-B", engine, "import-csv", "--wpr-dir", manual, "--csv", csv_path], project, env)
        run([runtime_python, "-B", engine, "validate", "--wpr-dir", manual], project, env)
        output = project / "manual-output"
        run([runtime_python, "-B", engine, "build", "--wpr-dir", manual, "--out-dir", output], project, env)
        payload = output / "sheets-payload.json"
        plan_path = project / "sync-plan.json"
        run([runtime_python, "-B", engine, "plan-sync", "--payload", payload, "--previous", payload,
             "--date", date, "--out", plan_path], project, env)
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
        if plan["network_writes"] or len(plan["tabs"]) != 2:
            raise AssertionError("Installed sync planning did not target quarter and annual tabs")
        roundtrip = project / "roundtrip"
        roundtrip.mkdir()
        shutil.copy2(manual / "wpr-config.md", roundtrip / "wpr-config.md")
        (roundtrip / "metrics-data.md").write_text("# Weekly Metrics Data\n", encoding="utf-8")
        run([runtime_python, "-B", engine, "import-xlsx", "--wpr-dir", roundtrip,
             "--xlsx", output / "wpr-workbook.xlsx"], project, env)
        if "| new_users | New Users | 7 | manual |" not in (roundtrip / "metrics-data.md").read_text(encoding="utf-8"):
            raise AssertionError("Installed workbook round trip lost the synthetic manual value")
        next_date = (dt.date.fromisoformat(date) + dt.timedelta(days=7)).isoformat()
        original = data.read_bytes()
        run([runtime_python, "-B", engine, "add-week", "--wpr-dir", manual,
             "--date", next_date, "--dry-run"], project, env)
        if data.read_bytes() != original:
            raise AssertionError("Installed dry run changed source data")
        run([runtime_python, "-B", engine, "add-week", "--wpr-dir", manual, "--date", next_date], project, env)
        if "## Week " + next_date not in data.read_text(encoding="utf-8"):
            raise AssertionError("Installed add-week did not create the next period")
        if files_at(installed) != installed_manifest:
            raise AssertionError("A workflow modified the installed Skill")
        return {"passed": True, "cli_version": json.loads((cli.parent.parent / "package.json").read_text(encoding="utf-8"))["version"],
                "runtime_version": run([runtime_python, "--version"], project, env).strip(),
                "skill_name": installed.name, "installed_file_count": len(installed_manifest),
                "installed_bytes": sum((installed / name).stat().st_size for name in installed_manifest),
                "installed_manifest": sorted(installed_manifest), "relative_links_checked": links,
                "excluded": ["development tests", "repository README", "promotional images", "QA records", "private/local files"],
                "workflows": ["collector candidates", "creator validation and build", "template scaffold", "CSV import",
                              "manual validation and build", "XLSX round trip", "date-keyed sync plan", "add-week dry run", "add-week"],
                "installed_files_unchanged_after_workflows": True, "telemetry_disabled": True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skills-cli", required=True, type=Path, help="Existing skills/bin/cli.mjs path")
    parser.add_argument("--report", type=Path, help="Optional local JSON verification report")
    parser.add_argument("--python", type=Path, help="Python interpreter for installed runtime workflow checks")
    args = parser.parse_args()
    result = verify(args.skills_cli.resolve(strict=True), args.python.resolve(strict=True) if args.python else None)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
