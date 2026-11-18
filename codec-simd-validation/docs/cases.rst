Historical case definitions
===========================

x265 energy reduction
---------------------

Before: ``1836f70c17cde142ac023da71a96ba9cc49c9213``.
Fixed: ``8e87b841b9374762a63af2a2e29246f701c1ccbd``.
The production file SHA-256 is pinned in the adapter as well as recording its
Git blob. The function and original helpers are extracted, then compiled
without changing their arithmetic. An independent int64 butterfly supplies
the reference, spot-checked with a direct Walsh sign matrix.

Both profiles include one separate known witness; 10/12-bit inputs; seeds
1, 17 and 20261117; uniform-independent, endpoints-zero and endpoints-near
groups; exhaustive zero/complement/near reconstruction patterns; strides
4, 7 and 16; and offsets 0, 1 and 3. Smoke uses 128 inputs per seeded group
and the first 512 enumerated source masks. Full uses 4096 and all 65536 masks.
Both versions run normally and under ASan/UBSan, with identical input hashes.
The historical no-argument C++ harness stream remains compatible with the
original full replay.

SVT compound predictor
----------------------

Before: ``e81d772d289854a4a548ae147614f728124436aa``.
Fixed: ``73a06389f981722c620e26cd270ad4e98f2b4459``.
The full NEON production file, C reference function and filter tables are
retained with fixed-revision headers. The fixed dependency closure is explicit
in the adapter and does not discover headers from a modified checkout.

Smoke has 3888 two-predictor pairs per version and 432 non-compound controls.
Full has 52488 pairs per version and 5832 controls. Legal initialized arrays
exercise 10/12-bit values, filter pairs, nontrivial strides, scale steps,
endpoint/random phases and nine averaging settings. A complete first-stage
pixel buffer initialized to 0xffff must remain unchanged. Compound-state
values, second-stage values, stored-state preservation and padding are checked
separately. This adapter currently runs an ordinary optimized build.

AOM IntraBC facade
------------------

Before: ``aac27b8f291ed449fac576bcce0ad0ca189be851``.
Fixed: ``a583a61feb0d424959a1ff0cff5e298e31c98992``.
The facade is the complete extracted upstream function; C/NEON kernel bodies
are verified unchanged across these two versions. Headers are fixed copies
and the small generated configuration is recorded. Other codec paths abort if
reached instead of supplying substitute arithmetic.

Smoke has 270 scenarios per variant; full has 9477. Before-with-NEON-installed,
fixed-with-NEON-installed, and fixed-with-C-installed receive identical inputs.
Three directions cover legal half-pel phases (8,0), (0,8) and (8,8), unscaled
and non-compound, at 8/10/12-bit storage. Independent formulas are
``(a+b+1)>>1`` and ``(a+b+c+d+2)>>2``. Full includes 27 dimensions, three
layouts and 13 patterns. Source padding is part of the legal contract.

Checks separate pixel comparisons, output guards, immutable source and route
counts. Both binaries use ASan/UBSan. Before calls C directly; fixed reaches
the explicitly installed pointers. This is direct execution of an extracted
production facade, not evidence that a full encoder invokes that facade or
that CPU feature detection installs the same route.
