"""Known-answer MultiQC reporting and local adapter contract tests.

Set NW_MULTIQC_PYTHON to a Python with the lock-matched Linux MultiQC dependencies
for source execution. This suite does not claim native Windows execution.
"""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


adapter = module('multiqc_adapter', ROOT / 'tools/multiqc/adapter.py')
prepare = module('multiqc_prepare', ROOT / 'scripts/prepare_multiqc_pack.py')


class AdapterTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='multiqc test ')
        self.root = Path(self.tmp.name)
        self.fixtures = self.root / 'fixtures'
        prepare.fixtures(self.fixtures)

    def tearDown(self):
        self.tmp.cleanup()

    def test_same_original_sample_name_remains_two_inputs(self):
        rows = adapter.stage_inputs([self.fixtures / 'sample-a_fastqc_data.txt', self.fixtures / 'sample-b_fastqc_data.txt'], self.root / 'stage')
        self.assertEqual(len(rows), 2)
        self.assertNotEqual(rows[0]['id'], rows[1]['id'])
        self.assertEqual([r['module'] for r in rows], ['fastqc', 'fastqc'])

    def test_duplicate_zip_and_extracted_report_rejected(self):
        source = self.fixtures / 'sample-a_fastqc_data.txt'
        archive = self.root / 'arbitrary-name.zip'
        with zipfile.ZipFile(archive, 'w') as z:
            z.write(source, 'sample_fastqc/fastqc_data.txt')
            z.writestr('../../never-extracted.txt', 'ignored')
        self.assertEqual(adapter.classify(archive)[0], 'fastqc')
        with self.assertRaisesRegex(ValueError, 'same report'):
            adapter.stage_inputs([source, archive], self.root / 'stage')
        self.assertFalse((self.root / 'never-extracted.txt').exists())

    def test_unknown_and_wrong_kallisto_outputs_rejected(self):
        for name, text in [('reads.fastq', '@read\nACGT\n+\nIIII\n'), ('run_info.json', '{"n_processed": 20}'), ('config.yaml', 'custom_content: {}')]:
            path = self.root / name
            path.write_text(text)
            with self.assertRaisesRegex(ValueError, 'Unsupported report'):
                adapter.classify(path)

    def test_zip_member_bound_and_multiple_reports(self):
        path = self.root / 'bad.zip'
        with zipfile.ZipFile(path, 'w', compression=zipfile.ZIP_DEFLATED) as z:
            z.writestr('a/fastqc_data.txt', '##FastQC\n')
            z.writestr('b/fastqc_data.txt', '##FastQC\n')
        with self.assertRaisesRegex(ValueError, 'exactly one'):
            adapter.classify(path)

    def test_featurecounts_column_identity_and_invalid_rows(self):
        source = self.fixtures / 'counts.summary'
        source.write_bytes(source.read_bytes().replace(b'\n', b'\r\n'))
        rows = adapter.stage_inputs([self.fixtures / 'counts.summary'], self.root / 'stage')
        self.assertEqual(rows[0]['originalSampleColumns'], ['sample.bam', 'second.bam'])
        contents = Path(rows[0]['staged']).read_text()
        self.assertIn('input001_counts_column001\tinput001_counts_column002', contents)
        self.assertIn('Assigned\t12\t8', contents)
        bad = self.root / 'bad.summary'
        bad.write_text('Status\tsample\nAssigned\t-5\n')
        with self.assertRaisesRegex(ValueError, 'nonnegative integer'):
            adapter.classify(bad)

    def test_hostile_names_are_safe_and_provenance_retains_original(self):
        source = self.root / '<script>alert(31)</script>.txt'.replace('/', '_')
        shutil.copy2(self.fixtures / 'sample-a_fastqc_data.txt', source)
        rows = adapter.stage_inputs([source], self.root / 'stage')
        self.assertNotIn('<', rows[0]['id'])
        self.assertEqual(rows[0]['source'], str(source))
        self.assertEqual(rows[0]['sourceSha256'], adapter.sha(source))

    def test_offline_audit_denies_network_and_subprocess(self):
        for event in ('socket.connect', 'socket.getaddrinfo', 'subprocess.Popen', 'os.system'):
            with self.assertRaisesRegex(RuntimeError, 'disabled'):
                adapter.offline_audit(event, ())
        adapter.offline_audit('open', ('local-report',))

    def test_existing_output_data_is_never_overwritten(self):
        data = self.root / 'multiqc_data'
        data.mkdir()
        protected = data / 'retained.txt'
        protected.write_text('previous data')
        with self.assertRaisesRegex(ValueError, 'not empty'):
            adapter.prepare_output_space(self.root)
        self.assertEqual(protected.read_text(), 'previous data')

    def test_remote_html_resource_rejected_but_javascript_strings_not_misclassified(self):
        path = self.root / 'report.html'
        path.write_text('<html><head></head><body><script>var unused = \'<img src="https://example.com/x.png">\';</script></body></html>')
        adapter.protect_html(path)
        self.assertIn('connect-src', path.read_text())
        path.write_text('<html><head></head><body><img src="https://example.com/x.png"></body></html>')
        with self.assertRaisesRegex(ValueError, 'remote asset'):
            adapter.protect_html(path)

    @unittest.skipUnless(os.environ.get('NW_MULTIQC_PYTHON'), 'Set NW_MULTIQC_PYTHON for real upstream scientific execution; no Windows claim')
    def test_real_multiqc_known_metrics_and_configuration_isolation(self):
        run = self.root / 'scientific results'
        run.mkdir()
        # Released native runner creates declared parent directories even when
        # no output files exist. Upstream must retain the exact declared names.
        (run / 'multiqc_data').mkdir()
        # This implicit config would remove every module and produce no report
        # if the adapter accidentally loaded it.
        (run / 'multiqc_config.yaml').write_text('run_modules: [does-not-exist]\noutput_dir: /must-not-write\n')
        (run / '.env').write_text('MULTIQC_TITLE=DOTENV_TITLE_IGNORED\n')
        inputs = [self.fixtures / n for n in ['sample-a_fastqc_data.txt', 'sample-b_fastqc_data.txt', 'rnaLog.final.out', 'quantification.log', 'counts.summary', 'preprocessing.json']]
        hashes = {p: adapter.sha(p) for p in inputs}
        env = dict(os.environ, MULTIQC_CONFIG_PATH=str(run / 'multiqc_config.yaml'), MULTIQC_TITLE='UNSAFE_TITLE_IGNORED')
        proc = subprocess.run([os.environ['NW_MULTIQC_PYTHON'], '-I', '-B', str(ROOT / 'tools/multiqc/adapter.py'), '--run', str(run), '--', *map(str, inputs)], env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=180)
        self.assertEqual(proc.returncode, 0, proc.stdout)
        data = json.loads((run / 'multiqc_data/multiqc_data.json').read_text())['report_saved_raw_data']
        self.assertEqual(sorted(r['Total Sequences'] for r in data['multiqc_fastqc'].values()), [20, 30])
        self.assertEqual(sorted(r['%GC'] for r in data['multiqc_fastqc'].values()), [40, 60])
        self.assertEqual(next(iter(data['multiqc_star'].values()))['uniquely_mapped'], 80)
        self.assertEqual(next(iter(data['multiqc_kallisto'].values()))['pseudoaligned_reads'], 16)
        self.assertEqual(sorted(r['Assigned'] for r in data['multiqc_featurecounts'].values()), [8, 12])
        self.assertEqual(next(iter(data['multiqc_fastp'].values()))['filtering_result']['passed_filter_reads'], 90)
        source_info = json.loads((run / 'report-inputs.json').read_text())
        self.assertEqual(source_info['inputCount'], 6)
        self.assertTrue(source_info['implicitDotenvDisabled'])
        html_text = (run / 'multiqc_report.html').read_text()
        self.assertIn('Content-Security-Policy', html_text)
        self.assertNotIn('UNSAFE_TITLE_IGNORED', html_text)
        self.assertNotIn('DOTENV_TITLE_IGNORED', html_text)
        self.assertEqual(hashes, {p: adapter.sha(p) for p in inputs})
        for assertion in prepare.checks()['checks'][0]['expect']:
            path = {'html': 'multiqc_report.html', 'data': 'multiqc_data/multiqc_data.json', 'general-statistics': 'multiqc_data/multiqc_general_stats.txt', 'sources': 'report-inputs.json'}[assertion['output']]
            text = (run / path).read_text()
            for expected in assertion['contains']:
                self.assertIn(expected, text)


if __name__ == '__main__':
    unittest.main(verbosity=2)
