"""Execution logs, immutable source snapshots and retained experiment evidence."""

from __future__ import annotations

import datetime as dt
import hashlib
from importlib import resources
import json
import os
from pathlib import Path, PurePosixPath
import platform
import re
import subprocess
import time


def utc_now():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def digest(path):
    value = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def write_json(path, value):
    """Replace a single JSON document after its complete serialization succeeds."""
    path = Path(path)
    data = json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n"
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(data, encoding="utf-8")
    temporary.replace(path)


def inside(root, relative):
    """Resolve a retained relative path without accepting traversal or symlinks."""
    root = Path(root).resolve()
    relative = Path(relative)
    if relative.is_absolute() or ".." in relative.parts or not relative.parts:
        raise ValueError("Expected a relative artifact path: " + str(relative))
    path = root / relative
    for parent in [path, *path.parents]:
        if parent == root:
            break
        if parent.is_symlink():
            raise ValueError("Artifact paths must not contain symlinks: " + str(relative))
    if not path.resolve().is_relative_to(root):
        raise ValueError("Artifact path escapes the run directory: " + str(relative))
    return path


def inventory(root, exclude=()):
    root = Path(root).resolve()
    excluded = set(exclude)
    result = []
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root).as_posix()
        if relative in excluded:
            continue
        if path.is_symlink():
            raise ValueError("Cannot retain symbolic-link artifacts: " + relative)
        if path.is_file():
            result.append({"path": relative, "size": path.stat().st_size, "sha256": digest(path)})
    return result


def host_info():
    result = {"platform": platform.platform(), "controller_machine": platform.machine(),
              "python": platform.python_version(), "cpu_count": os.cpu_count()}
    # A translated controller can still build and execute native ARM binaries.
    probe = (["/usr/bin/arch", "-arm64", "/usr/bin/uname", "-m"]
             if platform.system() == "Darwin" else ["uname", "-m"])
    try:
        completed = subprocess.run(probe, capture_output=True, timeout=10, check=False)
        result["native_probe"] = {"argv": probe, "returncode": completed.returncode,
                                  "stdout": completed.stdout.decode(errors="replace").strip()}
    except (OSError, subprocess.SubprocessError) as error:
        result["native_probe"] = {"argv": probe, "error": str(error)}
    return result


