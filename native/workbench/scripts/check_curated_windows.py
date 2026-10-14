#!/usr/bin/env python3
"""Exact-package native Windows curated-workflow and results gate.

The two bundled synthetic workflows run through the private application host and
native bridge, with independent known-answer assertions. Source/unit coverage,
Windows science, persisted result interpretation and native captures are separate
claims. Use a fresh disposable extraction and its bundled interpreter.
"""
from __future__ import annotations

import argparse
from collections import Counter
import copy
from datetime import datetime, timezone
import gzip
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import traceback

sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_references_windows import PrivateHost, require, sha256, write_json
from check_workspace_ui_windows import NativeUI
from check_batch_windows import NativeList, read_json, until

IDENTITIES = ("alignment-qc", "variant-calling")
PINS = {
    "align": "81c962222c93356a4f7727b23193c71d7dcd515859e62a179574781f411824d3",
    "bam": "45b3f9d5092b0b3014f67b29331003e1214c72919f85695a571fb371030a9888",
    "variants": "ea4b7f0a6c28709e4190b6514c07cbf7bdd58e1a4f2a2d931f2cae3ce6ec3795",
}


def check(report, description):
    report["checks"].append(description)
    print(json.dumps({"passed": len(report["checks"]), "check": description}), flush=True)


def metrics(summary):
    return {item["id"]: item for item in summary["metrics"]}


def complete(host, output):
    started = host.call("run", {"output_folder": str(output)})
    def finished():
        value = host.call("run/get", {"run_id": started["run_id"]})
        return value if value["status"] not in {"preparing", "running", "cancelling"} else None
    run = until("Curated native scientific execution did not finish.", finished, 240)
    require(run["status"] == "completed" and run.get("success"), "Curated workflow failed: " + json.dumps(run))
    return run


def science(root, run, identity, evidence):
    folder = Path(run["folder"])
    record, plan = read_json(folder / "run.json"), read_json(folder / "plan.json")
    require(record["status"] == "success" and record["success"] and record["planSha256"] == plan["sha256"],
            "Curated result does not bind its completed frozen plan.")
    for node in plan["graph"]["nodes"]:
        pack = node["pin"]["packId"]
        if pack in PINS:
            require(node["pin"] == {"packId": pack, "packVersion": "0.4.0", "manifestSha256": PINS[pack]},
                    "Curated graph silently selected a different installed pack.")
    for output in record["outputs"].values():
        require(all(sha256(path) == output["sha256"][name] for name, path in output["files"].items()),
                "Curated scientific output does not match its recorded SHA-256.")
    sam = Path(record["outputs"]["step-1::sam"]["files"]["sam"])
    bam = Path(record["outputs"]["step-2::bam"]["files"]["bam"])
    original = [line for line in sam.read_text().splitlines() if line and not line.startswith("@")]
    decoded = subprocess.run([str(root / "packs/bam-0.4.0/bin/samtools.exe"), "view", "-h", str(bam)],
                             capture_output=True, timeout=60, cwd=root)
    require(decoded.returncode == 0, "Exact bundled SAMtools failed to decode the curated BAM.")
    text = decoded.stdout.decode()
    converted = [line for line in text.splitlines() if line and not line.startswith("@")]
    rows = [line.split("\t") for line in converted]
    require(len(original) == len(rows) == 202 and
            all(int(row[1]) & 1 and int(row[1]) & 2 and not int(row[1]) & 4 and row[2] == "starter" for row in rows),
            "Curated alignment lost 202 mapped proper-pair records on the synthetic contig.")
    require([int(row[3]) for row in rows] == sorted(int(row[3]) for row in rows), "Curated BAM is not coordinate-sorted.")
    require(any(line.startswith("@SQ\tSN:starter\tLN:3000") for line in text.splitlines()) and
            any(line.startswith("@RG\t") and "SM:starter" in line for line in text.splitlines()),
            "Curated BAM lost the known reference length or explicit sample identity.")
    # BAM preparation intentionally fixes mate tags and marks duplicate records;
    # compare the invariant alignment fields, keeping all 202 reads represented.
    invariant = lambda line: tuple(line.split("\t")[index] for index in (0, 2, 3, 4, 5, 9, 10))
    require(Counter(map(invariant, original)) == Counter(map(invariant, converted)),
            "BAM preparation changed alignment coordinates, CIGAR, bases or quality scores.")
    answer = {"alignmentRecords": 202, "mappedProperPairs": 202, "sample": "starter", "reference": "starter:3000"}
    if identity == "variant-calling":
        with gzip.open(record["outputs"]["step-3::variants"]["files"]["variants"], "rt") as stream:
            variants = [line.split("\t") for line in stream if line.strip() and not line.startswith("#")]
        require(len(variants) == 1 and variants[0][:2] == ["starter", "1351"] and variants[0][3:5] == ["G", "A"] and
                variants[0][9].strip().split(":")[variants[0][8].split(":").index("GT")] == "1/1",
                "Curated variant calling lost known starter:1351 G>A GT=1/1 truth.")
        answer["variant"] = "starter:1351 G>A GT=1/1"
    else:
        require(not any(key.startswith("step-3::variants") for key in record["outputs"]),
                "Alignment-only training unexpectedly performed variant calling.")
    for name in ("plan.json", "run.json", "methods-completed.txt", "workflow.cwl"):
        require((folder / name).is_file(), "Curated result omitted methods/provenance: " + name)
    write_json(evidence / (identity + "-run.json"), record)
    return {"id": run["run_id"], "folder": str(folder), "planSha256": plan["sha256"],
            "runSha256": sha256(folder / "run.json"), "answer": answer,
            "outputHashes": {key: value["sha256"] for key, value in record["outputs"].items()}}


