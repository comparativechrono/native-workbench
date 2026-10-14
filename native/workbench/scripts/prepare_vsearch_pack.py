#!/usr/bin/env python3
"""Reproduce the VSEARCH Windows pack from hash-pinned official release assets.

No downloads or execution occur here. Run after fetching the documented archives;
Linux reference binaries are intentionally excluded from the Windows tool pack.
"""
import argparse
import hashlib
import json
from pathlib import Path
import random
import shutil
import sys
import tarfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'desktop'))
from prepare_modular_packs import field, number, artifact, execute, workflow

VERSION = '0.5.2'
VSEARCH = '2.32.0'
PAIR_SHA = '4f2dda7e26b5c115a7edee936a8a059eb55ece244931b2799a62cebfcd44ecd4'
PINS = {
    'vsearch-2.32.0-win-x86_64.zip': '50ead8474607a325c9021bae890f10d0fa296489d5c266a4dc621e23b98637cf',
    'vsearch-2.32.0.tar.gz': '99578a8b960a0fb87c1f19dc65aedecddc01cfa91851b697dac8294dd08a6ceb',
    'zlib-1.3.1-LICENSE.txt': '845efc77857d485d91fb3e0b884aaa929368c717ae8186b66fe1ed2495753243',
}
FASTQ = 'FASTQ reads|*.fastq;*.fq;*.fastq.gz;*.fq.gz|All files|*.*'
FASTA = 'Nucleotide FASTA|*.fa;*.fasta;*.fna;*.fa.gz;*.fasta.gz|All files|*.*'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def choice(identity, label, default, values, help=''):
    return field(identity, label, 'choice', default=str(default),
                 choices='|'.join(str(v)+':'+str(v) for v in values), help=help)


def sequence_field(weighted=False):
    return field('sequences', 'Sequences with abundance labels' if weighted else 'Nucleotide sequences', filter=FASTA,
                 help='Every FASTA ID must contain a positive ;size=N; annotation. Counts are preserved.' if weighted else
                 'Unaligned nucleotide FASTA without size annotations; each record counts once. If headers contain size=N, choose abundance-aware dereplication.')


def port(identity, kind, members, **extra):
    return dict(id=identity, type=kind, accepts=[kind], manifestInputs=members, min=1, max=1, **extra)


def output(identity, kind, members, **extra):
    state = {'compression': 'none'}
    if kind.startswith('fasta-'):
        state.update(alphabet='nucleotide', alignment='unaligned', abundance=kind.endswith('-abundance'))
    return dict(id=identity, type=kind, manifestOutputs=members, state=state, **extra)


