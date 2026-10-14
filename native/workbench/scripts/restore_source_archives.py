#!/usr/bin/env python3
"""Restore source archives from an intact matching release without downloading."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import shutil


def sha(path):
    h=hashlib.sha256()
    with path.open('rb') as source:
        for block in iter(lambda:source.read(1024*1024),b''):h.update(block)
    return h.hexdigest()


def safe_path(root,relative):
    if not isinstance(relative,str) or not relative or '\\' in relative or ':' in relative:
        raise ValueError('Invalid source inventory path')
    parts=relative.split('/')
    if any(part in ('','.','..') for part in parts):raise ValueError('Unsafe source inventory path')
    result=root.joinpath(*parts)
    for parent in (result,*result.parents):
        if parent==root.parent:break
        if parent.is_symlink() or (hasattr(parent,'is_junction') and parent.is_junction()):
            raise ValueError('Source archive paths cannot use links')
    return result


def restore(source_root,runtime_root):
    source_root,runtime_root=Path(source_root).resolve(),Path(runtime_root).resolve()
    manifest=json.loads((source_root/'SOURCE-CONTENTS.json').read_text(encoding='utf-8'))
    if manifest.get('schema')!=1:raise ValueError('Unsupported source inventory')
    items=manifest.get('restore_from_runtime')
    if not isinstance(items,list):raise ValueError('Missing source archive inventory')
    staged=[]
    # Validate all source and destination identities before creating anything.
    for item in items:
        source=safe_path(runtime_root,item['runtime_path'])
        target=safe_path(source_root,item['source_path'])
        if not item['runtime_path'].startswith('packs/') or '/licenses/' not in item['runtime_path']:
            raise ValueError('Corresponding source must come from a declared pack license folder')
        if type(item['bytes']) is not int or item['bytes']<0 or not isinstance(item['sha256'],str) or len(item['sha256'])!=64:
            raise ValueError('Invalid source identity')
        if not source.is_file() or source.stat().st_size!=item['bytes'] or sha(source)!=item['sha256']:
            raise ValueError('Corresponding source archive differs: '+str(source))
        if target.exists():
            if not target.is_file() or target.stat().st_size!=item['bytes'] or sha(target)!=item['sha256']:
                raise ValueError('Existing source archive differs; refusing overwrite: '+str(target))
        else:staged.append((source,target,item))
    copied=[]
    for source,target,item in staged:
        target.parent.mkdir(parents=True,exist_ok=True)
        with source.open('rb') as incoming,target.open('xb') as output:shutil.copyfileobj(incoming,output,1024*1024)
        if target.stat().st_size!=item['bytes'] or sha(target)!=item['sha256']:
            raise ValueError('Restored archive failed integrity check: '+str(target))
        copied.append(item['source_path'])
    return {'restored':len(copied),'already_present':len(items)-len(copied),'files':copied}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root',type=Path,default=Path(__file__).resolve().parents[1])
    parser.add_argument('--runtime-root',type=Path,required=True)
    args=parser.parse_args();print(json.dumps(restore(args.source_root,args.runtime_root),indent=2))


if __name__=='__main__':main()
