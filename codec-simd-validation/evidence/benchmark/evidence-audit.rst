Evidence audit for the software manuscript
=========================================

Scope
-----

This note maps manuscript claims to the retained full-profile evidence. Paths
are relative to the project root. The principal run is
``output/release-portable-full-20261118/``; ``R`` below denotes that directory.
The comparison run is ``output/baseline-full-20261118/``. Both contain known
historical cases selected after their issue and fix were available. Neither is
a prospective discovery experiment.

The run verifier accepted all 207 retained files in R and all 549 retained files
in the comparison run. These inventory sizes differ because the portable run
does not need the original Git-read command logs. They are artifact counts,
not test coverage or detection counts. ``validated`` means that the replay
matched its registered expectation, including the expected failure of an old
revision; it does not mean that the old code was correct.

Environment and builds
----------------------

``R/manifest.json`` records Python 3.13.2, eight reported logical CPUs and
macOS 26.5.2. The controller process reports x86_64, whereas the recorded
``/usr/bin/arch -arm64 /usr/bin/uname -m`` probe reports arm64. The three
adapters explicitly build native arm64 binaries. The CPU model is not retained
in this run and should not be inferred from the logical CPU count.

Each adapter's compiler stdout records Apple clang 21.0.0
``clang-2100.1.1.101``, targeting ``arm64-apple-darwin25.5.0``. Exact arguments
are in the respective ``R/cases/<alias>/commands.json`` files.

* x265: C++17, ``-O2 -g``; ordinary and
  ``-fsanitize=address,undefined -fno-omit-frame-pointer`` builds.
* SVT-AV1: C99, ``-O2 -g -Wall -Wextra -DARCH_AARCH64=1``; ordinary builds
  only. The reference and harness are compiled separately and linked to each
  version of the NEON production file.
* AOM: C++17, ``-O1 -g -fno-omit-frame-pointer``,
  ``-fsanitize=address,undefined -fno-sanitize-recover=all``. A retained
  minimal configuration and fixed headers support the extracted facade and
  kernels; this is not a complete upstream library build.

The study exercises this one host/compiler combination. Neither cross-platform
support nor cross-compiler agreement follows from it. Adapter elapsed time
includes building, input preparation, reference calculations and checks; it is
not an encoder throughput measurement or an optimized-kernel speed comparison.

x265: exact denominators and numeric observations
------------------------------------------------

Primary evidence is ``R/cases/x265/x265-results.json`` under ``rows``. Select
``variant``, ``mode``, ``depth`` and ``group`` before summing. The following
table selects ``variant=before``, ``mode=normal`` and ``depth=12``. Numerators
come respectively from ``source_energy_mismatches``,
``recon_energy_mismatches`` and ``cost_mismatches``; the denominator is the
sum of ``cases``. Every entry counts input pairs, not independent causes.

.. list-table:: Twelve-bit historical version, ordinary build
   :header-rows: 1

   * - Input group
     - Pairs
     - Source energy errors
     - Reconstruction energy errors
     - Final cost errors
   * - uniform-independent
     - 12,288
     - 0
     - 0
     - 0
   * - endpoints-zero
     - 12,288
     - 4,042
     - 0
     - 4,042
   * - endpoints-near
     - 12,288
     - 4,042
     - 4,042
     - 0
   * - exhaustive-zero
     - 65,536
     - 21,504
     - 0
     - 21,504
   * - exhaustive-complement
     - 65,536
     - 21,504
     - 21,504
     - 23,296
   * - exhaustive-near
     - 65,536
     - 21,504
     - 21,504
     - 0

Each seeded group has three seeds, 1, 17 and 20261117, with 4,096 pairs per
seed. The endpoints-zero final-cost numerators are respectively 1,383, 1,323
and 1,336. The known witness is separate from these groups: one 12-bit pair
has expected cost 67,568 and observed cost 2,032. It must not be folded into
the random-input results.

``R/cases/x265/x265-manifest.json`` records two depths, three seeded groups
and three exhaustive reconstruction groups. Each version/build combination
contains 25 rows and 466,945 input pairs:
``1 + 2 * (3 * 3 * 4096 + 3 * 65536)``. There are four version/build
combinations, yielding 100 data rows. They are repeated observations of the
same input families, not four independent samples. Before/fixed and
normal/sanitized pairs have the same per-group counts and input fingerprints.

