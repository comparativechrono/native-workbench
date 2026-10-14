#!/usr/bin/env python3
"""Local Kraken2 I/O adapter. All taxonomic assignments are upstream Kraken2."""
from __future__ import annotations
import argparse
import gzip
import importlib.util
import itertools
import json
import math
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile

HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('metagenomics_resources',HERE/'resources.py')
resources=importlib.util.module_from_spec(spec);spec.loader.exec_module(resources)
VERSION='2.17.2'

def inspect_database(root):
 """Check the native little-endian 64-bit database layout before native access."""
 root=Path(root)
 if (root/'opts.k2d').stat().st_size not in (56,64):raise ValueError('This pack supports 56-byte (Kraken2 2.0.8) or 64-byte Kraken2 DNA options from a 64-bit little-endian build.')
 opts=(root/'opts.k2d').read_bytes()
 k,l,seed,toggle,dna,minimum,rev,version,kind=struct.unpack('<QQQQ?7xQiii4x',opts.ljust(64,b'\0'))
 # The old 56-byte struct ended after revcom_version; bytes52-55 were ABI
 # padding, not db_version. Current upstream classification ignores those
 # reserved fields and retains its historical reverse-complement dispatch.
 if len(opts)==56:version=kind=0
 if opts[32]!=1 or not dna or not 1<=l<=31 or not l<=k<=4096 or rev!=1 or version!=0 or kind!=0:
  raise ValueError('Unsupported Kraken2 database: require DNA, current reverse-complement version, ordinary format0, k>=l and l<=31.')
 with (root/'hash.k2d').open('rb') as f:header=f.read(32)
 if len(header)!=32:raise ValueError('Truncated Kraken2 hash header.')
 capacity,used,keybits,valuebits=struct.unpack('<QQQQ',header)
 if capacity<1 or used>capacity or not 1<=valuebits<=31 or keybits<1 or keybits+valuebits not in (32,40):raise ValueError('Invalid Kraken2 hash-table header.')
 if (root/'hash.k2d').stat().st_size!=32+capacity*((keybits+valuebits)//8):raise ValueError('Kraken2 hash table length differs from its header.')
 with (root/'taxo.k2d').open('rb') as f:
  header=f.read(32)
  if len(header)!=32 or header[:8]!=b'K2TAXDAT':raise ValueError('Invalid Kraken2 taxonomy magic/header.')
  count,names,ranks=struct.unpack('<QQQ',header[8:])
  if count<2 or names<1 or ranks<1 or (root/'taxo.k2d').stat().st_size!=32+56*count+names+ranks:raise ValueError('Kraken2 taxonomy length differs from its header.')
  if count>1<<valuebits:raise ValueError('Taxonomy cannot fit the database value bits.')
  # Stream nodes; bounded memory even for complete NCBI taxonomy.
  for index in range(count):
   parent,child,nchild,name,rank,external,godparent=struct.unpack('<QQQQQQQ',f.read(56))
   if external>4294967295:raise ValueError('Kraken2 six-column reports support external taxonomy IDs only up to 4294967295; wider IDs would be truncated upstream.')
   if index and (parent>=index or child+nchild>count or (nchild and child<=index) or name>=names or rank>=ranks):raise ValueError('Invalid Kraken2 taxonomy node bounds.')
  f.seek(32+56*count+names-1)
  if f.read(1)!=b'\0':raise ValueError('Kraken2 taxonomy names are not terminated.')
  f.seek(32+56*count+names+ranks-1)
  if f.read(1)!=b'\0':raise ValueError('Kraken2 taxonomy ranks are not terminated.')
 return {'kmerLength':k,'minimizerLength':l,'alphabet':'nucleotide','optionsBytes':len(opts),'reverseComplementVersion':rev,'hashBytes':(root/'hash.k2d').stat().st_size,'taxonomyNodes':count,'cellBits':keybits+valuebits}

def fastq(path):
 path=resources.ordinary_file(path)
 with path.open('rb') as probe:compressed=probe.read(2)==b'\x1f\x8b'
 opener=gzip.open if compressed else open
 with opener(path,'rb') as stream:
  while True:
   header=stream.readline(16386)
   if not header:break
   sequence=stream.readline(10000002).rstrip(b'\r\n');plus=stream.readline(16386);quality=stream.readline(10000002).rstrip(b'\r\n')
   header=header.rstrip(b'\r\n');plus=plus.rstrip(b'\r\n')
   if not header.startswith(b'@') or not 2<=len(header)<=16384 or not plus.startswith(b'+') or not 1<=len(sequence)<=10000000 or len(sequence)!=len(quality):raise ValueError('Require complete four-line FASTQ records with matching sequence/quality lengths.')
   if any(c<32 or c>126 for c in header) or any(c not in b'ACGTNRYKMSWBDHVacgtnrykmswbdhv' for c in sequence) or any(c<33 or c>126 for c in quality):raise ValueError('FASTQ must contain IUPAC DNA and printable Phred+33 quality values.')
   identity=header[1:].split()[0]
   if plus!=b'+' and plus[1:]!=header[1:]:raise ValueError('FASTQ + identifier does not match the read header.')
   yield identity,header,sequence,quality

def mate_name(identity,mate):
 if identity.endswith((b'/1',b'/2')):
  if not identity.endswith(b'/'+str(mate).encode()):raise ValueError('Paired FASTQ mate suffix is reversed.')
  return identity[:-2]
 return identity

def stage_reads(paths,directory):
 stats=[{'records':0,'bases':0,'minLength':10000001,'maxLength':0} for _ in paths]
 outputs=[directory/('reads'+str(i+1)+'.fastq') for i in range(len(paths))]
 handles=[p.open('xb') for p in outputs]
 try:
  for records in itertools.zip_longest(*(fastq(p) for p in paths)):
   if any(r is None for r in records):raise ValueError('Paired FASTQ record counts differ.')
   if len(records)==2 and mate_name(records[0][0],1)!=mate_name(records[1][0],2):raise ValueError('Paired FASTQ identifiers or order differ.')
   if len(records)==2:
    for number,record in enumerate(records,1):
     fields=record[1][1:].split()
     if len(fields)>1 and fields[1].startswith((b'1:',b'2:')) and not fields[1].startswith(str(number).encode()+b':'):raise ValueError('Paired FASTQ CASAVA mate field is reversed.')
   for record,handle,s in zip(records,handles,stats):
    identity,header,sequence,quality=record
    handle.write(header+b'\n'+sequence+b'\n+\n'+quality+b'\n')
    s['records']+=1;s['bases']+=len(sequence);s['minLength']=min(s['minLength'],len(sequence));s['maxLength']=max(s['maxLength'],len(sequence))
 finally:
  for f in handles:f.close()
 if not stats[0]['records']:raise ValueError('FASTQ contains no reads.')
 return outputs,stats

def classify(a):
 run=Path(a.run).absolute();run.mkdir(parents=True,exist_ok=True)
 for name in ('classification-record.json','kraken.report.tsv','kraken.assignments.tsv','analysis-provenance.json','kraken.log'):
  if (run/name).exists():raise ValueError('Refusing to overwrite existing Kraken2 result '+name)
 if not 1<=a.threads<=64 or not math.isfinite(a.confidence) or not 0<=a.confidence<=1 or not 1<=a.minimum_hit_groups<=1000000 or not 0<=a.minimum_base_quality<=93:raise ValueError('Invalid classifier settings.')
 print('Verifying local Kraken2 database hashes before classification...',flush=True)
 resource=resources.validate_resource(a.database,verify_database=True)
 db=inspect_database(resource['root'])
 if any(resource['document'][key]!=db[key] for key in ('kmerLength','minimizerLength','alphabet')):raise ValueError('Descriptor k-mer/minimizer settings do not match actual opts.k2d.')
 binary=Path(a.binary).absolute() if a.binary else HERE/'bin/classify.exe'
 if os.name=='nt' and any(not str(p).isascii() for p in (HERE,run,resource['root'])):raise ValueError('Kraken2 installation, database and result paths must use ASCII characters; spaces are supported.')
 inputs=[Path(a.reads).absolute()]+([Path(a.reads2).absolute()] if a.reads2 else [])
 if len(inputs)==2 and os.path.samefile(*inputs):raise ValueError('Choose distinct mate files.')
 before=[resources.file_record(p) for p in inputs]
 temp=Path(tempfile.mkdtemp(prefix='_kraken-inputs-',dir=run))
 created_record=False;created_provenance=False
 try:
  staged,stats=stage_reads(inputs,temp)
  print('Validated '+str(stats[0]['records'])+' input fragments; running Kraken2 '+VERSION+'...',flush=True)
  for path,evidence in zip(inputs,before):resources.verify_file(path,evidence)
  args=[str(binary),'-H',str(resource['paths']['hash.k2d']),'-t',str(resource['paths']['taxo.k2d']),'-o',str(resource['paths']['opts.k2d']),'-p',str(a.threads),'-T',str(a.confidence),'-g',str(a.minimum_hit_groups),'-Q',str(a.minimum_base_quality),'-R',str(run/'kraken.report.tsv'),'-O',str(run/'kraken.assignments.tsv')]
  if a.memory=='mapped':args+=['-M']
  if len(staged)==2:args+=['-P','-c']
  args += [str(p) for p in staged]
  env=dict(os.environ)
  for name in list(env):
   if name.startswith(('KRAKEN2_','K2_','OMP_','KMP_')):env.pop(name)
  env['OMP_NUM_THREADS']=str(a.threads)
  with (run/'kraken.log').open('xb') as log:subprocess.run(args,cwd=run,env=env,stdout=log,stderr=subprocess.STDOUT,check=True)
  print('Checking database and input identity after classification...',flush=True)
  after=resources.validate_resource(a.database,verify_database=True)
  if after['sha256']!=resource['sha256']:raise ValueError('Database descriptor changed during classification.')
  for path,evidence in zip(inputs,before):resources.verify_file(path,evidence)
  classified=unclassified=0
  with (run/'kraken.assignments.tsv').open(encoding='ascii') as f:
   for line in f:
    fields=line.rstrip('\r\n').split('\t')
    if len(fields)!=5 or fields[0] not in ('C','U') or not fields[2].isdigit():raise ValueError('Unexpected Kraken2 assignment output.')
    classified+=fields[0]=='C';unclassified+=fields[0]=='U'
  fragments=stats[0]['records']
  if classified+unclassified!=fragments:raise ValueError('Kraken2 output count differs from validated input fragments.')
  reads={'paired':len(inputs)==2,'unit':'fragments' if len(inputs)==2 else 'reads','fragments':fragments,'reads':fragments*len(inputs),'bases':sum(s['bases'] for s in stats),'classifiedFragments':classified,'unclassifiedFragments':unclassified,'mate1':stats[0],'mate2':stats[1] if len(stats)==2 else None}
  record={'schema':1,'kind':resources.CLASSIFICATION_KIND,'success':True,'databaseFingerprint':resource['document']['databaseFingerprint'],'report':{'path':'kraken.report.tsv','format':'kraken2-six-column',**resources.file_record(run/'kraken.report.tsv')},'classifier':{'name':'Kraken2','version':VERSION,'confidence':a.confidence,'minimumHitGroups':a.minimum_hit_groups,'minimumBaseQuality':a.minimum_base_quality,'quick':False},'reads':reads}
  resources.write_json(run/'classification-record.json',record)
  created_record=True
  resources.validate_classification(run/'classification-record.json',resource)
  resources.write_json(run/'analysis-provenance.json',{'schema':1,'status':'completed','upstreamVersion':VERSION,'runtimeVersion':'2.17.2-workbench1','database':resource['document'],'databaseDescriptorSha256':resource['sha256'],'databaseLayout':db,'databaseHashedBeforeAndAfter':True,'inputs':[{'path':str(p),**h} for p,h in zip(inputs,before)],'inputUnchanged':True,'command':args,'threads':a.threads,'memoryMode':a.memory,'readStaging':'Validated and normalized FASTQ in owned temporary result child; removed after execution. No read filtering.','classification':record,'methods':'Kraken2 2.17.2 classified nucleotide reads against the explicitly selected local, hash-verified database. The recorded confidence, minimum hit groups and Phred+33 base-quality threshold were applied. Paired outputs count fragments jointly; this is taxonomic classification, not organism abundance estimation or clinical identification.'})
  created_provenance=True
 except BaseException:
  if created_record:(run/'classification-record.json').unlink(missing_ok=True)
  if created_provenance:(run/'analysis-provenance.json').unlink(missing_ok=True)
  raise
 finally:
  shutil.rmtree(temp)

def register(a):
 run=Path(a.run).absolute();run.mkdir(parents=True,exist_ok=True);archive=None
 resources.validate_registration_metadata(label=a.label,source_description=a.source,source_url=a.url,source_release=a.release)
 if (run/'database-resource.json').exists():raise ValueError('Refusing to overwrite an existing database descriptor.')
 if a.command=='prepare-archive':
  extracted=resources.extract_database_archive(a.archive,run,include_distributions=a.attest=='yes');anchor=extracted['anchor'];distributions=extracted['distributions'];archive=extracted['archive']
 else:anchor=Path(a.hash).absolute();distributions=a.distributions
 try:
  db=inspect_database(anchor.parent)
  resources.register_database(anchor,run/'database-resource.json',label=a.label,source_description=a.source,source_url=a.url,source_release=a.release,kmer_length=db['kmerLength'],minimizer_length=db['minimizerLength'],distributions=distributions,attest_distributions=a.attest=='yes',archive=archive)
 except BaseException:
  if a.command=='prepare-archive':shutil.rmtree(extracted['root'])
  raise

def main():
 p=argparse.ArgumentParser(description=__doc__);s=p.add_subparsers(dest='command',required=True)
 c=s.add_parser('classify');c.add_argument('--database',required=True);c.add_argument('--reads',required=True);c.add_argument('--reads2');c.add_argument('--run',required=True);c.add_argument('--threads',type=int,default=2);c.add_argument('--confidence',type=float,default=0);c.add_argument('--minimum-hit-groups',type=int,default=2);c.add_argument('--minimum-base-quality',type=int,default=0);c.add_argument('--memory',choices=('mapped','load'),default='mapped');c.add_argument('--binary')
 for command in ('register-database','prepare-archive'):
  r=s.add_parser(command);r.add_argument('--hash' if command=='register-database' else '--archive',required=True);r.add_argument('--run',required=True);r.add_argument('--label',required=True);r.add_argument('--source',required=True);r.add_argument('--url',default='');r.add_argument('--release',required=True);r.add_argument('--attest',choices=('yes','no'),default='no');r.add_argument('--distributions',nargs='*',default=[])
 a=p.parse_args()
 try:classify(a) if a.command=='classify' else register(a)
 except (ValueError,OSError,subprocess.CalledProcessError,EOFError) as e:
  print('Kraken2 could not complete: '+str(e),file=sys.stderr);return 2
 return 0
if __name__=='__main__':raise SystemExit(main())
