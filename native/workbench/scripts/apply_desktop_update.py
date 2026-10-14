"""Apply an exact 0.5.0-to-0.5.1, 0.5.1-to-0.5.2, 0.5.2-to-0.5.3 or 0.5.3-to-0.5.4 desktop update.

The complete baseline is verified first. Every replacement is staged and checked;
manifest-known obsolete files are backed up. The target manifest commits last.
Source ZIP bytes are reconstructed from hashed ranges without recompression.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import ctypes
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import time
import uuid

sys.dont_write_bytecode = True
UPDATE=Path(__file__).resolve().parent
FORBIDDEN=('workspace/web','workspace/server.py','workspace/session.py','workspace/launch.py')
SUPPORTED_UPDATES={('0.5.0','0.5.1'),('0.5.1','0.5.2'),('0.5.2','0.5.3'),('0.5.3','0.5.4')}


def require(condition,message):
    if not condition: raise ValueError(message)


def sha(path):
    digest=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda:stream.read(1024*1024),b''): digest.update(block)
    return digest.hexdigest()


def inside(root,relative):
    require(isinstance(relative,str) and relative and '\\' not in relative and ':' not in relative,'Unsafe update path')
    parts=relative.split('/')
    require(not relative.startswith('/') and all(p not in ('','.','..') for p in parts),'Unsafe update path')
    path=Path(root).joinpath(*parts)
    for parent in (path,*path.parents):
        if parent==Path(root).parent: break
        require(not parent.is_symlink() and not (hasattr(parent,'is_junction') and parent.is_junction()),'Update paths cannot use symbolic links or junctions')
    return path


def digest(value):
    require(isinstance(value,str) and len(value)==64 and all(c in '0123456789abcdef' for c in value),'Invalid SHA-256')
    return value


def verify(path,expected,size=None):
    digest(expected)
    require(path.is_file() and (size is None or (type(size)is int and size>=0 and path.stat().st_size==size)) and sha(path)==expected,
            'File is missing or differs from the required release: '+str(path))


def read_json(path):
    require(path.stat().st_size<=16*1024*1024,'Update metadata exceeds size limit')
    def pairs(items):
        result={}
        for key,value in items:
            require(key not in result,'Duplicate JSON key')
            result[key]=value
        return result
    def bad(value): raise ValueError('Nonfinite JSON value')
    return json.loads(path.read_text(encoding='utf-8'),object_pairs_hook=pairs,parse_constant=bad)


def inventory(manifest):
    require(isinstance(manifest.get('files'),list) and manifest['files'],'Missing release file inventory')
    result={}
    folded=set()
    for item in manifest['files']:
        require(isinstance(item,dict) and set(item)>={'path','sha256','bytes'},'Malformed release inventory')
        name=item['path']
        # Validate without touching filesystem or resolving a user-selected path.
        require(isinstance(name,str) and name and '\\' not in name and ':' not in name and not name.startswith('/')
                and all(p not in ('','.','..') for p in name.split('/')),'Unsafe inventory path')
        require(name.lower() not in folded and name!='manifest.json','Duplicate or self-referencing inventory path')
        require(name.split('/')[0] not in ('results','user-data','updates'),'Mutable content is not an update destination')
        require(type(item['bytes']) is int and item['bytes']>=0,'Invalid file size')
        digest(item['sha256'])
        folded.add(name.lower()); result[name]=item
    return result


def blob(update,identity):
    path=inside(update,'blobs/'+digest(identity))
    verify(path,identity)
    return path


def reconstruct_source(root,stage,update,recipe):
    original=inside(root,recipe['base']['path'])
    verify(original,recipe['base']['sha256'],recipe['base'].get('bytes'))
    target=inside(stage,recipe['target'])
    target.parent.mkdir(parents=True,exist_ok=True)
    require(isinstance(recipe.get('pieces'),list) and len(recipe['pieces'])<=10000,'Invalid ZIP reconstruction recipe')
    total=0
    with original.open('rb') as baseline,target.open('xb') as output:
        for piece in recipe['pieces']:
            length=piece['length']
            require(type(length)is int and length>=0,'Invalid source range length')
            total+=length
            require(total<=recipe['bytes'],'Source reconstruction exceeds declared size')
            if piece['kind']=='base':
                offset=piece['offset']
                require(type(offset)is int and offset>=0 and offset+length<=original.stat().st_size,'Source range outside original ZIP')
                baseline.seek(offset); stream=baseline
            elif piece['kind']=='blob':
                path=blob(update,piece['blob'])
                require(path.stat().st_size==length,'Source blob has unexpected trailing content')
                stream=path.open('rb')
            else: raise ValueError('Unknown source reconstruction operation')
            hashed=hashlib.sha256()
            try:
                left=length
                while left:
                    data=stream.read(min(left,1024*1024))
                    require(data,'Source reconstruction data ended early')
                    output.write(data);hashed.update(data);left-=len(data)
            finally:
                if stream is not baseline: stream.close()
            require(hashed.hexdigest()==digest(piece['sha256']),'Source range SHA-256 mismatch')
        output.flush();os.fsync(output.fileno())
    verify(target,recipe['sha256'],recipe['bytes'])
    return recipe['target']


def windows_kernel32():
    """Typed Win32 calls; handles must never pass through ctypes' default int."""
    from ctypes import wintypes
    kernel32=ctypes.WinDLL('kernel32',use_last_error=True)
    signatures={
        'GetFullPathNameW':([wintypes.LPCWSTR,wintypes.DWORD,wintypes.LPWSTR,ctypes.c_void_p],wintypes.DWORD),
        'CreateFileW':([wintypes.LPCWSTR,wintypes.DWORD,wintypes.DWORD,ctypes.c_void_p,wintypes.DWORD,wintypes.DWORD,wintypes.HANDLE],wintypes.HANDLE),
        'GetFinalPathNameByHandleW':([wintypes.HANDLE,wintypes.LPWSTR,wintypes.DWORD,wintypes.DWORD],wintypes.DWORD),
        'LCMapStringEx':([wintypes.LPCWSTR,wintypes.DWORD,wintypes.LPCWSTR,ctypes.c_int,wintypes.LPWSTR,ctypes.c_int,ctypes.c_void_p,ctypes.c_void_p,ctypes.c_ssize_t],ctypes.c_int),
        'CreateMutexW':([ctypes.c_void_p,wintypes.BOOL,wintypes.LPCWSTR],wintypes.HANDLE),
        'ReleaseMutex':([wintypes.HANDLE],wintypes.BOOL),
        'CloseHandle':([wintypes.HANDLE],wintypes.BOOL),
    }
    for name,(arguments,result) in signatures.items():
        function=getattr(kernel32,name);function.argtypes=arguments;function.restype=result
    return kernel32


