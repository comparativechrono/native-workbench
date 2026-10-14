"""Real SeqKit/VSEARCH/MUSCLE integration through the frozen DAG engine.

Set NW_APP_ROOT to an assembled 0.5.2 runtime. Linux binaries are a separately
SHA-pinned, test-only substitution for the declared Windows executables. These
tests verify scientific arguments and engine integration, not Windows execution.
MUSCLE uses the same documented workbench1 source patch as its Windows build;
SeqKit and VSEARCH use their official pinned Linux release binaries.
The same pack self-check assets run with the native backend from the Windows UI.
"""
import copy
import csv
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest

SOURCE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SOURCE / 'workspace'))
from catalog import load_catalog, parse_pack
from engine import Engine, digest_file
from pack_checks import run_pack_checks
from verify_installation import check_packs

APP = Path(os.environ.get('NW_APP_ROOT', SOURCE.parents[1] / 'integration-0.5.2' / 'native-workbench')).resolve()
BINARIES = {
    'seqkit': (Path(os.environ.get('NW_SEQKIT_LINUX', SOURCE.parents[1] / 'expansion-vendor/seqkit/linux/seqkit')),
               '88aa8a539b1e9097220a47811367b7ef826eff8637e5284fdd32a372770d6f7d'),
    'vsearch': (Path(os.environ.get('NW_VSEARCH_LINUX', SOURCE / 'build/vsearch/linux/vsearch-2.32.0-linux-x86_64/bin/vsearch')),
                'bfc7c72c67eab9bc86a5d408278ab596ee9702c428fc832316acfc0317e4cd1a'),
    'muscle': (Path(os.environ.get('NW_MUSCLE_LINUX', SOURCE / 'vendor-expanded/muscle-5.3/build-linux/muscle')),
               'a40a9b0183986ba93de71b068bf2be2f1cb630ecfa69e1459c6b30a08111a2f0'),
}


class LinuxExpansionBackend:
    """Execute published manifest arguments with pinned Linux reference builds."""
    def __init__(self):
        self.calls = []
        self.commands = []
        for identity, (path, checksum) in BINARIES.items():
            if not path.is_file():
                raise RuntimeError('Required real integration binary is missing: ' + str(path))
            if digest_file(path) != checksum:
                raise RuntimeError('Integration binary hash differs: ' + identity)

    def run(self, request, event, cancel):
        self.calls.append(copy.deepcopy(request))
        pack_root = Path(request['pack_folder'])
        if digest_file(pack_root / 'pack.ini') != request['pack_sha256']:
            raise ValueError('Pack changed before the test adapter executed')
        pack = parse_pack((pack_root / 'pack.ini').read_text(encoding='utf-8'))
        workflow = pack['workflows'][request['workflow_id']]
        folder = Path(request['output_folder']) / 'linux-validation'
        folder.mkdir()
        outputs = {item['id']: str(folder / item['path']) for item in workflow['outputs']}
        for filename in outputs.values():
            Path(filename).parent.mkdir(parents=True, exist_ok=True)
        assets = {key: str(pack_root / value['path']) for key, value in pack['assets'].items()}

        def expand(value):
            value = value.replace('{run}', str(folder))
            for kind, bindings in (('input', request['values']), ('output', outputs), ('asset', assets)):
                for key, replacement in bindings.items():
                    value = value.replace('{' + kind + ':' + key + '}', str(replacement))
            if '{' in value or '}' in value:
                raise ValueError('Unexpanded manifest placeholder: ' + value)
            return value

        def command(identity, arguments):
            declared = pack['tools'][identity]
            if digest_file(pack_root / declared['path']) != declared['sha256']:
                raise ValueError('Declared Windows executable hash differs')
            if identity == 'paircheck':
                # Existing portable integrity-pinned mate checker used by the
                # VSEARCH pack before overlap merging; it is not substituted.
                argv = [str(SOURCE / 'baselines/bin/ape-loader-linux'), str(pack_root / declared['path'])]
            elif identity not in BINARIES:
                raise ValueError('No explicit test substitution for executable: ' + identity)
            else:
                binary, checksum = BINARIES[identity]
                if digest_file(binary) != checksum:
                    raise ValueError('Linux validation executable changed')
                argv = [str(binary)]
            for argument in arguments:
                if argument.startswith('{inputs:') and argument.endswith('}'):
                    argv.extend(str(request['values'][argument[8:-1]]).splitlines())
                else:
                    argv.append(expand(argument))
            self.commands.append(argv)
            return argv

        try:
            for step in workflow['steps']:
                if cancel.is_set():
                    return {'success': False, 'cancelled': True, 'folder': str(folder)}
                event({'type': 'phase', 'message': step['label']})
                if step['kind'] == 'copy':
                    shutil.copyfile(expand(step['source']), outputs[step['destination']])
                    continue
                if step['kind'] != 'exec':
                    raise ValueError('Expansion validation adapter requires explicit exec/copy steps')
                stdout_path = Path(outputs[step['stdout']]) if step.get('stdout') else folder / (step['id'] + '.stdout.txt')
                stderr_path = folder / (step['id'] + '.stderr.txt')
                with stdout_path.open('wb') as stdout, stderr_path.open('wb') as stderr:
                    completed = subprocess.run(command(step['tool'], step['args']), cwd=folder,
                                               stdout=stdout, stderr=stderr, timeout=45)
                if completed.returncode:
                    raise ValueError('Real tool failed (%s): %s' % (completed.returncode, stderr_path.read_text(errors='replace')[-8000:]))
            for output in workflow['outputs']:
                path = Path(outputs[output['id']])
                if not path.is_file() or (output['nonempty'] and path.stat().st_size == 0):
                    raise ValueError('Manifest output missing or unexpectedly empty: ' + output['id'])
            return {'success': True, 'folder': str(folder), 'message': 'Real pinned Linux scientific executable completed'}
        except Exception as exc:
            return {'success': False, 'folder': str(folder), 'message': str(exc)}


