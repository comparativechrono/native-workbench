#!/usr/bin/env python3
"""Apply two exact, hash-guarded offline-boundary changes to pinned BLAST source."""
import argparse
import hashlib
import json
from pathlib import Path

EXPECTED = {
    'c++/src/app/blast/blast_formatter.cpp': (
        '17c2e8f4b2fc0813ac4d8ea4a6589d46f42b44b5e607de49b0be77d2d9be518f',
        '00256274213373cd8f27616c21cd04d6313a6aec646ecb63cbd3b4347424cfac'),
    'c++/src/algo/blast/blastinput/blast_scope_src.cpp': (
        'b040a3dc5e7fa8be0236f5e0598d50d24db9cd28508affb1a3d2e1a778b79c1e',
        '7036efe9edbff9a306b20b7a560c099cc8eae686d03d71899a9ae3a0778db5aa'),
}


def digest(data):
    return hashlib.sha256(data).hexdigest()


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source-root',type=Path,required=True)
    p.add_argument('--report',type=Path,required=True)
    args=p.parse_args()
    patch=Path(__file__).with_name('local-only.patch').read_bytes()
    hunks={}; identity=None; old=[];new=[]
    def flush():
        if old or new:
            hunks.setdefault(identity,[]).append((''.join(old),''.join(new)))
            old.clear();new.clear()
    for line in patch.decode('utf-8').splitlines(keepends=True):
        if line.startswith('--- a/'):
            flush();identity=line[6:].strip()
            if identity not in EXPECTED:raise ValueError('Unreviewed patch target')
        elif line.startswith('+++ b/'):continue
        elif line.startswith('@@'):flush()
        elif line.startswith(' '):old.append(line[1:]);new.append(line[1:])
        elif line.startswith('-'):old.append(line[1:])
        elif line.startswith('+'):new.append(line[1:])
        else:raise ValueError('Unexpected patch line')
    flush()
    if set(hunks)!=set(EXPECTED):raise ValueError('Incomplete offline patch set')
    records=[]
    for name,(before,after) in EXPECTED.items():
        path=args.source_root/name;data=path.read_bytes()
        if digest(data)!=before:raise ValueError('Source differs before patch: '+name)
        text=data.decode('utf-8')
        for old,new in hunks[name]:
            if text.count(old)!=1:raise ValueError('Patch context differs: '+name)
            text=text.replace(old,new)
        data=text.encode('utf-8')
        if digest(data)!=after:raise ValueError('Source differs after patch: '+name)
        path.write_bytes(data);records.append(dict(path=name,beforeSha256=before,afterSha256=after))
    args.report.write_text(json.dumps(dict(schema=1,patchSha256=digest(patch),files=records),indent=2)+'\n',encoding='utf-8')


if __name__=='__main__':main()
