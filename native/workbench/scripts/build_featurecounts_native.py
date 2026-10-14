#!/usr/bin/env python3
"""Verify official Subread 2.1.1 Windows featureCounts and build its input guard."""
import argparse, concurrent.futures, hashlib, json, os, re, shutil, subprocess, tarfile, urllib.request, zipfile
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
VERSION = '2.1.1'
TC_NAME = 'llvm-mingw-20260922-ucrt-ubuntu-22.04-x86_64'
SOURCES = {
    'subread-2.1.1-Windows-x86_64.zip': ('https://downloads.sourceforge.net/project/subread/subread-2.1.1/subread-2.1.1-Windows-x86_64.zip', '16f04778c1ade1bfca0c594016527a7e73eaecd1b6724f4eace00c674921ab3e'),
    'subread-2.1.1-source.tar.gz': ('https://downloads.sourceforge.net/project/subread/subread-2.1.1/subread-2.1.1-source.tar.gz', '6392d7c66831cdd767e58251892a79a51b6fab8ed0ba9671ad5e85ff1ab01eaa'),
    'zlib-1.3.2.tar.gz': ('https://zlib.net/zlib-1.3.2.tar.gz', 'bb329a0a2cd0274d05519d61c667c062e06990d72e125ee2dfa8de64f0119d16'),
}
def sha(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def extract(archive, root):
    with tarfile.open(archive) as stream:
        for member in stream.getmembers():
            rel = Path(member.name)
            if rel.is_absolute() or '..' in rel.parts or not (member.isfile() or member.isdir()): raise ValueError('Unsafe source archive entry')
            if member.isfile():
                dest = root / rel; dest.parent.mkdir(parents=True, exist_ok=True); dest.write_bytes(stream.extractfile(member).read())
def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--cache', type=Path, default=ROOT.parent/'popular-build/featurecounts'); p.add_argument('--toolchain', type=Path, default=ROOT.parent/'toolchains'/TC_NAME)
    p.add_argument('--fetch', action='store_true'); p.add_argument('--linux', action='store_true'); p.add_argument('--jobs', type=int, default=2)
    a = p.parse_args(); cache=a.cache.resolve(); tc=a.toolchain.resolve(); cache.mkdir(parents=True,exist_ok=True)
    for name, (url, digest) in SOURCES.items():
        path=cache/name
        if not path.exists() and a.fetch: path.write_bytes(urllib.request.urlopen(url,timeout=120).read())
        if not path.is_file() or sha(path)!=digest: raise ValueError('Missing/changed upstream artifact: '+str(path))
    for name in ('subread-2.1.1-source.tar.gz','zlib-1.3.2.tar.gz'): extract(cache/name,cache)
    out=cache/('build-linux' if a.linux else 'build-windows');out.mkdir(exist_ok=True)
    (out/'tmp').mkdir(exist_ok=True)
    env=dict(os.environ,LD_LIBRARY_PATH=str(tc/'lib'),TMPDIR=str(out/'tmp'))
    commands=[]
    if a.linux:
        command=['make','-f','Makefile.Linux','featureCounts','-j'+str(a.jobs)]
        subprocess.run(command,cwd=cache/'subread-2.1.1-source/src',check=True); commands.append(command)
        shutil.copy2(cache/'subread-2.1.1-source/src/featureCounts',out/'featureCounts')
    else:
        with zipfile.ZipFile(cache/'subread-2.1.1-Windows-x86_64.zip') as z:
            (out/'featureCounts.exe').write_bytes(z.read('subread-2.1.1-Windows-x86_64/bin/featureCounts.exe'))
    cc='gcc' if a.linux else str(tc/'bin/x86_64-w64-mingw32-clang')
    cxx='g++' if a.linux else str(tc/'bin/x86_64-w64-mingw32-clang++')
    zsource=cache/'zlib-1.3.2'; objects=[]
    for name in ('adler32','crc32','gzclose','gzlib','gzread','gzwrite','deflate','infback','inffast','inflate','inftrees','trees','zutil'):
        obj=out/(name+'.o');cmd=[cc,'-O2','-I'+str(zsource),'-c',str(zsource/(name+'.c')),'-o',str(obj)]
        subprocess.run(cmd,env=env,check=True);commands.append(cmd);objects.append(str(obj))
    guard=out/('featurecounts-guard' if a.linux else 'featurecounts-guard.exe')
    cmd=[cxx,'-O2','-std=c++17','-I'+str(zsource),str(ROOT/'tools/featurecounts/guard.cpp'),*objects,'-o',str(guard)]
    if not a.linux: cmd+=['-static','-Wl,--no-insert-timestamp']
    subprocess.run(cmd,env=env,check=True);commands.append(cmd)
    record={'schema':1,'version':VERSION,'upstreamBinaryUnmodified':not a.linux,'executionTestsPerformedByBuild':False,'sources':{k:{'url':v[0],'sha256':v[1]} for k,v in SOURCES.items()},'upstreamWindowsCompiler':'Not attested by the upstream binary distribution; binary retained unchanged','guardSourceSha256':sha(ROOT/'tools/featurecounts/guard.cpp'),'guardCompiler':subprocess.check_output([cxx,'--version'],env=env,text=True).splitlines()[0],'commands':commands,'files':{}}
    for name in ('featureCounts','featurecounts-guard'):
        file=out/(name+('' if a.linux else '.exe'));info={'bytes':file.stat().st_size,'sha256':sha(file)}
        if not a.linux:
            text=subprocess.check_output([str(tc/'bin/llvm-readobj'),'--coff-imports',str(file)],env=env,text=True)
            info['imports']=re.findall(r'^  Name: (.+)$',text,re.M)
            if any(d.lower()!='kernel32.dll' and not d.lower().startswith('api-ms-win-crt-') for d in info['imports']):raise ValueError('Unexpected Windows dependency')
        record['files'][file.name]=info
    (out/'build.json').write_text(json.dumps(record,indent=2)+'\n');print(json.dumps({'build':str(out),'files':record['files']},indent=2))
if __name__=='__main__': main()
