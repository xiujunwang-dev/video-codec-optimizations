"""Case selection and interpretation, independent of observed outcomes."""

CASES = {
    "x265": {
        "id": "x265-12bit-psy-reduction",
        "module": "x265",
        "classification": "historical_replay",
        "dimension": "numeric",
        "description": "Intermediate energy and final cost against an independent integer reference",
        "repository": "s265/x265-psy-cost-12bit-review",
    },
    "svt": {
        "id": "svt-highbd-first-compound-predictor",
        "module": "svt",
        "classification": "historical_replay",
        "dimension": "phase_state",
        "description": "First-predictor output preservation and paired compound-predictor state",
        "repository": "SVT-AV1-neon-compound-review",
    },
    "aom": {
        "id": "aom-highbd-intrabc-dispatch",
        "module": "aom",
        "classification": "historical_replay",
        "dimension": "dispatch",
        "description": "Extracted production facade routing with real C/NEON kernels and independent formulas",
        "repository": "aom",
    },
}

STATUSES = {"validated", "unsupported", "infrastructure_error", "unexpected_result"}
OUTCOMES = {"detected", "no_failure", "error", "unsupported"}
