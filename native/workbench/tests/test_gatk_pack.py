#!/usr/bin/env python3
"""Execute GATK pack argv with the pinned Linux Java, recording that boundary.

Installation checks use the same manifest and independent synthetic truth on
the native Windows bridge. This suite additionally inspects BAM records and
composes real merging/genotyping operations; a Linux pass is not Windows proof.
"""
import argparse
import collections
import copy
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
PACK = Path(os.environ.get('NW_GATK_PACK', ROOT / 'packs/gatk-1.0.0')).resolve()
JAVA_HOME = Path(os.environ.get('NW_GATK_JAVA_HOME', ROOT / 'build/gatk-jre/jdk-17.0.20.1+1-jre')).resolve()
LOADER = Path(os.environ.get('NW_GATK_LOADER', ROOT / 'build/gatk-tools/ape-loader-linux')).resolve()
JAVA_PINS = {
    'bin/java': 'f5aed21d3a0b0f4b05d3a3f9fe71263916d5bc0d47b53aa52a3340b90f0b4805',
    'lib/libjava.so': '180b9143f1b0889e492f21aecbcc4917c2fe168498d5f2589ad6b9403ef26026',
    'lib/server/libjvm.so': '11e5d09f442e42bddc4619b6eed829eaf3952158a5f77c797a58d558fae21738',
    'lib/modules': '7c4331d913282f8b4afef338a8b6313c2bd5c7c56ca4973504f14624e331a572',
    'release': 'a23a26314d44357bfbcee8358e63ffc117c42e6b6580bb0d27ccfef2c5d53983',
}
LOADER_SHA = 'ad98161cba98163f6aa383595804489cec52a9ff3b902be16b29368e171ba359'
sys.path.insert(0, str(ROOT / 'workspace'))
from catalog import load_pack, describe_workflow
from engine import Engine, pin_for, digest_file
from pack_checks import run_pack_checks

EXECUTIONS = []
CHECK_REPORTS = []
KEEP_RUNS = False


def bam_records(path):
    """Read BAM records independently of the GATK/HTSJDK implementation."""
    with gzip.open(path, 'rb') as stream:
        data = stream.read()
    if data[:4] != b'BAM\1':
        raise ValueError('Expected BAM magic')
    header_length, = struct.unpack_from('<i', data, 4)
    # Picard command-line header annotations can contain path bytes outside
    # ASCII. They are not part of these record/quality assertions.
    header = data[8:8 + header_length].decode('utf-8', errors='replace')
    offset = 8 + header_length
    references, = struct.unpack_from('<i', data, offset)
    offset += 4
    for _ in range(references):
        size, = struct.unpack_from('<i', data, offset)
        offset += 4 + size + 4
    records = []
    while offset < len(data):
        size, = struct.unpack_from('<i', data, offset)
        offset += 4
        body = data[offset:offset + size]
        if len(body) != size:
            raise ValueError('Truncated BAM record')
        ref, pos, bin_mapq_name, flag_cigar, sequence_length, mate_ref, mate_pos, span = struct.unpack_from('<iiIIiiii', body)
        name_length, cigar_count = bin_mapq_name & 255, flag_cigar & 65535
        name = body[32:32 + name_length - 1].decode('ascii')
        sequence_start = 32 + name_length + 4 * cigar_count
        quality_start = sequence_start + (sequence_length + 1) // 2
        encoded = body[sequence_start:quality_start]
        sequence = ''.join('=ACMGRSVTWYHKDBN'[nibble] for byte in encoded for nibble in (byte >> 4, byte & 15))[:sequence_length]
        records.append(dict(name=name, flag=flag_cigar >> 16, reference=ref, position=pos + 1,
                            cigar=body[32 + name_length:sequence_start].hex(), sequence=sequence,
                            quality=list(body[quality_start:quality_start + sequence_length]),
                            mateReference=mate_ref, matePosition=mate_pos + 1, templateLength=span))
        offset += size
    return header, records


