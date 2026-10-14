"""Real 0.5.3 aligner/caller DAG tests; Linux execution is not Windows evidence.

NW_APP_ROOT selects an assembled runtime. Bowtie2/HISAT2 use separately pinned
Linux reference builds. SAMtools, BCFtools, paircheck and LoFreq execute their
actual packaged portable binaries through the pinned APE loader.
"""
import copy
import gzip
import json
import os
from pathlib import Path
import random
import shutil
import subprocess
import sys
import tempfile
import unittest

SOURCE=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(SOURCE/'workspace'))
from catalog import load_catalog, parse_pack
from engine import Engine, digest_file
from pack_checks import run_pack_checks
from verify_installation import check_packs
from test_expansion_pipeline import BINARIES as SEQUENCE_BINARIES

APP=Path(os.environ.get('NW_APP_ROOT',SOURCE.parents[1]/'integration-0.5.3/native-workbench')).resolve()
LOADER=SOURCE/'baselines/bin/ape-loader-linux'
LOADER_SHA='ad98161cba98163f6aa383595804489cec52a9ff3b902be16b29368e171ba359'
BOWTIE=SOURCE.parents[1]/'expansion-vendor/bowtie2/linux-bin'
HISAT=SOURCE/'vendor-expanded/hisat2/build-linux'
JAVA_HOME=SOURCE/'build/vardict/linux-jre/jdk8u504-b01-jre'
SUBSTITUTIONS={
    ('bowtie2','align-s'):(BOWTIE/'bowtie2-align-s','e24a717f95d4d1403f69844ebd257f1d3b14c600679a2943fd2a3161f2ec0dab'),
    ('bowtie2','align-l'):(BOWTIE/'bowtie2-align-l','39bbceff23a89acddc7ea4c6deab10757c6ac37fc1ac4f0888d562a92a293b7b'),
    ('bowtie2','build-s'):(BOWTIE/'bowtie2-build-s','4006e604ca4e2146a6f0c8be40993c7590df68a001ae35b50fb1496ef7e20f2c'),
    ('bowtie2','build-l'):(BOWTIE/'bowtie2-build-l','a7a57dc4bd2232855ed6bff928a968563a3326c5b4c0feddefdc86f1c360e24a'),
    ('hisat2','hisat2-align-l'):(HISAT/'hisat2-align-l','95675bc96e8914f60c41fdee9000211ef2414461e9e21d508f382156ae9d2eae'),
    ('hisat2','hisat2-build-l'):(HISAT/'hisat2-build-l','0d63724b08d0ebea41b8a161406253b12a1b91301088bdfbc751295b8d312200'),
    ('vardict','java'):(JAVA_HOME/'bin/java','1a081a2c18367e5d966d716a6091d5fe2eec26b19e471980d0d8fd550174e21c'),
    ('vardict','perl'):(SOURCE/'build/vardict/perl-source/perl-5.42.3/perl','d6de08d1b4c2b77d932f933de839e3a24d8843a816b99bbdc11b4950306ca8d2'),
}
SUBSTITUTIONS.update({(name,name):value for name,value in SEQUENCE_BINARIES.items()})
PORTABLE={'samtools','bcftools','paircheck','lofreq'}


