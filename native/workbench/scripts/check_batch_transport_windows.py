#!/usr/bin/env python3
"""Bounded native transport responsiveness fixture on a separate app extraction.

The executable stays byte-identical. Only this isolated extraction's private
host dispatch gains an explicit marker-controlled index-read delay. This is
transport/GUI evidence, not an unchanged-host or scientific performance claim.
"""
from __future__ import annotations
import argparse
import copy
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import platform
import sys
import time
import traceback

sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_batch_windows import NativeList, NativeUI, add_job, queue_state, read_json, start_host, wait_jobs, until
from check_references_windows import require, sha256, write_json

VERSION = "0.13.0"


def prepare(root, evidence):
    output = evidence / "transport-results"
    output.mkdir()
    host = start_host(root, evidence, "transport-exact-preparation")
    try:
        require(host.call("init")["app_version"] == VERSION, "Wrong application version.")
        graph = host.call("example")["graph"]
        catalog = host.call("state")["catalog"]
        builder = next(tool for tool in catalog["toolVersions"]["align/build-sr-index"] if tool["packVersion"] == "0.4.1")
        reference = copy.deepcopy(next(source for source in graph["sources"] if source["id"] == "input-2"))
        index_graph = {"schema": 1, "name": "Transport fixture reference index", "sources": [reference],
                       "nodes": [{"id": "step-1", "tool": builder["id"], "label": "Build reusable reference",
                                  "pin": {key: builder[key] for key in ("packId", "packVersion", "manifestSha256")},
                                  "params": copy.deepcopy(builder["defaults"]), "inputs": {"reference": ["input-2"]}}],
                       "nextNode": 2, "nextSource": 3}
        built = add_job(host, index_graph, output)
        host.call("queue/start")
        require(wait_jobs(host, {built["job_id"]})[0]["status"] == "completed", "Exact host did not build the fixture index.")
        entries = host.call("index/list")["entries"]
        require(len(entries) == 1, "Fresh transport extraction should contain one reference index.")
        graph["nodes"][0]["params"]["threads"] = "1"
        # Explicitly enlarged synthetic reads keep real local execution active
        # while dialogs open. This is a cancellation fixture, not a benchmark.
        for mate in (1, 2):
            source = (root / "examples/starter" / ("reads%d.fastq" % mate)).read_bytes()
            path = evidence / ("transport-R%d.fastq" % mate)
            with path.open("wb") as stream:
                for _ in range(3000):
                    stream.write(source)
            graph["sources"][0]["files"]["reads%d" % mate] = str(path)
        queued = add_job(host, graph, output)
        require(queue_state(host)["paused"], "Fixture must not begin before the GUI starts it.")
        return queued, entries[0]["key"]
    finally:
        host.close()


def install_delay(root):
    path = root / "workspace/desktop_host.py"
    original = path.read_bytes()
    source = original.decode("utf-8")
    needle = "    def dispatch(self, method, params):\n"
    require(source.count(needle) == 1, "Host fixture dispatch location is ambiguous.")
    injection = '''    def dispatch(self, method, params):
        # TEST FIXTURE ONLY: marker-controlled slow read, removed after the gate.
        if method == "index/verify":
            import time as fixture_time
            fixture_data = self.app.root / "user-data"
            (fixture_data / "transport-verify-entered").write_text("entered", encoding="utf-8")
            fixture_deadline = fixture_time.monotonic() + 60
            while not (fixture_data / "transport-verify-release").exists():
                if fixture_time.monotonic() >= fixture_deadline:
                    raise TimeoutError("Transport fixture delay was not released within 60 seconds.")
                fixture_time.sleep(0.02)
'''
    path.write_bytes(source.replace(needle, injection, 1).encode("utf-8"))
    return path, original


