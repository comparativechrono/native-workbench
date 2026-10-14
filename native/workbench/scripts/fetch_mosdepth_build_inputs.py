#!/usr/bin/env python3
"""Recover exact public mosdepth source/compiler inputs; no analysis-time downloads."""
import argparse, hashlib, json, shutil, tarfile, urllib.request
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
CACHE=ROOT/'build/mosdepth-inputs'
SOURCES={
 'mingw-w64-source.tar.gz':('https://codeload.github.com/mingw-w64/mingw-w64/tar.gz/57b595039040eaa15bece85b7cc71d952281b269','a68816e314290facd5da1ac96c7eead7e6de6ea4f709a1fbdcf8185497c57eb2'),
 'starter.zip':('https://github.com/comparativechrono/workbench/releases/download/app-v0.6.0/native-workbench-0.6.0-starter-windows.zip','16fa802304c734b5721d838ff38b7e90ed36ccfc185a22239859cc3762af695a'),
 'nim-source.tar.gz':('https://codeload.github.com/nim-lang/Nim/tar.gz/94f8857d5955d2a1fa0b36f81762fa173844f104','6a493f04f66d7c3ee97a3651f6d5b4943ff047d0f71d54d443d2bf1835942c5e'),
 'llvm-mingw-source.tar.gz':('https://codeload.github.com/mstorsjo/llvm-mingw/tar.gz/refs/tags/20260922','9e430702df67673bb9632253d3f63868e1c13d15ef21deb350b953282b767627'),
 'mosdepth.tar.gz':('https://codeload.github.com/brentp/mosdepth/tar.gz/refs/tags/v0.3.14','abac67de4547dc5642efd46846044d6b3536d2ca3443b4ca172446edf82eeb42'),
 'hts-nim-pinned.tar.gz':('https://codeload.github.com/brentp/hts-nim/tar.gz/50b64d8843f20326d113c1ef1f29dc773f32915b','eaed2c7f321cfa9f9f0e12ad42d4cf2add34528a2aa218af37e9b3a6dbde2b00'),
 'htslib.tar.bz2':('https://github.com/samtools/htslib/releases/download/1.23.1/htslib-1.23.1.tar.bz2','f8a3f36effeec38f043c53ab1f2d9ed45064f14205c5ef8e3c815763b90803c4'),
 'zlib.tar.gz':('https://zlib.net/zlib-1.3.2.tar.gz','bb329a0a2cd0274d05519d61c667c062e06990d72e125ee2dfa8de64f0119d16'),
 'pcre2.tar.gz':('https://github.com/PCRE2Project/pcre2/releases/download/pcre2-10.46/pcre2-10.46.tar.gz','8d28d7f2c3b970c3a4bf3776bcbb5adfc923183ce74bc8df1ebaad8c1985bd07'),
 'docopt.tar.gz':('https://codeload.github.com/docopt/docopt.nim/tar.gz/refs/tags/v0.7.1','a172f7e8be5c10735727ca00f69294e8615c4ad055dd9b58dcdb0f7c6bd7d025'),
 'regex.tar.gz':('https://codeload.github.com/nitely/nim-regex/tar.gz/refs/tags/v0.26.3','f237ca8e162cd203c5530f0ca05c0dc3b00288ee190d8ad8efba45cd51a2d4d6'),
 'unicodedb.tar.gz':('https://codeload.github.com/nitely/nim-unicodedb/tar.gz/refs/tags/v0.13.2','61a994fbdc3f3596e5dd663ca17fe585726da5c5b7059e437087787b3aa9aae2'),
 'nim.tar.xz':('https://github.com/nim-lang/nightlies/releases/download/2026-10-01-version-2-2-94f8857d5955d2a1fa0b36f81762fa173844f104/linux_x64.tar.xz','d4d593c30815c6f9f55054e4fefaccdcd743a080525138f2d5dbb69b6d75b4d7'),
 'llvm.tar.xz':('https://github.com/mstorsjo/llvm-mingw/releases/download/20260922/llvm-mingw-20260922-ucrt-ubuntu-22.04-x86_64.tar.xz','bb7bb7654b33d5aa8712acb837c963b2e0c56352560c76105270a3268c665c21'),
 'upstream-mosdepth':('https://github.com/brentp/mosdepth/releases/download/v0.3.14/mosdepth','c5182b74a8f1b66710efa16e122cbc8a197834874b103e7c5c0bd9a6265ae7b6'),
}
def sha(p):
 with Path(p).open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def copy(source,dest):
 dest=Path(dest);dest.parent.mkdir(parents=True,exist_ok=True)
 with Path(source).open('rb') as src,dest.open('wb') as out:shutil.copyfileobj(src,out,1024*1024)
 if Path(source).stat().st_size!=dest.stat().st_size or sha(source)!=sha(dest):raise ValueError('Copy integrity failure: '+str(dest))
def extract(archive,dest):
 dest=Path(dest)
 if dest.exists():raise ValueError('Extraction requires a new directory: '+str(dest))
 dest.mkdir(parents=True)
 with tarfile.open(archive) as t:t.extractall(dest,filter='data')
 return next(dest.iterdir())
def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--cache',type=Path,default=CACHE);a=p.parse_args();a.cache.mkdir(parents=True,exist_ok=True)
 for name,(url,digest) in SOURCES.items():
  f=a.cache/name
  if not f.exists():
   with urllib.request.urlopen(url,timeout=180) as src,f.open('wb') as out:shutil.copyfileobj(src,out,1024*1024)
  if sha(f)!=digest:raise ValueError('Missing/changed pinned input: '+name)
 print(json.dumps({'sources':{n:{'url':u,'sha256':d,'bytes':(a.cache/n).stat().st_size} for n,(u,d) in SOURCES.items()}},indent=2))
if __name__=='__main__':main()
