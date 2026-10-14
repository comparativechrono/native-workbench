#!/usr/bin/env python3
"""Validate both FreeBayes builds on the independent SNP/indel truth fixture.

Runs on Linux. Portable APE execution here is not a Windows execution test.
Compares every VCF record field; only invocation/date metadata is omitted.
"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess

ROOT=Path(__file__).resolve().parents[2]

def sha(p):
    with p.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()

def canonical(path):
    headers=[];records=[]
    for line in path.read_text().splitlines():
        if line.startswith(('##commandline=','##fileDate=','##bcftools_normCommand=')):continue
        if line.startswith('#'):headers.append(line)
        elif line:records.append(line)
    return {'headers':headers,'records':records}

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--fixture',type=Path,default=ROOT/'validation/results/tiny-final-csi-20261002')
    p.add_argument('--output',type=Path,default=ROOT/'vendor-expanded/freebayes/validation/final')
    a=p.parse_args();dest=a.output.resolve();dest.mkdir(parents=True,exist_ok=False)
    ready=a.fixture.resolve()/'tiny-truth/portable';bin=ROOT/'baselines/bin'
    inputs=['reference.fa','reference.fa.fai','alignment.marked.bam','alignment.marked.bam.csi']
    hashes={n:sha(ready/n)for n in inputs}
    for n in inputs:shutil.copyfile(ready/n,dest/n)
    commands={'linux':[str(bin/'freebayes-linux')],
              'portable':[str(bin/'ape-loader-linux'),str(bin/'freebayes-cosmo.exe')]}
    report={'scope':__doc__,'inputs':hashes,'binaries':{k:{'file':v[-1],'sha256':sha(Path(v[-1]))}for k,v in commands.items()},'runs':[],'comparisons':{}}
    def run(cmd,out,err):
        with (dest/out).open('wb') as o,(dest/err).open('wb') as e:
            result=subprocess.run(cmd,cwd=dest,stdout=o,stderr=e,timeout=120)
        report['runs'].append({'argv':cmd,'exit_code':result.returncode,'stdout':out,'stderr':err})
        if result.returncode:raise RuntimeError(f'Command failed: {cmd}: {(dest/err).read_text()}')
    base=['--fasta-reference','reference.fa','--min-mapping-quality','20','--min-base-quality','20','--strict-vcf']
    for mode,extra in [('diploid',['--ploidy','2']),('haploid',['--ploidy','1']),('gvcf',['--ploidy','2','--gvcf'])]:
        paths={}
        for target,prefix in commands.items():
            name=mode+'-'+target
            run(prefix+base+extra+['alignment.marked.bam'],name+'.vcf',name+'.stderr.txt')
            paths[target]=dest/(name+'.vcf')
            if mode!='gvcf':
                run([str(bin/'bcftools-linux'),'norm','--no-version','-f','reference.fa','-m','-any','-Ov',name+'.vcf'],name+'.norm.vcf',name+'.norm.stderr.txt')
                paths[target]=dest/(name+'.norm.vcf')
        left=canonical(paths['linux']);right=canonical(paths['portable'])
        comparison={'all_record_fields_equal':left['records']==right['records'],
                    'scientific_headers_equal':left['headers']==right['headers'],'records':len(left['records']),
                    'normalized':mode!='gvcf',
                    'canonical_record_sha256':hashlib.sha256(('\n'.join(left['records'])+'\n').encode()).hexdigest()}
        report['comparisons'][mode]=comparison
        if not comparison['all_record_fields_equal'] or not comparison['scientific_headers_equal']:
            raise RuntimeError('Native and portable outputs differ: '+mode)
        if mode=='diploid':
            query=subprocess.check_output([str(bin/'bcftools-linux'),'query','-f','%CHROM\t%POS\t%REF\t%ALT[\t%GT]\n',str(paths['portable'])],cwd=dest,text=True)
            expected=(a.fixture.resolve()/'fixture/expected-variants.tsv').read_text()
            comparison['known_truth_match']=query.strip()==expected.strip()
            comparison['known_truth_variants']=len(expected.strip().splitlines())
            if not comparison['known_truth_match']:raise RuntimeError('Known variant truth mismatch')
        print(mode,comparison,flush=True)
    report['input_integrity']=all(sha(ready/n)==h and sha(dest/n)==h for n,h in hashes.items())
    report['status']='passed' if report['input_integrity'] else 'failed'
    (dest/'validation.json').write_text(json.dumps(report,indent=2)+'\n')
    if not report['input_integrity']:raise RuntimeError('Input file changed')

if __name__=='__main__':main()
