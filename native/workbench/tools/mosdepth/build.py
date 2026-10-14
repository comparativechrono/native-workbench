#!/usr/bin/env python3
"""Build pinned mosdepth with its explicit local BAM boundary for Windows/Linux."""
import argparse,difflib,json,os,re,shutil,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT/'scripts'))
from fetch_mosdepth_build_inputs import CACHE,SOURCES,sha,copy,extract

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--cache',type=Path,default=CACHE);p.add_argument('--output',type=Path,required=True);p.add_argument('--linux',action='store_true');a=p.parse_args();cache=a.cache.resolve();out=a.output.resolve();out.mkdir(parents=True,exist_ok=False)
 for name,(_,digest) in SOURCES.items():
  if sha(cache/name)!=digest:raise ValueError('Changed pinned input '+name)
 src={name:extract(cache/(name+'.tar.'+('bz2' if name=='htslib' else 'xz' if name in ('llvm','nim') else 'gz')),out/('src-'+name)) for name in ('mosdepth','hts-nim-pinned','htslib','zlib','pcre2','docopt','regex','unicodedb')}
 # Large immutable compiler trees can be shared across target builds after digest verification.
 for name in ('nim','llvm'):
  d=cache/name
  if not d.exists():extract(cache/(name+'.tar.xz'),d)
  src[name]=next(d.iterdir())
 sourcefile=src['mosdepth']/'mosdepth.nim';before=sourcefile.read_text();after=before
 for old,new in [('var tmp = getEnv("MOSDEPTH_PRECISION")','var tmp = "2" # Workbench fixes report formatting independently of host environment.'),('let env_fasta = getEnv("REF_PATH")','let env_fasta = "" # Workbench exposes local BAM only; no implicit reference.'),('let version = "mosdepth 0.3.14"','let version = "mosdepth 0.3.14-workbench1"')]:
  if after.count(old)!=1:raise ValueError('Portability patch anchor missing: '+old)
  after=after.replace(old,new)
 sourcefile.write_text(after);patch=out/'workbench1.patch';patch.write_text(''.join(difflib.unified_diff(before.splitlines(True),after.splitlines(True),fromfile='a/mosdepth.nim',tofile='b/mosdepth.nim')))
 tc=src['llvm'];(out/'tmp').mkdir();env=dict(os.environ,TMPDIR=str(out/'tmp'),LD_LIBRARY_PATH=str(tc/'lib'),PATH=str(tc/'bin')+os.pathsep+os.environ.get('PATH',''),SOURCE_DATE_EPOCH='1777037618')
 cc='gcc' if a.linux else str(tc/'bin/x86_64-w64-mingw32-clang');cxx='g++' if a.linux else str(tc/'bin/x86_64-w64-mingw32-clang++');ar='ar' if a.linux else str(tc/'bin/llvm-ar');ran='ranlib' if a.linux else str(tc/'bin/llvm-ranlib')
 commands=[]
 with (out/'build.log').open('w') as log:
  def run(cmd,cwd=None,runenv=None):
   commands.append({'args':cmd,'cwd':str(cwd or out)});subprocess.run(cmd,cwd=cwd or out,env=runenv or env,stdout=log,stderr=subprocess.STDOUT,check=True)
  z=src['zlib'];objs=[]
  for name in 'adler32 compress crc32 deflate gzclose gzlib gzread gzwrite infback inffast inflate inftrees trees uncompr zutil'.split():
   o=out/(name+'.o');objs.append(str(o));run([cc,'-O2','-fPIC','-DZ_HAVE_UNISTD_H','-I'+str(z),'-c',str(z/(name+'.c')),'-o',str(o)])
  run([ar,'rcs',str(out/'libz.a'),*objs])
  compileenv=dict(env,CC=cc,AR=ar,RANLIB=ran,CFLAGS='-O2 -fPIC -pipe',CPPFLAGS='-I'+str(z),LDFLAGS='-L'+str(out))
  if not a.linux:
   pe=dict(compileenv,LDFLAGS='-static');run(['./configure','--host=x86_64-w64-mingw32','--disable-shared','--enable-static','--disable-pcre2grep','--disable-pcre2test','--enable-pcre2-8','--prefix='+str(out/'pcre')],src['pcre2'],pe);run(['make','-j4','install'],src['pcre2'],pe)
   copy(out/'pcre/include/pcre2posix.h',out/'pcre/include/regex.h')
   compileenv.update(CPPFLAGS='-I'+str(z)+' -I'+str(out/'pcre/include')+' -DPCRE2_STATIC',LDFLAGS='-L'+str(out)+' -L'+str(out/'pcre/lib')+' -static -Wl,--no-insert-timestamp',LIBS='-lpcre2-posix -lpcre2-8')
  h=src['htslib'];run(['./configure',*([] if a.linux else ['--host=x86_64-w64-mingw32']),'--disable-libcurl','--disable-s3','--disable-gcs','--disable-plugins','--disable-bz2','--disable-lzma','--without-libdeflate'],h,compileenv)
  run(['make','-j4','lib-shared' if a.linux else 'hts-3.dll','libhts.a'],h,compileenv)
  dll='libhts.so' if a.linux else 'libhts.dll';copy(h/('libhts.so' if a.linux else 'hts-3.dll'),out/dll)
  nim=src['nim']/'bin/nim';binary=out/('mosdepth' if a.linux else 'mosdepth.exe')
  run([str(nim),'c','--mm:refc','-d:release','--parallelBuild:1','--passC:-pipe',*([] if a.linux else ['--os:windows','--cpu:amd64','--cc:clang','--clang.exe:'+cc,'--clang.linkerexe:'+cc,'--passL:-static','--passL:-Wl,--no-insert-timestamp']),*['--path:'+str(src[n]/'src') for n in ('hts-nim-pinned','docopt','regex','unicodedb')],'--nimcache:'+str(out/'nimcache'),'-o:'+str(binary),str(src['mosdepth']/'mosdepth.nim')])
  guard=out/('mosdepth-guard' if a.linux else 'mosdepth-guard.exe');run([cxx,'-O2','-std=c++17','-I'+str(h),'-I'+str(z),str(ROOT/'tools/mosdepth/guard.cpp'),str(h/'libhts.a'),'-L'+str(out),'-lz','-lpthread','-lm',*([] if a.linux else ['-L'+str(out/'pcre/lib'),'-lpcre2-posix','-lpcre2-8','-lws2_32','-static','-Wl,--no-insert-timestamp']),'-o',str(guard)])
 record={'schema':1,'upstreamVersion':'0.3.14','runtimeVersion':'0.3.14-workbench1','patchSha256':sha(patch),'htslibVersion':'1.23.1','platform':'linux-x86_64' if a.linux else 'windows-x86_64','upstreamAlgorithmModified':False,'nativeWindowsExecuted':False,'guardSha256':sha(ROOT/'tools/mosdepth/guard.cpp'),'sources':{n:{'url':u,'sha256':d} for n,(u,d) in SOURCES.items()},'nimCompiler':subprocess.check_output([str(nim),'--version'],env=env,text=True),'cCompiler':subprocess.check_output([cc,'--version'],env=env,text=True).splitlines()[0],'commands':commands,'files':{f.name:{'sha256':sha(f),'bytes':f.stat().st_size} for f in (binary,guard,out/dll)}}
 if not a.linux:
  for f in (binary,guard,out/dll):
   imports=subprocess.check_output([str(tc/'bin/llvm-readobj'),'--coff-imports',str(f)],env=env,text=True);names=re.findall(r'^  Name: (.+)$',imports,re.M);record['files'][f.name]['imports']=names
   for name in names:
    if name.lower() not in ('kernel32.dll','ws2_32.dll','advapi32.dll','bcrypt.dll') and not name.lower().startswith('api-ms-win-crt-'):raise ValueError('Unbundled DLL '+name)
 (out/'build.json').write_text(json.dumps(record,indent=2)+'\n');print(json.dumps({'output':str(out),'files':record['files']},indent=2))
if __name__=='__main__':main()
