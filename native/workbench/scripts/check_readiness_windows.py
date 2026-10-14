#!/usr/bin/env python3
"""Validate readiness, measurements and explicit diagnostics in one frozen app.

Requires native Windows and the candidate's private Python. Synthetic canaries
exercise export exclusions; no user files, network service or upload is used.
Captures establish only the runner's actual display DPI, not human acceptance.
"""
from __future__ import annotations

import argparse
import copy
import ctypes
from ctypes import wintypes
from datetime import datetime, timezone
import gzip
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import time
import traceback
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_references_windows import PrivateHost, require, sha256, write_json
from check_workspace_ui_windows import NativeUI

CANARIES = ("NW_PRIVATE_SAMPLE_72516", "NW_PRIVATE_INPUTS_72516", "NW_PRIVATE_GRAPH_72516")


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def check(report, description):
    report["checks"].append(description)
    print(json.dumps({"passed": len(report["checks"]), "check": description}), flush=True)


def check_zip(path, preview):
    with zipfile.ZipFile(path) as archive:
        require(archive.testzip() is None, "Diagnostic ZIP has an invalid CRC.")
        require(set(archive.namelist()) == {"report.json", "README.txt", "SHA256SUMS.txt"},
                "Diagnostic ZIP attached an unreviewed member.")
        require(archive.read("report.json") == preview.encode("utf-8"),
                "Saved report differs from the exact preview.")
        checksums = archive.read("SHA256SUMS.txt").decode("ascii").splitlines()
        require(len(checksums) == 2, "Diagnostic checksum manifest has unexpected coverage.")
        for line in checksums:
            digest, name = line.split("  ", 1)
            require(name in {"report.json", "README.txt"} and
                    hashlib.sha256(archive.read(name)).hexdigest() == digest,
                    "Diagnostic member failed its independent checksum.")
        for name in archive.namelist():
            require(not any(value.encode() in archive.read(name) for value in CANARIES),
                    "Diagnostic ZIP disclosed a synthetic private canary.")
    return {"file": path.name, "sha256": sha256(path), "bytes": path.stat().st_size}


