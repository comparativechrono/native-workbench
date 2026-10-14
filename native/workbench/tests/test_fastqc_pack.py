"""FastQC known-answer execution with a named Linux JDK, not Windows evidence."""
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[1]
PACK = Path(os.environ.get('NW_FASTQC_PACK', ROOT / 'packs/fastqc-1.0.0'))
JDK = Path(os.environ.get('NW_FASTQC_JDK', ROOT / 'vendor-expanded/java/linux/jdk8u504-b01')).resolve()
sys.path.insert(0, str(ROOT / 'scripts'))
from prepare_fastqc_pack import definitions
sys.path.insert(0, str(ROOT / 'workspace'))
from catalog import load_pack


class FastQCContracts(unittest.TestCase):
    def test_metrics_and_reads_are_not_interchangeable(self):
        workflows, schema = definitions()
        self.assertEqual({w['id'] for w in workflows}, {'single', 'paired'})
        self.assertEqual(schema['workflows']['paired']['ports'][0]['manifestInputs'], ['reads1', 'reads2'])
        for wf in schema['workflows'].values():
            kinds = {p['id']: p['type'] for p in wf['outputs']}
            self.assertEqual(kinds['report1'], 'report')
            self.assertEqual(kinds['archive1'], 'metrics')
            self.assertEqual(kinds['data1'], 'metrics')
            self.assertFalse(set(kinds.values()) & {'reads', 'pair', 'sam', 'bam'})


