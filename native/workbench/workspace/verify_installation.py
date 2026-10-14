"""Verify the local workspace installation without executing analysis tools.

Run with the bundled Python: python.exe -I workspace/verify_installation.py
--app-root <installation>. A new JSON report is written beneath results/.
"""
from __future__ import annotations

import argparse
import ast
from datetime import datetime, timezone
import hashlib
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import re
import struct
import sys
import uuid

# Embedded Python's isolated ._pth does not add a script's directory.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from catalog import CatalogError, _relative, load_catalog, load_pack

FASTP_SHA = '1dc1c0898be5625180d65dd630f426701d5741978a757624695d6bd54c1c4bd4'
FASTP_MANIFESTS = {
    'fastp': '7d18c64a45ebbd78e1d246b660a82d7d1a98166ccfd2c40e3f621cd9fee2a6a6',
    'research-variants': 'c255113ec8391e9f967b28612a7e6052da2d8344327db24fff3eff0f4f3db1f7',
}
SHA = re.compile(r'[0-9a-f]{64}\Z')


class VerificationError(ValueError):
    pass


def require(condition, message):
    if not condition:
        raise VerificationError(message)


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def strict_json(path, limit=32*1024*1024):
    require(path.stat().st_size <= limit, f'{path.name}: JSON exceeds size limit')
    def unique(pairs):
        result = {}
        for key, value in pairs:
            require(key not in result, f'{path.name}: duplicate JSON key {key!r}')
            result[key] = value
        return result
    def bad_constant(value):
        raise VerificationError(f'{path.name}: nonfinite JSON number')
    return json.loads(path.read_text(encoding='utf-8-sig'), object_pairs_hook=unique, parse_constant=bad_constant)


def inside(root, relative):
    require(isinstance(relative, str), 'File path is not text')
    relative = _relative(relative)
    candidate = root.joinpath(*relative.split('/'))
    require(candidate.resolve().is_relative_to(root.resolve()), f'File leaves installation: {relative}')
    require(not any(part.is_symlink() for part in (candidate, *candidate.parents) if part != root.parent), f'File uses symbolic link: {relative}')
    require(candidate.is_file(), f'Missing file: {relative}')
    return candidate


def pe_x64(path):
    with path.open('rb') as stream:
        header = stream.read(64)
        require(len(header) == 64 and header[:2] == b'MZ', f'{path.name}: missing MZ header')
        offset = struct.unpack_from('<I', header, 0x3c)[0]
        require(64 <= offset <= path.stat().st_size-26, f'{path.name}: invalid PE offset')
        stream.seek(offset)
        pe = stream.read(26)
    require(pe[:4] == b'PE\0\0', f'{path.name}: missing PE signature')
    machine = struct.unpack_from('<H', pe, 4)[0]
    magic = struct.unpack_from('<H', pe, 24)[0]
    require(machine == 0x8664 and magic == 0x20b, f'{path.name}: expected x86-64 PE32+')
    return {'machine': 'x86-64', 'format': 'PE32+', 'bytes': path.stat().st_size}


