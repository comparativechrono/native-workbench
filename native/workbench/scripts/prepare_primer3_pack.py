#!/usr/bin/env python3
"""Prepare the independent Primer3 1.0.0 native pack from exact source-bound binaries."""
import argparse
import json
from pathlib import Path
import shutil
import sys
import tarfile
from build_primer3_native import ROOT, VERSION as TOOL_VERSION, SOURCE_COMMIT, SOURCE_NAME, SOURCE_SHA256, sha
sys.path.insert(0, str(ROOT / 'desktop'))
from prepare_modular_packs import artifact, execute, field, number, workflow
VERSION = '1.0.0'
PARAMETERS = [
    ('product-min', 'Minimum product size (bp)', '100', 40, 10000, True, 'One inclusive product range; minimum must not exceed maximum or template length.'),
    ('product-max', 'Maximum product size (bp)', '300', 40, 10000, True, 'One inclusive product range; not an observed PCR product.'),
    ('pairs', 'Maximum candidate pairs', '5', 1, 20, True, 'Return up to this many ranked candidates. Zero pairs is a valid outcome.'),
    ('size-min', 'Minimum primer length (bases)', '18', 12, 36, True, 'Minimum <= optimum <= maximum. These are design constraints, not QC verdicts.'),
    ('size-opt', 'Optimum primer length (bases)', '20', 12, 36, True, 'Length preference within the selected bounds.'),
    ('size-max', 'Maximum primer length (bases)', '27', 12, 36, True, 'Upstream supports at most 36 bases for these PCR primers.'),
    ('tm-min', 'Minimum calculated Tm (C)', '57', 0, 100, False, 'Finite decimal. Minimum <= optimum <= maximum; calculated nearest-neighbor estimate, not a measured temperature.'),
    ('tm-opt', 'Optimum calculated Tm (C)', '60', 0, 100, False, 'Temperature preference under the entered chemistry settings.'),
    ('tm-max', 'Maximum calculated Tm (C)', '63', 0, 100, False, 'Maximum model estimate; this is not a guarantee of annealing or PCR success.'),
    ('salt-mono', 'Monovalent salt (mM)', '50', 0.01, 1000, False, 'Enter the monovalent cation concentration used by the thermodynamic model.'),
    ('salt-div', 'Divalent salt (mM)', '1.5', 0, 100, False, 'Enter the divalent cation concentration; upstream accounts for dNTP binding.'),
    ('dntp', 'Total dNTP concentration (mM)', '0.6', 0, 100, False, 'Total deoxyribonucleotide triphosphate concentration, not concentration of each nucleotide.'),
    ('oligo', 'Effective annealing oligo (nM)', '50', 0.01, 100000, False, 'PRIMER_DNA_CONC effective annealing oligonucleotide concentration. This empirical model input is not template DNA concentration and can differ from initial tube primer concentration.'),
]

