"""Offline portable projects with synthetic inputs; no scientific executable runs."""
import copy
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile
from urllib.parse import unquote, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from catalog import load_catalog
from engine import Engine, pin_for
import project_manager
from project_manager import ProjectManager
from test_pack_schema import MANIFEST, metadata


class ProjectTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="workbench portable project ")
        self.root = Path(self.temp.name)
        self.app = self.root / "app"
        self.pack = self.app / "packs/example-0.5.2"
        (self.pack / "bin").mkdir(parents=True)
        binary = b"Non executable fixture bytes"
        schema = json.dumps(metadata()).encode()
        (self.pack / "bin/example.exe").write_bytes(binary)
        (self.pack / "workbench-schema.json").write_bytes(schema)
        (self.pack / "pack.ini").write_text(MANIFEST.format(binary_sha=hashlib.sha256(binary).hexdigest(), schema_sha=hashlib.sha256(schema).hexdigest()), encoding="utf-8")
        self.engine = Engine(self.app, load_catalog(self.app))
        self.manager = ProjectManager(self.engine)
        self.input = self.root / "original input.fa"
        self.input.write_text(">chr1\nACGTACGTACGTACGT\n", encoding="utf-8")
        self.graph = {"schema": 1, "name": "Portable sequence filter", "sources": [
            {"id": "input-1", "type": "fasta-nucleotide", "files": {"sequences": str(self.input)}}],
            "nodes": [{"id": "step-1", "tool": "example/filter", "pin": pin_for(self.engine.tools["example/filter"]),
                       "params": {"minimum": "10"}, "inputs": {"sequences": ["input-1"]}}]}
        self.bundle = self.root / "portable.nwproject.zip"

    def tearDown(self):
        self.temp.cleanup()

    def export(self, included=True):
        preview = self.manager.export_preview(self.graph, include_data=included, sample_metadata={"sampleId": "sample1", "file": str(self.input), "condition": "control"})
        result = self.manager.export(preview, self.bundle)
        return preview, result

    def mutate(self, transform=None, extras=None):
        with zipfile.ZipFile(self.bundle) as source:
            data = {item.filename: source.read(item) for item in source.infolist()}
        if transform:
            transform(data)
        other = self.root / "malformed.zip"
        with zipfile.ZipFile(other, "w") as target:
            for name, raw in data.items():
                target.writestr(name, raw)
            for name, raw in extras or []:
                target.writestr(name, raw)
        return other

    def test_roundtrip_copies_exact_inputs_and_pins_without_bundling_packs(self):
        original = copy.deepcopy(self.graph)
        preview, exported = self.export()
        self.assertEqual(self.graph, original)
        self.assertEqual(exported["sha256"], hashlib.sha256(self.bundle.read_bytes()).hexdigest())
        with zipfile.ZipFile(self.bundle) as archive:
            self.assertEqual(set(archive.namelist()), {"project.json", "workflow.cwl", "data/data-000001/original input.fa"})
            combined = archive.read("project.json") + archive.read("workflow.cwl")
            self.assertNotIn(str(self.input).encode(), combined)
            self.assertNotIn(str(self.app).encode(), combined)
        inspected = self.manager.preview_import(self.bundle)
        self.assertTrue(inspected["summary"]["ready"], inspected["summary"])
        imported = self.manager.import_project(inspected, self.root / "imported")
        copied = Path(imported["graph"]["sources"][0]["files"]["sequences"])
        self.assertEqual(copied.read_bytes(), self.input.read_bytes())
        self.assertNotEqual(copied, self.input)
        self.assertEqual(imported["graph"]["nodes"][0]["pin"], self.graph["nodes"][0]["pin"])
        self.assertEqual(imported["sampleMetadata"]["file"], "nw-input:data-000001")
        self.assertFalse(preview["manifest"]["linuxProfile"]["scientificEquivalenceValidated"])

    def test_reopen_after_moving_project_and_original_inputs_removed(self):
        self.export()
        imported = self.manager.import_project(self.manager.preview_import(self.bundle), self.root / "original project folder")
        moved = self.root / "moved project folder"
        shutil.move(imported["folder"], moved)
        self.input.unlink()
        reopened = self.manager.open_project(moved)
        path = Path(reopened["graph"]["sources"][0]["files"]["sequences"])
        self.assertTrue(path.is_relative_to(moved))
        self.assertTrue(self.engine.validate(reopened["graph"])["ok"])

    def test_missing_data_requires_explicit_byte_identical_resolution(self):
        self.export(False)
        inspected = self.manager.preview_import(self.bundle)
        self.assertFalse(inspected["summary"]["ready"])
        self.assertEqual(inspected["summary"]["dependencies"][0]["status"], "missing")
        with self.assertRaisesRegex(ValueError, "Resolve every"):
            self.manager.import_project(inspected, self.root / "no import")
        self.assertFalse((self.root / "no import").exists())
        mapped = self.root / "elsewhere.fa"
        mapped.write_bytes(self.input.read_bytes())
        self.input.unlink()
        resolved = self.manager.preview_import(self.bundle, {"data-000001": str(mapped)})
        self.assertTrue(resolved["summary"]["ready"])
        result = self.manager.import_project(resolved, self.root / "resolved")
        mapped.unlink()
        self.assertTrue(self.engine.validate(result["graph"])["ok"])

    def test_wrong_mapped_bytes_never_substitute_original_identity(self):
        self.export(False)
        other = self.root / "wrong.fa"
        other.write_text(">chr1\nTTTTTTTTTTTTTTTT\n", encoding="utf-8")
        preview = self.manager.preview_import(self.bundle, {"data-000001": str(other)})
        self.assertFalse(preview["summary"]["ready"])
        self.assertEqual(preview["summary"]["dependencies"][0]["status"], "mismatch")

    def test_input_changed_after_export_preview_fails_without_archive(self):
        preview = self.manager.export_preview(self.graph, include_data=True)
        self.input.write_text(">chr1\nAAAAAAAAAAAAAAAA\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "bytes do not match"):
            self.manager.export(preview, self.bundle)
        self.assertFalse(self.bundle.exists())
        self.assertEqual(list(self.root.glob(".nw-project-*")), [])

    def test_mapped_input_changed_after_preview_blocks_import_and_preserves_source(self):
        self.export(False)
        preview = self.manager.preview_import(self.bundle, {"data-000001": str(self.input)})
        self.input.write_text(">changed\nACGT\n", encoding="utf-8")
        with self.assertRaises(ValueError):
            self.manager.import_project(preview, self.root / "changed")
        self.assertFalse((self.root / "changed").exists())
        self.assertIn("changed", self.input.read_text(encoding="utf-8"))

    def test_exact_missing_and_tampered_pack_reported_without_repinning(self):
        self.export()
        (self.pack / "bin/example.exe").write_bytes(b"changed")
        inspected = self.manager.preview_import(self.bundle)
        self.assertFalse(inspected["summary"]["ready"])
        self.assertEqual(inspected["summary"]["packs"][0]["status"], "missing-or-incompatible")
        no_packs = self.root / "different machine"
        no_packs.mkdir()
        manager = ProjectManager(Engine(no_packs, load_catalog(no_packs)))
        missing = manager.preview_import(self.bundle)
        self.assertFalse(missing["summary"]["ready"])
        self.assertEqual(missing["manifest"]["graph"]["nodes"][0]["pin"], self.graph["nodes"][0]["pin"])

    def test_changed_archive_after_preview_rejected(self):
        self.export()
        preview = self.manager.preview_import(self.bundle)
        with self.bundle.open("ab") as stream:
            stream.write(b"changed archive")
        with self.assertRaisesRegex(ValueError, "changed since preview"):
            self.manager.import_project(preview, self.root / "tampered")

    def test_tampered_member_rejected_even_with_valid_zip_crc(self):
        self.export()
        changed = self.mutate(lambda data: data.__setitem__("data/data-000001/original input.fa", b"corrupted"))
        with self.assertRaisesRegex(ValueError, "size mismatch|checksum mismatch"):
            self.manager.preview_import(changed)

    def test_inventory_missing_and_undeclared_members_fail(self):
        self.export()
        changed = self.mutate(lambda data: data.pop("workflow.cwl"))
        with self.assertRaisesRegex(ValueError, "inventory"):
            self.manager.preview_import(changed)
        changed = self.mutate(extras=[("extra.txt", b"unexpected")])
        with self.assertRaisesRegex(ValueError, "inventory"):
            self.manager.preview_import(changed)

    def test_traversal_absolute_backslash_reserved_and_case_collision_rejected(self):
        self.export()
        for name in ("../escaped", "/absolute", "C:/evil", "data\\evil", "CON.txt", "data/file. ", "PROJECT.JSON"):
            with self.subTest(name=name):
                changed = self.mutate(extras=[(name, b"bad")])
                with self.assertRaises(ValueError):
                    self.manager.preview_import(changed)
        self.assertFalse((self.root / "escaped").exists())

    def test_duplicate_and_symlink_members_rejected(self):
        self.export()
        changed = self.mutate(extras=[("workflow.cwl", b"duplicate")])
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            self.manager.preview_import(changed)
        link = zipfile.ZipInfo("link")
        link.create_system = 3
        link.external_attr = (stat.S_IFLNK | 0o777) << 16
        changed = self.mutate(extras=[(link, b"../outside")])
        with self.assertRaisesRegex(ValueError, "ordinary"):
            self.manager.preview_import(changed)

    def test_bounded_member_count_expansion_and_metadata(self):
        self.export()
        with patch.object(project_manager, "MAX_MEMBERS", 2), self.assertRaisesRegex(ValueError, "member limit"):
            self.manager.preview_import(self.bundle)
        with patch.object(project_manager, "MAX_FILE_BYTES", 8), self.assertRaisesRegex(ValueError, "size|limit"):
            self.manager.preview_import(self.bundle)
        with patch.object(project_manager, "MAX_MANIFEST", 8), self.assertRaisesRegex(ValueError, "size|oversized"):
            self.manager.preview_import(self.bundle)
        huge = self.root / "bomb.zip"
        with zipfile.ZipFile(huge, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("bomb", b"0" * 2_000_000)
        with self.assertRaisesRegex(ValueError, "compression limits"):
            self.manager.preview_import(huge)

    def test_duplicate_json_fields_and_inconsistent_data_pin_fail(self):
        self.export()
        changed = self.mutate(lambda data: data.__setitem__("project.json", b'{"schema":1,"schema":1}'))
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            self.manager.preview_import(changed)
        def change(data):
            document = json.loads(data["project.json"])
            document["dependencies"][0]["sha256"] = "f" * 64
            data["project.json"] = json.dumps(document).encode()
        changed = self.mutate(change)
        with self.assertRaisesRegex(ValueError, "inventory disagrees"):
            self.manager.preview_import(changed)

    def test_existing_archive_and_import_folder_preserved(self):
        preview, _ = self.export()
        original = self.bundle.read_bytes()
        with self.assertRaisesRegex(ValueError, "existing files"):
            self.manager.export(preview, self.bundle)
        self.assertEqual(self.bundle.read_bytes(), original)
        folder = self.root / "existing"
        folder.mkdir()
        (folder / "keep.txt").write_text("keep", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "existing files"):
            self.manager.import_project(self.manager.preview_import(self.bundle), folder)
        self.assertEqual((folder / "keep.txt").read_text(encoding="utf-8"), "keep")

    def test_unsupported_executable_data_and_symlink_inputs_rejected(self):
        # Use metrics/report input to avoid scientific-format validation masking
        # the portable-data executable guard.
        first = self.root / "one.txt"
        second = self.root / "two.txt"
        first.write_bytes(b"MZexecutable")
        second.write_text("metric\t2\n", encoding="utf-8")
        graph = self.report_graph(first, second)
        with self.assertRaisesRegex(ValueError, "Executable"):
            self.manager.export_preview(graph, include_data=True)
        first.write_text("metric\t1\n", encoding="utf-8")
        link = self.root / "linked.txt"
        try:
            link.symlink_to(first)
        except OSError:
            self.skipTest("Creating symbolic links requires a privilege unavailable on this host.")
        graph["sources"][0]["files"]["metrics"] = str(link)
        with self.assertRaises(ValueError):
            self.manager.export_preview(graph, include_data=True)

    def report_graph(self, first, second):
        return {"name": "Portable reports", "sources": [
            {"id": "input-1", "type": "metrics", "files": {"metrics": str(first)}},
            {"id": "input-2", "type": "metrics", "files": {"metrics": str(second)}}],
            "nodes": [{"id": "step-1", "tool": "builtin/report", "params": {}, "inputs": {"metrics": ["input-1", "input-2"]}}]}

    def test_local_project_tamper_or_unlisted_file_blocks_reopen(self):
        self.export()
        imported = self.manager.import_project(self.manager.preview_import(self.bundle), self.root / "imported")
        folder = Path(imported["folder"])
        (folder / "extra.txt").write_text("unexpected", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "unlisted"):
            self.manager.open_project(folder)
        (folder / "extra.txt").unlink()
        Path(imported["graph"]["sources"][0]["files"]["sequences"]).write_bytes(b"changed")
        with self.assertRaisesRegex(ValueError, "changed"):
            self.manager.open_project(folder)

    def test_offline_import_does_not_execute_or_download(self):
        self.export()
        with patch("subprocess.Popen", side_effect=AssertionError("No execution")), patch("socket.socket", side_effect=AssertionError("No network")):
            self.manager.import_project(self.manager.preview_import(self.bundle), self.root / "offline")

    def test_cwl_relative_data_and_required_pack_bindings(self):
        preview, _ = self.export(False)
        workflow = preview["cwl"]
        main = workflow["$graph"][0]
        data = [item for item in main["inputs"].values() if "nw:source" in item]
        self.assertEqual(data[0]["default"]["location"], "data/data-000001/original%20input.fa")
        packs = [item for item in main["inputs"].values() if item.get("type") == "Directory"]
        self.assertEqual(len(packs), 1)
        self.assertNotIn("default", packs[0])
        self.assertEqual(main["nw:execution"]["status"], "planned")
        self.assertEqual(main["nw:planSha256"], "")

    def test_explicit_subset_only_bundles_selected_dependencies(self):
        first, second = self.root / "one.txt", self.root / "two.txt"
        first.write_text("metric\t1\n", encoding="utf-8")
        second.write_text("metric\t2\n", encoding="utf-8")
        preview = self.manager.export_preview(self.report_graph(first, second), include_data=["data-000002"])
        self.assertEqual([item["included"] for item in preview["manifest"]["dependencies"]], [False, True])
        self.manager.export(preview, self.bundle)
        self.assertFalse(self.manager.preview_import(self.bundle)["summary"]["ready"])

    def test_generic_descriptor_input_requires_explicit_resource_contract(self):
        graph = self.report_graph(self.input, self.input)
        graph["sources"][0]["type"] = "file"
        # A future pack can explicitly accept generic files; portable closure
        # still cannot infer a databaseRoot from arbitrary descriptor contents.
        with patch.object(self.engine, "validate", return_value={"ok": True, "errors": []}):
            with self.assertRaisesRegex(ValueError, "portable resource contract"):
                self.manager.export_preview(graph, include_data=True)

    def test_project_metadata_rebinds_historical_context_after_relocation(self):
        self.export()
        imported = self.manager.import_project(self.manager.preview_import(self.bundle), self.root / "project")
        moved = self.root / "moved"
        shutil.move(imported["folder"], moved)
        reopened = self.manager.open_project(moved)
        context = reopened["projectMetadata"]
        self.assertTrue(context["referencesAreHistorical"])
        self.assertEqual(context["manifestSha256"], reopened["manifestSha256"])
        self.assertTrue(Path(context["dependencies"][0]["boundPath"]).is_relative_to(moved))
        again = self.manager.export_preview(reopened["graph"], include_data=True, sample_metadata=reopened["sampleMetadata"])
        self.assertEqual(again["manifest"]["sampleMetadata"], reopened["sampleMetadata"])

    def test_historical_reference_identity_survives_import_reopen_and_reexport(self):
        receipt = {"provider": "ensembl-archive", "release": 116, "assembly": "fixture", "receipt_path": "/private/library/receipt.json",
                   "file": {"path": str(self.input), "sha256": hashlib.sha256(self.input.read_bytes()).hexdigest(), "kind": "genome"}}
        preview = self.manager.export_preview(self.graph, include_data=True, reference_metadata={str(self.input): receipt})
        self.manager.export(preview, self.bundle)
        imported = self.manager.import_project(self.manager.preview_import(self.bundle), self.root / "project")
        again = self.manager.export_preview(imported["graph"], include_data=True, project_metadata=imported["projectMetadata"])
        reference = again["manifest"]["dependencies"][0]["references"]
        self.assertEqual(reference["assembly"], "fixture")
        self.assertNotIn("receipt_path", reference)
        self.assertNotIn("path", reference["file"])
        self.assertFalse((self.app / "user-data/references/library.json").exists())

    def test_explicit_path_aliases_preserve_sample_and_reference_identity(self):
        # Ordinary lexical aliases exercise the same raw-vs-resolved mismatch
        # as Windows' default TEMP path containing RUNNER~1. No links or guessed
        # file names are involved in mapping the historical identity.
        alias_folder = self.root / "existing alias folder"
        alias_folder.mkdir()
        alias = str(alias_folder / ".." / self.input.name)
        self.assertNotEqual(alias, str(self.input.resolve()))
        self.graph["sources"][0]["files"]["sequences"] = alias
        receipt = {"assembly": "alias-fixture", "file": {"path": alias, "sha256": hashlib.sha256(self.input.read_bytes()).hexdigest()}}
        preview = self.manager.export_preview(self.graph, include_data=True,
                    sample_metadata={"raw": alias, "canonical": str(self.input.resolve())},
                    reference_metadata={alias: receipt})
        self.assertEqual(preview["manifest"]["sampleMetadata"], {"raw": "nw-input:data-000001", "canonical": "nw-input:data-000001"})
        self.assertEqual(preview["manifest"]["dependencies"][0]["references"]["assembly"], "alias-fixture")
        self.manager.export(preview, self.bundle)
        imported = self.manager.import_project(self.manager.preview_import(self.bundle), alias_folder / ".." / "aliased project")
        again = self.manager.export_preview(imported["graph"], project_metadata=imported["projectMetadata"])
        self.assertEqual(again["manifest"]["dependencies"][0]["references"]["assembly"], "alias-fixture")
        self.assertNotIn(alias, json.dumps(preview["manifest"]))

    def test_duplicate_reference_aliases_rejected_and_wrong_alias_hash_not_accepted(self):
        alias_folder = self.root / "alias folder"
        alias_folder.mkdir()
        alias = str(alias_folder / ".." / self.input.name)
        receipt = {"assembly": "fixture", "file": {"sha256": hashlib.sha256(self.input.read_bytes()).hexdigest()}}
        with self.assertRaisesRegex(ValueError, "duplicate aliases"):
            self.manager.export_preview(self.graph, reference_metadata={str(self.input): receipt, alias: receipt})
        wrong = {"assembly": "fixture", "file": {"sha256": "f" * 64}}
        with self.assertRaisesRegex(ValueError, "differs from the selected input bytes"):
            self.manager.export_preview(self.graph, reference_metadata={alias: wrong})

    def test_import_rejects_generic_descriptor_even_if_graph_and_inventory_agree(self):
        self.export()
        def change(data):
            document = json.loads(data["project.json"])
            document["graph"]["sources"][0]["type"] = "file"
            data["project.json"] = json.dumps(document).encode()
        changed = self.mutate(change)
        with self.assertRaisesRegex(ValueError, "portable resource contract"):
            self.manager.preview_import(changed)

    def test_source_state_retained_and_historical_context_strict(self):
        self.graph["sources"][0]["state"] = {"compression": "none", "alphabet": "nucleotide"}
        preview, _ = self.export()
        self.assertEqual(preview["manifest"]["graph"]["sources"][0]["state"], self.graph["sources"][0]["state"])
        imported = self.manager.import_project(self.manager.preview_import(self.bundle), self.root / "context")
        valid = imported["projectMetadata"]
        self.assertEqual(project_manager.validate_project_metadata(valid), valid)
        for change in ({"extra": "unrecorded"}, {"referencesAreHistorical": False}, {"manifestSha256": "invalid"}):
            invalid = dict(valid, **change)
            with self.assertRaises(ValueError):
                project_manager.validate_project_metadata(invalid)

    def test_implicit_samtools_helper_is_exact_requirement_not_target_default(self):
        helper = self.app / "packs/helper-0.5.2"
        (helper / "bin").mkdir(parents=True)
        binary = b"Synthetic SAMtools helper, never executed"
        schema = json.dumps(metadata()).encode()
        (helper / "bin/example.exe").write_bytes(binary)
        (helper / "workbench-schema.json").write_bytes(schema)
        manifest = MANIFEST.format(binary_sha=hashlib.sha256(binary).hexdigest(), schema_sha=hashlib.sha256(schema).hexdigest())
        manifest = manifest.replace("id=example", "id=helper").replace("[tool:example]", "[tool:samtools]").replace("tool=example", "tool=samtools")
        (helper / "pack.ini").write_text(manifest, encoding="utf-8")
        self.engine = Engine(self.app, load_catalog(self.app))
        self.manager = ProjectManager(self.engine)
        with patch.object(self.engine, "_alignment_ports", side_effect=lambda tool: [{}] if tool["packId"] == "example" else []):
            preview, _ = self.export()
            recorded = preview["manifest"]["validationTools"]["step-1"]
            self.assertEqual(recorded["pin"]["packId"], "helper")
            with patch.object(self.engine, "_samtools_selection", side_effect=AssertionError("Never silently select a new helper")):
                imported = self.manager.import_project(self.manager.preview_import(self.bundle), self.root / "helper project")
                again = self.manager.export_preview(imported["graph"], project_metadata=imported["projectMetadata"])
                self.assertEqual(again["manifest"]["validationTools"]["step-1"], recorded)
            (helper / "bin/example.exe").write_bytes(b"tampered")
            missing = self.manager.preview_import(self.bundle)
            self.assertFalse(missing["summary"]["ready"])
            self.assertEqual(missing["summary"]["packs"][-1]["status"], "missing-or-incompatible")

    @unittest.skipUnless(os.environ.get("NW_CWLTOOL") or shutil.which("cwltool"), "Stock CWL engine is unavailable; Linux replay is not counted as passed.")
    def test_stock_cwl_report_replay_after_project_relocation(self):
        if os.name == "nt":
            self.skipTest("This independent execution profile specifically records Linux CWL replay.")
        first, second = self.root / "one.txt", self.root / "two.txt"
        first.write_text("reads\t11\n", encoding="utf-8")
        second.write_text("reads\t22\n", encoding="utf-8")
        preview = self.manager.export_preview(self.report_graph(first, second), include_data=True)
        self.manager.export(preview, self.bundle)
        imported = self.manager.import_project(self.manager.preview_import(self.bundle), self.root / "initial")
        moved = self.root / "moved CWL project"
        shutil.move(imported["folder"], moved)
        first.unlink()
        second.unlink()
        result = subprocess.run([os.environ.get("NW_CWLTOOL") or shutil.which("cwltool"), "--no-container", "--outdir", str(self.root / "cwl-results"), str(moved / "workflow.cwl")],
                                text=True, capture_output=True, timeout=120)
        self.assertEqual(result.returncode, 0, result.stderr)
        outputs = json.loads(result.stdout)
        report = Path(unquote(urlparse(outputs["step_1_o_report"]["location"]).path)).read_text(encoding="utf-8")
        self.assertIn("reads\t11", report)
        self.assertIn("reads\t22", report)
        self.assertIn("Counts from different callers or analyses have not been pooled", report)


if __name__ == "__main__":
    unittest.main()
