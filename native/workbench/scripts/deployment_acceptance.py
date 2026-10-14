#!/usr/bin/env python3
"""Offline, opt-in observations for an immutable NativeWorkbench tester kit.

Integrity is not publisher authentication. Human acceptance is never inferred
from hosted checks, hashes, signature observations or the presence of a report.
Only explicitly selected attachments are copied; this helper has no upload API.
"""
from __future__ import annotations

import argparse
import ctypes
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import subprocess
import sys
import tempfile

sys.dont_write_bytecode = True
SOURCE_COMMIT = 'e855dc4396e0c16ae35f4e840eb9cc734adb4441'
PUBLISHED_ARCHIVES = {
    'starter': ('native-workbench-0.16.0-starter-windows.zip', 17846873,
                'f96e03e43cac92ba8ca9a0a3807eb671f9924d5e624cadbba94d1a5ca1309073'),
    'updater': ('native-workbench-0.16.0-update-from-0.11.0.zip', 13199905,
                'd75d5129e9b9feaef70faa62d5ea91049c0162df8c7bdc74c7bc81d1933eec8f'),
    'source': ('native-workbench-0.16.0-source.zip', 47848425,
               'f746f00a82675c2cf52364a3b4d040721c6d06ac5605488efbdc0376ef5b7e44'),
    'baseline': ('native-workbench-0.11.0-starter-windows.zip', 17044022,
                 'e816e2f7cd5efe98af752fbf072fab00344ebaa2b6963795c2fbf4a86b5fa81c'),
}
MANIFEST = 'deployment-manifest.json'
MAX_JSON = 8 * 1024 * 1024
MAX_ATTACHMENT = 20 * 1024 * 1024
MAX_ATTACHMENT_TOTAL = 100 * 1024 * 1024
MAX_ATTACHMENTS = 32
STATES = ('not-tested', 'pass', 'failed', 'blocked')
MANUAL_CHECKS = {
    'first-launch': 'Launch the disposable application copy as your ordinary account. Check startup, tool library and both synthetic training workflows; record errors and actual results.',
    'keyboard': 'Use Tab/Shift+Tab, arrow keys, Enter and Escape through the main window, inputs, results, settings and dialogs. Check visible focus, reachability and cancellation.',
    'display-scaling': 'Record each scale setting actually tried. Inspect text, buttons, dialogs and results at each setting; check clipping, overlap and readable focus. Do not infer other scales.',
    'multiple-monitors': 'On actual multiple monitors, move the window/dialogs between displays and reopen them. Record the scale combinations tried and any misplaced or clipped controls.',
    'physical-trackpad': 'Using a physical trackpad, scroll library/forms/results in both directions, slowly and quickly. Check movement, end stops and flashing; injected wheel events do not establish this check.',
    'unicode-path': 'Create a disposable installation and synthetic output location containing Unicode characters, then run both training workflows. Record which characters and outcomes without a personal directory path.',
    'path-limit': 'Exercise a disposable deep output path and record its character count and actual outcome. Native working directories of 260 or more characters are unsupported; do not change Windows policy.',
    'updater-folder-picker': 'In disposable copies only, use the 0.11.0-to-0.16.0 updater folder picker: cancel once, select the baseline copy, and check the update result and preserved data. Do not update a working installation for this test.',
    'offline-use': 'Optional: under your normal permitted offline arrangement, use already installed tools and synthetic inputs. Record what ran and any dependency request. Do not alter managed network policy.',
    'managed-security': 'Optional: ask the responsible IT team to review normal launch and execution under its existing controls. Record approval separately; do not disable protection or bypass execution restrictions.',
}
HEX40 = re.compile(r'^[0-9a-f]{40}$')
HEX64 = re.compile(r'^[0-9a-f]{64}$')


