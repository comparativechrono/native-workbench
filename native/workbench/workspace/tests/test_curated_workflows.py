"""Training catalogue contracts and independent synthetic-data checks.

These source checks load published manifest text, but do not execute scientific
binaries. Exact packaged native Windows training runs are a separate gate.
"""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "workspace"))
from catalog import load_catalog, resolve_tool
from curated_workflows import list_catalogue, load_workflow
from engine import Engine


class CuratedWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="workbench curated ")
        self.root = Path(self.temp.name)
        shutil.copytree(ROOT / "examples/starter", self.root / "examples/starter")
        for identity in ("align", "bam", "variants"):
            target = self.root / "packs" / (identity + "-0.4.0")
            target.mkdir(parents=True)
            shutil.copyfile(ROOT / "pack-examples" / (identity + ".ini"), target / "pack.ini")
        self.catalog = load_catalog(self.root)
        self.assertEqual(self.catalog["errors"], [])

    def tearDown(self):
        self.temp.cleanup()

    def listing(self, catalog=None):
        return list_catalogue(self.root, self.catalog if catalog is None else catalog)

    def test_two_training_workflows_use_real_published_manifest_contracts(self):
        catalogue = self.listing()
        self.assertEqual([item["id"] for item in catalogue["workflows"]], ["alignment-qc", "variant-calling"])
        profile = json.loads((ROOT / "workspace/starter-check-profile.json").read_text())
        expected_pins = {pack["id"]: pack for pack in profile["packs"]}
        for item in catalogue["workflows"]:
            self.assertTrue(item["available"], item["issues"])
            graph = load_workflow(self.root, self.catalog, item["id"])
            self.assertEqual(len(graph["nodes"]), item["stepCount"])
            review = Engine(self.root, self.catalog).review(graph)
            self.assertTrue(review["valid"], review["issues"])
            for node in graph["nodes"]:
                pin = node["pin"]
                self.assertEqual(resolve_tool(self.catalog, node["tool"], pin)["manifestSha256"], pin["manifestSha256"])
                if pin["packId"] != "builtin":
                    expected = expected_pins[pin["packId"]]
                    self.assertEqual((pin["packVersion"], pin["manifestSha256"]),
                                     (expected["version"], expected["manifestSha256"]))

    def test_fixed_tool_versions_agree_with_the_published_manifests(self):
        for item in self.listing()["workflows"]:
            for requirement in item["requirements"]:
                declared = {tool["id"]: tool["version"] for tool in requirement["tools"]}
                observed = {}
                for operation in requirement["operations"]:
                    tool = resolve_tool(self.catalog, operation, {key: requirement[key] for key in
                                        ("packId", "packVersion", "manifestSha256")})
                    observed.update({executable["id"]: executable["version"] for executable in tool["executables"]})
                self.assertEqual(observed, declared)

    def test_catalogue_explains_inputs_answers_limits_and_exact_requirements(self):
        for entry in self.listing()["workflows"]:
            text = entry["details"]
            for expected in ("Synthetic training", "101", "100 bases", "3,000", "202 mapped",
                             "not QC pass thresholds", "MIT", "Manifest SHA-256", "2.28-r1209", "1.24"):
                self.assertIn(expected, text)
            self.assertIn("availabilityScope", self.listing())
            for field in entry["inputs"]:
                self.assertTrue(Path(field["path"]).is_absolute())
                self.assertTrue(field["available"])
                self.assertEqual(Path(field["path"]).stat().st_size, field["bytes"])
        variant = self.listing()["workflows"][1]
        self.assertIn("starter:1351 G>A", variant["details"])
        self.assertIn("genotype 1/1", variant["details"])
        self.assertIn("not a sample QC verdict", variant["details"])

    def test_newest_installed_version_cannot_silently_repin_training(self):
        old = self.catalog["tools"]["align/paired-end"]
        newer = copy.deepcopy(old)
        newer.update(packVersion="0.4.1", manifestSha256="a" * 64)
        self.catalog["tools"]["align/paired-end"] = newer
        self.catalog["toolVersions"]["align/paired-end"].insert(0, newer)
        graph = load_workflow(self.root, self.catalog, "alignment-qc")
        self.assertEqual(graph["nodes"][0]["pin"]["packVersion"], "0.4.0")
        self.assertEqual(graph["nodes"][0]["pin"]["manifestSha256"], old["manifestSha256"])
        self.catalog["toolVersions"]["align/paired-end"] = [newer]
        self.assertFalse(self.listing()["workflows"][0]["available"])
        with self.assertRaisesRegex(ValueError, "align 0.4.0"):
            load_workflow(self.root, self.catalog, "alignment-qc")

    def test_variant_dependency_is_optional_for_alignment_and_guidance_is_actionable(self):
        for key in ("tools", "toolVersions"):
            self.catalog[key] = {name: value for name, value in self.catalog[key].items()
                                 if not name.startswith("variants/")}
        alignment, variant = self.listing()["workflows"]
        self.assertTrue(alignment["available"])
        self.assertFalse(variant["available"])
        self.assertIn("Manage tools", " ".join(variant["issues"]))
        self.assertIn("native-workbench-pack-variants-0.4.0.zip", " ".join(variant["issues"]))
        load_workflow(self.root, self.catalog, "alignment-qc")
        with self.assertRaisesRegex(ValueError, "Missing exact dependency"):
            load_workflow(self.root, self.catalog, "variant-calling")

    def test_wrong_manifest_or_missing_operation_never_selects_another_tool(self):
        for mode in ("wrong-hash", "missing-operation", "ambiguous"):
            with self.subTest(mode=mode):
                catalog = copy.deepcopy(self.catalog)
                values = catalog["toolVersions"]["bam/prepare"]
                if mode == "wrong-hash":
                    values[0]["manifestSha256"] = "b" * 64
                elif mode == "ambiguous":
                    values.append(copy.deepcopy(values[0]))
                else:
                    values.clear()
                self.assertFalse(self.listing(catalog)["workflows"][0]["available"])
                with self.assertRaisesRegex(ValueError, "bam 0.4.0"):
                    load_workflow(self.root, catalog, "alignment-qc")

    def test_changed_missing_and_oversized_fixture_are_rejected_without_replacement(self):
        path = self.root / "examples/starter/reads1.fastq"
        original = path.read_bytes()
        for value in (None, original[:-1], b"X" + original[1:], b"x" * (1024 * 1024)):
            with self.subTest(length=None if value is None else len(value)):
                if value is None:
                    path.unlink(missing_ok=True)
                else:
                    path.write_bytes(value)
                entry = self.listing()["workflows"][0]
                self.assertFalse(entry["available"])
                self.assertIn("Restore examples/starter/reads1.fastq", " ".join(entry["issues"]))
                with self.assertRaisesRegex(ValueError, "original archive"):
                    load_workflow(self.root, self.catalog, "alignment-qc")
                self.assertEqual(path.read_bytes() if path.exists() else None, value)
        path.write_bytes(original)
        self.assertTrue(self.listing()["workflows"][0]["available"])

    def test_load_rechecks_fixture_after_successful_catalogue_review(self):
        self.assertTrue(self.listing()["workflows"][1]["available"])
        truth = self.root / "examples/starter/truth.json"
        truth.write_bytes(truth.read_bytes().replace(b"1351", b"1352"))
        with self.assertRaisesRegex(ValueError, "truth.json"):
            load_workflow(self.root, self.catalog, "variant-calling")

    def test_linked_fixture_is_not_read_even_if_its_bytes_match(self):
        original = self.root / "examples/starter/reference.fa"
        outside = self.root / "external-reference.fa"
        original.rename(outside)
        try:
            original.symlink_to(outside)
        except (OSError, NotImplementedError) as error:
            self.skipTest("Symlink privilege unavailable: " + str(error))
        self.assertFalse(self.listing()["workflows"][0]["available"])
        with self.assertRaisesRegex(ValueError, "linked fixture path"):
            load_workflow(self.root, self.catalog, "alignment-qc")

    def test_local_bounded_listing_and_loading_do_not_execute_download_or_mutate(self):
        before = {path.relative_to(self.root): hashlib.sha256(path.read_bytes()).hexdigest()
                  for path in self.root.rglob("*") if path.is_file()}
        with patch.object(socket, "socket", side_effect=AssertionError("Unexpected networking")), \
                patch.object(subprocess, "Popen", side_effect=AssertionError("Unexpected execution")):
            self.listing()
            load_workflow(self.root, self.catalog, "variant-calling")
        after = {path.relative_to(self.root): hashlib.sha256(path.read_bytes()).hexdigest()
                 for path in self.root.rglob("*") if path.is_file()}
        self.assertEqual(before, after)

    def test_graphs_have_explicit_parameters_independent_sources_and_safe_ids(self):
        first = load_workflow(self.root, self.catalog, "variant-calling")
        self.assertEqual(first["nodes"][2]["params"], {"ploidy": "2", "min-mapq": "20", "min-baseq": "20",
                                                     "max-depth": "1000", "min-qual": "20", "min-depth": "5"})
        first["nodes"][0]["params"]["sample"] = "edited"
        first["nodes"][0]["inputs"]["reads"].append("input-99")
        second = load_workflow(self.root, self.catalog, "variant-calling")
        self.assertEqual(second["nodes"][0]["params"]["sample"], "starter")
        self.assertEqual(second["nodes"][0]["inputs"]["reads"], ["input-1"])
        for identity in (None, [], {}, 1, "../starter", "", "x" * 81):
            with self.subTest(identity=identity), self.assertRaises(ValueError):
                load_workflow(self.root, self.catalog, identity)

    def test_known_answers_are_independently_grounded_in_artificial_input_sequences(self):
        folder = self.root / "examples/starter"
        fasta = (folder / "reference.fa").read_text().splitlines()
        self.assertEqual(fasta[0], ">starter")
        reference = "".join(fasta[1:])
        self.assertEqual(len(reference), 3000)
        self.assertEqual(reference[1350], "G")
        mutant = reference[:1350] + "A" + reference[1351:]
        reads = []
        for name in ("reads1.fastq", "reads2.fastq"):
            lines = (folder / name).read_text().splitlines()
            self.assertEqual(len(lines), 404)
            records = [lines[index:index + 4] for index in range(0, len(lines), 4)]
            self.assertEqual(len(records), 101)
            for label, sequence, plus, quality in records:
                self.assertTrue(label.startswith("@starter-"))
                self.assertEqual(plus, "+")
                self.assertEqual(len(sequence), 100)
                self.assertEqual(quality, "I" * 100)
                forward = sequence if name == "reads1.fastq" else sequence.translate(str.maketrans("ACGT", "TGCA"))[::-1]
                self.assertIn(forward, mutant)
            reads.append(records)
        for first, second in zip(*reads):
            self.assertEqual(first[0][:-2], second[0][:-2])
            self.assertTrue(first[0].endswith("/1") and second[0].endswith("/2"))
        self.assertEqual(sum(len(row[1]) for mate in reads for row in mate), 20200)


if __name__ == "__main__":
    unittest.main()
