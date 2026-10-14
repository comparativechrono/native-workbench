#!/usr/bin/env python3
"""Build unchanged FastTree 2.2.0 and a native input/output boundary; no execution gate implied."""
import argparse, hashlib, json, os, re, shutil, subprocess, urllib.request
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
COMMIT = 'a780aa4f6a18791ea76c04afaf37aafe43e51d59'
BASE = 'https://raw.githubusercontent.com/morgannprice/fasttree/' + COMMIT + '/'
SOURCES = {'FastTree.c': (BASE+'FastTree.c', '975202a6b74c9996af871404ff043bb2152edcbda539035662514bc12d1f3431'),
           'LICENSE': (BASE+'LICENSE', '3972dc9744f6499f0f9b2dbf76696f2ae7ad8af9b23dde66d6af86c9dfb36986'),
           'FastTree': (BASE+'FastTree', '55a9d997813aae2208bd4c2081bfa690e0ecdba2d6c491805d8689415c43e38e')}
def sha(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--cache',type=Path,default=ROOT/'build/fasttree-inputs')
    p.add_argument('--build',type=Path); p.add_argument('--toolchain',type=Path)
    p.add_argument('--fetch',action='store_true'); p.add_argument('--linux',action='store_true')
    a=p.parse_args(); cache=a.cache.resolve(); cache.mkdir(parents=True,exist_ok=True)
    out=(a.build or ROOT/('build/fasttree-linux' if a.linux else 'build/fasttree-windows')).resolve(); out.mkdir(parents=True,exist_ok=True)
    for name,(url,digest) in SOURCES.items():
        f=cache/name
        if not f.exists() and a.fetch:
            with urllib.request.urlopen(url,timeout=120) as r: f.write_bytes(r.read())
        if not f.is_file() or sha(f)!=digest: raise ValueError('Missing/changed pinned upstream input: '+str(f))
    (cache/'FastTree').chmod(0o755)
    tc=a.toolchain.resolve() if a.toolchain else None
    suffix='' if a.linux else '.exe'
    if tc:
        cc=str(tc/'bin/x86_64-w64-mingw32-clang'); cxx=cc+'++'; inspect=str(tc/'bin/llvm-readobj')
        if os.name=='nt': cc+='.exe'; cxx+='.exe'; inspect+='.exe'
    else: cc=shutil.which('gcc'); cxx=shutil.which('g++'); inspect=shutil.which('objdump')
    if not cc or not cxx: raise ValueError('Install GCC/G++ or provide --toolchain with LLVM/MinGW')
    flags=['-O3','-march=x86-64','-mtune=generic','-fno-fast-math']
    link=[] if a.linux else ['-static','-Wl,--no-insert-timestamp']
    commands=[[cc,*flags,str(cache/'FastTree.c'),'-o',str(out/('fasttree'+suffix)),'-lm',*link],
              [cxx,'-O2','-std=c++17','-march=x86-64','-mtune=generic','-Wall','-Wextra','-Werror',str(ROOT/'tools/fasttree/guard.cpp'),'-o',str(out/('fasttree-guard'+suffix)),*link]]
    env=dict(os.environ)
    (out/'tmp').mkdir(exist_ok=True);env['TMPDIR']=str(out/'tmp')
    if tc:
        env['LD_LIBRARY_PATH']=str(tc/'lib');env['PATH']=str(tc/'bin')+os.pathsep+env.get('PATH','')
    for cmd in commands: subprocess.run(cmd,check=True,env=env)
    record={'schema':1,'upstreamVersion':'2.2.0','upstreamCommit':COMMIT,'platform':'linux-x86_64' if a.linux else 'windows-x86_64','serial':True,'precision':'double','cpuBaseline':'x86-64; no AVX/AVX2 required','upstreamSourceUnmodified':True,'executionTestsPerformedByBuild':False,'guardSha256':sha(ROOT/'tools/fasttree/guard.cpp'),'builderSha256':sha(Path(__file__)),'compiler':subprocess.check_output([cc,'--version'],text=True,env=env).splitlines()[0],'guardCompiler':subprocess.check_output([cxx,'--version'],text=True,env=env).splitlines()[0],'commands':commands,'sources':{k:{'url':v[0],'sha256':v[1],'role':'comparison-only Linux executable; never packaged' if k=='FastTree' else 'corresponding source/license'} for k,v in SOURCES.items()},'files':{}}
    for name in ['fasttree'+suffix,'fasttree-guard'+suffix]:
        f=out/name; info={'sha256':sha(f),'bytes':f.stat().st_size}
        if not a.linux:
            if not inspect: raise ValueError('PE dependency inspector required')
            llvm='llvm-readobj' in inspect
            data=subprocess.check_output([inspect,'--coff-imports' if llvm else '-p',str(f)],text=True,env=env)
            imports=re.findall(r'^\s*(?:Name:|DLL Name:)\s*(\S+)\s*$',data,re.M)
            if not imports: raise ValueError('Cannot determine PE imports')
            allowed={'kernel32.dll','msvcrt.dll','ucrtbase.dll','advapi32.dll','user32.dll'}
            if any(x.lower() not in allowed and not x.lower().startswith('api-ms-win-crt-') for x in imports): raise ValueError('Unexpected dynamic dependency: '+repr(imports))
            info['imports']=sorted(imports)
        record['files'][name]=info
    notices=out/'compiler-notices'; notices.mkdir(exist_ok=True)
    if tc:
        candidates=[tc/'LICENSE.TXT',*sorted((tc/'x86_64-w64-mingw32/share/mingw32').glob('COPYING*'))]
    elif not a.linux:
        # MSYS2 MINGW64 compiler package notices accompany static GCC runtimes.
        prefix=Path(cc).resolve().parent.parent
        candidates=[*sorted((prefix/'share/licenses/gcc').glob('*')),*sorted((prefix/'share/licenses/mingw-w64').glob('*'))]
        candidates=[x for x in candidates if x.is_file()]
    else: candidates=[]
    if not a.linux and not candidates: raise ValueError('Compiler/runtime licensing notices missing; use --toolchain or install MSYS2 license files')
    for f in candidates:
        if f.is_file(): shutil.copyfile(f,notices/f.name)
    record['compilerNotices']={f.name:sha(f) for f in sorted(notices.iterdir()) if f.is_file()}
    (out/'build.json').write_text(json.dumps(record,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'build':str(out),'files':record['files']},indent=2))
if __name__=='__main__': main()
