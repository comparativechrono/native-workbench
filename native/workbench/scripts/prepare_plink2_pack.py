#!/usr/bin/env python3
"""Prepare PLINK2 1.0.0 from exact native outputs and complete matching sources."""
import argparse
import json
from pathlib import Path
import shutil
import sys
import tarfile

from build_plink2_native import ROOT, VERSION as TOOL_VERSION, SOURCE_COMMIT, SOURCE_NAME, SOURCES, sha
sys.path.insert(0, str(ROOT / 'desktop'))
from prepare_modular_packs import artifact, execute, field, workflow
VERSION = '1.0.0'
CITATION = {'text': 'Chang CC et al. (2015). Second-generation PLINK: rising to the challenge of larger and richer datasets. GigaScience 4:7.', 'url': 'https://doi.org/10.1186/s13742-015-0047-8'}


def definitions():
    inputs = [field('variants', 'Diploid genotype VCF', filter='Uncompressed VCF|*.vcf|All files|*.*', help='Plain VCF 4.2/4.3 with GT-only diploid hardcalls; human autosomes 1–22 and biallelic A/C/G/T SNPs. 2–1000 samples, 1–100000 variants, at most 10000000 genotypes and 64 MiB. Phased or unphased calls accepted; phase is not used. Full missing calls must be ./. or .|.; half-calls, dosage/likelihood FORMAT fields, indels and sex chromosomes are rejected. Unique nonmissing sample/variant IDs: 1–128 letters, digits, underscore, dot or hyphen; sample ID 0 is unsupported. Every sample and variant is counted regardless of FILTER. Select variants and sample relationships appropriately before interpreting results. One CPU; 640 MiB PLINK workspace allocation, not total memory or time prediction. ASCII paths required; spaces supported.')]
    outputs = [artifact('frequencies', 'ALT allele frequency table', 'plink.afreq'), artifact('genotypes', 'Genotype hardcall counts', 'plink.gcount'), artifact('sample-missingness', 'Sample missingness table', 'plink.smiss'), artifact('variant-missingness', 'Variant missingness table', 'plink.vmiss'), artifact('summary', 'Recorded genotype measurements', 'summary.json'), artifact('settings', 'Analysis settings', 'settings.json'), artifact('log', 'PLINK2 log', 'plink.log'), artifact('adapter-log', 'Execution diagnostics', 'adapter.log')]
    steps = [execute('version', 'Record bundled PLINK2 version', 'plink2', ['--version']), execute('summarize', 'Summarize diploid genotype hardcalls', 'plink2-adapter', ['{input:variants}', '{run}'], produces=[o['id'] for o in outputs])]
    workflows = [workflow('summarize-vcf', 'PLINK2: summarize genotype frequencies and missingness', 'Measure ALT frequencies, genotype counts and per-sample/per-variant missingness from a reviewed GT-only SNP dataset. No automatic QC filtering or pass thresholds.', inputs, outputs, steps)]
    schema = {'schema': 1, 'category': 'Population genetics', 'citations': [CITATION], 'workflows': {'summarize-vcf': {'ports': [{'id': 'variants', 'label': 'Diploid biallelic SNP genotypes', 'type': 'vcf', 'manifestInputs': ['variants'], 'min': 1, 'max': 1, 'requiredState': {'compression': 'none'}}], 'outputs': [{'id': o['id'], 'label': o['label'], 'type': 'text' if o['id'] in ('log', 'adapter-log') else 'metrics', 'manifestOutputs': [o['id']]} for o in outputs], 'pathPolicy': {'asciiOnly': True}, 'methods': 'PLINK 2.0 alpha 7.12 (2.0.0-a.7.12), compiled from unchanged upstream source for baseline x86-64 without LAPACK, summarized GT-only diploid biallelic SNP calls on human autosomes 1–22. All supplied samples were included (--nonfounders, --const-fid 0); no sample, variant, FILTER, genotype quality, missingness or allele-frequency filtering was requested. ALT frequency is the observed ALT allele count divided by all called allele observations; it is not necessarily minor allele frequency. All-missing variants have undefined frequencies. Genotype and missingness counts include every retained sample/variant. Phase is not used. One PLINK compute thread and a 640 MiB required workspace allocation were requested; the allocation is not a whole-process memory cap. Recorded measurements do not establish QC acceptance, ancestry, association or clinical findings. Dataset selection, relatedness and any LD treatment remain scientific decisions; PCA and association are not provided by this pack.'}}}
    return workflows, schema


