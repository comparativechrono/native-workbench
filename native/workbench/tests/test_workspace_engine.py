"""Graph-engine regression tests, including real portable tool integration.

Run with NW_APP_ROOT pointing at an assembled runtime. Linux portable execution
is a test adapter, never the Windows production backend.
"""
import copy
import gzip
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest

SOURCE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SOURCE / "workspace"))
from catalog import load_catalog, parse_pack
from engine import Engine, NativeBackend, digest_file, _parse_header, _fasta_dictionary

APP = Path(os.environ.get("NW_APP_ROOT", SOURCE.parents[1] / "integration-0.5" / "native-workbench")).resolve()


def graph_for(reads, two=True, report=True):
    graph = {"name": "Shared reads, independent summaries", "sources": [{"id": "input-1", "type": "reads", "label": "Reads", "files": {"reads": str(reads)}}], "nodes": [{"id": "step-1", "tool": "reads/quality-profile", "inputs": {"reads": ["input-1"]}, "params": {}}], "nextNode": 10, "nextSource": 5}
    if two:
        graph["nodes"].append({"id": "step-2", "tool": "reads/statistics", "inputs": {"reads": ["input-1"]}, "params": {}})
        if report:
            graph["nodes"].append({"id": "step-3", "tool": "builtin/report", "params": {"title": "Branch report"}, "inputs": {"metrics": ["step-1::quality", "step-2::statistics"]}})
    return graph


class FakeBackend:
    def __init__(self, catalog, fail=None, corrupt=None):
        self.catalog, self.fail, self.corrupt = catalog, fail, corrupt
        self.calls = []
    def run(self, request, event, cancel):
        self.calls.append(request)
        key = Path(request["pack_folder"]).name.rsplit("-", 1)[0] + "/" + request["workflow_id"]
        tool = self.catalog["tools"][key]
        folder = Path(request["output_folder"]) / "native-run"
        folder.mkdir()
        if request["workflow_id"] == self.fail:
            return {"success": False, "message": "Injected tool failure", "folder": str(folder)}
        for output in tool["outputs"]:
            for relative in output["files"].values():
                path = folder / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text('@r\nACGT\n+\nIIII\n' if output["type"] == "reads" else '<script>should be escaped</script>\nrecords=1\n', encoding="utf-8")
        if self.corrupt:
            self.corrupt(request, folder)
        return {"success": True, "message": "Completed", "folder": str(folder)}
    def inspect_alignment(self, executable, path, cancel):
        return "@HD\tVN:1.6\tSO:coordinate\n@SQ\tSN:chr1\tLN:4\n@RG\tID:" + Path(path).stem + "\tSM:sample1\n@PG\tID:fixmate\tPN:samtools\tCL:samtools fixmate\n"


