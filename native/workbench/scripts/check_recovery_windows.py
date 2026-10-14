#!/usr/bin/env python3
"""Exact-package Windows recovery, resource admission and project gate.

Core checks use the untouched extracted application and its private interpreter.
The abrupt-termination case uses a separate extraction with a labelled callback
barrier, restores the original service bytes, then restarts the unmodified app.
Synthetic execution intervals establish admission behavior, never benchmarking.
"""
from __future__ import annotations

import argparse
import copy
import ctypes
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import sys
import tempfile
import time
import traceback
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_batch_windows import (NativeList, NativeUI, add_job, check, queue_ready,
    queue_state, read_json, scientific_truth, start_host, until, wait_jobs)
from check_references_windows import require, sha256, stop_process_tree, write_json


def save_receipts(root, evidence, prefix, report):
    for name in ("run-queue.json", "runs.json"):
        source = root / "user-data" / name
        if source.exists():
            try:
                target = evidence / (prefix + "-" + name)
                write_json(target, read_json(source))
                report.setdefault("receipts", []).append({"file": target.name, "sha256": sha256(target)})
            except Exception as error:
                report.setdefault("receiptCaptureErrors", []).append({"file": name, "error": str(error)})


def complete_job(host, graph, output):
    job = add_job(host, graph, output)
    host.call("queue/start")
    result = wait_jobs(host, {job["job_id"]})[0]
    if result["status"] != "completed":
        detail = host.call("run/get", {"run_id": result["job_id"]})
        raise AssertionError("Native queued workflow failed: " + json.dumps({"job": result, "run": detail}))
    return result


def review_actions(review):
    return {node["id"]: node["action"] for node in review["nodes"]}


def queue_review(host, review, output):
    before = {job["job_id"] for job in queue_state(host)["jobs"]}
    host.call("restart/queue", {"token": review["token"], "output_folder": str(output)})
    state = queue_ready(host)
    added = [job for job in state["jobs"] if job["job_id"] not in before]
    require(len(added) == 1 and added[0]["status"] == "queued" and state["paused"],
            "Reviewed restart did not freeze one paused job for explicit Start.")
    require(not (Path(added[0]["folder"]) / "run.json").exists(), "Restart review or queueing executed analysis.")
    return added[0]


def fresh_graph(host, root, data):
    graph = host.call("example")["graph"]
    graph["name"] = "Synthetic verified recovery scientific chain"
    # A private input copy permits deliberate mutations without changing the
    # frozen application's examples or their published fixture identities.
    for source in graph["sources"]:
        for field, value in list(source["files"].items()):
            target = data / (source["id"] + "-" + Path(value).name)
            shutil.copyfile(value, target)
            source["files"][field] = str(target)
    return graph


def restart_checks(host, root, data, evidence, report):
    sys.path.insert(0, str(root / "workspace"))
    from catalog import load_catalog
    from engine import Engine
    catalog = load_catalog(root)
    engine = Engine(root, catalog)
    output = data / "results"
    output.mkdir()
    graph = fresh_graph(host, root, data)
    original = complete_job(host, graph, output)
    report["baselineScience"] = scientific_truth(root, original)
    folder = Path(original["folder"])
    original_record = read_json(folder / "run.json")
    source_hash = sha256(folder / "run.json")
    review = host.call("restart/review", {"run_id": original["job_id"]}, timeout=120)
    write_json(evidence / "completed-restart-review.json", review)
    require(review_actions(review) == {"step-1": "reuse", "step-2": "reuse", "step-3": "reuse", "step-4": "reuse", "step-5": "run"},
            "An unchanged completed chain did not verify four native steps and rebuild the path-bearing report.")
    restarted = queue_review(host, review, output)
    host.call("queue/start")
    restarted = wait_jobs(host, {restarted["job_id"]})[0]
    report["restartedScience"] = scientific_truth(root, restarted)
    recovered = read_json(Path(restarted["folder"]) / "run.json")
    require(Path(restarted["folder"]) != folder and sha256(folder / "run.json") == source_hash,
            "Restart mutated the original result rather than preparing a new result folder.")
    require({key: value["sha256"] for key, value in recovered["outputs"].items() if not key.startswith("step-5::")} ==
            {key: value["sha256"] for key, value in original_record["outputs"].items() if not key.startswith("step-5::")},
            "Verified restart changed completed scientific output bytes.")
    require(all(node.get("recovery", {}).get("action") == "reused" for node in recovered["nodes"] if node["id"] != "step-5"),
            "Reused completed steps are not explicitly distinguished in the result record.")
    rebuilt_report = next(node for node in recovered["nodes"] if node["id"] == "step-5")
    require(rebuilt_report["status"] == "success" and rebuilt_report.get("recovery", {}).get("action") != "reused",
            "The builtin report did not rebuild for the new result paths.")
    metrics = read_json(Path(restarted["folder"]) / "performance.json")
    require(all(not item["backendMetrics"]["available"] for item in metrics["steps"]),
            "A reused step fabricated new native resource measurements.")
    check(report, "An explicit reviewed restart creates a new paused plan; Start reuses four verified completed native steps byte-for-byte, rebuilds the path-bearing report and preserves the source result, retains known scientific truth and does not fabricate native measurements.")

    decisions = {}
    changed = copy.deepcopy(graph)
    changed["nodes"][0]["params"]["sample"] = "changed-synthetic-sample"
    decisions["parameters"] = engine.review_restart(changed, str(folder))
    require(review_actions(decisions["parameters"]) == {identity: "run" for identity in ("step-1", "step-2", "step-3", "step-4", "step-5")},
            "Changed alignment parameters did not invalidate its descendants.")
    alternate = copy.deepcopy(graph)
    current = alternate["nodes"][0]["pin"]["packVersion"]
    other = next(tool for tool in catalog["toolVersions"]["align/paired-end"] if tool["packVersion"] != current)
    alternate["nodes"][0]["pin"] = {key: other[key] for key in ("packId", "packVersion", "manifestSha256")}
    decisions["pins"] = engine.review_restart(alternate, str(folder))
    require(review_actions(decisions["pins"]) == {identity: "run" for identity in ("step-1", "step-2", "step-3", "step-4", "step-5")},
            "A changed exact pack pin did not invalidate its descendants.")
    reads = Path(next(source for source in graph["sources"] if source["type"] == "pair")["files"]["reads1"])
    original_reads = reads.read_bytes()
    try:
        reads.write_bytes(original_reads + b"\n")
        decisions["input"] = engine.review_restart(graph, str(folder))
        require(review_actions(decisions["input"]) == {identity: "run" for identity in ("step-1", "step-2", "step-3", "step-4", "step-5")},
                "Changed input bytes did not invalidate the consumer and its descendants.")
    finally:
        reads.write_bytes(original_reads)
    bam = Path(original_record["outputs"]["step-2::bam"]["files"]["bam"])
    original_bam = bam.read_bytes()
    try:
        bam.write_bytes(original_bam + b"changed")
        decisions["output"] = engine.review_restart(graph, str(folder))
        require(review_actions(decisions["output"]) == {"step-1": "reuse", "step-2": "run", "step-3": "run", "step-4": "run", "step-5": "run"},
                "Changed BAM output did not invalidate exactly its producing step and descendants.")
    finally:
        bam.write_bytes(original_bam)
    write_json(evidence / "recovery-invalidation-reviews.json", decisions)
    check(report, "Production Engine reviews invalidate changed input bytes, parameters and exact pack pins with their descendants; a tampered intermediate BAM invalidates its producer and descendants while the verified ancestor remains reusable.")
    return graph, original, restarted


