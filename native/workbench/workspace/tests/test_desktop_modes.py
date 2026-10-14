"""Native host mode isolation and canvas contracts; no Windows execution claim."""
from __future__ import annotations

import copy
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from desktop_host import DesktopHost
from desktop_model import DesktopModel
from service import Workbench, atomic_json


def fixture_catalog():
    tools = {}
    for name, kind, indexed in (("process", "reference", False),
                                 ("index", "reference", True),
                                 ("protein", "fasta-protein", False)):
        identity = "fixture/" + name
        field = {"id": "genome", "label": "Genome FASTA", "type": "file",
                 "required": True, "filter": "FASTA|*.fa;*.fasta"}
        port = {"id": "sequence", "label": "Sequence", "type": kind,
                "min": 1, "max": 1, "manifestInputs": ["genome"], "fields": [field]}
        if indexed:
            port["requiredState"] = {"indexed": True}
        tools[identity] = {
            "id": identity, "name": "Fixture " + name, "packId": "fixture",
            "packVersion": "1.0.0", "manifestSha256": "1" * 64,
            "ports": [port], "outputs": [{"id": "result", "label": "Result",
                                            "type": kind, "state": {"indexed": indexed}}],
            "params": [{"id": "threads", "label": "Threads", "type": "integer",
                        "default": "2", "required": True, "min": 1, "max": 8}], "defaults": {"threads": "2"}}
    return {"tools": tools, "packs": []}


class WaitingEngine:
    def __init__(self):
        self.running = threading.Event()

    def review(self, graph):
        return {"graph": copy.deepcopy(graph)}

    def prepare(self, graph, output, cancel, resource_policy=None):
        folder = Path(output) / "run-fixture"
        folder.mkdir(exist_ok=True)
        return {"folder": str(folder), "graph": graph, "methods": "Fixture methods"}

    def execute(self, plan, event, cancel):
        self.running.set()
        if not cancel.wait(5):
            raise RuntimeError("Fixture run was not cancelled")
        return {"status": "cancelled", "folder": plan["folder"], "nodes": []}


class LocalReference:
    def __init__(self, root):
        self.path = root / "reference.fa"
        self.path.write_text(">chr1\nACGT\n", encoding="utf-8")

    def resolve_file(self, record_id, file_id):
        if (record_id, file_id) != ("ready", "genome"):
            raise ValueError("Unknown fixture reference")
        return {"kind": "genome", "filename": self.path.name, "path": str(self.path)}

    def snapshot(self):
        return {"local": [{"id": "ready", "files": [{"id": "genome"}]}]}


class DesktopModeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="workbench-modes-")
        self.root = Path(self.tmp.name)
        self.app = Workbench(self.root, catalog=fixture_catalog())
        self.host = DesktopHost(self.root, app=self.app)

    def tearDown(self):
        self.host.close(grace=1)
        self.tmp.cleanup()

    def mode(self, value):
        return self.host.dispatch("workspace/mode", {"mode": value})

    def tool(self, name="process"):
        return self.host.dispatch("workspace/tool", {"toolId": "fixture/" + name})

    def action(self, action, **payload):
        return self.host.dispatch("model", {"action": action, "payload": payload})

    def test_startup_and_strict_workspace_requests_preserve_current_selection(self):
        state = self.host.dispatch("init", {})
        self.assertEqual(state["mode"], "tool")
        self.assertEqual(state["nodes"], [])
        self.tool()
        before = self.host.snapshot()
        for method, params in (("workspace/mode", {"mode": "history"}),
                               ("workspace/mode", {"mode": "workflow", "graph": {}}),
                               ("workspace/tool", {}),
                               ("workspace/tool", {"toolId": "not/installed"}),
                               ("workspace/tool", {"toolId": "fixture/process", "params": {}}),
                               ("workspace/tool", {"toolId": []})):
            with self.subTest(method=method, params=params), self.assertRaises(ValueError):
                self.host.dispatch(method, params)
            self.assertEqual(self.host.snapshot(), before)

    def test_tool_sessions_preserve_files_params_and_undo_without_touching_workflow(self):
        self.mode("workflow")
        self.action("add_tool", toolId="fixture/process")
        self.action("apply_fields", nodeId="step-1", params={"threads": "7"}, graphName="Workflow")
        workflow = self.host.graph()
        self.tool()
        path = str(self.root / "selected genome.fa")
        self.action("apply_fields", nodeId="step-1", params={"threads": "3"},
                    files={"input-1": {"genome": path}})
        single = self.host.graph()
        self.tool("index")
        self.action("apply_fields", nodeId="step-1", params={"threads": "4"})
        self.assertEqual(self.tool()["graph"], single)
        self.assertEqual(self.tool()["graph"], single, "Selecting the same tool must not reset edits")
        self.assertEqual(self.mode("workflow")["graph"], workflow)
        self.action("undo")
        self.assertNotEqual(self.host.graph(), workflow)
        self.assertEqual(self.mode("tool")["graph"], single)
        self.assertEqual(self.tool("index")["graph"]["nodes"][0]["params"]["threads"], "4")
        self.action("clear")
        reopened = self.tool("index")
        self.assertEqual(len(reopened["nodes"]), 1)
        self.assertEqual(reopened["graph"]["nodes"][0]["params"]["threads"], "2")

    def test_pipeline_load_and_example_select_workflow_and_preset_applies_active_tool(self):
        self.mode("workflow")
        self.action("add_tool", toolId="fixture/process")
        self.action("add_source", nodeId="step-1", portId="sequence")
        self.action("add_tool", toolId="fixture/process", fromRef="step-1::result")
        graph = self.host.graph()
        graph["sources"][0]["files"] = {"genome": str(self.root / "private.fa")}
        item = {"id": "pipeline", "graph": graph}
        preset = {"id": "preset", "tool": "fixture/process", "pin": graph["nodes"][0]["pin"],
                  "params": {"threads": "6"}}
        atomic_json(self.app.saved_path, {"pipelines": [item], "presets": [preset]})
        self.tool()
        loaded = self.host.dispatch("load", {"kind": "preset", "id": "preset", "node_id": "step-1"})
        self.assertEqual(loaded["mode"], "tool")
        single = self.host.graph()
        loaded = self.host.dispatch("load", {"kind": "pipeline", "id": "pipeline"})
        self.assertEqual(loaded["mode"], "workflow")
        self.assertEqual(len(loaded["nodes"]), 2)
        self.assertFalse(loaded["graph"]["sources"][0].get("files"))
        self.assertEqual(self.mode("tool")["graph"], single)
        with patch("example.make_example", return_value=graph):
            loaded = self.host.dispatch("example", {})
        self.assertEqual(loaded["mode"], "workflow")
        self.assertEqual(loaded["graph"]["sources"][0]["files"], graph["sources"][0]["files"])
        self.assertEqual(self.mode("tool")["graph"], single)

    def test_failed_pipeline_load_leaves_mode_and_both_sessions_unchanged(self):
        self.mode("workflow")
        self.action("add_tool", toolId="fixture/process")
        workflow = self.host.graph()
        self.tool("index")
        single = self.host.graph()
        atomic_json(self.app.saved_path, {"pipelines": [{"id": "broken", "graph": {"nodes": "invalid"}}], "presets": []})
        with self.assertRaises(ValueError):
            self.host.dispatch("load", {"kind": "pipeline", "id": "broken"})
        self.assertEqual(self.host.snapshot()["mode"], "tool")
        self.assertEqual(self.host.graph(), single)
        self.assertEqual(self.mode("workflow")["graph"], workflow)

    def test_reference_targets_and_binding_follow_active_session_only(self):
        manager = LocalReference(self.root)
        self.app._reference_manager = manager
        self.mode("workflow")
        self.action("add_tool", toolId="fixture/process")
        self.action("add_source", nodeId="step-1", portId="sequence")
        workflow = self.host.graph()
        self.tool()
        identity = {"record_id": "ready", "file_id": "genome"}
        target = self.host.dispatch("references/targets", identity)["targets"][0]
        result = self.host.dispatch("references/use", dict(identity, source_id=target["source_id"], field_id=target["field_id"]))
        self.assertEqual(result["model"]["mode"], "tool")
        self.assertEqual(self.host.graph()["sources"][0]["files"]["genome"], str(manager.path))
        self.assertEqual(self.mode("workflow")["graph"], workflow)
        self.assertEqual(self.host.dispatch("references/targets", identity)["targets"][0]["current_path"], "")
        self.tool("protein")
        self.assertEqual(self.host.dispatch("references/targets", identity)["targets"], [])

    def test_review_run_and_busy_switching_use_the_active_graph(self):
        self.mode("workflow")
        self.action("add_tool", toolId="fixture/process")
        self.action("add_tool", toolId="fixture/process", fromRef="step-1::result")
        self.tool("index")
        single = self.host.graph()
        self.app.engine = WaitingEngine()
        self.assertEqual(self.host.dispatch("review", {})["graph"], single)
        identity = self.host.dispatch("run", {"output_folder": str(self.root)})["run_id"]
        self.assertTrue(self.app.engine.running.wait(2))
        self.assertEqual(self.app.get_run(identity)["graph"], single)
        for method, params in (("workspace/mode", {"mode": "workflow"}),
                               ("workspace/tool", {"toolId": "fixture/process"})):
            self.host.dispatch(method, params)
        self.assertEqual(self.app.get_run(identity)["graph"], single)
        self.assertTrue(self.host.snapshot()["workspace_editable"])
        self.host.dispatch("cancel", {"run_id": identity})
        self.app.runs[identity]["_worker"].join(2)
        self.assertEqual(len(self.mode("workflow")["nodes"]), 2)

    def test_reference_and_pack_busy_flags_block_mode_and_tool_switches(self):
        self.tool()
        before = self.host.snapshot()
        for flag, message in (("_changing_references", "reference operation"),
                              ("_changing_packs", "pack operation")):
            with patch.object(self.app, flag, True):
                for call in (lambda: self.mode("workflow"), lambda: self.tool("index")):
                    with self.assertRaisesRegex(ValueError, message):
                        call()
            self.assertEqual(self.host.snapshot(), before)

    def test_pack_refresh_and_import_update_every_session_without_changing_pins(self):
        self.tool()
        self.tool("index")
        self.mode("workflow")
        self.action("add_tool", toolId="fixture/process")
        models = [self.host.model, *self.host._tool_models.values()]
        graphs = [copy.deepcopy(model.graph) for model in models]
        for method in ("packs/status", "import"):
            catalog = copy.deepcopy(self.app.catalog)
            for tool in catalog["tools"].values():
                tool["name"] += " refreshed"
            self.app.catalog = catalog
            if method == "packs/status":
                result = {"operation": {"status": "completed", "success": True, "id": "new-pack"}}
                operation = patch.object(self.app, "pack_state", return_value=result)
            else:
                operation = patch.object(self.app, "import_pack", return_value={"success": True})
            with operation:
                response = self.host.dispatch(method, {})
            self.assertEqual(response["model"]["mode"], "workflow")
            for model, graph in zip(models, graphs):
                self.assertIs(model.catalog, catalog)
                self.assertEqual(model.graph, graph)
                self.assertIn("refreshed", model.snapshot()["nodes"][0]["toolName"])

    def test_canvas_targets_match_type_state_and_cycle_validation(self):
        self.mode("workflow")
        self.action("add_tool", toolId="fixture/process")
        self.action("add_tool", toolId="fixture/process", fromRef="step-1::result")
        self.action("add_tool", toolId="fixture/index")
        state = self.action("add_tool", toolId="fixture/protein")
        before = self.host.snapshot()
        choices = {node["id"]: set() for node in state["nodes"]}
        for node in state["nodes"]:
            ref = node["outputs"][0]["ref"]
            preview = self.host.dispatch("workspace/connection-targets", {"ref": ref})
            self.assertEqual(preview["ref"], ref)
            for target in preview["targets"]:
                choices[target["nodeId"]].add(ref)
        self.assertEqual(self.host.snapshot(), before, "Drag previews must not change edits or selection")
        self.assertNotIn("step-1::result", choices["step-1"])
        self.assertNotIn("step-2::result", choices["step-1"])
        self.assertNotIn("step-4::result", choices["step-1"])
        self.assertIn("step-3::result", choices["step-1"])
        self.assertNotIn("step-1::result", choices["step-3"])
        self.assertNotIn("step-2::result", choices["step-3"])
        for node_id, ref in (("step-1", "step-2::result"), ("step-1", "step-4::result"),
                             ("step-3", "step-1::result")):
            before = self.host.graph()
            with self.assertRaisesRegex(ValueError, "compatible source"):
                self.action("connect", nodeId=node_id, portId="sequence", refs=[ref])
            self.assertEqual(self.host.graph(), before)
        connected = self.action("connect", nodeId="step-1", portId="sequence", refs=["step-3::result"])
        self.assertEqual(connected["graph"]["nodes"][0]["inputs"]["sequence"], ["step-3::result"])
        selected = self.action("select", nodeId="step-1")
        self.assertNotIn("choices", selected["nodes"][0]["inputs"][0])
        self.assertIn("choices", selected["inspector"]["ports"][0])
        for params in ({}, {"ref": "step-1::missing"}, {"ref": "input-missing"},
                       {"ref": "step-1::result", "nodeId": "step-2"}):
            with self.assertRaises(ValueError):
                self.host.dispatch("workspace/connection-targets", params)

    def test_canvas_target_capacity_and_bounded_large_snapshot(self):
        tool = self.app.catalog["tools"]["fixture/process"]
        tool["ports"][0]["max"] = 2
        self.mode("workflow")
        self.action("add_tool", toolId="fixture/process")
        self.action("add_source", nodeId="step-1", portId="sequence")
        self.action("add_tool", toolId="fixture/process")
        self.action("add_tool", toolId="fixture/process")
        self.action("connect", nodeId="step-3", portId="sequence", refs=["input-1", "step-1::result"])
        target = {"nodeId": "step-3", "portId": "sequence"}
        self.assertNotIn(target, self.host.dispatch("workspace/connection-targets", {"ref": "step-2::result"})["targets"])
        self.assertIn(target, self.host.dispatch("workspace/connection-targets", {"ref": "step-1::result"})["targets"])
        graph = {"name": "Large branch set", "nodes": [
            {"id": "step-" + str(i), "tool": "fixture/process", "inputs": {"sequence": ["input-1"]}, "params": {}}
            for i in range(1, 513)], "sources": [{"id": "input-1", "type": "reference", "files": {}}]}
        state = self.action("load_graph", graph=graph)
        self.assertLess(len(json.dumps(state).encode("utf-8")), 8 * 1024 * 1024)
        targets = self.host.dispatch("workspace/connection-targets", {"ref": "step-1::result"})
        self.assertEqual(len(targets["targets"]), 511)
        self.assertLess(len(json.dumps(targets).encode("utf-8")), 64 * 1024)

    def test_injected_model_remains_active_workflow_for_existing_callers(self):
        supplied = DesktopModel(self.root, self.app.catalog)
        supplied.dispatch("add_tool", {"toolId": "fixture/process"})
        host = DesktopHost(self.root, app=self.app, model=supplied)
        self.assertIs(host.model, supplied)
        self.assertEqual(host.snapshot()["mode"], "workflow")
        host.dispatch("workspace/tool", {"toolId": "fixture/index"})
        host.dispatch("workspace/mode", {"mode": "workflow"})
        self.assertIs(host.model, supplied)


if __name__ == "__main__":
    unittest.main(verbosity=2)