class PortableBackend:
    """Trusted installed manifests, real APE binaries, shell-free test only."""
    def __init__(self, app_root):
        self.app = Path(app_root)
        self.loader = SOURCE / "baselines" / "bin" / "ape-loader-linux"
    def inspect_alignment(self, executable, path, cancel):
        result = subprocess.run([str(self.loader), str(executable), "view", "-H", str(path)], capture_output=True, check=True)
        return result.stdout.decode()
    def run(self, request, event, cancel):
        pack_root = Path(request["pack_folder"])
        pack = parse_pack((pack_root / "pack.ini").read_text(encoding="utf-8"))
        workflow = pack["workflows"][request["workflow_id"]]
        folder = Path(request["output_folder"]) / "portable-test"
        folder.mkdir()
        outputs = {o["id"]: str(folder / o["path"]) for o in workflow["outputs"]}
        assets = {key: str(pack_root / value["path"]) for key, value in pack["assets"].items()}
        def expand(text):
            text = text.replace("{run}", str(folder))
            for kind, values in (("input", request["values"]), ("output", outputs), ("asset", assets)):
                for key, value in values.items():
                    text = text.replace("{" + kind + ":" + key + "}", value)
            return text
        def arguments(args):
            result = []
            for arg in args:
                if arg.startswith("{inputs:") and arg.endswith("}"):
                    result.extend(request["values"][arg[8:-1]].splitlines())
                else:
                    result.append(expand(arg))
            return result
        def command(identity, args):
            item = pack["tools"][identity]
            path = pack_root / item["path"]
            if digest_file(path) != item["sha256"]:
                raise ValueError("Portable test binary hash mismatch")
            return [str(self.loader), str(path)] + arguments(args)
        try:
            for step in workflow["steps"]:
                if cancel.is_set():
                    return {"success": False, "cancelled": True, "folder": str(folder)}
                event({"type": "phase", "message": step["label"]})
                if step["kind"] == "copy":
                    shutil.copyfile(expand(step["source"]), outputs[step["destination"]])
                    continue
                stdout_path = Path(outputs[step["stdout"]]) if step.get("stdout") else folder / (step["id"] + ".stdout.txt")
                with stdout_path.open("wb") as stdout, (folder / (step["id"] + ".stderr.txt")).open("wb") as stderr:
                    if step["kind"] == "pipe":
                        producer = subprocess.Popen(command(step["tool"], step["args"]), cwd=folder, stdout=subprocess.PIPE, stderr=stderr)
                        sink = subprocess.Popen(command(step["sinkTool"], step["sinkArgs"]), cwd=folder, stdin=producer.stdout, stdout=stdout, stderr=stderr)
                        producer.stdout.close()
                        sink_code, producer_code = sink.wait(), producer.wait()
                        if sink_code or producer_code:
                            raise ValueError(f"Portable pipeline failed {producer_code}/{sink_code}: {step['id']}")
                    else:
                        subprocess.run(command(step["tool"], step["args"]), cwd=folder, stdout=stdout, stderr=stderr, check=True)
            return {"success": True, "folder": str(folder), "message": "Portable manifest adapter completed"}
        except Exception as exc:
            return {"success": False, "folder": str(folder), "message": str(exc)}


class EngineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = load_catalog(APP)
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="graph-engine-")
        self.folder = Path(self.tmp.name)
        self.reads = self.folder / "reads.fastq"
        self.reads.write_text("@one\nACGT\n+\nIIII\n", encoding="ascii")
        self.backend = FakeBackend(self.catalog)
        self.engine = Engine(APP, self.catalog, self.backend)
        self.graph = graph_for(self.reads)
    def tearDown(self):
        self.tmp.cleanup()
    def test_branch_ranks_and_connection(self):
        review = self.engine.validate(self.graph)
        self.assertTrue(review["ok"], review)
        self.assertEqual(self.engine.rank_groups(self.graph), [{"rank":1,"nodes":["step-1","step-2"]},{"rank":2,"nodes":["step-3"]}])
        self.assertEqual(len(self.engine.save_pipeline(self.graph)["nodes"]), 3)
    def test_one_tool_is_preset_not_pipeline(self):
        graph = graph_for(self.reads, two=False)
        self.assertTrue(self.engine.validate(graph)["ok"])
        with self.assertRaisesRegex(ValueError, "two connected"):
            self.engine.save_pipeline(graph)
        preset = self.engine.save_preset({"tool": "bwa/paired-end", "params": {"sample":"do-not-save", "read-group":"rg", "library":"lib", "platform-unit":"unit"}})
        self.assertNotIn("sample", preset["params"])
        self.assertNotIn("read-group", preset["params"])
        self.assertNotIn("inputs", preset)
    def test_save_clears_bindings_keeps_ids_names_pins(self):
        self.graph["nodes"][0]["label"] = "Selected lane"
        self.graph["sources"][0].update(sample="secret",reference="ref")
        saved = self.engine.save_pipeline(self.graph)
        self.assertNotIn("files", saved["sources"][0])
        self.assertNotIn("sample", saved["sources"][0])
        self.assertEqual(saved["nextNode"], 10)
        self.assertEqual(saved["nodes"][0]["label"], "Selected lane")
        self.assertIn("manifestSha256", saved["nodes"][0]["pin"])
    def test_cycle_unknown_reference_and_wrong_type(self):
        g = graph_for(self.reads, two=False)
        g["nodes"][0].update(tool="reads/reverse-complement",inputs={"reads":["step-1::reversed"]})
        self.assertFalse(self.engine.validate(g)["ok"])
        g["nodes"][0]["inputs"]={"reads":["step-9::reversed"]}
        self.assertFalse(self.engine.validate(g)["ok"])
        g["nodes"][0]["inputs"]={"reads":["input-1"]}
        g["sources"][0]["type"]="reference"
        self.assertFalse(self.engine.validate(g)["ok"])
    def test_duplicate_connections_and_version_drift(self):
        self.graph["nodes"][2]["inputs"]["metrics"]=["step-1::quality", "step-1::quality"]
        self.assertFalse(self.engine.validate(self.graph)["ok"])
        self.graph = graph_for(self.reads)
        self.graph["nodes"][0]["pin"]={"packVersion":"999.0.0"}
        self.assertFalse(self.engine.validate(self.graph)["ok"])
    def test_parameters_constraints_no_arbitrary_commands(self):
        g = graph_for(self.reads, two=False)
        g["nodes"][0]["params"]={"command":"echo injected"}
        self.assertFalse(self.engine.validate(g)["ok"])
        with self.assertRaises(ValueError):
            self.engine.save_preset({"tool":"bwa/paired-end","params":{"threads":"99"}})
        with self.assertRaises(ValueError):
            self.engine.save_preset({"tool":"trimming/cutadapt-paired","params":{"adapter1":"-oops"}})
    def test_pair_roles_are_atomic_and_not_object_order(self):
        g = graph_for(self.reads, two=False)
        g["nodes"][0].update(tool="reads/check-pairs",inputs={"reads":["input-1"]})
        g["sources"][0].update(type="pair",files={"reads1":str(self.reads),"reads2":str(self.reads)})
        self.assertFalse(self.engine.validate(g)["ok"])
        mate=self.folder/"mate.fastq"; mate.write_text(self.reads.read_text())
        g["sources"][0]["files"]={"arbitraryB":str(mate),"arbitraryA":str(self.reads)}
        self.assertFalse(self.engine.validate(g)["ok"])
        g["sources"][0]["files"]={"reads2":str(mate),"reads1":str(self.reads)}
        self.assertTrue(self.engine.validate(g)["ok"])
    def test_frozen_tamper_and_input_change(self):
        plan=self.engine.prepare(self.graph,self.folder)
        bad=copy.deepcopy(plan);bad["graph"]["name"]="tampered"
        with self.assertRaisesRegex(ValueError,"changed"):
            self.engine.execute(bad)
        self.reads.write_text("@new\nTTTT\n+\nIIII\n")
        record=self.engine.execute(plan)
        self.assertEqual(record["status"],"failed")
        self.assertEqual([n["status"] for n in record["nodes"]],["failed","failed","blocked"])
    def test_failure_blocks_join_but_independent_branch_runs(self):
        self.backend.fail="quality-profile"
        record=self.engine.execute(self.engine.prepare(self.graph,self.folder))
        self.assertEqual([n["status"] for n in record["nodes"]],["failed","success","blocked"])
        self.assertEqual(len(self.backend.calls),2)
        self.assertNotIn("Quality profile was performed",record["methods"])
        self.assertIn("(FASTQ statistics) was performed",record["methods"])
    def test_success_report_escapes_and_separates(self):
        record=self.engine.execute(self.engine.prepare(self.graph,self.folder))
        self.assertTrue(record["success"],record)
        report=Path(record["outputs"]["step-3::report"]["files"]["report"]).read_text()
        self.assertEqual(report.count("<section>"),2)
        self.assertNotIn("<script>",report)
        self.assertIn("&lt;script&gt;",report)
        self.assertIn("Branch report",report)
    def test_report_attributes_sections_to_frozen_named_producers(self):
        self.graph["nodes"][0]["label"]="Retained <sequence> statistics"
        self.graph["nodes"][1]["label"]="Original sequence statistics"
        plan=self.engine.prepare(self.graph,self.folder)
        self.graph["nodes"][0]["label"]="Changed after freezing"
        record=self.engine.execute(plan)
        self.assertTrue(record["success"],record)
        report=Path(record["outputs"]["step-3::report"]["files"]["report"]).read_text()
        self.assertIn("S1 · Retained &lt;sequence&gt; statistics",report)
        self.assertIn("S2 · Original sequence statistics",report)
        self.assertNotIn("Changed after freezing",report)
        self.assertIn("step-1::quality",report)
        self.assertIn("step-2::statistics",report)
    def test_external_reports_are_distinct_named_sections(self):
        a=self.folder/"a.txt";a.write_text("alpha uniquely")
        b=self.folder/"b.txt";b.write_text("beta uniquely")
        g={"name":"Reports","sources":[{"id":"input-1","type":"metrics","label":"A","files":{"metrics":str(a)}},{"id":"input-2","type":"metrics","label":"B","files":{"metrics":str(b)}}],"nodes":[{"id":"step-1","tool":"builtin/report","params":{},"inputs":{"metrics":["input-1","input-2"]}}]}
        record=self.engine.execute(self.engine.prepare(g,self.folder))
        report=Path(record["outputs"]["step-1::report"]["files"]["report"]).read_text()
        self.assertEqual(report.count("alpha uniquely"),1)
        self.assertEqual(report.count("beta uniquely"),1)
        self.assertIn("input-1 · A",report)
        self.assertIn("input-2 · B",report)
    def test_cancellation_marks_all_pending_steps(self):
        event=threading.Event();event.set()
        record=self.engine.execute(self.engine.prepare(self.graph,self.folder),cancel=event)
        self.assertEqual(record["status"],"cancelled")
        self.assertEqual(self.backend.calls,[])
    def test_malformed_json_reviews_are_errors(self):
        for graph in (None,[],{}, {"nodes":[{"id":"step-1","tool":[]}],"sources":[]}, {"nodes":[],"sources":[],"__proto__":{}}):
            self.assertFalse(self.engine.review(graph)["ok"])
    def test_reuse_plan_is_rejected(self):
        plan=self.engine.prepare(self.graph,self.folder)
        self.engine.execute(plan)
        with self.assertRaisesRegex(ValueError,"already started"):
            self.engine.execute(plan)
    def test_duplicate_read_lineage_blocks_lane_merge(self):
        from example import make_example
        graph=make_example(APP,self.catalog)
        graph["nodes"]=graph["nodes"][:3]
        graph["nodes"].append({"id":"step-4","tool":"bam/sort","params":{},"inputs":{"alignment":["step-2::aligned"]}})
        graph["nodes"].append({"id":"step-5","tool":"bam/merge","params":{},"inputs":{"alignments":["step-3::bam","step-4::sorted"]}})
        review=self.engine.validate(graph,check_files=False)
        self.assertTrue(any("share original reads" in issue["message"] for issue in review["errors"]))
    def test_reference_slot_mismatch_is_rejected(self):
        from example import make_example
        graph=make_example(APP,self.catalog)
        graph["sources"].append(dict(graph["sources"][1],id="input-3"))
        graph["nodes"][3]["inputs"]["reference"]=["input-3"]
        review=self.engine.validate(graph,check_files=False)
        self.assertTrue(any("different reference" in issue["message"] for issue in review["errors"]))
    def test_reference_header_mismatch_is_rejected(self):
        ref=self.folder/"ref.fa";ref.write_text(">different\nACGT\n")
        node={"tool":self.catalog["tools"]["variants/call"]}
        with self.assertRaisesRegex(ValueError,"reference names or lengths"):
            self.engine._preflight(node,{"alignment":str(self.folder/"input.bam"),"reference":str(ref)},threading.Event())
    def test_reference_identity_evidence_is_honest(self):
        ref=self.folder/"ref.fa";ref.write_text(">chr1\nACGT\n")
        evidence=self.engine._preflight({"tool":self.catalog["tools"]["variants/call"]},{"alignment":str(self.folder/"input.bam"),"reference":str(ref)},threading.Event())
        self.assertEqual(evidence["referenceChecks"][0]["check"],"contig-names-and-lengths")
    def test_real_portable_branch_report(self):
        engine=Engine(APP,self.catalog,PortableBackend(APP))
        graph=graph_for(self.reads)
        graph["nodes"][1]["tool"]="reads/quality-profile"
        graph["nodes"][2]["inputs"]["metrics"][1]="step-2::quality"
        record=engine.execute(engine.prepare(graph,self.folder))
        self.assertTrue(record["success"],record)
        quality=Path(record["outputs"]["step-2::quality"]["files"]["quality"]).read_text()
        self.assertIn("ALL",quality)
        self.assertEqual(quality,Path(record["outputs"]["step-1::quality"]["files"]["quality"]).read_text())

    def test_stored_plan_tamper_is_rejected(self):
        plan=self.engine.prepare(self.graph,self.folder)
        path=Path(plan["folder"])/"plan.json"
        stored=json.loads(path.read_text());stored["graph"]["name"]="changed on disk"
        path.write_text(json.dumps(stored))
        with self.assertRaisesRegex(ValueError,"stored execution plan"):
            self.engine.execute(plan)

    def test_saved_template_whitelists_fields(self):
        self.graph["output_folder"]="do-not-save"
        self.graph["sources"][0]["bindings"]={"files":{"hidden":"secret.fastq"}}
        self.graph["sources"][0]["fields"]=[{"id":"reads","default":"secret.fastq"}]
        saved=self.engine.save_pipeline(self.graph)
        self.assertNotIn("do-not-save",json.dumps(saved))
        self.assertNotIn("secret.fastq",json.dumps(saved))
        self.assertEqual(saved["sources"][0]["fields"][0]["default"],"")

    def test_full_portable_variant_graph_matches_truth(self):
        from example import make_example
        engine=Engine(APP,self.catalog,PortableBackend(APP))
        graph=make_example(APP,self.catalog)
        record=engine.execute(engine.prepare(graph,self.folder))
        self.assertTrue(record["success"],[(n["id"],n["status"],n.get("message")) for n in record["nodes"]])
        expected=[line.split("\t") for line in (APP/"examples/variant-truth/expected-variants.tsv").read_text().splitlines()]
        for identity in ("step-4", "step-5"):
            path=Path(record["outputs"][identity+"::variants"]["files"]["variants"])
            rows=[]
            with gzip.open(path,"rt") as stream:
                for line in stream:
                    if not line.startswith("#"):
                        cols=line.rstrip().split("\t")
                        genotype=cols[9].split(":")[cols[8].split(":").index("GT")]
                        rows.append([cols[0],cols[1],cols[3],cols[4],genotype])
            self.assertEqual(rows,expected,identity)
        fastp_json=json.loads(Path(record["outputs"]["step-1::trim-json"]["files"]["trim-json"]).read_text())
        self.assertGreater(fastp_json["summary"]["after_filtering"]["total_reads"],0)
        self.assertEqual(len(record["nodes"]),8)

    def test_real_portable_distinct_lanes_merge(self):
        base=APP/"examples/variant-truth"
        sources=[]
        for lane in (1,2):
            files={}
            for mate in (1,2):
                lines=(base/f"reads{mate}.fastq").read_text().splitlines(keepends=True)
                midpoint=(len(lines)//8)*4
                part=lines[:midpoint] if lane==1 else lines[midpoint:]
                path=self.folder/f"lane{lane}-{mate}.fastq"
                path.write_text("".join(part));files[f"reads{mate}"]=str(path)
            sources.append({"id":f"input-{lane}","type":"pair","label":f"Lane {lane}","files":files})
        sources.append({"id":"input-3","type":"reference","label":"Shared reference","files":{"reference":str(base/"reference.fa")}})
        nodes=[]
        for lane in (1,2):
            params=dict(self.catalog["tools"]["bwa/paired-end"]["defaults"],sample="truth",library="library",**{"read-group":f"lane{lane}","platform-unit":f"unit{lane}"})
            nodes.append({"id":f"step-{lane}","tool":"bwa/paired-end","params":params,"inputs":{"reads":[f"input-{lane}"],"reference":["input-3"]}})
        nodes.extend([
            {"id":"step-3","tool":"bam/sort","params":{},"inputs":{"alignment":["step-1::aligned"]}},
            {"id":"step-4","tool":"bam/sort","params":{},"inputs":{"alignment":["step-2::aligned"]}},
            {"id":"step-5","tool":"bam/merge","params":{},"inputs":{"alignments":["step-3::sorted","step-4::sorted"]}},
        ])
        graph={"name":"Distinct lane merge","sources":sources,"nodes":nodes}
        backend=PortableBackend(APP)
        engine=Engine(APP,self.catalog,backend)
        record=engine.execute(engine.prepare(graph,self.folder))
        self.assertTrue(record["success"],[(n["id"],n["status"],n.get("message")) for n in record["nodes"]])
        merged=record["outputs"]["step-5::merged"]["files"]["merged"]
        samtools=APP/"packs/bam-0.4.0/bin/samtools.exe"
        header=_parse_header(backend.inspect_alignment(samtools,merged,threading.Event()))
        self.assertEqual({row["ID"] for row in header["readgroups"]},{"lane1","lane2"})
        self.assertEqual(header["sort"],"coordinate")

    def test_cancel_during_preparation_creates_no_run(self):
        cancel=threading.Event();cancel.set()
        with self.assertRaises(InterruptedError):
            self.engine.prepare(self.graph,self.folder,cancel=cancel)
        self.assertEqual(list(self.folder.glob("run-*")),[])

    def test_external_alignment_format_inferred_only_when_accepted(self):
        sam=self.folder/"input.sam"
        sam.write_text("@HD\tVN:1.6\tSO:unsorted\n@SQ\tSN:chr1\tLN:4\n")
        graph={"name":"SAM preparation","sources":[{"id":"input-1","label":"Alignment","type":"bam","files":{"alignment":str(sam)}}],"nodes":[{"id":"step-1","tool":"bam/prepare","params":{},"inputs":{"alignment":["input-1"]}}]}
        self.assertTrue(self.engine.validate(graph)["ok"])
        plan=self.engine.prepare(graph,self.folder)
        self.assertEqual(plan["graph"]["sources"][0]["type"],"sam")
        graph["nodes"][0]["tool"]="bam/index"
        self.assertFalse(self.engine.validate(graph)["ok"])

    def test_backend_shutdown_terminates_registered_child_and_rejects_restart(self):
        backend=NativeBackend(APP)
        child=backend._spawn([sys.executable,"-c","import time; time.sleep(30)"],stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        self.assertIsNone(child.poll())
        backend.shutdown()
        self.assertIsNotNone(child.poll())
        self.assertEqual(backend._processes,set())
        with self.assertRaises(InterruptedError):
            backend._spawn([sys.executable,"-c","pass"])
        backend.shutdown()

    def test_fasta_preflight_cooperatively_cancels_mid_scan(self):
        from unittest.mock import patch
        cancel=threading.Event()
        class Stream:
            def __enter__(self): return self
            def __exit__(self,*args): return False
            def __iter__(self):
                yield b">chr1\n"
                yield b"ACGT\n"
                cancel.set()
                yield b"ACGT\n"
        with patch("engine.open",return_value=Stream()):
            with self.assertRaisesRegex(InterruptedError,"reference FASTA"):
                _fasta_dictionary("reference.fa",cancel)


if __name__ == "__main__":
    unittest.main(verbosity=2)
