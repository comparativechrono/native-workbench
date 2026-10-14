#!/usr/bin/env python3
"""Prepare an independently installable local Bracken 3.1 abundance pack."""
import argparse
import json
from pathlib import Path
import shutil
import sys
import tarfile
import zipfile

from fetch_bracken_build_inputs import ROOT, LOCK, CACHE, obtain, sha
sys.path.insert(0, str(ROOT / 'desktop'))
from prepare_modular_packs import field, number, artifact, execute, workflow

PACK_VERSION = '1.0.0'
VERSION = '3.1'
CITATIONS = [
    {'text': 'Lu J, Breitwieser FP, Thielen P, Salzberg SL (2017). Bracken: estimating species abundance in metagenomics data. PeerJ Computer Science 3:e104.', 'url': 'https://doi.org/10.7717/peerj-cs.104'},
    {'text': 'Lu J et al. (2022). Metagenome analysis using the Kraken software suite. Nature Protocols 17:2815–2839.', 'url': 'https://doi.org/10.1038/s41596-022-00738-y'}]


def dump(path, value):
    with Path(path).open('w', encoding='utf-8', newline='\n') as stream:
        stream.write(json.dumps(value, indent=2, ensure_ascii=True) + '\n')


def definitions():
    workflows, metadata = [], {}
    for external in (False, True):
        identity = 'estimate-external' if external else 'estimate'
        if external:
            inputs = [
                field('report', 'Original six-column Kraken2 report', filter='Kraken report|*.tsv;*.txt;*.report|All files|*.*', help='Unmodified standard report from Kraken2 using confidence 0, minimum hit groups 2, minimum base quality 0 and no quick mode. MPA and minimizer-augmented reports are rejected.'),
                field('distribution', 'Matching local Bracken read-length distribution', filter='Bracken distribution|*.kmer_distrib;*.txt|All files|*.*', help='Select the distribution built for exactly the same Kraken database and declared read length. No Kraken database binary or installed Kraken pack is needed for this operation.'),
                field('database-label', 'Database name', 'text', help='Identify the exact external database used to classify this sample.'),
                field('database-release', 'Database release or source identifier', 'text', help='Record a dated release, immutable source identifier or your local database build identifier.'),
                field('external-confirmation', 'Confirm external report and model compatibility', 'choice', choices='confirmed:I confirm the same database standard classifier settings and stated read length', help='Required declaration. The report and distribution cannot themselves prove their database association, read length, or classifier settings; results explicitly retain user-declared provenance.'),
                field('external-unit', 'What the report counts', 'choice', default='reads', choices='reads:Single reads|fragments:Paired fragments', help='Kraken2 paired mode counts each pair once. Bracken does not double those counts.')]
            ports = [dict(id='report', label='External Kraken2 report', type='metrics', manifestInputs=['report'], min=1, max=1),
                     dict(id='distribution', label='Matching Bracken distribution', type='file', manifestInputs=['distribution'], min=1, max=1)]
            arguments = ['--report', '{input:report}', '--distribution', '{input:distribution}', '--database-label', '{input:database-label}', '--database-release', '{input:database-release}', '--external-confirmation', '{input:external-confirmation}', '--external-unit', '{input:external-unit}']
        else:
            inputs = [
                field('classification', 'Kraken2 classification record', filter='Kraken2 classification JSON|*.json', help='Connect the classification record produced by the Kraken2 pack, or select its saved JSON beside the original report. Report hash, database fingerprint and observed read lengths are checked.'),
                field('database', 'Matching local Kraken2 database resource', filter='Kraken2 database JSON|*.json', help='Registered descriptor with the matching Bracken read-length distribution. Bracken verifies the selected distribution and report, without rereading unused large Kraken index files.'),
                field('length-policy', 'Read-length model', 'choice', default='exact', choices='exact:Require all reads and mates to match exactly|representative:Use an explicitly chosen representative length', help='Exact is safest. For variable trimmed reads, representative length is an explicit approximation and must fall within observed lengths; no automatic averaging or nearest distribution selection.')]
            ports = [dict(id='classification', label='Kraken2 classification record', type='file', manifestInputs=['classification'], min=1, max=1),
                     dict(id='database', label='Local database resource', type='file', manifestInputs=['database'], min=1, max=1)]
            arguments = ['--classification', '{input:classification}', '--database', '{input:database}', '--length-policy', '{input:length-policy}']
        inputs += [number('read-length', 'Distribution read length (bases)', 150, 1, 10000000, help='Choose a distribution generated for this exact length. In paired mode this is the mate read length, not the combined insert or sum of mates.'),
                   field('level', 'Abundance rank', 'choice', default='S', choices='S:Species|G:Genus|F:Family|O:Order|C:Class|P:Phylum|D:Domain', help='Bracken reallocates ambiguous classifications to the selected rank; species absence does not prove organism absence.'),
                   number('threshold', 'Minimum Kraken clade count', 10, 0, 2147483647, help='Upstream threshold on original observations at/below the selected rank. For paired mode the count is fragments. Excluded and unclassified observations do not enter the abundance fraction denominator.')]
        outputs = [artifact('abundance', 'Bracken abundance table', 'bracken.abundance.tsv'),
                   artifact('report', 'Bracken reestimated taxonomy report', 'bracken.report.tsv'),
                   artifact('provenance', 'Database and report provenance', 'bracken-provenance.json'),
                   artifact('methods', 'Completed Bracken methods', 'bracken-methods.txt'),
                   artifact('log', 'Upstream Bracken execution log', 'bracken-upstream.log')]
        steps = [execute('estimate', 'Estimate abundance with upstream Bracken', 'python',
                         ['-I', '-B', '-X', 'utf8', '{asset:adapter}', '--mode', identity, '--run', '{run}', *arguments,
                          '--read-length', '{input:read-length}', '--level', '{input:level}', '--threshold', '{input:threshold}'],
                         produces=[value['id'] for value in outputs])]
        workflows.append(workflow(identity, 'Bracken: external Kraken report' if external else 'Bracken: reestimate Kraken2 abundance',
            'Estimate taxonomic read or fragment abundance from a standard Kraken2 report using its database-specific Bracken distribution. All analysis stays local.', inputs, outputs, steps))
        metadata[identity] = {'ports': ports, 'outputs': [dict(id=value['id'], label=value['label'], type='text' if value['id'] in ('methods', 'log') else 'metrics', manifestOutputs=[value['id']]) for value in outputs],
            'methods': 'Taxonomic abundance will be estimated with the unchanged Bracken 3.1 upstream Python estimator, using a separately selected local distribution for the stated database and read length, taxonomic rank and original Kraken clade-count threshold. ' +
                ('The external database association, classifier settings, read length and read-versus-fragment units are explicitly user-declared and cannot be verified from the report alone. Report and distribution hashes will be recorded. ' if external else 'The Kraken2 classification record binds the report hash, database fingerprint, observation units and actual read lengths. The selected distribution hash and registered association are verified; external model association remains a user declaration, not proof of the training database. Exact fixed read length is default; explicitly selected representative length is a documented approximation for variable reads. ') +
                'Only standard Kraken2 settings (confidence 0, minimum hit groups 2, minimum base quality 0, no quick mode) are supported. Paired report counts remain fragments. Upstream Bayesian reestimation, integer truncation and report output are retained. Fractions use Bracken retained estimated abundance, excluding unclassified and unallocated observations, and do not estimate organism cell abundance. Methods, source hashes and input identities accompany the result.'}
    return workflows, {'schema': 1, 'category': 'Metagenomics', 'citations': CITATIONS, 'workflows': metadata}


