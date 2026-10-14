"""Real LoFreq Linux and portable-APE scientific/pack regression checks.

APE is executed on Linux through its loader. This is not a native Windows test.
Fixtures are synthetic truths, not a sensitivity/specificity benchmark.
"""
import hashlib, json, os, re, shutil, subprocess, sys, tarfile, tempfile, threading, unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];PACK=ROOT/'packs/lofreq-0.5.3';VENDOR=ROOT/'vendor-expanded/lofreq'
sys.path.insert(0,str(ROOT/'workspace'));sys.path.insert(0,str(ROOT/'tests'))
from catalog import load_catalog,load_pack
from engine import Engine
from pack_checks import _assert_output
from test_workspace_engine import PortableBackend
LOADER=ROOT/'baselines/bin/ape-loader-linux'

def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def rows(path):return [line.split('\t') for line in Path(path).read_text().splitlines() if line and not line.startswith('#')]

class LofreqTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        LOADER.chmod(LOADER.stat().st_mode|0o111)
        cls.pack=load_pack(PACK/'pack.ini');cls.schema=json.loads((PACK/'workbench-schema.json').read_text())
        cls.workspace=tempfile.TemporaryDirectory(prefix='lofreq app ',dir=VENDOR)
        cls.app=Path(cls.workspace.name);(cls.app/'packs').mkdir();shutil.copytree(PACK,cls.app/'packs/lofreq-0.5.3')
        cls.catalog=load_catalog(cls.app)
    @classmethod
    def tearDownClass(cls):cls.workspace.cleanup()
    def setUp(self):
        self.temporary=tempfile.TemporaryDirectory(prefix='LoFreq spaces & symbols ',dir=VENDOR);self.root=Path(self.temporary.name);self.counter=0
    def tearDown(self):self.temporary.cleanup()
    def command(self,tool,args,ape=True):
        binary=PACK/self.pack['tools'][tool]['path']
        return [str(LOADER),str(binary),*map(str,args)] if ape or tool!='lofreq' else [str(VENDOR/'lofreq-linux'),*map(str,args)]
    def run_workflow(self,identity,values,ape=True,expect_success=True):
        self.counter+=1;folder=self.root/str(self.counter);folder.mkdir();workflow=self.pack['workflows'][identity]
        inputs={f['id']:f.get('default','') for f in workflow['inputs']};inputs.update({k:str(v) for k,v in values.items()});outputs={o['id']:folder/o['path'] for o in workflow['outputs']}
        def expand(value):
            for kind,items in [('input',inputs),('output',outputs)]:
                for key,text in items.items():value=value.replace('{'+kind+':'+key+'}',str(text))
            return value
        failed=False
        for step in workflow['steps']:
            if step['kind']=='copy':shutil.copyfile(expand(step['source']),outputs[step['destination']]);continue
            result=subprocess.run(self.command(step['tool'],[expand(a) for a in step['args']],ape),cwd=folder,capture_output=True,timeout=60)
            (folder/(step['id']+'.stderr.log')).write_bytes(result.stderr)
            if result.returncode:
                failed=True
                if expect_success:self.fail(result.stderr.decode(errors='replace'))
                break
            if step.get('stdout'):outputs[step['stdout']].write_bytes(result.stdout)
        self.assertEqual(failed,not expect_success)
        if expect_success:
            for item in workflow['outputs']:
                self.assertTrue(outputs[item['id']].is_file(),item)
                if item['nonempty']:self.assertGreater(outputs[item['id']].stat().st_size,0)
        return outputs
    def inputs(self,indels=False):return {'alignment':PACK/'fixtures'/('indels.bam' if indels else 'snps.bam'),'reference':PACK/'fixtures/reference.fa'}
    def graph(self,identity='call-snps',values=None):
        values=values or self.inputs()
        return {'name':'LoFreq truth','nodes':[{'id':'step-1','tool':'lofreq/'+identity,'params':{},'inputs':{'alignment':['input-1'],'reference':['input-2']}}],'sources':[{'id':'input-1','type':'bam','files':{'alignment':str(values['alignment'])}},{'id':'input-2','type':'reference','files':{'reference':str(values['reference'])}}]}
    def test_pins_inventory_and_three_dynamic_workflows(self):
        self.assertEqual(len(self.pack['workflows']),3)
        for item in list(self.pack['tools'].values())+list(self.pack['assets'].values()):self.assertEqual(sha(PACK/item['path']),item['sha256'])
        allowed={'pack.ini','PACK-README.md'}|{i['path'] for i in list(self.pack['tools'].values())+list(self.pack['assets'].values())}
        items=list(PACK.rglob('*'));self.assertLessEqual(len(items),2000);self.assertLessEqual(sum(x.stat().st_size for x in items if x.is_file()),256*1024*1024)
        for path in items:
            self.assertFalse(path.is_symlink())
            if path.is_file():self.assertTrue(path.relative_to(PACK).as_posix() in allowed or path.relative_to(PACK).as_posix().startswith('licenses/'))
        self.assertEqual(self.catalog['tools']['lofreq/call-snps']['outputs'][0]['type'],'vcf-pass')
        self.assertEqual(self.catalog['tools']['lofreq/indelqual-dindel']['outputs'][0]['id'],'prepared')
    def test_native_selfchecks_exact_truth_linux_and_ape(self):
        for case in json.loads((PACK/'workbench-checks.json').read_text())['checks']:
            results=[]
            for ape in (False,True):
                with self.subTest(check=case['id'],ape=ape):
                    inputs={key:PACK/self.pack['assets'][value]['path'] for members in case['inputs'].values() for member in members for key,value in member.items()}
                    outputs=self.run_workflow(case['workflow'],inputs,ape)
                    result={'outputs':{'step-1::'+item['id']:{'files':{field:str(outputs[field]) for field in item['manifestOutputs']}} for item in self.schema['workflows'][case['workflow']]['outputs']}}
                    for expectation in case['expect']:_assert_output(expectation,result)
                    results.append(rows(outputs['variants']))
            self.assertEqual(results[0],results[1])
    def test_low_quality_error_rejected_even_when_base_filter_disabled(self):
        outputs=self.run_workflow('call-snps',self.inputs()|{'min-baseq':0})
        variants=rows(outputs['variants']);self.assertEqual(len(variants),1);self.assertEqual(variants[0][1:5],['150','.','A','C']);self.assertIn('AF=0.100000',variants[0][7])
    def test_quality_threshold_can_produce_valid_empty_vcf(self):
        outputs=self.run_workflow('call-snps',self.inputs()|{'min-baseq':50})
        self.assertEqual(rows(outputs['variants']),[]);self.assertIn('#CHROM\tPOS',outputs['variants'].read_text())
    def test_indelqual_preserves_reads_and_adds_equal_length_bi_bd(self):
        output=self.run_workflow('indelqual-dindel',self.inputs(True))
        before=subprocess.check_output(self.command('samtools',['view',self.inputs(True)['alignment']]),text=True).splitlines()
        after=subprocess.check_output(self.command('samtools',['view',output['prepared']]),text=True).splitlines()
        self.assertEqual(len(after),400)
        self.assertTrue(output['prepared-index'].name.endswith('.csi'))
        for left,right in zip(before,after):
            a,b=left.split('\t'),right.split('\t');self.assertEqual(a[:11],b[:11]);tags={x[:2]:x[5:] for x in b[11:]};self.assertEqual(len(tags['BI']),len(b[9]));self.assertEqual(len(tags['BD']),len(b[9]))
    def test_no_input_changes_or_indexes_and_private_temporary_cleanup(self):
        values={}
        for key,source in self.inputs().items():
            target=self.root/(key+' original '+Path(source).name);shutil.copyfile(source,target);values[key]=target
        before={key:sha(path) for key,path in values.items()};output=self.run_workflow('call-snps',values)
        self.assertEqual(before,{key:sha(path) for key,path in values.items()});self.assertFalse(Path(str(values['reference'])+'.fai').exists());self.assertFalse(Path(str(values['alignment'])+'.bai').exists())
        self.assertFalse(list(output['variants'].parent.glob('lofreq2-call-dyn-bonf.*')))
    def test_graph_engine_runs_real_pack_and_keeps_truth(self):
        engine=Engine(self.app,self.catalog,PortableBackend(self.app));graph=self.graph();review=engine.review(graph);self.assertTrue(review['valid'],review)
        record=engine.execute(engine.prepare(graph,self.root));self.assertTrue(record['success'],record)
        path=record['outputs']['step-1::variants']['files']['variants'];self.assertEqual(rows(path)[0][1:5],['150','.','A','C'])
        self.assertIn('not sample genotypes',record['methods'])
    def test_impossible_coverage_and_depth_rejected_before_running(self):
        graph=self.graph();graph['nodes'][0]['params']={'min-coverage':'200','max-depth':'100'}
        review=Engine(self.app,self.catalog,PortableBackend(self.app)).review(graph)
        self.assertFalse(review['valid']);self.assertIn('coverage',str(review['issues']).lower())
    def test_reference_dictionary_mismatch_fails_without_outputs(self):
        reference=self.root/'wrong.fa';reference.write_text('>other\n'+'A'*500+'\n');graph=self.graph(values=self.inputs()|{'reference':reference});engine=Engine(self.app,self.catalog,PortableBackend(self.app));record=engine.execute(engine.prepare(graph,self.root));self.assertFalse(record['success']);self.assertEqual(record['outputs'],{});self.assertIn('reference',record['nodes'][0]['message'].lower())
    def test_truncated_bam_fails_before_calling(self):
        path=self.root/'truncated.bam';path.write_bytes(self.inputs()['alignment'].read_bytes()[:-100]);outputs=self.run_workflow('call-snps',self.inputs()|{'alignment':path},expect_success=False);self.assertFalse(outputs['variants'].exists())
    def test_spliced_cigar_rejected_for_dindel(self):
        source=(PACK/'fixtures/snps.sam').read_text().splitlines();record=source[3].split('\t');record[5]='100M10N150M';path=self.root/'spliced.sam';path.write_text('\n'.join(source[:3]+['\t'.join(record)])+'\n');bam=self.root/'spliced.bam';subprocess.run(self.command('samtools',['view','-b','-o',bam,path]),check=True)
        outputs=self.run_workflow('call-variants',self.inputs()|{'alignment':bam},expect_success=False);self.assertFalse(outputs['variants'].exists())
    def test_filtered_source_and_binary_omit_unused_cdf(self):
        with tarfile.open(PACK/'licenses/lofreq-2.1.5-source-subset.tar.gz') as archive:
            self.assertFalse(any('/dist/' in m.name or '/src/cdflib90/' in m.name for m in archive.getmembers()))
        for binary in (VENDOR/'lofreq-linux',VENDOR/'lofreq-cosmo.exe.dbg'):
            symbols=subprocess.check_output(['nm',str(binary)],text=True)
            for name in ('cdfbin','cdfbet','bratio','main_uniq','binom'):self.assertNotRegex(symbols,r'(?m)\s'+name+r'$')
        for ape in (False,True):
            result=subprocess.run(self.command('lofreq',['uniq'],ape),capture_output=True,text=True);self.assertNotEqual(result.returncode,0);self.assertIn('unavailable',result.stderr)
    def test_original_shell_filter_and_direct_dispatch_scientifically_equal(self):
        original=VENDOR/'lofreq-original-filter-linux';self.assertTrue(original.exists(),'Build the documented original-filter Linux comparator first')
        bin_dir=self.root/'upstream-bin';bin_dir.mkdir();shutil.copy2(original,bin_dir/'lofreq');env={**os.environ,'PATH':str(bin_dir)+os.pathsep+os.environ['PATH']}
        # Upstream shell cannot handle spaces; its comparator needs private paths
        # without spaces. The port is separately exercised with space/& paths.
        with tempfile.TemporaryDirectory(prefix='lf-original-',dir=VENDOR) as temporary:
            folder=Path(temporary);shutil.copyfile(PACK/'fixtures/reference.fa',folder/'ref.fa');shutil.copyfile(PACK/'fixtures/snps.bam',folder/'in.bam')
            subprocess.run(self.command('samtools',['faidx',folder/'ref.fa']),check=True)
            result=subprocess.run([str(bin_dir/'lofreq'),'call','-f','ref.fa','-o','out.vcf','in.bam'],cwd=folder,env=env,capture_output=True,text=True);self.assertEqual(result.returncode,0,result.stderr)
            port=self.run_workflow('call-snps',self.inputs()|{'min-mapq':0,'min-baseq':6,'min-coverage':10})
            self.assertEqual(rows(folder/'out.vcf'),rows(port['variants']))
if __name__=='__main__':unittest.main(verbosity=2)
