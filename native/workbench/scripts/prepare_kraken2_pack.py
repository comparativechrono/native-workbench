#!/usr/bin/env python3
"""Prepare an independently installable local Kraken2 pack from pinned builds."""
import argparse,hashlib,importlib.util,json,shutil,sys,tarfile,zipfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'desktop'))
from prepare_modular_packs import field,number,artifact,execute,workflow
from fetch_kraken2_build_inputs import CACHE,recover,sha
VERSION='1.0.0'
def dump(p,x):p.write_text(json.dumps(x,indent=2)+'\n',encoding='utf-8',newline='\n')
def copy(src,dst):
 dst.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(src,dst)
 if sha(src)!=sha(dst):raise ValueError('Copy mismatch '+str(dst))
def definitions():
 w=[];schema={'schema':1,'category':'Metagenomics','citations':[{'text':'Wood DE, Lu J, Langmead B (2019). Improved metagenomic analysis with Kraken2. Genome Biology20:257.','url':'https://doi.org/10.1186/s13059-019-1891-0'}],'workflows':{}}
 for paired in (False,True):
  identity='classify-paired' if paired else 'classify-single';keys=['reads1','reads2'] if paired else ['reads']
  inputs=[field(k,'Read '+str(i+1)+' FASTQ' if paired else 'Reads FASTQ',filter='FASTQ|*.fastq;*.fq;*.fastq.gz;*.fq.gz|All files|*.*',help='Four-line DNA FASTQ, plain or gzip, Phred+33. Reads are validated and privately staged; plan disk for decompressed inputs.') for i,k in enumerate(keys)]
  if paired:inputs[1]['different-from']='reads1'
  inputs += [field('database','Registered Kraken2 database',filter='Database descriptor|*.json|All files|*.*',help='Select database-resource.json returned by database registration or archive preparation. The referenced local index files must remain available.'),number('threads','Classification threads',2,1,64),field('confidence','Confidence threshold','choice',default='0',choices='0:0 (upstream default)|0.05:0.05|0.1:0.1|0.2:0.2|0.5:0.5|1:1.0',help='Higher values require stronger minimizer support and can raise calls to an ancestor/unclassified. This is not a probability. Bracken models must match settings.'),number('minimum-hit-groups','Minimum hit groups',2,1,1000000),number('minimum-base-quality','Minimum Phred+33 base quality',0,0,93),field('memory','Database access','choice',default='mapped',choices='mapped:Memory mapped (local disk)|load:Load hash table into RAM',help='Mapped mode can be slower if RAM is insufficient. Load mode needs RAM for the full index. Neither reduces database size; threads are not a memory cap.')]
  outputs=[artifact('classification','Classification record for Bracken','classification-record.json'),artifact('report','Six-column Kraken2 report','kraken.report.tsv'),artifact('assignments','Per-read or per-pair assignments','kraken.assignments.tsv'),artifact('provenance','Input/database hashes and methods','analysis-provenance.json'),artifact('log','Kraken2 log','kraken.log')]
  args=['-I','-B','-X','utf8','{asset:adapter}','classify','--database','{input:database}','--reads','{input:'+keys[0]+'}','--run','{run}','--threads','{input:threads}','--confidence','{input:confidence}','--minimum-hit-groups','{input:minimum-hit-groups}','--minimum-base-quality','{input:minimum-base-quality}','--memory','{input:memory}']
  if paired:args+=['--reads2','{input:reads2}']
  w.append(workflow(identity,'Kraken2: '+('paired reads' if paired else 'single reads'),'Classify local DNA reads against an explicitly registered database. Paired reads count as fragments.',inputs,outputs,[execute('classify','Classify with upstream Kraken2','python',args,produces=[o['id'] for o in outputs])]))
  schema['workflows'][identity]={'ports':[{'id':'reads','type':'pair' if paired else 'reads','manifestInputs':keys,'min':1,'max':1},{'id':'database','type':'file','manifestInputs':['database'],'min':1,'max':1}],'outputs':[{'id':o['id'],'label':o['label'],'type':'file' if o['id']=='classification' else 'text' if o['id']=='log' else 'metrics','manifestOutputs':[o['id']]} for o in outputs],'methods':'Kraken2 2.17.2 will classify validated Phred+33 DNA FASTQ against the selected local nucleotide database, with SHA-256 identity of its minimizer index, taxonomy and options to be verified before and after execution. Confidence, minimum hit groups, base-quality threshold, threads and memory access mode will be recorded. No quick mode or read trimming will be applied. '+('Mates will be validated for identity/order/count and classified jointly; report counts describe fragments.' if paired else 'Each input read will be classified independently.')+' Ordinary six-column reports, per-fragment minimizer evidence, observed read lengths, commands and input hashes will be retained. Classification proportions include unclassified input and are not Bracken abundance estimates. Database provenance is user-supplied and does not prove suitability or clinical identification.'}
 for identity in ('register-database','prepare-archive'):
  archive=identity=='prepare-archive';anchor='archive' if archive else 'hash'
  inputs=[field(anchor,'Downloaded database tar archive' if archive else 'Existing database hash.k2d',filter='Database tar archive|*.tar;*.tar.gz;*.tgz|All files|*.*' if archive else 'Kraken2 hash table|hash.k2d|All files|*.*',help='Local downloaded archive only; no network access. Required files are safely extracted to results.' if archive else 'Select hash.k2d beside matching opts.k2d and taxo.k2d; large indexes are not copied.'),field('label','Database label','text',default='My Kraken2 database'),field('source','Database source/provider','text',default='User-supplied local database'),field('release','Database release/date','text',default='unspecified'),field('url','Source URL (provenance only)','text',default=''),field('attest','Bracken model association','choice',default='no',choices='no:No Bracken distributions selected|yes:I confirm matching database, read lengths and standard settings',help='Choose yes only when each selected distribution was built for these exact indexes and filename read length using confidence0/minimum hit groups2/base quality0. File names cannot prove this association.')]
  by_id={item['id']:item for item in inputs}
  by_id['release']['help']='Use the actual provider release or build date; unspecified remains visibly unverified.';by_id['url']['required']='false'
  if archive:by_id['attest']['choices']='no:Classification database only|yes:Include models: I confirm database, read lengths and standard settings'
  if archive:by_id['attest']['help']='Default extracts only the three classification indexes. Choose include models only after confirming the archive distributions match the exact database and stated read lengths/settings.'
  if not archive:
   f=field('distributions','Matching Bracken distribution files','files',filter='Bracken distributions|*.kmer_distrib|All files|*.*',help='Optional exact matching database<N>mers.kmer_distrib files; up to64 lengths.');f['required']='false';inputs.append(f)
  outputs=[artifact('database','Registered database resource','database-resource.json')]
  args=['-I','-B','-X','utf8','{asset:adapter}',identity,'--'+anchor,'{input:'+anchor+'}','--run','{run}','--label','{input:label}','--source','{input:source}','--release','{input:release}','--url','{input:url}','--attest','{input:attest}']
  if not archive:args+=['--distributions','{inputs:distributions}']
  w.append(workflow(identity,'Kraken2: '+('prepare downloaded database' if archive else 'register existing database'),'Create a reusable local database descriptor with exact index hashes and declared source provenance.',inputs,outputs,[execute('register','Verify and register local database','python',args,produces=['database'])]))
  ports=[{'id':anchor,'type':'file','manifestInputs':[anchor],'min':1,'max':1}]
  if not archive:ports.append({'id':'distributions','type':'file','manifestInputs':['distributions'],'min':0,'max':64})
  schema['workflows'][identity]={'ports':ports,'outputs':[{'id':'database','label':'Kraken2 database descriptor','type':'file','manifestOutputs':['database']}],'methods':'A local Kraken2 nucleotide database resource will be '+('safely extracted from a downloaded tar archive and ' if archive else '')+'registered by validating the binary index layout and hashing its exact hash.k2d,opts.k2d and taxo.k2d bytes. Source/provider/release will be explicitly recorded. Optional Bracken distributions will be hash-pinned with an explicit user attestation of database/read-length/model-settings association. No classification, download or database construction is performed.'}
 return w,schema
