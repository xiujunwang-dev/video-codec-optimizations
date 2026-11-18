"""Replay the pinned x265 12-bit energy reduction and its correction."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess


CASE = "x265-12bit-psy-reduction"
BEFORE = "1836f70c17cde142ac023da71a96ba9cc49c9213"
FIXED = "8e87b841b9374762a63af2a2e29246f701c1ccbd"
SOURCE_HASHES = {
    BEFORE: "f41046a88fa59a3e26e96c1ed8c4d38b5ebca09238ce606a7a2120914705babc",
    FIXED: "3a475e000f7c3f40ed0ec6c928e5df5824f4190dc007e9a9f72ddd517bb5b51b",
}
SOURCE_PATHS = (
    "source/common/aarch64/pixel-prim.cpp",
    "source/common/aarch64/pixel-prim.h",
    "source/common/aarch64/mem-neon.h",
    "COPYING",
)
SEEDS = (1, 17, 20261117)
GROUPS = ("uniform-independent", "endpoints-zero", "endpoints-near")
EXHAUSTIVE_GROUPS = ("exhaustive-zero", "exhaustive-complement", "exhaustive-near")
LIMITS = [
    "Retrospective replay of a known defect; no prospective discovery claim.",
    "The production kernel and helpers are extracted without modification; this is not end-to-end encoding.",
    "The independent wide-integer transform is spot-checked against a direct sign-matrix transform.",
    "Source variants and sanitizer modes receive matching input counts and fingerprints within each group.",
    "Elapsed harness time includes input generation, the reference calculation and result checking.",
    "Sanitized numeric mismatches come from the reference comparison, not sanitizer diagnostics.",
]


class UnexpectedResult(RuntimeError):
    """A completed experiment violated its declared expectations."""


def _sha(data):
    return hashlib.sha256(data).hexdigest()


def _bytes(value):
    if value is None:
        return b""
    return value.encode() if isinstance(value, str) else value


def _extract(source, signature):
    start = source.index(signature)
    opening = source.index("{", start)
    depth, end = 1, opening + 1
    while depth and end < len(source):
        depth += (source[end] == "{") - (source[end] == "}")
        end += 1
    if depth:
        raise UnexpectedResult("Unbalanced braces in pinned function " + signature)
    return source[start:end]


def _row_key(row):
    return row["group"], row["depth"], row["seed"]


def _expected_rows(cases, exhaustive_limit):
    expected = {("known-witness", 12, 1): 1}
    for depth in (10, 12):
        for seed in SEEDS:
            for group in GROUPS:
                expected[(group, depth, seed)] = cases
        for group in EXHAUSTIVE_GROUPS:
            expected[(group, depth, 1)] = exhaustive_limit
    return expected


def _validate_rows(rows, variant, cases, exhaustive_limit):
    expected = _expected_rows(cases, exhaustive_limit)
    if len(rows) != len(expected):
        raise UnexpectedResult(f"Expected {len(expected)} result rows, got {len(rows)}")
    seen = set()
    integer_fields = (
        "cases", "source_energy_mismatches", "recon_energy_mismatches",
        "cost_mismatches", "input_mutations", "oracle_disagreements",
    )
    for row in rows:
        key = _row_key(row)
        if key in seen or key not in expected:
            raise UnexpectedResult(f"Duplicate or undeclared input group: {key}")
        seen.add(key)
        for name in integer_fields:
            value = row.get(name)
            if type(value) is not int or value < 0:
                raise UnexpectedResult(f"Invalid result counter {name}: {value!r}")
        if row["cases"] != expected[key]:
            raise UnexpectedResult(f"Input count differs from the declared budget: {key}")
        for name in integer_fields[1:]:
            if row[name] > row["cases"]:
                raise UnexpectedResult(f"Result counter exceeds the number of inputs: {name}")
        fingerprint = row.get("input_fnv1a64")
        if not isinstance(fingerprint, str) or not fingerprint or len(fingerprint) > 16:
            raise UnexpectedResult("Invalid input fingerprint")
        try:
            int(fingerprint, 16)
        except ValueError as error:
            raise UnexpectedResult("Invalid input fingerprint") from error
        if row["oracle_disagreements"] or row["input_mutations"]:
            raise UnexpectedResult(f"Reference or immutable input check failed: {key}")
        if variant == "fixed" or row["depth"] == 10:
            if any(row[name] for name in integer_fields[1:4]):
                raise UnexpectedResult(f"Unexpected numeric mismatch for {variant}: {key}")
        if row["group"] in ("endpoints-near", "exhaustive-near") and row["cost_mismatches"]:
            raise UnexpectedResult(f"Unexpected failure of the masked-cost control: {key}")
    if variant == "before":
        witness = next(row for row in rows if row["group"] == "known-witness")
        details = witness.get("witness", {})
        if details.get("expected_cost") != 67568 or details.get("observed_cost") != 2032:
            raise UnexpectedResult("The historical witness did not reproduce its pinned costs")
        if exhaustive_limit == 65536:
            count = sum(row["cost_mismatches"] for row in rows
                        if row["depth"] == 12 and row["group"] in EXHAUSTIVE_GROUPS)
            if count != 44800:
                raise UnexpectedResult(f"Full endpoint enumeration changed: {count} mismatches")


def run(context):
    """Run one paired historical experiment using the shared execution context."""
    output = Path(context.output)
    output.mkdir(parents=True, exist_ok=True)
    log_directory = output / "x265-logs"
    log_directory.mkdir(exist_ok=True)
    observations, rows, sources = [], [], []
    manifest_path = output / "x265-manifest.json"
    results_path = output / "x265-results.json"
    manifest = {"case": CASE, "classification": "historical true defect replay", "sources": sources}

    def relative(path):
        return Path(path).relative_to(output).as_posix()

    def write_manifest():
        manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")

    def execute(argv, label, timeout=120, env=None):
        result = context.command(argv, label, env=env, timeout=timeout, check=False)
        for stream in ("stdout", "stderr"):
            (log_directory / (label + "." + stream)).write_bytes(_bytes(getattr(result, stream)))
        return result

    def evidence_for(label):
        return [relative(log_directory / (label + "." + stream)) for stream in ("stdout", "stderr")]

    def observation(identifier, variant, check, result, evidence, details, **counters):
        item = {"id": identifier, "variant": variant, "check": check, "result": result,
                "evidence": evidence, "details": details}
        item.update(counters)
        observations.append(item)

    def finish(status, reason=None):
        if reason:
            manifest["reason"] = reason
        manifest["status"] = status
        write_manifest()
        results_path.write_text(json.dumps({"case": CASE, "status": status, "rows": rows}, indent=2) + "\n")
        return {"case": CASE, "status": status, "observations": observations, "limits": list(LIMITS),
                "manifest": relative(manifest_path), "results": relative(results_path)}

    try:
        profile = context.profile
        if profile not in ("smoke", "full"):
            raise UnexpectedResult(f"Unsupported profile: {profile}")
        cases, exhaustive_limit = (128, 512) if profile == "smoke" else (4096, 65536)
        manifest.update(profile=profile, cases_per_seed_group=cases, exhaustive_limit=exhaustive_limit,
                        seeds=list(SEEDS), depths=[10, 12], groups=list(GROUPS),
                        exhaustive_groups=list(EXHAUSTIVE_GROUPS))
        harness = Path(context.resource("psy_cost.cpp"))
        manifest["harness_sha256"] = _sha(harness.read_bytes())
        manifest["adapter_sha256"] = _sha(Path(__file__).read_bytes())
        write_manifest()
        host_probe = (["/usr/bin/arch", "-arm64", "/usr/bin/uname", "-m"]
                      if platform.system() == "Darwin" else ["uname", "-m"])
        host = execute(host_probe, "x265-host")
        machine = _bytes(host.stdout).decode(errors="replace").strip()
        manifest["machine"] = machine
        if host.returncode or machine not in ("arm64", "aarch64"):
            observation("x265-host", "all", "baseline", "unsupported", evidence_for("x265-host"),
                        {"reason": "A native AArch64 host is required for the pinned Neon replay."})
            return finish("unsupported", "A native AArch64 host is unavailable.")
        repo = Path(context.options.get("x265_repo") or Path(context.workspace) / "s265/x265-psy-cost-12bit-review").resolve()
        if not repo.is_dir() and getattr(context, "source_archive", None) is None:
            observation("x265-source", "all", "baseline", "unsupported", [relative(manifest_path)],
                        {"reason": "The source repository is unavailable.", "repo": str(repo)})
            return finish("unsupported", "The pinned source repository is unavailable.")
        compiler = context.options.get("x265_cxx") or shutil.which("clang++")
        if not compiler:
            observation("x265-compiler", "all", "baseline", "unsupported", [relative(manifest_path)],
                        {"reason": "A C++ compiler with AArch64 Neon support is required."})
            return finish("unsupported", "The C++ compiler is unavailable.")
        compiler_version = execute([str(compiler), "--version"], "x265-compiler")
        if compiler_version.returncode:
            raise RuntimeError("The compiler version probe failed")
        manifest["compiler"] = _bytes(compiler_version.stdout).decode(errors="replace")
        fingerprints = {}
        for variant, revision in (("before", BEFORE), ("fixed", FIXED)):
            directory = output / variant
            directory.mkdir(exist_ok=True)
            contents = {}
            for path in SOURCE_PATHS:
                snapshot = directory / path
                source = dict(context.record_source(repo, revision, path, destination=snapshot))
                if source["commit"] != revision:
                    raise UnexpectedResult("A source revision resolved to an unexpected commit")
                data = snapshot.read_bytes()
                if _sha(data) != source["sha256"]:
                    raise UnexpectedResult("A retained source snapshot differs from its recorded checksum")
                if path.endswith("pixel-prim.cpp") and source["sha256"] != SOURCE_HASHES[revision]:
                    raise UnexpectedResult("The pinned production source checksum does not match")
                source["variant"] = variant
                sources.append(source)
                contents[path] = data.decode()
            helper = contents["source/common/aarch64/pixel-prim.h"]
            memory_helper = contents["source/common/aarch64/mem-neon.h"]
            notice_end = memory_helper.find("*/")
            if not memory_helper.startswith("/*") or notice_end < 0:
                raise UnexpectedResult("The pinned memory helper has no opening license notice")
            notice = memory_helper[:notice_end + 2]
            chunks = [_extract(helper, "static inline void " + name + "(") for name in
                      ("sumsubq_s16", "abssumsubq_s16", "transpose_s16_s16x2",
                       "transpose_s16_s32x2", "transpose_s16_s64x2")]
            chunks.insert(0, "template<int N>\n" + _extract(memory_helper,
                                                        "static void inline load_u16x4xn("))
            kernel = _extract(contents["source/common/aarch64/pixel-prim.cpp"],
                              "static inline int calc_energy_4x4(")
            chunks.append(kernel)
            kernel_text = (notice + "\n\n#include <arm_neon.h>\n#include <stdint.h>\n#define HIGH_BIT_DEPTH 1\n"
                           "using pixel = uint16_t;\nnamespace candidate {\n" + "\n\n".join(chunks) + "\n}\n")
            (directory / "kernel.hpp").write_text(kernel_text)
            (directory / "harness.cpp").write_bytes(harness.read_bytes())
            manifest[variant + "_kernel_sha256"] = _sha(kernel.encode())
            write_manifest()
            for mode in ("normal", "sanitized"):
                label = "x265-" + variant + "-" + mode
                binary = directory / mode
                flags = ["-fsanitize=address,undefined", "-fno-omit-frame-pointer"] if mode == "sanitized" else []
                arch = ["-arch", "arm64"] if platform.system() == "Darwin" else []
                build = execute([str(compiler), *arch, "-std=c++17", "-O2", "-g", *flags,
                                 str(directory / "harness.cpp"), "-o", str(binary)], label + "-build")
                if build.returncode:
                    raise RuntimeError(label + " compilation failed")
                environment = os.environ.copy()
                environment.update(ASAN_OPTIONS="detect_leaks=0:halt_on_error=1",
                                   UBSAN_OPTIONS="halt_on_error=1:print_stacktrace=1")
                arguments = [str(binary), "--cases", str(cases), "--exhaustive-limit", str(exhaustive_limit)]
                for seed in SEEDS:
                    arguments.extend(("--seed", str(seed)))
                completed = execute(arguments, label + "-run", timeout=300, env=environment)
                evidence = evidence_for(label + "-run")
                if completed.returncode:
                    observation(label + "-execution", variant, "baseline", "error", evidence,
                                {"mode": mode, "returncode": completed.returncode,
                                 "reason": "An unclassified harness failure requires investigation."})
                    if completed.returncode in (3, 4):
                        raise UnexpectedResult(label + " rejected its reference or immutable-input check")
                    raise RuntimeError(label + " execution failed")
                try:
                    current = [json.loads(line) for line in _bytes(completed.stdout).decode().splitlines()]
                    for row in current:
                        row.update(variant=variant, mode=mode, classification="historical true defect replay")
                    rows.extend(current)
                    _validate_rows(current, variant, cases, exhaustive_limit)
                except (KeyError, TypeError, ValueError, UnicodeError) as error:
                    raise UnexpectedResult("Malformed harness output: " + str(error)) from error
                observation(label + "-execution", variant, "baseline", "no_failure", evidence,
                            {"mode": mode, "returncode": completed.returncode,
                             "diagnostic_bytes": len(_bytes(completed.stderr)),
                             "meaning": "Successful execution does not imply numeric correctness."})
                if _bytes(completed.stderr).strip():
                    raise RuntimeError(label + " emitted an unclassified diagnostic")
                for row in current:
                    key = _row_key(row)
                    fingerprint = (row["cases"], row["input_fnv1a64"])
                    if key in fingerprints and fingerprints[key] != fingerprint:
                        raise UnexpectedResult(f"Input fingerprint differs across paired runs: {key}")
                    fingerprints[key] = fingerprint
                    base = label + "-" + row["group"] + "-" + str(row["depth"]) + "-" + str(row["seed"])
                    details = {name: row[name] for name in ("group", "depth", "seed", "input_fnv1a64")}
                    details.update(mode=mode, classification="historical true defect replay")
                    if "witness" in row:
                        details["witness"] = row["witness"]
                    energy_mismatches = row["source_energy_mismatches"] + row["recon_energy_mismatches"]
                    observation(base + "-energy", variant, "numeric", "detected" if energy_mismatches else "no_failure",
                                evidence, dict(details, source_mismatches=row["source_energy_mismatches"],
                                               reconstruction_mismatches=row["recon_energy_mismatches"]),
                                count=2 * row["cases"], unit="energy_evaluations", mismatches=energy_mismatches)
                    observation(base + "-cost", variant, "numeric", "detected" if row["cost_mismatches"] else "no_failure",
                                evidence, details, count=row["cases"], unit="input_pairs", mismatches=row["cost_mismatches"])
                observation(label + "-reference-and-inputs", variant, "oracle", "no_failure", evidence,
                            {"mode": mode, "direct_matrix_checks_per_group": "first min(32, cases) input pairs",
                             "input_mutations": 0, "oracle_disagreements": 0},
                            count=sum(row["cases"] for row in current), unit="input_pairs", mismatches=0)
        manifest["paired_input_check"] = "All variants and sanitizer modes have matching case counts and input fingerprints."
        observation("x265-paired-inputs", "all", "baseline", "no_failure", [relative(results_path), relative(manifest_path)],
                    {"runs": 4, "groups_per_run": len(fingerprints), "paired_fields": ["cases", "input_fnv1a64"]},
                    count=len(fingerprints), unit="input_groups", mismatches=0)
        return finish("validated")
    except UnexpectedResult as error:
        observation("x265-expectations", "all", "oracle", "error", [relative(manifest_path), relative(results_path)],
                    {"reason": str(error)})
        return finish("unexpected_result", str(error))
    except (OSError, RuntimeError, subprocess.SubprocessError) as error:
        observation("x265-infrastructure", "all", "baseline", "error", [relative(manifest_path)],
                    {"reason": str(error), "exception": type(error).__name__})
        return finish("infrastructure_error", str(error))
