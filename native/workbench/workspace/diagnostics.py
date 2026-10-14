"""Explicit, bounded diagnostic review/export with no data or log collection.

Only supplied structured summaries and a small system inventory are examined.
The application root is deliberately not read: paths, settings, logs, filenames,
commands and arbitrary exception text must never become diagnostic attachments.
Pack identities are reported facts, not an integrity or publisher-trust check.
"""
from __future__ import annotations

from contextlib import contextmanager
import hashlib
import io
import itertools
import json
import os
from pathlib import Path
import re
import secrets
import stat
import sys
import zipfile

try:
    from .app_version import APP_VERSION, PACK_API
    from .pack_manager import filesystem_path, ordinary_windows_path
    from .performance import safe_system_identity
except ImportError:
    from app_version import APP_VERSION, PACK_API
    from pack_manager import filesystem_path, ordinary_windows_path
    from performance import safe_system_identity

MAX_RECORDS = 256
MAX_CHECKS = 4096
MAX_REPORT_BYTES = 256 * 1024
MAX_COUNT = 1_000_000_000
OFFICIAL_IDS = frozenset({
    'builtin', 'align', 'bam', 'bedtools', 'blast', 'bowtie2', 'bracken',
    'bwa', 'deseq2', 'fastp', 'fastqc', 'featurecounts', 'freebayes', 'gatk',
    'hisat2', 'iqtree', 'kallisto', 'kraken2', 'lofreq', 'mosdepth', 'multiqc',
    'muscle', 'mutect2', 'reads', 'research-variants', 'seqkit', 'snpeff',
    'star', 'trimming', 'vardict', 'variant-pipeline', 'variants', 'vsearch',
})
RUN_STATUSES = frozenset({'pending', 'preparing', 'running', 'cancelling', 'completed',
                          'success', 'failed', 'cancelled', 'blocked', 'interrupted', 'unknown'})
CHECK_STATUSES = ('passed', 'failed', 'warning', 'not_checked', 'deferred', 'unknown')
READINESS_STATUSES = frozenset({'blocked', 'incomplete', 'ready_for_preparation', 'unknown'})
VERSION = re.compile(r'(?:0|[1-9][0-9]{0,8})\.(?:0|[1-9][0-9]{0,8})\.(?:0|[1-9][0-9]{0,8})\Z')
SHA256 = re.compile(r'[a-f0-9]{64}\Z')
SYSTEM_VERSION = re.compile(r'[0-9]{1,6}(?:\.[0-9]{1,6}){0,3}\Z')
LIMITS = {
    'automaticUpload': False, 'fileContentsIncluded': False, 'filePathsIncluded': False,
    'logsOrCommandsIncluded': False, 'sampleNamesIncluded': False,
    'settingsOrEnvironmentIncluded': False, 'installationIntegrityVerified': False,
}
README = """Native Workbench diagnostic report

This archive was saved locally after review. Workbench does not upload it.
report.json contains the same canonical JSON displayed for review.
SHA256SUMS.txt covers report.json and this README; these are integrity hashes,
not a publisher signature. The archive is not encrypted.

Included: application/pack versions and manifest identities, broad system
configuration, bounded run state and readiness counts. Pack IDs outside the
fixed public list are labelled third-party. Recorded pack identities do not
establish authenticity, installation integrity or successful tool execution.
Unknown measurements are null, not zero or a pass. Lists may be truncated;
omitted counts and examined counts make this explicit.
Readiness counts describe the most recent workspace review and may precede
later edits; they are not a fresh check at diagnostic export time.

Excluded: scientific files and their hashes, filenames and paths, sample and
workflow names, logs, commands and parameters, raw exceptions, settings,
environment variables, network addresses, user names and computer names.
No application or user folders are scanned. Review the report before sharing;
system configuration and installed software can still identify a deployment.
"""


def _mapping(value):
    return value if type(value) is dict else {}


def _sequence(value):
    return value if type(value) in (list, tuple) else ()


def _count(value):
    return min(len(value), MAX_COUNT)


def _enum(value, allowed, default='unknown'):
    return value if type(value) is str and value in allowed else default


def _matched(value, expression):
    return value if type(value) is str and len(value) <= 64 and expression.fullmatch(value) else None


def _integer(value, maximum, minimum=0):
    return value if type(value) is int and minimum <= value <= maximum else None


