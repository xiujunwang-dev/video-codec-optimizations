"""Source archive integrity, path isolation, and bounded-read checks."""

import copy
import hashlib
import json
from pathlib import Path
import stat
import tempfile
import unittest
from unittest.mock import patch
import warnings
import zipfile

from simd_validation.catalog import CASES
from simd_validation.core import inventory, write_json
from simd_validation.portable import FORMAT, SourceArchive, export_sources


class PortableSourcesTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.run = self.root / "run"
        case = self.run / "cases/x265"
        case.mkdir(parents=True)
        self.content = b"/* Copyright retained from the upstream fixture. */\nint value = 17;\n"
        (case / "source.c").write_bytes(self.content)
        (case / "old-binary").write_bytes(b"unrelated binary contents")
        (case / "execution.stdout").write_text("previous execution result\n")
        blob = b"blob " + str(len(self.content)).encode() + b"\0" + self.content
        self.source = {
            "repo": "/original/location/codec",
            "commit": "a" * 40,
            "blob": hashlib.sha1(blob).hexdigest(),
            "sha256": hashlib.sha256(self.content).hexdigest(),
            "path": "source/kernel.c",
            "snapshot": "source.c",
        }
        second = dict(self.source, commit="b" * 40)
        write_json(case / "source-manifest.json", [self.source, second])
        result = {
            "schema_version": 1, "case": CASES["x265"]["id"], "alias": "x265",
            "classification": "historical_replay", "status": "validated", "elapsed_seconds": 0.0,
            "limits": ["Retained-source unit-test fixture; no real codec execution."],
            "observations": [{"id": "fixture", "variant": "fixed", "check": "baseline", "result": "no_failure",
                              "evidence": ["source.c"], "details": "Unit-test fixture source retained."}],
        }
        write_json(case / "result.json", result)
        summary = copy.deepcopy(result)
        summary.pop("schema_version")
        summary["result_path"] = "cases/x265/result.json"
        write_json(self.run / "suite.json", {"schema_version": 1, "status": "validated", "cases": [summary]})
        write_json(self.run / "manifest.json", {"selected": ["x265"]})
        write_json(self.run / "checksums.json", {"schema_version": 1, "algorithm": "sha256",
                                                "artifacts": inventory(self.run, exclude=("checksums.json",))})
        self.archive = self.root / "sources.zip"

    def export(self):
        return export_sources(self.run, self.archive)

    def archive_contents(self):
        with zipfile.ZipFile(self.archive) as archive:
            return {name: archive.read(name) for name in archive.namelist()}

    def rewrite(self, name, contents):
        path = self.root / name
        with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for entry, content in contents.items():
                archive.writestr(entry, content)
        return path

    def changed_manifest(self, name, change):
        contents = self.archive_contents()
        manifest = json.loads(contents["manifest.json"])
        change(manifest)
        contents["manifest.json"] = json.dumps(manifest).encode()
        return self.rewrite(name, contents)

    def test_export_deduplicates_only_referenced_sources_and_preserves_notice(self):
        summary = self.export()
        self.assertEqual(summary["source_references"], 2)
        self.assertEqual(summary["content_objects"], 1)
        contents = self.archive_contents()
        self.assertEqual(set(contents), {"manifest.json", "objects/" + self.source["sha256"]})
        archive = SourceArchive(self.archive)
        content, record = archive.lookup("x265", self.source["commit"], self.source["path"])
        self.assertEqual(content, self.content)
        self.assertEqual(record["blob"], self.source["blob"])
        self.assertEqual(record["repo"], self.source["repo"])
        self.assertEqual(record["portable_origin"]["archive_sha256"], summary["sha256"])
        self.assertEqual(record["portable_origin"]["format"], FORMAT)
        record["blob"] = "0" * 40
        self.assertEqual(archive.lookup("x265", self.source["commit"], self.source["path"])[1]["blob"], self.source["blob"])

    def test_existing_archive_is_not_overwritten(self):
        self.archive.write_bytes(b"existing contents")
        with self.assertRaises(FileExistsError):
            self.export()
        self.assertEqual(self.archive.read_bytes(), b"existing contents")

    def test_export_rejects_changed_run_and_output_inside_run(self):
        with self.assertRaises(ValueError):
            export_sources(self.run, self.run / "sources.zip")
        (self.run / "cases/x265/source.c").write_bytes(b"changed")
        with self.assertRaises(ValueError):
            self.export()
        self.assertFalse(self.archive.exists())

    def test_tampered_content_is_rejected(self):
        self.export()
        contents = self.archive_contents()
        entry = "objects/" + self.source["sha256"]
        contents[entry] = self.content.replace(b"17", b"18")
        with self.assertRaises(ValueError):
            SourceArchive(self.rewrite("tampered.zip", contents))

    def test_duplicate_zip_entry_is_rejected(self):
        self.export()
        duplicate = self.root / "duplicate.zip"
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            with zipfile.ZipFile(duplicate, "w") as archive:
                for entry, content in self.archive_contents().items():
                    archive.writestr(entry, content)
                archive.writestr("manifest.json", b"{}")
        with self.assertRaises(ValueError):
            SourceArchive(duplicate)

    def test_unsafe_or_extra_entries_and_symlinks_are_rejected(self):
        self.export()
        for index, entry in enumerate(("../kernel.c", "/kernel.c", "objects\\kernel.c", "objects/./kernel.c", "old-binary")):
            with self.subTest(entry=entry):
                contents = self.archive_contents()
                contents[entry] = b"unrequested contents"
                with self.assertRaises(ValueError):
                    SourceArchive(self.rewrite(f"unsafe-{index}.zip", contents))
        symbolic = self.root / "symbolic.zip"
        with zipfile.ZipFile(symbolic, "w") as archive:
            for entry, content in self.archive_contents().items():
                info = zipfile.ZipInfo(entry)
                info.create_system = 3
                info.external_attr = (stat.S_IFLNK | 0o777) << 16
                archive.writestr(info, content)
        with self.assertRaises(ValueError):
            SourceArchive(symbolic)

    def test_uncompressed_budget_is_enforced_on_compressed_sources(self):
        self.export()
        with patch("simd_validation.portable.MAX_UNCOMPRESSED_BYTES", 64):
            with self.assertRaises(ValueError):
                SourceArchive(self.archive)
            with self.assertRaises(ValueError):
                export_sources(self.run, self.root / "too-large.zip")
        contents = self.archive_contents()
        contents["objects/" + "0" * 64] = b"\0" * 4096
        with patch("simd_validation.portable.MAX_UNCOMPRESSED_BYTES", 2048):
            with self.assertRaises(ValueError):
                SourceArchive(self.rewrite("compressed-over-budget.zip", contents))

    def test_null_truncated_archive_entry_name_is_rejected(self):
        self.export()
        contents = self.archive_contents()
        contents["manifest.jsonX"] = contents.pop("manifest.json")
        path = self.rewrite("null-name.zip", contents)
        path.write_bytes(path.read_bytes().replace(b"manifest.jsonX", b"manifest.json\0"))
        with self.assertRaises(ValueError):
            SourceArchive(path)

    def test_invalid_blob_format_or_blob_content_hash_is_rejected(self):
        self.export()
        for value in ("z" * 40, "0" * 40, "0" * 64):
            with self.subTest(blob=value):
                path = self.changed_manifest("bad-blob-" + str(len(value)) + value[:1] + ".zip",
                                             lambda manifest: manifest["cases"][0]["sources"][0].update(blob=value))
                with self.assertRaises(ValueError):
                    SourceArchive(path)

    def test_unsafe_source_paths_and_duplicate_identities_are_rejected(self):
        self.export()
        for field in ("path", "snapshot"):
            with self.subTest(field=field):
                path = self.changed_manifest("unsafe-" + field + ".zip",
                                             lambda manifest: manifest["cases"][0]["sources"][0].update({field: "../outside"}))
                with self.assertRaises(ValueError):
                    SourceArchive(path)
        path = self.changed_manifest("duplicate-source.zip", lambda manifest: manifest["cases"][0]["sources"].append(
            copy.deepcopy(manifest["cases"][0]["sources"][0])))
        with self.assertRaises(ValueError):
            SourceArchive(path)

    def test_unreferenced_objects_and_missing_objects_are_rejected(self):
        self.export()
        contents = self.archive_contents()
        extra = b"extra bytes"
        contents["objects/" + hashlib.sha256(extra).hexdigest()] = extra
        with self.assertRaises(ValueError):
            SourceArchive(self.rewrite("unreferenced.zip", contents))
        contents = self.archive_contents()
        del contents["objects/" + self.source["sha256"]]
        with self.assertRaises(ValueError):
            SourceArchive(self.rewrite("missing-source.zip", contents))

    def test_lookup_requires_exact_case_commit_and_path(self):
        self.export()
        archive = SourceArchive(self.archive)
        for identity in (("aom", self.source["commit"], self.source["path"]),
                         ("x265", "c" * 40, self.source["path"]),
                         ("x265", "HEAD", self.source["path"]),
                         ("x265", self.source["commit"], "another.c"),
                         ("x265", self.source["commit"], "../kernel.c")):
            with self.subTest(identity=identity), self.assertRaises(ValueError):
                archive.lookup(*identity)

    def test_duplicate_json_keys_and_boolean_schema_version_are_rejected(self):
        self.export()
        path = self.changed_manifest("boolean-version.zip", lambda manifest: manifest.update(schema_version=True))
        with self.assertRaises(ValueError):
            SourceArchive(path)
        contents = self.archive_contents()
        contents["manifest.json"] = b'{"schema_version":1,"schema_version":1}'
        with self.assertRaises(ValueError):
            SourceArchive(self.rewrite("duplicate-json-key.zip", contents))


if __name__ == "__main__":
    unittest.main()