def checks():
 checks=[]
 for identity,paired,memory in [('single-mapped',False,'mapped'),('single-loaded',False,'load'),('paired-gzip-mapped',True,'mapped'),('paired-gzip-loaded',True,'load')]:
  checks.append({'id':identity,'workflow':'classify-paired' if paired else 'classify-single','params':{'memory':memory},'inputs':{'database':[{'database':'fixture-resource'}],'reads':[{'reads1':'fixture-reads1-gz','reads2':'fixture-reads2-gz'}] if paired else [{'reads':'fixture-reads'}]},'expect':[{'output':'classification','kind':'text','contains':['"classifiedFragments": 29','"unclassifiedFragments": 3','"fragments": 32','"reads": '+('64' if paired else '32')]},{'output':'report','kind':'text','contains':['\t12\t12\tS\t101\t','\t8\t8\tS\t102\t','\t5\t5\tS\t201\t','\t24\t4\tG\t10\t']},{'output':'provenance','kind':'text','contains':['"inputUnchanged": true','"databaseHashedBeforeAndAfter": true','"status": "completed"']}]})
 checks.append({'id':'register-existing','workflow':'register-database','params':{'label':'Synthetic check','source':'Deterministic fixture','release':'2026-10-04'},'inputs':{'hash':[{'hash':'fixture-hash'}]},'expect':[{'output':'database','kind':'text','contains':['"kmerLength": 35','"minimizerLength": 31','"alphabet": "nucleotide"']}]})
 checks.append({'id':'prepare-local-archive','workflow':'prepare-archive','params':{'label':'Synthetic archive check','source':'Deterministic fixture','release':'2026-10-04','attest':'yes'},'inputs':{'archive':[{'archive':'fixture-archive'}]},'expect':[{'output':'database','kind':'text','contains':['"kmerLength": 35','"readLength": 150','"user-attested-external"']}]})
 return {'schema':1,'checks':checks}
