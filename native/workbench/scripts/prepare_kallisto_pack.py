#!/usr/bin/env python3
"""Assemble the independently versioned kallisto RNA-seq pack for Workbench 0.6.0."""
import argparse, gzip, hashlib, json, random, shutil, sys
from pathlib import Path
from build_kallisto_native import ROOT, SOURCES, SOURCE_COMMIT, VERSION, TC_NAME, sha
from prepare_rnaseq_licenses import retain_rna_notices
sys.path.insert(0, str(ROOT / 'desktop'))
from prepare_modular_packs import field, number, artifact, execute, workflow

PACK_VERSION = '1.0.1'
CITATION = {'text': 'Bray NL, Pimentel H, Melsted P, Pachter L (2016). Near-optimal probabilistic RNA-seq quantification. Nature Biotechnology 34:525–527.', 'url': 'https://doi.org/10.1038/nbt.3519'}

def dump(path, value):
    path.write_text(json.dumps(value, indent=2) + '\n', encoding='utf-8')

def fixtures(path):
    path.mkdir(parents=True, exist_ok=True)
    rng = random.Random(810431)
    sequences = [''.join(rng.choice('ACGT') for _ in range(1000)) for _ in range(3)]
    (path / 'transcripts.fasta').write_text(''.join('>tx' + str(n+1) + '\n' + seq + '\n' for n, seq in enumerate(sequences)))
    first, second = [], []
    for transcript, count in enumerate((12, 6, 2)):
        for n in range(count):
            start, length = 70 + n*29, 180 + n % 5 - 2
            identity = 'tx' + str(transcript+1) + '_read' + str(n+1)
            first.append((identity, sequences[transcript][start:start+75]))
            second.append((identity, sequences[transcript][start+length-75:start+length].translate(str.maketrans('ACGT', 'TGCA'))[::-1]))
    for name, rows, suffix in [('single.fastq', first, ''), ('reads1.fastq', first, '/1'), ('reads2.fastq', second, '/2')]:
        data = ''.join('@' + label + suffix + '\n' + seq + '\n+\n' + 'I'*len(seq) + '\n' for label, seq in rows).encode()
        (path / name).write_bytes(data)
        with (path / (name + '.gz')).open('wb') as raw:
            with gzip.GzipFile(filename='', mode='wb', fileobj=raw, mtime=0) as stream: stream.write(data)
    dump(path / 'truth.json', {'transcriptLengths': {'tx1': 1000, 'tx2': 1000, 'tx3': 1000}, 'fragments': {'tx1': 12, 'tx2': 6, 'tx3': 2}, 'tpm': {'tx1': 600000, 'tx2': 300000, 'tx3': 100000}, 'readLength': 75, 'description': 'Three independent synthetic transcripts of equal length; 20 uniquely compatible fragments. This checks tool behavior, not biological accuracy.'})