def definitions():
    inputs = [field('template', 'Single DNA template FASTA', filter='Uncompressed FASTA|*.fa;*.fasta;*.fna|All files|*.*', help='One uncompressed, ungapped DNA sequence of 60-100000 bases, at most 2 MiB; A/C/G/T/N only. Lowercase becomes uppercase without masking. N is allowed in the template but not in selected primers. First-word ID: 1-128 ASCII letters/digits/underscore/dot/hyphen. Whole-template design: select a local target region yourself; no required target interval, exon handling, specificity database or wet-lab validation. ASCII paths; spaces supported.')]
    for identity, label, default, low, high, whole, help_text in PARAMETERS:
        inputs.append(number(identity, label, default, low, high, help=help_text) if whole else field(identity, label, 'text', default=default, help=help_text + f' Supported range {low}-{high}.'))
    outputs = [artifact('primers', 'Candidate primers and binding coordinates', 'primers.tsv'),
        artifact('boulder', 'Full Primer3 result and explanations', 'primer3-result.boulder'),
        artifact('request', 'Exact Primer3 request', 'primer3-input.boulder'),
        artifact('summary', 'Recorded design measurements', 'primer3-summary.json'),
        artifact('settings', 'Analysis settings', 'analysis-settings.json'),
        artifact('log', 'Primer3 execution log', 'primer3.log', nonempty=False)]
    steps = [execute('version', 'Record bundled Primer3 version', 'primer3', ['--about']),
        execute('design', 'Design standard PCR primer pairs', 'primer3-adapter', ['{input:template}', '{run}', *['{input:' + p[0] + '}' for p in PARAMETERS]], produces=[v['id'] for v in outputs])]
    item = workflow('design-pcr', 'Primer3: design PCR primer pairs', 'Rank standard PCR primer pairs from one local DNA template with explicit product, length, Tm and chemistry settings. Candidate design does not establish specificity or experimental success.', inputs, outputs, steps)
    schema = {'schema': 1, 'category': 'Primer design', 'citations': [{'text': 'Untergasser et al. (2012). Primer3: new capabilities and interfaces. Nucleic Acids Research 40:e115.', 'url': 'https://doi.org/10.1093/nar/gks596'}], 'workflows': {'design-pcr': {
        'ports': [{'id': 'template', 'label': 'Single DNA template', 'type': 'fasta-nucleotide', 'manifestInputs': ['template'], 'min': 1, 'max': 1, 'requiredState': {'compression': 'none'}, 'validation': {'minRecords': 1, 'maxLength': 100000, 'uniqueIds': True}}],
        'outputs': [{'id': o['id'], 'label': o['label'], 'type': 'text' if o['id'] in ('boulder','request','log') else 'metrics', 'manifestOutputs': [o['id']]} for o in outputs],
        'pathPolicy': {'asciiOnly': True},
        'methods': 'Standard PCR primer pairs were designed with unmodified Primer3 2.6.1, default parameter version 2, generic task, paired primers and no internal oligo. Explicit product-size, primer-length, calculated Tm and chemistry settings were recorded. Tm uses SantaLucia nearest-neighbor formula 1 and salt correction 1; thermodynamic oligo alignment is enabled and thermodynamic template alignment disabled. Bundled thermodynamic tables are exact source assets. Template masking and primer N acceptance are disabled. Unexposed preferences and constraints retain upstream default-version-2 values. Native validation verifies each reported primer against its template binding interval and reverse complement and verifies product size. TSV uses zero-based half-open intervals; raw Boulder retains Primer3 first-base-index 0 conventions, including the right-primer rightmost template coordinate. No specificity database, repeat library, target interval, organism identification or experimental validation was applied. Ranked pairs and calculated measurements have no invented QC pass thresholds.'}}}
    return [item], schema

