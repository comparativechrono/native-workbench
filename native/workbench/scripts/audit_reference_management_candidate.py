"""Independent downloaded-archive audit; no native execution or release claim."""
from pathlib import Path, PurePosixPath
import argparse
import configparser
import hashlib
import io
import json
import struct
import subprocess
import sys
import traceback
import zipfile

parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--artifact-dir',type=Path,required=True)
parser.add_argument('--repo',type=Path,required=True)
parser.add_argument('--commit',required=True)
parser.add_argument('--run-id',type=int,required=True)
args=parser.parse_args()
HERE=args.artifact_dir.resolve()
ROOT=args.repo.resolve()
COMMIT=args.commit
if (HERE/'independent-artifact-audit.json').exists():parser.error('Do not overwrite retained audit evidence; use a new audit directory.')
if len(COMMIT)!=40 or any(c not in '0123456789abcdef' for c in COMMIT):parser.error('An exact lowercase full git commit SHA is required.')
INNER=HERE/'unpacked'
report={'schema':1,'runId':args.run_id,'sourceCommit':COMMIT,'scope':'Independent downloaded archive and exact source identity audit only',
        'nativeWindowsExecuted':False,'published':False,'success':False,'checks':[],'failures':[],
        'limits':['Independent pack ZIP not downloaded from the large aggregate artifact; its declaration is checked against the bundled additional pack. Native import gate checks the actual independent ZIP.']}

def sha(raw):return hashlib.sha256(raw).hexdigest()
def require(ok,message):
    if not ok:raise ValueError(message)
def checked(message):report['checks'].append(message)
def verified(raw,entry,size='bytes'):
    require(len(raw)==entry[size] and sha(raw)==entry['sha256'],'Incorrect bytes/hash: '+str(entry.get('path',entry.get('file','member'))))
def archive(path):
    z=zipfile.ZipFile(path);names=z.namelist()
    require(len(names)==len(set(names)),'Duplicate ZIP names')
    require(all(not PurePosixPath(n).is_absolute() and '..' not in PurePosixPath(n).parts and '\\' not in n for n in names),'Unsafe ZIP names')
    require(z.testzip() is None,'ZIP CRC failure')
    return z
def git_blobs(paths):
    requests=''.join(COMMIT+':'+p+'\n' for p in paths).encode()
    raw=subprocess.run(['git','cat-file','--batch'],cwd=ROOT,input=requests,stdout=subprocess.PIPE,stderr=subprocess.PIPE,check=True).stdout
    result={};at=0
    for p in paths:
        end=raw.index(b'\n',at);header=raw[at:end].decode();fields=header.split()
        require(len(fields)==3 and fields[1]=='blob','Missing exact-commit source file: '+p)
        size=int(fields[2]);start=end+1;result[p]=raw[start:start+size];at=start+size+1
    require(at==len(raw),'Malformed git object batch response')
    return result
def ini(raw):
    c=configparser.ConfigParser(interpolation=None,strict=True);c.read_string(raw.decode('utf-8-sig'));return c

