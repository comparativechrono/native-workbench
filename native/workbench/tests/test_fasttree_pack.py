#!/usr/bin/env python3
"""FastTree pack: independent synthetic topology, all models, pinned Linux comparison, native boundaries."""
import argparse,configparser,hashlib,importlib.util,json,math,os,re,shutil,subprocess,sys,tempfile,time,unittest,zipfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
import prepare_fasttree_pack as prep
PACK=None;BUILD=ROOT/'build/fasttree-linux';REPORT=None;MUSCLE_ARCHIVE=None;REFERENCE_BINARY=ROOT/'build/fasttree-inputs/FastTree';EXECUTIONS=[];CHAIN=[];LIVE_REFERENCE_CASES=0
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def inventory(p):return {str(f.relative_to(p)):sha(f) for f in p.rglob('*') if f.is_file()}
def fasta(p):
    rows={};name=None
    for line in Path(p).read_text().splitlines():
        if line.startswith('>'):name=line[1:].split()[0];rows[name]=''
        elif line:rows[name]+=line
    return rows

def newick(text):
    """Independent recursive parser restricted to these small scientific fixtures."""
    tokens=re.findall(r'[(),:;]|[^(),:;\s]+',text);at=0;leaves=[];edges=[];supports=[]
    def node():
        nonlocal at
        if tokens[at]=='(':
            at+=1;group=set();children=0
            while True:
                group|=node();children+=1
                if tokens[at]==')':at+=1;break
                if tokens[at]!=',':raise ValueError('Expected Newick separator')
                at+=1
            if children<2:raise ValueError('Unary node')
            if tokens[at] not in [':',',',')',';']:supports.append(float(tokens[at]));at+=1
        else:group={tokens[at]};leaves.append(tokens[at]);at+=1
        if tokens[at]==':':
            at+=1;length=float(tokens[at]);at+=1
            if not math.isfinite(length) or length<0:raise ValueError('Invalid branch')
            edges.append((group,length))
        return group
    universe=node()
    if tokens[at:]!=[';']:raise ValueError('Incomplete/trailing tree')
    split_lengths={};pairs=set()
    for side,length in edges:
        other=universe-side;key=min(tuple(sorted(side)),tuple(sorted(other)),key=lambda x:(len(x),x))
        split_lengths[key]=split_lengths.get(key,0)+length
        if len(key)==2:pairs.add(frozenset(key))
    return leaves,pairs,split_lengths,supports

class SourceTests(unittest.TestCase):
    def test_explicit_typed_operations_and_consequential_options(self):
        workflows,schema=prep.definitions()
        self.assertEqual([w['id'] for w in workflows],['infer-nucleotide','infer-protein'])
        for w in workflows:
            meta=schema['workflows'][w['id']]
            self.assertEqual(meta['ports'][0]['type'],'msa-'+w['id'].removeprefix('infer-'))
            self.assertEqual(meta['outputs'][0]['type'],'file')
            self.assertEqual({i['id'] for i in w['inputs']},{'alignment','model','rates','support','seed'})
            self.assertTrue(meta['pathPolicy']['asciiOnly'])
            self.assertEqual(w['steps'][-1]['tool'],'fasttree-adapter')
    def test_fixture_truth_is_independent_and_locked(self):
        f=ROOT/'tools/fasttree/fixtures';truth=json.loads((f/'truth.json').read_text());reference=json.loads((f/'reference.json').read_text())
        self.assertEqual(reference['referenceExecutableSha256'],prep.SOURCES['FastTree'][1])
        for datatype in ['nucleotide','protein']:
            rows=fasta(f/(datatype+'.afa'));self.assertEqual(sha(f/(datatype+'.afa')),reference['fixtureSha256'][datatype]);self.assertEqual(list(rows),truth['taxa'])
            self.assertEqual({len(s) for s in rows.values()},{truth['columns']})
            counts=[{x:list(column).count(x) for x in set(column)} for column in zip(*rows.values())]
            self.assertEqual(sum(len(x)>1 for x in counts),truth['variableColumns'])
            self.assertEqual(sum(sum(v>=2 for v in x.values())>=2 for x in counts),truth['informativeColumns'])
        self.assertEqual(len(reference['cases']),20)

class ScientificTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.base=PACK if PACK else BUILD
        cls.bin=cls.base/'bin' if PACK else cls.base
        cls.guard=cls.bin/('fasttree-guard.exe' if os.name=='nt' else 'fasttree-guard')
        cls.binary=cls.bin/('fasttree.exe' if os.name=='nt' else 'fasttree')
        if not cls.guard.is_file() or not cls.binary.is_file():raise unittest.SkipTest('Build FastTree with scripts/build_fasttree_native.py or supply --pack on Windows')
        cls.fixtures=PACK/'fixtures' if PACK else ROOT/'tools/fasttree/fixtures'
        cls.truth=json.loads((cls.fixtures/'truth.json').read_text());cls.reference=json.loads((cls.fixtures/'reference.json').read_text())
        cls.before=inventory(cls.base)
    @classmethod
    def tearDownClass(cls):
        if inventory(cls.base)!=cls.before:raise AssertionError('Installed pack/build changed during checks')
    def setUp(self):
        parent=ROOT/'build/fasttree-tests';parent.mkdir(parents=True,exist_ok=True)
        self.temp=tempfile.TemporaryDirectory(prefix='scientific spaces ',dir=parent);self.directory=Path(self.temp.name)
    def tearDown(self):self.temp.cleanup()
    def run_tool(self,datatype='nucleotide',model='GTR',rates='cat',support='sh',source=None,seed='42',success=True):
        source=source or self.fixtures/(('protein' if datatype=='protein' else 'nucleotide')+'.afa');out=self.directory/('run '+str(len(list(self.directory.glob('run *')))));out.mkdir()
        before=sha(source);cmd=[str(self.guard.resolve()),str(source.resolve()),str(out.resolve()),datatype,model,rates,support,seed]
        result=subprocess.run(cmd,capture_output=True,text=True,timeout=180)
        EXECUTIONS.append({'datatype':datatype,'model':model,'rates':rates,'support':support,'returncode':result.returncode,'expectedSuccess':success,'stdout':result.stdout,'stderr':result.stderr})
        self.assertEqual(sha(source),before)
        if success:self.assertEqual(result.returncode,0,result.stderr)
        else:self.assertNotEqual(result.returncode,0);self.assertFalse((out/'inferred-tree.nwk').exists());self.assertIn('FastTree pack:',result.stderr)
        return out,result
    def assert_truth(self,out,support=True,compare=None):
        leaves,pairs,lengths,supports=newick((out/'inferred-tree.nwk').read_text());self.assertCountEqual(leaves,self.truth['taxa']);self.assertEqual(pairs,{frozenset(p) for p in self.truth['unrootedPairs']});self.assertEqual(len(lengths),9)
        self.assertEqual(len(supports),3 if support else 0)
        for v in supports:self.assertGreaterEqual(v,.95);self.assertLessEqual(v,1)
        if compare:
            rleaves,rpairs,rlen,rsupport=newick(self.reference['cases'][compare]['tree']);self.assertCountEqual(leaves,rleaves);self.assertEqual(pairs,rpairs);self.assertEqual(lengths.keys(),rlen.keys())
            for key,value in lengths.items():self.assertTrue(math.isclose(value,rlen[key],rel_tol=.01,abs_tol=.00002),f'{compare}: branch {key}: {value} vs official Linux {rlen[key]}')
        return lengths
    def test_01_all_models_rates_support_against_truth_and_pinned_linux(self):
        for datatype,models in [('nucleotide',['JC','GTR']),('protein',['JTT','LG','WAG'])]:
            for model in models:
                for rates in ['cat','gamma']:
                    for support in ['none','sh']:
                        key='-'.join([datatype,model,rates,support])
                        with self.subTest(case=key):
                            out,_=self.run_tool(datatype,model,rates,support);self.assert_truth(out,support=='sh',key)
                            report=json.loads((out/'alignment-summary.json').read_text());self.assertEqual(report['taxa'],6);self.assertEqual(report['columns'],800);self.assertEqual(report['parsimonyInformativeColumnsIgnoringMissing'],210)
                            log=(out/'fasttree.log').read_text();self.assertIn('FastTree Version 2.2.0 Double precision',log);self.assertIn('CAT-based',log)
                            if rates=='gamma':self.assertIn('Gamma',log)
                            settings=json.loads((out/'analysis-settings.json').read_text());self.assertEqual(settings['model'],model);self.assertTrue(settings['serial']);self.assertEqual(settings['supportResamples'],1000 if support=='sh' else 0)
    def test_02_native_direct_upstream_agrees_with_guard(self):
        out,_=self.run_tool();settings=json.loads((out/'analysis-settings.json').read_text());cmd=settings['argv'];direct=self.directory/'direct upstream.nwk';log=self.directory/'direct upstream.log'
        cmd[cmd.index('-out')+1]=str(direct);cmd[cmd.index('-log')+1]=str(log)
        result=subprocess.run(cmd,capture_output=True,text=True,timeout=60);self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(direct.read_text(),(out/'fasttree-work/raw-tree.nwk').read_text())
    def test_03_normalization_and_identifier_mapping(self):
        rows=fasta(self.fixtures/'nucleotide.afa');source=self.directory/'RNA alignment.fa'
        names=['taxon-1','taxon.2','taxon_3','001','-five','Six']
        source.write_text(''.join('>'+name+' description ignored\n'+seq.lower().replace('t','u')+'.NRY\n' for name,seq in zip(names,rows.values())))
        out,_=self.run_tool(source=source);leaves,_,_,_=newick((out/'inferred-tree.nwk').read_text());self.assertCountEqual(leaves,names)
        staged=fasta(out/'fasttree-work/alignment.fa');self.assertEqual(list(staged.values()),[s+'----' for s in rows.values()]);summary=json.loads((out/'alignment-summary.json').read_text());self.assertEqual(summary['ambiguityCharactersTreatedAsMissing'],18);self.assertEqual(summary['gapCharacters'],6)
    def test_04_invalid_alignments_and_options_fail_with_guidance(self):
        rows=list(fasta(self.fixtures/'nucleotide.afa').items())
        cases={'few':rows[:3],'unequal':rows[:-1]+[(rows[-1][0],rows[-1][1][:-1])],'duplicate':rows[:-1]+[(rows[0][0],rows[-1][1])],'empty':rows[:-1]+[(rows[-1][0],'')],'unknown':rows[:-1]+[(rows[-1][0],'N'*800)],'stop':rows[:-1]+[(rows[-1][0],rows[-1][1][:-1]+'*')],'unsafe-id':[('A|bad',rows[0][1])]+rows[1:]}
        for name,values in cases.items():
            with self.subTest(name=name):
                source=self.directory/(name+'.afa');source.write_text(''.join('>'+n+'\n'+s+'\n' for n,s in values));out,_=self.run_tool(source=source,success=False);self.assertEqual(list(out.iterdir()),[])
        for kwargs in [{'model':'LG'},{'rates':'gamma;echo'},{'support':'bootstrap'},{'seed':'0'},{'seed':'1;echo'},{'datatype':'DNA'}]:
            with self.subTest(kwargs=kwargs):self.run_tool(success=False,**kwargs)
    def test_05_protein_unknowns_missing_and_stops_rejected(self):
        rows=fasta(self.fixtures/'protein.afa');source=self.directory/'protein.afa';source.write_text(''.join('>'+n+'\n'+s+'BXZ.\n' for n,s in rows.items()))
        out,_=self.run_tool('protein','LG',source=source);self.assert_truth(out);self.assertEqual(json.loads((out/'alignment-summary.json').read_text())['ambiguityCharactersTreatedAsMissing'],18)
        source.write_text(source.read_text().replace('BXZ.','BXZ*'));self.run_tool('protein','LG',source=source,success=False)
    def test_06_input_and_installed_paths_with_spaces_and_ascii_guard(self):
        source=self.directory/'input with spaces.afa';shutil.copyfile(self.fixtures/'nucleotide.afa',source);out,_=self.run_tool(source=source);self.assert_truth(out)
        other=self.directory/'selected input é.afa';shutil.copyfile(source,other);self.run_tool(source=other,success=False)
    def test_07_existing_output_not_replaced(self):
        out,_=self.run_tool();before=inventory(out)
        result=subprocess.run([str(self.guard.resolve()),str((self.fixtures/'nucleotide.afa').resolve()),str(out.resolve()),'nucleotide','GTR','cat','sh','42'],capture_output=True,text=True)
        self.assertNotEqual(result.returncode,0);self.assertEqual(inventory(out),before)
    def test_08_declared_installation_checks_and_complete_hashes(self):
        declarations=prep.checks()
        if PACK:
            config=configparser.ConfigParser(interpolation=None);config.read(PACK/'pack.ini',encoding='utf-8');self.assertEqual(config['pack']['version'],'1.0.0')
            for section in config.sections():
                if section.startswith(('tool:','asset:')):self.assertEqual(sha(PACK/config[section]['path']),config[section]['sha256'])
            declarations=json.loads((PACK/'workbench-checks.json').read_text())
            sys.path.insert(0,str(ROOT/'workspace'))
            from catalog import load_pack,describe_workflow
            pack=load_pack(PACK/'pack.ini')
            self.assertEqual(pack['tools']['fasttree-adapter']['path'],'bin/fasttree-guard.exe')
            for wf in pack['workflows'].values():
                described=describe_workflow(pack,wf,str(PACK),pack['manifestSha256'])
                self.assertEqual(described['displayName'],wf['name'])
                self.assertEqual({t['id'] for t in described['executables']},{'fasttree','fasttree-adapter'})
        files={'tree':'inferred-tree.nwk','summary':'alignment-summary.json','settings':'analysis-settings.json','log':'fasttree.log','model-log':'fasttree-model.log'}
        for check in declarations['checks']:
            p=check['params'];out,_=self.run_tool(check['workflow'].removeprefix('infer-'),p['model'],p['rates'],p['support']);self.assert_truth(out)
            for expect in check['expect']:
                content=(out/files[expect['output']]).read_bytes().decode('utf-8')
                for fragment in expect['contains']:self.assertIn(fragment,content)
    def test_09_unresolved_identical_taxa_are_preserved(self):
        source=self.directory/'identical.afa';source.write_text(''.join('>'+name+'\n'+'ACGT'*30+'\n' for name in ['a','b','c','d']))
        out,_=self.run_tool(source=source);leaves,pairs,lengths,support=newick((out/'inferred-tree.nwk').read_text());self.assertCountEqual(leaves,['a','b','c','d']);self.assertEqual(pairs,set());self.assertEqual(support,[]);self.assertTrue(all(v==0 for v in lengths.values()));self.assertEqual(json.loads((out/'alignment-summary.json').read_text())['localSupportValues'],0)
        source.write_text(''.join('>'+name+'\n'+seq+'\n' for name,seq in [('a','ACGT'*30),('b','ACGT'*30),('c','ACGT'*29+'ATGT'),('d','ACGT'*29+'ATGT')]))
        out,_=self.run_tool(source=source);self.assertCountEqual(newick((out/'inferred-tree.nwk').read_text())[0],['a','b','c','d'])
    def test_10_missing_scientific_executable_fails(self):
        isolated=self.directory/'incomplete installation';isolated.mkdir();guard=isolated/self.guard.name;shutil.copyfile(self.guard,guard);guard.chmod(0o755);out=self.directory/'missing child run';out.mkdir()
        result=subprocess.run([str(guard.resolve()),str((self.fixtures/'nucleotide.afa').resolve()),str(out.resolve()),'nucleotide','GTR','cat','sh','42'],capture_output=True,text=True,timeout=30)
        self.assertNotEqual(result.returncode,0);self.assertIn('reinstall this pack',result.stderr);self.assertFalse((out/'inferred-tree.nwk').exists())
    def test_11_actual_published_muscle_chain(self):
        if os.name!='nt':self.skipTest('Actual published Windows MUSCLE chain is a native Windows gate')
        self.assertIsNotNone(MUSCLE_ARCHIVE,'Windows gate requires --muscle-archive')
        self.assertEqual(sha(MUSCLE_ARCHIVE),'c07d3e398f48df683926c0970ef77c3b7d2bdab6426b80c80186f2360ed25258')
        folder=self.directory/'published MUSCLE';folder.mkdir()
        with zipfile.ZipFile(MUSCLE_ARCHIVE) as archive:
            for name in ['muscle.exe','libomp.dll']:(folder/name).write_bytes(archive.read('pack/bin/'+name))
        for datatype,flag,model in [('nucleotide','-nt','GTR'),('protein','-amino','LG')]:
            source=self.fixtures/(datatype+'.afa');aligned=self.directory/(datatype+' muscle.afa')
            cmd=[str(folder/'muscle.exe'),'-super5',str(source),'-output',str(aligned),flag,'-threads','1','-perturb','0','-perm','none']
            result=subprocess.run(cmd,capture_output=True,text=True,timeout=120);self.assertEqual(result.returncode,0,result.stderr)
            self.assertEqual({k:v.replace('-','') for k,v in fasta(aligned).items()},fasta(source))
            out,_=self.run_tool(datatype,model,source=aligned);self.assert_truth(out)
            CHAIN.append({'datatype':datatype,'muscleArchiveSha256':sha(MUSCLE_ARCHIVE),'muscleExecutableSha256':sha(folder/'muscle.exe'),'alignmentSha256':sha(aligned),'residuesPreserved':True,'knownUnrootedPairsAndTaxaPassed':True})

    def test_12_live_pinned_linux_reference(self):
        global LIVE_REFERENCE_CASES
        if os.name=='nt':
            # The frozen Linux build-job report supplies this separate check.
            self.assertEqual(self.reference['referenceExecutableSha256'],prep.SOURCES['FastTree'][1])
            return
        self.assertTrue(REFERENCE_BINARY.is_file(),'Pinned Linux reference missing; build with --fetch and pass --reference-binary')
        spec=importlib.util.spec_from_file_location('fasttree_reference_recorder',ROOT/'tools/fasttree/record_reference.py');mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
        actual=mod.record(REFERENCE_BINARY,self.fixtures);LIVE_REFERENCE_CASES=mod.verify(actual,self.reference);self.assertEqual(LIVE_REFERENCE_CASES,20)

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--pack',type=Path);p.add_argument('--build',type=Path,default=BUILD);p.add_argument('--report',type=Path);p.add_argument('--muscle-archive',type=Path);p.add_argument('--reference-binary',type=Path,default=REFERENCE_BINARY);a=p.parse_args()
    PACK=a.pack.resolve() if a.pack else None;BUILD=a.build.resolve();MUSCLE_ARCHIVE=a.muscle_archive.resolve() if a.muscle_archive else None;REFERENCE_BINARY=a.reference_binary.resolve()
    if os.name=='nt' and not PACK:p.error('Native Windows checks must select the exact installed --pack')
    selected=(PACK/'bin' if PACK else BUILD)/('fasttree-guard.exe' if os.name=='nt' else 'fasttree-guard')
    if not selected.is_file() or not (selected.parent/('fasttree.exe' if os.name=='nt' else 'fasttree')).is_file():p.error('Scientific checks require the selected compiled guard and FastTree executable: '+str(selected.parent))
    started=time.monotonic();suite=unittest.TestSuite([unittest.defaultTestLoader.loadTestsFromTestCase(SourceTests),unittest.defaultTestLoader.loadTestsFromTestCase(ScientificTests)]);result=unittest.TextTestRunner(verbosity=2).run(suite)
    evidence={'schema':1,'packId':'fasttree','packVersion':'1.0.0','upstreamVersion':'2.2.0','platform':sys.platform,'nativeWindowsExecuted':os.name=='nt','testsRun':result.testsRun,'failures':len(result.failures),'errors':len(result.errors),'skipped':[{'test':str(t),'reason':s} for t,s in result.skipped],'success':result.wasSuccessful(),'seconds':round(time.monotonic()-started,3),'testSourceSha256':sha(__file__),'guardExecutableSha256':sha(selected),'scientificBinarySha256':sha(selected.parent/('fasttree.exe' if os.name=='nt' else 'fasttree')),'livePinnedLinuxReferenceCases':LIVE_REFERENCE_CASES,'packManifestSha256':sha(PACK/'pack.ini') if PACK else None,'referenceExecutableSha256':prep.SOURCES['FastTree'][1],'executions':EXECUTIONS,'muscleIntegration':CHAIN,'scope':'Independent 3-pair synthetic truth, all 5 models x2 rate settings x2 support settings; official Linux branch comparison tolerance relative1%/absolute0.00002; direct bundled upstream agreement; input/pack immutability and malformed-input guards. No realistic performance, nativeGUI, biological-rooting or clinical claim.'}
    if a.report:a.report.parent.mkdir(parents=True,exist_ok=True);a.report.write_text(json.dumps(evidence,indent=2)+'\n',encoding='utf-8')
    sys.exit(not result.wasSuccessful())
