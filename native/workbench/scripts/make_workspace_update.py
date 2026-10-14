#!/usr/bin/env python3
"""Build an exact, portable 0.4.1-to-0.5 workspace update without tool downloads.

The source archive is reconstructed from raw old-ZIP ranges and content-addressed
blobs, so the installed result does not depend on the receiving Python/zlib build.
The generator never changes its input release. An original 0.4.0 installation is
first upgraded by the preserved, hash-checked 0.4.1 fastp updater.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import shutil
import struct
import tempfile
import zipfile

SOURCE_ZIP = 'source/native-workbench-source.zip'


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha_bytes(data):
    return hashlib.sha256(data).hexdigest()


def sha_file(path):
    digest=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda:stream.read(1024*1024),b''):
            digest.update(block)
    return digest.hexdigest()


def safe_name(name):
    require(isinstance(name,str) and name and '\\' not in name and ':' not in name,
            'Invalid relative path')
    path=Path(name)
    require(not path.is_absolute() and not any(p in ('','.', '..') for p in name.split('/')), 'Unsafe relative path')
    return name


def file_table(manifest):
    table={}
    for entry in manifest['files']:
        name=safe_name(entry['path'])
        require(name not in table, 'Duplicate manifest path')
        require(isinstance(entry['bytes'],int) and entry['bytes']>=0 and len(entry['sha256'])==64,'Invalid manifest record')
        table[name]=entry
    return table


class Blobs:
    def __init__(self, root):
        self.root=root
        self.root.mkdir(parents=True)
        self.bytes=0
        self.count=0
    def add(self, data):
        identity=sha_bytes(data)
        path=self.root/identity
        if not path.exists():
            path.write_bytes(data)
            self.bytes+=len(data)
            self.count+=1
        return identity
    def file(self,path):
        return self.add(Path(path).read_bytes())


def zip_members(path):
    """Content hashes plus raw compressed offsets, without assuming compression."""
    result={}
    with zipfile.ZipFile(path) as archive,Path(path).open('rb') as stream:
        require(not archive.comment, 'Archive comments are unsupported by this release recipe')
        for info in archive.infolist():
            require(not info.is_dir(), 'Source release should contain files, not directory records')
            safe_name(info.filename)
            require(info.filename not in result,'Duplicate ZIP member')
            require(not info.flag_bits&1,'Encrypted ZIP members are not supported')
            require((info.external_attr>>16)&0o170000 != 0o120000,'Symbolic ZIP member')
            stream.seek(info.header_offset)
            header=stream.read(30)
            require(len(header)==30 and header[:4]==b'PK\x03\x04','Invalid ZIP local header')
            fields=struct.unpack('<4s5H3I2H',header)
            offset=info.header_offset+30+fields[-2]+fields[-1]
            require(offset+info.compress_size <= archive.start_dir,'ZIP member overlaps central directory')
            stream.seek(offset)
            compressed=stream.read(info.compress_size)
            require(len(compressed)==info.compress_size,'Truncated compressed ZIP member')
            content=hashlib.sha256()
            with archive.open(info) as member:
                for block in iter(lambda:member.read(1024*1024),b''): content.update(block)
            result[info.filename]={'info':info,'offset':offset,'length':info.compress_size,
                'sha256':content.hexdigest(),'compressedSha256':sha_bytes(compressed)}
        return result,archive.start_dir


def source_recipe(base_path,target_path,blobs,verify_output):
    old,_=zip_members(base_path)
    desired,central_start=zip_members(target_path)
    compressed_lookup={}
    for member in old.values():
        compressed_lookup.setdefault((member['compressedSha256'],member['length']),member)
    pieces=[]
    members=[]
    position=0
    reused_bytes=0
    with Path(target_path).open('rb') as target:
        def literal(start,length):
            if not length:return
            target.seek(start)
            data=target.read(length)
            require(len(data)==length,'Truncated source ZIP')
            identity=blobs.add(data)
            pieces.append({'kind':'blob','blob':identity,'length':length,'sha256':identity})
        for name,member in desired.items():
            info=member['info']
            require(info.header_offset>=position,'Source ZIP members are not in physical order')
            # Headers, any data descriptors, and inter-member bytes are target-exact.
            literal(position,member['offset']-position)
            prior=compressed_lookup.get((member['compressedSha256'],member['length']))
            if prior and member['length']:
                pieces.append({'kind':'base','offset':prior['offset'],'length':member['length'],'sha256':member['compressedSha256']})
                reused_bytes+=member['length']
            else:
                literal(member['offset'],member['length'])
            position=member['offset']+member['length']
            members.append({'name':name,'sha256':member['sha256'],'bytes':info.file_size,
                'date_time':list(info.date_time),'external_attr':info.external_attr,
                'compress_type':info.compress_type,'create_system':info.create_system,
                'create_version':info.create_version,'extract_version':info.extract_version,
                'flag_bits':info.flag_bits,'internal_attr':info.internal_attr,
                'extra_hex':info.extra.hex(),'comment_hex':info.comment.hex()})
        literal(position,Path(target_path).stat().st_size-position)
    recipe={'target':SOURCE_ZIP,'sha256':sha_file(target_path),'bytes':Path(target_path).stat().st_size,
        'base':{'path':SOURCE_ZIP,'sha256':sha_file(base_path),'bytes':Path(base_path).stat().st_size},
        'pieces':pieces,'members':members,'reuse_bytes':reused_bytes}
    # Exercise precisely the decoder contract, including every range hash.
    with Path(base_path).open('rb') as old_stream,Path(verify_output).open('wb') as reconstructed:
        for piece in pieces:
            if piece['kind']=='base':
                old_stream.seek(piece['offset'])
                data=old_stream.read(piece['length'])
            else:data=(blobs.root/piece['blob']).read_bytes()
            require(len(data)==piece['length'] and sha_bytes(data)==piece['sha256'],'Piece failed reconstruction verification')
            reconstructed.write(data)
    require(Path(verify_output).stat().st_size==recipe['bytes'] and sha_file(verify_output)==recipe['sha256'],'Reconstructed source ZIP is not byte-identical')
    with zipfile.ZipFile(verify_output) as archive:
        require(archive.testzip() is None,'Reconstructed source ZIP failed CRC checks')
    return recipe


def make(base_zip,patch_root,target_root,output,work):
    base_zip,patch_root,target_root,output,work=map(lambda p:Path(p).resolve(),(base_zip,patch_root,target_root,output,work))
    require(not output.exists() or (output.is_dir() and all(p.name=='apply_workspace_update.py' for p in output.iterdir())), 'Output already contains generated payload; use a fresh staging directory')
    work.mkdir(parents=True,exist_ok=True)
    target_manifest_bytes=(target_root/'manifest.json').read_bytes()
    target_manifest=json.loads(target_manifest_bytes)
    require(target_manifest.get('version')=='0.5.0','Expected target release 0.5.0')
    target_files=file_table(target_manifest)
    patch_metadata=json.loads((patch_root/'patch-metadata.json').read_text())
    require(patch_metadata.get('patch_id')=='fastp-report-fix-0.4.1','Unexpected patch identity')
    for relative,digest in patch_metadata['files'].items():
        safe_name(relative)
        require(sha_file(patch_root/relative)==digest,'Supplied fastp patch file differs: '+relative)
    patched_manifest_path=patch_root/'files/manifest.json'
    patched_manifest_bytes=patched_manifest_path.read_bytes()
    patched_manifest=json.loads(patched_manifest_bytes)
    require(patched_manifest.get('version')=='0.4.1','Expected patched base 0.4.1')
    baseline=file_table(patched_manifest)
    old_source=work/'original-source.zip'
    with zipfile.ZipFile(base_zip) as archive:
        names=set(archive.namelist())
        require('native-workbench/'+SOURCE_ZIP in names,'Base bundle has no nested source archive')
        raw_manifest=archive.read('native-workbench/manifest.json')
        original_manifest=json.loads(raw_manifest)
        require(original_manifest.get('version')=='0.4.0','Expected original release 0.4.0')
        with archive.open('native-workbench/'+SOURCE_ZIP) as src,old_source.open('wb') as dest:
            shutil.copyfileobj(src,dest,1024*1024)
    require(sha_file(old_source)==baseline[SOURCE_ZIP]['sha256'],'Original source ZIP differs from patched-base manifest')
    output.mkdir(parents=True,exist_ok=True)
    blobs=Blobs(output/'blobs')
    # Keep the original, independently verified updater intact for 0.4.0 users.
    shutil.copytree(patch_root,output/'fastp-report-fix',ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
    by_hash={}
    for name,entry in baseline.items():
        if name != SOURCE_ZIP: by_hash.setdefault((entry['sha256'],entry['bytes']),name)
    operations=[]
    reused=[]
    for name,entry in target_files.items():
        actual=target_root/name
        require(actual.is_file() and not actual.is_symlink() and actual.stat().st_size==entry['bytes'] and sha_file(actual)==entry['sha256'], 'Target no longer matches manifest: '+name)
        if name==SOURCE_ZIP:continue
        if name in baseline and baseline[name]['sha256']==entry['sha256'] and baseline[name]['bytes']==entry['bytes']:
            reused.append(name)
            continue
        base_name=by_hash.get((entry['sha256'],entry['bytes']))
        if base_name:
            source={'kind':'base','path':base_name}
        else:
            source={'kind':'blob','blob':blobs.file(actual)}
        operations.append({'path':name,'sha256':entry['sha256'],'bytes':entry['bytes'],'source':source})
    recipe=source_recipe(old_source,target_root/SOURCE_ZIP,blobs,work/'reconstructed-source.zip')
    manifest_blob=blobs.add(target_manifest_bytes)
    document={'schema_version':1,'name':'Native Workbench workspace update','version':'0.5.0',
        'base_versions':['0.4.0','0.4.1'],'original_base_manifest_sha256':sha_bytes(raw_manifest),
        'patched_base_manifest_sha256':sha_bytes(patched_manifest_bytes),
        'target_manifest':target_manifest,'target_manifest_sha256':sha_bytes(target_manifest_bytes),
        'target_manifest_blob':manifest_blob,'operations':operations,'source_zip':recipe,
        'unchanged_files':reused,'statistics':{'operations':len(operations),'unchanged_files':len(reused),
            'blobs':blobs.count,'blob_bytes':blobs.bytes,'source_zip_reuse_bytes':recipe['reuse_bytes'],
            'source_zip_bytes':recipe['bytes'],'source_zip_exact_reconstruction_verified':True}}
    (output/'update-manifest.json').write_text(json.dumps(document,indent=2)+'\n',encoding='utf-8')
    (work/'update-build-summary.json').write_text(json.dumps(document['statistics'],indent=2)+'\n',encoding='utf-8')
    return document['statistics']


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-zip',type=Path,required=True)
    parser.add_argument('--fastp-patch',type=Path,required=True)
    parser.add_argument('--app-root',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--work',type=Path,required=True)
    args=parser.parse_args()
    print(json.dumps(make(args.base_zip,args.fastp_patch,args.app_root,args.output,args.work),indent=2))


if __name__=='__main__':main()
