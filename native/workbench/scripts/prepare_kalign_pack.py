#!/usr/bin/env python3
"""Prepare Kalign 1.0.0 from exact native build outputs and retained source."""
import argparse
import json
from pathlib import Path
import shutil
import sys
import tarfile

from build_kalign_native import (
    ROOT, VERSION as TOOL_VERSION, SOURCE_COMMIT, SOURCE_NAME, SOURCE_SHA256, sha,
)

sys.path.insert(0, str(ROOT / 'desktop'))
from prepare_modular_packs import artifact, execute, field, workflow

VERSION = '1.0.0'
CITATION = {
    'text': 'Lassmann T (2020). Kalign 3: multiple sequence alignment of large data sets. Bioinformatics 36:1928-1929.',
    'url': 'https://doi.org/10.1093/bioinformatics/btz795',
}


def definitions():
    workflows = []
    schema = {'schema': 1, 'category': 'Multiple sequence alignment',
              'citations': [CITATION], 'workflows': {}}
    for datatype in ('nucleotide', 'protein'):
        nucleotide = datatype == 'nucleotide'
        identity = 'align-' + datatype
        model = ('DNA scoring; U scores as T and IUPAC ambiguities as N, while original letters are retained.'
                 if nucleotide else
                 'PFASUM43 protein scoring with the upstream variable-scoring-matrix default. B/X/Z are retained; stops, J, U and O are unsupported.')
        help_text = (
            'Select homologous sequences in a common orientation, not reads or whole genomes. No reverse-complement or codon-frame handling. Uncompressed, ungapped FASTA: '
            '2–10000 sequences; 1–15000 residues each; at most 10000000 residues and 64 MiB. '
            'Unique first-word IDs use 1–128 letters, digits, underscore, dot or hyphen. '
            'ASCII headers up to 1024 characters are restored in input order; letters become uppercase. '
            + model + ' Default single alignment, one CPU thread. Bounds are not time or memory forecasts. '
            'ASCII installation, input and output paths; spaces supported.')
        inputs = [field('sequences', 'Unaligned ' + datatype + ' FASTA',
                        filter='Uncompressed FASTA|*.fa;*.fasta;*.fna;*.faa|All files|*.*', help=help_text)]
        outputs = [
            artifact('aligned', 'Aligned ' + datatype + ' FASTA', 'alignment.afa'),
            artifact('summary', 'Recorded alignment measurements', 'alignment-summary.json'),
            artifact('settings', 'Analysis settings and sequence mapping', 'analysis-settings.json'),
            artifact('log', 'Kalign execution log', 'kalign.log'),
        ]
        steps = [execute('version', 'Record bundled Kalign version', 'kalign', ['--version']),
                 execute('align', 'Align homologous ' + datatype + ' sequences', 'kalign-adapter',
                         ['{input:sequences}', '{run}', datatype], produces=[item['id'] for item in outputs])]
        workflows.append(workflow(identity, 'Kalign: align ' + datatype + ' sequences',
            'Align homologous ' + datatype + ' sequences with Kalign 3.5.1-workbench1. '
            'Explicit ' + ('DNA' if nucleotide else 'protein') + ' scoring; upstream default single alignment; one CPU thread.',
            inputs, outputs, steps))
        schema['workflows'][identity] = {
            'ports': [{'id': 'sequences', 'label': 'Unaligned ' + datatype + ' sequences',
                       'type': 'fasta-' + datatype, 'manifestInputs': ['sequences'], 'min': 1, 'max': 1,
                       'requiredState': {'compression': 'none'},
                       'validation': {'minRecords': 2, 'maxLength': 15000, 'uniqueIds': True}}],
            'outputs': [{'id': item['id'], 'label': item['label'],
                         'type': 'msa-' + datatype if item['id'] == 'aligned' else 'text' if item['id'] == 'log' else 'metrics',
                         'manifestOutputs': [item['id']],
                         **({'state': {'compression': 'none'}} if item['id'] == 'aligned' else {})}
                        for item in outputs],
            'pathPolicy': {'asciiOnly': True},
            'methods': (
                'Homologous ' + datatype + ' sequences were aligned with Kalign 3.5.1-workbench1, '
                'serial baseline x86-64, using an explicit ' + ('DNA' if nucleotide else 'protein') + ' alphabet. '
                + model + ' Upstream default mode uses five consistency anchors with weight 2.0; '
                'no ensemble, refinement, custom penalties or guide-tree noise was requested. '
                'For these default-mode operations, the CLI boundary makes explicit type selection override composition-based alphabet detection; '
                'the upstream alignment and scoring algorithms are unchanged. Native I/O validation maps '
                'safe private identifiers and restores full headers and input order, verifying every ungapped '
                'residue and equal output row lengths. Recorded alignment measurements have no QC pass '
                'thresholds. Alignment does not establish homology, orthology, gene trees or species trees.'),
        }
    return workflows, schema