def windows_instance_name(root,kernel32):
    """Match desktop_ipc.cpp::instance_digest in the shipped 0.5.1 desktop.

    This must use Windows invariant lowercase, not Python lower/casefold, and
    hash UTF-16LE without a terminator, including supplementary characters.
    """
    path=str(root)
    require(path and '\0' not in path,'Invalid Workbench installation folder')
    size=kernel32.GetFullPathNameW(path,0,None,None)
    require(size,'Cannot resolve the Workbench instance folder')
    buffer=ctypes.create_unicode_buffer(size)
    used=kernel32.GetFullPathNameW(path,size,buffer,None)
    require(used and used<size,'Cannot resolve the Workbench instance folder')
    path=buffer.value
    while len(path)>3 and path[-1:] in ('\\','/'):
        path=path[:-1]
    if path.startswith('\\\\?\\'): native=path
    elif path.startswith('\\\\'): native='\\\\?\\UNC\\'+path[2:]
    else: native='\\\\?\\'+path
    handle=kernel32.CreateFileW(native,0,7,None,3,0x02000000,None)
    if handle not in (None,0,ctypes.c_void_p(-1).value):
        try:
            size=kernel32.GetFinalPathNameByHandleW(handle,None,0,0)
            if size:
                buffer=ctypes.create_unicode_buffer(size+1)
                used=kernel32.GetFinalPathNameByHandleW(handle,buffer,size+1,0)
                if used and used<size+1:path=buffer.value
        finally:kernel32.CloseHandle(handle)
    path=path.replace('/','\\')
    if path.startswith('\\\\?\\UNC\\'):path='\\\\'+path[8:]
    elif path.startswith('\\\\?\\'):path=path[4:]
    while len(path)>3 and path.endswith('\\'):path=path[:-1]
    source_units=len(path.encode('utf-16-le',errors='surrogatepass'))//2
    count=kernel32.LCMapStringEx('',0x00000100,path,source_units,None,0,None,None,0)
    require(count,'Cannot normalize the Workbench instance folder')
    normalized=ctypes.create_unicode_buffer(count)
    used=kernel32.LCMapStringEx('',0x00000100,path,source_units,normalized,count,None,None,0)
    require(used==count,'Cannot normalize the Workbench instance folder')
    encoded=normalized.value.encode('utf-16-le',errors='surrogatepass')
    require(len(encoded)==count*2,'Invalid normalized Workbench instance folder')
    return 'Local\\WorkbenchNativeWorkspace_'+hashlib.sha256(encoded).hexdigest()


