#!/usr/bin/env python3
"""SnpEff/SnpSift scientific regression: explicit pack and native/private Java.

Self-contained stdlib suite, also runnable against a released installed pack.
Windows runs omit --java; Linux science passes matching pinned Java explicitly.
No skip-based success and no system-Java fallback.
"""
import argparse,configparser,hashlib,json,os,platform,subprocess,sys,tempfile,unittest,zipfile
from pathlib import Path
sys.dont_write_bytecode=True
PACK=None;JAVA=None;REPORT=None

def sha(p):
    with Path(p).open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def rows(p):return [s.split('\t') for s in p.read_text(encoding='utf-8').splitlines() if s and not s.startswith('#')]
def infos(row):return dict((x.split('=',1)+[''])[:2] for x in row[7].split(';')) if row[7]!='.' else {}
def pin_inventory():
    result={}
    for p in sorted(PACK.rglob('*')):
        if p.is_file():result[p.relative_to(PACK).as_posix()]=sha(p)
    return result
class SnpEffScience(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not (PACK/'pack.ini').is_file() or not JAVA.is_file():raise RuntimeError('Prepare/select exact pack and pinned Java; no implicit fallback')
        cls.tmp=tempfile.TemporaryDirectory(prefix='snpeff scientific paths ');cls.root=Path(cls.tmp.name);cls.n=0;cls.assets=PACK/'assets';cls.f=PACK/'fixtures'
        cls.env=dict(os.environ)
        for k in ('JAVA_TOOL_OPTIONS','JDK_JAVA_OPTIONS','_JAVA_OPTIONS','CLASSPATH'):cls.env.pop(k,None)
        if os.name!='nt':cls.env['LD_LIBRARY_PATH']=str(JAVA.parent.parent/'lib')+':'+str(JAVA.parent.parent/'lib/server')
        cls.before=pin_inventory()
        config=configparser.ConfigParser(interpolation=None);config.read(PACK/'pack.ini',encoding='utf-8')
        for name in config.sections():
            if name.startswith(('tool:','asset:')):
                if sha(PACK/config[name]['path'])!=config[name]['sha256']:raise RuntimeError('Manifest checksum differs: '+name)
    @classmethod
    def tearDownClass(cls):
        after=pin_inventory()
        cls.tmp.cleanup()
        if cls.before!=after:raise AssertionError('Pack changed during scientific execution')
    def invoke(self,op,args,okay=True):
        type(self).n+=1;out=self.root/('result '+str(self.n));command=[str(JAVA),'-Xmx512m','-cp',os.pathsep.join(str(self.assets/n) for n in ('workbench-snpeff.jar','snpEff.jar')),'WorkbenchSnpEff',op]+[str(self.assets/n) for n in ('snpEff.jar','SnpSift.jar','snpEff.config')]+[str(out),'512']+list(map(str,args))
        result=subprocess.run(command,env=self.env,cwd=self.root,capture_output=True,text=True,timeout=180)
        detail=result.stdout+'\n'+result.stderr+'\n'+((out/'upstream.log').read_text(errors='replace') if (out/'upstream.log').is_file() else '')
        if okay:self.assertEqual(result.returncode,0,detail)
        else:
            self.assertNotEqual(result.returncode,0,detail);self.assertFalse((out/'variants.vcf').exists());self.assertFalse((out/'database.zip').exists());self.assertFalse((out/'provenance.json').exists())
        return out,detail
    def annotate(self,vcf=None,db=None,okay=True):return self.invoke('annotate',[vcf or self.f/'variants.vcf',db or self.f/'database.zip',5000,2],okay)
    def write(self,name,text):p=self.root/name;p.write_text(text,encoding='utf-8');return p
    def assert_truth(self,p):
        rr=rows(p);self.assertEqual([int(r[1]) for r in rr],[35,36,40]);self.assertEqual([r[-1] for r in rr],['0/1','1/1','0/1'])
        for r,effect,impact,aa in zip(rr,['missense_variant','synonymous_variant','stop_gained'],['MODERATE','LOW','HIGH'],['p.Ala2Val','p.Ala2Ala','p.Gln4*']):
            ann=infos(r)['ANN'].split('|');self.assertEqual(ann[1],effect);self.assertEqual(ann[2],impact);self.assertEqual(ann[10],aa)
    def test_01_build_and_annotate_independent_codon_truth(self):
        out,_=self.invoke('build-database',[self.f/'reference.fa',self.f/'genes.gff',self.f/'cds.fa','gff3','wbSynthetic1','fixture-v1','Standard','none']);ann,_=self.annotate(db=out/'database.zip');self.assert_truth(ann/'variants.vcf')
        for result in (out,ann):
            commands=json.loads((result/'provenance.json').read_text())['commands']
            for command in commands:self.assertEqual(command[command.index('-dataDir')+1],'data')
        with zipfile.ZipFile(out/'database.zip') as z:
            meta=json.loads(z.read('database.json'));self.assertEqual(meta['assembly'],'wbSynthetic1');self.assertEqual(meta['sourceInputs']['reference.fa.selected']['sha256'],sha(self.f/'reference.fa'))
            for r in meta['files']:self.assertEqual(hashlib.sha256(z.read(r['path'])).hexdigest(),r['sha256'])
    def test_02_plain_gzip_agree_and_inputs_unchanged(self):
        before={p.name:sha(p) for p in self.f.iterdir() if p.is_file()};a,_=self.annotate();b,_=self.annotate(self.f/'variants.vcf.gz');self.assertEqual(rows(a/'variants.vcf'),rows(b/'variants.vcf'));self.assert_truth(a/'variants.vcf');self.assertEqual(before,{p.name:sha(p) for p in self.f.iterdir() if p.is_file()})
    def test_03_local_annotation_is_allele_aware_and_retains_genotypes(self):
        before=sha(self.f/'annotations.vcf');out,_=self.invoke('annotate-local',[self.f/'variants.vcf',self.f/'annotations.vcf','AF','wbSynthetic1']);r=rows(out/'variants.vcf');self.assertEqual(len(r),3);self.assertNotIn('DB_AF',infos(r[0]));self.assertEqual(infos(r[1])['DB_AF'],'0.2');self.assertEqual(infos(r[2])['DB_AF'],'0.01');self.assertEqual([x[2] for x in r],['missense','synonymous','stop']);self.assertEqual([x[-1] for x in r],['0/1','1/1','0/1']);self.assertEqual(before,sha(self.f/'annotations.vcf'));self.assertFalse((self.f/'annotations.vcf.sidx').exists())
    def test_04_ref_mismatch_missing_contig_gvcf_and_existing_ann_fail(self):
        base=(self.f/'variants.vcf').read_text()
        for name,text in [('wrong-ref.vcf',base.replace('\t35\tmissense\tC\t','\t35\tmissense\tA\t')),('wrong-contig.vcf',base.replace('chrSynthetic','otherChr')),('gvcf.vcf',base.replace('\tC\tT\t60','\tC\t<NON_REF>\t60'))]:self.annotate(self.write(name,text),okay=False)
        self.annotate(self.f/'annotated.vcf',okay=False)
    def test_05_high_impact_and_valid_empty_outcome(self):
        out,_=self.invoke('filter-impact',[self.f/'annotated.vcf','HIGH']);self.assertEqual([int(r[1]) for r in rows(out/'variants.vcf')],[40])
        empty,_=self.invoke('filter-impact',[self.f/'annotated.vcf','MODIFIER']);self.assertEqual(rows(empty/'variants.vcf'),[]);self.assertIn('\tFORMAT\tSample1',(empty/'variants.vcf').read_text())
        ann,_=self.annotate(self.write('empty.vcf','\n'.join(l for l in (self.f/'variants.vcf').read_text().splitlines() if l.startswith('#'))+'\n'));self.assertEqual(rows(ann/'variants.vcf'),[]);self.assertIn('\tFORMAT\tSample1',(ann/'variants.vcf').read_text())
    def test_06_multiallelic_filter_keeps_whole_record_and_original_filter(self):
        ann=(self.f/'annotated.vcf').read_text();lines=ann.splitlines();body=[x for x in lines if not x.startswith('#')];r=body[-1].split('\t');r[4]='T,G';r[6]='LowQual';r[-1]='1/2';r[7]+=','+infos(r)['ANN'].replace('T|stop_gained|HIGH','G|missense_variant|MODERATE');header=[x for x in lines if x.startswith('#')];header.insert(1,'##FILTER=<ID=LowQual,Description="synthetic retained filter">');p=self.write('multi.vcf','\n'.join(header+['\t'.join(r)])+'\n');out,_=self.invoke('filter-impact',[p,'HIGH']);rr=rows(out/'variants.vcf');self.assertEqual(len(rr),1);self.assertEqual((rr[0][4],rr[0][6],rr[0][-1]),('T,G','LowQual','1/2'))
    def test_07_no_arbitrary_expression_or_bad_annotation(self):
        self.invoke('filter-impact',[self.f/'annotated.vcf',"HIGH' | true"],False);self.invoke('filter-impact',[self.f/'variants.vcf','HIGH'],False)
        self.invoke('annotate-local',[self.f/'variants.vcf',self.f/'annotations.vcf','AF;rm','wbSynthetic1'],False)
    def test_08_database_inventory_corruption_and_traversal_fail(self):
        with zipfile.ZipFile(self.f/'database.zip') as z:original={n:z.read(n) for n in z.namelist()}
        variants=[];bad=dict(original);bad['reference.fa']=bad['reference.fa'].replace(b'AAAA',b'CCCC',1);variants.append(bad)
        bad=dict(original);bad['../../escape']=b'evil';variants.append(bad)
        bad=dict(original);meta=json.loads(bad['database.json']);meta['snpEffVersion']='0.0';bad['database.json']=json.dumps(meta).encode();variants.append(bad)
        bad=dict(original);del bad[next(n for n in bad if n.endswith('snpEffectPredictor.bin'))];variants.append(bad)
        for i,content in enumerate(variants):
            p=self.root/('bad-resource-'+str(i)+'.zip')
            with zipfile.ZipFile(p,'x') as z:
                for n,data in content.items():z.writestr(n,data)
            self.annotate(db=p,okay=False)
        self.assertFalse((self.root/'escape').exists())
        self.annotate(db=self.f/'variants.vcf',okay=False)
    def test_09_mismatched_cds_build_fails_without_usable_resource(self):
        cds=self.write('wrong-cds.fa',(self.f/'cds.fa').read_text().replace('ATGGCT','ATGTTT'))
        self.invoke('build-database',[self.f/'reference.fa',self.f/'genes.gff',cds,'gff3','wbSynthetic1','fixture-v1','Standard','none'],False)
    def test_10_local_conflicting_assemblies_multi_and_output_collisions_fail(self):
        changed=self.write('wrong-assembly.vcf',(self.f/'annotations.vcf').read_text().replace('wbSynthetic1','OtherAssembly'))
        self.invoke('annotate-local',[self.f/'variants.vcf',changed,'AF','wbSynthetic1'],False)
        multi=self.write('multi-input.vcf',(self.f/'variants.vcf').read_text().replace('\tC\tT\t60','\tC\tT,G\t60'))
        self.invoke('annotate-local',[multi,self.f/'annotations.vcf','AF','wbSynthetic1'],False)
        self.invoke('annotate-local',[self.f/'variants.vcf',self.f/'annotations.vcf','MISSING','wbSynthetic1'],False)
        out,_=self.invoke('annotate-local',[self.f/'variants.vcf',self.f/'annotations.vcf','AF','wbSynthetic1']);self.invoke('annotate-local',[out/'variants.vcf',self.f/'annotations.vcf','AF','wbSynthetic1'],False)
    def test_11_recorded_commands_are_offline_and_methods_are_explicit(self):
        out,_=self.annotate();p=json.loads((out/'provenance.json').read_text());self.assertTrue(p['success']);self.assertTrue(p['allLociAllelesAndGenotypesRetained'])
        for cmd in p['commands']:self.assertIn('-noLog',cmd);self.assertIn('-nodownload',cmd);self.assertNotIn('download',cmd)
        schema=json.loads((PACK/'workbench-schema.json').read_text());self.assertIn('Entire' if False else 'complete VCF records',schema['workflows']['filter-impact']['methods']);self.assertEqual(schema['workflows']['build-database']['outputs'][0]['type'],'file')
    def test_12_resource_converter_accepts_explicit_archive_and_preserves_existing_output(self):
        import importlib.util
        spec=importlib.util.spec_from_file_location('converter',PACK/'licenses/prepare_database_resource.py');module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        p=self.root/'upstream.zip'
        with zipfile.ZipFile(self.f/'database.zip') as src,zipfile.ZipFile(p,'x') as dst:
            for n in src.namelist():
                if n.startswith('data/'):dst.writestr('snpEff/'+n,src.read(n))
        output=self.root/'converted.zip';module.convert(p,self.f/'reference.fa','wbSynthetic1','fixture-v1',sha(p),output,'https://example.org/synthetic-fixture',config=self.assets/'snpEff.config')
        out,_=self.annotate(db=output);self.assert_truth(out/'variants.vcf')
        before=sha(output)
        with self.assertRaises(FileExistsError):module.convert(p,self.f/'reference.fa','wbSynthetic1','fixture-v1',sha(p),output,'https://example.org/synthetic-fixture',config=self.assets/'snpEff.config')
        self.assertEqual(before,sha(output))
    def test_13_explicit_genetic_code_has_no_inherited_assembly_overrides(self):
        ref=self.write('mitochondrial-ref.fa',(self.f/'reference.fa').read_text().replace('chrSynthetic','M'))
        genes=self.write('mitochondrial-genes.gff',(self.f/'genes.gff').read_text().replace('chrSynthetic','M'))
        header='\n'.join(x.replace('chrSynthetic','M') for x in (self.f/'variants.vcf').read_text().splitlines() if x.startswith('#'))+'\n'
        vcf=self.write('tga.vcf',header+'M\t43\ttga\tTTT\tTGA\t60\tPASS\t.\tGT\t0/1\n')
        for code,effect in [('Standard','stop_gained'),('Vertebrate_Mitochondrial','missense_variant')]:
            database,_=self.invoke('build-database',[ref,genes,self.f/'cds.fa','gff3','hg38','fixture-v1',code,'none'])
            out,_=self.annotate(vcf,database/'database.zip');ann=infos(rows(out/'variants.vcf')[0])['ANN'];self.assertIn('|'+effect+'|',ann)
            config=(out/'work/snpEff.config').read_text();self.assertNotIn('hg38.M.codonTable',config)
        database,_=self.invoke('build-database',[ref,genes,self.f/'cds.fa','gff3','hg38','fixture-v1','Standard','M'])
        annotated,_=self.annotate(vcf,database/'database.zip');self.assertIn('|missense_variant|',infos(rows(annotated/'variants.vcf')[0])['ANN'])
        import importlib.util
        spec=importlib.util.spec_from_file_location('code_converter',PACK/'licenses/prepare_database_resource.py');module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        upstream=self.root/'hg38-synthetic-upstream.zip'
        with zipfile.ZipFile(database/'database.zip') as src,zipfile.ZipFile(upstream,'x') as dst:
            for name in src.namelist():
                if name.startswith('data/'):dst.writestr(name,src.read(name))
        converted=self.root/'hg38-converted.zip';module.convert(upstream,ref,'hg38','fixture-v1',sha(upstream),converted,'https://example.org/synthetic-fixture',config=self.assets/'snpEff.config')
        ann,_=self.annotate(vcf,converted);self.assertIn('|missense_variant|',infos(rows(ann/'variants.vcf')[0])['ANN'])
        with zipfile.ZipFile(converted) as z:self.assertEqual(json.loads(z.read('database.json'))['codonOverrides']['M'],'Vertebrate_Mitochondrial')
def main():
    global PACK,JAVA,REPORT
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--pack',type=Path,required=True);ap.add_argument('--java',type=Path);ap.add_argument('--report',type=Path,required=True);args=ap.parse_args();PACK=args.pack.resolve();JAVA=args.java.resolve() if args.java else PACK/'runtime/java/bin/java.exe';REPORT=args.report
    suite=unittest.defaultTestLoader.loadTestsFromTestCase(SnpEffScience);result=unittest.TextTestRunner(verbosity=2).run(suite)
    report=dict(schema='native-workbench-snpeff-regression-v1',packId='snpeff',platform=platform.platform(),nativeWindowsExecuted=os.name=='nt',explicitLinuxJavaOverride=args.java is not None,packManifestSha256=sha(PACK/'pack.ini'),testSourceSha256=sha(__file__),javaExecutableSha256=sha(JAVA),testsRun=result.testsRun,failures=len(result.failures),errors=len(result.errors),skipped=len(result.skipped),success=result.wasSuccessful() and result.testsRun==13 and not result.skipped,details=[{'test':str(t),'error':msg} for t,msg in result.failures+result.errors],scope='Unmodified upstream execution through pack adapter, scientific positive/negative assertions and installed pack hash immutability; separate native manifest checks cover released application import/runner. No GUI or clinical validation.')
    REPORT.parent.mkdir(parents=True,exist_ok=True);REPORT.write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8');print(json.dumps(report,indent=2));return 0 if report['success'] else 1
if __name__=='__main__':raise SystemExit(main())
