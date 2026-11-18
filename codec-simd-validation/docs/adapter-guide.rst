Adding a case adapter
======================

An adapter is a Python module with a ``run(context)`` function that rebuilds a
specific experiment and returns its declared result. The shared layer supplies
execution logs, retained sources, result validation, reports and integrity
checks. The case author supplies the input generator, legal domain, reference,
state predicates, route instrumentation and interpretation of the observations.
These checks are implemented for each function family; the tool does not derive
them from a function signature or generate an independent reference.

The interface described here is the version 0.1.0 source interface. There is no
external adapter discovery mechanism. Extending the installed case set requires
maintaining the package and its registration data together.

Define the experiment first
----------------------------

Record the source commits, supported hosts and compilers, invocation budgets,
seeds, expected outcomes and limits before implementing the experiment. Specify
bit depths, rounding and overflow rules, legal dimensions, strides, alignment,
padding and aliasing. For a multi-call function, describe which buffers each
phase may read or modify. For routing checks, identify the entry point and
required target calls, and state how dispatch pointers are initialized.

An upstream scalar function is a differential reference. Calling it does not
by itself provide an independent arithmetic reference. A separately implemented
formula or wide-integer model needs its own domain and cross-checks. Initialized
sentinels can detect writes and preserved-state changes, but cannot establish
absence of reads. Document which of these claims the case actually tests.

Use paired inputs for before/fixed variants and retain their fingerprints.
Specify nonempty expected coverage for each profile, then check the reported
invocations and comparison counts before interpreting zero mismatches. Keep
known witnesses, generated inputs and injected controls distinguishable.
Prospective work also requires the enrollment and exposure review described in
``evaluation.rst``.

Register the adapter
---------------------

Add the module under ``simd_validation/adapters/`` and an entry to
``simd_validation/catalog.py``. This illustrative entry describes a hypothetical
historical rounded-average case; it is not an additional shipped experiment::

    "average": {
        "id": "rounded-average-replay",
        "module": "rounded_average",
        "classification": "historical_replay",
        "dimension": "numeric",
        "description": "Rounded average against an independent integer formula",
        "repository": "codec",
    },

The alias ``average`` becomes a ``--case`` choice and creates an
``--average-repo`` option. The module name is imported relative to
``simd_validation.adapters``. The repository path is relative to
``--workspace`` unless the user supplies an override. The adapter must read that
override from ``context.options["average_repo"]`` when it is present.

The current ``doctor`` command keeps its own revision table in
``simd_validation/cli.py`` and expects two historical revisions per case.
Update that command when registering a case; adding a catalog entry alone is
insufficient. The run manifest and suite limitations
currently describe a historical cohort. A future prospective runner must update
that reporting and the evaluation registration as well as the catalog; changing
one case's classification alone does not establish prospective evaluation.

Put original harness files in ``harnesses/``. The package includes files with
``.c``, ``.cc``, ``.cpp`` and ``.h`` extensions there. Add any other resources to
the packaging configuration explicitly and check an installed-package run.
Retain applicable upstream notices and license files with the recorded source
closure.

RunContext interface
---------------------

The runner creates one ``RunContext`` per selected case. Its ``output`` directory
already exists and is new for the run. The adapter should use these attributes:

* ``workspace`` and ``output`` are resolved ``Path`` objects.
* ``profile`` is ``"smoke"`` or ``"full"`` through the current CLI.
* ``options`` contains supplied repository overrides. The CLI does not currently
  expose arbitrary per-adapter settings.
* ``case_alias`` identifies the catalog alias; ``source_archive`` is either a
  loaded portable source archive or ``None``.

Use ``context.command(argv, label, cwd=None, env=None, timeout=None, check=True)``
for build, probe and execution commands. Supply an argument list, with no shell
syntax. A label must be unique within the context and match
``[A-Za-z0-9][A-Za-z0-9_.-]{0,199}``. The default working directory is
``context.output`` and the default timeout is 120 seconds. The method records
arguments, working directory, timing, return code, stdout and stderr in
``commands.json`` and ``<label>.stdout`` / ``<label>.stderr``. It returns a
``subprocess.CompletedProcess`` with byte streams.

By default a nonzero exit raises ``subprocess.CalledProcessError`` after the
logs have been retained. ``check=False`` returns a nonzero exit for the adapter
to interpret. Launch errors and timeouts still raise. ``env`` adds overrides to
the inherited environment; the log retains only explicitly supplied sanitizer
runtime options, not the entire environment. Record other relevant build and
runtime settings separately when the experiment needs them.

