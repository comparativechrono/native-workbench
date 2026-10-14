"""Prodigal constructed scientific truth and input contracts; platform claims are separate."""
import argparse, hashlib, json, os, platform, shutil, subprocess, sys, tempfile, unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'));sys.path.insert(0,str(ROOT/'workspace'))
from prepare_prodigal_pack import definitions, fixtures, checks, VERSION, _fixture_module
from build_prodigal_native import pe_stack, WINDOWS_STACK_RESERVE, WINDOWS_STACK_COMMIT
from catalog import load_pack
from pack_checks import _assert_output
reverse_complement=_fixture_module.reverse_complement
translate=_fixture_module.translate
fasta=_fixture_module.fasta
CACHE=Path(os.environ.get('NW_PRODIGAL_CACHE',ROOT/'build/prodigal')).resolve()
PACK=None
REPORT=None
EXECUTIONS=[]

def sequences(path):
    rows={};identity=None
    for line in Path(path).read_text().splitlines():
        if line.startswith('>'):
            identity=line[1:].split()[0]
            if identity in rows:raise AssertionError('Duplicate output FASTA identity')
            rows[identity]=''
        elif line:rows[identity]+=line
    return rows

def annotations(path):
    return [line.split('\t') for line in Path(path).read_text().splitlines() if line and not line.startswith('#')]

class Declarations(unittest.TestCase):
    def test_genetic_code_requires_biological_choice(self):
        workflows,schema=definitions();self.assertEqual(len(workflows),2)
        genome={x['id']:x for x in workflows[0]['inputs']};meta={x['id']:x for x in workflows[1]['inputs']}
        self.assertNotIn('default',genome['genetic-code']);self.assertNotIn('genetic-code',meta)
        self.assertIn('11:',genome['genetic-code']['choices']);self.assertIn('25:',genome['genetic-code']['choices'])
    def test_empty_sequence_outputs_and_typed_contract(self):
        workflows,schema=definitions()
        for wf in workflows:
            outputs={x['id']:x for x in wf['outputs']};meta={x['id']:x for x in schema['workflows'][wf['id']]['outputs']}
            for identity,kind in [('proteins','fasta-protein'),('cds','fasta-nucleotide')]:
                self.assertEqual(outputs[identity]['nonempty'],'false');self.assertEqual(meta[identity]['type'],kind);self.assertEqual(meta[identity]['state']['compression'],'none')
            self.assertEqual(wf['steps'][-1]['tool'],'prodigal-adapter');self.assertEqual(wf['steps'][0]['tool'],'prodigal');self.assertEqual(wf['steps'][0]['arg.0'],'-v')
            self.assertEqual(schema['workflows'][wf['id']]['pathPolicy'],{'asciiOnly':True})
    def test_constructed_truth_has_both_strands_and_reassigned_stop_codons(self):
        with tempfile.TemporaryDirectory() as tmp:
            truth=fixtures(Path(tmp));self.assertEqual({x['strand'] for x in truth['planted']},{'+','-'})
            for item in truth['reassigned']:
                self.assertEqual(item['protein4'][40],'W');self.assertEqual(item['protein25'][40],'G');self.assertEqual(translate(item['cds'],'11')[40],'*')