def definitions():
    workflows, schemas = [], {}
    threads = lambda: number('threads', 'CPU threads', 2, 1, 64, help='Worker count; RAM use depends on transcriptome size and workers. There is no hard memory cap.')
    transcript = lambda: field('transcriptome', 'Transcriptome FASTA', filter='Transcript FASTA|*.fa;*.fasta;*.fna;*.fa.gz;*.fasta.gz;*.fna.gz|All files|*.*', help='Transcript/cDNA sequences with unique transcript IDs, such as an Ensembl cDNA FASTA. Use the release matching downstream gene annotations. A genomic FASTA is not a transcriptome. Plain or gzip accepted.')
    transcript_port = lambda: dict(id='transcriptome', label='Transcriptome FASTA', type='fasta-nucleotide', accepts=['fasta-nucleotide'], manifestInputs=['transcriptome'], min=1, max=1, validation={'minRecords': 1, 'uniqueIds': True})
    kmer = lambda: field('kmer', 'Index k-mer length', 'choice', default='31', choices='31:31 bases (standard)|25:25 bases|21:21 bases', help='Reads shorter than k cannot contribute indexed k-mers. Smaller k-mers may reduce specificity; the same index must be reused consistently across samples.')
    index_artifact = lambda: artifact('index', 'Reusable kallisto transcriptome index', 'transcripts.idx')
    index_product = lambda: dict(id='index', label='kallisto transcriptome index', type='index', manifestOutputs=['index'])
    index_step = lambda: execute('index', 'Build transcriptome index', 'kallisto', ['index', '--index', '{output:index}', '--kmer-size', '{input:kmer}', '--threads', '{input:threads}', '{input:transcriptome}'], produces=['index'])
    workflows.append(workflow('index', 'Build kallisto transcriptome index', 'Build a reusable kallisto index from transcript/cDNA FASTA. The reference is unchanged.', [transcript(), kmer(), threads()], [index_artifact()], [index_step()]))
    schemas['index'] = {'ports': [transcript_port()], 'outputs': [index_product()], 'methods': 'A transcriptome index was constructed with kallisto ' + VERSION + ' using the recorded k-mer length and transcript FASTA. Transcript identifiers were required to be unique; no external genomic D-list was supplied.', 'pathPolicy': {'asciiOnly': True}}
    for combined in (False, True):
        for paired in (False, True):
            identity = ('index-' if combined else '') + 'quant-' + ('paired' if paired else 'single')
            title = ('Index and quantify ' if combined else 'Quantify ') + ('paired-end' if paired else 'single-end') + ' RNA-seq'
            inputs = []
            for key in (['reads1', 'reads2'] if paired else ['reads']):
                extra = {'different-from': 'reads1'} if key == 'reads2' else {}
                inputs.append(field(key, {'reads1': 'Read 1 FASTQ', 'reads2': 'Read 2 FASTQ', 'reads': 'Reads FASTQ'}[key], filter='FASTQ reads|*.fastq;*.fq;*.fastq.gz;*.fq.gz|All files|*.*', help='Plain or gzip-compressed FASTQ; structure and quality lengths are validated before quantification. Paired files must have matching mate names, counts and order.', **extra))
            ports = [dict(id='reads', label='Paired RNA reads' if paired else 'RNA reads', type='pair' if paired else 'reads', manifestInputs=['reads1', 'reads2'] if paired else ['reads'], min=1, max=1)]
            if combined:
                inputs += [transcript(), kmer()]
                ports.append(transcript_port())
            else:
                inputs.append(field('index', 'kallisto transcriptome index', filter='kallisto index|*.idx;*.kidx|All files|*.*', help='A kallisto version-13 transcriptome index produced with this pack. BAM/FASTA indexes and indexes for other aligners are incompatible. Rebuild from transcript FASTA if unsure.'))
                ports.append(dict(id='index', label='Compatible kallisto index', type='index', manifestInputs=['index'], min=1, max=1))
            inputs += [field('strandness', 'RNA library strandedness', 'choice', default='unstranded', choices='unstranded:Unstranded|fr:Read 1 follows transcript (FR)|rf:Read 1 opposes transcript (RF)', help='Select the actual library preparation. FR means the single read/read 1 follows the transcript strand; RF means it opposes it. This is not inferred.'), threads(), number('bootstraps', 'Bootstrap replicates', 0, 0, 1000, help='0 disables resampling. Replicates assess technical quantification uncertainty and are not biological replicates. Plaintext tables are collected into bootstrap-estimates.tsv.'), number('seed', 'Bootstrap random seed', 42, 0, 2147483647)]
            if not paired:
                # Deliberately no defaults: users must supply estimates from library preparation.
                inputs += [field('fragment-mean', 'Mean fragment length (bases)', 'integer', min='1', max='10000', help='Required for single-end RNA-seq. Enter the mean fragment/insert length measured or estimated for this library, not simply the sequenced read length.'), field('fragment-sd', 'Fragment length SD (bases)', 'integer', min='1', max='10000', help='Required positive standard deviation for the same library fragment-length distribution. Both length fields accept whole bases.')]
            outputs = ([index_artifact()] if combined else []) + [artifact('read-check', 'FASTQ validation', 'read-check.json'), artifact('abundance', 'Transcript counts and TPM', 'quant/abundance.tsv'), artifact('run-info', 'kallisto run metrics', 'quant/run_info.json'), artifact('bootstraps', 'Bootstrap transcript estimates', 'quant/bootstrap-estimates.tsv')]
            validation = execute('validate-reads', 'Validate FASTQ structure and mate synchronization', 'readcheck', ['--reads1', '{input:reads1}', '--reads2', '{input:reads2}'] if paired else ['--single', '{input:reads}'], stdout='read-check')
            steps = [validation] + ([index_step()] if combined else [])
            steps.append(execute('quantify', 'Pseudoalign RNA reads and estimate transcript abundances', 'kallisto-adapter', ['quant', '{output:index}' if combined else '{input:index}', '{input:reads1}' if paired else '{input:reads}', '{input:reads2}' if paired else '-', '{run}/quant', '{input:strandness}', '{input:threads}', '{input:bootstraps}', '{input:seed}', '0' if paired else '{input:fragment-mean}', '0' if paired else '{input:fragment-sd}'], produces=['abundance', 'run-info', 'bootstraps']))
            workflows.append(workflow(identity, title, ('Build a fresh transcriptome index, then quantify' if combined else 'Use a compatible transcriptome index to quantify') + ' bulk short-read RNA-seq. Returns transcript-level estimated counts, TPM and optional bootstrap estimates; no differential-expression analysis.', inputs, outputs, steps))
            products = [dict(id='abundance', label='Transcript counts and TPM', type='metrics', manifestOutputs=['abundance']), dict(id='run-info', label='kallisto run metrics', type='metrics', manifestOutputs=['run-info']), dict(id='bootstraps', label='Bootstrap transcript estimates', type='metrics', manifestOutputs=['bootstraps']), dict(id='read-check', label='FASTQ validation', type='metrics', manifestOutputs=['read-check'])] + ([index_product()] if combined else [])
            schemas[identity] = {'ports': ports, 'outputs': products, 'methods': 'FASTQ records' + (' and paired-read synchronization' if paired else '') + ' were validated before analysis. ' + ('A fresh transcriptome index was constructed with the recorded k-mer length. ' if combined else 'A compatible kallisto transcriptome index was reused. ') + 'Transcript abundances were estimated using kallisto ' + VERSION + ' pseudoalignment and expectation maximization. Library strandedness, worker count, bootstrap replicate count and random seed were recorded. ' + ('Fragment lengths were estimated from the paired reads.' if paired else 'The specified library fragment-length mean and standard deviation were supplied for single-end estimation.') + ' Estimated transcript counts and TPM were written as plaintext; bootstrap estimates, when requested, were retained. No sequence-bias correction, gene-level aggregation or differential-expression test was performed.', 'pathPolicy': {'asciiOnly': True}}
    return workflows, {'schema': 1, 'category': 'RNA-seq', 'citations': [CITATION], 'workflows': schemas}