def require(condition, message):
    if not condition:
        raise ValueError(message)


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec='seconds').replace('+00:00', 'Z')


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def no_links(path):
    """Do not follow a symlink, junction or other reparse point supplied as data."""
    path = Path(path).absolute()
    for item in (path, *path.parents):
        if item.exists() or item.is_symlink():
            info = item.lstat()
            require(not stat.S_ISLNK(info.st_mode) and not
                    getattr(info, 'st_file_attributes', 0) & 0x400,
                    'Symlinks and reparse points are not accepted.')
    return path


def relative_path(value):
    require(isinstance(value, str) and 0 < len(value) <= 1024, 'Invalid relative path.')
    require('\\' not in value and ':' not in value and '\x00' not in value,
            'Non-portable relative path.')
    parts = PurePosixPath(value).parts
    require(parts and not value.startswith('/') and all(
        part not in ('.', '..') and part and part[-1] not in '. ' and
        not any(ord(char) < 32 for char in part) and
        part.split('.')[0].upper() not in {'CON', 'PRN', 'AUX', 'NUL',
            *('COM' + str(i) for i in range(1, 10)), *('LPT' + str(i) for i in range(1, 10))}
        for part in parts) and '/'.join(parts) == value, 'Unsafe relative path.')
    return value


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, 'Duplicate JSON object key.')
        result[key] = value
    return result


def read_json(path):
    path = no_links(path)
    require(path.is_file() and path.stat().st_size <= MAX_JSON, 'JSON file missing or too large.')
    return json.loads(path.read_text(encoding='utf-8-sig'), object_pairs_hook=unique_object)


def verify_bundle(root, expected_manifest_sha256=None):
    """Hash every regular file before running any companion helper.

    An independently obtained expected digest is optional because the unsigned
    kit cannot itself establish authenticity. The report always records it.
    """
    root = no_links(root).resolve()
    manifest_path = root / MANIFEST
    manifest = read_json(manifest_path)
    require(isinstance(manifest, dict), 'Manifest must be a JSON object.')
    digest = sha256(manifest_path)
    if expected_manifest_sha256 is not None:
        require(HEX64.fullmatch(expected_manifest_sha256) is not None and
                digest == expected_manifest_sha256, 'Bundle manifest digest differs from the expected value.')
    require(manifest.get('schema') == 1 and manifest.get('sourceCommit') == SOURCE_COMMIT,
            'This helper requires the exact published 0.16.0 application source.')
    require(isinstance(manifest.get('toolkitCommit'), str) and
            HEX40.fullmatch(manifest['toolkitCommit']), 'Missing exact toolkit source identity.')
    require(manifest.get('toolkitDirty', False) is False, 'A dirty toolkit cannot establish tester evidence.')
    rows = manifest.get('files')
    require(isinstance(rows, list) and 1 <= len(rows) <= 20000, 'Invalid bundle file inventory.')
    index, names = {}, set()
    for row in rows:
        require(isinstance(row, dict), 'Invalid file inventory entry.')
        name = relative_path(row.get('path'))
        require(name != MANIFEST and name.casefold() not in names, 'Duplicate or reserved inventory path.')
        require(type(row.get('bytes')) is int and 0 <= row['bytes'] <= 2 * 1024**3 and
                isinstance(row.get('sha256'), str) and HEX64.fullmatch(row['sha256']),
                'Invalid file size or SHA-256.')
        names.add(name.casefold())
        index[name] = row
    actual = set()
    for directory, folders, files in os.walk(root, followlinks=False):
        for name in folders + files:
            path = no_links(Path(directory) / name)
            require(path.is_dir() or path.is_file(), 'Special filesystem entries are not accepted.')
        for name in files:
            path = Path(directory) / name
            rel = path.relative_to(root).as_posix()
            if rel != MANIFEST:
                actual.add(rel)
    require(actual == set(index), 'Bundle inventory differs: files are missing or unrecorded.')
    for name, row in index.items():
        path = root / name
        require(path.stat().st_size == row['bytes'] and sha256(path) == row['sha256'],
                'Bundle integrity failure: ' + name)
    archives = manifest.get('inputArchives')
    require(isinstance(archives, list) and len(archives) == 4 and all(isinstance(item, dict) for item in archives) and
            {item.get('role') for item in archives} == {'starter', 'updater', 'source', 'baseline'},
            'Expected four identified published input archives.')
    for archive in archives:
        require(isinstance(archive.get('file'), str) and '/' not in archive['file'], 'Invalid archive filename.')
        require((archive['file'], archive.get('bytes'), archive.get('sha256')) ==
                PUBLISHED_ARCHIVES[archive['role']], 'Input archive differs from the published release.')
        row = index.get('archives/' + relative_path(archive['file']))
        require(row and row['sha256'] == archive.get('sha256') and row['bytes'] == archive.get('bytes'),
                'Archive identity differs from the inventory.')
    return {'root': root, 'manifestSha256': digest, 'sourceCommit': manifest['sourceCommit'],
            'toolkitCommit': manifest['toolkitCommit'], 'inputArchives': archives, 'filesByPath': index}


