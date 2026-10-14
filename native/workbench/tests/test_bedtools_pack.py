"""BEDTools scientific fixtures, pinned-upstream comparisons and contract failures.

These tests run real Linux executables; they do not claim native Windows execution.
The same manifest's workbench-checks.json runs separately on native Windows.
"""
import copy, hashlib, json, os, shutil, subprocess, sys, tempfile, unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
PACK=ROOT/'packs/bedtools-1.0.0'
CACHE=Path(os.environ.get('NW_BEDTOOLS_CACHE',ROOT.parent/'popular-build/bedtools'))
sys.path[:0]=[str(ROOT/'workspace'),str(ROOT/'scripts')]
from catalog import load_pack, describe_workflow, TYPES
from engine import Engine, digest_file
from pack_checks import _assert_output, run_pack_checks
from prepare_bedtools_pack import checks

class LinuxBedtoolsBackend:
    def __init__(self):self.commands=[]
    def run(self,request,event,cancel):
        folder=Path(request['output_folder'])/'linux-bedtools';folder.mkdir()
        pack=load_pack(Path(request['pack_folder'])/'pack.ini')
        if pack['manifestSha256']!=request['pack_sha256']:raise ValueError('Manifest changed')
        wf=pack['workflows'][request['workflow_id']]
        outputs={v['id']:str(folder/v['path']) for v in wf['outputs']}
        def expand(value):
            for prefix,bindings in [('input',request['values']),('output',outputs)]:
                for key,replacement in bindings.items():value=value.replace('{'+prefix+':'+key+'}',str(replacement))
            if '{' in value:raise ValueError('Unexpanded placeholder: '+value)
            return value
        try:
            for step in wf['steps']:
                if step['kind']=='copy':shutil.copy2(expand(step['source']),outputs[step['destination']]);continue
                tool=pack['tools'][step['tool']]
                if digest_file(PACK/tool['path'])!=tool['sha256']:raise ValueError('Declared Windows binary changed')
                executable=CACHE/'build-linux'/step['tool'];record=json.loads((CACHE/'build-linux/build.json').read_text())
                if digest_file(executable)!=record['files'][executable.name]['sha256']:raise ValueError('Linux binary changed')
                command=[str(executable),*[expand(v) for v in step['args']]];self.commands.append(command)
                destination=Path(outputs[step['stdout']]) if step.get('stdout') else folder/(step['id']+'.stdout.txt')
                with destination.open('wb') as out:r=subprocess.run(command,cwd=folder,stdout=out,stderr=subprocess.PIPE,timeout=60)
                if r.returncode:raise ValueError('Step '+step['id']+' failed: '+r.stderr.decode(errors='replace'))
            return {'success':True,'folder':str(folder),'message':'Real Linux BEDTools execution'}
        except Exception as exc:return {'success':False,'folder':str(folder),'message':str(exc)}

def catalog():
    pack=load_pack(PACK/'pack.ini');tools={}
    for wf in pack['workflows'].values():
        tool=describe_workflow(pack,wf,'packs/bedtools-1.0.0',pack['manifestSha256']);tools[tool['id']]=tool
    return {'schema':1,'tools':tools,'types':TYPES,'packs':[{'id':'bedtools','version':'1.0.0'}]}

def graph(case):
    sources=[];bindings={}
    pack=load_pack(PACK/'pack.ini');tool=catalog()['tools']['bedtools/'+case['workflow']]
    for portid,entries in case['inputs'].items():
        port=next(x for x in tool['ports'] if x['id']==portid);sid='input-'+str(len(sources)+1)
        sources.append({'id':sid,'label':portid,'type':port['type'],'files':{key:str(PACK/pack['assets'][value]['path']) for key,value in entries[0].items()}});bindings[portid]=[sid]
    return {'schema':1,'name':'BEDTools scientific check','sources':sources,'nodes':[{'id':'step-1','tool':'bedtools/'+case['workflow'],'inputs':bindings,'params':case.get('params',{})}]}

