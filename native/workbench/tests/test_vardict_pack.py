"""Real pinned Linux VarDict/Java/Perl tests of Windows pack argv and graph rules.

Windows binaries are inspected, not executed by this test adapter. The two
declared installation checks execute the actual Windows pack on a user's PC.
"""
import copy
import gzip
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
import zipfile

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'workspace'))
from catalog import load_pack, describe_workflow
from engine import Engine, pin_for
from pack_checks import run_pack_checks
PACK=ROOT/'packs/vardict-0.5.3'
JAVA_HOME=ROOT/'build/vardict/linux-jre/jdk8u504-b01-jre'
PERL=ROOT/'build/vardict/perl-source/perl-5.42.3/perl'


class LinuxReferenceBackend:
    def __init__(self):
        self.calls=[]
        self.executables={'java':JAVA_HOME/'bin/java','perl':PERL,'samtools':ROOT/'baselines/bin/samtools-linux','bcftools':ROOT/'baselines/bin/bcftools-linux'}
        self.environment={k:v for k,v in os.environ.items() if k not in {'JAVA_TOOL_OPTIONS','_JAVA_OPTIONS','JDK_JAVA_OPTIONS','PERL5OPT','PERL5LIB','PERLLIB','PERL_UNICODE'}}
        self.environment.update(LD_LIBRARY_PATH=':'.join(str(JAVA_HOME/p) for p in ('lib/amd64/jli','lib/amd64/server','lib/amd64')),JAVA_HOME=str(JAVA_HOME))
        for path in self.executables.values():path.chmod(path.stat().st_mode|0o100)
    def inspect_alignment(self,executable,path,cancel):
        return subprocess.check_output([str(self.executables['samtools']),'view','-H',str(path)],text=True)
    def run(self,request,event,cancel):
        self.calls.append(request)
        pack_root=Path(request['pack_folder']);pack=load_pack(pack_root/'pack.ini');wf=pack['workflows'][request['workflow_id']]
        folder=Path(request['output_folder'])/'linux reference execution';folder.mkdir()
        outputs={item['id']:folder/item['path'] for item in wf['outputs']}
        assets={key:pack_root/value['path'] for key,value in pack['assets'].items()}
        def expand(arg):
            arg=arg.replace('{run}',str(folder))
            for kind,values in [('input',request['values']),('output',outputs),('asset',assets)]:
                for key,value in values.items():arg=arg.replace('{'+kind+':'+key+'}',str(value))
            return arg
        try:
            for step in wf['steps']:
                if cancel.is_set():return {'success':False,'cancelled':True,'folder':str(folder)}
                if step['kind']=='copy':shutil.copyfile(expand(step['source']),outputs[step['destination']]);continue
                argv=[expand(arg) for arg in step['args']]
                if step['tool']=='java':
                    argv[argv.index('-cp')+1]=argv[argv.index('-cp')+1].replace(';',os.pathsep)
                result=subprocess.run([str(self.executables[step['tool']])]+argv,cwd=folder,env=self.environment,capture_output=True,timeout=60)
                (folder/(step['id']+'.stderr')).write_bytes(result.stderr)
                if step.get('stdout'):outputs[step['stdout']].write_bytes(result.stdout)
                if result.returncode:raise RuntimeError(step['id']+': '+result.stderr.decode(errors='replace'))
            return {'success':True,'folder':str(folder),'message':'Linux reference argv completed'}
        except Exception as exc:return {'success':False,'folder':str(folder),'message':str(exc)}


def catalog():
    pack=load_pack(PACK/'pack.ini')
    tool=describe_workflow(pack,pack['workflows']['call'],'packs/vardict-0.5.3',pack['manifestSha256'])
    return {'schema':1,'tools':{'vardict/call':tool},'packs':[{'id':'vardict','version':'0.5.3','folder':'packs/vardict-0.5.3','manifestSha256':pack['manifestSha256']}],'types':{}}


class VardictTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog=catalog()
    def setUp(self):
        self.temporary=tempfile.TemporaryDirectory(prefix='vardict science ')
        self.folder=Path(self.temporary.name)
        self.backend=LinuxReferenceBackend()
        self.engine=Engine(ROOT,self.catalog,self.backend)
        self.graph={'schema':1,'name':'VarDict fixture','nodes':[{'id':'step-1','tool':'vardict/call','pin':pin_for(self.catalog['tools']['vardict/call']),'params':{'sample':'validation'},'inputs':{'alignment':['input-1'],'reference':['input-2'],'targets':['input-3']}}],
          'sources':[{'id':'input-1','type':'bam','label':'BAM','files':{'alignment':str(PACK/'fixtures/input.bam')}},
            {'id':'input-2','type':'reference','label':'Reference','files':{'reference':str(PACK/'fixtures/reference.fa')}},
            {'id':'input-3','type':'bed','label':'Targets','files':{'targets':str(PACK/'fixtures/targets.bed')}}], 'nextNode':2,'nextSource':4}
    def tearDown(self):self.temporary.cleanup()
    def run_graph(self):
        plan=self.engine.prepare(self.graph,self.folder)
        result=self.engine.execute(plan)
        self.assertTrue(result['success'],result)
        return result
    def variants(self,result):
        path=next(iter(result['outputs']['step-1::variants']['files'].values()))
        with gzip.open(path,'rt') as stream:return [line.rstrip().split('\t') for line in stream if not line.startswith('#')]
    def reject(self):
        try:plan=self.engine.prepare(self.graph,self.folder)
        except ValueError as exc:return str(exc)
        result=self.engine.execute(plan)
        self.assertFalse(result['success'],result)
        self.assertEqual(self.backend.calls,[])
        return str(result)
    def test_all_pins_native_inventory_and_original_converter(self):
        pack=load_pack(PACK/'pack.ini');allowed={'pack.ini','PACK-README.md','PACK-README.txt','README.txt'}
        for item in list(pack['tools'].values())+list(pack['assets'].values()):
            allowed.add(item['path']);self.assertEqual(hashlib.sha256((PACK/item['path']).read_bytes()).hexdigest(),item['sha256'])
        items=list(PACK.rglob('*'))
        self.assertLessEqual(len(items),2000)
        self.assertLessEqual(sum(p.stat().st_size for p in items if p.is_file()),512*1024*1024)
        for p in items:
            self.assertFalse(p.is_symlink())
            if p.is_file():self.assertTrue(p.relative_to(PACK).as_posix() in allowed or p.relative_to(PACK).as_posix().startswith('licenses/'),p)
        with zipfile.ZipFile(ROOT/'vendor-expanded/vardict/VarDict-1.8.3.zip') as archive:
            member=next(name for name in archive.namelist() if name.endswith('/var2vcf_valid.pl'))
            self.assertEqual((PACK/'runtime/perl/var2vcf_valid.pl').read_bytes(),archive.read(member))
        self.assertIn('EXPERIMENTAL',self.catalog['tools']['vardict/call']['methodsDescription'])
        self.assertEqual(self.catalog['tools']['vardict/call']['output']['id'],'variants')
    def test_actual_declared_native_science_cases_with_reference_runtime(self):
        report=run_pack_checks(ROOT,self.catalog,self.folder,backend=self.backend)
        self.assertEqual(report['failed'],0,report)
        self.assertEqual(report['passed'],2)
    def test_reference_only_target_is_valid_zero_call_result(self):
        bed=self.folder/'empty coverage.bed';bed.write_text('chr1\t0\t100\tno_coverage\n')
        self.graph['sources'][2]['files']['targets']=str(bed)
        result=self.run_graph();self.assertEqual(self.variants(result),[])
        table=Path(next(iter(result['outputs']['step-1::calls-table']['files'].values())))
        self.assertEqual(table.stat().st_size,0)
    def test_valid_bed_headers_and_run_paths_with_spaces(self):
        bed=self.folder/'targets with spaces.bed';bed.write_text('# comment\ntrack name=example\nbrowser position chr1:1-1200\nchr1\t0\t1200\ttarget\n')
        self.graph['sources'][2]['files']['targets']=str(bed)
        rows=self.variants(self.run_graph())
        self.assertEqual([(row[0],row[1],row[3],row[4],row[6]) for row in rows],[('chr1','300','A','C','PASS')])
    def test_bed_rejects_empty_overlap_bounds_and_unknown_reference(self):
        for contents in ('','#comment\n','chr1\t1\t1\tempty\n','chr1\t0\t1201\toversize\n','wrong\t0\t10\twrong\n','chr1\t0\t400\ta\nchr1\t399\t600\tb\n','chr1\t0\t10\n'):
            with self.subTest(contents=contents):
                bed=self.folder/'invalid.bed';bed.write_text(contents);self.graph['sources'][2]['files']['targets']=str(bed)
                self.reject()
        self.assertEqual(self.backend.calls,[])
    def test_sample_mismatch_malformed_alignment_and_wrong_reference_fail(self):
        self.graph['nodes'][0]['params']['sample']='other'
        self.assertRegex(self.reject(),'sample|Sample')
        self.graph['nodes'][0]['params']['sample']='validation'
        bad=self.folder/'bad.bam';bad.write_bytes(b'not a BAM')
        self.graph['sources'][0]['files']['alignment']=str(bad)
        self.reject()
        self.graph['sources'][0]['files']['alignment']=str(PACK/'fixtures/input.bam')
        reference=self.folder/'wrong.fa';text=(PACK/'fixtures/reference.fa').read_text();reference.write_text(text.replace('\nT','\nA',1) if '\nT' in text else text.replace('\nA','\nT',1))
        # Preserve dictionary length while changing sequence identity.
        data=reference.read_text()
        if data==text:
            lines=text.splitlines();lines[1]=('A' if lines[1][0]!='A' else 'C')+lines[1][1:];reference.write_text('\n'.join(lines)+'\n')
        self.graph['sources'][1]['files']['reference']=str(reference)
        self.assertIn('MD5',self.reject())
        self.assertEqual(self.backend.calls,[])
    def test_semicolon_pipe_and_nonascii_paths_are_rejected(self):
        for leaf in ('targets;extra.bed','targets|extra.bed','targets-\u00e9.bed'):
            path=self.folder/leaf;path.write_text((PACK/'fixtures/targets.bed').read_text());self.graph['sources'][2]['files']['targets']=str(path)
            with self.subTest(leaf=leaf),self.assertRaises(ValueError):self.engine.prepare(self.graph,self.folder)
    def test_fisher_reference_evidence_matches_r_for_forty_tables(self):
        evidence=json.loads((ROOT/'validation/vardict-0.5.3-fisher.json').read_text())
        self.assertEqual(len(evidence['tables']),40)
        self.assertEqual(evidence['maxAbsolutePDelta'],0)
        self.assertEqual(evidence['finiteMaxAbsoluteOddsDelta'],0)
        self.assertFalse(evidence['nativeWindowsExecuted'])
        build=ROOT/'build/vardict'
        cp=os.pathsep.join(str(p) for p in sorted((PACK/'assets').glob('*.jar')))
        compile_result=subprocess.run([str(JAVA_HOME/'bin/java'),'-jar',str(build/'ecj-3.26.0.jar'),'-source','8','-target','8','-cp',cp,'-d',str(build),str(ROOT/'tests/VarDictFisherProbe.java')],env=self.backend.environment,capture_output=True)
        self.assertEqual(compile_result.returncode,0,compile_result.stderr.decode())
        labels=[','.join(map(str,item['cells'])) for item in evidence['tables']]
        result=subprocess.run([str(JAVA_HOME/'bin/java'),'-cp',str(build)+os.pathsep+cp,'VarDictFisherProbe']+labels,env=self.backend.environment,capture_output=True,timeout=60)
        self.assertEqual(result.returncode,0,result.stderr.decode())
        actual={line.split('\t')[0]:line.split('\t')[1:] for line in result.stdout.decode().splitlines()}
        for row,label in zip(evidence['tables'],labels):
            self.assertEqual(float(actual[label][0]),row['rP'],label)
            self.assertEqual(float(actual[label][1]),float(row['rOdds']),label)


if __name__=='__main__':unittest.main()