def performance_checks(folder, record, report):
    path = folder / "performance.json"
    require(record["performance"] == {"file": "performance.json", "schema": 1, "sha256": sha256(path)},
            "Final run does not bind the exact performance record.")
    value, plan = read_json(path), read_json(folder / "plan.json")
    require(value["schema"] == 1 and value["kind"] == "native-workbench-performance" and
            value["appVersion"] == report["appVersion"] and value["status"] == "success" and
            value["planSha256"] == record["planSha256"] == plan["sha256"] and value["runId"] == record["id"],
            "Performance identity does not match the frozen run.")
    require(value["system"]["os"]["name"] == "Windows" and value["system"]["logicalCpuCount"] > 0 and
            value["system"]["physicalMemoryBytes"] > 0, "Native hardware measurements unavailable.")
    require(value["inputSummary"]["uniqueFileCount"] == 3 and value["inputSummary"]["totalBytes"] > 0,
            "Scientific input sizes were not recorded.")
    require(all(set(item) == {"bytes", "sha256"} for item in value["inputSummary"]["files"]),
            "Performance input summary contains identifying paths.")
    require(not any(canary in path.read_text(encoding="utf-8") for canary in CANARIES),
            "Performance measurements copied sample, workflow or input names.")
    for section in ("preparation", "execution"):
        measured = value[section]
        require(measured["status"] == ("completed" if section == "preparation" else "success") and measured["elapsedSeconds"] >= 0,
                "Missing complete inclusive measurement: " + section)
        require(all(p["status"] == "completed" and p["elapsedSeconds"] >= 0 for p in measured["phases"].values()),
                "Missing completed measurement phase: " + section)
    require(value["interpretation"]["inclusiveTotalsOverlapPhases"] is True and
            "not resident set size" in value["interpretation"]["nativeMemoryMeaning"],
            "Performance scope is not explicit about overlap and committed memory.")
    # These ordinary-operation stage identities are unchanged in align 0.4.1
    # beside the published Starter 0.4.0 manifests. Their
    # BCFtools call uses intermediate files, not a binary producer/sink pipe.
    # Pipeline accounting is exercised separately by WindowsPerformanceChecks,
    # built from the same production process_pipeline.cpp.
    expected_stages = {
        "align/paired-end": [("check-pairs", "exec"), ("align", "exec")],
        "bam/prepare": [(name, "exec") for name in
                        ("name-sort", "fixmate", "coordinate-sort", "mark-duplicates", "index-bam", "flagstat", "alignment-stats")],
        "variants/call": [("copy-reference", "copy")] + [(name, "exec") for name in
                          ("index-reference", "pileup", "call", "normalize", "filter", "index-variants", "variant-stats")],
        "variants/statistics": [("statistics", "exec")],
    }
    stages, pipes, copies = 0, 0, 0
    partial_stages = []
    require(len(value["steps"]) == 5, "Performance omitted a workflow step.")
    for step in value["steps"]:
        require(step["status"] == "success" and step["elapsedSeconds"] >= 0, "Missing successful step measurement.")
        if step["tool"] == "builtin/report":
            require(step["backendMetrics"]["available"] is False, "Python report fabricated native counters.")
            continue
        require(all(phase["status"] == "completed" and phase["elapsedSeconds"] >= 0
                    for phase in step["phases"].values()), "A native step omitted a completed timing phase.")
        backend = step["backendMetrics"]
        require(backend["available"] and backend["data"]["source"] == "windows-job-object",
                "Native command metrics were unavailable in the exact package.")
        require([(stage["id"], stage["kind"]) for stage in backend["data"]["stages"]] == expected_stages[step["tool"]],
                "Native metrics omitted or changed an expected ordinary Starter command stage.")
        for stage in backend["data"]["stages"]:
            if stage["kind"] == "copy":
                require(stage["resources"] is None, "Copy operation fabricated native process counters.")
                copies += 1
                continue
            metrics = stage["resources"]
            require(stage["status"] == "success" and metrics["accounting_available"] and
                    metrics["memory_available"] and not metrics["accounting_error"] and not metrics["memory_error"],
                    "Successful native command lacks available resource accounting.")
            active = metrics["processes_active_at_snapshot"]
            require(0 <= active <= metrics["processes_total"] and
                    metrics["coverage"] == ("partial" if active else "complete"),
                    "Native resource coverage does not reflect the processes still active before job cleanup.")
            require(metrics["user_cpu_seconds"] >= 0 and metrics["kernel_cpu_seconds"] >= 0 and
                    metrics["peak_job_memory_bytes"] > 0 and metrics["wall_ms"] >= 0 and
                    metrics["memory_kind"] == "committed" and
                    metrics["snapshot"] == "before-job-close", "Invalid native process resource observations.")
            expected_scope = "pipeline-process-tree" if stage["kind"] == "pipe" else "command-process-tree"
            require(metrics["scope"] == expected_scope and metrics["processes_total"] >= (2 if stage["kind"] == "pipe" else 1),
                    "Native process accounting scope differs from its command kind.")
            stages += 1
            pipes += stage["kind"] == "pipe"
            if active:
                partial_stages.append({"stepId": step["id"], "tool": step["tool"], "stageId": stage["id"],
                                       "processesActiveAtSnapshot": active, "processesTotal": metrics["processes_total"]})
    require(stages == 17 and pipes == 0 and copies == 1,
            "Native measurement stage counts differ from the expected ordinary Starter workflows.")
    report["performance"] = {"sha256": sha256(path), "commandStages": stages, "pipelineStages": pipes,
                             "copyStages": copies, "system": value["system"], "memoryKind": "committed; not RSS",
                             "actualPins": [{"tool": step["tool"], "pin": step["pin"]} for step in value["steps"]],
                             "completeStageCount": stages - len(partial_stages), "partialStageCount": len(partial_stages),
                             "partialStages": partial_stages,
                             "coverageScope": "Counters are sampled before job cleanup. Stages with remaining active descendants are explicitly partial, not complete process-lifetime totals.",
                             "pipelineCoverage": "No binary pipe in the pinned Starter workflows; separate native performance helper exercises production pipeline accounting."}
    shutil.copyfile(path, Path(report["evidenceRoot"]) / "performance.json")
    check(report, "Frozen five-step Starter run binds phase timings, input sizes and real Windows Job Object measurements for all 17 exec stages, labels any live-descendant snapshot partial and leaves its copy without fabricated process counters.")


