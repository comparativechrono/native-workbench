"""Native desktop graph state, without HTTP, browser or a window toolkit."""
import copy
import json
import os
from pathlib import Path
import sys
import unittest

WORKSPACE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(WORKSPACE))
from catalog import load_catalog
from desktop_model import DesktopModel
from example import make_example

APP = Path(os.environ.get("NW_APP_ROOT", WORKSPACE.parents[2] / "integration-0.5/native-workbench")).resolve()


class DesktopModelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = load_catalog(APP)

    def setUp(self):
        self.model = DesktopModel(APP, self.catalog)

    def add(self, tool, **values):
        return self.model.dispatch("add_tool", dict(toolId=tool, **values))

    def test_empty_model_has_no_fake_run_or_preview(self):
        state = self.model.snapshot()
        self.assertEqual(state["nodes"], [])
        self.assertIsNone(state["inspector"])
        self.assertFalse(state["review"]["valid"])
        self.assertFalse(state["review"]["filesChecked"])
        json.dumps(state, allow_nan=False)

    def test_every_installed_tool_fields_ports_choices_and_outputs(self):
        self.assertGreaterEqual(len(self.catalog["tools"]),44)
        for identity, tool in self.catalog["tools"].items():
            with self.subTest(tool=identity):
                model = DesktopModel(APP,self.catalog)
                state=model.dispatch("add_tool",{"toolId":identity})
                inspector=state["inspector"]
                self.assertEqual(inspector["nodeId"],"step-1")
                self.assertEqual(inspector["tool"]["manifestSha256"],tool["manifestSha256"])
                self.assertEqual([p["id"] for p in inspector["params"]],[p["id"] for p in tool["params"]])
                self.assertEqual([p["id"] for p in inspector["ports"]],[p["id"] for p in tool["ports"]])
                for port, declared in zip(inspector["ports"],tool["ports"]):
                    self.assertEqual(len(port["refs"]),declared["min"])
                    for source in port["sources"]:
                        self.assertEqual([f["id"] for f in source["fields"]],declared["manifestInputs"])
                        for field, original in zip(source["fields"],declared["fields"]):
                            for key in ("label","type","role","filter"):
                                self.assertEqual(field.get(key),original.get(key))
                            self.assertEqual(field["value"],"")
                for field, original in zip(inspector["params"],tool["params"]):
                    self.assertEqual(field.get("choices"),original.get("choices"))
                    self.assertEqual(field.get("min"),original.get("min"))
                    self.assertEqual(field.get("max"),original.get("max"))
                self.assertEqual([o["ref"] for o in inspector["outputs"]],["step-1::"+o["id"] for o in tool["outputs"]])
                json.dumps(state,allow_nan=False)

    def test_paired_roles_binding_and_paths(self):
        state=self.add("fastp/paired")
        source=state["sources"][0]
        self.assertEqual([f["role"] for f in source["fields"]],["read1","read2"])
        paths={"reads1":str(APP/"examples/variant-truth/reads1.fastq"),"reads2":str(APP/"examples/variant-truth/reads2.fastq")}
        state=self.model.dispatch("bind_files",{"sourceId":source["id"],"files":paths})
        self.assertEqual(state["sources"][0]["files"],paths)
        with self.assertRaises(ValueError):
            self.model.dispatch("bind_files",{"sourceId":source["id"],"files":{"arbitrary":"bad"}})
        self.assertEqual(self.model.graph["sources"][0]["files"],paths)

    def test_exact_named_outputs_fanout_same_rank_then_join(self):
        self.add("reads/quality-profile")
        self.add("reads/statistics")
        self.model.dispatch("connect",{"nodeId":"step-2","portId":"reads","refs":["input-1"]})
        state=self.add("builtin/report")
        state=self.model.dispatch("connect",{"nodeId":"step-3","portId":"metrics","refs":["step-1::quality","step-2::statistics"]})
        self.assertEqual(state["ranks"],[{"rank":1,"nodes":["step-1","step-2"]},{"rank":2,"nodes":["step-3"]}])
        self.assertEqual([r["ref"] for r in state["inspector"]["ports"][0]["refs"]],["step-1::quality","step-2::statistics"])
        for label in [r["label"] for r in state["inspector"]["ports"][0]["refs"]]:
            self.assertIn(" → ",label)
            self.assertRegex(label,r"S[12] · ")
        self.assertEqual(state["nodes"][0]["outputs"][0]["consumers"][0]["nodeId"],"step-3")
        saved=self.model.engine.save_pipeline(self.model.graph)
        self.assertEqual(saved["nodes"][1]["inputs"]["reads"],["input-1"])

    def test_cycles_wrong_types_duplicates_atomic_rejection(self):
        self.add("reads/reverse-complement")
        self.add("reads/reverse-complement",fromRef="step-1::reversed")
        before=copy.deepcopy(self.model.graph)
        with self.assertRaises(ValueError):
            self.model.dispatch("connect",{"nodeId":"step-1","portId":"reads","refs":["step-2::reversed"]})
        self.assertEqual(self.model.graph,before)
        self.add("builtin/report")
        before=copy.deepcopy(self.model.graph)
        for refs in (["step-1::reversed"],["input-3","input-3"]):
            with self.assertRaises(ValueError):
                self.model.dispatch("connect",{"nodeId":"step-3","portId":"metrics","refs":refs})
            self.assertEqual(self.model.graph,before)

    def test_delete_no_silent_bypass_undo_and_never_reused_ids(self):
        self.add("reads/reverse-complement")
        self.add("reads/quality-profile",fromRef="step-1::reversed")
        state=self.model.dispatch("remove_step",{"nodeId":"step-1"})
        self.assertEqual(state["graph"]["nodes"][0]["inputs"]["reads"],[])
        self.assertIn("Reconnect",state["notice"])
        self.assertFalse(state["review"]["valid"])
        state=self.model.dispatch("undo")
        self.assertEqual(state["graph"]["nodes"][1]["inputs"]["reads"],["step-1::reversed"])
        self.model.dispatch("remove_step",{"nodeId":"step-2"})
        state=self.add("reads/statistics")
        self.assertEqual(state["selected"],"step-3")
        allocated_source=state["sources"][-1]["id"]
        self.model.dispatch("undo")
        state=self.add("reads/statistics")
        self.assertEqual(state["selected"],"step-4")
        self.assertNotEqual(state["sources"][-1]["id"],allocated_source)

    def test_rename_updates_named_provenance_and_methods(self):
        self.add("reads/reverse-complement")
        self.add("reads/quality-profile",fromRef="step-1::reversed")
        state=self.model.dispatch("rename_step",{"nodeId":"step-1","name":"Lane A preparation"})
        self.assertIn("Lane A preparation →",state["inspector"]["ports"][0]["refs"][0]["label"])
        self.assertIn("Lane A preparation →",state["review"]["methods"])
        self.model.dispatch("rename_source",{"sourceId":"input-1","name":"Lane A reads"})
        state=self.model.dispatch("select",{"nodeId":"step-1"})
        self.assertIn("Lane A reads",state["inspector"]["ports"][0]["refs"][0]["label"])

    def test_move_changes_sibling_order_only(self):
        self.add("reads/reverse-complement")
        self.add("reads/quality-profile",fromRef="step-1::reversed")
        self.add("reads/statistics",fromRef="step-1::reversed")
        links={n["id"]:copy.deepcopy(n["inputs"]) for n in self.model.graph["nodes"]}
        state=self.model.dispatch("move_step",{"nodeId":"step-3","direction":"up"})
        self.assertEqual(state["ranks"][1]["nodes"],["step-3","step-2"])
        self.assertEqual({n["id"]:n["inputs"] for n in state["graph"]["nodes"]},links)
        self.assertEqual(state["ranks"][0]["nodes"],["step-1"])

    def test_use_output_context_and_change_tool_disconnects_invalid_outputs(self):
        self.add("reads/reverse-complement")
        state=self.model.dispatch("use_output",{"ref":"step-1::reversed"})
        self.assertIn("reads/quality-profile",state["compatibleTools"])
        self.assertNotIn("variants/statistics",state["compatibleTools"])
        state=self.add("reads/quality-profile")
        self.assertEqual(state["graph"]["nodes"][1]["inputs"]["reads"],["step-1::reversed"])
        state=self.model.dispatch("change_tool",{"nodeId":"step-1","toolId":"reads/statistics"})
        self.assertEqual(state["graph"]["nodes"][1]["inputs"]["reads"],[])
        self.assertEqual(state["graph"]["nodes"][0]["inputs"]["reads"],["input-1"])
        self.assertIn("Reconnect",state["notice"])

    def test_load_template_strips_bindings_preserves_graph_pins_and_ids(self):
        example=make_example(APP,self.catalog)
        state=self.model.dispatch("load_graph",{"graph":example})
        self.assertEqual([n["id"] for n in state["graph"]["nodes"]],[n["id"] for n in example["nodes"]])
        self.assertEqual([n["inputs"] for n in state["graph"]["nodes"]],[n["inputs"] for n in example["nodes"]])
        self.assertEqual([n["pin"] for n in state["graph"]["nodes"]],[n["pin"] for n in example["nodes"]])
        self.assertTrue(all(s["files"]=={} for s in state["graph"]["sources"]))
        state=self.model.dispatch("select",{"nodeId":"step-2"})
        fields={p["id"]:p for p in state["inspector"]["params"]}
        self.assertEqual(fields["sample"]["value"],"")
        self.assertEqual(fields["read-group"]["value"],"")
        self.assertFalse(state["review"]["valid"])
        state=self.model.dispatch("load_graph",{"graph":example,"template":False})
        self.assertEqual(state["graph"]["sources"][0]["files"],example["sources"][0]["files"])

    def test_preset_keeps_files_sample_and_requires_exact_version(self):
        example=make_example(APP,self.catalog)
        self.model.dispatch("load_graph",{"graph":example,"template":False})
        preset=self.model.engine.save_preset(example["nodes"][1]);preset["params"]["threads"]="4"
        sources=copy.deepcopy(self.model.graph["sources"])
        state=self.model.dispatch("apply_preset",{"nodeId":"step-2","preset":preset})
        node=next(n for n in state["graph"]["nodes"] if n["id"]=="step-2")
        self.assertEqual(node["params"]["sample"],"truth")
        self.assertEqual(node["params"]["threads"],"4")
        self.assertEqual(state["graph"]["sources"],sources)
        preset["pin"]["packVersion"]="999.0.0"
        with self.assertRaises(ValueError):
            self.model.dispatch("apply_preset",{"nodeId":"step-2","preset":preset})

    def test_multiinput_add_disconnect_cardinality_and_new_slot(self):
        state=self.add("bam/merge")
        self.assertEqual(len(state["inspector"]["ports"][0]["refs"]),2)
        state=self.model.dispatch("add_source",{"nodeId":"step-1","portId":"alignments","label":"Third lane"})
        self.assertEqual(len(state["inspector"]["ports"][0]["refs"]),3)
        third=state["inspector"]["ports"][0]["refs"][-1]["ref"]
        state=self.model.dispatch("disconnect",{"nodeId":"step-1","portId":"alignments","ref":third})
        self.assertEqual(len(state["inspector"]["ports"][0]["refs"]),2)

    def test_unique_reference_reused_and_snapshot_is_compact(self):
        self.add("bwa/paired-end")
        state=self.add("variants/call")
        refs=[s for s in state["sources"] if s["type"]=="reference"]
        self.assertEqual(len(refs),1)
        self.assertEqual(state["graph"]["nodes"][0]["inputs"]["reference"],state["graph"]["nodes"][1]["inputs"]["reference"])
        self.assertNotIn("choices",state["nodes"][0]["inputs"][0])
        self.assertIn("choices",state["inspector"]["ports"][0])

    def test_large_model_snapshot_stays_below_ipc_frame_limit(self):
        graph={"name":"Large branch set","nodes":[{"id":"step-"+str(i),"tool":"reads/quality-profile","inputs":{"reads":["input-1"]},"params":{}} for i in range(1,513)],"sources":[{"id":"input-1","type":"reads","label":"Shared reads","files":{}}]}
        state=self.model.dispatch("load_graph",{"graph":graph})
        encoded=json.dumps(state,ensure_ascii=False).encode("utf-8")
        self.assertLess(len(encoded),8*1024*1024)
        self.assertEqual(len(state["ranks"][0]["nodes"]),512)

    def test_unbound_loaded_pipeline_can_be_saved_but_not_run(self):
        example=make_example(APP,self.catalog)
        self.model.dispatch("load_graph",{"graph":example})
        before=copy.deepcopy(self.model.graph)
        saved=self.model.engine.save_pipeline(self.model.graph)
        self.assertEqual(self.model.graph,before)
        bwa=next(n for n in saved["nodes"] if n["id"]=="step-2")
        self.assertNotIn("sample",bwa["params"])
        self.assertNotIn("read-group",bwa["params"])
        self.assertFalse(self.model.engine.review(self.model.graph)["valid"])
        with self.assertRaises(ValueError):
            self.model.engine.prepare(self.model.graph,APP)

    def test_apply_fields_atomic_failure_and_success_one_undo(self):
        self.add("bwa/paired-end")
        before=copy.deepcopy(self.model.graph)
        with self.assertRaises(ValueError):
            self.model.dispatch("apply_fields",{"nodeId":"step-1","params":{"threads":"4"},"files":{"input-1":{"unknown":"bad.fastq"}},"name":"Should not commit"})
        self.assertEqual(self.model.graph,before)
        with self.assertRaises(ValueError):
            self.model.dispatch("apply_fields",{"nodeId":"step-1","params":{"threads":"4","sample":"invalid sample"}})
        self.assertEqual(self.model.graph,before)
        state=self.model.dispatch("apply_fields",{"nodeId":"step-1","params":{"threads":"4","sample":"sample-a"},"files":{"input-1":{"reads1":"C:\\data\\mate1.fastq"}},"name":"Align lane A","graphName":"Experiment A"})
        self.assertEqual(state["graph"]["name"],"Experiment A")
        self.assertEqual(state["inspector"]["name"],"Align lane A")
        self.assertEqual(state["graph"]["nodes"][0]["params"]["threads"],"4")
        self.assertEqual(state["graph"]["sources"][0]["files"]["reads1"],"C:\\data\\mate1.fastq")
        state=self.model.dispatch("undo")
        self.assertEqual(state["graph"],before)

    def test_graph_name_only_form_commit_before_first_tool(self):
        state=self.model.dispatch("apply_fields",{"nodeId":"","graphName":"First analysis","params":{},"files":{}})
        self.assertEqual(state["graph"]["name"],"First analysis")
        self.assertEqual(state["nodes"],[])
        state=self.add("reads/statistics")
        self.assertEqual(state["graph"]["name"],"First analysis")
        self.assertEqual(state["selected"],"step-1")
        fresh=DesktopModel(APP,self.catalog)
        with self.assertRaises(ValueError):
            fresh.dispatch("apply_fields",{"nodeId":"","name":"Missing step"})


if __name__=="__main__":
    unittest.main(verbosity=2)
