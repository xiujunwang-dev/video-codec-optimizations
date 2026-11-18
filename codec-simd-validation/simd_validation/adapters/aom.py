"""Rebuild the historical high bit-depth IntraBC facade routing case."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import platform
import re
import shlex
import shutil
import subprocess


BASE_REVISION = "aac27b8f291ed449fac576bcce0ad0ca189be851"
FIXED_REVISION = "a583a61feb0d424959a1ff0cff5e298e31c98992"
CONVOLVE_PATH = "av1/common/convolve.c"
NEON_PATH = "av1/common/arm/highbd_convolve_neon.c"
FACADE_NAME = "av1_highbd_convolve_2d_facade"
KERNEL_NAMES = (
    "av1_highbd_convolve_x_sr_intrabc",
    "av1_highbd_convolve_y_sr_intrabc",
    "av1_highbd_convolve_2d_sr_intrabc",
)
PROFILE_EXPECTATIONS = {
    "smoke": {"scenarios": 270, "pixels_checked": 903096, "guard_cells_checked": 108000},
    "full": {"scenarios": 9477, "pixels_checked": 16287804, "guard_cells_checked": 8273772},
}


def _validate_metrics(data: object, profile: str, installed: str) -> list[str]:
    """Require nonempty fixed coverage before interpreting any outcome."""
    if not isinstance(data, dict):
        return ["metrics must be a JSON object"]
    errors = []
    expected = PROFILE_EXPECTATIONS[profile]
    for key, value in expected.items():
        actual = data.get(key)
        if type(actual) is not int or actual != value:
            errors.append(f"{key} must equal {value}")
    for key, value in (("profile", profile), ("installed_dispatch", installed)):
        if data.get(key) != value:
            errors.append(f"{key} must equal {value}")
    bounds = {
        "pixel_mismatches": expected["pixels_checked"],
        "c_formula_mismatches": expected["pixels_checked"],
        "c_differential_mismatches": expected["pixels_checked"],
        "guard_mismatches": expected["guard_cells_checked"],
        "source_mismatches": expected["scenarios"],
    }
    for key, maximum in bounds.items():
        value = data.get(key)
        if type(value) is not int or not 0 <= value <= maximum:
            errors.append(f"{key} must be a nonnegative integer no greater than {maximum}")
    for key in ("c_calls", "neon_calls", "dispatch_calls"):
        value = data.get(key)
        if not isinstance(value, list) or len(value) != 3 or any(
                type(counter) is not int or not 0 <= counter <= expected["scenarios"] for counter in value):
            errors.append(f"{key} must contain three bounded nonnegative integer counters")
    for key in ("input_digest_fnv1a64", "output_digest_fnv1a64"):
        if not isinstance(data.get(key), str) or not re.fullmatch(r"[0-9a-f]{16}", data[key]):
            errors.append(f"{key} must contain sixteen lowercase hexadecimal digits")
    return errors


def _function(source: str, name: str) -> tuple[str, int]:
    """Extract a complete named function without counting comment braces."""
    match = re.search(
        r"^void\s+" + re.escape(name) + r"\s*\([^;{}]*\)\s*\{",
        source,
        flags=re.MULTILINE,
    )
    if match is None:
        raise ValueError(f"cannot find complete function {name}")
    opening = source.index("{", match.start())
    depth = 0
    token = re.compile(r'//[^\n]*|/\*[\s\S]*?\*/|"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'|[{}]')
    for brace in token.finditer(source, opening):
        if brace.group() == "{":
            depth += 1
        elif brace.group() == "}":
            depth -= 1
            if depth == 0:
                return source[match.start():brace.end()] + "\n", source.count("\n", 0, match.start()) + 1
    raise ValueError(f"unterminated function {name}")


def _write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _relative(path: Path, output: Path) -> str:
    return path.relative_to(output).as_posix()


def run(context) -> dict:
    """Compile exact facade/kernel excerpts, then check arithmetic and calls.

    The dispatch pointers are installed explicitly by the harness. This is a
    local routing experiment, not CPU detection or encoder execution.
    """
    output = Path(context.output)
    output.mkdir(parents=True, exist_ok=True)
    if context.profile not in PROFILE_EXPECTATIONS:
        return {"status": "infrastructure_error", "observations": [{
            "id": "aom-intrabc-profile", "variant": "infrastructure", "check": "baseline",
            "result": "error", "evidence": [], "details": "The profile must be smoke or full."}], "limits": []}
    limits = [
        "Historical case selected after the original issue and fix were known; this is not a prospective discovery.",
        "Complete facade and kernel function bodies are extracted from fixed Git revisions and rebuilt in this run. Other codec paths are fail-fast stubs.",
        "The rebuild uses recorded upstream headers and a minimal configuration for these extracted functions, not a complete upstream library build.",
        "The local harness explicitly installs NEON or C dispatch pointers; it does not execute CPU feature detection, the generated RTCD initializer, an encoder, or a decoder.",
        "The two-tap non-compound unscaled IntraBC contract covers phases (8,0), (0,8), and (8,8), with uint16 storage at 8/10/12 bits. The copy path is outside this case.",
        "Source allocations include legal vector padding. Guard checks detect output changes outside the requested block, not every permissible source read.",
        "No local facade result establishes full-codec coverage, real-world issue prevalence, or whole-codec speedup.",
    ]
    darwin = platform.system() == "Darwin"
    native_arm = platform.machine().lower() in {"arm64", "aarch64"}
    if darwin and not native_arm:
        # A translated Python interpreter may report x86_64 on ARM hardware.
        hardware = context.command(["/usr/bin/arch", "-arm64", "/usr/bin/true"], "native-arm64-execution", timeout=30, check=False)
        native_arm = hardware.returncode == 0
    if not native_arm:
        return {"status": "unsupported", "observations": [], "limits": limits + ["This adapter currently requires native AArch64 NEON."]}
    architecture_flags = ["-arch", "arm64"] if darwin else []

    options = context.options or {}
    repository = Path(options.get("aom_repo", Path(context.workspace) / "aom")).resolve()
    compiler = shlex.split(str(options.get("cxx", os.environ.get("CXX", "clang++"))))
    if not compiler or shutil.which(compiler[0]) is None:
        return {"status": "unsupported", "observations": [], "limits": limits + ["A C++17 compiler with AArch64 NEON and address/undefined sanitizers is required."]}
    if not (repository / ".git").exists() and getattr(context, "source_archive", None) is None:
        return {"status": "unsupported", "observations": [], "limits": limits + [f"A local AOM Git repository is required at {repository}."]}

    build = output / "build"
    include = build / "include"
    include.mkdir(parents=True, exist_ok=True)
    observations = []
    extraction = []

    try:
        base = context.record_source(repository, BASE_REVISION, CONVOLVE_PATH)
        fixed = context.record_source(repository, FIXED_REVISION, CONVOLVE_PATH)
        neon = context.record_source(repository, BASE_REVISION, NEON_PATH)
        fixed_neon = context.record_source(repository, FIXED_REVISION, NEON_PATH)
        # Recording the registration establishes that these implementations
        # are registered upstream. The harness still installs its own pointers.
        registration = context.record_source(repository, BASE_REVISION, "av1/common/av1_rtcd_defs.pl")
        for path in ("LICENSE", "PATENTS"):
            context.record_source(repository, BASE_REVISION, path)

        def snapshot_path(record):
            path = Path(record["snapshot"])
            return path if path.is_absolute() else output / path

        base_source = snapshot_path(base).read_text(encoding="utf-8")
        fixed_source = snapshot_path(fixed).read_text(encoding="utf-8")
        neon_source = snapshot_path(neon).read_text(encoding="utf-8")
        fixed_neon_source = snapshot_path(fixed_neon).read_text(encoding="utf-8")
        for name in KERNEL_NAMES:
            if _function(base_source, name + "_c")[0] != _function(fixed_source, name + "_c")[0]:
                raise ValueError(f"C kernel changed across facade revisions: {name}")
            if _function(neon_source, name + "_neon")[0] != _function(fixed_neon_source, name + "_neon")[0]:
                raise ValueError(f"NEON kernel changed across facade revisions: {name}")
        registration_source = snapshot_path(registration).read_text(encoding="utf-8")
        excerpt = "\n".join(
            line for line in registration_source.splitlines()
            if any(name in line for name in KERNEL_NAMES)
        ) + "\n"
        (output / "registration-excerpt.txt").write_text(excerpt, encoding="utf-8")
        if not all(name in excerpt for name in KERNEL_NAMES):
            raise ValueError("recorded revision does not register all three IntraBC functions")

        seen_headers = set()

        def collect_header(path: str):
            if path in seen_headers or path.startswith("config/"):
                return
            if PurePosixPath(path).is_absolute() or ".." in PurePosixPath(path).parts:
                raise ValueError(f"unsafe header path: {path}")
            seen_headers.add(path)
            record = context.record_source(repository, BASE_REVISION, path, destination=include / path)
            text = snapshot_path(record).read_text(encoding="utf-8")
            for dependency in re.findall(r'^\s*#\s*include\s+"([^"\n]+)"', text, re.MULTILINE):
                collect_header(dependency)

        collect_header("av1/common/convolve.h")
        collect_header("aom_dsp/arm/mem_neon.h")
        config = include / "config" / "aom_config.h"
        config.parent.mkdir(parents=True, exist_ok=True)
        config.write_text(
            "/* Minimal configuration for the extracted IntraBC functions. */\n"
            "#ifndef AOM_CONFIG_H_\n#define AOM_CONFIG_H_\n"
            "#define CONFIG_AV1_HIGHBITDEPTH 1\n"
            "#define CONFIG_AV1_ENCODER 1\n#define CONFIG_AV1_DECODER 1\n"
            "#define CONFIG_REALTIME_ONLY 0\n#define CONFIG_MAX_DECODE_PROFILE 2\n"
            "#define HAVE_NEON 1\n#define AOM_ARCH_AARCH64 1\n"
            "#define INLINE inline\n#endif\n",
            encoding="utf-8",
        )

        def write_functions(destination: Path, source: str, record: dict, names: list[str]):
            # Preserve the upstream license notice in each derived excerpt.
            notice = source[:source.index("*/") + 2] + "\n\n"
            sections = [notice]
            for name in names:
                body, line = _function(source, name)
                sections.append(f'#line {line} "{record["path"]}@{record["commit"]}"\n' + body)
                extraction.append({
                    "name": name,
                    "commit": record["commit"],
                    "source_path": record["path"],
                    "source_line": line,
                    "function_sha256": hashlib.sha256(body.encode()).hexdigest(),
                    "destination": _relative(destination, output),
                })
            destination.write_text("\n".join(sections), encoding="utf-8")

        write_functions(build / "c_kernels.inc", base_source, base, [name + "_c" for name in KERNEL_NAMES])
        write_functions(build / "neon_kernels.inc", neon_source, neon, [name + "_neon" for name in KERNEL_NAMES])
        harness_path = context.resource("aom_intrabc_facade.cpp")
        harness = build / "aom_intrabc_facade.cpp"
        shutil.copyfile(harness_path, harness)
        _write_json(output / "build-contract.json", {
            "configuration": _relative(config, output),
            "configuration_sha256": hashlib.sha256(config.read_bytes()).hexdigest(),
            "headers": sorted(seen_headers),
            "dispatch_installation": "explicit function pointers; not generated RTCD initialization",
            "non_intrabc_paths": "fail-fast stubs",
            "source_padding_pixels_per_row": [16] if context.profile == "smoke" else [16, 23, 30],
            "seed": 20261118,
            "expected_coverage": PROFILE_EXPECTATIONS[context.profile],
            "input_digest": "FNV-1a 64-bit over all allocated source uint16 values in little-endian byte order; not a cryptographic hash",
            "independent_reference": "X/Y: (a+b+1)>>1; 2D: (a+b+c+d+2)>>2",
        })
        context.command(compiler + ["--version"], "compiler-version", timeout=30)
        variant_records = {}
        for variant, source, record in (("before", base_source, base), ("fixed", fixed_source, fixed)):
            variant_dir = build / variant
            variant_dir.mkdir(exist_ok=True)
            write_functions(variant_dir / "facade.inc", source, record, [FACADE_NAME])
            binary = variant_dir / "facade-check"
            context.command(
                compiler + architecture_flags + ["-std=c++17", "-O1", "-g", "-fno-omit-frame-pointer",
                    "-fsanitize=address,undefined", "-fno-sanitize-recover=all", "-I", str(include), "-I", str(variant_dir),
                    "-I", str(build), str(harness), "-o", str(binary)],
                f"compile-{variant}", timeout=120,
            )
            targets = ["neon"] if variant == "before" else ["neon", "c"]
            for installed in targets:
                label = f"run-{variant}-{installed}"
                completed = context.command(
                    [str(binary), context.profile, installed], label,
                    env={**os.environ, "ASAN_OPTIONS": "detect_leaks=0:halt_on_error=1", "UBSAN_OPTIONS": "halt_on_error=1"},
                    timeout=120, check=False,
                )
                raw = completed.stdout.decode("utf-8") if isinstance(completed.stdout, bytes) else completed.stdout
                stderr = completed.stderr.decode("utf-8", errors="replace") if isinstance(completed.stderr, bytes) else completed.stderr
                try:
                    result = json.loads(raw)
                except (ValueError, TypeError) as error:
                    observations.append({
                        "id": f"aom-intrabc-{variant}-{installed}-execution", "variant": f"{variant}-{installed}",
                        "check": "baseline", "result": "error", "evidence": [f"{label}.stdout", f"{label}.stderr"],
                        "details": f"The rebuilt harness exited with code {completed.returncode} and did not provide valid metrics: {error}.",
                    })
                    _write_json(output / "extraction-manifest.json", extraction)
                    return {"status": "unexpected_result", "observations": observations, "limits": limits}
                metric_errors = _validate_metrics(result, context.profile, installed)
                if completed.returncode != 0:
                    metric_errors.append(f"harness exited with nonzero code {completed.returncode}")
                if stderr.strip():
                    metric_errors.append("harness emitted stderr diagnostics; inspect the retained stderr")
                if not isinstance(result, dict):
                    result = {"raw_metrics": result}
                result["returncode"] = completed.returncode
                result["facade_commit"] = record["commit"]
                result["metric_validation_errors"] = metric_errors
                evidence = output / f"{label}.json"
                _write_json(evidence, result)
                if metric_errors:
                    observations.append({
                        "id": f"aom-intrabc-{variant}-{installed}-execution", "variant": f"{variant}-{installed}",
                        "check": "baseline", "result": "error", "evidence": [_relative(evidence, output), f"{label}.stdout", f"{label}.stderr"],
                        "details": "The rebuilt harness did not satisfy the fixed execution/coverage contract: " + "; ".join(metric_errors),
                    })
                    _write_json(output / "extraction-manifest.json", extraction)
                    return {"status": "unexpected_result", "observations": observations, "limits": limits}
                variant_records[(variant, installed)] = result
                numeric_failures = sum(result[key] for key in (
                    "pixel_mismatches", "c_formula_mismatches", "c_differential_mismatches"))
                observations.append({
                    "id": f"aom-intrabc-{variant}-{installed}-values",
                    "variant": f"{variant}-{installed}", "check": "numeric",
                    "result": "no_failure" if numeric_failures == 0 else "error",
                    "count": 3 * result["pixels_checked"], "unit": "pixel comparisons",
                    "mismatches": numeric_failures,
                    "scenarios": result["scenarios"],
                    "counts": {key: result[key] for key in ("pixel_mismatches", "c_formula_mismatches", "c_differential_mismatches")},
                    "evidence": [_relative(evidence, output), f"{label}.stdout", f"{label}.stderr"],
                    "details": ("Rebuilt extracted facade output checked against both a direct C-kernel reference and independent pixel formulas; whole destination guards and source preservation checked. "
                                + ("The fixed facade calls the actual upstream NEON kernel bodies." if variant == "fixed" and installed == "neon"
                                   else "This variant's facade calls the actual upstream C kernel bodies.")),
                })
                observations.extend([
                    {"id": f"aom-intrabc-{variant}-{installed}-guards", "variant": f"{variant}-{installed}",
                     "check": "baseline", "result": "no_failure" if result["guard_mismatches"] == 0 else "error",
                     "count": result["guard_cells_checked"], "unit": "guard-cell comparisons",
                     "mismatches": result["guard_mismatches"], "evidence": [_relative(evidence, output)],
                     "details": "Both facade and direct C reference preserve all destination cells outside the requested rectangle."},
                    {"id": f"aom-intrabc-{variant}-{installed}-source", "variant": f"{variant}-{installed}",
                     "check": "baseline", "result": "no_failure" if result["source_mismatches"] == 0 else "error",
                     "count": result["scenarios"], "unit": "source-preservation comparisons",
                     "mismatches": result["source_mismatches"], "evidence": [_relative(evidence, output)],
                     "details": "The complete source allocation, including vector padding, matches its pre-call snapshot after every facade/reference scenario."},
                ])

        _write_json(output / "extraction-manifest.json", extraction)
        before = variant_records[("before", "neon")]
        fixed_neon = variant_records[("fixed", "neon")]
        fallback = variant_records[("fixed", "c")]
        per_direction = PROFILE_EXPECTATIONS[context.profile]["scenarios"] // 3
        expected_calls = [per_direction] * 3
        zero_calls = [0, 0, 0]
        missing_dispatch = (before["dispatch_calls"] == zero_calls and before["neon_calls"] == zero_calls
                            and before["c_calls"] == expected_calls)
        fixed_dispatch = (fixed_neon["dispatch_calls"] == expected_calls
                          and fixed_neon["neon_calls"] == expected_calls
                          and fixed_neon["c_calls"] == zero_calls)
        fallback_dispatch = (fallback["dispatch_calls"] == expected_calls
                             and fallback["neon_calls"] == zero_calls
                             and fallback["c_calls"] == expected_calls)
        paired = (len({record["input_digest_fnv1a64"] for record in variant_records.values()}) == 1
                  and len({record["output_digest_fnv1a64"] for record in variant_records.values()}) == 1)
        observations.extend([
            {"id": "aom-intrabc-before-route", "variant": "before-neon", "check": "dispatch",
             "result": "detected" if missing_dispatch else "error", "count": sum(before["neon_calls"]),
             "expected_calls_per_direction": expected_calls,
             "unit": "NEON kernel calls", "evidence": ["run-before-neon.json", "registration-excerpt.txt"],
             "details": "All outputs agree with the formulas, while the extracted historical facade bypasses the explicitly installed NEON dispatch pointers and calls C directly."},
            {"id": "aom-intrabc-fixed-route", "variant": "fixed-neon", "check": "dispatch",
             "result": "no_failure" if fixed_dispatch else "error", "count": sum(fixed_neon["neon_calls"]),
             "expected_calls_per_direction": expected_calls,
             "unit": "NEON kernel calls", "evidence": ["run-fixed-neon.json"],
             "details": "The extracted fixed facade reaches each explicitly installed NEON pointer for its legal nonzero phase. This is local facade execution, not CPU detection or end-to-end codec execution."},
            {"id": "aom-intrabc-fixed-c-fallback", "variant": "fixed-c", "check": "dispatch",
             "result": "no_failure" if fallback_dispatch else "error", "count": sum(fallback["c_calls"]),
             "expected_calls_per_direction": expected_calls,
             "unit": "C kernel calls", "evidence": ["run-fixed-c.json"],
             "details": "Installing C in all dispatch slots preserves the same outputs and exercises the fixed facade's portable fallback route."},
            {"id": "aom-intrabc-paired-inputs", "variant": "before-and-fixed", "check": "baseline",
             "count": PROFILE_EXPECTATIONS[context.profile]["scenarios"], "unit": "matched facade scenarios per variant",
             "result": "no_failure" if paired else "error", "evidence": ["run-before-neon.json", "run-fixed-neon.json", "run-fixed-c.json"],
             "details": "All variants receive the same deterministic source buffers and produce equal output digests; these digests are consistency checks, not cryptographic provenance."},
        ])
        passed = missing_dispatch and fixed_dispatch and fallback_dispatch and paired and all(
            observation["result"] in {"detected", "no_failure"} for observation in observations)
        return {"status": "validated" if passed else "unexpected_result", "observations": observations, "limits": limits}
    except (OSError, ValueError, KeyError, subprocess.SubprocessError) as error:
        (output / "adapter-error.txt").write_text(f"{type(error).__name__}: {error}\n", encoding="utf-8")
        return {"status": "infrastructure_error", "observations": observations + [{
            "id": "aom-intrabc-execution", "variant": "infrastructure", "check": "baseline", "result": "error",
            "evidence": ["adapter-error.txt"], "details": "The live rebuild or execution did not complete; no historical result was substituted."}], "limits": limits}
