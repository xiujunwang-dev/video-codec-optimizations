Codec SIMD Validation
=====================

Codec SIMD Validation is a command-line toolkit for checking numeric results,
phase-specific buffer state and local dispatch routes in video-codec SIMD
implementations. Version 0.1.0 contains three source-pinned historical cases
from x265, SVT-AV1 and AOM. Each run rebuilds its harnesses and codec excerpts;
archived results are not substituted for new execution.

Installation
------------

The runtime requires Python 3.10 or later and has no third-party Python runtime
dependencies. Install the included wheel with::

    python3 -m pip install dist/codec_simd_validation-0.1.0-py3-none-any.whl

The experiments require Clang with C99/C++17 support and native AArch64 NEON
execution. x265 and AOM cases also use AddressSanitizer and
UndefinedBehaviorSanitizer. The recorded benchmark used macOS ARM64 and Apple
Clang 21. Other host and compiler combinations require separate validation.

Reproduction
------------

The case-source archive includes the fixed source snapshots and applicable
upstream licenses. It allows the experiments to be rebuilt without codec
checkouts::

    codec-simd-validate run --case all --profile full \
        --source-archive dist/case-sources-0.1.0.zip --out output/full-run
    codec-simd-validate verify output/full-run
    codec-simd-validate report output/full-run

Run a shorter check by selecting ``--profile smoke``. Cases can also be
selected individually with ``--case x265``, ``--case svt`` or ``--case aom``.
An existing output directory is never overwritten. The archive loader checks
entry names, file types, content hashes, Git blob identifiers and size limits
before the build starts.

The archive manifest uses neutral ``upstream/<case>`` repository aliases.
Source contents, blob identifiers, commits, paths and hashes are unchanged
from the locally tested archive. The alias removes machine-specific checkout
paths; commit membership remains a claim unless checked against the original
Git objects. The evaluated portable run used the original archive, whose
SHA-256 is retained in its run manifest.

Running from Git checkouts instead is also supported. See
``docs/cases.rst`` for the required revisions and ``docs/adapter-guide.rst``
for workspace options. No network fetch is performed automatically.

Cases
-----

``x265`` compares 10- and 12-bit energy reduction and final psy cost with a
64-bit Walsh-Hadamard reference. Intermediate source and reconstruction
energies are reported separately because their errors can cancel in the final
difference.

``svt`` checks the high-bit-depth scaled compound predictor across its first
and second calls. Full-buffer comparisons and initialized sentinels detect
numeric differences and unintended writes. All arrays are initialized; this
case does not diagnose uninitialized reads.

``aom`` checks the high-bit-depth IntraBC facade for selected non-compound
half-pel phases. It compares independent formulas and C results and counts the
locally installed C, NEON and dispatch calls. Pointers are installed directly;
the case does not exercise CPU feature detection, generated runtime dispatch
or whole-encoder execution.

All included cases are historical replays selected after the issues and fixes
were known. They are examples and a reproducible benchmark, not a prospective
test of unseen defects or their prevalence. Their workloads differ and are
not pooled as an equal-budget detector comparison. Harness timing includes
reference calculations and checks; it is not encoder throughput.

Evidence
--------

``evidence/benchmark/benchmark-runs-20261118.zip`` contains the original
full-profile Git-source run, the installed-wheel portable reconstruction and
the observation comparison. The 758 retained files were copied byte for byte
from the local records and checked against their source trees. The comparison
reports 229 matching observations and the preserved source identities. Both
runs followed tool integration changes and used the same host; this is not
independent replication with identical tool sources.

Verify the files against ``SHA256SUMS`` from this directory with::

    shasum -a 256 -c SHA256SUMS

Extract the benchmark archive at this directory's root to access its recorded
run paths and audit report. The separate ``evidence/pr-validation/`` directory
contains selected records from earlier patch testing, with checksums and scope
notes. Those records are not reruns of this toolkit.

Evaluation design, case revisions and result interpretation are documented in
``docs/evaluation.rst`` and ``docs/cases.rst``. The adapters do not establish
whole-codec correctness, production invocation frequency or encoder-speed
effects.

Licensing
---------

The toolkit and original harness code are distributed under the BSD 2-Clause
license in ``LICENSE``. Production excerpts, upstream headers and retained
licenses preserve their applicable upstream terms. In particular, the x265
excerpt and experiment binary remain subject to x265's GPL terms. The included
wheel contains the tool and harnesses; it does not bundle upstream production
sources or compiled experiments.
