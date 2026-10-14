#!/usr/bin/env python3
"""Truth tests for Bowtie 2 manifest commands using its pinned Linux counterpart."""
import argparse
import gzip
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'workspace'),str(ROOT/'scripts')]
from catalog import load_pack
from pack_checks import _assert_output
from fetch_bowtie2_vendor import LINUX,WINDOWS,ARTIFACTS
PACK=ROOT/'packs/bowtie2-0.5.3'
BINARIES=ROOT.parents[1]/'expansion-vendor/bowtie2/linux-bin'
COMMANDS=[]


def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def parse_sam(path):
    headers=[];records=[]
    for line in Path(path).read_text().splitlines():
        if line.startswith('@'):headers.append(line.split('\t'));continue
        fields=line.split('\t');assert len(fields)>=11
        records.append(dict(name=fields[0],flag=int(fields[1]),reference=fields[2],position=int(fields[3]),mapq=int(fields[4]),cigar=fields[5],mate=fields[6],mate_position=int(fields[7]),insert=int(fields[8]),sequence=fields[9],quality=fields[10],tags={x.split(':',2)[0]:x.split(':',2)[2] for x in fields[11:]}))
    return headers,records


class BowtieTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pack=load_pack(PACK/'pack.ini')
        for name,digest in LINUX.items():assert sha(BINARIES/name)==digest,name
        for name,digest in WINDOWS.items():assert sha(PACK/'bin'/name)==digest,name
        cls.ape=ROOT/'baselines/bin/ape-loader-linux'
        assert cls.ape.is_file()

    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='Bowtie 2 truth ')
        self.root=Path(self.temp.name)

    def tearDown(self):self.temp.cleanup()

    def run_workflow(self,identity,values=None,success=True):
        workflow=self.pack['workflows'][identity]
        source={'reference':str(PACK/'fixtures/reference.fa'),'reads1':str(PACK/'fixtures/reads1.fastq'),'reads2':str(PACK/'fixtures/reads2.fastq')}
        if identity.startswith('single'):source['reads1']=str(PACK/'fixtures/single.fastq')
        source.update({i['id']:str(i['default']) for i in workflow['inputs'] if i['type'] not in ('file','files','directory') and i.get('default') is not None})
        source.update({'sample':'validation','read-group':'validation','library':'fixture','threads':'1'})
        source.update({k:str(v) for k,v in (values or {}).items()})
        before={Path(source[i['id']]):sha(Path(source[i['id']])) for i in workflow['inputs'] if i['type']=='file'}
        folder=self.root/('run-'+str(len(list(self.root.iterdir()))));folder.mkdir()
        outputs={item['id']:folder/item['path'] for item in workflow['outputs']}
        for path in outputs.values():path.parent.mkdir(parents=True,exist_ok=True)
        def expand(argument):
            result=argument.replace('{run}',str(folder))
            for kind,mapping in [('input',source),('output',outputs)]:
                for key,value in mapping.items():result=result.replace('{'+kind+':'+key+'}',str(value))
            self.assertNotIn('{',result)
            return result
        failed=False;diagnostic=''
        for step in workflow['steps']:
            if step['kind']=='copy':shutil.copyfile(expand(step['source']),outputs[step['destination']]);continue
            self.assertEqual(step['kind'],'exec')
            tool=step['tool']
            executable=([str(self.ape),str(PACK/'bin/paircheck.exe')] if tool=='paircheck' else [str(BINARIES/('bowtie2-'+tool))])
            stdout=outputs[step['stdout']] if step.get('stdout') else folder/(step['id']+'.stdout.txt')
            argv=executable+[expand(value) for value in step['args']]
            with stdout.open('wb') as stream:
                run=subprocess.run(argv,stdout=stream,stderr=subprocess.PIPE,timeout=60)
            diagnostic=run.stderr.decode(errors='replace')
            COMMANDS.append({'workflow':identity,'step':step['id'],'tool':tool,'exitCode':run.returncode})
            if run.returncode:
                failed=True;break
        for path,digest in before.items():self.assertEqual(sha(path),digest,'Input modified: '+str(path))
        self.assertEqual(failed,not success,diagnostic)
        if success:
            for item in workflow['outputs']:
                self.assertTrue(outputs[item['id']].is_file(),item['id'])
                if item['nonempty']:self.assertGreater(outputs[item['id']].stat().st_size,0,item['id'])
        return outputs

    def assert_single(self,outputs):
        headers,records=parse_sam(outputs['sam'])
        self.assertEqual(len(records),3)
        self.assertEqual([(r['name'],r['flag'],r['position'],r['cigar']) for r in records],
                         [('single1',0,301,'75M'),('single2',16,651,'75M'),('unmapped',4,0,'*')])
        self.assertTrue(all(r['tags']['RG']=='validation' for r in records))
        self.assertIn(['@SQ','SN:chrTest','LN:900'],headers)
        self.assertIn(['@RG','ID:validation','SM:validation','LB:fixture','PL:ILLUMINA'],headers)
        return records

    def assert_pair(self,outputs):
        headers,records=parse_sam(outputs['sam'])
        self.assertEqual([(r['name'],r['flag'],r['position'],r['mate_position'],r['insert']) for r in records],
                         [('pair1',99,101,226,200),('pair1',147,226,101,-200),('pair2',99,401,526,200),('pair2',147,526,401,-200)])
        self.assertTrue(all(r['cigar']=='75M' and r['tags']['RG']=='validation' for r in records))
        self.assertIn(['@HD','VN:1.5','SO:unsorted','GO:query'],headers)
        self.assertTrue(outputs['pair-check'].is_file())
        return records

    def test_single_small_exact_positions_unmapped_and_tags(self):self.assert_single(self.run_workflow('single-end'))

    def test_single_large_matches_small(self):
        small=self.assert_single(self.run_workflow('single-end'))
        large=self.assert_single(self.run_workflow('single-end-large'))
        self.assertEqual(small,large)

    def test_paired_small_flags_fragment_lengths_and_mate_positions(self):self.assert_pair(self.run_workflow('paired-end'))

    def test_paired_large_matches_small(self):
        small=self.assert_pair(self.run_workflow('paired-end'))
        large=self.assert_pair(self.run_workflow('paired-end-large'))
        self.assertEqual(small,large)

    def test_gzip_read_files_and_space_paths(self):
        values={}
        for key,file in [('reads1','reads1.fastq'),('reads2','reads2.fastq')]:
            path=self.root/(key+' with spaces.fastq.gz');path.write_bytes(gzip.compress((PACK/'fixtures'/file).read_bytes()));values[key]=path
        self.assert_pair(self.run_workflow('paired-end',values))
        single=self.root/'single compressed.fastq.gz';single.write_bytes(gzip.compress((PACK/'fixtures/single.fastq').read_bytes()))
        self.assert_single(self.run_workflow('single-end',{'reads1':single}))

    def test_custom_read_group_and_library_and_platform(self):
        out=self.run_workflow('single-end',{'sample':'tumourA','read-group':'lane42','library':'library7','platform':'DNBSEQ'})
        headers,records=parse_sam(out['sam'])
        self.assertIn(['@RG','ID:lane42','SM:tumourA','LB:library7','PL:DNBSEQ'],headers)
        self.assertTrue(all(r['tags']['RG']=='lane42' for r in records))

    def test_paircheck_rejects_mismatched_names_before_indexing(self):
        path=self.root/'wrong mate.fastq';path.write_text((PACK/'fixtures/reads2.fastq').read_text().replace('@pair1/2','@different/2'))
        out=self.run_workflow('paired-end',{'reads2':path},success=False)
        self.assertFalse(out['reference'].exists())
        self.assertFalse(out['sam'].exists())

    def test_malformed_single_fastq_fails(self):
        path=self.root/'malformed.fastq';path.write_text('@bad\nACGT\n+\nIII\n')
        self.run_workflow('single-end',{'reads1':path},success=False)

    def test_seed_threads_reproducible_unique_alignments(self):
        first=self.assert_pair(self.run_workflow('paired-end',{'threads':1,'seed':11}))
        second=self.assert_pair(self.run_workflow('paired-end',{'threads':2,'seed':11}))
        self.assertEqual(first,second)

    def test_selected_sensitivity_preset(self):
        self.assert_single(self.run_workflow('single-end',{'preset':'very-sensitive'}))

    def test_all_four_shipped_native_selfcheck_expectations(self):
        checks=json.loads((PACK/'workbench-checks.json').read_text())
        self.assertEqual(len(checks['checks']),4)
        for case in checks['checks']:
            with self.subTest(case=case['id']):
                values={**case['params']}
                for members in case['inputs'].values():
                    for member in members:
                        values.update({key:str(PACK/self.pack['assets'][asset]['path']) for key,asset in member.items()})
                outputs=self.run_workflow(case['workflow'],values)
                result={'outputs':{'step-1::sam':{'files':{'sam':str(outputs['sam'])}}}}
                for expectation in case['expect']:_assert_output(expectation,result)

    def test_native_inventory_and_complete_source_hashes(self):
        allowed={'pack.ini','pack-readme.md','pack-readme.txt','readme.txt'}
        for item in list(self.pack['tools'].values())+list(self.pack['assets'].values()):
            self.assertEqual(sha(PACK/item['path']),item['sha256']);allowed.add(item['path'].lower())
        files=list(PACK.rglob('*'))
        self.assertLess(len(files),2000)
        self.assertLess(sum(p.stat().st_size for p in files if p.is_file()),256*1024*1024)
        for path in files:
            self.assertFalse(path.is_symlink())
            if path.is_file():
                relative=path.relative_to(PACK).as_posix().lower()
                self.assertTrue(relative in allowed or relative.startswith('licenses/'),relative)
        for name,_,digest in ARTIFACTS:
            if not name.endswith('.zip'):self.assertEqual(sha(PACK/'licenses'/name),digest)


