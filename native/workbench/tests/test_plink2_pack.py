#!/usr/bin/env python3
"""Independent diploid genotype arithmetic and exact PLINK 2 pack regressions."""
import argparse
import configparser
import gzip
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
PACK = None
BUILD = ROOT / "build/plink2-linux"
EXECUTIONS = []
VERSION = "2.0.0-a.7.12"
SOURCE_COMMIT = "5c1f185d4144e62fa23087d68760162f712cd2a8"


def sha(path):
    result = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for part in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(part)
    return result.hexdigest()


def inventory(path):
    return {p.relative_to(path).as_posix(): sha(p) for p in Path(path).rglob("*") if p.is_file()}


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    loaded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loaded)
    return loaded


FIXTURE = module("independent_plink2_fixtures", ROOT / "tools/plink2/fixtures.py")


def table(path):
    lines = Path(path).read_text(encoding="ascii").splitlines()
    header = lines[0].lstrip("#").split()
    rows = [line.split() for line in lines[1:] if line]
    if any(len(row) != len(header) for row in rows):
        raise AssertionError("Unexpected PLINK table structure: " + str(path))
    return [dict(zip(header, row)) for row in rows]


class SourceTests(unittest.TestCase):
    def test_fixture_bytes_and_independent_integer_truth(self):
        fixture_root = ROOT / "tools/plink2/fixtures"
        with tempfile.TemporaryDirectory() as directory:
            truth = FIXTURE.fixtures(directory)
            for path in Path(directory).iterdir():
                self.assertEqual(path.read_bytes(), (fixture_root / path.name).read_bytes())
        self.assertEqual([v["alternateAlleles"] for v in truth["variants"]], [0, 8, 2, 0, 3, 5])
        self.assertEqual([v["observedAlleles"] for v in truth["variants"]], [8, 8, 6, 0, 6, 6])
        self.assertEqual([v["homRef"] for v in truth["variants"]], [4, 0, 1, 0, 1, 0])
        self.assertEqual([v["heterozygous"] for v in truth["variants"]], [0, 0, 2, 0, 1, 1])
        self.assertEqual([v["homAlt"] for v in truth["variants"]], [0, 4, 0, 0, 1, 2])
        self.assertEqual(list(truth["sampleMissing"].values()), [1, 2, 2, 2])

    def test_one_bounded_operation_and_both_executables_are_recorded(self):
        import prepare_plink2_pack as prep
        workflows, schema = prep.definitions()
        self.assertEqual([w["id"] for w in workflows], ["summarize-vcf"])
        self.assertEqual({step["tool"] for step in workflows[0]["steps"]}, {"plink2", "plink2-adapter"})
        metadata = schema["workflows"]["summarize-vcf"]
        self.assertEqual(metadata["ports"][0]["type"], "vcf")
        self.assertTrue(metadata["pathPolicy"]["asciiOnly"])


class ScientificTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.base = PACK if PACK else BUILD
        cls.bin = cls.base / "bin" if PACK else cls.base
        suffix = ".exe" if os.name == "nt" else ""
        cls.guard = cls.bin / ("plink2-guard" + suffix)
        cls.binary = cls.bin / ("plink2" + suffix)
        cls.fixtures = PACK / "fixtures" if PACK else ROOT / "tools/plink2/fixtures"
        cls.truth = json.loads((cls.fixtures / "truth.json").read_text())
        cls.before = inventory(cls.base)

    @classmethod
    def tearDownClass(cls):
        if inventory(cls.base) != cls.before:
            raise AssertionError("Installed pack/build changed during execution")

    def setUp(self):
        parent = ROOT / "build/plink2-tests"
        parent.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix="scientific spaces ", dir=parent)
        self.directory = Path(self.temp.name)
        self.counter = 0

    def tearDown(self):
        self.temp.cleanup()

    def source(self, content, name="selected genotypes.vcf"):
        path = self.directory / name
        path.write_bytes(content if isinstance(content, bytes) else content.encode("ascii"))
        return path

    def run_tool(self, source=None, success=True):
        source = source or self.fixtures / "genotypes.vcf"
        output = self.directory / f"run {self.counter}"
        self.counter += 1
        output.mkdir()
        before = sha(source)
        child = subprocess.run([str(self.guard.resolve()), str(source.resolve()), str(output.resolve())],
                               capture_output=True, text=True, timeout=120)
        EXECUTIONS.append({"inputSha256": before, "returncode": child.returncode,
                           "expectedSuccess": success, "stdout": child.stdout, "stderr": child.stderr})
        self.assertEqual(sha(source), before, "Selected input was modified")
        if success:
            self.assertEqual(child.returncode, 0, child.stdout + child.stderr)
            for name in ["plink.afreq", "plink.gcount", "plink.smiss", "plink.vmiss", "summary.json", "settings.json", "plink.log", "adapter.log"]:
                self.assertTrue((output / name).is_file(), name)
        else:
            self.assertNotEqual(child.returncode, 0, child.stdout + child.stderr)
            self.assertIn("PLINK2 pack:", child.stderr)
            self.assertFalse((output / "summary.json").exists())
        return output, child

    def assert_truth(self, output):
        truth = self.truth
        expected_ids = [row["id"] for row in truth["variants"]]
        for suffix in ["afreq", "gcount", "vmiss"]:
            self.assertEqual([row["ID"] for row in table(output / ("plink." + suffix))], expected_ids)
        for row, expected in zip(table(output / "plink.afreq"), truth["variants"]):
            self.assertEqual(row["CHROM"], expected["chromosome"])
            self.assertEqual(row["REF"], expected["reference"])
            self.assertEqual(row["ALT"], expected["alternate"])
            self.assertEqual(int(row["OBS_CT"]), expected["observedAlleles"])
            if expected["alternateFrequency"] is None:
                self.assertIn(row["ALT_FREQS"].lower(), {"nan", "-nan", "na", "."})
            else:
                # PLINK writes six significant digits, not full binary doubles.
                self.assertAlmostEqual(float(row["ALT_FREQS"]), expected["alternateFrequency"], delta=0.0000006)
        for row, expected in zip(table(output / "plink.gcount"), truth["variants"]):
            self.assertEqual(int(row["HOM_REF_CT"]), expected["homRef"])
            self.assertEqual(int(row["HET_REF_ALT_CTS"]), expected["heterozygous"])
            self.assertEqual(int(row["HOM_ALT1_CT"]), expected["homAlt"])
            self.assertEqual(int(row["MISSING_CT"]), expected["missing"])
        for row, expected in zip(table(output / "plink.vmiss"), truth["variants"]):
            self.assertEqual(int(row["MISSING_CT"]), expected["missing"])
            self.assertEqual(int(row["OBS_CT"]), len(truth["samples"]))
            self.assertAlmostEqual(float(row["F_MISS"]), expected["missingFraction"], places=6)
        samples = table(output / "plink.smiss")
        self.assertEqual([row["IID"] for row in samples], truth["samples"])
        for row in samples:
            self.assertEqual(int(row["MISSING_CT"]), truth["sampleMissing"][row["IID"]])
            self.assertEqual(int(row["OBS_CT"]), len(truth["variants"]))
            self.assertAlmostEqual(float(row["F_MISS"]), truth["sampleMissing"][row["IID"]] / 6, delta=0.0000006)
        summary = json.loads((output / "summary.json").read_text())
        for key, expected in {"samples": 4, "variants": 6, "totalGenotypes": 24, "calledGenotypes": 17,
                              "missingGenotypes": 7, "observedAlleles": 34, "alternateAlleles": 18}.items():
            self.assertEqual(summary[key], expected, key)
        self.assertAlmostEqual(summary["missingFraction"], 7 / 24, delta=0.0000006)
        self.assertIn("no QC pass thresholds", summary["interpretation"])

    def test_01_independent_allele_genotype_missingness_truth(self):
        output, _ = self.run_tool()
        self.assert_truth(output)

    def test_02_direct_unmodified_upstream_and_explicit_settings(self):
        version = subprocess.run([str(self.binary), "--version"], capture_output=True, text=True, check=True)
        self.assertIn(VERSION, version.stdout + version.stderr)
        output, _ = self.run_tool()
        settings = json.loads((output / "settings.json").read_text())
        for key, expected in {"tool": "PLINK2", "version": VERSION, "threads": 1, "memoryMiB": 640,
                              "memoryIsWholeProcessLimit": False, "filtersApplied": False,
                              "allSamplesIncluded": True, "phaseUsed": False}.items():
            self.assertEqual(settings[key], expected, key)
        arguments = settings["args"][:]
        if arguments[0] != str(self.binary.resolve()):
            self.assertEqual(Path(arguments[0]).resolve(), self.binary.resolve())
        direct = self.directory / "direct upstream"
        arguments[arguments.index("--out") + 1] = str(direct)
        child = subprocess.run(arguments, capture_output=True, text=True, timeout=90)
        self.assertEqual(child.returncode, 0, child.stdout + child.stderr)
        for suffix in ["afreq", "gcount", "smiss", "vmiss"]:
            self.assertEqual(table(str(direct) + "." + suffix), table(output / ("plink." + suffix)))
        EXECUTIONS.append({"kind": "direct-unmodified-upstream", "returncode": child.returncode,
                           "binarySha256": sha(self.binary), "tableComparisons": 4})

    def test_03_vcf43_crlf_and_filter_labels_do_not_filter_records(self):
        content = FIXTURE.vcf(version="4.3").replace("\tPASS\t", "\tLowQual\t")
        content = content.replace("##FORMAT=", '##FILTER=<ID=LowQual,Description="Synthetic label; not a selection">\n##FORMAT=')
        source = self.source(content.replace("\n", "\r\n"))
        output, _ = self.run_tool(source)
        self.assert_truth(output)

    def test_04_minimum_two_samples_one_variant_and_phase_invariance(self):
        outputs = []
        for genotypes in [["0/1", "1/1"], ["1|0", "1|1"]]:
            source = self.source(FIXTURE.vcf(samples=["a", "b"], variants=[("1", 1, "v1", "A", "C", genotypes)]))
            output, _ = self.run_tool(source)
            outputs.append(output)
            row = table(output / "plink.afreq")[0]
            self.assertEqual(int(row["OBS_CT"]), 4)
            self.assertEqual(float(row["ALT_FREQS"]), 0.75)
        for suffix in ["afreq", "gcount", "smiss", "vmiss"]:
            self.assertEqual(table(outputs[0] / ("plink." + suffix)), table(outputs[1] / ("plink." + suffix)))

    def test_05_maximum_sample_count_is_accepted(self):
        samples = [f"s{index}" for index in range(1000)]
        source = self.source(FIXTURE.vcf(samples=samples, variants=[("22", 1, "v1", "A", "C", ["0/1"] * 1000)]))
        output, _ = self.run_tool(source)
        row = table(output / "plink.afreq")[0]
        self.assertEqual(int(row["OBS_CT"]), 2000)
        self.assertEqual(float(row["ALT_FREQS"]), 0.5)
        self.assertEqual([row["IID"] for row in table(output / "plink.smiss")], samples)

    def test_05b_all_missing_dataset_reports_undefined_frequency(self):
        source = self.source(FIXTURE.vcf(samples=["a", "b"], variants=[("1", 1, "v1", "A", "C", ["./.", ".|."])]))
        output, _ = self.run_tool(source)
        frequency = table(output / "plink.afreq")[0]
        self.assertEqual(int(frequency["OBS_CT"]), 0)
        self.assertIn(frequency["ALT_FREQS"].lower(), {"nan", "-nan", "na", "."})
        counts = table(output / "plink.gcount")[0]
        self.assertEqual(int(counts["MISSING_CT"]), 2)
        summary = json.loads((output / "summary.json").read_text())
        for key, expected in {"totalGenotypes": 2, "calledGenotypes": 0, "missingGenotypes": 2,
                              "observedAlleles": 0, "alternateAlleles": 0, "missingFraction": 1.0}.items():
            self.assertEqual(summary[key], expected, key)

    def test_06_invalid_vcf_structure_and_unsupported_variants_reject(self):
        good = FIXTURE.vcf()
        cases = {"empty": b"", "gzip": gzip.compress(good.encode("ascii")),
                 "version": good.replace("VCFv4.2", "VCFv4.1"),
                 "no-header": "\n".join(line for line in good.splitlines() if not line.startswith("#CHROM")) + "\n",
                 "no-records": "\n".join(line for line in good.splitlines() if line.startswith("#")) + "\n",
                 "wrong-chromosome": good.replace("1\t101\t", "X\t101\t"),
                 "zero-position": good.replace("1\t101\t", "1\t0\t"),
                 "indel": good.replace("\tA\tG\t", "\tAA\tG\t", 1),
                 "symbolic": good.replace("\tA\tG\t", "\tA\t<DEL>\t", 1),
                 "multiallelic": good.replace("\tA\tG\t", "\tA\tG,C\t", 1),
                 "ambiguous-base": good.replace("\tA\tG\t", "\tN\tG\t", 1),
                 "extra-format": good.replace("\tGT\t", "\tGT:DS\t", 1),
                 "too-few-columns": good.replace("\t0/0\t0|0\t0/0\t0/0", "\t0/0\t0|0\t0/0", 1)}
        for name, content in cases.items():
            with self.subTest(case=name):
                output, _ = self.run_tool(self.source(content), success=False)
                self.assertFalse((output / "plink.afreq").exists())

    def test_07_unsupported_genotypes_reject_before_scientific_execution(self):
        for genotype in ["0", ".", "0/.", "./1", ".|0", "1|.", "0/2", "0/0/1", "0:0", "-1/0", "A/G"]:
            with self.subTest(genotype=genotype):
                content = FIXTURE.vcf(samples=["a", "b"], variants=[("1", 1, "v1", "A", "C", [genotype, "0/1"])])
                output, _ = self.run_tool(self.source(content), success=False)
                self.assertFalse((output / "plink.afreq").exists())

    def test_08_duplicate_unsafe_and_oversized_ids_reject(self):
        good = FIXTURE.vcf()
        cases = {"duplicate-sample": good.replace("\t001\t", "\tz-last\t"),
                 "zero-sample": good.replace("\t001\t", "\t0\t"),
                 "duplicate-variant": good.replace("alternate_only", "reference_only"),
                 "empty-variant": good.replace("reference_only", "."),
                 "unsafe-sample": good.replace("under_score", "unsafe|sample"),
                 "unsafe-variant": good.replace("reference_only", "unsafe;variant"),
                 "long-sample": good.replace("under_score", "s" * 129),
                 "long-variant": good.replace("reference_only", "v" * 129),
                 "nonascii": good.encode("ascii").replace(b"under_score", b"s\xff")}
        for name, content in cases.items():
            with self.subTest(case=name):
                self.run_tool(self.source(content), success=False)

    def test_09_declared_input_bounds_reject(self):
        for count in [1, 1001]:
            with self.subTest(samples=count):
                content = FIXTURE.vcf(samples=[f"s{i}" for i in range(count)], variants=[("1", 1, "v1", "A", "C", ["0/1"] * count)])
                self.run_tool(self.source(content), success=False)
        for count, samples in [(100001, 2), (10001, 1000)]:
            with self.subTest(variants=count, samples=samples):
                path = self.directory / "large-count.vcf"
                with path.open("wb") as stream:
                    stream.write(FIXTURE.vcf(samples=[f"s{i}" for i in range(samples)], variants=[]).encode("ascii"))
                    for index in range(count):
                        row = f"1\t{index+1}\tv{index}\tA\tC\t.\tPASS\t.\tGT" + "\t0/1" * samples + "\n"
                        stream.write(row.encode("ascii"))
                self.run_tool(path, success=False)
        path = self.directory / "too-large.vcf"
        with path.open("wb") as stream:
            stream.truncate(64 * 1024 * 1024 + 1)
        self.run_tool(path, success=False)

    def test_10_space_paths_work_and_nonascii_paths_reject(self):
        path = self.source(FIXTURE.vcf(), "input with spaces.vcf")
        output, _ = self.run_tool(path)
        self.assert_truth(output)
        other = self.directory / "input \u00e9.vcf"
        shutil.copyfile(path, other)
        _, child = self.run_tool(other, success=False)
        self.assertIn("ASCII", child.stderr)

    def test_11_existing_results_are_not_overwritten(self):
        output, _ = self.run_tool()
        before = inventory(output)
        child = subprocess.run([str(self.guard), str(self.fixtures / "genotypes.vcf"), str(output)], capture_output=True, text=True, timeout=30)
        self.assertNotEqual(child.returncode, 0)
        self.assertIn("fresh output folder", child.stderr)
        self.assertEqual(inventory(output), before)

    def test_12_missing_scientific_binary_gives_reinstallation_guidance(self):
        isolated = self.directory / "incomplete installation"
        isolated.mkdir()
        guard = isolated / self.guard.name
        shutil.copyfile(self.guard, guard)
        guard.chmod(0o755)
        output = self.directory / "missing child"
        output.mkdir()
        child = subprocess.run([str(guard), str(self.fixtures / "genotypes.vcf"), str(output)], capture_output=True, text=True, timeout=30)
        self.assertNotEqual(child.returncode, 0)
        self.assertIn("reinstall this pack", child.stderr)
        self.assertFalse((output / "summary.json").exists())

    def test_13_repeated_execution_is_deterministic(self):
        first, _ = self.run_tool()
        second, _ = self.run_tool()
        for filename in ["plink.afreq", "plink.gcount", "plink.smiss", "plink.vmiss", "summary.json"]:
            self.assertEqual((first / filename).read_bytes(), (second / filename).read_bytes())

    def test_14_declared_checks_and_complete_installed_hashes(self):
        import prepare_plink2_pack as prep
        checks = prep.checks()
        if PACK:
            config = configparser.ConfigParser(interpolation=None)
            config.read(PACK / "pack.ini", encoding="utf-8")
            self.assertEqual(config["pack"]["version"], "1.0.0")
            for section in config.sections():
                if section.startswith(("tool:", "asset:")):
                    self.assertEqual(sha(PACK / config[section]["path"]), config[section]["sha256"])
            checks = json.loads((PACK / "workbench-checks.json").read_text())
            sys.path.insert(0, str(ROOT / "workspace"))
            from catalog import load_pack, describe_workflow
            pack = load_pack(PACK / "pack.ini")
            for workflow in pack["workflows"].values():
                described = describe_workflow(pack, workflow, str(PACK), pack["manifestSha256"])
                self.assertEqual({tool["id"] for tool in described["executables"]}, {"plink2", "plink2-adapter"})
        self.assertEqual({check["workflow"] for check in checks["checks"]}, {"summarize-vcf"})
        output, _ = self.run_tool()
        self.assert_truth(output)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pack", type=Path)
    parser.add_argument("--build", type=Path, default=BUILD)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    PACK = args.pack.resolve() if args.pack else None
    BUILD = args.build.resolve()
    if os.name == "nt" and not PACK:
        parser.error("Native Windows tests require the exact installed --pack")
    selected = (PACK / "bin" if PACK else BUILD) / ("plink2-guard.exe" if os.name == "nt" else "plink2-guard")
    binary = selected.parent / ("plink2.exe" if os.name == "nt" else "plink2")
    if not selected.is_file() or not binary.is_file():
        parser.error("Selected compiled PLINK2 and guard are required: " + str(selected.parent))
    started = time.monotonic()
    suite = unittest.TestSuite(unittest.defaultTestLoader.loadTestsFromTestCase(cls) for cls in [SourceTests, ScientificTests])
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    evidence = {"schema": 1, "packId": "plink2", "packVersion": "1.0.0", "toolVersion": VERSION,
                "platform": sys.platform, "nativeWindowsExecuted": os.name == "nt",
                "testsRun": result.testsRun, "failures": len(result.failures), "errors": len(result.errors),
                "skipped": [{"test": str(test), "reason": reason} for test, reason in result.skipped],
                "success": result.wasSuccessful(), "seconds": round(time.monotonic() - started, 3),
                "testSourceSha256": sha(__file__), "guardExecutableSha256": sha(selected),
                "scientificBinarySha256": sha(binary), "packManifestSha256": sha(PACK / "pack.ini") if PACK else None,
                "upstreamSourceCommit": SOURCE_COMMIT, "executions": EXECUTIONS,
                "scope": "Independent synthetic diploid biallelic SNP allele/genotype/missingness counts and denominators; direct bundled unmodified upstream execution; bounded input rejection; input/installation immutability and repeated runs. No PCA, association, filtering, scientific benchmark, GUI, population or clinical claim."}
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
    sys.exit(not result.wasSuccessful())
