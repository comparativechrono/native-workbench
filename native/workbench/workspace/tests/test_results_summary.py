"""Scientific-summary contracts with literal synthetic upstream-format reports.

These source checks do not execute SAMtools/BCFtools or establish Windows GUI
behavior. The packaged Windows gate separately exercises the real tool outputs.
"""
import copy
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import results_summary as summaries
from engine import canonical, display_id


SAM_STATS = """# This file was produced by samtools stats (1.24)
SN\traw total sequences:\t202\t# excluding supplementary and secondary reads
SN\treads mapped:\t200
SN\treads unmapped:\t2
SN\treads duplicated:\t8
SN\taverage length:\t150
SN\terror rate:\t6.600000e-03\t# mismatches / bases mapped
"""
FLAGSTAT = """202 + 3 in total (QC-passed reads + QC-failed reads)
202 + 3 primary
0 + 0 secondary
0 + 0 supplementary
8 + 1 duplicates
8 + 1 primary duplicates
200 + 2 mapped (99.01% : 66.67%)
200 + 2 primary mapped (99.01% : 66.67%)
202 + 3 paired in sequencing
101 + 2 read1
101 + 1 read2
198 + 2 properly paired (98.02% : 66.67%)
198 + 2 with itself and mate mapped
2 + 0 singletons (0.99% : 0.00%)
0 + 0 with mate mapped to a different chr
0 + 0 with mate mapped to a different chr (mapQ>=5)
"""
VCF_STATS = """# This file was produced by bcftools stats (1.24)
ID\t0\tvariants.vcf.gz
SN\t0\tnumber of samples:\t1
SN\t0\tnumber of records:\t3
SN\t0\tnumber of no-ALTs:\t0
SN\t0\tnumber of SNPs:\t2
SN\t0\tnumber of MNPs:\t0
SN\t0\tnumber of indels:\t1
SN\t0\tnumber of others:\t0
SN\t0\tnumber of multiallelic sites:\t0
SN\t0\tnumber of multiallelic SNP sites:\t0
"""


class ResultsSummaryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="workbench results ")
        self.folder = Path(self.temporary.name)
        self.pin = {"packId": "bam", "packVersion": "0.4.0", "manifestSha256": "a" * 64}
        self.record = {"schema": 1, "run_id": "history-id", "id": "run-synthetic", "name": "Synthetic alignment + variants",
                       "folder": str(self.folder), "status": "completed", "methods": "Completed synthetic methods.\n",
                       "nodes": [], "outputs": {}, "batch": {"sampleId": "Specimen_A"}}
        self.plan = {"schema": 1, "id": self.record["id"], "folder": str(self.folder),
                     "methods": "Planned synthetic methods.\n", "nodes": []}
        self.add_step("step-1", "samtools", "stats", SAM_STATS)
        self.add_step("step-2", "samtools", "flagstat", FLAGSTAT)
        self.add_step("step-3", "bcftools", "stats", VCF_STATS)
        self.save_plan()
        (self.folder / "methods-planned.txt").write_text(self.plan["methods"], encoding="utf-8")
        (self.folder / "methods-completed.txt").write_text(self.record["methods"], encoding="utf-8")
        (self.folder / "run.json").write_text(json.dumps(self.record), encoding="utf-8")
        (self.folder / "workflow.cwl").write_text("{}", encoding="utf-8")

    def tearDown(self):
        self.temporary.cleanup()

    def add_step(self, identity, executable, command, report):
        step = self.folder / display_id(identity)
        step.mkdir()
        # The filename is deliberately unrelated: parser selection must use the
        # exact frozen stdout declaration rather than filename guessing.
        path = step / "scientific measurement.txt"
        path.write_bytes(report.encode())
        pack = "bam" if executable == "samtools" else "variants"
        pin = dict(self.pin, packId=pack)
        operation = pack + "/" + ("statistics" if executable == "samtools" and command == "stats" else command)
        tool = {"id": operation, **pin, "executables": [{"id": executable, "version": "1.24", "sha256": "b" * 64}],
                "params": [{"id": "sample", "binding": True}],
                "steps": [{"tool": executable, "args": [command, "{input:alignment}"], "stdout": "statistics"}],
                "outputs": [{"id": "metrics", "label": "Recorded measurements", "files": {"statistics": path.name}}]}
        self.plan["nodes"].append({"id": identity, "tool": tool, "params": {"sample": "Explicit_A"}})
        ref = identity + "::metrics"
        output = {"id": ref, "producer": identity, "files": {"statistics": str(path)},
                  "sha256": {"statistics": hashlib.sha256(path.read_bytes()).hexdigest()}}
        self.record["nodes"].append({"id": identity, "name": executable + " " + command, "tool": operation,
                                      "pin": pin, "status": "success", "folder": str(step), "outputs": {ref: copy.deepcopy(output)}})
        self.record["outputs"][ref] = output

    def save_plan(self):
        self.plan.pop("sha256", None)
        digest = hashlib.sha256(canonical(self.plan).encode()).hexdigest()
        self.record["planSha256"] = digest
        (self.folder / "plan.json").write_text(json.dumps(dict(self.plan, sha256=digest)), encoding="utf-8")

    def product_path(self, index=0):
        return Path(next(iter(self.record["nodes"][index]["outputs"].values()))["files"]["statistics"])

    def change_report(self, text, index=0):
        path = self.product_path(index)
        path.write_bytes(text.encode())
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        ref = self.record["nodes"][index]["id"] + "::metrics"
        self.record["nodes"][index]["outputs"][ref]["sha256"]["statistics"] = digest
        self.record["outputs"][ref]["sha256"]["statistics"] = digest

    def metrics(self, summary):
        return {item["id"]: item["value"] for item in summary["metrics"]}

    def codes(self, summary):
        return {item["code"] for item in summary["unavailable"]}

    def test_records_literal_measurements_identity_pins_and_exact_sources(self):
        summary = summaries.build_summary(self.record)
        values = self.metrics(summary)
        self.assertEqual(values["samtools.stats.raw_total_sequences"], 202)
        self.assertEqual(values["samtools.stats.reads_mapped"], 200)
        self.assertEqual(values["samtools.stats.reads_duplicated"], 8)
        self.assertEqual(values["samtools.stats.average_length"], 150.0)
        self.assertEqual(values["samtools.stats.error_rate"], .0066)
        self.assertEqual(values["samtools.flagstat.total.qc_passed"], 202)
        self.assertEqual(values["samtools.flagstat.total.qc_failed"], 3)
        self.assertEqual(values["samtools.flagstat.mapped.qc_passed"], 200)
        self.assertEqual(values["samtools.flagstat.mapped.qc_failed"], 2)
        self.assertEqual(values["bcftools.stats.number_of_records"], 3)
        self.assertEqual(values["bcftools.stats.number_of_snps"], 2)
        self.assertEqual(values["bcftools.stats.number_of_indels"], 1)
        self.assertEqual(summary["sample"]["identities"][0]["value"], "Specimen_A")
        self.assertIn("Explicit_A", [item["value"] for item in summary["sample"]["identities"]])
        self.assertEqual(summary["tools"][0]["pin"], self.pin)
        self.assertEqual(summary["tools"][0]["executables"][0]["version"], "1.24")
        for item in summary["metrics"]:
            self.assertEqual(hashlib.sha256(Path(item["source_path"]).read_bytes()).hexdigest(), item["sha256"])
        self.assertFalse(summary["unavailable"])
        self.assertIn("not a QC pass/fail assessment", summary["details"])
        self.assertNotIn("qc_status", summary)
        self.assertEqual([item["status"] for item in summary["artifacts"] if item["kind"].startswith("methods")], ["verified", "verified"])

    def test_changed_report_never_displays_old_or_new_numbers(self):
        self.product_path().write_text(SAM_STATS.replace("202", "999"))
        summary = summaries.build_summary(self.record)
        self.assertIn("changed_output", self.codes(summary))
        self.assertFalse(any(item["step_id"] == "step-1" for item in summary["metrics"]))
        self.assertIn("bcftools.stats.number_of_records", self.metrics(summary))
        self.assertIn("Restore the original bytes", summary["details"])

    def test_missing_file_is_unavailable_without_losing_other_reports(self):
        self.product_path().unlink()
        summary = summaries.build_summary(self.record)
        self.assertIn("missing_file", self.codes(summary))
        self.assertEqual(self.metrics(summary)["bcftools.stats.number_of_records"], 3)

    def test_malformed_partial_and_duplicate_summary_rows_are_not_zero(self):
        for bad in ("unrecognized text", SAM_STATS.replace("\t202\t", "\tnan\t"),
                    SAM_STATS + "SN\treads mapped:\t200\n", SAM_STATS.replace("SN\treads duplicated:\t8\n", "")):
            with self.subTest(text=bad):
                self.change_report(bad)
                summary = summaries.build_summary(self.record)
                self.assertIn("malformed_report", self.codes(summary))
                self.assertFalse(any(item["step_id"] == "step-1" for item in summary["metrics"]))

    def test_comparison_bcftools_stats_sets_are_explicitly_unsupported(self):
        self.change_report(VCF_STATS + "SN\t1\tnumber of records:\t10\n", 2)
        summary = summaries.build_summary(self.record)
        self.assertIn("malformed_report", self.codes(summary))
        self.assertFalse(any(item["id"].startswith("bcftools") for item in summary["metrics"]))

    def test_failed_step_does_not_use_even_hash_verified_output(self):
        self.record["nodes"][0].update(status="failed", message="Synthetic reference mismatch")
        self.record["status"] = "failed"
        summary = summaries.build_summary(self.record)
        self.assertIn("step_not_complete", self.codes(summary))
        self.assertFalse(any(item["step_id"] == "step-1" for item in summary["metrics"]))
        self.assertEqual(summary["failures"][0]["message"], "Synthetic reference mismatch")
        self.assertIn("correct the reported cause", summary["failures"][0]["action"])

    def test_missing_changed_malformed_and_unbound_plan_disable_metrics(self):
        path = self.folder / "plan.json"
        for mode in ("missing", "changed", "malformed", "duplicate", "unbound"):
            with self.subTest(mode=mode):
                self.save_plan()
                if mode == "missing":
                    path.unlink()
                elif mode == "changed":
                    value = json.loads(path.read_text())
                    value["nodes"][0]["params"]["sample"] = "Changed"
                    path.write_text(json.dumps(value))
                elif mode == "malformed":
                    path.write_text("{")
                elif mode == "duplicate":
                    path.write_text('{"nodes":[],"nodes":[]}')
                else:
                    self.record["planSha256"] = "f" * 64
                summary = summaries.build_summary(self.record)
                self.assertFalse(summary["metrics"])
                self.assertIn("no_metrics", self.codes(summary))
                self.assertEqual(summary["sample"]["identities"], [{"value": "Specimen_A", "source": "recorded sample table"}])

    def test_recorded_pin_and_global_output_must_match_frozen_step(self):
        self.record["nodes"][0]["pin"]["packVersion"] = "9.9.9"
        self.record["outputs"]["step-2::metrics"]["sha256"]["statistics"] = "c" * 64
        summary = summaries.build_summary(self.record)
        self.assertIn("step_mismatch", self.codes(summary))
        self.assertIn("unbound_output", self.codes(summary))
        self.assertTrue(all(item["step_id"] == "step-3" for item in summary["metrics"]))

    def test_report_size_and_aggregate_count_are_bounded(self):
        with patch.object(summaries, "MAX_REPORT_BYTES", 64):
            summary = summaries.build_summary(self.record)
        self.assertFalse(summary["metrics"])
        self.assertIn("read_limit", self.codes(summary))
        with patch.object(summaries, "MAX_REPORTS", 1):
            summary = summaries.build_summary(self.record)
        self.assertIn("report_limit", self.codes(summary))
        self.assertTrue(all(item["step_id"] == "step-1" for item in summary["metrics"]))
        with patch.object(summaries, "MAX_TOTAL_REPORT_BYTES", len(SAM_STATS.encode()) + 2):
            summary = summaries.build_summary(self.record)
        self.assertIn("read_limit", self.codes(summary))

    def test_report_path_cannot_escape_result_folder(self):
        with tempfile.TemporaryDirectory() as outside:
            path = Path(outside) / "outside.txt"
            path.write_text(SAM_STATS)
            for product in (self.record["outputs"]["step-1::metrics"], self.record["nodes"][0]["outputs"]["step-1::metrics"]):
                product["files"]["statistics"] = str(path)
            summary = summaries.build_summary(self.record)
            self.assertIn("unsafe_path", self.codes(summary))
            self.assertFalse(any(item["step_id"] == "step-1" for item in summary["metrics"]))

    def test_missing_identity_is_not_inferred_from_filename_or_run_name(self):
        self.record.pop("batch")
        for node in self.plan["nodes"]:
            node["params"].clear()
        self.save_plan()
        summary = summaries.build_summary(self.record)
        self.assertFalse(summary["sample"]["available"])
        self.assertEqual(summary["sample"]["identities"], [])
        self.assertIn("filenames are not sample identities", summary["sample"]["reason"])

    def test_changed_missing_methods_are_not_labelled_verified(self):
        (self.folder / "methods-planned.txt").write_text("Edited text")
        (self.folder / "methods-completed.txt").unlink()
        summary = summaries.build_summary(self.record)
        methods = [item for item in summary["artifacts"] if item["kind"].startswith("methods")]
        self.assertEqual([item["status"] for item in methods], ["unavailable", "unavailable"])
        self.assertIn("does not match", methods[0]["reason"])
        self.assertIn("missing", methods[1]["reason"])

    def test_failure_before_preparation_has_actionable_details(self):
        summary = summaries.build_summary({"run_id": "r", "name": "Failed preparation", "status": "failed", "message": "Reference is missing"})
        self.assertFalse(summary["metrics"])
        self.assertEqual(summary["failures"][0]["message"], "Reference is missing")
        self.assertIn("prepare", summary["unavailable"][0]["action"])

    def test_search_matches_metadata_terms_without_reading_any_file(self):
        self.record["graph"] = {"nodes": [{"id": "step-4", "tool": "align/paired-end", "params": {"sample": "ReadGroup_B"}}]}
        with patch.object(summaries, "_bounded_read", side_effect=AssertionError("Search must not read files")):
            entry = summaries.search_entry(self.record)
            for query in ("alignment", "specimen_a", "ReadGroup_B", "completed", "samtools", "bcftools", "minimap2", "COMPLETED specimen_A"):
                self.assertTrue(summaries.matches(entry, query), query)
            self.assertFalse(summaries.matches(entry, "failed"))
            self.assertFalse(summaries.matches(entry, "specimen_a absent"))
            self.assertTrue(summaries.matches(entry, "   "))
        with self.assertRaises(ValueError):
            summaries.matches(entry, "x" * 501)

    def test_summary_budget_omits_explicitly_and_does_not_read_scientific_inputs(self):
        with patch.object(summaries, "MAX_LIST_BYTES", 1000):
            summary = summaries.build_summary(self.record)
        self.assertTrue(summary["omitted"])
        self.assertIn("exceed the display limit", summary["details"])
        self.assertLess(len(json.dumps(summary)), 12000)

    def test_crlf_reports_and_methods_are_supported(self):
        self.change_report(SAM_STATS.replace("\n", "\r\n"))
        (self.folder / "methods-completed.txt").write_bytes(self.record["methods"].replace("\n", "\r\n").encode())
        summary = summaries.build_summary(self.record)
        self.assertFalse(summary["unavailable"])
        self.assertEqual(self.metrics(summary)["samtools.stats.reads_mapped"], 200)

    def test_malformed_recorded_steps_are_unavailable_without_crashing(self):
        for value in (None, [], {"id": "step-1", "tool": "bam/statistics", "status": []}):
            with self.subTest(value=value):
                malformed = copy.deepcopy(self.record)
                malformed["nodes"][0] = value
                malformed["status"] = []
                summary = summaries.build_summary(malformed)
                self.assertIn("malformed_step", self.codes(summary))
                self.assertFalse(any(item["step_id"] == "step-1" for item in summary["metrics"]))

    def test_oversized_or_duplicate_sample_declarations_cannot_expand_response(self):
        self.plan["nodes"][0]["tool"]["params"] *= 100
        self.save_plan()
        summary = summaries.build_summary(self.record)
        self.assertEqual(len(summary["sample"]["identities"]), 4)
        self.plan["nodes"][0]["tool"]["params"] *= 100
        self.save_plan()
        summary = summaries.build_summary(self.record)
        self.assertIn("malformed_plan", self.codes(summary))
        self.assertFalse(summary["metrics"])
        self.assertLess(len(json.dumps(summary)), 20000)

    def test_guidance_follows_recorded_failure_and_preserves_message(self):
        for status, message, phrase in (
                ("failed", "An external input changed after the plan was frozen", "original paths"),
                ("failed", "Select an existing ordinary file: missing.fastq", "original paths"),
                ("failed", "The installed operation differs from the frozen plan", "trusted pack version"),
                ("failed", "Insufficient disk space", "available space and write access"),
                ("blocked", "An upstream step did not complete", "failed upstream step"),
                ("cancelled", "User cancelled", "was cancelled"),
                ("interrupted", "Previous session ended", "restart eligibility")):
            with self.subTest(status=status, message=message):
                self.record["nodes"][0].update(status=status, message=message)
                summary = summaries.build_summary(self.record)
                self.assertEqual(summary["failures"][0]["message"], message)
                self.assertIn(phrase, summary["failures"][0]["action"])

    def test_search_carries_recorded_timestamp_and_bounded_metadata(self):
        self.record["started"] = "2026-10-09T10:00:00Z"
        self.record["graph"] = {"nodes": [{"tool": "align/paired-end", "params": {"sample": str(n) + "a" * 1990}}
                                         for n in range(100)]}
        entry = summaries.search_entry(self.record)
        self.assertEqual(entry["started_at"], self.record["started"])
        self.assertLessEqual(len(entry["sample"]), 8192)
        self.assertGreater(entry["metadata_omitted"], 0)

    def test_report_cannot_be_relabelled_as_another_steps_output(self):
        source = self.record["outputs"]["step-2::metrics"]
        for product in (self.record["outputs"]["step-1::metrics"], self.record["nodes"][0]["outputs"]["step-1::metrics"]):
            product["files"] = copy.deepcopy(source["files"])
            product["sha256"] = copy.deepcopy(source["sha256"])
        summary = summaries.build_summary(self.record)
        self.assertIn("unbound_output", self.codes(summary))
        self.assertFalse(any(item["step_id"] == "step-1" for item in summary["metrics"]))

    def test_path_creation_time_and_handle_change_time_may_differ(self):
        # Windows CPython issue #157671: path stat ctime is creation time while
        # handle fstat ctime is change time. Stable readings from the two APIs
        # must not be compared as though those timestamps mean the same thing.
        original_fstat = os.fstat
        def handle_stat(descriptor):
            value = original_fstat(descriptor)
            fields = {key: getattr(value, key) for key in
                      ("st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns")}
            fields["st_ctime_ns"] += 1000000000
            return SimpleNamespace(**fields)
        with patch.object(summaries.os, "fstat", side_effect=handle_stat):
            summary = summaries.build_summary(self.record)
        self.assertFalse(summary["unavailable"])
        self.assertEqual(self.metrics(summary)["samtools.stats.raw_total_sequences"], 202)
        self.assertEqual([item["status"] for item in summary["artifacts"] if item["kind"].startswith("methods")], ["verified", "verified"])

    def test_open_handle_still_must_match_path_identity_size_and_mtime(self):
        original_fstat = os.fstat
        for changed in ("st_dev", "st_ino", "st_size", "st_mtime_ns"):
            with self.subTest(field=changed):
                def handle_stat(descriptor):
                    value = original_fstat(descriptor)
                    fields = {key: getattr(value, key) for key in
                              ("st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns")}
                    fields[changed] += 1
                    return SimpleNamespace(**fields)
                with patch.object(summaries.os, "fstat", side_effect=handle_stat):
                    with self.assertRaises(summaries.Unavailable) as failure:
                        summaries._bounded_read(self.product_path(), 10000, self.folder)
                self.assertEqual(failure.exception.code, "changed_file")

    def test_same_handle_change_time_mutation_remains_rejected(self):
        original_fstat = os.fstat
        calls = 0
        def handle_stat(descriptor):
            nonlocal calls
            calls += 1
            value = original_fstat(descriptor)
            fields = {key: getattr(value, key) for key in
                      ("st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns")}
            fields["st_ctime_ns"] += calls
            return SimpleNamespace(**fields)
        with patch.object(summaries.os, "fstat", side_effect=handle_stat):
            with self.assertRaises(summaries.Unavailable) as failure:
                summaries._bounded_read(self.product_path(), 10000, self.folder)
        self.assertEqual(failure.exception.code, "changed_file")

    def test_actual_content_mutation_during_read_remains_rejected(self):
        path = self.product_path()
        before = path.stat()
        original_open = open
        class MutatingReader:
            def __init__(self, *args, **kwargs):
                self.stream = original_open(*args, **kwargs)
            def __enter__(self):
                return self
            def __exit__(self, *args):
                self.stream.close()
            def fileno(self):
                return self.stream.fileno()
            def read(self, limit):
                data = self.stream.read(limit)
                # Same-size alteration after the reader obtains the original
                # bytes: their SHA alone would miss this concurrent mutation.
                path.write_bytes(data.replace(b"202", b"999"))
                os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns + 2000000000))
                return data
        with patch.object(summaries, "open", MutatingReader, create=True):
            with self.assertRaises(summaries.Unavailable) as failure:
                summaries._bounded_read(path, 10000, self.folder)
        self.assertEqual(failure.exception.code, "changed_file")

    def test_native_metadata_after_prior_write_can_be_read_unchanged(self):
        # Runs on the actual platform, including both packaged Windows paths.
        # Prior changes can separate Windows creation time from change time;
        # an unchanged current report must nevertheless remain readable.
        path = self.product_path()
        expected = path.read_bytes()
        previous = path.stat()
        path.write_bytes(expected)
        os.utime(path, ns=(previous.st_atime_ns, previous.st_mtime_ns + 1000000000))
        self.assertEqual(summaries._bounded_read(path, 10000, self.folder), expected)


if __name__ == "__main__":
    unittest.main(verbosity=2)
