"""Portable retained sources without binaries, execution results, or Git restore.

The archive preserves source bytes and the provenance claimed by a verified
run. Content and Git blob hashes are checked again when it is read. An archive
does not independently prove that a blob belongs to its stated commit; that
membership can be checked separately against the original Git repository.
"""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import stat
import zipfile

from .core import inside


FORMAT = "codec-simd-retained-sources"
MAX_UNCOMPRESSED_BYTES = 64 * 1024 * 1024
MAX_ARCHIVE_BYTES = MAX_UNCOMPRESSED_BYTES + 8 * 1024 * 1024
MAX_ENTRIES = 8192
_OBJECT_ID = re.compile(r"[0-9a-f]{40}|[0-9a-f]{64}")
_SHA256 = re.compile(r"[0-9a-f]{64}")
_ALIAS = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}")


def _json_bytes(value):
    return (json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n").encode("utf-8")


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON key: " + key)
        result[key] = value
    return result


def _json(data):
    def invalid_constant(value):
        raise ValueError("Nonfinite JSON value: " + value)

    try:
        return json.loads(data, object_pairs_hook=_pairs, parse_constant=invalid_constant)
    except (UnicodeError, json.JSONDecodeError, TypeError) as error:
        raise ValueError("Invalid source archive manifest") from error


def _path(value, label):
    if not isinstance(value, str) or not value or len(value) > 4096:
        raise ValueError(label + " must be a nonempty relative path")
    path = PurePosixPath(value)
    if (path.is_absolute() or "\\" in value or ":" in value or "\x00" in value
            or any(part in ("", ".", "..") for part in value.split("/"))
            or path.as_posix() != value):
        raise ValueError("Unsafe " + label + ": " + value)
    return value


def _validate_record(record):
    if not isinstance(record, dict):
        raise ValueError("Source records must be objects")
    for name in ("commit", "blob"):
        value = record.get(name)
        if not isinstance(value, str) or not _OBJECT_ID.fullmatch(value):
            raise ValueError("Source " + name + " must be a full lowercase Git object identifier")
    if len(record["blob"]) != len(record["commit"]):
        raise ValueError("A source commit and blob must use the same Git object format")
    if not isinstance(record.get("sha256"), str) or not _SHA256.fullmatch(record["sha256"]):
        raise ValueError("Source SHA-256 must contain 64 lowercase hexadecimal digits")
    _path(record.get("path"), "source path")
    _path(record.get("snapshot"), "source snapshot")
    if "repo" in record and not isinstance(record["repo"], str):
        raise ValueError("Original source repository must be text")
    expected_entry = "objects/" + record["sha256"]
    if "archive_entry" in record and record["archive_entry"] != expected_entry:
        raise ValueError("Source archive entry differs from its content hash")
    return expected_entry


def _validate_content(content, record):
    if hashlib.sha256(content).hexdigest() != record["sha256"]:
        raise ValueError("Retained source does not match its SHA-256")
    blob = b"blob " + str(len(content)).encode("ascii") + b"\0" + content
    algorithm = hashlib.sha1 if len(record["blob"]) == 40 else hashlib.sha256
    if algorithm(blob).hexdigest() != record["blob"]:
        raise ValueError("Retained source does not match its Git blob identifier")


def _source_bytes(path, remaining):
    if path.stat().st_size > remaining:
        raise ValueError("Source archive exceeds the uncompressed size budget")
    with path.open("rb") as stream:
        content = stream.read(remaining + 1)
    if len(content) > remaining:
        raise ValueError("Source archive exceeds the uncompressed size budget")
    return content


def export_sources(run_dir, archive_path):
    """Export only verified source-manifest references to a new ZIP file.

    The source archive is created exclusively and must live outside the run
    being verified. Existing files are never overwritten. The returned summary
    counts source references and distinct content objects, not executed tests.
    """
    # A local import avoids a dependency cycle when the CLI exposes this API.
    from .cli import verify_run

    root = Path(run_dir).resolve()
    target = Path(archive_path).absolute()
    if target.resolve().is_relative_to(root):
        raise ValueError("The source archive must be outside the retained run directory")
    suite, _ = verify_run(root)
    objects = {}
    cases = []
    total = 0
    references = 0
    for case in suite["cases"]:
        alias = case["alias"]
        if not isinstance(alias, str) or not _ALIAS.fullmatch(alias):
            raise ValueError("Invalid source case alias")
        case_root = inside(root, "cases/" + alias)
        original = _json((case_root / "source-manifest.json").read_bytes())
        if not isinstance(original, list):
            raise ValueError("A source manifest must be a list")
        retained = []
        identities = set()
        for record in original:
            entry = _validate_record(record)
            identity = record["commit"], record["path"]
            if identity in identities:
                raise ValueError("Duplicate source identity in case " + alias)
            identities.add(identity)
            if entry not in objects:
                content = _source_bytes(inside(case_root, record["snapshot"]), MAX_UNCOMPRESSED_BYTES - total)
                _validate_content(content, record)
                objects[entry] = content
                total += len(content)
            else:
                _validate_content(objects[entry], record)
            row = copy.deepcopy(record)
            row["archive_entry"] = entry
            retained.append(row)
            references += 1
        cases.append({"alias": alias, "sources": retained})
    if not objects:
        raise ValueError("The retained run has no source snapshots to export")
    manifest = {
        "schema_version": 1,
        "format": FORMAT,
        "provenance": "Retained bytes and Git blob hashes are checked; commit membership is a retained claim requiring the original repository for independent verification.",
        "cases": cases,
    }
    manifest_bytes = _json_bytes(manifest)
    if total + len(manifest_bytes) > MAX_UNCOMPRESSED_BYTES or len(objects) + 1 > MAX_ENTRIES:
        raise ValueError("Source archive exceeds its entry or uncompressed size budget")
    # Validation is complete before exclusive creation of the destination.
    with target.open("xb") as stream:
        with zipfile.ZipFile(stream, mode="w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
            archive.writestr("manifest.json", manifest_bytes)
            for entry, content in sorted(objects.items()):
                archive.writestr(entry, content)
    return {"archive": str(target), "cases": len(cases), "source_references": references,
            "content_objects": len(objects), "uncompressed_bytes": total + len(manifest_bytes),
            "sha256": _file_sha256(target)}


def _file_sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


class SourceArchive:
    """Read validated source bytes without extracting or executing ZIP entries.

    All entries are checked at construction. Lookup requires an exact case,
    full commit identifier and source path. A successful lookup confirms bytes
    and blob identity; it does not independently establish commit membership.
    """

    def __init__(self, path):
        self.path = Path(path).resolve()
        self._records = {}
        self._objects = {}
        if self.path.stat().st_size > MAX_ARCHIVE_BYTES:
            raise ValueError("Source archive exceeds the stored size budget")
        try:
            with zipfile.ZipFile(self.path) as archive:
                infos = archive.infolist()
                if not infos or len(infos) > MAX_ENTRIES:
                    raise ValueError("Source archive has no entries or exceeds the entry budget")
                names = set()
                declared_size = 0
                for info in infos:
                    if info.orig_filename != info.filename:
                        raise ValueError("Archive entry names must not contain truncated characters")
                    name = _path(info.filename, "archive entry")
                    if name in names:
                        raise ValueError("Duplicate archive entry: " + name)
                    names.add(name)
                    if name != "manifest.json" and not re.fullmatch(r"objects/[0-9a-f]{64}", name):
                        raise ValueError("Unexpected source archive entry: " + name)
                    mode = info.external_attr >> 16
                    if info.is_dir() or (stat.S_IFMT(mode) not in (0, stat.S_IFREG)):
                        raise ValueError("Source archive entries must be regular files")
                    if info.flag_bits & 1 or info.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED):
                        raise ValueError("Encrypted or unsupported compressed entries are not accepted")
                    if info.file_size < 0:
                        raise ValueError("Invalid archive entry size")
                    declared_size += info.file_size
                    if declared_size > MAX_UNCOMPRESSED_BYTES:
                        raise ValueError("Source archive exceeds the uncompressed size budget")
                if "manifest.json" not in names:
                    raise ValueError("Source archive has no manifest")
                remaining = MAX_UNCOMPRESSED_BYTES
                for info in infos:
                    with archive.open(info) as stream:
                        content = stream.read(remaining + 1)
                    if len(content) > remaining or len(content) != info.file_size:
                        raise ValueError("Source archive exceeds its actual size budget or declared entry size")
                    remaining -= len(content)
                    if info.filename == "manifest.json":
                        manifest = _json(content)
                    else:
                        if hashlib.sha256(content).hexdigest() != info.filename.removeprefix("objects/"):
                            raise ValueError("Archive content differs from its entry SHA-256")
                        self._objects[info.filename] = content
        except (zipfile.BadZipFile, RuntimeError, NotImplementedError, EOFError) as error:
            raise ValueError("Invalid or unreadable source archive") from error
        if (not isinstance(manifest, dict) or type(manifest.get("schema_version")) is not int
                or manifest["schema_version"] != 1 or manifest.get("format") != FORMAT):
            raise ValueError("Unsupported source archive manifest")
        cases = manifest.get("cases")
        if not isinstance(cases, list) or not cases:
            raise ValueError("Source archive has no case list")
        aliases = set()
        referenced = set()
        for case in cases:
            if not isinstance(case, dict) or not isinstance(case.get("alias"), str) or not _ALIAS.fullmatch(case["alias"]):
                raise ValueError("Invalid source case alias")
            alias = case["alias"]
            if alias in aliases:
                raise ValueError("Duplicate source case alias")
            aliases.add(alias)
            sources = case.get("sources")
            if not isinstance(sources, list):
                raise ValueError("Archive source records must be a list")
            for record in sources:
                entry = _validate_record(record)
                if record.get("archive_entry") != entry or entry not in self._objects:
                    raise ValueError("A referenced source object is missing")
                _validate_content(self._objects[entry], record)
                key = alias, record["commit"], record["path"]
                if key in self._records:
                    raise ValueError("Duplicate source identity: " + str(key))
                self._records[key] = record
                referenced.add(entry)
        if not self._records or referenced != self._objects.keys():
            raise ValueError("Source archive contains empty or unreferenced content")
        self.sha256 = _file_sha256(self.path)
        self.manifest = copy.deepcopy(manifest)

    def lookup(self, case_alias, revision, source_path):
        """Return ``(source_bytes, provenance_record)`` for one exact identity."""
        if not isinstance(case_alias, str) or not _ALIAS.fullmatch(case_alias):
            raise ValueError("Invalid source case alias")
        if not isinstance(revision, str) or not _OBJECT_ID.fullmatch(revision):
            raise ValueError("Source lookup requires a full lowercase commit identifier")
        _path(source_path, "source path")
        record = self._records.get((case_alias, revision, source_path))
        if record is None:
            raise ValueError("Source identity is absent from the archive: " + str((case_alias, revision, source_path)))
        result = copy.deepcopy(record)
        result["portable_origin"] = {
            "format": FORMAT,
            "schema_version": 1,
            "archive_sha256": self.sha256,
            "entry": result["archive_entry"],
            "commit_membership": "retained claim; not independently established by this archive",
        }
        return self._objects[record["archive_entry"]], result