class Science(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory(prefix='Prodigal scientific paths ');cls.root=Path(cls.temp.name);cls.counter=0
        if PACK:
            cls.pack=load_pack(PACK/'pack.ini');cls.binary=PACK/'bin/prodigal.exe';cls.guard=PACK/'bin/prodigal-guard.exe';cls.input=PACK/'fixtures'
            for item in cls.pack['tools'].values():
                path=PACK/item['path'];assert hashlib.sha256(path.read_bytes()).hexdigest()==item['sha256'],'Pack binary hash mismatch'
            cls.truth=json.loads((cls.input/'truth.json').read_text())
        else:
            cls.pack=None;cls.binary=CACHE/'build-linux/prodigal';cls.guard=CACHE/'build-linux/prodigal-guard';cls.input=cls.root/'inputs with spaces';cls.truth=fixtures(cls.input)
        if not cls.binary.is_file() or not cls.guard.is_file():
            cls.temp.cleanup();raise unittest.SkipTest('Build the Linux reference/guard, or supply --pack for exact Windows science')
    @classmethod
    def tearDownClass(cls):cls.temp.cleanup()
    @staticmethod
    def invoke(args):
        command=[str(x) for x in args];result=subprocess.run(command,capture_output=True,text=True,timeout=120)
        EXECUTIONS.append({'command':command,'returncode':result.returncode,'stdoutSha256':hashlib.sha256(result.stdout.encode()).hexdigest(),'stderrSha256':hashlib.sha256(result.stderr.encode()).hexdigest()})
        return result
    def predict(self,mode='meta',input=None,code=None,model='auto',closed=False,mask=True,okay=True):
        type(self).counter+=1;out=self.root/('result with spaces '+str(self.counter));out.mkdir()
        source=input or self.input/('genome.fna' if mode=='single' else 'metagenome.fna');code=code or ('11' if mode=='single' else 'auto')
        input_before=hashlib.sha256(Path(source).read_bytes()).hexdigest()
        output={'annotations':out/'genes.gff','proteins':out/'proteins.faa','cds':out/'coding-sequences.fna','summary':out/'prediction-summary.json'}
        values={'sequence':str(source),'genetic-code':code,'start-model':model,'closed-ends':str(closed).lower(),'mask-n':str(mask).lower()}
        if self.pack:
            wf=self.pack['workflows']['predict-'+('genome' if mode=='single' else 'metagenome')]
            result=None
            for step in wf['steps']:
                args=[]
                for arg in step['args']:
                    for key,value in values.items():arg=arg.replace('{input:'+key+'}',value)
                    for key,value in output.items():arg=arg.replace('{output:'+key+'}',str(value))
                    self.assertNotIn('{',arg);args.append(arg)
                result=self.invoke([PACK/self.pack['tools'][step['tool']]['path'],*args])
                if result.returncode:break
                if step.get('stdout'):output[step['stdout']].write_text(result.stdout)
        else:
            result=self.invoke([self.guard,'bundled',mode,source,output['annotations'],output['proteins'],output['cds'],code,model,str(closed).lower(),str(mask).lower(),'report-v1'])
            if result.returncode==0:output['summary'].write_text(result.stdout)
        self.assertEqual(hashlib.sha256(Path(source).read_bytes()).hexdigest(),input_before,'Scientific input changed during execution')
        if okay:self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        return result,output
    def consistency(self,source,outputs,code='11'):
        inputs=sequences(source);proteins=sequences(outputs['proteins']);cds=sequences(outputs['cds']);counts={}
        rows=annotations(outputs['annotations']);self.assertEqual(len(rows),len(cds));self.assertEqual(set(cds),set(proteins))
        for row in rows:
            contig=row[0];counts[contig]=counts.get(contig,0)+1;identity=contig+'_'+str(counts[contig]);start,end=int(row[3]),int(row[4])
            self.assertGreaterEqual(start,1);self.assertLessEqual(end,len(inputs[contig]));self.assertEqual(row[7],'0')
            dna=inputs[contig][start-1:end].upper()
            if row[6]=='-':dna=reverse_complement(dna)
            self.assertEqual(cds[identity],dna)
            attrs=dict(item.split('=',1) for item in row[8].split(';') if '=' in item)
            partial=attrs['partial'];complete_start=(partial[0]=='0' if row[6]=='+' else partial[1]=='0')
            self.assertEqual(proteins[identity],translate(dna,code,complete_start))
        return rows
    def test_version_and_upstream_metadata_are_preserved(self):
        if PACK:
            self.assertEqual(pe_stack(self.binary),(WINDOWS_STACK_RESERVE,WINDOWS_STACK_COMMIT),'Native executable must reserve enough stack for upstream non-SD training')
        result=self.invoke([self.binary,'-v']);self.assertEqual(result.returncode,0);self.assertIn(VERSION,result.stdout+result.stderr)
        _,out=self.predict();gff=out['annotations'].read_text();self.assertIn('version=Prodigal.v'+VERSION,gff);self.assertIn('ID=1_1;partial=00;',gff);self.assertIn('model="',gff)
    def test_genome_exact_constructed_genes_and_both_strands(self):
        _,out=self.predict('single');rows=self.consistency(self.input/'genome.fna',out)
        truth=self.truth['planted'];self.assertEqual(len(rows),len(truth))
        self.assertEqual([(int(r[3]),int(r[4]),r[6]) for r in rows],[(x['start'],x['end'],x['strand']) for x in truth])
        self.assertEqual(sequences(out['proteins']),{'synthetic_genome_'+str(i+1):x['protein'] for i,x in enumerate(truth)})
    def test_metagenome_exact_constructed_genes_and_model(self):
        _,out=self.predict();rows=self.consistency(self.input/'metagenome.fna',out)
        truth=[x for x in self.truth['planted'] if 'meta' in x];self.assertEqual(len(rows),4)
        self.assertEqual([(r[0],int(r[3]),int(r[4]),r[6]) for r in rows],[(x['meta']['contig'],x['meta']['start'],x['meta']['end'],x['strand']) for x in truth])
        self.assertEqual(sequences(out['proteins']),{x['meta']['contig']+'_1':x['protein'] for x in truth});self.assertIn('transl_table=11;',out['annotations'].read_text())
    def test_alternative_genetic_codes_translate_constructed_tga(self):
        source=self.input/'alternative-codes.fna'
        for code in ('4','25'):
            with self.subTest(code=code):
                _,out=self.predict('single',source,code=code);self.consistency(source,out,code)
                self.assertEqual(sequences(out['proteins']),{x['contig']+'_1':x['protein'+code] for x in self.truth['reassigned']})
                self.assertIn('transl_table='+code+';',out['annotations'].read_text())
        _,out=self.predict('single',source,code='11');self.consistency(source,out,'11')
        self.assertFalse(any(len(x)==300 for x in sequences(out['proteins']).values()))
    def test_no_genes_preserves_empty_sequences(self):
        _,out=self.predict(input=self.input/'no-genes.fna',closed=True)
        self.assertEqual(out['proteins'].read_bytes(),b'');self.assertEqual(out['cds'].read_bytes(),b'');self.assertEqual(annotations(out['annotations']),[])
        self.assertEqual(json.loads(out['summary'].read_text())['predictedGenes'],0)
    def test_closed_ends_excludes_constructed_partial_gene(self):
        source=self.root/'partial.fna';fasta(source,[('partial',self.truth['planted'][0]['cds'][150:-150])])
        _,open_out=self.predict(input=source);rows=self.consistency(source,open_out);self.assertEqual(len(rows),1);self.assertNotIn('partial=00;',rows[0][8])
        _,closed_out=self.predict(input=source,closed=True);self.assertEqual(annotations(closed_out['annotations']),[])
    def test_n_gap_masking_and_recorded_exact_arguments(self):
        source=self.root/'gap.fna';cds=self.truth['planted'][0]['cds'];fasta(source,[('gap',cds[:450]+'N'*60+cds[450:])])
        _,out=self.predict(input=source,mask=True);rows=self.consistency(source,out)
        for row in rows:self.assertFalse(int(row[3])<=450 and int(row[4])>=511)
        report=json.loads(out['summary'].read_text());self.assertEqual(report['ambiguousBases'],60);self.assertIn('-m',report['command'])
        _,unmasked=self.predict(input=source,mask=False);self.assertNotIn('-m',json.loads(unmasked['summary'].read_text())['command'])
    def test_non_sd_model_records_actual_flag(self):
        _,out=self.predict('single',model='nonsd');self.consistency(self.input/'genome.fna',out);report=json.loads(out['summary'].read_text());self.assertIn('-n',report['command']);self.assertIn('uses_sd=0',out['annotations'].read_text())
    def test_malformed_inputs_fail_before_creating_predictions(self):
        cases={'empty':b'','duplicate':b'>same a\nACGT\n>same b\nACGT\n','protein':b'>p\nMKWVTF\n','ambiguous':b'>x\nACGTR\n','empty-record':b'>a\n>b\nACGT\n','bad-id':b'>a;b\nACGT\n','compressed':b'\x1f\x8bnotplain','long-line':b'>a\n'+b'A'*8193+b'\n','nul':b'>x\nAC\x00GT\n'}
        for name,data in cases.items():
            with self.subTest(case=name):
                source=self.root/(name+'.fna');source.write_bytes(data);result,out=self.predict(input=source,okay=False)
                self.assertNotEqual(result.returncode,0);self.assertIn('Prodigal input/run error:',result.stderr);self.assertFalse(out['annotations'].exists())
    def test_missing_bundled_executable_fails_clearly(self):
        alone=self.root/'missing sibling tools';alone.mkdir();guard=alone/self.guard.name;shutil.copy2(self.guard,guard)
        result=self.invoke([guard,'bundled','meta',self.input/'metagenome.fna',alone/'genes.gff',alone/'proteins.faa',alone/'cds.fna','auto','auto','false','true','report-v1'])
        self.assertNotEqual(result.returncode,0);self.assertIn('Prodigal input/run error:',result.stderr);self.assertFalse((alone/'genes.gff').exists())
    def test_short_genome_has_actionable_failure(self):
        result,out=self.predict('single',self.input/'metagenome.fna',okay=False);self.assertNotEqual(result.returncode,0);self.assertIn('at least 20,000',result.stderr);self.assertIn('metagenome mode',result.stderr);self.assertFalse(out['annotations'].exists())
    def test_lowercase_crlf_preserves_predictions(self):
        source=self.root/'lower case.fna';source.write_bytes((self.input/'metagenome.fna').read_bytes().lower().replace(b'\n',b'\r\n'))
        _,normal=self.predict();_,lower=self.predict(input=source);self.assertEqual(sequences(normal['proteins']),sequences(lower['proteins']));self.assertEqual(sequences(normal['cds']),sequences(lower['cds']))
    def test_declared_installation_checks_assert_actual_scientific_outputs(self):
        for case in checks(self.truth)['checks']:
            mode='single' if case['workflow']=='predict-genome' else 'meta'
            fixture=case['inputs']['sequence'][0]['sequence'].replace('fixture-','')+'.fna'
            _,out=self.predict(mode,self.input/fixture,closed=case['params']['closed-ends'])
            result={'outputs':{'step-1::'+key:{'files':{key:str(value)}} for key,value in out.items()}}
            for expectation in case['expect']:_assert_output(expectation,result)
    @unittest.skipIf(os.name=='nt','Pristine Linux reference comparison is a separate platform gate')
    def test_pristine_upstream_scientific_results_match(self):
        reference=CACHE/'reference-linux/prodigal'
        if not reference.is_file():self.skipTest('Build --linux --upstream for independent pristine-source comparison')
        for mode,code,fixture in [('single','11','genome'),('meta','auto','metagenome'),('single','4','alternative-codes'),('single','25','alternative-codes')]:
            _,out=self.predict(mode,self.input/(fixture+'.fna'),code=code)
            ref=self.root/('reference '+mode+code);ref.mkdir()
            args=[reference,'-p',mode,'-i',self.input/(fixture+'.fna'),'-f','gff','-o',ref/'genes.gff','-a',ref/'proteins.faa','-d',ref/'cds.fna','-m']
            if mode=='single':args+=['-g',code]
            result=self.invoke(args);self.assertEqual(result.returncode,0,result.stderr)
            self.assertEqual([r[2:8] for r in annotations(out['annotations'])],[r[2:8] for r in annotations(ref/'genes.gff')])
            self.assertEqual(sequences(out['proteins']),sequences(ref/'proteins.faa'));self.assertEqual(sequences(out['cds']),sequences(ref/'cds.fna'))

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--pack',type=Path);parser.add_argument('--report',type=Path);args,remaining=parser.parse_known_args()
    PACK=args.pack.resolve() if args.pack else None
    if not PACK and args.report:
        missing=[str(CACHE/name) for name in ('build-linux/prodigal','build-linux/prodigal-guard','reference-linux/prodigal') if not (CACHE/name).is_file()]
        if missing:parser.error('Required Linux science binaries are absent: '+', '.join(missing))
    if PACK and os.name!='nt':parser.error('--pack requires native Windows; Linux source tests use NW_PRODIGAL_CACHE')
    suite=unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__])
    if PACK:
        # The separately reported pristine Linux reference gate is not selected
        # as a native Windows test; no unavailable Windows check is hidden here.
        suite=unittest.TestSuite(test for group in suite for test in group if test._testMethodName!='test_pristine_upstream_scientific_results_match')
    result=unittest.TextTestRunner(verbosity=2).run(suite)
    if args.report:
        value={'schema':1,'success':result.wasSuccessful() and not result.skipped,'executions':EXECUTIONS,'platform':platform.platform(),'nativeWindowsExecuted':os.name=='nt','pack':str(PACK) if PACK else None,'testsRun':result.testsRun,'passed':result.testsRun-len(result.failures)-len(result.errors)-len(result.skipped),'failed':len(result.failures)+len(result.errors),'skipped':[{'test':str(t),'reason':r} for t,r in result.skipped],'failures':[{'test':str(t),'detail':detail} for t,detail in result.failures+result.errors]}
        if PACK:value['files']={str(p.relative_to(PACK)):{'sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'bytes':p.stat().st_size} for p in [PACK/'pack.ini',*sorted((PACK/'bin').glob('*.exe'))]}
        args.report.parent.mkdir(parents=True,exist_ok=True);args.report.write_text(json.dumps(value,indent=2)+'\n')
    sys.exit(0 if result.wasSuccessful() else 1)
