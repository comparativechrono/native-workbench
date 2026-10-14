#!/usr/bin/env python3
"""Independent binding truth, exact native Primer3 science, bounded input and provenance checks."""
import argparse
import configparser
import csv
import gzip
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
import build_primer3_native as builder
import prepare_primer3_pack as prep
PACK=None
BUILD=ROOT/'build/primer3-linux'
REFERENCE_BINARY=ROOT/'build/primer3-reference-linux/primer3_core'
EXECUTIONS=[]
LIVE_REFERENCE=None

def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def inventory(path):return {p.relative_to(path).as_posix():sha(p) for p in path.rglob('*') if p.is_file()}
def module(name,path):
    spec=importlib.util.spec_from_file_location(name,path);result=importlib.util.module_from_spec(spec);spec.loader.exec_module(result);return result
recorder=module('primer3_record_reference',ROOT/'tools/primer3/record_reference.py')

def sequence(path):return ''.join(Path(path).read_text().splitlines()[1:]).upper()
def revcomp(text):return text.translate(str.maketrans('ACGTN','TGCAN'))[::-1]

class SourceTests(unittest.TestCase):
    def test_01_fixture_construction_and_reference_source_identity(self):
        generator=module('primer3_fixtures',ROOT/'tools/primer3/fixtures.py')
        with tempfile.TemporaryDirectory() as directory:
            generator.fixtures(directory)
            for p in Path(directory).iterdir():self.assertEqual(p.read_bytes(),(ROOT/'tools/primer3/fixtures'/p.name).read_bytes())
        ref=json.loads((ROOT/'tools/primer3/fixtures/reference.json').read_text())
        self.assertEqual(ref['sourceCommit'],builder.SOURCE_COMMIT)
        self.assertEqual(ref['sourceArchiveSha256'],builder.SOURCE_SHA256)
        for name,case in ref['cases'].items():self.assertEqual(case['fixtureSha256'],sha(ROOT/'tools/primer3/fixtures'/(name+'.fa')))
    def test_02_manifest_semantics_and_scientific_version_step(self):
        workflows,schema=prep.definitions();self.assertEqual([w['id'] for w in workflows],['design-pcr'])
        self.assertEqual(workflows[0]['steps'][0]['arg.0'],'--about')
        self.assertEqual({s['tool'] for s in workflows[0]['steps']},{'primer3','primer3-adapter'})
        self.assertEqual(schema['workflows']['design-pcr']['ports'][0]['type'],'fasta-nucleotide')
        self.assertTrue(schema['workflows']['design-pcr']['pathPolicy']['asciiOnly'])

class ScientificTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.binary_dir=PACK/'bin' if PACK else BUILD
        cls.guard=cls.binary_dir/('primer3-guard.exe' if os.name=='nt' else 'primer3-guard')
        cls.binary=cls.binary_dir/('primer3_core.exe' if os.name=='nt' else 'primer3_core')
        cls.fixtures=PACK/'fixtures' if PACK else ROOT/'tools/primer3/fixtures'
        cls.truth=json.loads((cls.fixtures/'truth.json').read_text())
        cls.reference=json.loads((cls.fixtures/'reference.json').read_text())
        cls.before=inventory(PACK if PACK else cls.binary_dir)
    @classmethod
    def tearDownClass(cls):
        if inventory(PACK if PACK else cls.binary_dir)!=cls.before:raise AssertionError('Installed pack/build bytes changed during execution')
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='primer3-science-');self.directory=Path(self.temp.name);self.counter=0
    def tearDown(self):self.temp.cleanup()
    def run_tool(self,name='ordinary',source=None,settings=None,success=True,guard=None):
        self.counter+=1;out=self.directory/('run with spaces '+str(self.counter));out.mkdir()
        source=source or self.fixtures/(name+'.fa');before=sha(source)
        settings=list(settings or self.truth['plantedSettings' if name=='planted' else 'defaultSettings'])
        args=[str(guard or self.guard),str(source),str(out),*settings]
        child=subprocess.run(args,capture_output=True,text=True,timeout=180)
        EXECUTIONS.append({'case':self.id(),'executableSha256':sha(guard or self.guard),'inputSha256':before,'returncode':child.returncode,'expectedSuccess':success,'settings':settings})
        self.assertEqual(sha(source),before)
        if success:self.assertEqual(child.returncode,0,child.stdout+child.stderr)
        else:self.assertNotEqual(child.returncode,0)
        return out,child
    def source(self,text):
        p=self.directory/('input'+str(self.counter)+'.fa');p.write_bytes(text.encode('ascii'));return p
    def rows(self,out):
        with (out/'primers.tsv').open(encoding='ascii',newline='') as f:return list(csv.DictReader(f,delimiter='\t'))
    def assert_bindings(self,src,out,settings=None):
        seq=sequence(src);settings=settings or self.truth['defaultSettings'];rows=self.rows(out)
        summary=json.loads((out/'primer3-summary.json').read_text());self.assertEqual(summary['pairsReturned'],len(rows));self.assertEqual(summary['templateBases'],len(seq));self.assertFalse(summary['specificityEvaluated'])
        for row in rows:
            l0,l1,r0,r1=map(int,[row['left_start0'],row['left_end0_exclusive'],row['right_start0'],row['right_end0_exclusive']])
            self.assertEqual(row['left_sequence_5to3'],seq[l0:l1]);self.assertEqual(row['right_sequence_5to3'],revcomp(seq[r0:r1]))
            self.assertEqual(int(row['product_bp']),r1-l0)
            self.assertGreaterEqual(int(row['product_bp']),int(settings[0]));self.assertLessEqual(int(row['product_bp']),int(settings[1]))
            for side in ('left','right'):
                bases=row[side+'_sequence_5to3'];self.assertGreaterEqual(len(bases),int(settings[3]));self.assertLessEqual(len(bases),int(settings[5]));self.assertNotIn('N',bases)
                self.assertAlmostEqual(float(row[side+'_gc_percent']),100*(bases.count('G')+bases.count('C'))/len(bases),delta=0.00051)
                # Output rounds to 0.001 C; allow its half-unit display precision.
                self.assertGreaterEqual(float(row[side+'_tm_C']),float(settings[6])-0.0005);self.assertLessEqual(float(row[side+'_tm_C']),float(settings[8])+0.0005)
        return rows
    def test_03_independent_planted_binding_sites_and_product(self):
        out,_=self.run_tool('planted');rows=self.assert_bindings(self.fixtures/'planted.fa',out,self.truth['plantedSettings']);self.assertEqual(len(rows),1)
        row=rows[0]
        for key,value in {'left_sequence_5to3':self.truth['left'],'right_sequence_5to3':self.truth['right'],'left_start0':'40','left_end0_exclusive':'60','right_start0':'200','right_end0_exclusive':'220','product_bp':'180'}.items():self.assertEqual(row[key],value)
    def test_04_ordinary_ranked_pairs_and_locked_pristine_reference(self):
        for name in ('planted','ordinary','no-pairs'):
            with self.subTest(name=name):
                out,_=self.run_tool(name);tags=recorder.result_tags((out/'primer3-result.boulder').read_text())
                self.assertEqual(tags,self.reference['cases'][name]['resultTags'])
                self.assert_bindings(self.fixtures/(name+'.fa'),out,self.truth['plantedSettings' if name=='planted' else 'defaultSettings'])
                if name=='ordinary':self.assertEqual(len(self.rows(out)),5)
    def test_05_no_candidates_is_valid_and_actionable(self):
        out,_=self.run_tool('no-pairs');self.assertEqual(self.rows(out),[]);summary=json.loads((out/'primer3-summary.json').read_text());self.assertEqual(summary['pairsReturned'],0);self.assertIn('No candidate pair',summary['guidance']);self.assertIn('PRIMER_LEFT_EXPLAIN=',(out/'primer3-result.boulder').read_text())
    def test_06_explicit_chemistry_length_product_and_tm_settings(self):
        settings=['150','220','3','19','21','24','55','61','66','75','2.0','0.8','125']
        out,_=self.run_tool(settings=settings);self.assertTrue(self.assert_bindings(self.fixtures/'ordinary.fa',out,settings));record=json.loads((out/'analysis-settings.json').read_text());self.assertEqual(record['settings']['PRIMER_DNA_CONC'],'125');self.assertEqual(record['settings']['PRIMER_DNTP_CONC'],'0.8');self.assertIn('not measurements',record['model']);self.assertEqual(record['defaultVersion'],2)
    def test_07_short_and_maximum_templates_and_primer_length_bound(self):
        for length,settings in [(60,['60','60','1','12','12','12','0','30','100','50','1.5','0.6','50']),(100000,['100','300','1','36','36','36','0','60','100','50','1.5','0.6','50'])]:
            with self.subTest(length=length):
                out,_=self.run_tool(source=self.source('>bounded\n'+'N'*length+'\n'),settings=settings);self.assertEqual(json.loads((out/'primer3-summary.json').read_text())['templateBases'],length)
        out,child=self.run_tool(source=self.source('>short\n'+'A'*60+'\n'),success=False);self.assertIn('Product minimum exceeds template length',child.stderr);self.assertEqual(list(out.iterdir()),[])
    def test_08_invalid_fasta_and_compression_rejected(self):
        cases=['', 'A'*100, '>empty\n', '>one\n'+'A'*100+'\n>two\n'+'C'*100+'\n', '>one\n'+'A'*99+'R\n', '>one\n'+'A'*99+'-\n','>bad;id\n'+'A'*100+'\n','>a\n'+'A'*59+'\n','>a\n'+'A'*100001+'\n','>'+'a'*129+'\n'+'A'*100+'\n']
        for text in cases:
            with self.subTest(length=len(text)):
                out,_=self.run_tool(source=self.source(text),success=False);self.assertEqual(list(out.iterdir()),[])
        compressed=self.directory/'compressed.fa.gz';compressed.write_bytes(gzip.compress(('>a\n'+'A'*100+'\n').encode()));out,child=self.run_tool(source=compressed,success=False);self.assertIn('uncompressed FASTA',child.stderr);self.assertEqual(list(out.iterdir()),[])
    def test_09_invalid_settings_rejected_before_output(self):
        cases=[(0,'301'),(2,'0'),(2,'21'),(3,'28'),(5,'37'),(6,'64'),(8,'56'),(9,'0'),(10,'nan'),(11,'-1'),(12,'inf'),(12,'1;echo')]
        for index,value in cases:
            with self.subTest(index=index,value=value):
                settings=list(self.truth['defaultSettings']);settings[index]=value;out,_=self.run_tool(settings=settings,success=False);self.assertEqual(list(out.iterdir()),[])
    def test_10_case_spaces_and_ascii_path_policy(self):
        src=self.directory/'selected template with spaces.fa';src.write_text((self.fixtures/'ordinary.fa').read_text().lower(),encoding='ascii');out,_=self.run_tool(source=src);self.assert_bindings(src,out)
        nonascii=self.directory/'template-é.fa';shutil.copyfile(src,nonascii);out,child=self.run_tool(source=nonascii,success=False);self.assertIn('ASCII',child.stderr);self.assertEqual(list(out.iterdir()),[])
    def test_11_output_replacement_is_rejected(self):
        out,_=self.run_tool();before=inventory(out);child=subprocess.run([str(self.guard),str(self.fixtures/'ordinary.fa'),str(out),*self.truth['defaultSettings']],capture_output=True,text=True,timeout=30);self.assertNotEqual(child.returncode,0);self.assertIn('fresh output',child.stderr);self.assertEqual(inventory(out),before)
    def test_12_missing_binary_and_configuration_have_guidance(self):
        for missing in ('binary','config','table'):
            with self.subTest(missing=missing):
                isolated=self.directory/missing;isolated.mkdir();guard=isolated/self.guard.name;shutil.copyfile(self.guard,guard);guard.chmod(0o755)
                if missing!='binary':shutil.copyfile(self.binary,isolated/self.binary.name);(isolated/self.binary.name).chmod(0o755)
                if missing=='table':shutil.copytree(self.binary_dir/'primer3_config',isolated/'primer3_config');(isolated/'primer3_config/stack.dh').unlink()
                out,child=self.run_tool(guard=guard,success=False);self.assertIn('reinstall this pack',child.stderr);self.assertEqual(list(out.iterdir()),[])
    def test_13_repeated_execution_and_version(self):
        a,_=self.run_tool();b,_=self.run_tool();self.assertEqual((a/'primers.tsv').read_bytes(),(b/'primers.tsv').read_bytes());self.assertEqual((a/'primer3-summary.json').read_bytes(),(b/'primer3-summary.json').read_bytes())
        version=subprocess.run([str(self.binary),'--about'],capture_output=True,text=True,timeout=30);self.assertEqual(version.returncode,0);self.assertIn('2.6.1',version.stdout+version.stderr)
    def test_14_installed_hashes_and_thermodynamic_source_correspondence(self):
        if PACK:
            cfg=configparser.ConfigParser(interpolation=None);cfg.read(PACK/'pack.ini',encoding='utf-8')
            self.assertEqual(cfg['pack']['id'],'primer3')
            for section in cfg.sections():
                if section.startswith(('tool:','asset:')):self.assertEqual(sha(PACK/cfg[section]['path']),cfg[section]['sha256'])
            record=json.loads((PACK/'licenses/build-provenance.json').read_text())
        else:record=json.loads((BUILD/'build.json').read_text())
        self.assertTrue(record['upstreamSourceUnmodified']);self.assertEqual(record['upstreamCommit'],builder.SOURCE_COMMIT)
        for path,digest in record['configurationFiles'].items():self.assertEqual(sha(self.binary_dir/'primer3_config'/path),digest)
        self.assertEqual(sha(self.binary),record['files'][self.binary.name]['sha256'])

