"""Real HISAT2 source-build and pack regression tests; Windows execution is not inferred."""
import copy, gzip, hashlib, json, os, shutil, subprocess, sys, tempfile, threading, unittest
from pathlib import Path
SOURCE=Path(__file__).resolve().parents[1]
PACK=SOURCE/'packs/hisat2-0.5.3'
CACHE=SOURCE/'vendor-expanded/hisat2'
sys.path.insert(0,str(SOURCE/'workspace'))
from catalog import load_pack, parse_pack, describe_workflow, TYPES
from engine import Engine, digest_file, pin_for
from pack_checks import run_pack_checks, _assert_output
BINARIES={
 'hisat2-align-l':(CACHE/'build-linux/hisat2-align-l','95675bc96e8914f60c41fdee9000211ef2414461e9e21d508f382156ae9d2eae'),
 'hisat2-build-l':(CACHE/'build-linux/hisat2-build-l','0d63724b08d0ebea41b8a161406253b12a1b91301088bdfbc751295b8d312200'),
}

class LinuxHisat2Backend:
    """Execute published manifest arguments with pinned Linux reference builds."""
    def __init__(self):
        self.calls = []
        self.commands = []
        for identity, (path, checksum) in BINARIES.items():
            if not path.is_file():
                raise RuntimeError('Required real integration binary is missing: ' + str(path))
            if digest_file(path) != checksum:
                raise RuntimeError('Integration binary hash differs: ' + identity)

    def run(self, request, event, cancel):
        self.calls.append(copy.deepcopy(request))
        pack_root = Path(request['pack_folder'])
        if digest_file(pack_root / 'pack.ini') != request['pack_sha256']:
            raise ValueError('Pack changed before the test adapter executed')
        pack = parse_pack((pack_root / 'pack.ini').read_text(encoding='utf-8'))
        workflow = pack['workflows'][request['workflow_id']]
        folder = Path(request['output_folder']) / 'linux-validation'
        folder.mkdir()
        outputs = {item['id']: str(folder / item['path']) for item in workflow['outputs']}
        for filename in outputs.values():
            Path(filename).parent.mkdir(parents=True, exist_ok=True)
        assets = {key: str(pack_root / value['path']) for key, value in pack['assets'].items()}

        def expand(value):
            value = value.replace('{run}', str(folder))
            for kind, bindings in (('input', request['values']), ('output', outputs), ('asset', assets)):
                for key, replacement in bindings.items():
                    value = value.replace('{' + kind + ':' + key + '}', str(replacement))
            if '{' in value or '}' in value:
                raise ValueError('Unexpanded manifest placeholder: ' + value)
            return value

        def command(identity, arguments):
            declared = pack['tools'][identity]
            if digest_file(pack_root / declared['path']) != declared['sha256']:
                raise ValueError('Declared Windows executable hash differs')
            if identity in ('paircheck','samtools'):
                # Existing portable integrity-pinned mate checker used by the
                # VSEARCH pack before overlap merging; it is not substituted.
                argv = [str(SOURCE / 'baselines/bin/ape-loader-linux'), str(pack_root / declared['path'])]
            elif identity not in BINARIES:
                raise ValueError('No explicit test substitution for executable: ' + identity)
            else:
                binary, checksum = BINARIES[identity]
                if digest_file(binary) != checksum:
                    raise ValueError('Linux validation executable changed')
                argv = [str(binary)]
            for argument in arguments:
                if argument.startswith('{inputs:') and argument.endswith('}'):
                    argv.extend(str(request['values'][argument[8:-1]]).splitlines())
                else:
                    argv.append(expand(argument))
            self.commands.append(argv)
            return argv

        try:
            for step in workflow['steps']:
                if cancel.is_set():
                    return {'success': False, 'cancelled': True, 'folder': str(folder)}
                event({'type': 'phase', 'message': step['label']})
                if step['kind'] == 'copy':
                    shutil.copyfile(expand(step['source']), outputs[step['destination']])
                    continue
                if step['kind'] != 'exec':
                    raise ValueError('Expansion validation adapter requires explicit exec/copy steps')
                stdout_path = Path(outputs[step['stdout']]) if step.get('stdout') else folder / (step['id'] + '.stdout.txt')
                stderr_path = folder / (step['id'] + '.stderr.txt')
                with stdout_path.open('wb') as stdout, stderr_path.open('wb') as stderr:
                    completed = subprocess.run(command(step['tool'], step['args']), cwd=folder,
                                               stdout=stdout, stderr=stderr, timeout=45)
                if completed.returncode:
                    raise ValueError('Real tool failed (%s): %s' % (completed.returncode, stderr_path.read_text(errors='replace')[-8000:]))
            for output in workflow['outputs']:
                path = Path(outputs[output['id']])
                if not path.is_file() or (output['nonempty'] and path.stat().st_size == 0):
                    raise ValueError('Manifest output missing or unexpectedly empty: ' + output['id'])
            return {'success': True, 'folder': str(folder), 'message': 'Real pinned Linux scientific executable completed'}
        except Exception as exc:
            return {'success': False, 'folder': str(folder), 'message': str(exc)}


