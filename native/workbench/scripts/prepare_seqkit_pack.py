#!/usr/bin/env python3
"""Build the SeqKit 2.14.0 native Windows pack from verified upstream artifacts."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'desktop'))
from prepare_modular_packs import field, number, artifact, execute, workflow

PACK_VERSION = '0.5.2'
TOOL_VERSION = '2.14.0'
WINDOWS_SHA256 = 'fe776820ff4f924844753b3b251966a7c8fd0b07d77c69f03caf59828ab077a1'
LINUX_SHA256 = '88aa8a539b1e9097220a47811367b7ef826eff8637e5284fdd32a372770d6f7d'
GALAXY_COMMIT = '5a09e4ee5fd1f9035706cd975e602e9a9de2d401'
KINDS = {
    'reads': ('FASTQ reads', 'reads', 'fastq', 'dna', 'FASTQ reads|*.fastq;*.fq;*.fastq.gz;*.fq.gz|All files|*.*'),
    'nucleotide': ('nucleotide FASTA', 'fasta-nucleotide', 'fasta', 'auto', 'Nucleotide FASTA|*.fa;*.fasta;*.fna;*.fa.gz;*.fasta.gz;*.fna.gz|All files|*.*'),
    'protein': ('protein FASTA', 'fasta-protein', 'faa', 'protein', 'Protein FASTA|*.faa;*.fa;*.fasta;*.faa.gz;*.fa.gz;*.fasta.gz|All files|*.*'),
}
SINGLE = 'This operation treats one file independently and does not preserve paired-end read synchronization.'


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def definitions():
    workflows, schemas = [], {}
    def add(identity, title, description, kind, command, params=(), output_type=None, ids=False, metrics=False, nonempty=True, methods=None):
        label, data_type, extension, alphabet, picker = KINDS[kind]
        output_type = output_type or data_type
        if output_type == 'fasta-protein':
            extension = 'faa'
        elif output_type == 'fasta-nucleotide':
            extension = 'fasta'
        input_fields = [field('sequences', label.capitalize(), filter=picker,
                              help=('Plain or gzip-compressed input. ' + (SINGLE if kind == 'reads' and not metrics else 'Sequence IDs are the first whitespace-delimited header token.')))]
        ports = [dict(id='sequences', type=data_type, accepts=[data_type] + (['reference'] if kind == 'nucleotide' else []), manifestInputs=['sequences'], min=1, max=1)]
        if ids:
            input_fields.append(field('ids', 'Sequence IDs', filter='ID list|*.txt;*.tsv|All files|*.*',
                                      help='One exact sequence ID per line; no header, descriptions, regular expressions or wildcards.'))
            ports.append(dict(id='ids', type='id-list', manifestInputs=['ids'], min=1, max=1))
        input_fields += list(params)
        input_fields.append(number('threads', 'Threads', 2, 1, 64, help='SeqKit worker limit; most operations are limited by file reading and writing.'))
        output_id = 'statistics' if metrics else 'result'
        outputs = [artifact(output_id, title + ' output', 'statistics.tsv' if metrics else 'result.' + extension, nonempty=nonempty)]
        args = list(command) + ['--threads', '{input:threads}', '--seq-type', alphabet, '--', '{input:sequences}']
        steps = [execute('run', title, 'seqkit', args, stdout=output_id)]
        output_schema = [dict(id=output_id, type='metrics' if metrics else output_type,
                             manifestOutputs=[output_id], state={'compression': 'none'})]
        if identity in ('statistics-reads', 'sample-reads'):
            # Upstream stats/sample2 can print an error and still exit zero on
            # malformed FASTQ. The strict streaming seq command must succeed
            # before either command runs. IDs are much smaller than a read copy.
            outputs.insert(0, artifact('validated-ids', 'Validated read identifiers', 'validated-read-ids.txt', final=False))
            output_schema.append(dict(id='validated-ids',type='id-list',manifestOutputs=['validated-ids'],state={}))
            steps.insert(0,execute('validate','Validate every FASTQ record','seqkit',
                                  ['seq','--validate-seq','--name','--only-id','--seq-type','dna','--threads','{input:threads}','--','{input:sequences}'],stdout='validated-ids'))
            methods = 'FASTQ records were validated with SeqKit seq before analysis. ' + (methods or description)
        workflows.append(workflow(identity, title, description, input_fields, outputs, steps))
        schemas[identity] = dict(ports=ports, outputs=output_schema, methods=methods or description)

    for kind in KINDS:
        label = KINDS[kind][0]
        add('statistics-' + kind, 'Statistics: ' + label,
            'Summarize record counts, lengths, quartiles and N50 in a tab-separated report. FASTQ quality statistics assume Phred+33.', kind,
            ['stats', '--all', '--tabular', '--fq-encoding', 'sanger'], metrics=True,
            methods='Sequence statistics were calculated with SeqKit stats using all-statistics tabular output; FASTQ quality encoding was Phred+33.')
        add('filter-' + kind, 'Length filter: ' + label,
            'Retain records within inclusive length limits; sequence order and FASTQ qualities are preserved. ' + (SINGLE if kind == 'reads' else 'Length counts residues, including ambiguous bases.'), kind,
            ['seq', '--validate-seq', '--min-len', '{input:min-length}', '--max-len', '{input:max-length}'],
            [number('min-length', 'Minimum length', 50 if kind == 'reads' else 1, 1, 1000000000),
             number('max-length', 'Maximum length', 1000000000, 1, 1000000000,
                    help='Inclusive upper limit; must be at least the minimum length.')], nonempty=False,
            methods='Sequences were filtered by inclusive record length using SeqKit seq with alphabet validation.')
        add('subset-' + kind, 'Extract by ID: ' + label,
            'Retain exact IDs from a text list, in input order. Matching is case sensitive and uses the first header token. Missing IDs are omitted; zero matches produce an empty output. ' + (SINGLE if kind == 'reads' else ''), kind,
            ['grep', '--pattern-file', '{input:ids}'], ids=True, nonempty=False,
            methods='Sequences were selected by exact, case-sensitive sequence identifier with SeqKit grep, retaining input order.')
    for kind in ('reads', 'nucleotide'):
        add('sample-' + kind, 'Random sample: ' + KINDS[kind][0],
            'Select exactly the requested count, or all records if fewer are available. Two-pass sampling bounds memory by selected indices. Same input and seed give the same selection. ' + (SINGLE if kind == 'reads' else ''), kind,
            ['sample2', '--number', '{input:count}', '--two-pass', '--rand-seed', '{input:seed}'],
            [number('count', 'Number of records', 1000, 1, 1000000000), number('seed', 'Random seed', 11, 0, 2147483647)],
            methods='A deterministic fixed-size subset was selected using SeqKit sample2 with two passes and an explicit random seed; the selected count was capped at the available records.')
    add('fastq-to-fasta', 'FASTQ to nucleotide FASTA',
        'Convert reads to FASTA, preserving sequence headers and bases. Quality scores are discarded; this output cannot be used as FASTQ reads.', 'reads',
        ['fq2fa'], output_type='fasta-nucleotide',
        methods='FASTQ records were converted to nucleotide FASTA using SeqKit fq2fa, discarding per-base quality scores.')
    add('reverse-complement', 'Reverse complement DNA FASTA',
        'Reverse-complement each DNA sequence. IUPAC ambiguous DNA bases are supported. Input must be DNA, not protein or RNA.', 'nucleotide',
        ['seq', '--reverse', '--complement', '--validate-seq'],
        methods='DNA FASTA sequences were reverse complemented with SeqKit seq using explicit DNA alphabet validation.')
    # Override auto-detection for an operation that must reject RNA and proteins.
    rc = workflows[-1]['steps'][0]
    rc[next(k for k,v in rc.items() if k.startswith('arg.') and v == 'auto')] = 'dna'
    add('translate', 'Translate nucleotide FASTA',
        'Translate one chosen reading frame using the selected genetic code. Stop symbols are retained and the frame is appended to IDs. This is translation, not gene prediction or ORF selection; trailing incomplete codons are omitted.', 'nucleotide',
        ['translate', '--frame', '{input:frame}', '--transl-table', '{input:code}', '--append-frame'],
        [field('frame', 'Reading frame', 'choice', default='1', choices='1:Forward 1|2:Forward 2|3:Forward 3|-1:Reverse 1|-2:Reverse 2|-3:Reverse 3'),
         field('code', 'Genetic code', 'choice', default='1', choices='1:Standard (1)|2:Vertebrate mitochondrial (2)|3:Yeast mitochondrial (3)|4:Mold mitochondrial and Mycoplasma (4)|5:Invertebrate mitochondrial (5)|6:Ciliate nuclear (6)|9:Echinoderm mitochondrial (9)|10:Euplotid nuclear (10)|11:Bacterial archaeal and plastid (11)|12:Alternative yeast nuclear (12)',
               help='Choose from sample biology; it is not inferred. Stop codons remain as *. Alternative start codons are not forced to methionine.')],
        output_type='fasta-protein',
        methods='Nucleotide FASTA sequences were translated with SeqKit translate using the specified reading frame and genetic code, retaining stop codons and appending frame identifiers.')
    return workflows, dict(schema=1, category='Sequence utilities',
        citations=[dict(text='Shen W, Sipos B, Zhao L. SeqKit2: A Swiss Army Knife for Sequence and Alignment Processing. iMeta (2024), e191.', url='https://doi.org/10.1002/imt2.191')], workflows=schemas)


def checks():
    def case(identity, wf, asset, expect, params=None):
        return dict(id=identity, workflow=wf, params=params or {}, inputs={'sequences': [{'sequences': asset}]}, expect=[expect])
    return dict(schema=1, checks=[
        case('fastq-statistics', 'statistics-reads', 'check-reads', dict(output='statistics', kind='text', contains=['num_seqs\tsum_len', '\tFASTQ\tDNA\t2\t12\t4\t6.0\t8\t'])),
        case('quality-loss-conversion', 'fastq-to-fasta', 'check-reads', dict(output='result', kind='fasta', records=2, sequences={'r1':'ACGT','r2':'ATGGCCAA'})),
        case('translation-standard-code', 'translate', 'check-cds', dict(output='result', kind='fasta', records=1, sequences={'cds1_frame=1':'MAIVMGR*KGAR*'})),
        case('exact-count-sampling', 'sample-reads', 'check-reads', dict(output='result', kind='fastq', records=1), {'count':1, 'seed':11}),
    ])


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--vendor', type=Path, required=True, help='Cache populated by fetch_seqkit_vendor.py')
    p.add_argument('--destination', type=Path, default=ROOT / 'packs' / ('seqkit-' + PACK_VERSION))
    args = p.parse_args()
    vendor, destination = args.vendor.resolve(), args.destination.resolve()
    binary = vendor / 'windows/seqkit.exe'
    if digest(binary) != WINDOWS_SHA256:
        raise ValueError('Official Windows SeqKit binary hash differs')
    provenance = json.loads((vendor / 'licenses/provenance.json').read_text())
    if provenance['builds']['windows-amd64']['sha256'] != WINDOWS_SHA256:
        raise ValueError('License provenance does not describe this executable')
    for entry in [f for m in provenance['modules'] for f in m['notices']] + provenance['go']['notices']:
        if digest(vendor / 'licenses' / entry['file']) != entry['sha256']:
            raise ValueError('License notice differs: ' + entry['file'])
    if destination.exists():
        if destination.name != 'seqkit-' + PACK_VERSION or not (destination / 'pack.ini').is_file():
            raise ValueError('Refusing to replace an unrelated directory')
        shutil.rmtree(destination)
    (destination / 'bin').mkdir(parents=True)
    shutil.copy2(binary, destination / 'bin/seqkit.exe')
    shutil.copytree(vendor / 'licenses', destination / 'licenses')
    workflows, schema = definitions()
    (destination / 'workbench-schema.json').write_text(json.dumps(schema, indent=2) + '\n')
    (destination / 'workbench-checks.json').write_text(json.dumps(checks(), indent=2) + '\n')
    (destination / 'fixtures').mkdir()
    (destination / 'fixtures/reads.fastq').write_text('@r1\nACGT\n+\nIJKL\n@r2\nATGGCCAA\n+\nABCDEFGH\n')
    (destination / 'fixtures/cds.fasta').write_text('>cds1\nATGGCCATTGTAATGGGCCGCTGAAAGGGTGCCCGATAG\n')
    sections = []
    def section(name, values):
        sections.append('['+name+']\n'+'\n'.join(k+'='+str(v) for k,v in values.items() if k != 'id')+'\n')
    sections.append('[pack]\nformat=2\nid=seqkit\nversion='+PACK_VERSION+'\nname=SeqKit sequence utilities\nplatform=windows-x86_64\ndescription=Typed FASTA and FASTQ statistics, filtering, selection, conversion and translation.\ncolor=#307F78\n')
    section('tool:seqkit', dict(path='bin/seqkit.exe', version=TOOL_VERSION, sha256=WINDOWS_SHA256))
    assets = {'workbench-schema':'workbench-schema.json', 'workbench-checks':'workbench-checks.json',
              'check-reads':'fixtures/reads.fastq', 'check-cds':'fixtures/cds.fasta'}
    for identity, path in assets.items():
        section('asset:'+identity, dict(path=path, sha256=digest(destination/path)))
    for wf in workflows:
        section('workflow:'+wf['id'], dict(name=wf['name'], description=wf['description'], inputs=','.join(x['id'] for x in wf['inputs']), outputs=','.join(x['id'] for x in wf['outputs']), steps=','.join(x['id'] for x in wf['steps'])))
        for kind, plural in [('input','inputs'),('output','outputs'),('step','steps')]:
            for record in wf[plural]:
                section(f'{kind}:{wf["id"]}:{record["id"]}', record)
    (destination / 'pack.ini').write_text('\n'.join(sections), encoding='utf-8')
    (destination / 'PACK-README.txt').write_text(
        'SeqKit sequence utilities — pack '+PACK_VERSION+' / upstream '+TOOL_VERSION+'\n\n'
        'Unmodified upstream native Windows amd64 executable; no installed Go, shell, network connection or administrator rights are needed to run these workflows. The computer must allow the bundled executable.\n\n'
        'Inputs are typed separately as FASTQ reads, nucleotide FASTA and protein FASTA. Paired-end data are deliberately not offered as paired inputs. Never filter or sample the two mates independently and assume pairing is preserved. FASTQ-to-FASTA discards quality scores. Translation does not predict genes or choose a genetic code.\n\n'
        'All workflows use separate argv elements, with no shell. Outputs are created in the run folder; input files are unchanged. Empty filter/subset outputs are valid and are recorded as such. FASTQ statistics and sampling include a strict streaming validation pass and a private identifier list because upstream stats/sample2 can otherwise exit successfully after a malformed-input error.\n\n'
        'Upstream source: https://github.com/shenwei356/seqkit/tree/v2.14.0\n'
        'Documentation: https://bioinf.shenwei.me/seqkit/usage/\n'
        'Galaxy IUC reviewed wrappers: https://github.com/galaxyproject/tools-iuc/tree/'+GALAXY_COMMIT+'/tools/seqkit\n'
        'Galaxy wrappers informed workflow choices; this pack implements its own declarative argument lists and does not execute Galaxy XML or shell commands.\n\n'
        'MIT-licensed SeqKit and its statically linked dependency/runtime notices are included under licenses. provenance.json records official release SHA256, source tag, embedded Go versions/module checksums and the upstream dirty-build marker. No byte-reproducibility claim is made for upstream binaries.\n\n'
        'Validation: Linux upstream counterpart tested on exact sequence, quality, count, sampling and translation expectations. Windows PE imports were inspected. Windows execution has not been performed in this development environment; use Check installation to execute four included scientific checks on Windows.\n\n'
        + '\n'.join('- '+w['name']+': '+w['description'] for w in workflows)+'\n', encoding='utf-8')
    print(json.dumps({'pack':str(destination), 'workflows':len(workflows), 'binarySha256':WINDOWS_SHA256, 'manifestSha256':digest(destination/'pack.ini')}))


if __name__ == '__main__':
    main()
