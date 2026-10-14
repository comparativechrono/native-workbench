#!/usr/bin/env python3
"""Prepare the independent Prodigal 1.0.0 pack from a recorded native build."""
import argparse, importlib.util, json, shutil, sys
from pathlib import Path
from build_prodigal_native import ROOT, VERSION, SOURCE_COMMIT, SOURCE_NAME, SOURCE_SHA256, TC_NAME, sha
sys.path.insert(0,str(ROOT/'desktop'))
from prepare_modular_packs import field, artifact, execute, workflow
_spec=importlib.util.spec_from_file_location('prodigal_fixtures',ROOT/'tools/prodigal/fixtures.py')
_fixture_module=importlib.util.module_from_spec(_spec);_spec.loader.exec_module(_fixture_module)
fixtures=_fixture_module.fixtures
PACK_VERSION='1.0.0'
CITATION={'text':'Hyatt D et al. (2010). Prodigal: prokaryotic gene recognition and translation initiation site identification. BMC Bioinformatics 11:119.','url':'https://doi.org/10.1186/1471-2105-11-119'}
def dump(path,value): path.write_text(json.dumps(value,indent=2)+'\n',encoding='utf-8')
def definitions():
    workflows=[]; schemas={}
    for mode,label in [('single','genome'),('meta','metagenome')]:
        identity='predict-'+label
        inputs=[field('sequence','Prokaryotic assembly FASTA',filter='Uncompressed DNA FASTA|*.fa;*.fna;*.fasta|All files|*.*',help='Unaligned A/C/G/T/N DNA only; no gzip, reads or proteins. Unique ASCII first-word IDs. Single genome needs at least 20,000 resolved bases; upstream recommends 100,000. See pack guide for explicit size and header limits.')]
        if mode=='single': inputs += [field('genetic-code','Genetic code (required)','choice',choices='11:11 - Bacterial, archaeal and plastid|4:4 - Mycoplasma/Spiroplasma (TGA is W)|25:25 - Candidate Division SR1 (TGA is G)',help='Select from organism biology; code is not inferred. Other translation tables are outside this initial pack.'),field('start-model','Translation initiation model','choice',default='auto',choices='auto:Learn automatically|nonsd:Force non-Shine-Dalgarno model',help='Automatic training learns from this assembly. Force non-SD only when scientifically appropriate (-n). No saved external training model is used.')]
        inputs += [field('closed-ends','Require complete genes at contig ends','boolean',default='false',help='False permits partial genes at contig boundaries. True passes upstream -c and excludes genes that run off either edge; this does not circularize chromosomes.'),field('mask-n','Prevent genes crossing long N gaps','boolean',default='true',help='Pass upstream -m to mask runs of unknown N bases. The original upstream masking behavior is preserved, including its handling of terminal N runs.')]
        outputs=[artifact('annotations','Predicted gene annotations (GFF3)','genes.gff'),artifact('proteins','Predicted proteins (FASTA)','proteins.faa',nonempty=False),artifact('cds','Predicted coding DNA (FASTA)','coding-sequences.fna',nonempty=False),artifact('summary','Recorded prediction summary','prediction-summary.json')]
        args=['bundled',mode,'{input:sequence}','{output:annotations}','{output:proteins}','{output:cds}','{input:genetic-code}' if mode=='single' else 'auto','{input:start-model}' if mode=='single' else 'auto','{input:closed-ends}','{input:mask-n}','report-v1']
        explanation='Train on this prokaryotic genome, then predict genes with the selected genetic code.' if mode=='single' else 'Predict genes in short or mixed prokaryotic contigs using upstream preset metagenomic models. Prodigal selects each sequence model and its genetic code; GFF records those choices.'
        workflows.append(workflow(identity,'Prodigal gene prediction - '+label,explanation+' Outputs predictions, not experimentally confirmed functions.',inputs,outputs,[execute('version','Record scientific executable version','prodigal',['-v']),execute('predict','Validate DNA and predict prokaryotic genes','prodigal-adapter',args,stdout='summary',produces=['annotations','proteins','cds'])]))
        types={'annotations':'text','proteins':'fasta-protein','cds':'fasta-nucleotide','summary':'metrics'}
        schemas[identity]={'ports':[dict(id='sequence',label='Prokaryotic DNA FASTA',type='fasta-nucleotide',accepts=['fasta-nucleotide','reference'],manifestInputs=['sequence'],min=1,max=1,requiredState={'compression':'none'})],'outputs':[dict(id=o['id'],label=o['label'],type=types[o['id']],manifestOutputs=[o['id']],**({'state':{'compression':'none'}} if o['id'] in ('proteins','cds') else {})) for o in outputs],'pathPolicy':{'asciiOnly':True},'methods':'Prokaryotic coding sequences were predicted with Prodigal '+VERSION+' (upstream 2.6.3, commit '+SOURCE_COMMIT+'). '+explanation+' Contig-edge completion and N-gap masking settings were recorded. Genome mode exposes translation tables 11, 4 and 25 and automatic or forced non-SD training. The native Workbench launcher checks FASTA identity and bounded input contracts without changing sequence or gene predictions. GFF coordinates are 1-based inclusive; CDS FASTA is in coding orientation, and upstream protein terminal stop symbols are retained. Legitimate zero-gene outcomes retain empty sequence outputs. These measurements do not establish biological accuracy or QC pass thresholds.'}
    return workflows,{'schema':1,'category':'Gene prediction','citations':[CITATION],'workflows':schemas}
