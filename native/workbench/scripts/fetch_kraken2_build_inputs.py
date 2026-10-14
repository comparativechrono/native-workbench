#!/usr/bin/env python3
"""Recover hash-pinned Kraken2 build inputs; never run during analysis."""
import argparse,hashlib,json,shutil,urllib.request
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
CACHE=ROOT/'build/kraken2/inputs'
SOURCES={
 'kraken2-2.17.2.tar.gz':('https://codeload.github.com/DerrickWood/kraken2/tar.gz/refs/tags/2.17.2','84ff95cd6d8a4c9e93ab6bf1d9b3892099baaefb0277bcf2edc3eb4948566035'),
 'python.zip':('https://www.python.org/ftp/python/3.13.16/python-3.13.16-embed-amd64.zip','97dae5274cc54867065e8d5a3226e48c35017ed332a0fdb0e27d5b5821961297'),
 'python-source.tar.xz':('https://www.python.org/ftp/python/3.13.16/Python-3.13.16.tar.xz','f4b1bfb3c79b5bb11b8d228a12504163b4c0dab4d679828d8f5f26b6cb6ab35d'),
 'llvm-project-23.1.2.src.tar.xz':('https://github.com/llvm/llvm-project/releases/download/llvmorg-23.1.2/llvm-project-23.1.2.src.tar.xz','c98bbef08a2b4c2613cd50e9aa9ae7b69b1fe6c16b2c40373bc0ab6116fdf78a'),
 'mingw-w64-source.tar.gz':('https://codeload.github.com/mingw-w64/mingw-w64/tar.gz/57b595039040eaa15bece85b7cc71d952281b269','a68816e314290facd5da1ac96c7eead7e6de6ea4f709a1fbdcf8185497c57eb2'),
 'llvm-mingw-source.tar.gz':('https://codeload.github.com/mstorsjo/llvm-mingw/tar.gz/refs/tags/20260922','9e430702df67673bb9632253d3f63868e1c13d15ef21deb350b953282b767627')}
TOOLCHAIN=('https://github.com/mstorsjo/llvm-mingw/releases/download/20260922/llvm-mingw-20260922-ucrt-ubuntu-22.04-x86_64.tar.xz','bb7bb7654b33d5aa8712acb837c963b2e0c56352560c76105270a3268c665c21')
def sha(p):
 with Path(p).open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def recover(cache,fetch=False):
 cache=Path(cache);cache.mkdir(parents=True,exist_ok=True)
 for name,(url,digest) in SOURCES.items():
  path=cache/name
  if not path.exists() and fetch:
   partial=path.with_name(path.name+'.partial')
   with urllib.request.urlopen(url,timeout=180) as src,partial.open('wb') as out:shutil.copyfileobj(src,out,1024*1024)
   if sha(partial)!=digest:raise ValueError('Download checksum differs: '+name)
   partial.replace(path)
  if not path.is_file() or sha(path)!=digest:raise ValueError('Missing or altered pinned input '+name+'; run fetch_kraken2_build_inputs.py explicitly.')
 return {n:{'url':u,'sha256':d,'bytes':(cache/n).stat().st_size} for n,(u,d) in SOURCES.items()}
def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--cache',type=Path,default=CACHE);p.add_argument('--with-toolchain',action='store_true',help='Also download the pinned Linux-hosted LLVM/MinGW compiler archive for explicit extraction.');a=p.parse_args();record=recover(a.cache,True)
 if a.with_toolchain:
  path=a.cache/'llvm-mingw-20260922.tar.xz';url,digest=TOOLCHAIN
  if not path.exists():
   with urllib.request.urlopen(url,timeout=180) as src,path.with_suffix('.partial').open('wb') as out:shutil.copyfileobj(src,out,1024*1024)
   if sha(path.with_suffix('.partial'))!=digest:raise ValueError('Compiler archive checksum differs.')
   path.with_suffix('.partial').replace(path)
  if sha(path)!=digest:raise ValueError('Compiler archive checksum differs.')
  record[path.name]={'url':url,'sha256':digest,'bytes':path.stat().st_size}
 print(json.dumps(record,indent=2))
if __name__=='__main__':main()
