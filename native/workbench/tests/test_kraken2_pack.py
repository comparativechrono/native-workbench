#!/usr/bin/env python3
"""Kraken2 native scientific, real database, resource and failure regressions."""
import argparse,configparser,hashlib,json,os,shutil,struct,subprocess,sys,tarfile,tempfile,time,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];PACK=ROOT/'build/kraken2-prepared-v2';BINARY=None;EXECUTIONS=[]
def sha(p):
 with Path(p).open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def inventory(p):return {str(f.relative_to(p)):sha(f) for f in sorted(p.rglob('*')) if f.is_file()}
def write(p,d):p.write_text(json.dumps(d,indent=2)+'\n',encoding='utf-8',newline='\n')
class Kraken2Tests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  if not PACK.is_dir() or not BINARY.is_file():raise RuntimeError('Prepare the pack and select an explicit Linux reference executable; native Windows uses the installed pack.')
  cls.before=inventory(PACK);cls.temp=tempfile.TemporaryDirectory(prefix='kraken scientific paths ');cls.root=Path(cls.temp.name);cls.counter=0;cls.python=PACK/'bin/python.exe' if os.name=='nt' else Path(sys.executable);cls.truth=json.loads((PACK/'fixtures/truth.json').read_text())
 @classmethod
 def tearDownClass(cls):
  if inventory(PACK)!=cls.before:raise AssertionError('Installed pack was changed by scientific tests')
  cls.temp.cleanup()
 def out(self):
  type(self).counter+=1;p=self.root/('run '+str(self.counter));p.mkdir();return p
 def cmd(self,args,okay=True):
  command=[str(self.python),'-I','-B','-X','utf8',str(PACK/'adapter.py'),*map(str,args)];r=subprocess.run(command,capture_output=True,text=True,encoding='utf-8',timeout=180)
  EXECUTIONS.append({'arguments':command,'exitCode':r.returncode,'stdout':r.stdout,'stderr':r.stderr})
  if okay:self.assertEqual(r.returncode,0,r.stdout+r.stderr)
  else:self.assertNotEqual(r.returncode,0,r.stdout+r.stderr)
  return r
 def classify(self,paired=False,reads=None,reads2=None,database=None,extra=(),okay=True):
  out=self.out();args=['classify','--database',database or PACK/'fixtures/database-resource.json','--reads',reads or PACK/('fixtures/reads_1.fastq.gz' if paired else 'fixtures/reads.fastq'),'--run',out,*extra]
  if paired:args+=['--reads2',reads2 or PACK/'fixtures/reads_2.fastq.gz']
  if os.name!='nt':args+=['--binary',BINARY]
  r=self.cmd(args,okay)
  if not okay:self.assertFalse((out/'classification-record.json').exists());self.assertFalse(list(out.glob('_kraken-inputs-*')))
  return out,r
 def assert_truth(self,out,paired=False,wide=False):
  rows={}
  for line in (out/'kraken.assignments.tsv').read_text().splitlines():
   c,name,tax,length,hits=line.split('\t');rows[name.removesuffix('/1')]=int(tax)
  truth=dict(self.truth['assignments'])
  if wide:truth={n:4294967497 if t==201 else t for n,t in truth.items()}
  self.assertEqual(rows,truth)
  record=json.loads((out/'classification-record.json').read_text());self.assertEqual(record['reads']['classifiedFragments'],29);self.assertEqual(record['reads']['unclassifiedFragments'],3);self.assertEqual(record['reads']['fragments'],32);self.assertEqual(record['reads']['reads'],64 if paired else 32);self.assertEqual(record['reads']['unit'],'fragments' if paired else 'reads');self.assertEqual(record['reads']['mate1']['minLength'],150)
  self.assertEqual(record['report']['sha256'],sha(out/'kraken.report.tsv'))
 def db_copy(self):
  p=self.out()
  for n in ('hash.k2d','opts.k2d','taxo.k2d'):shutil.copyfile(PACK/'fixtures'/n,p/n)
  doc=json.loads((PACK/'fixtures/database-resource.json').read_text());doc['databaseRoot']='.';doc['brackenDistributions']=[]
  return p,doc
 def descriptor(self,p,doc):
  doc['files']={n:{'bytes':(p/n).stat().st_size,'sha256':sha(p/n)} for n in ('hash.k2d','opts.k2d','taxo.k2d')};doc['databaseFingerprint']=hashlib.sha256(json.dumps(doc['files'],sort_keys=True,separators=(',',':'),ensure_ascii=True).encode()).hexdigest();write(p/'database-resource.json',doc);return p/'database-resource.json'
 def test_01_independent_truth(self):
  out,_=self.classify();self.assert_truth(out);self.assertEqual((out/'kraken.report.tsv').read_text().splitlines(),(PACK/'fixtures/expected.report.tsv').read_text().splitlines())
 def test_02_load_map_thread_agreement(self):
  for mode,threads in [('mapped',1),('mapped',4),('load',1),('load',2),('load',4)]:
   out,_=self.classify(extra=['--memory',mode,'--threads',threads]);self.assert_truth(out)
 def test_03_paired_gzip_fragment_units(self):
  for mode in ('mapped','load'):
   out,_=self.classify(paired=True,extra=['--memory',mode]);self.assert_truth(out,paired=True)
 def test_04_direct_upstream_agreement(self):
  out,_=self.classify();direct=self.out();args=[str(BINARY),'-H',str(PACK/'fixtures/hash.k2d'),'-t',str(PACK/'fixtures/taxo.k2d'),'-o',str(PACK/'fixtures/opts.k2d'),'-M','-p','2','-g','2','-R',str(direct/'report'),'-O',str(direct/'assignments'),str(PACK/'fixtures/reads.fastq')];r=subprocess.run(args,capture_output=True,text=True,timeout=120);self.assertEqual(r.returncode,0,r.stderr);self.assertEqual((out/'kraken.report.tsv').read_text(),(direct/'report').read_text());self.assertEqual((out/'kraken.assignments.tsv').read_text(),(direct/'assignments').read_text())
 def test_05_quality_masking_and_empty_classification(self):
  p=self.root/'low quality.fastq';lines=(PACK/'fixtures/reads.fastq').read_text().splitlines()
  for i in range(3,len(lines),4):lines[i]='!'*len(lines[i])
  p.write_text('\n'.join(lines)+'\n');out,_=self.classify(reads=p,extra=['--minimum-base-quality',1]);d=json.loads((out/'classification-record.json').read_text());self.assertEqual(d['reads']['classifiedFragments'],0);self.assertEqual(d['reads']['unclassifiedFragments'],32);self.assertEqual((out/'kraken.report.tsv').read_text().strip(),'100.00\t32\t32\tU\t0\tunclassified')
 def test_06_confidence_and_absent_short_reads(self):
  out,_=self.classify(extra=['--confidence',1]);self.assert_truth(out)
  p=self.root/'short.fastq';p.write_text('@short\nACGT\n+\nIIII\n@ambiguous\n'+'N'*150+'\n+\n'+'I'*150+'\n');out,_=self.classify(reads=p);d=json.loads((out/'classification-record.json').read_text());self.assertEqual(d['reads']['unclassifiedFragments'],2)
 def test_07_malformed_reads_and_compression(self):
  for name,data in [('broken.fastq',b'@x\nACGT\n+\nIII\n'),('protein.fastq',b'@x\nACGE\n+\nIIII\n'),('empty.fastq',b''),('truncated.fastq.gz',(PACK/'fixtures/reads.fastq.gz').read_bytes()[:-6])]:
   p=self.root/name;p.write_bytes(data);self.classify(reads=p,okay=False)
 def test_08_pair_guards(self):
  self.classify(paired=True,reads=PACK/'fixtures/reads_1.fastq.gz',reads2=PACK/'fixtures/reads_1.fastq.gz',okay=False)
  p=self.root/'mismatch.fastq';p.write_text((PACK/'fixtures/reads_2.fastq').read_text().replace('taxon101_0/2','different/2',1));self.classify(paired=True,reads2=p,okay=False)
  p.write_text('\n'.join((PACK/'fixtures/reads_2.fastq').read_text().splitlines()[:-4])+'\n');self.classify(paired=True,reads2=p,okay=False)
 def test_09_changed_database_rejected(self):
  p,doc=self.db_copy();descriptor=self.descriptor(p,doc);data=bytearray((p/'hash.k2d').read_bytes());data[-1]^=1;(p/'hash.k2d').write_bytes(data);out,r=self.classify(database=descriptor,okay=False);self.assertIn('checksum',r.stderr.lower())
 def test_10_incompatible_or_corrupt_database(self):
  for kind in ('protein','header','taxonomy','descriptor'):
   p,doc=self.db_copy()
   if kind=='protein':b=bytearray((p/'opts.k2d').read_bytes());b[32]=0;(p/'opts.k2d').write_bytes(b)
   elif kind=='header':(p/'opts.k2d').write_bytes(b'wrong')
   elif kind=='taxonomy':b=bytearray((p/'taxo.k2d').read_bytes());b[:8]=b'NOTTAXON';(p/'taxo.k2d').write_bytes(b)
   else:doc['kmerLength']=36
   descriptor=self.descriptor(p,doc);self.classify(database=descriptor,okay=False)
 def test_11_legacy_56_byte_options_layout(self):
  p,doc=self.db_copy();legacy=bytearray((p/'opts.k2d').read_bytes()[:56]);legacy[52:56]=b'\x81\xaa\x12\xff';(p/'opts.k2d').write_bytes(legacy);out,_=self.classify(database=self.descriptor(p,doc));self.assert_truth(out);self.assertEqual(json.loads((out/'analysis-provenance.json').read_text())['databaseLayout']['optionsBytes'],56)
 def test_12_wide_taxonomy_identifier_rejected_before_upstream_truncation(self):
  p,doc=self.db_copy();data=bytearray((p/'taxo.k2d').read_bytes());count=struct.unpack_from('<Q',data,8)[0];changes=0
  for i in range(count):
   at=32+56*i+40
   if struct.unpack_from('<Q',data,at)[0]==201:struct.pack_into('<Q',data,at,4294967497);changes+=1
  self.assertEqual(changes,1);(p/'taxo.k2d').write_bytes(data);out,r=self.classify(database=self.descriptor(p,doc),okay=False);self.assertIn('4294967295',r.stderr)
 def test_13_database_registration_and_archive(self):
  for command,selected in [('register-database',PACK/'fixtures/hash.k2d'),('prepare-archive',PACK/'fixtures/database.tar.gz')]:
   out=self.out();args=[command,'--hash' if command=='register-database' else '--archive',selected,'--run',out,'--label','Synthetic database','--source','Independent fixture','--release','2026-10-04','--attest','yes']
   if command=='register-database':args+=['--distributions',PACK/'fixtures/database150mers.kmer_distrib']
   self.cmd(args);d=json.loads((out/'database-resource.json').read_text());self.assertEqual(d['brackenDistributions'][0]['association'],'user-attested-external');classified,_=self.classify(database=out/'database-resource.json');self.assert_truth(classified)
 def test_14_archive_failure_cleanup(self):
  p,doc=self.db_copy();(p/'opts.k2d').write_bytes(b'bad');archive=p/'bad.tar.gz'
  with tarfile.open(archive,'w:gz') as t:
   for n in ('hash.k2d','opts.k2d','taxo.k2d'):t.add(p/n,arcname=n)
  out=self.out();self.cmd(['prepare-archive','--archive',archive,'--run',out,'--label','bad','--source','bad','--release','bad'],False);self.assertEqual(list(out.iterdir()),[])
 def test_15_unicode_input_and_result_policy(self):
  p=self.root/'reads é.fastq';p.write_bytes((PACK/'fixtures/reads.fastq').read_bytes());out,_=self.classify(reads=p);self.assert_truth(out)
  if os.name=='nt':
   out=self.root/'output é';out.mkdir();self.cmd(['classify','--database',PACK/'fixtures/database-resource.json','--reads',p,'--run',out],False);self.assertEqual(list(out.iterdir()),[])
 def test_16_existing_results_are_preserved(self):
  out=self.out();existing=out/'classification-record.json';existing.write_bytes(b'preserve this existing result\n');self.cmd(['classify','--database',PACK/'fixtures/database-resource.json','--reads',PACK/'fixtures/reads.fastq','--run',out],False);self.assertEqual(existing.read_bytes(),b'preserve this existing result\n')
  out=self.out();existing=out/'database-resource.json';existing.write_bytes(b'preserve this descriptor\n');self.cmd(['register-database','--hash',PACK/'fixtures/hash.k2d','--run',out,'--label','fixture','--source','fixture','--release','test'],False);self.assertEqual(existing.read_bytes(),b'preserve this descriptor\n')
