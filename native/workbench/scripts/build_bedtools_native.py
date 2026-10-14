#!/usr/bin/env python3
"""Build SHA-pinned BEDTools 2.31.1 for Windows or a Linux scientific reference."""
import argparse, difflib, hashlib, json, os, re, shutil, subprocess, tarfile, urllib.request
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CACHE = ROOT.parent / 'popular-build/bedtools'
DEFAULT_TC = ROOT.parent / 'toolchains/llvm-mingw-20260922-ucrt-ubuntu-22.04-x86_64'
VERSION = '2.31.1-workbench1'
SOURCES = {
    'bedtools-2.31.1.tar.gz': ('https://codeload.github.com/arq5x/bedtools2/tar.gz/refs/tags/v2.31.1', '79a1ba318d309f4e74bfa74258b73ef578dccb1045e270998d7fe9da9f43a50e'),
    'zlib-1.3.2.tar.gz': ('https://zlib.net/zlib-1.3.2.tar.gz', 'bb329a0a2cd0274d05519d61c667c062e06990d72e125ee2dfa8de64f0119d16'),
}
def sha(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def extract(archive, destination, prefix):
    with tarfile.open(archive) as handle:
        for member in handle.getmembers():
            part = Path(member.name)
            if part.is_absolute() or '..' in part.parts or part.parts[0] != prefix or not (member.isfile() or member.isdir()):
                raise ValueError('Unsafe upstream archive member: ' + member.name)
            if member.isfile():
                path = destination / part.relative_to(prefix); path.parent.mkdir(parents=True, exist_ok=True)
                data = handle.extractfile(member).read()
                if not path.exists() or path.read_bytes() != data: path.write_bytes(data)
                path.chmod(member.mode & 0o755)
def prepare(cache, fetch, target, upstream=False):
    cache.mkdir(parents=True, exist_ok=True)
    for name, (url, checksum) in SOURCES.items():
        path = cache / name
        if not path.exists() and fetch: path.write_bytes(urllib.request.urlopen(url, timeout=120).read())
        if not path.is_file() or sha(path) != checksum: raise ValueError('Missing/changed source: ' + str(path))
    source = cache / ('source-' + target + ('-upstream' if upstream else ''))
    extract(cache/'bedtools-2.31.1.tar.gz', source, 'bedtools2-2.31.1')
    zsource = cache / 'zlib-1.3.2'; extract(cache/'zlib-1.3.2.tar.gz', zsource, 'zlib-1.3.2')
    changes = []
    def replace(name, old, new):
        path=source/name; before=path.read_text()
        if old not in before: raise ValueError('Upstream patch anchor absent: '+name+' '+old)
        after=before.replace(old,new); path.write_text(after)
        changes.append(''.join(difflib.unified_diff(before.splitlines(True),after.splitlines(True),fromfile='a/'+name,tofile='b/'+name)))
    if not upstream:
        replace('src/bedtools.cpp','int main(int argc, char *argv[])\n{','int main(int argc, char *argv[])\n{\n#ifdef _WIN32\n    _set_fmode(_O_BINARY); _setmode(_fileno(stdin),_O_BINARY); _setmode(_fileno(stdout),_O_BINARY); _setmode(_fileno(stderr),_O_BINARY);\n#endif')
        replace('src/utils/FileRecordTools/FileReaders/InputStreamMgr.cpp','new ifstream(_filename.c_str())','new ifstream(_filename.c_str(), ios::in | ios::binary)')
        replace('src/fastaFromBed/fastaFromBed.cpp','ios::out)','ios::out | ios::binary)')
        replace('src/utils/VectorOps/VectorOps.cpp','#include "VectorOps.h"','#include "VectorOps.h"\n#include <iterator>')
        replace('src/utils/Fasta/Fasta.h','#include <sys/mman.h>','#ifndef _WIN32\n#include <sys/mman.h>\n#endif')
        for name in ('src/nucBed/LargeFileSupport.h','src/utils/Fasta/LargeFileSupport.h'):
            replace(name,'__int64_t','int64_t')
        replace('src/regressTest/RegressTest.cpp','mkdir(_tmpDirname.c_str(), S_IRWXU | S_IRWXG | S_IRWXO )','\n#ifdef _WIN32\n        _mkdir(_tmpDirname.c_str())\n#else\n        mkdir(_tmpDirname.c_str(), S_IRWXU | S_IRWXG | S_IRWXO )\n#endif\n')
        replace('src/coverageFile/coverageFile.cpp','delete _floatValBuf;','delete[] _floatValBuf;')
        replace('src/utils/Contexts/ContextCoverage.cpp','  _perBase(false),','  _mean(false),\n  _perBase(false),')
        replace('src/utils/Contexts/ContextBase.cpp','  _program(UNSPECIFIED_PROGRAM),','  _runToQueryEnd(false),\n  _isCram(false),\n  _program(UNSPECIFIED_PROGRAM),')
        replace('src/utils/Contexts/ContextIntersect.cpp','ContextIntersect::ContextIntersect()\n{','ContextIntersect::ContextIntersect() : _shouldRunToDbEnd(false)\n{')
        replace('src/utils/GenomeFile/GenomeFile.cpp','GenomeFile::GenomeFile(const string &genomeFile) {','GenomeFile::GenomeFile(const string &genomeFile) : _genomeLength(0) {')
        replace('src/utils/GenomeFile/GenomeFile.cpp','long c2;', 'long long c2;')
        replace('src/utils/GenomeFile/GenomeFile.cpp','strtol(', 'strtoll(')
        replace('src/utils/GenomeFile/GenomeFile.cpp','atol(genomeFields[1].c_str())','strtoll(genomeFields[1].c_str(), NULL, 10)')
        replace('src/utils/version/version_release.txt','2.31.1',VERSION)
    # The pack exposes BED/plain FASTA only. zlib is used for internal input sniffing and faidx;
    # optional CRAM bzip2/lzma codecs are not needed or linked.
    (source/'src/utils/htslib/config.h').write_text('#define HAVE_FSEEKO 1\n' + ('#define HAVE_DRAND48 1\n' if target=='linux' else ''))
    patch=cache/('workbench1-'+target+'.patch');patch.write_text(''.join(changes))
    return source,zsource,patch

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cache',type=Path,default=DEFAULT_CACHE);parser.add_argument('--toolchain',type=Path,default=DEFAULT_TC)
    parser.add_argument('--fetch',action='store_true');parser.add_argument('--linux',action='store_true');parser.add_argument('--upstream',action='store_true')
    parser.add_argument('--jobs',type=int,default=2); args=parser.parse_args()
    if args.upstream and not args.linux:parser.error('--upstream is a Linux comparison build only')
    cache=args.cache.resolve();tc=args.toolchain.resolve();target='linux' if args.linux else 'windows'
    source,zsource,patch=prepare(cache,args.fetch,target,args.upstream)
    output=cache/('build-'+target+('-upstream' if args.upstream else '')); output.mkdir(exist_ok=True)
    temporary=output/'tmp';temporary.mkdir(exist_ok=True)
    env=dict(os.environ,LD_LIBRARY_PATH=str(tc/'lib'),SOURCE_DATE_EPOCH='1699401600',TMPDIR=str(temporary))
    cc='gcc' if args.linux else str(tc/'bin/x86_64-w64-mingw32-clang');cxx='g++' if args.linux else str(tc/'bin/x86_64-w64-mingw32-clang++');ar='ar' if args.linux else str(tc/'bin/llvm-ar')
    zfiles='adler32 compress crc32 deflate gzclose gzlib gzread gzwrite infback inffast inflate inftrees trees uncompr zutil'.split()
    objects=[]
    for name in zfiles:
        obj=output/('zlib-'+name+'.o');objects.append(str(obj))
        subprocess.run([cc,'-O2','-DZ_HAVE_UNISTD_H','-I'+str(zsource),'-c',str(zsource/(name+'.c')),'-o',str(obj)],env=env,check=True)
    subprocess.run([ar,'rcs',str(output/'libz.a'),*objects],env=env,check=True)
    flags='-O2 -Wno-deprecated-declarations -Wno-register -Wno-unused-result'
    cpp='-I'+str(zsource)
    if not args.upstream:cpp+=' -include '+str(ROOT/'tools/bedtools/windows_compat.h')
    command=['make','-j'+str(args.jobs),'bin/bedtools','CXX='+cxx,'CC='+cc,'AR='+ar,'RANLIB='+('ranlib' if args.linux else str(tc/'bin/llvm-ranlib')),'CXXFLAGS='+flags,'CFLAGS='+flags,'CPPFLAGS='+cpp,'LDFLAGS=-L'+str(output)+('' if args.linux else ' -static -Wl,--no-insert-timestamp'),'BT_LIBS=-lz -lm -lpthread'+('' if args.linux else ' -lws2_32'),'LIBS=']
    signature=hashlib.sha256((json.dumps(command)+sha(patch)+sha(ROOT/'tools/bedtools/windows_compat.h')+sha(ROOT/'tools/bedtools/bedcheck.cpp')+sha(Path(shutil.which(cxx)).resolve())).encode()).hexdigest()
    stamp=output/'build-signature.txt'
    if not stamp.exists() or stamp.read_text()!=signature:
        for obj in list((source/'obj').glob('*'))+list((source/'src/utils/htslib').glob('*.o'))+list((source/'src/utils/htslib/cram').glob('*.o')):
            if obj.is_file():obj.unlink()
        hts=source/'src/utils/htslib/libhts.a'
        if hts.exists():hts.unlink()
    log=output/'build.log'
    with log.open('w') as handle: subprocess.run(command,cwd=source,env=env,stdout=handle,stderr=subprocess.STDOUT,check=True)
    stamp.write_text(signature)
    binary=output/('bedtools' if args.linux else 'bedtools.exe');built=source/'bin/bedtools'
    if not built.exists():built=source/'bin/bedtools.exe'
    shutil.copy2(built,binary)
    helper=output/('bedcheck' if args.linux else 'bedcheck.exe')
    if not args.upstream:subprocess.run([cxx,'-O2','-std=c++17',str(ROOT/'tools/bedtools/bedcheck.cpp'),* ([] if args.linux else ['-static','-Wl,--no-insert-timestamp']),'-o',str(helper)],env=env,check=True)
    record={'schema':1,'version':'2.31.1' if args.upstream else VERSION,'platform':target+'-x86_64','sources':{name:{'url':url,'sha256':checksum} for name,(url,checksum) in SOURCES.items()},'patchSha256':sha(patch),'buildCommand':command,'compiler':subprocess.check_output([cxx,'--version'],env=env,text=True).splitlines()[0],'compilerSha256':sha(Path(shutil.which(cxx)).resolve()),'sourceDateEpoch':env['SOURCE_DATE_EPOCH'],'buildSignature':signature,'executionTestsPerformedByBuild':False,'files':{binary.name:{'sha256':sha(binary),'bytes':binary.stat().st_size}}}
    if not args.upstream:record['files'][helper.name]={'sha256':sha(helper),'bytes':helper.stat().st_size}
    if not args.linux:
        for executable in (binary,helper):
            imports=subprocess.check_output([str(tc/'bin/llvm-readobj'),'--coff-imports',str(executable)],env=env,text=True)
            record['files'][executable.name]['imports']=re.findall(r'^  Name: (.+)$',imports,re.M)
            for dep in record['files'][executable.name]['imports']:
                if dep.lower() not in ('kernel32.dll','ws2_32.dll','advapi32.dll','bcrypt.dll') and not dep.lower().startswith('api-ms-win-crt-'):raise ValueError('Unbundled DLL: '+dep)
    (output/'build.json').write_text(json.dumps(record,indent=2)+'\n');print(json.dumps(record,indent=2))
if __name__=='__main__':main()