def fasta_records(path):
    records = {}
    identity = None
    for line in Path(path).read_text().splitlines():
        if line.startswith('>'):
            identity = line[1:].split()[0]
            if identity in records:
                raise AssertionError('Duplicate FASTA identifier: ' + identity)
            records[identity] = ''
        elif line.strip():
            if identity is None:
                raise AssertionError('Sequence precedes FASTA header')
            records[identity] += line.strip()
    return records


def output_path(record, reference):
    files = record['outputs'][reference]['files']
    if len(files) != 1:
        raise AssertionError('Choose a field for grouped output: ' + reference)
    return Path(next(iter(files.values())))


def node(identity, tool, inputs, params=None, label=None):
    item = {'id': identity, 'tool': tool, 'inputs': inputs, 'params': params or {}}
    if label:
        item['label'] = label
    return item


def source(identity, kind, path, label='Sequences'):
    return {'id': identity, 'type': kind, 'label': label, 'files': {'sequences': str(path)}}


class ExpansionPipelineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = load_catalog(APP)
        cls.selfcheck_summary = []
        cls.executed_graphs = []
        # Mirror native closed inventory and every declared asset hash before
        # allowing the Linux argv adapter to provide scientific evidence.
        check_packs(APP, cls.catalog)
        for family in ('seqkit', 'vsearch', 'muscle'):
            if not any(t['packId'] == family for t in cls.catalog['tools'].values()):
                raise RuntimeError('Required expansion pack missing: ' + family)

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='expansion-pipeline-')
        self.folder = Path(self.temporary.name)
        self.backend = LinuxExpansionBackend()
        self.engine = Engine(APP, self.catalog, backend=self.backend)

    def tearDown(self):
        self.temporary.cleanup()

    def execute(self, graph):
        review = self.engine.review(graph)
        self.assertTrue(review['valid'], review)
        plan = self.engine.prepare(graph, self.folder)
        result = self.engine.execute(plan)
        self.assertTrue(result['success'], result)
        self.__class__.executed_graphs.append({
            'name': graph.get('name', 'Unnamed graph'), 'plan_sha256': plan['sha256'],
            'nodes': [{'id': n['id'], 'tool': n['tool'], 'status': n['status'], 'pin': n['pin']}
                      for n in result['nodes']],
            'outputs': {ref: {'type': value['type'], 'sha256': value['sha256']}
                        for ref, value in result['outputs'].items()},
            'methods': result['methods'],
        })
        return plan, result

    def test_every_new_family_declares_and_passes_native_check_contract(self):
        report = run_pack_checks(APP, self.catalog, self.folder, backend=self.backend)
        self.__class__.selfcheck_summary = [{k: c[k] for k in ('id', 'status', 'message') if k in c}
                                          for c in report['checks']]
        self.assertTrue(report['success'], report)
        for family in ('seqkit', 'vsearch', 'muscle'):
            cases = [c for c in report['checks'] if c['id'].startswith(family + '/')]
            self.assertTrue(cases, 'No meaningful check declared by ' + family)
            self.assertTrue(all(c['status'] == 'passed' for c in cases), cases)
        self.assertFalse(report['nativeWindowsExecuted'], 'This suite is Linux validation only')

    def test_sequence_filter_branches_to_alignment_statistics_and_report(self):
        sequences = {
            'alpha': 'ATGGCCATTGTAATGGGCCGCTGAAAGGGTGCCCGATAG' * 3,
            'beta': 'ATGGCCATTGTAATGGGCCGCTGGAAGGGTGCCCGATAG' * 3,
            'gamma': 'ATGGCCGTAATGGGCCGCTGAAAGGGTGCCCGATAG' * 3,
            'too-short': 'ACGT',
        }
        path = self.folder / 'homologues.fa'
        path.write_text(''.join('>' + k + '\n' + v + '\n' for k, v in sequences.items()))
        graph = {'schema': 1, 'name': 'Filter and inspect homologues',
                 'sources': [source('input-1', 'fasta-nucleotide', path, 'Unaligned homologues')],
                 'nodes': [
                     node('step-1', 'seqkit/filter-nucleotide', {'sequences': ['input-1']},
                          {'min-length': '80', 'threads': '1'}, 'Keep long homologues'),
                     node('step-2', 'muscle/align-nucleotide', {'sequences': ['step-1::result']},
                          {'threads': '1'}, 'Align retained homologues'),
                     node('step-3', 'seqkit/statistics-nucleotide', {'sequences': ['step-1::result']},
                          {'threads': '1'}, 'Retained sequence statistics'),
                     node('step-4', 'seqkit/statistics-nucleotide', {'sequences': ['input-1']},
                          {'threads': '1'}, 'Original sequence statistics'),
                     node('step-5', 'builtin/report', {'metrics': ['step-3::statistics', 'step-4::statistics']},
                          {'title': 'Before and after length selection'}),
                 ]}
        self.assertEqual(self.engine.rank_groups(graph), [
            {'rank': 1, 'nodes': ['step-1', 'step-4']},
            {'rank': 2, 'nodes': ['step-2', 'step-3']},
            {'rank': 3, 'nodes': ['step-5']},
        ])
        plan, record = self.execute(graph)
        expected = {k: v for k, v in sequences.items() if k != 'too-short'}
        self.assertEqual(fasta_records(output_path(record, 'step-1::result')), expected)
        aligned = fasta_records(output_path(record, 'step-2::aligned'))
        self.assertEqual({k: v.replace('-', '') for k, v in aligned.items()}, expected)
        self.assertEqual(len({len(v) for v in aligned.values()}), 1)
        self.assertEqual(record['outputs']['step-2::aligned']['type'], 'msa-nucleotide')
        for reference, count in (('step-3::statistics', 3), ('step-4::statistics', 4)):
            rows = list(csv.DictReader(output_path(record, reference).read_text().splitlines(), delimiter='\t'))
            self.assertEqual(int(rows[0]['num_seqs']), count)
        report = output_path(record, 'step-5::report').read_text()
        self.assertEqual(report.count('<section>'), 2)
        self.assertIn('Retained sequence statistics', report)
        self.assertIn('Original sequence statistics', report)
        self.assertIn('SeqKit', record['methods'])
        self.assertIn('MUSCLE', record['methods'])
        self.assertIn('2.14.0', record['methods'])
        self.assertIn('step-1::result', json.dumps(plan))
        for entry in record['nodes']:
            self.assertEqual(entry['pin']['manifestSha256'], self.catalog['tools'][entry['tool']]['manifestSha256'])
        for descriptor in record['outputs'].values():
            for field, filename in descriptor['files'].items():
                self.assertEqual(descriptor['sha256'][field], digest_file(filename))
        template = self.engine.save_pipeline(graph)
        self.assertNotIn('files', template['sources'][0])
        self.assertEqual(template['nodes'][1]['inputs']['sequences'], ['step-1::result'])

    def test_translation_flows_to_protein_alignment_without_losing_stops(self):
        coding = {
            'cds1': 'ATGGCCATTGTAATGGGCCGCTGAAAGGGTGCCCGATAG',
            'cds2': 'ATGGCCATTGTAATGGGCCGCTGGAAGGGTGCCCGATAG',
            'cds3': 'ATGGCCGTAATGGGCCGCTGAAAGGGTGCCCGATAG',
        }
        expected = {'cds1_frame=1': 'MAIVMGR*KGAR*', 'cds2_frame=1': 'MAIVMGRWKGAR*',
                    'cds3_frame=1': 'MAVMGR*KGAR*'}
        path = self.folder / 'coding.fa'
        path.write_text(''.join('>' + k + '\n' + v + '\n' for k, v in coding.items()))
        graph = {'name': 'Translate and align protein',
                 'sources': [source('input-1', 'fasta-nucleotide', path)],
                 'nodes': [
                     node('step-1', 'seqkit/translate', {'sequences': ['input-1']},
                          {'frame': '1', 'code': '1', 'threads': '1'}),
                     node('step-2', 'muscle/align-protein', {'sequences': ['step-1::result']}, {'threads': '1'}),
                 ]}
        _, record = self.execute(graph)
        self.assertEqual(fasta_records(output_path(record, 'step-1::result')), expected)
        aligned = fasta_records(output_path(record, 'step-2::aligned'))
        self.assertEqual({k: v.replace('-', '') for k, v in aligned.items()}, expected)
        self.assertEqual(len({len(v) for v in aligned.values()}), 1)
        self.assertEqual(record['outputs']['step-1::result']['type'], 'fasta-protein')
        self.assertEqual(record['outputs']['step-2::aligned']['type'], 'msa-protein')

    def test_reads_to_dereplication_clustering_and_attributed_report_preserves_counts(self):
        a = 'ACGT' * 30
        b = a[:40] + 'T' + a[41:]
        c = 'GATTTCCGAA' * 12
        reads = [('a1', a), ('a2', a), ('a3', a), ('b1', b), ('b2', b), ('c1', c)]
        path = self.folder / 'amplicons.fastq'
        path.write_text(''.join('@' + k + '\n' + v + '\n+\n' + 'I' * len(v) + '\n' for k, v in reads))
        graph = {'name': 'Dereplicate and cluster amplicon reads',
                 'sources': [source('input-1', 'reads', path, 'Six unpaired amplicon reads')],
                 'nodes': [
                     node('step-1', 'seqkit/fastq-to-fasta', {'sequences': ['input-1']}, {'threads': '1'}),
                     node('step-2', 'vsearch/dereplicate', {'sequences': ['step-1::result']},
                          {'strand': 'plus'}, 'Count unique amplicons'),
                     node('step-3', 'vsearch/cluster-abundance', {'sequences': ['step-2::unique']},
                          {'identity': '0.97', 'strand': 'plus', 'threads': '1'}, 'Cluster at 97 percent identity'),
                     node('step-4', 'seqkit/statistics-reads', {'sequences': ['input-1']},
                          {'threads': '1'}, 'Original amplicon read statistics'),
                     node('step-5', 'builtin/report', {'metrics': ['step-2::log', 'step-3::log', 'step-4::statistics']},
                          {'title': 'Amplicon operation evidence'}),
                 ]}
        _, record = self.execute(graph)
        unique = fasta_records(output_path(record, 'step-2::unique'))
        counts = {v: int(re.search(r';size=(\d+)', k).group(1)) for k, v in unique.items()}
        self.assertEqual(counts, {a: 3, b: 2, c: 1})
        centroids = fasta_records(output_path(record, 'step-3::centroids'))
        self.assertEqual(len(centroids), 2)
        cluster_counts = [int(re.search(r';size=(\d+)', k).group(1)) for k in centroids]
        self.assertEqual(sorted(cluster_counts), [1, 5])
        self.assertEqual(sum(cluster_counts), len(reads))
        self.assertEqual(record['outputs']['step-3::centroids']['type'], 'fasta-nucleotide-abundance')
        report = output_path(record, 'step-5::report').read_text()
        self.assertEqual(report.count('<section>'), 3)
        self.assertIn('Count unique amplicons', report)
        self.assertIn('Cluster at 97 percent identity', report)
        self.assertIn('Original amplicon read statistics', report)
        self.assertIn('2.32.0', record['methods'])
        self.assertIn('0.97', record['methods'])
        self.assertIn('--sizein', self.backend.commands[-1])
        self.assertTrue(any('--sizeout' in command for command in self.backend.commands))

    def test_weighted_dereplication_and_abundance_filter_count_observations(self):
        a, b = 'ACGT' * 30, 'GATTTCCGAA' * 12
        path = self.folder / 'weighted.fa'
        path.write_text('>a;size=10;\n' + a + '\n>a-copy;size=4;\n' + a + '\n>b;size=2;\n' + b + '\n')
        graph = {'name': 'Preserve weighted observations',
                 'sources': [source('input-1', 'fasta-nucleotide-abundance', path)],
                 'nodes': [
                     node('step-1', 'vsearch/dereplicate-weighted', {'sequences': ['input-1']}),
                     node('step-2', 'vsearch/filter-abundance', {'sequences': ['step-1::unique']},
                          {'minimum-abundance': '3'}),
                 ]}
        _, record = self.execute(graph)
        unique = fasta_records(output_path(record, 'step-1::unique'))
        self.assertEqual({v: int(re.search(r';size=(\d+)', k).group(1)) for k, v in unique.items()}, {a: 14, b: 2})
        retained = fasta_records(output_path(record, 'step-2::retained'))
        self.assertEqual(list(retained.values()), [a])
        self.assertEqual(int(re.search(r';size=(\d+)', next(iter(retained))).group(1)), 14)

    def test_incompatible_biological_types_cannot_be_connected(self):
        path = self.folder / 'fixture.fa'
        path.write_text('>one\nACGTACGT\n>two\nACGTTCGT\n')
        graph = {'sources': [source('input-1', 'fasta-protein', path)],
                 'nodes': [node('step-1', 'muscle/align-nucleotide', {'sequences': ['input-1']})]}
        self.assertFalse(self.engine.validate(graph, check_files=False)['valid'])
        graph['sources'][0]['type'] = 'fasta-nucleotide'
        graph['nodes'].append(node('step-2', 'seqkit/filter-nucleotide', {'sequences': ['step-1::aligned']}))
        self.assertFalse(self.engine.validate(graph, check_files=False)['valid'], 'Aligned FASTA must not be treated as unaligned sequences')
        graph['nodes'] = [node('step-1', 'seqkit/sample-reads', {'sequences': ['input-1']})]
        graph['sources'][0]['type'] = 'pair'
        self.assertFalse(self.engine.validate(graph, check_files=False)['valid'], 'Sampling one file cannot consume an atomic pair')
        graph['nodes'] = [node('step-1', 'seqkit/statistics-nucleotide', {'sequences': ['input-1']})]
        graph['sources'][0]['type'] = 'fasta-nucleotide-abundance'
        self.assertFalse(self.engine.validate(graph, check_files=False)['valid'], 'Record statistics must not silently discard abundance semantics')

    def test_protein_mislabeled_as_nucleotide_rejected_before_binary_execution(self):
        path = self.folder / 'protein-with-dna-header.fa'
        path.write_text('>protein\nMAIVMGRWKGARL\n>another\nMAIVMGRWKGARF\n')
        graph = {'sources': [source('input-1', 'fasta-nucleotide', path)],
                 'nodes': [node('step-1', 'muscle/align-nucleotide', {'sequences': ['input-1']})]}
        try:
            plan = self.engine.prepare(graph, self.folder)
        except ValueError:
            pass
        else:
            record = self.engine.execute(plan)
            self.assertFalse(record['success'], record)
        self.assertFalse(self.backend.calls, 'Alphabet validation must reject content before a biological tool receives it')

    def test_raw_and_weighted_external_fasta_cannot_silently_exchange_counts(self):
        for workflow, kind, content in (
            ('dereplicate', 'fasta-nucleotide', '>weighted;size=10;\n' + 'ACGT' * 30 + '\n'),
            ('dereplicate-weighted', 'fasta-nucleotide-abundance', '>missing-count\n' + 'ACGT' * 30 + '\n'),
            ('dereplicate-weighted', 'fasta-nucleotide-abundance', '>zero;size=0;\n' + 'ACGT' * 30 + '\n'),
            ('dereplicate-weighted', 'fasta-nucleotide-abundance', ''.join(
                '>overflow%d;size=9223372036854775807;\n%s\n' % (i, 'ACGT' * 30) for i in range(3))),
        ):
            with self.subTest(workflow=workflow, content=content[:30]):
                path = self.folder / ('invalid-' + str(len(list(self.folder.iterdir()))) + '.fa')
                path.write_text(content)
                graph = {'sources': [source('input-1', kind, path)],
                         'nodes': [node('step-1', 'vsearch/' + workflow, {'sequences': ['input-1']})]}
                try:
                    plan = self.engine.prepare(graph, self.folder)
                except ValueError:
                    pass
                else:
                    result = self.engine.execute(plan)
                    self.assertFalse(result['success'], result)
                self.assertFalse(self.backend.calls, 'Count validation must fail before executing VSEARCH')

    def test_nucleotide_sequence_output_is_not_a_genomic_reference(self):
        path = self.folder / 'sequences.fa'
        path.write_text('>sequence\nACGTACGT\n')
        reads = self.folder / 'reads.fastq'
        reads.write_text('@r\nACGT\n+\nIIII\n')
        graph = {'sources': [source('input-1', 'fasta-nucleotide', path),
                             source('input-2', 'reads', reads)],
                 'nodes': [
                     node('step-1', 'seqkit/filter-nucleotide', {'sequences': ['input-1']}),
                     node('step-2', 'align/single-end', {'reference': ['step-1::result'], 'reads1': ['input-2']}),
                 ]}
        self.assertTrue('align/single-end' in self.catalog['tools'], 'Baseline minimap2 single-end operation is missing')
        result = self.engine.validate(graph, check_files=False)
        errors = [e for e in result['errors'] if e.get('nodeId') == 'step-2' and e.get('portId') == 'reference']
        self.assertTrue(any('fasta-nucleotide cannot feed reference' in e['message'] for e in errors), result)

    def test_rna_filter_to_alignment_retains_uracil(self):
        sequences = {'rna1': 'ACGUACGUACGUACGU', 'rna2': 'ACGUACUACGUACGU'}
        path = self.folder / 'rna.fa'
        path.write_text(''.join('>' + k + '\n' + v + '\n' for k, v in sequences.items()))
        graph = {'name': 'Filter and align RNA without changing uracil',
                 'sources': [source('input-1', 'fasta-nucleotide', path)],
                 'nodes': [
                     node('step-1', 'seqkit/filter-nucleotide', {'sequences': ['input-1']}, {'threads': '1'}),
                     node('step-2', 'muscle/align-nucleotide', {'sequences': ['step-1::result']}, {'threads': '1'}),
                 ]}
        _, result = self.execute(graph)
        aligned = fasta_records(output_path(result, 'step-2::aligned'))
        self.assertEqual({k: v.replace('-', '') for k, v in aligned.items()}, sequences)
        self.assertEqual(len({len(v) for v in aligned.values()}), 1)


if __name__ == '__main__':
    unittest.main()
