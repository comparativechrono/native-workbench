#!/usr/bin/env python3
"""Run shipped BLAST argv with independent synthetic known-answer assertions.

Default execution uses the pinned official Linux BLAST+ reference and compiled
boundary adapter. Set NW_BLAST_BIN to a native Windows build's bin directory to
exercise the identical operations on Windows. This is not a native pack-import
test; the released application import/check gate is separate.
"""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
SPEC=importlib.util.spec_from_file_location('blast_recipe',ROOT/'scripts/prepare_blast_pack.py')
RECIPE=importlib.util.module_from_spec(SPEC);SPEC.loader.exec_module(RECIPE)
BIN=Path(os.environ.get('NW_BLAST_BIN',str(ROOT.parent/'popular-build/blast/linux/bin'))).resolve()
GUARD=BIN/('blast-guard.exe' if os.name=='nt' else 'blast-guard')
SPACED_RUNS=os.name=='nt' or os.environ.get('NW_BLAST_SPACED_RUNS')=='1'
EXECUTED=[]


class BlastScientificTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not GUARD.is_file(): raise unittest.SkipTest('Build the BLAST guard and recover the pinned BLAST executable set first')
        cls.workflows={x['id']:x for x in RECIPE.definitions()[0]}
        for program in RECIPE.PROGRAMS:
            result=subprocess.run([str(GUARD),'run',program,'-version'],capture_output=True,text=True,timeout=30)
            if result.returncode or '2.17.0' not in result.stdout:raise RuntimeError('Wrong/nonrunning BLAST reference: '+program+' '+result.stderr)

    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='BLAST scientific with spaces ' if SPACED_RUNS else 'blast-scientific-')
        self.root=Path(self.temp.name)
        self.files={}
        for name,text in RECIPE.fixtures().items():
            p=self.root/('input with spaces '+name);p.write_text(text,encoding='ascii');self.files[name]=p
        self.before={p:RECIPE.sha(p) for p in self.files.values()}

    def tearDown(self):
        for p,digest in self.before.items():self.assertEqual(RECIPE.sha(p),digest,'Analysis modified input data')
        self.temp.cleanup()

    def run_workflow(self,identity,query,subjects,params=None,success=True):
        wf=self.workflows[identity];out=self.root/(identity+(' output ' if SPACED_RUNS else '-output-')+str(len(EXECUTED)));out.mkdir()
        values={x['id']:x['default'] for x in wf['inputs'] if 'default' in x}
        values.update(query=str(query),subjects=str(subjects));values.update({k:str(v) for k,v in (params or {}).items()})
        outputs={x['id']:out/x['path'] for x in wf['outputs']}
        def expand(arg):
            arg=arg.replace('{run}',str(out))
            arg=re.sub(r'\{input:([^}]+)\}',lambda m:values[m[1]],arg)
            arg=re.sub(r'\{output:([^}]+)\}',lambda m:str(outputs[m[1]]),arg)
            self.assertNotIn('{',arg);return arg
        for step in wf['steps']:
            args=[expand(step[k]) for k in sorted((k for k in step if k.startswith('arg.')),key=lambda k:int(k[4:]))]
            result=subprocess.run([str(GUARD),*args],cwd=out,capture_output=True,text=True,timeout=90)
            EXECUTED.append(dict(workflow=identity,step=step['id'],exitCode=result.returncode))
            if result.returncode:break
        if success:
            self.assertEqual(result.returncode,0,result.stderr)
            for item in wf['outputs']:
                self.assertTrue(outputs[item['id']].is_file(),item['id'])
                if item['nonempty']=='true':self.assertGreater(outputs[item['id']].stat().st_size,0,item['id'])
        else:self.assertNotEqual(result.returncode,0,'Malformed input was accepted')
        return outputs,result

    def assert_hit(self,identity,query,subject,expected,frames,qlen,slen,params=None):
        out,_=self.run_workflow(identity,self.files[query],self.files[subject],params)
        rows=[x.split('\t') for x in out['hits'].read_text().splitlines()]
        self.assertEqual(len(rows),1,rows)
        row=rows[0];self.assertEqual(len(row),16)
        self.assertEqual(row[:10],expected)
        self.assertLessEqual(float(row[10]),1e-5)
        self.assertGreater(float(row[11]),0)
        self.assertEqual(row[12:],[str(qlen),str(slen),*map(str,frames)])
        report=out['report'].read_text();self.assertIn('# 1 hits found',report);self.assertIn('# Fields:',report)
        self.assertEqual(json.loads(out['query-validation'].read_text())['records'],1)
        return row

    def test_blastn_exact_known_coordinate(self):
        self.assert_hit('blastn','nucl-query.fa','nucl-db.fa',['nq','ns','100.000','120','0','0','1','120','81','200'],[1,1],120,240)

    def test_blastp_exact_known_coordinate(self):
        self.assert_hit('blastp','protein-query.fa','protein-db.fa',['pq','ps','100.000','50','0','0','1','50','11','60'],[1,1],50,80)

    def test_blastx_translation_coordinate_units(self):
        self.assert_hit('blastx','translated-query.fa','protein-db.fa',['xq','ps','100.000','50','0','0','1','150','11','60'],[1,0],150,80)

    def test_tblastn_translation_coordinate_units(self):
        self.assert_hit('tblastn','protein-query.fa','translated-db.fa',['pq','xs','100.000','50','0','0','1','50','31','180'],[0,1],50,240)

    def test_reverse_strand_coordinates(self):
        sequence=RECIPE.fixtures()['nucl-query.fa'].splitlines()[1]
        reverse=sequence.translate(str.maketrans('ACGT','TGCA'))[::-1]
        path=self.root/'reverse.fa';path.write_text('>reverse\n'+reverse+'\n')
        out,_=self.run_workflow('blastn',path,self.files['nucl-db.fa'])
        row=out['hits'].read_text().strip().split('\t')
        self.assertEqual(row[:10],['reverse','ns','100.000','120','0','0','1','120','200','81'])
        self.assertEqual(row[-2:],['1','-1'])

    def test_no_hits_produces_empty_table_and_valid_report_archive(self):
        out,_=self.run_workflow('blastn',self.files['no-hit.fa'],self.files['nucl-db.fa'])
        self.assertEqual(out['hits'].read_bytes(),b'')
        self.assertIn('# 0 hits found',out['report'].read_text())
        self.assertIn('Blast4-archive',out['archive'].read_text())

    def test_task_and_thread_choices_keep_exact_truth(self):
        for task in ('megablast','blastn-short'):
            self.assert_hit('blastn','nucl-query.fa','nucl-db.fa',['nq','ns','100.000','120','0','0','1','120','81','200'],[1,1],120,240,{'task':task,'threads':1})

    def test_malformed_and_duplicate_fasta_rejected_before_index(self):
        for content in ('ACGT\n','>empty\n','>bad\nACGT!\n','>same\nACGT\n>same\nACGT\n','>rna\nACGU\n','>lcl|name\nACGT\n','>space\nAC GT\n'):
            with self.subTest(content=content):
                path=self.root/'bad-input.fa';path.write_text(content)
                out,result=self.run_workflow('blastn',path,self.files['nucl-db.fa'],success=False)
                self.assertIn('BLAST pack:',result.stderr)
                self.assertFalse(out['index-log'].exists())

    def test_remote_search_option_rejected(self):
        for option in ('-remote','-rid'):
            result=subprocess.run([str(GUARD),'run','blastn',option],capture_output=True,text=True)
            self.assertNotEqual(result.returncode,0);self.assertIn('Remote BLAST is not permitted',result.stderr)

    def test_patched_formatter_and_search_fail_on_missing_local_database(self):
        if os.environ.get('NW_BLAST_PATCHED')!='1':
            self.skipTest('Do not exercise missing-database retrieval with the upstream network-capable reference')
        out,_=self.run_workflow('blastn',self.files['nucl-query.fa'],self.files['nucl-db.fa'])
        folder=out['archive'].parent
        for path in folder.glob('blast-database.*'):path.rename(path.with_name('removed-'+path.name))
        for program,args in [('blast_formatter',['-archive',str(out['archive']),'-outfmt','6']),
                             ('blastn',['-query',str(self.files['nucl-query.fa']),'-db','blast-database','-outfmt','6'])]:
            result=subprocess.run([str(GUARD),'run',program,*args],cwd=folder,capture_output=True,text=True,timeout=15)
            self.assertNotEqual(result.returncode,0)
            self.assertIn('No alias or index file found',result.stderr)

    def test_guard_ignores_host_configuration_and_disables_telemetry(self):
        # Linux-only executable stub checks the process boundary, not scientific
        # behavior. Windows CI still exercises native known-answer fixtures.
        if os.name=='nt':self.skipTest('POSIX environment probe only')
        probe=self.root/'environment probe';probe.mkdir()
        import shutil
        shutil.copy2(GUARD,probe/'blast-guard')
        target=probe/'blastn'
        target.write_text('#!/bin/sh\nprintf "%s|%s|%s|%s" "$BLAST_USAGE_REPORT" "$NCBI_DONT_USE_NCBIRC" "$NCBI_DONT_USE_LOCAL_CONFIG" "$BLASTDB"\n')
        target.chmod(0o755)
        result=subprocess.run([str(probe/'blast-guard'),'run','blastn'],capture_output=True,text=True,env={**os.environ,'BLAST_USAGE_REPORT':'true'})
        self.assertEqual(result.returncode,0);self.assertEqual(result.stdout,'false|1|1|.')


if __name__=='__main__':unittest.main()
