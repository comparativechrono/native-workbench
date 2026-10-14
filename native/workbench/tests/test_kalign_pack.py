#!/usr/bin/env python3
"""Independent Kalign indel truth, upstream comparison and bounded native regressions."""
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
import build_kalign_native as builder

PACK = None
BUILD = ROOT / "build/kalign-linux"
REFERENCE_BINARY = ROOT / "build/kalign-reference-linux/kalign"
EXECUTIONS = []
LIVE_REFERENCE = None


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for part in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(part)
    return digest.hexdigest()


def inventory(path):
    return {p.relative_to(path).as_posix(): sha(p) for p in Path(path).rglob("*") if p.is_file()}


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def fasta(path):
    rows, headers = {}, {}
    name = None
    for line in Path(path).read_text(encoding="ascii").splitlines():
        if line.startswith(">"):
            name = line[1:].split()[0]
            if name in rows:
                raise ValueError("Duplicate FASTA identifier")
            rows[name] = ""
            headers[name] = line[1:]
        elif line:
            if name is None:
                raise ValueError("Missing FASTA header")
            rows[name] += line
    return rows, headers


class SourceTests(unittest.TestCase):
    def test_independent_fixture_construction_and_locked_reference(self):
        fixtures = ROOT / "tools/kalign/fixtures"
        generator = module("kalign_fixtures", ROOT / "tools/kalign/fixtures.py")
        with tempfile.TemporaryDirectory() as directory:
            generator.fixtures(directory)
            for path in Path(directory).iterdir():
                self.assertEqual(path.read_bytes(), (fixtures / path.name).read_bytes())
        reference = json.loads((fixtures / "reference.json").read_text())
        self.assertEqual(reference["sourceCommit"], builder.SOURCE_COMMIT)
        self.assertEqual(reference["sourceArchiveSha256"], builder.SOURCE_SHA256)
        for datatype, case in reference["cases"].items():
            self.assertEqual(case["fixtureSha256"], sha(fixtures / f"{datatype}.fa"))
            self.assertEqual(case["truthSha256"], sha(fixtures / f"{datatype}-truth.afa"))
            self.assertEqual(case["alignment"], fasta(fixtures / f"{datatype}-truth.afa")[0])

    def test_explicit_typed_operations_and_exact_scientific_executables(self):
        import prepare_kalign_pack as prep
        workflows, schema = prep.definitions()
        self.assertEqual([w["id"] for w in workflows], ["align-nucleotide", "align-protein"])
        for workflow in workflows:
            datatype = workflow["id"].removeprefix("align-")
            metadata = schema["workflows"][workflow["id"]]
            self.assertEqual(metadata["ports"][0]["type"], "fasta-" + datatype)
            self.assertEqual(metadata["outputs"][0]["type"], "msa-" + datatype)
            self.assertTrue(metadata["pathPolicy"]["asciiOnly"])
            self.assertEqual({step["tool"] for step in workflow["steps"]}, {"kalign", "kalign-adapter"})


class ScientificTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.base = PACK if PACK else BUILD
        cls.bin = cls.base / "bin" if PACK else cls.base
        suffix = ".exe" if os.name == "nt" else ""
        cls.guard, cls.binary = cls.bin / ("kalign-guard" + suffix), cls.bin / ("kalign" + suffix)
        cls.fixtures = PACK / "fixtures" if PACK else ROOT / "tools/kalign/fixtures"
        cls.truth = json.loads((cls.fixtures / "truth.json").read_text())["cases"]
        cls.reference = json.loads((cls.fixtures / "reference.json").read_text())
        cls.before = inventory(cls.base)

    @classmethod
    def tearDownClass(cls):
        if inventory(cls.base) != cls.before:
            raise AssertionError("Installed pack/build was changed during checks")

    def setUp(self):
        parent = ROOT / "build/kalign-tests"
        parent.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix="scientific spaces ", dir=parent)
        self.directory = Path(self.temp.name)
        self.counter = 0

    def tearDown(self):
        self.temp.cleanup()

    def source(self, text, name="sequences.fa"):
        source = self.directory / name
        source.write_bytes(text if isinstance(text, bytes) else text.encode("ascii"))
        return source

    def run_tool(self, datatype="nucleotide", source=None, success=True):
        source = source or self.fixtures / (datatype + ".fa")
        output = self.directory / f"run {self.counter}"
        self.counter += 1
        output.mkdir()
        before = sha(source)
        arguments = [str(self.guard.resolve()), str(source.resolve()), str(output.resolve()), datatype]
        child = subprocess.run(arguments, capture_output=True, text=True, timeout=90)
        EXECUTIONS.append({"datatype": datatype, "inputSha256": before,
                           "returncode": child.returncode, "expectedSuccess": success,
                           "stdout": child.stdout, "stderr": child.stderr})
        self.assertEqual(sha(source), before, "User input was modified")
        if success:
            self.assertEqual(child.returncode, 0, child.stdout + child.stderr)
            self.assertTrue((output / "alignment.afa").is_file())
        else:
            self.assertNotEqual(child.returncode, 0)
            self.assertFalse((output / "alignment.afa").exists())
            self.assertIn("Kalign pack:", child.stderr)
        return output, child

    def assert_preserved(self, source, output):
        inputs, headers = fasta(source)
        aligned, actual_headers = fasta(output / "alignment.afa")
        self.assertEqual(list(aligned), list(inputs))
        self.assertEqual(actual_headers, headers)
        self.assertEqual({name: row.replace("-", "") for name, row in aligned.items()},
                         {name: row.upper() for name, row in inputs.items()})
        self.assertEqual(len({len(row) for row in aligned.values()}), 1)
        self.assertFalse(any(all(residue == "-" for residue in column)
                             for column in zip(*aligned.values())))
        return aligned

    def assert_measurements(self, source, output, datatype):
        inputs, _ = fasta(source)
        aligned = self.assert_preserved(source, output)
        report = json.loads((output / "alignment-summary.json").read_text())
        canonical = "ACGTU" if datatype == "nucleotide" else "ACDEFGHIKLMNPQRSTVWY"
        expected = {
            "sequences": len(inputs), "inputResidues": sum(map(len, inputs.values())),
            "minInputLength": min(map(len, inputs.values())),
            "maxInputLength": max(map(len, inputs.values())),
            "columns": len(next(iter(aligned.values()))),
            "gapCharacters": sum(row.count("-") for row in aligned.values()),
            "allGapColumns": 0,
            "ambiguityCharacters": sum(c.upper() not in canonical for row in inputs.values() for c in row),
            "preservedUngappedResidues": True, "preservedInputOrder": True,
        }
        for key, value in expected.items():
            self.assertEqual(report[key], value, key)
        self.assertIn("no QC pass thresholds", report["interpretation"])
        return report

    def test_01_known_indel_homology_for_both_explicit_types(self):
        for datatype in ["nucleotide", "protein"]:
            with self.subTest(datatype=datatype):
                source = self.fixtures / f"{datatype}.fa"
                output, _ = self.run_tool(datatype, source)
                expected = fasta(self.fixtures / f"{datatype}-truth.afa")[0]
                self.assertEqual(self.assert_preserved(source, output), expected)
                self.assertEqual(expected, self.reference["cases"][datatype]["alignment"])
                report = self.assert_measurements(source, output, datatype)
                for key in ["sequences", "inputResidues", "columns", "gapCharacters"]:
                    self.assertEqual(report[key], self.truth[datatype][key])

    def test_02_actual_bundled_upstream_matches_guard_and_records_type(self):
        version = subprocess.run([str(self.binary), "--version"], capture_output=True, text=True, check=True)
        self.assertIn(builder.VERSION, version.stdout + version.stderr)
        for datatype, upstream_type in [("nucleotide", "dna"), ("protein", "protein")]:
            with self.subTest(datatype=datatype):
                output, _ = self.run_tool(datatype)
                settings = json.loads((output / "analysis-settings.json").read_text())
                for key, expected in {"tool": "Kalign", "version": builder.VERSION,
                                      "datatype": datatype, "upstreamType": upstream_type,
                                      "mode": "default", "threads": 1, "serial": True,
                                      "ensembleRuns": 0, "refinement": "none"}.items():
                    self.assertEqual(settings[key], expected)
                self.assertEqual(settings["consistencyAnchors"], 5)
                self.assertEqual(settings["consistencyWeight"], 2.0)
                arguments = settings["argv"][:]
                direct = self.directory / f"{datatype} direct.afa"
                arguments[arguments.index("-o") + 1] = str(direct)
                child = subprocess.run(arguments, capture_output=True, text=True, timeout=60)
                self.assertEqual(child.returncode, 0, child.stdout + child.stderr)
                self.assertEqual(fasta(direct)[0], fasta(output / "kalign-work/alignment.afa")[0])

    def test_03_crlf_lowercase_wrapping_descriptions_ids_and_order(self):
        rows, _ = fasta(self.fixtures / "nucleotide.fa")
        names = ["z-last", "001", "-hyphen", "a.dot", "under_score", "B"]
        source = self.source("".join(
            f">{name}\tdescription {index}\r\n{row[:120].lower()}\r\n{row[120:].lower()}\r\n"
            for index, (name, row) in enumerate(zip(names, reversed(list(rows.values()))))))
        output, _ = self.run_tool(source=source)
        self.assert_measurements(source, output, "nucleotide")
        mapping = json.loads((output / "analysis-settings.json").read_text())["sequenceMapping"]
        self.assertEqual([m["originalId"] for m in mapping], names)
        self.assertEqual([m["stagedId"] for m in mapping], [f"S{i:06}" for i in range(1, 7)])

    def test_04_repeated_sequences_remain_distinct_records(self):
        for datatype, sequence in [("nucleotide", "ACGT" * 25), ("protein", "MELKQW" * 15)]:
            with self.subTest(datatype=datatype):
                source = self.source("".join(f">same_{i}\n{sequence}\n" for i in range(4)))
                output, _ = self.run_tool(datatype, source)
                self.assertEqual(list(self.assert_preserved(source, output).values()), [sequence] * 4)
                self.assert_measurements(source, output, datatype)

    def test_05_minimum_two_records_one_residue(self):
        for datatype, letter in [("nucleotide", "A"), ("protein", "W")]:
            with self.subTest(datatype=datatype):
                source = self.source(f">a\n{letter}\n>b\n{letter}\n")
                output, _ = self.run_tool(datatype, source)
                self.assertEqual(self.assert_preserved(source, output), {"a": letter, "b": letter})
                self.assert_measurements(source, output, datatype)

    def test_06_ambiguity_heavy_nucleotide_and_rna_preserve_symbols(self):
        for sequence in ["NNRYSMWKBDHV" * 8, "AUGCURYSWKMBDHVN" * 8, "N", "U"]:
            with self.subTest(sequence=sequence[:16]):
                source = self.source(f">a\n{sequence}\n>b\n{sequence}\n")
                output, _ = self.run_tool(source=source)
                self.assert_measurements(source, output, "nucleotide")
                self.assertIn("explicit nucleotide alphabet selected", (output / "kalign.log").read_text())

    def test_07_explicit_acgt_only_protein_and_supported_ambiguities(self):
        for sequence in ["ACGT" * 25, "BXZ" * 25, "ACDEFGHIKLMNPQRSTVWYBXZ", "X"]:
            with self.subTest(sequence=sequence[:22]):
                source = self.source(f">a\n{sequence}\n>b\n{sequence}\n")
                output, _ = self.run_tool("protein", source)
                self.assert_measurements(source, output, "protein")
                self.assertIn("explicit protein alphabet selected", (output / "kalign.log").read_text())

    def test_08_invalid_fasta_and_protein_symbols_fail_actionably_before_execution(self):
        cases = {
            "empty": b"", "singleton": b">one\nACGT\n", "no-header": b"ACGT\n",
            "empty-sequence": b">one\nACGT\n>two\n", "empty-id": b">\nACGT\n>b\nACGT\n",
            "duplicate": b">a first\nACGT\n>a second\nACGT\n",
            "unsafe-id": b">a|pipe\nACGT\n>b\nACGT\n",
            "gaps": b">a\nAC-GT\n>b\nACGT\n", "dot-gap": b">a\nAC.GT\n>b\nACGT\n",
            "embedded-space": b">a\nAC GT\n>b\nACGT\n", "tab": b">a\nAC\tGT\n>b\nACGT\n",
            "digits": b">a\nACGT1\n>b\nACGT\n", "stop": b">a\nACGT*\n>b\nACGT\n",
            "non-ascii": b">a\nAC\xffGT\n>b\nACGT\n", "non-ascii-header": b">a \xff\nACGT\n>b\nACGT\n",
            "gzip": gzip.compress(b">a\nACGT\n>b\nACGT\n"),
        }
        for name, content in cases.items():
            with self.subTest(name=name):
                output, _ = self.run_tool(source=self.source(content), success=False)
                self.assertEqual(list(output.iterdir()), [], name)
        for symbol in "*JUO":
            with self.subTest(proteinSymbol=symbol):
                output, child = self.run_tool("protein", self.source(f">a\nMELK{symbol}\n>b\nMELK\n"), success=False)
                self.assertIn("Unsupported protein symbol", child.stderr)
                self.assertEqual(list(output.iterdir()), [])

    def test_09_declared_bounds_reject_oversized_inputs(self):
        cases = {
            "identifier": ">" + "a" * 129 + "\nACGT\n>b\nACGT\n",
            "header": ">a " + "x" * 1023 + "\nACGT\n>b\nACGT\n",
            "sequence": ">a\n" + "A" * 15001 + "\n>b\nA\n",
            "records": "".join(f">s{i}\nA\n" for i in range(10001)),
            "total-residues": "".join(f">s{i}\n" + "A" * 15000 + "\n" for i in range(668)),
        }
        for name, content in cases.items():
            with self.subTest(bound=name):
                output, _ = self.run_tool(source=self.source(content), success=False)
                self.assertEqual(list(output.iterdir()), [])
        source = self.directory / "oversized.fa"
        with source.open("wb") as stream:
            stream.truncate(64 * 1024 * 1024 + 1)
        output, child = self.run_tool(source=source, success=False)
        self.assertIn("File exceeds bounded pack size limit", child.stderr)
        self.assertEqual(list(output.iterdir()), [])

    def test_10_invalid_datatype_is_not_autodetected(self):
        for datatype in ["dna", "auto", "protein;echo", ""]:
            with self.subTest(datatype=datatype):
                output, child = self.run_tool(datatype, self.fixtures / "nucleotide.fa", success=False)
                self.assertIn("Choose nucleotide or protein explicitly", child.stderr)
                self.assertEqual(list(output.iterdir()), [])

    def test_11_spaces_supported_non_ascii_paths_rejected(self):
        source = self.directory / "selected file with spaces.fa"
        shutil.copyfile(self.fixtures / "nucleotide.fa", source)
        output, _ = self.run_tool(source=source)
        self.assert_preserved(source, output)
        other = self.directory / "selected file \u00e9.fa"
        shutil.copyfile(source, other)
        output, child = self.run_tool(source=other, success=False)
        self.assertIn("ASCII", child.stderr)
        self.assertEqual(list(output.iterdir()), [])

    def test_12_existing_output_is_not_replaced(self):
        output, _ = self.run_tool()
        before = inventory(output)
        child = subprocess.run([str(self.guard), str(self.fixtures / "nucleotide.fa"), str(output), "nucleotide"], capture_output=True, text=True)
        self.assertNotEqual(child.returncode, 0)
        self.assertIn("fresh output folder", child.stderr)
        self.assertEqual(inventory(output), before)

    def test_13_missing_scientific_executable_reports_reinstallation(self):
        isolated = self.directory / "incomplete installation"
        isolated.mkdir()
        guard = isolated / self.guard.name
        shutil.copyfile(self.guard, guard)
        guard.chmod(0o755)
        output = self.directory / "missing child"
        output.mkdir()
        child = subprocess.run([str(guard), str(self.fixtures / "nucleotide.fa"), str(output), "nucleotide"], capture_output=True, text=True, timeout=30)
        self.assertNotEqual(child.returncode, 0)
        self.assertIn("reinstall this pack", child.stderr)
        self.assertEqual(list(output.iterdir()), [])

    def test_14_serial_repeated_execution_is_deterministic(self):
        for datatype in ["nucleotide", "protein"]:
            with self.subTest(datatype=datatype):
                first, _ = self.run_tool(datatype)
                second, _ = self.run_tool(datatype)
                self.assertEqual((first / "alignment.afa").read_bytes(), (second / "alignment.afa").read_bytes())
                self.assertEqual((first / "alignment-summary.json").read_bytes(), (second / "alignment-summary.json").read_bytes())

    def test_15_declared_installation_checks_and_complete_installed_hashes(self):
        import prepare_kalign_pack as prep
        declarations = prep.checks()
        if PACK:
            config = configparser.ConfigParser(interpolation=None)
            config.read(PACK / "pack.ini", encoding="utf-8")
            self.assertEqual(config["pack"]["version"], "1.0.0")
            for section in config.sections():
                if section.startswith(("tool:", "asset:")):
                    self.assertEqual(sha(PACK / config[section]["path"]), config[section]["sha256"])
            declarations = json.loads((PACK / "workbench-checks.json").read_text())
            sys.path.insert(0, str(ROOT / "workspace"))
            from catalog import load_pack, describe_workflow
            pack = load_pack(PACK / "pack.ini")
            for workflow in pack["workflows"].values():
                described = describe_workflow(pack, workflow, str(PACK), pack["manifestSha256"])
                self.assertEqual({tool["id"] for tool in described["executables"]}, {"kalign", "kalign-adapter"})
        files = {"aligned": "alignment.afa", "summary": "alignment-summary.json",
                 "settings": "analysis-settings.json", "log": "kalign.log"}
        self.assertEqual({c["workflow"] for c in declarations["checks"]}, {"align-nucleotide", "align-protein"})
        for check in declarations["checks"]:
            datatype = check["workflow"].removeprefix("align-")
            output, _ = self.run_tool(datatype)
            self.assertEqual(fasta(output / "alignment.afa")[0], fasta(self.fixtures / f"{datatype}-truth.afa")[0])
            for expectation in check["expect"]:
                content = (output / files[expectation["output"]]).read_text()
                for fragment in expectation.get("contains", []):
                    self.assertIn(fragment, content)