def check_summary(summary, identity):
    values = metrics(summary)
    required = {"samtools.stats.raw_total_sequences": 202, "samtools.stats.reads_mapped": 202,
                "samtools.stats.average_length": 100, "samtools.flagstat.total.qc_passed": 202,
                "samtools.flagstat.mapped.qc_passed": 202}
    if identity == "variant-calling":
        required.update({"bcftools.stats.number_of_records": 1, "bcftools.stats.number_of_snps": 1,
                         "bcftools.stats.number_of_indels": 0, "bcftools.stats.number_of_samples": 1})
    for name, value in required.items():
        require(name in values and values[name]["value"] == value, "Missing or incorrect recorded metric: " + name)
        require(sha256(values[name]["source_path"]) == values[name]["sha256"], "Summary metric is not bound to its source file.")
    require(summary["sample"]["available"] and
            any(item["value"] == "starter" for item in summary["sample"]["identities"]),
            "Summary omitted the explicitly recorded sample identity.")
    require(not summary["failures"] and not summary["unavailable"], "Successful curated result has unexpected missing evidence.")
    require(summary["details"] and summary["interpretation"], "Summary omitted readable interpretation limits.")
    return required


def host_checks(root, evidence, report, version):
    fixture = root / "examples/starter"
    profile = read_json(root / "workspace/starter-check-profile.json")
    require(all(sha256(fixture / name) == expected for name, expected in profile["fixtures"].items()),
            "Curated fixture bytes differ from the frozen Starter dataset.")
    output = evidence / "scientific-results"
    output.mkdir()
    host = PrivateHost(root, evidence, "curated-host", offline=True)
    records, summaries = {}, {}
    try:
        require(host.call("init")["app_version"] == version, "Wrong frozen application version.")
        standalone = host.call("workspace/tool", {"toolId": "align/paired-end"})["graph"]
        listing = host.call("examples/list")
        entries = {item["id"]: item for item in listing["workflows"]}
        require(set(entries) == set(IDENTITIES) and all(item["available"] for item in entries.values()),
                "Exact packaged curated catalogue is incomplete or unexpectedly unavailable.")
        require(all("synthetic" in item["details"].lower() and "0.4.0" in item["details"] for item in entries.values()),
                "Curated details omit training scope or exact dependencies.")
        write_json(evidence / "curated-catalogue.json", listing)
        check(report, "Offline catalogue exposes both synthetic workflows, known answers and available exact 0.4.0 dependency pins beside align 0.4.1.")
        for identity in IDENTITIES:
            before = host.call("history")
            state = host.call("examples/load", {"id": identity})
            graph = state["graph"]
            require(state["mode"] == "workflow" and len(graph["nodes"]) == (3 if identity == "alignment-qc" else 5) and len(graph["sources"]) == 2,
                    "Curated load did not create the complete ordinary editable graph.")
            require(host.call("history") == before and not host.call("status")["active"], "Loading unexpectedly executed an analysis.")
            original = copy.deepcopy(graph)
            host.call("model", {"action": "rename_graph", "payload": {"name": "Native curated " + identity}})
            reloaded = host.call("examples/load", {"id": identity})["graph"]
            require(reloaded == original, "Editing one draft changed the reusable curated definition.")
            require(host.call("workspace/mode", {"mode": "tool"})["graph"] == standalone,
                    "Curated load changed the independent standalone tool session.")
            host.call("workspace/mode", {"mode": "workflow"})
            host.call("model", {"action": "rename_graph", "payload": {"name": "Native curated " + identity}})
            require(host.call("review")["valid"], "Curated graph failed ordinary readiness review.")
            run = complete(host, output)
            records[identity] = science(root, run, identity, evidence)
            summary = host.call("results/summary", {"id": run["run_id"]})
            # Retain unavailable/error details before an assertion can stop the gate.
            write_json(evidence / (identity + "-summary.json"), summary)
            records[identity]["expectedSummaryMetrics"] = check_summary(summary, identity)
            summaries[identity] = summary
            check(report, identity + ": editable exact-pin graph executes through native tools with known synthetic alignment truth and hash-bound result measurements.")
        for query, expected in (("VARIANT-CALLING", {records["variant-calling"]["id"]}),
                                ("starter", {item["id"] for item in records.values()}),
                                ("minimap2", {item["id"] for item in records.values()}),
                                ("definitely-unrecorded-result", set())):
            result = host.call("results/search", {"query": query})
            require({item["run_id"] for item in result["runs"]} == expected and result["omitted"] == 0,
                    "Result search returned incorrect identities for " + query)
        check(report, "Result search filters recorded names case-insensitively, explicit sample and tool metadata; an unmatched query returns no records.")
        source = Path(metrics(summaries["variant-calling"])["bcftools.stats.number_of_records"]["source_path"])
        original_bytes = source.read_bytes()
        try:
            source.write_bytes(original_bytes + b"\n# deliberately changed test evidence\n")
            changed = host.call("results/summary", {"id": records["variant-calling"]["id"]})
            require(changed["unavailable"] and not any(item["source_path"] == str(source) for item in changed["metrics"]),
                    "Changed result bytes were still presented as verified measurements.")
            write_json(evidence / "changed-output-summary.json", changed)
        finally:
            source.write_bytes(original_bytes)
        check_summary(host.call("results/summary", {"id": records["variant-calling"]["id"]}), "variant-calling")
        check(report, "A deliberately changed result file is reported unavailable and contributes no trusted metrics; restoring its original bytes restores the summary.")
    finally:
        host.close()
    reopened = PrivateHost(root, evidence, "curated-reopened-host", offline=True)
    try:
        reopened.call("init")
        result = reopened.call("results/search", {"query": "Native curated"})
        require({item["run_id"] for item in result["runs"]} == {item["id"] for item in records.values()},
                "Recorded result search lost completed analyses after reopening.")
        for identity in IDENTITIES:
            check_summary(reopened.call("results/summary", {"id": records[identity]["id"]}), identity)
        check(report, "A fresh private application process restores both results and reconstructs the same scientific summaries from persisted evidence.")
    finally:
        reopened.close()
    # Remove only one required pack from this disposable extraction. The newer
    # additional aligner stays installed; the catalogue must not substitute it.
    pack = root / "packs/align-0.4.0"
    held = root.parent / "curated-held-align-0.4.0"
    pack.rename(held)
    unavailable = None
    try:
        unavailable = PrivateHost(root, evidence, "curated-missing-pin-host", offline=True)
        unavailable.call("init")
        before = unavailable.call("state")["graph"]
        listing = unavailable.call("examples/list")
        require(all(not row["available"] and row["issues"] for row in listing["workflows"]),
                "Missing published align pin was silently replaced by installed align 0.4.1.")
        try:
            unavailable.call("examples/load", {"id": "alignment-qc"})
        except ValueError as error:
            require("0.4.0" in str(error), "Missing pin error lacks an actionable exact version.")
        else:
            raise AssertionError("Missing-pin curated load unexpectedly succeeded.")
        require(unavailable.call("state")["graph"] == before, "Failed curated loading changed the draft.")
        write_json(evidence / "missing-dependency-catalogue.json", listing)
        check(report, "Missing align 0.4.0 disables both curated workflows with exact-version guidance and preserves the draft; installed align 0.4.1 is never substituted.")
    finally:
        try:
            if unavailable:
                unavailable.close()
        finally:
            held.rename(pack)
    diagnosis = PrivateHost(root, evidence, "curated-failed-input-host", offline=True)
    try:
        diagnosis.call("init")
        graph = diagnosis.call("examples/load", {"id": "alignment-qc"})["graph"]
        missing = evidence / "explicitly-selected-missing-reads1.fastq"
        require(not missing.exists(), "Missing-input fixture unexpectedly exists.")
        selected = dict(graph["sources"][0]["files"])
        selected["reads1"] = str(missing)
        diagnosis.call("model", {"action": "apply_fields", "payload": {
            "sourceId": "input-1", "files": {"input-1": selected}}})
        failed_name = "Missing input training diagnosis"
        diagnosis.call("model", {"action": "rename_graph", "payload": {"name": failed_name}})
        started = diagnosis.call("run", {"output_folder": str(output)})
        def failed_preparation():
            value = diagnosis.call("run/get", {"run_id": started["run_id"]})
            return value if value["status"] not in {"preparing", "running", "cancelling"} else None
        failed = until("Missing-input preparation did not reach a recorded failure.", failed_preparation, 60)
        require(failed["status"] == "failed" and not failed.get("success") and not failed.get("planSha256") and
                not failed.get("outputs") and not failed.get("nodes"),
                "Missing selected input did not fail before native execution and scientific outputs.")
        require(failed["name"] == failed_name and missing.name in failed["message"],
                "Failed preparation lost its submitted workflow name or actual missing-file cause.")
        summary = diagnosis.call("results/summary", {"id": started["run_id"]})
        require(summary["status"] == "failed" and not summary["metrics"] and summary["failures"],
                "Failed preparation was presented as successful or supplied unsupported scientific metrics.")
        cause = next((item for item in summary["failures"] if item["message"] == failed["message"]), None)
        require(cause is not None and "input" in cause["action"].lower() and "new run" in cause["action"].lower(),
                "Missing-input summary did not preserve its actual error and actionable input guidance.")
        require(failed["message"] in summary["details"] and cause["action"] in summary["details"] and
                "not a QC pass/fail" in summary["interpretation"],
                "Readable failure detail omitted the cause, next action or limits on QC interpretation.")
        found = diagnosis.call("results/search", {"query": failed_name + " failed"})
        require([item["run_id"] for item in found["runs"]] == [started["run_id"]],
                "Recorded failed preparation cannot be found by submitted name and failure state.")
        write_json(evidence / "missing-input-failed-run.json", failed)
        write_json(evidence / "missing-input-failed-summary.json", summary)
        report["failedPreparation"] = {"id": started["run_id"], "name": failed_name, "missingInput": str(missing),
                                       "message": failed["message"], "action": cause["action"],
                                       "stage": "preparation", "nativeScientificStepsExecuted": 0}
        check(report, "An explicitly selected missing read path fails preparation, retains its actual cause and submitted analysis name, and supplies actionable input guidance without scientific metrics or a QC verdict.")
    finally:
        diagnosis.close()
    require(all(sha256(fixture / name) == expected for name, expected in profile["fixtures"].items()),
            "Curated execution changed bundled input fixtures.")
    require(all(sha256(Path(item["folder"]) / "run.json") == item["runSha256"] for item in records.values()),
            "Result interpretation changed the original execution record.")
    for item in records.values():
        original = read_json(Path(item["folder"]) / "run.json")
        require(all(sha256(path) == output["sha256"][name]
                    for output in original["outputs"].values() for name, path in output["files"].items()),
                "Failure diagnosis changed a previous completed scientific output.")
    report["scientificRuns"] = records
    report["networkSocketOperationsDeniedInScientificHosts"] = True