All ten-bit rows have zero errors. The sanitized historical rows have the
same numeric numerators as the ordinary historical rows; execution exits
successfully with empty diagnostics. Their numeric mismatches are reported by
the independent reference comparison, not by sanitizer diagnostics. Both
fixed-version builds have zero numeric discrepancies on all 466,945 pairs,
and all rows record zero input mutations and zero oracle disagreements.

The oracle uses an independent int64 Walsh butterfly, and a direct sign matrix
spot-checks the first min(32, cases) pairs in each group. This is not an
exhaustive proof that the reference is correct for the entire legal domain.
The complete input allocations are checked for changes. Input fingerprints
are FNV-1a consistency checks, not cryptographic provenance.

The defensible result is that particular input families and intermediate
checks reveal different aspects of this known numeric defect. The
0/12,288 versus 4,042/12,288 comparison has equal pair counts but intentionally
different input distributions. It does not estimate a general discovery rate
or establish superiority over existing test suites on unseen defects.

SVT-AV1: phase state and differential output
------------------------------------------

Primary evidence is ``R/cases/svt/before-metrics.json`` and
``fixed-metrics.json``, also embedded under ``metrics`` in ``result.json``.
Each compiled version executes 52,488 two-predictor scenarios and 5,832
non-compound controls. The full scenario budget is
``18 dimensions * 2 bit depths * 6 scale-step pairs * 3 vertical filters *
3 horizontal filters * 9 averaging settings * 3 phase settings``.
The controls cover only one of the nine averaging settings, so their workload
is not equal to that of the compound pairs.

The two predictors are each called through both C and NEON implementations.
Thus each version executes 110,808 calls to its NEON implementation and the
same number to C: ``2 * 52488 + 5832``. These are direct primitive invocations
within the harness, not a count of calls during encoding.

``first_dst_mismatch_cases`` is 52,488/52,488 before and 0/52,488 fixed.
``c_first_changed_cases`` is zero in both. This establishes that the C first
predictor preserves its destination sentinel while the historical NEON first
predictor changes it. The complete arrays are initialized; the first-stage
pixel buffer is initialized to 0xffff and the compound buffer to 0x5a5a.
The recorded first witness is ``[2, 2, 10, 512, 1024, 0, 0, 0, 0]`` for
width, height, bit depth, x/y scale steps, x/y filter and x/y phase.

For both versions, the following discrepancy counts are zero:

* ``first_compound_mismatch_cases``: 0/52,488 full-buffer comparisons.
* ``second_dst_mismatch_cases``: 0/52,488 full-buffer comparisons.
* ``second_compound_mismatch_cases``: 0/52,488 full-buffer comparisons.
* ``baseline_mismatch_cases``: 0/5,832 full-buffer comparisons.

Together these form 0/163,296 numeric full-buffer comparisons per version.
The separate state predicates ``c_first_changed_cases``,
``c_persistent_changed_cases``, ``neon_persistent_changed_cases`` and
``padding_changed_cases`` are all zero, totaling 0/209,952 predicates per
version. A padding predicate aggregates the relevant buffers and stages; it
must not be described as one compared memory cell.

The 127,359,216 ``first_dst_mismatch_cells`` in the historical version are
changed buffer cells accumulated across scenarios. They are useful supporting
detail, but an unsuitable headline result: they heavily weight large blocks
and repeatedly count the same underlying regression. A main table should
prefer the 52,488 affected scenarios with their denominator.

Both versions record input digest ``9e84739b1d11c70f``. The C implementation
is a differential reference, not an independent proof. Sentinel and snapshot
checks detect unintended writes or altered state; they do not diagnose
uninitialized reads. These results establish no bitstream corruption,
production-call frequency or encoder-speed effect.

AOM: pixel agreement and local route reachability
-------------------------------------------------

Primary evidence is ``R/cases/aom/run-before-neon.json``,
``run-fixed-neon.json`` and ``run-fixed-c.json``. Each contains 9,477 facade
scenarios:
``27 dimensions * 3 layouts * 3 bit depths * 13 patterns * 3 directions``.
Each direction therefore has 3,159 scenarios. Legal phases are (8,0), (0,8)
and (8,8); scaling, compound modes and the copy path are outside this case.

.. list-table:: Reached kernels for each facade variant
   :header-rows: 1

   * - Variant and installed slots
     - C calls by direction
     - NEON calls by direction
     - Dispatch-wrapper calls by direction
   * - Historical facade, NEON installed
     - [3159, 3159, 3159]
     - [0, 0, 0]
     - [0, 0, 0]
   * - Fixed facade, NEON installed
     - [0, 0, 0]
     - [3159, 3159, 3159]
     - [3159, 3159, 3159]
   * - Fixed facade, C installed
     - [3159, 3159, 3159]
     - [0, 0, 0]
     - [3159, 3159, 3159]