def sam_rows(path):
    return [line.split('\t') for line in Path(path).read_text().splitlines() if line and not line.startswith('@')]


def graph_for(identity):
    family=identity.split('-')[0];paired=identity.endswith('paired')
    files={'reads1':str(PACK/'fixtures'/(family+'-r1.fastq')),'reads2':str(PACK/'fixtures'/(family+'-r2.fastq'))} if paired else {'reads':str(PACK/'fixtures'/(family+'-single.fastq'))}
    return {'schema':1,'name':'HISAT2 scientific check','sources':[{'id':'input-1','label':'Synthetic reads','type':'pair' if paired else 'reads','files':files},{'id':'input-2','label':'Synthetic reference','type':'reference','files':{'reference':str(PACK/'fixtures/reference.fa')}}],'nodes':[{'id':'step-1','tool':'hisat2/'+identity,'inputs':{'reads':['input-1'],'reference':['input-2']},'params':{'sample':'validation','read-group':'validation','library':'lib1','platform-unit':'unit1','threads':'1','seed':'0'}}]}


def catalog():
    pack=load_pack(PACK/'pack.ini')
    tools={}
    for workflow in pack['workflows'].values():
        tool=describe_workflow(pack,workflow,'packs/hisat2-0.5.3',pack['manifestSha256']);tools[tool['id']]=tool
    return {'schema':1,'tools':tools,'types':TYPES,'packs':[{'id':'hisat2','version':'0.5.3'}]}


