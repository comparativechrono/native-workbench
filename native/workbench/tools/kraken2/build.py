#!/usr/bin/env python3
"""Compile pinned Kraken2 with a narrow Windows OS/I/O boundary."""
import argparse, difflib, hashlib, json, os, re, shutil, subprocess, tarfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
SOURCE_SHA='84ff95cd6d8a4c9e93ab6bf1d9b3892099baaefb0277bcf2edc3eb4948566035'
def sha(p):
 with Path(p).open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def main():
 p=argparse.ArgumentParser();p.add_argument('--source',type=Path,default=ROOT/'build/kraken2/inputs/kraken2-2.17.2.tar.gz');p.add_argument('--output',type=Path,required=True);p.add_argument('--toolchain',type=Path,default=ROOT/'build/mosdepth-inputs/llvm/llvm-mingw-20260922-ucrt-ubuntu-22.04-x86_64');p.add_argument('--linux',action='store_true',help='Build unchanged upstream Linux reference; all compatibility edits are Windows-only.');p.add_argument('--upstream',action='store_true',help='Explicit assertion of unchanged reference; only valid with --linux.');a=p.parse_args()
 if a.upstream and not a.linux:p.error('--upstream applies only to the unchanged Linux reference build.')
 if sha(a.source)!=SOURCE_SHA:raise ValueError('Kraken2 source hash differs')
 out=a.output.resolve();out.mkdir(parents=True,exist_ok=False)
 with tarfile.open(a.source) as t:t.extractall(out/'source',filter='data')
 src=out/'source/kraken2-2.17.2/src';tc=a.toolchain.resolve();patches=[]
 if not a.linux:
  for f in src.iterdir():
   if f.suffix not in ('.cc','.h'):continue
   before=f.read_text();after=before
   for header in ('err.h','sysexits.h','sys/mman.h','sys/wait.h'):after=after.replace('#include <'+header+'>','// Windows OS boundary supplies '+header)
   after=re.sub(r'(?<![.>:\w])open\(', 'wb_open(', after)
   after=re.sub(r'(?<![.>:\w])read\(', 'wb_read(', after)
   after=after.replace('KSTREAM_INIT(int, read,', 'KSTREAM_INIT(int, wb_read,')
   after=after.replace('case Unknown:', 'case kraken2::Unknown:').replace('stoul(token)', 'stoull(token)')
   after=after.replace('idx_opt_fs(opts.options_filename);','idx_opt_fs(opts.options_filename, std::ios::binary);')
   if f.name in ('taxonomy.cc','kv_store.h'):after=after.replace('std::ifstream ifs(filename);','std::ifstream ifs(filename, std::ios::binary);').replace('ofstream taxo_file(filename);','ofstream taxo_file(filename, std::ios::binary);')
   if f.name=='hyperloglogplus.cc':after=after.replace('#ifdef WIN32','#if defined(_MSC_VER) && !defined(__clang__)').replace('__builtin_clzl(x)','__builtin_clzll(x)')
   if f.name in ('build_db.cc','estimate_capacity.cc'):after=after.replace('strtol(optarg, nullptr, 2)','strtoull(optarg, nullptr, 2)')
   if f.name=='build_db.cc':after=after.replace('ofstream opts_fs(opts.options_filename);','ofstream opts_fs(opts.options_filename, std::ios::binary);')
   if f.name=='classify.cc':
    start=after.index('void RemoveBlocking(');end=after.index('IndexData *load_index',start);after=after[:start]+after[end:]
    start=after.index('void ClassifyDaemon(');end=after.index('int main(',start);after=after[:start]+'void ClassifyDaemon(Options) { errx(EX_USAGE,"Daemon mode is unavailable in the local Workbench pack"); }\n\n'+after[end:]
   if f.name=='compact_hash.h':
    start=after.index('  if (threads < 1) threads = 1;',after.index('static inline void pread_parallel'))
    end=after.index('\n}\n',start)
    after=after[:start]+'  // Windows synchronous CRT handle: bounded sequential loading preserves bytes.\n  if (_lseeki64(fd,base_off,SEEK_SET)<0) errx(EX_OSERR,"seek failed for %s",what);\n  read_fully(fd,buf,n,what);'+after[end:]
   if before!=after:
    f.write_text(after);patches.extend(difflib.unified_diff(before.splitlines(True),after.splitlines(True),fromfile='a/src/'+f.name,tofile='b/src/'+f.name))
  shutil.copyfile(ROOT/'tools/kraken2/mmap_windows.cc',src/'mmap_file.cc')
 (out/'windows.patch').write_text(''.join(patches))
 env=dict(os.environ,LD_LIBRARY_PATH=str(tc/'lib'),SOURCE_DATE_EPOCH='1788861365',TMPDIR=str(out/'tmp'));(out/'tmp').mkdir()
 cxx='g++' if a.linux else str(tc/'bin/x86_64-w64-mingw32-clang++')
 flags=['-O3','-std=c++11','-fopenmp','-DLINEAR_PROBING']
 if not a.linux:flags+=['-D_FILE_OFFSET_BITS=64','-include',str(ROOT/'tools/kraken2/windows_compat.h')]
 common='reports hyperloglogplus mmap_file compact_hash taxonomy seqreader mmscanner omp_hack aa_translate utilities'.split()
 programs={'classify':['classify',*common],'build_db':['build_db','mmap_file','compact_hash','taxonomy','seqreader','mmscanner','omp_hack','utilities'],'dump_table':['dump_table','mmap_file','compact_hash','omp_hack','taxonomy','reports','hyperloglogplus'],'estimate_capacity':['estimate_capacity','seqreader','mmscanner','omp_hack','utilities']}
 commands=[]
 with (out/'build.log').open('w') as log:
  def run(cmd):commands.append(cmd);subprocess.run(cmd,cwd=src,env=env,stdout=log,stderr=subprocess.STDOUT,check=True)
  abi=out/'abi-check.cc';abi.write_text('#include "kraken2_data.h"\n#include "taxonomy.h"\n#include "compact_hash.h"\nstatic_assert(sizeof(size_t)==8,"size_t must be64-bit");\nstatic_assert(sizeof(off_t)==8,"off_t must be64-bit");\nstatic_assert(sizeof(kraken2::IndexOptions)==64,"IndexOptions must match upstream x64 layout");\nstatic_assert(sizeof(kraken2::TaxonomyNode)==56,"TaxonomyNode layout differs");\nstatic_assert(sizeof(kraken2::CompactHashCell)==4,"32bitcell layout differs");\nstatic_assert(sizeof(kraken2::CompactHashCell40)==5,"40bitcell layout differs");\n')
  run([cxx,*flags,'-I'+str(src),'-c',str(abi),'-o',str(out/'abi-check.o')])
  for name in sorted(set(sum(programs.values(),[]))):run([cxx,*flags,'-c',str(src/(name+'.cc')),'-o',str(out/(name+'.o'))])
  for name,objects in programs.items():run([cxx,*flags,*[str(out/(x+'.o')) for x in objects],*([] if a.linux else ['-static-libstdc++','-static-libgcc','-Wl,--no-insert-timestamp']),'-o',str(out/(name+('' if a.linux else '.exe')))])
 files={}
 if not a.linux:shutil.copyfile(tc/'x86_64-w64-mingw32/bin/libomp.dll',out/'libomp.dll')
 for name in [x+('' if a.linux else '.exe') for x in programs]+([] if a.linux else ['libomp.dll']):
  f=out/name;files[name]={'sha256':sha(f),'bytes':f.stat().st_size}
  if not a.linux:
   info=subprocess.check_output([str(tc/'bin/llvm-readobj'),'--coff-imports',str(f)],env=env,text=True);files[name]['imports']=re.findall(r'^  Name: (.+)$',info,re.M)
 record={'schema':1,'upstreamVersion':'2.17.2','runtimeVersion':'2.17.2-workbench1','sourceSha256':SOURCE_SHA,'windowsExecuted':False,'platform':'linux-x86_64' if a.linux else 'windows-x86_64','compiler':subprocess.check_output([cxx,'--version'],env=env,text=True).splitlines()[0],'compilerSha256':sha(Path(shutil.which(cxx)).resolve()),'commands':commands,'files':files,'patchSha256':sha(out/'windows.patch'),'scientificAlgorithmsModified':False,'boundarySources':{name:sha(ROOT/'tools/kraken2'/name) for name in ('build.py','windows_compat.h','mmap_windows.cc')}}
 (out/'build.json').write_text(json.dumps(record,indent=2)+'\n');print(json.dumps({'output':str(out),'files':files},indent=2))
if __name__=='__main__':main()
