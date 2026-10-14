"""featureCounts science and input-boundary tests; Linux is not Windows evidence."""
import json, os, shutil, subprocess, sys, tempfile, unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
CACHE=Path(os.environ.get('NW_FEATURECOUNTS_CACHE',ROOT.parent/'popular-build/featurecounts'))
PACK=ROOT/'packs/featurecounts-1.0.0'
sys.path.insert(0,str(ROOT/'scripts'));from prepare_featurecounts_pack import definitions, fixtures, bam_bytes, checks
sys.path.insert(0,str(ROOT/'workspace'));from catalog import load_pack

class FeatureCountsDeclarations(unittest.TestCase):
    def test_library_choice_is_explicit_and_rna_state_is_typed(self):
        workflows,schema=definitions()
        for wf in workflows:
            fields={x['id']:x for x in wf['inputs']}
            self.assertNotIn('default',fields['strandness'])
            self.assertEqual(schema['workflows'][wf['id']]['ports'][0]['type'],'bam-rna')
            self.assertEqual(schema['workflows'][wf['id']]['ports'][0]['requiredState']['pairing'],wf['id'].split('-')[1])
            args=[value for key,value in wf['steps'][-1].items() if key.startswith('arg.')]
            if wf['id'].endswith('paired'):
                for flag in ('-p','--countReadPairs','-B','-C'):self.assertIn(flag,args)
            else:self.assertNotIn('--countReadPairs',args)