def install_fault_barrier(root):
    path = root / "workspace/service.py"
    original = path.read_bytes()
    source = original.decode("utf-8")
    needle = '                        run["events"].append(copy.deepcopy(event))\n'
    require(source.count(needle) == 1, "Queue callback fixture insertion is ambiguous.")
    barrier = '''                        # GATE FIXTURE ONLY: abrupt termination at a persisted step boundary.
                        if event.get("type") == "step" and event.get("nodeId") == "step-1" and event.get("status") == "success":
                            import time as fixture_time
                            (self.data / "recovery-fault-entered").write_text("persisted step-1 success", encoding="utf-8")
                            fixture_deadline = fixture_time.monotonic() + 60
                            while fixture_time.monotonic() < fixture_deadline:
                                fixture_time.sleep(0.02)
                            raise TimeoutError("Recovery gate did not terminate the blocked host within 60 seconds.")
'''
    path.write_bytes(source.replace(needle, barrier + needle).encode("utf-8"))
    return path, original


def fault_checks(root, data, evidence, report):
    output = data / "fault-results"
    output.mkdir()
    input_folder = data / "fault-inputs"
    input_folder.mkdir()
    original_exe = sha256(root / "NativeWorkbench.exe")
    service, original = install_fault_barrier(root)
    fault = {"fixtureOnlyDuringAbruptTermination": True, "originalServiceSha256": hashlib.sha256(original).hexdigest(),
             "instrumentedServiceSha256": sha256(service), "nativeExecutableSha256": original_exe,
             "scope": "Separate extraction with a bounded callback barrier after persisted step-1 success; external process-tree termination. Original service bytes are restored before reopening and performing recovery."}
    report["faultInjection"] = fault
    host = None
    try:
        host = start_host(root, evidence, "fault-instrumented-host")
        require(host.call("init")["app_version"] == report["appVersion"], "Incorrect fault candidate version.")
        graph = fresh_graph(host, root, input_folder)
        job = add_job(host, graph, output)
        host.call("queue/start")
        marker = root / "user-data/recovery-fault-entered"
        until("Completed-step abrupt-termination barrier was not reached.", marker.exists, 180)
        snapshot = read_json(Path(job["folder"]) / "run.json")
        require(any(node["id"] == "step-1" and node["status"] == "success" for node in snapshot["nodes"]),
                "Fault barrier fired before the completed step was durably recorded.")
        fault["interruptedRun"] = snapshot
        stop_process_tree(host.process)
        host.stderr.close()
        host = None
    finally:
        if host is not None:
            stop_process_tree(host.process)
            host.stderr.close()
        service.write_bytes(original)
        fault["restoredServiceSha256"] = sha256(service)
        require(fault["restoredServiceSha256"] == fault["originalServiceSha256"], "Fault fixture failed to restore exact service bytes.")
    host = start_host(root, evidence, "fault-reopened-exact-host")
    try:
        host.call("init")
        state = queue_state(host)
        observed = next(row for row in state["jobs"] if row["job_id"] == job["job_id"])
        require(state["paused"] and observed["status"] == "interrupted", "Abruptly abandoned work was automatically resumed or not labelled interrupted.")
        review = host.call("restart/review", {"run_id": job["job_id"]}, timeout=120)
        require(review_actions(review) == {"step-1": "reuse", "step-2": "run", "step-3": "run", "step-4": "run", "step-5": "run"},
                "Restart did not reuse only the completed verified ancestor after abrupt termination.")
        fault["review"] = review
        restarted = queue_review(host, review, output)
        host.call("queue/start")
        restarted = wait_jobs(host, {restarted["job_id"]})[0]
        fault["restartedScience"] = scientific_truth(root, restarted)
        require(sha256(root / "NativeWorkbench.exe") == original_exe and sha256(service) == fault["originalServiceSha256"],
                "Restored native restart did not use the original candidate bytes.")
        check(report, "A separately labelled abrupt-termination fixture leaves a paused interrupted job; after exact service bytes are restored, explicit restart reuses only its verified completed ancestor and produces the expected 202 alignments and homozygous SNP.")
    finally:
        try:
            host.close()
        finally:
            save_receipts(root, evidence, "fault-final", report)