class RunContext:
    """Shared adapter interface; commands run without a shell and preserve failures."""

    def __init__(self, workspace, output, profile="smoke", options=None, case_alias=None, source_archive=None):
        self.workspace = Path(workspace).resolve()
        self.output = Path(output).resolve()
        self.output.mkdir(parents=True, exist_ok=False)
        self.profile = profile
        self.options = dict(options or {})
        self.case_alias = case_alias
        self.source_archive = source_archive
        self.sources = []
        self.commands = []
        self._labels = set()
        write_json(self.output / "commands.json", self.commands)
        write_json(self.output / "source-manifest.json", self.sources)

    def resource(self, name):
        relative = PurePosixPath(name)
        if relative.parts[:1] == ("harnesses",):
            relative = PurePosixPath(*relative.parts[1:])
        if relative.is_absolute() or ".." in relative.parts or len(relative.parts) != 1:
            raise ValueError("Harness resources must use a simple file name")
        checkout = Path(__file__).resolve().parent.parent / "harnesses" / str(relative)
        if checkout.is_file():
            return checkout
        packaged = resources.files("simd_validation.harnesses").joinpath(str(relative))
        path = Path(str(packaged))
        if not path.is_file():
            raise FileNotFoundError("Missing harness resource: " + str(relative))
        return path

    def command(self, argv, label, cwd=None, env=None, timeout=None, check=True):
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,199}", label):
            raise ValueError("Command labels must be simple unique file names")
        if label in self._labels:
            raise ValueError("Duplicate command label: " + label)
        if not argv or isinstance(argv, (str, bytes)):
            raise ValueError("Commands require a nonempty argument list")
        self._labels.add(label)
        arguments = [str(value) for value in argv]
        working = Path(cwd).resolve() if cwd else self.output
        record = {"label": label, "argv": arguments, "cwd": str(working),
                  "started_at_utc": utc_now(), "timeout_seconds": timeout or 120,
                  "stdout": label + ".stdout", "stderr": label + ".stderr",
                  "status": "running"}
        # Only record the explicitly relevant runtime settings, never the inherited environment.
        if env:
            record["runtime_options"] = {key: env[key] for key in ("ASAN_OPTIONS", "UBSAN_OPTIONS") if key in env}
        self.commands.append(record)
        write_json(self.output / "commands.json", self.commands)
        started = time.monotonic()
        stdout, stderr, pending = b"", b"", None
        try:
            environment = dict(os.environ, **env) if env is not None else None
            completed = subprocess.run(arguments, cwd=working, env=environment, timeout=timeout or 120,
                                       stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
            stdout, stderr = completed.stdout, completed.stderr
            record.update(status="completed", returncode=completed.returncode)
            if check and completed.returncode:
                pending = subprocess.CalledProcessError(completed.returncode, arguments, stdout, stderr)
        except subprocess.TimeoutExpired as error:
            stdout, stderr, pending = error.stdout or b"", error.stderr or b"", error
            record.update(status="timeout", returncode=None, error=str(error))
        except OSError as error:
            pending = error
            record.update(status="launch_error", returncode=None, error=str(error))
        finally:
            (self.output / record["stdout"]).write_bytes(stdout)
            (self.output / record["stderr"]).write_bytes(stderr)
            record.update(elapsed_seconds=time.monotonic() - started, completed_at_utc=utc_now())
            write_json(self.output / "commands.json", self.commands)
        if pending is not None:
            raise pending
        return completed

    def record_source(self, repo, revision, path, destination=None):
        """Read committed files or verified retained snapshots; preserve their provenance mode."""
        repo = Path(repo).resolve()
        relative = PurePosixPath(path)
        if not re.fullmatch(r"[0-9a-fA-F]{40}|[0-9a-fA-F]{64}", revision):
            raise ValueError("Source snapshots require a full commit identifier")
        if relative.is_absolute() or ".." in relative.parts or not relative.parts:
            raise ValueError("Source paths must be relative to their repository")
        portable = None
        if self.source_archive is not None:
            data, portable = self.source_archive.lookup(self.case_alias, revision, relative.as_posix())
            resolved, blob = portable["commit"], portable["blob"]
        else:
            prefix = "source-" + str(len(self.sources) + 1).zfill(3)
            resolved = self.command(["git", "-C", repo, "rev-parse", "--verify", revision + "^{commit}"],
                                    prefix + "-commit").stdout.decode().strip()
            tree_path = resolved + ":" + relative.as_posix()
            blob = self.command(["git", "-C", repo, "rev-parse", "--verify", tree_path],
                                prefix + "-blob").stdout.decode().strip()
            data = self.command(["git", "-C", repo, "show", tree_path], prefix + "-content").stdout
        if destination is None:
            target = inside(self.output, Path("sources") / resolved / Path(path))
        else:
            target = Path(destination)
            if target.is_absolute():
                target = inside(self.output, target.relative_to(self.output))
            else:
                target = inside(self.output, target)
        if target.exists() and target.read_bytes() != data:
            raise ValueError("Refusing to overwrite a different source snapshot")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        record = {"repo": str(repo), "commit": resolved, "path": relative.as_posix(), "blob": blob,
                  "sha256": hashlib.sha256(data).hexdigest(), "snapshot": target.relative_to(self.output).as_posix()}
        if portable is not None:
            record.update(repo=portable["repo"], source_mode="portable_snapshot", portable_origin=portable["portable_origin"])
        self.sources.append(record)
        write_json(self.output / "source-manifest.json", self.sources)
        return record
