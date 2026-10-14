#!/usr/bin/env python3
"""Scientific and boundary regressions against installed PE or Linux build executables."""
import argparse,configparser,gzip,hashlib,json,os,platform,subprocess,sys,tempfile,time,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'tools/mosdepth'))
from fixtures import ROWS,REFS,REGIONS,bam_bytes,depths
ARGS=None

def sha(p):
 with Path(p).open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def text(p):
 with (gzip.open(p,'rt') if str(p).endswith('.gz') else Path(p).open()) as f:return f.read().replace('\r\n','\n')
def inventory(p):return {str(x.relative_to(p)):sha(x) for x in p.rglob('*') if x.is_file()}
class MosdepthScience(unittest.TestCase):
 executedscience=False
 @classmethod
 def setUpClass(cls):
  cls.pack=ARGS.pack.resolve();cls.before=inventory(cls.pack);cls.cfg=configparser.ConfigParser(interpolation=None);cls.cfg.read(cls.pack/'pack.ini');cls.temp=tempfile.TemporaryDirectory(prefix='mosdepth scientific spaces ',dir=ARGS.temp_dir);cls.root=Path(cls.temp.name);cls.count=0
  cls.native=os.name=='nt';cls.bin=cls.pack/'bin' if cls.native else ARGS.linux_build.resolve();cls.env=dict(os.environ,LD_LIBRARY_PATH=str(cls.bin));cls.guard=cls.bin/('mosdepth-guard.exe' if cls.native else 'mosdepth-guard');cls.mosdepth=cls.bin/('mosdepth.exe' if cls.native else 'mosdepth')
  for path in (cls.guard,cls.mosdepth):
   if not path.is_file():raise FileNotFoundError(str(path))
  if not cls.native:
   cls.guard.chmod(0o755);cls.mosdepth.chmod(0o755)
 @classmethod
 def tearDownClass(cls):
  after=inventory(cls.pack);cls.temp.cleanup()
  if after!=cls.before:raise AssertionError('Installed pack files changed during scientific tests')
 @classmethod
 def out(cls):cls.count+=1;p=cls.root/('run with spaces '+str(cls.count));p.mkdir();return p
 def invoke(self,args,okay=True):
  r=subprocess.run([str(x) for x in args],capture_output=True,text=True,env=self.env,timeout=120)
  if Path(args[0])==self.mosdepth and '--version' not in args:type(self).executedscience=True
  if okay:self.assertEqual(r.returncode,0,r.stdout+r.stderr)
  return r
 def run_workflow(self,op='targets',mapq=0,flags=1796,threads=2,bam=None,bed=None,thresholds=(1,2,3)):
  out=self.out();fields={'alignment':str(bam or self.pack/'fixtures/coverage.bam'),'regions':str(bed or self.pack/'fixtures/targets.bed'),'mapq':str(mapq),'exclude-flags':str(flags),'threads':str(threads),**{'threshold-'+k:str(v) for k,v in zip(['low','middle','high'],thresholds)}};wf=self.cfg['workflow:'+op];outputs={n:str(out/self.cfg['output:'+op+':'+n]['path']) for n in wf['outputs'].split(',')}
  for sid in wf['steps'].split(','):
   step=self.cfg['step:'+op+':'+sid];tool=step['tool'];args=[]
   for i in range(100):
    if 'arg.'+str(i) not in step:break
    arg=step['arg.'+str(i)]
    for k,v in fields.items():arg=arg.replace('{input:'+k+'}',v)
    for k,v in outputs.items():arg=arg.replace('{output:'+k+'}',v)
    arg=arg.replace('{run}',str(out));self.assertNotIn('{',arg);args.append(arg)
   if tool=='samtools':
    if not self.native:continue # PE/APE helper is exercised by the native installation gate.
    binary=self.pack/'bin/samtools.exe'
   else:binary=self.guard if tool=='mosdepth-guard' else self.mosdepth
   r=self.invoke([binary,*args]);
   if 'stdout' in step:Path(outputs[step['stdout']]).write_text(r.stdout)
  return out,{k:Path(v) for k,v in outputs.items()}
 def rows(self,p):return [line.split('\t') for line in text(p).splitlines()]
 def expected_perbase(self,p,expected):
  observed={n:[None]*length for n,length in REFS}
  for chrom,start,end,depth in self.rows(p):
   for pos in range(int(start),int(end)):
    self.assertIsNone(observed[chrom][pos]);observed[chrom][pos]=int(depth)
  self.assertEqual(observed['chr1'],expected);self.assertEqual(observed['chr2'],[0]*50)
 def test_01_real_upstream_version(self):self.assertIn('mosdepth 0.3.14',self.invoke([self.mosdepth,'--version']).stdout)
 def test_02_both_manifest_operations_and_declared_checks(self):
  checks=json.loads((self.pack/'workbench-checks.json').read_text())['checks'];self.assertEqual(len(checks),4)
  for check in checks:
   params=check['params'];_,out=self.run_workflow(check['workflow'],params['mapq'],int(params['exclude-flags']),params['threads'])
   for expect in check['expect']:
    for fragment in expect['contains']:self.assertIn(fragment,text(out[expect['output']]))
 def test_03_all_depth_filters_pair_overlap_and_cigar_truth(self):
  for mapq,flags in [(0,1796),(20,1796),(0,3844),(20,3844),(0,772)]:
   for threads in (1,2,4):
    with self.subTest(mapq=mapq,flags=flags,threads=threads):
     _,out=self.run_workflow(mapq=mapq,flags=flags,threads=threads);self.expected_perbase(out['perbase'],depths(mapq,flags))
 def test_04_target_breadth_uses_complete_intervals(self):
  _,out=self.run_workflow();expected=depths();rows=self.rows(out['thresholds']);self.assertEqual(rows[0][-3:],['1X','2X','3X']);self.assertEqual(len(rows),len(REGIONS)+1)
  for actual,(chrom,start,stop,name) in zip(rows[1:],REGIONS):self.assertEqual(actual,[chrom,str(start),str(stop),name,*[str(sum(d>=t for d in expected[start:stop])) for t in [1,2,3]]])
  summary={tuple(r[:2]):r[2:] for r in self.rows(out['summary'])[1:]};self.assertEqual(summary['reference-total','total'],['250','100','0.400000','90','0.360000','10','0.040000','0','0.000000'])
  self.assertEqual(summary['target','empty'][:3],['20','0','0.000000']);self.assertEqual(summary['target-total','total'][:3],['135','100','0.740741'])
  self.assertIn('total\t200\t100\t0.50\t0\t2\n',text(out['raw-summary']))
 def test_05_empty_contig_and_empty_bam_denominators(self):
  for bam in (self.pack/'fixtures/coverage.bam',self.pack/'fixtures/empty.bam'):
   _,out=self.run_workflow(bam=bam,bed=self.pack/'fixtures/empty-contig.bed');self.assertIn('target\tempty_contig\t50\t0\t0.000000\t0\t0.000000',text(out['summary']));self.assertIn('chr2\t0\t50\tempty_contig\t0\t0\t0\n',text(out['thresholds']))
   if bam.name=='empty.bam':self.assertIn('reference-total\ttotal\t250\t0\t0.000000',text(out['summary']));self.expected_perbase(out['perbase'],[0]*200)
 def guard_bad(self,bam=None,bed='none',thresholds=('1','2','3')):
  out=self.out();r=self.invoke([self.guard,bam or self.pack/'fixtures/coverage.bam',out/'stage.bam',bed,out/'targets.bed',*thresholds],False);self.assertNotEqual(r.returncode,0);self.assertIn('mosdepth input validation:',r.stderr);return r
 def test_06_bam_sort_record_bounds_format_and_truncation_guards(self):
  cases={'wrongorder':bam_bytes(list(reversed(ROWS))),'wrongsort':bam_bytes(sort='queryname'),'bounds':bam_bytes([('offend',0,195,[(10,'M')],-1,0,60,40)]),'truncated':(self.pack/'fixtures/coverage.bam').read_bytes()[:-30],'sam':b'@HD\tVN:1.6\tSO:coordinate\n@SQ\tSN:chr1\tLN:200\n','badcigar':bam_bytes([('bad',0,10,[(5,'B'),(10,'M')],-1,0,60,40)])}
  for name,data in cases.items():
   with self.subTest(name=name):p=self.root/(name+'.bam');p.write_bytes(data);self.guard_bad(bam=p)
 def test_07_bed_assembly_bounds_order_overlap_and_empty_guards(self):
  for name,data in {'contig':'wrong\t0\t5\n','bounds':'chr1\t0\t201\n','negative':'chr1\t-1\t5\n','empty':'','zero':'chr1\t5\t5\n','overlap':'chr1\t0\t10\nchr1\t5\t15\n','order':'chr2\t0\t5\nchr1\t0\t5\n','bed6':'chr1\t0\t5\tx\t0\t+\n'}.items():
   with self.subTest(name=name):p=self.root/(name+'.bed');p.write_text(data);self.guard_bad(bed=p)
 def test_08_threshold_guards_and_crlf_bed(self):
  for thresholds in [('0','2','3'),('3','2','1'),('1','1','3'),('1','2','1000001'),('1','2','3;bad')]:self.guard_bad(thresholds=thresholds)
  bed=self.root/'crlf targets.bed';bed.write_bytes((self.pack/'fixtures/targets.bed').read_bytes().replace(b'\n',b'\r\n'));_,a=self.run_workflow(bed=bed);_,b=self.run_workflow();self.assertEqual(text(a['summary']),text(b['summary']))
 def test_08b_host_environment_cannot_change_format_or_reference(self):
  original=self.env;self.env=dict(original,MOSDEPTH_PRECISION='7',REF_PATH=str(self.root/'nonexistent-reference.fa'))
  try:_,out=self.run_workflow()
  finally:self.env=original
  self.assertIn('chr1\t0\t40\tpaired\t1.25\n',text(out['regions']))
 def test_09_summary_rejects_missing_overlapping_and_wrong_contigs(self):
  run,out=self.run_workflow();original=text(out['perbase'])
  for value in [original.replace('chr1\t0\t10\t1\n',''),original.replace('chr1\t0\t10\t1\n','chr1\t0\t11\t1\n'),original.replace('chr2','wrong'),original.replace('chr2\t0\t50\t0\n','')]:
   altered=self.root/('altered-'+str(self.count)+'.bed.gz');self.count+=1
   with gzip.open(altered,'wt') as f:f.write(value)
   r=self.invoke([self.guard,'summary',run/'staged.bam',run/'targets.bed',altered,self.root/'invalid-summary.tsv','1','2','3'],False);self.assertNotEqual(r.returncode,0)
 def test_10_inputs_and_installed_pack_remain_unchanged(self):
  before=inventory(self.pack/'fixtures');self.run_workflow();self.assertEqual(before,inventory(self.pack/'fixtures'));self.assertEqual(self.before,inventory(self.pack))
 def test_11_linux_outputs_match_unmodified_official_release(self):
  binary=ARGS.upstream.resolve();self.assertEqual(sha(binary),'c5182b74a8f1b66710efa16e122cbc8a197834874b103e7c5c0bd9a6265ae7b6');binary.chmod(0o755)
  for op,mapq,flags in [('coverage',0,1796),('targets',0,1796),('targets',20,3844),('targets',0,772)]:
   run,out=self.run_workflow(op,mapq,flags);prefix=run/'official';self.invoke([binary,'--threads','2','--mapq',str(mapq),'--flag',str(flags),*(['--by',run/'targets.bed','--thresholds','1,2,3'] if op=='targets' else []),prefix,run/'staged.bam'])
   for key,path in out.items():
    if key in ('validation','summary') or key.endswith('-index'):continue
    expected=Path(str(prefix)+path.name.removeprefix('coverage'));self.assertEqual(text(path),text(expected),(op,key))
