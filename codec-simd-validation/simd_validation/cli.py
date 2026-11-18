"""Command line entry points for live replay and retained evidence checking."""

from __future__ import annotations

import argparse
import importlib
from importlib import resources
import json
from pathlib import Path
import shutil
import sys
import time
import traceback

from . import __version__
from .catalog import CASES
from .core import RunContext, digest, host_info, inside, inventory, utc_now, write_json
from .report import observations_csv, render
from .schema import validate_case, validate_sources


def default_workspace():
    checkout = Path(__file__).resolve().parent.parent
    return checkout.parent if (checkout / "protocol.json").is_file() else Path.cwd()


def add_workspace(parser):
    parser.add_argument("--workspace", type=Path, default=default_workspace(),
                        help="Directory containing the local codec source repositories")
    for alias in CASES:
        parser.add_argument("--" + alias + "-repo", type=Path, help="Override the " + alias + " repository")


def selected_cases(args):
    selected = args.case or ["all"]
    if "all" in selected:
        if len(selected) != 1:
            raise ValueError("Select all or individual cases, without combining them")
        return list(CASES)
    if len(set(selected)) != len(selected):
        raise ValueError("Each case may be selected only once")
    return selected


def source_inventory():
    package = Path(__file__).resolve().parent
    rows = [{"path": "simd_validation/" + path.relative_to(package).as_posix(), "sha256": digest(path)}
            for path in sorted(package.rglob("*.py")) if "__pycache__" not in path.parts]
    harnesses = package.parent / "harnesses"
    if not harnesses.is_dir():
        harnesses = package / "harnesses"
    rows.extend({"path": "harnesses/" + path.name, "sha256": digest(path)}
                for path in sorted(harnesses.iterdir()) if path.suffix in (".cpp", ".cc", ".c", ".h"))
    rows.extend({"path": "simd_validation/data/" + path.name, "sha256": digest(path)}
                for path in sorted((package / "data").glob("*.json")))
    return rows


def load_data(name):
    return json.loads(resources.files("simd_validation").joinpath("data", name).read_text(encoding="utf-8"))


