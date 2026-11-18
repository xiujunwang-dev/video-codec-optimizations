"""Summaries retain per-check units and do not count observations as defects."""

import csv
import io
import json


def render(suite):
    lines = ["Codec SIMD validation run", "=" * 25, "",
             "Status: " + suite["status"], "Profile: " + suite["profile"],
             "Completed at: " + suite["completed_at_utc"], "",
             "All cases in this release are historical replays selected after the issues were known.",
             "Validated means that the declared replay expectations held, including expected failures",
             "in historical implementations. It does not mean that every tested implementation is correct.",
             "Observation totals are checks, not independent defects or prospective discoveries.", ""]
    for case in suite["cases"]:
        heading = case["case"]
        lines.extend([heading, "-" * len(heading), "", "Status: " + case["status"],
                      "Classification: " + case["classification"],
                      "Evidence: " + case["result_path"], ""])
        detections = [row for row in case["observations"] if row["result"] == "detected"]
        errors = [row for row in case["observations"] if row["result"] == "error"]
        lines.append("Checks with a reported difference: " + str(len(detections)))
        lines.append("Checks with an execution or expectation error: " + str(len(errors)))
        for row in detections:
            counter = (str(row.get("mismatches", row.get("count", "recorded"))) + " "
                       + row.get("unit", "observations"))
            lines.append("* " + row["variant"] + ": " + row["id"] + "; " + counter)
        lines.extend(["", "Limits:"] + ["* " + text for text in case["limits"]] + [""])
    lines.extend(["Interpretation", "--------------", "",
                  "Harness elapsed time includes generation, reference calculations and checking.",
                  "It is not encoder throughput. A local facade check does not establish production",
                  "CPU detection or end-to-end coverage. No discovery rate or acceptance probability",
                  "is estimated. See each case's limitations and original command logs.", ""])
    return "\n".join(lines)


def observations_csv(suite):
    buffer = io.StringIO(newline="")
    fields = ["case", "classification", "case_status", "id", "variant", "check", "result",
              "count", "unit", "mismatches", "evidence", "details"]
    writer = csv.DictWriter(buffer, fieldnames=fields)
    writer.writeheader()
    for case in suite["cases"]:
        for observation in case["observations"]:
            row = {key: observation.get(key, "") for key in fields}
            row.update(case=case["case"], classification=case["classification"], case_status=case["status"],
                       evidence=json.dumps(observation["evidence"], ensure_ascii=False),
                       details=json.dumps(observation["details"], ensure_ascii=False))
            writer.writerow(row)
    return buffer.getvalue()
