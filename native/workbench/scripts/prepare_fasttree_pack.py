#!/usr/bin/env python3
"""Prepare independent FastTree1.0.0 from verified native Windows build outputs."""
import argparse,json,shutil,sys
from pathlib import Path
from build_fasttree_native import ROOT,SOURCES,COMMIT,sha
sys.path.insert(0,str(ROOT/'desktop'))
from prepare_modular_packs import field,number,artifact,execute,workflow
VERSION='1.0.0'
def definitions():
    workflows=[];schema={'schema':1,'category':'Phylogenetics','citations':[{'text':'Price MN, Dehal PS, Arkin AP (2010). FastTree 2—Approximately Maximum-Likelihood Trees for Large Alignments. PLoS ONE 5:e9490.','url':'https://doi.org/10.1371/journal.pone.0009490'}],'workflows':{}}
    for datatype in ['nucleotide','protein']:
        nt=datatype=='nucleotide';identity='infer-'+datatype
        inputs=[field('alignment','Aligned '+datatype+' FASTA',filter='Aligned FASTA|*.afa;*.fa;*.fasta;*.fna;*.faa|All files|*.*',help='Aligned homologous sequences, 4–10000 taxa, 20–1000000 equal-length columns, uncompressed FASTA up to 256 MiB. Unique first-word IDs: letters, digits, underscore, dot, hyphen only; rename pipe/punctuation IDs first. ASCII paths; spaces supported. These bounds are not a RAM guarantee.'),field('model','Substitution model','choice',default='GTR' if nt else 'LG',choices='JC:Jukes-Cantor|GTR:General time reversible' if nt else 'JTT:Jones-Taylor-Thornton|LG:Le-Gascuel|WAG:Whelan-Goldman',help='Explicit fixed model; no automatic model selection. DNA U becomes T. Ambiguous DNA symbols and protein B/X/Z are missing data, not probabilistic ambiguity. Protein stops, J, U and O are rejected; check/remove biologically appropriate terminal stops before alignment.'),field('rates','Rate variation and branch lengths','choice',default='cat',choices='cat:CAT20 search and branch lengths|gamma:CAT20 search; Gamma20 length rescaling',help='Gamma20 optimizes the gamma shape and a common branch-length scale after CAT20 topology search. It does not perform a full gamma topology search.'),field('support','Branch support','choice',default='sh',choices='sh:SH-like local support (1000 resamples)|none:No branch support',help='SH-like local support values lie between 0 and 1. These are not global bootstrap percentages or posterior probabilities.'),number('seed','Random seed',42,1,2147483647,help='Recorded seed for serial, double-precision FastTree. Exact floating-point bytes can differ between platforms.')]
        outputs=[artifact('tree','Unrooted approximate-ML tree (Newick)','inferred-tree.nwk'),artifact('summary','Recorded alignment and tree measurements','alignment-summary.json'),artifact('settings','Analysis settings and taxon mapping','analysis-settings.json'),artifact('log','FastTree execution and likelihood log','fasttree.log'),artifact('model-log','FastTree models and intermediate trees','fasttree-model.log')]
        steps=[execute('version','Record bundled FastTree version','fasttree',['-help']),execute('infer','Infer unrooted '+datatype+' tree','fasttree-adapter',['{input:alignment}','{run}',datatype,'{input:model}','{input:rates}','{input:support}','{input:seed}'],produces=[x['id'] for x in outputs])]
        workflows.append(workflow(identity,'FastTree: '+datatype+' phylogeny','Infer an unrooted approximate maximum-likelihood tree from an existing homologous-sequence alignment. Serial FastTree2.2.0, fixed model and optional SH-like local support.',inputs,outputs,steps))
        schema['workflows'][identity]={'ports':[{'id':'alignment','label':'Aligned '+datatype+' sequences','type':'msa-'+datatype,'manifestInputs':['alignment'],'min':1,'max':1,'requiredState':{'compression':'none'}}],'outputs':[{'id':o['id'],'label':o['label'],'type':'file' if o['id']=='tree' else 'text' if o['id'] in ('log','model-log') else 'metrics','manifestOutputs':[o['id']]} for o in outputs],'pathPolicy':{'asciiOnly':True},'methods':'An unrooted approximate maximum-likelihood gene tree was inferred from aligned '+datatype+' sequences with unchanged FastTree2.2.0, serial double precision, baseline x86-64. The explicit fixed substitution model, random seed, CAT20 search and optional Gamma20 branch-length rescaling, and no support or 1000-resample SH-like local support were recorded. Gamma rescales lengths after CAT20 search; it is not a full gamma topology search. SH-like local supports are neither global bootstrap percentages nor posterior probabilities. First-word identifiers were mapped privately then restored exactly; descriptions were ignored. Letters were uppercased, dot gaps became hyphens, nucleotide U became T, and ambiguity symbols were treated as missing data, matching the upstream engine. Recorded alignment/tree measurements have no invented QC thresholds. The display root is arbitrary; no species-tree inference, model selection, root placement, sequence alignment or homology selection was performed.'}
    return workflows,schema