def main():
    global PACK,BINARIES
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pack',type=Path,default=PACK)
    parser.add_argument('--binaries',type=Path,default=BINARIES)
    parser.add_argument('--report',type=Path)
    args=parser.parse_args();PACK=args.pack.resolve();BINARIES=args.binaries.resolve()
    result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(BowtieTests))
    binaries=[]
    for name in WINDOWS:
        path=PACK/'bin'/name
        pe=subprocess.run(['objdump','-p',str(path)],capture_output=True,text=True,check=True).stdout
        imports=re.findall(r'DLL Name:\s*(\S+)',pe)
        binaries.append(dict(name=name,sha256=sha(path),bytes=path.stat().st_size,imports=imports))
    record=dict(schema=1,tool='Bowtie 2',version='2.5.5',packVersion='0.5.3',testsRun=result.testsRun,
        failures=len(result.failures),errors=len(result.errors),success=result.wasSuccessful(),nativeWindowsExecuted=False,
        manifestSha256=sha(PACK/'pack.ini'),windowsBinaries=binaries,linuxBinaries=LINUX,commands=COMMANDS,
        checks=['All four shipped workflows execute the actual manifest argv against pinned official Linux counterparts.',
                'Mapped coordinates, CIGAR, pair flags, fragment lengths, unmapped records, sample/library/RG/PL tags, gzip input and spaces, malformed reads and mate rejection checked.',
                'Small/large index results and thread/seed reproducibility compared on exact unique-read fixtures.',
                'All four hash-pinned native self-check assertions executed against actual produced SAM.',
                'Windows PE imports and executable digests inspected; no Windows execution performed.'])
    if args.report:
        args.report.parent.mkdir(parents=True,exist_ok=True);args.report.write_text(json.dumps(record,indent=2)+'\n')
    raise SystemExit(0 if record['success'] else 1)


if __name__=='__main__':main()