def outside_bundle(path, bundle):
    path = no_links(Path(path).expanduser()).resolve()
    require(path != bundle['root'] and not path.is_relative_to(bundle['root']),
            'Reports and disposable test copies must be outside the immutable bundle.')
    return path


def platform_observations():
    # platform.node(), uname(), environment dumps and device identities are
    # deliberately excluded. Display geometry contains no monitor serial/name.
    result = {'system': sys.platform, 'release': 'unavailable',
              'version': 'unavailable', 'architecture': str(ctypes.sizeof(ctypes.c_void_p) * 8) + '-bit process',
              'displays': {'status': 'not-tested', 'observations': []}}
    if os.name != 'nt':
        return result
    windows = sys.getwindowsversion()
    result.update(system='Windows', release='%d.%d' % (windows.major, windows.minor),
                  version='%d.%d.%d' % (windows.major, windows.minor, windows.build))
    try:
        from ctypes import wintypes
        class SystemInfo(ctypes.Structure):
            _fields_ = [('processorArchitecture', wintypes.WORD), ('reserved', wintypes.WORD),
                        ('pageSize', wintypes.DWORD), ('minimumAddress', ctypes.c_void_p),
                        ('maximumAddress', ctypes.c_void_p), ('activeProcessorMask', ctypes.c_size_t),
                        ('numberOfProcessors', wintypes.DWORD), ('processorType', wintypes.DWORD),
                        ('allocationGranularity', wintypes.DWORD), ('processorLevel', wintypes.WORD),
                        ('processorRevision', wintypes.WORD)]
        info = SystemInfo()
        ctypes.WinDLL('kernel32').GetNativeSystemInfo(ctypes.byref(info))
        result['architecture'] = {0: 'x86', 6: 'IA64', 9: 'AMD64', 12: 'ARM64'}.get(
            info.processorArchitecture, 'unavailable')
        displays = []
        user32 = ctypes.WinDLL('user32', use_last_error=True)
        callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HANDLE,
                                           wintypes.HDC, ctypes.POINTER(wintypes.RECT), wintypes.LPARAM)
        def observe(monitor, _dc, rect, _data):
            item = {'width': rect.contents.right - rect.contents.left,
                    'height': rect.contents.bottom - rect.contents.top,
                    'dpi': None, 'dpiStatus': 'unavailable'}
            try:
                x, y = ctypes.c_uint(), ctypes.c_uint()
                shcore = ctypes.WinDLL('shcore', use_last_error=True)
                shcore.GetDpiForMonitor.argtypes = [wintypes.HANDLE, ctypes.c_int,
                                                   ctypes.POINTER(ctypes.c_uint), ctypes.POINTER(ctypes.c_uint)]
                if shcore.GetDpiForMonitor(monitor, 0, ctypes.byref(x), ctypes.byref(y)) == 0:
                    item.update(dpi=[x.value, y.value], dpiStatus='observed')
            except (OSError, AttributeError):
                pass
            displays.append(item)
            return True
        callback = callback_type(observe)
        require(bool(user32.EnumDisplayMonitors(None, None, callback, 0)), 'Display enumeration unavailable.')
        result['displays'] = {'status': 'observed', 'observations': displays,
            'scope': 'Current process-visible geometry and effective DPI; values may be DPI-virtualized. This is not a visual acceptance check.'}
    except (OSError, ValueError, AttributeError):
        result['displays']['status'] = 'unavailable'
    return result