@contextmanager
def windows_instance_lock(root,kernel32=None):
    kernel32=kernel32 if kernel32 is not None else windows_kernel32()
    name=windows_instance_name(root,kernel32)
    ctypes.set_last_error(0)
    handle=kernel32.CreateMutexW(None,True,name)
    code=ctypes.get_last_error()
    require(handle,'Cannot acquire the native Workbench instance lock (Windows error '+str(code)+')')
    owned=code!=183  # ERROR_ALREADY_EXISTS, matching the desktop's singleton.
    try:
        require(owned,'Native Workbench is still running, or another update is in progress. Close its window and retry the update.')
        yield
    finally:
        if owned:kernel32.ReleaseMutex(handle)
        kernel32.CloseHandle(handle)


@contextmanager
def native_instance_lock(root):
    if os.name=='nt':
        with windows_instance_lock(root):yield
    else:yield


@contextmanager
def legacy_session_lock(root):
    # Retain the browser host's file lock as well as the native mutex. This also
    # serializes old updaters, and prevents the 0.5.0 service from starting.
    folder=inside(root,'user-data');folder.mkdir(exist_ok=True)
    path=inside(root,'user-data/session.lock')
    stream=path.open('a+b')
    locked=False
    try:
        if stream.tell()==0: stream.write(b'\0');stream.flush()
        stream.seek(0)
        try:
            if os.name=='nt':
                import msvcrt
                msvcrt.locking(stream.fileno(),msvcrt.LK_NBLCK,1)
            else:
                import fcntl
                fcntl.flock(stream.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
            locked=True
        except OSError as exc:
            raise ValueError('The workbench service or another update is still running. Close the native window, or stop the 0.5.0 service using Tools & installation, then retry.') from exc
        yield
    finally:
        if locked:
            stream.seek(0)
            if os.name=='nt':
                import msvcrt
                msvcrt.locking(stream.fileno(),msvcrt.LK_UNLCK,1)
            else:
                import fcntl
                fcntl.flock(stream.fileno(),fcntl.LOCK_UN)
        stream.close()


@contextmanager
def update_lock(root):
    # Hold both identities through verification, staging, commit and rollback.
    # A newly launched native GUI sees our mutex and refuses to start.
    with native_instance_lock(root),legacy_session_lock(root):
        yield


def check_no_browser(root):
    for relative in FORBIDDEN:
        require(not inside(root,relative).exists(),'Obsolete browser component remains: '+relative)


def apply(root,update=UPDATE):
    root,update=Path(root).resolve(),Path(update).resolve()
    recipe=read_json(update/'update-manifest.json')
    require(recipe.get('schema_version')==1 and recipe.get('kind')=='native-desktop-update','Unsupported native desktop updater schema')
    base_version,target_version=recipe.get('base_version'),recipe.get('target_version')
    require((base_version,target_version) in SUPPORTED_UPDATES,'Unsupported update versions')
    manifest_blob=blob(update,recipe['target_manifest_blob'])
    verify(manifest_blob,recipe['target_manifest_sha256'])
    target_manifest=read_json(manifest_blob)
    require(target_manifest==recipe['target_manifest'] and target_manifest.get('version')==target_version
            and target_manifest.get('interface')=='native-win32' and target_manifest.get('requires_browser') is False,
            'Inconsistent native desktop release metadata')
    targets=inventory(target_manifest)
    current=read_json(inside(root,'manifest.json'))
    with update_lock(root):
        if sha(root/'manifest.json')==recipe['target_manifest_sha256']:
            for name,item in targets.items(): verify(inside(root,name),item['sha256'],item['bytes'])
            check_no_browser(root)
            return {'status':'already-installed','version':target_version,'files_verified':len(targets)}
        require(current.get('version')==base_version,'This update requires Native Workbench '+base_version+'. Use the full '+target_version+' bundle for other installations.')
        if base_version!='0.5.0':
            require(current.get('interface')=='native-win32' and current.get('requires_browser') is False,'The '+base_version+' baseline must be the native desktop release')
        verify(root/'manifest.json',recipe['base_manifest_sha256'])
        baseline=inventory(current)
        print('Checking every file in the existing '+base_version+' installation...',flush=True)
        for name,item in baseline.items(): verify(inside(root,name),item['sha256'],item['bytes'])
        operations=recipe['operations'];obsolete=recipe['obsolete']
        require(isinstance(operations,list) and isinstance(obsolete,list),'Missing update operations')
        paths=[o['path'] for o in operations]
        require(len(paths)==len(set(p.lower() for p in paths)),'Duplicate replacement destination')
        require(len(obsolete)==len(set(p.lower() for p in obsolete)),'Duplicate obsolete destination')
        require(set(obsolete)==set(baseline)-set(targets),'Obsolete list must contain exactly removed baseline files')
        for name in obsolete: require(name in baseline and name not in targets,'Refusing to delete an unrecognized file')
        for name in set(targets)-set(baseline):
            if inside(root,name).exists():
                verify(inside(root,name),targets[name]['sha256'],targets[name]['bytes'])
        source_target=recipe['source_zip']['target']
        require(source_target=='source/native-workbench-source.zip' and source_target in targets and source_target not in paths,'Invalid source ZIP destination')
        require(set(paths)|{source_target}=={name for name,item in targets.items() if name not in baseline or item!=baseline[name]},'Replacement list does not match release differences')
        for operation in operations:
            require(operation['path'] in targets and operation['path']!='manifest.json','Unrecognized replacement')
            target=targets[operation['path']]
            require(operation['sha256']==target['sha256'] and operation['bytes']==target['bytes'],'Replacement metadata differs from target manifest')
        # Do not delete user-added content inside the removed historical web folder.
        browser=inside(root,'workspace/web')
        if browser.exists():
            for path in browser.rglob('*'):
                if path.is_file(): require(path.relative_to(root).as_posix() in obsolete,'The historical web folder contains extra files; move them out before updating: '+str(path))
        stamp=time.strftime('%Y%m%d-%H%M%S')+'-'+uuid.uuid4().hex[:8]
        work=inside(root,'updates/native-'+target_version.replace('.','')+'-'+stamp)
        stage,backup=work/'stage',work/'backup'
        stage.mkdir(parents=True);backup.mkdir()
        report_path=work/'update-result.json'
        staged=[];installed=[];saved=[]
        try:
            print('Staging the native desktop and local host...',flush=True)
            for operation in operations:
                source=operation['source']
                if source['kind']=='base':
                    require(source['path'] in baseline,'Copy source is outside the verified baseline inventory')
                    path=inside(root,source['path'])
                elif source['kind']=='blob': path=blob(update,source['blob'])
                else: raise ValueError('Unknown replacement source')
                verify(path,operation['sha256'],operation['bytes'])
                destination=inside(stage,operation['path']);destination.parent.mkdir(parents=True,exist_ok=True)
                shutil.copyfile(path,destination);staged.append(operation['path'])
            print('Reconstructing the complete source archive...',flush=True)
            staged.append(reconstruct_source(root,stage,update,recipe['source_zip']))
            replaced=set(staged)
            for name,item in targets.items(): verify(inside(stage if name in replaced else root,name),item['sha256'],item['bytes'])
            shutil.copyfile(manifest_blob,stage/'manifest.json');staged.append('manifest.json')
            journal={'status':'prepared','base_manifest_sha256':recipe['base_manifest_sha256'],'target_manifest_sha256':recipe['target_manifest_sha256'],
                     'replacements':staged,'obsolete':obsolete,'backup':str(backup)}
            report_path.write_text(json.dumps(journal,indent=2)+'\n',encoding='utf-8')
            print('Installing verified release files'+(' and retiring the historical web interface' if base_version=='0.5.0' else '')+'...',flush=True)
            for relative in [*obsolete,*staged]:
                target=inside(root,relative);old=inside(backup,relative)
                target.parent.mkdir(parents=True,exist_ok=True)
                if target.exists():
                    old.parent.mkdir(parents=True,exist_ok=True);os.replace(target,old);saved.append(relative)
                if relative in replaced or relative=='manifest.json':
                    os.replace(inside(stage,relative),target);installed.append(relative)
            # Only empty historical directories are removed. Unknown content was
            # rejected before any replacement; unrelated user folders are retained.
            if browser.exists():
                for directory in sorted((p for p in browser.rglob('*') if p.is_dir()),key=lambda p:len(p.parts),reverse=True): directory.rmdir()
                browser.rmdir()
            for name,item in targets.items(): verify(inside(root,name),item['sha256'],item['bytes'])
            check_no_browser(root)
            result={'status':'installed','version':target_version,'files_verified':len(targets),'removed_files':len(obsolete),
                    'manifest_sha256':sha(root/'manifest.json'),'backup':str(backup)}
            report_path.write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
            shutil.rmtree(stage)
            return result
        except Exception as exc:
            errors=[]
            for relative in reversed(installed):
                try: inside(root,relative).unlink(missing_ok=True)
                except OSError as error: errors.append(str(error))
            for relative in reversed(saved):
                try:
                    target=inside(root,relative);target.parent.mkdir(parents=True,exist_ok=True)
                    os.replace(inside(backup,relative),target)
                except OSError as error: errors.append(str(error))
            if not errors:
                try:
                    verify(root/'manifest.json',recipe['base_manifest_sha256'])
                    for name,item in baseline.items(): verify(inside(root,name),item['sha256'],item['bytes'])
                except (OSError,ValueError) as error: errors.append(str(error))
            result={'status':'failed','error':str(exc),'rollback_errors':errors,'baseline_restored':not errors,
                    'note':'Only declared release files were changed. Staging and remaining backups are retained for diagnosis.'}
            report_path.write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
            raise RuntimeError(str(exc)+'\nUpdate report: '+str(report_path)) from exc


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--app-root',type=Path,required=True)
    args=parser.parse_args()
    try:
        result=apply(args.app_root)
        print(json.dumps(result,indent=2),flush=True)
        print('Update complete. Open NativeWorkbench.exe directly in your workbench folder.',flush=True)
        return 0
    except Exception as exc:
        print('UPDATE FAILED: '+str(exc),file=sys.stderr,flush=True)
        return 1


if __name__=='__main__': raise SystemExit(main())
