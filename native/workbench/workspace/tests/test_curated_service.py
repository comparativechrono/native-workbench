"""Curated/results host integration; no scientific/native execution is implied."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from desktop_host import DesktopHost
from service import Workbench


class CuratedServiceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="curated-service-")
        self.root = Path(self.tmp.name)
        self.app = Workbench(self.root, catalog={"tools": {}})
        self.host = DesktopHost(self.root, app=self.app)

    def tearDown(self):
        self.host.close(grace=.1)
        self.tmp.cleanup()

    def test_catalogue_does_not_change_draft_or_install_dependencies(self):
        before = self.host.graph()
        listing = self.host.dispatch("examples/list", {})
        self.assertEqual({r["id"] for r in listing["workflows"]}, {"alignment-qc", "variant-calling"})
        self.assertTrue(all(not r["available"] for r in listing["workflows"]))
        self.assertEqual(self.host.graph(), before)
        self.assertFalse((self.root / "packs").exists())
        self.assertIsNone(self.app._pack_worker)

    def test_unavailable_or_unknown_example_preserves_both_editing_sessions(self):
        self.host._workflow_model.graph["name"] = "Preserve workflow draft"
        self.host._tool_model.graph["name"] = "Preserve standalone draft"
        before = self.host.snapshot()
        workflow = copy.deepcopy(self.host._workflow_model.graph)
        for identity in ("alignment-qc", "variant-calling", "not-a-workflow"):
            with self.subTest(identity=identity), self.assertRaises(ValueError):
                self.host.dispatch("examples/load", {"id": identity})
            self.assertEqual(self.host.snapshot(), before)
            self.assertEqual(self.host._workflow_model.graph, workflow)

    def test_explicit_load_switches_workflow_and_preserves_standalone_and_active_job(self):
        self.host._tool_model.graph["name"] = "Standalone edits"
        standalone = copy.deepcopy(self.host._tool_model.graph)
        graph = {"schema": 1, "name": "Synthetic training", "nodes": [], "sources": []}
        job = {"run_id": "frozen-job", "status": "running", "graph": {"name": "Frozen scientific work"}}
        self.app.runs["frozen-job"] = copy.deepcopy(job)
        with patch("curated_workflows.load_workflow", return_value=graph):
            state = self.host.dispatch("examples/load", {"id": "alignment-qc"})
        self.assertEqual(state["mode"], "workflow")
        self.assertEqual(self.host.graph()["name"], "Synthetic training")
        self.assertEqual(self.host._tool_model.graph, standalone)
        self.assertEqual(self.app.runs["frozen-job"], job)
        self.app.runs.clear()

    def test_strict_requests_reject_paths_graphs_and_unbounded_queries(self):
        bad = [("examples/list", {"path": str(self.root)}),
               ("examples/load", {"id": "alignment-qc", "graph": {}}),
               ("examples/load", {"id": []}),
               ("results/search", {"query": "x" * 501}),
               ("results/search", {"query": "x\n"}),
               ("results/search", {"query": [], "folder": str(self.root)}),
               ("results/summary", {"folder": str(self.root)}),
               ("results/summary", {"id": "not-recorded"})]
        before = self.host.graph()
        for method, params in bad:
            with self.subTest(method=method, params=params), self.assertRaises(ValueError):
                self.host.dispatch(method, params)
            self.assertEqual(self.host.graph(), before)

    def test_search_deduplicates_live_history_and_summary_uses_recorded_id(self):
        old = {"run_id": "same", "name": "Old name", "status": "completed", "nodes": []}
        live = {"run_id": "same", "name": "Training Alpha", "status": "failed", "nodes": []}
        other = {"run_id": "other", "name": "Training Beta", "status": "completed", "nodes": []}
        self.app.history = [old, other]
        self.app.runs["same"] = live
        rows = self.host.dispatch("results/search", {"query": "training"})["runs"]
        self.assertEqual([r["run_id"] for r in rows], ["same", "other"])
        rows = self.host.dispatch("results/search", {"query": "ALPHA failed"})["runs"]
        self.assertEqual([r["run_id"] for r in rows], ["same"])
        self.assertEqual(self.host.dispatch("results/search", {"query": "no-match"})["runs"], [])
        with patch("results_summary.build_summary", return_value={"details": "Recorded failure"}) as summary:
            result = self.host.dispatch("results/summary", {"id": "same"})
        self.assertEqual(result["details"], "Recorded failure")
        self.assertEqual(summary.call_args.args[0]["name"], "Training Alpha")
        self.assertEqual(self.app.history, [old, other])
        json.dumps(result, allow_nan=False)

    def test_failed_preparation_retains_searchable_submitted_identity_without_plan(self):
        graph = {"schema": 1, "name": "Missing input training diagnosis", "nodes": [], "sources": []}
        with patch.object(self.app.engine, "prepare", side_effect=ValueError("Input file does not exist: missing-reads.fastq")):
            started = self.app.start({"graph": graph, "output_folder": str(self.root)})
            self.app.runs[started["run_id"]]["_worker"].join(3)
        record = self.app.get_run(started["run_id"])
        self.assertEqual(record["status"], "failed")
        self.assertEqual(record["name"], graph["name"])
        self.assertEqual(record["graph"], graph)
        self.assertEqual(record["graph_status"], "submitted")
        self.assertNotIn("planSha256", record)
        self.assertEqual(len(self.app.search_results("training diagnosis failed")["runs"]), 1)
        summary = self.app.result_summary(started["run_id"])
        self.assertEqual(summary["metrics"], [])
        self.assertIn("missing-reads.fastq", summary["details"])
        self.assertTrue(summary["failures"][0]["action"])


if __name__ == "__main__":
    unittest.main()