def new_report(bundle, alias):
    require(isinstance(alias, str) and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,47}', alias),
            'Use a tester-selected alias of 1–48 letters, numbers, dots, underscores or hyphens.')
    now = utc_now()
    return {'schemaVersion': 1, 'kind': 'native-workbench-deployment-acceptance',
        'applicationVersion': '0.16.0', 'createdAt': now, 'updatedAt': now,
        'machineAlias': alias, 'sourceCommit': bundle['sourceCommit'],
        'toolkitCommit': bundle['toolkitCommit'], 'bundleManifestSha256': bundle['manifestSha256'],
        'inputArchives': bundle['inputArchives'],
        'helpers': [row for name, row in sorted(bundle['filesByPath'].items()) if name.startswith('toolkit/')],
        'observations': platform_observations(),
        'manualChecks': [{'id': key, 'status': 'not-tested', 'observedAt': None, 'note': '',
                          'evidence': [], 'history': []} for key in MANUAL_CHECKS],
        'automatedReports': [], 'signatures': {'status': 'not-tested'},
        'testInstallation': {'status': 'not-prepared'}, 'attachments': [],
        'summary': {'manualAcceptance': 'not-tested', 'institutionalApproval': 'not-established'},
        'privacy': 'No automatic user, hostname, domain, IP or device identifiers. Notes and attachments are explicitly selected by the tester; review before sharing. Nothing is uploaded.',
        'limits': ['Manual checks start untested and require the tester’s observations.',
                   'Hashes establish byte consistency, not publisher trust or institutional approval.',
                   'Hosted automated evidence does not establish physical-trackpad or representative-PC acceptance.']}


def load_report(path, bundle):
    path = outside_bundle(path, bundle)
    report = read_json(path)
    require(report.get('schemaVersion') == 1 and report.get('kind') == 'native-workbench-deployment-acceptance',
            'Not an acceptance report.')
    require(all(report.get(key) == value for key, value in (
        ('bundleManifestSha256', bundle['manifestSha256']), ('sourceCommit', bundle['sourceCommit']),
        ('toolkitCommit', bundle['toolkitCommit']))), 'Report belongs to different bundle bytes.')
    checks = report.get('manualChecks', [])
    require(len(checks) == len(MANUAL_CHECKS) and {item.get('id') for item in checks} == set(MANUAL_CHECKS)
            and all(item.get('status') in STATES for item in checks), 'Invalid manual checks.')
    return report


def write_report(path, report, bundle, *, create=False):
    path = outside_bundle(path, bundle)
    require(path.suffix.lower() == '.json', 'Report must have a .json extension.')
    path.parent.mkdir(parents=True, exist_ok=True)
    if create:
        require(not path.exists(), 'Report already exists; use record or guided to resume it.')
    report['updatedAt'] = utc_now()
    states = [row['status'] for row in report['manualChecks']]
    summary = 'failed' if 'failed' in states else 'blocked' if 'blocked' in states else \
        'pass' if states and all(state == 'pass' for state in states) else 'incomplete' if 'pass' in states else 'not-tested'
    report['summary'] = {'manualAcceptance': summary, 'institutionalApproval': 'not-established'}
    text = json.dumps(report, indent=2, ensure_ascii=False) + '\n'
    require(len(text.encode('utf-8')) <= MAX_JSON, 'Report exceeds size limit.')
    if create:
        with path.open('x', encoding='utf-8', newline='\n') as stream:
            stream.write(text)
    else:
        handle, temporary = tempfile.mkstemp(prefix='.acceptance-', suffix='.tmp', dir=path.parent)
        try:
            with os.fdopen(handle, 'w', encoding='utf-8', newline='\n') as stream:
                stream.write(text)
            os.replace(temporary, path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)