def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--cache',type=Path,default=CACHE);p.add_argument('--build',type=Path,default=ROOT/'build/kraken2/windows-v10');p.add_argument('--fixtures',type=Path,default=ROOT/'build/kraken2/fixture');p.add_argument('--distribution',type=Path,default=ROOT/'build/bracken-inputs/chain-model/database150mers.kmer_distrib');p.add_argument('--destination',type=Path,required=True);p.add_argument('--toolchain',type=Path,default=ROOT/'build/mosdepth-inputs/llvm/llvm-mingw-20260922-ucrt-ubuntu-22.04-x86_64');a=p.parse_args()
 lock=recover(a.cache);dest=a.destination.absolute()
 if dest.exists():raise ValueError('Use a new destination; never mutate a frozen pack.')
 (dest/'bin').mkdir(parents=True);(dest/'licenses').mkdir()
 record=json.loads((a.build/'build.json').read_text())
 if record['upstreamVersion']!='2.17.2' or record['platform']!='windows-x86_64':raise ValueError('Unexpected build provenance.')
 for name,digest in record['boundarySources'].items():
  if sha(ROOT/'tools/kraken2'/name)!=digest:raise ValueError('Native boundary source changed after build: '+name)
 for name in ('classify.exe','libomp.dll'):
  if sha(a.build/name)!=record['files'][name]['sha256']:raise ValueError('Built runtime changed '+name)
  copy(a.build/name,dest/'bin'/name)
  for dll in record['files'][name]['imports']:
   if dll.lower() not in ('libomp.dll','kernel32.dll') and not dll.lower().startswith('api-ms-win-crt-'):raise ValueError('Unbundled runtime DLL '+dll)
 with zipfile.ZipFile(a.cache/'python.zip') as z:z.extractall(dest/'bin')
 (dest/'bin/pythonw.exe').unlink();(dest/'bin/python313._pth').write_text('python313.zip\n.\n',encoding='ascii')
 for name in lock:
  if name!='python.zip':copy(a.cache/name,dest/'licenses'/name)
 for source,target in [(ROOT/'tools/kraken2/adapter.py','adapter.py'),(ROOT/'tools/metagenomics/resources.py','resources.py'),(ROOT/'docs/KRAKEN2-PACK.md','PACK-README.md'),(ROOT/'docs/METAGENOMICS-RESOURCES.md','licenses/METAGENOMICS-RESOURCES.md'),(ROOT/'LICENSE','licenses/Workbench-MIT.txt'),(a.toolchain/'LICENSE.TXT','licenses/LLVM-LICENSE.txt'),(a.build/'build.json','licenses/native-build.json'),(a.build/'windows.patch','licenses/windows.patch')]:copy(source,dest/target)
 for source in sorted((ROOT/'tools/kraken2').glob('*')):
  if source.is_file():copy(source,dest/'licenses'/source.name)
 for name in ('fetch_kraken2_build_inputs.py','prepare_kraken2_pack.py'):copy(ROOT/'scripts'/name,dest/'licenses'/name)
 copy(ROOT/'tools/metagenomics/resources.py',dest/'licenses/resources.py')
 with tarfile.open(a.cache/'kraken2-2.17.2.tar.gz') as t:(dest/'licenses/Kraken2-MIT.txt').write_bytes(t.extractfile('kraken2-2.17.2/LICENSE').read())
 with tarfile.open(a.cache/'mingw-w64-source.tar.gz') as t:
  for suffix in ('COPYING',):
   name=next(n for n in t.getnames() if n.count('/')==1 and n.endswith('/'+suffix));(dest/'licenses'/('MinGW-'+suffix+'.txt')).write_bytes(t.extractfile(name).read())
 dump(dest/'licenses/input-lock.json',{'schema':1,'inputs':lock})
 (dest/'licenses/NOTICE.txt').write_text('Kraken2 2.17.2: MIT; exact upstream source and bundled klib/HyperLogLog notices retained. Workbench adapter/OS boundaries: MIT. LLVM23.1.2 compiler-rt/libc++/libc++abi/libunwind/OpenMP: Apache2 with LLVM exceptions; complete source retained. LLVM-MinGW20260922 scripts and matching MinGW-w64 source/notices retained. CPython3.13.16: PSF and bundled component notices retained in bin/LICENSE.txt and source archive. All source inputs are SHA-pinned; native execution is a separate gate, not a build claim. No third-party biological database is bundled: installation checks use synthetic sequences only.\n',encoding='utf-8')
 shutil.copytree(a.fixtures,dest/'fixtures')
 copy(a.distribution,dest/'fixtures/database150mers.kmer_distrib')
 if (a.distribution.parent/'fixture-model-provenance.json').is_file():copy(a.distribution.parent/'fixture-model-provenance.json',dest/'licenses/fixture-bracken-provenance.json')
 spec=importlib.util.spec_from_file_location('resources',ROOT/'tools/metagenomics/resources.py');r=importlib.util.module_from_spec(spec);spec.loader.exec_module(r)
 files={n:r.file_record(dest/'fixtures'/n) for n in r.DATABASE_FILES};fingerprint=r.database_fingerprint(files);source={'description':'Synthetic independent DNA fixture, PRNG742','url':'','release':'2026-10-04'}
 resource={'schema':1,'kind':r.DATABASE_KIND,'databaseRoot':'.','label':'Synthetic installation fixture only','source':source,'files':files,'databaseFingerprint':fingerprint,'kmerLength':35,'minimizerLength':31,'alphabet':'nucleotide','brackenDistributions':[{'readLength':150,'kmerLength':35,'path':'database150mers.kmer_distrib',**r.file_record(dest/'fixtures/database150mers.kmer_distrib'),'databaseFingerprint':fingerprint,'association':'locally-built','source':source,'classifierSettings':{'confidence':0,'minimumHitGroups':2,'minimumBaseQuality':0,'quick':False}}]}
 dump(dest/'fixtures/database-resource.json',resource);r.validate_resource(dest/'fixtures/database-resource.json',verify_database=True)
 with tarfile.open(dest/'fixtures/database.tar.gz','w:gz') as t:
  for n in (*r.DATABASE_FILES,'database150mers.kmer_distrib'):t.add(dest/'fixtures'/n,arcname='synthetic/'+n)
 workflows,schema=definitions();dump(dest/'workbench-schema.json',schema);dump(dest/'workbench-checks.json',checks());sections=[]
 def section(name,values):sections.append('['+name+']\n'+'\n'.join(k+'='+str(v) for k,v in values.items() if k!='id' or name=='pack')+'\n')
 section('pack',{'format':2,'id':'kraken2','version':VERSION,'name':'Kraken2 taxonomic classification','platform':'windows-x86_64','description':'Local single/paired metagenomic classification and checked external database resources. Requires Workbench0.6.0.','color':'#397D8A'})
 for identity,name,version in [('kraken2','classify.exe','2.17.2-workbench1'),('python','python.exe','3.13.16')]:section('tool:'+identity,{'path':'bin/'+name,'version':version,'sha256':sha(dest/'bin'/name)})
 explicit={'adapter':'adapter.py','workbench-schema':'workbench-schema.json','workbench-checks':'workbench-checks.json','fixture-resource':'fixtures/database-resource.json','fixture-reads':'fixtures/reads.fastq','fixture-reads1-gz':'fixtures/reads_1.fastq.gz','fixture-reads2-gz':'fixtures/reads_2.fastq.gz','fixture-hash':'fixtures/hash.k2d','fixture-archive':'fixtures/database.tar.gz'};used={'bin/classify.exe','bin/python.exe'}
 for identity,relative in explicit.items():section('asset:'+identity,{'path':relative,'sha256':sha(dest/relative)});used.add(relative)
 for i,path in enumerate(sorted(dest.rglob('*'))):
  relative=path.relative_to(dest).as_posix()
  if path.is_file() and relative not in used and not relative.startswith('licenses/') and relative!='PACK-README.md':section('asset:runtime-'+str(i),{'path':relative,'sha256':sha(path)})
 for wf in workflows:
  section('workflow:'+wf['id'],{'name':wf['name'],'description':wf['description'],'inputs':','.join(x['id'] for x in wf['inputs']),'outputs':','.join(x['id'] for x in wf['outputs']),'steps':','.join(x['id'] for x in wf['steps'])})
  for kind in ('input','output','step'):
   for item in wf[kind+'s']:section(kind+':'+wf['id']+':'+item['id'],item)
 (dest/'pack.ini').write_text('\n'.join(sections),encoding='utf-8',newline='\n');sys.path.insert(0,str(ROOT/'workspace'));from catalog import load_pack
 loaded=load_pack(dest/'pack.ini');print(json.dumps({'pack':str(dest),'manifestSha256':sha(dest/'pack.ini'),'workflows':list(loaded['workflows']),'nativeWindowsExecuted':False},indent=2))
if __name__=='__main__':main()
