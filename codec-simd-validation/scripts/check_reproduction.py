"""Compare retained historical results after rebuilding on another installation."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from simd_validation.cli import verify_run


def canonical_hash(value):
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def source_identities(root, alias):
    sources = read_json(root / "cases" / alias / "source-manifest.json")
    identities = sorted((row["commit"], row["path"], row["blob"], row["sha256"])
                        for row in sources)
    return identities, sources


def tool_changes(baseline, reproduction):
    def hashes(manifest):
        return {row["path"].replace("simd_validation/harnesses/", "harnesses/", 1): row["sha256"]
                for row in manifest["tool_sources"]}

    before, after = hashes(baseline), hashes(reproduction)
    added, removed = sorted(after.keys() - before.keys()), sorted(before.keys() - after.keys())
    changed = sorted(path for path in before.keys() & after.keys() if before[path] != after[path])
    return {"same_recorded_hashes": not (added or removed or changed),
            "added": added, "removed": removed, "changed": changed}


def compare(baseline, reproduction, require_portable=False):
    old, old_files = verify_run(baseline)
    new, new_files = verify_run(reproduction)
    old_manifest = read_json(baseline / "manifest.json")
    new_manifest = read_json(reproduction / "manifest.json")
    checks = {
        "same_tool_version": old["tool_version"] == new["tool_version"],
        "same_profile": old["profile"] == new["profile"],
        "same_selected_cases": old_manifest["selected"] == new_manifest["selected"],
        "both_runs_validated": old["status"] == new["status"] == "validated",
    }
    for filename in ("evaluation-protocol.json", "pilot-registry.json"):
        checks["same_" + filename] = read_json(baseline / filename) == read_json(reproduction / filename)
    old_cases = {case["alias"]: case for case in old["cases"]}
    rows = []
    for case in new["cases"]:
        alias = case["alias"]
        previous = old_cases.get(alias)
        before_sources, _ = source_identities(baseline, alias) if previous else ([], [])
        after_sources, sources = source_identities(reproduction, alias)
        commands = read_json(reproduction / "cases" / alias / "commands.json")
        git_commands = sum(Path(command["argv"][0]).name == "git" or
                           (Path(command["argv"][0]).name == "arch" and
                            any(Path(arg).name == "git" for arg in command["argv"][1:4]))
                           for command in commands)
        case_checks = {
            "same_case_and_classification": previous is not None and all(
                previous[key] == case[key] for key in ("case", "classification", "status")),
            "same_observations": previous is not None and previous["observations"] == case["observations"],
            "same_source_identities": before_sources == after_sources,
        }
        modes = sorted({source.get("source_mode", "git") for source in sources})
        if require_portable:
            case_checks["portable_sources_only"] = bool(sources) and modes == ["portable_snapshot"]
            case_checks["no_recorded_git_invocations"] = git_commands == 0
        rows.append({"case": alias, "checks": case_checks,
                     "observations": len(case["observations"]), "source_references": len(sources),
                     "observation_sha256": canonical_hash(case["observations"]),
                     "source_identities_sha256": canonical_hash(after_sources),
                     "recorded_git_invocations": git_commands, "source_modes": modes})
    if require_portable:
        checks["source_archive_recorded"] = bool(new_manifest.get("source_archive"))
    matched = all(checks.values()) and all(all(row["checks"].values()) for row in rows)
    return {"schema_version": 1, "status": "matched" if matched else "different",
            "baseline": str(baseline), "reproduction": str(reproduction),
            "baseline_retained_files": old_files, "reproduction_retained_files": new_files,
            "checks": checks, "cases": rows,
            "tool_source_comparison": tool_changes(old_manifest, new_manifest),
            "limits": ["This comparison excludes elapsed time, command paths and build artifacts.",
                       "Matched observations do not require identical tool sources; recorded hash differences are listed separately.",
                       "A matching rebuild on the same machine is not independent replication.",
                       "Matching observations do not establish additional defect discoveries."]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("baseline", type=Path)
    parser.add_argument("reproduction", type=Path)
    parser.add_argument("--require-portable", action="store_true")
    parser.add_argument("--out", type=Path, required=True, help="New JSON evidence file")
    args = parser.parse_args()
    baseline, reproduction = args.baseline.resolve(), args.reproduction.resolve()
    output = args.out.resolve()
    if any(output.is_relative_to(root) for root in (baseline, reproduction)):
        parser.error("Comparison output must be outside both retained runs")
    result = compare(baseline, reproduction, args.require_portable)
    with args.out.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, indent=2, ensure_ascii=False)
        stream.write("\n")
    print(json.dumps({"status": result["status"], "cases": len(result["cases"]), "out": str(args.out)}))
    return 0 if result["status"] == "matched" else 1


if __name__ == "__main__":
    raise SystemExit(main())
