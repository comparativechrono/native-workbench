"""Readiness failures and claims using real local files and synthetic packs.

These are source-contract checks. No scientific executable or Windows GUI runs.
Permission/full-drive cases are injected because CI may run as an administrator.
"""
import copy
import hashlib
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import engine as engine_module
from catalog import load_catalog
from engine import Engine, pin_for
from readiness import build_readiness
from test_pack_schema import MANIFEST, metadata


class ReadinessTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="workbench readiness ")
        self.root = Path(self.tmp.name)
        self.pack = self.root / "packs/example-0.5.2"
        (self.pack / "bin").mkdir(parents=True)
        binary = b"Non-executable readiness fixture"
        (self.pack / "bin/example.exe").write_bytes(binary)
        schema = json.dumps(metadata()).encode()
        (self.pack / "workbench-schema.json").write_bytes(schema)
        (self.pack / "pack.ini").write_text(MANIFEST.format(
            binary_sha=hashlib.sha256(binary).hexdigest(), schema_sha=hashlib.sha256(schema).hexdigest()))
        self.engine = Engine(self.root, load_catalog(self.root))
        self.input = self.root / "sequences.fa"
        self.input.write_text(">chr1\nACGTACGT\n")
        self.output = self.root / "results"
        self.output.mkdir()
        self.graph = {"schema": 1, "name": "Readiness fixture", "sources": [
            {"id": "input-1", "type": "fasta-nucleotide", "files": {"sequences": str(self.input)}}],
            "nodes": [{"id": "step-1", "tool": "example/filter",
                       "pin": pin_for(self.engine.tools["example/filter"]), "params": {},
                       "inputs": {"sequences": ["input-1"]}}]}

    def tearDown(self):
        self.tmp.cleanup()

    def review(self, graph=None, output=None):
        return build_readiness(self.engine, self.graph if graph is None else graph,
                               self.output if output is None else output)

    def check(self, result, code):
        return [check for check in result["readiness"]["checks"] if check["code"] == code]

    def test_valid_destination_preserves_review_contract_and_existing_files(self):
        existing = self.output / "existing-result.txt"
        existing.write_text("Preserve this result")
        original_graph = copy.deepcopy(self.graph)
        before = self.engine.review(self.graph)
        after = self.review()
        for key, value in before.items():
            self.assertEqual(after[key], value, key)
        self.assertEqual(after["readiness"]["status"], "ready_for_preparation")
        self.assertEqual(after["readiness"]["outputFolder"]["path"], str(self.output))
        self.assertGreater(after["readiness"]["outputFolder"]["freeBytes"], 0)
        self.assertEqual(list(self.output.iterdir()), [existing])
        self.assertEqual(existing.read_text(), "Preserve this result")
        self.assertEqual(self.graph, original_graph)

    def test_missing_or_non_absolute_destination_is_never_created(self):
        missing = self.root / "missing" / "results"
        for folder in (missing, "relative-results", "", self.input, 17):
            with self.subTest(folder=folder):
                result = self.review(output=folder)
                self.assertFalse(result["valid"])
                self.assertEqual(result["readiness"]["status"], "blocked")
                self.assertEqual(self.check(result, "output_location")[0]["status"], "failed")
        self.assertFalse(missing.parent.exists())
        self.assertEqual(list(self.output.iterdir()), [])

    def test_methods_only_preview_does_not_claim_destination_was_checked(self):
        result = build_readiness(self.engine, self.graph)
        self.assertTrue(result["valid"])
        self.assertEqual(result["readiness"]["status"], "incomplete")
        self.assertEqual(self.check(result, "output_location")[0]["status"], "not_checked")
        self.assertEqual(self.check(result, "output_write"), [])
        self.assertIsNone(result["readiness"]["outputFolder"]["freeBytes"])

    def test_missing_and_wrong_scientific_input_block_readiness_without_pack_verification(self):
        for content in (None, "This is not FASTA\n"):
            with self.subTest(content=content):
                if content is None:
                    self.input.unlink(missing_ok=True)
                else:
                    self.input.write_text(content)
                with patch.object(self.engine, "_verify_manifest", wraps=self.engine._verify_manifest) as verify:
                    result = self.review()
                self.assertFalse(result["valid"])
                self.assertEqual(result["readiness"]["status"], "blocked")
                self.assertEqual(self.check(result, "graph_inputs")[0]["status"], "failed")
                verify.assert_not_called()

    def test_malformed_graphs_return_actionable_failed_review(self):
        graphs = [None, [], {"nodes": [], "sources": []},
                  {"nodes": [None], "sources": []},
                  {"nodes": [{"id": ["step-1"]}], "sources": []},
                  dict(self.graph, sources=[{"id": "input-1", "type": "fasta-nucleotide", "files": []}])]
        for graph in graphs:
            with self.subTest(graph=graph):
                result = build_readiness(self.engine, graph, self.output)
                self.assertFalse(result["valid"])
                self.assertEqual(result["readiness"]["status"], "blocked")
                self.assertTrue(result["errors"])
                self.assertIsInstance(result["methods"], str)
        self.assertEqual(list(self.output.iterdir()), [])

    def test_saved_pin_must_match_an_installed_version_without_latest_fallback(self):
        self.graph["nodes"][0]["pin"]["packVersion"] = "99.0.0"
        result = self.review()
        self.assertFalse(result["valid"])
        self.assertEqual(result["readiness"]["status"], "blocked")
        self.assertIn("exact saved tool version", " ".join(issue["message"] for issue in result["issues"]))

    def test_manifest_and_schema_tampering_block_readiness_after_catalogue_load(self):
        for filename in ("pack.ini", "workbench-schema.json"):
            with self.subTest(filename=filename):
                path = self.pack / filename
                original = path.read_bytes()
                try:
                    path.write_bytes(original + b"\n ")
                    self.assertTrue(self.engine.review(self.graph)["valid"])
                    result = self.review()
                    self.assertFalse(result["valid"])
                    self.assertEqual(self.check(result, "pack_manifests")[0]["status"], "failed")
                    self.assertEqual(result["errors"][-1]["nodeId"], "step-1")
                finally:
                    path.write_bytes(original)

    def test_read_only_destination_blocks_run_and_leaves_no_probe(self):
        with patch("readiness.tempfile.mkstemp", side_effect=PermissionError("Access denied by destination ACL")):
            result = self.review()
        self.assertFalse(result["valid"])
        self.assertEqual(self.check(result, "output_write")[0]["status"], "failed")
        self.assertEqual(list(self.output.iterdir()), [])

    def test_failed_flush_still_removes_probe(self):
        with patch("readiness.os.fsync", side_effect=OSError("Disk flush failed")):
            result = self.review()
        self.assertFalse(result["valid"])
        self.assertEqual(self.check(result, "output_write")[0]["status"], "failed")
        self.assertEqual(list(self.output.iterdir()), [])

    def test_full_destination_blocks_run_and_unavailable_capacity_remains_unknown(self):
        usage = type(shutil.disk_usage(self.output))(100, 100, 0)
        with patch("readiness.shutil.disk_usage", return_value=usage):
            result = self.review()
        self.assertFalse(result["valid"])
        self.assertEqual(result["readiness"]["outputFolder"]["freeBytes"], 0)
        self.assertEqual(self.check(result, "output_space")[0]["status"], "failed")
        with patch("readiness.shutil.disk_usage", side_effect=OSError("Volume is unavailable")):
            unknown = self.review()
        self.assertEqual(self.check(unknown, "output_space")[0]["status"], "warning")
        self.assertIsNone(unknown["readiness"]["outputFolder"]["freeBytes"])
        self.assertEqual(list(self.output.iterdir()), [])

    def test_symlink_destination_and_ancestor_are_rejected_before_writing(self):
        linked = self.root / "linked-results"
        try:
            linked.symlink_to(self.output, target_is_directory=True)
        except (OSError, NotImplementedError) as exc:
            self.skipTest("This environment cannot create a directory symlink: " + str(exc))
        nested = self.output / "nested"
        nested.mkdir()
        for destination in (linked, linked / "nested"):
            with self.subTest(destination=destination), patch("readiness._probe_write") as probe:
                result = self.review(output=destination)
                self.assertFalse(result["valid"])
                self.assertEqual(self.check(result, "output_location")[0]["status"], "failed")
                probe.assert_not_called()
        self.assertEqual(list(nested.iterdir()), [])

    def test_declared_output_path_restrictions_block_an_otherwise_writable_destination(self):
        self.engine.tools["example/filter"]["pathPolicy"] = {"asciiOnly": True, "forbiddenCharacters": [","]}
        folder = self.root / "comma,results"
        folder.mkdir()
        result = self.review(output=folder)
        self.assertFalse(result["valid"])
        self.assertEqual(self.check(result, "output_path_policy")[0]["status"], "failed")
        self.assertEqual(list(folder.iterdir()), [])

    def test_output_path_policy_uses_same_canonical_destination_as_preparation(self):
        self.engine.tools["example/filter"]["pathPolicy"] = {"asciiOnly": True, "forbiddenCharacters": [","]}
        unused = self.root / "unused,component"
        unused.mkdir()
        requested = unused / ".." / self.output.name
        result = self.review(output=requested)
        self.assertTrue(result["valid"], result["issues"])
        self.assertEqual(result["readiness"]["outputFolder"]["path"], str(self.output))
        self.assertEqual(list(self.output.iterdir()), [])
        plan = self.engine.prepare(self.graph, requested)
        self.assertEqual(Path(plan["folder"]).parent, self.output)

    def test_resolved_non_ascii_destination_cannot_bypass_a_tool_path_policy(self):
        self.engine.tools["example/filter"]["pathPolicy"] = {"asciiOnly": True}
        canonical = self.root / "résults"
        canonical.mkdir()
        # Simulate resolution of a Windows 8.3 alias. This exercises the policy
        # boundary on source CI; it does not claim native short-path coverage.
        with patch("readiness._resolved_path", return_value=canonical):
            result = self.review()
        self.assertFalse(result["valid"])
        self.assertEqual(result["readiness"]["outputFolder"]["path"], str(canonical))
        self.assertEqual(self.check(result, "output_path_policy")[0]["status"], "failed")
        self.assertEqual(list(canonical.iterdir()), [])

    def test_no_dataset_hashing_execution_or_false_scientific_completion_claims(self):
        # The signature is FASTA, but later invalid letters need the existing
        # complete scientific preflight. Readiness must not claim it passed.
        self.input.write_text(">chr1\n" + "ACGT" * 2048 + "\n>invalid\nZZZ\n")
        with patch("engine.digest_file", wraps=engine_module.digest_file) as hashes, \
                patch.object(self.engine.backend, "run", side_effect=AssertionError("No execution during readiness")):
            result = self.review()
        self.assertTrue(result["valid"])
        self.assertEqual(result["readiness"]["status"], "ready_for_preparation")
        self.assertNotIn(self.input, [Path(call.args[0]) for call in hashes.call_args_list])
        for code in ("scientific_preflight", "input_integrity", "tool_execution"):
            self.assertEqual(self.check(result, code)[0]["status"], "deferred")
        self.assertEqual(result["readiness"]["requirements"],
                         {"memoryBytes": None, "temporaryBytes": None, "outputBytes": None})
        self.assertFalse(list(self.root.glob("run-*")))
        self.assertEqual(list(self.output.iterdir()), [])

    def test_engine_without_manifest_capability_is_explicitly_incomplete(self):
        class ReviewOnly:
            def review(inner, graph):
                return self.engine.review(graph)
        result = build_readiness(ReviewOnly(), self.graph, self.output)
        self.assertTrue(result["valid"])
        self.assertEqual(result["readiness"]["status"], "incomplete")
        self.assertEqual(self.check(result, "pack_manifests")[0]["status"], "not_checked")


if __name__ == "__main__":
    unittest.main()