These are ``c_calls``, ``neon_calls`` and ``dispatch_calls`` respectively.
The explicitly called C differential reference is not included in the
facade-route C counters. In particular, ``dispatch_calls`` is not synonymous
with NEON calls, as the fixed-C control demonstrates.

Each variant's ``pixels_checked`` is 16,287,804 active pixel positions.
``pixel_mismatches``, ``c_formula_mismatches`` and
``c_differential_mismatches`` are all zero, each with that denominator.
The normalized result reports 48,863,412 pixel comparisons because it sums
these three checks on the same active positions. It must not be described as
48,863,412 independent pixels or scenarios. ``guard_cells_checked`` is
8,273,772, counting destination and C-reference guard comparisons together;
``guard_mismatches`` is zero. Whole-source snapshot discrepancies are
0/9,477 scenarios. All three variants share input digest
``7cb4f849381aba24`` and output digest ``1a3e9ee8b5619557``.

The independent expected values use ``(a+b+1)>>1`` for one-dimensional and
``(a+b+c+d+2)>>2`` for two-dimensional half-pel interpolation. The retained
complete facade and production kernel bodies are rebuilt, and unsupported
branches abort. The harness installs dispatch pointers explicitly. Its route
observations do not exercise CPU feature detection, generated RTCD
initialization or an encoder/decoder entry point. Legal source vector padding
is provided; output guards do not characterize all source reads. Zero numeric
errors with a missed local NEON route is supported, but end-to-end route
coverage and whole-codec speedup are not.

Portable rebuild and release evidence
-------------------------------------

``output/release-reproduction-audit-20261118.json`` records 209 matching
x265 observations, seven SVT observations and 13 AOM observations: 229
normalized observation records in total. This is a correspondence check,
not 229 tests, discoveries or independent defects. The audit compares
case/classification, observations, source identities, budget registration and
protocol data. It excludes elapsed time, absolute command paths and compiled
artifacts. All three portable cases record zero Git invocations and only
``portable_snapshot`` source modes.

The comparison is not between identical tool-source hashes. The audit records
two added files and five changed files for portable support, despite both
runs retaining the version string 0.1.0. Describe the result as a same-host
rebuild of retained source snapshots with matching observations, not as an
independent replication or a bit-for-bit rebuild of the same software.

There are 57 source references: eight x265, 31 SVT and 18 AOM. The portable
ZIP contains 53 unique content objects plus its manifest, with 1,669,364
uncompressed bytes including the manifest; its compressed size is 260,802
bytes. SHA-256 is
``41366462454ca17f1810edfaf5c922d0f81a897926b7b25554aa6ae00c3c7837``.
The archive validates retained bytes against SHA-256 and Git blob identities.
It cannot independently prove that a blob belongs to a claimed commit without
the original Git objects. The original Git-backed run retains that lookup
evidence. Local checksums provide neither a signature nor an external release
timestamp.

``dist/release-manifest-0.1.0.json`` records 24 passed and zero failed
automated software tests, matching distribution checks and all three
historical replays. The 24 tests concern software/evidence/archive behavior;
they are not additional codec defects. Distribution byte sizes and SHA-256
values, audit hash and both run-checksum hashes were independently compared
with the retained files during this manuscript audit and matched.

Claims to exclude from the present main results
----------------------------------------------

* A new defect count, prospective accuracy, real-world prevalence, or a claim
  that upstream suites necessarily miss all three cases. The cohort is
  retrospective, and no frozen prospective comparison has run.
* A combined rate formed by pooling x265 input pairs, SVT predicates, AOM
  pixels, and report rows. These units and work budgets differ.
* Generalized detector superiority based only on the selected known cases or
  p-values that treat repeated inputs/builds as independent causes.
* Encoder throughput, full-codec dispatch coverage, bitrate or quality
  effects. None of the retained runs measures those outcomes.
* Independent replication, multi-host portability or a published archival
  release. ``independent_replication_completed`` and
  ``prospective_evaluation_started`` are both false in the release manifest.

The strongest current software-paper claims are the reusable evidence and
rebuild workflow, three auditable historical demonstrations with distinct
numeric/state/route observations, and a same-host installed-package rebuild
from retained sources. Additional users, host/compiler combinations and a
stable archived release would strengthen the submission.
