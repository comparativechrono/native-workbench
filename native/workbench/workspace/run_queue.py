"""Durable local run queue. Stored plans are immutable; reopening never runs work.

The lock is an operating-system lock, held for the host's lifetime. A leftover
lock filename is harmless and must never be deleted to steal another host's lock.
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import threading
from datetime import datetime, timezone

from file_io import replace_file

MAX_JOBS = 200
MAX_STATE_BYTES = 4 * 1024 * 1024
MAX_PLAN_BYTES = 16 * 1024 * 1024
STATES = {"preparing", "queued", "running", "completed", "failed", "cancelled", "interrupted"}
TERMINAL = {"completed", "failed", "cancelled", "interrupted"}
JOB_FIELDS = {"job_id", "run_id", "batch_id", "sample_id", "metadata", "name", "status", "folder",
              "plan_sha256", "files", "created_at", "started_at", "finished_at", "message"}


def utc():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def strict_json(data):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("Duplicate queue JSON field: " + key)
            result[key] = value
        return result
    def bad(value):
        raise ValueError("Non-finite queue JSON value")
    return json.loads(data, object_pairs_hook=pairs, parse_constant=bad)


def physical(path):
    if os.name == "nt":
        from pack_manager import filesystem_path
        return filesystem_path(path)
    return Path(path)


def ordinary_directory(path):
    path = Path(path)
    if not path.is_absolute() or not physical(path).is_dir():
        raise ValueError("Choose an existing absolute output folder.")
    for ancestor in (path, *path.parents):
        item = physical(ancestor)
        if item.is_symlink() or (hasattr(item, "is_junction") and item.is_junction()):
            raise ValueError("Queue folders must not use symbolic links or junctions.")
    return path


def _regular(path):
    item = physical(path)
    if item.is_symlink() or (hasattr(item, "is_junction") and item.is_junction()) or not item.is_file():
        raise ValueError("A queued plan file is missing or is a symbolic link: " + path.name)
    return item


def _read(path, maximum):
    item = _regular(path)
    if item.stat().st_size > maximum:
        raise ValueError("Queued plan file exceeds the supported size.")
    with item.open("rb") as stream:
        data = stream.read(maximum + 1)
    if len(data) > maximum:
        raise ValueError("Queued plan file exceeds the supported size.")
    return data


def _digest(path, cancel=None):
    checksum = hashlib.sha256()
    with _regular(path).open("rb") as stream:
        while part := stream.read(1024 * 1024):
            if cancel is not None and cancel.is_set():
                raise InterruptedError("Cancelled while verifying the queued plan.")
            checksum.update(part)
    return checksum.hexdigest()


def freeze_plan(plan):
    """Record the exact preparation files; do not make a second executable plan."""
    folder = ordinary_directory(plan.get("folder", ""))
    stored = strict_json(_read(folder / "plan.json", MAX_PLAN_BYTES))
    if stored != plan or not re.fullmatch(r"[0-9a-f]{64}", str(plan.get("sha256", ""))):
        raise ValueError("The prepared execution plan differs from its stored bytes.")
    value = copy.deepcopy(plan)
    claimed = value.pop("sha256")
    canonical = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    if hashlib.sha256(canonical.encode("utf-8")).hexdigest() != claimed:
        raise ValueError("The prepared execution plan checksum is invalid.")
    expected = {"plan.json", "graph.json", "workflow.cwl", "methods-planned.txt", "pipeline.svg", "performance.json"}
    if plan.get("references"):
        expected.add("reference-provenance.json")
    if {item.name for item in physical(folder).iterdir()} != expected:
        raise ValueError("The queued results folder contains unexpected files. Prepare a new run.")
    return {"folder": str(folder), "plan_sha256": claimed,
            "files": {name: _digest(folder / name) for name in sorted(expected)}}


def load_plan(job, cancel=None):
    """Refuse modified/partially started folders before handing them to Engine."""
    folder = ordinary_directory(job["folder"])
    if {item.name for item in physical(folder).iterdir()} != set(job["files"]):
        raise ValueError("The queued results folder changed or has already started. Prepare a new run.")
    for name, expected in job["files"].items():
        if _digest(folder / name, cancel) != expected:
            raise ValueError("A queued preparation file changed: " + name)
    plan = strict_json(_read(folder / "plan.json", MAX_PLAN_BYTES))
    if plan.get("folder") != job["folder"] or plan.get("sha256") != job["plan_sha256"]:
        raise ValueError("The queued execution plan identity changed.")
    # Engine independently verifies its canonical plan hash, CWL binding,
    # installed operation and external input hashes before actual consumption.
    return plan


class RunQueue:
    def __init__(self, data):
        self.data = ordinary_directory(data)
        self.path = self.data / "run-queue.json"
        self.lock = threading.RLock()
        self.write_lock = threading.Lock()
        self.jobs = []
        self.error = ""
        lock_path = self.data / "run-queue.lock"
        if physical(lock_path).is_symlink():
            raise ValueError("The run queue lock must not be a symbolic link.")
        self.file = physical(lock_path).open("a+b")
        self.owned = False
        try:
            if self.file.seek(0, 2) == 0:
                self.file.write(b"0")
                self.file.flush()
            self.file.seek(0)
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(self.file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.owned = True
        except OSError as error:
            self.file.close()
            self.error = "Another Native Workbench host owns this installation. This window is read-only; close the other window before reopening it to run or change stored data."
        try:
            if physical(self.path).exists() or physical(self.path).is_symlink():
                value = strict_json(_read(self.path, MAX_STATE_BYTES))
                self._validate(value)
                self.jobs = value["jobs"]
                changed = False
                for job in self.jobs:
                    if self.owned and job["status"] in ("preparing", "running"):
                        job.update(status="interrupted", finished_at=utc(),
                                   message="The previous session ended before completion. Inspect the results; prepare a new run to retry.")
                        changed = True
                if changed and self.owned:
                    self._write(self.jobs)
        except (ValueError, OSError, TypeError, KeyError, RecursionError) as error:
            # Do not replace uncertain state with an empty, apparently safe queue.
            self.jobs = []
            self.error = "The saved run queue cannot be used. Preserve user-data/run-queue.json for recovery. " + str(error)

    @staticmethod
    def _validate(value):
        if (not isinstance(value, dict) or set(value) != {"schema", "jobs"} or type(value["schema"]) is not int or value["schema"] != 1
                or not isinstance(value["jobs"], list) or len(value["jobs"]) > MAX_JOBS):
            raise ValueError("Invalid saved run queue.")
        identities = set()
        for job in value["jobs"]:
            if not isinstance(job, dict) or set(job) != JOB_FIELDS:
                raise ValueError("Invalid saved queue job fields.")
            for key in ("job_id", "run_id", "batch_id"):
                if not isinstance(job[key], str) or not re.fullmatch(r"[0-9a-f]{32}", job[key]):
                    raise ValueError("Invalid saved queue identity.")
            if job["run_id"] != job["job_id"] or job["job_id"] in identities or job["status"] not in STATES:
                raise ValueError("Invalid saved queue status or repeated identity.")
            identities.add(job["job_id"])
            for key in ("sample_id", "name", "folder", "created_at", "started_at", "finished_at", "message"):
                if not isinstance(job[key], str) or len(job[key]) > (30000 if key == "folder" else 2000):
                    raise ValueError("Invalid saved queue text.")
            wrapper = {"batchId": job["batch_id"], "sampleId": job["sample_id"], "metadata": job["metadata"]}
            if (not isinstance(job["metadata"], dict)
                    or len(json.dumps(wrapper, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")) > 16 * 1024):
                raise ValueError("Invalid queue sample metadata.")
            if not isinstance(job["files"], dict) or len(job["files"]) > 7:
                raise ValueError("Invalid queued file inventory.")
            allowed_files = {"plan.json", "graph.json", "workflow.cwl", "methods-planned.txt", "pipeline.svg", "performance.json", "reference-provenance.json"}
            for name, digest in job["files"].items():
                if name not in allowed_files or not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
                    raise ValueError("Invalid queued file checksum.")
            if job["status"] in ("queued", "running", "completed"):
                if (not Path(job["folder"]).is_absolute() or not isinstance(job["plan_sha256"], str)
                        or not re.fullmatch(r"[0-9a-f]{64}", job["plan_sha256"])
                        or not allowed_files - {"reference-provenance.json"} <= set(job["files"])):
                    raise ValueError("The saved job has no frozen execution plan.")
            elif not isinstance(job["plan_sha256"], str):
                raise ValueError("Invalid queue plan checksum.")

    def _write(self, jobs):
        value = {"schema": 1, "jobs": jobs}
        self._validate(value)
        raw = (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8")
        if len(raw) > MAX_STATE_BYTES or len(json.dumps(value, ensure_ascii=True)) > MAX_STATE_BYTES:
            raise ValueError("The run queue size limit has been reached.")
        if physical(self.path).is_symlink():
            raise ValueError("The saved run queue must not be a symbolic link.")
        tmp = self.path.with_name(self.path.name + "." + secrets.token_hex(16) + ".tmp")
        try:
            with physical(tmp).open("xb") as stream:
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
            replace_file(physical(tmp), physical(self.path))
            if os.name != "nt":
                descriptor = os.open(self.data, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
                try:
                    os.fsync(descriptor)
                finally:
                    os.close(descriptor)
        finally:
            physical(tmp).unlink(missing_ok=True)

    def ready(self):
        if self.error:
            raise ValueError(self.error)
        if not self.owned:
            raise ValueError("The run queue is closed.")

    def snapshot(self):
        with self.lock:
            return {"schema": 1, "jobs": copy.deepcopy(self.jobs), "error": self.error}

    def change(self, update):
        """Serialise disk commits without holding the state/read or app lock."""
        with self.write_lock:
            self.ready()
            with self.lock:
                jobs = copy.deepcopy(self.jobs)
            result = update(jobs)
            self._write(jobs)
            with self.lock:
                self.jobs = jobs
            return result

    def add(self, samples, batch_id):
        created = utc()
        new = []
        for sample in samples:
            identity = secrets.token_hex(16)
            new.append({"job_id": identity, "run_id": identity, "batch_id": batch_id,
                        "sample_id": sample.get("sampleId", ""), "metadata": copy.deepcopy(sample.get("metadata", {})),
                        "name": str(sample["graph"].get("name", "Analysis"))[:200], "status": "preparing",
                        "folder": "", "plan_sha256": "", "files": {}, "created_at": created,
                        "started_at": "", "finished_at": "", "message": "Preparing immutable execution plan."})
        def add(jobs):
            if len(jobs) + len(new) > MAX_JOBS:
                # Full completed evidence stays in result folders and run history.
                retained = [job for job in jobs if job["status"] not in TERMINAL]
                room = MAX_JOBS - len(new) - len(retained)
                if room < 0:
                    raise ValueError("The pending run queue limit (200) has been reached.")
                terminal = [job for job in jobs if job["status"] in TERMINAL]
                jobs[:] = retained + (terminal[-room:] if room else [])
            jobs.extend(new)
        self.change(add)
        return copy.deepcopy(new)

    def update(self, identities, **values):
        wanted = set(identities)
        def update(jobs):
            if not wanted <= {job["job_id"] for job in jobs}:
                raise ValueError("The selected queued job is no longer recorded.")
            for job in jobs:
                if job["job_id"] in wanted:
                    job.update(copy.deepcopy(values))
        self.change(update)

    def close(self):
        if self.owned:
            self.file.seek(0)
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(self.file.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.file.fileno(), fcntl.LOCK_UN)
            self.owned = False
            self.file.close()