class LinuxReferenceTests(unittest.TestCase):
    def test_live_pristine_upstream_comparison_on_both_independent_fixtures(self):
        global LIVE_REFERENCE
        recorder = module("kalign_reference", ROOT / "tools/kalign/record_reference.py")
        fixtures = ROOT / "tools/kalign/fixtures"
        LIVE_REFERENCE = recorder.record(REFERENCE_BINARY, fixtures)
        expected = json.loads((fixtures / "reference.json").read_text())
        self.assertEqual(recorder.verify(LIVE_REFERENCE, expected), 2)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pack", type=Path)
    parser.add_argument("--build", type=Path, default=BUILD)
    parser.add_argument("--reference-binary", type=Path, default=REFERENCE_BINARY)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    PACK = args.pack.resolve() if args.pack else None
    BUILD, REFERENCE_BINARY = args.build.resolve(), args.reference_binary.resolve()
    if os.name == "nt" and not PACK:
        parser.error("Native Windows checks require the exact installed --pack")
    selected = (PACK / "bin" if PACK else BUILD) / ("kalign-guard.exe" if os.name == "nt" else "kalign-guard")
    binary = selected.parent / ("kalign.exe" if os.name == "nt" else "kalign")
    if not selected.is_file() or not binary.is_file():
        parser.error("Selected compiled Kalign and guard are required: " + str(selected.parent))
    if os.name != "nt" and not REFERENCE_BINARY.is_file():
        parser.error("Linux checks require the pinned pristine --reference-binary")
    classes = [SourceTests, ScientificTests]
    if os.name != "nt":
        classes.append(LinuxReferenceTests)
    started = time.monotonic()
    suite = unittest.TestSuite(unittest.defaultTestLoader.loadTestsFromTestCase(cls) for cls in classes)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    evidence = {
        "schema": 1, "packId": "kalign", "packVersion": "1.0.0", "upstreamVersion": builder.UPSTREAM_VERSION,
        "toolVersion": builder.VERSION, "platform": sys.platform, "nativeWindowsExecuted": os.name == "nt",
        "testsRun": result.testsRun, "failures": len(result.failures), "errors": len(result.errors),
        "skipped": [{"test": str(test), "reason": reason} for test, reason in result.skipped],
        "success": result.wasSuccessful(), "seconds": round(time.monotonic() - started, 3),
        "testSourceSha256": sha(__file__), "guardExecutableSha256": sha(selected),
        "scientificBinarySha256": sha(binary), "packManifestSha256": sha(PACK / "pack.ini") if PACK else None,
        "upstreamSourceCommit": builder.SOURCE_COMMIT, "upstreamSourceArchiveSha256": builder.SOURCE_SHA256,
        "livePinnedLinuxReferenceCases": len(LIVE_REFERENCE["cases"]) if LIVE_REFERENCE else 0,
        "liveReferenceExecutableSha256": LIVE_REFERENCE["referenceExecutableSha256"] if LIVE_REFERENCE else None,
        "linuxReferenceScope": "Pristine reference execution is a separate Linux-only class, excluded from native Windows selection; the frozen reference and independent truth are verified on both platforms.",
        "executions": EXECUTIONS,
        "scope": "Independent six-sequence nucleotide/protein indel homology; direct bundled upstream agreement; explicit-alphabet correction, exact residue/ID/order preservation; measured summaries; malformed/bounded input and immutable-file regressions. No benchmark, native GUI, real-data alignment-accuracy, orthology or clinical claim.",
    }
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
    sys.exit(not result.wasSuccessful())