def fasta_records(path):
    records = {}
    identity = None
    for line in path.read_text(encoding='ascii').splitlines():
        if line.startswith('>'):
            identity = line[1:].split()[0]
            records[identity] = ''
        elif line:
            records[identity] += line
    return records


def checks():
    truth = json.loads((ROOT / 'tools/kalign/fixtures/truth.json').read_text(encoding='utf-8'))
    result = []
    for datatype in ('nucleotide', 'protein'):
        case = truth['cases'][datatype]
        result.append({
            'id': datatype + '-known-indels', 'workflow': 'align-' + datatype,
            'inputs': {'sequences': [{'sequences': 'fixture-' + datatype}]}, 'params': {},
            'expect': [
                {'output': 'aligned', 'kind': 'fasta', 'records': case['sequences'], 'aligned': True,
                 'sequences': fasta_records(ROOT / 'tools/kalign/fixtures' / (datatype + '-truth.afa')),
                 'ungapped': fasta_records(ROOT / 'tools/kalign/fixtures' / (datatype + '.fa'))},
                {'output': 'summary', 'kind': 'text', 'contains': [
                    '"sequences": ' + str(case['sequences']), '"columns": ' + str(case['columns']),
                    '"inputResidues": ' + str(case['inputResidues']), '"gapCharacters": ' + str(case['gapCharacters']),
                    '"preservedUngappedResidues": true', '"preservedInputOrder": true']},
                {'output': 'settings', 'kind': 'text', 'contains': [
                    '"version": "3.5.1-workbench1"', '"upstreamType": "' + ('dna' if datatype == 'nucleotide' else 'protein') + '"',
                    '"threads": 1', '"mode": "default"']},
            ],
        })
    return {'schema': 1, 'checks': result}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cache', type=Path, default=ROOT / 'build/kalign-cache')
    parser.add_argument('--build', type=Path, default=ROOT / 'build/kalign-windows')
    parser.add_argument('--destination', type=Path, default=ROOT / 'packs/kalign-1.0.0')
    args = parser.parse_args()
    cache, build, destination = args.cache.resolve(), args.build.resolve(), args.destination.resolve()
    record = json.loads((build / 'build.json').read_text(encoding='utf-8'))
    expected = {
        'platform': 'windows-x86_64', 'version': TOOL_VERSION, 'upstreamCommit': SOURCE_COMMIT,
        'guardSourceSha256': sha(ROOT / 'tools/kalign/guard.cpp'),
        'builderSha256': sha(ROOT / 'scripts/build_kalign_native.py'),
        'windowsCompatibilityHeaderSha256': sha(ROOT / 'tools/kalign/upstream_windows_compat.h'),
        'patchSha256': sha(cache / 'workbench1.patch'),
    }
    for key, value in expected.items():
        if record.get(key) != value:
            raise ValueError('Build/source correspondence failed: ' + key)
    if sha(cache / SOURCE_NAME) != SOURCE_SHA256:
        raise ValueError('Changed pinned upstream archive')
    if destination.exists() and any(destination.iterdir()):
        raise ValueError('Destination must be new/empty')
    for name in ('bin', 'fixtures', 'licenses'):
        (destination / name).mkdir(parents=True, exist_ok=True)
    sections = []

    def section(name, values):
        sections.append('[' + name + ']\n' + '\n'.join(
            key + '=' + str(value) for key, value in values.items()
            if key != 'id' or name == 'pack') + '\n')

    section('pack', dict(format=2, id='kalign', version=VERSION, name='Kalign multiple sequence alignment',
        platform='windows-x86_64', description='Align homologous nucleotide or protein sequences with explicit alphabets and recorded alignment measurements.', color='#59788D'))
    for name in ('kalign', 'kalign-guard'):
        executable = build / (name + '.exe')
        if sha(executable) != record['files'][executable.name]['sha256'] or executable.read_bytes()[:2] != b'MZ':
            raise ValueError('Changed/non-Windows executable: ' + name)
        shutil.copyfile(executable, destination / 'bin' / executable.name)
        section('tool:' + ('kalign-adapter' if name == 'kalign-guard' else name),
                dict(path='bin/' + executable.name, version=VERSION if name == 'kalign-guard' else TOOL_VERSION, sha256=sha(executable)))
    workflows, schema = definitions()
    for name, value in [('workbench-schema.json', schema), ('workbench-checks.json', checks())]:
        (destination / name).write_text(json.dumps(value, indent=2) + '\n', encoding='utf-8')
    assets = {'workbench-schema': 'workbench-schema.json', 'workbench-checks': 'workbench-checks.json'}
    for source in sorted((ROOT / 'tools/kalign/fixtures').iterdir()):
        if not source.is_file():
            raise ValueError('Unexpected directory in fixture source')
        relative = 'fixtures/' + source.name
        shutil.copyfile(source, destination / relative)
        assets['fixture-' + source.stem] = relative
    for name, path in assets.items():
        section('asset:' + name, dict(path=path, sha256=sha(destination / path)))
    for item in workflows:
        section('workflow:' + item['id'], dict(name=item['name'], description=item['description'],
            inputs=','.join(value['id'] for value in item['inputs']), outputs=','.join(value['id'] for value in item['outputs']),
            steps=','.join(value['id'] for value in item['steps'])))
        for kind in ('input', 'output', 'step'):
            for value in item[kind + 's']:
                section(kind + ':' + item['id'] + ':' + value['id'], value)
    (destination / 'pack.ini').write_text('\n'.join(sections), encoding='utf-8')
    licenses = destination / 'licenses'
    for source in [cache / SOURCE_NAME, cache / 'workbench1.patch', ROOT / 'tools/kalign/upstream_windows_compat.h',
                   ROOT / 'tools/kalign/guard.cpp', ROOT / 'tools/kalign/fixtures.py', ROOT / 'tools/kalign/record_reference.py',
                   ROOT / 'scripts/build_kalign_native.py', Path(__file__), ROOT / 'LICENSE']:
        shutil.copyfile(source, licenses / ('Workbench-LICENSE.txt' if source.name == 'LICENSE' else source.name))
    # The SHA-pinned archive is the licensing authority, not a mutable extraction.
    with tarfile.open(cache / SOURCE_NAME) as source:
        for name, target in [('COPYING', 'Kalign-Apache-2.0.txt'),
                             ('lib/src/tlrng.c', 'Kalign-tlrng-source-notices.c'),
                             ('lib/src/esl_stopwatch.c', 'Kalign-stopwatch-source-notices.c')]:
            data = source.extractfile('kalign-' + SOURCE_COMMIT + '/' + name).read()
            (licenses / target).write_bytes(data)
    shutil.copyfile(build / 'build.json', licenses / 'build-provenance.json')
    (licenses / 'NOTICE.txt').write_text(
        'Kalign 3.5.1-workbench1: local Native Workbench build, not an official upstream binary.\n'
        'Kalign Copyright (C) 2006-2026 Timo Lassmann; Apache License 2.0 (Kalign-Apache-2.0.txt).\n\n'
        'Compiled lib/src/esl_stopwatch.c includes portable high-resolution timer code\n'
        '(C) 2012 David Robert Nadeau, http://NadeauSoftware.com/,\n'
        'Creative Commons Attribution 3.0 Unported: http://creativecommons.org/licenses/by/3.0/deed.en_US\n'
        'Thanks to Warren Gish for assistance. Retained without modification in Kalign-stopwatch-source-notices.c.\n\n'
        'Compiled lib/src/tlrng.c includes code by David Blackman and Sebastiano Vigna (2018),\n'
        'dedicated to the public domain to the extent possible: http://creativecommons.org/publicdomain/zero/1.0/.\n'
        'It includes distribution-sampling code Copyright 2005 Robert Kern and code bits from Sean Eddy\'s Easel library.\n'
        'Full copyright, permission and warranty texts are retained in Kalign-tlrng-source-notices.c.\n\n'
        'The complete upstream source archive retains every source notice; Workbench and compiler/runtime licences are separate.\n',
        encoding='utf-8')
    for name, digest in record['compilerNotices'].items():
        if sha(build / 'compiler-notices' / name) != digest:
            raise ValueError('Changed compiler/runtime notice: ' + name)
        shutil.copyfile(build / 'compiler-notices' / name, licenses / ('compiler-' + name))
    (licenses / 'MODIFICATIONS.txt').write_text(
        'Kalign 3.5.1-workbench1, Native Workbench, 2026-10-13.\n'
        'For the supported default-mode operations, explicit CLI sequence type overrides composition-based alphabet detection.\n'
        'Windows I/O compatibility uses getline/localtime_r boundary implementations and removes an ERROR macro conflict.\n'
        'The build identifies this local distribution with -workbench1. Scientific alignment/scoring routines are unchanged.\n'
        'The initial build is serial, baseline x86-64; no OpenMP or AVX2 runtime requirement.\n'
        'Complete upstream source, Apache-2.0 licence, embedded third-party notices, exact patch, compatibility header, adapters and recipes are retained.\n'
        'The source archive includes public-domain/MIT random-number material and David Nadeau CC-BY-3.0 timing attribution.\n', encoding='utf-8')
    shutil.copyfile(ROOT / 'docs/KALIGN-PACK.md', destination / 'PACK-README.md')
    sys.path.insert(0, str(ROOT / 'workspace'))
    from catalog import load_pack
    pack = load_pack(destination / 'pack.ini')
    print(json.dumps({'pack': str(destination), 'manifestSha256': sha(destination / 'pack.ini'),
                      'workflows': list(pack['workflows']), 'checks': len(checks()['checks'])}, indent=2))


if __name__ == '__main__':
    main()
