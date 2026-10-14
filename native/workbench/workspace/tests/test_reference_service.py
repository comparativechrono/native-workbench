"""Reference manager lifecycle and explicit graph binding; no native GUI claim."""
import copy
import gzip
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from desktop_host import DesktopHost
from desktop_model import DesktopModel
from service import Workbench


def catalog_fixture():
    declarations = [
        ("genome", "Reference genome", "reference", "FASTA|*.fa;*.fasta;*.fna"),
        ("transcripts", "Transcriptome FASTA", "fasta-nucleotide", "FASTA|*.fa;*.fasta;*.fna"),
        ("protein", "Protein sequences", "fasta-protein", "FASTA|*.fa;*.faa;*.fasta"),
        ("annotation", "Gene annotation", "text", "GTF|*.gtf|All files|*.*"),
        ("cds", "CDS FASTA", "fasta-nucleotide", "FASTA|*.fa;*.fasta"),
        ("anything", "Any file", "file", "All files|*.*"),
        ("msa", "Aligned sequences", "msa-nucleotide", "FASTA|*.fa;*.fasta"),
        ("generic-annotation", "Annotation", "file", "GTF|*.gtf"),
        ("sequence-genome", "Genome FASTA", "fasta-nucleotide", "FASTA|*.fa;*.fasta"),
    ]
    ports = [{"id": identity, "label": label, "type": kind, "min": 1, "max": 1,
              "manifestInputs": [identity], "fields": [{"id": identity, "label": label, "type": "file",
                                                        "required": True, "filter": pattern}]}
             for identity, label, kind, pattern in declarations]
    tool = {"id": "fixture/reference", "name": "Reference fixture", "packId": "fixture",
            "packVersion": "1.0.0", "manifestSha256": "1" * 64, "ports": ports,
            "outputs": [], "params": [], "defaults": {}}
    return {"tools": {tool["id"]: tool}, "packs": []}


class Manager:
    def __init__(self, root):
        self.root = root
        self.started, self.release = threading.Event(), threading.Event()
        self.calls = []
        self.fail = False
        self.local = [{"id": "ready", "label": "Test reference", "files": [{"id": "genome"}]}]
        self.path = root / "genome.fa"
        self.path.write_text(">chr1\nACGT\n")

    def snapshot(self):
        return {"schema": 1, "providers": [], "releases": [116], "species": [],
                "discovery": None, "local": copy.deepcopy(self.local), "notice": "Local records"}

    def _work(self, action, args, cancel, event):
        self.calls.append((action, args))
        event({"bytes": 5, "total": 20, "message": "Working"})
        self.started.set()
        while not self.release.wait(.01):
            if cancel.is_set():
                raise InterruptedError("Reference operation cancelled.")
        if self.fail:
            raise ValueError("Reference checksum mismatch")
        return self.snapshot()

    def search(self, release, query, *, cancel, event):
        return self._work("search", (release, query), cancel, event)

    def discover(self, release, species_id, *, cancel, event):
        return self._work("discover", (release, species_id), cancel, event)

    def download(self, selection_id, file_ids, destination, *, cancel, event):
        return self._work("download", (selection_id, file_ids, destination), cancel, event)

    def resolve_file(self, record_id, file_id):
        if record_id != "ready" or file_id != "genome" or not self.path.is_file():
            raise ValueError("Reference file is unavailable")
        return {"path": str(self.path), "filename": self.path.name, "kind": "genome"}

    def record_folder(self, record_id):
        self.resolve_file(record_id, "genome")
        return str(self.root)


class ReferenceServiceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.app = Workbench(self.root, catalog=catalog_fixture())
        self.manager = Manager(self.root)
        self.app._reference_manager = self.manager
        self.model = DesktopModel(self.root, self.app.catalog)
        self.host = DesktopHost(self.root, app=self.app, model=self.model)

    def tearDown(self):
        self.manager.release.set()
        self.host.close(grace=2)
        self.tmp.cleanup()

    def start(self, action="search", params=None):
        result = self.host.dispatch("references/" + action, params or {"query": "yeast"})
        self.assertTrue(self.manager.started.wait(2))
        return result

    def join(self):
        self.app._reference_worker.join(2)
        self.assertFalse(self.app._reference_worker.is_alive())
        return self.host.dispatch("references/status", {})

    def test_local_state_is_offline_and_does_not_mutate_graph(self):
        before = copy.deepcopy(self.model.graph)
        self.assertIsNone(self.app._pack_manager)
        with patch("urllib.request.urlopen", side_effect=AssertionError("Unexpected network")):
            self.assertEqual(self.host.dispatch("references/list", {})["local"], self.manager.local)
            self.assertEqual(self.host.dispatch("references/open", {"record_id": "ready"}), {"path": str(self.root)})
            self.host.dispatch("state", {})
        self.assertFalse(self.manager.calls)
        self.assertEqual(self.model.graph, before)

    def test_background_progress_serializes_graph_runs_and_pack_operations(self):
        self.start()
        status = self.host.dispatch("references/status", {})
        self.assertTrue(status["operation"]["active"])
        self.assertEqual(status["operation"]["bytes"], 5)
        self.assertTrue(self.host.snapshot()["changing_references"])
        for call in (lambda: self.app.ensure_editable(),
                     lambda: self.host.dispatch("model", {"action": "add_tool", "payload": {"toolId": "fixture/reference"}}),
                     lambda: self.app.start({"output_folder": str(self.root)}),
                     lambda: self.host.dispatch("packs/refresh", {}),
                     lambda: self.host.dispatch("references/search", {"query": "human"})):
            with self.assertRaisesRegex(ValueError, "reference operation"):
                call()
        self.host.dispatch("references/cancel", {})
        self.assertEqual(self.join()["operation"]["status"], "cancelled")
        self.app.ensure_editable()

    def test_success_preserves_discovery_and_download_arguments(self):
        self.manager.release.set()
        self.start("discover", {"species_id": "saccharomyces_cerevisiae", "release": 116})
        self.assertEqual(self.join()["operation"]["status"], "completed")
        self.start("download", {"selection_id": "discovery1", "file_ids": ["genome", "annotation"],
                                "destination": str(self.root)})
        status = self.join()
        self.assertEqual(self.manager.calls[-1], ("download", ("discovery1", ["genome", "annotation"], str(self.root))))
        self.assertTrue(status["operation"]["success"])
        self.assertFalse(status["changing_references"])

    def test_failure_is_not_completed_and_shutdown_joins_active_worker(self):
        self.manager.fail = True
        self.manager.release.set()
        self.start()
        status = self.join()
        self.assertEqual(status["operation"]["status"], "failed")
        self.assertIn("checksum", status["operation"]["message"])
        self.manager.release.clear()
        self.start()
        self.assertTrue(self.host.close(grace=2))
        self.assertFalse(self.app._reference_worker.is_alive())
        self.assertEqual(self.app._reference_operation["status"], "cancelled")

    def test_analysis_and_pack_operations_prevent_reference_work(self):
        self.app._changing_packs = True
        with self.assertRaisesRegex(ValueError, "pack operation"):
            self.host.dispatch("references/search", {"query": "human"})
        self.app._changing_packs = False
        self.app.runs["active"] = {"run_id": "active", "status": "running"}
        try:
            with self.assertRaisesRegex(ValueError, "active analysis"):
                self.host.dispatch("references/search", {"query": "human"})
        finally:
            self.app.runs.clear()
        self.assertFalse(self.manager.calls)

    def test_invalid_requests_never_start_a_download_or_accept_urls(self):
        requests = [("search", {"release": True}), ("search", {"query": "x\n"}),
                    ("search", {"url": "https://arbitrary.example/"}),
                    ("discover", {"species_id": "../../data"}),
                    ("download", {"selection_id": "x", "file_ids": ["x", "x"], "destination": str(self.root)}),
                    ("download", {"selection_id": "x", "file_ids": ["https://arbitrary.example"], "destination": str(self.root)}),
                    ("download", {"selection_id": "x", "file_ids": ["x"], "destination": "relative"}),
                    ("download", {"selection_id": "x", "file_ids": ["x"], "destination": str(self.root / "missing-custom-destination")}),
                    ("status", {"refresh": True}), ("open", {"record_id": "ready", "path": str(self.root)})]
        for action, params in requests:
            with self.subTest(action=action, params=params), self.assertRaises(ValueError):
                self.host.dispatch("references/" + action, params)
        self.assertFalse(self.manager.calls)
        self.assertFalse((self.root / "missing-custom-destination").exists())

    def test_explicit_use_binds_only_selected_field_and_is_undoable(self):
        self.host.dispatch("model", {"action": "add_tool", "payload": {"toolId": "fixture/reference"}})
        request = {"record_id": "ready", "file_id": "genome"}
        targets = self.host.dispatch("references/targets", request)["targets"]
        self.assertEqual({item["field_id"] for item in targets}, {"genome", "sequence-genome"})
        before = copy.deepcopy(self.model.graph)
        chosen = targets[0]
        result = self.host.dispatch("references/use", dict(request, source_id=chosen["source_id"], field_id=chosen["field_id"]))
        self.assertIn("model", result)
        self.assertEqual(self.model.graph["sources"][0]["files"], {"genome": str(self.manager.path)})
        self.assertEqual(self.model.graph["sources"][1:], before["sources"][1:])
        self.assertEqual(self.model.graph["nodes"], before["nodes"])
        self.model.dispatch("undo")
        self.assertEqual(self.model.graph, before)

    def test_missing_reference_stale_target_and_client_provenance_are_rejected(self):
        request = {"record_id": "ready", "file_id": "genome"}
        self.assertEqual(self.host.dispatch("references/targets", request)["targets"], [])
        with self.assertRaisesRegex(ValueError, "no longer matches"):
            self.host.dispatch("references/use", dict(request, source_id="input-1", field_id="genome"))
        with self.assertRaises(ValueError):
            self.host.dispatch("references/use", dict(request, source_id="input-1", field_id="genome", path="fake.fa"))
        self.manager.path.unlink()
        with self.assertRaisesRegex(ValueError, "unavailable"):
            self.host.dispatch("references/targets", request)

    def test_resource_type_filters_exclude_cds_alignments_and_wildcard_only(self):
        self.model.dispatch("add_tool", {"toolId": "fixture/reference"})
        expected = {"genome": {"genome", "sequence-genome"}, "cdna": {"transcripts"},
                    "ncrna": {"transcripts"}, "protein": {"protein"},
                    "annotation": {"annotation", "generic-annotation"}}
        for kind, fields in expected.items():
            resource = {"kind": kind, "filename": "reference.gtf" if kind == "annotation" else "reference.fa"}
            self.assertEqual({t["field_id"] for t in self.model.reference_targets(resource)}, fields)
        # A user's source label is not a declaration of scientific file type.
        self.model.graph["sources"][1]["label"] = "Genome alignment CDS"
        self.assertEqual({t["field_id"] for t in self.model.reference_targets({"kind": "cdna", "filename": "reference.fa"})}, {"transcripts"})
        self.model.graph["nodes"][0]["inputs"]["genome"] = []
        resource = {"kind": "genome", "filename": "reference.fa"}
        self.assertEqual({t["field_id"] for t in self.model.reference_targets(resource)}, {"sequence-genome"})

    def test_real_manager_provider_and_host_complete_local_binding(self):
        # Exercise the actual boundaries with a deterministic HTTPS fixture;
        # scientific reference contents and the network are deliberately tiny.
        import reference_provider as provider
        from reference_manager import ReferenceManager, _bsd_update
        from test_reference_provider import fixture
        transport, folders, names, species = fixture()
        transport.add(provider.BASE_URL, '<a href="release-116/">116</a>')
        plain = b">chr1\nACGTACGT\n"
        compressed = gzip.compress(plain, mtime=0)
        transport.add(folders["dna"] + names["dna"], compressed)
        transport.add(folders["dna"] + names["dna"], b"", method="HEAD",
                      headers={"Content-Length": str(len(compressed))})
        transport.add(folders["dna"] + "CHECKSUMS", f'{_bsd_update(0, compressed)} 1 {names["dna"]}\n')
        self.app._reference_manager = ReferenceManager(self.root, provider.EnsemblArchiveProvider(transport))
        # Use the same published path as the native UI. Windows may resolve
        # the application's root from a short 8.3 spelling to a long spelling.
        destination = Path(self.app._reference_manager.snapshot()["default_destination"])
        self.assertEqual(destination.resolve(), (self.app.data / "references").resolve())
        self.assertFalse(destination.exists())
        self.assertEqual(self.host.dispatch("references/list", {})["local"], [])
        self.assertFalse(transport.calls)
        self.assertFalse(destination.exists())

        def complete(action, request):
            self.host.dispatch("references/" + action, request)
            result = self.join()
            self.assertEqual(result["operation"]["status"], "completed", result["operation"])
            return result

        complete("search", {"release": 116, "query": "saccharomyces"})
        discovery = complete("discover", {"release": 116, "species_id": species})["discovery"]
        result = complete("download", {"selection_id": discovery["selection_id"], "file_ids": ["genome"],
                                       "destination": str(destination)})
        record = result["local"][0]
        self.assertEqual(record["status"], "ready")
        self.assertEqual(Path(record["files"][0]["path"]).read_bytes(), plain)
        self.model.dispatch("add_tool", {"toolId": "fixture/reference"})
        identities = {"record_id": record["id"], "file_id": "genome"}
        target = self.host.dispatch("references/targets", identities)["targets"][0]
        self.host.dispatch("references/use", dict(identities, source_id=target["source_id"], field_id=target["field_id"]))
        self.assertEqual(self.model.graph["sources"][0]["files"]["genome"], record["files"][0]["path"])
        count = len(transport.calls)
        self.assertEqual(self.host.dispatch("references/open", {"record_id": record["id"]})["path"], record["folder"])
        self.host.dispatch("references/list", {})
        self.assertEqual(len(transport.calls), count)


if __name__ == "__main__":
    unittest.main()
