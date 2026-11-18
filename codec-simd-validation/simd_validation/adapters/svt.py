"""Replay the historical high bit-depth scaled compound predictor regression."""

from __future__ import annotations

import hashlib
import json
import platform
import shutil
import subprocess
from pathlib import Path


CASE = "svt-highbd-first-compound-predictor"
BEFORE = "e81d772d289854a4a548ae147614f728124436aa"
FIXED = "73a06389f981722c620e26cd270ad4e98f2b4459"
NEON_SOURCE = "Source/Lib/ASM_NEON/highbd_convolve_scale_neon.c"
REFERENCE_SOURCE = "Source/Lib/Codec/inter_prediction.c"
INCLUDE_DIRS = (
    "Source/API",
    "Source/Lib/Codec",
    "Source/Lib/Globals",
    "Source/Lib/ASM_NEON",
    "third_party/aom_dsp/inc",
    "third_party/fastfeat",
)
FILTER_TABLES = (
    "sub_pel_filters_8",
    "sub_pel_filters_4",
    "sub_pel_filters_8sharp",
    "sub_pel_filters_8smooth",
    "bilinear_filters",
    "sub_pel_filters_4smooth",
)
HEADERS = (
    "Source/API/EbConfigMacros.h", "Source/API/EbDebugMacros.h", "Source/API/EbSvtAv1.h",
    "Source/API/EbSvtAv1Enc.h", "Source/API/EbSvtAv1Formats.h",
    "Source/Lib/ASM_NEON/compound_convolve_neon.h", "Source/Lib/ASM_NEON/convolve_scale_neon.h",
    "Source/Lib/ASM_NEON/highbd_convolve_scale_neon.h", "Source/Lib/ASM_NEON/mem_neon.h",
    "Source/Lib/ASM_NEON/transpose_neon.h", "Source/Lib/Codec/av1_structs.h",
    "Source/Lib/Codec/block_structures.h", "Source/Lib/Codec/cabac_context_model.h",
    "Source/Lib/Codec/common_dsp_rtcd.h", "Source/Lib/Codec/common_utils.h",
    "Source/Lib/Codec/convolve.h", "Source/Lib/Codec/definitions.h", "Source/Lib/Codec/filter.h",
    "Source/Lib/Codec/inter_prediction.h", "Source/Lib/Codec/mv.h", "Source/Lib/Codec/object.h",
    "Source/Lib/Codec/pic_buffer_desc.h", "Source/Lib/Codec/segmentation_params.h",
    "Source/Lib/Codec/svt_malloc.h", "Source/Lib/Codec/utility.h",
)


def _extract_function(source: str, name: str) -> str:
    start = source.index("void " + name + "(")
    opening = source.index("{", start)
    depth, end = 1, opening + 1
    while depth:
        depth += (source[end] == "{") - (source[end] == "}")
        end += 1
    return source[start:end]


def _extract_reference(source: str) -> str:
    chunks = [source[: source.index("#include")], '#include "convolve.h"\n']
    for name in FILTER_TABLES:
        start = source.index("DECLARE_ALIGNED(256, const InterpKernel, " + name + "[")
        chunks.append(source[start : source.index(";", start) + 1])
    chunks.append(_extract_function(source, "svt_av1_highbd_convolve_2d_scale_c"))
    return "\n\n".join(chunks) + "\n"


def _write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _observation(identifier, variant, check, result, evidence, details, **extra):
    return dict(id=identifier, variant=variant, check=check, result=result,
                evidence=evidence, details=details, **extra)


def _unsupported(reason: str, evidence=None) -> dict:
    return {
        "status": "unsupported",
        "observations": [_observation("svt-platform", "all", "baseline", "unsupported", evidence or [], reason)],
        "limits": [reason],
    }


