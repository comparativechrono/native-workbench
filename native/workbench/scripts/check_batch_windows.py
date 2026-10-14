#!/usr/bin/env python3
"""Validate one frozen native Windows batch/queue/index application candidate.

Uses known, synthetic Starter reads. No hosted service or network operation is
needed. Saved plans, native scientific outputs and actual Win32 dialogs are
separate assertions; observed CI display coverage is not human acceptance.
"""
from __future__ import annotations

import argparse
import copy
import csv
import ctypes
from ctypes import wintypes
from datetime import datetime, timezone
import gzip
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import threading
import time
import traceback

sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_references_windows import PrivateHost, require, sha256, write_json
from check_workspace_ui_windows import NativeUI
from check_readiness_windows import menu_command
from native_tree import NativeTree

VERSION = "0.13.0"
TERMINAL = {"completed", "failed", "cancelled", "interrupted"}


def read_json(path):
    path = Path(path)
    if os.name != "nt":
        return json.loads(path.read_text(encoding="utf-8"))
    # This independent observer must not deny DELETE sharing while the app
    # atomically replaces its queue receipt. The CRT-backed Path.open does not
    # grant that share mode and can either fail itself or obstruct the writer.
    # An open handle pins one complete old/new snapshot across a rename. There
    # is deliberately no retry that could conceal an application write error.
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                  ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    kernel.CreateFileW.restype = wintypes.HANDLE
    kernel.GetFileSizeEx.argtypes = [wintypes.HANDLE, ctypes.POINTER(ctypes.c_longlong)]
    kernel.GetFileSizeEx.restype = wintypes.BOOL
    kernel.ReadFile.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD,
                               ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p]
    kernel.ReadFile.restype = wintypes.BOOL
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL
    name = str(path.absolute())
    if not name.startswith("\\\\?\\"):
        name = "\\\\?\\UNC\\" + name[2:] if name.startswith("\\\\") else "\\\\?\\" + name
    handle = kernel.CreateFileW(name, 0x80000000, 0x1 | 0x2 | 0x4, None, 3, 0x80, None)
    if handle == ctypes.c_void_p(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        size = ctypes.c_longlong()
        if not kernel.GetFileSizeEx(handle, ctypes.byref(size)):
            raise ctypes.WinError(ctypes.get_last_error())
        require(0 <= size.value <= 64 * 1024 * 1024, "Native evidence JSON exceeds its bounded snapshot size.")
        pieces, remaining = [], size.value
        while remaining:
            buffer = ctypes.create_string_buffer(min(65536, remaining))
            count = wintypes.DWORD()
            if not kernel.ReadFile(handle, buffer, len(buffer), ctypes.byref(count), None):
                raise ctypes.WinError(ctypes.get_last_error())
            require(count.value > 0, "Native evidence snapshot ended before its declared size.")
            pieces.append(buffer.raw[:count.value])
            remaining -= count.value
        return json.loads(b"".join(pieces).decode("utf-8"))
    finally:
        kernel.CloseHandle(handle)


def check(report, description):
    report["checks"].append(description)
    print(json.dumps({"passed": len(report["checks"]), "check": description}), flush=True)


def until(description, predicate, timeout=180):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        found = predicate()
        if found:
            return found
        time.sleep(.05)
    raise TimeoutError(description)


def start_host(root, evidence, name):
    host = PrivateHost(root, evidence, name, offline=True)
    host.gate_queue_state_path = root / "user-data/run-queue.json"
    return host


def queue_state(host):
    # Public status intentionally omits sample metadata and file inventories. Read
    # the actual persistent receipt independently, without altering its bytes.
    state = host.call("queue/status")
    # Live status comes entirely from the production RPC. Detailed inventories
    # are needed only for frozen-plan assertions while the queue is idle; avoid
    # opening the writer's files during preparation or execution at all.
    if not state["preparing"] and not state["queue_running"]:
        persisted = read_json(host.gate_queue_state_path) if host.gate_queue_state_path.exists() else {"jobs": []}
        by_id = {job["job_id"]: job for job in persisted["jobs"]}
        state["jobs"] = [{**by_id.get(job["job_id"], {}), **job} for job in state["jobs"]]
    return state


def queue_ready(host):
    return until("Queue preparation did not finish.", lambda: (s if not s["preparing"] else None)
                 if (s := queue_state(host)) else None)


def wait_jobs(host, identities):
    def terminal():
        state = queue_state(host)
        jobs = [job for job in state["jobs"] if job["job_id"] in identities]
        return jobs if len(jobs) == len(identities) and all(job["status"] in TERMINAL for job in jobs) else None
    result = until("Queued jobs did not finish.", terminal, 300)
    until("Queue worker did not become idle after completion.", lambda: not queue_state(host)["queue_running"])
    return result


def add_job(host, graph, output):
    previous = {job["job_id"] for job in queue_state(host)["jobs"]}
    host.call("queue/add", {"graph": graph, "output_folder": str(output)})
    state = queue_ready(host)
    added = [job for job in state["jobs"] if job["job_id"] not in previous]
    require(len(added) == 1 and added[0]["status"] == "queued", "A new individual plan was not frozen and queued.")
    return added[0]


def frozen_hashes(job):
    folder = Path(job["folder"])
    observed = {name: sha256(folder / name) for name in job["files"]}
    require(observed == job["files"], "Queue does not bind its exact prepared companions.")
    plan = read_json(folder / "plan.json")
    require(plan["sha256"] == job["plan_sha256"], "Queue plan identity is inconsistent.")
    return observed


def sample_fixture(root, evidence, suffix="samples"):
    inputs = evidence / suffix
    inputs.mkdir()
    fixture = root / "examples/starter"
    profile = read_json(root / "workspace/starter-check-profile.json")
    for name, digest in profile["fixtures"].items():
        require(sha256(fixture / name) == digest, "Starter fixture is not its independently pinned scientific dataset.")
    for identity in ("sampleA", "sampleB"):
        for mate in (1, 2):
            shutil.copyfile(fixture / ("reads%d.fastq" % mate), inputs / ("%s-R%d.fastq" % (identity, mate)))
    table = inputs / "samples.csv"
    with table.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(["sample_id", "read1", "read2", "condition", "replicate"])
        writer.writerow(["sampleA", "sampleA-R1.fastq", "sampleA-R2.fastq", "synthetic", "1"])
        writer.writerow(["sampleB", "sampleB-R1.fastq", "sampleB-R2.fastq", "synthetic", "2"])
    return table


def bindings():
    return [{"sourceId": "input-1", "fieldId": "reads1", "column": "read1"},
            {"sourceId": "input-1", "fieldId": "reads2", "column": "read2"}]


def batch_preview(host, graph, table):
    parsed = host.call("sample/table", {"path": str(table)})
    result = host.call("sample/preview", {"graph": graph, "table_token": parsed["table_token"], "bindings": bindings(),
             "parameter_bindings": [{"nodeId": "step-1", "parameterId": "sample", "column": "sample_id"}]})
    require(result["valid"] and result["sampleCount"] == 2 and result.get("token"), "Explicit two-sample preview failed.")
    return parsed, result


def scientific_truth(root, job, expected_sample=None):
    require(job["status"] == "completed", "Queued scientific workflow failed: " + str(job))
    folder = Path(job["folder"])
    record, plan = read_json(folder / "run.json"), read_json(folder / "plan.json")
    require(record["success"] and record["status"] == "success" and record["planSha256"] == job["plan_sha256"],
            "Scientific record differs from its frozen queued plan.")
    require(record["workflowExport"]["sha256"] == sha256(folder / "workflow.cwl") and
            record["performance"]["sha256"] == sha256(folder / "performance.json"), "Result companion integrity was not retained.")
    sam = Path(record["outputs"]["step-1::sam"]["files"]["sam"])
    rows = [line.split("\t") for line in sam.read_text().splitlines() if line and not line.startswith("@")]
    require(len(rows) == 202 and all(int(row[1]) & 1 and int(row[1]) & 2 and not int(row[1]) & 4 and row[2] == "starter" for row in rows),
            "A batch member lost the expected 202 mapped proper-pair alignments.")
    if expected_sample:
        require(any("SM:" + expected_sample in line for line in sam.read_text().splitlines() if line.startswith("@RG")),
                "Explicit sample-to-read-group parameter mapping was lost.")
        require(plan.get("batch", {}).get("sampleId") == expected_sample and record.get("batch") == plan["batch"],
                "Frozen per-sample batch identity was not carried into the result.")
        columns = plan["batch"]["metadata"]["columns"]
        require(columns["condition"] == "synthetic" and columns["replicate"] == ("1" if expected_sample == "sampleA" else "2"),
                "Sample condition or replicate metadata was lost from the frozen plan.")
        cwl = read_json(folder / "workflow.cwl")["$graph"][0]
        require(json.loads(cwl["nw:batch"]) == plan["batch"] and
                json.loads(cwl["nw:execution"]["recordJson"])["batch"] == plan["batch"],
                "CWL did not retain the exact frozen and executed sample metadata.")
    bam = record["outputs"]["step-2::bam"]["files"]["bam"]
    decoded = subprocess.run([str(root / "packs/bam-0.4.0/bin/samtools.exe"), "view", bam], capture_output=True, timeout=60)
    require(decoded.returncode == 0 and len(decoded.stdout.decode().splitlines()) == 202, "Prepared batch BAM has the wrong record count.")
    with gzip.open(record["outputs"]["step-3::variants"]["files"]["variants"], "rt") as stream:
        variants = [line.split("\t") for line in stream.read().splitlines() if line and not line.startswith("#")]
    require(len(variants) == 1 and variants[0][:2] == ["starter", "1351"] and variants[0][3:5] == ["G", "A"] and
            variants[0][9].split(":")[variants[0][8].split(":").index("GT")] == "1/1", "A batch member changed known SNP truth.")
    for value in record["outputs"].values():
        require(all(sha256(path) == value["sha256"][name] for name, path in value["files"].items()), "Batch output hash mismatch.")
    return {"jobId": job["job_id"], "sampleId": expected_sample, "planSha256": job["plan_sha256"],
            "runSha256": sha256(folder / "run.json"), "alignmentCount": 202, "variant": "starter:1351 G>A GT=1/1",
            "outputHashes": {key: value["sha256"] for key, value in record["outputs"].items()}}


def host_checks(root, evidence, report):
    output = evidence / "queued-results"
    output.mkdir()
    host = start_host(root, evidence, "batch-host")
    try:
        require(host.call("init")["app_version"] == VERSION, "Incorrect frozen app version.")
        graph = host.call("example")["graph"]
        # Explicitly saved historical pins must remain selectable beside the new
        # candidate. Ordinary operations retain their published 0.4.0 graph.
        sys.path.insert(0, str(root / "workspace"))
        from catalog import load_catalog
        catalog = load_catalog(root)
        old = next(tool for tool in catalog["toolVersions"]["align/paired-end"] if tool["packVersion"] == "0.4.0")
        graph["nodes"][0]["pin"] = {key: old[key] for key in ("packId", "packVersion", "manifestSha256")}
        parsed, preview = batch_preview(host, graph, sample_fixture(root, evidence))
        bad = host.call("sample/preview", {"graph": graph, "table_token": parsed["table_token"], "bindings": []})
        require(not bad["valid"] and not bad.get("token"), "Unmapped sample reads were guessed or queued.")
        require(not list(output.iterdir()) and not queue_state(host)["jobs"], "Sample preview prepared or executed an unapproved batch.")
        require([row["sampleId"] for row in preview["samples"]] == ["sampleA", "sampleB"] and
                parsed["rows"][1]["replicate"] == "2", "Sample preview changed row identity or metadata.")
        write_json(evidence / "sample-preview.json", preview)
        check(report, "CSV preview requires explicit paired-read and sample-parameter mappings, retains metadata/shared reference and creates no plans or runs before Queue.")
        host.call("queue/add-batch", {"token": preview["token"], "output_folder": str(output)})
        state = queue_ready(host)
        require(state["paused"] and len(state["jobs"]) == 2 and all(job["status"] == "queued" for job in state["jobs"]),
                "Batch did not freeze all rows before a separate Start queued action.")
        jobs = state["jobs"]
        saved = {job["job_id"]: frozen_hashes(job) for job in jobs}
        for job in jobs:
            plan = read_json(Path(job["folder"]) / "plan.json")
            require(plan["graph"]["nodes"][0]["pin"]["packVersion"] == "0.4.0", "Adding new aligner version upgraded a saved batch pin.")
        host.call("model", {"action": "rename_graph", "payload": {"name": "Edited future workflow"}})
        require(all(frozen_hashes(job) == saved[job["job_id"]] for job in jobs), "Editing the draft changed queued plans.")
        host.close()
        host = start_host(root, evidence, "batch-reopened-host")
        host.call("init")
        reopened = queue_state(host)
        require(reopened["paused"] and not reopened["scheduled"] and not reopened["active_job"] and
                [job["job_id"] for job in reopened["jobs"]] == [job["job_id"] for job in jobs] and
                all(job["status"] == "queued" and frozen_hashes(job) == saved[job["job_id"]] for job in reopened["jobs"]),
                "Reopened queue auto-started or altered frozen plans/pins.")
        check(report, "Two immutable plans and exact companion hashes survive editing and clean shutdown/reopen, remain paused and retain historical align 0.4.0 pins beside 0.4.1.")
        host.call("queue/start")
        completed = wait_jobs(host, {job["job_id"] for job in jobs})
        report["batchScience"] = [scientific_truth(root, job, job["sample_id"]) for job in completed]
        check(report, "Explicit Start executes both frozen samples serially with independent read groups, 202 proper-pair alignments, known homozygous SNP and verified CWL/performance/output provenance.")
        combined_checks(host, completed, catalog, output, evidence, report)
        corruption_checks(host, graph, output, evidence, report)
        cancellation_checks(host, graph, output, root, evidence, report)
        index_checks(host, graph, output, root, evidence, report, catalog)
        receipt_reader_checks(host, root, output, evidence, report, catalog)
        setup = host.call("setup/status")
        require((root / "user-data/run-queue.json").is_file() and setup["offered"] is False,
                "Persisted queue/results must be recognised as a returning installation.")
        report["returningInstallation"] = {"persistentQueuePresent": True, "setupOffered": setup["offered"],
                                            "reason": "The host gate has already created real queue, run and reference-index records."}
        report["networkSocketOperationsDeniedForHost"] = True
    finally:
        try:
            host.close()
        finally:
            # Capture every outcome only after the exact host has relinquished
            # its files. These are synthetic gate records, never user history.
            # This preserves an earlier preparation/execution failure even when
            # no per-run run.json was created and no later assertion was reached.
            for name in ("run-queue.json", "runs.json"):
                source = root / "user-data" / name
                if source.exists():
                    try:
                        target = evidence / ("host-final-" + name)
                        write_json(target, read_json(source))
                        report.setdefault("hostFinalReceipts", []).append({"file": target.name, "sha256": sha256(target)})
                    except Exception as capture_error:
                        report.setdefault("hostFinalReceiptErrors", []).append({"file": name, "error": str(capture_error)})


class HeldReceiptReader:
    """Real Windows read handle, including DELETE sharing; no app patch."""
    def __init__(self, path):
        self.kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        self.kernel.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                          ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
        self.kernel.CreateFileW.restype = wintypes.HANDLE
        self.kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        self.kernel.CloseHandle.restype = wintypes.BOOL
        name = str(Path(path).absolute())
        if not name.startswith("\\\\?\\"):
            name = "\\\\?\\UNC\\" + name[2:] if name.startswith("\\\\") else "\\\\?\\" + name
        self.handle = self.kernel.CreateFileW(name, 0x80000000, 7, None, 3, 0x80, None)
        if self.handle == ctypes.c_void_p(-1).value:
            raise ctypes.WinError(ctypes.get_last_error())
        self.lock = threading.Lock()
        self.released = None
        self.error = None

    def close(self):
        with self.lock:
            if self.handle is not None:
                if not self.kernel.CloseHandle(self.handle):
                    self.error = str(ctypes.WinError(ctypes.get_last_error()))
                self.handle = None
                self.released = time.monotonic()


def receipt_reader_checks(host, root, output, evidence, report, catalog):
    # These are real external handles on the unchanged packaged host's queue
    # and run history. No methods are wrapped and no runtime module is patched.
    # Ordinary Windows rename can be blocked even by a DELETE-sharing reader.
    metrics = []
    for number in (1, 2):
        path = evidence / ("receipt-reader-metric-%d.txt" % number)
        path.write_text("Synthetic receipt-reader check\t%d\n" % number, encoding="utf-8")
        metrics.append(path)
    tool = catalog["tools"]["builtin/report"]
    graph = {"schema": 1, "name": "Receipt reader overlap", "nextSource": 3, "nextNode": 2,
             "sources": [{"id": "input-%d" % number, "type": "metrics", "label": "Metric %d" % number,
                          "files": {"metrics": str(path)}} for number, path in enumerate(metrics, 1)],
             "nodes": [{"id": "step-1", "tool": "builtin/report", "label": "Receipt overlap report",
                        "inputs": {"metrics": ["input-1", "input-2"]}, "params": copy.deepcopy(tool["defaults"]),
                        "pin": {key: tool[key] for key in ("packId", "packVersion", "manifestSha256")}}]}
    queue_path, history_path = root / "user-data/run-queue.json", root / "user-data/runs.json"
    observation = {"applicationPatched": False, "sharing": ["READ", "WRITE", "DELETE"]}
    report["receiptReaderOverlap"] = observation
    require(not host.call("queue/status")["queue_running"], "Receipt overlap check requires an idle host.")
    held = HeldReceiptReader(queue_path)
    started = time.monotonic()
    release = threading.Timer(.2, held.close)
    release.start()
    try:
        added = host.call("queue/add", {"graph": graph, "output_folder": str(output)})["added"]
        elapsed = time.monotonic() - started
        require(held.released is not None and held.error is None and elapsed >= .18,
                "Queue admission did not overlap the briefly held external receipt reader.")
        observation["queueBriefReader"] = {"releasedAfterSeconds": held.released - started,
                                            "admissionSeconds": elapsed, "added": added}
    finally:
        release.cancel()
        release.join(timeout=2)
        held.close()
    prepared = queue_ready(host)
    job = next(job for job in prepared["jobs"] if job["job_id"] in added)
    require(job["status"] == "queued", "Queue preparation did not commit after its external reader closed: " + json.dumps(job))
    observation["frozenCompanions"] = frozen_hashes(job)

    held = HeldReceiptReader(history_path)
    started = time.monotonic()
    try:
        host.call("queue/start")
        time.sleep(.12)
        active = host.call("queue/status")
        observation["historyWhileHeld"] = {"queueRunning": active["queue_running"], "activeJob": active["active_job"],
                                            "runFilePresent": (Path(job["folder"]) / "run.json").exists()}
        require(active["queue_running"] and active["active_job"] == job["job_id"] and
                not observation["historyWhileHeld"]["runFilePresent"],
                "History receipt reader did not overlap initial execution commit: " + json.dumps(active))
    finally:
        held.close()
        observation["historyReaderReleasedAfterSeconds"] = held.released - started
    require(held.error is None, "History receipt reader did not close cleanly.")
    finished = wait_jobs(host, set(added))[0]
    observation["completedJob"] = finished
    require(finished["status"] == "completed", "Queued report failed after its history reader closed: " + json.dumps(finished))
    run = read_json(Path(job["folder"]) / "run.json")
    require(run["success"] and run["outputs"], "Receipt overlap report has no successful execution record.")
    for value in run["outputs"].values():
        require(all(sha256(path) == value["sha256"][name] for name, path in value["files"].items()),
                "Receipt overlap report changed its recorded outputs.")

    before = read_json(queue_path)
    before_hash = sha256(queue_path)
    before_folders = {path.name for path in output.iterdir()}
    held = HeldReceiptReader(queue_path)
    started = time.monotonic()
    error = None
    try:
        try:
            host.call("queue/add", {"graph": graph, "output_folder": str(output)})
        except ValueError as failure:
            error = str(failure)
        elapsed = time.monotonic() - started
        observation["persistentQueueReader"] = {"error": error, "admissionSeconds": elapsed,
                                                "beforeSha256": before_hash, "afterSha256": sha256(queue_path)}
        require(error is not None and "run-queue.json" in error and
                any("[WinError %d]" % code in error for code in (5, 32, 33)) and .45 <= elapsed < 5,
                "A persistent queue reader did not produce a bounded, explicit Windows sharing failure: " + str(error))
        require(read_json(queue_path) == before and sha256(queue_path) == before_hash and
                {path.name for path in output.iterdir()} == before_folders,
                "Failed queue admission changed an existing receipt or created an uncommitted plan.")
        status = host.call("queue/status")
        require(not status["preparing"] and not status["queue_running"] and not status["error"] and
                [job["job_id"] for job in status["jobs"]] == [job["job_id"] for job in before["jobs"]],
                "A failed queue commit mutated in-memory jobs or left the host busy.")
    finally:
        held.close()
        write_json(evidence / "receipt-reader-overlap.json", observation)
    require(held.error is None, "Persistent receipt reader did not close cleanly.")
    require(not list((root / "user-data").glob("run-queue.json.*.tmp")), "Failed queue commit left temporary receipt files.")
    check(report, "Exact packaged queue and history commits survive brief real external read handles; a persistent handle exhausts the bounded Windows wait with an explicit sharing error, preserves existing jobs/bytes, creates no plan and leaves the host responsive.")


def combined_checks(host, completed, catalog, output, evidence, report):
    table = evidence / "combined-reports.csv"
    with table.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(["sample_id", "report", "condition"])
        for job in completed:
            record = read_json(Path(job["folder"]) / "run.json")
            metric = next(iter(record["outputs"]["step-4::statistics"]["files"].values()))
            writer.writerow([job["sample_id"], metric, "synthetic"])
    tool = catalog["tools"]["builtin/report"]
    graph = {"schema": 1, "name": "Explicit combined sample reports", "sources": [], "nextSource": 1, "nextNode": 2,
             "nodes": [{"id": "step-1", "tool": "builtin/report", "label": "Combined reports", "inputs": {"metrics": []},
                        "params": copy.deepcopy(tool["defaults"]),
                        "pin": {key: tool[key] for key in ("packId", "packVersion", "manifestSha256")}}]}
    parsed = host.call("sample/table", {"path": str(table)})
    preview = host.call("sample/preview", {"graph": graph, "table_token": parsed["table_token"], "bindings": [], "mode": "combined",
                                         "combined_target": {"nodeId": "step-1", "portId": "metrics", "column": "report"}})
    require(preview["valid"] and len(preview["samples"]) == 1 and preview["samples"][0]["sampleId"] == "combined",
            "Explicit many-valued report binding did not produce one combined job.")
    added = host.call("queue/add-batch", {"token": preview["token"], "output_folder": str(output)})["added"]
    queue_ready(host)
    host.call("queue/start")
    job = wait_jobs(host, set(added))[0]
    observed = {key: job[key] for key in ("job_id", "status", "message", "folder")}
    report["combinedJob"] = observed
    write_json(evidence / "combined-job.json", observed)
    write_json(evidence / "combined-run-state.json", host.call("run/get", {"run_id": job["job_id"]}))
    require(job["status"] == "completed", "Explicit combined report job failed: " + json.dumps(observed))
    record = read_json(Path(job["folder"]) / "run.json")
    plan = read_json(Path(job["folder"]) / "plan.json")
    require(len(plan["graph"]["sources"]) == 2 and record["batch"] == plan["batch"] and
            record["batch"]["metadata"]["mode"] == "combined" and len(record["batch"]["metadata"]["rows"]) == 2,
            "Combined report collapsed sample identities or dropped its explicit mode/provenance.")
    for value in record["outputs"].values():
        require(all(sha256(path) == value["sha256"][name] for name, path in value["files"].items()), "Combined report output integrity failed.")
    report["combinedReports"] = {"jobId": job["job_id"], "sourceCount": 2, "mode": "combined", "planSha256": job["plan_sha256"]}
    check(report, "Explicit combined-report mode maps two separately named sample reports into one declared many-valued report port, retains all row metadata and verifies resulting files without pooling biological reads.")


def corruption_checks(host, graph, output, evidence, report):
    changed = copy.deepcopy(graph)
    filename = evidence / "changed-input.fastq"
    shutil.copyfile(Path(graph["sources"][0]["files"]["reads1"]), filename)
    changed["sources"][0]["files"]["reads1"] = str(filename)
    altered_input = add_job(host, changed, output)
    altered_plan = add_job(host, graph, output)
    filename.write_bytes(filename.read_bytes() + b"\n")
    companion = Path(altered_plan["folder"]) / "methods-planned.txt"
    companion.write_text(companion.read_text(encoding="utf-8") + "\nChanged after queue.\n", encoding="utf-8")
    host.call("queue/start")
    failed = wait_jobs(host, {altered_input["job_id"]})
    until("Failed queue did not settle paused.", lambda: queue_state(host)["paused"])
    require(next(job for job in queue_state(host)["jobs"] if job["job_id"] == altered_plan["job_id"])["status"] == "queued",
            "Failure did not pause the remaining frozen queue.")
    host.call("queue/start")
    failed.extend(wait_jobs(host, {altered_plan["job_id"]}))
    observed = [{key: job[key] for key in ("job_id", "status", "message", "folder")} for job in failed]
    report["failClosed"] = observed
    write_json(evidence / "corruption-queue-results.json", observed)
    write_json(evidence / "corruption-persisted-queue.json", read_json(host.gate_queue_state_path))
    history_path = host.gate_queue_state_path.with_name("runs.json")
    if history_path.exists():
        history = read_json(history_path)
        identities = {job["job_id"] for job in failed}
        write_json(evidence / "corruption-persisted-history.json", [run for run in history if run.get("run_id") in identities])
    for job in failed:
        write_json(evidence / ("corruption-run-state-" + job["job_id"] + ".json"),
                   host.call("run/get", {"run_id": job["job_id"]}))
    require(all(job["status"] == "failed" for job in failed), "Changed input or queued companion did not fail closed: " + json.dumps(observed))
    input_failure = next(job for job in failed if job["job_id"] == altered_input["job_id"])
    companion_failure = next(job for job in failed if job["job_id"] == altered_plan["job_id"])
    require("queued preparation file changed: methods-planned.txt" in companion_failure["message"].lower(),
            "Corrupt companion failed for an unexpected reason: " + json.dumps(observed))
    require(not (Path(altered_plan["folder"]) / "run.json").exists(), "Corrupt prepared companion reached execution.")
    run_path = Path(altered_input["folder"]) / "run.json"
    require(run_path.is_file(), "Changed-input job did not enter the expected engine integrity check: " + json.dumps(observed))
    run = read_json(run_path)
    require(not run["success"] and not run["outputs"] and
            any("external input changed after the plan was frozen" in node.get("message", "").lower() for node in run["nodes"]),
            "Changed sample was not rejected by the intended frozen input-integrity check: " + json.dumps(observed))
    check(report, "Changing an input after freezing or altering a prepared companion fails closed; neither produces accepted outputs and corrupt preparation never enters execution.")


def cancellation_checks(host, graph, output, root, evidence, report):
    long_graph = copy.deepcopy(graph)
    long_graph["nodes"][0]["params"]["threads"] = "1"
    # An explicit synthetic repetition keeps the real native workflow active
    # long enough to observe and cancel it; it is not a throughput benchmark.
    for mate in (1, 2):
        path = evidence / ("cancel-R%d.fastq" % mate)
        source = (root / "examples/starter" / ("reads%d.fastq" % mate)).read_bytes()
        with path.open("wb") as stream:
            for _ in range(1200):
                stream.write(source)
        long_graph["sources"][0]["files"]["reads%d" % mate] = str(path)
    first, second = add_job(host, long_graph, output), add_job(host, graph, output)
    frozen = frozen_hashes(first)
    host.call("queue/start")
    def running():
        state = queue_state(host)
        observed = next(job for job in state["jobs"] if job["job_id"] == first["job_id"])
        if observed["status"] in TERMINAL:
            details = {key: observed[key] for key in ("job_id", "status", "message", "folder")}
            report["cancellationEarlyOutcome"] = details
            write_json(evidence / "cancellation-early-job.json", details)
            write_json(evidence / "cancellation-early-run-state.json", host.call("run/get", {"run_id": first["job_id"]}))
            raise AssertionError("Queued cancellation fixture terminated before its native bridge was observed: " + json.dumps(details))
        return state if state["active_job"] == first["job_id"] and list(Path(first["folder"]).glob("*/bridge-request.json")) else None
    until("Cancellable queued job did not reach its native bridge.", running)
    host.call("example")
    edited = host.call("model", {"action": "rename_graph", "payload": {"name": "Next analysis edited during frozen execution"}})
    require(edited["graph"]["name"] == "Next analysis edited during frozen execution" and
            sha256(Path(first["folder"]) / "plan.json") == frozen["plan.json"], "Active draft editing changed execution or was blocked.")
    host.call("queue/cancel", {"job_id": first["job_id"]})
    cancelled = wait_jobs(host, {first["job_id"]})[0]
    require(cancelled["status"] == "cancelled", "Active queued job did not record cancellation.")
    state = queue_state(host)
    waiting = next(job for job in state["jobs"] if job["job_id"] == second["job_id"])
    require(state["paused"] and not state["scheduled"] and waiting["status"] == "queued" and
            not (Path(second["folder"]) / "run.json").exists(), "Cancellation automatically started the next queued job.")
    host.call("queue/start")
    next_job = wait_jobs(host, {second["job_id"]})[0]
    report["afterCancellationScience"] = scientific_truth(root, next_job)
    report["cancellation"] = {"jobId": first["job_id"], "status": cancelled["status"], "nextRequiredExplicitStart": True,
                               "nativeBridgeRequestObserved": True, "draftEditingPreservedPlan": True}
    check(report, "During native execution the draft remains editable without mutating the frozen plan; Cancel stops that job, pauses its successor, and explicit Start runs the successor successfully.")


def index_checks(host, graph, output, root, evidence, report, catalog):
    def pinned(identity):
        tool = next(tool for tool in catalog["toolVersions"][identity] if tool["packVersion"] == "0.4.1")
        return tool, {key: tool[key] for key in ("packId", "packVersion", "manifestSha256")}
    builder, builder_pin = pinned("align/build-sr-index")
    consumer, consumer_pin = pinned("align/paired-end-indexed")
    indexed = copy.deepcopy(graph)
    indexed["nextNode"] = 7
    indexed["nodes"][0].update(tool=consumer["id"], pin=consumer_pin)
    indexed["nodes"][0]["inputs"].pop("reference")
    indexed["nodes"][0]["inputs"]["index"] = ["step-6::index"]
    indexed["nodes"].insert(0, {"id": "step-6", "label": "Explicit reusable short-read index", "tool": builder["id"],
                              "pin": builder_pin, "params": copy.deepcopy(builder["defaults"]), "inputs": {"reference": ["input-2"]}})
    def run(selected):
        job = add_job(host, selected, output)
        host.call("queue/start")
        job = wait_jobs(host, {job["job_id"]})[0]
        return job, read_json(Path(job["folder"]) / "run.json")
    first, first_record = run(indexed)
    report["indexedScience"] = scientific_truth(root, first)
    built = next(node for node in first_record["nodes"] if node["id"] == "step-6")["referenceIndex"]
    require(built["action"] == "built" and built["identity"]["pack"]["packVersion"] == "0.4.1", "First explicit index did not execute the pinned builder.")
    second, second_record = run(indexed)
    scientific_truth(root, second)
    reused = next(node for node in second_record["nodes"] if node["id"] == "step-6")["referenceIndex"]
    require(reused["action"] == "reused" and reused["key"] == built["key"] and reused["files"] == built["files"] and
            reused["receiptSha256"] == built["receiptSha256"], "Repeated matching reference did not reuse exact verified index bytes.")
    metric = next(step for step in read_json(Path(second["folder"]) / "performance.json")["steps"] if step["id"] == "step-6")
    require(not metric["backendMetrics"]["available"] and metric["backendMetrics"]["reason"] == "reference_index_reused_without_native_command" and
            not list(Path(next(node for node in second_record["nodes"] if node["id"] == "step-6")["folder"]).glob("**/bridge-request.json")), "A reused index claims or ran new native indexing.")
    ordinary_job, ordinary_record = run(graph)
    scientific_truth(root, ordinary_job)
    def alignments(record):
        sam = Path(record["outputs"]["step-1::sam"]["files"]["sam"])
        return sorted(line for line in sam.read_text().splitlines() if line and not line.startswith("@"))
    require(alignments(first_record) == alignments(second_record) == alignments(ordinary_record),
            "Explicitly indexed minimap2 output differs from ordinary short-read alignment records.")
    receipt_path = root / "user-data/reference-indexes/v1" / built["key"] / "index.json"
    require(sha256(receipt_path) == built["receiptSha256"], "Result receipt hash does not match verified local inventory.")
    changed_reference = copy.deepcopy(indexed)
    changed_fasta = evidence / "equivalent-reference.fa"
    changed_fasta.write_bytes((root / "examples/starter/reference.fa").read_bytes() + b"\n")
    changed_reference["sources"][1]["files"]["reference"] = str(changed_fasta)
    third, third_record = run(changed_reference)
    scientific_truth(root, third)
    changed = next(node for node in third_record["nodes"] if node["id"] == "step-6")["referenceIndex"]
    changed_parameters = copy.deepcopy(indexed)
    changed_parameters["nodes"][0]["params"]["threads"] = "1"
    fourth, fourth_record = run(changed_parameters)
    scientific_truth(root, fourth)
    options = next(node for node in fourth_record["nodes"] if node["id"] == "step-6")["referenceIndex"]
    require(changed["action"] == options["action"] == "built" and len({built["key"], changed["key"], options["key"]}) == 3,
            "Changed reference content or declared indexing parameters reused a different identity.")
    report["referenceIndexes"] = {"first": built, "second": reused, "changedReference": changed, "changedParameters": options,
                                   "alignmentRecordEquivalence": True, "indexMemoryMetricsOnReuse": "unavailable; no new index command"}
    check(report, "Real minimap2 index build/reuse binds exact references, pack/executable/options and inventory; indexed and ordinary SAM records are identical, changed reference/options create distinct indexes, and reuse reports no invented native counters.")
    stored_index = receipt_path.parent / "files" / next(iter(built["files"]))
    original = stored_index.read_bytes()
    try:
        stored_index.write_bytes(original + b"corruption")
        corrupt, record = run(indexed)
        require(corrupt["status"] == "failed" and not record["outputs"] and
                "integrity" in json.dumps(record).lower(), "Corrupted cache entry was consumed, rebuilt silently, or accepted.")
    finally:
        stored_index.write_bytes(original)
    job = add_job(host, indexed, output)
    binary = root / builder["packFolder"] / next(item["path"] for item in builder["executables"] if item["id"] == "minimap2")
    executable = binary.read_bytes()
    try:
        binary.write_bytes(executable + b"tampered binary")
        host.call("queue/start")
        rejected = wait_jobs(host, {job["job_id"]})[0]
        record = read_json(Path(rejected["folder"]) / "run.json")
        require(rejected["status"] == "failed" and not record["outputs"] and "integrity" in json.dumps(record).lower(),
                "Cache hit bypassed integrity verification for changed executable bytes.")
    finally:
        binary.write_bytes(executable)
    require(sha256(binary) == next(item["sha256"] for item in builder["executables"] if item["id"] == "minimap2"),
            "Native gate did not restore the unchanged candidate executable.")
    check(report, "Corrupt stored index and a modified builder executable both fail closed even when a matching cache identity exists; verified candidate bytes are restored after the negative checks.")


class NativeList:
    """Read documented native ListView data; real pointer input selects rows."""
    def __init__(self, ui, hwnd):
        self.ui, self.hwnd = ui, hwnd
        self.memory = NativeTree(ui.user, ui.send, ui.process.pid, hwnd)

    def count(self):
        return self.ui.send(self.hwnd, 0x1004)

    def text(self, row, column=0):
        class Item(ctypes.Structure):
            _fields_ = [("mask", wintypes.UINT), ("iItem", ctypes.c_int), ("iSubItem", ctypes.c_int),
                        ("state", wintypes.UINT), ("stateMask", wintypes.UINT), ("pszText", ctypes.c_void_p),
                        ("cchTextMax", ctypes.c_int), ("iImage", ctypes.c_int), ("lParam", wintypes.LPARAM),
                        ("iIndent", ctypes.c_int), ("iGroupId", ctypes.c_int), ("cColumns", wintypes.UINT),
                        ("puColumns", ctypes.c_void_p), ("piColFmt", ctypes.c_void_p), ("iGroup", ctypes.c_int)]
        offset, size = ctypes.sizeof(Item), 4096
        def payload(address):
            return bytes(Item(iItem=row, iSubItem=column, pszText=address + offset, cchTextMax=size // 2)) + bytes(size)
        raw = self.memory._buffer(payload, offset + size,
                                 lambda address: self.ui.send(self.hwnd, 0x1073, row, address) >= 0)
        return raw[offset:].decode("utf-16-le").split("\0", 1)[0]

    def click(self, row):
        require(0 <= row < self.count(), "Selected native list row does not exist.")
        self.ui.send(self.hwnd, 0x1013, row, 0)  # LVM_ENSUREVISIBLE.
        raw = self.memory._buffer(bytes(wintypes.RECT(0, 0, 0, 0)), ctypes.sizeof(wintypes.RECT),
                                  lambda address: self.ui.send(self.hwnd, 0x100E, row, address))
        rect = wintypes.RECT.from_buffer_copy(raw)
        point = wintypes.POINT(rect.left + 30, (rect.top + rect.bottom) // 2)
        self.ui.user.ClientToScreen(self.hwnd, ctypes.byref(point))
        self.ui.click_at(point.x, point.y, expected=self.hwnd)
        self.ui.wait("native list row selected", lambda: self.ui.send(self.hwnd, 0x100C, -1, 2) == row)


def gui_checks(root, evidence, report):
    ui = NativeUI(root, evidence)
    report["nativeGUILaunched"] = True
    try:
        def window(title):
            return next((handle for handle in ui.windows() if ui.label(handle) == title), None)
        def setup():
            return next((handle for handle in ui.windows() if ui.label(handle, True) == "WorkbenchToolSetup0100"), None)
        # Host/scientific checks deliberately precede this GUI check in the
        # same extraction so its verified indexes and durable jobs can be used.
        # Real persisted records make this a returning installation; fresh
        # welcome behavior remains independently required by the library gate.
        require(report["returningInstallation"]["setupOffered"] is False,
                "Native batch UI gate requires its recorded returning-installation state.")
        ui.wait("returning native workspace ready", lambda: ui.user.IsWindowEnabled(ui.child(410)) and ui.library().tools())
        require(not setup(), "A returning installation unexpectedly opened first-launch Tool Setup.")
        ui.fit_window(1280, 900)
        ui.post(ui.main, 0x0111, 302)
        ui.wait("native example loaded", lambda: "Starter example" in ui.label(ui.child(101)))
        ui.click_button(424)
        ui.wait("native Samples window", lambda: window("Samples · Native Workbench"))
        samples = window("Samples · Native Workbench")
        table = sample_fixture(root, evidence, "gui-samples")
        ui.set_text(ui.child(801, samples), str(table))
        ui.send(ui.child(803, samples), 0x00F5)
        targets = NativeList(ui, ui.child(804, samples))
        sample_rows = NativeList(ui, ui.child(808, samples))
        ui.wait("loaded two native sample rows", lambda: sample_rows.count() == 2 and targets.count() >= 3)
        mappings = [(row, targets.text(row)) for row in range(targets.count())]
        def choose_column(target_fragment, column):
            candidates = [row for row, label in mappings if target_fragment in label]
            require(len(candidates) == 1, "Ambiguous/missing native mapping target: " + target_fragment + " " + str(mappings))
            row = candidates[0]
            targets.click(row)
            combo = ui.child(805, samples)
            choices = []
            for index in range(ui.send(combo, 0x0146)):
                text = ctypes.create_unicode_buffer(4096)
                ui.send(combo, 0x0148, index, ctypes.addressof(text))
                choices.append(text.value)
            require(column in choices, "Imported column not offered by the native mapping chooser.")
            ui.send(combo, 0x014E, choices.index(column), 0)
            ui.send(samples, 0x0111, 805 | (1 << 16), combo)
            ui.wait("explicit native column mapping committed", lambda: targets.text(row, 1) == column)
        choose_column("read1", "read1")
        choose_column("read2", "read2")
        choose_column("step-1 · Sample name", "sample_id")
        output = evidence / "gui-batch-results"
        output.mkdir()
        ui.set_text(ui.child(810, samples), str(output))
        before = {job["job_id"] for job in read_json(root / "user-data/run-queue.json")["jobs"]}
        ui.send(ui.child(807, samples), 0x00F5)
        ui.wait("native reviewed batch valid", lambda: ui.user.IsWindowEnabled(ui.child(812, samples)) and
                all(sample_rows.text(row, 1) == "Valid" for row in range(2)))
        require(not list(output.iterdir()), "Native Preview executed or froze a batch before Queue.")
        report["captures"].append(ui.capture("samples-native-preview.bmp", samples))
        write_json(evidence / "samples-native-controls.json", ui.controls(samples))
        ui.send(ui.child(812, samples), 0x00F5)
        def added_jobs():
            state = read_json(root / "user-data/run-queue.json")
            jobs = [job for job in state["jobs"] if job["job_id"] not in before]
            if state.get("error") or any(job["status"] in TERMINAL for job in jobs):
                write_json(evidence / "gui-preparation-failure.json", state)
                observed = [{key: job[key] for key in ("job_id", "status", "message", "folder")} for job in jobs]
                raise AssertionError("Native sample preparation failed before explicit Start: " +
                                     json.dumps({"error": state.get("error"), "jobs": observed}))
            return jobs if len(jobs) == 2 and all(job["status"] == "queued" for job in jobs) else None
        ui.wait("native batch frozen without starting", added_jobs)
        added = added_jobs()
        ui.send(ui.child(813, samples), 0x00F5)
        ui.wait("Samples closed", lambda: not window("Samples · Native Workbench"))
        already_open = window("Analysis queue · Native Workbench")
        if already_open:
            ui.send(ui.child(909, already_open), 0x00F5)
            ui.wait("automatically shown queue closed", lambda: not window("Analysis queue · Native Workbench"))
        ui.click_button(425)
        ui.wait("native Queue window", lambda: window("Analysis queue · Native Workbench"))
        queue = window("Analysis queue · Native Workbench")
        listing = NativeList(ui, ui.child(901, queue))
        ui.wait("native queue lists prepared samples", lambda: listing.count() == len(read_json(root / "user-data/run-queue.json")["jobs"]))
        # Use persisted stable identities to find their current display rows; the
        # native list preserves store order and never sorts rows independently.
        stored = read_json(root / "user-data/run-queue.json")["jobs"]
        row = next(index for index, job in enumerate(stored) if job["job_id"] == added[0]["job_id"])
        listing.click(row)
        ui.wait("native queue shows frozen identity", lambda: added[0]["plan_sha256"] in ui.label(ui.child(902, queue)))
        report["captures"].append(ui.capture("queue-native-paused.bmp", queue))
        write_json(evidence / "queue-native-controls.json", ui.controls(queue))
        require(not any((Path(job["folder"]) / "run.json").exists() for job in added), "Opening Queue automatically began analysis.")
        ui.send(ui.child(906, queue), 0x00F5)
        ui.wait("native queued cancellation recorded", lambda: next(job for job in read_json(root / "user-data/run-queue.json")["jobs"] if job["job_id"] == added[0]["job_id"])["status"] == "cancelled")
        ui.wait("native Start queued available", lambda: ui.user.IsWindowEnabled(ui.child(904, queue)))
        ui.send(ui.child(904, queue), 0x00F5)
        def finished():
            job = next(job for job in read_json(root / "user-data/run-queue.json")["jobs"] if job["job_id"] == added[1]["job_id"])
            return job if job["status"] in TERMINAL else None
        job = until("Native Start queued did not finish selected sample.", finished, 240)
        report["nativeQueuedScience"] = scientific_truth(root, job, "sampleB")
        report["captures"].append(ui.capture("queue-native-completed.bmp", queue))
        ui.send(ui.child(909, queue), 0x00F5)
        ui.wait("Queue closed", lambda: not window("Analysis queue · Native Workbench"))
        ui.click_button(410)
        # Tools mode is committed by an asynchronous host response. Its native
        # controls can be rebuilt between the navigation click and the next
        # input; a previously obtained search HWND is not proof of readiness.
        # Wait for the visible new mode and its current, hit-testable search
        # control, then keep set_text's real pointer/foreground safeguards.
        def tools_search_ready():
            search, form = ui.child(102), ui.child(118)
            if not (search and form and ui.user.IsWindowVisible(search) and
                    ui.user.IsWindowEnabled(search) and ui.user.IsWindowVisible(form)):
                return False
            if not any(control["text"] == "Choose a tool to begin" for control in ui.controls(form)):
                return False
            if ui.label(ui.child(113)) != "Run tool":
                return False
            rect = wintypes.RECT()
            if not ui.user.GetWindowRect(search, ctypes.byref(rect)):
                return False  # Replaced during this bounded readiness probe.
            hit = ui.user.WindowFromPoint(wintypes.POINT((rect.left + rect.right) // 2,
                                                        (rect.top + rect.bottom) // 2))
            return hit == search and search == ui.child(102)
        ui.wait("Tools mode and current search ready after workflow", tools_search_ready)
        ui.set_text(ui.child(102), "Combine statistics reports")
        ui.wait("native combined-report tool available", lambda: len(ui.library().tools()) == 1)
        ui.click_at(*ui.library().first_tool_point(), expected=ui.child(104))
        ui.wait("native combined-report tool opened", lambda: any(control["text"] == "Combine statistics reports" and
                control["class"].lower() == "edit" for control in ui.controls(ui.child(118))))
        ui.click_button(424)
        ui.wait("Samples reopened for report mode", lambda: window("Samples · Native Workbench"))
        samples = window("Samples · Native Workbench")
        ui.set_text(ui.child(801, samples), str(evidence / "combined-reports.csv"))
        ui.send(ui.child(803, samples), 0x00F5)
        targets = NativeList(ui, ui.child(804, samples))
        sample_rows = NativeList(ui, ui.child(808, samples))
        ui.wait("native report table loaded", lambda: sample_rows.count() == 2 and
                "Loaded 2 samples" in ui.label(ui.child(809, samples)))
        mode = ui.child(814, samples)
        ui.send(mode, 0x014E, 1, 0)
        ui.send(samples, 0x0111, 814 | (1 << 16), mode)
        ui.wait("native combined-report target", lambda: targets.count() == 1)
        mappings = [(row, targets.text(row)) for row in range(targets.count())]
        choose_column("Statistics to include", "report")
        ui.send(ui.child(807, samples), 0x00F5)
        ui.wait("native one-job combined preview", lambda: sample_rows.count() == 1 and
                sample_rows.text(0) == "combined" and sample_rows.text(0, 1) == "Valid" and
                ui.label(ui.child(812, samples)) == "Queue one combined report")
        report["captures"].append(ui.capture("samples-native-combined-preview.bmp", samples))
        write_json(evidence / "samples-native-combined-controls.json", ui.controls(samples))
        ui.send(ui.child(813, samples), 0x00F5)
        ui.wait("combined preview closed without queueing", lambda: not window("Samples · Native Workbench"))
        menu_command(ui, "Reference indexes...")
        ui.wait("native reference-index library", lambda: window("Reference indexes · Native Workbench"))
        indexes = window("Reference indexes · Native Workbench")
        inventory = NativeList(ui, ui.child(1001, indexes))
        ui.wait("native index identities listed", lambda: inventory.count() == 3)
        inventory.click(0)
        require("Reference SHA-256:" in ui.label(ui.child(1002, indexes)) and
                inventory.text(0, 2) == "not_verified", "Index listing falsely claims full verification.")
        ui.send(ui.child(1004, indexes), 0x00F5)
        ui.wait("native explicit index verification", lambda: inventory.text(0, 2) == "Verified this session" and
                "Verified file inventory:" in ui.label(ui.child(1002, indexes)))
        report["captures"].append(ui.capture("reference-indexes-native-verified.bmp", indexes))
        write_json(evidence / "reference-indexes-native-controls.json", ui.controls(indexes))
        ui.send(ui.child(1006, indexes), 0x00F5)
        report["dpi"] = ui.user.GetDpiForWindow(ui.main)
        report["nativeGUIValidated"] = True
        check(report, "Actual native Samples imports CSV, maps mate columns, previews before queueing; Queue displays frozen identity, cancels one waiting sample and explicitly starts the other with known scientific output; native combined mode previews one explicitly mapped report job.")
        check(report, "Native Reference indexes lists three distinct cached identities without claiming verification; explicit Verify rehashes the inventory and updates the selected entry.")
    except Exception:
        try:
            ui.desktop_evidence("batch gate failure")
            for number, handle in enumerate(ui.windows()):
                ui.capture("batch-failure-window-%d.bmp" % number, handle)
                write_json(evidence / ("batch-failure-window-%d.json" % number), {"title": ui.label(handle), "controls": ui.controls(handle)})
        except Exception as capture_error:
            report["failureCaptureError"] = str(capture_error)
        raise
    finally:
        try:
            ui.close()
        finally:
            # The GUI has its own host and can fail after the earlier host
            # checks passed. Preserve that final synthetic queue/history too,
            # after shutdown, including preparation errors without run.json.
            for name in ("run-queue.json", "runs.json"):
                source = root / "user-data" / name
                if source.exists():
                    try:
                        target = evidence / ("gui-final-" + name)
                        write_json(target, read_json(source))
                        report.setdefault("guiFinalReceipts", []).append({"file": target.name, "sha256": sha256(target)})
                    except Exception as capture_error:
                        report.setdefault("guiFinalReceiptErrors", []).append({"file": name, "error": str(capture_error)})


def main():
    global VERSION
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app-root", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--asset-sha256", required=True)
    parser.add_argument("--asset-name", required=True)
    parser.add_argument("--app-version", default=VERSION)
    args = parser.parse_args()
    VERSION = args.app_version
    root, report_path = args.app_root.resolve(), args.report.resolve()
    evidence = report_path.parent
    evidence.mkdir(parents=True, exist_ok=True)
    report = {"schema": 1, "success": False, "appVersion": VERSION, "sourceCommit": args.source_commit,
              "assetName": args.asset_name, "assetSha256": args.asset_sha256, "gateSha256": sha256(__file__),
              "platform": platform.platform(), "python": sys.version, "startedUtc": datetime.now(timezone.utc).isoformat(),
              "nativeWindowsExecuted": False, "nativeGUILaunched": False, "nativeGUIValidated": False,
              "checks": [], "skips": [], "captures": [],
              "limits": ["Synthetic Starter scientific truth and bounded cancellation fixture; not realistic-data capacity or Windows/Linux benchmarking.",
                         "Observed hosted display DPI only; physical trackpad, high DPI, multi-monitor and institutional endpoint acceptance are not established."]}
    try:
        require(os.name == "nt", "This gate requires native Windows; unavailable execution cannot pass.")
        require(Path(sys.executable).resolve() == (root / "runtime/python/python.exe").resolve(), "Use the exact app's private Python.")
        report["appFiles"] = {str(path.relative_to(root)): sha256(path) for path in
                              [root / "NativeWorkbench.exe", root / "WorkbenchBridge.exe", *sorted((root / "workspace").glob("*.py"))]}
        host_checks(root, evidence, report)
        report["nativeWindowsExecuted"] = True
        gui_checks(root, evidence, report)
        report["success"] = True
    except Exception as exc:
        report.update(error=str(exc), traceback=traceback.format_exc())
    finally:
        report.update(completedUtc=datetime.now(timezone.utc).isoformat(), passed=len(report["checks"]),
                      failed=0 if report["success"] else 1, skipped=len(report["skips"]))
        write_json(report_path, report)
    print(json.dumps({"success": report["success"], "passed": report["passed"], "report": str(report_path)}), flush=True)
    return 0 if report["success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