def vcf_records(path):
    with path.open('rb') as stream:
        compressed = stream.read(2) == b'\x1f\x8b'
    with (gzip.open(path, 'rt') if compressed else path.open()) as stream:
        lines = stream.read().splitlines()
    samples = next(line.split('\t')[9:] for line in lines if line.startswith('#CHROM'))
    rows = []
    for line in lines:
        if not line or line.startswith('#'):
            continue
        fields = line.split('\t')
        formats = fields[8].split(':') if len(fields) > 8 else []
        info = dict((item.split('=', 1) + [True])[:2] for item in fields[7].split(';') if item != '.')
        rows.append(dict(chrom=fields[0], pos=int(fields[1]), ref=fields[3], alt=fields[4],
                         filter=fields[6], info=info,
                         samples={sample: dict(zip(formats, value.split(':'))) for sample, value in zip(samples, fields[9:])}))
    return samples, rows


class LinuxReferenceBackend:
    """Use original manifest argv, pinned Linux Java and the pinned APE helper."""
    def __init__(self):
        self.calls = []
        self.steps = []
        self.environment = {key: value for key, value in os.environ.items()
                            if key.upper() not in {'JAVA_TOOL_OPTIONS', '_JAVA_OPTIONS', 'JDK_JAVA_OPTIONS', 'CLASSPATH'}}
        self.environment['LD_LIBRARY_PATH'] = os.pathsep.join(str(JAVA_HOME / sub) for sub in ('lib', 'lib/server'))

    def inspect_alignment(self, executable, path, cancel):
        if cancel.is_set():
            raise InterruptedError('Cancelled before alignment inspection')
        if not LOADER.is_file() or digest_file(LOADER) != LOADER_SHA:
            raise RuntimeError('Recover the pinned APE loader for the actual SAMtools preflight')
        return subprocess.check_output([str(LOADER), str(executable), 'view', '-H', str(path)],
                                       env=self.environment, text=True, timeout=45)

    def run(self, request, event, cancel):
        self.calls.append(request)
        pack_root = Path(request['pack_folder'])
        if digest_file(pack_root / 'pack.ini') != request['pack_sha256']:
            raise ValueError('Pack manifest changed before execution')
        pack = load_pack(pack_root / 'pack.ini')
        workflow = pack['workflows'][request['workflow_id']]
        folder = Path(request['output_folder']) / 'Linux reference output é'
        folder.mkdir()
        outputs = {item['id']: folder / item['path'] for item in workflow['outputs']}
        assets = {identity: pack_root / item['path'] for identity, item in pack['assets'].items()}
        def expand(argument):
            argument = argument.replace('{run}', str(folder))
            for kind, values in [('input', request['values']), ('output', outputs), ('asset', assets)]:
                for identity, value in values.items():
                    argument = argument.replace('{' + kind + ':' + identity + '}', str(value))
            if '{' in argument:
                raise ValueError('Unexpanded manifest argument: ' + argument)
            return argument
        try:
            for step in workflow['steps']:
                if cancel.is_set():
                    return {'success': False, 'cancelled': True, 'folder': str(folder)}
                if step['kind'] == 'copy':
                    shutil.copyfile(expand(step['source']), outputs[step['destination']])
                    continue
                if step['kind'] != 'exec':
                    raise ValueError('Unexpected GATK step kind: ' + step['kind'])
                declared = pack['tools'][step['tool']]
                executable = pack_root / declared['path']
                if digest_file(executable) != declared['sha256']:
                    raise ValueError('Declared executable checksum differs')
                if step['tool'] == 'java':
                    prefix = [str(JAVA_HOME / 'bin/java')]
                elif step['tool'] == 'samtools':
                    prefix = [str(LOADER), str(executable)]
                else:
                    raise ValueError('Unexpected reference executable: ' + step['tool'])
                arguments = []
                for argument in step['args']:
                    match = re.fullmatch(r'\{inputs:([^}]+)\}', argument)
                    arguments.extend(request['values'][match[1]].splitlines() if match else [expand(argument)])
                argv = prefix + arguments
                record = dict(workflow=request['workflow_id'], step=step['id'], argv=argv, folder=str(folder))
                self.steps.append(record)
                completed = subprocess.run(argv, cwd=folder, env=self.environment, capture_output=True, timeout=240)
                record['exitCode'] = completed.returncode
                EXECUTIONS.append(record)
                (folder / (step['id'] + '.stderr')).write_bytes(completed.stderr)
                (folder / (step['id'] + '.stdout')).write_bytes(completed.stdout)
                if step.get('stdout'):
                    outputs[step['stdout']].write_bytes(completed.stdout)
                if completed.returncode:
                    raise RuntimeError(step['id'] + ': ' + completed.stderr.decode(errors='replace'))
            return dict(success=True, folder=str(folder), message='Original pack argv completed using pinned Linux Java')
        except Exception as error:
            return dict(success=False, folder=str(folder), message=str(error))


