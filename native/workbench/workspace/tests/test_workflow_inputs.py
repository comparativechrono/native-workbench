"""Explicit workflow inputs and legacy/standalone bindings; no Windows claim."""
from __future__ import annotations

import copy
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from desktop_host import DesktopHost
from desktop_model import DesktopModel
from engine import _source_fields
from service import Workbench
from test_desktop_modes import fixture_catalog, LocalReference


def catalog():
    result = fixture_catalog()
    for identity, fields in (("paired", ("left", "right")), ("paired-other", ("forward", "reverse"))):
        tool = copy.deepcopy(result["tools"]["fixture/process"])
        tool.update(id="fixture/" + identity, name="Paired " + identity)
        tool["ports"] = [{"id": "reads", "label": "Paired reads", "type": "pair", "min": 1, "max": 1,
                          "manifestInputs": list(fields), "fields": [
                              {"id": field, "label": "Read " + str(index + 1), "type": "file", "required": True,
                               "role": "read" + str(index + 1), "filter": "FASTQ|*.fastq;*.fq"}
                              for index, field in enumerate(fields)]}]
        tool["outputs"] = [{"id": "result", "label": "Processed reads", "type": "pair", "state": {}}]
        result["tools"][tool["id"]] = tool
    return result


class WorkflowInputTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="workbench-inputs-")
        self.root = Path(self.tmp.name)
        self.app = Workbench(self.root, catalog=catalog())
        self.host = DesktopHost(self.root, app=self.app)
        self.host.dispatch("workspace/mode", {"mode": "workflow"})

    def tearDown(self):
        self.host.close(grace=1)
        self.tmp.cleanup()

    def action(self, action, **payload):
        return self.host.dispatch("model", {"action": action, "payload": payload})

    def test_workflow_tools_start_unconnected_without_automatic_file_boxes(self):
        self.action("add_tool", toolId="fixture/process")
        state = self.action("add_tool", toolId="fixture/paired")
        self.assertEqual(state["sources"], [])
        self.assertEqual(state["graph"]["sources"], [])
        self.assertEqual([node["inputs"] for node in state["graph"]["nodes"]], [{"sequence": []}, {"reads": []}])
        self.assertEqual(state["inspector"]["sources"], [])
        self.assertEqual(state["inspector"]["ports"][0]["sources"], [])
        self.assertFalse(state["review"]["valid"])
        self.assertTrue(any(error.get("portId") == "reads" for error in state["review"]["errors"]))
        state = self.action("add_tool", toolId="fixture/process", fromRef="step-1::result")
        self.assertEqual(state["graph"]["nodes"][-1]["inputs"]["sequence"], ["step-1::result"])
        self.assertEqual(state["sources"], [])

    def test_standalone_fields_remain_available_and_do_not_change_workflow(self):
        self.action("add_tool", toolId="fixture/paired")
        workflow = self.host.graph()
        state = self.host.dispatch("workspace/tool", {"toolId": "fixture/paired"})
        self.assertEqual(len(state["sources"]), 1)
        self.assertEqual([field["id"] for field in state["inspector"]["ports"][0]["sources"][0]["fields"]], ["left", "right"])
        self.action("apply_fields", nodeId="step-1", files={"input-1": {"left": "left.fq", "right": "right.fq"}})
        self.assertEqual(self.host.dispatch("workspace/mode", {"mode": "workflow"})["graph"], workflow)

    def test_explicit_reference_can_be_bound_before_tools_and_shared_without_duplicate_editors(self):
        self.app._reference_manager = manager = LocalReference(self.root)
        state = self.action("add_input", inputType="reference", label="Yeast reference")
        self.assertEqual(state["selected"], "input-1")
        self.assertEqual(state["inspector"]["kind"], "source")
        identity = {"record_id": "ready", "file_id": "genome"}
        targets = self.host.dispatch("references/targets", identity)["targets"]
        self.assertEqual([(target["source_id"], target["field_id"]) for target in targets], [("input-1", "genome")])
        self.host.dispatch("references/use", dict(identity, source_id="input-1", field_id="genome"))
        for number in (1, 2):
            self.action("add_tool", toolId="fixture/process")
            state = self.action("connect", nodeId="step-" + str(number), portId="sequence", refs=["input-1"])
            self.assertEqual(state["inspector"]["ports"][0]["sources"], [])
            self.assertEqual(state["inspector"]["sources"], [])
            self.assertEqual(state["inspector"]["ports"][0]["refs"][0]["ref"], "input-1")
        self.assertEqual(len(state["sources"]), 1)
        self.assertEqual(len(state["sources"][0]["consumers"]), 2)
        state = self.action("select", nodeId="input-1")
        self.assertEqual(state["inspector"]["fields"][0]["value"], str(manager.path))
        state = self.action("apply_fields", sourceId="input-1", name="Shared genome", files={"input-1": {"genome": str(manager.path)}})
        self.assertEqual(state["sources"][0]["label"], "Shared genome")
        self.assertTrue(self.host.model.engine.validate(self.host.graph(), check_files=True)["ok"])

    def test_pair_roles_remain_stable_across_receivers_and_bind_as_one_atomic_pair(self):
        # Third-party metadata can give paired fields distinct manifest IDs;
        # their declared pair order still carries read-1/read-2 roles.
        for tool in self.app.catalog["tools"].values():
            if tool["ports"][0]["type"] == "pair":
                for field in tool["ports"][0]["fields"]:
                    field["role"] = "file"
        state = self.action("add_input", inputType="pair", label="Sample A reads")
        self.assertEqual([(field["id"], field["role"]) for field in state["inspector"]["fields"]], [("reads1", "read1"), ("reads2", "read2")])
        paths = {}
        for number in (1, 2):
            path = self.root / ("reads" + str(number) + ".fastq")
            path.write_text("@read/" + str(number) + "\nACGT\n+\nIIII\n", encoding="utf-8")
            paths["reads" + str(number)] = str(path)
        self.action("apply_fields", sourceId="input-1", files={"input-1": paths})
        for number, identity in enumerate(("paired", "paired-other"), 1):
            self.action("add_tool", toolId="fixture/" + identity)
            self.action("connect", nodeId="step-" + str(number), portId="reads", refs=["input-1"])
            port = self.app.catalog["tools"]["fixture/" + identity]["ports"][0]
            self.assertEqual(list(_source_fields(self.host.graph()["sources"][0], port).values()), list(paths.values()))
        self.assertTrue(self.host.model.engine.validate(self.host.graph(), check_files=True)["ok"])
        saved = self.host.model.engine.save_pipeline(self.host.graph())
        self.action("load_graph", graph=saved)
        self.action("apply_fields", sourceId="input-1", files={"input-1": paths})
        self.assertTrue(self.host.model.engine.validate(self.host.graph(), check_files=True)["ok"])
        self.action("remove_step", nodeId="step-1")
        state = self.action("select", nodeId="input-1")
        self.assertEqual({field["id"]: field["value"] for field in state["inspector"]["fields"]}, paths)
        self.action("apply_fields", sourceId="input-1", files={"input-1": {"reads2": paths["reads1"]}})
        self.assertFalse(self.host.model.engine.validate(self.host.graph(), check_files=True)["ok"])

    def test_remove_input_disconnects_all_consumers_and_undo_preserves_bound_files(self):
        self.action("add_input", inputType="reference")
        self.action("apply_fields", sourceId="input-1", files={"input-1": {"genome": "genome.fa"}})
        for number in (1, 2):
            self.action("add_tool", toolId="fixture/process")
            self.action("connect", nodeId="step-" + str(number), portId="sequence", refs=["input-1"])
        self.action("select", nodeId="input-1")
        before = self.host.graph()
        state = self.action("remove_source", sourceId="input-1")
        self.assertEqual(state["sources"], [])
        self.assertIsNone(state["selected"])
        self.assertTrue(all(node["inputs"]["sequence"] == [] for node in state["graph"]["nodes"]))
        self.assertIn("Reconnect", state["notice"])
        self.assertEqual(self.action("undo")["graph"], before)
        self.action("remove_source", sourceId="input-1")
        state = self.action("add_input", inputType="reference")
        self.assertEqual(state["selected"], "input-2")

    def test_input_and_tool_forms_reject_cross_object_edits_atomically(self):
        self.action("add_input", inputType="reference")
        self.action("add_tool", toolId="fixture/process")
        before = self.host.graph()
        bad = [("apply_fields", {"sourceId": "input-1", "params": {"threads": "8"}}),
               ("apply_fields", {"sourceId": "input-1", "nodeId": "step-1", "name": "Ambiguous"}),
               ("apply_fields", {"sourceId": "input-1", "files": {"input-2": {"genome": "bad.fa"}}}),
               ("apply_fields", {"sourceId": "input-1", "files": {"input-1": {"unknown": "bad.fa"}}}),
               ("apply_fields", {"nodeId": "step-1", "files": {"input-1": {"genome": "unconnected.fa"}}}),
               ("add_input", {"inputType": "unknown"}),
               ("add_input", {"inputType": "reference", "fields": []}),
               ("add_input", {"inputType": "reference", "label": " "})]
        for action, payload in bad:
            with self.subTest(action=action, payload=payload), self.assertRaises(ValueError):
                self.action(action, **payload)
            self.assertEqual(self.host.graph(), before)

    def test_changing_workflow_tool_never_fills_unconnected_ports_implicitly(self):
        self.action("add_tool", toolId="fixture/process")
        self.action("add_tool", toolId="fixture/process", fromRef="step-1::result")
        state = self.action("change_tool", nodeId="step-1", toolId="fixture/protein")
        self.assertEqual(state["sources"], [])
        self.assertEqual(state["graph"]["nodes"][0]["inputs"]["sequence"], [])
        self.assertEqual(state["graph"]["nodes"][1]["inputs"]["sequence"], [])

    def test_saved_workflow_and_legacy_graph_keep_pins_sources_and_connections(self):
        self.action("add_input", inputType="reference", label="Shared genome")
        self.action("apply_fields", sourceId="input-1", files={"input-1": {"genome": "private.fa"}})
        self.action("add_tool", toolId="fixture/process")
        self.action("connect", nodeId="step-1", portId="sequence", refs=["input-1"])
        self.action("add_tool", toolId="fixture/process", fromRef="step-1::result")
        before = self.host.graph()
        saved = self.host.model.engine.save_pipeline(before)
        self.assertNotIn("files", saved["sources"][0])
        state = self.action("load_graph", graph=saved)
        self.assertEqual([node["pin"] for node in state["graph"]["nodes"]], [node["pin"] for node in before["nodes"]])
        self.assertEqual([node["inputs"] for node in state["graph"]["nodes"]], [node["inputs"] for node in before["nodes"]])
        self.assertEqual(state["sources"][0]["files"], {})
        saved["sources"][0].pop("fields", None)
        state = self.action("load_graph", graph=saved)
        self.assertEqual(state["sources"][0]["fields"][0]["id"], "genome")
        self.assertEqual(state["sources"][0]["consumers"][0]["nodeId"], "step-1")
        self.assertEqual(self.action("select", nodeId="input-1")["inspector"]["kind"], "source")

    def test_detached_input_schema_survives_template_load_without_file_values(self):
        self.action("add_input", inputType="pair")
        graph = self.host.graph()
        graph["sources"][0]["files"] = {"reads1": "private-1.fq", "reads2": "private-2.fq"}
        graph["sources"][0]["fields"][0].update(default="private-default.fq", value="private-value.fq")
        self.action("load_graph", graph=graph)
        state = self.action("select", nodeId="input-1")
        self.assertEqual(state["sources"][0]["files"], {})
        self.assertEqual([field["id"] for field in state["inspector"]["fields"]], ["reads1", "reads2"])
        self.assertTrue(all(field["value"] == "" and "default" not in field for field in state["inspector"]["fields"]))

    def test_accepted_sam_input_is_named_and_typed_separately_from_bam(self):
        base = self.app.catalog["tools"]["fixture/process"]
        for identity, accepts in (("sort", ["sam", "bam"]), ("bam-index", ["bam"])):
            tool = copy.deepcopy(base)
            tool.update(id="fixture/" + identity, name=identity)
            tool["ports"][0].update(type="bam", accepts=accepts)
            self.app.catalog["tools"][tool["id"]] = tool
        self.host.model.update_catalog(self.app.catalog)
        kinds = {item["id"]: item for item in self.host.snapshot()["inputTypes"]}
        self.assertEqual(kinds["sam"]["label"], "SAM alignments")
        self.assertEqual(kinds["bam"]["label"], "BAM alignments")
        self.action("add_input", inputType="sam")
        self.action("add_tool", toolId="fixture/sort")
        self.action("add_tool", toolId="fixture/bam-index")
        targets = self.host.dispatch("workspace/connection-targets", {"ref": "input-1"})["targets"]
        self.assertIn({"nodeId": "step-1", "portId": "sequence"}, targets)
        self.assertNotIn({"nodeId": "step-2", "portId": "sequence"}, targets)
        with self.assertRaisesRegex(ValueError, "compatible source"):
            self.action("connect", nodeId="step-2", portId="sequence", refs=["input-1"])

    def test_detached_input_remains_editable_after_saving_a_connected_pipeline(self):
        self.action("add_input", inputType="reference")
        self.action("add_tool", toolId="fixture/process")
        self.action("connect", nodeId="step-1", portId="sequence", refs=["input-1"])
        self.action("add_tool", toolId="fixture/process", fromRef="step-1::result")
        self.action("add_input", inputType="pair", label="Next sample")
        before = self.host.snapshot()["inspector"]["fields"]
        saved = self.host.model.engine.save_pipeline(self.host.graph())
        self.action("load_graph", graph=saved)
        state = self.action("select", nodeId="input-2")
        self.assertEqual(state["inspector"]["fields"], before)


if __name__ == "__main__":
    unittest.main(verbosity=2)