def checks():
    result = []
    for identity, level, threshold, expected in [
        ('external-species', 'S', 0, ['Synthetic alpha\t101\tS\t30\t7\t37\t0.41111', 'Synthetic beta\t102\tS\t20\t12\t32\t0.35556', 'Synthetic gamma\t201\tS\t20\t0\t20\t0.22222']),
        ('external-genus', 'G', 0, ['Synthetic genus\t10\tG\t70\t0\t70\t0.77778', 'Second genus\t20\tG\t20\t0\t20\t0.22222']),
        ('external-threshold', 'S', 25, ['Synthetic alpha\t101\tS\t30\t20\t50\t1.00000'])]:
        result.append({'id': identity, 'workflow': 'estimate-external', 'inputs': {'report':[{'report':'fixture-manual-report'}], 'distribution':[{'distribution':'fixture-manual-distribution'}]},
            'params': {'database-label':'Synthetic probability fixture', 'database-release':'hand-calculated-2026-10-04', 'external-confirmation':'confirmed', 'external-unit':'reads', 'read-length':150, 'level':level, 'threshold':threshold},
            'expect': [{'output':'abundance','kind':'text','contains':expected}, {'output':'provenance','kind':'text','contains':['"identityScope": "user-declared-external-report-unverified"', '"inputsUnchanged": true', '"totalInputObservations": 100', '"unclassifiedInputObservations": 10']} ]})
    result.append({'id':'kraken-record-species','workflow':'estimate','inputs':{'classification':[{'classification':'fixture-classification'}],'database':[{'database':'fixture-database'}]},
        'params':{'read-length':150,'level':'S','threshold':0,'length-policy':'exact'},
        'expect':[{'output':'abundance','kind':'text','contains':['Synthetic alpha\t101\tS\t12\t2\t14\t0.48276','Synthetic beta\t102\tS\t8\t1\t9\t0.31034','Synthetic gamma\t201\tS\t5\t0\t5\t0.17241']},
            {'output':'provenance','kind':'text','contains':['"identityScope": "hash-bound-workbench-classification"','"unclassifiedInputObservations": 3','"sumOfTruncatedEstimatedCounts": 28']} ]})
    return {'schema':1,'checks':result}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cache', type=Path, default=CACHE)
    parser.add_argument('--destination', type=Path, default=ROOT / 'packs/bracken-1.0.0')
    parser.add_argument('--fetch', action='store_true')
    args = parser.parse_args()
    destination = args.destination.resolve()
    if destination.exists() and any(destination.iterdir()):
        raise ValueError('Pack destination must be new or empty')
    lock = json.loads(LOCK.read_text(encoding='utf-8'))
    for pin in [lock['upstreamSource'], *lock['python']]:
        obtain(pin, args.cache / pin['filename'], args.fetch)
    for sub in ['bin', 'upstream', 'licenses', 'fixtures']:
        (destination / sub).mkdir(parents=True, exist_ok=True)
    python_pin = next(pin for pin in lock['python'] if pin['filename'].endswith('.zip'))
    with zipfile.ZipFile(args.cache / python_pin['filename']) as archive:
        archive.extractall(destination / 'bin')
    (destination / 'bin/pythonw.exe').unlink(missing_ok=True)
    (destination / 'bin/python313._pth').write_bytes(b'python313.zip\n.\n')
    with tarfile.open(args.cache / lock['upstreamSource']['filename']) as archive:
        data = archive.extractfile(lock['estimator']['archivePath']).read()
        (destination / 'upstream/est_abundance.py').write_bytes(data)
        (destination / 'licenses/Bracken-GPL-3.0.txt').write_bytes(archive.extractfile('Bracken-3.1/LICENSE').read())
    if sha(destination / 'upstream/est_abundance.py') != lock['estimator']['sha256']:
        raise ValueError('Estimator bytes differ from pinned upstream source')
    for source, name in [(ROOT/'tools/bracken/adapter.py','adapter.py'), (ROOT/'tools/metagenomics/resources.py','resources.py')]:
        shutil.copyfile(source, destination / name)
        shutil.copyfile(source, destination / 'licenses' / name)
    shutil.copytree(ROOT/'tools/bracken/fixtures', destination/'fixtures', dirs_exist_ok=True)
    for source in [LOCK, ROOT/'tools/bracken/build_fixture.py', ROOT/'scripts/fetch_bracken_build_inputs.py', Path(__file__)]:
        shutil.copyfile(source, destination/'licenses'/source.name)
    for pin in [lock['upstreamSource'], next(pin for pin in lock['python'] if pin['filename'].endswith('.xz'))]:
        shutil.copyfile(args.cache/pin['filename'], destination/'licenses'/pin['filename'])
    shutil.copyfile(ROOT/'LICENSE',destination/'licenses/Workbench-MIT.txt')
    shutil.copyfile(ROOT/'docs/BRACKEN-PACK.md',destination/'PACK-README.md')
    (destination/'licenses/NOTICE.txt').write_text('Bracken 3.1 est_abundance.py is unchanged GPL-3.0-or-later upstream source. Complete pinned Bracken source and GPL text are included. The independent Workbench adapter and resource helper are MIT. Private Python 3.13.16 is the official Windows embeddable distribution; its unchanged LICENSE.txt and complete CPython source archive retain PSF and bundled component notices. No C++ Bracken database builder, POSIX shell, system Python, pip, or external Python packages are used. Large classification/model databases are separate local resources.\n',encoding='utf-8')
    dump(destination/'licenses/provenance.json',{'schema':1,'pack':'bracken','packVersion':PACK_VERSION,'upstreamVersion':VERSION,'sourceLockSha256':sha(LOCK),'upstreamEstimatorSha256':lock['estimator']['sha256'],'pythonVersion':lock['pythonVersion'],'windowsExecuted':False,'scientificAlgorithmModified':False,'scope':'Estimate abundance using unchanged upstream Python estimator; no bundled general database-build operation.','runtime':'Official isolated private Windows CPython. No global Python, install script, network request or system configuration during analysis.','fixture':'Manual probability truth and exhaustive actual Kraken2 classification over every synthetic-genome150-base window; see fixture records.','adaptations':['Shell launcher replaced by shell-free argument array invoking the unchanged estimator.','Explicit output report prevents upstream default output beside the input.','Strict provenance, input format and unchanged-input checks precede/follow the estimator.','No-estimable-taxa inputs fail clearly, preserving upstream no-estimate semantics.']})
    workflows,schema=definitions()
    dump(destination/'workbench-schema.json',schema);dump(destination/'workbench-checks.json',checks())
    sections=[]
    def section(name,values):
        sections.append('['+name+']\n'+'\n'.join(key+'='+str(value) for key,value in values.items() if key!='id' or name=='pack')+'\n')
    section('pack',{'format':2,'id':'bracken','version':PACK_VERSION,'name':'Bracken metagenomic abundance','platform':'windows-x86_64','description':'Database-bound Kraken2 abundance reestimation and explicitly declared external reports. Workbench0.6.0 or newer.','color':'#597B78'})
    section('tool:python',{'path':'bin/python.exe','version':lock['pythonVersion'],'sha256':sha(destination/'bin/python.exe')})
    explicit={'adapter':'adapter.py','workbench-schema':'workbench-schema.json','workbench-checks':'workbench-checks.json','fixture-manual-report':'fixtures/manual.report.tsv','fixture-manual-distribution':'fixtures/manual150mers.kmer_distrib','fixture-classification':'fixtures/classification.json','fixture-database':'fixtures/database.json'}
    used={'bin/python.exe'}
    for identity,path in explicit.items():
        section('asset:'+identity,{'path':path,'sha256':sha(destination/path)});used.add(path)
    for index,path in enumerate(sorted(destination.rglob('*'))):
        relative=path.relative_to(destination).as_posix()
        if path.is_file() and relative not in used and not relative.startswith('licenses/') and relative!='PACK-README.md':
            section('asset:runtime-'+str(index),{'path':relative,'sha256':sha(path)})
    for wf in workflows:
        section('workflow:'+wf['id'],{'name':wf['name'],'description':wf['description'],'inputs':','.join(v['id'] for v in wf['inputs']),'outputs':','.join(v['id'] for v in wf['outputs']),'steps':','.join(v['id'] for v in wf['steps'])})
        for kind in ('input','output','step'):
            for item in wf[kind+'s']:
                section(kind+':'+wf['id']+':'+item['id'],item)
    (destination/'pack.ini').write_text('\n'.join(sections),encoding='utf-8')
    sys.path.insert(0,str(ROOT/'workspace'))
    from catalog import load_pack
    pack=load_pack(destination/'pack.ini')
    print(json.dumps({'pack':str(destination),'manifestSha256':sha(destination/'pack.ini'),'workflows':list(pack['workflows']),'checks':len(checks()['checks']),'filesAndFolders':len(list(destination.rglob('*'))),'bytes':sum(p.stat().st_size for p in destination.rglob('*') if p.is_file())},indent=2))


if __name__=='__main__':
    main()