def gui_checks(root, evidence, report):
    ui = NativeUI(root, evidence)
    report["nativeGUILaunched"] = True
    try:
        def window(title):
            return next((handle for handle in ui.windows() if ui.label(handle) == title), None)
        def button(owner, identity):
            handle = ui.child(identity, owner)
            ui.wait("enabled native button " + str(identity), lambda: ui.user.IsWindowEnabled(handle))
            ui.send(handle, 0x00F5)
        ui.wait("returning native workspace ready", lambda: ui.user.IsWindowEnabled(ui.child(410)) and ui.library().tools())
        ui.fit_window(1280, 900)
        ui.post(ui.main, 0x0111, 1430)
        ui.wait("native curated catalogue", lambda: window("Curated workflows · Native Workbench"))
        curated = window("Curated workflows · Native Workbench")
        rows = NativeList(ui, ui.child(1401, curated))
        ui.wait("two native curated workflows", lambda: rows.count() == 2)
        rows.click(0)
        ui.wait("curated exact dependency detail", lambda: "0.4.0" in ui.label(ui.child(1402, curated)))
        details = ui.label(ui.child(1402, curated))
        require("synthetic" in details.lower() and "202" in details and "SHA-256" in details,
                "Native curated details omit fixture truth, training scope or exact pack identities.")
        report["captures"].append(ui.capture("curated-native-catalogue.bmp", curated))
        write_json(evidence / "curated-native-controls.json", ui.controls(curated))
        ui.wait("curated load enabled", lambda: ui.user.IsWindowEnabled(ui.child(1403, curated)))
        ui.post(ui.child(1403, curated), 0x00F5)
        confirmation = until("Native curated load confirmation did not appear.", lambda: window("Load training workflow"), 20)
        ui.send(ui.child(6, confirmation), 0x00F5)
        ui.wait("curated graph loaded in editable workspace", lambda: "Synthetic training" in ui.label(ui.child(101)))
        if window("Curated workflows · Native Workbench"):
            button(curated, 1407)
        report["captures"].append(ui.capture("curated-native-loaded-workflow.bmp"))
        check(report, "Native curated window lists both workflows, shows exact pins and synthetic expected answers, and loads an editable workflow.")
        ui.post(ui.main, 0x0111, 417)
        ui.wait("native searchable results", lambda: window("Recorded results · Native Workbench"))
        results = window("Recorded results · Native Workbench")
        ui.set_text(ui.child(1501, results), "variant-calling")
        button(results, 1502)
        runs = NativeList(ui, ui.child(1503, results))
        ui.wait("filtered native result", lambda: runs.count() == 1)
        runs.click(0)
        ui.wait("selected result scientific detail", lambda: "202" in ui.label(ui.child(1504, results)) and "starter" in ui.label(ui.child(1504, results)))
        detail = ui.label(ui.child(1504, results))
        require("0.4.0" in detail and "BCFtools" in detail and "SAMtools" in detail,
                "Native result summary omitted recorded tool versions or measured outputs.")
        report["captures"].append(ui.capture("results-native-filtered-summary.bmp", results))
        write_json(evidence / "results-native-controls.json", ui.controls(results))
        failed = report["failedPreparation"]
        ui.set_text(ui.child(1501, results), failed["name"])
        button(results, 1502)
        ui.wait("recorded preparation failure search", lambda: runs.count() == 1 and runs.text(0, 1) == "failed")
        runs.click(0)
        details_control = ui.child(1504, results)
        ui.wait("native failure cause and next action", lambda: failed["message"] in ui.label(details_control) and
                failed["action"] in ui.label(details_control))
        failed_details = ui.label(details_control)
        require("Execution status: failed" in failed_details and "Execution issue" in failed_details,
                "Native failure detail omitted the actual unsuccessful state.")
        report["captures"].append(ui.capture("results-native-failed-preparation.bmp", results))
        # The full text remains independently recorded. Scroll its native edit to
        # the execution issue so the second desktop capture also shows the cause
        # and corrective action when the interpretation notice wraps onto lines.
        offset = failed_details.index("Execution issue")
        character_line = ui.send(details_control, 0x00C9, offset, 0)  # EM_LINEFROMCHAR.
        first_line = ui.send(details_control, 0x00CE)  # EM_GETFIRSTVISIBLELINE.
        ui.send(details_control, 0x00B6, 0, max(0, character_line - first_line))  # EM_LINESCROLL.
        report["captures"].append(ui.capture("results-native-failure-guidance.bmp", results))
        write_json(evidence / "results-native-failed-controls.json", ui.controls(results))
        check(report, "A fresh native desktop finds the named failed preparation and displays its recorded missing-file error, failed execution state and explicit corrective input guidance.")
        ui.set_text(ui.child(1501, results), "definitely-unrecorded-result")
        button(results, 1502)
        ui.wait("empty native search state", lambda: runs.count() == 0)
        require(not ui.user.IsWindowEnabled(ui.child(1505, results)), "Native View remains enabled without a selected result.")
        report["captures"].append(ui.capture("results-native-empty-search.bmp", results))
        button(results, 1508)
        report["dpi"] = ui.user.GetDpiForWindow(ui.main)
        report["nativeGUIValidated"] = True
        check(report, "Native results search selects the recorded variant run, renders sample/tool versions and scientific metrics, and disables View for an empty result set.")
    except Exception:
        try:
            ui.desktop_evidence("curated/results gate failure")
            for number, handle in enumerate(ui.windows()):
                ui.capture("curated-failure-%d.bmp" % number, handle)
                write_json(evidence / ("curated-failure-%d.json" % number), {"title": ui.label(handle), "controls": ui.controls(handle)})
        except Exception as error:
            report["failureCaptureError"] = str(error)
        raise
    finally:
        ui.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app-root", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--asset-sha256", required=True)
    parser.add_argument("--asset-name", required=True)
    parser.add_argument("--app-version", required=True)
    args = parser.parse_args()
    root, target = args.app_root.resolve(), args.report.resolve()
    evidence = target.parent
    evidence.mkdir(parents=True, exist_ok=True)
    report = {"schema": 1, "success": False, "appVersion": args.app_version, "sourceCommit": args.source_commit,
              "assetName": args.asset_name, "assetSha256": args.asset_sha256, "gateSha256": sha256(__file__),
              "platform": platform.platform(), "python": sys.version, "startedUtc": datetime.now(timezone.utc).isoformat(),
              "nativeWindowsExecuted": False, "nativeGUILaunched": False, "nativeGUIValidated": False,
              "checks": [], "skips": [], "captures": [],
              "limits": ["Small bundled synthetic inputs and exact pack pins; no clinical accuracy, biological dataset or capacity claim.",
                         "Metrics are recorded measurements with explicit source identities, not inferred sample QC pass/fail.",
                         "Private scientific hosts deny Python socket operations; this is not operating-system firewall isolation.",
                         "Hosted display DPI only; physical trackpad, high DPI, multi-monitor and institutional acceptance remain separate."]}
    try:
        require(os.name == "nt", "This gate requires native Windows; unavailable execution cannot pass.")
        require(Path(sys.executable).resolve() == (root / "runtime/python/python.exe").resolve(), "Use the exact app's private Python.")
        report["appFiles"] = {str(path.relative_to(root)): sha256(path) for path in
                              [root / "NativeWorkbench.exe", root / "WorkbenchBridge.exe", *sorted((root / "workspace").glob("*.py"))]}
        host_checks(root, evidence, report, args.app_version)
        report["nativeWindowsExecuted"] = True
        gui_checks(root, evidence, report)
        require({name: sha256(root / name) for name in report["appFiles"]} == report["appFiles"],
                "Application bytes changed during the curated/results gate.")
        report["success"] = True
    except Exception as error:
        report.update(error=str(error), traceback=traceback.format_exc())
        print(json.dumps({"gateError": str(error), "traceback": report["traceback"]}), flush=True)
    finally:
        report.update(completedUtc=datetime.now(timezone.utc).isoformat(), passed=len(report["checks"]),
                      failed=0 if report["success"] else 1, skipped=len(report["skips"]))
        write_json(target, report)
    print(json.dumps({"success": report["success"], "passed": report["passed"], "report": str(target)}), flush=True)
    return 0 if report["success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
