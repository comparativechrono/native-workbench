"""Verified, immutable local reference indexes for explicit pack operations.

The pack still owns every scientific command. Only a declared index-building
operation may reuse this store; ordinary alignment is never rewritten. Receipts
are integrity records, not signatures or a sandbox for trusted pack software.
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import shutil
from contextlib import contextmanager


def _io(path):
    if os.name == 'nt':
        try:
            from .pack_manager import filesystem_path
        except ImportError:
            from pack_manager import filesystem_path
        return filesystem_path(path)
    return Path(path)


def _canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False)


def _check_cancel(cancel):
    if cancel is not None and cancel.is_set():
        raise InterruptedError('Cancelled while preparing a reusable reference index.')


def _ordinary(path, file=False):
    path=Path(path).absolute()
    for item in [path, *path.parents]:
        physical=_io(item)
        if physical.is_symlink() or (hasattr(physical,'is_junction') and physical.is_junction()):
            raise ValueError('Reference indexes must not use symbolic links or junctions.')
    if file and not _io(path).is_file():
        raise ValueError('A reference index file is missing.')
    return path


def _digest(path, cancel=None):
    _ordinary(path, file=True)
    before=_io(path).stat()
    h=hashlib.sha256()
    with _io(path).open('rb') as stream:
        for block in iter(lambda:stream.read(1024*1024),b''):
            _check_cancel(cancel)
            h.update(block)
    after=_io(path).stat()
    if (before.st_size,before.st_mtime_ns)!=(after.st_size,after.st_mtime_ns):
        raise ValueError('A reference index file changed during verification.')
    return {'bytes':after.st_size,'sha256':h.hexdigest()}


def _relative(value):
    if not isinstance(value,str) or not value or len(value)>240 or '\\' in value:
        raise ValueError('Unsafe reference index inventory path.')
    parts=value.split('/')
    reserved={'con','prn','aux','nul','conin$','conout$'}|{f'{p}{n}' for p in ('com','lpt') for n in '123456789¹²³'}
    if any(not p or p in ('.','..') or p[-1] in '. ' or any(c in p for c in ':<>"|?*') or
           any(ord(c)<32 or ord(c)==127 for c in p) or p.split('.')[0].lower() in reserved for p in parts):
        raise ValueError('Unsafe reference index inventory path.')
    return value


def _json(path):
    _ordinary(path,file=True)
    if _io(path).stat().st_size>1024*1024:
        raise ValueError('Reference index receipt exceeds its size limit.')
    def pairs(items):
        result={}
        for key,value in items:
            if key in result:
                raise ValueError('Duplicate reference index receipt field.')
            result[key]=value
        return result
    def invalid(value):
        raise ValueError('Non-finite reference index receipt number.')
    value=json.loads(_io(path).read_text(encoding='utf-8'),object_pairs_hook=pairs,parse_constant=invalid)
    if not isinstance(value,dict):
        raise ValueError('The reference index receipt must be a JSON object.')
    return value


def _write_json(path,value):
    with _io(path).open('x',encoding='utf-8',newline='\n') as stream:
        stream.write(_canonical(value)+'\n')
        stream.flush()
        os.fsync(stream.fileno())


def key_for(identity):
    return hashlib.sha256(_canonical(identity).encode('utf-8')).hexdigest()


def _receipt_files(receipt,key,identity=None):
    if (set(receipt)!={'schema','key','identity','files'} or type(receipt['schema']) is not int or receipt['schema']!=1 or
            not isinstance(receipt['identity'],dict) or receipt['key']!=key or key_for(receipt['identity'])!=key or
            (identity is not None and receipt['identity']!=identity)):
        raise ValueError('The reference index receipt does not match its identity.')
    description=receipt['identity']
    expected={'schema','format','operation','pack','executables','indexTool','parameters','steps','outputs','reference'}
    if (set(description)!=expected or type(description['schema']) is not int or description['schema']!=1 or
            description['format']!='minimap2-sr-v1' or not isinstance(description['pack'],dict) or
            not isinstance(description['executables'],list) or not description['executables'] or
            not isinstance(description['parameters'],dict) or not isinstance(description['steps'],list) or
            not isinstance(description['reference'],dict)):
        raise ValueError('Invalid reference index identity structure.')
    files=receipt['files'];declared=description['outputs']
    if (not isinstance(files,dict) or not files or len(files)>64 or not isinstance(declared,dict) or
            any(not isinstance(value,str) for value in declared.values()) or set(files)!=set(declared.values())):
        raise ValueError('The reference index inventory is incomplete.')
    for relative,entry in files.items():
        _relative(relative)
        if (not isinstance(entry,dict) or set(entry)!={'bytes','sha256'} or type(entry['bytes']) is not int or
                entry['bytes']<=0 or not isinstance(entry['sha256'],str) or not re.fullmatch(r'[0-9a-f]{64}',entry['sha256'])):
            raise ValueError('Invalid reference index inventory entry.')
    return files


def _copy_verified(source,target,expected,cancel):
    _ordinary(source,file=True)
    _ordinary(target)
    _io(target.parent).mkdir(parents=True,exist_ok=True)
    h=hashlib.sha256();size=0;created=False
    try:
        with _io(source).open('rb') as src, _io(target).open('xb') as dst:
            created=True
            for block in iter(lambda:src.read(1024*1024),b''):
                _check_cancel(cancel)
                dst.write(block);h.update(block);size+=len(block)
            dst.flush();os.fsync(dst.fileno())
        if {'bytes':size,'sha256':h.hexdigest()}!=expected or _digest(target,cancel)!=expected:
            raise ValueError('A reference index changed while being copied.')
    except BaseException:
        if created:
            _io(target).unlink(missing_ok=True)
        raise


def _check_mmi(path):
    # This is a bounded signature diagnostic, not a substitute for minimap2's
    # full reader. Exact tool/format compatibility is checked independently.
    with _io(path).open('rb') as stream:
        header=stream.read(24)
    if len(header)<24 or header[:4]!=b'MMI\x02':
        raise ValueError('The index builder did not produce a minimap2 index.')


def make_identity(app_root,node,values,cancel=None):
    tool=node['tool'];contract=tool['referenceIndex']
    port=next(p for p in tool['ports'] if p['id']==contract['referencePort'])
    source=_ordinary(values[port['manifestInputs'][0]],file=True)
    reference=_digest(source,cancel)
    # A cache hit bypasses the bridge, so it must still verify the exact declared
    # executable bytes. The engine separately verifies manifest/schema pins.
    for executable in tool['executables']:
        path=Path(app_root)/tool['packFolder']/_relative(executable['path'])
        if _digest(path,cancel)['sha256']!=executable['sha256']:
            raise ValueError('The reference index executable failed integrity verification.')
    identity={'schema':1,'format':contract['format'],'operation':tool['id'],
              'pack':{k:tool[k] for k in ('packId','packVersion','manifestSha256')},
              'executables':copy.deepcopy(tool['executables']),
              'indexTool':contract['tool'],'parameters':copy.deepcopy(node['params']),
              'steps':copy.deepcopy(tool['steps']),
              'outputs':{key:relative for output in tool['outputs'] for key,relative in output['files'].items()},
              'reference':reference}
    return identity,source


def compatible(tool,receipt):
    """Require producer evidence, the same format, and the exact mapping binary."""
    expected=tool['requiresReferenceIndex']
    if not isinstance(receipt,dict) or not isinstance(receipt.get('identity'),dict):
        raise ValueError('Connect the verified Build short-read reference index output; an arbitrary .mmi file is not supported.')
    identity=receipt['identity']
    own=next((e for e in tool['executables'] if e['id']==expected['tool']),None)
    built=next((e for e in identity.get('executables',[]) if e.get('id')==identity.get('indexTool')),None)
    if (identity.get('format')!=expected['format'] or not own or not built or
            any(own[k]!=built.get(k) for k in ('id','version','sha256')) or
            receipt.get('key')!=key_for(identity)):
        raise ValueError('This reference index is incompatible with the selected indexing format or exact mapping executable.')


class ReferenceIndexStore:
    def __init__(self,app_root):
        self.root=Path(app_root).absolute()/'user-data/reference-indexes/v1'

    def _root(self,create=False):
        _ordinary(self.root)
        if create:
            _io(self.root).mkdir(parents=True,exist_ok=True)
        elif not _io(self.root).exists():
            return False
        if not _io(self.root).is_dir():
            raise ValueError('The reference index store is not a folder.')
        return True

    @contextmanager
    def _locked(self,key,cancel):
        self._root(create=True);_check_cancel(cancel)
        lock=self.root/('.'+key+'.lock')
        _ordinary(lock)
        stream=_io(lock).open('a+b');owned=False
        try:
            if stream.seek(0,2)==0:
                stream.write(b'0');stream.flush()
            stream.seek(0)
            try:
                if os.name=='nt':
                    import msvcrt
                    msvcrt.locking(stream.fileno(),msvcrt.LK_NBLCK,1)
                else:
                    import fcntl
                    fcntl.flock(stream.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
                owned=True
            except OSError as exc:
                raise ValueError('This reference index is already being built or verified by another Workbench process. Try again after that operation finishes.') from exc
            yield
        finally:
            if owned:
                stream.seek(0)
                if os.name=='nt':
                    import msvcrt
                    msvcrt.locking(stream.fileno(),msvcrt.LK_UNLCK,1)
                else:
                    import fcntl
                    fcntl.flock(stream.fileno(),fcntl.LOCK_UN)
            stream.close()
            # Keep the inode/filename. Unlinking it while another process has
            # opened it would allow two different locks for the same index.
            # The OS releases the lease on process death, without PID guessing.

    def verify(self,key,identity=None,cancel=None):
        if not re.fullmatch(r'[0-9a-f]{64}',key):
            raise ValueError('Invalid reference index identity.')
        self._root()
        folder=_ordinary(self.root/key)
        if not _io(folder).is_dir():
            raise ValueError('The complete reference index is missing.')
        receipt=_json(folder/'index.json')
        files=_receipt_files(receipt,key,identity)
        expected={'index.json'}
        for relative,entry in files.items():
            path=folder/'files'/relative
            if _digest(path,cancel)!=entry:
                raise ValueError('The reference index is incomplete or corrupted; its stored file failed integrity verification.')
            _check_mmi(path)
            expected.add('files/'+relative)
        observed=set();count=0
        for path in _io(folder).rglob('*'):
            count+=1
            if count>256:
                raise ValueError('The reference index store has unexpected content.')
            _ordinary(path)
            if path.is_file():
                observed.add(path.relative_to(_io(folder)).as_posix())
        if observed!=expected:
            raise ValueError('The reference index store has undeclared files.')
        return receipt

    def run(self,app_root,node,values,step_folder,run,cancel=None,policy='reuse',expected_reference_sha256=None):
        if policy not in ('reuse','rebuild'):
            raise ValueError('Unknown reference index policy.')
        identity,reference=make_identity(app_root,node,values,cancel)
        if expected_reference_sha256 is not None and identity['reference']['sha256']!=expected_reference_sha256:
            raise ValueError('The reference changed after the frozen input was verified.')
        key=key_for(identity);folder=self.root/key
        with self._locked(key,cancel):
            existing=self.verify(key,identity,cancel) if _io(folder).exists() else None
            if existing is not None and policy=='reuse':
                for relative,entry in existing['files'].items():
                    _copy_verified(folder/'files'/relative,Path(step_folder)/relative,entry,cancel)
                result={'success':True,'folder':str(step_folder),'message':'Verified reference index reused; indexing command was not run.'}
                action='reused';receipt=existing
                if _digest(reference,cancel)!=identity['reference']:
                    raise ValueError('The reference changed while its index was being reused.')
            else:
                result=run()
                if not result.get('success'):
                    return result,None
                actual=_ordinary(result.get('folder',step_folder))
                if not _io(actual).resolve().is_relative_to(_io(step_folder).resolve()):
                    raise ValueError('The index runner returned an output outside its private folder.')
                if _digest(reference,cancel)!=identity['reference']:
                    raise ValueError('The reference changed while its index was being built.')
                inventory={}
                for relative in identity['outputs'].values():
                    path=actual/_relative(relative)
                    _check_mmi(_ordinary(path,file=True))
                    inventory[relative]=_digest(path,cancel)
                receipt={'schema':1,'key':key,'identity':identity,'files':inventory}
                if existing is not None:
                    if existing['files']!=inventory:
                        raise ValueError('Rebuilding the same reference index identity produced different bytes; the previous index was preserved.')
                else:
                    partial=self.root/('.'+key+'.partial-'+secrets.token_hex(8))
                    _io(partial).mkdir()
                    try:
                        for relative,entry in inventory.items():
                            _copy_verified(actual/relative,partial/'files'/relative,entry,cancel)
                        _write_json(partial/'index.json',receipt)
                        _check_cancel(cancel)
                        os.rename(_io(partial),_io(folder))
                    finally:
                        if _io(partial).exists():
                            shutil.rmtree(_io(partial))
                    self.verify(key,identity,cancel)
                action='built'
            evidence={'schema':1,'action':action,'key':key,'identity':copy.deepcopy(identity),
                      'files':copy.deepcopy(receipt['files']),
                      'receiptSha256':_digest(folder/'index.json',cancel)['sha256']}
            _write_json(Path(result.get('folder',step_folder))/'reference-index.json',evidence)
            return result,evidence

    def list(self,limit=256):
        """Read-only bounded inventory; readiness is rechecked in full on use."""
        if type(limit) is not int or not 1<=limit<=256:
            raise ValueError('Invalid reference index list limit.')
        if not self._root():
            return {'schema':1,'entries':[],'truncated':False}
        entries=[];truncated=False
        for path in sorted(_io(self.root).iterdir()):
            if not re.fullmatch(r'[0-9a-f]{64}',path.name):
                continue
            if len(entries)>=limit:
                truncated=True;break
            try:
                _ordinary(path)
                receipt=_json(path/'index.json')
                _receipt_files(receipt,path.name)
                entries.append({'key':path.name,'status':'not_verified','identity':receipt['identity'],
                                'note':'All stored index bytes are verified before reuse.'})
            except (OSError,ValueError,TypeError):
                entries.append({'key':path.name,'status':'invalid','note':'Index receipt is unavailable or invalid.'})
        return {'schema':1,'entries':entries,'truncated':truncated}