Use ``context.record_source(repo, revision, path, destination=None)`` for every
required upstream source, header and license. ``revision`` must be a full
40- or 64-hexadecimal commit identifier, and ``path`` must be relative to the
repository. The method reads committed bytes through Git, or looks up the exact
case/commit/path in a loaded source archive. It writes a snapshot beneath the
case output and appends its commit, Git blob identifier, SHA-256 and relative
snapshot path to ``source-manifest.json``. The returned record contains those
fields. ``destination`` may select a path within the output directory.

Compile the retained snapshots and recorded generated files. A live checkout
must not supply unnoticed headers, configuration or dependency discovery.
When ``context.source_archive`` is present, a repository directory is not
required: source lookup uses the archive. Archive provenance retains the commit
label but does not independently prove membership of a blob in that commit.

``context.resource("rounded_average_check.c")`` returns the path of an original
harness resource in a checkout or installed package. Copy it into the output
before compiling it. This method locates a resource; it does not implement or
validate the harness.

Minimal numeric skeleton
-------------------------

The following skeleton assumes that the author has supplied a self-contained
``src/kernel.c``, its header and a ``rounded_average_check.c`` harness. Replace
the commit placeholder and source paths with the registered experiment. The
harness must implement the legal inputs and independent formula, call the
retained production function, and emit the JSON fields checked below. This
example compares one numeric result per invocation. It demonstrates result
plumbing for one pinned variant; a historical before/fixed case also needs its
paired variants and explicit replay expectations::

    import json
    import shutil
    from pathlib import Path

    from simd_validation.schema import validate_case

    CASE_ID = "rounded-average-replay"
    PINNED_REVISION = "<full pinned commit identifier>"
    BUDGETS = {"smoke": 128, "full": 4096}

    def run(context):
        output = context.output
        limits = ["Direct primitive calls with one numeric comparison per call."]

        def finish(status, observations):
            value = {"status": status, "observations": observations,
                     "limits": limits}
            return validate_case(value, output, CASE_ID)

        compiler = shutil.which("clang")
        if compiler is None:
            limits.append("This build requires an available C compiler.")
            return finish("unsupported", [])

        repo = Path(context.options.get("average_repo",
                                        context.workspace / "codec"))
        for source, destination in (("src/kernel.c", "kernel.c"),
                                    ("src/kernel.h", "kernel.h")):
            context.record_source(repo, PINNED_REVISION, source,
                                  destination=destination)
        context.record_source(repo, PINNED_REVISION, "LICENSE")
        harness = output / "rounded_average_check.c"
        shutil.copyfile(context.resource(harness.name), harness)
        binary = output / "rounded-average-check"
        context.command([compiler, "--version"], "average-compiler")
        context.command([compiler, "-std=c99", "-O2", "kernel.c",
                         str(harness), "-o", str(binary)], "average-build")
        executed = context.command([str(binary), context.profile],
                                   "average-run", check=False)
        evidence = ["average-run.stdout", "average-run.stderr",
                    "commands.json", "source-manifest.json"]
        row = {"id": "rounded-average", "variant": "pinned",
               "check": "numeric", "evidence": evidence}
        try:
            metrics = json.loads(executed.stdout)
            budget = BUDGETS[context.profile]
            if executed.returncode != 0 or executed.stderr:
                raise ValueError("The harness failed or emitted diagnostics.")
            if not isinstance(metrics, dict):
                raise ValueError("Metrics must be a JSON object.")
            if metrics.get("profile") != context.profile:
                raise ValueError("The harness ran a different profile.")
            for key in ("invocations", "comparisons"):
                if type(metrics.get(key)) is not int or metrics[key] != budget:
                    raise ValueError("Coverage differs from the declared budget.")
            mismatches = metrics.get("mismatches")
            if type(mismatches) is not int or not 0 <= mismatches <= budget:
                raise ValueError("Invalid mismatch count.")
        except (ValueError, UnicodeError) as error:
            row.update(result="error", details=str(error))
            return finish("unexpected_result", [row])
        row.update(result="detected" if mismatches else "no_failure",
                   count=budget, unit="numeric result comparisons",
                   mismatches=mismatches,
                   details="Rounded average against the independent formula.")
        return finish("unexpected_result" if mismatches else "validated", [row])

Add architecture and compiler capability probes before building when the case
requires NEON, another instruction set or sanitizer runtimes. A probe should
establish that the required binary can both compile and execute. Record its
logs and return ``unsupported`` for an unavailable capability. Do not interpret
a production-source compile failure as a capability test. The skeleton leaves
build failures to the runner's exception handling, which preserves the command
logs and records ``infrastructure_error``.

