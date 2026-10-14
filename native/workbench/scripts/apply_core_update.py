#!/usr/bin/env python3
"""Apply an independently versioned core update; never own or update tool packs.

The historical updater supplies the already audited Windows instance lock and
path/hash helpers. Its legacy update entry point is not called. This script is
also shipped as update/apply_workspace_update.py for the native folder picker.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import shutil
import sys
import time
import uuid

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
from apply_desktop_update import digest, inside, read_json, require, sha, update_lock, verify

UPDATE = Path(__file__).resolve().parent
CORE_TOP_FILES = {'NativeWorkbench.exe', 'WorkbenchBridge.exe', 'LICENSE', 'README.txt',
                  'start-windows.cmd', 'check-windows.cmd', 'check-workspace-windows.cmd',
                  'SOURCE-AVAILABILITY.json'}
CORE_TREES = {'runtime', 'workspace', 'examples'}
NATIVE_NOTICE_FILES = ('COPYING', 'COPYING.MinGW-w64-runtime.txt', 'COPYING.MinGW-w64.txt',
                       'COPYING.winpthreads.txt', 'LLVM-Apache-2.0-with-exceptions.txt')
VERSION = re.compile(r'(?:0|[1-9][0-9]{0,8})\.(?:0|[1-9][0-9]{0,8})\.(?:0|[1-9][0-9]{0,8})\Z')


def ordinary_root(path):
    path = Path(path).absolute()
    for parent in (path, *path.parents):
        require(not parent.is_symlink() and not (hasattr(parent, 'is_junction') and parent.is_junction()),
                'Update paths must not contain links: '+str(parent))
    require(path.is_dir(), 'Update folder is missing: '+str(path))
    return path.resolve()


def core_path(name):
    require(isinstance(name, str) and name and len(name) <= 240 and '\\' not in name
            and ':' not in name and not name.startswith('/'), 'Unsafe core path')
    parts = name.split('/')
    require(all(p not in ('', '.', '..') and p[-1] not in '. ' and
                not any(c in p for c in '<>"|?*') and all(32 <= ord(c) < 127 for c in p)
                and p.split('.')[0].lower() not in {'con','prn','aux','nul','conin$','conout$',
                     *('com'+str(i) for i in range(1,10)), *('lpt'+str(i) for i in range(1,10))}
                for p in parts), 'Unsafe core path')
    require(name in CORE_TOP_FILES or (len(parts) > 1 and parts[0] in CORE_TREES),
            'The core updater cannot own this path: '+name)
    require(not any(p.startswith('.') or p == '__pycache__' for p in parts), 'Hidden/generated core file')
    require(not (parts[0] == 'workspace' and (parts[1] == 'web' or parts[1] in
                {'server.py', 'session.py', 'launch.py'})), 'Browser runtime is not a core component')
    return name


def core_inventory(manifest):
    require(manifest.get('schema_version') == 2 and manifest.get('ownership') == 'core'
            and manifest.get('pack_management') == 'independent', 'Expected an independent core manifest')
    require(manifest.get('interface') == 'native-win32' and manifest.get('requires_browser') is False
            and manifest.get('transport') == 'anonymous-pipes'
            and manifest.get('manifest_includes_itself') is False, 'Invalid native core metadata')
    require(isinstance(manifest.get('version'), str) and VERSION.fullmatch(manifest['version']), 'Invalid core version')
    require(isinstance(manifest.get('files'), list) and manifest['files'], 'Empty core inventory')
    result, folded = {}, set()
    for item in manifest['files']:
        require(isinstance(item, dict) and set(item) == {'path', 'bytes', 'sha256'}, 'Invalid core inventory entry')
        name = core_path(item['path']); lower = name.lower()
        require(not any(lower == old or lower.startswith(old+'/') or old.startswith(lower+'/') for old in folded),
                'Core file paths collide')
        require(type(item['bytes']) is int and item['bytes'] >= 0, 'Invalid core file size')
        digest(item['sha256']); folded.add(lower); result[name] = item
    require({'NativeWorkbench.exe','WorkbenchBridge.exe','workspace/desktop_host.py'} <= set(result),
            'Required native core components are missing')
    return result


def baseline_inventory(manifest, target):
    if manifest.get('ownership') == 'core':
        return core_inventory(manifest), False
    require(manifest.get('version') == '0.5.4' and manifest.get('interface') == 'native-win32'
            and manifest.get('requires_browser') is False, 'Only 0.5.4 can migrate from a combined release')
    # Import its strict inventory parser, but verify only destinations the new
    # core will own. Installed/removed optional packs never gate core migration.
    from apply_desktop_update import inventory
    old = inventory(manifest)
    return {name: old[name] for name in target if name in old}, True


def _report(path, data):
    temporary = path.with_name(path.name+'.partial')
    with temporary.open('w', encoding='utf-8') as stream:
        json.dump(data, stream, indent=2); stream.write('\n'); stream.flush(); os.fsync(stream.fileno())
    os.replace(temporary, path)


def apply(root, update=UPDATE):
    root, update = ordinary_root(root), ordinary_root(update)
    require(not root.is_relative_to(update) and not update.is_relative_to(root),
            'Extract the updater outside the installation being updated')
    recipe = read_json(inside(update, 'update-manifest.json'))
    require(recipe.get('schema_version') == 1 and recipe.get('kind') == 'native-core-update', 'Unsupported core update')
    for key in ('base_manifest_sha256','target_manifest_sha256','target_manifest_blob'): digest(recipe.get(key))
    manifest_blob = inside(update, 'blobs/'+recipe['target_manifest_blob'])
    verify(manifest_blob, recipe['target_manifest_sha256'])
    target = read_json(manifest_blob); targets = core_inventory(target)
    require(target['version'] == recipe.get('target_version'), 'Target version differs')
    require(VERSION.fullmatch(str(recipe.get('base_version',''))) and
            tuple(map(int, recipe['base_version'].split('.'))) < tuple(map(int, target['version'].split('.'))),
            'Core updates must advance the application version')
    with update_lock(root):
        current_path = inside(root, 'manifest.json')
        if sha(current_path) == recipe['target_manifest_sha256']:
            for name,item in targets.items(): verify(inside(root,name), item['sha256'], item['bytes'])
            return {'status':'already-installed','version':target['version'],'files_verified':len(targets)}
        verify(current_path, recipe['base_manifest_sha256'])
        current = read_json(current_path)
        require(current.get('version') == recipe.get('base_version'), 'This update requires application '+str(recipe.get('base_version')))
        baseline, migrating = baseline_inventory(current, targets)
        for name,item in baseline.items(): verify(inside(root,name), item['sha256'], item['bytes'])
        expected_changed = {name for name,item in targets.items() if baseline.get(name) != item}
        expected_removed = set() if migrating else set(baseline)-set(targets)
        operations, obsolete = recipe.get('operations'), recipe.get('obsolete')
        require(isinstance(operations,list) and isinstance(obsolete,list) and all(isinstance(n,str) for n in obsolete),
                'Invalid update operations')
        require(len(obsolete) == len(set(obsolete)) and set(obsolete) == expected_removed, 'Unexpected removed core files')
        seen = set()
        for operation in operations:
            require(isinstance(operation,dict) and set(operation) == {'path','bytes','sha256','blob'}, 'Invalid replacement')
            name = core_path(operation['path'])
            require(name not in seen and name in expected_changed, 'Unexpected replacement destination')
            require({k:operation[k] for k in ('path','bytes','sha256')} == targets[name], 'Replacement differs from core manifest')
            digest(operation['blob']); seen.add(name)
        require(seen == expected_changed, 'Replacement list is incomplete')
        for name in set(targets)-set(baseline):
            path = inside(root,name)
            if path.exists(): verify(path, targets[name]['sha256'], targets[name]['bytes'])
        stamp = time.strftime('%Y%m%d-%H%M%S')+'-'+uuid.uuid4().hex[:8]
        work = inside(root,'updates/core-'+target['version']+'-'+stamp)
        stage, backup = work/'stage', work/'backup'
        stage.mkdir(parents=True); backup.mkdir()
        report_path = work/'update-result.json'
        installed, saved = [], []
        try:
            for operation in operations:
                payload = inside(update,'blobs/'+operation['blob'])
                verify(payload,operation['sha256'],operation['bytes'])
                path = inside(stage,operation['path']); path.parent.mkdir(parents=True,exist_ok=True)
                shutil.copyfile(payload,path); verify(path,operation['sha256'],operation['bytes'])
            for name,item in targets.items(): verify(inside(stage if name in seen else root,name),item['sha256'],item['bytes'])
            shutil.copyfile(manifest_blob,stage/'manifest.json')
            _report(report_path, {'status':'prepared','migration':migrating,'replacements':sorted(seen),
                                 'obsolete':obsolete,'backup':str(backup)})
            # The manifest commits last. Backups are retained for diagnosis and
            # every successful rename is tracked for exception rollback.
            for name in [*obsolete, *sorted(seen), 'manifest.json']:
                destination, old = inside(root,name), inside(backup,name)
                destination.parent.mkdir(parents=True,exist_ok=True)
                if destination.exists():
                    old.parent.mkdir(parents=True,exist_ok=True)
                    os.replace(destination,old); saved.append(name)
                if name in seen or name == 'manifest.json':
                    os.replace(inside(stage,name),destination); installed.append(name)
            for name,item in targets.items(): verify(inside(root,name),item['sha256'],item['bytes'])
            verify(current_path,recipe['target_manifest_sha256'])
            result = {'status':'installed','version':target['version'],'migration':migrating,
                      'files_verified':len(targets),'removed_files':len(obsolete),'backup':str(backup),
                      'packs_changed':False,'source_and_evidence_preserved':True}
            _report(report_path,result); shutil.rmtree(stage)
            return result
        except Exception as exc:
            errors = []
            for name in reversed(installed):
                try: inside(root,name).unlink(missing_ok=True)
                except OSError as error: errors.append(str(error))
            for name in reversed(saved):
                try:
                    path=inside(root,name); path.parent.mkdir(parents=True,exist_ok=True)
                    os.replace(inside(backup,name),path)
                except OSError as error: errors.append(str(error))
            if not errors:
                try:
                    verify(current_path,recipe['base_manifest_sha256'])
                    for name,item in baseline.items(): verify(inside(root,name),item['sha256'],item['bytes'])
                except (OSError,ValueError) as error: errors.append(str(error))
            _report(report_path,{'status':'failed','error':str(exc),'rollback_errors':errors,'baseline_restored':not errors})
            raise RuntimeError(str(exc)+'\nUpdate report: '+str(report_path)) from exc


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--app-root',type=Path,required=True)
    args=parser.parse_args()
    try:
        print(json.dumps(apply(args.app_root),indent=2),flush=True)
        print('Update complete. Open NativeWorkbench.exe in your Workbench folder.',flush=True)
        return 0
    except Exception as exc:
        print('UPDATE FAILED: '+str(exc),file=sys.stderr,flush=True); return 1


if __name__ == '__main__': raise SystemExit(main())