class ReferenceBackend:
    def __init__(self):
        self.calls=[]
        self.commands=[]
        if digest_file(LOADER)!=LOADER_SHA:
            raise ValueError('APE validation loader differs')
        for key,(path,sha) in SUBSTITUTIONS.items():
            if not path.is_file() or digest_file(path)!=sha:
                raise ValueError('Required pinned Linux reference binary missing or changed: '+str(key))

    def inspect_alignment(self,executable,path,cancel):
        if cancel.is_set():
            raise InterruptedError('Cancelled before checking header')
        return subprocess.run([str(LOADER),str(executable),'view','-H',str(path)],
                              check=True,capture_output=True,text=True,timeout=45).stdout

    def run(self,request,event,cancel):
        self.calls.append(copy.deepcopy(request))
        root=Path(request['pack_folder'])
        if digest_file(root/'pack.ini')!=request['pack_sha256']:
            raise ValueError('Manifest changed before execution')
        pack=parse_pack((root/'pack.ini').read_text(encoding='utf-8'))
        workflow=pack['workflows'][request['workflow_id']]
        folder=Path(request['output_folder'])/'linux-reference'
        folder.mkdir()
        outputs={o['id']:str(folder/o['path']) for o in workflow['outputs']}
        assets={k:str(root/v['path']) for k,v in pack['assets'].items()}
        for path in outputs.values():
            Path(path).parent.mkdir(parents=True,exist_ok=True)

        def expand(value):
            value=value.replace('{run}',str(folder))
            for kind,bindings in (('input',request['values']),('output',outputs),('asset',assets)):
                for key,replacement in bindings.items():
                    value=value.replace('{'+kind+':'+key+'}',str(replacement))
            if '{' in value or '}' in value:
                raise ValueError('Unexpanded manifest argument: '+value)
            return value

        def command(identity,args):
            declared=pack['tools'][identity]
            executable=root/declared['path']
            if digest_file(executable)!=declared['sha256']:
                raise ValueError('Declared executable hash differs')
            substitution=SUBSTITUTIONS.get((pack['id'],identity))
            if substitution:
                path,expected=substitution
                if digest_file(path)!=expected:
                    raise ValueError('Reference executable hash differs')
                argv=[str(path)]
            elif identity in PORTABLE:
                argv=[str(LOADER),str(executable)]
            else:
                raise ValueError('No explicit Linux validation mapping for '+pack['id']+'/'+identity)
            for arg in args:
                if arg.startswith('{inputs:') and arg.endswith('}'):
                    argv.extend(str(request['values'][arg[8:-1]]).splitlines())
                else:
                    argv.append(expand(arg))
            if pack['id']=='vardict' and identity=='java':
                # The manifest is for Windows. Only the JVM classpath separator
                # is platform syntax; preserve every biological argument.
                at=argv.index('-cp')+1
                argv[at]=argv[at].replace(';',os.pathsep)
            self.commands.append(argv)
            return argv

        def environment(argv):
            blocked={'JAVA_TOOL_OPTIONS','_JAVA_OPTIONS','JDK_JAVA_OPTIONS','CLASSPATH','PERL5OPT','PERL5LIB',
                     'PERLLIB','PERL5SHELL','PERL_UNICODE','PERLIO','PERLIO_DEBUG'}
            result={k:v for k,v in os.environ.items() if k.upper() not in blocked}
            if argv[0]==str(JAVA_HOME/'bin/java'):
                result['LD_LIBRARY_PATH']=os.pathsep.join(str(JAVA_HOME/p) for p in ('lib/amd64/jli','lib/amd64/server','lib/amd64'))
                result['JAVA_HOME']=str(JAVA_HOME)
            return result
        try:
            for step in workflow['steps']:
                if cancel.is_set():
                    return {'success':False,'cancelled':True,'folder':str(folder)}
                event({'type':'phase','message':step['label']})
                if step['kind']=='copy':
                    shutil.copyfile(expand(step['source']),outputs[step['destination']])
                    continue
                out=Path(outputs[step['stdout']]) if step.get('stdout') else folder/(step['id']+'.stdout.txt')
                err=folder/(step['id']+'.stderr.txt')
                with out.open('wb') as stdout,err.open('wb') as stderr:
                    if step['kind']=='pipe':
                        first=command(step['tool'],step['args']);second=command(step['sinkTool'],step['sinkArgs'])
                        producer=subprocess.Popen(first,cwd=folder,stdout=subprocess.PIPE,stderr=stderr,env=environment(first))
                        sink=subprocess.Popen(second,cwd=folder,stdin=producer.stdout,stdout=stdout,stderr=stderr,env=environment(second))
                        producer.stdout.close()
                        try:
                            codes=(sink.wait(timeout=90),producer.wait(timeout=90))
                        finally:
                            for process in (sink,producer):
                                if process.poll() is None:
                                    process.kill();process.wait()
                        if any(codes):
                            raise ValueError('Manifest pipe failed: '+str(codes))
                    else:
                        argv=command(step['tool'],step['args'])
                        completed=subprocess.run(argv,cwd=folder,stdout=stdout,stderr=stderr,timeout=90,env=environment(argv))
                        if completed.returncode:
                            raise ValueError('Manifest command failed ('+str(completed.returncode)+'): '+err.read_text(errors='replace')[-4000:])
            for output in workflow['outputs']:
                path=Path(outputs[output['id']])
                if not path.is_file() or (output['nonempty'] and not path.stat().st_size):
                    raise ValueError('Expected declared output missing or empty: '+output['id'])
            return {'success':True,'folder':str(folder),'message':'Actual scientific manifest completed on Linux reference backend'}
        except Exception as exc:
            return {'success':False,'folder':str(folder),'message':str(exc)}


