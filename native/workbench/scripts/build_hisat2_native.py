#!/usr/bin/env python3
"""Build HISAT2 v2.2.3 large-index executables for Windows or Linux.

Use the upstream source/algorithms with deterministic build identity. The Windows
build is static and does not invoke Python, a shell, WSL, or a system installation.
"""
import argparse, concurrent.futures, difflib, hashlib, json, os, re, shutil, subprocess, tarfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
CACHE=ROOT/'vendor-expanded/hisat2'
TC=ROOT.parents[1]/'toolchains/llvm-mingw-20260922-ucrt-ubuntu-22.04-x86_64'
SHA='b53107422e5b44ebea4b20b1a77bb9e240d6b92d654fcd7e6a6ab5d1aae86c45'
COMMIT='0d244324f98de541bce04d45c75e83bc3522f7f4'

def prepare(upstream=False):
    archive=CACHE/'hisat2-v2.2.3.tar.gz'
    retained=ROOT/'packs/hisat2-0.5.3/licenses'/archive.name
    if not archive.exists() and retained.is_file():
        CACHE.mkdir(parents=True,exist_ok=True)
        shutil.copy2(retained,archive)
    if hashlib.sha256(archive.read_bytes()).hexdigest()!=SHA:raise ValueError('Source SHA mismatch')
    pristine=CACHE/'source/hisat2-2.2.3'
    with tarfile.open(archive) as t:
        members=t.getmembers()
        for m in members:
            p=Path(m.name)
            if p.is_absolute() or '..' in p.parts or not p.parts or p.parts[0]!='hisat2-2.2.3' or not(m.isfile() or m.isdir() or m.issym()):raise ValueError('Unsafe source member')
        if not pristine.exists(): t.extractall(pristine.parent,members=[m for m in members if not m.issym()],filter='data')
        for m in members:
            if m.isfile() and (pristine/Path(m.name).relative_to('hisat2-2.2.3')).read_bytes()!=t.extractfile(m).read():raise ValueError('Pristine source changed')
    source=CACHE/('build-source-upstream' if upstream else 'build-source')
    for member in members:
        if member.isfile():
            relative=Path(member.name).relative_to('hisat2-2.2.3')
            destination=source/relative
            destination.parent.mkdir(parents=True,exist_ok=True)
            shutil.copy2(pristine/relative,destination)
    if not upstream:
        path=source/'hisat2.cpp'
        old=path.read_text()
        needle='else if(strandness == "RF") rna_strandness = RNA_STRANDNESS_RF;'
        if old.count(needle)!=1:raise ValueError('Unexpected upstream strandness code')
        new=old.replace(needle,needle+'\n            else if(strandness == "unstranded") rna_strandness = RNA_STRANDNESS_UNKNOWN;')
        path.write_text(new)
        (CACHE/'workbench1.patch').write_text(''.join(difflib.unified_diff(old.splitlines(True),new.splitlines(True),fromfile='a/hisat2.cpp',tofile='b/hisat2.cpp')))
    return source

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--linux',action='store_true');p.add_argument('--upstream',action='store_true');p.add_argument('--jobs',type=int,default=1);a=p.parse_args()
    source=prepare(a.upstream);target=('linux' if a.linux else 'windows')+('-upstream' if a.upstream else '');out=CACHE/('build-'+target);out.mkdir(exist_ok=True)
    env=dict(os.environ,LD_LIBRARY_PATH=str(TC/'lib'),SOURCE_DATE_EPOCH='1785525628')
    compiler='g++' if a.linux else str(TC/'bin/x86_64-w64-mingw32-clang++')
    make=(source/'Makefile').read_text().replace('\\\n',' ')
    def group(name):return re.search(r'^'+name+r'\s*=([^\n]*)',make,re.M).group(1).split()
    shared=group('SHARED_CPPS')
    commands={'hisat2-align-l':['hisat2.cpp',*shared,*group('SEARCH_CPPS'),'hisat2_main.cpp'],'hisat2-build-l':['hisat2_build.cpp',*shared,*group('BUILD_CPPS'),'hisat2_build_main.cpp']}
    flags=['-std=c++11','-O2','-DNDEBUG','-fno-strict-aliasing','-msse2','-DPOPCNT_CAPABILITY','-DBOWTIE2','-DBOWTIE_64BIT_INDEX','-D_LARGEFILE_SOURCE','-D_FILE_OFFSET_BITS=64','-D_GNU_SOURCE','-DHISAT2_VERSION="'+('2.2.3' if a.upstream else '2.2.3-workbench1')+'"','-DBUILD_HOST="NativeWorkbench"','-DBUILD_TIME="2026-07-31"','-DCOMPILER_VERSION="'+('GCC Linux reference' if a.linux else 'LLVM-MinGW 20260922')+'"','-DCOMPILER_OPTIONS="O2 SSE2 large-index'+('' if a.linux else ' static')+'"','-iquote',str(source),'-I',str(source/'third_party'),'-Wno-deprecated-declarations','-Wno-format','-Wno-unused-result']
    def compile(name):
        obj=out/(Path(name).stem+'.o')
        r=subprocess.run([compiler,*flags,'-c',str(source/name),'-o',str(obj)],env=env,capture_output=True,text=True)
        if r.returncode:raise RuntimeError(name+'\n'+r.stdout+r.stderr)
        return obj
    names=sorted(set(n for files in commands.values() for n in files))
    with concurrent.futures.ThreadPoolExecutor(max_workers=a.jobs) as pool: list(pool.map(compile,names))
    record={'patchSha256':None if a.upstream else hashlib.sha256((CACHE/'workbench1.patch').read_bytes()).hexdigest(),'sourceCommit':COMMIT,'sourceSha256':SHA,'flags':flags,'compiler':subprocess.check_output([compiler,'--version'],env=env,text=True).splitlines()[0],'files':{}}
    for name,files in commands.items():
        binary=out/(name+('' if a.linux else '.exe'))
        links=['-pthread'] if a.linux else ['-static','-Wl,--no-insert-timestamp']
        subprocess.run([compiler,*[str(out/(Path(f).stem+'.o')) for f in files],*links,'-o',str(binary)],env=env,check=True)
        item={'sha256':hashlib.sha256(binary.read_bytes()).hexdigest(),'bytes':binary.stat().st_size}
        if not a.linux:
            imports=subprocess.check_output([str(TC/'bin/llvm-readobj'),'--coff-imports',str(binary)],env=env,text=True)
            item['imports']=re.findall(r'^  Name: (.+)$',imports,re.M)
            if any(name.lower()!='kernel32.dll' and not name.lower().startswith('api-ms-win-crt-') for name in item['imports']):raise ValueError('Unexpected non-system Windows dependency')
            (out/(name+'.imports.txt')).write_text(imports)
        record['files'][binary.name]=item
    (out/'build.json').write_text(json.dumps(record,indent=2)+'\n');print(json.dumps(record['files'],indent=2))
if __name__=='__main__':main()