try:
    previous_commit='38917349449ce56a45d3e0f4f41b7d2a38621c6d'
    changed_source=subprocess.check_output(['git','diff','--name-only',previous_commit,COMMIT],cwd=ROOT,text=True).splitlines()
    require(not any(p.startswith(('pack-examples/','packs/','publishing/')) or p in ('workspace/setup-profile.json','workspace/catalog-sources.json','scripts/package_reusable_index.py') for p in changed_source),'Published pack/trust/profile or additional pack recipe changed')
    report['previousCandidateSourceComparison']={'sourceCommit':previous_commit,'changedPaths':changed_source,'scientificPackRecipeAndProductionTrustUnchanged':True}
    artifacts=json.loads((HERE/'github-artifacts.json').read_text())
    report['transportArtifacts']=[]
    require(len(artifacts)==4,'Expected exactly four bounded transport artifacts')
    for item in artifacts:
        require(item['workflow_run']['id']==args.run_id and item['workflow_run']['head_sha']==COMMIT,'Artifact belongs to a different run or commit')
        label='source1' if 'part-1' in item['name'] else 'source2' if 'part-2' in item['name'] else 'metadata' if 'metadata' in item['name'] else 'starter'
        path=HERE/(label+'-outer.zip');raw=path.read_bytes()
        require(len(raw)==item['size_in_bytes'] and 'sha256:'+sha(raw)==item['digest'],'GitHub transport integrity mismatch: '+label)
        with archive(path):pass
        report['transportArtifacts'].append({'id':item['id'],'name':item['name'],'bytes':len(raw),'sha256':sha(raw),'zipCrc':'passed'})
    checked('Four downloaded bounded GitHub artifacts match declared sizes/digests and pass ZIP CRC/name checks.')
    transport=json.loads((INNER/'TRANSPORT-VERIFICATION.json').read_text())
    for entry in transport['sourceTransportParts']:verified((INNER/entry['file']).read_bytes(),entry)
    source_path=INNER/transport['sourceArchive']['file'];verified(source_path.read_bytes(),transport['sourceArchive'])
    require(source_path.read_bytes()==b''.join((INNER/p['file']).read_bytes() for p in transport['sourceTransportParts']), 'Source reassembly differs from transport order')
    build=json.loads((INNER/'BUILD-PROVENANCE.json').read_text())
    require(build['sourceCommit']==COMMIT and build['published'] is False and build['updaterBuilt'] is False,'Build identity/publication claims differ')
    by_name={e['file']:e for e in build['archives']}
    starter_path=INNER/'native-workbench-0.15.0-starter-windows.zip'
    verified(starter_path.read_bytes(),by_name[starter_path.name]);verified(source_path.read_bytes(),by_name[source_path.name])
    report['archives']=[dict(by_name[starter_path.name],verified=True),dict(by_name[source_path.name],verified=True),dict(by_name['native-workbench-pack-align-0.4.1.zip'],verified=False)]
    checked('Inner Starter and reassembled source archives match build and independent transport metadata.')
    baseline_path=ROOT.parent/'candidate-audit/accepted-archives/baseline-0.6.0-starter.zip'
    require(sha(baseline_path.read_bytes())=='16fa802304c734b5721d838ff38b7e90ed36ccfc185a22239859cc3762af695a','Recovered baseline changed')
    with archive(source_path) as sources,archive(starter_path) as starter,archive(baseline_path) as baseline:
        prefix='native-workbench/'
        manifest=json.loads(starter.read(prefix+'manifest.json'));old_manifest=json.loads(baseline.read(prefix+'manifest.json'))
        require(manifest['version']=='0.15.0' and manifest['ownership']=='core' and manifest['requires_browser'] is False and manifest['network_listener'] is False,'Incorrect packaged app identity')
        recovery=json.loads(sources.read('SOURCE-RECOVERY.json'))
        inventory=recovery['current_source_files']
        require(recovery['release']=='0.15.0' and len({e['path'] for e in inventory})==len(inventory),'Source inventory identity/uniqueness failure')
        require({n for n in sources.namelist() if n.startswith('current/')}=={e['path'] for e in inventory},'Source inventory omits/duplicates a current file')
        blobs=git_blobs([e['path'][len('current/'):] for e in inventory])
        for entry in inventory:
            raw=sources.read(entry['path']);verified(raw,entry)
            require(raw==blobs[entry['path'][len('current/'):]],'Source differs from exact commit: '+entry['path'])
        legacy=sources.read('legacy/native-workbench-0.5.4-source.zip');verified(legacy,recovery['legacy_source'])
        with archive(io.BytesIO(legacy)):pass
        availability=json.loads(starter.read(prefix+'SOURCE-AVAILABILITY.json'))
        require(availability['sourceArtifact']['sha256']==sha(source_path.read_bytes()),'Runtime source companion pin differs')
        report['source']={'currentFiles':len(inventory),'everyCurrentFileMatchesCommit':True,'legacyBytes':len(legacy),'legacySha256':sha(legacy),'legacyCrc':'passed'}
        checked('All '+str(len(inventory))+' current source files match their inventory and exact git commit; embedded legacy source, CRC and runtime source-companion pin verified.')
        expected={prefix+'manifest.json'}
        for entry in manifest['files']:
            verified(starter.read(prefix+entry['path']),entry);expected.add(prefix+entry['path'])
        require(manifest['starter_packs']==old_manifest['starter_packs']==build['starterPacks'],'Published Starter pin list changed')
        preserved=[];runtime=[]
        for name in baseline.namelist():
            if name.startswith(prefix+'packs/'):
                require(starter.read(name)==baseline.read(name),'Published pack bytes changed: '+name)
                expected.add(name);preserved.append(name)
            if name.startswith(prefix+'runtime/'):
                require(starter.read(name)==baseline.read(name),'Private runtime bytes changed: '+name)
                runtime.append(name)
        require(len(manifest['additional_packs'])==1 and manifest['additional_packs']==build['additionalPacks'],'Unexpected additional pack set')
        additional=manifest['additional_packs'][0]
        require((additional['id'],additional['version'],additional['folder'])==('align','0.4.1','packs/align-0.4.1'),'Wrong candidate pack identity')
        for entry in additional['files']:
            name=prefix+additional['folder']+'/'+entry['path'];verified(starter.read(name),entry,'size');expected.add(name)
        require(set(starter.namelist())==expected,'Uninventoried or missing Starter members')
        require(not any('/user-data/' in n or '/results/' in n for n in starter.namelist()),'User data entered candidate')
        runtime_source=[]
        for name in starter.namelist():
            if name.startswith(prefix+'workspace/') and name.endswith('.py'):
                relative=name[len(prefix):]
                require(starter.read(name)==blobs[relative],'Runtime Python module differs from exact source: '+relative)
                runtime_source.append(relative)
        require({'workspace/file_io.py','workspace/execution_resources.py','workspace/recovery.py','workspace/project_manager.py','workspace/reference_library.py','workspace/reference_transfer.py','workspace/reference_ncbi.py'} <= set(runtime_source),'Final candidate omitted required runtime modules')
        report['packagedAtomicWriteHelper']={'path':'workspace/file_io.py','sha256':sha(starter.read(prefix+'workspace/file_io.py')),'matchesExactSourceCommit':True,'executed':False}
        for filename,expected_sha in (('setup-profile.json','4cad899dcc1f6541f6edecc3ace7d0d4dd5d6103b1b16218fece0c0b68d2a4ba'),('catalog-sources.json','240cef994004c040584d3b8806bb361683693b1e7c0e92c9aedeaddc683fbefc')):
            require(sha(starter.read(prefix+'workspace/'+filename))==expected_sha,'Published setup/trust metadata changed')
        require(len(json.loads(starter.read(prefix+'workspace/setup-profile.json'))['packs'])==32,'Official setup profile lost 32 pins')
        report['starter']={'coreFiles':len(manifest['files']),'totalFiles':len(expected),'preservedPublishedPackFiles':len(preserved),'preservedPrivateRuntimeFiles':len(runtime),'runtimeModulesMatchSource':len(runtime_source),'publishedStarterPins':manifest['starter_packs'],'officialSetupPacks':32,'setupProfileAndTrustUnchanged':True,'containsUserData':False}
        checked('Complete Starter inventory, all published pack files/private runtime files, runtime Python source correspondence and production 32-pack profile/trust preserved.')
        pack_prefix=prefix+'packs/align-0.4.1/'
        pack=ini(starter.read(pack_prefix+'pack.ini'));old_pack=ini(starter.read(prefix+'packs/align-0.4.0/pack.ini'))
        meta=json.loads((INNER/'align-0.4.1-metadata.json').read_text())
        require(meta['minAppVersion']=='0.13.0' and meta['manifestSha256']==additional['manifestSha256']==sha(starter.read(pack_prefix+'pack.ini')),'Candidate pack minimum app or manifest metadata differs')
        for name in old_pack.sections():
            if name!='pack':require(dict(pack[name])==dict(old_pack[name]),'Old workflow/tool command changed in new pack: '+name)
        workflows=[s for s in pack.sections() if s.startswith('workflow:')]
        require(set(workflows)=={'workflow:single-end','workflow:paired-end','workflow:single-end-indexed','workflow:paired-end-indexed','workflow:build-sr-index'},'Unexpected candidate workflows')
        for name in ('minimap2','paircheck'):
            require(starter.read(pack_prefix+'bin/'+name+'.exe')==starter.read(prefix+'packs/align-0.4.0/bin/'+name+'.exe'),'Candidate scientific executable changed')
        for name in baseline.namelist():
            old_prefix=prefix+'packs/align-0.4.0/licenses/'
            if name.startswith(old_prefix):require(starter.read(pack_prefix+'licenses/'+name[len(old_prefix):])==baseline.read(name),'Candidate license/source notice changed')
        for name in ('workbench-schema','workbench-checks','fixture-reads1','fixture-reads2','fixture-reference'):
            asset=pack['asset:'+name];require(sha(starter.read(pack_prefix+asset['path']))==asset['sha256'],'Candidate declared asset mismatch')
        schema=json.loads(starter.read(pack_prefix+'workbench-schema.json'));checks=json.loads(starter.read(pack_prefix+'workbench-checks.json'))
        require(schema['workflows']['build-sr-index']['referenceIndex']['format']=='minimap2-sr-v1','Builder contract missing')
        require(all(schema['workflows'][name]['requiresReferenceIndex']['format']=='minimap2-sr-v1' for name in ('single-end-indexed','paired-end-indexed')),'Consumer contracts missing')
        require(len(checks['checks'])==1 and checks['checks'][0]['workflow']=='paired-end' and checks['checks'][0]['expect'][0]['records']==202 and checks['checks'][0]['expect'][0]['properPairs']==202,'Declared self-check lost scientific assertions')
        report['additionalPack']={'id':'align','version':'0.4.1','minAppVersionDeclared':'0.13.0','manifestSha256':additional['manifestSha256'],'files':len(additional['files']),'toolBinaryBytesUnchanged':True,'legacyOperationsUnchanged':True,'newOperations':['build-sr-index','single-end-indexed','paired-end-indexed'],'declaredInstallationChecks':1,'expectedMappedProperPairRecords':202,'standalonePackZipVerified':False}
        require(by_name['native-workbench-pack-align-0.4.1.zip']['sha256']=='3a08cf061f0b62c5502d1420115db3fcae2b04bf695ad3cfd1c3063de0fafa02','Unchanged additional pack ZIP identity differs from 0.13.0 candidate')
        checked('New align 0.4.1 contracts/assets/self-check verified with unchanged legacy operations, binaries, licenses and exact minimum-app declaration; standalone ZIP verification remains separate.')
        native={}
        for name in ('NativeWorkbench.exe','WorkbenchBridge.exe'):
            raw=starter.read(prefix+name);offset=struct.unpack_from('<I',raw,60)[0]
            require(raw[:2]==b'MZ' and raw[offset:offset+4]==b'PE\0\0','Not a native PE executable: '+name)
            machine=struct.unpack_from('<H',raw,offset+4)[0];require(machine==0x8664,'Not an x64 PE executable')
            native[name]={'bytes':len(raw),'sha256':sha(raw),'machine':'AMD64','executed':False}
        report['nativeExecutables']=native
        checked('Packaged application and bridge are native AMD64 PE files; this inspection does not establish Windows execution.')
    report['success']=True
except Exception as error:
    report['failures'].append({'type':type(error).__name__,'message':str(error),'traceback':traceback.format_exc()})
finally:
    (HERE/'independent-artifact-audit.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'success':report['success'],'checks':len(report['checks']),'failures':report['failures'],'report':str(HERE/'independent-artifact-audit.json')}))
if not report['success']:sys.exit(1)