class LinuxReferenceTests(unittest.TestCase):
    def test_15_fresh_pristine_upstream_reference(self):
        global LIVE_REFERENCE
        LIVE_REFERENCE=recorder.record(REFERENCE_BINARY,ROOT/'tools/primer3/fixtures');expected=json.loads((ROOT/'tools/primer3/fixtures/reference.json').read_text());self.assertEqual(recorder.verify(LIVE_REFERENCE,expected),3)

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--pack',type=Path);p.add_argument('--build',type=Path,default=BUILD);p.add_argument('--reference-binary',type=Path,default=REFERENCE_BINARY);p.add_argument('--report',type=Path);a=p.parse_args()
    PACK=a.pack.resolve() if a.pack else None;BUILD=a.build.resolve();REFERENCE_BINARY=a.reference_binary.resolve()
    if os.name=='nt' and not PACK:p.error('Native Windows requires the exact installed --pack')
    selected=(PACK/'bin' if PACK else BUILD)/('primer3-guard.exe' if os.name=='nt' else 'primer3-guard');binary=selected.parent/('primer3_core.exe' if os.name=='nt' else 'primer3_core')
    if not selected.is_file() or not binary.is_file():p.error('Selected compiled Primer3 and guard are required')
    if os.name!='nt' and not REFERENCE_BINARY.is_file():p.error('Linux checks require pinned pristine --reference-binary')
    classes=[SourceTests,ScientificTests]+([LinuxReferenceTests] if os.name!='nt' else [])
    started=time.monotonic();result=unittest.TextTestRunner(verbosity=2).run(unittest.TestSuite(unittest.defaultTestLoader.loadTestsFromTestCase(c) for c in classes))
    evidence={'schema':1,'packId':'primer3','packVersion':'1.0.0','upstreamVersion':builder.UPSTREAM_VERSION,'toolVersion':builder.VERSION,'platform':sys.platform,'nativeWindowsExecuted':os.name=='nt','testsRun':result.testsRun,'failures':len(result.failures),'errors':len(result.errors),'skipped':[{'test':str(t),'reason':r} for t,r in result.skipped],'success':result.wasSuccessful(),'seconds':round(time.monotonic()-started,3),'testSourceSha256':sha(__file__),'guardExecutableSha256':sha(selected),'scientificBinarySha256':sha(binary),'packManifestSha256':sha(PACK/'pack.ini') if PACK else None,'upstreamSourceCommit':builder.SOURCE_COMMIT,'upstreamSourceArchiveSha256':builder.SOURCE_SHA256,'livePinnedLinuxReferenceCases':len(LIVE_REFERENCE['cases']) if LIVE_REFERENCE else 0,'liveReferenceExecutableSha256':LIVE_REFERENCE['referenceExecutableSha256'] if LIVE_REFERENCE else None,'executions':EXECUTIONS,'scope':'Independent planted primer binding/strand/product/GC and requested Tm/length ranges; pristine upstream comparison; zero-pair success; explicit chemistry; input/pack immutability; bounds/missing dependencies and path guidance. No specificity, experimental PCR, clinical or benchmark claim.'}
    if a.report:a.report.parent.mkdir(parents=True,exist_ok=True);a.report.write_text(json.dumps(evidence,indent=2)+'\n',encoding='utf-8')
    sys.exit(not result.wasSuccessful())