def pe_imports(path):
    """Read PE32+ import names using only the bundled standard library."""
    data = path.read_bytes()
    pe_x64(path)
    pe = struct.unpack_from('<I', data, 0x3c)[0]
    count = struct.unpack_from('<H', data, pe+6)[0]
    optional_size = struct.unpack_from('<H', data, pe+20)[0]
    optional = pe+24
    require(optional_size >= 128, 'Missing PE import directory')
    import_rva, import_size = struct.unpack_from('<II', data, optional+120)
    sections = []
    for index in range(count):
        at = optional+optional_size+index*40
        require(at+40 <= len(data), 'Truncated PE section table')
        virtual_size, virtual_address, raw_size, raw_address = struct.unpack_from('<IIII', data, at+8)
        sections.append((virtual_address, raw_size, raw_address))
    def offset(rva, size=1):
        for address, raw_size, raw in sections:
            if address <= rva and rva-address+size <= raw_size:
                result = raw+rva-address
                require(result+size <= len(data), 'PE data leaves file')
                return result
        raise VerificationError('PE import address leaves mapped sections')
    require(import_rva and import_size >= 20, 'Missing PE imports')
    names = []
    for index in range(min(import_size//20, 1024)):
        at = offset(import_rva+20*index, 20)
        fields = struct.unpack_from('<IIIII', data, at)
        if fields == (0,0,0,0,0):
            return names
        start = offset(fields[3])
        end = data.find(b'\0', start, min(start+512, len(data)))
        require(end > start, 'Invalid PE import library name')
        names.append(data[start:end].decode('ascii').lower())
    raise VerificationError('Unterminated PE import table')


def check_release_manifest(root):
    manifest = strict_json(inside(root, 'manifest.json'))
    require(manifest.get('manifest_includes_itself') is False, 'Manifest must explicitly exclude its own hash')
    require(isinstance(manifest.get('files'), list) and manifest['files'], 'Manifest has no file inventory')
    seen, count, size = set(), 0, 0
    failures = []
    for item in manifest['files']:
        require(isinstance(item, dict) and set(item) >= {'path','bytes','sha256'}, 'Malformed manifest entry')
        relative = item['path']
        key = relative.replace('\\','/').lower() if isinstance(relative,str) else ''
        require(key and key not in seen and key != 'manifest.json', 'Duplicate or self-referencing manifest path')
        seen.add(key)
        require(key.split('/')[0] not in {'results','user-data','updates'}, 'Manifest includes mutable user content')
        if manifest.get('ownership') == 'core':
            require(key.split('/')[0] != 'packs', 'Core inventory must not own independently installed packs')
        require(isinstance(item['bytes'],int) and not isinstance(item['bytes'],bool) and item['bytes'] >= 0, 'Invalid file byte count')
        require(isinstance(item['sha256'],str) and SHA.fullmatch(item['sha256']), 'Invalid file SHA-256')
        try:
            path = inside(root, relative)
            require(path.stat().st_size == item['bytes'], f'File size differs: {relative}')
            require(sha256(path) == item['sha256'], f'File hash differs: {relative}')
            count += 1
            size += item['bytes']
        except (OSError, ValueError) as exc:
            failures.append(str(exc))
    required = {'nativeworkbench.exe','workbenchbridge.exe','workspace/catalog.py','workspace/engine.py','workspace/verify_installation.py'}
    if manifest.get('interface') == 'native-win32':
        required |= {'workspace/desktop_host.py','workspace/desktop_model.py','workspace/service.py'}
        require(manifest.get('requires_browser') is False and manifest.get('transport') == 'anonymous-pipes',
                'Native desktop manifest must declare pipe transport without a browser')
        if manifest.get('ownership') == 'core':
            require(manifest.get('schema_version') == 2 and manifest.get('pack_management') == 'independent',
                    'Core manifest must declare independent pack ownership')
            required |= {'workspace/core_checks.py'}
    else:
        required |= {'workspace/server.py','workspace/web/index.html'}
    require(required <= seen, 'Release manifest does not cover all required workspace components: '+', '.join(sorted(required-seen)))
    require(not failures, '; '.join(failures[:20]) + (f'; {len(failures)-20} more' if len(failures)>20 else ''))
    return {'version':manifest.get('version'),'filesVerified':count,'bytesVerified':size}


def check_packs(root, catalog):
    failures, count, assets, manifests = [], 0, 0, 0
    for installed in catalog['packs']:
        pack_root = root / installed['folder']
        pack = load_pack(pack_root/'pack.ini')
        require(pack['manifestSha256'] == installed['manifestSha256'], 'Pack manifest changed during discovery')
        manifests += 1
        # Match the native runner's closed pack inventory, not just its declared
        # hashes. An undeclared manual/source file would make Windows execution
        # fail even though a Linux command-line adapter could run the binary.
        declared = {'pack.ini','pack-readme.md','pack-readme.txt','readme.txt'}
        declared.update(item['path'].replace('\\','/').lower() for kind in ('tools','assets') for item in pack[kind].values())
        members = list(pack_root.rglob('*'))
        require(len(members) <= 2000, 'Pack exceeds the native 2000-file/folder limit: '+installed['folder'])
        byte_count = 0
        for path in members:
            require(not path.is_symlink() and not (hasattr(path,'is_junction') and path.is_junction()), 'Pack inventory contains a link: '+str(path))
            if not path.is_file():
                continue
            name = path.relative_to(pack_root).as_posix().lower()
            require(name in declared or name.startswith('licenses/'), 'Undeclared file rejected by the native runner: '+installed['folder']+'/'+name)
            byte_count += path.stat().st_size
        require(byte_count <= 1024*1024*1024, 'Pack exceeds the native 1024 MiB limit: '+installed['folder'])
        for kind in ('tools','assets'):
            for item in pack[kind].values():
                try:
                    path = inside(pack_root, item['path'])
                    require(path.stat().st_size <= 512*1024*1024, 'Tool or asset exceeds the native 512 MiB file limit: '+str(path))
                    require(sha256(path) == item['sha256'], f'{installed["folder"]}/{item["path"]}: hash mismatch')
                    count += kind == 'tools'
                    assets += kind == 'assets'
                except (OSError, ValueError) as exc:
                    failures.append(str(exc))
    require(not failures, '; '.join(failures[:20]) + (f'; {len(failures)-20} more' if len(failures)>20 else ''))
    return {'packManifests':manifests,'executablesVerified':count,'assetsVerified':assets}


def check_fastp(root, catalog):
    verified = []
    for pack_id, expected_manifest in FASTP_MANIFESTS.items():
        matches = [p for p in catalog['packs'] if p['id']==pack_id and p['version']=='0.4.1']
        require(len(matches)==1, f'{pack_id} 0.4.1 from the report fix is missing')
        pack = matches[0]
        require(pack['manifestSha256']==expected_manifest, f'{pack_id}: original fixed manifest differs')
        fixed = inside(root, pack['folder']+'/bin/fastp.exe')
        require(sha256(fixed)==FASTP_SHA, f'{pack_id}: fastp report fix has been replaced')
        verified.append(pack['folder'])
    evidence_root = root/'docs'/'fastp-report-fix'
    metadata = strict_json(inside(evidence_root,'patch-metadata.json'))
    require(metadata.get('patch_id')=='fastp-report-fix-0.4.1', 'Wrong fastp patch identity')
    require(metadata['files']['files/fastp.exe']==FASTP_SHA, 'Patch metadata does not identify the fixed executable')
    evidence_names = [name for name in metadata['files'] if name.startswith('evidence/')]
    require(evidence_names, 'No preserved fastp validation evidence')
    for name in evidence_names:
        require(sha256(inside(evidence_root,name))==metadata['files'][name], f'Preserved fastp evidence differs: {name}')
    provenance_path = 'source/vendor-expanded/fastp-provenance.json'
    require(sha256(inside(evidence_root,provenance_path))==metadata['files'][provenance_path], 'Fastp build provenance differs')
    provenance = strict_json(evidence_root/provenance_path)
    require(provenance['outputs']['cosmo']['sha256']==FASTP_SHA, 'Fastp provenance identifies another executable')
    require(any('JSON' in p and 'escap' in p for p in provenance.get('patches',[])), 'Report escaping patch absent from provenance')
    return {'fixedExecutableSha256':FASTP_SHA,'packs':verified,'preservedEvidenceFiles':len(evidence_names),
            'note':'Checks fix identity and preserved evidence; does not repeat native Windows tool execution.'}


class AssetLinks(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links=[]
    def handle_starttag(self, tag, attrs):
        attrs=dict(attrs)
        if tag=='script' and 'src' in attrs: self.links.append(attrs['src'])
        if tag=='link' and 'href' in attrs and not (attrs.get('rel')=='icon' and attrs['href']=='data:,'): self.links.append(attrs['href'])


def check_frontend(root):
    manifest = strict_json(inside(root, 'manifest.json'))
    if manifest.get('interface') == 'native-win32':
        modules = []
        # Inspect all shipped Python modules. Source archives may preserve the old
        # browser implementation; the live desktop installation must not ship it.
        blocked = {'http', 'urllib', 'socket', 'socketserver', 'webbrowser', 'server', 'session'}
        for path in sorted((root/'workspace').glob('*.py')):
            tree = ast.parse(path.read_text(encoding='utf-8'), filename=path.name)
            imports = set()
            full_imports = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    imports.update(alias.name.split('.')[0] for alias in node.names)
                    full_imports.update(alias.name for alias in node.names)
                elif isinstance(node, ast.ImportFrom) and node.module:
                    imports.add(node.module.split('.')[0])
                    full_imports.add(node.module)
                    full_imports.update(node.module+'.'+alias.name for alias in node.names)
                elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                    require(node.func.attr not in {'bind','listen','serve_forever'}, 'Desktop module creates a network listener: '+path.name)
            # Explicit pack and reference providers may retrieve public data.
            # Both remain outbound clients, never listeners or browser hosts.
            permitted = {'http', 'urllib', 'socket'} if path.name in {'pack_manager.py', 'reference_provider.py', 'reference_ncbi.py'} else set()
            if path.name in {'pack_security.py', 'catalog.py', 'reference_manager.py', 'project_manager.py'}:
                require(all(name == 'urllib.parse' or name.startswith('urllib.parse.')
                            for name in full_imports if name == 'urllib' or name.startswith('urllib.')),
                        path.name+' may only import URL parsing, not a network client')
                permitted = {'urllib'}
            if path.name == 'reference_transfer.py':
                # Range orchestration handles a provider response that ends
                # early. It needs this exception class, not an HTTP client.
                for node in ast.walk(tree):
                    if isinstance(node, ast.Import):
                        require(not any(alias.name == 'http' or alias.name.startswith('http.') for alias in node.names),
                                'reference_transfer.py may only import the HTTPException class, not an HTTP client')
                    elif isinstance(node, ast.ImportFrom) and node.module and node.module.split('.')[0] == 'http':
                        require(node.level == 0 and node.module == 'http.client' and len(node.names) == 1 and
                                node.names[0].name == 'HTTPException',
                                'reference_transfer.py may only import the HTTPException class, not an HTTP client')
                permitted = {'http'}
            require(not any(name == 'http.server' or name.startswith('http.server.') for name in full_imports), 'Desktop module imports an HTTP listener: '+path.name)
            require(not (imports & blocked) - permitted, f'Desktop module imports a network/browser component: {path.name}')
            modules.append(path.name)
        require({'desktop_host.py','desktop_model.py','service.py'} <= set(modules), 'Native desktop host modules are missing')
        for obsolete in ('web', 'server.py', 'session.py', 'launch.py'):
            require(not (root/'workspace'/obsolete).exists(), 'Obsolete browser frontend is still installed: '+obsolete)
        return {'interface':'native-win32','transport':'anonymous-pipes','modules':modules,
                'requiresBrowser':False,'note':'Static inventory/import check; does not execute Windows GUI code.'}
    web = root/'workspace'/'web'
    parser = AssetLinks()
    parser.feed(inside(web,'index.html').read_text(encoding='utf-8'))
    require(parser.links,'No frontend scripts or styles were referenced')
    for link in parser.links:
        require(not re.match(r'^[a-z]+:|^//',link,re.I), 'Frontend depends on a remote asset')
        path = link.lstrip('/').removeprefix('static/')
        path = path.split('?',1)[0].split('#',1)[0]
        inside(web,path)
    for name in ('app.js','model.js','dag.js','workspace.css','dag.css'):
        path = inside(web,name)
        require(path.stat().st_size>100, f'Frontend asset is empty: {name}')
    return {'assets':parser.links,'remoteAssets':False}


def check_runtime(root):
    runtime = root/'runtime'/'python'
    results = {}
    for name in ('python.exe','pythonw.exe','python313.dll'):
        results[name]=pe_x64(inside(runtime,name))
    inside(runtime,'python313.zip')
    content=inside(runtime,'python313._pth').read_text(encoding='utf-8-sig')
    entries=[line.strip() for line in content.splitlines() if line.strip() and not line.lstrip().startswith('#')]
    require(entries and 'python313.zip' in entries and '.' in entries, 'Missing isolated Python paths')
    require(all(not entry.startswith('import ') for entry in entries), 'Embedded Python must not import global site packages')
    for entry in entries:
        require(not Path(entry).is_absolute() and ':' not in entry and '\\' not in entry, 'Python search path must be relative and local')
        path=(runtime/entry).resolve()
        require(path.is_relative_to(runtime.resolve()) and path.exists(), 'Python search path leaves private runtime or is missing')
    if os.name=='nt':
        require(sys.flags.isolated==1,'Run the checker with Python -I for isolated imports')
        require(Path(sys.executable).resolve().is_relative_to(runtime.resolve()), 'Checker must use the bundled Python runtime')
    return {'executables':results,'searchPaths':entries,'hostPythonIsolated':bool(sys.flags.isolated)}


def check_native(root):
    # The old all-tools validation EXE couples application checks to optional
    # scientific packs. The bridge is now exercised through installed checks.
    result = {name:pe_x64(inside(root,name)) for name in ('NativeWorkbench.exe','WorkbenchBridge.exe')}
    manifest = strict_json(inside(root,'manifest.json'))
    if manifest.get('interface') == 'native-win32':
        imports = pe_imports(inside(root,'NativeWorkbench.exe'))
        allowed = {'kernel32.dll','user32.dll','gdi32.dll','gdiplus.dll','comctl32.dll','ole32.dll',
                   'oleaut32.dll','shell32.dll','shlwapi.dll','uxtheme.dll','dwmapi.dll','advapi32.dll','bcrypt.dll',
                   'comdlg32.dll','ntdll.dll','ucrtbase.dll','version.dll','imm32.dll'}
        require(imports and all(name in allowed or name.startswith('api-ms-win-crt-') for name in imports),
                'Desktop UI has an unexpected external dependency: '+', '.join(name for name in imports if name not in allowed and not name.startswith('api-ms-win-crt-')))
        result['NativeWorkbench.exe']['importedLibraries'] = imports
        result['NativeWorkbench.exe']['browserRuntimeImported'] = False
    return result


def check_graph(root, catalog):
    from engine import Engine
    # Structural validation belongs to the application and works even with no
    # packs installed. These in-memory descriptors are never installed or run.
    from copy import deepcopy
    from catalog import builtin_report
    synthetic = deepcopy(builtin_report())
    synthetic.update(id='core-check/metrics', packId='core-check', workflowId='metrics')
    synthetic['ports'][0]['min'] = 1
    synthetic['outputs'][0].update(id='statistics', type='metrics')
    synthetic['output'] = synthetic['outputs'][0]
    catalog = {'schema':1, 'packs':[], 'tools':{'core-check/metrics':synthetic, 'builtin/report':builtin_report()}}
    engine=Engine(root,catalog)
    graph={'schema':1,'name':'Installation graph check','sources':[{'id':'input-1','label':'One shared metrics input','type':'metrics','files':{'metrics':'C:\\installation-check\\placeholder.txt'},'sample':'not-saved'}],
           'nodes':[],'nextNode':9,'nextSource':6}
    for identity,tool,inputs in (
        ('step-1','core-check/metrics',{'metrics':['input-1']}),
        ('step-2','core-check/metrics',{'metrics':['input-1']}),
        ('step-3','builtin/report',{'metrics':['step-1::statistics','step-2::statistics']})):
        spec=catalog['tools'][tool]
        graph['nodes'].append({'id':identity,'tool':tool,'inputs':inputs,'params':dict(spec['defaults']),
                              'pin':{'packVersion':spec['packVersion'],'manifestSha256':spec['manifestSha256']}})
    validation=engine.validate(graph,check_files=False)
    require(validation['ok'], 'Graph structure did not validate: '+str(validation.get('errors')))
    order=validation['order']
    require(set(order)=={'step-1','step-2','step-3'} and order[-1]=='step-3','Report did not follow both producer steps')
    ranks=engine.rank_groups(graph)
    require(ranks==[{'rank':1,'nodes':['step-1','step-2']},{'rank':2,'nodes':['step-3']}], 'Independent consumers were not placed at one dependency level')
    result=engine.save_pipeline(graph)
    require(len(result['nodes'])==3 and result['nextNode']==9 and result['nextSource']==6,'Graph persistence lost stable steps or counters')
    require(not result['sources'][0].get('files'),'Saved pipeline retained local file bindings')
    return {'nodes':3,'fanOut':2,'joinInputs':2,'savedWithoutFileBindings':True,'ranks':ranks}


def run_checks(root, event=None, cancel=None, catalog=None):
    report={'format':'native-workbench-installation-checks','version':1,
            'startedUtc':datetime.now(timezone.utc).isoformat(), 'platform':sys.platform,
            'python':sys.version.split()[0], 'nativeAnalysisExecuted':False,'checks':[]}
    event = event or (lambda item: None)
    def check(name,function):
        try:
            if cancel is not None and cancel.is_set():
                raise InterruptedError('Cancelled during installation checks')
            details=function()
            item={'name':name,'status':'PASS','details':details}
        except Exception as exc:
            item={'name':name,'status':'FAIL','message':str(exc) or type(exc).__name__}
        report['checks'].append(item)
        print(item['status']+': '+name+((' — '+item['message']) if item['status']=='FAIL' else ''),flush=True)
        event({'type':'log','message':item['status']+': '+name+((' — '+item['message']) if item['status']=='FAIL' else '')})
    def discover():
        nonlocal catalog
        catalog=load_catalog(root)
        require(not catalog.get('errors'), 'Installed pack discovery failed: '+str(catalog.get('errors')))
        require('builtin/report' in catalog['tools'], 'Built-in reporting operation is missing')
        return {'packs':len(catalog['packs']),'tools':len(catalog['tools']),'schema':catalog['schema']}
    check('Release inventory and SHA-256 hashes',lambda:check_release_manifest(root))
    check('Pack discovery and typed catalogue',discover)
    check('Declared pack executables and assets',lambda:check_packs(root,catalog))
    check('Local frontend assets',lambda:check_frontend(root))
    check('Windows x86-64 desktop and bridge executables',lambda:check_native(root))
    check('Private isolated Python runtime',lambda:check_runtime(root))
    check('Graph branching, joining and persistence',lambda:check_graph(root,catalog))
    report['passed']=sum(c['status']=='PASS' for c in report['checks'])
    report['failed']=len(report['checks'])-report['passed']
    report['completedUtc']=datetime.now(timezone.utc).isoformat()
    report['cancelled']=cancel.is_set() if cancel is not None else False
    report['success']=report['failed']==0 and not report['cancelled']
    return report


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--app-root',type=Path,default=Path(__file__).resolve().parent.parent)
    args=parser.parse_args(argv)
    root=args.app_root.resolve()
    require(root.is_dir(),'Installation folder does not exist')
    results=root/'results'
    results.mkdir(exist_ok=True)
    folder=results/('installation-'+datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')+'-'+uuid.uuid4().hex[:10])
    folder.mkdir()
    report=run_checks(root)
    path=folder/'installation-checks.json'
    path.write_text(json.dumps(report,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
    print(f'\n{report["passed"]} of {len(report["checks"])} checks passed. Report: {path}',flush=True)
    print('These checks inspect application files and installed pack integrity. Use Check installation in the application to run the available pack scientific checks.',flush=True)
    return 0 if report['success'] else 1


if __name__=='__main__':
    try:
        sys.exit(main())
    except Exception as exc:
        print('FAIL: '+str(exc),file=sys.stderr)
        sys.exit(1)