def checks():
    expected = '1\tCTACTCAGGACTAGCCAAGC\tCGCCGAGCCTAGACAACGAA\t40\t60\t200\t220\t180\t'
    return {'schema': 1, 'checks': [
        {'id': 'planted-binding-sites', 'workflow': 'design-pcr', 'inputs': {'template': [{'template': 'fixture-planted'}]}, 'params': {'size-min':20,'size-opt':20,'size-max':20}, 'expect': [
            {'output': 'primers', 'kind': 'text', 'contains': [expected]},
            {'output': 'summary', 'kind': 'text', 'contains': ['"pairsReturned": 1', '"productBases": 180', '"specificityEvaluated": false']},
            {'output': 'boulder', 'kind': 'text', 'contains': ['PRIMER_LEFT_0=40,20', 'PRIMER_RIGHT_0=219,20', 'PRIMER_PAIR_0_PRODUCT_SIZE=180']}]},
        {'id': 'legitimate-no-pairs', 'workflow': 'design-pcr', 'inputs': {'template': [{'template': 'fixture-no-pairs'}]}, 'params': {}, 'expect': [
            {'output': 'summary', 'kind': 'text', 'contains': ['"pairsReturned": 0', 'No candidate pair satisfies']},
            {'output': 'boulder', 'kind': 'text', 'contains': ['PRIMER_PAIR_NUM_RETURNED=0', 'PRIMER_LEFT_EXPLAIN=']}]},
    ]}

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cache', type=Path, default=ROOT/'build/primer3-cache')
    parser.add_argument('--build', type=Path, default=ROOT/'build/primer3-windows')
    parser.add_argument('--destination', type=Path, default=ROOT/'packs/primer3-1.0.0')
    args = parser.parse_args()
    cache, build, destination = args.cache.resolve(), args.build.resolve(), args.destination.resolve()
    record = json.loads((build/'build.json').read_text())
    for key, value in {'platform':'windows-x86_64','version':TOOL_VERSION,'upstreamCommit':SOURCE_COMMIT,'guardSourceSha256':sha(ROOT/'tools/primer3/guard.cpp'),'builderSha256':sha(ROOT/'scripts/build_primer3_native.py'),'upstreamSourceUnmodified':True}.items():
        if record.get(key) != value: raise ValueError('Build/source correspondence failed: '+key)
    if sha(cache/SOURCE_NAME) != SOURCE_SHA256: raise ValueError('Changed upstream source archive')
    if destination.exists() and any(destination.iterdir()): raise ValueError('Destination must be new/empty')
    for name in ('bin','fixtures','licenses'): (destination/name).mkdir(parents=True,exist_ok=True)
    sections=[]
    def section(name, values):
        sections.append('['+name+']\n'+'\n'.join(k+'='+str(v) for k,v in values.items() if k!='id' or name=='pack')+'\n')
    section('pack',dict(format=2,id='primer3',version=VERSION,name='Primer3 PCR primer design',platform='windows-x86_64',description='Design standard PCR primer pairs from one template with explicit settings and recorded measurements.',color='#59788D'))
    for name,identity in [('primer3_core','primer3'),('primer3-guard','primer3-adapter')]:
        source=build/(name+'.exe')
        if sha(source)!=record['files'][source.name]['sha256'] or source.read_bytes()[:2]!=b'MZ':raise ValueError('Changed/non-Windows executable')
        shutil.copyfile(source,destination/'bin'/source.name)
        section('tool:'+identity,dict(path='bin/'+source.name,version=TOOL_VERSION if identity=='primer3' else VERSION,sha256=sha(source)))
    workflows,schema=definitions()
    assets={}
    for name,value in [('workbench-schema.json',schema),('workbench-checks.json',checks())]:
        (destination/name).write_text(json.dumps(value,indent=2)+'\n',encoding='utf-8');assets[name[:-5]]=name
    for source in sorted((ROOT/'tools/primer3/fixtures').iterdir()):
        if not source.is_file():raise ValueError('Fixture tree must contain files')
        relative='fixtures/'+source.name;shutil.copyfile(source,destination/relative);assets['fixture-'+source.stem]=relative
    config=build/'primer3_config'
    for i,(name,digest) in enumerate(sorted(record['configurationFiles'].items())):
        source=config/name
        if sha(source)!=digest:raise ValueError('Changed thermodynamic table: '+name)
        relative='bin/primer3_config/'+name;(destination/relative).parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(source,destination/relative);assets['thermodynamic-'+str(i)]=relative
    for name,path in assets.items():section('asset:'+name,dict(path=path,sha256=sha(destination/path)))
    for item in workflows:
        section('workflow:'+item['id'],dict(name=item['name'],description=item['description'],inputs=','.join(v['id'] for v in item['inputs']),outputs=','.join(v['id'] for v in item['outputs']),steps=','.join(v['id'] for v in item['steps'])))
        for kind in ('input','output','step'):
            for value in item[kind+'s']:section(kind+':'+item['id']+':'+value['id'],value)
    (destination/'pack.ini').write_text('\n'.join(sections),encoding='utf-8')
    licenses=destination/'licenses'
    for source in [cache/SOURCE_NAME,ROOT/'tools/primer3/guard.cpp',ROOT/'tools/primer3/fixtures.py',ROOT/'tools/primer3/record_reference.py',ROOT/'scripts/build_primer3_native.py',Path(__file__),ROOT/'LICENSE']:
        shutil.copyfile(source,licenses/('Workbench-LICENSE.txt' if source.name=='LICENSE' else source.name))
    with tarfile.open(cache/SOURCE_NAME) as source:
        for name,target in [('LICENSE','Primer3-GPL-2.0.txt'),('src/LICENSE_GPL3_for_Amplicon3','Amplicon3-GPL-3.0.txt'),('src/amplicontm.c','Amplicon3-source-notices.c')]:
            (licenses/target).write_bytes(source.extractfile('primer3-'+SOURCE_COMMIT+'/'+name).read())
    shutil.copyfile(build/'build.json',licenses/'build-provenance.json')
    for name,digest in record['compilerNotices'].items():
        if sha(build/'compiler-notices'/name)!=digest:raise ValueError('Changed compiler notice')
        shutil.copyfile(build/'compiler-notices'/name,licenses/('compiler-'+name))
    (licenses/'NOTICE.txt').write_text('Primer3 2.6.1: local native build of unmodified upstream source, not an official upstream binary.\nPrimer3 suite/libraries are GPL-2.0-or-later. Compiled Amplicon3 amplicontm.c/h (DECIPHER-derived) are GPL-3.0-or-later; both licences and original notices are retained.\nFull source archive contains all copyright and component notices. Thermodynamic configuration is copied without changes from the exact archive.\nNo source modifications. Native baseline x86-64 build uses upstream Windows OS_WIN conditionals, which omit unsupported masker. No masking operation is exposed.\nWorkbench adapter, build and preparation scripts are separate MIT code; compiler/runtime notices are retained.\n',encoding='utf-8')
    shutil.copyfile(ROOT/'docs/PRIMER3-PACK.md',destination/'PACK-README.md')
    sys.path.insert(0,str(ROOT/'workspace'))
    from catalog import load_pack
    pack=load_pack(destination/'pack.ini')
    print(json.dumps({'pack':str(destination),'manifestSha256':sha(destination/'pack.ini'),'workflows':list(pack['workflows']),'checks':len(checks()['checks'])},indent=2))

if __name__=='__main__':main()