def definitions():
    workflows, schema = [], {}
    def add(identity, name, description, inputs, outputs, steps, ports, descriptors, methods):
        workflows.append(workflow(identity, name, description, inputs, outputs, steps))
        schema[identity] = dict(ports=ports, outputs=descriptors, methods=methods)
    def log():
        return artifact('log', 'VSEARCH run statistics', 'vsearch.log')
    def log_descriptor():
        return output('log', 'metrics', ['log'])
    def args_log():
        return ['--log', '{output:log}', '--no_progress']
    add('merge-pairs', 'VSEARCH: merge paired reads',
        'Validate mate identifiers, then merge overlapping paired-end Phred+33 reads. Retain unmerged mates separately.',
        [field('reads1', 'Forward reads', filter=FASTQ), field('reads2', 'Reverse reads', filter=FASTQ, **{'different-from':'reads1'}),
         number('minimum-overlap', 'Minimum overlap (bases)', 20, 5, 10000),
         number('maximum-differences', 'Maximum overlap mismatches', 5, 0, 10000),
         number('minimum-merged-length', 'Minimum merged length', 1, 1, 100000),
         number('threads', 'Threads', 1, 1, 64)],
        [artifact('merged', 'Merged FASTQ', 'merged.fastq', nonempty=False),
         artifact('unmerged1', 'Unmerged forward reads', 'unmerged_R1.fastq', nonempty=False),
         artifact('unmerged2', 'Unmerged reverse reads', 'unmerged_R2.fastq', nonempty=False),
         artifact('pair-check', 'Mate validation', 'pair-check.json'), log()],
        [execute('check-pairs', 'Validate paired FASTQ records', 'paircheck', ['--reads1','{input:reads1}','--reads2','{input:reads2}'], stdout='pair-check'),
         execute('merge', 'Merge overlaps', 'vsearch', ['--fastq_mergepairs','{input:reads1}','--reverse','{input:reads2}',
            '--fastq_ascii','33','--fastq_qmax','93','--fastq_qmaxout','41',
            '--fastq_minovlen','{input:minimum-overlap}','--fastq_maxdiffs','{input:maximum-differences}',
            '--fastq_minmergelen','{input:minimum-merged-length}','--threads','{input:threads}',
            '--fastqout','{output:merged}','--fastqout_notmerged_fwd','{output:unmerged1}',
            '--fastqout_notmerged_rev','{output:unmerged2}']+args_log(), produces=['merged','unmerged1','unmerged2','log'])],
        [port('reads','pair',['reads1','reads2'])],
        [output('merged','reads',['merged']),output('unmerged','pair',['unmerged1','unmerged2']),output('pair-check','metrics',['pair-check']),log_descriptor()],
        'Mate identifiers and record structure were checked with paircheck, then paired reads were merged with VSEARCH using Phred+33 qualities, the configured overlap and mismatch thresholds, and an output quality cap of 41. Staggered pairs were not allowed. Unmerged mates were retained separately; ambiguous bases receive quality zero under VSEARCH merging rules.')
    add('quality-filter', 'VSEARCH: filter read quality',
        'Filter single or merged Phred+33 FASTQ reads by expected errors, ambiguous bases and length. Export FASTQ and FASTA.',
        [field('reads','Single or merged reads',filter=FASTQ),
         choice('maximum-expected-errors','Maximum expected errors',1,[0.1,0.5,1,2,3,5,10],
                'Expected errors are the sum of per-base error probabilities. This is filtering, not denoising.'),
         number('maximum-ns','Maximum N bases',0,0,100000),number('minimum-length','Minimum length',1,1,100000),
         number('maximum-length','Maximum length',100000,1,100000)],
        [artifact('retained','Retained FASTQ','retained.fastq',nonempty=False),artifact('fasta','Retained FASTA','retained.fasta',nonempty=False),
         artifact('discarded','Discarded FASTQ','discarded.fastq',nonempty=False),log()],
        [execute('filter','Filter reads','vsearch',['--fastq_filter','{input:reads}','--fastq_ascii','33','--fastq_qmax','93',
            '--fastq_maxee','{input:maximum-expected-errors}','--fastq_maxns','{input:maximum-ns}',
            '--fastq_minlen','{input:minimum-length}','--fastq_maxlen','{input:maximum-length}',
            '--fastqout','{output:retained}','--fastaout','{output:fasta}','--fastqout_discarded','{output:discarded}']+args_log(),
            produces=['retained','fasta','discarded','log'])],
        [port('reads','reads',['reads'])],
        [output('retained','reads',['retained']),output('fasta','fasta-nucleotide',['fasta']),output('discarded','reads',['discarded']),log_descriptor()],
        'Single or merged reads were quality filtered with VSEARCH, interpreting qualities as Phred+33. Reads exceeding the configured expected-error or N-base threshold or outside the selected length range were discarded; retained reads were exported as FASTQ and FASTA. No ASV inference or error-model denoising was performed.')
    for weighted in (False, True):
        identity = 'dereplicate-weighted' if weighted else 'dereplicate'
        kind = 'fasta-nucleotide-abundance' if weighted else 'fasta-nucleotide'
        add(identity, 'VSEARCH: dereplicate '+('abundance sequences' if weighted else 'sequences'),
            'Collapse identical full-length nucleotide sequences and '+('sum existing abundances.' if weighted else 'count input records.'),
            [sequence_field(weighted),choice('strand','Strand comparison','plus',['plus','both'],
                'Both also groups reverse complements. Use plus for already oriented amplicons.')],
            [artifact('unique','Unique sequences with abundances','unique.fasta'),artifact('membership','Dereplication membership','dereplication.uc'),log()],
            [execute('dereplicate','Collapse identical sequences','vsearch',['--fastx_uniques','{input:sequences}',
                '--fastaout','{output:unique}','--uc','{output:membership}','--sizeout','--minseqlength','1',
                '--strand','{input:strand}','--relabel','Uniq']+(['--sizein'] if weighted else [])+args_log(), produces=['unique','membership','log'])],
            [port('sequences',kind,['sequences'],**({'validation':{'rejectAbundance':True}} if not weighted else {}))],
            [output('unique','fasta-nucleotide-abundance',['unique']),output('membership','cluster-membership',['membership']),log_descriptor()],
            'Full-length nucleotide sequences were dereplicated using VSEARCH fastx_uniques with the configured strand comparison. '+
            ('Existing positive size annotations were summed (--sizein).' if weighted else 'Each input record contributed one count; prior header abundance values were not used.')+
            ' Unique sequences were sorted by abundance and written with new Uniq identifiers and explicit size annotations (--sizeout); UC membership was retained.')
    add('filter-abundance','VSEARCH: filter sequence abundance','Retain sequences at or above a minimum abundance and sort them by abundance.',
        [sequence_field(True),number('minimum-abundance','Minimum abundance',2,1,1000000000)],
        [artifact('retained','Sequences passing abundance threshold','abundant.fasta',nonempty=False),log()],
        [execute('abundance','Filter by abundance','vsearch',['--sortbysize','{input:sequences}','--output','{output:retained}',
            '--minsize','{input:minimum-abundance}','--minseqlength','1','--sizeout']+args_log(),produces=['retained','log'])],
        [port('sequences','fasta-nucleotide-abundance',['sequences'])],
        [output('retained','fasta-nucleotide-abundance',['retained']),log_descriptor()],
        'Sequences were filtered by their positive size annotations using VSEARCH sortbysize and the configured minimum abundance. Retained sequences were sorted by decreasing abundance without changing their counts. This threshold is not an error-model denoising step.')
    add('cluster-abundance','VSEARCH: cluster abundant sequences','Greedy abundance-ordered OTU-style clustering; preserve summed abundances and UC membership.',
        [sequence_field(True),choice('identity','Minimum global identity',0.97,[0.8,0.85,0.9,0.95,0.97,0.98,0.99,1.0],
            'Matches divided by alignment length excluding terminal gaps (iddef 2). Heuristic centroid search; not ASV inference.'),
         choice('strand','Strand comparison','plus',['plus','both']),number('threads','Threads',1,1,64)],
        [artifact('centroids','Cluster centroids with abundances','centroids.fasta'),artifact('membership','Cluster membership','clusters.uc'),log()],
        [execute('cluster','Cluster sequences by abundance','vsearch',['--cluster_size','{input:sequences}',
            '--centroids','{output:centroids}','--uc','{output:membership}','--id','{input:identity}','--iddef','2',
            '--strand','{input:strand}','--sizein','--sizeout','--minseqlength','1','--qmask','none',
            '--maxaccepts','1','--maxrejects','32','--threads','{input:threads}','--relabel','OTU']+args_log(),
            produces=['centroids','membership','log'])],
        [port('sequences','fasta-nucleotide-abundance',['sequences'])],
        [output('centroids','fasta-nucleotide-abundance',['centroids']),output('membership','cluster-membership',['membership']),log_descriptor()],
        'Abundance-annotated sequences were greedily clustered with VSEARCH cluster_size in decreasing abundance order using the configured identity threshold and strand policy. Identity used matching columns divided by alignment length excluding terminal gaps (iddef 2); nucleotide masking was disabled. The heuristic centroid search used maxaccepts 1 and maxrejects 32. Input abundances were summed into OTU centroid size annotations; this produces OTU-style clusters, not ASVs.')
    add('chimera-reference','VSEARCH: reference chimera screening','Screen abundance sequences against a user-supplied chimera-free nucleotide reference; retain three classifications separately.',
        [sequence_field(True),field('reference','Chimera-free reference FASTA',filter=FASTA,
            help='Provide a suitable curated reference in the same orientation. No database is downloaded or inferred.'),
         choice('minimum-score','Minimum chimera score',0.28,[0.1,0.2,0.28,0.5,1.0]),
         number('minimum-differences','Minimum differences per segment',3,1,1000),number('threads','Threads',1,1,64)],
        [artifact('nonchimeras','Classified nonchimeras','nonchimeras.fasta',nonempty=False),
         artifact('chimeras','Classified chimeras','chimeras.fasta',nonempty=False),
         artifact('borderline','Borderline sequences','borderline.fasta',nonempty=False),
         artifact('classification','UCHIME classification table','uchime.tsv'),log()],
        [execute('chimera','Screen against reference','vsearch',['--uchime_ref','{input:sequences}','--db','{input:reference}',
            '--nonchimeras','{output:nonchimeras}','--chimeras','{output:chimeras}','--borderline','{output:borderline}',
            '--uchimeout','{output:classification}','--sizeout','--minseqlength','1','--qmask','none','--dbmask','none',
            '--minh','{input:minimum-score}','--mindiffs','{input:minimum-differences}','--threads','{input:threads}']+args_log(),
            produces=['nonchimeras','chimeras','borderline','classification','log'])],
        [port('sequences','fasta-nucleotide-abundance',['sequences']),port('reference','fasta-nucleotide',['reference'])],
        [output(name,'fasta-nucleotide-abundance',[name]) for name in ('nonchimeras','chimeras','borderline')]+
        [output('classification','metrics',['classification']),log_descriptor()],
        'Reference-based chimera screening used VSEARCH uchime_ref with the supplied nucleotide reference in the plus orientation, the configured minimum score and segment-difference thresholds, and disabled masking. Abundances were retained. Nonchimera, chimera and borderline classifications were written separately with an 18-field UCHIME table. Classification depends on reference coverage and curation and does not prove that all retained sequences are nonchimeric.')
    return workflows, dict(schema=1,category='Amplicon analysis',citations=[{
        'text':'Rognes et al. (2016). VSEARCH: a versatile open source tool for metagenomics. PeerJ 4:e2584.',
        'url':'https://doi.org/10.7717/peerj.2584'}],workflows=schema)


