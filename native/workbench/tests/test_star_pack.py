"""Real STAR scientific regression checks; Linux execution is separately identified."""
import copy, hashlib, json, os, shutil, subprocess, sys, tempfile, unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
PACK=ROOT/'packs/star-1.0.0'
CACHE=ROOT.parent/'rna-build/star'
sys.path.insert(0,str(ROOT/'workspace'))
from catalog import load_pack, parse_pack, describe_workflow, TYPES
from engine import Engine, digest_file
from pack_checks import _assert_output

class LinuxStarBackend:
    def __init__(self):self.commands=[]
    def run(self,request,event,cancel):
        folder=Path(request['output_folder'])/'linux-validation';folder.mkdir()
        pack=load_pack(Path(request['pack_folder'])/'pack.ini')
        if pack['manifestSha256']!=request['pack_sha256']:raise ValueError('Pack changed')
        workflow=pack['workflows'][request['workflow_id']]
        outputs={v['id']:str(folder/v['path']) for v in workflow['outputs']}
        def expand(value):
            value=value.replace('{run}',str(folder))
            for prefix,bindings in [('input',request['values']),('output',outputs)]:
                for key,replacement in bindings.items():value=value.replace('{'+prefix+':'+key+'}',str(replacement))
            if '{' in value:raise ValueError('Unexpanded placeholder: '+value)
            return value
        try:
            for step in workflow['steps']:
                tool=pack['tools'][step['tool']];declared=PACK/tool['path']
                if digest_file(declared)!=tool['sha256']:raise ValueError('Declared Windows executable changed')
                if step['tool']=='star':
                    binary=CACHE/'build-linux/STAR';record=json.loads((CACHE/'build-linux/build.json').read_text())
                    if digest_file(binary)!=record['files']['STAR']['sha256']:raise ValueError('Linux STAR build changed')
                    command=[str(binary)]
                else:
                    loader=ROOT.parent/'integration-source/native-workbench/baselines/bin/ape-loader-linux'
                    command=[str(loader),str(declared)]
                command += [expand(v) for v in step['args']];self.commands.append(command)
                destination=Path(outputs[step['stdout']]) if step.get('stdout') else folder/(step['id']+'.stdout.txt')
                with destination.open('wb') as stdout:
                    result=subprocess.run(command,cwd=folder,stdout=stdout,stderr=subprocess.PIPE,timeout=90)
                if result.returncode:raise ValueError('STAR step '+step['id']+' failed: '+result.stderr.decode(errors='replace'))
            return {'success':True,'folder':str(folder),'message':'Real Linux scientific reference execution'}
        except Exception as e:return {'success':False,'folder':str(folder),'message':str(e)}

def catalog():
    pack=load_pack(PACK/'pack.ini');tools={}
    for w in pack['workflows'].values():
        t=describe_workflow(pack,w,'packs/star-1.0.0',pack['manifestSha256']);tools[t['id']]=t
    return {'schema':1,'tools':tools,'types':TYPES,'packs':[{'id':'step-1','version':'1.0.0'}]}

def graph_for(identity):
    paired='paired' in identity;counts=identity.endswith('counts')
    sources=[{'id':'input-1','label':'Synthetic RNA reads','type':'pair' if paired else 'reads','files':{'reads1':str(PACK/'fixtures/rna-r1.fastq'),'reads2':str(PACK/'fixtures/rna-r2.fastq')} if paired else {'reads':str(PACK/'fixtures/rna-single.fastq')}},{'id':'input-2','label':'Genome','type':'reference','files':{'reference':str(PACK/'fixtures/reference.fa')}}]
    inputs={'reads':['input-1'],'reference':['input-2']}
    if counts:sources.append({'id':'input-3','label':'GTF','type':'text','files':{'text':str(PACK/'fixtures/annotation.gtf')}});inputs['annotation']=['input-3']
    return {'schema':1,'name':'STAR scientific regression','sources':sources,'nodes':[{'id':'step-1','tool':'star/'+identity,'inputs':inputs,'params':{'sample':'validation','read-group':'validation','threads':'2' if paired and counts else '1'}}]}