@unittest.skipUnless((PACK / 'pack.ini').is_file() and (JDK / 'bin/java').is_file(), 'Prepare the FastQC pack and set NW_FASTQC_JDK to the pinned Linux JDK')
class FastQCScience(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix='fastqc scientific paths ', dir=ROOT / 'vendor-expanded' if (ROOT / 'vendor-expanded').exists() else ROOT)
        cls.folder = Path(cls.temp.name)
        cls.counter = 0
        cls.pack = load_pack(PACK / 'pack.ini')
        cls.cp = os.pathsep.join(str(PACK / 'assets' / name) for name in ('workbench-fastqc.jar', 'fastqc-0.13.0.jar', 'commons-io-2.22.0.jar', 'commons-compress-1.28.0.jar'))
        cls.env = dict(os.environ, LD_LIBRARY_PATH=str(JDK / 'jre/lib/amd64/jli'))
        for key in ('JAVA_TOOL_OPTIONS', 'JDK_JAVA_OPTIONS', '_JAVA_OPTIONS', 'CLASSPATH'): cls.env.pop(key, None)

    @classmethod
    def tearDownClass(cls): cls.temp.cleanup()

    def run_tool(self, paired=False, reads=None, offset=33, threads=2, okay=True):
        type(self).counter += 1
        out = self.folder / ('result with spaces ' + str(self.counter))
        one = PACK / 'fixtures/reads1.fastq'
        two = PACK / 'fixtures/reads2.fastq.gz' if paired else '-'
        if reads: one, two = reads
        command = [str(JDK / 'bin/java'), '-Xmx128m', '-Djava.awt.headless=true', '-cp', self.cp, 'WorkbenchFastQC',
                   'paired' if paired else 'single', str(one), str(two), str(out), str(threads), '512', str(offset)]
        result = subprocess.run(command, env=self.env, cwd=self.folder, capture_output=True, text=True, timeout=90)
        if okay: self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        else: self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        return out, result

    def data(self, folder, mate=1): return (folder / ('read' + str(mate)) / 'fastqc_data.txt').read_text()

    def assert_truth(self, folder, mate=1):
        text = self.data(folder, mate)
        for value in ('##FastQC\t0.13.0', 'Total Sequences\t20\n', 'Total Bases\t800 bp\n', '%GC\t50\n', 'Sequence length\t40\n', 'Mean Length\t40\n', 'Median Length\t40\n', '1\t40.0\t'):
            self.assertIn(value, text)
        check = json.loads((folder / 'input-validation.json').read_text())
        self.assertTrue(check['valid']); self.assertEqual(check['recordsPerFile'], 20)
        self.assertEqual(check['bases1'], 800)
        if mate == 2: self.assertEqual(check['bases2'], 800)

    def test_single_and_paired_truth_with_default_two_threads(self):
        for paired in (False, True):
            with self.subTest(paired=paired):
                out, _ = self.run_tool(paired)
                self.assert_truth(out)
                if paired: self.assert_truth(out, 2)

    def test_plain_and_gzip_inputs_agree(self):
        plain, _ = self.run_tool()
        zipped, _ = self.run_tool(reads=(PACK / 'fixtures/reads1.fastq.gz', '-'))
        clean = lambda s: re.sub(r'^Filename\t.*$', 'Filename\tINPUT', s, flags=re.M)
        self.assertEqual(clean(self.data(plain)), clean(self.data(zipped)))

    def test_one_and_four_threads_agree(self):
        one, _ = self.run_tool(threads=1)
        four, _ = self.run_tool(threads=4)
        self.assertEqual(self.data(one), self.data(four))

    def test_html_is_offline_and_zip_data_is_unchanged(self):
        out, _ = self.run_tool()
        for mate in (1,):
            folder = out / ('read' + str(mate))
            html = (folder / 'fastqc.html').read_text()
            self.assertIn('FastQC Report', html)
            self.assertIn('data:image/', html)
            self.assertNotRegex(html, r'(?i)<(?:script|img|link|iframe)\b[^>]*(?:src|href)\s*=\s*[\'\"](?:https?:)?//')
            with zipfile.ZipFile(folder / 'fastqc.zip') as archive:
                original = archive.read(next(n for n in archive.namelist() if n.endswith('/fastqc_data.txt')))
                self.assertEqual(original, (folder / 'fastqc_data.txt').read_bytes())
                self.assertIn(b'Filename\treads1.fastq', original)
            self.assertFalse((folder / 'upstream').exists())

    def test_phred64_is_explicit_and_correct(self):
        path = self.folder / 'legacy quality.fastq'
        text = (PACK / 'fixtures/reads1.fastq').read_text()
        lines = text.splitlines()
        for i in range(3, len(lines), 4): lines[i] = 'h' * len(lines[i])
        path.write_text('\n'.join(lines) + '\n')
        out, _ = self.run_tool(reads=(path, '-'), offset=64)
        self.assert_truth(out)
        self.assertEqual(json.loads((out / 'input-validation.json').read_text())['qualityOffset'], 64)
        wrong = self.folder / 'not legacy.fastq'; wrong.write_text('@r\nACGT\n+\n!!!!\n')
        bad, failure = self.run_tool(reads=(wrong, '-'), offset=64, okay=False)
        self.assertIn('Quality outside', failure.stderr); self.assertFalse((bad / 'input-validation.json').exists())

    def test_malformed_empty_truncated_gzip_and_mates_fail(self):
        examples = {'bad length.fastq': '@r\nACGT\n+\nIII\n', 'empty.fastq': '', 'bad base.fastq': '@r\nAC!T\n+\nIIII\n',
                    'empty identifier.fastq': '@ \nACGT\n+\nIIII\n'}
        for name, text in examples.items():
            path = self.folder / name; path.write_text(text)
            out, _ = self.run_tool(reads=(path, '-'), okay=False)
            self.assertFalse((out / 'input-validation.json').exists())
        truncated = self.folder / 'truncated.fastq.gz'; truncated.write_bytes((PACK / 'fixtures/reads1.fastq.gz').read_bytes()[:-7])
        self.run_tool(reads=(truncated, '-'), okay=False)
        mate = self.folder / 'wrong mate.fastq'; mate.write_text((PACK / 'fixtures/reads2.fastq').read_text().replace('synthetic0/2', 'wrong0/2'))
        _, failure = self.run_tool(True, reads=(PACK / 'fixtures/reads1.fastq', mate), okay=False)
        self.assertIn('Mate identifiers or order differ', failure.stderr)
        _, failure = self.run_tool(True, reads=(PACK / 'fixtures/reads1.fastq', PACK / 'fixtures/reads1.fastq'), okay=False)
        self.assertIn('different files', failure.stderr)
        empty1, empty2 = self.folder / 'empty mate1.fastq', self.folder / 'empty mate2.fastq'
        empty1.write_text('@/1\nACGT\n+\nIIII\n'); empty2.write_text('@/2\nACGT\n+\nIIII\n')
        _, failure = self.run_tool(True, reads=(empty1, empty2), okay=False)
        self.assertIn('no mate identifier', failure.stderr)

    def test_upstream_stdin_sentinel_is_rejected_before_launch(self):
        sentinel = self.folder / 'stdin_reads.fastq'
        sentinel.write_bytes((PACK / 'fixtures/reads1.fastq').read_bytes())
        for paired, reads in ((False, (sentinel, '-')), (True, (PACK / 'fixtures/reads1.fastq', sentinel))):
            out, failure = self.run_tool(paired, reads=reads, okay=False)
            self.assertIn('Rename the selected FASTQ file', failure.stderr)
            self.assertNotIn('Started analysis', failure.stdout + failure.stderr)
            self.assertFalse(out.exists())


if __name__ == '__main__': unittest.main()
