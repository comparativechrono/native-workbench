"""Real kallisto RNA-seq regression tests; Linux evidence is not Windows evidence.

Build with scripts/build_kallisto_native.py --linux and prepare the pack first.
NW_KALLISTO_CACHE optionally selects the source/build cache. The official Linux
0.52.0 reference is optional but is SHA-pinned when present.
"""
import csv, gzip, hashlib, importlib.util, json, math, os, shutil, subprocess, sys, tempfile, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CACHE = Path(os.environ.get('NW_KALLISTO_CACHE', ROOT.parent / 'rna-build/kallisto-fixed'))
PACK = ROOT / 'packs/kallisto-1.0.1'
LINUX = CACHE / 'build-linux'
OFFICIAL = CACHE / 'official-linux-standard/kallisto/kallisto'
OFFICIAL_SHA = '9000fd5afc1fb9f07cb4cf6513a4d932bcb086079982d0740843016a07178fa1'
sys.path.insert(0, str(ROOT / 'scripts'))
from prepare_kallisto_pack import definitions
sys.path.insert(0, str(ROOT / 'workspace'))
from catalog import load_pack, describe_workflow, TYPES

def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def abundances(path):
    with Path(path).open(newline='') as stream:
        return {row['target_id']: {key: float(row[key]) for key in ('length', 'eff_length', 'est_counts', 'tpm')} for row in csv.DictReader(stream, delimiter='\t')}

class KallistoDeclarations(unittest.TestCase):
    def test_single_end_fragment_parameters_have_no_guessed_defaults(self):
        workflows, _ = definitions()
        for workflow in workflows:
            if workflow['id'].endswith('-single'):
                fields = {field['id']: field for field in workflow['inputs']}
                for name in ('fragment-mean', 'fragment-sd'):
                    self.assertNotIn('default', fields[name])
                    self.assertEqual(fields[name]['required'], 'true')
                    self.assertEqual(fields[name]['min'], '1')

    def test_quantification_is_not_an_alignment_or_variant_input(self):
        _, schema = definitions()
        for identity, workflow in schema['workflows'].items():
            self.assertTrue(workflow['pathPolicy']['asciiOnly'])
            if identity != 'index':
                products = {product['id']: product for product in workflow['outputs']}
                self.assertEqual(products['abundance']['type'], 'metrics')
                self.assertTrue(all(p['type'] in {'metrics', 'index'} for p in workflow['outputs']))
                self.assertIn('No sequence-bias correction', workflow['methods'])