def run(args):
    selected = selected_cases(args)
    source_archive = None
    if getattr(args, "source_archive", None) is not None:
        from .portable import SourceArchive
        source_archive = SourceArchive(args.source_archive)
    output = args.out.resolve()
    output.mkdir(parents=True, exist_ok=False)
    started = utc_now()
    options = {key: str(value.resolve()) for key, value in vars(args).items()
               if key.endswith("_repo") and value is not None}
    manifest = {"schema_version": 1, "tool_version": __version__, "started_at_utc": started,
                "profile": args.profile, "selected": selected, "workspace": str(args.workspace.resolve()),
                "options": options, "host": host_info(), "tool_sources": source_inventory(),
                "classification": "historical_replay", "prospective_evaluation_started": False}
    if source_archive is not None:
        manifest["source_archive"] = {"path": str(args.source_archive.resolve()), "sha256": source_archive.sha256,
                                      "mode": "retained_snapshots; commit membership not independently rechecked"}
    write_json(output / "evaluation-protocol.json", load_data("evaluation-protocol.json"))
    write_json(output / "pilot-registry.json", load_data("pilot-registry.json"))
    manifest["protocol_sha256"] = digest(output / "evaluation-protocol.json")
    manifest["pilot_registry_sha256"] = digest(output / "pilot-registry.json")
    write_json(output / "manifest.json", manifest)
    suite = {"schema_version": 1, "tool_version": __version__, "started_at_utc": started,
             "profile": args.profile, "status": "running", "cases": []}
    write_json(output / "suite.json", suite)
    for alias in selected:
        definition = CASES[alias]
        case_output = output / "cases" / alias
        context = RunContext(args.workspace, case_output, args.profile, options,
                             case_alias=alias, source_archive=source_archive)
        tick = time.monotonic()
        print("Running " + alias + " (" + args.profile + ")", flush=True)
        try:
            module = importlib.import_module("simd_validation.adapters." + definition["module"])
            result = module.run(context)
            validate_case(result, case_output, definition["id"])
            validate_sources(context.sources, case_output)
        except Exception as error:
            (case_output / "adapter-exception.txt").write_text(traceback.format_exc(), encoding="utf-8")
            result = {"status": "infrastructure_error", "observations": [{
                "id": "adapter-exception", "variant": "all", "check": "baseline", "result": "error",
                "evidence": ["adapter-exception.txt", "commands.json"],
                "details": {"type": type(error).__name__, "reason": str(error)}}],
                "limits": ["The adapter did not complete or its retained result failed schema validation."]}
        result.update(schema_version=1, case=definition["id"], alias=alias,
                      classification=definition["classification"], elapsed_seconds=time.monotonic() - tick)
        write_json(case_output / "result.json", result)
        write_json(case_output / "artifact-manifest.json", {
            "schema_version": 1, "artifacts": inventory(case_output, exclude=("artifact-manifest.json",))})
        summary = {name: result[name] for name in ("case", "alias", "classification", "status", "elapsed_seconds", "observations", "limits")}
        summary["result_path"] = (case_output / "result.json").relative_to(output).as_posix()
        suite["cases"].append(summary)
        write_json(output / "suite.json", suite)
        print(alias + ": " + result["status"], flush=True)
    statuses = {case["status"] for case in suite["cases"]}
    suite["status"] = ("failed" if statuses & {"infrastructure_error", "unexpected_result"}
                       else "incomplete" if "unsupported" in statuses else "validated")
    suite["completed_at_utc"] = utc_now()
    suite["limitations"] = ["All selected cases are retrospective and already known.",
                            "Checks are not independent defects; counters retain their own units.",
                            "The three cases are not a pooled equal-budget experiment."]
    write_json(output / "suite.json", suite)
    (output / "report.rst").write_text(render(suite), encoding="utf-8")
    (output / "observations.csv").write_text(observations_csv(suite), encoding="utf-8")
    manifest["completed_at_utc"] = suite["completed_at_utc"]
    manifest["status"] = suite["status"]
    write_json(output / "manifest.json", manifest)
    write_json(output / "checksums.json", {"schema_version": 1, "algorithm": "sha256",
                                          "artifacts": inventory(output, exclude=("checksums.json",))})
    print(json.dumps({"status": suite["status"], "cases": len(suite["cases"]), "out": str(output)}))
    return 0 if suite["status"] == "validated" else 2 if suite["status"] == "incomplete" else 1


def verify_run(root):
    root = Path(root).resolve()
    document = json.loads((root / "checksums.json").read_text(encoding="utf-8"))
    if document.get("schema_version") != 1 or document.get("algorithm") != "sha256":
        raise ValueError("Unsupported checksum manifest")
    expected = document.get("artifacts")
    if not isinstance(expected, list) or not expected:
        raise ValueError("Checksum manifest has no artifacts")
    declared = {}
    for row in expected:
        path = row["path"]
        inside(root, path)
        if path in declared or path == "checksums.json":
            raise ValueError("Duplicate or recursive checksum entry")
        declared[path] = row
    actual = {row["path"]: row for row in inventory(root, exclude=("checksums.json",))}
    if declared.keys() != actual.keys():
        raise ValueError("Retained files differ from the inventory; missing=" + str(sorted(declared.keys() - actual.keys()))
                         + "; added=" + str(sorted(actual.keys() - declared.keys())))
    changed = [path for path in actual if actual[path] != declared[path]]
    if changed:
        raise ValueError("Artifact size or checksum changed: " + ", ".join(changed))
    suite = json.loads((root / "suite.json").read_text(encoding="utf-8"))
    if suite.get("schema_version") != 1 or suite.get("status") not in ("validated", "failed", "incomplete"):
        raise ValueError("Run is incomplete or has an unknown result schema")
    if not suite.get("cases"):
        raise ValueError("Run has no cases")
    seen = set()
    for summary in suite["cases"]:
        alias = summary["alias"]
        if alias not in CASES or alias in seen or summary["case"] != CASES[alias]["id"]:
            raise ValueError("Unknown or duplicate case in suite")
        seen.add(alias)
        result_path = inside(root, summary["result_path"])
        value = json.loads(result_path.read_text(encoding="utf-8"))
        validate_case(value, result_path.parent, summary["case"])
        sources = json.loads((result_path.parent / "source-manifest.json").read_text(encoding="utf-8"))
        validate_sources(sources, result_path.parent)
        for name in ("case", "alias", "classification", "status", "elapsed_seconds", "observations", "limits"):
            if value[name] != summary[name]:
                raise ValueError("Suite and case result disagree: " + alias + "/" + name)
    statuses = {case["status"] for case in suite["cases"]}
    expected_status = ("failed" if statuses & {"infrastructure_error", "unexpected_result"}
                       else "incomplete" if "unsupported" in statuses else "validated")
    if suite["status"] != expected_status:
        raise ValueError("Suite status does not match the retained case results")
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    if manifest["selected"] != [case["alias"] for case in suite["cases"]]:
        raise ValueError("Selected cases and executed cases differ")
    return suite, len(actual)