def intervals(record):
    result = []
    for node in record["nodes"]:
        if "started" in node and "finished" in node:
            result.append({"id": node["id"], "started": node["started"], "finished": node["finished"],
                           "status": node["status"], "reservation": node["reservation"]})
    return result


def overlap(rows):
    return max(0.0, (min(datetime.fromisoformat(row["finished"].replace("Z", "+00:00")) for row in rows) -
                     max(datetime.fromisoformat(row["started"].replace("Z", "+00:00")) for row in rows)).total_seconds())


def assert_admission(record, policy):
    events = []
    for row in intervals(record):
        events.append((row["started"], 1, row["reservation"]["cpus"]))
        events.append((row["finished"], -1, -row["reservation"]["cpus"]))
    cpus = active = peak = 0
    for _, delta, slots in sorted(events):
        cpus += slots
        active += delta
        require(0 <= cpus <= policy["cpuBudget"] and 0 <= active <= policy["maxParallel"],
                "Recorded native step intervals exceed their frozen admission budget.")
        peak = max(peak, active)
    require(cpus == 0 and active == 0, "Unbalanced native admission intervals.")
    require(record["resources"] == policy, "Execution changed its frozen resource policy.")
    return peak


def resource_checks(host, root, graph, data, evidence, report):
    state = host.call("resources/get", {"graph": graph})
    require(state["logical_cpus"] >= 2, "Native parallel admission requires at least two available logical CPUs.")
    branches = copy.deepcopy(graph)
    branches["name"] = "Synthetic branch admission observations, not a benchmark"
    branches["nodes"] = [copy.deepcopy(graph["nodes"][0]), copy.deepcopy(graph["nodes"][0])]
    branches["nodes"][1]["id"] = "step-2"
    branches["nodes"][1]["label"] = "Second independent alignment"
    for node in branches["nodes"]:
        node["params"]["threads"] = "1"
    # A bounded 400-fold synthetic input gives real native commands enough
    # duration to establish overlapping intervals without treating timings as
    # representative throughput measurements.
    for source in branches["sources"]:
        if source["type"] == "pair":
            for field, filename in source["files"].items():
                target = data / ("parallel-" + field + ".fastq")
                original = Path(filename).read_bytes()
                with target.open("wb") as stream:
                    for _ in range(400):
                        stream.write(original)
                source["files"][field] = str(target)
    output = data / "parallel-results"
    output.mkdir()
    temp = data / "selected-temporary-storage"
    temp.mkdir()
    observations = {}
    cases = {"cpu-budget-one": {"cpuBudget": 1, "maxParallel": 2, "stepCpus": {"step-1": 1, "step-2": 1}, "temporaryFolder": str(temp)},
             "step-limit-one": {"cpuBudget": 2, "maxParallel": 1, "stepCpus": {"step-1": 1, "step-2": 1}, "temporaryFolder": str(temp)},
             "unknown-exclusive": {"cpuBudget": 2, "maxParallel": 2, "stepCpus": {}, "temporaryFolder": str(temp)},
             "declared-parallel": {"cpuBudget": 2, "maxParallel": 2, "stepCpus": {"step-1": 1, "step-2": 1}, "temporaryFolder": str(temp)}}
    for name, policy in cases.items():
        host.call("resources/set", {"graph": branches, "policy": policy})
        queued = add_job(host, branches, output)
        # Changes to global settings after preparation must not alter this plan.
        if name == "declared-parallel":
            host.call("resources/set", {"graph": branches, "policy": cases["cpu-budget-one"]})
        host.call("queue/start")
        completed = wait_jobs(host, {queued["job_id"]})[0]
        require(completed["status"] == "completed", "Native resource case failed: " + str(completed))
        record = read_json(Path(completed["folder"]) / "run.json")
        peak = assert_admission(record, policy)
        rows = intervals(record)
        seconds = overlap(rows)
        require(peak == (2 if name == "declared-parallel" else 1), "Native concurrency did not match explicit admission policy.")
        require(seconds > 0 if name == "declared-parallel" else seconds == 0, "Native step overlap did not match admission policy.")
        if name == "unknown-exclusive":
            require(all(row["reservation"]["source"] == "unknown-exclusive" and row["reservation"]["cpus"] == 2 for row in rows),
                    "Unknown CPU requirements were guessed instead of running exclusively.")
        for value in record["outputs"].values():
            require(all(sha256(path) == value["sha256"][key] for key, path in value["files"].items()), "Parallel scientific output checksum differs.")
        for identity in ("step-1", "step-2"):
            sam = Path(record["outputs"][identity + "::sam"]["files"]["sam"])
            with sam.open(encoding="utf-8") as stream:
                count = sum(1 for line in stream if line and not line.startswith("@"))
            require(count == 202 * 400, "A parallel branch changed the expected mapped record count.")
        owned_temp = Path(record["temporaryStorage"]["folder"])
        require(owned_temp.parent == temp and owned_temp.is_dir() and (owned_temp / "S1").is_dir() and (owned_temp / "S2").is_dir(),
                "Native commands did not receive separate run-owned temporary directories.")
        observations[name] = {"policy": policy, "peakActiveSteps": peak, "overlapSeconds": seconds,
                              "intervals": rows, "planSha256": completed["plan_sha256"], "alignmentCountPerBranch": 80800,
                              "temporaryStorage": record["temporaryStorage"], "benchmark": False}
    write_json(evidence / "native-admission-observations.json", observations)
    report["resourceObservations"] = observations
    check(report, "Real native independent branches obey CPU-slot and maximum-step admission limits, unknown requirements run exclusively, and two explicitly reserved branches overlap; the queued policy stays frozen after settings change, with separate temporary directories and 80,800 records per branch. These are admission observations, not benchmarks.")

    host.call("resources/set", {"graph": branches, "policy": cases["declared-parallel"]})
    cancelled = add_job(host, branches, output)
    host.call("queue/start")
    def two_running():
        queued = queue_state(host)
        job = next(item for item in queued["jobs"] if item["job_id"] == cancelled["job_id"])
        if job["status"] in {"completed", "failed", "cancelled", "interrupted"}:
            raise AssertionError("Parallel cancellation job became terminal before observation: " + json.dumps(job))
        if queued["active_job"] != cancelled["job_id"]:
            return None
        state = host.call("run/get", {"run_id": cancelled["job_id"]})
        callbacks = {event.get("nodeId") for event in state["events"] if event.get("type") in {"phase", "log"}}
        bridges = list(Path(cancelled["folder"]).glob("*/bridge-request.json"))
        return state if sum(node.get("status") == "running" for node in state["nodes"]) == 2 and len(bridges) == 2 and callbacks >= {"step-1", "step-2"} else None
    until("Two real native branches did not become active for cancellation.", two_running, 120)
    started = time.monotonic()
    host.call("queue/cancel", {"job_id": cancelled["job_id"]})
    cancelled = wait_jobs(host, {cancelled["job_id"]})[0]
    require(cancelled["status"] == "cancelled", "Cancellation did not stop the parallel job.")
    cancelled_record = read_json(Path(cancelled["folder"]) / "run.json")
    require(all(node["status"] == "cancelled" for node in cancelled_record["nodes"]), "Parallel cancellation left a running or falsely successful branch.")
    report["parallelCancellation"] = {"elapsedSeconds": time.monotonic() - started, "nodes": cancelled_record["nodes"], "benchmark": False}
    check(report, "Cancellation reaches both active native branches and the durable queue records the job as cancelled; no branch remains marked running.")

    # Add a real dependency to the first branch; deliberately changed frozen
    # input bytes must fail its consumers and block the downstream BAM step.
    failed_graph = copy.deepcopy(branches)
    downstream = copy.deepcopy(graph["nodes"][1]); downstream["id"] = "step-3"
    failed_graph["nodes"].append(downstream)
    policy = dict(cases["declared-parallel"], stepCpus={"step-1": 1, "step-2": 1, "step-3": 1})
    host.call("resources/set", {"graph": failed_graph, "policy": policy})
    failed = add_job(host, failed_graph, output)
    changed = Path(next(source for source in failed_graph["sources"] if source["type"] == "pair")["files"]["reads1"])
    original_size = changed.stat().st_size
    with changed.open("ab") as stream:
        stream.write(b"changed after freezing")
    try:
        host.call("queue/start")
        failed = wait_jobs(host, {failed["job_id"]})[0]
        result = read_json(Path(failed["folder"]) / "run.json")
        statuses = {node["id"]: node["status"] for node in result["nodes"]}
        require(failed["status"] == "failed" and statuses == {"step-1": "failed", "step-2": "failed", "step-3": "blocked"},
                "Changed input did not fail independent consumers and block their dependent work.")
        report["dependencyFailure"] = {"statuses": statuses, "messages": {node["id"]: node.get("message", "") for node in result["nodes"]}}
    finally:
        with changed.open("r+b") as stream:
            stream.truncate(original_size)
    host.call("resources/set", {"graph": graph, "policy": {"cpuBudget": 1, "maxParallel": 1, "stepCpus": {}, "temporaryFolder": ""}})
    check(report, "A deliberately changed frozen input fails both consumers, blocks their dependent BAM step and pauses the queue without silently retrying analysis.")


