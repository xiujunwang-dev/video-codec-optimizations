"""Integrity and failure-path tests for retained scientific evidence."""

import argparse
import contextlib
import copy
import importlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

from simd_validation import cli
from simd_validation.core import RunContext, inside, inventory, write_json
from simd_validation.schema import validate_case, validate_sources


class EvidenceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.context = RunContext(self.root, self.root / "case")

    def test_failed_command_keeps_both_streams_and_return_code(self):
        with self.assertRaises(subprocess.CalledProcessError):
            self.context.command([sys.executable, "-c", "import sys; print('out'); print('err', file=sys.stderr); sys.exit(7)"], "failure")
        self.assertEqual((self.context.output / "failure.stdout").read_text(), "out\n")
        self.assertEqual((self.context.output / "failure.stderr").read_text(), "err\n")
        records = json.loads((self.context.output / "commands.json").read_text())
        self.assertEqual(records[0]["returncode"], 7)
        self.assertEqual(records[0]["status"], "completed")

    def test_timeout_keeps_partial_output_and_timeout_status(self):
        with self.assertRaises(subprocess.TimeoutExpired):
            self.context.command([sys.executable, "-c", "import time; print('started', flush=True); time.sleep(5)"], "timeout", timeout=0.2)
        self.assertEqual((self.context.output / "timeout.stdout").read_text(), "started\n")
        self.assertEqual(self.context.commands[-1]["status"], "timeout")

    def test_missing_executable_keeps_launch_error(self):
        with self.assertRaises(FileNotFoundError):
            self.context.command([str(self.root / "does-not-exist")], "missing")
        self.assertEqual(self.context.commands[-1]["status"], "launch_error")
        self.assertTrue((self.context.output / "missing.stderr").is_file())

    def test_duplicate_labels_and_shell_strings_are_rejected(self):
        self.context.command([sys.executable, "-c", "pass"], "unique")
        with self.assertRaises(ValueError):
            self.context.command([sys.executable], "unique")
        with self.assertRaises(ValueError):
            self.context.command("echo no", "shell")

    def test_evidence_paths_reject_traversal_and_symlinks(self):
        with self.assertRaises(ValueError):
            inside(self.root, "../outside")
        (self.root / "link").symlink_to(self.context.output, target_is_directory=True)
        with self.assertRaises(ValueError):
            inside(self.root, "link/commands.json")

    def test_source_pin_uses_committed_content_and_checks_blob(self):
        repo = self.root / "repo"
        subprocess.run(["git", "init", "-q", str(repo)], check=True, capture_output=True)
        (repo / "kernel.c").write_text("int value = 17;\n")
        subprocess.run(["git", "-C", str(repo), "add", "kernel.c"], check=True)
        environment = dict(os.environ, GIT_AUTHOR_NAME="Validation Tests", GIT_AUTHOR_EMAIL="validation@example.invalid",
                           GIT_COMMITTER_NAME="Validation Tests", GIT_COMMITTER_EMAIL="validation@example.invalid")
        subprocess.run(["git", "-C", str(repo), "-c", "commit.gpgsign=false", "commit", "-qm", "Add numeric fixture"],
                       env=environment, check=True, capture_output=True)
        revision = subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"], text=True).strip()
        (repo / "kernel.c").write_text("int value = 99;\n")
        record = self.context.record_source(repo, revision, "kernel.c")
        snapshot = self.context.output / record["snapshot"]
        self.assertEqual(snapshot.read_text(), "int value = 17;\n")
        validate_sources(self.context.sources, self.context.output)
        snapshot.write_text("int value = 18;\n")
        with self.assertRaises(ValueError):
            validate_sources(self.context.sources, self.context.output)
        with self.assertRaises(ValueError):
            self.context.record_source(repo, "HEAD", "kernel.c")

    def test_validated_result_rejects_missing_evidence_or_negative_counters(self):
        value = {"status": "validated", "limits": [], "observations": [{
            "id": "output", "variant": "fixed", "check": "numeric", "result": "no_failure",
            "evidence": ["commands.json"], "details": {}, "count": 1, "unit": "inputs", "mismatches": 0}]}
        validate_case(value, self.context.output, "fixture")
        for field, changed in (("evidence", ["absent.log"]), ("mismatches", -1), ("count", True), ("result", "error")):
            broken = copy.deepcopy(value)
            broken["observations"][0][field] = changed
            with self.assertRaises(ValueError):
                validate_case(broken, self.context.output, "fixture")


class SuiteTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    @staticmethod
    def adapter(status="validated"):
        def run(context):
            (context.output / "executed.json").write_text('{"executed": 1}\n')
            return {"status": status, "limits": ["Unit-test fixture only"], "observations": [{
                "id": "fixture", "variant": "fixed", "check": "baseline",
                "result": "unsupported" if status == "unsupported" else "no_failure",
                "evidence": ["executed.json"], "details": {"executed": 1}}]}
        return types.SimpleNamespace(run=run)

    def run_fixture(self, status="validated", name="run"):
        args = argparse.Namespace(out=self.root / name, workspace=self.root, profile="smoke", case=["x265"],
                                  x265_repo=None, svt_repo=None, aom_repo=None)
        original_import = importlib.import_module
        def load(name, *arguments, **keywords):
            if name == "simd_validation.adapters.x265":
                return self.adapter(status)
            return original_import(name, *arguments, **keywords)
        with patch("simd_validation.cli.importlib.import_module", side_effect=load), contextlib.redirect_stdout(io.StringIO()):
            code = cli.run(args)
        return args.out, code

    def test_verified_run_detects_retained_content_change(self):
        output, code = self.run_fixture()
        self.assertEqual(code, 0)
        suite, count = cli.verify_run(output)
        self.assertEqual(suite["status"], "validated")
        self.assertGreater(count, 5)
        (output / "cases/x265/executed.json").write_text('{"executed": 0}\n')
        with self.assertRaises(ValueError):
            cli.verify_run(output)

    def test_report_cannot_hide_unsupported_case(self):
        output, code = self.run_fixture("unsupported")
        self.assertEqual(code, 2)
        self.assertEqual(cli.verify_run(output)[0]["status"], "incomplete")

    def test_summary_mismatch_rejected_even_after_hash_refresh(self):
        output, _ = self.run_fixture()
        suite = json.loads((output / "suite.json").read_text())
        suite["cases"][0]["observations"][0]["details"] = {"executed": 0}
        write_json(output / "suite.json", suite)
        write_json(output / "checksums.json", {"schema_version": 1, "algorithm": "sha256",
                                               "artifacts": inventory(output, exclude=("checksums.json",))})
        with self.assertRaises(ValueError):
            cli.verify_run(output)

    def test_existing_output_is_not_overwritten(self):
        self.run_fixture()
        with self.assertRaises(FileExistsError):
            self.run_fixture()


if __name__ == "__main__":
    unittest.main()