def node(identity,tool,inputs,params=None,label=None):
    return {'id':identity,'tool':tool,'inputs':inputs,'params':params or {},'label':label or ''}


def output_path(record,ref,field=None):
    files=record['outputs'][ref]['files']
    return Path(files[field] if field else next(iter(files.values())))


def vcf_rows(path):
    with path.open('rb') as stream:
        compressed=stream.read(2)==b'\x1f\x8b'
    with (gzip.open(path,'rt') if compressed else path.open()) as stream:
        return [line.rstrip('\n').split('\t') for line in stream if line and not line.startswith('#')]


class AlignerCallerPipelineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog=load_catalog(APP)
        check_packs(APP,cls.catalog)
        cls.executed_graphs=[]
        cls.selfchecks=[]
        for pack in ('bowtie2','hisat2','lofreq','vardict'):
            if not any(tool['packId']==pack for tool in cls.catalog['tools'].values()):
                raise RuntimeError('Required new pack is missing: '+pack)

    def setUp(self):
        self.temporary=tempfile.TemporaryDirectory(prefix='aligner-caller-')
        self.folder=Path(self.temporary.name)
        self.backend=ReferenceBackend()
        self.engine=Engine(APP,self.catalog,self.backend)
        randomizer=random.Random(531)
        sequence=''.join(randomizer.choice('ACGT') for _ in range(1800))
        self.position=600
        self.reference_base=sequence[self.position-1]
        self.alternate_base={'A':'C','C':'T','G':'A','T':'G'}[self.reference_base]
        self.reference=self.folder/'reference.fa'
        self.reference.write_text('>chrTest\n'+sequence+'\n')
        self.reads1,self.reads2=self.folder/'r1.fastq',self.folder/'r2.fastq'
        reverse=str.maketrans('ACGT','TGCA')
        with self.reads1.open('w') as one,self.reads2.open('w') as two:
            for i in range(60):
                start=520+i if i<30 else 320+i-30
                fragment=sequence[start-1:start-1+300]
                if i%5==0:
                    offset=self.position-start
                    fragment=fragment[:offset]+self.alternate_base+fragment[offset+1:]
                r1,r2=fragment[:100],fragment[-100:].translate(reverse)[::-1]
                one.write('@pair'+str(i)+'/1\n'+r1+'\n+\n'+'I'*100+'\n')
                two.write('@pair'+str(i)+'/2\n'+r2+'\n+\n'+'I'*100+'\n')
        self.sources=[{'id':'input-1','type':'pair','label':'Sixty pairs; 20 percent SNP alleles','files':{'reads1':str(self.reads1),'reads2':str(self.reads2)}},
                      {'id':'input-2','type':'reference','label':'Known synthetic reference','files':{'reference':str(self.reference)}}]
        self.targets=self.folder/'targets.bed'
        self.targets.write_text('chrTest\t450\t700\tknown_variant_region\n')

    def tearDown(self):
        self.temporary.cleanup()

    def graph(self,aligner='bowtie2/paired-end'):
        alignment='sam' if aligner.startswith('bowtie2/') else 'aligned'
        return {'name':'Known 20 percent SNP from '+aligner,'sources':copy.deepcopy(self.sources),
                'nodes':[node('step-1',aligner,{'reads':['input-1'],'reference':['input-2']},
                              {'sample':'validation','read-group':'lane1','threads':'1'},'Map the known read pairs'),
                         node('step-2','bam/prepare',{'alignment':['step-1::'+alignment]},label='Prepare DNA alignments'),
                         node('step-3','lofreq/call-snps',{'alignment':['step-2::bam'],'reference':['input-2']},label='Call low-frequency SNPs')]}

    def execute(self,graph):
        review=self.engine.review(graph)
        self.assertTrue(review['valid'],review)
        plan=self.engine.prepare(graph,self.folder)
        result=self.engine.execute(plan)
        self.assertTrue(result['success'],[(n['id'],n['status'],n.get('message')) for n in result['nodes']])
        self.__class__.executed_graphs.append({'name':graph['name'],'planSha256':plan['sha256'],
            'nodes':[{'id':n['id'],'tool':n['tool'],'pin':n['pin'],'status':n['status']}for n in result['nodes']],
            'outputs':{ref:{'type':o['type'],'sha256':o['sha256']}for ref,o in result['outputs'].items()},'methods':result['methods']})
        return plan,result

    def assert_snp(self,result,reference):
        rows=vcf_rows(output_path(result,reference))
        self.assertEqual([(r[0],int(r[1]),r[3],r[4])for r in rows],
                         [('chrTest',self.position,self.reference_base,self.alternate_base)])
        info=dict(item.split('=',1)for item in rows[0][7].split(';')if'='in item)
        self.assertEqual(int(info['DP']),60)
        self.assertAlmostEqual(float(info['AF']),0.2,places=5)

    def test_bowtie2_to_prepared_bam_to_lofreq_calls_known_snp(self):
        _,result=self.execute(self.graph())
        self.assert_snp(result,'step-3::variants')
        self.assertIn('LoFreq',result['methods'])

    def test_hisat2_dna_to_prepared_bam_to_lofreq_calls_known_snp(self):
        _,result=self.execute(self.graph('hisat2/dna-paired'))
        self.assert_snp(result,'step-3::variants')
        self.assertTrue(any('--no-spliced-alignment' in command for command in self.backend.commands))

    def test_both_aligners_form_same_rank_branches_with_distinct_reports(self):
        graph=self.graph()
        graph['name']='Compare aligners with separately attributed SNP reports'
        graph['nodes'].extend([
            node('step-4','hisat2/dna-paired',{'reads':['input-1'],'reference':['input-2']},{'sample':'validation','read-group':'lane1','threads':'1'},'HISAT2 DNA branch'),
            node('step-5','bam/prepare',{'alignment':['step-4::aligned']}),
            node('step-6','lofreq/call-snps',{'alignment':['step-5::bam'],'reference':['input-2']}),
            node('step-7','variants/statistics',{'variants':['step-3::variants']},label='Bowtie2-based calls'),
            node('step-8','variants/statistics',{'variants':['step-6::variants']},label='HISAT2-based calls'),
            node('step-9','builtin/report',{'metrics':['step-7::statistics','step-8::statistics']},{'title':'Separate aligner results'}),
        ])
        self.assertEqual(self.engine.rank_groups(graph),[{'rank':1,'nodes':['step-1','step-4']},{'rank':2,'nodes':['step-2','step-5']},
            {'rank':3,'nodes':['step-3','step-6']},{'rank':4,'nodes':['step-7','step-8']},{'rank':5,'nodes':['step-9']}])
        _,result=self.execute(graph)
        self.assert_snp(result,'step-3::variants');self.assert_snp(result,'step-6::variants')
        report=output_path(result,'step-9::report').read_text()
        self.assertEqual(report.count('<section>'),2)
        self.assertIn('Bowtie2-based calls',report);self.assertIn('HISAT2-based calls',report)

    def test_rna_products_and_inconsistent_reference_slots_cannot_feed_dna_caller(self):
        graph=self.graph('hisat2/rna-paired')
        result=self.engine.validate(graph)
        self.assertFalse(result['valid'])
        self.assertTrue(any('bam-rna cannot feed bam' in e['message']for e in result['errors']),result)
        graph=self.graph()
        graph['sources'].append(dict(self.sources[1],id='input-3'))
        graph['nodes'][2]['inputs']['reference']=['input-3']
        result=self.engine.validate(graph)
        self.assertFalse(result['valid'])
        self.assertTrue(any('different reference input slots' in e['message']for e in result['errors']),result)

    def test_new_families_pass_all_declared_native_fixture_assertions(self):
        families={'bowtie2','hisat2','lofreq','vardict','seqkit','vsearch','muscle'}
        # This adapter pins the seven 0.5.2/0.5.3 families. Later packs have
        # their own executable mappings and scientific self-check suites.
        selected=dict(self.catalog,tools={identity:tool for identity,tool in self.catalog['tools'].items()
                                         if tool.get('packId') in families})
        report=run_pack_checks(APP,selected,self.folder,backend=self.backend)
        self.__class__.selfchecks=[{key:case[key]for key in ('id','status','message')if key in case}for case in report['checks']]
        self.assertTrue(report['success'],self.selfchecks)
        for family in families:
            self.assertTrue(any(case['id'].startswith(family+'/')for case in report['checks']),family+' lacks a scientific self-check')
        self.assertFalse(report['nativeWindowsExecuted'])

    def test_shared_bam_branches_to_lofreq_and_vardict_without_pooling_calls(self):
        graph=self.graph()
        graph['name']='Independent callers on the same prepared BAM'
        graph['sources'].append({'id':'input-3','type':'bed','label':'Known target interval','files':{'targets':str(self.targets)}})
        graph['nodes'].extend([
            node('step-4','vardict/call',{'alignment':['step-2::bam'],'reference':['input-2'],'targets':['input-3']},
                 {'sample':'validation','threads':'1'},'VarDict targeted calls'),
            node('step-5','variants/statistics',{'variants':['step-3::variants']},label='LoFreq call statistics'),
            node('step-6','builtin/report',{'metrics':['step-5::statistics','step-4::variant-stats']},{'title':'Independent caller results'}),
        ])
        self.assertEqual(self.engine.rank_groups(graph),[{'rank':1,'nodes':['step-1']},{'rank':2,'nodes':['step-2']},
            {'rank':3,'nodes':['step-3','step-4']},{'rank':4,'nodes':['step-5']},{'rank':5,'nodes':['step-6']}])
        _,result=self.execute(graph)
        self.assert_snp(result,'step-3::variants')
        vardict=vcf_rows(output_path(result,'step-4::variants'))
        self.assertEqual([(row[0],int(row[1]),row[3],row[4])for row in vardict],
                         [('chrTest',self.position,self.reference_base,self.alternate_base)])
        self.assertEqual(len(vardict[0]),10,'VarDict has one sample, while LoFreq remains site-only')
        self.assertEqual(len(vcf_rows(output_path(result,'step-3::variants'))[0]),8)
        report=output_path(result,'step-6::report').read_text()
        self.assertEqual(report.count('<section>'),2)
        self.assertIn('VarDict targeted calls',report);self.assertIn('LoFreq call statistics',report)
        self.assertIn('EXPERIMENTAL',result['methods'])


if __name__=='__main__':
    unittest.main()