def doctor(args):
    from .adapters import aom, svt, x265
    revisions = {"aom": [aom.BASE_REVISION, aom.FIXED_REVISION], "svt": [svt.BEFORE, svt.FIXED],
                 "x265": [x265.BEFORE, x265.FIXED]}
    import subprocess
    rows = []
    for alias in CASES:
        repo = getattr(args, alias + "_repo") or args.workspace / CASES[alias]["repository"]
        checks = []
        if shutil.which("git") and repo.is_dir():
            for commit in revisions[alias]:
                completed = subprocess.run(["git", "-C", str(repo), "cat-file", "-e", commit + "^{commit}"],
                                           capture_output=True, timeout=30, check=False)
                checks.append({"commit": commit, "available": completed.returncode == 0})
        rows.append({"case": alias, "repo": str(repo.resolve()), "available": len(checks) == 2 and all(row["available"] for row in checks),
                     "revisions": checks})
    print(json.dumps({"host": host_info(), "clang": shutil.which("clang"), "clangxx": shutil.which("clang++"),
                      "repositories": rows}, indent=2))
    return 0 if all(row["available"] for row in rows) and shutil.which("clang") and shutil.which("clang++") else 2


def main(argv=None):
    parser = argparse.ArgumentParser(description="Rebuild and validate source-pinned video codec SIMD cases")
    parser.add_argument("--version", action="version", version=__version__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    listing = subparsers.add_parser("list", help="List case classifications and checked dimensions")
    listing.add_argument("--json", action="store_true")
    preflight = subparsers.add_parser("doctor", help="Check local history and compiler availability without reading candidate implementations")
    add_workspace(preflight)
    subparsers.add_parser("pilot", help="Show candidate exposure status; this does not execute candidate implementations")
    runner = subparsers.add_parser("run", help="Build and execute cases in a new output directory")
    runner.add_argument("--case", action="append", choices=["all", *CASES])
    runner.add_argument("--profile", choices=["smoke", "full"], default="smoke")
    runner.add_argument("--out", type=Path, required=True)
    runner.add_argument("--source-archive", type=Path, help="Rebuild from exported source snapshots instead of local codec repositories")
    add_workspace(runner)
    exporter = subparsers.add_parser("export", help="Export verified retained sources and upstream licenses, without binaries or old results")
    exporter.add_argument("directory", type=Path)
    exporter.add_argument("--out", type=Path, required=True)
    verifier = subparsers.add_parser("verify", help="Check all retained hashes, evidence paths and case summaries")
    verifier.add_argument("directory", type=Path)
    reporter = subparsers.add_parser("report", help="Print a verified retained run report")
    reporter.add_argument("directory", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == "list":
            if args.json:
                print(json.dumps(CASES, indent=2))
            else:
                for alias, row in CASES.items():
                    print(alias + ": " + row["classification"] + "; " + row["dimension"] + "; " + row["description"])
            return 0
        if args.command == "doctor":
            return doctor(args)
        if args.command == "pilot":
            print(json.dumps(load_data("pilot-registry.json"), indent=2))
            return 0
        if args.command == "run":
            return run(args)
        if args.command == "export":
            from .portable import export_sources
            print(json.dumps(export_sources(args.directory, args.out), ensure_ascii=False))
            return 0
        suite, count = verify_run(args.directory)
        if args.command == "report":
            print(render(suite), end="")
        else:
            print(json.dumps({"integrity": "verified", "run_status": suite["status"], "files": count,
                              "cases": len(suite["cases"])}))
        return 0
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(type(error).__name__ + ": " + str(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