def checks():
    out=[]
    for datatype,model in [('nucleotide','GTR'),('protein','LG')]:
        out.append({'id':datatype+'-known-pairs','workflow':'infer-'+datatype,'inputs':{'alignment':[{'alignment':'fixture-'+datatype}]},'params':{'model':model,'rates':'cat','support':'sh','seed':42},'expect':[{'output':'tree','kind':'text','contains':['alpha1:','alpha2:','beta1:','beta2:','gamma1:','gamma2:',');']},{'output':'summary','kind':'text','contains':['"taxa": 6','"columns": 800','"variableColumnsIgnoringMissing": 300','"parsimonyInformativeColumnsIgnoringMissing": 210','"treeTaxa": 6','"localSupportValues": 3']},{'output':'settings','kind':'text','contains':['"serial": true','"model": "'+model+'"','"supportResamples": 1000']}]})
    return {'schema':1,'checks':out}

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--cache',type=Path,default=ROOT/'build/fasttree-inputs');p.add_argument('--build',type=Path,default=ROOT/'build/fasttree-windows');p.add_argument('--destination',type=Path,default=ROOT/'packs/fasttree-1.0.0');a=p.parse_args();cache=a.cache.resolve();build=a.build.resolve();dest=a.destination.resolve()
    record=json.loads((build/'build.json').read_text(encoding='utf-8'))
    if record['platform']!='windows-x86_64' or record['upstreamCommit']!=COMMIT or record['guardSha256']!=sha(ROOT/'tools/fasttree/guard.cpp') or record['builderSha256']!=sha(ROOT/'scripts/build_fasttree_native.py'):raise ValueError('Build/source correspondence failed')
    if dest.exists() and any(dest.iterdir()):raise ValueError('Destination must be new/empty')
    for d in ['bin','fixtures','licenses']:(dest/d).mkdir(parents=True,exist_ok=True)
    sections=[]
    def section(name,values):sections.append('['+name+']\n'+'\n'.join(k+'='+str(v) for k,v in values.items() if k!='id' or name=='pack')+'\n')
    section('pack',dict(format=2,id='fasttree',version=VERSION,name='FastTree phylogenetics',platform='windows-x86_64',description='Serial approximate maximum-likelihood trees from nucleotide/protein alignments, with explicit models and local support.',color='#527A65'))
    for name in ['fasttree','fasttree-guard']:
        f=build/(name+'.exe')
        if sha(f)!=record['files'][f.name]['sha256'] or f.read_bytes()[:2]!=b'MZ':raise ValueError('Changed/non-Windows executable '+name)
        shutil.copyfile(f,dest/'bin'/f.name);section('tool:'+('fasttree-adapter' if name=='fasttree-guard' else name),dict(path='bin/'+f.name,version='2.2.0' if name=='fasttree' else VERSION,sha256=sha(f)))
    workflows,schema=definitions()
    for name,value in [('workbench-schema.json',schema),('workbench-checks.json',checks())]:(dest/name).write_text(json.dumps(value,indent=2)+'\n',encoding='utf-8')
    for f in (ROOT/'tools/fasttree/fixtures').iterdir():shutil.copyfile(f,dest/'fixtures'/f.name)
    assets={'workbench-schema':'workbench-schema.json','workbench-checks':'workbench-checks.json',**{'fixture-'+name:'fixtures/'+name+'.afa' for name in ['nucleotide','protein']},'fixture-truth':'fixtures/truth.json','fixture-reference':'fixtures/reference.json'}
    for name,path in assets.items():section('asset:'+name,dict(path=path,sha256=sha(dest/path)))
    for wf in workflows:
        section('workflow:'+wf['id'],dict(name=wf['name'],description=wf['description'],inputs=','.join(x['id'] for x in wf['inputs']),outputs=','.join(x['id'] for x in wf['outputs']),steps=','.join(x['id'] for x in wf['steps'])))
        for kind in ['input','output','step']:
            for item in wf[kind+'s']:section(kind+':'+wf['id']+':'+item['id'],item)
    (dest/'pack.ini').write_text('\n'.join(sections),encoding='utf-8')
    for name in ['FastTree.c','LICENSE']:
        if sha(cache/name)!=SOURCES[name][1]:raise ValueError('Changed upstream source/license')
        shutil.copyfile(cache/name,dest/'licenses'/('FastTree-LICENSE.txt' if name=='LICENSE' else name))
    for f in [ROOT/'tools/fasttree/guard.cpp',ROOT/'tools/fasttree/fixtures.py',ROOT/'scripts/build_fasttree_native.py',Path(__file__),ROOT/'LICENSE']:shutil.copyfile(f,dest/'licenses'/('Workbench-LICENSE.txt' if f.name=='LICENSE' else f.name))
    shutil.copyfile(build/'build.json',dest/'licenses/build-provenance.json')
    for name,digest in record['compilerNotices'].items():
        if sha(build/'compiler-notices'/name)!=digest:raise ValueError('Changed runtime notice')
        shutil.copyfile(build/'compiler-notices'/name,dest/'licenses'/('compiler-'+name))
    shutil.copyfile(ROOT/'docs/FASTTREE-PACK.md',dest/'PACK-README.md')
    sys.path.insert(0,str(ROOT/'workspace'));from catalog import load_pack
    pack=load_pack(dest/'pack.ini');print(json.dumps({'pack':str(dest),'manifestSha256':sha(dest/'pack.ini'),'workflows':list(pack['workflows']),'checks':len(checks()['checks'])},indent=2))
if __name__=='__main__':main()
