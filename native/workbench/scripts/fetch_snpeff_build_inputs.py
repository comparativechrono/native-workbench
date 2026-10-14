#!/usr/bin/env python3
"""Recover immutable SnpEff/SnpSift and private Java build inputs, never analysis data."""
import argparse, hashlib, json, urllib.request
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
PINS=json.loads((ROOT/'tools/snpeff/build-inputs.json').read_text())
def sha(path):
    with Path(path).open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()
def recover(cache,fetch=True):
    cache.mkdir(parents=True,exist_ok=True)
    for row in PINS:
        p=cache/row['name']
        if not p.exists() and fetch:
            q=p.with_name(p.name+'.partial')
            with urllib.request.urlopen(row['url'],timeout=90) as src,q.open('wb') as dst:
                while block:=src.read(1024*1024):dst.write(block)
            if sha(q)!=row['sha256']:raise ValueError('Downloaded checksum differs: '+row['name'])
            q.replace(p)
        if not p.is_file() or sha(p)!=row['sha256']:raise ValueError('Missing or changed pinned input: '+str(p))
    return {'files':len(PINS),'cache':str(cache)}
if __name__=='__main__':
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--cache',type=Path,default=ROOT/'build/snpeff-inputs');ap.add_argument('--verify-only',action='store_true');a=ap.parse_args();print(json.dumps(recover(a.cache.resolve(),not a.verify_only),indent=2))
