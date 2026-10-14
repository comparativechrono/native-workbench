"""Recovery/project/resource transport contracts; fake engines are not native evidence."""
import copy
import hashlib
import json
import os
import queue
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from service import Workbench
from desktop_host import DesktopHost
from test_run_queue import Engine as QueueEngine, Model, wait_for


class Engine(QueueEngine):
    def __init__(self):
        super().__init__()
        self.policies = []
        self.restarts = []

    def prepare(self, graph, output, cancel=None, run_metadata=None, resource_policy=None, restart_from=None):
        self.policies.append(copy.deepcopy(resource_policy))
        self.restarts.append(copy.deepcopy(restart_from))
        return super().prepare(graph, output, cancel=cancel, run_metadata=run_metadata)

    def review_restart(self, graph, folder, resource_policy=None):
        return {"sourceFolder": folder, "sourcePlanSha256": "1" * 64, "sourceRunSha256": "2" * 64,
                "nodes": [{"id": "step-1", "action": "reuse", "reason": "Verified", "outputs": {"private": "kept server-side"}},
                          {"id": "step-2", "action": "run", "reason": "Incomplete"}]}


class ProjectManager:
    calls = []
    changed_archive = False

    def __init__(self, engine):
        self.engine = engine

    def export_preview(self, graph, include_data=False, sample_metadata=None, project_metadata=None, reference_metadata=None, validation_tools=None):
        return {"graph": copy.deepcopy(graph), "sample": sample_metadata, "paths": {"secret": "LOCAL FILE"},
                "summary": {"ready": True, "included": include_data}}

    def export(self, preview, destination):
        self.calls.append(("export", copy.deepcopy(preview), destination))
        Path(destination).write_text(json.dumps(preview))
        return {"path": destination}

    def preview_import(self, archive, mappings=None):
        return {"archive": archive, "archiveSha256": "2" * 64 if self.changed_archive else "1" * 64,
                "mappings": mappings or {}, "summary": {"ready": bool(mappings), "dependencies": []}}

    def import_project(self, preview, destination):
        self.calls.append(("import", copy.deepcopy(preview), destination))
        return {"folder": destination, "graph": {"name": "Imported", "nodes": [], "sources": []}}

    def open_project(self, folder):
        return {"folder": folder, "graph": {"name": "Opened", "nodes": [], "sources": []}}


class RecoveryServiceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="recovery-service-")
        self.root = Path(self.tmp.name)
        self.engine = Engine()
        self.app = Workbench(self.root, engine=self.engine, catalog={"tools": {}})
        self.model = Model()
        self.model.graph = {"name": "Draft", "nodes": [{"id": "step-1"}, {"id": "step-2"}], "sources": []}
        self.host = DesktopHost(self.root, app=self.app, model=self.model)
        ProjectManager.calls = []
        ProjectManager.changed_archive = False

    def tearDown(self):
        self.engine.release.set()
        self.engine.prepare_release.set()
        self.host.close(grace=3)
        self.tmp.cleanup()

    def policy(self, **values):
        result = {"cpuBudget": 1, "maxParallel": 1, "stepCpus": {"step-1": 1}, "temporaryFolder": ""}
        result.update(values)
        return result

    def test_resources_persist_exact_graph_reservations_and_edits_invalidate(self):
        original = copy.deepcopy(self.model.graph)
        self.host.dispatch("resources/set", {"policy": self.policy(temporaryFolder=str(self.root))})
        self.assertEqual(self.host.dispatch("resources/get", {})["policy"]["stepCpus"], {"step-1": 1})
        self.model.graph["nodes"][0]["params"] = {"threads": "2"}
        self.assertEqual(self.host.dispatch("resources/get", {})["policy"]["stepCpus"], {})
        self.host.close()
        self.app = Workbench(self.root, engine=self.engine, catalog={"tools": {}})
        self.host = DesktopHost(self.root, app=self.app, model=self.model)
        self.assertEqual(self.host.dispatch("resources/get", {"graph": original})["policy"]["stepCpus"], {"step-1": 1})
        saved_temporary = Path(self.host.dispatch("resources/get", {})["policy"]["temporaryFolder"])
        self.assertTrue(saved_temporary.is_absolute())
        # Persisted paths are canonical; Windows tempfile may originally use
        # the same directory's short 8.3 spelling.
        self.assertTrue(saved_temporary.samefile(self.root))
        self.assertFalse(self.engine.calls)

    def test_resource_profiles_bounded_and_unknown_steps_do_not_reserve(self):
        graphs = []
        for number in range(5):
            graph = dict(self.model.graph, name=str(number))
            graphs.append(graph)
            self.host.dispatch("resources/set", {"graph": graph, "policy": self.policy()})
        self.assertEqual(self.host.dispatch("resources/get", {"graph": graphs[0]})["policy"]["stepCpus"], {})
        self.assertEqual(len(self.app._resource_state["profiles"]), 4)
        old = self.app.resource_path.read_bytes()
        with self.assertRaises(ValueError):
            self.host.dispatch("resources/set", {"policy": self.policy(stepCpus={"step-99": 1})})
        self.assertEqual(self.app.resource_path.read_bytes(), old)

    def test_resource_commit_preserves_old_settings_on_storage_failure_and_second_host(self):
        self.host.dispatch("resources/set", {"policy": self.policy()})
        old = self.app.resource_path.read_bytes()
        with patch("service.replace_file", side_effect=PermissionError("fixture sharing conflict")):
            with self.assertRaises(PermissionError):
                self.host.dispatch("resources/set", {"policy": self.policy(stepCpus={})})
        self.assertEqual(self.app.resource_path.read_bytes(), old)
        self.assertEqual(self.host.dispatch("resources/get", {})["policy"]["stepCpus"], {"step-1": 1})
        other = Workbench(self.root, engine=Engine(), catalog={"tools": {}})
        try:
            with self.assertRaisesRegex(ValueError, "owns this installation"):
                other.set_resources(self.model.graph, self.policy())
        finally:
            other.shutdown()

    def test_corrupt_settings_fail_closed_without_replacing_evidence(self):
        self.host.close()
        path = self.root / "user-data" / "resource-settings.json"
        path.write_text('{"schema":1,"schema":1}')
        self.app = Workbench(self.root, engine=self.engine, catalog={"tools": {}})
        self.host = DesktopHost(self.root, app=self.app, model=self.model)
        self.assertIn("cannot be used", self.host.dispatch("resources/get", {})["error"])
        with self.assertRaisesRegex(ValueError, "cannot be used"):
            self.host.dispatch("queue/add", {"output_folder": str(self.root)})
        self.assertEqual(path.read_text(), '{"schema":1,"schema":1}')
        self.assertFalse(self.app.queue_state()["jobs"])

    def test_queued_resource_policy_is_frozen_before_later_settings_changes(self):
        self.host.dispatch("resources/set", {"policy": self.policy()})
        self.engine.prepare_release.clear()
        response = self.host.dispatch("queue/add", {"output_folder": str(self.root)})
        self.assertTrue(self.engine.preparing.wait(2))
        self.host.dispatch("resources/set", {"policy": self.policy(stepCpus={})})
        self.engine.prepare_release.set()
        wait_for(lambda: not self.app.queue_state()["preparing"])
        self.assertEqual(self.engine.policies[0]["stepCpus"], {"step-1": 1})
        self.assertEqual(self.app.queue_state()["jobs"][0]["job_id"], response["added"][0])
        self.assertFalse(self.engine.calls)

    def test_restart_review_is_bounded_private_one_use_and_never_autostarts(self):
        self.app.runs["old"] = {"run_id": "old", "status": "interrupted", "graph": copy.deepcopy(self.model.graph),
                                "folder": str(self.root), "events": [], "nodes": []}
        self.host.dispatch("resources/set", {"policy": self.policy()})
        review = self.host.dispatch("restart/review", {"run_id": "old"})
        self.assertEqual(review["reuse_count"], 1)
        self.assertEqual(review["rerun_count"], 1)
        self.assertNotIn("LOCAL FILE", json.dumps(review))
        self.assertNotIn("outputs", review["nodes"][0])
        self.model.graph["name"] = "Later draft"
        self.host.dispatch("resources/set", {"policy": self.policy(stepCpus={})})
        result = self.host.dispatch("restart/queue", {"token": review["token"], "output_folder": str(self.root)})
        wait_for(lambda: not self.app.queue_state()["preparing"])
        self.assertEqual(self.engine.prepare_calls[0]["name"], "Draft")
        self.assertEqual(self.engine.policies[0]["stepCpus"], {"step-1": 1})
        self.assertEqual(self.engine.restarts[0]["sourceRunSha256"], "2" * 64)
        self.assertFalse(self.engine.calls)
        self.assertEqual(self.app.queue_state()["jobs"][0]["status"], "queued")
        with self.assertRaisesRegex(ValueError, "expired"):
            self.host.dispatch("restart/queue", {"token": review["token"], "output_folder": str(self.root)})
        self.assertEqual(len(result["added"]), 1)

    def test_active_or_installation_record_without_graph_cannot_restart(self):
        for status, graph in (("running", self.model.graph), ("completed", None)):
            self.app.runs["old"] = {"run_id": "old", "status": status, "graph": graph, "folder": str(self.root)}
            with self.assertRaises(ValueError):
                self.host.dispatch("restart/review", {"run_id": "old"})
        self.app.runs.clear()

    @patch("project_manager.ProjectManager", ProjectManager)
    def test_export_token_holds_reviewed_graph_and_private_fields_stay_server_side(self):
        preview = self.host.dispatch("project/export-preview", {"include_data": False})
        self.assertNotIn("paths", preview)
        self.model.graph["name"] = "Changed after preview"
        result = self.host.dispatch("project/export", {"token": preview["token"], "destination": str(self.root / "project.zip")})
        self.assertTrue(Path(result["path"]).exists())
        self.assertEqual(ProjectManager.calls[0][1]["graph"]["name"], "Draft")
        with self.assertRaisesRegex(ValueError, "expired"):
            self.host.dispatch("project/export", {"token": preview["token"], "destination": str(self.root / "again.zip")})
        self.assertFalse(self.engine.calls)

    @patch("project_manager.ProjectManager", ProjectManager)
    def test_project_resolution_accumulates_explicit_mappings_and_rejects_changed_archive(self):
        preview = self.host.dispatch("project/inspect", {"path": str(self.root / "source.zip")})
        resolved = self.host.dispatch("project/resolve", {"token": preview["token"], "mappings": {"reads": str(self.root / "r.fastq")}})
        with self.assertRaisesRegex(ValueError, "expired"):
            self.app._preview(self.app._project_import_previews, preview["token"])
        ProjectManager.changed_archive = True
        with self.assertRaisesRegex(ValueError, "changed"):
            self.host.dispatch("project/resolve", {"token": resolved["token"], "mappings": {"ref": str(self.root / "r.fa")}})
        self.assertEqual(self.app._preview(self.app._project_import_previews, resolved["token"])["mappings"], {"reads": str(self.root / "r.fastq")})
        self.assertFalse(self.engine.calls)

    def test_unavailable_saved_scratch_can_be_explicitly_corrected(self):
        scratch = self.root / "scratch"
        scratch.mkdir()
        self.host.dispatch("resources/set", {"policy": self.policy(temporaryFolder=str(scratch))})
        self.host.close()
        scratch.rmdir()
        self.app = Workbench(self.root, engine=self.engine, catalog={"tools": {}})
        self.host = DesktopHost(self.root, app=self.app, model=self.model)
        self.assertEqual(self.host.dispatch("resources/get", {})["error"], "")
        with self.assertRaisesRegex(ValueError, "temporary-storage"):
            self.host.dispatch("queue/add", {"output_folder": str(self.root)})
        self.host.dispatch("resources/set", {"policy": self.policy(temporaryFolder="")})
        self.assertEqual(self.host.dispatch("resources/get", {})["policy"]["temporaryFolder"], "")
        self.assertFalse(self.engine.calls)

    def test_saved_budget_can_be_corrected_on_a_smaller_host(self):
        with patch("execution_resources.os.cpu_count", return_value=4):
            self.host.dispatch("resources/set", {"policy": self.policy(cpuBudget=4)})
        self.host.close()
        with patch("execution_resources.os.cpu_count", return_value=1):
            self.app = Workbench(self.root, engine=self.engine, catalog={"tools": {}})
            self.host = DesktopHost(self.root, app=self.app, model=self.model)
            self.assertEqual(self.host.dispatch("resources/get", {})["error"], "")
            with self.assertRaisesRegex(ValueError, "cpuBudget"):
                self.host.dispatch("queue/add", {"output_folder": str(self.root)})
            self.host.dispatch("resources/set", {"policy": self.policy(cpuBudget=1)})
            self.assertEqual(self.host.dispatch("resources/get", {})["policy"]["cpuBudget"], 1)

    @patch("project_manager.ProjectManager", ProjectManager)
    def test_recorded_result_export_uses_verified_original_inputs_and_metadata(self):
        from engine import canonical
        source = self.root / "reads.fastq"
        source.write_bytes(b"original sample input")
        batch = {"batchId": "1" * 32, "sampleId": "sample-a", "metadata": {"condition": "control"}}
        plan = {"id": "run-original", "folder": str(self.root), "graph": copy.deepcopy(self.model.graph), "nodes": [],
                "inputs": {str(source): {"bytes": source.stat().st_size, "sha256": hashlib.sha256(source.read_bytes()).hexdigest()}}, "batch": batch}
        plan["sha256"] = hashlib.sha256(canonical(plan).encode()).hexdigest()
        (self.root / "plan.json").write_text(json.dumps(plan), encoding="utf-8")
        (self.root / "run.json").write_text(json.dumps({"id": plan["id"], "planSha256": plan["sha256"], "nodes": [], "batch": batch}))
        self.app.runs["selected"] = {"run_id": "selected", "id": plan["id"], "status": "completed", "folder": str(self.root)}
        self.model.graph["name"] = "Different draft"
        preview = self.host.dispatch("project/export-preview", {"run_id": "selected", "include_data": False})
        self.assertEqual(preview["sample_metadata"], batch)
        self.assertEqual(preview["source"], "recorded-result")
        self.host.dispatch("project/export", {"token": preview["token"], "destination": str(self.root / "old.zip")})
        self.assertEqual(ProjectManager.calls[0][1]["graph"]["name"], "Draft")
        source.write_bytes(b"changed sample input!")
        with self.assertRaisesRegex(ValueError, "original result input changed"):
            self.host.dispatch("project/export-preview", {"run_id": "selected"})
        with self.assertRaises(ValueError):
            self.host.dispatch("project/export-preview", {"run_id": "selected", "sample_metadata": {"invented": "sample"}})

    @patch("project_manager.ProjectManager", ProjectManager)
    def test_imported_sample_context_only_reexports_for_the_exact_loaded_graph(self):
        self.app.remember_project(self.model.graph, {"sampleMetadata": {"condition": "case"}})
        preview = self.host.dispatch("project/export-preview", {})
        self.assertEqual(preview["sample_metadata"], {"condition": "case"})
        self.model.graph["name"] = "Edited"
        self.assertIsNone(self.host.dispatch("project/export-preview", {})["sample_metadata"])

    def test_real_project_import_normalized_display_counters_preserve_frozen_context(self):
        from catalog import load_catalog
        from engine import Engine as RealEngine, pin_for
        from project_manager import ProjectManager as RealProjects
        from test_pack_schema import MANIFEST, metadata
        self.host.close()
        pack = self.root / "packs" / "example-0.5.2"
        (pack / "bin").mkdir(parents=True)
        binary = b"Non executable fixture bytes"
        schema = json.dumps(metadata()).encode()
        (pack / "bin/example.exe").write_bytes(binary)
        (pack / "workbench-schema.json").write_bytes(schema)
        (pack / "pack.ini").write_text(MANIFEST.format(binary_sha=hashlib.sha256(binary).hexdigest(), schema_sha=hashlib.sha256(schema).hexdigest()), encoding="utf-8")
        catalog = load_catalog(self.root)
        scientific = RealEngine(self.root, catalog)
        self.app = Workbench(self.root, engine=scientific, catalog=catalog)
        self.host = DesktopHost(self.root, app=self.app)
        self.host.dispatch("workspace/mode", {"mode": "workflow"})
        self.host.model.graph["nextNode"] = 90
        self.host.model.graph["nextSource"] = 80
        self.host.model._next_node = 90
        self.host.model._next_source = 80
        source = self.root / "original.fa"
        source.write_text(">chr1\nACGTACGTACGTACGT\n")
        graph = {"schema": 1, "name": "Portable", "sources": [
            {"id": "input-1", "type": "fasta-nucleotide", "files": {"sequences": str(source)}}],
            "nodes": [{"id": "step-1", "tool": "example/filter", "pin": pin_for(scientific.tools["example/filter"]),
                       "params": {"minimum": "10"}, "inputs": {"sequences": ["input-1"]}}]}
        manager = RealProjects(scientific)
        manager.export(manager.export_preview(graph, include_data=True, sample_metadata={"sampleId": "descriptive-only"}), self.root / "project.zip")
        inspected = self.host.dispatch("project/inspect", {"path": str(self.root / "project.zip")})
        imported = self.host.dispatch("project/import", {"token": inspected["token"], "destination_folder": str(self.root / "imported")})
        self.assertTrue(imported["model_loaded"])
        self.assertEqual(imported["model"]["graph"]["nextNode"], 90)
        context = self.app._project_context(self.host.graph())
        self.assertEqual(context["sampleMetadata"], {"sampleId": "descriptive-only"})
        self.assertEqual(context["projectMetadata"]["manifestSha256"], imported["manifestSha256"])
        self.assertEqual(self.host.dispatch("project/export-preview", {})["sample_metadata"], {"sampleId": "descriptive-only"})
        self.host.dispatch("queue/add", {"output_folder": str(self.root)})
        wait_for(lambda: not self.app.queue_state()["preparing"])
        job = self.app.queue_state()["jobs"][-1]
        self.assertEqual(job["status"], "queued", job)
        plan = json.loads((Path(job["folder"]) / "plan.json").read_text(encoding="utf-8"))
        self.assertEqual(plan["project"]["manifestSha256"], imported["manifestSha256"])
        self.assertNotIn("batch", plan)
        self.host.close()
        self.app = Workbench(self.root, engine=scientific, catalog=catalog)
        self.host = DesktopHost(self.root, app=self.app)
        self.assertEqual(self.host.graph()["nodes"], [])  # Drafts are not auto-restored.
        self.assertEqual(self.app.queue_state()["jobs"][-1]["status"], "queued")
        self.assertTrue(self.app.queue_state()["paused"])
        from run_queue import load_plan
        restored = load_plan(self.app.run_queue.snapshot()["jobs"][-1])
        self.assertEqual(restored["project"]["manifestSha256"], imported["manifestSha256"])
        reopened = self.host.dispatch("project/open", {"folder": str(self.root / "imported")})
        self.assertTrue(reopened["model_loaded"])
        context = self.app._project_context(self.host.graph())
        self.assertEqual(context["projectMetadata"]["manifestSha256"], imported["manifestSha256"])
        self.assertEqual(self.host.dispatch("project/export-preview", {})["sample_metadata"], {"sampleId": "descriptive-only"})
        self.host.dispatch("queue/add", {"output_folder": str(self.root)})
        wait_for(lambda: not self.app.queue_state()["preparing"])
        later = self.app.run_queue.snapshot()["jobs"][-1]
        self.assertEqual(later["status"], "queued", later)
        self.assertEqual(load_plan(later)["project"], restored["project"])

    def test_project_and_resource_io_do_not_block_active_queue_cancellation(self):
        import desktop_host
        response = self.host.dispatch("queue/add", {"output_folder": str(self.root)})
        wait_for(lambda: not self.app.queue_state()["preparing"])
        self.engine.release.clear()
        self.host.dispatch("queue/start", {})
        self.assertTrue(self.engine.running.wait(2))
        entered, release, guard = threading.Event(), threading.Event(), threading.Lock()
        count, closed = [0], []
        incoming, outgoing = queue.Queue(), queue.Queue()
        class Input:
            def readline(self, limit):
                return incoming.get(timeout=10)
        class Output:
            def write(self, data):
                outgoing.put(json.loads(data))
            def flush(self):
                pass
        def delayed(*args, **kwargs):
            with guard:
                count[0] += 1
                if count[0] == 2:
                    entered.set()
            if not release.wait(5):
                raise AssertionError("Background fixture was not released")
            return {"fixture": True}
        def send(identity, method, params=None):
            incoming.put((json.dumps({"id": identity, "method": method, "params": params or {}}) + "\n").encode())
        with patch.object(self.app, "project_preview", side_effect=delayed), patch.object(self.app, "set_resources", side_effect=delayed):
            worker = threading.Thread(target=lambda: closed.append(desktop_host.serve(self.host, Input(), Output())))
            worker.start()
            try:
                send(1, "project/inspect", {"path": str(self.root / "large.zip")})
                send(2, "resources/set", {"policy": self.policy()})
                self.assertTrue(entered.wait(2))
                send(3, "queue/status")
                reply = outgoing.get(timeout=1)
                self.assertEqual(reply["id"], 3)
                self.assertTrue(reply["ok"])
                send(4, "queue/cancel", {"job_id": response["added"][0]})
                reply = outgoing.get(timeout=1)
                self.assertEqual(reply["id"], 4)
                self.assertTrue(reply["ok"], reply)
                self.assertTrue(self.app.runs[response["added"][0]]["_cancel"].is_set())
            finally:
                release.set()
                incoming.put(b"")
                worker.join(6)
        self.assertFalse(worker.is_alive())
        self.assertEqual(closed, [True])

    def test_unknown_rpc_fields_and_arbitrary_preview_payloads_are_rejected(self):
        for method, params in (("resources/set", {"policy": {}, "run": True}),
                               ("restart/review", {"folder": str(self.root)}),
                               ("restart/queue", {"review": {}, "output_folder": str(self.root)}),
                               ("project/import", {"preview": {}, "destination_folder": str(self.root)}),
                               ("project/export", {"token": "x", "destination": "x", "graph": {}})):
            with self.assertRaises(ValueError, msg=method):
                self.host.dispatch(method, params)


if __name__ == "__main__":
    unittest.main()
