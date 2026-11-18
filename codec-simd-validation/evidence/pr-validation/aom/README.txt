Official Gerrit review upload (2026-11-17)

The three changes are now uploaded for review on main, with topic
intrabc-convolution-fixes. All are NEW and ready for review, patchset 1.

221681: https://aomedia-review.googlesource.com/c/aom/+/221681
  Fix IntraBC convolution benchmark parameters
221682: https://aomedia-review.googlesource.com/c/aom/+/221682
  Cover IntraBC convolution boundaries and rounding
221683: https://aomedia-review.googlesource.com/c/aom/+/221683
  Use runtime dispatch for high bit-depth IntraBC

Base: aac27b8f291ed449fac576bcce0ad0ca189be851 (latest main at upload)
Local series branch: intrabc-convolution-fixes
Series commits: 40c1ccb57b -> 1f54f29440 -> a583a61feb
Each commit has its own Change-Id. The three functional diffs are identical
to the original independent patches. The new series is chained for review.
Review-series patches and exact metadata are in gerrit-series/.

The latest main was rechecked for overlapping fixes before upload.
The exact uploaded HEAD passed 1269/1269 tests with ARM64 assertions,
ASAN, UBSAN and Werror, including all 486 disabled speed benchmarks.
Tests took 86.482 seconds; reports are logs/upload-tests.log and .xml.
The existing avif_optimization branch and uncommitted changes are preserved.

The following sections describe the original independent patches and the
initial audit baseline. Those original branches and exports are retained.

-----------------------------------------------------------------------

IntraBC convolution fixes and regression coverage

Baseline and delivery

Official repository: https://aomedia.googlesource.com/aom
Official review system: https://aomedia-review.googlesource.com
Checked on 2026-11-16. The default development branch is main.
main / HEAD: 12ad11ebd0c781c6b9fb95f4de1d821cbf7e7fc5
master: 402e264b94fd74bdf66837da216b6251805b4ae4 (2022; obsolete development branch)

All three commits have the same direct parent, 12ad11ebd0. Each exported
patch applies independently to that baseline. They also apply together
without conflicts, and the exported patches produce the exact source tree
used for the combined test run.

The three branches are saved in the original local repository. The active
avif_optimization branch and its existing uncommitted resize/scale changes
were preserved. The changes are local commits.

1. intrabc-benchmark-parameters
   Commit: e486d67f70b833a558f9efd059ddc5d48b04cb98
   Patch: patches/01-fix-intrabc-benchmark-parameters.patch

   Fix the X/Y half-pel phases, use the dedicated two-tap IntraBC filter in
   the high bit-depth Y/2D benchmarks, and initialize high bit-depth
   ConvolveParams with the actual bit depth. Compare C and optimized
   output after timing in all six benchmark fixtures.

2. intrabc-convolve-regression-coverage
   Commit: 40ccbb509cc1680d14745827bec7166fdb7f120b
   Patch: patches/02-cover-intrabc-boundaries-and-rounding.patch

   Add a separate common test for X/Y/2D primitives over the original 27
   sizes. Cover uint8 at 8 bits and uint16 at 8/10/12 bits. Exercise three
   stride/offset layouts, ten directed patterns and four deterministic
   random buffers. Compare both C and the selected implementation with
   independent pixel formulas. Check every output sample, including
   prefix/suffix guards and row padding, and verify source preservation.
   Poison active output pixels with the complement of the expected value
   so an omitted write cannot accidentally pass. Source padding permits
   the vector loads supported by the current implementations.

3. highbd-intrabc-runtime-dispatch
   Commit: 0b511df2f12439e7b1be7aa78783753e51077326
   Patch: patches/03-use-highbd-intrabc-runtime-dispatch.patch

   Replace three explicit high bit-depth C calls in the IntraBC facade
   with the registered RTCD entry points. Add a separate common facade
   test for (0,0), (8,0), (0,8), (8,8), 27 sizes and 8/10/12-bit buffers.
   Compare with C and mathematical references and check output guards and
   source preservation. The test also runs in decoder-only builds.

Validation

Host: Apple M1, ARM64. Assertions remain enabled for the sanitizer tests.

- Patch 1: 972/972 C and NEON cases pass, including all 486 benchmarks
  carrying DISABLED_ names, run with --gtest_also_run_disabled_tests.
  AddressSanitizer and UndefinedBehaviorSanitizer were enabled.
- Patch 2: 216/216 C and NEON cases pass with ASAN+UBSAN and Werror.
  These execute 27,216 scenarios and 54,432 primitive calls. Each scenario
  calls C once and its suite implementation once; these are not all NEON
  calls. Its new test also compiles on a generic target with high bit-depth
  support disabled.
- Patch 3: 81/81 ARM64 NEON cases and 81/81 generic C fallback cases pass
  with ASAN+UBSAN and Werror. Each run executes 648 facade calls. LLVM
  function counts confirm that each high bit-depth NEON IntraBC X/Y/2D
  kernel is reached 162 times by the facade-only test run. The generic
  build has HAVE_NEON=0 and all three entry points resolve to C.
