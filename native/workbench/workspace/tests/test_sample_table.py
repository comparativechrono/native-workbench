"""Local sample binding and per-sample graph safety, using synthetic manifests.

No scientific executable, installed optional pack, network or Windows GUI runs.
"""
import copy
import csv
import hashlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from catalog import load_catalog
from engine import Engine, pin_for
import sample_table
from sample_table import binding_targets, parse_table, preview_batch, read_table
from test_pack_schema import MANIFEST, metadata


class SampleTableTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="workbench samples ")
        self.root = Path(self.tmp.name)
        pack = self.root / "packs/example-0.5.2"
        (pack / "bin").mkdir(parents=True)
        binary = b"Non-executable sample-table fixture"
        (pack / "bin/example.exe").write_bytes(binary)
        schema = json.dumps(metadata()).encode()
        (pack / "workbench-schema.json").write_bytes(schema)
        (pack / "pack.ini").write_text(MANIFEST.format(binary_sha=hashlib.sha256(binary).hexdigest(), schema_sha=hashlib.sha256(schema).hexdigest()))
        self.engine = Engine(self.root, load_catalog(self.root))
        for name in ("a.fa", "b.fa", "reference.fa"):
            (self.root / name).write_text(">chr1\nACGTACGT\n")
        self.graph = {"schema": 1, "name": "Per-sample sequence analysis", "sources": [
            {"id": "input-1", "type": "fasta-nucleotide", "files": {"sequences": str(self.root / "a.fa")}}],
            "nodes": [{"id": "step-1", "tool": "example/filter", "pin": pin_for(self.engine.tools["example/filter"]),
                       "params": {"minimum": "10"}, "inputs": {"sequences": ["input-1"]}}]}
        self.binding = [{"sourceId": "input-1", "fieldId": "sequences", "column": "sequence"}]
        self.table = parse_table("sample_id,sequence,condition,replicate,note\ns1,a.fa,control,1,original\ns2,b.fa,treated,2,original\n", base_directory=self.root)

    def tearDown(self):
        self.tmp.cleanup()

    def preview(self, **kwargs):
        return preview_batch(self.engine, kwargs.pop("graph", self.graph), kwargs.pop("table", self.table), kwargs.pop("bindings", self.binding), **kwargs)

    def message(self, result):
        return " ".join(error["message"] for error in result["errors"])

    def test_csv_tsv_utf8_bom_quoted_metadata_and_original_bytes_hash(self):
        text = '\ufeffsample_id\tsequence\tcondition\tnote\ns1\ta.fa\tcontrol\t"a, quoted value"\n'
        table = parse_table(text.encode(), base_directory=self.root)
        self.assertEqual(table["rows"][0]["note"], "a, quoted value")
        self.assertEqual(table["delimiter"], "\t")
        self.assertEqual(table["sha256"], hashlib.sha256(text.encode()).hexdigest())
        file = self.root / "samples.tsv"
        file.write_bytes(text.encode())
        self.assertEqual(read_table(file), table)

    def test_reject_duplicate_missing_unsafe_and_case_ambiguous_sample_ids(self):
        for rows in ("s1,a.fa\ns1,b.fa\n", "s1,a.fa\nS1,b.fa\n", ",a.fa\n", "../s1,a.fa\n", "s 1,a.fa\n"):
            with self.subTest(rows=rows), self.assertRaises(ValueError):
                parse_table("sample_id,sequence\n" + rows)

    def test_reject_duplicate_ambiguous_missing_headers_and_ragged_rows(self):
        for text in ("sample_id,x,x\ns1,a,b\n", "sample_id,x,X\ns1,a,b\n", "sample,sequence\ns1,a\n",
                     "sample_id, sequence\ns1,a\n", "sample_id,x\ns1,a,b\n", "sample_id,x\ns1\n", "sample_id,x\n",
                     "sample_id,x\ns1,a\n\n", 'sample_id,x\ns1,"unterminated'):
            with self.subTest(text=text), self.assertRaises(ValueError):
                parse_table(text)

    def test_bounded_bytes_rows_columns_cells_and_control_characters(self):
        with patch.object(sample_table, "MAX_TABLE_BYTES", 30), self.assertRaises(ValueError):
            parse_table("sample_id,value\ns1," + "a" * 50)
        with patch.object(sample_table, "MAX_ROWS", 1), self.assertRaises(ValueError):
            parse_table("sample_id,value\ns1,a\ns2,b\n")
        with patch.object(sample_table, "MAX_COLUMNS", 1), self.assertRaises(ValueError):
            parse_table("sample_id,value\ns1,a\n")
        for value in ("a\0b", '"a\nb"', "a" * (sample_table.MAX_CELL + 1)):
            with self.subTest(value=value[:10]), self.assertRaises(ValueError):
                parse_table("sample_id,value\ns1," + value + "\n")

    def test_source_fields_and_parameter_targets_from_installed_contract(self):
        targets = binding_targets(self.engine, self.graph)
        self.assertEqual(targets["files"][0]["fieldId"], "sequences")
        self.assertEqual(targets["files"][0]["sourceType"], "fasta-nucleotide")
        self.assertEqual(targets["parameters"][0]["parameterId"], "minimum")

    def test_independent_copies_preserve_pins_connections_metadata_and_originals(self):
        originals = copy.deepcopy((self.graph, self.table, self.binding))
        result = self.preview(parameter_bindings=[{"nodeId": "step-1", "parameterId": "minimum", "column": "replicate"}])
        self.assertTrue(result["valid"], result)
        self.assertEqual(result["sampleCount"], 2)
        first, second = result["samples"]
        self.assertNotEqual(first["graph"]["name"], second["graph"]["name"])
        self.assertEqual(first["graph"]["sources"][0]["files"]["sequences"], str(self.root / "a.fa"))
        self.assertEqual(second["graph"]["sources"][0]["files"]["sequences"], str(self.root / "b.fa"))
        for entry in result["samples"]:
            self.assertEqual(entry["graph"]["nodes"][0]["pin"], self.graph["nodes"][0]["pin"])
            self.assertEqual(entry["graph"]["nodes"][0]["inputs"], self.graph["nodes"][0]["inputs"])
            self.assertEqual(entry["metadata"]["columns"]["note"], "original")
            self.assertEqual(entry["metadata"]["tableSha256"], self.table["sha256"])
        first["graph"]["nodes"][0]["pin"]["packVersion"] = "mutated"
        first["metadata"]["columns"]["note"] = "mutated"
        self.assertNotEqual(second["graph"]["nodes"][0]["pin"]["packVersion"], "mutated")
        self.assertEqual((self.graph, self.table, self.binding), originals)

    def test_relative_paths_need_explicit_base_and_missing_files_block_entire_batch(self):
        table = copy.deepcopy(self.table)
        table["baseDirectory"] = None
        result = self.preview(table=table)
        self.assertFalse(result["valid"])
        self.assertIn("Relative file paths", self.message(result))
        table = copy.deepcopy(self.table)
        table["rows"][1]["sequence"] = "missing.fa"
        result = self.preview(table=table)
        self.assertFalse(result["valid"])
        self.assertTrue(result["samples"][0]["valid"])
        self.assertFalse(result["samples"][1]["valid"])

    def test_duplicate_paths_and_hard_links_rejected_even_across_different_columns(self):
        table = copy.deepcopy(self.table)
        table["rows"][1]["sequence"] = "a.fa"
        result = self.preview(table=table)
        self.assertFalse(result["valid"])
        self.assertIn("same input file", self.message(result))
        alias = self.root / "alias.fa"
        os.link(self.root / "a.fa", alias)
        table["rows"][1]["sequence"] = "alias.fa"
        self.assertFalse(self.preview(table=table)["valid"])

    def test_binding_errors_reject_unknown_duplicate_columns_and_repeated_fields(self):
        for bindings in ([], [dict(self.binding[0], fieldId="arbitrary")], [dict(self.binding[0], column="missing")],
                         self.binding * 2, [dict(self.binding[0], column="sample_id")],
                         [dict(self.binding[0], shared="true")], [dict(self.binding[0], execute="shell")]):
            with self.subTest(bindings=bindings):
                self.assertFalse(self.preview(bindings=bindings)["valid"])
        for bindings in ([{"nodeId": "step-1", "parameterId": "unknown", "column": "sample_id"}],
                         [{"nodeId": "step-1", "parameterId": "minimum", "column": "replicate"}] * 2):
            self.assertFalse(self.preview(parameter_bindings=bindings)["valid"])

    def test_all_connected_sample_inputs_need_explicit_mapping(self):
        graph = copy.deepcopy(self.graph)
        graph["sources"].append({"id": "input-2", "type": "fasta-nucleotide", "files": {"sequences": str(self.root / "b.fa")}})
        node = copy.deepcopy(graph["nodes"][0])
        node.update(id="step-2", inputs={"sequences": ["input-2"]})
        graph["nodes"].append(node)
        result = self.preview(graph=graph)
        self.assertFalse(result["valid"])
        self.assertIn("Map every sample input", self.message(result))

    def test_shared_reference_binding_is_preserved_and_can_be_explicitly_repeated(self):
        graph = copy.deepcopy(self.graph)
        graph["sources"].append({"id": "input-2", "type": "reference", "files": {"sequences": str(self.root / "reference.fa")}})
        node = copy.deepcopy(graph["nodes"][0])
        node.update(id="step-2", inputs={"sequences": ["input-2"]})
        graph["nodes"].append(node)
        tool = self.engine.tools["example/filter"]
        tool["ports"][0]["accepts"].append("reference")
        result = self.preview(graph=graph)
        self.assertTrue(result["valid"], result)
        for sample in result["samples"]:
            self.assertEqual(sample["graph"]["sources"][1], graph["sources"][1])
        table = copy.deepcopy(self.table)
        table["columns"].append("reference")
        for row in table["rows"]:
            row["reference"] = "reference.fa"
        result = self.preview(graph=graph, table=table, bindings=self.binding + [{"sourceId": "input-2", "fieldId": "sequences", "column": "reference"}])
        self.assertTrue(result["valid"], result)

    def test_explicit_generic_shared_resources_must_be_constant(self):
        table = copy.deepcopy(self.table)
        result = self.preview(table=table, bindings=[dict(self.binding[0], shared=True)])
        self.assertFalse(result["valid"])
        self.assertIn("same file in every sample row", self.message(result))
        table["rows"][1]["sequence"] = "a.fa"
        self.assertTrue(self.preview(table=table, bindings=[dict(self.binding[0], shared=True)])["valid"])

    def test_sample_variant_formats_cannot_be_shared_but_explicit_metrics_can(self):
        for kind in ("vcf", "vcf-pass", "bcf", "bcf-likelihoods"):
            graph = copy.deepcopy(self.graph)
            graph["sources"][0]["type"] = kind
            for options in ({"bindings": [dict(self.binding[0], shared=True)]},
                            {"shared_sources": ["input-1"]}):
                with self.subTest(kind=kind, options=options):
                    result = self.preview(graph=graph, **options)
                    self.assertFalse(result["valid"])
                    self.assertEqual(result["samples"], [])
                    self.assertIn("shared", self.message(result))
        graph = copy.deepcopy(self.graph)
        graph["sources"][0]["type"] = "metrics"
        self.engine.tools["example/filter"]["ports"][0]["accepts"].append("metrics")
        table = copy.deepcopy(self.table)
        table["rows"][1]["sequence"] = "a.fa"
        for options in ({"bindings": [dict(self.binding[0], shared=True)]},
                        {"shared_sources": ["input-1"]}):
            with self.subTest(shared_metrics=options):
                result = self.preview(graph=graph, table=table, **options)
                self.assertTrue(result["valid"], result)

    def test_missing_or_changed_exact_pin_never_resolves_to_latest(self):
        for change in ("missing", "version", "hash"):
            graph = copy.deepcopy(self.graph)
            if change == "missing":
                del graph["nodes"][0]["pin"]
            else:
                graph["nodes"][0]["pin"]["packVersion" if change == "version" else "manifestSha256"] = "incorrect"
            self.assertFalse(self.preview(graph=graph)["valid"])

    def test_ipc_table_object_is_revalidated_and_metadata_is_not_trusted_as_evidence(self):
        for change in ("extra", "nontext", "missing", "duplicate", "hash"):
            table = copy.deepcopy(self.table)
            if change == "extra": table["rows"][0]["command"] = "unsafe"
            elif change == "nontext": table["rows"][0]["replicate"] = 2
            elif change == "missing": del table["rows"][0]["sequence"]
            elif change == "duplicate": table["rows"][1]["sample_id"] = "s1"
            else: table["sha256"] = "not a digest"
            with self.subTest(change=change): self.assertFalse(self.preview(table=table)["valid"])

    def test_pooling_and_cohort_requests_never_silently_expand_or_concatenate(self):
        for mode in ("pooled", "cohort", ""):
            result = self.preview(mode=mode)
            self.assertFalse(result["valid"])
            self.assertEqual(result["samples"], [])
            self.assertIn("never combined automatically", self.message(result))

    def paired_graph(self):
        graph = copy.deepcopy(self.graph)
        graph["sources"][0].update(type="pair", files={}, fields=[
            {"id": "reads1", "type": "file", "role": "read1"},
            {"id": "reads2", "type": "file", "role": "read2"}])
        tool = self.engine.tools["example/filter"]
        tool["ports"][0].update(type="pair", accepts=["pair"], manifestInputs=["reads1", "reads2"], requiredState={},
                               fields=copy.deepcopy(graph["sources"][0]["fields"]))
        for name in ("a1.fq", "a2.fq", "b1.fq", "b2.fq"):
            (self.root / name).write_text("@r1\nACGT\n+\nIIII\n")
        table = parse_table("sample_id,read1,read2\ns1,a1.fq,a2.fq\ns2,b1.fq,b2.fq\n", base_directory=self.root)
        bindings = [{"sourceId": "input-1", "fieldId": field, "column": column}
                    for field, column in (("reads1", "read1"), ("reads2", "read2"))]
        return graph, table, bindings

    def test_paired_files_require_both_explicit_distinct_roles_without_filename_guessing(self):
        graph, table, bindings = self.paired_graph()
        self.assertTrue(self.preview(graph=graph, table=table, bindings=bindings)["valid"])
        self.assertFalse(self.preview(graph=graph, table=table, bindings=bindings[:1])["valid"])
        for value in ("", "a1.fq"):
            table["rows"][0]["read2"] = value
            self.assertFalse(self.preview(graph=graph, table=table, bindings=bindings)["valid"])
        table["rows"][0]["read2"] = "a2.fq"
        self.assertFalse(self.preview(graph=graph, table=table, bindings=[dict(item, shared=True) for item in bindings])["valid"])
        self.assertFalse(self.preview(graph=graph, table=table, bindings=bindings, shared_sources=["input-1"])["valid"])
        graph["sources"][0]["fields"] = [{"id": "arbitrary1", "type": "file"}, {"id": "arbitrary2", "type": "file"}]
        self.assertFalse(self.preview(graph=graph, table=table, bindings=bindings)["valid"])

    def test_scientific_sample_parameter_must_be_mapped_to_distinct_sample_id(self):
        tool = self.engine.tools["example/filter"]
        tool["params"].append({"id": "sample", "label": "Sample", "type": "text", "required": True, "binding": True, "constraint": ""})
        self.graph["nodes"][0]["params"]["sample"] = "old-sample"
        result = self.preview()
        self.assertFalse(result["valid"])
        self.assertIn("distinct scientific identities", self.message(result))
        result = self.preview(parameter_bindings=[{"nodeId": "step-1", "parameterId": "sample", "column": "sample_id"}])
        self.assertTrue(result["valid"], result)
        self.assertEqual([item["graph"]["nodes"][0]["params"]["sample"] for item in result["samples"]], ["s1", "s2"])

    def combined_graph(self):
        tool = self.engine.tools["builtin/report"]
        return {"schema": 1, "name": "Combined metrics", "sources": [], "nodes": [
            {"id": "step-1", "tool": "builtin/report", "pin": pin_for(tool), "params": {"title": "Two samples"}, "inputs": {"metrics": []}}]}

    def test_combined_reports_make_one_graph_with_distinct_typed_sources_and_row_metadata(self):
        graph = self.combined_graph()
        before = copy.deepcopy(graph)
        targets = binding_targets(self.engine, graph)
        self.assertEqual(targets["combined"][0]["portId"], "metrics")
        result = self.preview(graph=graph, bindings=[], mode="combined", combined_target={"nodeId": "step-1", "portId": "metrics", "column": "sequence"})
        self.assertTrue(result["valid"], result)
        self.assertEqual(result["sampleCount"], 2)
        self.assertEqual(len(result["samples"]), 1)
        sample = result["samples"][0]
        self.assertEqual(sample["metadata"]["rows"], self.table["rows"])
        self.assertEqual(len(sample["graph"]["sources"]), 2)
        self.assertEqual(sample["graph"]["nodes"][0]["inputs"]["metrics"], ["input-1", "input-2"])
        self.assertEqual(sample["graph"]["nodes"][0]["pin"], graph["nodes"][0]["pin"])
        self.assertEqual(graph, before)
        self.assertIn("one combined-report job", result["warnings"][-1]["message"])

    def test_combined_reports_do_not_replace_selected_files_or_accept_duplicate_reports(self):
        graph = self.combined_graph()
        target = {"nodeId": "step-1", "portId": "metrics", "column": "sequence"}
        graph["sources"] = [{"id": "input-1", "type": "metrics", "files": {"metrics": str(self.root / "a.fa")}}]
        graph["nodes"][0]["inputs"]["metrics"] = ["input-1"]
        self.assertFalse(self.preview(graph=graph, bindings=[], mode="combined", combined_target=target)["valid"])
        graph["sources"][0]["files"] = {}
        result = self.preview(graph=graph, bindings=[], mode="combined", combined_target=target)
        self.assertTrue(result["valid"], result)
        self.assertEqual([source["id"] for source in result["samples"][0]["graph"]["sources"]], ["input-2", "input-3"])
        table = copy.deepcopy(self.table)
        table["rows"][1]["sequence"] = "a.fa"
        self.assertFalse(self.preview(graph=graph, table=table, bindings=[], mode="combined", combined_target=target)["valid"])

    def test_combined_reports_fail_closed_for_missing_target_single_port_reads_or_cardinality(self):
        result = self.preview(bindings=[], mode="combined")
        self.assertFalse(result["valid"])
        self.assertIn("explicit combined-report", self.message(result))
        self.assertFalse(self.preview(bindings=[], mode="combined", combined_target={"nodeId": "step-1", "portId": "sequences", "column": "sequence"})["valid"])
        graph = self.combined_graph()
        table = copy.deepcopy(self.table)
        table["rows"] = table["rows"][:1]
        result = self.preview(graph=graph, table=table, bindings=[], mode="combined", combined_target={"nodeId": "step-1", "portId": "metrics", "column": "sequence"})
        self.assertFalse(result["valid"])
        self.assertIn("accepts 2", self.message(result))

    def test_historical_exact_pin_without_pack_id_is_preserved(self):
        graph = copy.deepcopy(self.graph)
        del graph["nodes"][0]["pin"]["packId"]
        result = self.preview(graph=graph)
        self.assertTrue(result["valid"], result)
        self.assertEqual(result["samples"][0]["graph"]["nodes"][0]["pin"], graph["nodes"][0]["pin"])

    def test_oversized_metadata_blocks_preview_without_silent_truncation(self):
        table = copy.deepcopy(self.table)
        for index in range(5):
            column = "large_note_" + str(index)
            table["columns"].append(column)
            for row in table["rows"]:
                row[column] = "x" * 4000
        result = self.preview(table=table)
        self.assertFalse(result["valid"])
        self.assertIn("16 KiB", self.message(result))
        self.assertEqual(result["samples"][0]["metadata"]["columns"]["large_note_0"], "x" * 4000)
        graph = self.combined_graph()
        result = self.preview(graph=graph, table=table, bindings=[], mode="combined", combined_target={"nodeId": "step-1", "portId": "metrics", "column": "sequence"})
        self.assertFalse(result["valid"])
        self.assertEqual(result["samples"], [])

    def test_graph_expansion_limit_checked_before_allocating(self):
        with patch.object(sample_table, "MAX_EXPANDED_BYTES", 10):
            result = self.preview()
        self.assertFalse(result["valid"])
        self.assertEqual(result["samples"], [])

    def test_file_symlinks_and_symlink_table_parent_are_rejected(self):
        alias = self.root / "link.fa"
        try:
            alias.symlink_to(self.root / "a.fa")
        except OSError:
            self.skipTest("This account cannot create symbolic links.")
        table = copy.deepcopy(self.table)
        table["rows"][0]["sequence"] = "link.fa"
        self.assertFalse(self.preview(table=table)["valid"])
        directory = self.root / "link-dir"
        directory.symlink_to(self.root, target_is_directory=True)
        with self.assertRaises(ValueError):
            parse_table("sample_id,x\ns1,a\n", base_directory=directory)

    def test_parameters_use_pack_validation_after_explicit_binding(self):
        table = copy.deepcopy(self.table)
        table["rows"][0]["replicate"] = "not an integer"
        result = self.preview(table=table, parameter_bindings=[{"nodeId": "step-1", "parameterId": "minimum", "column": "replicate"}])
        self.assertFalse(result["valid"])
        self.assertIn("integer", self.message(result))


if __name__ == "__main__":
    unittest.main()
