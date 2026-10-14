#!/usr/bin/env python3
"""Bounded diagnosis of intermittent frozen-queue failures in one exact package.

This is a focused storage/observer experiment, not another full candidate gate.
It alternates 12 unobserved cycles with 12 cycles reading the live queue receipt
using the validator's existing Windows READ/WRITE/DELETE sharing helper. The
application, private host and runtime are never patched. Any unexpected failure
stops the experiment and retains the exact phase, response and durable records.
"""
from __future__ import annotations

import argparse
import copy
import ctypes
from ctypes import wintypes
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import platform
import sys
import threading
import time
import traceback

sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_batch_windows import read_json, TERMINAL
from check_references_windows import PrivateHost, require, sha256, write_json


def now():
    return datetime.now(timezone.utc).isoformat()


def replacement_control(evidence):
    """Observe the primitive with the validator's exact handle share modes.

    A held handle deliberately makes the timing deterministic. This disposable
    file is outside application data. The later closed-handle attempt is an
    explicitly labelled comparison, not an application retry or a hidden pass.
    """
    folder = evidence / "replacement-control"
    folder.mkdir()
    destination, staged = folder / "receipt.json", folder / "receipt.tmp"
    destination.write_bytes(b'{"revision":"old"}\n')
    staged.write_bytes(b'{"revision":"new"}\n')
    result = {"desiredAccess": "GENERIC_READ", "sharing": ["READ", "WRITE", "DELETE"],
              "applicationFilesTouched": False, "oldSha256": sha256(destination), "newSha256": sha256(staged)}
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                  ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    kernel.CreateFileW.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL
    handle = kernel.CreateFileW("\\\\?\\" + str(destination), 0x80000000, 7, None, 3, 0x80, None)
    if handle == ctypes.c_void_p(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        try:
            os.replace(staged, destination)
            result["heldHandleReplace"] = {"success": True}
            try:
                result["reopenWhileOldHandleHeld"] = {"success": True, "value": read_json(destination)}
            except OSError as error:
                result["reopenWhileOldHandleHeld"] = {"success": False, "error": str(error),
                                                       "errno": error.errno, "winerror": error.winerror}
        except OSError as error:
            result["heldHandleReplace"] = {"success": False, "error": str(error),
                                            "errno": error.errno, "winerror": error.winerror}
    finally:
        require(kernel.CloseHandle(handle), "Control read handle did not close.")
    if not result["heldHandleReplace"]["success"]:
        result["heldFailurePreservedSource"] = staged.is_file() and sha256(staged) == result["newSha256"]
        result["heldFailurePreservedDestination"] = sha256(destination) == result["oldSha256"]
        require(result["heldFailurePreservedSource"] and result["heldFailurePreservedDestination"],
                "Failed primitive replacement did not preserve both expected control files.")
        try:
            os.replace(staged, destination)
            result["closedHandleComparison"] = {"success": True, "destinationSha256": sha256(destination)}
        except OSError as error:
            result["closedHandleComparison"] = {"success": False, "error": str(error),
                                                 "errno": error.errno, "winerror": error.winerror}
    else:
        result["closedHandleComparison"] = {"performed": False, "reason": "Initial replacement already succeeded."}
    result["finalDestinationSha256"] = sha256(destination)
    write_json(evidence / "replacement-control.json", result)
    return result


class Observer:
    def __init__(self, path):
        self.path = path
        self.stop = threading.Event()
        self.reads = 0
        self.last = None
        self.error = None
        self.active_snapshots = 0
        self.thread = threading.Thread(target=self.read, name="independent-queue-observer", daemon=True)

    def read(self):
        try:
            while not self.stop.is_set():
                self.last = read_json(self.path)
                self.reads += 1
                self.active_snapshots += any(job["status"] in ("preparing", "running") for job in self.last["jobs"])
                self.stop.wait(.05)
        except Exception as error:
            self.error = {"error": str(error), "traceback": traceback.format_exc(), "at": now()}

    def close(self):
        self.stop.set()
        self.thread.join(timeout=5)
        require(not self.thread.is_alive(), "Independent observer did not stop.")


def report_graph(catalog, inputs):
    tool = catalog["tools"]["builtin/report"]
    return {"schema": 1, "name": "Queue persistence diagnostic", "nextSource": 3, "nextNode": 2,
            "sources": [{"id": "input-" + str(i), "type": "metrics", "label": "Synthetic metric " + str(i),
                         "files": {"metrics": str(path)}} for i, path in enumerate(inputs, 1)],
            "nodes": [{"id": "step-1", "tool": "builtin/report", "label": "Separate synthetic reports",
                       "inputs": {"metrics": ["input-1", "input-2"]}, "params": copy.deepcopy(tool["defaults"]),
                       "pin": {key: tool[key] for key in ("packId", "packVersion", "manifestSha256")}}]}


def diagnose(root, evidence, report):
    host = PrivateHost(root, evidence, "queue-observer-host", offline=True)
    active = None
    events = (evidence / "actions.jsonl").open("w", encoding="utf-8")
    phase = "initialization"

    def record(event, value):
        events.write(json.dumps({"at": now(), "phase": phase, "event": event, "value": value}) + "\n")
        events.flush()

    def status():
        # RPC only. In particular, the no-observer cycles never open a live
        # receipt; private file inventories are collected after worker idle.
        value = host.call("queue/status")
        if value.get("error"):
            record("queue-error", value)
            raise AssertionError("Queue storage error: " + str(value["error"]))
        return value

    def settle(description):
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            state = status()
            if not state["preparing"] and not state["queue_running"]:
                return state
            time.sleep(.05)
        record("timeout-status", state)
        raise TimeoutError(description)

    def receipts(label):
        files = []
        for filename in ("run-queue.json", "runs.json"):
            source = root / "user-data" / filename
            if source.exists():
                target = evidence / (label + "-" + filename)
                write_json(target, read_json(source))
                files.append({"file": target.name, "sha256": sha256(target)})
        return files

    try:
        initial = host.call("init")
        catalog = initial["catalog"]
        require(not status()["jobs"], "This diagnostic requires a fresh candidate extraction.")
        inputs = [evidence / ("metric-%d.txt" % i) for i in (1, 2)]
        for i, path in enumerate(inputs, 1):
            path.write_text("Synthetic diagnostic count\t%d\n" % i, encoding="utf-8")
        report["inputs"] = [{"file": str(path), "sha256": sha256(path)} for path in inputs]
        graph = report_graph(catalog, inputs)
        write_json(evidence / "fixture-graph.json", graph)
        output = evidence / "results"
        output.mkdir()
        queue_path = root / "user-data/run-queue.json"
        for index in range(24):
            observed = index % 2 == 1
            cycle = {"cycle": index + 1, "liveObserver": observed, "startedUtc": now()}
            report["cycles"].append(cycle)
            phase = "cycle-%02d-preparation" % (index + 1)
            record("begin", cycle)
            if observed:
                active = Observer(queue_path)
                active.thread.start()
            try:
                queued = host.call("queue/add", {"graph": graph, "output_folder": str(output)})
                record("queue/add", queued)
                identities = set(queued["added"])
                cycle["jobIds"] = sorted(identities)
                state = settle("Queue preparation did not settle.")
                jobs = [job for job in state["jobs"] if job["job_id"] in identities]
                cycle["prepared"] = jobs
                record("prepared", jobs)
                require(len(jobs) == 1 and jobs[0]["status"] == "queued",
                        "Preparation failed: " + json.dumps(jobs))
                phase = "cycle-%02d-execution" % (index + 1)
                record("queue/start", host.call("queue/start"))
                state = settle("Queue execution did not settle.")
                jobs = [job for job in state["jobs"] if job["job_id"] in identities]
                cycle["finished"] = jobs
                record("finished", jobs)
                for job in jobs:
                    record("run/get", host.call("run/get", {"run_id": job["job_id"]}))
                require(len(jobs) == 1 and jobs[0]["status"] == "completed",
                        "Execution failed: " + json.dumps(jobs))
            finally:
                if active is not None:
                    active.close()
                    cycle["observer"] = {"reads": active.reads, "activeSnapshots": active.active_snapshots,
                                         "error": active.error}
                    if active.last is not None:
                        write_json(evidence / ("cycle-%02d-observer-last.json" % (index + 1)), active.last)
                    active = None
            # Both groups are idle here. Retain exact file inventories, plan
            # input hashes and output hashes without modifying the application.
            state = read_json(queue_path)
            job = next(job for job in state["jobs"] if job["job_id"] in identities)
            folder = Path(job["folder"])
            plan, run = read_json(folder / "plan.json"), read_json(folder / "run.json")
            cycle["planInputs"] = plan["inputs"]
            cycle["preparedFileInventory"] = job["files"]
            cycle["planSha256"] = plan["sha256"]
            cycle["runSha256"] = sha256(folder / "run.json")
            require(run["success"] and run["outputs"], "Completed report lacks a successful execution record.")
            for result in run["outputs"].values():
                require(all(sha256(path) == result["sha256"][key] for key, path in result["files"].items()),
                        "Synthetic report output differs from its recorded hash.")
            if observed:
                require(cycle["observer"]["reads"] > 0, "Live-observer cycle took no receipt snapshots.")
                require(cycle["observer"]["error"] is None, "Independent observer failed: " + json.dumps(cycle["observer"]))
            cycle["completedUtc"] = now()
            record("cycle-complete", cycle)
        report["success"] = True
    except Exception as error:
        report.update(error=str(error), phase=phase, traceback=traceback.format_exc())
        record("failure", {key: report[key] for key in ("error", "phase", "traceback")})
        try:
            state = host.call("queue/status")
            record("failure-status", state)
            report["failureStatus"] = state
            for job in state["jobs"]:
                if job["status"] in TERMINAL and job["status"] != "completed":
                    record("failure-run/get", host.call("run/get", {"run_id": job["job_id"]}))
        except Exception as capture_error:
            report["failureCaptureError"] = str(capture_error)
    finally:
        if active is not None:
            active.close()
        try:
            host.close()
        finally:
            report["finalReceipts"] = receipts("final")
            queue_path = root / "user-data/run-queue.json"
            if queue_path.exists():
                details = []
                for job in read_json(queue_path)["jobs"]:
                    item = {key: job[key] for key in ("job_id", "status", "message", "folder", "files")}
                    if job["folder"]:
                        folder = Path(job["folder"])
                        item["actualFileInventory"] = {str(path.relative_to(folder)): sha256(path)
                                                       for path in sorted(folder.rglob("*")) if path.is_file()}
                        if (folder / "plan.json").exists():
                            plan = read_json(folder / "plan.json")
                            item["planInputs"] = plan["inputs"]
                            item["planSha256"] = plan["sha256"]
                    details.append(item)
                write_json(evidence / "final-job-details.json", details)
            events.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app-root", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--asset-sha256", required=True)
    args = parser.parse_args()
    root, target = args.app_root.resolve(), args.report.resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    report = {"schema": 1, "success": False, "scope": "Focused queue persistence and live-observer diagnosis; not the full candidate gate.",
              "sourceCommit": args.source_commit, "assetSha256": args.asset_sha256, "gateSha256": sha256(__file__),
              "observerHelperSha256": sha256(Path(__file__).with_name("check_batch_windows.py")),
              "platform": platform.platform(), "python": sys.version, "startedUtc": now(), "cycles": [],
              "observerIntervalSeconds": .05, "plannedCycles": 24, "applicationPatched": False}
    try:
        require(os.name == "nt", "This diagnostic requires native Windows.")
        require(Path(sys.executable).resolve() == (root / "runtime/python/python.exe").resolve(), "Use the exact private runtime.")
        report["appFiles"] = {str(path.relative_to(root)): sha256(path) for path in
                              [root / "NativeWorkbench.exe", root / "WorkbenchBridge.exe", *sorted((root / "workspace").glob("*.py"))]}
        report["replacementControl"] = replacement_control(target.parent)
        diagnose(root, target.parent, report)
    except Exception as error:
        report.update(success=False, error=str(error), traceback=traceback.format_exc())
    finally:
        report["completedUtc"] = now()
        report["completedCycles"] = sum("completedUtc" in cycle for cycle in report["cycles"])
        write_json(target, report)
    print(json.dumps({"success": report["success"], "completedCycles": report["completedCycles"], "report": str(target)}))
    return 0 if report["success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
