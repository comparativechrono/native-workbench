"""Performance contracts with real local files and a synthetic host subprocess.

The subprocess copies known bytes, not a scientific tool or Windows Job Object.
Mocked native counters below test serialization only, not native measurement.
"""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import engine
import performance
from catalog import load_catalog
from cwl_export import definition_sha256
from test_pack_versions import make_pack


class Clock:
    def __init__(self):
        self.value = 0.0
    def __call__(self):
        return self.value
    def advance(self, amount):
        self.value += amount


class HostFixtureBackend:
    """Actual synthetic subprocess using the test host's Python, without metrics."""
    def __init__(self):
        self.requests = []
        self.mode = "success"
        self.clock = None
    def run(self, request, event, cancel):
        self.requests.append(copy.deepcopy(request))
        if self.clock:
            self.clock.advance(7)
        if self.mode == "exception":
            raise OSError("Synthetic runner launch failure")
        if self.mode == "cancel":
            cancel.set()
            return {"success": False, "cancelled": True}
        if self.mode == "failure":
            return {"success": False, "message": "Synthetic exit failure"}
        if self.mode != "missing_output":
            command = "from pathlib import Path; import sys; Path(sys.argv[2]).write_bytes(Path(sys.argv[1]).read_bytes() + b'|processed')"
            subprocess.run([sys.executable, "-c", command, request["values"]["source"], str(Path(request["output_folder"]) / "result.dat")], check=True, timeout=15)
        return {"success": True, "folder": request["output_folder"]}


def mock_native_metrics():
    return {"schema": 1, "source": "windows-job-object", "scope": "workflow-command-stages", "stages": [
        {"id": "align", "kind": "pipe", "status": "success", "resources": {
            "schema": 1, "source": "windows-job-object", "scope": "pipeline-process-tree", "wall_ms": 24,
            "user_cpu_seconds": 0.015, "kernel_cpu_seconds": 0.004, "peak_job_memory_bytes": 1048576,
            "memory_kind": "committed", "processes_total": 2, "processes_active_at_snapshot": 0,
            "accounting_available": True, "memory_available": True, "coverage": "complete",
            "snapshot": "before-job-close", "accounting_error": None, "memory_error": None}}]}


class PerformanceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="workbench-performance-")
        self.root = Path(self.tmp.name)
        make_pack(self.root, "1.0.0")
        self.catalog = load_catalog(self.root)
        self.source = self.root / "private-sample-name.dat"
        self.source.write_bytes(b"fixture-input")
        self.backend = HostFixtureBackend()
        self.engine = engine.Engine(self.root, self.catalog, self.backend)

    def tearDown(self):
        self.tmp.cleanup()

    def graph(self):
        return {"schema": 1, "name": "private-project-name", "sources": [{"id": "input-1", "type": "file", "files": {"source": str(self.source)}}],
                "nodes": [{"id": "step-1", "label": "private-label", "tool": "example/process", "params": {}, "inputs": {"source": ["input-1"]}},
                          {"id": "step-2", "tool": "example/process", "params": {}, "inputs": {"source": ["step-1::result"]}}]}

    def prepared(self):
        return self.engine.prepare(self.graph(), self.root)

    def read(self, plan):
        return json.loads((Path(plan["folder"]) / "performance.json").read_text())

    def test_prepared_record_is_path_free_and_preparation_is_frozen(self):
        plan = self.prepared()
        report = self.read(plan)
        self.assertEqual(report["status"], "planned")
        self.assertEqual(report["preparation"], plan["performancePreparation"])
        self.assertEqual(set(report["preparation"]["phases"]), set(performance.PREPARATION_PHASES))
        self.assertTrue(all(phase["status"] == "completed" for phase in report["preparation"]["phases"].values()))
        self.assertEqual(report["inputSummary"], {"sourceCount": 1, "uniqueFileCount": 1, "totalBytes": 13,
                          "files": [{"sha256": hashlib.sha256(b"fixture-input").hexdigest(), "bytes": 13}]})
        text = json.dumps(report)
        for private in (str(self.root), "private-sample-name", "private-project-name", "private-label"):
            self.assertNotIn(private, text)
        self.assertFalse(any(key in report["system"] for key in ("hostname", "username", "home", "environment")))
        changed = copy.deepcopy(plan)
        changed["performancePreparation"]["elapsedSeconds"] = 0
        with self.assertRaisesRegex(ValueError, "frozen execution plan"):
            self.engine.execute(changed)

    def test_actual_synthetic_subprocess_chain_preserves_output_and_binds_metrics(self):
        plan = self.prepared()
        record = self.engine.execute(plan)
        report = self.read(plan)
        self.assertTrue(record["success"], record)
        output = record["outputs"]["step-2::result"]["files"]["result"]
        self.assertEqual(Path(output).read_bytes(), b"fixture-input|processed|processed")
        self.assertEqual(report["status"], "success")
        self.assertEqual(report["planSha256"], record["planSha256"])
        self.assertEqual(record["performance"]["sha256"], engine.digest_file(Path(plan["folder"]) / "performance.json"))
        self.assertEqual(record["workflowExport"]["sha256"], engine.digest_file(Path(plan["folder"]) / "workflow.cwl"))
        workflow = json.loads((Path(plan["folder"]) / "workflow.cwl").read_text())
        self.assertEqual(definition_sha256(workflow), plan["workflowExport"]["definitionSha256"])
        embedded = json.loads(workflow["$graph"][0]["nw:execution"]["recordJson"])
        self.assertNotIn("performance", embedded, "Final sidecar hash must not enter reciprocal CWL hashing")
        for step in report["steps"]:
            self.assertEqual(step["status"], "success")
            self.assertGreater(step["elapsedSeconds"], 0)
            self.assertEqual(step["pin"]["packVersion"], "1.0.0")
            self.assertEqual(step["backendMetrics"], performance.unavailable_metrics())
            self.assertTrue(all(phase["status"] == "completed" for phase in step["phases"].values()))

    def test_monotonic_phases_separate_backend_preflight_and_hashing(self):
        plan = self.prepared()
        clock = Clock()
        self.backend.clock = clock
        real_digest = engine.digest_file
        def digest(*args, **kwargs):
            value = real_digest(*args, **kwargs)
            clock.advance(5)
            return value
        def preflight(*args, **kwargs):
            clock.advance(3)
            return {}
        with patch.object(performance.time, "perf_counter", clock), patch.object(engine, "digest_file", digest), patch.object(self.engine, "_preflight", preflight):
            self.engine.execute(plan)
        report = self.read(plan)
        for step in report["steps"]:
            self.assertEqual(step["phases"]["input_verification"]["elapsedSeconds"], 10)
            self.assertEqual(step["phases"]["scientific_preflight"]["elapsedSeconds"], 3)
            self.assertEqual(step["phases"]["backend_runner"]["elapsedSeconds"], 7)
            self.assertEqual(step["phases"]["output_validation_and_hashing"]["elapsedSeconds"], 5)
            self.assertEqual(step["elapsedSeconds"], 25)
        self.assertEqual(report["execution"]["phases"]["startup"]["elapsedSeconds"], 5)
        self.assertEqual(report["execution"]["phases"]["finalization"]["elapsedSeconds"], 5)
        self.assertEqual(report["execution"]["elapsedSeconds"], 60)
        self.assertTrue(report["interpretation"]["inclusiveTotalsOverlapPhases"])

    def test_failed_backend_and_blocked_descendant_do_not_get_zero_measurements(self):
        plan = self.prepared()
        self.backend.mode = "failure"
        result = self.engine.execute(plan)
        report = self.read(plan)
        self.assertFalse(result["success"])
        first, second = report["steps"]
        self.assertEqual((first["status"], second["status"]), ("failed", "blocked"))
        self.assertEqual(first["phases"]["backend_runner"]["status"], "completed")
        self.assertEqual(first["phases"]["output_validation_and_hashing"], {"status": "not_run", "elapsedSeconds": None})
        self.assertIsNone(second["elapsedSeconds"])
        self.assertTrue(all(phase == {"status": "not_run", "elapsedSeconds": None} for phase in second["phases"].values()))
        self.assertEqual(len(self.backend.requests), 1)

    def test_exception_retains_partial_phase_and_never_claims_missing_metrics(self):
        plan = self.prepared()
        clock = Clock()
        self.backend.clock = clock
        self.backend.mode = "exception"
        with patch.object(performance.time, "perf_counter", clock):
            self.engine.execute(plan)
        first = self.read(plan)["steps"][0]
        self.assertEqual(first["phases"]["backend_runner"], {"status": "failed", "elapsedSeconds": 7})
        self.assertFalse(first["backendMetrics"]["available"])

    def test_cancellation_during_backend_marks_later_steps_unrun(self):
        plan = self.prepared()
        self.backend.mode = "cancel"
        result = self.engine.execute(plan)
        report = self.read(plan)
        self.assertEqual(result["status"], "cancelled")
        self.assertEqual([step["status"] for step in report["steps"]], ["cancelled", "cancelled"])
        self.assertIsNotNone(report["steps"][0]["phases"]["backend_runner"]["elapsedSeconds"])
        self.assertIsNone(report["steps"][1]["elapsedSeconds"])
        self.assertEqual(report["steps"][1]["backendMetrics"]["reason"], "step_not_run")

    def test_cancel_before_execution_has_no_started_steps(self):
        plan = self.prepared()
        cancel = threading.Event()
        cancel.set()
        self.engine.execute(plan, cancel=cancel)
        report = self.read(plan)
        self.assertEqual(report["status"], "cancelled")
        self.assertFalse(self.backend.requests)
        self.assertTrue(all(step["elapsedSeconds"] is None for step in report["steps"]))

    def test_changed_input_failure_is_distinct_from_backend_or_scientific_failure(self):
        plan = self.prepared()
        self.source.write_bytes(b"changed")
        self.engine.execute(plan)
        first = self.read(plan)["steps"][0]
        self.assertEqual(first["phases"]["input_verification"]["status"], "failed")
        self.assertEqual(first["phases"]["scientific_preflight"]["status"], "not_run")
        self.assertEqual(first["phases"]["backend_runner"]["status"], "not_run")
        self.assertFalse(self.backend.requests)

    def test_preflight_failure_and_cancellation_keep_their_own_partial_duration(self):
        for error, status in ((ValueError("Synthetic incompatibility"), "failed"), (InterruptedError("Synthetic cancellation"), "cancelled")):
            with self.subTest(status=status):
                plan = self.prepared()
                clock = Clock()
                def preflight(*args, **kwargs):
                    clock.advance(3)
                    raise error
                with patch.object(performance.time, "perf_counter", clock), patch.object(self.engine, "_preflight", preflight):
                    self.engine.execute(plan)
                first = self.read(plan)["steps"][0]
                self.assertEqual(first["status"], status)
                self.assertEqual(first["phases"]["scientific_preflight"], {"status": status, "elapsedSeconds": 3})
                self.assertEqual(first["phases"]["backend_runner"], {"status": "not_run", "elapsedSeconds": None})
                self.assertFalse(self.backend.requests)

    def test_successful_exit_missing_output_is_measured_as_output_validation_failure(self):
        plan = self.prepared()
        self.backend.mode = "missing_output"
        self.engine.execute(plan)
        first = self.read(plan)["steps"][0]
        self.assertEqual(first["status"], "failed")
        self.assertEqual(first["phases"]["backend_runner"]["status"], "completed")
        self.assertEqual(first["phases"]["output_validation_and_hashing"]["status"], "failed")

    def test_older_valid_plan_has_explicitly_unavailable_preparation(self):
        plan = self.prepared()
        del plan["performancePreparation"]
        del plan["sha256"]
        plan["sha256"] = hashlib.sha256(engine.canonical(plan).encode()).hexdigest()
        folder = Path(plan["folder"])
        engine.write_json(folder / "plan.json", plan)
        workflow = json.loads((folder / "workflow.cwl").read_text())
        workflow["$graph"][0]["nw:planSha256"] = plan["sha256"]
        engine.write_json(folder / "workflow.cwl", workflow)
        self.assertTrue(self.engine.execute(plan)["success"])
        self.assertEqual(self.read(plan)["preparation"]["status"], "unavailable")

    def test_native_counter_fixture_is_bounded_and_committed_memory_not_rss(self):
        raw = mock_native_metrics()
        raw["private_path"] = str(self.source)
        raw["stages"][0]["resources"]["private_environment"] = "secret"
        result = performance.native_metrics(raw)
        self.assertTrue(result["available"])
        self.assertNotIn("private", json.dumps(result))
        resource = result["data"]["stages"][0]["resources"]
        self.assertEqual(resource["memory_kind"], "committed")
        self.assertEqual(resource["peak_job_memory_bytes"], 1048576)
        self.assertNotIn("rss", resource)
        for bad in (-1, float("nan"), True, "123", 2**2048):
            invalid = copy.deepcopy(raw)
            invalid["stages"][0]["resources"]["user_cpu_seconds"] = bad
            self.assertFalse(performance.native_metrics(invalid)["available"])

    def test_partial_native_counter_coverage_is_preserved_without_inventing_values(self):
        raw = mock_native_metrics()
        resource = raw["stages"][0]["resources"]
        resource.update(coverage="partial", memory_available=False, peak_job_memory_bytes=None, memory_error=5)
        parsed = performance.native_metrics(raw)["data"]["stages"][0]["resources"]
        self.assertEqual(parsed["coverage"], "partial")
        self.assertIsNone(parsed["peak_job_memory_bytes"])
        self.assertEqual(parsed["memory_error"], 5)

    def test_phase_cancellation_preserves_elapsed_without_using_wall_clock(self):
        clock = Clock()
        target = {}
        with self.assertRaises(InterruptedError):
            with performance.measure(target, "scientific_preflight", clock=clock):
                clock.advance(4)
                raise InterruptedError("cancel fixture")
        self.assertEqual(target, {"scientific_preflight": {"status": "cancelled", "elapsedSeconds": 4}})

    def test_builtin_report_measures_local_work_without_claiming_native_counters(self):
        second = self.root / "second.dat"
        second.write_bytes(b"second report")
        graph = {"schema": 1, "name": "Synthetic report", "sources": [
                    {"id": "input-1", "type": "metrics", "files": {"source": str(self.source)}},
                    {"id": "input-2", "type": "metrics", "files": {"source": str(second)}}],
                 "nodes": [{"id": "step-1", "tool": "builtin/report", "params": {}, "inputs": {"metrics": ["input-1", "input-2"]}}]}
        plan = self.engine.prepare(graph, self.root)
        self.assertTrue(self.engine.execute(plan)["success"])
        step = self.read(plan)["steps"][0]
        self.assertEqual(step["phases"]["scientific_preflight"], {"status": "not_applicable", "elapsedSeconds": None})
        self.assertEqual(step["phases"]["backend_runner"]["status"], "completed")
        self.assertEqual(step["backendMetrics"], performance.unavailable_metrics("builtin_operation_without_native_command"))
        self.assertFalse(self.backend.requests)

    def test_record_during_execution_distinguishes_running_from_unstarted_steps(self):
        plan = self.prepared()
        observed = []
        def event(item):
            if item.get("type") == "step" and item.get("status") == "running":
                observed.append(self.read(plan))
        self.engine.execute(plan, event=event)
        self.assertEqual([step["status"] for step in observed[0]["steps"]], ["running", "not_run"])
        self.assertEqual([step["status"] for step in observed[1]["steps"]], ["success", "running"])

    def test_system_information_works_with_all_socket_audits_denied(self):
        # A subprocess owns the irreversible audit hook. Even gethostname is
        # denied, matching the real offline Windows gate that exposed this bug.
        code = '''
import json, socket, sys
from unittest.mock import patch
sys.path.insert(0, sys.argv[1])
import performance
def deny_socket(event, args):
    if event.startswith("socket."):
        raise PermissionError("offline fixture denies socket activity")
sys.addaudithook(deny_socket)
try:
    socket.gethostname()
except PermissionError:
    pass
else:
    raise AssertionError("fixture must deny hostname lookup")
with patch("platform.uname", side_effect=AssertionError("platform.uname consults host identity")):
    report = performance.system_information()
assert report["os"]["name"] and report["architecture"], report
assert report["os"]["release"] and report["os"]["version"], report
assert not {"hostname", "nodename", "username", "environment"}.intersection(report)
print(json.dumps(report))
'''
        result = subprocess.run([sys.executable, "-I", "-c", code, str(Path(__file__).resolve().parents[1])],
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(json.loads(result.stdout)["architecture"])

    def test_windows_kernel_identity_uses_numeric_version_and_native_architecture(self):
        import ctypes
        def native_information(pointer):
            information = pointer._obj
            self.assertEqual(ctypes.sizeof(information), 48 if ctypes.sizeof(ctypes.c_void_p) == 8 else 36)
            information.architecture = 12  # Native ARM64, independent of interpreter bitness.
        library = SimpleNamespace(GetNativeSystemInfo=native_information)
        with patch.object(performance.os, "name", "nt"), \
             patch.object(performance.sys, "getwindowsversion", return_value=SimpleNamespace(major=10, minor=0, build=20348), create=True), \
             patch.object(ctypes, "WinDLL", return_value=library, create=True):
            identity = performance.safe_system_identity()
        self.assertEqual(identity, {"os": {"name": "Windows", "release": "10.0", "version": "10.0.20348"}, "architecture": "ARM64"})


if __name__ == "__main__":
    unittest.main(verbosity=2)