def _pack(value, installed=False):
    value = _mapping(value)
    identity = value.get('id' if installed else 'packId')
    return {
        'id': _enum(identity, OFFICIAL_IDS, 'third-party'),
        'version': _matched(value.get('version' if installed else 'packVersion'), VERSION),
        'manifestSha256': _matched(value.get('manifestSha256'), SHA256),
    }


def _memory_bytes():
    try:
        if os.name == 'nt':
            import ctypes
            from ctypes import wintypes
            class MemoryStatus(ctypes.Structure):
                _fields_ = [('length', wintypes.DWORD), ('load', wintypes.DWORD)] + [
                    (key, ctypes.c_ulonglong) for key in (
                        'totalPhysical', 'availablePhysical', 'totalPageFile',
                        'availablePageFile', 'totalVirtual', 'availableVirtual', 'extendedVirtual')]
            result = MemoryStatus()
            result.length = ctypes.sizeof(result)
            query = ctypes.WinDLL('kernel32', use_last_error=True).GlobalMemoryStatusEx
            query.argtypes = [ctypes.POINTER(MemoryStatus)]
            query.restype = wintypes.BOOL
            return int(result.totalPhysical) if query(ctypes.byref(result)) else None
        return os.sysconf('SC_PHYS_PAGES') * os.sysconf('SC_PAGE_SIZE')
    except (AttributeError, OSError, ValueError, TypeError):
        return None


def _system():
    # platform.machine()/system() also collect the hostname through uname() on
    # Windows. Query the native identity helper instead; keep only the allowlisted
    # architecture, not POSIX version/release strings with locally chosen text.
    family = {'win32': 'Windows', 'linux': 'Linux', 'darwin': 'macOS'}.get(sys.platform, 'other')
    version = None
    if sys.platform == 'win32':
        try:
            current = sys.getwindowsversion()
            version = f'{current.major}.{current.minor}.{current.build}'
        except (AttributeError, OSError):
            pass
    machine = _mapping(safe_system_identity()).get('architecture')
    architecture = {'amd64': 'x86-64', 'x86_64': 'x86-64', 'x86': 'x86',
                    'i386': 'x86', 'i686': 'x86', 'arm64': 'arm64', 'aarch64': 'arm64'}.get(
                        machine.lower() if type(machine) is str else '', 'other')
    return {'os': family, 'version': _matched(version, SYSTEM_VERSION),
            'architecture': architecture,
            'logicalCpuCount': _integer(os.cpu_count(), 65536, 1),
            'totalMemoryBytes': _integer(_memory_bytes(), 2**60, 1)}


def build_report(app_root, catalog, run=None, readiness=None):
    """Return a fresh, bounded public diagnostic summary; never read app_root.

    Pass a trusted in-memory current run and engine review/readiness object.
    Supplied objects are treated as untrusted data and are never modified.
    No path, identifier, label, free text or scientific digest is copied.
    """
    catalog = _mapping(catalog)
    packs = _sequence(catalog.get('packs'))
    report = {
        'schema': 1, 'kind': 'native-workbench-diagnostics',
        'app': {'version': APP_VERSION, 'packApi': PACK_API},
        'system': _system(),
        'catalog': {'packCount': _count(packs),
                    'operationCount': _count(_mapping(catalog.get('tools'))),
                    'catalogErrorCount': _count(_sequence(catalog.get('errors'))),
                    'packs': [_pack(value, installed=True) for value in itertools.islice(packs, MAX_RECORDS)],
                    'omittedPackCount': max(0, _count(packs) - MAX_RECORDS)},
        'run': None, 'readiness': None, 'limits': dict(LIMITS),
    }
    if type(run) is dict:
        nodes = _sequence(run.get('nodes'))
        performance = _mapping(run.get('performance'))
        report['run'] = {
            'status': _enum(run.get('status'), RUN_STATUSES),
            'stepCount': _count(nodes),
            'steps': [{'number': number + 1,
                       'status': _enum(_mapping(node).get('status'), RUN_STATUSES),
                       'pack': _pack(_mapping(node).get('pin'))}
                      for number, node in enumerate(itertools.islice(nodes, MAX_RECORDS))],
            'omittedStepCount': max(0, _count(nodes) - MAX_RECORDS),
            'performanceRecordPresent': type(performance.get('schema')) is int and performance.get('schema') == 1 and
                                        performance.get('file') == 'performance.json',
        }
    if type(readiness) is dict:
        readiness = _mapping(readiness.get('readiness', readiness))
        checks = _sequence(readiness.get('checks'))
        counts = dict.fromkeys(CHECK_STATUSES, 0)
        for check in itertools.islice(checks, MAX_CHECKS):
            counts[_enum(_mapping(check).get('status'), CHECK_STATUSES)] += 1
        report['readiness'] = {
            'status': _enum(readiness.get('status'), READINESS_STATUSES),
            'checkCount': _count(checks), 'examinedCheckCount': min(len(checks), MAX_CHECKS),
            'omittedCheckCount': max(0, _count(checks) - MAX_CHECKS), 'statusCounts': counts,
        }
    # This also protects future changes from accidentally expanding the export.
    preview_text(report)
    return report