def checks():
    return {'schema': 1, 'checks': [{'id': 'known-diploid-hardcalls', 'workflow': 'summarize-vcf', 'inputs': {'variants': [{'variants': 'fixture-genotypes'}]}, 'params': {}, 'expect': [{'output': 'summary', 'kind': 'text', 'contains': ['"samples": 4', '"variants": 6', '"calledGenotypes": 17', '"missingGenotypes": 7', '"observedAlleles": 34', '"alternateAlleles": 18']}, {'output': 'frequencies', 'kind': 'text', 'contains': ['ALT_FREQS', 'reference_only\tA\tG\t0\t8', 'alternate_only\tC\tT\t1\t8', 'all_missing\tT\tC\t']}, {'output': 'genotypes', 'kind': 'text', 'contains': ['HOM_REF_CT', 'HET_REF_ALT_CTS', 'HOM_ALT1_CT', 'MISSING_CT']}, {'output': 'sample-missingness', 'kind': 'text', 'contains': ['under_score\t2\t6\t0.333333']}, {'output': 'settings', 'kind': 'text', 'contains': ['"allSamplesIncluded": true', '"filtersApplied": false', '"phaseUsed": false']}]}]}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--cache', type=Path, default=ROOT / 'build/plink2-cache')
    p.add_argument('--build', type=Path, default=ROOT / 'build/plink2-windows')
    p.add_argument('--destination', type=Path, default=ROOT / 'packs/plink2-1.0.0')
    a = p.parse_args()
    cache, build, destination = a.cache.resolve(), a.build.resolve(), a.destination.resolve()
    record = json.loads((build / 'build.json').read_text())
    for key, expected in {'platform': 'windows-x86_64', 'version': TOOL_VERSION, 'upstreamCommit': SOURCE_COMMIT, 'builderSha256': sha(ROOT / 'scripts/build_plink2_native.py'), 'guardSourceSha256': sha(ROOT / 'tools/plink2/guard.cpp'), 'upstreamSourceUnmodified': True, 'lapack': False, 'sources': SOURCES}.items():
        if record.get(key) != expected:
            raise ValueError('Build/source correspondence failed: ' + key)
    for name, source in SOURCES.items():
        if sha(cache / name) != source['sha256']:
            raise ValueError('Changed source archive: ' + name)
    if destination.exists() and any(destination.iterdir()):
        raise ValueError('Destination must be new/empty')
    for name in ('bin', 'fixtures', 'licenses'):
        (destination / name).mkdir(parents=True, exist_ok=True)
    sections = []
    def section(name, values):
        sections.append('[' + name + ']\n' + '\n'.join(key + '=' + str(value) for key, value in values.items() if key != 'id' or name == 'pack') + '\n')
    section('pack', dict(format=2, id='plink2', version=VERSION, name='PLINK2 genotype summaries', platform='windows-x86_64', description='Recorded ALT frequencies, genotype counts and missingness for a reviewed diploid SNP dataset.', color='#637E71'))
    for name in ('plink2', 'plink2-guard'):
        path = build / (name + '.exe')
        if sha(path) != record['files'][path.name]['sha256'] or path.read_bytes()[:2] != b'MZ':
            raise ValueError('Changed/non-Windows executable: ' + name)
        shutil.copyfile(path, destination / 'bin' / path.name)
        section('tool:' + ('plink2-adapter' if name.endswith('-guard') else name), dict(path='bin/' + path.name, version=VERSION if name.endswith('-guard') else TOOL_VERSION, sha256=sha(path)))
    workflows, schema = definitions()
    for name, value in [('workbench-schema.json', schema), ('workbench-checks.json', checks())]:
        (destination / name).write_text(json.dumps(value, indent=2) + '\n', encoding='utf-8')
    assets = {'workbench-schema': 'workbench-schema.json', 'workbench-checks': 'workbench-checks.json'}
    for path in sorted((ROOT / 'tools/plink2/fixtures').iterdir()):
        if not path.is_file():
            raise ValueError('Unexpected fixture directory')
        relative = 'fixtures/' + path.name
        shutil.copyfile(path, destination / relative)
        assets['fixture-' + path.stem] = relative
    for identity, relative in assets.items():
        section('asset:' + identity, dict(path=relative, sha256=sha(destination / relative)))
    for item in workflows:
        section('workflow:' + item['id'], dict(name=item['name'], description=item['description'], inputs=','.join(v['id'] for v in item['inputs']), outputs=','.join(v['id'] for v in item['outputs']), steps=','.join(v['id'] for v in item['steps'])))
        for kind in ('input', 'output', 'step'):
            for value in item[kind + 's']:
                section(kind + ':' + item['id'] + ':' + value['id'], value)
    (destination / 'pack.ini').write_text('\n'.join(sections), encoding='utf-8')
    licenses = destination / 'licenses'
    for path in [*[cache / name for name in SOURCES], ROOT / 'tools/plink2/guard.cpp', ROOT / 'tools/plink2/fixtures.py', ROOT / 'scripts/build_plink2_native.py', Path(__file__), ROOT / 'LICENSE']:
        shutil.copyfile(path, licenses / ('Workbench-LICENSE.txt' if path.name == 'LICENSE' else path.name))
    with tarfile.open(cache / SOURCE_NAME) as archive:
        for relative, name in [('COPYING', 'PLINK2-GPLv3.txt'), ('COPYING.LESSER', 'PLINK2-LGPLv3.txt'), ('include/LICENSE.QD', 'QD-LICENSE.txt'), ('include/SFMT.c', 'SFMT-source-notices.c'), ('simde/COPYING', 'SIMDe-MIT.txt'), ('libdeflate/COPYING', 'libdeflate-MIT.txt'), ('zstd/COPYING', 'zstd-GPLv2.txt'), ('zstd/LICENSE', 'zstd-BSD.txt')]:
            (licenses / name).write_bytes(archive.extractfile('plink-ng-' + SOURCE_COMMIT + '/2.0/' + relative).read())
    with tarfile.open(cache / 'zlib-1.3.2.tar.gz') as archive:
        (licenses / 'zlib-LICENSE.txt').write_bytes(archive.extractfile('zlib-1.3.2/LICENSE').read())
    shutil.copyfile(build / 'build.json', licenses / 'build-provenance.json')
    for name, digest in record['compilerNotices'].items():
        if sha(build / 'compiler-notices' / name) != digest:
            raise ValueError('Changed compiler/runtime notice')
        shutil.copyfile(build / 'compiler-notices' / name, licenses / ('compiler-' + name))
    (licenses / 'NOTICE.txt').write_text('PLINK2 2.0.0-a.7.12, Copyright (C) 2005-2026 Shaun Purcell and Christopher Chang.\nThis is a Native Workbench source build, not an official upstream binary.\nThe unchanged upstream source is GPLv3+; include/ is LGPLv3+.\nBundled SIMDe and libdeflate use MIT notices; zstd is BSD/GPLv2 dual-licensed.\nQD-derived high-precision code, SFMT random-number code and all embedded notices are retained in the complete original source archive.\nPrivate static zlib 1.3.2 source and notices and LLVM/MinGW runtime notices are included.\nNo upstream source patches. Build forces the standard math.h declaration needed by the NOLAPACK route and disables advanced CPU requirements.\nThe separate MIT-licensed Workbench adapter validates a bounded VCF contract, invokes PLINK2 shell-free and verifies retained genotype counts.\nNo LAPACK, OpenBLAS, PCA or association workflow is included.\n', encoding='utf-8')
    shutil.copyfile(ROOT / 'docs/PLINK2-PACK.md', destination / 'PACK-README.md')
    sys.path.insert(0, str(ROOT / 'workspace'))
    from catalog import load_pack
    pack = load_pack(destination / 'pack.ini')
    print(json.dumps({'pack': str(destination), 'manifestSha256': sha(destination / 'pack.ini'), 'workflows': list(pack['workflows']), 'checks': len(checks()['checks'])}, indent=2))


if __name__ == '__main__':
    main()
