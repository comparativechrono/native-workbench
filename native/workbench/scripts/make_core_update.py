#!/usr/bin/env python3
"""Build an exact app-only update, independent of installed optional packs."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sys
import zipfile

sys.dont_write_bytecode=True
sys.path.insert(0,str(Path(__file__).resolve().parent))
from apply_core_update import NATIVE_NOTICE_FILES, baseline_inventory, core_inventory, ordinary_root
from apply_desktop_update import inside, read_json, require, sha, verify

SOURCE=Path(__file__).resolve().parents[1]


def make(base,target,output,launcher=None):
    base,target=ordinary_root(base),ordinary_root(target)
    output=Path(output).absolute()
    require(not output.exists(),'Choose a new updater staging directory')
    require(not output.is_relative_to(base) and not output.is_relative_to(target), 'Updater staging must be outside installations')
    old_raw=(base/'manifest.json').read_bytes(); old=read_json(base/'manifest.json')
    new_raw=(target/'manifest.json').read_bytes(); new=read_json(target/'manifest.json')
    targets=core_inventory(new); baseline,migration=baseline_inventory(old,targets)
    require(tuple(map(int,old['version'].split('.')))<tuple(map(int,new['version'].split('.'))),'Update must advance the core version')
    for name,item in baseline.items():verify(inside(base,name),item['sha256'],item['bytes'])
    for name,item in targets.items():verify(inside(target,name),item['sha256'],item['bytes'])
    if launcher is not None:
        require(Path(launcher).is_file(),'Build the native core update launcher first')
        require('runtime/python/python.exe' in targets,'The updater needs its own bundled private Python')
        require({'LICENSE',*('runtime/licenses/native/'+name for name in NATIVE_NOTICE_FILES)} <= set(targets),
                'The updater needs the application license and complete native runtime notices')
    output.mkdir(parents=True); update=output/'update'; (update/'blobs').mkdir(parents=True)
    def blob(path):
        identity=sha(path); destination=update/'blobs'/identity
        if not destination.exists():shutil.copyfile(path,destination)
        return identity
    operations=[]
    for name,item in targets.items():
        if baseline.get(name)!=item:operations.append({**item,'blob':blob(inside(target,name))})
    target_blob=blob(target/'manifest.json')
    recipe={'schema_version':1,'kind':'native-core-update','base_version':old['version'],'target_version':new['version'],
            'base_manifest_sha256':hashlib.sha256(old_raw).hexdigest(),
            'target_manifest_sha256':hashlib.sha256(new_raw).hexdigest(),'target_manifest_blob':target_blob,
            'operations':operations,'obsolete':[] if migration else sorted(set(baseline)-set(targets))}
    (update/'update-manifest.json').write_text(json.dumps(recipe,indent=2)+'\n',encoding='utf-8')
    shutil.copy2(SOURCE/'scripts/apply_core_update.py',update/'apply_workspace_update.py')
    # Reuse exact lock/path primitives. The historical apply() is never called.
    shutil.copy2(SOURCE/'scripts/apply_desktop_update.py',update/'apply_desktop_update.py')
    if launcher is not None:
        shutil.copy2(launcher,output/'UpdateWorkbench.exe')
        # Execute with the updater's private copy, never the installation's
        # interpreter. Windows must be able to replace Python/DLLs in the target.
        for name,item in targets.items():
            if name == 'LICENSE' or name.startswith(('runtime/python/','runtime/licenses/native/')):
                destination=inside(output,name);destination.parent.mkdir(parents=True,exist_ok=True)
                shutil.copyfile(inside(target,name),destination)
                verify(destination,item['sha256'],item['bytes'])
    (output/'README.txt').write_text(
        'Native Workbench '+new['version']+' application update\n\n'
        'This update requires application '+old['version']+'. Close all Workbench windows.\n'
        'Extract this complete ZIP outside your Workbench folder. Run UpdateWorkbench.exe\n'
        'and choose the existing native-workbench folder. Open NativeWorkbench.exe after success.\n\n'
        'The update changes application files only. Installed tool packs, results, saved\n'
        'settings, previous source archives, evidence and unrelated files are retained.\n'
        'Optional packs do not have to match a bundled full distribution.\n'
        'Every replacement is staged and checked. The core manifest commits last; backups\n'
        'and an update report remain in updates/. Errors trigger rollback of changed files.\n'
        'A forced power loss is not an atomic filesystem transaction; retain the backups\n'
        'and report if an update is interrupted. The updater includes its own private Python,\n'
        'so the installed application runtime can also be updated. No system Python or\n'
        'administrator rights are used. Application LICENSE, Python notices and native\n'
        'runtime notices under runtime/licenses/native accompany this updater.\n',encoding='utf-8')
    bundled=[{'path':p.relative_to(output).as_posix(),'bytes':p.stat().st_size,'sha256':sha(p)}
             for p in sorted(output.rglob('*')) if p.is_file()]
    (output/'update-inventory.json').write_text(json.dumps({'schema':1,'files':bundled},indent=2)+'\n',encoding='utf-8')
    return {'base_version':old['version'],'target_version':new['version'],'migration':migration,
            'replacement_files':len(operations),'obsolete_files':len(recipe['obsolete']),
            'blob_bytes':sum(p.stat().st_size for p in (update/'blobs').iterdir()),'packs_changed':False}


def archive(folder,output):
    output=Path(output);require(not output.exists(),'Update ZIP already exists')
    partial=output.with_name(output.name+'.partial');require(not partial.exists(),'Partial update ZIP already exists')
    with zipfile.ZipFile(partial,'x',zipfile.ZIP_DEFLATED,compresslevel=6,allowZip64=True) as zipped:
        for path in sorted(Path(folder).rglob('*')):
            if path.is_file():
                require(not path.is_symlink(),'Updater contains a symbolic file')
                zipped.write(path,path.relative_to(folder).as_posix())
    with zipfile.ZipFile(partial) as zipped:require(zipped.testzip() is None,'Update ZIP CRC failure')
    partial.replace(output)
    return {'path':str(output),'bytes':output.stat().st_size,'sha256':sha(output)}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-root',type=Path,required=True)
    parser.add_argument('--app-root',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True,help='New updater staging folder')
    parser.add_argument('--launcher',type=Path,default=SOURCE/'build/desktop/UpdateWorkbench.exe')
    parser.add_argument('--zip',type=Path)
    args=parser.parse_args();result=make(args.base_root,args.app_root,args.output,args.launcher)
    if args.zip:result['archive']=archive(args.output,args.zip)
    print(json.dumps(result,indent=2))


if __name__=='__main__':main()
