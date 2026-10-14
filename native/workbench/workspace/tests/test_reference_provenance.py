"""Frozen reference evidence survives library changes without trusting graphs."""
import copy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from catalog import load_catalog
from engine import Engine
from reference_provenance import collect_references, methods_text, used_paths
from test_pack_versions import make_pack, RecordingBackend


class ReferenceProvenanceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="reference provenance ")
        self.root = Path(self.tmp.name)
        make_pack(self.root, "1.0.0")
        self.input = self.root / "genome.fa"
        self.input.write_bytes(b">chr1\nACGT\n")
        self.path = str(self.input.resolve())
        self.hash = hashlib.sha256(self.input.read_bytes()).hexdigest()
        self.reference = {"provider": "ensembl-archive", "release": 116,
                          "species": {"id": "fixture_species", "name": "Fixture species"},
                          "assembly": "Assembly1", "assembly_accession": "GCA_000000001.1",
                          "downloaded_at": "2026-10-05T10:00:00Z", "receipt_sha256": "a" * 64,
                          "file": {"path": self.path, "filename": "genome.fa", "kind": "genome",
                                   "label": "Genome FASTA", "sha256": self.hash,
                                   "source_url": "https://ftp.ensembl.org/pub/release-116/fixture.fa.gz"}}
        self.references = {self.path: self.reference}
        self.graph = {"schema": 1, "name": "Reference evidence fixture", "sources": [
            {"id": "input-1", "type": "file", "files": {"source": self.path}}], "nodes": [
            {"id": "step-1", "tool": "example/process", "params": {},
             "inputs": {"source": ["input-1"]}}]}
        self.engine = Engine(self.root, load_catalog(self.root), backend=RecordingBackend())

    def tearDown(self):
        self.tmp.cleanup()

    def test_preview_names_reference_but_does_not_claim_a_completed_hash_check(self):
        with patch("engine.collect_references", return_value=self.references) as lookup:
            methods = self.engine.methods(self.graph)
        self.assertIn("Ensembl archive, release 116", methods)
        self.assertIn("Assembly1 (GCA_000000001.1)", methods)
        self.assertIn("will be checked", methods)
        self.assertNotIn("were checked", methods)
        lookup.assert_called_once_with(self.root.resolve(), {self.path})

    def test_frozen_hash_receipt_and_methods_survive_library_removal(self):
        def lookup(root, paths, evidence=None):
            self.assertEqual(evidence[self.path]["sha256"], self.hash)
            return copy.deepcopy(self.references)
        with patch("engine.collect_references", side_effect=lookup):
            plan = self.engine.prepare(self.graph, self.root)
        self.assertEqual(plan["inputs"][self.path]["reference"], self.reference)
        frozen = json.loads((Path(plan["folder"]) / "reference-provenance.json").read_text())
        self.assertEqual(frozen["inputs"], self.references)
        self.assertIn("were checked", plan["methods"])
        with patch("engine.collect_references", side_effect=AssertionError("No library lookup during execution")):
            result = self.engine.execute(plan)
        self.assertTrue(result["success"], result)
        self.assertEqual(result["references"], self.references)
        self.assertIn("Assembly1", result["methods"])
        self.assertIn("Ensembl archive", (Path(plan["folder"]) / "methods-completed.txt").read_text())

    def test_ncbi_snapshot_annotation_and_accession_survive_frozen_run(self):
        self.reference.update(provider='ncbi-refseq', provider_name='NCBI RefSeq assembly lookup',
                              release='GCF_000146045.2', assembly='R64', assembly_accession='GCF_000146045.2')
        self.reference['file']['annotation'] = {'name': 'SGD R64-5-1', 'provider': 'SGD', 'release_date': '2026-07-10'}
        self.reference['file']['source_url'] = 'https://ftp.ncbi.nlm.nih.gov/genomes/all/GCF/000/146/045/GCF_000146045.2_R64/GCF_000146045.2_R64_genomic.fna.gz'
        with patch('engine.collect_references', return_value=self.references):
            plan = self.engine.prepare(self.graph, self.root)
        frozen = json.loads((Path(plan['folder']) / 'reference-provenance.json').read_text())
        self.assertEqual(frozen['inputs'][self.path]['file']['annotation'], self.reference['file']['annotation'])
        with patch('engine.collect_references', side_effect=AssertionError('No new provider or library lookup')):
            result = self.engine.execute(plan)
        self.assertTrue(result['success'])
        for text in (plan['methods'], result['methods'], (Path(plan['folder']) / 'methods-completed.txt').read_text()):
            self.assertIn('accession GCF_000146045.2', text)
            self.assertIn('Observed annotation: SGD R64-5-1; provider SGD; release date 2026-07-10', text)
            self.assertIn('retrieved snapshot', text)
            self.assertIn('may change without a new assembly accession', text)
            self.assertNotIn('release GCF_000146045.2', text)
        self.assertEqual(result['references'][self.path]['file']['annotation'], self.reference['file']['annotation'])

    def test_known_changed_reference_prevents_run_creation(self):
        with patch("engine.collect_references", side_effect=ValueError("Reference file has changed")):
            with self.assertRaisesRegex(ValueError, "has changed"):
                self.engine.prepare(self.graph, self.root)
        self.assertFalse(list(self.root.glob("run-*")))

    def test_failed_step_does_not_claim_reference_in_completed_methods(self):
        text = self.engine.methods(self.graph, completed=True, statuses={"step-1": "failed"}, references=self.references)
        self.assertNotIn("Reference data:", text)
        self.assertEqual(used_paths(self.graph, {"step-1": "failed"}), set())

    def test_client_provenance_is_not_used_and_unregistered_files_remain_valid(self):
        self.graph["sources"][0]["reference_provenance"] = {"assembly": "Untrusted assertion"}
        self.assertEqual(collect_references(self.root, [self.path]), {})
        plan = self.engine.prepare(self.graph, self.root)
        self.assertEqual(plan["references"], {})
        self.assertNotIn("Untrusted assertion", plan["methods"])
        self.assertFalse((Path(plan["folder"]) / "reference-provenance.json").exists())


if __name__ == "__main__":
    unittest.main()