def host_checks(root, evidence, report):
    host = PrivateHost(root, evidence, "readiness-host", offline=True)
    try:
        require(host.call("init")["app_version"] == report["appVersion"], "Incorrect packaged candidate version.")
        graph = host.call("example")["graph"]
        manifest = read_json(root / "manifest.json")
        available_align = [pack for pack in manifest["starter_packs"] + manifest.get("additional_packs", []) if pack["id"] == "align"]
        latest_align = max(available_align, key=lambda pack: tuple(map(int, pack["version"].split("."))))
        require(graph["nodes"][0]["pin"]["packVersion"] == latest_align["version"] and
                graph["nodes"][0]["pin"]["manifestSha256"] == latest_align["manifestSha256"],
                "New example did not select the exact newest installed ordinary alignment; saved pins are checked separately.")
        graph["name"] = CANARIES[2]
        fixture = root / "examples/starter"
        profile = read_json(root / "workspace/starter-check-profile.json")
        private_inputs = evidence / CANARIES[1]
        private_inputs.mkdir()
        for name, expected in profile["fixtures"].items():
            require(sha256(fixture / name) == expected, "Starter fixture differs from its pinned scientific identity.")
            shutil.copyfile(fixture / name, private_inputs / name)
        for source in graph["sources"]:
            source["label"] = CANARIES[1]
            source["files"] = {key: str(private_inputs / Path(value).name) for key, value in source["files"].items()}
        graph["nodes"][0]["params"]["sample"] = CANARIES[0]
        output = evidence / "analysis-results"
        output.mkdir()
        missing = copy.deepcopy(graph)
        missing["sources"][0]["files"]["reads1"] = str(private_inputs / "missing.fastq")
        blocked = host.call("review", {"graph": missing, "output_folder": str(output)})
        require(not blocked["valid"] and blocked["readiness"]["status"] == "blocked" and
                any(c["code"] == "graph_inputs" and c["status"] == "failed" for c in blocked["readiness"]["checks"]),
                "Missing selected input was not blocked by readiness.")
        bad_output = host.call("review", {"graph": graph, "output_folder": str(output / "absent")})
        require(not bad_output["valid"] and bad_output["readiness"]["status"] == "blocked",
                "Nonexistent output directory passed readiness.")
        incomplete = host.call("review", {"graph": graph})
        require(incomplete["valid"] and incomplete["readiness"]["status"] == "incomplete",
                "Legacy methods preview falsely declared complete readiness without an output folder.")
        ready = host.call("review", {"graph": graph, "output_folder": str(output)})
        rows = {row["code"]: row["status"] for row in ready["readiness"]["checks"]}
        require(ready["valid"] and ready["readiness"]["status"] == "ready_for_preparation" and
                all(rows[key] == "passed" for key in ("graph_inputs", "pack_manifests", "output_location", "output_write", "output_space")) and
                all(rows[key] == "deferred" for key in ("input_integrity", "scientific_preflight", "tool_execution")),
                "Readiness did not distinguish preparation checks from deferred execution/integrity.")
        require(not list(output.iterdir()), "Readiness launched an analysis or left a temporary probe.")
        write_json(evidence / "readiness.json", ready)
        check(report, "Readiness blocks missing input/destination, leaves no probe, preserves incomplete legacy previews and explicitly defers execution and complete integrity checks.")
        started = host.call("run", {"graph": graph, "output_folder": str(output)})
        deadline = time.monotonic() + 240
        while time.monotonic() < deadline:
            result = host.call("run/get", {"run_id": started["run_id"]})
            if result["status"] not in {"preparing", "running", "cancelling"}:
                break
            time.sleep(.1)
        else:
            raise TimeoutError("Measured starter scientific workflow did not finish.")
        write_json(evidence / "service-result.json", result)
        require(result["status"] == "completed" and result["success"], "Measured starter workflow failed.")
        folder = Path(result["folder"])
        record = read_json(folder / "run.json")
        sam = Path(record["outputs"]["step-1::sam"]["files"]["sam"])
        bam = Path(record["outputs"]["step-2::bam"]["files"]["bam"])
        original = [line for line in sam.read_text().splitlines() if line and not line.startswith("@")]
        rows = [line.split("\t") for line in original]
        require(len(rows) == 202 and all(int(row[1]) & 1 and int(row[1]) & 2 and not int(row[1]) & 4 and row[2] == "starter" for row in rows),
                "Measured minimap2 run lost known 202 mapped proper-pair records.")
        decoded = subprocess.run([str(root / "packs/bam-0.4.0/bin/samtools.exe"), "view", str(bam)], capture_output=True, timeout=60)
        require(decoded.returncode == 0 and len(decoded.stdout.decode().splitlines()) == 202, "Measured prepared BAM lost alignment records.")
        vcf = Path(record["outputs"]["step-3::variants"]["files"]["variants"])
        with gzip.open(vcf, "rt") as stream:
            variants = [line.split("\t") for line in stream.read().splitlines() if line and not line.startswith("#")]
        require(len(variants) == 1 and variants[0][:2] == ["starter", "1351"] and variants[0][3:5] == ["G", "A"] and
                variants[0][9].split(":")[variants[0][8].split(":").index("GT")] == "1/1", "Measured run changed the known SNP truth.")
        for item in record["outputs"].values():
            for key, filename in item["files"].items():
                require(sha256(filename) == item["sha256"][key], "Measured result failed frozen output provenance.")
        check(report, "Real native minimap2/SAMtools/BCFtools starter workflow retains 202 paired alignments and starter:1351 G>A, GT=1/1 with independently checked output hashes.")
        performance_checks(folder, record, report)
        exports = evidence / "diagnostic-exports"
        exports.mkdir()
        preview = host.call("diagnostics/review", {"run_id": started["run_id"]})
        parsed = json.loads(preview["preview"])
        require(parsed["kind"] == "native-workbench-diagnostics" and parsed["run"]["stepCount"] == 5 and
                parsed["run"]["performanceRecordPresent"] and parsed["readiness"] is None,
                "Diagnostic snapshot lacks trusted run status or misattributes current readiness to a historical run.")
        require(not any(profile["fixtures"][name] in preview["preview"] for name in ("reads1.fastq", "reads2.fastq", "reference.fa")),
                "Diagnostic preview disclosed scientific input hashes.")
        require(not list(exports.iterdir()), "Review wrote an export without explicit Save.")
        saved = host.call("diagnostics/save", {"token": preview["token"], "output_folder": str(exports)})
        require(saved["uploaded"] is False, "Diagnostic save implies a remote upload.")
        report["diagnostics"] = check_zip(Path(saved["path"]), preview["preview"])
        try:
            host.call("diagnostics/save", {"token": preview["token"], "output_folder": str(exports)})
        except ValueError:
            pass
        else:
            raise AssertionError("Consumed diagnostic preview token could be reused.")
        require(len(list(exports.iterdir())) == 1, "Rejected diagnostic token created another file.")
        check(report, "Explicit diagnostic Save writes only the reviewed JSON and checksum/README, excludes synthetic private names and rejects token reuse without another export.")
        report["networkSocketOperationsDeniedForHost"] = True
    finally:
        host.close()