def run_gui(root, evidence, report, job):
    entered = root / "user-data/transport-verify-entered"
    release = root / "user-data/transport-verify-release"
    entered.unlink(missing_ok=True)
    release.unlink(missing_ok=True)
    ui = NativeUI(root, evidence)
    report["nativeGUILaunched"] = True
    try:
        def window(title):
            return next((handle for handle in ui.windows() if ui.label(handle) == title), None)
        def activate(handle):
            ui.user.SetForegroundWindow(handle)
        def button(identity, parent):
            handle = ui.child(identity, parent)
            ui.wait("enabled native control " + str(identity), lambda: ui.user.IsWindowEnabled(handle))
            ui.send(handle, 0x00F5)
        def selected_job():
            return next(item for item in read_json(root / "user-data/run-queue.json")["jobs"] if item["job_id"] == job["job_id"])
        # Exact-host preparation made this a returning installation; no welcome
        # dismissal is inferred from a timer or an absent screenshot.
        ui.wait("returning native workspace ready", lambda: ui.user.IsWindowEnabled(ui.child(410)) and ui.library().tools())
        ui.fit_window(1280, 900)
        ui.click_button(425)
        ui.wait("native queue window", lambda: window("Analysis queue · Native Workbench"))
        queue = window("Analysis queue · Native Workbench")
        listing = NativeList(ui, ui.child(901, queue))
        records = read_json(root / "user-data/run-queue.json")["jobs"]
        row = next(index for index, item in enumerate(records) if item["job_id"] == job["job_id"])
        ui.wait("native prepared job listed", lambda: listing.count() == len(records))
        listing.click(row)
        button(904, queue)
        until("Native queued job did not reach its real bridge.", lambda:
              selected_job()["status"] == "running" and list(Path(job["folder"]).glob("*/bridge-request.json")), 120)
        # Reference indexes is a native View-menu command, not a main HWND.
        ui.post(ui.main, 0x0111, 426)
        ui.wait("native index library", lambda: window("Reference indexes · Native Workbench"))
        indexes = window("Reference indexes · Native Workbench")
        inventory = NativeList(ui, ui.child(1001, indexes))
        ui.wait("seeded index listed", lambda: inventory.count() == 1)
        inventory.click(0)
        button(1004, indexes)
        until("Fixture index verification did not enter its bounded delay.", entered.exists, 10)
        require(selected_job()["status"] == "running", "Scientific job finished before the transport cancellation observation.")
        report["captures"].append(ui.capture("transport-verification-pending.bmp", indexes))
        # Close and reopen this view before its delayed response arrives. The
        # new generation must not inherit the previous view's verification.
        button(1006, indexes)
        ui.wait("old index view closed", lambda: not window("Reference indexes · Native Workbench"))
        ui.post(ui.main, 0x0111, 426)
        ui.wait("fresh index view opened during pending read", lambda: window("Reference indexes · Native Workbench"))
        fresh = window("Reference indexes · Native Workbench")
        activate(queue)
        listing.click(row)
        started = time.monotonic()
        button(906, queue)
        until("Cancel was blocked behind a slow index read.", lambda: selected_job()["status"] == "cancelled", 10)
        ui.wait("native queue receives cancellation status while read pending", lambda: listing.text(row, 2) == "cancelled")
        report["cancelElapsedSeconds"] = time.monotonic() - started
        require(not release.exists(), "The slow fixture was released before cancellation finished.")
        report["captures"].append(ui.capture("transport-cancelled-while-read-pending.bmp", queue))
        report["checks"].append("Actual native queue cancellation and status updates pass a blocked index read; the real local job records cancellation before the delay is released.")
        release.write_text("release", encoding="utf-8")
        fresh_inventory = NativeList(ui, ui.child(1001, fresh))
        ui.wait("fresh index view receives its own listing", lambda: fresh_inventory.count() == 1 and ui.user.IsWindowEnabled(ui.child(1004, fresh)))
        require(fresh_inventory.text(0, 2) == "not_verified", "Closed view's late verification contaminated the reopened view.")
        activate(fresh)
        fresh_inventory.click(0)
        require("Verified file inventory:" not in ui.label(ui.child(1002, fresh)), "Stale verification details were retained by the new view.")
        report["captures"].append(ui.capture("transport-reopened-index-unverified.bmp", fresh))
        button(1004, fresh)
        ui.wait("new explicit verification succeeds", lambda: fresh_inventory.text(0, 2) == "Verified this session")
        report["checks"].append("Closing/reopening the index dialog discards its old response by generation; only a new explicit Verify updates the fresh view.")
        # Closing the application must also bypass a blocked read. No analysis
        # remains active now; its recorded cancellation is already durable.
        entered.unlink(missing_ok=True)
        release.unlink(missing_ok=True)
        button(1004, fresh)
        until("Second bounded read did not begin.", entered.exists, 10)
        started = time.monotonic()
        ui.post(ui.main, 0x0010)
        require(ui.process.wait(timeout=12) == 0, "Native close did not complete while a read was pending.")
        report["closeElapsedSeconds"] = time.monotonic() - started
        require(not release.exists(), "Pending-read close required releasing the fixture.")
        report["checks"].append("Native close completes with a pending read and preserves the cancelled queue record; remaining private-host work is contained by the owning desktop process tree.")
        report["nativeGUIValidated"] = True
    except Exception:
        try:
            ui.desktop_evidence("transport fixture failure")
            for index, handle in enumerate(ui.windows()):
                ui.capture("transport-failure-%d.bmp" % index, handle)
                write_json(evidence / ("transport-failure-%d.json" % index), {"title": ui.label(handle), "controls": ui.controls(handle)})
        except Exception as error:
            report["failureCaptureError"] = str(error)
        raise
    finally:
        release.write_text("release", encoding="utf-8")
        ui.close()


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
    root, target = args.app_root.resolve(), args.report.resolve()
    evidence = target.parent
    evidence.mkdir(parents=True, exist_ok=True)
    report = {"schema": 1, "success": False, "appVersion": VERSION, "sourceCommit": args.source_commit,
              "assetName": args.asset_name, "assetSha256": args.asset_sha256, "gateSha256": sha256(__file__),
              "platform": platform.platform(), "startedUtc": datetime.now(timezone.utc).isoformat(),
              "nativeGUILaunched": False, "nativeGUIValidated": False, "checks": [], "captures": [],
              "fixtureOnly": True, "limits": ["Separate candidate extraction: exact native executable, deliberately instrumented private host index read. This does not claim unchanged-host execution during the transport fixture.",
              "Synthetic cancellation fixture, not throughput or realistic-data benchmarking; hosted display only."]}
    host_path, original = None, None
    try:
        require(os.name == "nt", "Native Windows is required; unavailable checks cannot pass.")
        require(Path(sys.executable).resolve() == (root / "runtime/python/python.exe").resolve(), "Use the exact private interpreter.")
        report["nativeExecutableSha256"] = sha256(root / "NativeWorkbench.exe")
        require(not (root / "user-data/run-queue.json").exists(), "Use a separate fresh extraction for this fixture.")
        job, key = prepare(root, evidence)
        report["jobId"], report["indexKey"] = job["job_id"], key
        report["originalHostSha256"] = sha256(root / "workspace/desktop_host.py")
        host_path, original = install_delay(root)
        report["instrumentedHostSha256"] = sha256(host_path)
        run_gui(root, evidence, report, job)
        require(sha256(root / "NativeWorkbench.exe") == report["nativeExecutableSha256"], "Native executable changed during the fixture.")
        report["success"] = True
    except Exception as error:
        report.update(error=str(error), traceback=traceback.format_exc())
    finally:
        if host_path is not None:
            host_path.write_bytes(original)
            report["restoredHostSha256"] = sha256(host_path)
            if report["restoredHostSha256"] != report["originalHostSha256"]:
                report.update(success=False, error="Fixture host restoration checksum differs.")
        report.update(completedUtc=datetime.now(timezone.utc).isoformat(), passed=len(report["checks"]), failed=0 if report["success"] else 1)
        write_json(target, report)
    print(json.dumps({"success": report["success"], "passed": report["passed"], "report": str(target)}), flush=True)
    return 0 if report["success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
