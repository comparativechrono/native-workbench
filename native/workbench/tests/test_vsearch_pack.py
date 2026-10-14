"""Real VSEARCH 2.32.0 Linux reference tests of the Windows pack argv.

These tests do not execute the Windows executable. Native fixtures additionally
run through the ordinary Engine when installation checks are requested on Windows.
"""
import hashlib
import json
from pathlib import Path
import random
import re
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'workspace'))
from catalog import load_pack
from pack_checks import _assert_output

PACK = ROOT/'packs/vsearch-0.5.2'
VSEARCH = ROOT/'build/vsearch/linux/vsearch-2.32.0-linux-x86_64/bin/vsearch'
PAIR = ROOT/'baselines/bin/paircheck-linux'


def fasta(path):
    records, key = {}, None
    for line in path.read_text().splitlines():
        if line.startswith('>'):
            key = line[1:].split()[0]
            records[key] = ''
        elif line:
            records[key] += line
    return records


def abundance(records):
    return {sequence: int(re.search(r';size=(\d+)(?:;|$)', key).group(1)) for key,sequence in records.items()}


class VsearchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not VSEARCH.is_file():
            raise RuntimeError('Pinned VSEARCH Linux reference binary is required')
        cls.pack = load_pack(PACK/'pack.ini')
        cls.schema = json.loads((PACK/'workbench-schema.json').read_text())
        PAIR.chmod(PAIR.stat().st_mode | 0o100)

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='vsearch science ')
        self.root = Path(self.temporary.name)
        self.counter = 0

    def tearDown(self):
        self.temporary.cleanup()

    def run_workflow(self, identity, values):
        self.counter += 1
        folder = self.root/str(self.counter)
        folder.mkdir()
        wf = self.pack['workflows'][identity]
        inputs = {item['id']: item.get('default','') for item in wf['inputs']}
        inputs.update({key:str(value) for key,value in values.items()})
        outputs = {item['id']:folder/item['path'] for item in wf['outputs']}
        def expand(value):
            for kind, bindings in [('input',inputs),('output',outputs)]:
                for key, content in bindings.items():
                    value = value.replace('{'+kind+':'+key+'}',str(content))
            return value
        for step in wf['steps']:
            executable = PAIR if step['tool']=='paircheck' else VSEARCH
            result = subprocess.run([str(executable)]+[expand(arg) for arg in step['args']],cwd=folder,capture_output=True,timeout=30)
            (folder/(step['id']+'.stderr')).write_bytes(result.stderr)
            self.assertEqual(result.returncode,0,result.stderr.decode(errors='replace'))
            if step.get('stdout'):
                outputs[step['stdout']].write_bytes(result.stdout)
        for item in wf['outputs']:
            self.assertTrue(outputs[item['id']].is_file(),item)
            if item['nonempty']:
                self.assertGreater(outputs[item['id']].stat().st_size,0,item)
        return outputs

    def test_all_pinned_files_and_seven_typed_workflows(self):
        self.assertEqual(len(self.pack['workflows']),7)
        for item in list(self.pack['tools'].values())+list(self.pack['assets'].values()):
            self.assertEqual(hashlib.sha256((PACK/item['path']).read_bytes()).hexdigest(),item['sha256'])
        for identity,metadata in self.schema['workflows'].items():
            self.assertTrue(any(item['id']=='log' and item['type']=='metrics' for item in metadata['outputs']),identity)
        self.assertEqual(self.pack['workflows']['merge-pairs']['steps'][0]['tool'],'paircheck')

    def test_native_inventory_limits_and_declared_runtime_files(self):
        allowed = {'pack.ini','PACK-README.md','PACK-README.txt','README.txt'}
        allowed.update(item['path'] for item in list(self.pack['tools'].values())+list(self.pack['assets'].values()))
        items = list(PACK.rglob('*'))
        self.assertLessEqual(len(items),2000)
        self.assertLessEqual(sum(p.stat().st_size for p in items if p.is_file()),256*1024*1024)
        for path in items:
            relative = path.relative_to(PACK).as_posix()
            self.assertFalse(path.is_symlink())
            self.assertLessEqual(len(path.relative_to(PACK).parts),12)
            if path.is_file():
                self.assertTrue(relative in allowed or relative.startswith('licenses/'),relative)

    def test_declared_native_self_checks_against_linux_reference(self):
        checks = json.loads((PACK/'workbench-checks.json').read_text())
        for case in checks['checks']:
            with self.subTest(case=case['id']):
                values = dict(case['params'])
                for members in case['inputs'].values():
                    for member in members:
                        values.update({key:PACK/self.pack['assets'][asset]['path'] for key,asset in member.items()})
                outputs = self.run_workflow(case['workflow'],values)
                metadata = self.schema['workflows'][case['workflow']]
                result = {'outputs':{'step-1::'+item['id']:{'files':{field:str(outputs[field]) for field in item['manifestOutputs']}} for item in metadata['outputs']}}
                for expectation in case['expect']:
                    _assert_output(expectation,result)

    def test_quality_filter_exact_expected_error_selection(self):
        outputs = self.run_workflow('quality-filter',{'reads':PACK/'fixtures/quality-fastq.txt'})
        self.assertEqual(list(fasta(outputs['fasta'])),['good'])
        self.assertIn('@good\n',outputs['retained'].read_text())
        self.assertNotIn('@bad\n',outputs['retained'].read_text())
        self.assertIn('@bad\n',outputs['discarded'].read_text())
        self.assertNotIn('@good\n',outputs['discarded'].read_text())

    def test_dereplication_distinguishes_records_from_abundances(self):
        weighted = PACK/'fixtures/weighted-fasta.txt'
        records = fasta(weighted)
        sequences = list(records.values())
        raw = self.run_workflow('dereplicate',{'sequences':weighted})
        summed = self.run_workflow('dereplicate-weighted',{'sequences':weighted})
        self.assertEqual(abundance(fasta(raw['unique'])),{sequences[0]:2,sequences[2]:1})
        self.assertEqual(abundance(fasta(summed['unique'])),{sequences[0]:10,sequences[2]:2})
        # Explicitly test reverse-complement grouping; plus remains orientation-specific.
        sequence = sequences[0]
        path = self.root/'strand.fasta'
        path.write_text('>a\n'+sequence+'\n>b\n'+sequence.translate(str.maketrans('ACGT','TGCA'))[::-1]+'\n')
        plus = self.run_workflow('dereplicate',{'sequences':path,'strand':'plus'})
        both = self.run_workflow('dereplicate',{'sequences':path,'strand':'both'})
        self.assertEqual(len(fasta(plus['unique'])),2)
        self.assertEqual(list(abundance(fasta(both['unique'])).values()),[2])

    def test_minimum_abundance_preserves_counts_and_all_rejected_is_valid(self):
        unique = self.run_workflow('dereplicate-weighted',{'sequences':PACK/'fixtures/weighted-fasta.txt'})['unique']
        retained = self.run_workflow('filter-abundance',{'sequences':unique,'minimum-abundance':'3'})
        self.assertEqual(list(abundance(fasta(retained['retained'])).values()),[10])
        empty = self.run_workflow('filter-abundance',{'sequences':unique,'minimum-abundance':'20'})
        self.assertEqual(empty['retained'].read_text(),'')

    def test_clustering_identity_and_abundance_membership(self):
        initial = list(fasta(PACK/'fixtures/weighted-fasta.txt').values())
        near = list(initial[0])
        for at in (40,80,120):
            near[at] = {'A':'C','C':'G','G':'T','T':'A'}[near[at]]
        path = self.root/'cluster.fasta'
        path.write_text('>parent;size=7;\n'+initial[0]+'\n>near;size=3;\n'+''.join(near)+'\n>other;size=2;\n'+initial[2]+'\n')
        strict = self.run_workflow('cluster-abundance',{'sequences':path,'identity':'1.0'})
        relaxed = self.run_workflow('cluster-abundance',{'sequences':path,'identity':'0.97'})
        self.assertEqual(sorted(abundance(fasta(strict['centroids'])).values()),[2,3,7])
        self.assertEqual(abundance(fasta(relaxed['centroids'])),{initial[0]:10,initial[2]:2})
        membership = relaxed['membership'].read_text()
        self.assertIn('98.5',membership)
        self.assertIn('near;size=3;',membership)
        self.assertIn('parent;size=7;',membership)

    def test_chimera_reference_classification_and_counts(self):
        rng = random.Random(888)
        parent_a = ''.join(rng.choice('ACGT') for _ in range(400))
        parent_b = list(parent_a)
        for at in range(3,400,4):
            parent_b[at] = {'A':'C','C':'G','G':'T','T':'A'}[parent_b[at]]
        parent_b = ''.join(parent_b)
        chimera = parent_a[:200]+parent_b[200:]
        reference, queries = self.root/'reference.fasta', self.root/'queries.fasta'
        reference.write_text('>parentA\n'+parent_a+'\n>parentB\n'+parent_b+'\n')
        queries.write_text('>real;size=20;\n'+parent_a+'\n>chimera;size=3;\n'+chimera+'\n')
        outputs = self.run_workflow('chimera-reference',{'sequences':queries,'reference':reference})
        self.assertEqual(abundance(fasta(outputs['nonchimeras'])),{parent_a:20})
        self.assertEqual(abundance(fasta(outputs['chimeras'])),{chimera:3})
        self.assertEqual(fasta(outputs['borderline']),{})
        rows = [line.split('\t') for line in outputs['classification'].read_text().splitlines()]
        self.assertEqual({row[1].split(';')[0]:row[-1] for row in rows},{'real':'N','chimera':'Y'})
        self.assertTrue(all(len(row)==18 for row in rows))

    def test_mate_identity_mismatch_fails_before_merge(self):
        wrong = self.root/'wrong.fastq'
        wrong.write_text((PACK/'fixtures/merge-r2.txt').read_text().replace('amplicon/2','wrong/2'))
        result = subprocess.run([str(PAIR),'--reads1',str(PACK/'fixtures/merge-r1.txt'),'--reads2',str(wrong)],capture_output=True)
        self.assertNotEqual(result.returncode,0)
        self.assertIn('identifiers differ',result.stderr.decode().lower())


if __name__=='__main__':
    unittest.main()