def attach_files(report_path, report, bundle, selected):
    require(len(report['attachments']) + len(selected) <= MAX_ATTACHMENTS, 'Too many evidence attachments.')
    total = sum(item['bytes'] for item in report['attachments'])
    prepared = []
    for name in selected:
        path = no_links(name)
        require(path.is_file() and path.resolve() != Path(report_path).resolve(), 'Select a regular evidence file, not the report.')
        size = path.stat().st_size
        require(size <= MAX_ATTACHMENT and total + size <= MAX_ATTACHMENT_TOTAL,
                'Attachment limit is 20 MiB per file and 100 MiB per report.')
        total += size
        prepared.append((path, size, sha256(path)))
    folder = outside_bundle(Path(report_path).with_suffix(''), bundle).with_name(Path(report_path).stem + '-evidence')
    no_links(folder)
    folder.mkdir(parents=True, exist_ok=True)
    added = []
    for path, size, digest in prepared:
        extension = path.suffix.lower()
        if not re.fullmatch(r'\.[a-z0-9]{1,8}', extension):
            extension = '.bin'
        filename = '%03d-%s%s' % (len(report['attachments']) + 1, digest[:16], extension)
        destination = folder / filename
        with path.open('rb') as source, destination.open('xb') as target:
            shutil.copyfileobj(source, target, 1024 * 1024)
        require(destination.stat().st_size == size and sha256(destination) == digest, 'Evidence changed during copying.')
        item = {'id': 'evidence-%03d' % (len(report['attachments']) + 1),
                'file': folder.name + '/' + filename, 'bytes': size, 'sha256': digest,
                'selectedAt': utc_now(), 'selection': 'explicit tester file selection'}
        report['attachments'].append(item)
        added.append(item['id'])
    return added


def record_check(report_path, report, bundle, check_id, status, note, attachments=()):
    require(check_id in MANUAL_CHECKS and status in STATES, 'Unknown manual check or status.')
    require(isinstance(note, str) and len(note) <= 4000, 'Observation note is too long.')
    require(status == 'not-tested' or note.strip(), 'An actual observation or blocking reason is required.')
    evidence = attach_files(report_path, report, bundle, attachments) if attachments else []
    item = next(row for row in report['manualChecks'] if row['id'] == check_id)
    if item.get('observedAt'):
        require(len(item.setdefault('history', [])) < 100, 'Too many revisions for one manual check.')
        item['history'].append({key: item[key] for key in ('status', 'note', 'observedAt', 'evidence')})
    item.update(status=status, note=note.strip(), observedAt=utc_now(), evidence=evidence)