def fixtures():
    rng = random.Random(5320)
    sequence = ''.join(rng.choice('ACGT') for _ in range(200))
    other = ''.join(rng.choice('ACGT') for _ in range(200))
    reverse = lambda value: value.translate(str.maketrans('ACGT','TGCA'))[::-1]
    def fq(identity, value, quality='I'):
        return '@'+identity+'\n'+value+'\n+\n'+quality*len(value)+'\n'
    records = {
        'derep-fasta': '>r1\n'+sequence+'\n>r2\n'+sequence+'\n>r3\n'+other+'\n',
        'weighted-fasta': '>a;size=7;\n'+sequence+'\n>b;size=3;\n'+sequence+'\n>c;size=2;\n'+other+'\n',
        'merge-r1': fq('amplicon/1', sequence[:150]),
        'merge-r2': fq('amplicon/2', reverse(sequence[-150:])),
        'quality-fastq': fq('good',sequence)+fq('bad',other,'!'),
    }
    checks = dict(schema=1,checks=[
        dict(id='merge-overlap',workflow='merge-pairs',params={},inputs={'reads':[{'reads1':'fixture-merge-r1','reads2':'fixture-merge-r2'}]},
             expect=[dict(output='merged',kind='fastq',records=1,sequences={'amplicon/1':sequence}),
                     dict(output='unmerged',field='unmerged1',kind='fastq',records=0),
                     dict(output='unmerged',field='unmerged2',kind='fastq',records=0)]),
        dict(id='dereplication-counts',workflow='dereplicate',params={},inputs={'sequences':[{'sequences':'fixture-derep-fasta'}]},
             expect=[dict(output='unique',kind='fasta',records=2,sequences={'Uniq1;size=2':sequence,'Uniq2;size=1':other})]),
        dict(id='weighted-cluster-counts',workflow='cluster-abundance',params={'identity':'1.0'},inputs={'sequences':[{'sequences':'fixture-weighted-fasta'}]},
             expect=[dict(output='centroids',kind='fasta',records=2,sequences={'OTU1;size=10':sequence,'OTU2;size=2':other})]),
    ])
    return records, checks


