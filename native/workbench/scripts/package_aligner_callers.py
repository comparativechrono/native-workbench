#!/usr/bin/env python3
"""Stage the 0.5.3 native aligner/caller release over a frozen 0.5.2 inventory."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sys
import tempfile
import zipfile

import package_desktop as desktop
from apply_desktop_update import inside, inventory, read_json, verify

SOURCE=Path(__file__).resolve().parents[1]
VERSION='0.5.3'
BASE_VERSION='0.5.2'
MAX_PACK_BYTES=512*1024*1024
MAX_PACK_FILE_BYTES=256*1024*1024
MAX_PACK_FILES=2000
LOFREQ_SOURCE_NAME='lofreq-2.1.5-source-subset.tar.gz'
LOFREQ_SOURCE_SHA256='5578d1ac7afd6d6ed8180b5d893322aef2389d58bd82258fabe3821186b8aa9e'
PACKS=('bowtie2','hisat2','lofreq','vardict')
MODULES=(*desktop.RUNTIME_MODULES,'pack_checks.py')
MUTABLE=desktop.MUTABLE|{'node_modules','.git'}
SOURCE_TOP={'baselines','desktop','docs','examples','include','licenses','pack-examples',
            'packs','platform_windows','scripts','src','tests','tools','validation','vendor',
            'vendor-variant','vendor-expanded','variant-build','workspace'}
BUILD_PARTS={'build','build-source','build-linux','build-windows','__pycache__','node_modules'}
BINARY_SUFFIXES={'.exe','.dll','.pyd','.o','.obj','.a','.lib','.so','.class','.jar','.jmod','.pyc','.whl','.tmp','.dbg'}
ARCHIVE_SUFFIXES=('.tar.gz','.tar.bz2','.tar.xz','.tgz','.zip')
BINARY_ACQUISITIONS={
    'vendor-expanded/vardict/strawberry-perl-5.42.3.1-64bit-portable.zip',
    'vendor-expanded/vardict/OpenJDK8U-jre_x64_linux_hotspot_8u504b01.tar.gz',
    'vendor-expanded/vardict/VarDict-1.8.3.zip',
}
GENERATED_VENDOR_PREFIXES=('vendor-expanded/hisat2/fixtures/','vendor-expanded/hisat2/scientific spaces/')


def archive_file(path):return path.name.lower().endswith(ARCHIVE_SUFFIXES)
def linked(path):return path.is_symlink() or (hasattr(path,'is_junction') and path.is_junction())


def separate(base,app):
    desktop.require(not app.is_relative_to(base) and not base.is_relative_to(app),'Baseline and target overlap')


def baseline(base):
    manifest=read_json(base/'manifest.json')
    desktop.require(manifest.get('version')==BASE_VERSION and manifest.get('interface')=='native-win32'
                    and manifest.get('requires_browser') is False,'Expected native '+BASE_VERSION+' baseline')
    table=inventory(manifest)
    for name,item in table.items():verify(inside(base,name),item['sha256'],item['bytes'])
    return manifest,table


def catalog_module():
    location=str(SOURCE/'workspace')
    if location not in sys.path:sys.path.insert(0,location)
    import catalog
    return catalog


def validate_pack(folder):
    """Match native import budgets and require every runtime byte to be declared."""
    desktop.require(folder.is_dir() and not linked(folder),'Pack folder must be ordinary: '+str(folder))
    pack=catalog_module().load_pack(folder/'pack.ini')
    declared={'pack.ini','pack-readme.md','pack-readme.txt','readme.txt'}
    for item in [*pack['tools'].values(),*pack['assets'].values()]:
        path=inside(folder,item['path'])
        verify(path,item['sha256'])
        desktop.require(path.stat().st_size<=MAX_PACK_FILE_BYTES,'Executable/asset exceeds native 256 MiB limit: '+str(path))
        declared.add(item['path'].lower())
    entries=list(folder.rglob('*'))
    desktop.require(len(entries)<=MAX_PACK_FILES,'Pack exceeds native import limit of 2000 files/folders: '+str(folder))
    total=0
    for path in entries:
        desktop.require(not linked(path),'Pack contains a link: '+str(path))
        if not path.is_file():continue
        name=path.relative_to(folder).as_posix().lower()
        desktop.require(name in declared or name.startswith('licenses/'),'Undeclared runtime pack file: '+str(path))
        total+=path.stat().st_size
    desktop.require(total<=MAX_PACK_BYTES,'Pack exceeds native import limit of 512 MiB: '+str(folder))
    return pack


def verify_preserved_packs(base_table,app):
    folders=set()
    for name,item in base_table.items():
        if name.startswith('packs/'):
            folders.add(name.split('/')[1]);verify(inside(app,name),item['sha256'],item['bytes'])
    desktop.require(len(folders)==13,'Expected the complete original 13-pack baseline')
    return sorted(folders)


def stage(base,app,pack_ids=PACKS):
    base,app=Path(base).resolve(),Path(app).resolve();separate(base,app)
    desktop.require(not app.exists(),'Choose a new target directory')
    old,table=baseline(base)
    pack_ids=tuple(pack_ids)
    desktop.require(pack_ids and len(pack_ids)==len(set(pack_ids)),'Choose distinct new pack IDs')
    for identity in pack_ids:
        desktop.require(identity in PACKS,'Unexpected aligner/caller pack: '+identity)
        pack=validate_pack(SOURCE/'packs'/(identity+'-'+VERSION))
        desktop.require((pack['id'],pack['version'])==(identity,VERSION),'Pack folder identity/version differs')
    app.mkdir(parents=True)
    for name in table:
        if name.startswith('source/'):continue
        destination=inside(app,name);destination.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(inside(base,name),destination)
    for name in MODULES:shutil.copy2(SOURCE/'workspace'/name,app/'workspace'/name)
    for name in ('DesktopWorkbench.exe','WorkbenchBridge.exe'):
        source=SOURCE/'build/desktop'/name
        desktop.require(source.is_file(),'Build required native component: '+str(source))
        shutil.copy2(source,app/('NativeWorkbench.exe' if name=='DesktopWorkbench.exe' else name))
    for identity in pack_ids:
        folder=identity+'-'+VERSION
        desktop.require(not (app/'packs'/folder).exists(),'New pack would replace a baseline folder')
        shutil.copytree(SOURCE/'packs'/folder,app/'packs'/folder)
    shutil.copytree(SOURCE/'workspace/release-aligner-callers',app,dirs_exist_ok=True)
    shutil.copy2(SOURCE/'README-0.5.3.txt',app/'docs/BUILD-0.5.3.txt')
    for path in (SOURCE/'validation').glob('*0.5.3*'):
        if path.is_file() and not linked(path):shutil.copy2(path,app/'validation'/path.name)
    preserved=verify_preserved_packs(table,app)
    desktop.verify_fixed_packs(app)
    for forbidden in ('web','server.py','session.py','launch.py'):
        desktop.require(not (app/'workspace'/forbidden).exists(),'Browser runtime entered the release')
    workspace_files={p.name for p in (app/'workspace').iterdir() if p.is_file()}
    desktop.require(workspace_files==set(MODULES),'Runtime Python module inventory differs')
    for cmd in app.glob('*.cmd'):desktop.verify_cmd(cmd)
    catalog=catalog_module().load_catalog(app)
    desktop.require(len(catalog['packs'])==len(preserved)+len(pack_ids),'Unexpected installed pack inventory')
    return catalog


def source_candidate(path):
    relative=path.relative_to(SOURCE);parts=relative.parts
    if parts[:2]==('vendor-expanded','varscan'):return False
    if relative.as_posix() in BINARY_ACQUISITIONS or relative.as_posix().startswith(GENERATED_VENDOR_PREFIXES):return False
    if any(part.startswith('.') for part in parts) or set(parts)&(MUTABLE|BUILD_PARTS) or any(part.startswith('build-') for part in parts[:-1]):return False
    if len(parts)==1:return path.name in {'LICENSE','build_variant.py','variant-protocol.txt','variant-provenance.json'} or path.name.startswith('README') or path.suffix=='.cmd'
    if parts[0] not in SOURCE_TOP:return False
    if path.suffix.lower() in BINARY_SUFFIXES:return False
    if parts[0]=='baselines' and set(parts[1:])&{'bin','data','data-200000','results','results-200000'}:return False
    if parts[0]=='packs' and len(parts)>2 and parts[2] in {'bin','runtime','jre','jdk','perl','python'}:return False
    if parts[:2]==('vendor-expanded','lofreq') and archive_file(path) and path.name!=LOFREQ_SOURCE_NAME:return False
    if parts[0] in {'vendor-expanded','variant-build'}:
        if set(parts[1:])&{'source','sources','src','work','dist','build-source','build-linux','build-windows'}:return False
        # Outside explicitly rebuildable trees, retain uncertain historical
        # code, notices, fixtures and acquisition inputs conservatively.
        if path.is_file():
            with path.open('rb') as source:
                if source.read(4)==b'\x7fELF':return False
    # Binary distribution downloads are reproducible acquisition inputs, not
    # corresponding source. Their pinned provenance/build scripts stay included.
    if archive_file(path) and any(token in path.name.lower() for token in ('windows','win-x86','win32','win64','embed-amd64','cosmocc-','llvm-mingw-','-linux-x86_64.zip','-linux_x86_64.zip')):return False
    return True


def collect_sources(app):
    """Reference exact source archives already distributed under pack licenses."""
    canonical={};runtime=[]
    for path in sorted((app/'packs').glob('*/licenses/**/*')):
        if path.is_file() and archive_file(path):
            desktop.require(not linked(path),'Linked runtime source archive')
            item={'runtime_path':path.relative_to(app).as_posix(),'bytes':path.stat().st_size,'sha256':desktop.sha(path)}
            runtime.append(item);canonical.setdefault((item['sha256'],item['bytes']),item)
    files=[];references=[]
    for path in sorted(SOURCE.rglob('*')):
        if not path.is_file() or not source_candidate(path):continue
        desktop.require(not linked(path),'Linked source file: '+str(path))
        relative=path.relative_to(SOURCE).as_posix()
        if archive_file(path):
            identity=(desktop.sha(path),path.stat().st_size)
            if path.name==LOFREQ_SOURCE_NAME:
                desktop.require(identity[0]==LOFREQ_SOURCE_SHA256,'Filtered LoFreq source archive differs from the reviewed subset')
            if identity in canonical:
                references.append({'source_path':relative,**canonical[identity]});continue
        files.append(path)
    contents={'schema':1,'release':VERSION,'included_files':len(files),
              'runtime_source_archives':runtime,'restore_from_runtime':references,
              'policy':'Application/history/build/test source, patches, provenance and licenses are retained. Compiled executables, bundled runtime copies, generated results and expanded rebuildable vendor/build trees are excluded. Exact corresponding-source archives already in shipped packs/licenses are referenced by SHA-256 and can be restored with scripts/restore_source_archives.py. Locally patched source must be represented by retained patches/build scripts or a complete corresponding-source archive.'}
    return files,contents


def source_archive(base,app):
    files,contents=collect_sources(app)
    source=app/'source/native-workbench-source.zip';source.parent.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='source-053-',dir=app.parent) as temporary:
        temporary=Path(temporary);raw=temporary/'source.zip'
        desktop.archive(raw,files,SOURCE)
        with zipfile.ZipFile(raw,'a',compression=zipfile.ZIP_DEFLATED,compresslevel=6) as archive:
            info=zipfile.ZipInfo('native-workbench/SOURCE-CONTENTS.json',(2026,10,3,0,0,0));info.compress_type=zipfile.ZIP_DEFLATED
            archive.writestr(info,json.dumps(contents,indent=2)+'\n')
        from reuse_source_zip import reuse
        reuse(base/'source/native-workbench-source.zip',raw,source)
    with zipfile.ZipFile(source) as archive:
        names=set(archive.namelist())
        for required in ('SOURCE-CONTENTS.json','README-0.5.3.txt','LICENSE','scripts/package_aligner_callers.py',
                         'scripts/restore_source_archives.py','workspace/desktop_host.py','desktop/desktop_workspace.cpp',
                         'tools/build_fastp.py','tools/build_paircheck.py','tools/paircheck.c','tools/build_lofreq.py',
                         'build_variant.py','variant-protocol.txt','variant-provenance.json',
                         'vendor-expanded/freebayes/compat/llrintl.c','vendor-expanded/freebayes/compat/test_llrintl.c',
                         'vendor-expanded/archives/plotly-1.2.0.js','vendor-expanded/archives/plotly-1.2.0.min.js'):
            desktop.require('native-workbench/'+required in names,'Missing source member: '+required)
        desktop.require(archive.testzip() is None,'Source ZIP failed CRC verification')
    (app/'docs/SOURCE-CONTENTS-0.5.3.json').write_text(json.dumps(contents,indent=2)+'\n',encoding='utf-8')
    return source,contents


def finish(base,app,output=None):
    base,app=Path(base).resolve(),Path(app).resolve();separate(base,app)
    desktop.require(app.is_dir(),'Stage the target before finishing')
    _,table=baseline(base);preserved=verify_preserved_packs(table,app)
    catalog=catalog_module().load_catalog(app)
    new=[p for p in catalog['packs'] if p['folder'].split('/')[-1] not in preserved]
    desktop.require(new and all(p['id'] in PACKS and p['version']==VERSION for p in new),'Unexpected new pack set')
    for pack in new:validate_pack(app/pack['folder'])
    source,contents=source_archive(base,app)
    desktop.VERSION=VERSION;files=desktop.write_manifest(app)
    manifest_path=app/'manifest.json';manifest=read_json(manifest_path)
    manifest.update(expansion_packs=[p['id'] for p in new],preserved_packs=preserved,
                    pack_metadata='sha256-pinned-workbench-schema-v1',source_archive_policy='SOURCE-CONTENTS-0.5.3')
    manifest_path.write_text(json.dumps(manifest,indent=2)+'\n',encoding='utf-8')
    result={'version':VERSION,'files':len(files)+1,'preserved_packs':len(preserved),'new_packs':[p['id'] for p in new],
            'source_bytes':source.stat().st_size,'source_sha256':desktop.sha(source),
            'source_archives_referenced':len(contents['restore_from_runtime'])}
    if output:
        output=Path(output).resolve();desktop.require(not output.is_relative_to(app) and not output.is_relative_to(base),'ZIP must be outside both installations')
        output.parent.mkdir(parents=True,exist_ok=True)
        desktop.archive(output,[*files,manifest_path],app)
        result.update(path=str(output),bytes=output.stat().st_size,sha256=desktop.sha(output))
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-root',type=Path,required=True);parser.add_argument('--app-root',type=Path,required=True)
    parser.add_argument('--pack',action='append',choices=PACKS,help='Select each confirmed new pack; defaults to all candidates')
    parser.add_argument('--output',type=Path);parser.add_argument('--stage-only',action='store_true');parser.add_argument('--finish',action='store_true')
    args=parser.parse_args()
    desktop.require(not (args.stage_only and args.finish),'Choose staging or finishing')
    if not args.finish:
        catalog=stage(args.base_root,args.app_root,args.pack or PACKS)
        print(json.dumps({'packs':len(catalog['packs']),'tasks':len(catalog['tools'])}))
    if not args.stage_only:print(json.dumps(finish(args.base_root,args.app_root,args.output),indent=2))


if __name__=='__main__':main()
