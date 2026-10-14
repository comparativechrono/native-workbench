#!/usr/bin/env python3
"""Assemble DESeq2/tximport with pinned R, Windows packages and isolated Python."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import sys
import zipfile
from fetch_deseq2_build_inputs import LOCK, obtain, sha
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'desktop'))
from prepare_modular_packs import field,number,artifact,execute,workflow
PACK_VERSION='1.0.0'
CITATIONS=[{'text':'Love MI, Huber W, Anders S (2014). Moderated estimation of fold change and dispersion for RNA-seq data with DESeq2. Genome Biology 15:550.','url':'https://doi.org/10.1186/s13059-014-0550-8'}, {'text':'Soneson C, Love MI, Robinson MD (2015). Differential analyses for RNA-seq: transcript-level estimates improve gene-level inferences. F1000Research 4:1521.','url':'https://doi.org/10.12688/f1000research.7563.2'}]


def dump(path,value):Path(path).write_text(json.dumps(value,indent=2)+'\n',encoding='utf-8')
def copy(source,destination):
    destination.parent.mkdir(parents=True,exist_ok=True)
    with source.open('rb') as src,destination.open('xb') as dst:shutil.copyfileobj(src,dst,1024*1024)
    if source.stat().st_size!=destination.stat().st_size or sha(source)!=sha(destination):raise ValueError('Copy changed: '+str(destination))


def definitions():
    workflows=[];schemas={}
    for mode,title in [('counts','DESeq2: raw gene-count matrix'),('featurecounts','DESeq2: merge featureCounts samples'),('kallisto','tximport + DESeq2: kallisto samples')]:
        inputs=[field('counts','Raw gene-count matrix' if mode=='counts' else 'Sample count files in metadata order','file' if mode=='counts' else 'files',filter='Count tables|*.tsv;*.txt|All files|*.*',help='One TSV with gene_id followed by exact sample_id columns; non-negative raw integer counts only. Rounded TPM/FPKM or normalized counts are not valid.' if mode=='counts' else ('Select 4 to 64 one-sample featureCounts gene tables. File order maps explicitly to input_index in the sample sheet. Identical genes/annotation/order required.' if mode=='featurecounts' else 'Select 4 to 64 kallisto abundance.tsv files in sample-sheet input_index order. All must use the same transcript reference. TPM alone and bootstrap tables are not supported.')),
                field('samples','Sample metadata TSV',filter='Sample table|*.tsv;*.txt|All files|*.*',help='Columns: sample_id, condition, biological_replicate; batch for batch adjustment; input_index for multiple files (1-based selected-file position). Independent biological IDs must be unique. At least two biological replicates per condition; three or more preferable.'),
                field('design','Experimental design','choice',default='condition',choices='condition:Condition only|batch-condition:Batch plus condition',help='Fixed additive formulas only. Batch must not be confounded with condition. Paired/repeated-measure/continuous/interaction designs are not supported.'),
                field('numerator','Numerator condition (positive fold change)','text',constraint='identifier',help='Exact condition label from the sample table. Positive log2 fold changes mean higher expression in this condition.'),
                field('denominator','Denominator / reference condition','text',constraint='identifier',help='Different exact condition label from the sample table.'),
                field('alpha','Adjusted P-value threshold','text',default='0.05',help='Decimal strictly between 0 and 1; used by upstream independent filtering and BH-adjusted significance.'),
                number('min-count','Minimum total gene count',10,1,1000000,help='Genes below this summed count across all samples remain in the full result table labelled prefiltered. At least 20 genes must remain.')]
        temporary=field('scratch-root','Temporary files folder (optional)','directory',help='Usually leave blank to use your Windows temporary folder. If R reports spaces in its temporary path, select an existing writable folder with no spaces in its full path. Only a private child is created and removed.')
        temporary['required']='false'
        inputs.append(temporary)
        ports=[dict(id='counts',label='Raw gene counts' if mode=='counts' else 'Sample '+('featureCounts' if mode=='featurecounts' else 'kallisto')+' tables',type='metrics',accepts=['metrics'],manifestInputs=['counts'],min=1 if mode=='counts' else 4,max=1 if mode=='counts' else 64),dict(id='samples',label='Sample metadata',type='text',manifestInputs=['samples'],min=1,max=1),dict(id='scratch-root',label='Optional temporary files folder',type='directory',manifestInputs=['scratch-root'],min=0,max=1)]
        if mode=='kallisto':
            inputs.append(field('tx2gene','Transcript-to-gene mapping TSV',filter='Transcript gene mapping|*.tsv;*.txt|All files|*.*',help='Exactly two columns: transcript_id and gene_id. Every quantified transcript must have one mapping, including exact version suffix. Use the annotation release matching the quantified transcriptome.'))
            ports.append(dict(id='tx2gene',label='Matching transcript-to-gene mapping',type='text',manifestInputs=['tx2gene'],min=1,max=1))
        outputs=[artifact('results','Complete differential-expression results','differential-expression.tsv'),artifact('normalized-counts','Normalized retained-gene counts','normalized-counts.tsv'),artifact('imported-counts','Imported gene counts','imported-gene-counts.tsv'),artifact('summary','Statistical settings and summary','analysis-summary.json'),artifact('design','Realized design matrix','design-matrix.tsv'),artifact('pca','PCA plot (PDF)','pca.pdf'),artifact('ma','MA plot (PDF)','ma.pdf'),artifact('pca-coordinates','PCA coordinates','pca-coordinates.tsv'),artifact('session','R session and package versions','R-session.txt'),artifact('methods','Executed analysis methods','analysis-methods.txt'),artifact('provenance','Selected sample file hashes','input-provenance.json'),artifact('commands','Private R command','commands.json')]
        argv=['-I','-B','-X','utf8','{asset:adapter}','--mode',mode,'--run','{run}','--samples','{input:samples}','--scratch-root','{input:scratch-root}','--tx2gene','{input:tx2gene}' if mode=='kallisto' else '-', '--design','{input:design}','--numerator','{input:numerator}','--denominator','{input:denominator}','--alpha','{input:alpha}','--min-count','{input:min-count}','--counts-origin','raw-integer' if mode=='counts' else mode,'--','{input:counts}' if mode=='counts' else '{inputs:counts}']
        steps=[execute('analyse','Fit differential-expression model and generate diagnostics','python',argv,produces=[o['id'] for o in outputs])]
        workflows.append(workflow(mode,title,'Local bulk RNA gene-level Wald inference with explicit biological samples, contrast and optional batch adjustment. Unshrunk log2 fold changes, BH FDR, PCA and MA diagnostics; no online package installation.',inputs,outputs,steps))
        methods='Gene-level differential expression was tested with DESeq2 1.52.0 under private R 4.6.1. '+('Transcript abundance files were summarized with tximport 1.40.0 (countsFromAbundance=no) using exact transcript-to-gene mappings and DESeqDataSetFromTximport, retaining average-transcript-length normalization offsets. ' if mode=='kallisto' else 'Unnormalized integer gene counts were supplied to DESeqDataSetFromMatrix. ')+ 'The selected additive condition or batch-plus-condition design and numerator-versus-denominator contrast were explicitly recorded. Genes below the selected total-count threshold were prefiltered. Serial Wald tests used median-of-ratios size-factor estimation, parametric dispersion fitting with upstream fallback, Cook-distance filtering, independent filtering and Benjamini-Hochberg adjustment at the recorded alpha. Automatic count replacement and fold-change shrinkage were disabled. Results preserve NA and prefiltered statuses; positive log2 fold change means higher expression in the numerator condition. PCA uses design-aware variance stabilization and up to 500 variable genes. Metadata assert independent biological replication; technical replicates and paired/repeated-measures designs are outside this operation.'
        schemas[mode]={'ports':ports,'outputs':[dict(id=o['id'],label=o['label'],type='file' if o['id'] in ('pca','ma') else 'text' if o['id'] in ('session','methods') else 'metrics',manifestOutputs=[o['id']]) for o in outputs],'methods':methods,'pathPolicy':{'asciiOnly':True}}
    return workflows,{'schema':1,'category':'RNA-seq','citations':CITATIONS,'workflows':schemas}


def checks():
    checks=[]
    for mode in ('counts','featurecounts','kallisto'):
        bindings={'counts':[{'counts':'fixture-counts'}] if mode=='counts' else [{'counts':'fixture-'+mode+'-'+str(n)} for n in range(1,7)],'samples':[{'samples':'fixture-samples'}]}
        if mode=='kallisto':bindings['tx2gene']=[{'tx2gene':'fixture-tx2gene'}]
        checks.append({'id':mode+'-six-samples','workflow':mode,'params':{'design':'condition','numerator':'treated','denominator':'control','alpha':'0.05','min-count':10},'inputs':bindings,
          'expect':[{'output':'summary','kind':'text','contains':['"samples": 6','"genesInput": 300','"genesTested": 300','"test": "Wald"','"pAdjustment": "BH"','"positiveSignificant": 13','"negativeSignificant": 15']},{'output':'results','kind':'text','contains':['gene_id\tbaseMean\tlog2FoldChange\tlfcSE\tstat\tpvalue\tpadj\tstatus','gene0001\t','gene0300\t']},{'output':'session','kind':'text','contains':['DESeq2_1.52.0','tximport_1.40.0']},{'output':'provenance','kind':'text','contains':['"unchanged": true']}]})
    return {'schema':1,'checks':checks}


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--cache',type=Path,default=ROOT/'build/deseq2-inputs');p.add_argument('--r-runtime-zip',type=Path,required=True);p.add_argument('--r-runtime-provenance',type=Path,required=True);p.add_argument('--destination',type=Path,default=ROOT/'packs/deseq2-1.0.0');p.add_argument('--fetch',action='store_true');a=p.parse_args()
    dest=a.destination.resolve();cache=a.cache.resolve();lock=json.loads(LOCK.read_text());rprov=json.loads(a.r_runtime_provenance.read_text())
    if dest.exists() and any(dest.iterdir()):raise ValueError('Destination must be new/empty')
    # Root-owned runtime recipe supplies exact installer-bound inventory.
    rpin=rprov['runtimeArchive']
    if rprov['rVersion']!='4.6.1':raise ValueError('Unexpected private R version')
    if rpin['sha256']!=sha(a.r_runtime_zip) or rpin['bytes']!=a.r_runtime_zip.stat().st_size:raise ValueError('R runtime archive identity mismatch')
    if rprov['installer']['sha256']!=lock['R']['installer']['sha256']:raise ValueError('R runtime is not bound to the pinned upstream installer')
    for folder in ['bin','runtime','licenses','fixtures']:(dest/folder).mkdir(parents=True,exist_ok=True)
    def cached(pin):
        f=cache/pin['filename']
        if a.fetch:return obtain(pin,cache)
        if not f.is_file() or f.stat().st_size!=pin['bytes'] or sha(f)!=pin['sha256']:raise ValueError('Missing or altered cache input: '+str(f))
        return f
    python=next(x for x in lock['python'] if x['filename'].endswith('.zip'))
    with zipfile.ZipFile(cached(python)) as z:z.extractall(dest/'bin')
    (dest/'bin/pythonw.exe').unlink(missing_ok=True)
    (dest/'bin/python313._pth').write_text('python313.zip\n.\n',encoding='ascii')
    copy(a.r_runtime_zip,dest/'runtime/R-4.6.1-windows.zip')
    archives=[dict(path='runtime/R-4.6.1-windows.zip',destination='R',sha256=sha(a.r_runtime_zip),bytes=a.r_runtime_zip.stat().st_size)]
    for pkg in lock['packages']:
        if pkg['runtime']:
            src=cached(pkg['binary']);target=dest/'runtime'/src.name;copy(src,target)
            archives.append(dict(path='runtime/'+src.name,destination='R/library',sha256=sha(src),bytes=src.stat().st_size))
        source=cached(pkg['source']);copy(source,dest/'licenses'/source.name)
    for pin in [lock['R']['source'],*lock['python'][1:]]:
        source=cached(pin);copy(source,dest/'licenses'/source.name)
    dump(dest/'runtime-index.json',{'schema':1,'RVersion':lock['RVersion'],'archives':archives,'privatePerRun':True,'installPackagesAtAnalysisTime':False})
    for name in ['adapter.py','analysis.R']:copy(ROOT/'tools/deseq2'/name,dest/name)
    for src,name in [(LOCK,'windows-lock.json'),(a.r_runtime_provenance,'R-runtime-provenance.json'),(ROOT/'scripts/prepare_deseq2_pack.py','prepare_deseq2_pack.py'),(ROOT/'scripts/fetch_deseq2_build_inputs.py','fetch_deseq2_build_inputs.py'),(ROOT/'tools/deseq2/adapter.py','adapter.py'),(ROOT/'tools/deseq2/analysis.R','analysis.R'),(ROOT/'tools/deseq2/fixtures.py','fixtures.py'),(ROOT/'LICENSE','Workbench-MIT.txt'),(ROOT/'scripts/build_r_runtime_windows.py','build_r_runtime_windows.py')]:copy(src,dest/'licenses'/name)
    source_archive=json.loads((ROOT/'tools/deseq2/r-runtime-source-archive.json').read_text())
    if source_archive['correspondingRuntimeSha256']!=rpin['sha256'] or source_archive['sourceLockSha256']!=sha(ROOT/'tools/deseq2/r-runtime-source-lock.json'):raise ValueError('Corresponding-source companion is not bound to this runtime/source lock')
    for name in ['r-runtime-source-lock.json','r-runtime-source-archive.json','R-RUNTIME-SOURCES.md','prepare_runtime_sources.py']:copy(ROOT/'tools/deseq2'/name,dest/'licenses'/name)
    spec=importlib.util.spec_from_file_location('deseq_fixtures',ROOT/'tools/deseq2/fixtures.py');mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod);mod.fixtures(dest/'fixtures')
    for name in ['kallisto-abundance.tsv','kallisto-fixture-provenance.json']:copy(ROOT/'tools/deseq2'/name,dest/'fixtures'/name)
    workflows,schema=definitions();dump(dest/'workbench-schema.json',schema);dump(dest/'workbench-checks.json',checks())
    copy(ROOT/'docs/DESEQ2-PACK.md',dest/'PACK-README.md')
    (dest/'licenses/NOTICE.txt').write_text('DESeq2 and tximport are unmodified upstream Bioconductor Windows binaries. Each R package preserves its LICENSE, DESCRIPTION and installed source/documentation inside its ZIP; the matching source tar.gz archives, including build-time LinkingTo dependencies, are retained here. DESeq2 is LGPL >=3; tximport is GPL >=2. R is GPL-2 or GPL-3 with component notices retained in the complete private runtime; its matching official source release includes recommended-package sources. CPython retains its PSF/component license and matching source. The Workbench adapters are MIT, do not alter statistical algorithms, and extract private runtimes only inside each run directory. No user packages or startup scripts are loaded. No installer runs during analysis.\n',encoding='utf-8')
    with (dest/'licenses/NOTICE.txt').open('a',encoding='utf-8') as notice:
        notice.write('\nAdditional external Rtools and Tcl/Tk libraries, compiler runtime sources, R-project build scripts and patches are supplied in the separate source companion identified by r-runtime-source-archive.json. Its source lock and recovery script are retained here.\nSource companion: '+source_archive['url']+'\nSHA-256: '+source_archive['sha256']+'\nBytes: '+str(source_archive['bytes'])+'\nR scratch files use a unique owned temporary child removed on ordinary completion/failure.\n')
    sections=[]
    def section(name,values):sections.append('['+name+']\n'+'\n'.join(k+'='+str(v) for k,v in values.items() if k!='id' or name=='pack')+'\n')
    section('pack',dict(format=2,id='deseq2',version=PACK_VERSION,name='DESeq2 differential expression',platform='windows-x86_64',description='Bulk RNA differential expression with DESeq2, tximport and private R. Raw gene matrices, featureCounts and kallisto sample fan-in. Workbench 0.6.0 or newer.',color='#39857D'))
    section('tool:python',dict(path='bin/python.exe',version='3.13.16',sha256=sha(dest/'bin/python.exe')))
    explicit={'adapter':'adapter.py','analysis':'analysis.R','workbench-schema':'workbench-schema.json','workbench-checks':'workbench-checks.json','fixture-counts':'fixtures/counts.tsv','fixture-samples':'fixtures/samples.tsv','fixture-tx2gene':'fixtures/tx2gene.tsv'}
    explicit.update({'fixture-featurecounts-'+str(n):'fixtures/featurecounts-'+str(n)+'.tsv' for n in range(1,7)})
    explicit.update({'fixture-kallisto-'+str(n):'fixtures/abundance-'+str(n)+'.tsv' for n in range(1,7)})
    used={'bin/python.exe'}
    for name,path in explicit.items():section('asset:'+name,dict(path=path,sha256=sha(dest/path)));used.add(path)
    for n,path in enumerate(sorted(dest.rglob('*'))):
        rel=path.relative_to(dest).as_posix()
        if path.is_file() and rel not in used and not rel.startswith('licenses/') and rel!='PACK-README.md':section('asset:runtime-'+str(n),dict(path=rel,sha256=sha(path)))
    for wf in workflows:
        section('workflow:'+wf['id'],dict(name=wf['name'],description=wf['description'],inputs=','.join(x['id'] for x in wf['inputs']),outputs=','.join(x['id'] for x in wf['outputs']),steps=','.join(x['id'] for x in wf['steps'])))
        for kind in ('input','output','step'):
            for item in wf[kind+'s']:section(kind+':'+wf['id']+':'+item['id'],item)
    (dest/'pack.ini').write_text('\n'.join(sections),encoding='utf-8')
    sys.path.insert(0,str(ROOT/'workspace'));from catalog import load_pack
    pack=load_pack(dest/'pack.ini');print(json.dumps({'pack':str(dest),'manifestSha256':sha(dest/'pack.ini'),'workflows':list(pack['workflows']),'filesAndDirectories':len(list(dest.rglob('*')))},indent=2))

if __name__=='__main__':main()
