#!/usr/bin/env python3
"""Assemble an offline review/acceptance companion from four exact local ZIPs.

No downloads, application rebuilds, installed-workspace copying, signing or
machine-policy changes occur. A checksum is integrity evidence, not IT approval.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import zipfile

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))

REPOSITORY = Path(__file__).resolve().parents[1]
LOCK_PATH = 'packaging/deployment-0.16.0-lock.json'
BUNDLE_NAME = 'native-workbench-deployment-0.16.0'
ARCHIVE_NAME = 'native-workbench-0.16.0-deployment-toolkit.zip'
MAX_MEMBERS = 20000
MAX_MEMBER_BYTES = 512 * 1024 * 1024
MAX_TOTAL_BYTES = 2 * 1024 * 1024 * 1024
SHA256 = re.compile(r'[0-9a-f]{64}\Z')
COMMIT = re.compile(r'[0-9a-f]{40}\Z')
RESERVED = {'con', 'prn', 'aux', 'nul', 'conin$', 'conout$'} | {
    f'{prefix}{digit}' for prefix in ('com', 'lpt') for digit in '123456789¹²³'}
TOOLKIT_FILES = (
    'scripts/build_deployment_bundle.py', 'scripts/deployment_inventory.py',
    'scripts/deployment_acceptance.py', 'scripts/collect_deployment_signatures.ps1',
    'tests/test_deployment_bundle.py', 'tests/test_deployment_inventory.py',
    'tests/test_deployment_acceptance.py', LOCK_PATH,
    'docs/deployment-acceptance.md', 'docs/institutional-deployment.md',
    'AGENTS.md', 'LICENSE',
)


class BundleError(ValueError):
    pass


def require(condition, message):
    if not condition:
        raise BundleError(message)


def digest(path):
    result = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            result.update(block)
    return result.hexdigest()


def identity(path):
    return {'bytes': path.stat().st_size, 'sha256': digest(path)}


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + '\n', encoding='utf-8')


def strict_json(raw):
    def unique(pairs):
        obj = {}
        for key, value in pairs:
            require(key not in obj, 'Duplicate JSON key: ' + key)
            obj[key] = value
        return obj
    def invalid(value):
        raise BundleError('Nonfinite JSON number: ' + value)
    try:
        return json.loads(raw, object_pairs_hook=unique, parse_constant=invalid)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise BundleError('Malformed JSON: ' + str(exc)) from exc


def relative_path(name):
    require(isinstance(name, str) and name and len(name) <= 2048, 'Invalid archive path')
    require('\\' not in name and not name.startswith('/') and '\x00' not in name,
            'Absolute, backslash or NUL path rejected: ' + repr(name))
    parts = name.split('/')
    for part in parts:
        require(part not in ('', '.', '..') and not part.endswith((' ', '.')),
                'Ambiguous or traversing path rejected: ' + repr(name))
        require(not any(ord(c) < 32 or c in '<>:"|?*' for c in part),
                'Windows-unsafe path rejected: ' + repr(name))
        require(part.split('.')[0].rstrip(' ').casefold() not in RESERVED, 'Device path rejected: ' + repr(name))
    return name


def regular_file(path):
    info = path.lstat()
    require(stat.S_ISREG(info.st_mode) and not (getattr(info, 'st_file_attributes', 0) & 0x400),
            'Expected a regular file without a reparse point: ' + str(path))
    for ancestor in path.parents:
        info = ancestor.lstat()
        require(not stat.S_ISLNK(info.st_mode) and not (getattr(info, 'st_file_attributes', 0) & 0x400),
                'Linked/reparse ancestor rejected: ' + str(ancestor))


@contextmanager
def checked_zip(path, *, max_members=MAX_MEMBERS, max_member_bytes=MAX_MEMBER_BYTES,
                max_total_bytes=MAX_TOTAL_BYTES):
    """Preflight all names/types/declared sizes before reading any member."""
    regular_file(path)
    try:
        archive = zipfile.ZipFile(path)
        with archive:
            members = archive.infolist()
            require(0 < len(members) <= max_members, 'ZIP member count exceeds limit or is empty')
            seen, directories, total = {}, {}, 0
            for member in members:
                require(member.orig_filename == member.filename, 'ZIP member name was truncated')
                directory = member.is_dir()
                name = relative_path(member.filename[:-1] if directory else member.filename)
                key = name.casefold()
                require(key not in seen, 'Duplicate/case-colliding ZIP member: ' + name)
                seen[key] = (name, directory)
                mode = member.external_attr >> 16
                kind = stat.S_IFMT(mode)
                require(kind in (0, stat.S_IFDIR if directory else stat.S_IFREG),
                        'Link or special ZIP member rejected: ' + name)
                require(not (member.external_attr & 0x400), 'Reparse ZIP member rejected: ' + name)
                require(not (member.flag_bits & 1), 'Encrypted ZIP member rejected: ' + name)
                require(member.compress_type in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED),
                        'Unsupported ZIP compression: ' + name)
                require(0 <= member.file_size <= max_member_bytes, 'ZIP member exceeds size limit: ' + name)
                require(not directory or member.file_size == 0, 'ZIP directory contains data: ' + name)
                total += member.file_size
                require(total <= max_total_bytes, 'ZIP expanded size exceeds limit')
                parts = name.split('/')
                for count in range(1, len(parts)):
                    parent = '/'.join(parts[:count])
                    prior = directories.setdefault(parent.casefold(), parent)
                    require(prior == parent, 'Case-colliding ZIP directory: ' + parent)
            for key, (name, directory) in seen.items():
                if key in directories:
                    require(directory and directories[key] == name, 'ZIP file/directory collision: ' + name)
            yield archive
    except (zipfile.BadZipFile, EOFError, RuntimeError, NotImplementedError) as exc:
        raise BundleError('Invalid ZIP: ' + str(exc)) from exc


def extract_zip(path, destination, *, strip_prefix=''):
    require(not destination.exists(), 'Extraction destination already exists: ' + str(destination))
    with checked_zip(path) as archive:
        if strip_prefix:
            require(all(member.filename.startswith(strip_prefix) for member in archive.infolist()),
                    'ZIP root differs from expected ' + strip_prefix)
        destination.mkdir(parents=True)
        for member in archive.infolist():
            name = member.filename.removeprefix(strip_prefix)
            if not name or member.is_dir():
                continue
            output = destination / relative_path(name)
            output.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(member) as source, output.open('xb') as target:
                remaining = member.file_size
                while remaining:
                    data = source.read(min(1024 * 1024, remaining))
                    require(bool(data), 'Truncated ZIP member: ' + member.filename)
                    target.write(data)
                    remaining -= len(data)
                require(not source.read(1), 'ZIP member exceeds declared size: ' + member.filename)
            require(output.stat().st_size == member.file_size, 'Extracted size differs')


def tree_files(root):
    result, seen = [], set()
    for path in sorted(root.rglob('*'), key=lambda item: item.relative_to(root).as_posix()):
        info = path.lstat()
        require(not stat.S_ISLNK(info.st_mode) and not (getattr(info, 'st_file_attributes', 0) & 0x400),
                'Linked/reparse tree entry rejected: ' + str(path))
        name = relative_path(path.relative_to(root).as_posix())
        require(name.casefold() not in seen, 'Case-colliding tree entry: ' + name)
        seen.add(name.casefold())
        if stat.S_ISDIR(info.st_mode):
            continue
        regular_file(path)
        result.append({'path': name, **identity(path)})
    return result


def checked_inventory(root, entries, *, size_key='bytes'):
    require(isinstance(entries, list) and entries, 'Missing file inventory')
    seen = set()
    for item in entries:
        require(isinstance(item, dict), 'Invalid file inventory entry')
        name = relative_path(item.get('path'))
        require(name.casefold() not in seen, 'Duplicate inventory entry: ' + name)
        seen.add(name.casefold())
        require(isinstance(item.get(size_key), int) and not isinstance(item[size_key], bool)
                and item[size_key] >= 0 and isinstance(item.get('sha256'), str)
                and SHA256.fullmatch(item['sha256']), 'Invalid inventory identity: ' + name)
        path = root / name
        regular_file(path)
        require(identity(path) == {'bytes': item[size_key], 'sha256': item['sha256']},
                'Inventory identity differs: ' + name)
    return seen


def load_lock(repository=REPOSITORY):
    path = repository / LOCK_PATH
    regular_file(path)
    lock = strict_json(path.read_bytes())
    require(lock.get('schema') == 1 and lock.get('applicationVersion') == '0.16.0'
            and lock.get('sourceCommit') == 'e855dc4396e0c16ae35f4e840eb9cc734adb4441'
            and lock.get('coreFiles') == 87 and lock.get('sourceFiles') == 748,
            'Unexpected deployment lock/version/source')
    inputs = lock.get('inputArchives')
    require(isinstance(inputs, list) and len(inputs) == 4
            and {row.get('role') for row in inputs} == {'starter', 'updater', 'source', 'baseline'},
            'Expected four distinct release archive roles')
    names = set()
    for row in inputs:
        name = relative_path(row.get('file'))
        require('/' not in name and name.casefold() not in names, 'Invalid/duplicate input archive name')
        names.add(name.casefold())
        require(isinstance(row.get('bytes'), int) and not isinstance(row['bytes'], bool)
                and 0 < row['bytes'] <= MAX_MEMBER_BYTES and SHA256.fullmatch(row.get('sha256', '')),
                'Invalid input archive identity')
        version = '0.11.0' if row['role'] == 'baseline' else '0.16.0'
        require(row.get('url') == 'https://github.com/comparativechrono/workbench/releases/download/app-v'
                + version + '/' + name, 'Unexpected source URL')
    return lock


def verify_inputs(inputs, lock):
    result = {}
    for row in lock['inputArchives']:
        path = inputs / row['file']
        regular_file(path)
        require(identity(path) == {key: row[key] for key in ('bytes', 'sha256')},
                'Release archive hash/size differs: ' + row['file'])
        with checked_zip(path) as archive:
            require(archive.testzip() is None, 'ZIP CRC check failed: ' + row['file'])
        result[row['role']] = path
    return result


def verify_payloads(app, updater, archives, lock):
    manifest = strict_json((app / 'manifest.json').read_bytes())
    require(manifest.get('version') == lock['applicationVersion'] and manifest.get('ownership') == 'core'
            and manifest.get('manifest_includes_itself') is False, 'Starter core identity differs')
    require(len(manifest.get('files', [])) == lock['coreFiles'], 'Core file count differs')
    checked_inventory(app, manifest['files'])
    installed = [{key: value for key, value in row.items() if key != 'files'}
                 for row in manifest.get('starter_packs', []) + manifest.get('additional_packs', [])]
    require(installed == lock['packs'], 'Starter pack versions differ from reviewed selection')
    require({p.name for p in (app / 'packs').iterdir()} == {Path(p['folder']).name for p in lock['packs']},
            'Unexpected installed pack directory')
    # Use the already hash-verified published validators for closed pack inventories.
    previous_path = list(sys.path)
    previous_modules = {name: sys.modules.pop(name, None) for name in ('catalog', 'app_version', 'verify_installation')}
    try:
        sys.path.insert(0, str(app / 'workspace'))
        import catalog
        import verify_installation
        core_check = verify_installation.check_release_manifest(app)
        pack_check = verify_installation.check_packs(app, catalog.load_catalog(app))
        runtime = app / 'runtime/python'
        runtime_files = [row for row in manifest['files'] if row['path'].startswith('runtime/python/')]
        require({row['path'].removeprefix('runtime/python/') for row in runtime_files}
                == {row['path'] for row in tree_files(runtime)}, 'Private Python inventory is incomplete')
        runtime_check = {name: verify_installation.pe_x64(runtime / name)
                         for name in ('python.exe', 'pythonw.exe', 'python313.dll')}
    finally:
        sys.path[:] = previous_path
        for name, old in previous_modules.items():
            sys.modules.pop(name, None)
            if old is not None:
                sys.modules[name] = old
    for pin in lock['packs']:
        require(digest(app / pin['folder'] / 'pack.ini') == pin['manifestSha256'], 'Pack manifest differs')
    additional = manifest.get('additional_packs', [])
    for pin in additional:
        names = checked_inventory(app / pin['folder'], pin['files'], size_key='size')
        require(names == {row['path'].casefold() for row in tree_files(app / pin['folder'])},
                'Additional pack complete inventory differs')
    source_identity = strict_json((app / 'SOURCE-AVAILABILITY.json').read_bytes())['sourceArtifact']
    source_pin = next(row for row in lock['inputArchives'] if row['role'] == 'source')
    require(all(source_identity[key] == source_pin[key] for key in ('file', 'bytes', 'sha256')),
            'Starter source companion differs')
    with checked_zip(archives['source']) as source:
        recovery = strict_json(source.read('SOURCE-RECOVERY.json'))
        entries = recovery['current_source_files']
        require(recovery['release'] == '0.16.0' and len(entries) == lock['sourceFiles'],
                'Source recovery version/count differs')
        names = set()
        packaged_python = {row['path'] for row in manifest['files']
                           if row['path'].startswith('workspace/') and row['path'].endswith('.py')}
        matched_python = set()
        for row in entries:
            name = relative_path(row['path'])
            require(name.startswith('current/') and name not in names, 'Invalid source inventory member')
            names.add(name)
            raw = source.read(name)
            require(len(raw) == row['bytes'] and hashlib.sha256(raw).hexdigest() == row['sha256'],
                    'Source inventory hash differs: ' + name)
            relative = name.removeprefix('current/')
            if relative in packaged_python:
                require((app / relative).read_bytes() == raw, 'Packaged Python differs from source: ' + relative)
                matched_python.add(relative)
        require(matched_python == packaged_python, 'Packaged Python source correspondence is incomplete')
        require(names == {name for name in source.namelist() if name.startswith('current/') and not name.endswith('/')},
                'Source inventory is incomplete')
    update_inventory = strict_json((updater / 'update-inventory.json').read_bytes())
    names = checked_inventory(updater, update_inventory['files'])
    require(names | {'update-inventory.json'} == {row['path'].casefold() for row in tree_files(updater)},
            'Updater closed inventory differs')
    recipe = strict_json((updater / 'update/update-manifest.json').read_bytes())
    require(recipe['kind'] == 'native-core-update' and recipe['base_version'] == '0.11.0'
            and recipe['target_version'] == '0.16.0' and recipe['obsolete'] == [], 'Updater recipe differs')
    require(recipe['target_manifest_sha256'] == digest(app / 'manifest.json'), 'Updater target manifest differs')
    with checked_zip(archives['baseline']) as baseline:
        raw = baseline.read('native-workbench/manifest.json')
        require(hashlib.sha256(raw).hexdigest() == recipe['base_manifest_sha256']
                and strict_json(raw)['version'] == '0.11.0', 'Updater baseline manifest differs')
    for operation in recipe['operations']:
        name = relative_path(operation['path'])
        blob = relative_path(operation['blob'])
        require('/' not in blob and SHA256.fullmatch(blob), 'Invalid update blob')
        expected = {key: operation[key] for key in ('bytes', 'sha256')}
        require(identity(updater / 'update/blobs' / blob) == expected == identity(app / name),
                'Updater blob is not the exact Starter core file: ' + name)
    require(digest(updater / 'update/blobs' / relative_path(recipe['target_manifest_blob']))
            == digest(app / 'manifest.json'), 'Updater manifest blob differs')
    return {'core': core_check, 'packs': pack_check, 'privateRuntime': runtime_check,
            'sourceFiles': len(entries), 'updaterInventoryFiles': len(update_inventory['files']),
            'updateOperations': len(recipe['operations']), 'nativeWindowsExecuted': False,
            'scope': 'Static complete-file/archive identities, PE inspection and source correspondence only.'}


def source_identity(repository, toolkit_commit):
    def git(*args):
        return subprocess.check_output(['git', '-C', str(repository), *args])
    actual = git('rev-parse', 'HEAD').decode('ascii').strip()
    require(COMMIT.fullmatch(actual) and (toolkit_commit is None or toolkit_commit == actual),
            'Toolkit commit must equal this checkout HEAD')
    records = []
    for relative in TOOLKIT_FILES:
        path = repository / relative
        regular_file(path)
        try:
            committed = git('show', actual + ':' + relative)
            blob = git('rev-parse', actual + ':' + relative).decode('ascii').strip()
        except subprocess.CalledProcessError as exc:
            raise BundleError('Included toolkit file is not committed: ' + relative) from exc
        require(path.read_bytes() == committed,
                'Included toolkit file differs from checkout commit: ' + relative)
        records.append({'path': relative, 'gitBlobSha1': blob,
                        'bytes': len(committed), 'sha256': hashlib.sha256(committed).hexdigest()})
    dirty = bool(git('status', '--porcelain', '--untracked-files=normal').strip())
    return actual, dirty, records


def make_zip(root, destination):
    with zipfile.ZipFile(destination, 'x', zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for row in tree_files(root):
            info = zipfile.ZipInfo(BUNDLE_NAME + '/' + row['path'], (1980, 1, 1, 0, 0, 0))
            info.create_system = 3
            info.external_attr = (stat.S_IFREG | 0o644) << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            with (root / row['path']).open('rb') as source, archive.open(info, 'w') as target:
                shutil.copyfileobj(source, target, 1024 * 1024)


def launchers(root):
    for filename, command in [('verify.cmd', 'verify'), ('acceptance.cmd', 'guided'), ('signatures.cmd', 'signatures')]:
        (root / filename).write_bytes((
            '@echo off\r\nsetlocal DisableDelayedExpansion\r\n'
            '"%~dp0native-workbench\\runtime\\python\\python.exe" -I -B '
            '"%~dp0toolkit\\scripts\\deployment_acceptance.py" ' + command +
            ' --bundle-root "%~dp0." %*\r\nset "toolkit_exit=%errorlevel%"\r\n'
            'echo.\r\npause\r\nexit /b %toolkit_exit%\r\n').encode('ascii'))


def inventory_markdown(app, update):
    lines = ['# NativeWorkbench 0.16.0 deployment inventory', '',
             'This inventories the unchanged published Starter and updater. Hashes establish integrity against the reviewed lock; they are not publisher authentication, executable signatures or institutional approval.', '',
             'Only the Starter selection is installed: align 0.4.0 and 0.4.1, bam 0.4.0, variants 0.4.0. The baseline 0.11.0 ZIP is retained only for disposable upgrade acceptance. No optional catalogue packs are downloaded.', '']
    for label, value in [('Starter (native-workbench/)', app), ('Updater (updater/)', update)]:
        lines += ['## ' + label, '', '| Component | Kind | Version |', '| --- | --- | --- |']
        for component in value.get('components', []):
            cells = [str(component.get(key) if component.get(key) is not None else 'Unknown (not declared)').replace('|', '\\|').replace('\n', ' ') for key in ('name', 'kind', 'version')]
            lines.append('| ' + ' | '.join(cells) + ' |')
        lines += ['', f"Files: {len(value['files'])}. Executable/runtime objects: {len(value.get('executables', []))}. Licence files: {len(value.get('licenceFiles', []))}.", '',
                  'See the adjacent JSON for every file hash, executable format/imports, licence paths, source-availability files and unresolved metadata. Direct PE imports are static evidence, not a complete runtime dependency graph or a vulnerability assessment.', '']
        for item in value.get('limitations', []):
            lines.append('- ' + str(item))
        lines.append('')
    lines += ['## Review and acceptance', '',
              'Read toolkit/docs/institutional-deployment.md and toolkit/docs/deployment-acceptance.md. Run verify.cmd before execution. Keep reports outside this immutable bundle. Signature collection records observations without signing, changing security policies or bypassing a block.', '']
    return '\n'.join(lines)


def build(inputs, output, *, repository=REPOSITORY, toolkit_commit=None):
    inputs, output, repository = Path(inputs).absolute(), Path(output).absolute(), Path(repository).absolute()
    require(not output.exists(), 'Output directory already exists; choose a new destination')
    require(output.parent.is_dir(), 'Output parent directory must exist')
    lock = load_lock(repository)
    archives = verify_inputs(inputs, lock)
    commit, dirty, toolkit_sources = source_identity(repository, toolkit_commit)
    for relative in TOOLKIT_FILES:
        regular_file(repository / relative)
    with tempfile.TemporaryDirectory(prefix='.deployment-build-', dir=output.parent) as temporary:
        stage = Path(temporary)
        root = stage / BUNDLE_NAME
        root.mkdir()
        extract_zip(archives['starter'], root / 'native-workbench', strip_prefix='native-workbench/')
        extract_zip(archives['updater'], root / 'updater')
        static_checks = verify_payloads(root / 'native-workbench', root / 'updater', archives, lock)
        (root / 'archives').mkdir()
        for row in lock['inputArchives']:
            shutil.copyfile(archives[row['role']], root / 'archives' / row['file'])
            require(identity(root / 'archives' / row['file']) == {key: row[key] for key in ('bytes', 'sha256')},
                    'Input archive changed while copying')
        expected_toolkit = {row['path']: row for row in toolkit_sources}
        for relative in TOOLKIT_FILES:
            target = root / 'toolkit' / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(repository / relative, target)
            require(identity(target) == {key: expected_toolkit[relative][key] for key in ('bytes', 'sha256')},
                    'Toolkit file changed while copying: ' + relative)
        # Execute the exact committed companion bytes just staged and checked.
        spec = importlib.util.spec_from_file_location('deployment_bundle_inventory', root / 'toolkit/scripts/deployment_inventory.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        app_inventory = module.inventory_tree(root / 'native-workbench', 'starter')
        update_inventory = module.inventory_tree(root / 'updater', 'updater')
        write_json(root / 'inventory/app.json', app_inventory)
        write_json(root / 'inventory/update.json', update_inventory)
        (root / 'inventory/IT-INVENTORY.md').write_text(inventory_markdown(app_inventory, update_inventory), encoding='utf-8')
        (root / 'README.txt').write_text(
            'NativeWorkbench 0.16.0 offline deployment and acceptance companion\n\n'
            'Read toolkit/docs/deployment-acceptance.md before starting.\n'
            'verify.cmd checks the complete immutable bundle. acceptance.cmd guides a\n'
            'local report; signatures.cmd records Windows signature observations.\n'
            'All launchers use the bundled private Python, without a system Python.\n'
            'These interactive launchers pause before closing so failures stay visible.\n'
            'Reports must be written outside this bundle. Native Windows execution is\n'
            'subject to your institution\'s approval; no security policy is bypassed.\n'
            'The unchanged Starter lives in native-workbench/; the unchanged updater\n'
            'lives in updater/. archives/ preserves the four reviewed published ZIPs.\n'
            'The 0.11.0 ZIP is for disposable upgrade testing, not a new installation.\n'
            'See inventory/IT-INVENTORY.md and both JSON inventories for file, licence,\n'
            'runtime and source identities. This companion neither signs executables\n'
            'nor establishes institutional or representative-PC acceptance.\n', encoding='utf-8')
        launchers(root)
        manifest = {'schema': 1, 'id': BUNDLE_NAME, 'applicationVersion': '0.16.0',
                    'sourceCommit': lock['sourceCommit'], 'toolkitCommit': commit, 'toolkitDirty': dirty,
                    'inputArchives': lock['inputArchives'], 'packs': lock['packs'],
                    'toolkitSources': toolkit_sources, 'toolkitFilesMatchCommit': True,
                    'manifestIncludesItself': False, 'files': tree_files(root),
                    'staticValidation': static_checks, 'trust': lock['trust']}
        write_json(root / 'deployment-manifest.json', manifest)
        published = stage / 'output'
        published.mkdir()
        make_zip(root, published / ARCHIVE_NAME)
        bundle_identity = identity(published / ARCHIVE_NAME)
        provenance = {'schema': 1, 'applicationRebuilt': False, 'applicationVersion': '0.16.0',
                      'sourceCommit': lock['sourceCommit'], 'toolkitCommit': commit, 'toolkitDirty': dirty,
                      'archive': {'file': ARCHIVE_NAME, **bundle_identity},
                      'manifest': {'path': BUNDLE_NAME + '/deployment-manifest.json',
                                   **identity(root / 'deployment-manifest.json')},
                      'inputArchives': lock['inputArchives'],
                      'toolkitFiles': [row for row in manifest['files'] if row['path'].startswith('toolkit/')],
                      'toolkitSources': toolkit_sources, 'toolkitFilesMatchCommit': True,
                      'staticValidation': static_checks,
                      'nativeWindowsExecuted': False, 'published': False,
                      'limitations': ['No executable signing or publisher authentication by this builder.',
                                      'No institutional or representative-PC acceptance is implied.',
                                      'No Windows GUI or native scientific execution occurs in this build.']}
        write_json(published / 'BUILD-DEPLOYMENT-PROVENANCE.json', provenance)
        (published / 'SHA256SUMS.txt').write_text(''.join(
            digest(published / name) + '  ' + name + '\n'
            for name in (ARCHIVE_NAME, 'BUILD-DEPLOYMENT-PROVENANCE.json')), encoding='ascii')
        require(not output.exists(), 'Output appeared during build; refusing replacement')
        os.rename(published, output)
    return provenance


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--inputs', required=True, type=Path, help='Directory holding the four exact canonical ZIP filenames')
    parser.add_argument('--output', required=True, type=Path, help='New output directory (parent must exist)')
    parser.add_argument('--toolkit-commit', help='Expected 40-character checkout HEAD; defaults to actual HEAD')
    args = parser.parse_args(argv)
    try:
        result = build(args.inputs, args.output, toolkit_commit=args.toolkit_commit)
    except (ValueError, OSError, KeyError, TypeError, subprocess.CalledProcessError) as exc:
        parser.exit(1, 'Deployment bundle failed: ' + str(exc) + '\n')
    print(json.dumps({'archive': result['archive'], 'toolkitCommit': result['toolkitCommit'],
                      'toolkitDirty': result['toolkitDirty'], 'nativeWindowsExecuted': False}, indent=2))


if __name__ == '__main__':
    main()