Result and observation contract
-------------------------------

``validate_case(value, output, case_id)`` validates the returned dictionary and
retained evidence paths. The CLI calls it after ``run``; the skeleton also calls
it directly so the example can be checked in isolation. Return ``status``,
``observations`` and ``limits``. ``limits`` must be a list of strings. An
optional ``case`` must match the catalog identifier. The runner adds schema,
alias, classification and elapsed-time fields and writes ``result.json``.

The declared case statuses have these meanings:

* ``validated``: all registered replay expectations held. A known before
  variant may have ``detected`` observations while its fixed variant has
  ``no_failure``. This status does not mean every tested implementation passed.
* ``unsupported``: required source history, host or tool capability is
  unavailable. Describe the missing prerequisite in ``limits`` and retain any
  probe evidence. An empty observation list is permitted for this status.
* ``infrastructure_error``: building, launching, retaining or interpreting the
  experiment could not complete reliably. An uncaught adapter exception is
  converted to this status with an exception record and command logs.
* ``unexpected_result``: an executed experiment differs from its declared
  expectations, including unexpected failures, missing required coverage or
  malformed metrics that the adapter handles explicitly.

A crash is unclassified evidence until investigated. The adapter should retain
it and explain its status; a nonzero exit alone is not a confirmed numeric,
state or route defect. Case statuses are declarations checked for consistency
with the result schema, not conclusions inferred by the shared layer.

Each observation requires nonempty string fields ``id``, ``variant`` and
``check``; a ``result``; ``details`` as text or a dictionary; and ``evidence`` as
a list of relative file paths within the case output. The pair
``(id, variant)`` must be unique. Observation outcomes are ``detected``,
``no_failure``, ``error`` and ``unsupported``. Only ``unsupported`` may omit
evidence. A validated case needs at least one observation and cannot contain
``error`` or ``unsupported`` outcomes.

Optional ``count``, ``mismatches`` and ``mismatched_cells`` must be nonnegative
integers, with booleans rejected. Every ``count`` needs a nonempty ``unit``.
The author must check relationships between counters, exact expected coverage,
matching input fingerprints and variant expectations. The schema does not
establish those relationships or require a specific vocabulary for ``check``.

These illustrative records show three checking dimensions. Their numbers are
examples, not measured results. Each named evidence file must exist when the
record is validated::

    {
        "id": "average-values", "variant": "fixed", "check": "numeric",
        "result": "no_failure", "count": 128,
        "unit": "numeric result comparisons", "mismatches": 0,
        "evidence": ["fixed-metrics.json"],
        "details": "Rounded values match an independent integer formula."
    }

    {
        "id": "first-output-preservation", "variant": "before",
        "check": "phase_state", "result": "detected", "count": 128,
        "unit": "first-predictor calls", "mismatches": 128,
        "mismatched_cells": 8192, "evidence": ["before-metrics.json"],
        "details": "The first call changed initialized pixel output that must be preserved."
    }

    {
        "id": "optimized-route", "variant": "before", "check": "dispatch",
        "result": "detected", "count": 128, "unit": "facade invocations",
        "mismatches": 128, "evidence": ["before-route-metrics.json"],
        "details": {"initialization": "explicit local function pointers",
                    "expected_optimized_calls": 128, "actual_optimized_calls": 0,
                    "actual_scalar_calls": 128}
    }

Report state predicates separately from cell comparisons and route calls.
Multiple failed inputs or observations from one cause do not become independent
defects. Explicitly installed local routes do not demonstrate generated dispatch
initialization, CPU detection or whole-codec execution.

Check the integration
----------------------

Exercise the adapter with a new smoke output directory, inspect its raw logs
and counters, then run ``verify`` and ``report``. A successful integrity check
means the retained inventory, source blobs, evidence paths and case summaries
agree. It does not prove the legal input domain, arithmetic reference or replay
expectations are correct, and does not change the declared run status.

Check that missing prerequisites produce an explicit unsupported outcome and
that a build failure remains a retained infrastructure failure. Check malformed
or empty harness metrics and incorrect coverage so they cannot produce a
validated result. For historical cases, confirm the expected before failure and
fixed behavior on identical inputs. Use independent review for the harness's
domain, reference and phase rules.

Finally, build and install the package, export a completed run's source archive,
and rebuild from that archive without codec checkouts. This checks resource
packaging and the completeness of the recorded source closure. Rebuilding on
the same machine is an integration check; replication by another user or on
another supported machine is a separate evaluation step. Harness timing
includes reference and checking work and is not encoder throughput.