def _require(condition):
    if not condition:
        raise ValueError('The reviewed diagnostic report is invalid or exceeds its limits.')


def _keys(value, expected):
    _require(type(value) is dict and set(value) == set(expected))


def _number(value, maximum=MAX_COUNT, minimum=0):
    _require(_integer(value, maximum, minimum) is not None)


def _validate_pack(value):
    _keys(value, ('id', 'version', 'manifestSha256'))
    _require(type(value['id']) is str and value['id'] in OFFICIAL_IDS | {'third-party'})
    _require(value['version'] is None or _matched(value['version'], VERSION) is not None)
    _require(value['manifestSha256'] is None or _matched(value['manifestSha256'], SHA256) is not None)


def _validate_report(report):
    _keys(report, ('schema', 'kind', 'app', 'system', 'catalog', 'run', 'readiness', 'limits'))
    _require(type(report['schema']) is int and report['schema'] == 1 and
             report['kind'] == 'native-workbench-diagnostics')
    _keys(report['app'], ('version', 'packApi'))
    _require(_matched(report['app']['version'], VERSION) is not None)
    _number(report['app']['packApi'], 1000, 1)
    system = report['system']
    _keys(system, ('os', 'version', 'architecture', 'logicalCpuCount', 'totalMemoryBytes'))
    _require(_enum(system['os'], {'Windows', 'Linux', 'macOS', 'other'}, None) is not None)
    _require(_enum(system['architecture'], {'x86-64', 'x86', 'arm64', 'other'}, None) is not None)
    _require(system['version'] is None or _matched(system['version'], SYSTEM_VERSION) is not None)
    for key, maximum in (('logicalCpuCount', 65536), ('totalMemoryBytes', 2**60)):
        if system[key] is not None:
            _number(system[key], maximum, 1)
    catalog = report['catalog']
    _keys(catalog, ('packCount', 'operationCount', 'catalogErrorCount', 'packs', 'omittedPackCount'))
    for key in ('packCount', 'operationCount', 'catalogErrorCount', 'omittedPackCount'):
        _number(catalog[key])
    _require(type(catalog['packs']) is list and len(catalog['packs']) <= MAX_RECORDS and
             len(catalog['packs']) + catalog['omittedPackCount'] == catalog['packCount'])
    for pack in catalog['packs']:
        _validate_pack(pack)
    run = report['run']
    if run is not None:
        _keys(run, ('status', 'stepCount', 'steps', 'omittedStepCount', 'performanceRecordPresent'))
        _require(_enum(run['status'], RUN_STATUSES, None) is not None and type(run['performanceRecordPresent']) is bool)
        _number(run['stepCount'])
        _number(run['omittedStepCount'])
        _require(type(run['steps']) is list and len(run['steps']) <= MAX_RECORDS and
                 len(run['steps']) + run['omittedStepCount'] == run['stepCount'])
        for number, step in enumerate(run['steps'], 1):
            _keys(step, ('number', 'status', 'pack'))
            _require(type(step['number']) is int and step['number'] == number and
                     _enum(step['status'], RUN_STATUSES, None) is not None)
            _validate_pack(step['pack'])
    readiness = report['readiness']
    if readiness is not None:
        _keys(readiness, ('status', 'checkCount', 'examinedCheckCount', 'omittedCheckCount', 'statusCounts'))
        _require(_enum(readiness['status'], READINESS_STATUSES, None) is not None)
        for key in ('checkCount', 'examinedCheckCount', 'omittedCheckCount'):
            _number(readiness[key])
        _keys(readiness['statusCounts'], CHECK_STATUSES)
        for value in readiness['statusCounts'].values():
            _number(value, MAX_CHECKS)
        _require(sum(readiness['statusCounts'].values()) == readiness['examinedCheckCount'] <= MAX_CHECKS and
                 readiness['examinedCheckCount'] + readiness['omittedCheckCount'] == readiness['checkCount'])
    _keys(report['limits'], LIMITS)
    _require(all(value is False for value in report['limits'].values()))