@unittest.skipUnless((CACHE/'build-linux/STAR').is_file() and (PACK/'pack.ini').is_file(),'Build STAR pack and Linux scientific reference first')
class StarPackTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory(prefix='star scientific spaces ');cls.folder=Path(cls.temp.name)
        cls.backend=LinuxStarBackend();cls.engine=Engine(ROOT,catalog(),backend=cls.backend);cls.results={}
        for identity in ('rna-single','rna-paired','rna-single-counts','rna-paired-counts'):
            result=cls.engine.execute(cls.engine.prepare(graph_for(identity),cls.folder))
            if not result['success']:raise AssertionError(result)
            cls.results[identity]=result
        graph=graph_for('rna-single-counts');graph['sources'][0]['files']['reads']=str(PACK/'fixtures/rna-unmapped.fastq')
        result=cls.engine.execute(cls.engine.prepare(graph,cls.folder))
        if not result['success']:raise AssertionError(result)
        cls.results['rna-unmapped-counts']=result
    @classmethod
    def tearDownClass(cls):cls.temp.cleanup()
    def output(self,identity,key):return Path(self.results[identity]['outputs']['step-1::'+key]['files'][key])
    def test_splice_positions_mates_and_counts(self):
        for check in json.loads((PACK/'workbench-checks.json').read_text())['checks']:
            for expected in check['expect']:
                # Pack checker expects the single node's conventional step-1 identifier.
                result=copy.deepcopy(self.results[check['id']]);result['outputs']={k.replace('star::','step-1::'):v for k,v in result['outputs'].items()}
                with self.subTest(workflow=check['workflow'],output=expected['output']):_assert_output(expected,result)
    def test_coordinate_bam_and_csi(self):
        loader=ROOT.parent/'integration-source/native-workbench/baselines/bin/ape-loader-linux'
        for identity in ('rna-single','rna-paired','rna-single-counts','rna-paired-counts'):
            bam=self.output(identity,'aligned');cmd=[str(loader),str(PACK/'bin/samtools.exe')]
            self.assertIn('SO:coordinate',subprocess.check_output([*cmd,'view','-H',str(bam)],text=True))
            self.assertIn('50M800N50M',subprocess.check_output([*cmd,'view',str(bam),'chrSynthetic:651-700'],text=True))
            self.assertGreater(self.output(identity,'bam-index').stat().st_size,0)
    def test_small_chunk_recycling_matches_upstream(self):
        # Force >50 input chunks and repeated SAM flushes with the same source
        # adapter compiled on both platforms. Reusing tiny chunks must not repeat
        # stale reads, lose the final chunk, or detach SAM bytes from the buffer.
        original=self.output('rna-paired-counts','aligned-sam')
        source_command=next(c for c in self.backend.commands if '--readFilesIn' in c and c[c.index('--outFileNamePrefix')+1]==str(original.parent)+'/')
        count=200;mates=[]
        for mate in (1,2):
            text=(PACK/('fixtures/rna-r'+str(mate)+'.fastq')).read_text()
            path=self.folder/('many-r'+str(mate)+'.fastq')
            path.write_text(''.join(text.replace('@rna_pair','@rna_pair_'+str(i)) for i in range(count)))
            mates.append(str(path))
        products=[]
        for label,binary,limits in [('bounded',CACHE/'build-linux/STAR',['--limitIObufferSize','204000','6000','--limitOutSAMoneReadBytes','1000']),('upstream',CACHE/'reference-upstream/STAR',[])]:
            folder=self.folder/('chunk-'+label);folder.mkdir()
            command=source_command.copy();command[0]=str(binary)
            command[command.index('--outFileNamePrefix')+1]=str(folder)+'/'
            start=command.index('--readFilesIn')+1;command[start:start+2]=mates
            completed=subprocess.run(command+limits,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=90)
            self.assertEqual(completed.returncode,0,completed.stderr.decode())
            lines=sorted(line for line in (folder/'Aligned.out.sam').read_text().splitlines() if not line.startswith('@'))
            self.assertEqual(len(lines),2*count)
            self.assertIn('gene1\t200\t200\t0',(folder/'ReadsPerGene.out.tab').read_text())
            products.append((lines,(folder/'ReadsPerGene.out.tab').read_bytes()))
        self.assertEqual(products[0],products[1])
    def test_matches_official_upstream_alignments_and_gene_counts(self):
        upstream=CACHE/'reference-upstream/STAR'
        self.assertTrue(upstream.is_file(),'Extract official Linux reference from pinned STAR archive')
        self.assertEqual(digest_file(upstream),'36e94b899a56b0ea5de5d65e722f55bc552b6713bd2d1e83a5c2abbd06c9881a')
        for identity in ('rna-single','rna-paired-counts'):
            original=self.output(identity,'aligned-sam');folder=self.folder/(identity+' upstream');folder.mkdir()
            source_command=next(c for c in self.backend.commands if '--readFilesIn' in c and c[c.index('--outFileNamePrefix')+1]==str(original.parent)+'/')
            command=source_command.copy();command[0]=str(upstream);command[command.index('--outFileNamePrefix')+1]=str(folder)+'/'
            result=subprocess.run(command,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=90)
            self.assertEqual(result.returncode,0,result.stderr.decode())
            def alignments(p):return sorted(line for line in p.read_text().splitlines() if not line.startswith('@'))
            self.assertEqual(alignments(original),alignments(folder/'Aligned.out.sam'))
            if identity.endswith('counts'):self.assertEqual(self.output(identity,'gene-counts').read_bytes(),(folder/'ReadsPerGene.out.tab').read_bytes())
    def test_strict_annotation_rejections(self):
        valid=(PACK/'fixtures/annotation.gtf').read_text()
        invalid=[valid.replace('chrSynthetic','wrongAssembly'),valid.replace('\t301\t','\t0\t'),valid.replace('gene_id "gene1"; ',''),valid.replace('\t1900\t','\t10001\t'), 'not a GTF\n']
        for i,text in enumerate(invalid):
            directory=self.folder/('bad-annotation-'+str(i));directory.mkdir();gtf=directory/'bad.gtf';gtf.write_text(text)
            cmd=[str(CACHE/'build-linux/STAR'),'--runMode','genomeGenerate','--genomeDir',str(directory/'index')+'/', '--genomeFastaFiles',str(PACK/'fixtures/reference.fa'),'--genomeSAindexNbases','0','--sjdbGTFfile',str(gtf),'--sjdbOverhang','99','--outFileNamePrefix',str(directory)+'/']
            completed=subprocess.run(cmd,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=30)
            self.assertNotEqual(completed.returncode,0)
            self.assertIn('GTF',completed.stderr.decode())
    def test_compressed_reads_and_unsupported_paths_rejected(self):
        import gzip
        gz=self.folder/'reads.fastq.gz';gz.write_bytes(gzip.compress((PACK/'fixtures/rna-single.fastq').read_bytes()))
        for filename in [gz,self.folder/'reads,one.fastq',self.folder/'reads-\u00e9.fastq']:
            if filename!=gz:filename.write_bytes((PACK/'fixtures/rna-single.fastq').read_bytes())
            graph=graph_for('rna-single');graph['sources'][0]['files']['reads']=str(filename)
            with self.subTest(filename=filename.name), self.assertRaises(ValueError):self.engine.prepare(graph,self.folder)
    def test_mismatched_mates_fail_before_indexing(self):
        bad=self.folder/'mismatched.fastq';bad.write_text((PACK/'fixtures/rna-r2.fastq').read_text().replace('@rna_pair','@wrong_pair'))
        graph=graph_for('rna-paired');graph['sources'][0]['files']['reads2']=str(bad)
        before=len(self.backend.commands);result=self.engine.execute(self.engine.prepare(graph,self.folder))
        self.assertFalse(result['success']);self.assertEqual(len(self.backend.commands)-before,1)
    def test_pipeline_types_and_parameter_constraint(self):
        cat=catalog()
        for tool in cat['tools'].values():
            kinds={o['id']:o['type'] for o in tool['outputs']}
            self.assertEqual(kinds['aligned'],'bam-rna');self.assertEqual(kinds['aligned-sam'],'sam-rna')
        graph=graph_for('rna-single');graph['nodes'][0]['params'].update({'min-intron':'200','max-intron':'100'})
        self.assertFalse(self.engine.validate(graph)['valid'])
if __name__=='__main__':unittest.main()