@unittest.skipUnless((LINUX / 'kallisto').is_file() and (PACK / 'pack.ini').is_file(), 'Build and prepare the kallisto pack to run real executable tests')
class KallistoScience(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix='kallisto scientific paths ')
        cls.root = Path(cls.temp.name)
        cls.bin = cls.root / 'tools with spaces'
        cls.bin.mkdir()
        record = json.loads((LINUX / 'build.json').read_text())
        for name in ('kallisto', 'kallisto-adapter', 'readcheck'):
            if sha(LINUX / name) != record['files'][name]['sha256']: raise AssertionError('Linux reference changed: ' + name)
            shutil.copy2(LINUX / name, cls.bin / name)
        cls.fixtures = PACK / 'fixtures'
        cls.index = cls.root / 'transcripts with spaces.idx'
        cls.invoke([str(cls.bin / 'kallisto'), 'index', '-i', str(cls.index), '-k', '31', '-t', '1', str(cls.fixtures / 'transcripts.fasta')], cls.root)
        cls.pack = load_pack(PACK / 'pack.ini')
        cls.counter = 0

    @classmethod
    def tearDownClass(cls): cls.temp.cleanup()

    @staticmethod
    def invoke(argv, cwd, okay=True):
        completed = subprocess.run(argv, cwd=cwd, capture_output=True, text=True, timeout=120)
        if okay and completed.returncode: raise AssertionError('Tool failed:\n' + completed.stdout + completed.stderr)
        return completed

    def quant(self, paired, *, strand='unstranded', bootstraps=0, threads=2, index=None, reads=None):
        type(self).counter += 1
        folder = self.root / ('quant result ' + str(self.counter))
        r1 = self.fixtures / ('reads1.fastq.gz' if paired else 'single.fastq.gz')
        r2 = self.fixtures / 'reads2.fastq.gz' if paired else '-'
        if reads: r1, r2 = reads
        self.invoke([str(self.bin / 'kallisto-adapter'), 'quant', str(index or self.index), str(r1), str(r2), str(folder), strand, str(threads), str(bootstraps), '42', '180' if not paired else '0', '20' if not paired else '0'], self.root)
        return folder

    def assert_truth(self, folder):
        rows = abundances(folder / 'abundance.tsv')
        self.assertEqual(set(rows), {'tx1', 'tx2', 'tx3'})
        for name, count, tpm in [('tx1', 12, 600000), ('tx2', 6, 300000), ('tx3', 2, 100000)]:
            self.assertAlmostEqual(rows[name]['est_counts'], count, places=8)
            self.assertAlmostEqual(rows[name]['tpm'], tpm, places=5)
        info = json.loads((folder / 'run_info.json').read_text())
        self.assertEqual(info['n_processed'], 20)
        self.assertEqual(info['n_pseudoaligned'], 20)
        self.assertEqual(info['index_version'], 13)

    def test_single_and_paired_counts_tpm_and_bootstrap_files(self):
        for paired in (False, True):
            with self.subTest(paired=paired):
                folder = self.quant(paired, strand='fr', bootstraps=3)
                self.assert_truth(folder)
                with (folder / 'bootstrap-estimates.tsv').open() as stream: rows = list(csv.DictReader(stream, delimiter='\t'))
                self.assertEqual(len(rows), 9)
                for n in range(3):
                    selected = [row for row in rows if row['bootstrap'] == str(n)]
                    self.assertEqual({row['target_id'] for row in selected}, {'tx1', 'tx2', 'tx3'})
                    self.assertAlmostEqual(sum(float(row['est_counts']) for row in selected), 20)
                    self.assertAlmostEqual(sum(float(row['tpm']) for row in selected), 1000000)
                again = self.quant(paired, strand='fr', bootstraps=3)
                self.assertEqual((folder / 'bootstrap-estimates.tsv').read_bytes(), (again / 'bootstrap-estimates.tsv').read_bytes())

    def test_plaintext_bootstraps_match_between_one_two_and_four_threads(self):
        # Regression for upstream 0.52.0's USE_HDF5-guarded dispatch. Worker
        # count must not drop requested plaintext replicates or alter seed IDs.
        for paired in (False, True):
            serial = self.quant(paired, bootstraps=3, threads=1)
            for threads in (2, 4):
                with self.subTest(paired=paired, threads=threads):
                    parallel = self.quant(paired, bootstraps=3, threads=threads)
                    self.assert_truth(parallel)
                    self.assertEqual((serial / 'bootstrap-estimates.tsv').read_bytes(),
                                     (parallel / 'bootstrap-estimates.tsv').read_bytes())
                    self.assertEqual((serial / 'abundance.tsv').read_bytes(),
                                     (parallel / 'abundance.tsv').read_bytes())

    def test_disabled_bootstraps_and_reverse_strand_library(self):
        folder = self.quant(True)
        self.assert_truth(folder)
        self.assertEqual(len((folder / 'bootstrap-estimates.tsv').read_text().splitlines()), 1)
        # Exchange paired ends to model read 1 opposing the transcript strand.
        reverse = self.quant(True, strand='rf', reads=(self.fixtures / 'reads2.fastq.gz', self.fixtures / 'reads1.fastq.gz'))
        self.assert_truth(reverse)

    def test_ambiguous_identical_transcripts_are_split_by_em(self):
        reference = self.root / 'ambiguous transcripts.fa'
        lines = (self.fixtures / 'transcripts.fasta').read_text().splitlines()
        reference.write_text('\n'.join(lines) + '\n>tx1_alternate\n' + lines[1] + '\n')
        index = self.root / 'ambiguous.idx'
        self.invoke([str(self.bin / 'kallisto'), 'index', '-i', str(index), '-t', '1', str(reference)], self.root)
        folder = self.quant(True, index=index)
        rows = abundances(folder / 'abundance.tsv')
        self.assertAlmostEqual(rows['tx1']['est_counts'], 6, places=6)
        self.assertAlmostEqual(rows['tx1_alternate']['est_counts'], 6, places=6)
        self.assertAlmostEqual(sum(row['est_counts'] for row in rows.values()), 20, places=6)

    def test_incompatible_indexes_and_invalid_parameters_fail(self):
        invalid = self.root / 'not kallisto.idx'
        invalid.write_bytes(b'BAI\x01' + bytes(32))
        argv = [str(self.bin / 'kallisto-adapter'), 'quant', str(invalid), str(self.fixtures / 'single.fastq'), '-', str(self.root / 'rejected'), 'unstranded', '1', '0', '42', '180', '20']
        result = self.invoke(argv, self.root, okay=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('version 13', result.stderr)
        argv[2] = str(self.index); argv[-1] = '0'
        self.assertNotEqual(self.invoke(argv, self.root, okay=False).returncode, 0)

    def test_strict_fastq_validation_rejects_bad_pairs_and_truncated_gzip(self):
        checker = str(self.bin / 'readcheck')
        valid = self.invoke([checker, '--reads1', str(self.fixtures / 'reads1.fastq.gz'), '--reads2', str(self.fixtures / 'reads2.fastq.gz')], self.root)
        self.assertEqual(json.loads(valid.stdout)['pairs'], 20)
        bad = self.root / 'bad mate.fastq'
        bad.write_text((self.fixtures / 'reads2.fastq').read_text().replace('@tx1_read1/2', '@different/2', 1))
        self.assertNotEqual(self.invoke([checker, '--reads1', str(self.fixtures / 'reads1.fastq.gz'), '--reads2', str(bad)], self.root, okay=False).returncode, 0)
        bad_gzip = self.root / 'truncated.fastq.gz'
        bad_gzip.write_bytes((self.fixtures / 'single.fastq.gz').read_bytes()[:-7])
        self.assertNotEqual(self.invoke([checker, '--single', str(bad_gzip)], self.root, okay=False).returncode, 0)
        malformed = self.root / 'bad quality.fastq'
        malformed.write_text('@read\nACGT\n+\nIII\n')
        self.assertNotEqual(self.invoke([checker, '--single', str(malformed)], self.root, okay=False).returncode, 0)

    def test_every_manifest_workflow_with_real_binaries_and_paths_with_spaces(self):
        for workflow in self.pack['workflows'].values():
            with self.subTest(workflow=workflow['id']):
                folder = self.root / ('manifest workflow ' + workflow['id'])
                folder.mkdir()
                values = {item['id']: item.get('default', '') for item in workflow['inputs']}
                values.update({'reads': str(self.fixtures / 'single.fastq.gz'), 'reads1': str(self.fixtures / 'reads1.fastq.gz'), 'reads2': str(self.fixtures / 'reads2.fastq.gz'), 'transcriptome': str(self.fixtures / 'transcripts.fasta'), 'index': str(self.index), 'fragment-mean': '180', 'fragment-sd': '20', 'threads': '2'})
                outputs = {item['id']: str(folder / item['path']) for item in workflow['outputs']}
                for path in outputs.values(): Path(path).parent.mkdir(parents=True, exist_ok=True)
                def expand(argument):
                    argument = argument.replace('{run}', str(folder))
                    for category, mapping in (('input', values), ('output', outputs)):
                        for key, value in mapping.items(): argument = argument.replace('{' + category + ':' + key + '}', str(value))
                    if '{' in argument: raise AssertionError('Unexpanded manifest argument ' + argument)
                    return argument
                for step in workflow['steps']:
                    result = self.invoke([str(self.bin / step['tool']), *[expand(arg) for arg in step['args']]], folder)
                    if step.get('stdout'): Path(outputs[step['stdout']]).write_text(result.stdout)
                for item in workflow['outputs']:
                    self.assertTrue(Path(outputs[item['id']]).is_file())
                    if item['nonempty']: self.assertGreater(Path(outputs[item['id']]).stat().st_size, 0)
                if 'abundance' in outputs: self.assert_truth(folder / 'quant')

    @unittest.skipUnless(OFFICIAL.is_file(), 'Fetch the pinned upstream Linux 0.52.0 release to compare real upstream outputs')
    def test_numeric_outputs_match_official_upstream_on_synthetic_and_upstream_data(self):
        self.assertEqual(sha(OFFICIAL), OFFICIAL_SHA)
        for label, reference, read1, read2 in [('synthetic', self.fixtures / 'transcripts.fasta', self.fixtures / 'reads1.fastq.gz', self.fixtures / 'reads2.fastq.gz'), ('upstream', OFFICIAL.parent / 'test/transcripts.fasta.gz', OFFICIAL.parent / 'test/reads_1.fastq.gz', OFFICIAL.parent / 'test/reads_2.fastq.gz')]:
            outputs = []
            for name, binary in [('official', OFFICIAL), ('patched', self.bin / 'kallisto')]:
                folder = self.root / (label + ' ' + name)
                folder.mkdir()
                index = folder / 'transcripts.idx'
                self.invoke([str(binary), 'index', '-i', str(index), '-t', '1', str(reference)], folder)
                self.invoke([str(binary), 'quant', '-i', str(index), '-o', str(folder / 'quant'), '-t', '1', '--plaintext', str(read1), str(read2)], folder)
                outputs.append(abundances(folder / 'quant/abundance.tsv'))
            self.assertEqual(set(outputs[0]), set(outputs[1]))
            for target in outputs[0]:
                for key in outputs[0][target]:
                    self.assertTrue(math.isclose(outputs[0][target][key], outputs[1][target][key], rel_tol=1e-6, abs_tol=1e-6), (label, target, key, outputs[0][target][key], outputs[1][target][key]))

if __name__ == '__main__': unittest.main(verbosity=2)
