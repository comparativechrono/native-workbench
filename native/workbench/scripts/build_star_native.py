#!/usr/bin/env python3
"""Build pinned STAR 2.7.11b with a bounded Windows OS portability patch."""
import argparse, concurrent.futures, difflib, hashlib, json, os, re, shutil, subprocess, tarfile, urllib.request
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
CACHE=ROOT.parent/'rna-build/star'
TC=ROOT.parent/'toolchains/llvm-mingw-20260922-ucrt-ubuntu-22.04-x86_64'
SOURCE_URL='https://codeload.github.com/alexdobin/STAR/tar.gz/refs/tags/2.7.11b'
SOURCE_SHA='3f65305e4112bd154c7e22b333dcdaafc681f4a895048fa30fa7ae56cac408e7'
ZLIB_URL='https://zlib.net/zlib-1.3.2.tar.gz'
ZLIB_SHA='b99a0b86c0ba9360ec7e78c4f1e43b1cbdf1e6936c8fa0f6835c0cd694a495a1'
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def source_archive(name,url,digest,fetch):
    p=CACHE/name
    if not p.exists() and fetch:p.write_bytes(urllib.request.urlopen(url,timeout=120).read())
    if not p.is_file() or sha(p)!=digest:raise ValueError('Missing/changed source '+str(p)+'; use --fetch')
    return p

def extract(archive,prefix,dest,selected=None):
    with tarfile.open(archive) as t:
        for m in t.getmembers():
            q=Path(m.name)
            if q.is_absolute() or '..' in q.parts or q.parts[0]!=prefix or not(m.isfile() or m.isdir()):raise ValueError('Unsafe archive entry')
            relative=q.relative_to(prefix)
            if selected and relative.parts and relative.parts[0] not in selected:continue
            if m.isfile():
                p=dest/relative;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(t.extractfile(m).read())

