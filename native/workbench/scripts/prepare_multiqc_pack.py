#!/usr/bin/env python3
"""Build a pinned, offline MultiQC pack with a private Windows Python runtime."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sys
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'desktop'))
from prepare_modular_packs import field, artifact, execute, workflow

PACK_VERSION = '1.0.0'
VERSION = '1.35'
LOCK = ROOT / 'tools/multiqc/windows-lock.json'
CITATION = {'text': 'Ewels P, Magnusson M, Lundin S, Käller M (2016). MultiQC: summarize analysis results for multiple tools and samples in a single report. Bioinformatics 32:3047-3048.', 'url': 'https://doi.org/10.1093/bioinformatics/btw354'}


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def dump(path, value):
    path.write_text(json.dumps(value, indent=2, ensure_ascii=True) + '\n', encoding='utf-8')


def definitions():
    inputs = [field('reports', 'QC reports to compare', 'files', filter='QC metrics|*.zip;*.txt;*.json;*.out;*.log;*.summary|All files|*.*',
        help='Select 1 to 64 FastQC ZIP/data reports, fastp JSON reports, STAR Log.final.out summaries, featureCounts .summary files, or captured kallisto quantification logs. Identical reports are rejected. Each file stays separately labelled; matching biological samples across tools is not inferred.')]
    outputs = [artifact('html', 'Interactive MultiQC HTML report', 'multiqc_report.html'),
        artifact('data', 'Complete MultiQC data', 'multiqc_data/multiqc_data.json'),
        artifact('general-statistics', 'General statistics table', 'multiqc_data/multiqc_general_stats.txt'),
        artifact('sources', 'Report input identities and hashes', 'report-inputs.json')]
    steps = [execute('report', 'Aggregate local QC reports with MultiQC', 'python',
        ['-I', '-B', '-X', 'utf8', '{asset:adapter}', '--run', '{run}', '--private-runtime', '--', '{inputs:reports}'],
        produces=['html', 'data', 'general-statistics', 'sources'])]
    wf = workflow('aggregate', 'MultiQC: compare QC reports',
        'Build a self-contained MultiQC report from selected local QC files. No cloud uploads, AI summaries, browser launch or automatic configuration.', inputs, outputs, steps)
    schema = {'schema': 1, 'category': 'Quality control', 'citations': [CITATION], 'workflows': {'aggregate': {
        'ports': [{'id': 'reports', 'label': 'Selected QC reports', 'type': 'metrics', 'accepts': ['metrics'], 'manifestInputs': ['reports'], 'min': 1, 'max': 64}],
        'outputs': [{'id': item['id'], 'label': item['label'], 'type': 'report' if item['id'] == 'html' else 'metrics', 'manifestOutputs': [item['id']]} for item in outputs],
        'methods': 'QC report files were aggregated with MultiQC 1.35 using its FastQC, fastp, STAR, featureCounts and kallisto parsers. Each selected report received a distinct recorded input namespace; biological sample identity across different tools was not inferred. featureCounts columns received distinct recorded labels without changing the numerical counts. A self-contained interactive HTML report, upstream machine-readable data, general statistics and input hashes were retained. Automatic user configuration, version checks, remote uploads and AI summaries were disabled. The original analyses were not rerun, and no clinical or experimental QC acceptance decision was inferred.'}}}
    return [wf], schema


def fixtures(destination):
    destination.mkdir(exist_ok=True)
    for name, count, gc in [('sample-a', 20, 40), ('sample-b', 30, 60)]:
        text = f'##FastQC\t0.13.0\n>>Basic Statistics\tpass\n#Measure\tValue\nFilename\tshared-name.fastq\nFile type\tConventional base calls\nEncoding\tSanger / Illumina 1.9\nTotal Sequences\t{count}\nSequences flagged as poor quality\t0\nSequence length\t50\n%GC\t{gc}\n>>END_MODULE\n'
        (destination / (name + '_fastqc_data.txt')).write_text(text)
    star = {'Number of input reads': 100, 'Average input read length': 100,
        'Uniquely mapped reads number': 80, 'Uniquely mapped reads %': '80.00%', 'Average mapped length': 100,
        'Number of splices: Total': 20, 'Number of splices: Annotated (sjdb)': 18,
        'Number of splices: GT/AG': 20, 'Number of splices: GC/AG': 0, 'Number of splices: AT/AC': 0,
        'Number of splices: Non-canonical': 0, 'Mismatch rate per base, %': '0.10%',
        'Deletion rate per base': '0.00%', 'Deletion average length': 0,
        'Insertion rate per base': '0.00%', 'Insertion average length': 0,
        'Number of reads mapped to multiple loci': 10, '% of reads mapped to multiple loci': '10.00%',
        'Number of reads mapped to too many loci': 0, '% of reads mapped to too many loci': '0.00%',
        '% of reads unmapped: too many mismatches': '0.00%', '% of reads unmapped: too short': '10.00%',
        '% of reads unmapped: other': '0.00%'}
    (destination / 'rnaLog.final.out').write_text('\n'.join(k + ' |\t' + str(v) for k, v in star.items()) + '\n')
    (destination / 'quantification.log').write_text('[quant] will process file 1: shared-name.fastq\n[quant] finding pseudoalignments for the reads\n[quant] processed 20 reads, 16 reads pseudoaligned\n[quant] estimated average fragment length: 180\n[quant] quantifying the abundances ... done\n')
    (destination / 'counts.summary').write_text('Status\tsample.bam\tsecond.bam\nAssigned\t12\t8\nUnassigned_NoFeatures\t3\t2\nUnassigned_Ambiguity\t5\t0\n')
    before = {'total_reads': 100, 'total_bases': 5000, 'q20_bases': 4900, 'q30_bases': 4500, 'q20_rate': 0.98, 'q30_rate': 0.9, 'read1_mean_length': 50, 'gc_content': 0.5}
    after = {'total_reads': 90, 'total_bases': 4500, 'q20_bases': 4500, 'q30_bases': 4410, 'q20_rate': 1.0, 'q30_rate': 0.98, 'read1_mean_length': 50, 'gc_content': 0.5}
    dump(destination / 'preprocessing.json', {'summary': {'fastp_version': '1.0.1', 'before_filtering': before, 'after_filtering': after},
        'filtering_result': {'passed_filter_reads': 90, 'low_quality_reads': 10, 'too_many_N_reads': 0, 'too_short_reads': 0, 'too_long_reads': 0},
        'duplication': {'rate': 0.1}, 'command': 'fastp -i synthetic.fastq -o filtered.fastq'})
    dump(destination / 'truth.json', {'source': 'Synthetic, hand-authored QC summaries; no patient or user data.', 'fastqc': [{'reads': 20, 'gcPercent': 40}, {'reads': 30, 'gcPercent': 60}], 'star': {'totalReads': 100, 'uniqueReads': 80, 'multimappedReads': 10}, 'kallisto': {'processedReads': 20, 'pseudoalignedReads': 16}})


def checks():
    return {'schema': 1, 'checks': [{'id': 'aggregate-distinct-inputs', 'workflow': 'aggregate', 'inputs': {'reports': [
        {'reports': 'fixture-fastqc-a'}, {'reports': 'fixture-fastqc-b'}, {'reports': 'fixture-star'}, {'reports': 'fixture-kallisto'}, {'reports': 'fixture-featurecounts'}, {'reports': 'fixture-fastp'}]},
        'expect': [{'output': 'html', 'kind': 'text', 'contains': ['MultiQC Report', 'Content-Security-Policy', 'connect-src', 'input001_', 'input002_']},
            {'output': 'general-statistics', 'kind': 'text', 'contains': ['input001_', 'input002_', 'input003_', 'input004_', 'fastqc-total_sequences', 'star-uniquely_mapped', 'kallisto-pseudoaligned_reads']},
            {'output': 'data', 'kind': 'text', 'contains': ['"Total Sequences": 20.0', '"Total Sequences": 30.0', '"uniquely_mapped": 80.0', '"pseudoaligned_reads": 16.0', '"Assigned": 12', '"Assigned": 8', '"passed_filter_reads": 90']},
            {'output': 'sources', 'kind': 'text', 'contains': ['"inputCount": 6', '"networkDisabled": true', '"automaticConfigurationDisabled": true', '"originalSampleColumns"']}]}]}


def obtain(pin, path, fetch):
    if not path.exists():
        if not fetch:
            raise ValueError('Missing pinned build input; use --fetch: ' + str(path))
        path.parent.mkdir(parents=True, exist_ok=True)
        with urllib.request.urlopen(pin['url'], timeout=180) as response, path.open('wb') as output:
            shutil.copyfileobj(response, output)
    if sha(path) != pin['sha256']:
        raise ValueError('Build input SHA-256 mismatch: ' + str(path))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cache', type=Path, default=ROOT.parent / 'popular-build/multiqc')
    parser.add_argument('--destination', type=Path, default=ROOT / 'packs' / ('multiqc-' + PACK_VERSION))
    parser.add_argument('--fetch', action='store_true')
    args = parser.parse_args()
    cache, dest = args.cache.resolve(), args.destination.resolve()
    lock = json.loads(LOCK.read_text())
    if dest.exists() and any(dest.iterdir()):
        raise ValueError('Pack destination must be new or empty')
    for sub in ('bin', 'wheels', 'licenses', 'fixtures'):
        (dest / sub).mkdir(parents=True, exist_ok=True)
    python_pin = next(p for p in lock['python'] if p['filename'].endswith('.zip'))
    obtain(python_pin, cache / python_pin['filename'], args.fetch)
    with zipfile.ZipFile(cache / python_pin['filename']) as archive:
        archive.extractall(dest / 'bin')
    for name in ('pythonw.exe',):
        (dest / 'bin' / name).unlink(missing_ok=True)
    # Explicit isolated embedded search path: no import site, global modules,
    # registry Python settings or user-controlled .pth files.
    (dest / 'bin/python313._pth').write_text('python313.zip\n.\n', encoding='ascii')
    for pin in lock['wheels']:
        source = cache / 'wheels313' / pin['filename']
        obtain(pin, source, args.fetch)
        shutil.copy2(source, dest / 'wheels' / source.name)
    # MultiQC wheel contains complete Python source and license. Retain the
    # official source archive too; Python source documents bundled components.
    multiqc = next(w for w in lock['wheels'] if w['name'].lower() == 'multiqc')
    for pin in [next(p for p in lock['python'] if p['filename'].endswith('.xz')), multiqc['source']]:
        source = cache / pin['filename']
        obtain(pin, source, args.fetch)
        shutil.copy2(source, dest / 'licenses' / source.name)
    shutil.copy2(ROOT / 'tools/multiqc/adapter.py', dest / 'adapter.py')
    shutil.copy2(LOCK, dest / 'licenses/windows-lock.json')
    shutil.copy2(ROOT / 'scripts/prepare_multiqc_pack.py', dest / 'licenses/prepare_multiqc_pack.py')
    shutil.copy2(ROOT / 'tools/multiqc/adapter.py', dest / 'licenses/adapter.py')
    shutil.copy2(ROOT / 'LICENSE', dest / 'licenses/Workbench-MIT.txt')
    shutil.copy2(ROOT / 'docs/MULTIQC-PACK.md', dest / 'PACK-README.md')
    workflows, schema = definitions()
    dump(dest / 'workbench-schema.json', schema)
    dump(dest / 'workbench-checks.json', checks())
    fixtures(dest / 'fixtures')
    dump(dest / 'licenses/provenance.json', {'schema': 1, 'pack': 'multiqc', 'packVersion': PACK_VERSION,
        'toolVersion': VERSION, 'pythonVersion': lock['pythonVersion'], 'lockSha256': sha(LOCK), 'citation': CITATION,
        'upstream': 'https://github.com/MultiQC/MultiQC/tree/v1.35', 'windowsExecuted': False,
        'runtime': 'Official Python embeddable runtime and unchanged pinned Windows wheels; unpacked privately in each run; no pip, installer, registry change or system Python.',
        'adaptations': ['Implicit user configuration is disabled through a process-local config.find_user_files override.', 'Inputs are content-classified and staged under safe distinct names; FastQC ZIP reads only fastqc_data.txt; fastp JSON is serialized without changing data.', 'Only an empty reserved output directory precreated by the native runner is removed before invoking MultiQC, preserving exact declared output names; nonempty directories and existing reports are refused.', 'Version checks, AI, remote uploads and flat rendering are disabled; Python audit hook refuses outbound network calls and subprocess launch; HTML receives a restrictive offline Content Security Policy.', 'Kaleido static-image dependency is deliberately omitted; interactive upstream plots are forced.'],
        'sourcePolicy': 'The MultiQC and CPython source archives are bundled. Python dependencies retain original wheel source/metadata/licenses; windows-lock.json lists exact corresponding source URLs and hashes where supplied on PyPI.'})
    (dest / 'licenses/NOTICE.txt').write_text('MultiQC 1.35 is GPL-3.0-or-later. This distribution retains its unchanged wheel and source archive. Workbench adapter/preparer are MIT. Python is distributed under PSF and bundled component licenses; its original embedded LICENSE.txt and source archive are retained. Each dependency wheel retains its original dist-info licenses/notices and distribution metadata; see windows-lock.json for exact upstream source references. Wheels are not replaced with compiled stubs. Kaleido/Chromium is not distributed or used.\n', encoding='utf-8')
    sections = []
    def section(name, values):
        sections.append('[' + name + ']\n' + '\n'.join(k + '=' + str(v) for k, v in values.items() if k != 'id' or name == 'pack') + '\n')
    section('pack', {'format': 2, 'id': 'multiqc', 'version': PACK_VERSION, 'name': 'MultiQC local reporting', 'platform': 'windows-x86_64', 'description': 'Compare selected FastQC, fastp, STAR, featureCounts and kallisto reports locally. Workbench 0.6.0 or newer.', 'color': '#557C9D'})
    section('tool:python', {'path': 'bin/python.exe', 'version': lock['pythonVersion'], 'sha256': sha(dest / 'bin/python.exe')})
    explicit = {'adapter': 'adapter.py', 'workbench-schema': 'workbench-schema.json', 'workbench-checks': 'workbench-checks.json',
        'fixture-fastqc-a': 'fixtures/sample-a_fastqc_data.txt', 'fixture-fastqc-b': 'fixtures/sample-b_fastqc_data.txt',
        'fixture-star': 'fixtures/rnaLog.final.out', 'fixture-kallisto': 'fixtures/quantification.log', 'fixture-featurecounts': 'fixtures/counts.summary', 'fixture-fastp': 'fixtures/preprocessing.json'}
    used = {'bin/python.exe'}
    for key, path in explicit.items():
        section('asset:' + key, {'path': path, 'sha256': sha(dest / path)})
        used.add(path)
    for n, path in enumerate(sorted(dest.rglob('*'))):
        relative = path.relative_to(dest).as_posix()
        if path.is_file() and relative not in used and not relative.startswith('licenses/') and relative != 'PACK-README.md':
            section('asset:runtime-' + str(n), {'path': relative, 'sha256': sha(path)})
    for wf in workflows:
        section('workflow:' + wf['id'], {'name': wf['name'], 'description': wf['description'], 'inputs': ','.join(i['id'] for i in wf['inputs']), 'outputs': ','.join(i['id'] for i in wf['outputs']), 'steps': ','.join(i['id'] for i in wf['steps'])})
        for kind in ('input', 'output', 'step'):
            for item in wf[kind + 's']:
                section(kind + ':' + wf['id'] + ':' + item['id'], item)
    (dest / 'pack.ini').write_text('\n'.join(sections), encoding='utf-8')
    sys.path.insert(0, str(ROOT / 'workspace'))
    from catalog import load_pack
    pack = load_pack(dest / 'pack.ini')
    print(json.dumps({'pack': str(dest), 'manifestSha256': sha(dest / 'pack.ini'), 'workflows': list(pack['workflows']), 'filesAndFolders': len(list(dest.rglob('*'))), 'bytes': sum(p.stat().st_size for p in dest.rglob('*') if p.is_file())}, indent=2))


if __name__ == '__main__':
    main()
