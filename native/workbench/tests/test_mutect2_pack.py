"""Execute Mutect2 pack commands with pinned matching Linux Java.

This is genuine GATK execution, not a Windows execution claim. Installation
checks use the same declared scientific assertions with the native backend.
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
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'workspace'))
from catalog import load_pack, describe_workflow
from engine import Engine, pin_for, digest_file
from pack_checks import run_pack_checks

PACK = ROOT/'packs/mutect2-0.5.4'
JAVA_HOME = ROOT/'vendor-expanded/gatk/linux-jre'
LOADER = ROOT/'baselines/bin/ape-loader-linux'
LOADER_SHA = 'ad98161cba98163f6aa383595804489cec52a9ff3b902be16b29368e171ba359'
JAVA_SHA = 'f5aed21d3a0b0f4b05d3a3f9fe71263916d5bc0d47b53aa52a3340b90f0b4805'
JAVA_CORE_PINS = {
    'lib/libjava.so':'180b9143f1b0889e492f21aecbcc4917c2fe168498d5f2589ad6b9403ef26026',
    'lib/server/libjvm.so':'11e5d09f442e42bddc4619b6eed829eaf3952158a5f77c797a58d558fae21738',
    'lib/modules':'7c4331d913282f8b4afef338a8b6313c2bd5c7c56ca4973504f14624e331a572',
    'release':'a23a26314d44357bfbcee8358e63ffc117c42e6b6580bb0d27ccfef2c5d53983',
}


class LinuxReferenceBackend:
    """Run packaged APE tools; substitute the pinned matching Linux Java."""
    def __init__(self):
        self.calls = []
        self.steps = []
        self.executables = {'java': JAVA_HOME/'bin/java'}
        if digest_file(LOADER) != LOADER_SHA or digest_file(self.executables['java']) != JAVA_SHA:
            raise ValueError('Pinned APE loader or Linux reference Java differs')
        for relative,digest in JAVA_CORE_PINS.items():
            if digest_file(JAVA_HOME/relative) != digest:
                raise ValueError('Pinned Linux Java runtime differs: '+relative)
        forbidden = {'JAVA_TOOL_OPTIONS','_JAVA_OPTIONS','JDK_JAVA_OPTIONS','CLASSPATH'}
        self.environment = {key:value for key,value in os.environ.items() if key.upper() not in forbidden}
        self.environment.update(LD_LIBRARY_PATH=os.pathsep.join(str(JAVA_HOME/sub) for sub in ('lib','lib/server')))
        for executable in self.executables.values():
            executable.chmod(executable.stat().st_mode | 0o100)

    def inspect_alignment(self, executable, path, cancel):
        if cancel.is_set():
            raise InterruptedError('Cancelled before alignment inspection')
        return subprocess.check_output([str(LOADER),str(executable),'view','-H',str(path)],text=True,timeout=45)

    def run(self, request, event, cancel):
        self.calls.append(request)
        pack_root = Path(request['pack_folder'])
        if digest_file(pack_root/'pack.ini') != request['pack_sha256']:
            raise ValueError('Pack manifest changed before execution')
        pack = load_pack(pack_root/'pack.ini')
        workflow = pack['workflows'][request['workflow_id']]
        folder = Path(request['output_folder'])/'linux reference execution'
        folder.mkdir()
        outputs = {item['id']:folder/item['path'] for item in workflow['outputs']}
        assets = {identity:pack_root/item['path'] for identity,item in pack['assets'].items()}
        def expand(argument):
            argument = argument.replace('{run}',str(folder))
            for kind,values in [('input',request['values']),('output',outputs),('asset',assets)]:
                for identity,value in values.items():
                    argument = argument.replace('{'+kind+':'+identity+'}',str(value))
            return argument
        try:
            for step in workflow['steps']:
                if cancel.is_set():
                    return {'success':False,'cancelled':True,'folder':str(folder)}
                if step['kind'] == 'copy':
                    shutil.copyfile(expand(step['source']), outputs[step['destination']])
                    continue
                if step['kind'] != 'exec':
                    raise ValueError('Unexpected Mutect2 execution kind: '+step['kind'])
                declared = pack['tools'][step['tool']]
                executable = pack_root/declared['path']
                if digest_file(executable) != declared['sha256']:
                    raise ValueError('Declared executable checksum differs: '+step['tool'])
                if step['tool'] == 'java':
                    prefix = [str(self.executables['java'])]
                elif step['tool'] in {'samtools','bcftools'}:
                    prefix = [str(LOADER),str(executable)]
                else:
                    raise ValueError('Unexpected reference backend tool: '+step['tool'])
                argv = prefix+[expand(arg) for arg in step['args']]
                if step['tool'] == 'java' and '-cp' in argv:
                    at = argv.index('-cp')+1
                    argv[at] = argv[at].replace(';',os.pathsep)
                self.steps.append({'id':step['id'],'argv':argv,'folder':str(folder)})
                result = subprocess.run(argv,cwd=folder,env=self.environment,capture_output=True,timeout=300)
                (folder/(step['id']+'.stderr')).write_bytes(result.stderr)
                if step.get('stdout'):
                    outputs[step['stdout']].write_bytes(result.stdout)
                if result.returncode:
                    raise RuntimeError(step['id']+': '+result.stderr.decode(errors='replace'))
            return {'success':True,'folder':str(folder),'message':'Pinned Linux reference runtime completed original pack argv'}
        except Exception as error:
            return {'success':False,'folder':str(folder),'message':str(error)}


def catalog():
    pack = load_pack(PACK/'pack.ini')
    tools = {pack['id']+'/'+identity:describe_workflow(pack,workflow,'packs/mutect2-0.5.4',pack['manifestSha256'])
             for identity,workflow in pack['workflows'].items()}
    return {'schema':1,'tools':tools,'packs':[{'id':pack['id'],'version':'0.5.4','folder':'packs/mutect2-0.5.4','manifestSha256':pack['manifestSha256']}],'types':{}}


def fixture_graph(tool_catalog, workflow='tumor-normal'):
    tool = 'mutect2/'+workflow
    inputs = {'tumor':['input-1'],'reference':['input-2'],'targets':['input-3']}
    params = {'tumor-sample':'TUMOR','memory':1024}
    sources = [
        {'id':'input-1','type':'bam','label':'Tumor sample','files':{'alignment':str(PACK/'fixtures/tumor.bam')}},
        {'id':'input-2','type':'reference','label':'Reference','files':{'reference':str(PACK/'fixtures/reference.fa')}},
        {'id':'input-3','type':'bed','label':'Targets','files':{'targets':str(PACK/'fixtures/targets.bed')}},
    ]
    if 'normal' in workflow:
        params['normal-sample'] = 'NORMAL'
        inputs['normal'] = ['input-4']
        sources.append({'id':'input-4','type':'bam','label':'Matched normal','files':{'alignment':str(PACK/'fixtures/normal.bam')}})
    if workflow.endswith('-resources'):
        for name,filename in [('germline-resource','germline.vcf'),('panel-of-normals','pon.vcf')]:
            source_id = 'input-'+str(len(sources)+1)
            inputs[name] = [source_id]
            sources.append({'id':source_id,'type':'vcf','label':name,'files':{'variants':str(PACK/'fixtures'/filename)}})
    return {'schema':1,'name':'Mutect2 scientific fixture','nodes':[{'id':'step-1','tool':tool,'pin':pin_for(tool_catalog['tools'][tool]),'params':params,'inputs':inputs}],
            'sources':sources,'nextNode':2,'nextSource':len(sources)+1}


class Mutect2Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = catalog()

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='mutect2 science é ')
        self.folder = Path(self.temporary.name)
        self.backend = LinuxReferenceBackend()
        self.engine = Engine(ROOT,self.catalog,self.backend)
        self.graph = fixture_graph(self.catalog)

    def tearDown(self):
        self.temporary.cleanup()

    def run_graph(self):
        result = self.engine.execute(self.engine.prepare(self.graph,self.folder))
        self.assertTrue(result['success'],result)
        return result

    def output_file(self,result,identity):
        return Path(next(iter(result['outputs']['step-1::'+identity]['files'].values())))

    def rows(self,result,identity='variants'):
        path = self.output_file(result,identity)
        with path.open('rb') as stream:
            compressed = stream.read(2) == b'\x1f\x8b'
        with (gzip.open(path,'rt') if compressed else path.open()) as stream:
            return [line.rstrip().split('\t') for line in stream if not line.startswith('#')]

    def reject(self):
        try:
            plan = self.engine.prepare(self.graph,self.folder)
        except ValueError as error:
            self.assertEqual(self.backend.calls,[])
            return str(error)
        result = self.engine.execute(plan)
        self.assertFalse(result['success'],result)
        self.assertEqual(self.backend.calls,[])
        return str(result)

    def test_actual_declared_scientific_checks_with_pinned_reference_runtime(self):
        report = run_pack_checks(ROOT,self.catalog,self.folder,backend=self.backend)
        self.assertEqual(report['failed'],0,report)
        self.assertEqual(report['passed'],4,report)

    def test_uncovered_intervals_are_valid_empty_vcf_not_failure(self):
        self.graph['sources'][2]['files']['targets'] = str(PACK/'fixtures/empty.bed')
        result = self.run_graph()
        self.assertEqual(self.rows(result),[])
        self.assertEqual(self.rows(result,'pass-variants'),[])
        self.assertGreater(self.output_file(result,'call-stats').stat().st_size,0)
        self.assertGreater(self.output_file(result,'filtering-stats').stat().st_size,0)

    def test_all_sources_are_preserved_and_filtered_outputs_are_primary(self):
        before = {path:hashlib.sha256(path.read_bytes()).hexdigest() for path in (PACK/'fixtures').iterdir() if path.is_file()}
        self.graph['nodes'][0]['params']['contamination'] = '0.01'
        result = self.run_graph()
        expected = [('chr1','1000','C','G','PASS'),('chr1','2000','T','TAGC','PASS'),('chr1','3001','GTTT','G','PASS')]
        self.assertEqual([(row[0],row[1],row[3],row[4],row[6]) for row in self.rows(result)],expected)
        for path,digest in before.items():
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(),digest,str(path))
        for tool in self.catalog['tools'].values():
            self.assertEqual(tool['output']['id'],'variants')
        text = '\n'.join(' '.join(step['argv']) for step in self.backend.steps)
        for required in ('LOGLESS_CACHING','--smith-waterman JAVA','FilterMutectCalls','LearnReadOrientationModel','--contamination-estimate 0.01','-Dsamjdk.use_libdeflate=false','-Dsamjdk.snappy.disable=true'):
            self.assertIn(required,text)

    def test_gzip_population_and_pon_inputs_are_staged_and_honored(self):
        self.graph = fixture_graph(self.catalog,'tumor-normal-resources')
        for source in self.graph['sources'][-2:]:
            original = Path(source['files']['variants'])
            compressed = self.folder/(original.name+'.gz')
            compressed.write_bytes(gzip.compress(original.read_bytes(),mtime=0))
            source['files']['variants'] = str(compressed)
        result = self.run_graph()
        self.assertEqual([(row[1],row[3],row[4],row[6]) for row in self.rows(result)],
                         [('2000','T','TAGC','PASS'),('3001','GTTT','G','PASS')])

    def test_wrong_sample_equal_names_and_same_bam_fail_before_execution(self):
        original = copy.deepcopy(self.graph)
        for invalid in ('TUMOR sample','TUMORé'):
            self.graph = copy.deepcopy(original)
            self.graph['nodes'][0]['params']['tumor-sample'] = invalid
            self.reject()
        self.graph = copy.deepcopy(original)
        self.graph['nodes'][0]['params']['tumor-sample'] = 'WRONG'
        self.assertRegex(self.reject(),'[Ss]ample|SM')
        self.graph = copy.deepcopy(original)
        self.graph['nodes'][0]['params']['normal-sample'] = 'TUMOR'
        self.assertRegex(self.reject(),'[Ss]ample|different|equal|!=')
        self.graph = copy.deepcopy(original)
        self.graph['sources'][3]['files']['alignment'] = str(PACK/'fixtures/tumor.bam')
        self.assertRegex(self.reject(),'[Ss]ample|different|same|SM')

    def test_wrong_reference_malformed_bam_and_outside_intervals_fail(self):
        original = copy.deepcopy(self.graph)
        reference = (PACK/'fixtures/reference.fa').read_text()
        lines = reference.splitlines()
        lines[1] = ('A' if lines[1][0] != 'A' else 'C')+lines[1][1:]
        wrong = self.folder/'wrong.fa';wrong.write_text('\n'.join(lines)+'\n')
        self.graph['sources'][1]['files']['reference'] = str(wrong)
        self.assertIn('MD5',self.reject())
        self.graph = copy.deepcopy(original)
        bad = self.folder/'bad.bam';bad.write_bytes(b'not a BAM')
        self.graph['sources'][0]['files']['alignment'] = str(bad)
        self.reject()
        self.graph = copy.deepcopy(original)
        bed = self.folder/'outside.bed';bed.write_text('chr1\t0\t5001\n')
        self.graph['sources'][2]['files']['targets'] = str(bed)
        self.reject()

    def test_population_resource_without_allele_frequency_declaration_fails(self):
        self.graph = fixture_graph(self.catalog,'tumor-normal-resources')
        resource = self.folder/'missing-af.vcf'
        resource.write_text('\n'.join(line for line in (PACK/'fixtures/germline.vcf').read_text().splitlines()
                                      if not line.startswith('##INFO=<ID=AF,'))+'\n')
        self.graph['sources'][-2]['files']['variants'] = str(resource)
        self.assertIn('AF',self.reject())


if __name__ == '__main__':
    unittest.main()