def menu_command(ui, label):
    user = ui.user
    user.GetMenu.argtypes, user.GetMenu.restype = [wintypes.HWND], wintypes.HMENU
    user.GetSubMenu.argtypes, user.GetSubMenu.restype = [wintypes.HMENU, ctypes.c_int], wintypes.HMENU
    user.GetMenuItemCount.argtypes = [wintypes.HMENU]
    user.GetMenuItemID.argtypes, user.GetMenuItemID.restype = [wintypes.HMENU, ctypes.c_int], wintypes.UINT
    user.GetMenuStringW.argtypes = [wintypes.HMENU, wintypes.UINT, wintypes.LPWSTR, ctypes.c_int, wintypes.UINT]
    def find(menu):
        for index in range(user.GetMenuItemCount(menu)):
            value = ctypes.create_unicode_buffer(1024)
            user.GetMenuStringW(menu, index, value, len(value), 0x400)
            if value.value.replace("&", "") == label:
                return user.GetMenuItemID(menu, index)
            child = user.GetSubMenu(menu, index)
            if child:
                found = find(child)
                if found is not None:
                    return found
        return None
    result = find(user.GetMenu(ui.main))
    require(result is not None, "Native menu lacks " + label)
    ui.post(ui.main, 0x0111, result)


def gui_checks(root, evidence, report):
    ui = NativeUI(root, evidence)
    report["nativeGUILaunched"] = True
    try:
        def window(title):
            return next((handle for handle in ui.windows() if ui.label(handle) == title), None)
        def setup():
            return next((handle for handle in ui.windows() if ui.label(handle, True) == "WorkbenchToolSetup0100"), None)
        ui.wait("first launch setup or ready desktop", lambda: setup() or ui.user.IsWindowEnabled(ui.child(410)))
        if setup():
            welcome = setup()
            ui.wait("Use Workbench available", lambda: ui.user.IsWindowEnabled(ui.child(713, welcome)))
            ui.send(ui.child(713, welcome), 0x00F5)
            ui.wait("first launch closed", lambda: not setup())
        ui.wait("native tools ready", lambda: ui.user.IsWindowEnabled(ui.child(410)) and len(ui.library().tools()) > 0)
        ui.fit_window(1280, 900)
        ui.post(ui.main, 0x0111, 302)  # Established File > Open example workflow.
        ui.wait("example workflow loaded", lambda: "Starter example" in ui.label(ui.child(101)))
        if not ui.user.IsWindowVisible(ui.child(111)):
            ui.click_button(412)  # General settings in workflow mode.
        # A pointer click queues the panel transition and any preceding model
        # commit. Wait for the same visible/enabled edit a person must use.
        ui.wait("output folder edit ready", lambda:
                ui.user.IsWindowVisible(ui.child(111)) and ui.user.IsWindowEnabled(ui.child(111)))
        destination = evidence / "gui-diagnostic-exports"
        destination.mkdir()
        ui.set_text(ui.child(111), str(destination))
        require(ui.label(ui.child(115)) == "Methods", "Native footer did not expose separate Methods.")
        ui.click_button(115)
        ui.wait("planned methods modal", lambda: window("Planned methods"))
        modal = window("Planned methods")
        text = ui.label(ui.child(105, modal))
        require("minimap2" in text and "Ready for preparation" not in text,
                "Separate Methods did not show the planned scientific methods independently of readiness.")
        report["captures"] = [ui.capture("methods-native.bmp", modal)]
        write_json(evidence / "methods-native-controls.json", ui.controls(modal))
        ui.send(ui.child(2, modal), 0x00F5)
        ui.wait("planned methods modal closed", lambda: not window("Planned methods"))
        require(not list(destination.iterdir()), "Methods preview created output files.")
        ui.click_button(113)
        ui.wait("Run preflight review", lambda: window("Review and run"))
        modal = window("Review and run")
        text = ui.label(ui.child(105, modal))
        require("Ready for preparation" in text and "deferred" in text.lower() and "Successful tool execution" in text,
                "Run preflight omitted readiness limits or planned-method review.")
        # Retain actual native pixels for visual review of introductory text
        # fit. A WM_GETFONT handle belongs to the application process and cannot
        # provide a valid cross-process DrawText measurement in this helper.
        report["captures"].append(ui.capture("run-preflight-native.bmp", modal))
        write_json(evidence / "run-preflight-native-controls.json", ui.controls(modal))
        ui.send(ui.child(2, modal), 0x00F5)
        ui.wait("Run preflight cancelled", lambda: not window("Review and run"))
        require(not list(destination.iterdir()), "Cancelled Run preflight created an analysis.")
        menu_command(ui, "Review diagnostics...")
        ui.wait("diagnostic preview modal", lambda: window("Review diagnostic report"))
        modal = window("Review diagnostic report")
        require(ui.label(ui.child(1, modal)) == "Save diagnostic ZIP", "Diagnostic review lacks an explicit Save action.")
        preview = ui.label(ui.child(105, modal)).replace("\r\n", "\n")
        require(json.loads(preview)["kind"] == "native-workbench-diagnostics", "Native diagnostic preview is not its structured report.")
        report["captures"].append(ui.capture("diagnostics-native-preview.bmp", modal))
        ui.send(ui.child(2, modal), 0x00F5)
        ui.wait("diagnostic preview closed without saving", lambda: not window("Review diagnostic report"))
        require(not list(destination.iterdir()), "Closing the diagnostic review still exported a file.")
        menu_command(ui, "Review diagnostics...")
        ui.wait("new diagnostic preview", lambda: window("Review diagnostic report"))
        modal = window("Review diagnostic report")
        preview = ui.label(ui.child(105, modal)).replace("\r\n", "\n")
        ui.send(ui.child(1, modal), 0x00F5)
        ui.wait("diagnostic saved confirmation", lambda: window("Diagnostic report saved"))
        saved = list(destination.glob("native-workbench-diagnostics-*.zip"))
        require(len(saved) == 1, "Native explicit Save did not produce exactly one diagnostic ZIP.")
        report["guiDiagnosticExport"] = check_zip(saved[0], preview)
        ui.send(ui.child(1, window("Diagnostic report saved")), 0x00F5)
        report["dpi"] = ui.user.GetDpiForWindow(ui.main)
        report["nativeGUIValidated"] = True
        check(report, "Native Methods is separate, Run retains preparation checks, and diagnostics preview/save controls work; Close saves nothing and explicit Save preserves the exact displayed JSON.")
    finally:
        ui.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app-root", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--asset-sha256", required=True)
    parser.add_argument("--asset-name", required=True)
    parser.add_argument("--app-version", default="0.12.0")
    args = parser.parse_args()
    root, report_path = args.app_root.resolve(), args.report.resolve()
    evidence = report_path.parent
    evidence.mkdir(parents=True, exist_ok=True)
    report = {"schema": 1, "success": False, "appVersion": args.app_version, "sourceCommit": args.source_commit,
              "assetName": args.asset_name, "assetSha256": args.asset_sha256, "gateSha256": sha256(__file__),
              "platform": platform.platform(), "python": sys.version, "evidenceRoot": str(evidence),
              "startedUtc": datetime.now(timezone.utc).isoformat(), "nativeWindowsExecuted": False,
              "nativeGUILaunched": False, "nativeGUIValidated": False, "checks": [], "skips": [],
              "limits": ["Synthetic small-data gate, not a Windows-versus-Linux benchmark or large-data capacity estimate.",
                         "Display assertions cover only the observed runner DPI; physical trackpad, multiple displays and institutional endpoint acceptance are not tested."]}
    try:
        require(os.name == "nt", "This gate requires real native Windows and has no passing skip mode.")
        require(Path(sys.executable).resolve() == (root / "runtime/python/python.exe").resolve(),
                "Execute using the exact packaged app's private Python.")
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