def main():
 global ARGS
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--pack',type=Path,required=True);p.add_argument('--linux-build',type=Path,default=ROOT/'build/mosdepth-linux-v2');p.add_argument('--upstream',type=Path,default=ROOT/'build/mosdepth-inputs/upstream-mosdepth');p.add_argument('--temp-dir',type=Path);p.add_argument('--report',type=Path,required=True);ARGS=p.parse_args()
 if ARGS.temp_dir:ARGS.temp_dir.mkdir(parents=True,exist_ok=True)
 names=unittest.defaultTestLoader.getTestCaseNames(MosdepthScience)
 if os.name=='nt':names.remove('test_11_linux_outputs_match_unmodified_official_release')
 suite=unittest.TestSuite(MosdepthScience(name) for name in names);start=time.time();result=unittest.TextTestRunner(verbosity=2).run(suite);report={'schema':1,'packId':'mosdepth','packVersion':MosdepthScience.cfg['pack']['version'],'upstreamVersion':'0.3.14','platform':platform.platform(),'nativeWindowsExecuted':os.name=='nt' and MosdepthScience.executedscience,'scientificExecutablesExecuted':MosdepthScience.executedscience,'officialLinuxComparisonExecuted':os.name!='nt','manifestSha256':sha(ARGS.pack/'pack.ini'),'testSourceSha256':sha(__file__),'testsRun':result.testsRun,'failures':len(result.failures),'errors':len(result.errors),'skipped':len(result.skipped),'durationSeconds':round(time.time()-start,3),'success':result.wasSuccessful(),'details':{'failures':result.failures,'errors':result.errors},'scope':'Synthetic BAM coverage, CIGAR/overlap/filter truth, empty references/targets, full-dictionary streaming aggregation, validation guards, immutable inputs and installed files; no GUI/whole-genome/clinical claim.'}
 report['details']={k:[{'test':str(t),'traceback':tb} for t,tb in v] for k,v in report['details'].items()};ARGS.report.parent.mkdir(parents=True,exist_ok=True);ARGS.report.write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report,indent=2));return 0 if result.wasSuccessful() else 1
if __name__=='__main__':raise SystemExit(main())