def catalog():
    pack = load_pack(PACK / 'pack.ini')
    relative = str(PACK.relative_to(ROOT))
    tools = {pack['id'] + '/' + identity: describe_workflow(pack, workflow, relative, pack['manifestSha256'])
             for identity, workflow in pack['workflows'].items()}
    return {'schema': 1, 'tools': tools, 'packs': [dict(id=pack['id'], version=pack['version'], folder=relative,
                                                    manifestSha256=pack['manifestSha256'])], 'types': {}}


class GatkScience(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not (PACK / 'pack.ini').is_file() or not (JAVA_HOME / 'bin/java').is_file():
            raise unittest.SkipTest('Prepare the GATK pack and recover its pinned matching Linux Java first')
        for relative, expected in JAVA_PINS.items():
            if digest_file(JAVA_HOME / relative) != expected:
                raise RuntimeError('Pinned Linux runtime differs: ' + relative)
        if not LOADER.is_file():
            raise unittest.SkipTest('Recover the pinned APE loader for the actual SAMtools preflight')
        cls.catalog = catalog()
        cls.pack = load_pack(PACK / 'pack.ini')
        for item in [*cls.pack['tools'].values(), *cls.pack['assets'].values()]:
            if digest_file(PACK / item['path']) != item['sha256']:
                raise RuntimeError('Pack file hash differs: ' + item['path'])
        cls.truth = json.loads((PACK / 'fixtures/truth.json').read_text())
        cls.checks = json.loads((PACK / 'workbench-checks.json').read_text())['checks']
        cls.fixture_hashes = {path: digest_file(path) for path in (PACK / 'fixtures').iterdir() if path.is_file()}

    @classmethod
    def tearDownClass(cls):
        for path, expected in cls.fixture_hashes.items():
            if digest_file(path) != expected:
                raise AssertionError('Analysis changed an input fixture: ' + str(path))

    def setUp(self):
        base = ROOT / 'build/gatk-evidence/runs'
        base.mkdir(parents=True, exist_ok=True)
        self.folder = Path(tempfile.mkdtemp(prefix=self._testMethodName + ' é ', dir=base))
        self.backend = LinuxReferenceBackend()
        self.engine = Engine(ROOT, self.catalog, self.backend)

    def tearDown(self):
        if not KEEP_RUNS:
            shutil.rmtree(self.folder)

    def graph(self, workflow, replacements=None, params=None):
        case = next(case for case in self.checks if case['workflow'] == workflow)
        tool = self.catalog['tools']['gatk/' + workflow]
        sources, inputs = [], {}
        ports = {item['id']: item for item in tool['ports']}
        for port_id, members in case['inputs'].items():
            inputs[port_id] = []
            for member in members:
                source_id = 'input-' + str(len(sources) + 1)
                files = {key: str(PACK / self.pack['assets'][asset]['path']) for key, asset in member.items()}
                sources.append(dict(id=source_id, type=ports[port_id]['type'], label=port_id, files=files))
                inputs[port_id].append(source_id)
        graph = dict(schema=1, name='GATK scientific fixture', sources=sources,
                     nodes=[dict(id='step-1', tool=tool['id'], pin=pin_for(tool),
                                 params=dict(case['params'], **(params or {})), inputs=inputs)],
                     nextNode=2, nextSource=len(sources) + 1)
        for key, value in (replacements or {}).items():
            for source in graph['sources']:
                if key in source['files']:
                    source['files'][key] = str(value)
        return graph

    def execute(self, graph, success=True):
        try:
            result = self.engine.execute(self.engine.prepare(graph, self.folder))
        except ValueError as error:
            if success:
                raise
            return dict(success=False, message=str(error), outputs={})
        self.assertEqual(result['success'], success, result)
        return result

    def output(self, result, identity, step='step-1'):
        return Path(next(iter(result['outputs'][step + '::' + identity]['files'].values())))

    def test_actual_manifest_native_check_specification(self):
        report = run_pack_checks(ROOT, self.catalog, self.folder, backend=self.backend)
        CHECK_REPORTS.append(report)
        self.assertEqual(report['failed'], 0, report)
        self.assertEqual(report['passed'], 9, report)

    def test_mark_duplicates_flags_exact_fragments_without_losing_reads(self):
        result = self.execute(self.graph('mark-duplicates'))
        _, before = bam_records(PACK / 'fixtures/duplicates.bam')
        _, after = bam_records(self.output(result, 'bam'))
        self.assertEqual(len(after), 10)
        self.assertEqual(sum(bool(row['flag'] & 1024) for row in after), 4)
        self.assertEqual({row['name'] for row in after if row['flag'] & 1024}, {'copy-a-one', 'copy-a-two'})
        normalize = lambda rows: sorted([{**row, 'flag': row['flag'] & ~1024} for row in rows], key=lambda row: (row['name'], row['flag']))
        self.assertEqual(normalize(after), normalize(before))
        self.assertGreater(self.output(result, 'bam-index').stat().st_size, 0)

    def test_bqsr_changes_qualities_without_changing_sequence_or_coordinates(self):
        result = self.execute(self.graph('bqsr'))
        _, before = bam_records(PACK / 'fixtures/recalibration.bam')
        _, after = bam_records(self.output(result, 'bam'))
        self.assertEqual(len(after), 400)
        self.assertEqual(sum(len(row['quality']) for row in after), 60000)
        self.assertEqual({q for row in before for q in row['quality']}, {40})
        self.assertTrue(any(a['quality'] != b['quality'] for a, b in zip(before, after)))
        self.assertTrue(all(0 <= q <= 93 for row in after for q in row['quality']))
        without_quality = lambda rows: [{key: value for key, value in row.items() if key != 'quality'} for row in rows]
        self.assertEqual(without_quality(before), without_quality(after))
        table = self.output(result, 'recalibration').read_text()
        self.assertRegex(table, r'synthetic-unit\s+M\s+38\.0000\s+40\.0000\s+59970\s+40\.00')

    def test_haplotypecaller_reference_blocks_cover_full_interval(self):
        result = self.execute(self.graph('haplotypecaller-gvcf'))
        samples, rows = vcf_records(self.output(result, 'gvcf'))
        self.assertEqual(samples, ['SAMPLE_A'])
        self.assertEqual(rows[0]['pos'], 1)
        expected_start = 1
        for row in rows:
            self.assertEqual(row['pos'], expected_start, 'gVCF has a gap or overlapping block')
            expected_start = int(row['info'].get('END', row['pos'])) + 1
        self.assertEqual(expected_start, 5001)
        variant = next(row for row in rows if row['pos'] == 1000)
        self.assertEqual((variant['ref'], variant['alt'], variant['samples']['SAMPLE_A']['GT']), ('A', 'C,<NON_REF>', '0/1'))
        self.assertTrue(any(row['alt'] == '<NON_REF>' and row['samples']['SAMPLE_A']['GT'] == '0/0' for row in rows))

    def test_uncovered_intervals_produce_valid_empty_callset(self):
        result = self.execute(self.graph('haplotypecaller-vcf', {'targets': PACK / 'fixtures/empty-targets.bed'}))
        samples, rows = vcf_records(self.output(result, 'variants'))
        self.assertEqual(samples, ['SAMPLE_A'])
        self.assertEqual(rows, [])

    def test_combine_then_joint_genotype_preserves_both_sample_genotypes(self):
        graph = self.graph('combine-gvcfs')
        genotype = self.catalog['tools']['gatk/genotype-gvcfs']
        reference_source = graph['nodes'][0]['inputs']['reference']
        graph['nodes'].append(dict(id='step-2', tool=genotype['id'], pin=pin_for(genotype),
                                   params={'memory': 1024}, inputs={'reference': reference_source, 'gvcf': ['step-1::gvcf']}))
        graph['nextNode'] = 3
        result = self.execute(graph)
        samples, rows = vcf_records(self.output(result, 'variants', 'step-2'))
        self.assertEqual(samples, self.truth['samples'])
        self.assertEqual(len(rows), 2)
        for row, truth in zip(rows, self.truth['variants']):
            self.assertEqual((row['chrom'], row['pos'], row['ref'], row['alt']),
                             (truth['chrom'], truth['pos'], truth['ref'], truth['alt']))
            self.assertEqual({sample: values['GT'] for sample, values in row['samples'].items()}, truth['genotypes'])
        self.assertEqual(rows[0]['info']['AC'], '3')
        self.assertEqual(rows[1]['info']['AC'], '1')
        self.assertTrue(all(row['info']['AN'] == '4' for row in rows))

    def test_select_indels_and_filter_threshold_are_biological_operations(self):
        selected = self.execute(self.graph('select-variants', params={'variant-type': 'INDEL'}))
        _, rows = vcf_records(self.output(selected, 'variants'))
        sequence = ''.join((PACK / 'fixtures/reference.fa').read_text().splitlines()[1:])
        self.assertEqual([(row['pos'], row['ref'], row['alt']) for row in rows], [(3000, sequence[2999], sequence[2999] + 'AC')])
        filtered = self.execute(self.graph('variant-filtration', params={'filter-threshold': '55'}))
        _, rows = vcf_records(self.output(filtered, 'variants'))
        self.assertEqual([(row['pos'], row['filter']) for row in rows], [(1000, 'PASS'), (2000, 'LowQual'), (3000, 'LowQual')])
        self.assertTrue(all(row['samples']['SAMPLE_A']['GT'] == '0/1' for row in rows))

    def test_wrong_bam_sample_reference_and_interval_fail(self):
        graph = self.graph('haplotypecaller-vcf', params={'sample': 'WRONG'})
        result = self.execute(graph, success=False)
        self.assertRegex(str(result), r'(?i)sample|SM')
        wrong = self.folder / 'wrong reference.fa'
        text = (PACK / 'fixtures/reference.fa').read_text()
        lines = text.splitlines(); lines[1] = ('C' if lines[1][0] == 'A' else 'A') + lines[1][1:]
        wrong.write_text('\n'.join(lines) + '\n')
        result = self.execute(self.graph('haplotypecaller-vcf', {'reference': wrong}), success=False)
        self.assertRegex(str(result), r'(?i)MD5|reference|sequence')
        interval = self.folder / 'outside.bed'; interval.write_text('chr1\t0\t5001\n')
        self.execute(self.graph('haplotypecaller-vcf', {'targets': interval}), success=False)

    def test_missing_or_unknown_record_read_groups_fail_before_calling(self):
        # Preserve the valid BAM @RG/SM header but deliberately invalidate the
        # per-record RG tags. GATK otherwise silently discards these alignments.
        sys.path.insert(0, str(ROOT / 'scripts'))
        from generate_gatk_fixtures import _bgzf
        with gzip.open(PACK / 'fixtures/sample-a.bam', 'rb') as stream:
            original = stream.read()
        header_length, = struct.unpack_from('<i', original, 4)
        offset = 8 + header_length
        count, = struct.unpack_from('<i', original, offset); offset += 4
        for _ in range(count):
            size, = struct.unpack_from('<i', original, offset); offset += size + 8
        prefix, record_start = original[:offset], offset
        for label, replacement in [('missing', b''), ('unknown', b'RGZundeclared-rg\0')]:
            changed = bytearray(prefix)
            offset = record_start
            while offset < len(original):
                size, = struct.unpack_from('<i', original, offset)
                body = original[offset + 4:offset + 4 + size]
                tag = b'RGZsample_a-rg\0'
                self.assertTrue(body.endswith(tag), 'Malformed control-fixture RG placement')
                body = body[:-len(tag)] + replacement
                changed += struct.pack('<i', len(body)) + body
                offset += size + 4
            bam = self.folder / (label + ' record read groups.bam')
            bam.write_bytes(_bgzf(bytes(changed)))
            result = self.execute(self.graph('haplotypecaller-vcf', {'bam': bam}), success=False)
            self.assertRegex(str(result), r'(?i)read.?group|RG')
            self.assertNotIn('step-1::variants', result['outputs'])

    def test_duplicate_gvcf_samples_and_ordinary_vcf_are_rejected(self):
        graph = self.graph('combine-gvcfs')
        members = [source for source in graph['sources'] if 'gvcfs' in source['files']]
        second = self.folder / 'repeated sample.g.vcf'
        second.write_bytes((PACK / 'fixtures/sample-a.g.vcf').read_bytes())
        members[1]['files']['gvcfs'] = str(second)
        result = self.execute(graph, success=False)
        self.assertRegex(str(result), r'(?i)duplicate|sample|distinct|overlap')
        result = self.execute(self.graph('genotype-gvcfs', {'gvcf': PACK / 'fixtures/variants.vcf'}), success=False)
        self.assertRegex(str(result), r'(?i)gvcf|NON_REF|reference.confidence')

    def test_wrong_vcf_reference_allele_fails_validation(self):
        bad = self.folder / 'wrong REF.vcf'
        lines = (PACK / 'fixtures/variants.vcf').read_text().splitlines()
        for index, line in enumerate(lines):
            if line.startswith('chr1\t1000\t'):
                fields = line.split('\t'); fields[3] = 'G'; lines[index] = '\t'.join(fields)
        bad.write_text('\n'.join(lines) + '\n')
        result = self.execute(self.graph('validate-variants', {'variants': bad}), success=False)
        self.assertRegex(str(result), r'(?i)reference|REF|allele')
        self.assertNotIn('step-1::validation', result['outputs'])

    def test_gzip_vcf_and_multiple_known_sites_are_staged_without_modification(self):
        compressed = self.folder / 'variants with spaces.vcf.gz'
        compressed.write_bytes(gzip.compress((PACK / 'fixtures/variants.vcf').read_bytes(), mtime=0))
        before = digest_file(compressed)
        result = self.execute(self.graph('select-variants', {'variants': compressed}))
        _, rows = vcf_records(self.output(result, 'variants'))
        self.assertEqual([row['pos'] for row in rows], [1000, 2000])
        self.assertEqual(digest_file(compressed), before)
        # The two resources together have precisely the same known-site union.
        first = self.folder / 'known one.vcf.gz'
        second = self.folder / 'known two.vcf'
        lines = (PACK / 'fixtures/known-sites.vcf').read_text().splitlines()
        headers = [line for line in lines if line.startswith('#')]
        records = [line for line in lines if not line.startswith('#')]
        first.write_bytes(gzip.compress(('\n'.join(headers + records[:1]) + '\n').encode(), mtime=0))
        second.write_text('\n'.join(headers + records[1:]) + '\n')
        graph = self.graph('bqsr', {'known-sites': first})
        source_id = 'input-' + str(graph['nextSource'])
        graph['sources'].append(dict(id=source_id, type='vcf', label='Second known-site resource', files={'known-sites': str(second)}))
        graph['nodes'][0]['inputs']['known-sites'].append(source_id)
        graph['nextSource'] += 1
        result = self.execute(graph)
        _, recalibrated = bam_records(self.output(result, 'bam'))
        self.assertEqual(dict(collections.Counter(q for row in recalibrated for q in row['quality'])), {35: 400, 36: 59600})

    def test_filter_expression_cannot_be_injected_and_missing_annotation_is_labelled(self):
        for value in ('30 || true', 'NaN', 'Infinity'):
            self.execute(self.graph('variant-filtration', params={'filter-threshold': value}), success=False)
        result = self.execute(self.graph('variant-filtration', params={'filter-annotation': 'QD', 'filter-name': 'MissingQD'}))
        _, rows = vcf_records(self.output(result, 'variants'))
        self.assertEqual([row['filter'] for row in rows], ['MissingQD'] * 3)

    def test_empty_gvcf_derived_variant_subset_remains_valid_ordinary_vcf(self):
        graph = self.graph('genotype-gvcfs')
        reference_source = graph['nodes'][0]['inputs']['reference']
        for identity, workflow, upstream, params in [
            ('step-2', 'select-variants', 'step-1', {'variant-type': 'INDEL'}),
            ('step-3', 'validate-variants', 'step-2', {}),
        ]:
            tool = self.catalog['tools']['gatk/' + workflow]
            graph['nodes'].append(dict(id=identity, tool=tool['id'], pin=pin_for(tool), params=dict(memory=1024, **params),
                                       inputs={'reference': reference_source, 'variants': [upstream + '::variants']}))
        graph['nextNode'] = 4
        result = self.execute(graph)
        samples, rows = vcf_records(self.output(result, 'variants', 'step-2'))
        self.assertEqual(samples, ['SAMPLE_A'])
        self.assertEqual(rows, [])
        self.assertTrue(json.loads(self.output(result, 'validation', 'step-3').read_text())['valid'])


def main():
    global KEEP_RUNS
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report', type=Path)
    args, rest = parser.parse_known_args()
    KEEP_RUNS = args.report is not None
    started = time.time()
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(GatkScience)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        report = dict(schema=1, platform=sys.platform, nativeWindowsExecuted=False,
                      executionBoundary='Original manifest arguments with pinned matching Linux Java and APE SAMtools; native Windows import/bridge tests are separate.',
                      pack=str(PACK), manifestSha256=digest_file(PACK / 'pack.ini') if (PACK / 'pack.ini').exists() else None,
                      javaHome=str(JAVA_HOME), javaPins=JAVA_PINS,
                      elapsedSeconds=round(time.time() - started, 3), tests=result.testsRun,
                      failures=[{'test': str(test), 'detail': detail} for test, detail in result.failures],
                      errors=[{'test': str(test), 'detail': detail} for test, detail in result.errors],
                      skipped=[{'test': str(test), 'reason': reason} for test, reason in result.skipped],
                      success=result.wasSuccessful() and not result.skipped,
                      nativeCheckSpecifications=CHECK_REPORTS, executions=EXECUTIONS)
        args.report.write_text(json.dumps(report, indent=2) + '\n')
    return 0 if result.wasSuccessful() and not result.skipped else 1


if __name__ == '__main__':
    raise SystemExit(main())