def preview_text(report):
    """Canonical review text; these exact UTF-8 bytes are exported as report.json."""
    _validate_report(report)
    result = json.dumps(report, ensure_ascii=True, sort_keys=True, indent=2, allow_nan=False) + '\n'
    _require(len(result.encode('utf-8')) <= MAX_REPORT_BYTES)
    return result


def _reject_reparse(info):
    if not (stat.S_ISDIR(info.st_mode) and not stat.S_ISLNK(info.st_mode) and
            not getattr(info, 'st_file_attributes', 0) & 0x400):
        raise ValueError('Choose an ordinary diagnostic destination folder without links or junctions.')


@contextmanager
def _directory(parent):
    """Pin the selected directory, never following a symlink or Windows reparse.

    POSIX opens every component relative to an already opened directory. On
    Windows all ancestor handles exclude delete sharing, preventing substitution
    while the unique child is created. No destination folders are created.
    """
    path = Path(ordinary_windows_path(parent) if os.name == 'nt' else parent)
    _require(path.is_absolute())
    _require('..' not in path.parts and bool(path.anchor))
    if os.name == 'nt':
        import ctypes
        from ctypes import wintypes
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        create = kernel.CreateFileW
        create.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p,
                           wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
        create.restype = wintypes.HANDLE
        close = kernel.CloseHandle
        close.argtypes = [wintypes.HANDLE]
        close.restype = wintypes.BOOL
        invalid = ctypes.c_void_p(-1).value
        handles = []
        try:
            for component in reversed((path, *path.parents)):
                io_component = filesystem_path(component)
                handle = create(str(io_component), 0x80, 0x1 | 0x2, None, 3, 0x02000000 | 0x00200000, None)
                if handle == invalid:
                    raise OSError('The diagnostic destination could not be opened safely.')
                handles.append(handle)
                _reject_reparse(io_component.lstat())
            yield path, None
        finally:
            for handle in reversed(handles):
                close(handle)
    else:
        descriptor = os.open(path.anchor, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            for component in path.parts[1:]:
                following = os.open(component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=descriptor)
                os.close(descriptor)
                descriptor = following
            _reject_reparse(os.fstat(descriptor))
            yield path, descriptor
        finally:
            os.close(descriptor)


def export_report(report, destination_parent):
    """Save one new local ZIP containing exactly the reviewed canonical report.

    The destination must already be an ordinary directory. No files are read,
    overwritten or uploaded. Unsupported/reparse destinations fail closed.
    """
    raw = preview_text(report).encode('utf-8')
    members = {'report.json': raw, 'README.txt': README.encode('utf-8')}
    members['SHA256SUMS.txt'] = ''.join(
        f'{hashlib.sha256(value).hexdigest()}  {name}\n' for name, value in members.items()).encode('ascii')
    memory = io.BytesIO()
    with zipfile.ZipFile(memory, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        for name, value in members.items():
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100600 << 16
            archive.writestr(info, value)
    payload = memory.getvalue()
    with _directory(destination_parent) as (parent, directory_fd):
        name = 'native-workbench-diagnostics-' + secrets.token_hex(16) + '.zip'
        location = parent / name
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_BINARY', 0) | getattr(os, 'O_NOFOLLOW', 0)
        kwargs = {'dir_fd': directory_fd} if directory_fd is not None else {}
        target = name if directory_fd is not None else str(filesystem_path(location))
        descriptor = os.open(target, flags, 0o600, **kwargs)
        try:
            with os.fdopen(descriptor, 'wb') as output:
                output.write(payload)
                output.flush()
                os.fsync(output.fileno())
            if directory_fd is not None:
                actual, selected = os.fstat(directory_fd), parent.stat(follow_symlinks=False)
                _require((actual.st_dev, actual.st_ino) == (selected.st_dev, selected.st_ino))
        except BaseException:
            os.unlink(target, **kwargs)
            raise
    return location
