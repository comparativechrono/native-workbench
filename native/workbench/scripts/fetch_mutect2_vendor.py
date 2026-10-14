#!/usr/bin/env python3
"""Verify pinned Mutect2 inputs; download only with explicit --download."""
import argparse
from pathlib import Path
import shutil
import urllib.request
from prepare_mutect2_pack import PINS,VENDOR,digest

TEMURIN='https://github.com/adoptium/temurin17-binaries/releases/download/jdk-17.0.20.1%2B1/'
URLS={
 'gatk-4.7.0.0.zip':'https://github.com/broadinstitute/gatk/releases/download/4.7.0.0/gatk-4.7.0.0.zip',
 'gatk-4.7.0.0-source.tar.gz':'https://api.github.com/repos/broadinstitute/gatk/tarball/4.7.0.0',
 'OpenJDK17U-jre_x64_windows_hotspot_17.0.20.1_1.zip':TEMURIN+'OpenJDK17U-jre_x64_windows_hotspot_17.0.20.1_1.zip',
 'OpenJDK17U-jdk-sources_17.0.20.1_1.tar.gz':TEMURIN+'OpenJDK17U-jdk-sources_17.0.20.1_1.tar.gz',
 'Microsoft-VC-Runtime-2015-2022-License.docx':'https://visualstudio.microsoft.com/wp-content/uploads/2021/09/Visual-C-Runtime-2015-2022-License-1.docx',
}
REFERENCE={'OpenJDK17U-jre_x64_linux_hotspot_17.0.20.1_1.tar.gz':(TEMURIN+'OpenJDK17U-jre_x64_linux_hotspot_17.0.20.1_1.tar.gz','0b2b640e3046b64c8ec504de0ab9d91bb5610182bda21fad454681ce54d45a62')}


def main():
 parser=argparse.ArgumentParser(description=__doc__)
 parser.add_argument('--download',action='store_true')
 parser.add_argument('--reference-linux',action='store_true')
 parser.add_argument('--restore-sources',type=Path)
 parser.add_argument('--directory',type=Path,default=VENDOR)
 args=parser.parse_args();assert PINS.keys()==URLS.keys()
 assets={name:(URLS[name],pin) for name,pin in PINS.items()}
 if args.reference_linux:assets.update(REFERENCE)
 args.directory.mkdir(parents=True,exist_ok=True)
 for name,(url,pin) in assets.items():
  target=args.directory/name
  if not target.exists() and args.restore_sources:
   source=args.restore_sources/name
   if source.is_file():
    if digest(source)!=pin:raise ValueError('Restored source checksum mismatch: '+name)
    shutil.copyfile(source,target)
  if not target.exists():
   if not args.download:raise FileNotFoundError('Missing '+name+'; use --download or --restore-sources')
   temporary=target.with_name(target.name+'.partial')
   try:
    request=urllib.request.Request(url,headers={'User-Agent':'Native-Workbench-source-fetch/0.5.4'})
    with urllib.request.urlopen(request,timeout=180) as response,temporary.open('wb') as stream:shutil.copyfileobj(response,stream,length=1024*1024)
    if digest(temporary)!=pin:raise ValueError('Downloaded checksum mismatch: '+name)
    temporary.replace(target)
   finally:temporary.unlink(missing_ok=True)
  if digest(target)!=pin:raise ValueError('Existing file checksum mismatch: '+name)
  print('Verified '+name)


if __name__=='__main__':main()