def rewrite_zip(source, target, transform):
    with zipfile.ZipFile(source) as archive:
        members = {name: archive.read(name) for name in archive.namelist()}
    transform(members)
    with zipfile.ZipFile(target, "x", compression=zipfile.ZIP_STORED) as archive:
        for name, value in members.items():
            archive.writestr(name, value)


def expected_error(host, method, params, fragment):
    try:
        host.call(method, params, timeout=120)
    except ValueError as error:
        require(fragment.lower() in str(error).lower(), "Unexpected rejection: " + str(error))
        return str(error)
    raise AssertionError("Operation unexpectedly succeeded: " + method)


def project_checks(host, root, graph, original, data, evidence, report):
    archive = evidence / "synthetic-portable-project.zip"
    # Windows' default temporary directory may use an 8.3 alias even though
    # ordinary-file validation resolves the long name. Exercise that exact
    # packaged boundary with data created by this gate, not a mocked path.
    with tempfile.TemporaryDirectory(prefix="nw-project-alias-") as temporary:
        alias_graph = copy.deepcopy(graph)
        alias_input = None
        for source in alias_graph["sources"]:
            for field, filename in list(source["files"].items()):
                target = Path(temporary) / (source["id"] + "-" + Path(filename).name)
                shutil.copyfile(filename, target)
                source["files"][field] = str(target)
                alias_input = alias_input or target
        require(os.path.normcase(str(alias_input)) != os.path.normcase(str(alias_input.resolve())),
                "This Windows host did not expose distinct short/long temporary input spellings for the alias regression.")
        alias_preview = host.call("project/export-preview", {"graph": alias_graph, "include_data": True,
                                  "sample_metadata": {"file": str(alias_input)}}, timeout=120)
        alias_archive = evidence / "synthetic-short-path-project.zip"
        host.call("project/export", {"token": alias_preview["token"], "destination": str(alias_archive)}, timeout=120)
        with zipfile.ZipFile(alias_archive) as zipped:
            alias_manifest = json.loads(zipped.read("project.json"))
        require(alias_manifest["sampleMetadata"]["file"] == "nw-input:data-000001" and
                json.dumps(str(alias_input), ensure_ascii=False) not in json.dumps(alias_manifest, ensure_ascii=False),
                "A short-name input alias escaped project metadata tokenization as an absolute machine path.")
        report["shortPathProjectExport"] = {"distinctSpellingsObserved": True, "samplePathTokenized": True,
                                             "archiveSha256": sha256(alias_archive)}
    descriptive = {"study": "synthetic-portable-project", "sample_id": "synthetic-sample"}
    preview = host.call("project/export-preview", {"graph": graph, "include_data": True, "sample_metadata": descriptive}, timeout=120)
    require(len(preview["dependencies"]) == 3 and all(row["included"] for row in preview["dependencies"]),
            "Explicit project export did not select exactly three bound scientific input files.")
    exported = host.call("project/export", {"token": preview["token"], "destination": str(archive)}, timeout=120)
    require(exported["sha256"] == sha256(archive), "Exported project checksum differs.")
    with zipfile.ZipFile(archive) as zipped:
        require(zipped.testzip() is None, "Project export CRC check failed.")
        manifest = json.loads(zipped.read("project.json"))
        require(set(zipped.namelist()) == {"project.json", "workflow.cwl", *[row["path"] for row in manifest["dependencies"]]},
                "Project bundle included an unreviewed file.")
        require(all(Path(name).suffix.lower() not in {".exe", ".dll", ".pyd", ".py"} for name in zipped.namelist()),
                "Project bundle redistributed an executable or private runtime.")
        require(all(value.startswith("nw-input:") for source in manifest["graph"]["sources"] for value in source["files"].values()),
                "Portable graph retained original absolute input paths.")
        require(manifest["linuxProfile"]["scientificEquivalenceValidated"] is False, "Project invented Linux scientific equivalence.")
    moved_archive = data / "project archive moved.zip"
    shutil.copyfile(archive, moved_archive)
    inspected = host.call("project/inspect", {"path": str(moved_archive)}, timeout=120)
    require(inspected["ready"] and all(row["status"] == "bundled" for row in inspected["dependencies"]), "Complete moved bundle was not independently verified offline.")
    imported_folder = data / "imported project"
    imported = host.call("project/import", {"token": inspected["token"], "destination_folder": str(imported_folder)}, timeout=120)
    require(imported["model_loaded"] and imported_folder.is_dir(), "Explicit import did not load the project draft.")
    moved = data / "project moved again"
    imported_folder.rename(moved)
    reopened = host.call("project/open", {"folder": str(moved)}, timeout=120)
    rebound = reopened["model"]["graph"]
    require(reopened["model_loaded"] and all(Path(value).is_relative_to(moved) for source in rebound["sources"] for value in source["files"].values()),
            "Reopening a moved project did not rebind its relative input files.")
    output = data / "portable-project-results"
    output.mkdir()
    executed = complete_job(host, rebound, output)
    report["portableScience"] = scientific_truth(root, executed)
    completed_folder = Path(executed["folder"])
    plan = read_json(completed_folder / "plan.json")
    result = read_json(completed_folder / "run.json")
    cwl = read_json(completed_folder / "workflow.cwl")["$graph"][0]
    context = reopened["projectMetadata"]
    require(context["sampleMetadata"] == descriptive and context["referencesAreHistorical"] is True and
            all(Path(item["boundPath"]).is_relative_to(moved) for item in context["dependencies"]),
            "Relocation lost descriptive project metadata or confused historical receipts with current references.")
    require(plan["project"] == result["project"] == context and json.loads(cwl["nw:project"]) == context and
            json.loads(cwl["nw:execution"]["recordJson"])["project"] == context and
            "Historical reference receipts and descriptive sample metadata are retained in the project section" in result["methods"],
            "Imported project identity and metadata were not frozen into the native plan, run, CWL and completed methods.")
    report["portableBundle"] = {"sha256": sha256(archive), "bytes": archive.stat().st_size, "manifest": manifest,
                                "networkBlockedByAuditHook": True, "movedTwice": True}
    check(report, "An explicitly selected three-input project contains CWL, relative file identities and exact pack requirements without executables; offline import and a second folder move preserve input bytes, project/sample metadata in plan/run/CWL/methods and the known native scientific result.")

    external = evidence / "synthetic-external-project.zip"
    preview = host.call("project/export-preview", {"graph": graph, "include_data": False}, timeout=120)
    host.call("project/export", {"token": preview["token"], "destination": str(external)}, timeout=120)
    missing = host.call("project/inspect", {"path": str(external)}, timeout=120)
    require(not missing["ready"] and all(row["status"] == "missing" for row in missing["dependencies"]), "Unbundled dependencies were silently guessed.")
    mappings = {row["id"]: next(value for source in graph["sources"] for value in source["files"].values() if Path(value).name == row["filename"]) for row in missing["dependencies"]}
    wrong = data / "wrong-input.fasta"; wrong.write_text(">wrong\nACGT\n", encoding="utf-8")
    first = missing["dependencies"][0]["id"]
    mismatch = host.call("project/resolve", {"token": missing["token"], "mappings": {first: str(wrong)}}, timeout=120)
    require(not mismatch["ready"] and next(row for row in mismatch["dependencies"] if row["id"] == first)["status"] == "mismatch", "A wrong mapped file was accepted.")
    mapped = host.call("project/resolve", {"token": mismatch["token"], "mappings": mappings}, timeout=120)
    require(mapped["ready"] and all(row["status"] == "mapped" for row in mapped["dependencies"]), "Exact explicitly mapped input bytes were rejected.")
    host.call("project/import", {"token": mapped["token"], "destination_folder": str(data / "explicitly mapped project")}, timeout=120)
    report["projectDependencyReview"] = {"missing": missing, "mismatch": mismatch, "resolved": mapped}

    absent = evidence / "synthetic-missing-pack.zip"
    def absent_pack(members):
        value = json.loads(members["project.json"])
        tool = value["graph"]["nodes"][0]["tool"]
        value["graph"]["nodes"][0]["pin"]["packVersion"] = "99.0.0"
        next(row for row in value["packs"] if row["tool"] == tool)["pin"]["packVersion"] = "99.0.0"
        members["project.json"] = json.dumps(value).encode("utf-8")
    rewrite_zip(archive, absent, absent_pack)
    missing_pack = host.call("project/inspect", {"path": str(absent)}, timeout=120)
    require(not missing_pack["ready"] and any(row["status"] == "missing-or-incompatible" for row in missing_pack["packs"]),
            "Unavailable exact pack version was silently substituted.")
    report["missingPackReview"] = missing_pack
    check(report, "An external-data project reports all absent inputs, rejects an incorrect explicit mapping and imports only byte-identical mappings; an unavailable exact pack version stays unresolved without substitution or download.")

    tampered = evidence / "synthetic-tampered-project.zip"
    member = manifest["dependencies"][0]["path"]
    def tamper(members):
        payload = bytearray(members[member]); payload[-1] ^= 1; members[member] = bytes(payload)
    rewrite_zip(archive, tampered, tamper)
    traversal = evidence / "synthetic-traversal-project.zip"
    rewrite_zip(archive, traversal, lambda members: members.update({"../escape.txt": b"must not escape"}))
    duplicate = evidence / "synthetic-case-collision-project.zip"
    rewrite_zip(archive, duplicate, lambda members: members.update({"PROJECT.JSON": members["project.json"]}))
    report["projectRejections"] = {
        "tampered": expected_error(host, "project/inspect", {"path": str(tampered)}, "checksum"),
        "traversal": expected_error(host, "project/inspect", {"path": str(traversal)}, "path"),
        "caseCollision": expected_error(host, "project/inspect", {"path": str(duplicate)}, "colliding")}
    require(not (evidence.parent / "escape.txt").exists() and not (data / "escape.txt").exists(), "Malformed archive escaped its project boundary.")
    check(report, "Project inspection rejects a checksum-tampered member, parent traversal and a case-colliding archive before extraction; no outside file is created.")
    return archive