def prepare(fetch=False):
    CACHE.mkdir(parents=True,exist_ok=True)
    archive=source_archive('STAR-2.7.11b.tar.gz',SOURCE_URL,SOURCE_SHA,fetch)
    zarchive=source_archive('zlib-1.3.2.tar.gz',ZLIB_URL,ZLIB_SHA,fetch)
    pristine=CACHE/'STAR-2.7.11b';extract(archive,'STAR-2.7.11b',pristine,{'source','LICENSE','README.md'})
    zsource=CACHE/'zlib-1.3.2';extract(zarchive,'zlib-1.3.2',zsource)
    source=CACHE/'source-workbench';shutil.copytree(pristine/'source',source,dirs_exist_ok=True)
    patches=[]
    def modify(name,new):
        p=source/name;old=p.read_text();p.write_text(new)
        patches.append(''.join(difflib.unified_diff(old.splitlines(True),new.splitlines(True),fromfile='a/source/'+name,tofile='b/source/'+name)))
    p=source/'IncludeDefine.h';s=p.read_text()
    s=s.replace('#include <sys/ipc.h>\n#include <sys/shm.h>\n#include <sys/mman.h>', '#ifndef _WIN32\n#include <sys/ipc.h>\n#include <sys/shm.h>\n#include <sys/mman.h>\n#endif')
    modify('IncludeDefine.h',s)
    for name,replacement in [('SharedMemory.cpp','shared_memory_windows.cpp'),('sysRemoveDir.cpp','remove_dir_windows.cpp')]:
        old=(source/name).read_text();modify(name,'#ifdef _WIN32\n'+(ROOT/'tools/star'/replacement).read_text()+'\n#else\n'+old+'\n#endif\n')
    p=source/'streamFuns.cpp';modify(p.name,p.read_text().replace('#include <sys/statvfs.h>','#ifdef _WIN32\n#include "statvfs_windows.h"\n#else\n#include <sys/statvfs.h>\n#endif'))
    # Windows default must be binary, including libc++ file streams: no CRLF or Ctrl-Z transformations.
    p=source/'STAR.cpp';s=p.read_text();s=s.replace('int main(int argInN, char *argIn[])\n{','int main(int argInN, char *argIn[])\n{\n#ifdef _WIN32\n    _set_fmode(_O_BINARY); _setmode(_fileno(stdin),_O_BINARY); _setmode(_fileno(stdout),_O_BINARY);\n#endif')
    if '_set_fmode' not in s:raise ValueError('Changed STAR main signature')
    modify(p.name,s)
    p=source/'opal/opal.cpp';modify('opal/opal.cpp',p.read_text().replace('#include <vector>','#include <vector>\n#include <cmath>'))
    p=source/'SoloBarcode.cpp';modify(p.name,'#include <cmath>\n'+p.read_text())
    p=source/'htslib/hfile.c';s=p.read_text().replace('#include <sys/socket.h>','#ifdef _WIN32\n#include <winsock2.h>\n#include <io.h>\n#define fsync _commit\n#else\n#include <sys/socket.h>\n#endif')
    s=s.replace('return sbuf.st_blksize;','#ifdef _WIN32\n    return 65536;\n#else\n    return sbuf.st_blksize;\n#endif')
    s=s.replace('return hopen_net(fname, mode);','{ errno=ENOSYS; return NULL; }')
    modify('htslib/hfile.c',s)
    p=source/'Genome_genomeGenerate.cpp';s=p.read_text();needle='    if (pGe.gSAindexNbases > log2(nGenomeTrue)/2-1) {'
    s=s.replace(needle,'    if (pGe.gSAindexNbases == 0) {\n        pGe.gSAindexNbases = std::max(1, std::min(14, int(log2(nGenomeTrue)/2-1)));\n        P.inOut->logMain << "Workbench automatic genomeSAindexNbases = " << pGe.gSAindexNbases << "\\n";\n    }\n'+needle)
    modify(p.name,s)
    p=source/'htslib/sam.c';s=p.read_text()
    # STAR calls only BAM header/record/auxiliary primitives, not the SAM/CRAM parser or indexer.
    s=s[:s.index('static hts_idx_t *bam_index(')]+s[s.index('void bam_aux_append('):s.index('int sam_open_mode(')]
    s=s.replace('#include "cram/cram.h"','')
    s=s.replace('KHASH_DECLARE(s2i, kh_cstr_t, int64_t)','KHASH_MAP_INIT_STR(s2i, int64_t)\nint hts_verbose = 3;')
    modify('htslib/sam.c',s)
    p=source/'Parameters.cpp';s=p.read_text()
    s=s.replace('if ( inOut->logMain.good() ) {','if ( inOut->logMain.is_open() && inOut->logMain.good() ) {')
    modify(p.name,s)
    # libc++ ignores basic_stringbuf::pubsetbuf. Use explicit external-buffer
    # streams on both platforms, retaining STAR's chunking and mapping code.
    p=source/'ReadAlignChunk.h';s=p.read_text().replace('#include "IncludeDefine.h"','#include "IncludeDefine.h"\n#include "WorkbenchBufferStream.h"')
    s=s.replace('istringstream** readInStream;', 'WorkbenchInputStream** readInStream;').replace('ostringstream*  chunkOutBAMstream;', 'WorkbenchOutputStream* chunkOutBAMstream;')
    modify(p.name,s)
    p=source/'ReadAlignChunk.cpp';s=p.read_text().replace('new istringstream* [P.readNends]', 'new WorkbenchInputStream* [P.readNends]')
    s=s.replace('readInStream[ii] = new istringstream;\n       readInStream[ii]->rdbuf()->pubsetbuf(chunkIn[ii],P.chunkInSizeBytesArray);', 'readInStream[ii] = new WorkbenchInputStream(chunkIn[ii], P.chunkInSizeBytesArray);')
    s=s.replace('chunkOutBAMstream=new ostringstream;\n        chunkOutBAMstream->rdbuf()->pubsetbuf(chunkOutBAM,P.chunkOutBAMsizeBytes);', 'chunkOutBAMstream=new WorkbenchOutputStream(chunkOutBAM, P.chunkOutBAMsizeBytes);')
    if 'pubsetbuf' in s:raise ValueError('Unexpected STAR chunk stream setup')
    modify(p.name,s)
    p=source/'ReadAlignChunk_processChunks.cpp';s=p.read_text()
    s=s.replace("            for (uint imate=0; imate<P.readNends; imate++) \n                chunkIn[imate][chunkInSizeBytesTotal[imate]]='\\n';//extra empty line at the end of the chunks", "            for (uint imate=0; imate<P.readNends; imate++) {\n                chunkIn[imate][chunkInSizeBytesTotal[imate]]='\\n';//extra empty line at the end of the chunks\n                readInStream[imate]->inputSize(chunkInSizeBytesTotal[imate] + 1);\n            }")
    if 'inputSize(chunkInSizeBytesTotal' not in s:raise ValueError('Unexpected STAR chunk boundary')
    modify(p.name,s)
    p=source/'ReadAlignChunk_mapChunk.cpp';s=p.read_text().replace('if ( chunkOutBAMtotal > P.chunkOutBAMsizeBytes )', 'if ( !RA->outSAMstream->good() || chunkOutBAMtotal > P.chunkOutBAMsizeBytes )')
    modify(p.name,s)
    p=source/'GTF.cpp';s=p.read_text()
    s=s.replace('continue; //do not process exons/transcripts on missing chromosomes','exitWithError("FATAL GTF INPUT: annotation chromosome is absent from the selected genome: " + chr1 + "\\n", std::cerr, P.inOut->logMain, EXIT_CODE_INPUT_FILES, P);')
    s=s.replace('uint64 ex1,ex2;','uint64 ex1=0,ex2=0;')
    s=s.replace('if ( ex2 > genome.chrLength[genome.chrNameIndex[chr1]] ) {','if ( !oneLineStream || ex1 < 1 || ex1 > ex2 || ex2 > genome.chrLength[genome.chrNameIndex[chr1]] || (str1 != \'+\' && str1 != \'-\') ) {')
    s=s.replace('            \tcontinue;','                exitWithError("FATAL GTF INPUT: malformed or out-of-range exon coordinates/strand in selected annotation\\n" + oneLine + "\\n", std::cerr, P.inOut->logMain, EXIT_CODE_INPUT_FILES, P);')
    s=s.replace('            if (exAttr[0]=="") {','            if (exAttr[0]=="" || exAttr[1]=="") {\n                exitWithError("FATAL GTF INPUT: every exon needs gene_id and transcript_id attributes\\n" + oneLine + "\\n", std::cerr, P.inOut->logMain, EXIT_CODE_INPUT_FILES, P);\n            };\n            if (exAttr[0]=="") {')
    modify(p.name,s)
    for name in ('windows_compat.h','statvfs_windows.h','WorkbenchBufferStream.h'):shutil.copy2(ROOT/'tools/star'/name,source/name)
    p=source/'VERSION';modify('VERSION',p.read_text().replace('2.7.11b','2.7.11b-workbench1'))
    data=(source/'parametersDefault').read_bytes()
    (source/'parametersDefault.xxd').write_text('unsigned char parametersDefault[] = {'+','.join(str(x) for x in data)+'};\nunsigned int parametersDefault_len = '+str(len(data))+';\n')
    modify('htslib/config.h','#define BGZF_CACHE\n#define BGZF_MT\n')
    (CACHE/'workbench1.patch').write_text(''.join(patches))
    return source,zsource

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--fetch',action='store_true');p.add_argument('--linux',action='store_true');p.add_argument('--upstream',action='store_true',help='Extract the official pinned Linux static binary for scientific comparison (requires --linux)');p.add_argument('--jobs',type=int,default=2);a=p.parse_args()
    source,zsource=prepare(a.fetch)
    if a.upstream:
        if not a.linux:raise ValueError('--upstream is a Linux reference only, never a Windows build')
        out=CACHE/'reference-upstream';out.mkdir(exist_ok=True);binary=out/'STAR'
        with tarfile.open(CACHE/'STAR-2.7.11b.tar.gz') as t:binary.write_bytes(t.extractfile('STAR-2.7.11b/bin/Linux_x86_64_static/STAR').read())
        binary.chmod(0o755)
        if sha(binary)!='36e94b899a56b0ea5de5d65e722f55bc552b6713bd2d1e83a5c2abbd06c9881a':raise ValueError('Unexpected upstream reference binary hash')
        print(json.dumps({'officialLinuxReference':str(binary),'sha256':sha(binary)}));return
    target=('linux' if a.linux else 'windows')+('-upstream' if a.upstream else '')
    out=CACHE/('build-'+target);out.mkdir(exist_ok=True)
    env=dict(os.environ,LD_LIBRARY_PATH=str(TC/'lib'),SOURCE_DATE_EPOCH='1706274000')
    cxx='g++' if a.linux else str(TC/'bin/x86_64-w64-mingw32-clang++')
    cc='gcc' if a.linux else str(TC/'bin/x86_64-w64-mingw32-clang')
    common=['-O2','-DNDEBUG','-D_FILE_OFFSET_BITS=64','-ffunction-sections','-fdata-sections','-I'+str(source),'-I'+str(zsource),'-I'+str(source/'htslib'),'-Wno-unused-result','-Wno-deprecated-declarations','-Wno-format','-Wno-register','-DSAMTOOLS=1','-I'+str(source/'opal')]
    cxxflags=['-std=c++17','-fopenmp','-DCOMPILATION_TIME_PLACE="2024-01-26 NativeWorkbench"','-DGIT_BRANCH_COMMIT_DIFF="STAR-2.7.11b-workbench1"']
    if not a.linux:cxxflags+=['-include',str(source/'windows_compat.h')]
    make=(source/'Makefile').read_text().replace('\\\n',' ')
    items=re.search(r'^OBJECTS = (.*?)\n\n',make,re.M|re.S).group(1).split()
    cppfiles=[source/(i[:-2]+'.cpp' if i.endswith('.o') else i) for i in items]
    cppfiles=[f if f.is_file() else f.with_suffix('.c') for f in cppfiles]
    zfiles=[zsource/(name+'.c') for name in ['adler32','compress','crc32','deflate','gzclose','gzlib','gzread','gzwrite','infback','inffast','inflate','inftrees','trees','uncompr','zutil']]
    # Local BGZF/BAM subset is selected by the recorded source patch; no CRAM/network backend.
    hfiles=[source/'htslib'/name for name in ['bgzf.c','sam.c','kstring.c','hfile.c']]
    jobs=[(f,True) for f in cppfiles]+[(f,False) for f in zfiles+hfiles]
    headers=hashlib.sha256(b''.join(f.read_bytes() for f in sorted([*source.rglob('*.h'),*zsource.glob('*.h'),source/'VERSION',source/'parametersDefault.xxd']))).hexdigest()
    def compile(item):
        f,cpp=item;obj=out/(str(f.relative_to(source)).replace('/','_')+'.o' if f.is_relative_to(source) else 'zlib_'+f.stem+'.o')
        cmd=[cxx if cpp else cc,*common,*(cxxflags if cpp else ['-std=gnu11']),'-c',str(f),'-o',str(obj)]
        signature=hashlib.sha256((json.dumps(cmd)+headers).encode()+f.read_bytes()).hexdigest();stamp=Path(str(obj)+'.sha256')
        if obj.exists() and stamp.exists() and stamp.read_text()==signature:return obj
        r=subprocess.run(cmd,env=env,capture_output=True,text=True)
        if r.returncode:return (str(f)+'\n'+r.stdout+r.stderr)
        stamp.write_text(signature)
        return obj
    with concurrent.futures.ThreadPoolExecutor(max_workers=a.jobs) as pool:objects=list(pool.map(compile,jobs))
    errors=[x for x in objects if isinstance(x,str)]
    if errors:raise RuntimeError('\n'.join(errors))
    binary=out/('STAR' if a.linux else 'STAR.exe')
    links=['-pthread','-fopenmp','-Wl,--gc-sections'] if a.linux else ['-static','-pthread',str(TC/'x86_64-w64-mingw32/lib/libomp.dll.a'),'-lws2_32','-Wl,--gc-sections','-Wl,--no-insert-timestamp']
    subprocess.run([cxx,*map(str,objects),*links,'-o',str(binary)],env=env,check=True)
    record={'schema':1,'compileFlags':common+cxxflags,'linkFlags':links,'sourceDateEpoch':env['SOURCE_DATE_EPOCH'],'toolchain':'GCC Linux reference' if a.linux else 'LLVM-MinGW 20260922 UCRT x86_64','compilerSha256':sha(Path(shutil.which(cxx)).resolve()),'sourceUrl':SOURCE_URL,'sourceSha256':SOURCE_SHA,'zlibSourceSha256':ZLIB_SHA,'patchSha256':sha(CACHE/'workbench1.patch'),'compiler':subprocess.check_output([cxx,'--version'],env=env,text=True).splitlines()[0],'executionTestsPerformedByBuild':False,'files':{binary.name:{'sha256':sha(binary),'bytes':binary.stat().st_size}}}
    if not a.linux:
        shutil.copy2(TC/'x86_64-w64-mingw32/bin/libomp.dll',out/'libomp.dll')
        for f in (binary,out/'libomp.dll'):
            imports=subprocess.check_output([str(TC/'bin/llvm-readobj'),'--coff-imports',str(f)],env=env,text=True)
            record['files'][f.name]={'sha256':sha(f),'bytes':f.stat().st_size,'imports':re.findall(r'^  Name: (.+)$',imports,re.M)}
            for dependency in record['files'][f.name]['imports']:
                if dependency.lower() not in ('kernel32.dll','ws2_32.dll','libomp.dll') and not dependency.lower().startswith('api-ms-win-crt-'):raise ValueError('Unexpected Windows DLL dependency: '+dependency)
    (out/'build.json').write_text(json.dumps(record,indent=2)+'\n');print(json.dumps(record,indent=2))
if __name__=='__main__':main()