- Combined patches: 1269/1269 cases from 17 suites pass with ASAN+UBSAN,
  Werror and assertions. This includes 972 existing cases, 216 new
  primitive cases and 81 new facade cases. The 486 disabled benchmarks
  were actually executed. failures=0 and errors=0 in the XML report.
- The new facade file also compiles with CONFIG_AV1_HIGHBITDEPTH=OFF.
- Formatting and git diff --check pass. Each exported patch passes
  git apply --check on the baseline; all three pass git am together.

RTCD also registers RVV, so patch 3 makes that implementation reachable
on supported RISC-V builds. RVV and 32-bit ARM were not executed here.
Generic fallback was tested on the ARM64 host. This validation covers the
convolution primitives and facade; it does not constitute a full codec
suite using external test data.

Combined test reproduction

Use a clean checkout of 12ad11ebd0, apply the three patches with git am,
and run the following (replace SOURCE and BUILD with absolute paths):

cmake -S SOURCE -B BUILD -G Ninja \
  -DAOM_TARGET_CPU=arm64 -DCMAKE_OSX_ARCHITECTURES=arm64 \
  -DCMAKE_BUILD_TYPE=Debug \
  '-DCMAKE_C_FLAGS_DEBUG=-O2 -g' '-DCMAKE_CXX_FLAGS_DEBUG=-O2 -g' \
  -DENABLE_TESTS=ON -DENABLE_TESTDATA=OFF -DENABLE_DOCS=OFF \
  -DENABLE_EXAMPLES=OFF -DENABLE_TOOLS=OFF \
  -DCONFIG_AV1_ENCODER=ON -DSANITIZE=address,undefined -DENABLE_WERROR=ON
cmake --build BUILD --target test_libaom -j4
UBSAN_OPTIONS=halt_on_error=1 BUILD/test_libaom \
  --gtest_also_run_disabled_tests \
  '--gtest_filter=C/*IntraBCTest.*:NEON/*IntraBCTest.*:*IntraBCConvolve*:*AV1HighbdIntraBCFacadeTest.*'

For the generic facade fallback, use AOM_TARGET_CPU=generic and
CONFIG_AV1_ENCODER=OFF, then run '*AV1HighbdIntraBCFacadeTest.*'.
For only the new primitive tests, run '*IntraBCConvolve*'.

Official upstream comparison

The latest main still contains all three issues addressed here.
Related changes already in the baseline:

- 221421 / 12ad11ebd0: Optimize LBD/HBD IntraBC 2D convolve.
  Width-specialized NEON passes and compact intermediates; no benchmark,
  regression-fixture or high bit-depth facade dispatch changes.
  https://aomedia-review.googlesource.com/c/aom/+/221421
- 220901 / 1b7f9ef3dd: Avoid over-read in 4-wide IntraBC convolutions.
  Narrows low bit-depth NEON loads to avoid reads into a concurrently
  reconstructed region. It addresses a different problem.
  https://aomedia-review.googlesource.com/c/aom/+/220901
- 193501 / 226cedfc9b: Use IntraBC RTCD functions in the low bit-depth
  facade. The high bit-depth facade was not changed by that commit.
  https://aomedia-review.googlesource.com/c/aom/+/193501

Related open changes checked:

- 215301: ASAN output guard for ordinary AV1Convolve2DTest, not an IntraBC
  fixture or benchmark. Its identical guard is already in main through
  92094f8c5f, Convolve 2d: fix mismatch in hwy. This does not supply the
  IntraBC patterns, strides, row guards or bit-depth coverage in patch 2.
  https://aomedia-review.googlesource.com/c/aom/+/215301
- 208401: Small-block handling in ordinary high bit-depth RVV convolution;
  it does not alter the IntraBC kernels or high bit-depth IntraBC facade.
  https://aomedia-review.googlesource.com/c/aom/+/208401

Queries used IntraBC/highbd convolution terms and the relevant source/test
files. The open file query returned 12 records without further pagination.
Eight touched av1/common/convolve.c or test/av1_convolve_test.cc; their
current file diffs were read individually. None changed the high bit-depth
IntraBC dispatch or the six IntraBC benchmark parameter sets. The remaining
four records did not touch those two files. No equivalent fix for the three
issues was found in the inspected public changes. This is a scoped search
of current revisions, not a claim about every historical patchset or branch.
See upstream-review-evidence.json for query strings, counts and record IDs.

Logs and local timing

The logs directory contains the individual and combined test reports,
function counts, generic fallback result, high-bit-depth-disabled compile
result, exported-patch application check, and a local Release facade timing
comparison. The timing source, compile commands and CSV samples are included.
The facade timing uses the same Release compiler flags for both versions,
five alternating runs and per-case medians over 54 size/phase/bit-depth
combinations. All output checksums match. It measures only the facade and
its convolution kernel, and does not establish whole-codec speedup.