def build(destination):
    vendor = ROOT/'vendor-expanded/vsearch'
    for name, expected in PINS.items():
        if sha(vendor/name) != expected:
            raise ValueError('Upstream archive checksum mismatch: '+name)
    if destination.exists():
        raise ValueError('Output already exists; choose an empty destination: '+str(destination))
    destination.mkdir(parents=True)
    (destination/'bin').mkdir()
    (destination/'licenses').mkdir()
    (destination/'fixtures').mkdir()
    with zipfile.ZipFile(vendor/'vsearch-2.32.0-win-x86_64.zip') as archive:
        prefix = 'vsearch-2.32.0-win-x86_64/'
        for name in ('vsearch.exe','zlib1.dll','libbz2.dll'):
            (destination/'bin'/name).write_bytes(archive.read(prefix+'bin/'+name))
        for name in ('LICENSE.txt','LICENSE_GNU_GPL3.txt','LICENSE_bzip2.txt'):
            (destination/'licenses'/name).write_bytes(archive.read(prefix+name))
        (destination/'licenses/upstream-README.md').write_bytes(archive.read(prefix+'README.md'))
        for name in archive.namelist():
            if name.startswith(prefix+'man/') and not name.endswith('/'):
                # Flat distribution paths avoid Windows MAX_PATH failures.
                (destination/'licenses'/Path(name).name).write_bytes(archive.read(name))
    shutil.copy2(vendor/'zlib-1.3.1-LICENSE.txt',destination/'licenses/zlib-1.3.1.txt')
    shutil.copy2(vendor/'vsearch-2.32.0.tar.gz',destination/'licenses/vsearch-2.32.0.tar.gz')
    for name in ('upstream-downloads.json','github-release-metadata.json','SHA256SUMS','vsearch-2.32.0.tar.gz.sha256'):
        shutil.copy2(vendor/name,destination/'licenses'/name)
    (destination/'licenses/zlib-license-provenance.txt').write_text('Official zlib v1.3.1 license: https://raw.githubusercontent.com/madler/zlib/v1.3.1/LICENSE\nSHA256 '+PINS['zlib-1.3.1-LICENSE.txt']+'\n',encoding='utf-8')
    with tarfile.open(vendor/'vsearch-2.32.0.tar.gz','r:gz') as archive:
        city = archive.extractfile('vsearch-2.32.0/src/vendored/city.cc').read().decode()
        (destination/'licenses/cityhash-MIT.txt').write_text(city[:city.index('#include')],encoding='utf-8')
    paircheck = ROOT/'baselines/bin/paircheck-cosmo.exe'
    if sha(paircheck) != PAIR_SHA:
        raise ValueError('Paircheck executable checksum mismatch')
    shutil.copy2(paircheck,destination/'bin/paircheck.exe')
    shutil.copy2(ROOT/'tools/paircheck.c',destination/'licenses/paircheck.c')
    shutil.copy2(ROOT/'tools/build_paircheck.py',destination/'licenses/build_paircheck.py')
    cosmo = ROOT/'baselines/licenses/cosmopolitan-3.3.10'
    license_map = {}
    for source in sorted(cosmo.rglob('*')):
        if source.is_file():
            name = 'cosmo-'+hashlib.sha256(str(source.relative_to(cosmo)).encode()).hexdigest()[:12]+'.txt'
            shutil.copy2(source,destination/'licenses'/name)
            license_map[name] = str(source.relative_to(cosmo))
    (destination/'licenses/cosmopolitan-notice-index.json').write_text(json.dumps(license_map,indent=2)+'\n',encoding='utf-8')
    (destination/'licenses/paircheck-MIT.txt').write_text((ROOT/'tools/paircheck.c').read_text().split(' * The parser supports')[0]+' */\n',encoding='utf-8')
    workflows, schema = definitions()
    (destination/'workbench-schema.json').write_text(json.dumps(schema,indent=2)+'\n',encoding='utf-8')
    records, checks = fixtures()
    for identity, contents in records.items():
        (destination/'fixtures'/(identity+'.txt')).write_text(contents,encoding='ascii')
    (destination/'workbench-checks.json').write_text(json.dumps(checks,indent=2)+'\n',encoding='utf-8')
    sections = ['[pack]\nformat=2\nid=vsearch\nversion='+VERSION+'\nname=VSEARCH amplicon tools\nplatform=windows-x86_64\ndescription=Nucleotide amplicon merging, filtering, dereplication, clustering and reference chimera screening.\ncolor=#378B86\n']
    def section(name, values):
        sections.append('['+name+']\n'+'\n'.join(k+'='+str(v) for k,v in values.items() if k != 'id')+'\n')
    for name, version in [('vsearch',VSEARCH),('paircheck','1.0.1')]:
        path = 'bin/'+name+'.exe'
        section('tool:'+name,dict(path=path,version=version,sha256=sha(destination/path)))
    assets = {'zlib':'bin/zlib1.dll','bzip2':'bin/libbz2.dll','workbench-schema':'workbench-schema.json','workbench-checks':'workbench-checks.json'}
    assets.update({'fixture-'+identity:'fixtures/'+identity+'.txt' for identity in records})
    for identity, path in assets.items():
        section('asset:'+identity,dict(path=path,sha256=sha(destination/path)))
    for wf in workflows:
        section('workflow:'+wf['id'],dict(name=wf['name'],description=wf['description'],inputs=','.join(x['id'] for x in wf['inputs']),outputs=','.join(x['id'] for x in wf['outputs']),steps=','.join(x['id'] for x in wf['steps'])))
        for kind, plural in [('input','inputs'),('output','outputs'),('step','steps')]:
            for record in wf[plural]:
                section(kind+':'+wf['id']+':'+record['id'],record)
    (destination/'pack.ini').write_text('\n'.join(sections),encoding='utf-8')
    (destination/'PACK-README.md').write_text('''# VSEARCH amplicon tools

Pack 0.5.2; official VSEARCH 2.32.0 Windows x86-64 binary, plus paircheck 1.0.1 for strict paired-read validation. Everything executes locally using argv without a shell. No Python, Docker, WSL or separate VSEARCH installation is required by the tool pack.

The seven workflows cover paired-read merging, expected-error quality filtering, raw and abundance-aware full-length dereplication, abundance filtering, greedy OTU-style clustering, and reference-based chimera screening. Each workflow also runs alone. Logs and UC/UCHIME tables retain individual tool results; they must not be pooled as though they describe the same read population. Filtering and clustering are not ASV denoising. This is not a complete taxonomic or differential-abundance analysis pipeline.

All sequence operations require unaligned nucleotide data. Raw dereplication counts records once; weighted dereplication sums positive size annotations. Clustering preserves abundance with sizein/sizeout. Reference chimera screening requires a suitable user-supplied chimera-free nucleotide reference and writes nonchimera, chimera and borderline outputs separately. Empty filtering outputs are valid; a downstream sequence tool will ask for nonempty input. FASTQ workflows use Phred+33. Paired inputs are validated before VSEARCH, which itself pairs by position.

## Windows validation scope

The executable and bundled compression DLLs are official x86-64 PE files. Only operating-system DLLs are imported. Scientific reference tests use the separately pinned Linux build of the same VSEARCH version; those are not Windows execution tests. The workbench installation check executes the actual Windows pack's merging, dereplication and weighted-clustering fixtures on the user's machine.

VSEARCH uses narrow-character filename APIs. Non-ASCII and very long Windows paths have not been validated and may fail on a machine's code page. Use short ASCII paths for installation, inputs and result folders for this pack. The archive uses flat license and manual paths to avoid deeply nested import paths.

## Provenance and redistribution

VSEARCH is dual licensed under BSD 2-Clause or GPLv3-or-later; unmodified notices and the exact corresponding source archive are included. The bundled zlib and bzip2 DLLs retain their notices. Paircheck source, build instructions and flattened Cosmopolitan notices are included separately.

The current official Windows archive was replaced on 2026-09-28 after SHA256SUMS was published on 2026-09-18. Its current hash matches the official GitHub release asset digest, not the stale Windows line in SHA256SUMS. See licenses/upstream-downloads.json and licenses/github-release-metadata.json for exact provenance. The source archive agrees with its separate SHA256 checksum. Do not substitute an archive with the stale checksum without revising and validating the pin.

Official project: https://github.com/torognes/vsearch
Citation: Rognes et al. (2016), PeerJ 4:e2584, https://doi.org/10.7717/peerj.2584
''',encoding='utf-8')
    print(destination)
    return destination


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,default=ROOT/'packs'/('vsearch-'+VERSION))
    build(parser.parse_args().output.resolve())