class Hisat2PackTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog=catalog()
        cls.temp=tempfile.TemporaryDirectory(prefix='hisat2 scientific spaces ')
        cls.folder=Path(cls.temp.name)
        cls.backend=LinuxHisat2Backend();cls.engine=Engine(SOURCE,cls.catalog,backend=cls.backend)
        cls.results={}
        for identity in ('rna-single','rna-paired','dna-single','dna-paired'):
            plan=cls.engine.prepare(graph_for(identity),cls.folder)
            result=cls.engine.execute(plan)
            if not result['success']:raise AssertionError(result)
            cls.results[identity]=result

    @classmethod
    def tearDownClass(cls):cls.temp.cleanup()

    def test_four_scientific_alignment_specs(self):
        checks=json.loads((PACK/'workbench-checks.json').read_text())
        for case in checks['checks']:
            with self.subTest(workflow=case['workflow']):
                for expectation in case['expect']:_assert_output(expectation,self.results[case['workflow']])

    def test_rna_coordinate_bam_and_csi(self):
        for identity in ('rna-single','rna-paired'):
            result=self.results[identity]
            bam=Path(result['outputs']['step-1::aligned']['files']['aligned'])
            csi=Path(result['outputs']['step-1::bam-index']['files']['bam-index'])
            command=[str(SOURCE/'baselines/bin/ape-loader-linux'),str(PACK/'bin/samtools.exe')]
            header=subprocess.check_output([*command,'view','-H',str(bam)],text=True)
            self.assertIn('SO:coordinate',header);self.assertIn('SM:validation',header)
            self.assertGreater(csi.stat().st_size,0)
            region=subprocess.check_output([*command,'view',str(bam),'chrSynthetic:471-500'],text=True)
            self.assertIn('30M100N30M',region)
            self.assertEqual(result['outputs']['step-1::aligned']['type'],'bam-rna')

    def test_unstranded_matches_unmodified_upstream(self):
        upstream=CACHE/'build-linux-upstream/hisat2-align-l'
        self.assertTrue(upstream.is_file())
        self.assertEqual(digest_file(upstream),'f17f6fa1ca9576779c563e4e65f548c632c48b77141509cadb502b1cf99279e3')
        for identity in ('rna-single','rna-paired'):
            result=self.results[identity]
            sam=Path(result['outputs']['step-1::aligned-sam']['files']['aligned-sam']);folder=sam.parent
            output=self.folder/(identity+'-upstream.sam')
            command=[str(upstream),'--wrapper','basic-0','-x',str(folder/'reference'),'-S',str(output),'-p','1','--seed','0','--reorder','--phred33','--dta','--min-intronlen','20','--max-intronlen','500000','--rg-id','validation','--rg','SM:validation','--rg','LB:lib1','--rg','PL:ILLUMINA','--rg','PU:unit1']
            command+=['--fr','-1',str(PACK/'fixtures/rna-r1.fastq'),'-2',str(PACK/'fixtures/rna-r2.fastq')] if identity.endswith('paired') else ['-U',str(PACK/'fixtures/rna-single.fastq')]
            result=subprocess.run(command,capture_output=True,text=True,timeout=30)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertEqual(sam_rows(sam),sam_rows(output))

    def test_strandedness_options_assign_transcript_strand(self):
        sam=Path(self.results['rna-single']['outputs']['step-1::aligned-sam']['files']['aligned-sam'])
        for option,expected in [('F','+'),('R','-'),('FR','+'),('RF','-')]:
            output=self.folder/('strand-'+option+'.sam')
            command=[str(BINARIES['hisat2-align-l'][0]),'--wrapper','basic-0','-x',str(sam.parent/'reference'),'-S',str(output),'-p','1','--dta','--rna-strandness',option]
            command+=['-U',str(PACK/'fixtures/rna-single.fastq')] if len(option)==1 else ['--fr','-1',str(PACK/'fixtures/rna-r1.fastq'),'-2',str(PACK/'fixtures/rna-r2.fastq')]
            completed=subprocess.run(command,capture_output=True,text=True,timeout=30)
            self.assertEqual(completed.returncode,0,completed.stderr)
            mapped=[row for row in sam_rows(output) if not(int(row[1])&4)]
            self.assertTrue(mapped)
            self.assertTrue(all('XS:A:'+expected in row[11:] for row in mapped),(option,mapped))

    def test_no_splice_dna_rejects_junction_and_bad_intron_bounds(self):
        sam=Path(self.results['rna-single']['outputs']['step-1::aligned-sam']['files']['aligned-sam'])
        common=[str(BINARIES['hisat2-align-l'][0]),'--wrapper','basic-0','-x',str(sam.parent/'reference'),'-U',str(PACK/'fixtures/rna-single.fastq'),'-p','1']
        no_splice=self.folder/'dna-junction.sam'
        result=subprocess.run([*common,'--no-spliced-alignment','-S',str(no_splice)],capture_output=True,text=True,timeout=30)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertTrue(all('N' not in row[5] for row in sam_rows(no_splice)))
        bad=self.folder/'bad-intron.sam'
        result=subprocess.run([*common,'--min-intronlen','1000','--max-intronlen','20','-S',str(bad)],capture_output=True,text=True,timeout=30)
        self.assertNotEqual(result.returncode,0);self.assertFalse(bad.exists())

    def test_mismatched_mates_fail_before_indexing(self):
        wrong=self.folder/'wrong-r2.fastq'
        wrong.write_text((PACK/'fixtures/rna-r2.fastq').read_text().replace('@rna_pair/2','@different_read/2'))
        graph=graph_for('rna-paired');graph['sources'][0]['files']['reads2']=str(wrong)
        backend=LinuxHisat2Backend();engine=Engine(SOURCE,self.catalog,backend=backend)
        result=engine.execute(engine.prepare(graph,self.folder))
        self.assertFalse(result['success'])
        self.assertEqual(len(backend.commands),1)
        self.assertIn('paircheck.exe',backend.commands[0][1])
        self.assertFalse(any(Path(result['folder']).rglob('*.ht2l')))

    def test_rna_cannot_feed_dna_preparation(self):
        base=SOURCE.parents[1]/'integration-0.5.2/native-workbench/packs/bam-0.4.0'
        pack=load_pack(base/'pack.ini');workflow=pack['workflows']['name-sort']
        dna=describe_workflow(pack,workflow,'packs/bam-0.4.0',pack['manifestSha256'])
        cat=copy.deepcopy(self.catalog);cat['tools'][dna['id']]=dna
        graph=graph_for('rna-single')
        graph['nodes'].append({'id':'step-2','tool':dna['id'],'params':{},'inputs':{'alignment':['step-1::aligned']}})
        result=Engine(SOURCE,cat,backend=self.backend).validate(graph,check_files=False)
        self.assertFalse(result['valid']);self.assertTrue(any(row.get('portId')=='alignment' and 'bam-rna' in row['message'] for row in result['errors']),result)

    def test_dependent_bounds_reject_during_review(self):
        for identity,left,right in [('rna-single','min-intron','max-intron'),('rna-paired','min-intron','max-intron'),('dna-paired','min-insert','max-insert')]:
            graph=graph_for(identity);graph['nodes'][0]['params'].update({left:'1000',right:'20'})
            self.assertFalse(self.engine.validate(graph)['valid'])

    def test_paths_compression_hashes_and_inventory(self):
        for filename in ('nonascii-\u00e9.fastq','comma,reads.fastq'):
            path=self.folder/filename;path.write_bytes((PACK/'fixtures/rna-single.fastq').read_bytes())
            graph=graph_for('rna-single');graph['sources'][0]['files']['reads']=str(path)
            self.assertFalse(self.engine.validate(graph)['valid'])
        path=self.folder/'compressed.fastq.gz';path.write_bytes(gzip.compress((PACK/'fixtures/rna-single.fastq').read_bytes()))
        graph=graph_for('rna-single');graph['sources'][0]['files']['reads']=str(path)
        self.assertFalse(self.engine.validate(graph)['valid'])
        pack=load_pack(PACK/'pack.ini')
        declared={a['path'] for group in ('tools','assets') for a in pack[group].values()}
        for group in ('tools','assets'):
            for asset in pack[group].values():self.assertEqual(digest_file(PACK/asset['path']),asset['sha256'])
        for path in PACK.rglob('*'):
            relative=path.relative_to(PACK).as_posix()
            if path.is_file() and not relative.startswith('licenses/') and relative not in ('pack.ini','PACK-README.md'):self.assertIn(relative,declared)
        self.assertLess(sum(path.is_file() for path in PACK.rglob('*')),2000)
        self.assertLess(sum(path.stat().st_size for path in PACK.rglob('*') if path.is_file()),256*1024*1024)
        for entry in json.loads((PACK/'licenses/windows-build.json').read_text())['files'].values():
            self.assertTrue(all(name.lower()=='kernel32.dll' or name.lower().startswith('api-ms-win-crt-') for name in entry['imports']))

    def test_generic_pack_selfcheck_engine(self):
        report=run_pack_checks(SOURCE,self.catalog,self.folder,backend=LinuxHisat2Backend())
        self.assertEqual(report['passed'],4,report);self.assertEqual(report['failed'],0,report)

if __name__=='__main__':unittest.main()