@unittest.skipUnless((CACHE/'build-linux/bedtools').exists() and (PACK/'pack.ini').exists(),'Build BEDTools Windows pack and Linux reference first')
class BedtoolsPackTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory(prefix='bedtools spaces ');cls.folder=Path(cls.temp.name);cls.backend=LinuxBedtoolsBackend();cls.engine=Engine(ROOT,catalog(),backend=cls.backend);cls.results={}
        for case in checks()['checks']:
            result=cls.engine.execute(cls.engine.prepare(graph(case),cls.folder))
            if not result['success']:raise AssertionError(result)
            cls.results[case['id']]=result
    @classmethod
    def tearDownClass(cls):cls.temp.cleanup()
    def output(self,identity,key='result'):return Path(self.results[identity]['outputs']['step-1::'+key]['files'][key])
    def test_all_declared_scientific_assertions(self):
        for case in checks()['checks']:
            for expected in case['expect']:
                with self.subTest(check=case['id'],output=expected['output']):_assert_output(expected,self.results[case['id']])
    def test_installation_checker_uses_real_executables(self):
        report=run_pack_checks(ROOT,catalog(),self.folder,backend=LinuxBedtoolsBackend())
        self.assertTrue(report['success'],report);self.assertEqual(report['passed'],len(checks()['checks']));self.assertFalse(report['nativeWindowsExecuted'])
    def test_exact_outputs_match_unmodified_pinned_upstream(self):
        upstream=CACHE/'build-linux-upstream/bedtools'
        self.assertTrue(upstream.exists(),'Build --linux --upstream for independent source comparison')
        record=json.loads((CACHE/'build-linux-upstream/build.json').read_text());self.assertEqual(digest_file(upstream),record['files']['bedtools']['sha256'])
        for case in checks()['checks']:
            identity=case['id'];actual=self.output(identity)
            wf=load_pack(PACK/'pack.ini')['workflows'][case['workflow']]
            values={key:str(PACK/load_pack(PACK/'pack.ini')['assets'][asset]['path']) for entries in case['inputs'].values() for key,asset in entries[0].items()};values.update(case.get('params',{}));values.setdefault('distance','0')
            for step in wf['steps']:
                if step.get('tool')!='bedtools':continue
                args=[]
                for arg in step['args']:
                    for key,value in values.items():arg=arg.replace('{input:'+key+'}',value)
                    for item in wf['outputs']:arg=arg.replace('{output:'+item['id']+'}',str(actual.parent/item['path']))
                    args.append(arg)
                if '-fo' in args:
                    expected=self.folder/(identity+' upstream.fasta');args[args.index('-fo')+1]=str(expected)
                    completed=subprocess.run([str(upstream),*args],stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=60);data=expected.read_bytes()
                else:
                    completed=subprocess.run([str(upstream),*args],stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=60);data=completed.stdout
                self.assertEqual(completed.returncode,0,completed.stderr.decode())
                destination=actual.parent/next(x['path'] for x in wf['outputs'] if x['id']==(step.get('stdout') or 'result'))
                self.assertEqual(data,destination.read_bytes(),identity+' '+step['id'])
    def test_empty_result_and_adjacent_merge(self):
        self.assertEqual(self.output('legitimate-empty-overlap').read_bytes(),b'')
        self.assertEqual(self.output('merge-adjacent').read_text(),'chr1\t0\t8\nchr1\t10\t12\n')
        self.assertEqual(self.output('large-64bit-coordinates').read_text(),'chrLarge\t3000000000\t3000000100\n')
    def test_malformed_bed_and_wrong_strand_rejected(self):
        valid='chr1\t0\t4\tx\t0\t+\n'
        for i,text in enumerate(['chr1\t0\t0\n','chr1\t4\t2\n','chr1\t-1\t4\n',valid.replace('+','?'),valid+'chr1\t4\t8\n','chr1\t0\t4\tx\t1001\t+\n','chr1\t0\t4\tx\t0\t+\t0\t4\t0\t1\t4\t0\n']):
            path=self.folder/('bad-'+str(i)+'.bed');path.write_text(text);r=subprocess.run([str(CACHE/'build-linux/bedcheck'),'plain',str(path)],capture_output=True)
            self.assertNotEqual(r.returncode,0,r.stdout)
        path=self.folder/'unstranded.bed';path.write_text(valid.replace('+','.'))
        r=subprocess.run([str(CACHE/'build-linux/bedcheck'),'strand',str(path)],capture_output=True);self.assertNotEqual(r.returncode,0)
    def test_reference_validation_and_original_untouched(self):
        original=PACK/'fixtures/reference.fa'
        self.assertFalse(Path(str(original)+'.fai').exists());self.assertEqual(load_pack(PACK/'pack.ini')['assets']['fixture-reference']['sha256'],digest_file(original))
        for i,text in enumerate(['>chr1\nACGT\n>chr1\nTTTT\n','>chr1\nACGTX\n','>chr1\n']):
            path=self.folder/('badref-'+str(i)+'.fa');path.write_text(text);r=subprocess.run([str(CACHE/'build-linux/bedcheck'),'reference',str(path)],capture_output=True);self.assertNotEqual(r.returncode,0)
        case=next(c for c in checks()['checks'] if c['id']=='extract-forward');g=graph(case);bad=self.folder/'wrong-contig.bed';bad.write_text('missing\t0\t4\n');g['sources'][0]['files']['a']=str(bad)
        before=len(self.backend.commands);result=self.engine.execute(self.engine.prepare(g,self.folder))
        self.assertFalse(result['success']);self.assertRegex(str(result),'absent|exceed');self.assertEqual(before,len(self.backend.commands))
    def test_same_strand_differs_from_unstranded(self):
        r=subprocess.run([str(CACHE/'build-linux/bedtools'),'intersect','-a',str(PACK/'fixtures/a.bed'),'-b',str(PACK/'fixtures/strand.bed'),'-u'],capture_output=True,check=True)
        self.assertEqual(len(r.stdout.splitlines()),3);self.assertEqual(len(self.output('same-strand').read_bytes().splitlines()),1)
if __name__=='__main__':unittest.main()
