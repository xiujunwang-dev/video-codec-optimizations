Evaluation design
=================

The software artifact is the primary deliverable. The first release establishes
that separately rebuilt, source-pinned experiments share one execution and
evidence format across three projects and three checking dimensions. It does
not establish that the approach discovers more previously unknown defects.

Historical cohort
-----------------

The psy energy reduction, scaled first compound predictor, and high bit-depth
IntraBC facade are selected known cases. Before/fixed runs use paired inputs.
Known witnesses are positive controls, not generated-input discovery evidence.
Each case records its own denominator and units. Multiple failed inputs, depths,
lanes or observations arising from one cause are not independent defects.

The numeric case directly compares generated input groups at identical counts.
Its normal and sanitizer modes use the same stream. Numeric discrepancies in
the sanitized run are found by the independent reference, not by sanitizer
diagnostics. The compound baseline, paired phase checks and facade experiments
are not asserted to have the same computational budget.

Candidate enrollment
--------------------

The initial six candidate labels are provisional. Before enrollment, reconcile
implementation exposure for every participant, including earlier sessions,
patch review and related function families. The historical ``reserved`` label
for SVT sum-of-squares does not resolve later exposure. Unknown exposure stays
unknown. An exploratory cohort may include exposed implementations, but must
not be described as blind or used to estimate prospective discovery accuracy.

Before opening an enrolled implementation, record its project and source
commit, interface declarations, legal numeric domain, layouts and padding,
reference independence, permitted phase writes, required entry/routes and
expected call count. Freeze budgets, seeds, comparison order and exclusions in
a new checksummed registration directory. A local timestamp and hash preserve
a revision; they do not independently prove when it was written.

Comparison arms
---------------

Retain existing upstream tests as a coverage baseline. Also compare ordinary
uniform C differential testing, the same input stream under ordinary memory
sanitizers, and the registered contract checks. Uniform and contract arms use
the same invocation budget and legal domain. Report any unavoidable budget
difference explicitly. Count oracle, initialization and checking costs in
wall-clock measurements, and separately report manual contract-writing time.

The primary unit is an independently reproduced cause in a registered family.
Record actual calls, covered phases/routes, false positives, time to first
evidence, manual effort and valid no-failure outcomes. An unexpected crash is
an unclassified result until investigated. Injected changes are controls and
must not be counted as new real-world discoveries. Keep the registered sample
and negative results in the released artifact.

Continuation decisions
----------------------

The internal method-study gate is two independently confirmed new causes in
two projects, with one phase/access/route case missed by registered baselines.
It guides further investment and is not a journal acceptance condition.

Without such findings, a software paper can still be supported by a reusable
tool, documented diagnostic value, negative results and independent replication.
The release still needs replication on another machine or by another user,
validation of additional compiler/host combinations, and a stable archived
software release before submission. No publication outcome is claimed.

Related work boundary
---------------------

Differential testing, boundary inputs, independent integer references,
sanitizers, sentinels and function counters are established techniques.
Zhang et al., Complexity Measurement and Fault Detection Techniques for H.264
Optimized Functions (2012), already discuss optimized-function numeric errors
and testing. checkasm already supports production primitive testing across
architectures. The proposed artifact complements those tools with explicit
phase-state and local route checks, retained provenance and comparative cases;
its additional value must be demonstrated by use and replication.

References:

* https://www.jsoftware.us/vol7/jsw0708-20.pdf
* https://checkasm.videolan.me/
