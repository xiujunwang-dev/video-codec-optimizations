Prior pull-request validation records
====================================

This supplement retains selected records from the patch-validation work that
preceded the version 0.1.0 benchmark. The author reports that the related pull
requests were tested on different machines. The records included here document
the particular platforms, revisions and workloads described below; they are
not a complete inventory of every machine or test used during that work.

The thirteen original files were copied without content changes. Their SHA-256
hashes, byte sizes and original workspace-relative locations appear in
``source-manifest.json``. Absolute paths, author fields, upstream names and
other recorded details remain unchanged. A local path in a command describes
the original environment, rather than a portable command for a new checkout.
Files referenced inside an original summary are included only when listed in
the manifest. No binaries or complete build directories are part of this
supplement.

The checksums establish correspondence between retained bytes and the supplied
inventory. They do not independently authenticate the original environment,
identify an additional physical machine or prove the correctness of a test's
assumptions. To check the inventory from this directory, run::

    shasum -a 256 -c SHA256SUMS

x265 energy-reduction patch
---------------------------

``x265/VALIDATION.txt`` records Apple M1, ARM64, AppleClang 21, Release and
C++17. Its baseline is
``1836f70c17cde142ac023da71a96ba9cc49c9213``. It lists the historical fix
``45fbaeeba4b45215e1fc2595c57036f94bbbf573`` and branch tip
``0b28c58efdc235eb0904a9c593299e9ec9929973``. These records concern that
earlier patch history; they must not be relabelled as executions of the later
exact toolkit revision ``8e87b841b9374762a63af2a2e29246f701c1ccbd``.

The summary describes 196,608 enumerated source/reconstruction pairs per bit
depth, 44,800 historical NEON discrepancies at 12 bits, and agreement for the
corrected 8/10/12-bit implementations. It records TestBench validation of NEON
and NEON DotProd. SVE2 was compile-tested, not executed. ``validation.json``
retains commands and expected/actual exit codes. ``integration.json`` retains
the 21 C/NEON encoding comparisons. The original summary explicitly identifies
three remaining differences attributed to other functions; they are not
presented as resolved by this patch.

SVT-AV1 compound predictor
--------------------------

``svt/rebase-validation.txt`` identifies the updated commit
``73a06389f981722c620e26cd270ad4e98f2b4459`` on baseline
``e81d772d289854a4a548ae147614f728124436aa``. It records native ARM64 CMake
testing, focused NEON ASan/UBSan testing and an x86_64 SSE4.1 regression
control under Rosetta. The XML reports each record zero failures and errors:

* ``rebase-native-tests.xml``: 180 declared tests, 72 disabled, 108 enabled.
* ``rebase-sanitize-tests.xml``: 144 declared, 54 disabled, 90 enabled.
* ``rebase-sse-tests.xml``: 180 declared, 54 disabled, 126 enabled.

Rosetta is an execution mode on the ARM host, not evidence of a second physical
machine. The SSE4.1 control checks regression behavior; it does not execute
NEON instructions on x86. The included records do not identify every OS
release or compiler version used in the prior validation.

``svt/validation.txt`` describes the original matrix, reproduction commands,
temporary-buffer poisoning tests and encoding smoke checks. The separate
poisoning work belongs to the earlier patch validation. Version 0.1.0's
initialized-sentinel adapter checks writes and persistent state and must not
be described as detecting uninitialized reads on the basis of that earlier
experiment. The poison and encoding logs themselves are outside this small
supplement.

AOM IntraBC patch series
------------------------

``aom/gerrit-series/series.json`` pins the uploaded three-patch series from
``aac27b8f291ed449fac576bcce0ad0ca189be851`` to
``a583a61feb0d424959a1ff0cff5e298e31c98992``. ``aom/README.txt`` records
Apple M1 ARM64. ``aom/logs/upload-tests.xml`` records 1,269 tests with zero
failures and errors; the README states that all 486 normally disabled
benchmarks were executed with ASan, UBSan, Werror and assertions. The 1,269
tests cover all three patches, rather than the dispatch patch alone.

The README also describes the original individual dispatch-patch validation:
81 ARM64 NEON cases and 81 generic C fallback cases, with 648 facade calls in
each run. ``aom/logs/dispatch-route-counts.txt`` records 648 facade calls and
162 calls to each high-bit-depth X/Y/2D NEON kernel. These function counts
belong to the earlier individual-patch test. The generic configuration log
identifies AppleClang 21.0.0.21000101. Generic fallback ran on the ARM64 host;
it does not establish a second host or execution on RISC-V. RVV and 32-bit ARM
are expressly recorded as unexecuted.

These older tests exercise production-library primitive and facade integration
with different scopes from the current extracted-facade benchmark. In
particular, their production dispatch evidence must not be transferred to the
current adapter, which explicitly installs local function pointers and does
not execute generated runtime-dispatch initialization or CPU detection.

Relation to the software benchmark
-----------------------------------

The patch records supply supporting regression, integration and platform
history. Their test counts, bit-depth domains, revisions and instrumentation
remain separate from the packaged benchmark's input-pair, state-predicate and
local-route observations. They are neither additional new defects nor reruns
of the version 0.1.0 full profile.

The installed-package and portable-source results in the manuscript use one
recorded host/compiler combination. This selected prior-patch supplement does
not contain an external-machine execution of that workflow. That limitation
concerns the toolkit-run records and does not negate the author's report of
multi-machine testing of the underlying patches.
