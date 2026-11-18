"""Strict result checks before a case can enter a consolidated report."""

import hashlib
import re

from .catalog import OUTCOMES, STATUSES
from .core import inside


def validate_case(value, output, case_id):
    if not isinstance(value, dict) or value.get("status") not in STATUSES:
        raise ValueError("Case result has no recognized status")
    if value.get("case", case_id) != case_id:
        raise ValueError("Adapter returned a different case identifier")
    if not isinstance(value.get("limits"), list) or not all(isinstance(item, str) for item in value["limits"]):
        raise ValueError("Case limitations must be a list of strings")
    rows = value.get("observations")
    if not isinstance(rows, list):
        raise ValueError("Case observations must be a list")
    if value["status"] == "validated" and not rows:
        raise ValueError("A validated case must retain observations")
    seen = set()
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("Observations must be objects")
        for name in ("id", "variant", "check"):
            if not isinstance(row.get(name), str) or not row[name]:
                raise ValueError("Observation requires a nonempty " + name)
        key = row["id"], row["variant"]
        if key in seen:
            raise ValueError("Duplicate observation identifier and variant: " + str(key))
        seen.add(key)
        if row.get("result") not in OUTCOMES:
            raise ValueError("Observation has an unknown outcome")
        if not isinstance(row.get("details"), (str, dict)):
            raise ValueError("Observation details must be text or an object")
        if value["status"] == "validated" and row["result"] in ("error", "unsupported"):
            raise ValueError("A validated case cannot contain errors or unsupported checks")
        evidence = row.get("evidence")
        if not isinstance(evidence, list) or not all(isinstance(path, str) for path in evidence):
            raise ValueError("Observation evidence must be a list of retained relative file paths")
        if not evidence and row["result"] != "unsupported":
            raise ValueError("Completed checks must retain evidence")
        for relative in evidence:
            if not inside(output, relative).is_file():
                raise ValueError("Missing observation evidence: " + relative)
        for name in ("count", "mismatches", "mismatched_cells"):
            if name in row and (type(row[name]) is not int or row[name] < 0):
                raise ValueError("Observation counters must be nonnegative integers: " + name)
        if "count" in row and (not isinstance(row.get("unit"), str) or not row["unit"]):
            raise ValueError("Observation counts require a unit")
    return value


def validate_sources(sources, output):
    if not isinstance(sources, list):
        raise ValueError("Source manifest must be a list")
    for source in sources:
        if not re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", source["commit"]):
            raise ValueError("Source commit is not a full object identifier")
        snapshot = inside(output, source["snapshot"])
        content = snapshot.read_bytes()
        if hashlib.sha256(content).hexdigest() != source["sha256"]:
            raise ValueError("Source content differs from its recorded SHA-256")
        blob = b"blob " + str(len(content)).encode() + b"\0" + content
        object_hash = hashlib.sha1(blob).hexdigest() if len(source["blob"]) == 40 else hashlib.sha256(blob).hexdigest()
        if object_hash != source["blob"]:
            raise ValueError("Retained source does not match its Git blob identifier")