def checks(truth):
    values=[]
    for mode in ('genome','metagenome'):
        selected=truth['planted'] if mode=='genome' else [x for x in truth['planted'] if 'meta' in x]
        proteins={};cds={};rows=[]
        for i,item in enumerate(selected):
            contig='synthetic_genome' if mode=='genome' else item['meta']['contig'];ordinal=i+1 if mode=='genome' else 1
            proteins[contig+'_'+str(ordinal)]=item['protein'];cds[contig+'_'+str(ordinal)]=item['cds']
            loc=item if mode=='genome' else item['meta']
            rows.append(contig+'\tProdigal_v'+VERSION+'\tCDS\t'+str(loc['start'])+'\t'+str(loc['end'])+'\t')
        params={'closed-ends':False,'mask-n':True}
        if mode=='genome':params.update({'genetic-code':'11','start-model':'auto'})
        values.append({'id':mode+'-known-genes','workflow':'predict-'+mode,'params':params,'inputs':{'sequence':[{'sequence':'fixture-'+mode}]},'expect':[{'output':'annotations','kind':'text','contains':['##gff-version',*rows]},{'output':'proteins','kind':'fasta','records':len(proteins),'sequences':proteins},{'output':'cds','kind':'fasta','records':len(cds),'sequences':cds},{'output':'summary','kind':'text','contains':['"predictedGenes":'+str(len(cds))+',']}]})
    values.append({'id':'metagenome-zero-genes','workflow':'predict-metagenome','params':{'closed-ends':True,'mask-n':True},'inputs':{'sequence':[{'sequence':'fixture-no-genes'}]},'expect':[{'output':'annotations','kind':'text','contains':['##gff-version']},{'output':'proteins','kind':'fasta','records':0,'sequences':{}},{'output':'cds','kind':'fasta','records':0,'sequences':{}},{'output':'summary','kind':'text','contains':['"predictedGenes":0,']}]})
    return {'schema':1,'checks':values}