def checks():
    values = []
    for paired in (False, True):
        params = {'threads': 2, 'bootstraps': 3, 'seed': 42, 'kmer': '31', 'strandness': 'fr'}
        if not paired: params.update({'fragment-mean': 180, 'fragment-sd': 20})
        length = '821.4' if paired else '821'
        values.append({'id': 'known-' + ('paired' if paired else 'single') + '-abundances', 'workflow': 'index-quant-' + ('paired' if paired else 'single'), 'params': params, 'inputs': {'transcriptome': [{'transcriptome': 'fixture-transcriptome'}], 'reads': [{'reads1': 'fixture-reads1-gz', 'reads2': 'fixture-reads2-gz'}] if paired else [{'reads': 'fixture-single-gz'}]}, 'expect': [{'output': 'abundance', 'kind': 'text', 'contains': ['target_id\tlength\teff_length\test_counts\ttpm', *['tx' + str(n+1) + '\t1000\t' + length + '\t' + str(count) + '\t' + str(tpm) for n, (count, tpm) in enumerate(((12, 600000), (6, 300000), (2, 100000)))]]}, {'output': 'run-info', 'kind': 'text', 'contains': ['"n_processed": 20', '"n_pseudoaligned": 20', '"n_bootstraps": 3', '"index_version": 13']}, {'output': 'bootstraps', 'kind': 'text', 'contains': ['bootstrap\ttarget_id\tlength\teff_length\test_counts\ttpm', '0\ttx1\t1000\t', '2\ttx3\t1000\t']}, {'output': 'read-check', 'kind': 'text', 'contains': ['"valid":true', '"reads":40' if paired else '"reads":20']}]})
    return {'schema': 1, 'checks': values}

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--vendor', type=Path, default=ROOT / 'vendor-expanded/kallisto')
    parser.add_argument('--destination', type=Path, default=ROOT / 'packs' / ('kallisto-' + PACK_VERSION))
    parser.add_argument('--toolchain', type=Path, default=ROOT.parent / 'toolchains' / TC_NAME)
    args = parser.parse_args()
    vendor, destination = args.vendor.resolve(), args.destination.resolve()
    build = json.loads((vendor / 'build-windows/build.json').read_text())
    if build['version'] != VERSION or build['sourceCommit'] != SOURCE_COMMIT or build['patchSha256'] != sha(vendor / 'workbench2.patch'):
        raise ValueError('Build identity does not match pinned sources and patch')
    if destination.exists() and any(destination.iterdir()): raise ValueError('Pack destination must be new/empty: ' + str(destination))
    for directory in ('bin', 'licenses', 'fixtures'): (destination / directory).mkdir(parents=True, exist_ok=True)
    sections = []
    def section(name, values):
        sections.append('[' + name + ']\n' + '\n'.join(key + '=' + str(value) for key, value in values.items() if key != 'id' or name == 'pack') + '\n')
    section('pack', {'format': 2, 'id': 'kallisto', 'version': PACK_VERSION, 'name': 'kallisto RNA-seq quantification', 'platform': 'windows-x86_64', 'description': 'Index transcriptomes and quantify paired or single-end bulk RNA-seq locally, with explicit library settings and optional bootstrap estimates. Workbench 0.6.0 or newer.', 'color': '#358A83'})
    for tool in ('kallisto', 'kallisto-adapter', 'readcheck'):
        source = vendor / 'build-windows' / (tool + '.exe')
        if sha(source) != build['files'][source.name]['sha256']: raise ValueError('Executable changed since build: ' + tool)
        shutil.copy2(source, destination / 'bin' / source.name)
        section('tool:' + tool, {'path': 'bin/' + source.name, 'version': VERSION if tool == 'kallisto' else '1.0.0', 'sha256': sha(source)})
    workflows, schema = definitions()
    dump(destination / 'workbench-schema.json', schema)
    dump(destination / 'workbench-checks.json', checks())
    fixtures(destination / 'fixtures')
    assets = {'workbench-schema': 'workbench-schema.json', 'workbench-checks': 'workbench-checks.json', 'fixture-transcriptome': 'fixtures/transcripts.fasta', 'fixture-truth': 'fixtures/truth.json'}
    for name in ('single', 'reads1', 'reads2'):
        assets['fixture-' + name] = 'fixtures/' + name + '.fastq'
        assets['fixture-' + name + '-gz'] = 'fixtures/' + name + '.fastq.gz'
    for key, path in assets.items(): section('asset:' + key, {'path': path, 'sha256': sha(destination / path)})
    for wf in workflows:
        section('workflow:' + wf['id'], {'name': wf['name'], 'description': wf['description'], 'inputs': ','.join(x['id'] for x in wf['inputs']), 'outputs': ','.join(x['id'] for x in wf['outputs']), 'steps': ','.join(x['id'] for x in wf['steps'])})
        for kind in ('input', 'output', 'step'):
            for item in wf[kind + 's']: section(kind + ':' + wf['id'] + ':' + item['id'], item)
    (destination / 'pack.ini').write_text('\n'.join(sections), encoding='utf-8')
    licenses = destination / 'licenses'
    for name, (url, checksum) in SOURCES.items():
        if sha(vendor / name) != checksum: raise ValueError('Source archive differs: ' + name)
        shutil.copy2(vendor / name, licenses / name)
    for source, name in [(vendor / 'kallisto-0.52.0/license.txt', 'kallisto-BSD-2-Clause.txt'), (vendor / 'kallisto-0.52.0/ext/bifrost/LICENSE', 'Bifrost-BSD-2-Clause.txt'), (vendor / 'zlib-1.3.2/README', 'zlib-README.txt'), (vendor / 'workbench2.patch', 'workbench2.patch'), (ROOT / 'scripts/build_kallisto_native.py', 'build_kallisto_native.py'), (ROOT / 'tools/kallisto/adapter.cpp', 'adapter.cpp'), (ROOT / 'tools/kallisto/readcheck.c', 'readcheck.c'), (args.toolchain / 'LICENSE.TXT', 'LLVM-LICENSE.txt')]: shutil.copy2(source, licenses / name)
    for source in (args.toolchain / 'x86_64-w64-mingw32/share/mingw32').glob('COPYING*'): shutil.copy2(source, licenses / source.name)
    (licenses / 'MODIFICATIONS.txt').write_text('kallisto 0.52.0-workbench2, modified 2026-10-03 for Native Workbench. The exact upstream source and patch are included. Changes: explicit pthread header in Bifrost; correct an unused DataStorage copy-template member typo; match Bifrost Windows aligned allocation with aligned deallocation; use a private inline roaring_bitmap_contains definition to avoid duplicate COFF symbols; identify the modified build in version metadata. Workbench2 fixes upstream plaintext bootstrap dispatch when threads exceed one: it invokes the existing BootstrapThreadPool without an HDF5 writer, using the already calculated worker limit. Single-thread and multithread bootstraps use the same upstream seeds, sampler and EM algorithm. The RNA quantification algorithms and mathematical parameters are unchanged. Built without HDF5 or HTSlib/BAM; plaintext bootstrap output is supported. The MIT-licensed adapter handles explicit strand selection and concatenates unchanged plaintext bootstrap tables, without a shell. readcheck is the existing MIT Workbench strict gzip/FASTQ pair parser extended for single-end files and compiled natively. Full upstream and embedded third-party copyright/license notices remain in the source archives.\n')
    dump(licenses / 'provenance.json', {'schema': 1, 'pack': 'kallisto', 'packVersion': PACK_VERSION, 'minAppVersion': '0.6.0', 'nativeBuild': build, 'citation': CITATION, 'upstream': 'https://github.com/pachterlab/kallisto/tree/v0.52.0', 'limitations': ['Bulk short-read transcript quantification only; no single-cell BUS, long-read quantification, BAM output, bias correction, gene aggregation or differential-expression analysis.', 'A transcript/cDNA reference is required; a genomic reference cannot be substituted.', 'ASCII paths required; spaces supported. Threads do not impose a memory cap.', 'The index input type cannot distinguish indexes for different tools; native version validation and kallisto loading reject incompatible inputs.', 'Bootstrap values can differ across compiler/platform standard-library random distributions; the seed remains reproducible within the same pack build.'], 'windowsExecuted': False})
    shutil.copy2(ROOT / 'docs/KALLISTO-PACK.md', destination / 'PACK-README.md')
    retain_rna_notices(ROOT, destination, 'kallisto')
    sys.path.insert(0, str(ROOT / 'workspace'))
    from catalog import load_pack
    pack = load_pack(destination / 'pack.ini')
    print(json.dumps({'pack': str(destination), 'manifestSha256': sha(destination / 'pack.ini'), 'workflows': list(pack['workflows'])}, indent=2))

if __name__ == '__main__': main()