def host_checks(root, fault_root, data, evidence, report):
    host = start_host(root, evidence, "recovery-exact-host")
    try:
        require(host.call("init")["app_version"] == report["appVersion"], "Incorrect frozen app version.")
        graph, original, restarted = restart_checks(host, root, data, evidence, report)
        resource_checks(host, root, graph, data, evidence, report)
        project = project_checks(host, root, graph, original, data, evidence, report)
        report["guiFixture"] = {"runId": original["job_id"], "runFolder": original["folder"], "project": str(project), "graph": graph}
    finally:
        try:
            host.close()
        finally:
            save_receipts(root, evidence, "host-final", report)
    fault_checks(fault_root, data, evidence, report)


def gui_checks(root, data, evidence, report):
    ui = NativeUI(root, evidence)
    report["nativeGUILaunched"] = True
    try:
        def window(title):
            return next((handle for handle in ui.windows() if ui.label(handle) == title), None)
        def button(parent, identity):
            handle = ui.child(identity, parent)
            ui.wait("enabled native control " + str(identity), lambda: ui.user.IsWindowEnabled(handle))
            ui.send(handle, 0x00F5)
        ui.wait("returning native workspace ready", lambda: ui.user.IsWindowEnabled(ui.child(410)) and ui.library().tools())
        ui.fit_window(1280, 900)
        ui.post(ui.main, 0x0111, 302)
        ui.wait("example workflow loaded", lambda: "Starter example" in ui.label(ui.child(101)))
        ui.post(ui.main, 0x0111, 427)
        ui.wait("native resource policy", lambda: window("Resources · Native Workbench"))
        resources = window("Resources · Native Workbench")
        rows = NativeList(ui, ui.child(1105, resources))
        ui.wait("resource steps loaded", lambda: rows.count() == 5 and ui.user.IsWindowEnabled(ui.child(1109, resources)))
        ui.set_text(ui.child(1101, resources), "2")
        ui.set_text(ui.child(1102, resources), "2")
        rows.click(0)
        ui.set_text(ui.child(1106, resources), "1")
        button(resources, 1107)
        ui.wait("explicit first-step reservation shown", lambda: rows.text(0, 1) == "1")
        require(all("Unknown" in rows.text(index, 1) for index in range(1, 5)), "Native resource editor guessed unassigned reservations.")
        scratch = data / "gui-temporary"
        scratch.mkdir()
        ui.set_text(ui.child(1103, resources), str(scratch))
        button(resources, 1109)
        ui.wait("resource policy explicitly saved", lambda: ui.label(ui.child(1108, resources)).startswith("Saved."))
        stored = read_json(root / "user-data/resource-settings.json")
        require(stored["defaults"]["cpuBudget"] == 2 and stored["defaults"]["maxParallel"] == 2 and stored["defaults"]["temporaryFolder"] == str(scratch),
                "Native resource controls did not persist the reviewed policy.")
        report["captures"].append(ui.capture("resources-native-saved.bmp", resources))
        write_json(evidence / "resources-native-controls.json", ui.controls(resources))
        button(resources, 1110)
        ui.wait("resource view closed", lambda: not window("Resources · Native Workbench"))
        check(report, "Native Resources edits CPU budget, maximum parallel steps, one explicit reservation and temporary storage; Save persists those values and leaves other step requirements visibly unknown.")

        ui.post(ui.main, 0x0111, 306)
        ui.wait("recorded results chooser", lambda: window("Recorded results"))
        chooser = window("Recorded results")
        listing = ui.child(105, chooser)
        names = []
        for index in range(ui.send(listing, 0x018B)):
            buffer = ctypes.create_unicode_buffer(32768)
            ui.send(listing, 0x0189, index, ctypes.addressof(buffer))
            names.append(buffer.value)
        selected = next(index for index, label in enumerate(names) if report["guiFixture"]["runFolder"] in label)
        ui.send(listing, 0x0186, selected)
        button(chooser, 1)
        ui.wait("recorded baseline displayed", lambda: not window("Recorded results") and any(item["text"] == "Recorded results" for item in ui.controls()))
        ui.post(ui.main, 0x0111, 428)
        ui.wait("native restart review", lambda: window("Restart analysis · Native Workbench"))
        restart = window("Restart analysis · Native Workbench")
        decisions = NativeList(ui, ui.child(1201, restart))
        ui.wait("five reviewed restart decisions", lambda: decisions.count() == 5 and ui.user.IsWindowEnabled(ui.child(1206, restart)))
        require([decisions.text(index, 1) for index in range(5)] == ["reuse", "reuse", "reuse", "reuse", "run"], "Native restart omitted verified reuse and report-rebuild decisions.")
        output = data / "gui-restart-results"
        output.mkdir()
        ui.set_text(ui.child(1203, restart), str(output))
        report["captures"].append(ui.capture("restart-native-reviewed.bmp", restart))
        write_json(evidence / "restart-native-controls.json", ui.controls(restart))
        before = {job["job_id"] for job in read_json(root / "user-data/run-queue.json")["jobs"]}
        button(restart, 1206)
        def prepared():
            jobs = [job for job in read_json(root / "user-data/run-queue.json")["jobs"] if job["job_id"] not in before]
            if any(job["status"] in {"failed", "cancelled", "interrupted"} for job in jobs):
                raise AssertionError("Native reviewed restart failed preparation: " + json.dumps(jobs))
            return jobs if len(jobs) == 1 and jobs[0]["status"] == "queued" else None
        added = until("Native restart was not frozen in the queue.", prepared, 120)
        require(not (Path(added[0]["folder"]) / "run.json").exists(), "Native Queue reviewed restart automatically began execution.")
        ui.wait("restart opens queue", lambda: window("Analysis queue · Native Workbench"))
        queue = window("Analysis queue · Native Workbench")
        queue_rows = NativeList(ui, ui.child(901, queue))
        jobs = read_json(root / "user-data/run-queue.json")["jobs"]
        ui.wait("queued restart visible", lambda: queue_rows.count() == len(jobs))
        row = next(index for index, job in enumerate(jobs) if job["job_id"] == added[0]["job_id"])
        queue_rows.click(row)
        button(queue, 904)
        def completed():
            job = next(job for job in read_json(root / "user-data/run-queue.json")["jobs"] if job["job_id"] == added[0]["job_id"])
            return job if job["status"] in {"completed", "failed", "cancelled", "interrupted"} else None
        report["nativeRestartScience"] = scientific_truth(root, until("Native explicitly started restart did not complete.", completed, 180))
        ui.wait("native queue displays completed restart", lambda: queue_rows.text(row, 2) == "completed" and
                "Status: completed" in ui.label(ui.child(902, queue)))
        report["captures"].append(ui.capture("restart-native-queued-complete.bmp", queue))
        button(queue, 909)
        button(restart, 1208)
        ui.wait("restart views closed", lambda: not window("Restart analysis · Native Workbench") and not window("Analysis queue · Native Workbench"))
        check(report, "Native recorded-result Restart shows each verified reuse decision, queues without running, and explicit Queue Start creates a scientifically correct new result.")

        ui.post(ui.main, 0x0111, 429)
        ui.wait("native projects window", lambda: window("Portable projects · Native Workbench"))
        projects = window("Portable projects · Native Workbench")
        ui.set_text(ui.child(1301, projects), str(evidence / "synthetic-external-project.zip"))
        button(projects, 1303)
        inputs = NativeList(ui, ui.child(1304, projects))
        ui.wait("native unresolved project listed", lambda: inputs.count() == 3 and all(inputs.text(index, 1) == "missing" for index in range(3)))
        require(not ui.user.IsWindowEnabled(ui.child(1313, projects)), "Native import enabled with missing data.")
        report["captures"].append(ui.capture("project-native-missing-inputs.bmp", projects))
        graph = report["guiFixture"]["graph"]
        for index in range(3):
            filename = inputs.text(index, 2)
            actual = next(value for source in graph["sources"] for value in source["files"].values() if Path(value).name == filename)
            inputs.click(index)
            ui.set_text(ui.child(1305, projects), actual)
            button(projects, 1307)
            ui.wait("native explicit input mapping " + filename, lambda index=index: inputs.text(index, 1) == "mapped")
        ui.wait("native resolved import enabled", lambda: ui.user.IsWindowEnabled(ui.child(1313, projects)))
        imported = data / "native GUI imported project"
        ui.set_text(ui.child(1309, projects), str(imported))
        report["captures"].append(ui.capture("project-native-mapped-ready.bmp", projects))
        write_json(evidence / "projects-native-controls.json", ui.controls(projects))
        # Import's ordinary Windows confirmation is intentionally acknowledged;
        # the standard NativeUI wait rejects unexpected system dialogs.
        ui.post(ui.child(1313, projects), 0x00F5)
        confirm = until("Native import confirmation did not appear.", lambda: window("Import portable project"), 20)
        ui.send(ui.child(1, confirm), 0x00F5)
        ui.wait("project imported as draft", lambda: (imported / "project.json").exists() and "editable draft" in ui.label(ui.child(1314, projects)))
        require(not (imported / "run.json").exists(), "Project import executed an analysis.")
        button(projects, 1312)
        ui.wait("native export preview", lambda: window("Review portable project export"))
        preview = window("Review portable project export")
        text = ui.label(ui.child(105, preview))
        require("SHA-256:" in text and "external requirement" in text and "Pack" in text,
                "Native export preview omitted input identities or exact pack requirements.")
        report["captures"].append(ui.capture("project-native-export-review.bmp", preview))
        button(preview, 2)
        ui.wait("native export cancelled before writing", lambda: not window("Review portable project export"))
        button(projects, 1315)
        report["dpi"] = ui.user.GetDpiForWindow(ui.main)
        report["nativeGUIValidated"] = True
        check(report, "Native Projects keeps Import disabled for missing data, verifies all three explicit file mappings, confirms import into a new editable draft without analysis, and shows a cancellable export preview with file hashes and exact pack requirements.")
    except Exception:
        try:
            ui.desktop_evidence("recovery gate failure")
            for number, handle in enumerate(ui.windows()):
                ui.capture("recovery-failure-%d.bmp" % number, handle)
                write_json(evidence / ("recovery-failure-%d.json" % number), {"title": ui.label(handle), "controls": ui.controls(handle)})
        except Exception as error:
            report["failureCaptureError"] = str(error)
        raise
    finally:
        try:
            ui.close()
        finally:
            save_receipts(root, evidence, "gui-final", report)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app-root", type=Path, required=True)
    parser.add_argument("--fault-root", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--asset-sha256", required=True)
    parser.add_argument("--asset-name", required=True)
    parser.add_argument("--app-version", default="0.14.0")
    args = parser.parse_args()
    root, fault_root, target = args.app_root.resolve(), args.fault_root.resolve(), args.report.resolve()
    evidence = target.parent
    evidence.mkdir(parents=True, exist_ok=True)
    data = root.parent / "recovery-synthetic-data"
    data.mkdir()
    report = {"schema": 1, "success": False, "appVersion": args.app_version, "sourceCommit": args.source_commit,
              "assetName": args.asset_name, "assetSha256": args.asset_sha256, "gateSha256": sha256(__file__),
              "platform": platform.platform(), "python": sys.version, "startedUtc": datetime.now(timezone.utc).isoformat(),
              "nativeWindowsExecuted": False, "nativeGUILaunched": False, "nativeGUIValidated": False,
              "checks": [], "skips": [], "captures": [],
              "limits": ["Synthetic scientific truth and declared CPU admission observations; not CPU enforcement, realistic-data capacity or Windows/Linux benchmarking.",
                         "Abrupt termination uses a separately labelled callback barrier extraction; service bytes are restored before exact-host restart.",
                         "Hosted display DPI only; physical trackpad, high DPI, multi-monitor and institutional endpoint acceptance are not established."]}
    try:
        require(os.name == "nt", "This gate requires native Windows; unavailable execution cannot pass.")
        require(Path(sys.executable).resolve() == (root / "runtime/python/python.exe").resolve(), "Use the exact app's private Python.")
        report["appFiles"] = {str(path.relative_to(root)): sha256(path) for path in
                              [root / "NativeWorkbench.exe", root / "WorkbenchBridge.exe", *sorted((root / "workspace").glob("*.py"))]}
        require({name: sha256(fault_root / name) for name in report["appFiles"]} == report["appFiles"],
                "The fault extraction differs from the exact unmodified candidate before instrumentation.")
        host_checks(root, fault_root, data, evidence, report)
        report["nativeWindowsExecuted"] = True
        gui_checks(root, data, evidence, report)
        require({name: sha256(root / name) for name in report["appFiles"]} == report["appFiles"],
                "Untouched application files changed during the core gate.")
        report["success"] = True
    except Exception as error:
        report.update(error=str(error), traceback=traceback.format_exc())
        print(json.dumps({"gateError": str(error)[:8000], "traceback": report["traceback"]}), flush=True)
    finally:
        report.update(completedUtc=datetime.now(timezone.utc).isoformat(), passed=len(report["checks"]),
                      failed=0 if report["success"] else 1, skipped=len(report["skips"]))
        write_json(target, report)
    print(json.dumps({"success": report["success"], "passed": report["passed"], "report": str(target)}), flush=True)
    return 0 if report["success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
