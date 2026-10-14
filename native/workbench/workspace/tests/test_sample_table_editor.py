"""Full-table editing, explicit file roles and create-new exports; no tool run."""
import copy
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "workspace"))
from catalog import load_catalog
from desktop_host import DesktopHost
from sample_table import read_table
import sample_table_editor as editor
from service import Workbench


class SampleTableEditorTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="workbench sample editor ")
        self.root = Path(self.tmp.name)
        self.inputs = self.root / "input files"
        self.inputs.mkdir()
        (self.inputs / "r1.fastq").write_text("synthetic first read")
        (self.inputs / "r2.fastq").write_text("synthetic second read")
        self.destination = self.root / "different destination"
        self.destination.mkdir()
        self.app = Workbench(self.root, catalog={"tools": {}})
        self.host = DesktopHost(self.root, app=self.app)
        self.draft = {"columns": ["sample_id", "read1", "read2", "note"],
                      "rows": [{"sample_id": "s1", "read1": "r1.fastq", "read2": "r2.fastq", "note": "relative/metadata"}],
                      "baseDirectory": str(self.inputs), "delimiter": ",", "fileColumns": ["read1", "read2"]}

    def tearDown(self):
        self.host.close(grace=.1)
        self.tmp.cleanup()

    def apply(self, draft=None):
        return self.host.dispatch("sample/apply", {"table": self.draft if draft is None else draft})

    def save(self, table, path, selected=None):
        return self.host.dispatch("sample/save", {"table_token": table["table_token"], "path": str(path),
                                                   "file_columns": ["read1", "read2"] if selected is None else selected})

    def test_full_import_edit_retains_every_row_beyond_short_preview(self):
        path = self.inputs / "many.csv"
        path.write_text("sample_id,note\n" + "".join(f"s{i},row{i}\n" for i in range(1000)))
        summary = self.host.dispatch("sample/table", {"path": str(path)})
        self.assertEqual((summary["rowCount"], len(summary["rows"]), summary["preview_omitted"]), (1000, 100, 900))
        full = self.host.dispatch("sample/edit", {"table_token": summary["table_token"]})
        self.assertEqual(len(full["rows"]), 1000)
        self.assertEqual(full["rows"][-1], {"sample_id": "s999", "note": "row999"})
        self.assertEqual(full["limits"]["maxRows"], 1000)
        self.assertEqual(full["fileColumns"], [])

    def test_oversized_editor_rejects_instead_of_truncating_imported_table(self):
        path = self.inputs / "large.csv"
        path.write_text("sample_id,note\n" + "".join(f"s{i}," + "界" * 4000 + "\n" for i in range(60)), encoding="utf-8")
        summary = self.host.dispatch("sample/table", {"path": str(path)})
        with self.assertRaisesRegex(ValueError, "No rows were truncated"):
            self.host.dispatch("sample/edit", {"table_token": summary["table_token"]})
        self.assertEqual(len(self.app._sample_table(summary["table_token"])["rows"]), 60)

    def test_edit_and_cancel_do_not_write_files_or_mutate_original_snapshot(self):
        original = self.apply()
        before = sorted(str(path.relative_to(self.root)) for path in self.root.rglob("*"))
        draft = self.host.dispatch("sample/edit", {"table_token": original["table_token"]})
        draft["rows"][0]["sample_id"] = "cancelled-edit"
        self.assertEqual(self.app._sample_table(original["table_token"])["rows"][0]["sample_id"], "s1")
        self.assertEqual(sorted(str(path.relative_to(self.root)) for path in self.root.rglob("*")), before)

    def test_applying_edits_makes_new_token_and_checksum_without_mutating_old(self):
        original = self.apply()
        changed = copy.deepcopy(self.draft)
        changed["rows"][0]["sample_id"] = "s2"
        applied = self.apply(changed)
        self.assertNotEqual(applied["table_token"], original["table_token"])
        self.assertNotEqual(applied["sha256"], original["sha256"])
        self.assertEqual(self.app._sample_table(original["table_token"])["rows"][0]["sample_id"], "s1")
        self.assertEqual(applied["rows"][0]["sample_id"], "s2")

    def test_invalid_ids_headers_ragged_cells_and_draft_extras_rejected(self):
        mutations = []
        for identity in ("", "../sample", "sample name"):
            value = copy.deepcopy(self.draft)
            value["rows"][0]["sample_id"] = identity
            mutations.append(value)
        duplicate = copy.deepcopy(self.draft)
        duplicate["rows"].append(dict(duplicate["rows"][0], sample_id="S1"))
        mutations.append(duplicate)
        for value in (dict(self.draft, columns=["sample_id", "bad name"]),
                      dict(self.draft, columns=[[]]), dict(self.draft, sha256="a" * 64),
                      dict(self.draft, rows=[{"sample_id": "s1"}]), dict(self.draft, delimiter="|"),
                      dict(self.draft, fileColumns=["missing"]), dict(self.draft, fileColumns=["sample_id"])):
            mutations.append(value)
        for value in mutations:
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.apply(value)
        self.assertEqual(self.app._sample_tables, {})

    def test_unicode_tsv_roundtrip_preserves_metadata_and_declared_path_meaning(self):
        self.draft["rows"][0]["note"] = 'metadata, "界" and relative/metadata'
        table = self.apply()
        path = self.destination / "saved samples.tsv"
        saved = self.save(table, path)
        imported = read_table(path)
        self.assertEqual(imported["delimiter"], "\t")
        self.assertEqual(imported["rows"], saved["rows"])
        self.assertEqual(imported["rows"][0]["read1"], str(self.inputs / "r1.fastq"))
        self.assertEqual(imported["rows"][0]["read2"], str(self.inputs / "r2.fastq"))
        self.assertEqual(imported["rows"][0]["note"], self.draft["rows"][0]["note"])
        self.assertEqual(saved["sha256"], hashlib.sha256(path.read_bytes()).hexdigest())
        self.assertEqual(saved["baseDirectory"], str(self.destination))
        self.assertEqual(self.app._sample_table(table["table_token"])["rows"][0]["read1"], "r1.fastq")

    def test_changing_base_folder_is_explicit_and_changes_only_future_saved_paths(self):
        first = self.apply()
        alternate = self.root / "alternate"
        alternate.mkdir()
        for name in ("r1.fastq", "r2.fastq"):
            (alternate / name).write_text("other explicitly chosen source")
        self.draft["baseDirectory"] = str(alternate)
        second = self.apply()
        one = self.save(first, self.destination / "first.csv")
        two = self.save(second, self.destination / "second.csv")
        self.assertEqual(one["rows"][0]["read1"], str(self.inputs / "r1.fastq"))
        self.assertEqual(two["rows"][0]["read1"], str(alternate / "r1.fastq"))

    def test_save_requires_explicit_file_columns_and_preserves_path_like_metadata(self):
        table = self.apply()
        saved = self.save(table, self.destination / "metadata.csv", selected=[])
        self.assertEqual(saved["rows"], self.draft["rows"])
        with self.assertRaisesRegex(ValueError, "explicit file-path columns"):
            self.host.dispatch("sample/save", {"table_token": table["table_token"], "path": str(self.destination / "missing.csv")})

    def test_missing_relative_base_or_files_blocks_save_without_output(self):
        for base in (None, str(self.destination)):
            draft = dict(self.draft, baseDirectory=base)
            table = self.apply(draft)
            with self.subTest(base=base), self.assertRaises((ValueError, OSError)):
                self.save(table, self.destination / "blocked.csv")
            self.assertFalse((self.destination / "blocked.csv").exists())
            self.assertEqual(list(self.destination.iterdir()), [])

    def test_save_never_overwrites_existing_file_even_during_atomic_publication(self):
        table = self.apply()
        target = self.destination / "existing.csv"
        target.write_bytes(b"preserve existing exact bytes")
        with self.assertRaisesRegex(ValueError, "never overwritten"):
            self.save(table, target)
        self.assertEqual(target.read_bytes(), b"preserve existing exact bytes")
        target.unlink()
        publish = os.rename if os.name == "nt" else os.link
        def race(source, destination):
            Path(destination).write_bytes(b"another writer won")
            return publish(source, destination)
        method = "sample_table_editor.os.rename" if os.name == "nt" else "sample_table_editor.os.link"
        with patch(method, side_effect=race), self.assertRaisesRegex(ValueError, "never overwritten"):
            self.save(table, target)
        self.assertEqual(target.read_bytes(), b"another writer won")
        self.assertEqual(list(self.destination.iterdir()), [target])

    def test_save_failure_removes_temporary_file_and_keeps_token_available(self):
        table = self.apply()
        with patch("sample_table_editor.os.fsync", side_effect=OSError("disk failure")), self.assertRaises(OSError):
            self.save(table, self.destination / "failed.csv")
        self.assertEqual(list(self.destination.iterdir()), [])
        self.assertEqual(self.app._sample_table(table["table_token"])["rows"], self.draft["rows"])

    def test_save_rejects_windows_devices_streams_and_unsafe_filenames_on_every_platform(self):
        table = self.apply()
        for name in ("CON.csv", "con .csv", "prn.data.csv", "AUX.tsv", "NUL.csv", "COM1.csv", "LPT9.tsv",
                     "COM¹.csv", "CONIN$.csv", "file:stream.csv", 'bad"name.csv', "bad?.csv", "bad*.tsv",
                     "bad<.csv", "bad>.csv", "bad|.csv", "bad\\name.csv", "bad\x7f.csv", "trailing.csv.", "trailing.csv "):
            with self.subTest(name=name), self.assertRaises(ValueError):
                self.save(table, self.destination / name)
        self.assertEqual(list(self.destination.iterdir()), [])

    def test_absolute_path_expansion_that_cannot_reopen_in_editor_never_creates_file(self):
        base = self.inputs / ("x" * 180)
        base.mkdir()
        (base / "reads.dat").write_text("synthetic editor size fixture")
        columns = ["sample_id"] + ["file" + str(index) for index in range(6)]
        rows = [dict({name: "reads.dat" for name in columns[1:]}, sample_id="s" + str(index)) for index in range(1000)]
        table = self.apply({"columns": columns, "rows": rows, "baseDirectory": str(base), "fileColumns": columns[1:]})
        self.assertEqual(len(self.host.dispatch("sample/edit", {"table_token": table["table_token"]})["rows"]), 1000)
        with self.assertRaisesRegex(ValueError, "absolute paths would exceed"):
            self.save(table, self.destination / "too large.csv", columns[1:])
        self.assertEqual(list(self.destination.iterdir()), [])
        self.assertEqual(len(self.app._sample_table(table["table_token"])["rows"]), 1000)

    def test_retained_selection_survives_repeated_saved_and_cancelled_editor_drafts(self):
        original = self.apply()
        token = original["table_token"]
        for index in range(8):
            changed = copy.deepcopy(self.draft)
            changed["rows"][0]["sample_id"] = "edit" + str(index)
            applied = self.host.dispatch("sample/apply", {"table": changed, "retain_token": token})
            self.host.dispatch("sample/save", {"table_token": applied["table_token"], "path": str(self.destination / (str(index) + ".csv")),
                                                "file_columns": ["read1", "read2"], "retain_token": token})
            self.assertEqual(self.app._sample_table(token)["rows"], self.draft["rows"])
            self.assertLessEqual(len(self.app._sample_tables), 4)
            self.assertLessEqual(sum(item[2] for item in self.app._sample_tables.values()), 32 * 1024 * 1024)
        # Cancelling the editor means no new token is selected. The original
        # selection still resolves to every original row after cache churn.
        self.assertEqual(self.host.dispatch("sample/edit", {"table_token": token})["rows"], self.draft["rows"])

    def test_malformed_retention_fails_before_creating_an_export(self):
        table = self.apply()
        for retained in (None, [], "", "x" * 101):
            with self.subTest(retained=retained), self.assertRaises(ValueError):
                self.host.dispatch("sample/save", {"table_token": table["table_token"], "path": str(self.destination / "blocked.csv"),
                                                    "file_columns": [], "retain_token": retained})
        self.assertEqual(list(self.destination.iterdir()), [])

    def test_long_edit_session_can_apply_and_save_complete_draft_and_preserve_original(self):
        original = self.apply()
        token = original["table_token"]
        changed = copy.deepcopy(self.draft)
        changed["rows"][0]["sample_id"] = "edited-after-15-minutes"
        created = self.app._sample_tables[token][0]
        with patch("service.time.monotonic", return_value=created + 901):
            with self.assertRaisesRegex(ValueError, "expired"):
                self.host.dispatch("sample/edit", {"table_token": token})
            applied = self.host.dispatch("sample/apply", {"table": changed, "retain_token": token})
            saved = self.host.dispatch("sample/save", {"table_token": applied["table_token"],
                "path": str(self.destination / "long edit.csv"), "file_columns": ["read1", "read2"], "retain_token": token})
            self.assertEqual(self.app._sample_table(token)["rows"], self.draft["rows"])
        self.assertTrue(applied["retainedSelectionAvailable"])
        self.assertTrue(saved["retainedSelectionAvailable"])
        self.assertEqual(read_table(self.destination / "long edit.csv")["rows"][0]["sample_id"], changed["rows"][0]["sample_id"])
        self.assertLessEqual(len(self.app._sample_tables), 4)

    def test_evicted_original_does_not_strand_complete_draft_and_is_reported(self):
        original = self.apply()
        token = original["table_token"]
        changed = copy.deepcopy(self.draft)
        changed["rows"][0]["sample_id"] = "recovered-draft"
        for unused in range(4):
            self.apply()
        self.assertNotIn(token, self.app._sample_tables)
        applied = self.host.dispatch("sample/apply", {"table": changed, "retain_token": token})
        saved = self.host.dispatch("sample/save", {"table_token": applied["table_token"],
            "path": str(self.destination / "recovered.csv"), "file_columns": ["read1", "read2"], "retain_token": token})
        for result in (applied, saved):
            self.assertFalse(result["retainedSelectionAvailable"])
            self.assertIn("no longer cached", result["retentionNotice"])
        self.assertEqual(read_table(self.destination / "recovered.csv")["rows"][0]["sample_id"], "recovered-draft")
        self.assertLessEqual(len(self.app._sample_tables), 4)

    def test_edit_refreshes_valid_token_lifetime_without_changing_its_rows(self):
        table = self.apply()
        token = table["table_token"]
        created = self.app._sample_tables[token][0]
        with patch("service.time.monotonic", return_value=created + 899):
            self.host.dispatch("sample/edit", {"table_token": token})
        with patch("service.time.monotonic", return_value=created + 901):
            self.assertEqual(self.app._sample_table(token)["rows"], self.draft["rows"])

    def test_cold_editor_import_and_local_export_do_not_use_socket_apis(self):
        program = r'''
import json, pathlib, sys, tempfile
def no_network(event, arguments):
    if event.startswith("socket."):
        raise RuntimeError("Sample editor attempted a network API: " + event)
sys.addaudithook(no_network)
sys.path.insert(0, sys.argv[1])
import sample_table_editor
with tempfile.TemporaryDirectory() as folder:
    table = sample_table_editor.apply_draft({"columns": ["sample_id", "note"],
        "rows": [{"sample_id": "s1", "note": "local"}], "baseDirectory": folder})
    saved = sample_table_editor.save_table(table, pathlib.Path(folder) / "samples.csv", [])
    assert saved["rows"] == table["rows"]
print(json.dumps({"saved": True}))
'''
        result = subprocess.run([sys.executable, "-I", "-c", program, str(ROOT / "workspace")],
                                capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue(json.loads(result.stdout)["saved"])

    def test_expired_and_malformed_tokens_never_save_or_fetch_a_partial_table(self):
        table = self.apply()
        with patch("service.time.monotonic", return_value=time.monotonic() + 901):
            for method, request in (("sample/edit", {"table_token": table["table_token"]}),
                                    ("sample/save", {"table_token": table["table_token"], "path": str(self.destination / "expired.csv"), "file_columns": []})):
                with self.subTest(method=method), self.assertRaisesRegex(ValueError, "expired"):
                    self.host.dispatch(method, request)
        for token in (None, [], "", "x" * 101, "not-issued"):
            with self.subTest(token=token), self.assertRaises(ValueError):
                self.host.dispatch("sample/edit", {"table_token": token})
        self.assertEqual(list(self.destination.iterdir()), [])

    def test_strict_routes_reject_extra_fields(self):
        requests = [("sample/edit", {"table_token": "not-issued", "rows": []}),
                    ("sample/apply", {"table": self.draft, "overwrite": True}),
                    ("sample/example", {"path": str(self.root)}),
                    ("sample/save", {"table_token": "not-issued", "path": str(self.root / "x.csv"), "file_columns": [], "overwrite": True}),
                    ("methods/preview", {"output_folder": str(self.destination)})]
        for method, params in requests:
            with self.subTest(method=method), self.assertRaises(ValueError):
                self.host.dispatch(method, params)

    def test_methods_preview_is_read_only_and_never_runs_readiness_or_resource_probes(self):
        graph = {"schema": 1, "name": "Draft methods", "sources": [], "nodes": []}
        expected = {"valid": False, "methods": "Planned methods", "issues": [{"severity": "error", "message": "Choose a tool"}]}
        with patch.object(self.app.engine, "review", return_value=expected) as review, \
             patch("readiness.build_readiness", side_effect=AssertionError("readiness probe")), \
             patch.object(self.app, "resource_policy", side_effect=AssertionError("resource probe")):
            result = self.host.dispatch("methods/preview", {"graph": graph})
        self.assertEqual(result, expected)
        self.assertEqual(review.call_args.args[0], graph)
        self.assertIsNone(self.app._last_readiness)
        self.assertEqual(list(self.destination.iterdir()), [])

    def install_example(self):
        shutil.copytree(ROOT / "examples/starter", self.root / "examples/starter")
        pack = self.root / "packs/align-0.4.0"
        pack.mkdir(parents=True)
        shutil.copyfile(ROOT / "pack-examples/align.ini", pack / "pack.ini")
        self.app.catalog = load_catalog(self.root)

    def test_example_matches_bundled_one_sample_csv_and_does_not_mutate_packs(self):
        self.install_example()
        before = (self.root / "packs/align-0.4.0/pack.ini").read_bytes()
        example = self.host.dispatch("sample/example", {})
        bundled = read_table(self.root / "examples/starter/samples.csv")
        self.assertEqual(example["rowCount"], 1)
        self.assertEqual(example["rows"][0]["sample_id"], "starter")
        self.assertEqual(example["fileColumns"], ["read1", "read2", "reference"])
        for name in example["fileColumns"]:
            self.assertEqual(Path(example["rows"][0][name]), Path(bundled["baseDirectory"]) / bundled["rows"][0][name])
        self.assertIn("not independent biological replicates", example["exampleNotice"])
        self.assertEqual((self.root / "packs/align-0.4.0/pack.ini").read_bytes(), before)
        self.assertIsNone(self.app._pack_worker)
        self.assertEqual(self.app.runs, {})

    def test_example_missing_exact_pin_or_changed_fixture_has_actionable_error(self):
        with self.assertRaisesRegex(ValueError, "Manage tools.*align 0.4.0"):
            self.host.dispatch("sample/example", {})
        self.install_example()
        reads = self.root / "examples/starter/reads1.fastq"
        content = reads.read_bytes()
        reads.write_bytes(bytes([content[0] ^ 1]) + content[1:])
        with self.assertRaisesRegex(ValueError, "Restore examples/starter/reads1.fastq"):
            self.host.dispatch("sample/example", {})
        self.assertEqual(self.app._sample_tables, {})


if __name__ == "__main__":
    unittest.main()
