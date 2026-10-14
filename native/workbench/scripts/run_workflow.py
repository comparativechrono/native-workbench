#!/usr/bin/env python3
"""Local, byte-preserving two-process example; no shell or network operations."""
import argparse,hashlib,json,os,pathlib,platform,signal,subprocess,sys,time
ROOT=pathlib.Path(__file__).resolve().parents[1]
def sha(path):
    h=hashlib.sha256()
    with open(path,'rb') as f:
        for block in iter(lambda:f.read(1024*1024),b''):h.update(block)
    return h.hexdigest()
def commands(backend):
    packaged=(ROOT/'bin').is_dir()
    if os.name=='nt':
        if backend=='linux':raise ValueError('Linux reference executables cannot run directly on Windows.')
        d=ROOT/'bin'/'portable' if packaged else ROOT/'baselines'/'bin'
        return [str(d/('seqtk.exe' if packaged else 'seqtk-cosmo.exe'))],[str(d/('minimap2.exe' if packaged else 'minimap2-cosmo.exe'))]
    if backend=='portable':
        d=ROOT/'bin'/'portable' if packaged else ROOT/'baselines'/'bin'
        ape=ROOT/'bin'/'linux'/'ape-loader' if packaged else ROOT/'baselines'/'bin'/'ape-loader-linux'
        return [str(ape),str(d/('seqtk.exe' if packaged else 'seqtk-cosmo.exe'))],[str(ape),str(d/('minimap2.exe' if packaged else 'minimap2-cosmo.exe'))]
    d=ROOT/'bin'/'linux' if packaged else ROOT/'baselines'/'bin'
    return [str(d/('seqtk' if packaged else 'seqtk-linux'))],[str(d/('minimap2' if packaged else 'minimap2-linux'))]
def main():
    p=argparse.ArgumentParser(description='Example: reverse-complement FASTQ reads using seqtk, then align with minimap2. This is a portability test workflow, not an analysis recommendation.')
    p.add_argument('--input',type=pathlib.Path,required=True);p.add_argument('--reference',type=pathlib.Path,required=True)
    p.add_argument('--output-dir',type=pathlib.Path,required=True);p.add_argument('--threads',type=int,default=2)
    p.add_argument('--backend',choices=['portable','linux'],default='portable');a=p.parse_args()
    if not 1<=a.threads<=64:p.error('threads must be 1..64')
    inp=a.input.resolve(strict=True);ref=a.reference.resolve(strict=True)
    if not inp.is_file() or not ref.is_file():p.error('input/reference must be regular files')
    if ref.stat().st_size==0:p.error('reference must not be empty')
    seq,align=commands(a.backend)
    # Pin and record the actual executable bytes used, as well as the published versions.
    binaries={x:sha(x) for x in set(seq+align)}
    out=a.output_dir.resolve();out.mkdir(parents=True,exist_ok=False)
    seq+=['seq','-r',str(inp)];align+=['-a','-x','sr','-t',str(a.threads),str(ref),'-']
    manifest={'format_version':1,'workflow':'reverse-complement-and-align-demo','status':'running','platform':platform.platform(),'backend':a.backend,'threads':a.threads,'argv':[seq,align],'executables_sha256':binaries,'tool_versions':{'seqtk':'1.4-r122','minimap2':'2.28-r1209'},'started_utc':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),'network_used_by_runner':False,'inputs':{'reads':{'path':str(inp),'sha256':sha(inp)},'reference':{'path':str(ref),'sha256':sha(ref)}}}
    record=out/'run.json';record.write_text(json.dumps(manifest,indent=2)+'\n')
    children=[];partial=out/'alignment.sam.partial';started=time.perf_counter();result=1
    try:
        with open(out/'seqtk.log','wb') as l1,open(out/'minimap2.log','wb') as l2,open(partial,'xb') as target:
            opts={'creationflags':subprocess.CREATE_NEW_PROCESS_GROUP} if os.name=='nt' else {'start_new_session':True}
            first=subprocess.Popen(seq,stdout=subprocess.PIPE,stderr=l1,**opts);children.append(first)
            try:second=subprocess.Popen(align,stdin=first.stdout,stdout=target,stderr=l2,**opts)
            finally:first.stdout.close()
            children.append(second)
            code2=second.wait()
            if code2 and first.poll() is None:first.terminate()
            code1=first.wait();manifest['exit_codes']=[code1,code2]
            if code1 or code2:raise RuntimeError(f'Workflow failed (seqtk={code1}, minimap2={code2}); see logs.')
            target.flush();os.fsync(target.fileno())
        # Results are published only when both stages completed successfully.
        final=out/'alignment.sam';os.rename(partial,final)
        manifest['status']='succeeded';manifest['output']={'path':final.name,'sha256':sha(final),'bytes':final.stat().st_size};result=0
    except KeyboardInterrupt:
        manifest['status']='cancelled';manifest['error']='User interrupted the workflow.';result=130
    except Exception as e:
        manifest['status']='failed';manifest['error']=str(e)
    finally:
        for child in children:
            if child.poll() is None:
                if os.name=='nt':child.terminate()
                else:os.killpg(child.pid,signal.SIGTERM)
        for child in children:
            try:child.wait(timeout=3)
            except subprocess.TimeoutExpired:
                if os.name=='nt':child.kill()
                else:os.killpg(child.pid,signal.SIGKILL)
                child.wait()
        if result and partial.exists():partial.unlink()
        manifest['elapsed_seconds']=time.perf_counter()-started
        manifest['finished_utc']=time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime())
        record.write_text(json.dumps(manifest,indent=2)+'\n')
    print(str(record));return result
if __name__=='__main__':raise SystemExit(main())
