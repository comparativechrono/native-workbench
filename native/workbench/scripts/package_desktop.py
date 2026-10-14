#!/usr/bin/env python3
"""Stage and package Native Workbench 0.5.1 as a native desktop application.

Creates a separate installation from the validated 0.5 baseline. Scientific
packs and the exact fastp 0.4.1 correction are retained. Browser-host code is
kept in the source archive as history, not installed as a runtime dependency.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile
import zipfile

SOURCE=Path(__file__).resolve().parents[1]
VERSION='0.5.1'
RUNTIME_MODULES=('catalog.py','engine.py','example.py','desktop_host.py','desktop_model.py','service.py','verify_installation.py')
MUTABLE={'results','user-data','updates','__pycache__'}
BASE_SKIP=MUTABLE|{'workspace','source','manifest.json','workspace-startup-error.txt'}
SOURCE_SKIP={'__pycache__','fastp-build','node_modules','.git','build'}
FIXED_FASTP_SHA='1dc1c0898be5625180d65dd630f426701d5741978a757624695d6bd54c1c4bd4'


def require(condition,message):
    if not condition: raise ValueError(message)


def sha(path):
    digest=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda:stream.read(1024*1024),b''): digest.update(chunk)
    return digest.hexdigest()


def archive(path,files,base,prefix='native-workbench'):
    partial=path.with_name(path.name+'.partial')
    with zipfile.ZipFile(partial,'w',zipfile.ZIP_DEFLATED,compresslevel=6,allowZip64=True) as out:
        for file in sorted(files):
            require(not file.is_symlink(),'Refusing symbolic file: '+str(file))
            info=zipfile.ZipInfo(prefix+'/'+file.relative_to(base).as_posix(),(2026,10,3,0,0,0))
            info.compress_type=zipfile.ZIP_DEFLATED
            info.external_attr=(file.stat().st_mode&0xFFFF)<<16
            with file.open('rb') as src,out.open(info,'w',force_zip64=True) as dest:
                shutil.copyfileobj(src,dest,1024*1024)
    os.replace(partial,path)


def verify_fixed_packs(app):
    for pack in ('fastp-0.4.1','research-variants-0.4.1'):
        require(sha(app/'packs'/pack/'bin/fastp.exe')==FIXED_FASTP_SHA,'Fixed fastp payload differs: '+pack)
    metadata=json.loads((app/'docs/fastp-report-fix/patch-metadata.json').read_text(encoding='utf-8'))
    require(metadata['files']['files/fastp.exe']==FIXED_FASTP_SHA,'Preserved patch identifies a different fastp build')


def copy_baseline(base,app):
    require(base.resolve()!=app.resolve(),'The native package must be separate from its baseline')
    require(not app.resolve().is_relative_to(base.resolve()) and not base.resolve().is_relative_to(app.resolve()),'Baseline and target folders must not overlap')
    require(not app.exists(),'Target staging folder already exists; select a new empty location')
    manifest=json.loads((base/'manifest.json').read_text(encoding='utf-8'))
    require(manifest.get('version')=='0.5.0','Expected a 0.5.0 baseline')
    verify_fixed_packs(base)
    # Copy only release files. Mutable results and settings are never included.
    app.mkdir(parents=True)
    for file in sorted(base.rglob('*')):
        relative=file.relative_to(base)
        if set(relative.parts)&MUTABLE or relative.parts[0] in BASE_SKIP: continue
        if not file.is_file() or file.suffix=='.pyc': continue
        require(not file.is_symlink(),'Baseline contains a symbolic file')
        destination=app/relative
        destination.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(file,destination)


def verify_cmd(path):
    data=path.read_bytes()
    require(b'\\r\\n' not in data and data.endswith(b'\r\n'),'Launcher has escaped or missing CRLF: '+path.name)
    require(b'\n' not in data.replace(b'\r\n',b''),'Launcher has mixed line endings: '+path.name)


def prepare_runtime(base,app):
    required=[SOURCE/'build/desktop/DesktopWorkbench.exe',SOURCE/'build/desktop/WorkbenchBridge.exe']
    required += [SOURCE/'workspace'/name for name in RUNTIME_MODULES]
    required += [SOURCE/'README-0.5.1.txt',SOURCE/'workspace/release-desktop/README.txt']
    for path in required: require(path.is_file(),'Build or create required native component first: '+str(path))
    copy_baseline(base,app)
    require((app/'NativeWorkbenchClassic.exe').is_file(),'Baseline has no retained classic desktop application')
    shutil.copy2(SOURCE/'build/desktop/DesktopWorkbench.exe',app/'NativeWorkbench.exe')
    shutil.copy2(SOURCE/'build/desktop/WorkbenchBridge.exe',app/'WorkbenchBridge.exe')
    workspace=app/'workspace'
    workspace.mkdir()
    for name in RUNTIME_MODULES: shutil.copy2(SOURCE/'workspace'/name,workspace/name)
    release=SOURCE/'workspace/release-desktop'
    shutil.copytree(release,app,dirs_exist_ok=True)
    runtime=app/'runtime/python'
    require((runtime/'python.exe').is_file() and (runtime/'python313.zip').is_file(),'Private Python runtime is missing')
    (runtime/'python313._pth').write_bytes(b'python313.zip\n.\n')
    for forbidden in ('web','server.py','session.py','launch.py'):
        require(not (workspace/forbidden).exists(),'Browser host entered the native runtime')
    for cmd in app.glob('*.cmd'): verify_cmd(cmd)
    evidence=[SOURCE/'validation/native-desktop-0.5.1.json',*sorted((SOURCE/'validation').glob('desktop-0.5.1*'))]
    require(all(p.is_file() for p in evidence),'Native desktop validation evidence is missing')
    (app/'validation').mkdir(exist_ok=True)
    for file in evidence: shutil.copy2(file,app/'validation'/file.name)
    verify_fixed_packs(app)


def build_source_archive(app,base,exclude_relative=()):
    source_zip=app/'source/native-workbench-source.zip'
    source_zip.parent.mkdir(exist_ok=True)
    files=[p for p in SOURCE.rglob('*') if p.is_file()
           and not set(p.relative_to(SOURCE).parts)&SOURCE_SKIP
           and not any(part.startswith('.') for part in p.relative_to(SOURCE).parts)
           and not any(p.relative_to(SOURCE).as_posix().startswith(prefix.rstrip('/')+'/') for prefix in exclude_relative)
           and p.suffix not in ('.pyc','.o','.obj')]
    archive(source_zip,files,SOURCE)
    # Preserve existing compressed member bodies for a compact exact-byte update.
    # The independent helper verifies every decompressed content hash and metadata.
    from reuse_source_zip import reuse
    with tempfile.TemporaryDirectory(prefix='native-source-',dir=app.parent) as temporary:
        optimized=Path(temporary)/source_zip.name
        reuse(base/'source/native-workbench-source.zip',source_zip,optimized)
        os.replace(optimized,source_zip)
    # Retain licenses, build inputs and historical interfaces in source only.
    with zipfile.ZipFile(source_zip) as zipped:
        names=set(zipped.namelist())
        for required in ('README-0.5.1.txt','LICENSE','desktop/desktop_workspace.cpp','workspace/desktop_host.py','workspace/desktop_model.py','workspace/service.py','scripts/package_desktop.py'):
            require('native-workbench/'+required in names,'Source archive missing: '+required)
        require(any(n.startswith('native-workbench/workspace/web/') for n in names),'Historical interface source was omitted')
        require(zipped.testzip() is None,'Source archive failed CRC verification')
    return source_zip


def write_manifest(app):
    files=[p for p in app.rglob('*') if p.is_file() and not set(p.relative_to(app).parts)&MUTABLE
           and not any(part.startswith('.') for part in p.relative_to(app).parts)
           and p!=app/'manifest.json' and p.suffix!='.pyc']
    manifest={'schema_version':1,'version':VERSION,'manifest_includes_itself':False,
        'platform':'windows-x86_64','release_status':'native-desktop-development-build',
        'interface':'native-win32','transport':'anonymous-pipes','requires_browser':False,
        'network_listener':False,'native_windows_integration_tested':False,
        'fastp_patch':'fastp-report-fix-0.4.1',
        'note':'Normal user installation. Pack versions are independent. Results and saved settings are excluded.',
        'files':[{'path':p.relative_to(app).as_posix(),'bytes':p.stat().st_size,'sha256':sha(p)} for p in sorted(files)]}
    (app/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n',encoding='utf-8')
    return files


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-root',type=Path,required=True)
    parser.add_argument('--app-root',type=Path,required=True)
    parser.add_argument('--output',type=Path)
    parser.add_argument('--stage-only',action='store_true',help='Create installation/source/manifest, but no outer release ZIP')
    args=parser.parse_args()
    require(args.stage_only or args.output is not None,'Supply --output, or --stage-only while validating')
    base,app=args.base_root.resolve(),args.app_root.resolve()
    prepare_runtime(base,app)
    source_zip=build_source_archive(app,base)
    files=write_manifest(app)
    result={'version':VERSION,'app_root':str(app),'files':len(files)+1,
            'source_zip_bytes':source_zip.stat().st_size,'source_zip_sha256':sha(source_zip)}
    if not args.stage_only:
        output=args.output.resolve()
        require(not output.is_relative_to(app),'Outer ZIP must be outside the installation')
        output.parent.mkdir(parents=True,exist_ok=True)
        archive(output,[*files,app/'manifest.json'],app)
        result.update(path=str(output),bytes=output.stat().st_size,sha256=sha(output))
    print(json.dumps(result,indent=2))


if __name__=='__main__':main()