def run(context) -> dict:
    """Build both pinned production implementations and compare stage state."""
    workspace, output = Path(context.workspace), Path(context.output)
    output.mkdir(parents=True, exist_ok=True)
    options = context.options
    repo = Path(options.get("svt_repo", workspace / "SVT-AV1-neon-compound-review"))
    if not repo.is_absolute():
        repo = workspace / repo
    if platform.system() != "Darwin" and platform.machine().lower() not in ("arm64", "aarch64"):
        return _unsupported("The pinned NEON production implementation requires a native AArch64 host.")
    cc_option = str(options.get("cc", "clang" if platform.system() == "Darwin" else "cc"))
    cc = shutil.which(cc_option)
    if cc is None:
        return _unsupported("A C compiler is required: " + cc_option)
    if getattr(context, "source_archive", None) is None and (shutil.which("git") is None or not (repo / ".git").exists()):
        return _unsupported("The pinned SVT Git checkout is unavailable: " + str(repo))
    profile = context.profile
    if profile not in ("smoke", "full"):
        raise ValueError("SVT profile must be smoke or full")

    observations, source_records = [], []
    limits = [
        "This is a retrospective replay of one known production regression, not a prospective discovery.",
        "The C implementation is a differential reference; it is not an independent arithmetic proof.",
        "Sentinel checks detect unintended writes and persistent-state changes. They do not detect reads from uninitialized storage.",
        "These are direct primitive calls. No bitstream corruption, production-call frequency, or encoder speed claim follows.",
        "The non-compound baseline and compound pairs perform different work; their pass/fail results are not an equal-budget comparison.",
    ]
    arch = ["-arch", "arm64"] if platform.system() == "Darwin" else []
    flags = [*arch, "-DARCH_AARCH64=1", "-O2", "-g", "-std=c99", "-Wall", "-Wextra"]
    raw = output / "sources"
    raw.mkdir(exist_ok=True)
    harness_path = context.resource("svt_compound.c")
    try:
        context.command([cc, "--version"], "svt-compiler")
        probe = output / "svt-platform.c"
        probe.write_text("#include <arm_neon.h>\nint main(void) {\n"
                         "  uint16x8_t v = vdupq_n_u16(17);\n"
                         "  return vgetq_lane_u16(v, 0) != 17;\n}\n", encoding="utf-8")
        probe_binary = output / "svt-platform"
        compiled = context.command([cc, *arch, str(probe), "-o", str(probe_binary)],
                                   "svt-platform-build", check=False, timeout=30)
        if compiled.returncode != 0:
            return _unsupported("The compiler cannot build a native AArch64 NEON executable.",
                                ["svt-platform-build.stdout", "svt-platform-build.stderr"])
        try:
            executed = context.command([str(probe_binary)], "svt-platform-run", check=False, timeout=30)
        except OSError as error:
            return _unsupported("The host cannot execute the AArch64 probe: " + str(error),
                                ["svt-platform-build.stdout", "svt-platform-build.stderr"])
        if executed.returncode != 0:
            return _unsupported("The AArch64 executable probe did not complete successfully.",
                                ["svt-platform-run.stdout", "svt-platform-run.stderr"])
        for variant, revision in (("before", BEFORE), ("fixed", FIXED)):
            destination = raw / (variant + "-highbd_convolve_scale_neon.c")
            source_records.append(context.record_source(repo, revision, NEON_SOURCE, destination=destination))
        reference_raw = raw / "inter_prediction.c"
        source_records.append(context.record_source(repo, FIXED, REFERENCE_SOURCE, destination=reference_raw))
        for path in ("LICENSE.md", "LICENSE-BSD2.md", "PATENTS.md"):
            source_records.append(context.record_source(repo, FIXED, path, destination=raw / path))
        reference = raw / "scale_reference.c"
        reference.write_text(_extract_reference(reference_raw.read_text()), encoding="utf-8")
        harness = raw / "svt_compound.c"
        harness.write_bytes(harness_path.read_bytes())
        generated = {
            "reference": {
                "path": str(reference.relative_to(output)),
                "sha256": hashlib.sha256(reference.read_bytes()).hexdigest(),
                "method": "Verbatim filter tables and one C function extracted from the pinned source.",
            },
            "harness": {
                "path": str(harness.relative_to(output)),
                "sha256": hashlib.sha256(harness.read_bytes()).hexdigest(),
            },
        }
        _write_json(output / "generated-sources.json", generated)

        # The dependency closure is frozen with this historical case. Both
        # dependency selection and final compilation are independent of checkout contents.
        include_root = raw / "include"
        for path in HEADERS:
            destination = include_root / path
            destination.parent.mkdir(parents=True, exist_ok=True)
            source_records.append(context.record_source(repo, FIXED, path, destination=destination))
        _write_json(output / "svt-sources.json", source_records)
        includes = [item for directory in INCLUDE_DIRS for item in ("-I", str(include_root / directory))]

        objects = []
        for name, src in (("reference", reference), ("harness", harness)):
            obj = output / (name + ".o")
            context.command([cc, *flags, *includes, "-c", str(src), "-o", str(obj)], "svt-build-" + name)
            objects.append(obj)

        metrics = {}
        for variant in ("before", "fixed"):
            obj = output / (variant + ".o")
            context.command([cc, *flags, *includes, "-c", str(raw / (variant + "-highbd_convolve_scale_neon.c")),
                             "-o", str(obj)], "svt-build-" + variant)
            binary = output / ("svt-compound-" + variant)
            context.command([cc, *arch, *(str(path) for path in objects), str(obj), "-o", str(binary)],
                            "svt-link-" + variant)
            result = context.command([str(binary), profile], "svt-run-" + variant, timeout=240)
            text = result.stdout.decode() if isinstance(result.stdout, bytes) else result.stdout
            metrics[variant] = json.loads(text)
            _write_json(output / (variant + "-metrics.json"), metrics[variant])
        before, fixed = metrics["before"], metrics["fixed"]
        expected_pairs = 3888 if profile == "smoke" else 52488
        for data in metrics.values():
            for name, value in data.items():
                if name.endswith(("_cases", "_cells")) or name == "pairs":
                    if type(value) is not int or value < 0:
                        raise ValueError("Invalid SVT counter: " + name)
                    if name.endswith("_cases") and name != "baseline_cases" and value > expected_pairs:
                        raise ValueError("SVT case counter exceeds its declared budget: " + name)
            if data["profile"] != profile or data["baseline_cases"] != expected_pairs // 9:
                raise ValueError("SVT profile or baseline count differs from the declared experiment")
        counts_valid = all(data["pairs"] == expected_pairs for data in metrics.values())
        paired = before["input_digest_fnv1a64"] == fixed["input_digest_fnv1a64"]
        observations.append(_observation(
            "svt-paired-inputs", "both", "baseline", "no_failure" if paired and counts_valid else "error",
            ["before-metrics.json", "fixed-metrics.json", "generated-sources.json"],
            "Both binaries receive the same deterministic source pixels, legal filter/scale parameters, and initialized buffers.",
            count=expected_pairs, unit="two-predictor pairs per version", matched_input_digest=paired))
        numeric_keys = ("first_compound_mismatch_cases", "second_dst_mismatch_cases",
                        "second_compound_mismatch_cases", "baseline_mismatch_cases")
        persistent_keys = ("c_first_changed_cases", "c_persistent_changed_cases",
                           "neon_persistent_changed_cases", "padding_changed_cases")
        expected = paired and counts_valid
        for variant, data in metrics.items():
            evidence = [variant + "-metrics.json", "svt-run-" + variant + ".stdout",
                        "svt-run-" + variant + ".stderr", "svt-sources.json"]
            phase_failures = data["first_dst_mismatch_cases"]
            observations.append(_observation(
                "svt-first-predictor-dst", variant, "phase_state",
                "detected" if phase_failures else "no_failure", evidence,
                "The first compound predictor must preserve the complete pixel output buffer initialized to 0xffff; only the compound predictor buffer is writable.",
                count=data["pairs"], unit="predictor pairs", mismatches=phase_failures,
                mismatched_cells=data["first_dst_mismatch_cells"], witness=data["first_dst_witness"]))
            numeric_failures = sum(data[key] for key in numeric_keys)
            observations.append(_observation(
                "svt-predictor-values", variant, "numeric",
                "detected" if numeric_failures else "no_failure", evidence,
                "Complete-buffer C/NEON comparisons after each predictor: compound state after first, pixel output and compound state after second; separate non-compound baseline included.",
                count=3 * data["pairs"] + data["baseline_cases"], unit="full-buffer comparisons", mismatches=numeric_failures,
                counts={key: data[key] for key in numeric_keys}))
            state_failures = sum(data[key] for key in persistent_keys)
            observations.append(_observation(
                "svt-persistent-state", variant, "phase_state",
                "detected" if state_failures else "no_failure", evidence,
                "The C first predictor preserves pixel output; the second predictor preserves stored compound state; both calls preserve padding outside the legal output rectangle.",
                count=4 * data["pairs"], unit="state predicates", mismatches=state_failures,
                counts={key: data[key] for key in persistent_keys}))
            expected &= numeric_failures == 0 and state_failures == 0
        expected &= before["first_dst_mismatch_cases"] == expected_pairs and fixed["first_dst_mismatch_cases"] == 0
        return {"status": "validated" if expected else "unexpected_result",
                "observations": observations, "limits": limits,
                "metrics": metrics, "profile": profile,
                "historical": True, "fixed_revision": FIXED, "before_revision": BEFORE}
    except (FileNotFoundError, subprocess.CalledProcessError, subprocess.TimeoutExpired,
            ValueError, KeyError, IndexError, OSError) as error:
        observations.append(_observation(
            "svt-execution", "all", "baseline", "error", ["commands.json"],
            type(error).__name__ + ": " + str(error)))
        return {"status": "infrastructure_error", "observations": observations, "limits": limits}
