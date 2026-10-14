#!/usr/bin/env python3
"""Native Windows science/guard regression gate for a frozen DESeq2 pack.

Run: python tests/test_deseq2_pack.py --pack INSTALLED_PACK --report evidence.json
No system R, package installation, network request or Linux substitution is used.
"""
import argparse
import csv
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
import unittest

PACK=None
TEMP=None
EVIDENCE={}


def sha(path):
    with Path(path).open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()

def inventory(root):return {p.relative_to(root).as_posix():sha(p) for p in root.rglob('*') if p.is_file()}
def table(path):
    with path.open(encoding='utf-8',newline='') as f:return list(csv.DictReader(f,delimiter='\t'))
def write_table(path,rows):
    with path.open('w',encoding='utf-8',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0]),delimiter='\t',lineterminator='\n');w.writeheader();w.writerows(rows)
def invoke(argv,cwd,env=None,okay=True):
    r=subprocess.run([str(x) for x in argv],cwd=cwd,env=env,capture_output=True,text=True,timeout=240)
    if okay and r.returncode:raise AssertionError(r.stdout+'\n'+r.stderr)
    return r


class DESeq2Science(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if os.name!='nt':raise RuntimeError('This gate requires native Windows; no skipped scientific checks are accepted')
        cls.root=Path(TEMP or tempfile.mkdtemp(prefix='deseq2 native scientific paths ')).resolve();cls.root.mkdir(parents=True,exist_ok=True)
        cls.pack=PACK.resolve();cls.fixture=cls.pack/'fixtures';cls.before=inventory(cls.pack)
        cls.counter=0;cls.valid={}
        for mode in ('counts','featurecounts','kallisto'):
            out=cls.root/('valid '+mode);out.mkdir()
            command=cls.adapter_command(mode,out)
            env=os.environ.copy()
            # A hostile inherited user startup file must not execute.
            poison=cls.root/'user profile.R';poison.write_text("stop('USER STARTUP EXECUTED')\n")
            env['R_PROFILE_USER']=str(poison);env['R_ENVIRON_USER']=str(poison);env['R_LIBS_USER']=str(cls.root/'not a library')
            if mode!='counts':
                spaced_temp=cls.root/'host temporary files with spaces';spaced_temp.mkdir(exist_ok=True)
                env['TEMP']=str(spaced_temp);env['TMP']=str(spaced_temp)
                # An explicit user-owned short root handles hosts where 8.3 aliases are disabled.
                command[command.index('--samples'):command.index('--samples')]=['--scratch-root',str(Path(os.environ['RUNNER_TEMP']) if 'RUNNER_TEMP' in os.environ else Path(tempfile.gettempdir()))]
            invoke(command,out,env=env)
            cls.valid[mode]=out
        cls.rhome=cls.valid['counts']/'_runtime/R';cls.rexe=cls.rhome/'bin/x64/Rscript.exe'
        cls.env={k:v for k,v in os.environ.items() if not k.upper().startswith(('R_','RSTUDIO','_R_'))}
        cls.env.update(R_HOME=str(cls.rhome),R_LIBS=str(cls.rhome/'library'),R_LIBS_USER=str(cls.rhome/'library'),R_LIBS_SITE=str(cls.rhome/'library'),R_USER=str(cls.root),OMP_NUM_THREADS='1')
        EVIDENCE['validSummaries']={mode:json.loads((out/'analysis-summary.json').read_text()) for mode,out in cls.valid.items()}

    @classmethod
    def adapter_command(cls,mode,out,files=None):
        selected=files or ([cls.fixture/'counts.tsv'] if mode=='counts' else [cls.fixture/((mode if mode=='featurecounts' else 'abundance')+'-'+str(n)+'.tsv') for n in range(1,7)])
        return [cls.pack/'bin/python.exe','-I','-B','-X','utf8',cls.pack/'adapter.py','--mode',mode,'--run',out,'--samples',cls.fixture/'samples.tsv','--tx2gene',cls.fixture/'tx2gene.tsv' if mode=='kallisto' else '-', '--design','condition','--numerator','treated','--denominator','control','--alpha','0.05','--min-count','10','--counts-origin','raw-integer' if mode=='counts' else mode,'--',*selected]

    @classmethod
    def tearDownClass(cls):
        after=inventory(cls.pack)
        EVIDENCE['installedPackUnchanged']=after==cls.before
        if after!=cls.before:raise AssertionError('Scientific checks changed the installed pack')

    def request(self,mode='counts'):
        type(self).counter+=1
        out=self.root/('regression '+str(self.counter));out.mkdir()
        request=json.loads((self.valid[mode]/'request.json').read_text());request['run']=str(out)
        return out,request

    def run_request(self,out,request,expected=None):
        path=out/'request.json';path.write_text(json.dumps(request))
        r=invoke([self.rexe,'--vanilla',self.pack/'analysis.R',path],out,env=self.env,okay=expected is None)
        if expected is not None:
            self.assertNotEqual(r.returncode,0)
            self.assertIn(expected,r.stdout+r.stderr)
            self.assertFalse((out/'differential-expression.tsv').exists())
        return r

    def modify(self,out,request,key,transform,index=None):
        original=Path(request[key] if index is None else request[key][index]);rows=table(original);transform(rows)
        target=out/(key+str(index)+'.tsv');write_table(target,rows)
        if index is None:request[key]=str(target)
        else:request[key][index]=str(target)

    def test_01_effect_direction_fdr_and_null_genes(self):
        truth=json.loads((self.fixture/'truth.json').read_text())
        EVIDENCE['plantedEffects']={}
        for mode,out in self.valid.items():
            rows={r['gene_id']:r for r in table(out/'differential-expression.tsv')}
            self.assertEqual(len(rows),300)
            for gene in truth['positive']:
                self.assertGreater(float(rows[gene]['log2FoldChange']),2)
                self.assertLess(float(rows[gene]['padj']),.01)
            for gene in truth['negative']:
                self.assertLess(float(rows[gene]['log2FoldChange']),-2)
                self.assertLess(float(rows[gene]['padj']),.01)
            null_discoveries=sum(r['padj']!='NA' and float(r['padj'])<.05 for g,r in rows.items() if g in truth['null'])
            self.assertLessEqual(null_discoveries,5)
            EVIDENCE['plantedEffects'][mode]={'positiveRecovered':len(truth['positive']),'negativeRecovered':len(truth['negative']),'incidentalNullDiscoveries':null_discoveries,'scope':'Deterministic effect-direction and adjusted-P-value regression; not empirical FDR calibration or a power benchmark.'}
            self.assertTrue((out/'pca.pdf').read_bytes().startswith(b'%PDF-'))
            self.assertTrue((out/'ma.pdf').read_bytes().startswith(b'%PDF-'))
            self.assertEqual([x['sample_id'] for x in table(out/'design-matrix.tsv')],truth['samples'])

    def test_02_count_import_equivalence_and_normalization_conventions(self):
        base=table(self.valid['counts']/'differential-expression.tsv')
        for x,y in zip(base,table(self.valid['featurecounts']/'differential-expression.tsv')):
            self.assertEqual(x['gene_id'],y['gene_id'])
            for key in ('baseMean','log2FoldChange','lfcSE','stat','pvalue','padj'):
                if x[key]=='NA':self.assertEqual(y[key],'NA')
                else:self.assertAlmostEqual(float(x[key]),float(y[key]),delta=max(1e-10,abs(float(x[key]))*1e-10))
        raw=table(self.fixture/'counts.tsv')
        imported=table(self.valid['kallisto']/'imported-gene-counts.tsv')
        self.assertEqual(len(imported),len(raw))
        for x,y in zip(raw,imported):
            self.assertEqual(x['gene_id'],y['gene_id'])
            for key in x:
                if key!='gene_id':self.assertEqual(float(x[key]),float(y[key]))
        # This fixture has constant effective lengths across samples. Upstream's
        # tximport normalization factors are recentered to geometric mean 1;
        # ordinary raw-matrix size factors are not. Thus baseMean has a known
        # global scale difference even though imported counts are identical.
        samples=[x for x in raw[0] if x!='gene_id']
        log_geomeans=[statistics.mean(math.log(float(row[s])) for s in samples) for row in raw]
        sf=[math.exp(statistics.median(math.log(float(row[s]))-gm for row,gm in zip(raw,log_geomeans))) for s in samples]
        scale=math.exp(statistics.mean(math.log(x) for x in sf))
        observed=[]
        for x,y in zip(base,table(self.valid['kallisto']/'differential-expression.tsv')):
            self.assertEqual(x['gene_id'],y['gene_id'])
            ratio=float(y['baseMean'])/float(x['baseMean']);observed.append(ratio)
            self.assertAlmostEqual(ratio,scale,delta=1e-10)
        EVIDENCE['normalizationConvention']={'countsIdentical':True,'rawSizeFactors':sf,'sizeFactorGeometricMean':scale,'observedBaseMeanRatioRange':[min(observed),max(observed)],'explanation':'Pinned DESeq2 estimateNormFactors recenters tximport length normalization factors to geometric mean1; ordinary matrix size factors are not recentered. All inferential columns are instead compared against the corresponding independent upstream API path.'}

    def test_03_unwrapped_upstream_reference_crosscheck(self):
        script_hashes={}
        for mode in ('counts','kallisto'):
            out,request=self.request(mode)
            # Independently invoke the public APIs without the Workbench analysis script.
            script=out/'reference.R'
            script.write_text(""".libPaths(file.path(R.home(),'library'))
suppressPackageStartupMessages(library(DESeq2)); suppressPackageStartupMessages(library(jsonlite)); suppressPackageStartupMessages(library(tximport))
a<-commandArgs(TRUE); q<-fromJSON(a[1])
s<-read.delim(q$samples,stringsAsFactors=FALSE);rownames(s)<-s$sample_id;s$condition<-relevel(factor(s$condition),'control')
if(q$mode=='kallisto') {
 f<-setNames(q$files[as.integer(s$input_index)],s$sample_id)
 txg<-read.delim(q$tx2gene,stringsAsFactors=FALSE,check.names=FALSE)
 txi<-tximport(f,type='kallisto',tx2gene=txg,countsFromAbundance='no',dropInfReps=TRUE,importer=function(path,...) read.delim(path,check.names=FALSE,stringsAsFactors=FALSE))
 d<-DESeqDataSetFromTximport(txi,s,~condition)
} else {
 x<-read.delim(q$files[1],row.names=1,check.names=FALSE)
 d<-DESeqDataSetFromMatrix(as.matrix(x[,s$sample_id]),s,~condition)
}
d<-d[rowSums(counts(d))>=10,]
d<-DESeq(d,test='Wald',fitType='parametric',sfType='ratio',betaPrior=FALSE,minReplicatesForReplace=Inf,parallel=FALSE)
r<-results(d,contrast=c('condition','treated','control'),alpha=.05,independentFiltering=TRUE,cooksCutoff=TRUE,pAdjustMethod='BH',parallel=FALSE)
write.table(data.frame(gene_id=rownames(r),as.data.frame(r)),a[2],sep='\\t',quote=FALSE,row.names=FALSE,na='NA')
""")
            req=out/'reference-request.json';req.write_text(json.dumps(request));reference=out/'reference.tsv'
            invoke([self.rexe,'--vanilla',script,req,reference],out,env=self.env)
            reference_rows=table(reference);actual_rows=table(self.valid[mode]/'differential-expression.tsv')
            self.assertEqual(len(reference_rows),300);self.assertEqual(len(actual_rows),300)
            for x,y in zip(reference_rows,actual_rows):
                self.assertEqual(x['gene_id'],y['gene_id'])
                for key in ('baseMean','log2FoldChange','lfcSE','stat','pvalue','padj'):
                    if x[key]=='NA':self.assertEqual(y[key],'NA')
                    else:self.assertAlmostEqual(float(x[key]),float(y[key]),delta=max(1e-10,abs(float(x[key]))*1e-10))
            script_hashes[mode]=sha(script)
        EVIDENCE['unwrappedUpstreamCrosscheck']={'samePinnedRuntime':True,'allGenesCompared':300,'inputModes':['counts','kallisto'],'totalGeneComparisons':600,'relativeTolerance':1e-10,'scriptSha256ByMode':script_hashes}

    def test_04_batch_adjustment_and_reversed_contrast(self):
        for reverse in (False,True):
            out,q=self.request();q['design']='batch-condition'
            if reverse:q['numerator'],q['denominator']=q['denominator'],q['numerator']
            self.run_request(out,q)
            r=table(out/'differential-expression.tsv')[0]
            self.assertLess(float(r['log2FoldChange']),-2) if reverse else self.assertGreater(float(r['log2FoldChange']),2)
            self.assertIn('batch',json.loads((out/'analysis-summary.json').read_text())['design'])

    def test_05_fractional_normalized_and_duplicate_gene_inputs(self):
        for kind in ('fraction','header','duplicate'):
            out,q=self.request()
            def change(rows):
                if kind=='fraction':rows[0]['control1']='4.5'
                elif kind=='header':
                    for r in rows:r['TPM']=r.pop('gene_id')
                else:rows[1]['gene_id']=rows[0]['gene_id']
            self.modify(out,q,'files',change,0)
            self.run_request(out,q,{'fraction':'raw non-negative integers','header':'first column must be gene_id','duplicate':'identifiers must be nonempty and unique'}[kind])

    def test_06_sample_mismatch_and_replication_failures(self):
        for kind in ('mismatch','duplicate','one-replicate'):
            out,q=self.request()
            def change(rows):
                if kind=='mismatch':rows[0]['sample_id']='missing'
                elif kind=='duplicate':rows[1]['biological_replicate']=rows[0]['biological_replicate']
                else:rows[0]['condition']='singleton'
            self.modify(out,q,'samples',change)
            self.run_request(out,q,{'mismatch':'sample columns must exactly match','duplicate':'biological replicate IDs must be globally unique','one-replicate':'at least two independent biological replicates'}[kind])

    def test_07_confounded_batch_and_residual_degrees_of_freedom(self):
        for kind in ('confounded','saturated','one-residual-df'):
            out,q=self.request();q['design']='batch-condition'
            def change(rows):
                for i,r in enumerate(rows):r['batch']=r['condition'] if kind=='confounded' else 'batch'+str(i//2+1)
                if kind=='saturated':
                    for i,r in enumerate(rows):r['batch']='batch'+str(i+1)
                if kind=='one-residual-df':
                    for r,batch in zip(rows,('batch1','batch2','batch3','batch1','batch2','batch4')):r['batch']=batch
            self.modify(out,q,'samples',change)
            self.run_request(out,q,'at least two residual degrees of freedom' if kind=='one-residual-df' else 'not full rank')

    def test_08_tx2gene_complete_unique_versioned_identifiers(self):
        for kind in ('missing','duplicate','version'):
            out,q=self.request('kallisto')
            def change(rows):
                if kind=='missing':rows.pop()
                elif kind=='duplicate':rows.append(rows[0].copy())
                else:rows[0]['transcript_id']+='.1'
            self.modify(out,q,'tx2gene',change)
            self.run_request(out,q,'identifiers must be nonempty and unique' if kind=='duplicate' else 'exact tx2gene mapping')

    def test_09_kallisto_format_ids_and_lengths_are_validated(self):
        for kind in ('id','length','negative','header'):
            out,q=self.request('kallisto')
            def change(rows):
                if kind=='id':rows[0]['target_id']='different'
                elif kind=='length':rows[0]['eff_length']='0'
                elif kind=='negative':rows[0]['est_counts']='-1'
                else:
                    for r in rows:r['counts']=r.pop('est_counts')
            self.modify(out,q,'files',change,1)
            self.run_request(out,q,{'id':'identical transcript IDs','length':'effective lengths must be positive','negative':'finite non-negative values','header':'must be an abundance.tsv table'}[kind])

    def test_10_fan_in_order_is_explicit_and_duplicate_files_rejected(self):
        out,q=self.request('featurecounts');self.modify(out,q,'samples',lambda rows:rows[1].update(input_index='1'))
        self.run_request(out,q,'map every selected file exactly once')
        duplicate=self.root/'duplicate adapter';duplicate.mkdir()
        files=[self.fixture/'featurecounts-1.tsv']*6
        r=invoke(self.adapter_command('featurecounts',duplicate,files),duplicate,okay=False)
        self.assertNotEqual(r.returncode,0);self.assertIn('same physical count file',r.stderr)
        self.assertFalse((duplicate/'_runtime').exists())

    def test_11_inputs_runtime_environment_and_pack_are_unchanged(self):
        for mode,out in self.valid.items():
            proof=json.loads((out/'input-provenance.json').read_text());self.assertTrue(proof['unchanged']);self.assertTrue(proof['temporaryDirectoryRemoved'])
            self.assertTrue(json.loads((out/'commands.json').read_text())['userStartupDisabled'])
            for item in proof['inputs']:self.assertEqual(sha(item['path']),item['sha256'])
        self.assertEqual(inventory(self.pack),self.before)

    def test_12_invalid_expression_contrast_fails_without_execution(self):
        out=self.root/'injection guard';out.mkdir()
        cmd=self.adapter_command('counts',out);cmd[cmd.index('--numerator')+1]='treated;system("whoami")'
        r=invoke(cmd,out,okay=False);self.assertNotEqual(r.returncode,0);self.assertIn('Contrast names',r.stderr)
        self.assertFalse((out/'_runtime').exists())

    def test_13_empty_libraries_and_prefiltered_gene_status(self):
        out,q=self.request();self.modify(out,q,'files',lambda rows:[r.update(control1='0') for r in rows],0)
        self.run_request(out,q,'positive count library')
        out,q=self.request();self.modify(out,q,'files',lambda rows:rows[-1].update({k:'0' for k in rows[-1] if k!='gene_id'}),0)
        self.run_request(out,q)
        self.assertEqual(table(out/'differential-expression.tsv')[-1]['status'],'prefiltered')


    def test_14_actual_kallisto_output_import(self):
        out,q=self.request()
        script=out/'actual-kallisto-import.R'
        script.write_text(""".libPaths(file.path(R.home(),'library'))
suppressPackageStartupMessages(library(tximport));suppressPackageStartupMessages(library(jsonlite))
a<-commandArgs(TRUE);f<-setNames(a[1],'actual_sample')
x<-tximport(f,type='kallisto',txOut=TRUE,dropInfReps=TRUE,countsFromAbundance='no',importer=function(path,...) read.delim(path,check.names=FALSE))
stopifnot(identical(rownames(x$counts),c('tx1','tx2','tx3')),all(abs(x$counts[,1]-c(12,6,2))<1e-8),all(abs(x$abundance[,1]-c(600000,300000,100000))<1e-6))
write_json(list(success=TRUE,counts=x$counts[,1],abundance=x$abundance[,1],length=x$length[,1],scope='Actual upstream kallisto output import, not differential-expression inference on three transcripts'),a[2],pretty=TRUE,auto_unbox=TRUE)
""")
        output=out/'actual-kallisto.json'
        invoke([self.rexe,'--vanilla',script,self.fixture/'kallisto-abundance.tsv',output],out,env=self.env)
        EVIDENCE['actualKallistoImport']=json.loads(output.read_text())
        EVIDENCE['actualKallistoFixture']=json.loads((self.fixture/'kallisto-fixture-provenance.json').read_text())


def main():
    global PACK,TEMP
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--pack',type=Path,required=True);p.add_argument('--report',type=Path,required=True);p.add_argument('--temp',type=Path);a=p.parse_args()
    PACK=a.pack;TEMP=a.temp
    started=time.time();suite=unittest.defaultTestLoader.loadTestsFromTestCase(DESeq2Science);result=unittest.TextTestRunner(verbosity=2).run(suite)
    report={'schema':1,'packId':'deseq2','packVersion':next(line.split('=',1)[1].strip() for line in (PACK/'pack.ini').read_text().splitlines() if line.startswith('version=')),'packManifestSha256':sha(PACK/'pack.ini'),'nativeWindowsHost':os.name=='nt','nativeWindowsExecuted':os.name=='nt' and bool(EVIDENCE.get('validSummaries')),'testSourceSha256':sha(Path(__file__)),'testsRun':result.testsRun,'failures':len(result.failures),'errors':len(result.errors),'skipped':len(result.skipped),'success':result.wasSuccessful() and not result.skipped,'seconds':time.time()-started,'evidence':EVIDENCE,'limitations':['Synthetic gene-count fixtures are not a real-cohort accuracy/power benchmark.','No GUI, clinical, repeated-measure or whole-transcriptome memory/cancellation validation.','Count format and sample identifiers do not prove biological independence or that integer data were never normalized.']}
    a.report.parent.mkdir(parents=True,exist_ok=True);a.report.write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report,indent=2));return 0 if report['success'] else 1

if __name__=='__main__':sys.exit(main())