def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--cache',type=Path,default=ROOT/'build/prodigal');p.add_argument('--destination',type=Path,default=ROOT/'packs/prodigal-1.0.0');p.add_argument('--toolchain',type=Path,default=ROOT/'build/toolchains'/TC_NAME);a=p.parse_args()
    cache=a.cache.resolve();dest=a.destination.resolve();tc=a.toolchain.resolve();build=json.loads((cache/'build-windows/build.json').read_text())
    if build.get('builderSha256')!=sha(ROOT/'scripts/build_prodigal_native.py') or build['version']!=VERSION or build['sourceCommit']!=SOURCE_COMMIT or build['guardSourceSha256']!=sha(ROOT/'tools/prodigal/guard.cpp') or build['patchSha256']!=sha(cache/'workbench1.patch') or sha(cache/SOURCE_NAME)!=SOURCE_SHA256:raise ValueError('Build/source identity mismatch')
    if dest.exists() and any(dest.iterdir()):raise ValueError('Destination must be new/empty')
    for folder in ('bin','fixtures','licenses'):(dest/folder).mkdir(parents=True,exist_ok=True)
    sections=[]
    def section(name,values):sections.append('['+name+']\n'+'\n'.join(k+'='+str(v) for k,v in values.items() if k!='id' or name=='pack')+'\n')
    section('pack',dict(format=2,id='prodigal',version=PACK_VERSION,name='Prodigal prokaryotic genes',platform='windows-x86_64',description='Predict coding genes, proteins and coding DNA in prokaryotic genomes or metagenomic contigs. Native optional pack; no external runtime.',color='#447A58'))
    for name in ('prodigal','prodigal-guard'):
        source=cache/'build-windows'/(name+'.exe')
        if sha(source)!=build['files'][source.name]['sha256']:raise ValueError('Changed executable: '+name)
        shutil.copy2(source,dest/'bin'/source.name);section('tool:'+('prodigal-adapter' if name=='prodigal-guard' else name),dict(path='bin/'+source.name,version=VERSION if name=='prodigal' else PACK_VERSION,sha256=sha(source)))
    truth=fixtures(dest/'fixtures');workflows,schema=definitions();dump(dest/'workbench-schema.json',schema);dump(dest/'workbench-checks.json',checks(truth))
    assets={'workbench-schema':'workbench-schema.json','workbench-checks':'workbench-checks.json','fixture-truth':'fixtures/truth.json'}
    assets.update({'fixture-'+name:'fixtures/'+name+'.fna' for name in ('genome','metagenome','no-genes','alternative-codes')})
    for name,path in assets.items():section('asset:'+name,dict(path=path,sha256=sha(dest/path)))
    for wf in workflows:
        section('workflow:'+wf['id'],dict(name=wf['name'],description=wf['description'],inputs=','.join(x['id'] for x in wf['inputs']),outputs=','.join(x['id'] for x in wf['outputs']),steps=','.join(x['id'] for x in wf['steps'])))
        for kind in ('input','output','step'):
            for item in wf[kind+'s']:section(kind+':'+wf['id']+':'+item['id'],item)
    (dest/'pack.ini').write_text('\n'.join(sections),encoding='utf-8');lic=dest/'licenses'
    for source,name in [(cache/SOURCE_NAME,SOURCE_NAME),(cache/'workbench1.patch','workbench1.patch'),(cache/'source-workbench/LICENSE','Prodigal-GPL-3.0.txt'),(tc/'LICENSE.TXT','LLVM-LICENSE.txt'),(ROOT/'LICENSE','Workbench-MIT.txt'),(ROOT/'tools/prodigal/guard.cpp','guard.cpp'),(ROOT/'tools/prodigal/fixtures.py','fixtures.py'),(ROOT/'scripts/build_prodigal_native.py','build_prodigal_native.py'),(ROOT/'scripts/prepare_prodigal_pack.py','prepare_prodigal_pack.py')]:shutil.copy2(source,lic/name)
    notices=list((tc/'x86_64-w64-mingw32/share/mingw32').glob('COPYING*'))
    if not notices:raise ValueError('MinGW runtime license notices are required')
    for source in notices:shutil.copy2(source,lic/source.name)
    dump(lic/'provenance.json',build)
    (lic/'MODIFICATIONS.txt').write_text('Prodigal 2.6.3 is built from the immutable pinned source. Workbench fixes fourteen overlapping sprintf metadata appends by writing at the existing string terminator and labels its version 2.6.3-workbench1. Prediction, training, translation and scoring algorithms are unchanged. The complete GPL source archive, exact patch, build recipe and separate MIT guard/fixture sources are retained. Build provenance is not native execution evidence.\n')
    shutil.copy2(ROOT/'docs/PRODIGAL-PACK.md',dest/'PACK-README.md')
    sys.path.insert(0,str(ROOT/'workspace'));from catalog import load_pack
    pack=load_pack(dest/'pack.ini');print(json.dumps({'pack':str(dest),'manifestSha256':sha(dest/'pack.ini'),'workflows':list(pack['workflows'])},indent=2))
if __name__=='__main__':main()