@unittest.skipUnless((CACHE/'build-linux/featureCounts').is_file() and (PACK/'pack.ini').is_file(),'Build Linux reference/guard and prepare pack first')
class FeatureCountsScience(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory(prefix='featureCounts scientific paths ')
        cls.root=Path(cls.temp.name); cls.fixtures=cls.root/'inputs with spaces';fixtures(cls.fixtures)
        cls.bin=cls.root/'tools with spaces';cls.bin.mkdir()
        for name in ('featureCounts','featurecounts-guard'):shutil.copy2(CACHE/'build-linux'/name,cls.bin/name)
        cls.pack=load_pack(PACK/'pack.ini');cls.counter=0
        cls.truth=json.loads((cls.fixtures/'truth.json').read_text())
    @classmethod
    def tearDownClass(cls):cls.temp.cleanup()
    @staticmethod
    def invoke(args,okay=True):
        result=subprocess.run([str(x) for x in args],capture_output=True,text=True,timeout=120)
        if okay and result.returncode:raise AssertionError(result.stdout+result.stderr)
        return result
    def run_workflow(self,mode,strand='0',mapq=0,threads=2,bam=None):
        type(self).counter+=1;out=self.root/('output with spaces '+str(self.counter));out.mkdir()
        wf=self.pack['workflows']['count-'+mode]
        inputs={'alignment':str(bam or self.fixtures/(mode+'.bam')),'annotation':str(self.fixtures/'genes.gtf'),'strandness':strand,'threads':str(threads),'mapq':str(mapq)}
        outputs={x['id']:str(out/x['path']) for x in wf['outputs']}
        for step in wf['steps']:
            args=[]
            for argument in step['args']:
                for k,v in inputs.items():argument=argument.replace('{input:'+k+'}',v)
                for k,v in outputs.items():argument=argument.replace('{output:'+k+'}',v)
                argument=argument.replace('{run}',str(out));self.assertNotIn('{',argument);args.append(argument)
            binary='featureCounts' if step['tool']=='featurecounts' else step['tool']
            result=self.invoke([self.bin/binary,*args])
            if step.get('stdout'):Path(outputs[step['stdout']]).write_text(result.stdout)
        counts={}
        for line in Path(outputs['counts']).read_text().splitlines():
            if line.startswith('#') or line.startswith('Geneid'):continue
            fields=line.split('\t');counts[fields[0]]=int(fields[-1])
        summary={line.split('\t')[0]:int(line.split('\t')[1]) for line in Path(outputs['summary']).read_text().splitlines()[1:]}
        return counts,summary,out
    def test_all_strand_modes_and_both_manifest_operations(self):
        for mode in ('single','paired'):
            for strand in ('0','1','2'):
                with self.subTest(mode=mode,strand=strand):
                    counts,summary,out=self.run_workflow(mode,strand)
                    self.assertEqual(counts,dict(zip(self.truth['genes'],self.truth[mode][strand])))
                    self.assertEqual(summary['Assigned'],sum(counts.values()))
                    self.assertEqual(summary['Unassigned_MultiMapping'],1)
                    self.assertEqual(summary['Unassigned_Secondary'],1)
                    self.assertEqual(summary['Unassigned_Duplicate'],0)
                    if mode=='paired':
                        self.assertEqual(summary['Unassigned_Singleton'],1);self.assertEqual(summary['Unassigned_Chimera'],1)
                    self.assertTrue(json.loads((out/'input-validation.json').read_text())['valid'])
    def test_mapq_and_thread_counts_preserve_known_assignment(self):
        for threads in (1,2,4):
            counts,summary,_=self.run_workflow('single',mapq=20,threads=threads)
            self.assertEqual(counts,{'geneA':3,'geneB':1,'geneC':1,'geneD':0,'geneE':0})
            self.assertEqual(summary['Unassigned_MappingQuality'],1)
    def test_windows_text_assertions_keep_exact_crlf_count_boundaries(self):
        from pack_checks import _assert_output
        for check in checks()['checks']:
            mode=check['workflow'].split('-')[1]
            _,_,out=self.run_workflow(mode,check['params']['strandness'])
            paths={'counts':out/'gene-counts.tsv','summary':out/'gene-counts.tsv.summary','input-check':out/'input-validation.json'}
            # Model native Windows C text-mode writes without changing any cells.
            # Guard JSON deliberately does not need a platform-specific terminator.
            for name in ('counts','summary'):
                paths[name].write_bytes(paths[name].read_bytes().replace(b'\n',b'\r\n'))
            result={'outputs':{'step-1::'+name:{'files':{name:str(path)}} for name,path in paths.items()}}
            for expectation in check['expect']:_assert_output(expectation,result)
            # 4 must not match 40, and no ordinary LF-only suffix can match CRLF.
            expected=check['expect'][0]['contains'][1]
            self.assertTrue(expected.endswith('\r\n'))
            self.assertNotIn(expected.replace('\r\n','\n'),paths['counts'].read_bytes().decode())
            raw=paths['counts'].read_bytes(); needle=expected.encode()
            paths['counts'].write_bytes(raw.replace(needle,needle[:-2]+b'0\r\n',1))
            with self.assertRaises(ValueError):_assert_output(check['expect'][0],result)
    def test_legitimate_zero_counts_are_retained(self):
        bam=self.root/'intergenic.bam';bam.write_bytes(bam_bytes([('outside',0,1000,[(20,'M')],0,0,1,60)]))
        counts,summary,_=self.run_workflow('single',bam=bam)
        self.assertEqual(set(counts.values()),{0});self.assertEqual(summary['Unassigned_NoFeatures'],1)
    def test_wrong_pair_mode_supplementary_and_truncation_are_rejected(self):
        cases=[('wrong mode',self.fixtures/'paired.bam','single')]
        extra=self.root/'supplementary.bam';extra.write_bytes(bam_bytes([('supplementary',2048,120,[(20,'M')],0,0,1,60)]));cases.append(('supplementary',extra,'single'))
        truncated=self.root/'truncated.bam';truncated.write_bytes((self.fixtures/'single.bam').read_bytes()[:60]);cases.append(('truncated',truncated,'single'))
        for label,bam,mode in cases:
            with self.subTest(case=label):self.assertNotEqual(self.invoke([self.bin/'featurecounts-guard',mode,bam,self.fixtures/'genes.gtf'],okay=False).returncode,0)
    def test_mismatched_annotation_bounds_and_gene_attributes_are_rejected(self):
        text=(self.fixtures/'genes.gtf').read_text()
        for label,bad in [('contig',text.replace('chr1','chrWrong')),('bounds',text.replace('\t199\t','\t2999\t')),('gene',text.replace('gene_id','unknown_attribute')),('strand',text.replace('\t+\t','\t.\t'))]:
            path=self.root/(label+'.gtf');path.write_text(bad)
            with self.subTest(case=label):self.assertNotEqual(self.invoke([self.bin/'featurecounts-guard','single',self.fixtures/'single.bam',path],okay=False).returncode,0)
    def test_upstream_version_is_real_and_unmodified(self):
        result=self.invoke([self.bin/'featureCounts','-v']);self.assertIn('featureCounts v2.1.1',result.stdout+result.stderr)
        build=json.loads((CACHE/'build-windows/build.json').read_text());self.assertTrue(build['upstreamBinaryUnmodified'])
        self.assertEqual(build['version'],'2.1.1')

if __name__=='__main__':unittest.main(verbosity=2)
