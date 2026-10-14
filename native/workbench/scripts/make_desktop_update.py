#!/usr/bin/env python3
"""Build a compact, exact 0.5.0-to-0.5.1, 0.5.1-to-0.5.2, 0.5.2-to-0.5.3 or 0.5.3-to-0.5.4 update.

Use a target staged by package_desktop.py. It has already preserved matching
baseline compressed source members, allowing a portable raw-range ZIP delta.
No source archive or installation input is modified by this generator.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import zipfile

from make_workspace_update import Blobs, file_table, require, sha_bytes, sha_file, source_recipe, SOURCE_ZIP

SOURCE=Path(__file__).resolve().parents[1]
SUPPORTED_UPDATES={('0.5.0','0.5.1'),('0.5.1','0.5.2'),('0.5.2','0.5.3'),('0.5.3','0.5.4')}


def verify_inventory(root,manifest):
    table=file_table(manifest)
    for name,item in table.items():
        path=root/name
        require(path.is_file() and not path.is_symlink() and path.stat().st_size==item['bytes'] and sha_file(path)==item['sha256'],
                'Installation differs from its manifest: '+str(path))
    return table


def make(base,target,output,work):
    base,target,output,work=map(lambda p:Path(p).resolve(),(base,target,output,work))
    require(base!=target,'Base and target must be separate installations')
    require(not output.exists(),'Update output already exists; choose a new staging directory')
    old_bytes=(base/'manifest.json').read_bytes();old_manifest=json.loads(old_bytes)
    new_bytes=(target/'manifest.json').read_bytes();new_manifest=json.loads(new_bytes)
    base_version,target_version=old_manifest.get('version'),new_manifest.get('version')
    require((base_version,target_version) in SUPPORTED_UPDATES,'Supported exact updates are 0.5.0 to 0.5.1, 0.5.1 to 0.5.2, 0.5.2 to 0.5.3 and 0.5.3 to 0.5.4')
    require(new_manifest.get('interface')=='native-win32' and new_manifest.get('requires_browser') is False,
            'Target is not a native desktop release')
    if base_version!='0.5.0':
        require(old_manifest.get('interface')=='native-win32' and old_manifest.get('requires_browser') is False,
                'The '+base_version+' baseline must be the native desktop release')
    old=verify_inventory(base,old_manifest);new=verify_inventory(target,new_manifest)
    output.mkdir(parents=True);work.mkdir(parents=True,exist_ok=True)
    update=output/'update';update.mkdir()
    blobs=Blobs(update/'blobs')
    hash_sources={}
    for name,item in old.items():
        if name!=SOURCE_ZIP: hash_sources.setdefault((item['sha256'],item['bytes']),name)
    operations=[]
    for name,item in new.items():
        if name==SOURCE_ZIP or old.get(name)==item: continue
        origin=hash_sources.get((item['sha256'],item['bytes']))
        source={'kind':'base','path':origin} if origin else {'kind':'blob','blob':blobs.file(target/name)}
        operations.append({'path':name,'sha256':item['sha256'],'bytes':item['bytes'],'source':source})
    require(old[SOURCE_ZIP]!=new[SOURCE_ZIP],'Target source archive was not updated')
    source=source_recipe(base/SOURCE_ZIP,target/SOURCE_ZIP,blobs,work/'reconstructed-desktop-source.zip')
    obsolete=sorted(set(old)-set(new))
    if base_version=='0.5.0':
        require(all(name.startswith('workspace/') for name in obsolete),'Unexpected removed release file outside the retired workspace: '+str(obsolete))
    manifest_blob=blobs.add(new_bytes)
    recipe={'schema_version':1,'kind':'native-desktop-update','base_version':base_version,'target_version':target_version,
            'base_manifest_sha256':sha_bytes(old_bytes),'target_manifest':new_manifest,
            'target_manifest_sha256':sha_bytes(new_bytes),'target_manifest_blob':manifest_blob,
            'operations':operations,'obsolete':obsolete,'source_zip':source,
            'statistics':{'replacement_files':len(operations),'obsolete_files':len(obsolete),
                'unchanged_files':sum(name in old and old[name]==item for name,item in new.items()),
                'blob_count':blobs.count,'blob_bytes':blobs.bytes,'source_zip_reuse_bytes':source['reuse_bytes'],
                'source_zip_exact_reconstruction_verified':True}}
    (update/'update-manifest.json').write_text(json.dumps(recipe,indent=2)+'\n',encoding='utf-8')
    shutil.copy2(SOURCE/'scripts/apply_desktop_update.py',update/'apply_workspace_update.py')
    launcher=SOURCE/'build/desktop/UpdateWorkbench.exe'
    require(launcher.is_file(),'Build the native update folder picker first')
    shutil.copy2(launcher,output/'UpdateWorkbench.exe')
    code=update/'source';code.mkdir()
    for name in ('apply_desktop_update.py','make_desktop_update.py','make_workspace_update.py','reuse_source_zip.py'):
        shutil.copy2(SOURCE/'scripts'/name,code/name)
    close_step=('Close the old workbench service from Tools & installation.' if base_version=='0.5.0'
                else 'Close every NativeWorkbench window for the installation you will update.')
    retirement=('Historical browser runtime files are backed up and removed; saved user-data\n'
                'and results are retained. ' if base_version=='0.5.0' else
                'Saved user-data, analysis results and unrelated extra files are retained.\n')
    (output/'README.txt').write_text(
        f'Native Workbench {target_version} native desktop update\n\n'
        f'This compact update requires the exact {base_version} installation. For any\n'
        f'other version, use the complete {target_version} distribution. The fastp fix is retained.\n\n'
        f'1. {close_step}\n'
        '2. Extract this complete ZIP into a separate folder.\n'
        '3. Run UpdateWorkbench.exe and select your existing native-workbench folder.\n'
        '4. After success, open NativeWorkbench.exe in that existing installation,\n'
        '   then choose File > Check installation. No command prompt is needed.\n'
        '   The .cmd launchers and extra integrity checker are optional.\n\n'
        'The updater checks the complete original release before replacing files.\n'
        'It holds the same Windows instance mutex as the native application, plus\n'
        'the earlier service lock, and refuses to update an active installation.\n'
        'New pack files and the complete source archive are staged and hash-checked.\n'
        +retirement+
        'The release manifest is committed last. Backups and the update report\n'
        'remain under updates in your workbench folder.\n\n'
        'The resulting interface is native Win32, with anonymous pipes to its private\n'
        'Python runtime. It has no HTTP listener or browser dependency. This is an\n'
        'unsigned development build; institutional application-control approval may\n'
        'be needed for the application, Python runtime and scientific executables.\n'
        'No administrator rights or policy-bypass mechanism are provided.\n',encoding='utf-8')
    (work/'desktop-update-build-summary.json').write_text(json.dumps(recipe['statistics'],indent=2)+'\n',encoding='utf-8')
    return recipe['statistics']


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-root',type=Path,required=True)
    parser.add_argument('--app-root',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True,help='New update staging directory; no ZIP is created here')
    parser.add_argument('--work',type=Path,required=True)
    args=parser.parse_args()
    print(json.dumps(make(args.base_root,args.app_root,args.output,args.work),indent=2))


if __name__=='__main__':main()