if __name__=='__main__':
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--pack',type=Path,default=PACK);p.add_argument('--binary',type=Path);p.add_argument('--report',type=Path);a=p.parse_args();PACK=a.pack.resolve();BINARY=a.binary.resolve() if a.binary else PACK/'bin/classify.exe'
 if os.name=='nt' and a.binary:p.error('Native checks must use the installed executable.')
 if os.name!='nt' and not a.binary:p.error('Linux requires --binary pinned upstream executable; no substitute native claim.')
 start=time.monotonic();result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(Kraken2Tests));cfg=configparser.ConfigParser(interpolation=None);cfg.read(PACK/'pack.ini',encoding='utf-8');e={'schema':1,'packId':'kraken2','packVersion':cfg['pack']['version'],'upstreamVersion':'2.17.2','platform':sys.platform,'nativeWindowsExecuted':os.name=='nt','nativeWindowsHost':os.name=='nt','scientificExecutablesExecuted':True,'packManifestSha256':sha(PACK/'pack.ini'),'scientificBinarySha256':sha(BINARY),'installedAdapterSha256':sha(PACK/'adapter.py'),'testSourceSha256':sha(Path(__file__)),'testsRun':result.testsRun,'failures':len(result.failures),'errors':len(result.errors),'skipped':len(result.skipped),'success':result.wasSuccessful(),'seconds':round(time.monotonic()-start,3),'executions':EXECUTIONS,'scope':'Synthetic independent classification/LCA/unclassified truth; actual upstream direct equality; mapped/load and1/2/4threads; pairing/gzip/Q/confidence;64-bit taxids and56-byte layout; resource/archive/guards; immutable installed pack. Not GUI, large database benchmark or clinical validation.'}
 if a.report:a.report.parent.mkdir(parents=True,exist_ok=True);write(a.report,e)
 print(json.dumps({k:v for k,v in e.items() if k!='executions'},indent=2));sys.exit(not result.wasSuccessful())
