#!/usr/bin/env python3
"""Build official FreeBayes1.3.10 with pinned bundled components and HTSlib1.24.

The source list follows upstream meson.build's prefer_system_deps=false build.
Compile the required translation units directly, avoiding Meson's optional
system-library detection. Source archives are SHA256 checked before extraction.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tarfile

ROOT=Path(__file__).resolve().parent.parent
VENDOR=ROOT/'vendor-expanded/freebayes'
SOURCES={
 'freebayes-1.3.10-src.tar.gz':('f828738176b38987d40cd8180d68d77af90163384f4ed9a16bb05cfa2fdb5a71','https://github.com/freebayes/freebayes/releases/download/v1.3.10/freebayes-1.3.10-src.tar.gz'),
 'tabixpp-v1.1.2.tar.gz':('c850299c3c495221818a85c9205c60185c8ed9468d5ec2ed034470bb852229dc','https://codeload.github.com/ekg/tabixpp/tar.gz/refs/tags/v1.1.2'),
 'simde-v0.8.2.tar.gz':('ed2a3268658f2f2a9b5367628a85ccd4cf9516460ed8604eed369653d49b25fb','https://codeload.github.com/simd-everywhere/simde/tar.gz/refs/tags/v0.8.2'),
 'intervaltree-aa593775.tar.gz':('9e425796787985322e1dbced4aaf12669ebe402914aac3ba1255b02a4511dc89','https://codeload.github.com/ekg/intervaltree/tar.gz/aa5937755000f1cd007402d03b6f7ce4427c5d21'),
 'musl-1.2.5.tar.gz':('a9a118bbe84d8764da0ea0d28b3ab3fae8477fc7e4085d90102b8596fc7c75e4','https://musl.libc.org/releases/musl-1.2.5.tar.gz'),
}

def sha(p):
    with p.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()

def run(cmd,cwd,log,env):
    with log.open('wb') as out:
        out.write((json.dumps(list(map(str,cmd)))+'\n').encode());out.flush()
        subprocess.run(list(map(str,cmd)),cwd=cwd,stdout=out,stderr=out,env=env,check=True)

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--target',choices=['linux','cosmo','all'],default='all')
    p.add_argument('--cosmocc-root',type=Path,default=ROOT/'variant-build/cosmocc-3.3.10')
    p.add_argument('--htslib-build-root',type=Path,default=ROOT/'variant-build')
    p.add_argument('--jobs',type=int,default=2)
    p.add_argument('--resume',action='store_true')
    a=p.parse_args();build=VENDOR/'build';build.mkdir(exist_ok=True)
    for name,(expected,_) in SOURCES.items():
        archive=VENDOR/'archives'/name
        if sha(archive)!=expected:raise RuntimeError('Source hash mismatch: '+name)
        if not a.resume:
            with tarfile.open(archive) as tf:tf.extractall(build,filter='data')
    # Supply the missing runtime function using exact upstream musl source.
    with tarfile.open(VENDOR/'archives/musl-1.2.5.tar.gz') as tf:
        rounding_source=tf.extractfile('musl-1.2.5/src/math/x86_64/llrintl.c').read()
    if (VENDOR/'compat/llrintl.c').read_bytes()!=rounding_source:
        raise RuntimeError('The runtime adapter differs from pinned upstream musl source')
    src=build/'freebayes-1.3.10';tabix=build/'tabixpp-1.1.2';simde=build/'simde-0.8.2'
    include=build/'include';(include/'intervaltree').mkdir(parents=True,exist_ok=True)
    shutil.copyfile(build/'intervaltree-aa5937755000f1cd007402d03b6f7ce4427c5d21/IntervalTree.h',include/'intervaltree/IntervalTree.h')
    # Use the public POSIX file-offset type, not glibc's private typedef.
    for rel in ['src/LargeFileSupport.h','contrib/fastahack/LargeFileSupport.h']:
        header=src/rel;text=header.read_text()
        if 'typedef __off64_t off_type;' in text:
            text=text.replace('typedef __off64_t off_type;', 'typedef off_t off_type;\nstatic_assert(sizeof(off_type) >= 8, "64-bit file offsets required");')
            header.write_text('#include <sys/types.h>\n'+text)
    # execinfo.h is a glibc extension; only omit the diagnostic backtrace.
    for rel in ['src/SegfaultHandler.h','src/SegfaultHandler.cpp']:
        header=src/rel;text=header.read_text()
        text=text.replace('#ifndef __CYGWIN__', '#if !defined(__CYGWIN__) && !defined(__COSMOPOLITAN__)')
        if rel.endswith('.cpp') and 'FreeBayes terminated after signal' not in text:
            text=text.replace('    exit(1);', '    fprintf(stderr, "FreeBayes terminated after signal %d\\n", sig);\n    exit(1);')
        if header.read_text()!=text:header.write_text(text)
    meson=(src/'meson.build').read_text()
    names=['freebayes_common_src','vcflib_src','fastahack_src','smithwaterman_src','seqlib_src']
    files=[]
    for name in names:
        matches=re.findall(r'\b'+name+r' = files\(\s*\n(.*?)\n\s*\)',meson,re.S)
        block=next((x for x in matches if "'" in x),None)
        if block is None:raise RuntimeError('Upstream source-list block not found: '+name)
        for line in block.splitlines():
            if line.lstrip().startswith('#'):continue
            files.extend(src/x for x in re.findall(r"'([^']+\.(?:c|cpp))'",line))
    files.extend([src/'src/freebayes.cpp',tabix/'tabix.cpp'])
    if len(files)!=len(set(files)):raise RuntimeError('Duplicate source in extracted upstream build list')
    for target in ['cosmo','linux'] if a.target=='all' else [a.target]:
        dst=build/target;dst.mkdir(exist_ok=True);(dst/'tmp').mkdir(exist_ok=True)
        hts=a.htslib_build_root.resolve()/target/'samtools/samtools-1.24/htslib-1.24'
        if not (hts/'libhts.a').is_file():raise RuntimeError('Build HTSlib1.24 first: '+str(hts))
        cosmo=a.cosmocc_root.resolve();cpp=str(cosmo/'bin/x86_64-unknown-cosmo-c++') if target=='cosmo' else 'g++';cc=str(cosmo/'bin/x86_64-unknown-cosmo-cc') if target=='cosmo' else 'gcc'
        inc=[include,src/'src',src/'contrib',src/'contrib/ttmath',src/'contrib/vcflib-min/include',src/'contrib/vcflib-min/include/vcflib',src/'contrib/fastahack',src/'contrib/smithwaterman',src/'contrib/SeqLib',tabix,simde,hts]
        if target=='cosmo':inc.append(cosmo/'include/third_party/zlib')
        common=['-O2','-g','-ffunction-sections','-fdata-sections']+[f'-I{x}' for x in inc]
        env={**os.environ,'TMPDIR':str(dst/'tmp')}
        target_files=files+([VENDOR/'compat/llrintl.c'] if target=='cosmo' else [])
        def compile_one(s):
            key=hashlib.sha256(str(s.relative_to(VENDOR)).encode()).hexdigest()[:10]+'-'+s.name
            obj=dst/(key+'.o');log=dst/(key+'.log')
            if a.resume and obj.is_file() and obj.stat().st_size>64 and log.exists() and obj.stat().st_mtime>=s.stat().st_mtime:return obj
            opts=['-std=c++17','-fexceptions','-fpermissive','-Wno-reorder','-Wno-sign-compare','-Wno-unused-variable','-Wno-unused-but-set-variable','-Wno-maybe-uninitialized'] if s.suffix=='.cpp' else []
            run([cpp if s.suffix=='.cpp' else cc,*common,*opts,'-c',s,'-o',obj],src,log,env)
            if not obj.is_file() or obj.stat().st_size<=64 or obj.read_bytes()[:4]!=b'\x7fELF':
                raise RuntimeError('Compiler did not produce a valid ELF object: '+str(obj))
            print(target,s.relative_to(VENDOR),flush=True)
            return obj
        # Compile the largest translation unit alone to bound build memory.
        large=src/'src/AlleleParser.cpp'
        objects=[compile_one(large)]
        with ThreadPoolExecutor(max_workers=a.jobs) as ex:
            objects.extend(ex.map(compile_one,[s for s in target_files if s!=large]))
        out=ROOT/'baselines/bin'/('freebayes-cosmo.exe' if target=='cosmo' else 'freebayes-linux')
        libs=['-lpthread','-lm']+(['-lz'] if target=='linux' else [])
        run([cpp,'-Wl,--gc-sections','-o',out,*objects,hts/'libhts.a',*libs],src,dst/'link.log',env)
        print(out,sha(out),flush=True)

if __name__=='__main__':main()
