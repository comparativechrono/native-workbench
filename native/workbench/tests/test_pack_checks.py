"""Pack self-check runner regression tests; no scientific binary is mocked as evidence.

These tests isolate the runner with a declared copy operation. Real new-family
scientific execution is tested separately in test_expansion_pipeline.py.
"""
import copy
import gzip
import json
from pathlib import Path
import shutil
import sys
import tempfile
import threading
import unittest

SOURCE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SOURCE / 'workspace'))
from catalog import load_catalog
from engine import digest_file
from pack_checks import run_pack_checks, _assert_output


class CopyBackend:
    def __init__(self, fail=False, cancel_during=False):
        self.calls = []
        self.fail, self.cancel_during = fail, cancel_during

    def run(self, request, event, cancel):
        self.calls.append(request)
        folder = Path(request['output_folder']) / 'copy-operation'
        folder.mkdir()
        if self.cancel_during:
            cancel.set()
            return {'success': False, 'cancelled': True, 'folder': str(folder)}
        if self.fail:
            return {'success': False, 'folder': str(folder), 'message': 'Deliberate backend failure'}
        shutil.copyfile(request['values']['reads'], folder / 'copied.fastq')
        return {'success': True, 'folder': str(folder)}


class PackChecksTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='pack-check-tests-')
        self.root = Path(self.temporary.name).resolve()
        self.pack = self.root / 'packs' / 'fixture-1.0.0'
        self.pack.mkdir(parents=True)
        (self.pack / 'unused.exe').write_bytes(b'declared integrity fixture; never executed')
        self.fixture = self.pack / 'reads.fastq'
        self.fixture.write_text('@one\nACGT\n+\nIIII\n@two\nGCTA\n+\nHHHH\n')
        self.spec = {'schema': 1, 'checks': [{
            'id': 'copy-reads', 'workflow': 'copy', 'params': {},
            'inputs': {'reads': [{'reads': 'fixture'}]},
            'expect': [{'output': 'copied', 'kind': 'fastq', 'records': 2,
                        'sequences': {'one': 'ACGT', 'two': 'GCTA'}}]
        }]}
        self.write_pack()

    def tearDown(self):
        self.temporary.cleanup()

    def write_pack(self):
        (self.pack / 'checks.json').write_text(json.dumps(self.spec))
        manifest = f'''[pack]
format=2
id=fixture
version=1.0.0
name=Fixture copy
platform=windows-x86_64

[tool:unused]
path=unused.exe
version=1.0.0
sha256={digest_file(self.pack / 'unused.exe')}

[asset:workbench-checks]
path=checks.json
sha256={digest_file(self.pack / 'checks.json')}

[asset:fixture]
path=reads.fastq
sha256={digest_file(self.fixture)}

[workflow:copy]
name=Copy checked reads
description=Copy a pinned test fixture without biological transformation.
inputs=reads
outputs=copied
steps=copy

[input:copy:reads]
label=Reads
type=file
filter=FASTQ|*.fastq

[output:copy:copied]
label=Copied reads
path=copied.fastq

[step:copy:copy]
label=Copy reads
kind=copy
source={{input:reads}}
destination=copied
'''
        (self.pack / 'pack.ini').write_text(manifest)
        self.catalog = load_catalog(self.root)

    def run_checks(self, backend=None, cancel=None):
        return run_pack_checks(self.root, self.catalog, self.root,
                               backend=backend or CopyBackend(), cancel=cancel)

    def test_success_uses_pinned_fixture_and_normal_engine_provenance(self):
        backend = CopyBackend()
        result = self.run_checks(backend)
        self.assertTrue(result['success'], result)
        self.assertEqual((result['passed'], result['failed']), (1, 0))
        self.assertEqual(backend.calls[0]['values']['reads'], str(self.fixture))
        run = json.loads((Path(result['checks'][0]['folder']) / 'run.json').read_text())
        self.assertEqual(run['status'], 'success')
        self.assertEqual(run['nodes'][0]['pin']['manifestSha256'],
                         self.catalog['tools']['fixture/copy']['manifestSha256'])
        self.assertEqual(run['outputs']['step-1::copied']['sha256']['copied'],
                         digest_file(self.fixture))
        persisted = json.loads((Path(result['folder']) / 'pack-checks.json').read_text())
        self.assertEqual(persisted, result)

    def test_check_runs_share_installation_parent_without_report_path_prefix(self):
        second = copy.deepcopy(self.spec['checks'][0])
        second['id'] = 'independent-copy'
        self.spec['checks'].append(second)
        self.write_pack()
        # Exercise real Engine preparation and recorded backend destinations in
        # a long path with spaces. The copy backend is only a runner contract
        # fixture; native CreateProcess behavior has its separate Windows gate.
        output_parent = self.root / 'installation checks' / ('nested output ' * 5).rstrip()
        output_parent.mkdir(parents=True)
        backend = CopyBackend()
        result = run_pack_checks(self.root, self.catalog, output_parent, backend=backend)
        self.assertTrue(result['success'], result)
        self.assertEqual((result['passed'], result['failed']), (2, 0))
        report_folder = Path(result['folder'])
        self.assertEqual(report_folder.parent, output_parent)
        self.assertTrue(report_folder.name.startswith('pack-checks-'))
        folders = {Path(case['folder']) for case in result['checks']}
        self.assertEqual(len(folders), 2)
        for case, call in zip(result['checks'], backend.calls):
            folder = Path(case['folder'])
            self.assertEqual(folder.parent, output_parent)
            self.assertNotIn(report_folder, folder.parents)
            self.assertEqual(Path(call['output_folder']), folder / 'S1')
            plan = json.loads((folder / 'plan.json').read_text())
            run = json.loads((folder / 'run.json').read_text())
            self.assertEqual(plan['folder'], str(folder))
            self.assertEqual(run['planSha256'], plan['sha256'])
            copied = run['outputs']['step-1::copied']
            self.assertTrue(Path(copied['files']['copied']).is_relative_to(folder))
            self.assertEqual(copied['sha256']['copied'], digest_file(self.fixture))
        persisted = json.loads((report_folder / 'pack-checks.json').read_text())
        self.assertEqual(persisted, result)

    def test_fixture_tamper_is_rejected_before_execution(self):
        self.fixture.write_text('@changed\nA\n+\nI\n')
        backend = CopyBackend()
        result = self.run_checks(backend)
        self.assertFalse(result['success'])
        self.assertEqual(len(backend.calls), 0)
        self.assertIn('hash differs', result['checks'][0]['message'])

    def test_retained_versions_run_their_own_checks_and_keep_exact_provenance(self):
        newer = self.root / 'packs/fixture-2.0.0'
        shutil.copytree(self.pack, newer)
        manifest = newer / 'pack.ini'
        manifest.write_text(manifest.read_text().replace('version=1.0.0', 'version=2.0.0', 1))
        self.catalog = load_catalog(self.root)
        self.assertEqual(self.catalog['tools']['fixture/copy']['packVersion'], '2.0.0')
        backend = CopyBackend()
        result = self.run_checks(backend)
        self.assertTrue(result['success'], result)
        self.assertEqual((result['passed'], result['failed']), (2, 0))
        self.assertEqual({Path(call['pack_folder']).name for call in backend.calls}, {'fixture-1.0.0','fixture-2.0.0'})
        self.assertEqual(len({case['id'] for case in result['checks']}), 2)
        self.assertEqual({case['pin']['packVersion'] for case in result['checks']}, {'1.0.0','2.0.0'})
        for case in result['checks']:
            run = json.loads((Path(case['folder']) / 'run.json').read_text())
            self.assertEqual(run['nodes'][0]['pin'], case['pin'])

    def test_changed_manifest_is_a_scoped_failure_without_using_latest(self):
        newer = self.root / 'packs/fixture-2.0.0'
        shutil.copytree(self.pack, newer)
        manifest = newer / 'pack.ini'
        manifest.write_text(manifest.read_text().replace('version=1.0.0', 'version=2.0.0', 1))
        self.catalog = load_catalog(self.root)
        with (self.pack / 'pack.ini').open('a') as stream:
            stream.write('\n; changed after discovery\n')
        backend = CopyBackend()
        result = self.run_checks(backend)
        self.assertFalse(result['success'])
        self.assertEqual((result['passed'], result['failed']), (1, 1))
        self.assertEqual([Path(call['pack_folder']).name for call in backend.calls], ['fixture-2.0.0'])
        failure = next(case for case in result['checks'] if case['status']=='failed')
        self.assertEqual(failure['pin']['packVersion'], '1.0.0')
        self.assertIn('changed after catalogue discovery', failure['message'])

    def test_specification_tamper_and_duplicate_fields_are_rejected(self):
        checks = self.pack / 'checks.json'
        checks.write_text('{"schema":1,"schema":1,"checks":[]}')
        backend = CopyBackend()
        result = self.run_checks(backend)
        self.assertFalse(result['success'])
        self.assertIn('hash differs', result['checks'][0]['message'])
        manifest = self.pack / 'pack.ini'
        text = manifest.read_text()
        start = text.index('[asset:workbench-checks]')
        end = text.index('[asset:fixture]')
        old = text[start:end]
        manifest.write_text(text[:start] + old[:old.index('sha256=')] +
                            'sha256=' + digest_file(checks) + '\n\n' + text[end:])
        self.catalog = load_catalog(self.root)
        result = self.run_checks(backend)
        self.assertFalse(result['success'])
        self.assertIn('Duplicate', result['checks'][0]['message'])
        self.assertFalse(backend.calls)

    def test_invalid_fixture_reference_and_field_fail_without_running(self):
        for member in ({'reads': 'missing'}, {'other': 'fixture'}):
            with self.subTest(member=member):
                self.spec['checks'][0]['inputs']['reads'] = [member]
                self.write_pack()
                backend = CopyBackend()
                result = self.run_checks(backend)
                self.assertFalse(result['success'])
                self.assertFalse(backend.calls)

    def test_failed_assertion_does_not_prevent_independent_case(self):
        second = copy.deepcopy(self.spec['checks'][0])
        second['id'] = 'second-copy'
        self.spec['checks'][0]['expect'][0]['records'] = 3
        self.spec['checks'].append(second)
        self.write_pack()
        backend = CopyBackend()
        result = self.run_checks(backend)
        self.assertFalse(result['success'])
        self.assertEqual((result['passed'], result['failed']), (1, 1))
        self.assertEqual(len(backend.calls), 2)
        self.assertIn('Unexpected sequence count', result['checks'][0]['message'])

    def test_backend_failure_is_not_a_passing_check(self):
        result = self.run_checks(CopyBackend(fail=True))
        self.assertFalse(result['success'])
        self.assertEqual(result['failed'], 1)
        self.assertIn('Tool did not complete', result['checks'][0]['message'])

    def test_cancellation_before_or_during_run_never_passes(self):
        for during in (False, True):
            with self.subTest(during=during):
                cancel = threading.Event()
                if not during:
                    cancel.set()
                backend = CopyBackend(cancel_during=during)
                result = self.run_checks(backend, cancel)
                self.assertFalse(result['success'])
                self.assertTrue(result['cancelled'])
                self.assertEqual(result['passed'], 0)
                self.assertEqual(len(backend.calls), int(during))

    def test_alignment_assertions_detect_residue_loss_and_unequal_width(self):
        path = self.root / 'alignment.fa'
        result = {'outputs': {'step-1::aligned': {'files': {'aligned': str(path)}}}}
        assertion = {'output': 'aligned', 'kind': 'fasta', 'records': 2,
                     'aligned': True, 'ungapped': {'a': 'ACGT', 'b': 'ACT'}}
        path.write_text('>a\nACGT\n>b\nAC-T\n')
        _assert_output(assertion, result)
        for invalid in ('>a\nACGT\n>b\nACT\n', '>a\nACGT\n>b\nAG-T\n'):
            path.write_text(invalid)
            with self.assertRaises(ValueError):
                _assert_output(assertion, result)

    def test_structured_sam_truth_checks_flags_reference_samples_and_splice(self):
        path = self.root / 'alignments.sam'
        sam = ('@HD\tVN:1.6\tSO:unsorted\n@SQ\tSN:chr1\tLN:300\n@RG\tID:rg1\tSM:validation\n'
               'read\t99\tchr1\t31\t60\t30M100N30M\t=\t201\t230\t'+('A'*60)+'\t'+('I'*60)+'\tRG:Z:rg1\tXS:A:+\n'
               'read\t147\tchr1\t201\t60\t60M\t=\t31\t-230\t'+('T'*60)+'\t'+('I'*60)+'\tRG:Z:rg1\n')
        result = {'outputs': {'step-1::sam': {'files': {'sam': str(path)}}}}
        assertion = {'output':'sam','kind':'sam','records':2,'mapped':2,'paired':2,'properPairs':2,
                     'secondary':0,'supplementary':0,'spliced':1,'references':{'chr1':300},
                     'samples':['validation'],'allReadGroups':True,
                     'alignments':[{'name':'read','reference':'chr1','position':31,'cigar':'30M100N30M','flag':99,'tags':{'RG':'rg1','XS':'+'}},
                                   {'name':'read','position':201,'flag':147}]}
        path.write_text(sam)
        _assert_output(assertion,result)
        for changed in (sam.replace('SM:validation','SM:wrong'),sam.replace('LN:300','LN:301'),
                        sam.replace('30M100N30M','60M'),sam.replace('RG:Z:rg1','RG:Z:unknown'),
                        sam.replace('\t99\t','\t97\t')):
            path.write_text(changed)
            with self.assertRaises(ValueError):
                _assert_output(assertion,result)

    def test_structured_vcf_truth_checks_site_sample_genotype_and_absence(self):
        path = self.root / 'variants.vcf.gz'
        vcf = ('##fileformat=VCFv4.2\n'
               '#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tvalidation\n'
               'chr1\t101\t.\tA\tG\t70\tPASS\tDP=20;SOMATIC\tGT:DP\t0/1:20\n')
        result = {'outputs': {'step-1::variants': {'files': {'variants': str(path)}}}}
        assertion = {'output':'variants','kind':'vcf','records':1,'samples':['validation'],
                     'variants':[{'chrom':'chr1','pos':101,'ref':'A','alt':'G','filter':'PASS',
                                  'info':{'DP':'20','SOMATIC':True},'genotypes':{'validation':'0/1'}}],
                     'absentVariants':[{'chrom':'chr1','pos':102,'ref':'A','alt':'T'}]}
        with gzip.open(path,'wt') as stream:
            stream.write(vcf)
        _assert_output(assertion,result)
        for changed in (vcf.replace('0/1:20','0/0:20'),vcf.replace('\tG\t','\tT\t'),
                        vcf.replace('\tPASS\t','\tLowQual\t'),vcf.replace('DP=20','DP=2'),
                        vcf.replace('\tvalidation\n','\twrong\n')):
            with gzip.open(path,'wt') as stream:
                stream.write(changed)
            with self.assertRaises(ValueError):
                _assert_output(assertion,result)

    def test_site_only_vcf_and_bounded_decompression(self):
        path = self.root/'sites.vcf.gz'
        result = {'outputs': {'step-1::sites': {'files': {'sites': str(path)}}}}
        assertion = {'output':'sites','kind':'vcf','records':1,'samples':[],
                     'variants':[{'chrom':'chr1','pos':20,'ref':'T','alt':'C'}]}
        with gzip.open(path,'wt') as stream:
            stream.write('##fileformat=VCFv4.2\n#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\nchr1\t20\t.\tT\tC\t40\tPASS\tDP=10\n')
        _assert_output(assertion,result)
        with gzip.open(path,'wb') as stream:
            stream.write(b'x'*(4*1024*1024+1))
        with self.assertRaisesRegex(ValueError,'Decompressed'):
            _assert_output(assertion,result)


if __name__ == '__main__':
    unittest.main()
