#!/usr/bin/env python3
"""Compare FreeBayes Linux/portable scientific VCF fields on one real contig."""
import hashlib,json,subprocess,shutil,argparse
from pathlib import Path
from validate import canonical
ROOT=Path(__file__).resolve().parents[2]
def sha(p):
 with p.open('rb')as f:return hashlib.file_digest(f,'sha256').hexdigest()
def main():
 p=argparse.ArgumentParser(description=__doc__)
 p.add_argument('--inputs',type=Path,default=ROOT/'validation/results/research-bcftools-20261002/yeast-lane1-bwa-quality-only/portable')
 p.add_argument('--output',type=Path,default=ROOT/'vendor-expanded/freebayes/validation/yeast-contig-I')
 p.add_argument('--region',default='I')
 a=p.parse_args();src=a.inputs.resolve();out=a.output.resolve();out.mkdir(parents=True,exist_ok=False)
 names=['reference.fa','reference.fa.fai','alignment.marked.bam','alignment.marked.bam.csi']
 hashes={n:sha(src/n)for n in names}
 for n in names:shutil.copyfile(src/n,out/n)
 bins=ROOT/'baselines/bin';cmds={'linux':[str(bins/'freebayes-linux')],'portable':[str(bins/'ape-loader-linux'),str(bins/'freebayes-cosmo.exe')]}
 report={'status':'running','scope':__doc__+' Execution on Linux x86-64 only; bounded existing dataset, not an independent variant truth test.','region':a.region,'input_directory':str(src),'inputs':hashes,'binaries':{k:{'file':v[-1],'sha256':sha(Path(v[-1]))}for k,v in cmds.items()},'runs':[]}
 def run(cmd,name):
  with (out/(name+'.stdout')).open('wb')as o,(out/(name+'.stderr')).open('wb')as e:r=subprocess.run(cmd,cwd=out,stdout=o,stderr=e,timeout=180)
  report['runs'].append({'argv':cmd,'exit_code':r.returncode,'stdout':name+'.stdout','stderr':name+'.stderr'})
  (out/'validation.json').write_text(json.dumps(report,indent=2)+'\n')
  if r.returncode:raise RuntimeError(str(cmd)+' failed; see '+str(out/(name+'.stderr')))
 for target,cmd in cmds.items():
  run(cmd+['--fasta-reference','reference.fa','--region',a.region,'--ploidy','2','--min-alternate-count','2','--min-alternate-fraction','0.2','--min-mapping-quality','20','--min-base-quality','20','--strict-vcf','alignment.marked.bam'],target)
  run([str(bins/'bcftools-linux'),'norm','--no-version','-f','reference.fa','-m','-any','-Ov',target+'.stdout'],target+'.normalized')
 left=canonical(out/'linux.normalized.stdout');right=canonical(out/'portable.normalized.stdout')
 report['comparison']={'all_record_fields_equal':left['records']==right['records'],'scientific_headers_equal':left['headers']==right['headers'],'records':len(left['records']),'canonical_record_sha256':hashlib.sha256(('\n'.join(left['records'])+'\n').encode()).hexdigest(),'omitted_metadata':['##commandline=','##fileDate=','##bcftools_normCommand=']}
 report['input_integrity']=all(sha(src/n)==h and sha(out/n)==h for n,h in hashes.items())
 report['status']='passed' if report['comparison']['all_record_fields_equal']and report['comparison']['scientific_headers_equal']and report['input_integrity']else'failed'
 (out/'validation.json').write_text(json.dumps(report,indent=2)+'\n');print(report['comparison']);print(report['status'])
 if report['status']!='passed':raise SystemExit(1)
if __name__=='__main__':main()
