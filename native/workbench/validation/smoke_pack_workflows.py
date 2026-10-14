#!/usr/bin/env python3
"""Execute generated pack commands on tiny fixtures, independently of Win32 UI.

Uses portable APE tools on Linux; bwfastq uses the corresponding Linux host.
Checks argument substitution, step outputs and format readability. This does
not execute the Windows workflow runner or establish Windows runtime support.
"""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import shutil
import subprocess

ROOT = Path(__file__).resolve().parent.parent

def digest(path):
    with path.open('rb') as f: return hashlib.file_digest(f, 'sha256').hexdigest()

def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--fixtures', type=Path, default=ROOT/'validation/rebuild-tiny',
                    help='Output root from validate_variant_pipeline.py, including fixture and tiny-truth/portable')
    ap.add_argument('--output', type=Path, default=ROOT/'validation/pack-smoke')
    local_host = ROOT/'build/bwfastq-linux'
    ap.add_argument('--bwfastq-linux', type=Path, default=local_host,
                    help='Corresponding Linux bwfastq host (build with scripts/build.py if absent)')
    args = ap.parse_args(); fixture = args.fixtures.resolve()/'fixture'; ready = args.fixtures.resolve()/'tiny-truth/portable'
    if not args.bwfastq_linux.is_file():
        ap.error('Missing local bwfastq host; run python3 scripts/build.py or set --bwfastq-linux')
    if not fixture.is_dir() or not ready.is_dir():
        ap.error('Missing prepared fixture/BAM/VCF folders; run validate_variant_pipeline.py first and pass its output root as --fixtures')
    dest = args.output.resolve(); dest.mkdir(parents=True, exist_ok=False)
    generator = ROOT/'desktop/prepare_modular_packs.py'
    spec = importlib.util.spec_from_file_location('generated_packs', generator); mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
    binaries = {t:[str(ROOT/'baselines/bin/ape-loader-linux'),str(ROOT/'baselines/bin'/f'{t}-cosmo.exe')] for t in ['seqtk','minimap2','samtools','bcftools','paircheck']}
    binaries['bwfastq'] = [str(args.bwfastq_linux.resolve())]
    report = {'scope':__doc__, 'generator_sha256':digest(generator), 'results':[], 'tools':{t:{'command':c,'sha256':digest(Path(c[-1]))} for t,c in binaries.items()}}
    source_files = list(fixture.glob('*'))+list(ready.glob('*'))
    source_hashes = {str(p):digest(p) for p in source_files if p.is_file()}
    token = re.compile(r'\{(input|output):([^}]+)\}|\{run\}')
    def expanded(s, ins, outs, run):
        return token.sub(lambda m:str(run) if m.group()=='{run}' else str((ins if m[1]=='input' else outs)[m[2]]),s)
    for pack_id,_,_,_,_,workflows in mod.all_workflows():
        for wf in workflows:
            folder = dest/(pack_id+'--'+wf['id']); folder.mkdir()
            inputs = {i['id']:i.get('default','') for i in wf['inputs']}
            generic = {'reads':fixture/'reads1.fastq','reads1':fixture/'reads1.fastq','reads2':fixture/'reads2.fastq',
                       'reference':fixture/'reference.fa','alignment':ready/'alignment.marked.bam',
                       'likelihoods':ready/'pileup.bcf','variants':ready/'variants.vcf.gz','sample':'truth'}
            for k in inputs:
                if k in generic: inputs[k] = str(generic[k])
            if pack_id=='bam':
                if wf['id'] in ['prepare','sort','name-sort']: inputs['alignment']=str(ready/'alignment.sam')
                elif wf['id']=='fixmate': inputs['alignment']=str(ready/'namesorted.bam')
                elif wf['id']=='mark-duplicates': inputs['alignment']=str(ready/'coordinates.bam')
                elif wf['id']=='merge':
                    second = folder/'second-lane-fixture.bam'; shutil.copyfile(ready/'coordinates.bam',second)
                    inputs['alignments']=[str(ready/'coordinates.bam'),str(second)]
            if pack_id=='variants' and wf['id']=='normalize': inputs['variants']=str(ready/'calls.bcf')
            outputs = {o['id']:folder/o['path'] for o in wf['outputs']}
            result = {'pack':pack_id,'workflow':wf['id'],'status':'running','steps':[],'outputs':{}}
            report['results'].append(result)
            try:
                for step in wf['steps']:
                    evidence={'step':step['id'],'kind':step['kind']}; result['steps'].append(evidence)
                    if step['kind']=='copy':
                        source=Path(expanded(step['source'],inputs,outputs,folder)); out=outputs[step['destination']]
                        if out.exists(): raise RuntimeError('Copy would overwrite output')
                        shutil.copyfile(source,out); produced=[step['destination']]
                    else:
                        argv=[]
                        for _,value in sorted(((int(k[4:]),v) for k,v in step.items() if k.startswith('arg.'))):
                            m=re.fullmatch(r'\{inputs:([^}]+)\}',value)
                            argv.extend(inputs[m[1]] if m else [expanded(value,inputs,outputs,folder)])
                        if step['tool'] in ['samtools','bcftools'] and any(x in ['-@','--threads'] for x in argv):
                            raise RuntimeError('Unsupported HTSlib threading enabled in release command')
                        cmd=binaries[step['tool']]+argv; evidence['command']=cmd
                        out=outputs[step['stdout']] if step.get('stdout') else folder/(step['id']+'.stdout.txt')
                        err=folder/(step['id']+'.stderr.txt')
                        with out.open('xb') as stdout,err.open('xb') as stderr:
                            p=subprocess.run(cmd,cwd=folder,stdout=stdout,stderr=stderr,timeout=90)
                        evidence.update(exit_code=p.returncode,stderr=str(err))
                        if p.returncode: raise RuntimeError(f'Exit {p.returncode}: {err.read_text()[-2000:]}')
                        produced=[x for x in step.get('produces','').split(',') if x]
                        if step.get('stdout'): produced.append(step['stdout'])
                    for key in produced:
                        p=outputs[key]
                        if not p.is_file(): raise RuntimeError('Missing declared step output: '+key)
                for definition in wf['outputs']:
                    p=outputs[definition['id']]
                    if not p.is_file(): raise RuntimeError('Missing workflow output: '+str(p))
                    if definition['nonempty']=='true' and not p.stat().st_size: raise RuntimeError('Empty output: '+str(p))
                    result['outputs'][definition['id']]={'path':str(p),'bytes':p.stat().st_size,'sha256':digest(p)}
                    if p.suffix=='.bam': subprocess.run(binaries['samtools']+['quickcheck',str(p)],check=True,capture_output=True)
                if pack_id=='bam' and wf['id']=='index':
                    # Explicit index path tests the standalone CSI artifact,
                    # rather than accidentally using the fixture's own index.
                    sam=outputs['alignment']; idx=outputs['index']
                    region='truth:1-6000'
                    contig=(fixture/'reference.fa').read_text().splitlines()[0][1:].split()[0];region=contig+':1-6000'
                    count=subprocess.check_output(binaries['samtools']+['view','-c',str(sam)+'##idx##'+str(idx),region],text=True).strip()
                    if int(count)<=0: raise RuntimeError('CSI region query returned no alignments')
                    result['indexed_region_count']=int(count)
                if pack_id=='variant-pipeline':
                    query=subprocess.check_output(binaries['bcftools']+['query','-f','%CHROM\t%POS\t%REF\t%ALT[\t%GT]\n',str(outputs['variants'])],text=True)
                    expected=(fixture/'expected-variants.tsv').read_text()
                    # Expected fixture TSV includes a header; compare records.
                    rows=[s for s in expected.splitlines() if s and not s.startswith('#')]
                    if rows and rows[0].lower().startswith('chrom'): rows=rows[1:]
                    if query.strip().splitlines()!=rows: raise RuntimeError('Pipeline known-truth variants mismatch')
                    result['known_truth_variants']=len(rows)
                result['status']='passed'
            except Exception as exc: result.update(status='failed',error=str(exc))
            print(pack_id,wf['id'],result['status'],flush=True)
            (dest/'smoke-results.json').write_text(json.dumps(report,indent=2)+'\n')
    report['input_integrity']=all(Path(p).is_file() and digest(Path(p))==h for p,h in source_hashes.items())
    report['passed']=sum(r['status']=='passed' for r in report['results']);report['total']=len(report['results'])
    report['status']='passed' if report['passed']==report['total'] and report['input_integrity'] else 'failed'
    (dest/'smoke-results.json').write_text(json.dumps(report,indent=2)+'\n')
    print(report['status'],report['passed'],'/',report['total'])
    return 0 if report['status']=='passed' else 1

if __name__=='__main__': raise SystemExit(main())