def valid_time(value):
    require(isinstance(value, str) and re.fullmatch(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?Z', value),
            'UTC observation time required.')
    datetime.fromisoformat(value[:-1] + '+00:00')


def import_automated(path, report, bundle):
    value = read_json(path)
    require(isinstance(value, dict) and set(value) == {'schemaVersion', 'kind', 'sourceCommit', 'toolkitCommit',
                          'bundleManifestSha256', 'observedAt', 'checks', 'limits'},
            'Automated summary has unexpected or missing fields.')
    require(value['schemaVersion'] == 1 and value['kind'] == 'native-deployment-gate', 'Unsupported automated summary.')
    require(all(value[key] == report[key] for key in ('sourceCommit', 'toolkitCommit', 'bundleManifestSha256')),
            'Automated evidence describes different source or bundle bytes.')
    valid_time(value['observedAt'])
    require(isinstance(value['checks'], list) and 1 <= len(value['checks']) <= 100, 'Invalid automated checks.')
    ids = set()
    for item in value['checks']:
        require(isinstance(item, dict) and set(item) == {'id', 'status', 'observedAt', 'note'} and
                isinstance(item['id'], str) and re.fullmatch(r'[a-z0-9][a-z0-9-]{0,79}', item['id']) and
                item['id'] not in ids and item['status'] in STATES and
                isinstance(item['note'], str) and len(item['note']) <= 4000,
                'Invalid or duplicate automated check.')
        valid_time(item['observedAt'])
        ids.add(item['id'])
    require(isinstance(value['limits'], list) and len(value['limits']) <= 20 and
            all(isinstance(item, str) and len(item) <= 1000 for item in value['limits']), 'Invalid automated limits.')
    require(len(report['automatedReports']) < 20, 'Too many automated reports.')
    report['automatedReports'].append({'importedAt': utc_now(), 'sha256': sha256(path),
        'summary': value, 'scope': 'Automated observations only; no manual check state is changed.'})


def prepare_installation(work_root, bundle, report):
    destination = outside_bundle(work_root, bundle)
    require(not destination.exists(), 'Disposable installation destination must not exist.')
    prefix = 'native-workbench/'
    rows = [(name[len(prefix):], row) for name, row in bundle['filesByPath'].items() if name.startswith(prefix)]
    require(rows and any(name == 'NativeWorkbench.exe' for name, _ in rows), 'Application files are missing.')
    destination.mkdir(parents=True)
    for name, row in rows:
        target = destination / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(bundle['root'] / (prefix + name), target)
        require(target.stat().st_size == row['bytes'] and sha256(target) == row['sha256'], 'Disposable copy verification failed.')
    report['testInstallation'] = {'status': 'prepared', 'preparedAt': utc_now(), 'files': len(rows),
        'initialBytesVerified': True, 'scope': 'Fresh Starter copy only. Subsequent manual outcomes are recorded separately; no absolute installation path is collected.'}
    return destination


def collect_signatures(report_path, report, bundle):
    if os.name != 'nt':
        report['signatures'] = {'status': 'unavailable', 'observedAt': utc_now(), 'reason': 'Authenticode observation requires native Windows.'}
        return
    collector = 'toolkit/scripts/collect_deployment_signatures.ps1'
    require(collector in bundle['filesByPath'], 'Signature collector is not inventoried.')
    # System PowerShell is selected explicitly; no PATH lookup, profile loading,
    # elevation, policy override or shell expansion is involved.
    system = ctypes.create_unicode_buffer(32768)
    require(ctypes.windll.kernel32.GetSystemDirectoryW(system, len(system)) > 0, 'System directory unavailable.')
    powershell = Path(system.value) / 'WindowsPowerShell/v1.0/powershell.exe'
    output = outside_bundle(Path(report_path).with_name(Path(report_path).stem + '-signatures.json'), bundle)
    require(not output.exists(), 'Signature observation file already exists; choose a new report name.')
    launch_error = None
    try:
        result = subprocess.run([str(powershell), '-NoLogo', '-NoProfile', '-NonInteractive', '-File',
            str(bundle['root'] / collector), '-BundleRoot', str(bundle['root']),
            '-ManifestSha256', bundle['manifestSha256'], '-OutputPath', str(output)],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=300, check=False)
    except (OSError, subprocess.TimeoutExpired) as error:
        result = None
        launch_error = type(error).__name__
    if result is None or result.returncode != 0 or not output.is_file():
        report['signatures'] = {'status': 'unavailable', 'observedAt': utc_now(),
            'reason': 'The signature collector could not complete under the existing system policy/trust context. No policy was changed.',
            'collectorSha256': bundle['filesByPath'][collector]['sha256'],
            'diagnostic': collector_diagnostic(result.stdout if result is not None else b'',
                result.returncode if result is not None else None, launch_error)}
        return
    value = read_json(output)
    expected = signature_targets(bundle)
    require(value.get('schemaVersion') == 1 and value.get('kind') == 'native-workbench-authenticode-observations'
            and value.get('bundleManifestSha256') == bundle['manifestSha256'], 'Invalid signature observation identity.')
    rows = value.get('files', [])
    require(len(rows) == len(expected) and {row.get('path') for row in rows} == set(expected),
            'Signature observation does not cover the exact executable inventory.')
    require(all(row.get('sha256') == expected[row['path']]['sha256'] for row in rows),
            'Signature observations describe different executable bytes.')
    report['signatures'] = {'status': 'observed', 'observedAt': utc_now(), 'file': output.name,
        'sha256': sha256(output), 'collectorSha256': bundle['filesByPath'][collector]['sha256'],
        'fileCount': len(rows), 'scope': 'Actual Windows Authenticode observations for inventoried PE content (including extensionless updater blobs) and .exe/.dll/.pyd paths. Script formats (.py/.cmd/.ps1) and other inventory kinds are not checked by this collector. This is not publisher approval or institutional acceptance; unavailable and unsigned statuses remain explicit.'}


def collector_diagnostic(stdout, returncode, launch_error=None):
    """Export only a bounded stage/type/line record, never PowerShell output."""
    diagnostic = {'stage': 'collector-launch', 'errorType':
        launch_error if launch_error in ('OSError', 'FileNotFoundError', 'PermissionError', 'TimeoutExpired')
        else 'NoStructuredDiagnostic', 'scriptLine': None, 'exitCode': returncode}
    if not isinstance(stdout, bytes) or len(stdout) > 4096:
        return diagnostic
    prefix = 'NW_SIGNATURE_DIAGNOSTIC '
    for line in stdout.decode('utf-8', errors='replace').splitlines():
        if not line.startswith(prefix) or len(line) > 1024:
            continue
        try:
            value = json.loads(line[len(prefix):], object_pairs_hook=unique_object)
            require(isinstance(value, dict) and set(value) == {'schemaVersion', 'stage', 'errorType', 'scriptLine'}
                    and value['schemaVersion'] == 1, 'Invalid collector diagnostic.')
            require(value['stage'] in ('startup', 'system-modules', 'root-check', 'manifest-check', 'inventory-check',
                    'output-check', 'signature-observation', 'write-observations'), 'Invalid diagnostic stage.')
            require(isinstance(value['errorType'], str) and len(value['errorType']) <= 160 and
                    re.fullmatch(r'(?:System\.|Microsoft\.)[A-Za-z0-9_.+`]+', value['errorType']),
                    'Invalid diagnostic exception type.')
            require(type(value['scriptLine']) is int and 0 <= value['scriptLine'] <= 100000,
                    'Invalid diagnostic line.')
        except (ValueError, TypeError):
            continue
        return {'stage': value['stage'], 'errorType': value['errorType'],
                'scriptLine': value['scriptLine'], 'exitCode': returncode}
    return diagnostic


def signature_targets(bundle):
    """Include update blobs whose PE content has no executable filename suffix."""
    result = {}
    for name, row in bundle['filesByPath'].items():
        selected = Path(name).suffix.lower() in ('.exe', '.dll', '.pyd')
        if not selected and row['bytes'] >= 64:
            with (bundle['root'] / name).open('rb') as stream:
                header = stream.read(64)
                if header[:2] == b'MZ':
                    offset = int.from_bytes(header[60:64], 'little')
                    if 64 <= offset <= min(1024 * 1024, row['bytes'] - 4):
                        stream.seek(offset)
                        selected = stream.read(4) == b'PE\0\0'
        if selected:
            result[name] = row
    return result


def guided(args, bundle):
    print('Local tester report. Use a neutral alias such as PC-A; do not enter your username or hostname.')
    report_path = args.report or input('Report JSON path outside the bundle: ').strip().strip('"')
    path = outside_bundle(report_path, bundle)
    if path.exists():
        report = load_report(path, bundle)
    else:
        alias = args.machine_alias or input('Tester-selected machine alias: ').strip()
        report = new_report(bundle, alias)
        write_report(path, report, bundle, create=True)
    if report['testInstallation']['status'] == 'not-prepared':
        print('Keep the bundle unchanged. A disposable application copy is required for interactive testing.')
        destination = input('New application-copy folder outside the bundle (Enter to leave preparation untested): ').strip().strip('"')
        if destination:
            copy = prepare_installation(destination, bundle, report)
            write_report(path, report, bundle)
            print('Verified copy ready. Open NativeWorkbench.exe in: ' + str(copy))
    print('Use synthetic inputs only. Notes and selected attachments stay local; review them before sharing.')
    print('Leave any unexercised scenario not-tested. Controls and policy must not be bypassed.')
    for check_id, guidance in MANUAL_CHECKS.items():
        item = next(row for row in report['manualChecks'] if row['id'] == check_id)
        print('\n' + check_id + ': ' + guidance)
        status = input('State [pass/failed/blocked/not-tested], Enter keeps ' + item['status'] + ': ').strip()
        if not status:
            continue
        require(status in STATES, 'Use one of the displayed states.')
        note = input('Observed outcome or reason (avoid names and personal paths): ').strip()
        selected = []
        while True:
            attachment = input('Explicit evidence file path to copy, or Enter to continue: ').strip().strip('"')
            if not attachment:
                break
            selected.append(attachment)
        record_check(path, report, bundle, check_id, status, note, selected)
        write_report(path, report, bundle)
    print('Report saved: ' + str(path))
    return 0


def parser():
    result = argparse.ArgumentParser(description=__doc__)
    sub = result.add_subparsers(dest='command', required=True)
    for name in ('verify', 'init', 'guided', 'record', 'import-automated', 'signatures', 'prepare'):
        command = sub.add_parser(name)
        command.add_argument('--bundle-root', type=Path, required=True)
        command.add_argument('--expected-manifest-sha256')
        if name != 'verify':
            command.add_argument('--report', type=Path, required=name not in ('guided', 'signatures'))
        if name in ('init', 'guided', 'signatures'):
            command.add_argument('--machine-alias', required=name == 'init')
        if name == 'record':
            command.add_argument('--check', choices=tuple(MANUAL_CHECKS), required=True)
            command.add_argument('--status', choices=STATES, required=True)
            command.add_argument('--note', default='')
            command.add_argument('--attach', type=Path, action='append', default=[])
        if name == 'import-automated':
            command.add_argument('--automated-report', type=Path, required=True)
        if name == 'prepare':
            command.add_argument('--work-root', type=Path, required=True)
    return result


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        bundle = verify_bundle(args.bundle_root, args.expected_manifest_sha256)
        if args.command == 'verify':
            print(json.dumps({'status': 'verified', 'bundleManifestSha256': bundle['manifestSha256'],
                'files': len(bundle['filesByPath']), 'sourceCommit': bundle['sourceCommit'],
                'toolkitCommit': bundle['toolkitCommit'], 'trust': 'Byte integrity only; no publisher or institutional approval implied.'}))
            return 0
        if args.command == 'guided':
            return guided(args, bundle)
        if args.command == 'signatures' and not args.report:
            args.report = Path(input('Report JSON path outside the bundle: ').strip().strip('"'))
        if args.command == 'init' or (args.command == 'signatures' and not args.report.exists()):
            alias = args.machine_alias or input('Neutral tester-selected machine alias (for example PC-A): ').strip()
            report = new_report(bundle, alias)
            write_report(args.report, report, bundle, create=True)
        else:
            report = load_report(args.report, bundle)
        if args.command == 'record':
            record_check(args.report, report, bundle, args.check, args.status, args.note, args.attach)
        elif args.command == 'import-automated':
            import_automated(args.automated_report, report, bundle)
        elif args.command == 'signatures':
            collect_signatures(args.report, report, bundle)
        elif args.command == 'prepare':
            prepare_installation(args.work_root, bundle, report)
        write_report(args.report, report, bundle)
        print('Local report saved. Manual acceptance: ' + report['summary']['manualAcceptance'])
        return 2 if args.command == 'signatures' and report['signatures']['status'] == 'unavailable' else 0
    except (ValueError, OSError, EOFError, KeyboardInterrupt) as error:
        print('Acceptance helper stopped: ' + str(error), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
