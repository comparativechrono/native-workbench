#!/usr/bin/env python3
"""Static 0.4 release audit; never executes a Windows binary.

Run with Python 3.10+ and the packaging module after both desktop builds and
pack generation. The report covers build artifacts, not an assembled ZIP.
"""
import argparse
import configparser
from datetime import datetime, timezone
from email.parser import BytesParser
import hashlib
import json
from pathlib import Path, PureWindowsPath
import re
import struct
import sys
import xml.etree.ElementTree as ET
import zipfile

# The legacy desktop/inspect.py must not shadow Python's inspect standard library
# when packaging imports dataclasses. This audit imports no sibling modules.
sys.path = [entry for entry in sys.path
            if Path(entry or '.').resolve() != Path(__file__).resolve().parent]

from packaging.markers import default_environment
from packaging.requirements import Requirement
from packaging.specifiers import SpecifierSet
from packaging.utils import canonicalize_name

ROOT = Path(__file__).resolve().parents[1]
VERSION = '0.4.1'
PACK_VERSIONS = {'fastp': '0.4.1', 'research-variants': '0.4.1'}
PACK_TOOLS = {
    'reads': {'bwfastq', 'seqtk', 'paircheck'},
    'align': {'minimap2', 'paircheck'}, 'bam': {'samtools'},
    'variants': {'samtools', 'bcftools'},
    'variant-pipeline': {'seqtk', 'minimap2', 'samtools', 'bcftools', 'paircheck'},
    'trimming': {'python', 'paircheck'}, 'fastp': {'fastp', 'paircheck'},
    'bwa': {'bwa', 'samtools', 'paircheck'},
    'freebayes': {'freebayes', 'samtools', 'bcftools'},
    'research-variants': {'python', 'paircheck', 'seqtk', 'bwa', 'minimap2',
                          'samtools', 'bcftools', 'freebayes', 'fastp'},
}
TOOL_VERSIONS = dict(bwfastq='0.1.0-experiment', seqtk='1.4-r122',
    minimap2='2.28-r1209', samtools='1.24', bcftools='1.24', paircheck='1.0.1',
    bwa='0.7.19-r1273', freebayes='1.3.10', python='3.13.16-Cutadapt-5.2', fastp='1.3.7-reportfix1')
PYTHON_DISTRIBUTIONS = {'cutadapt': '5.2', 'dnaio': '1.2.4', 'xopen': '2.1.0',
    'isal': '1.8.0', 'zlib-ng': '1.0.0', 'backports-zstd': '1.7.0'}
SYSTEM_DLLS = {name + '.dll' for name in (
    'advapi32', 'bcrypt', 'bcryptprimitives', 'comctl32', 'comdlg32', 'crypt32', 'dwmapi',
    'gdi32', 'gdiplus', 'iphlpapi', 'kernel32', 'ntdll', 'ole32', 'oleaut32',
    'propsys', 'psapi', 'rpcrt4', 'shell32', 'user32', 'uxtheme', 'version',
    'winmm', 'ws2_32')}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def relative(path):
    return path.relative_to(ROOT).as_posix()


class PE:
    """Minimal bounded PE reader for headers, imports and embedded resources."""
    def __init__(self, path):
        self.path, self.data = path, path.read_bytes()
        require(self.data[:2] == b'MZ', f'{path}: missing DOS signature')
        offset = self.unpack('<I', 60)[0]
        require(self.data[offset:offset + 4] == b'PE\0\0', f'{path}: missing PE signature')
        machine, count, timestamp, _, _, optional_size, chars = self.unpack('<HHIIIHH', offset + 4)
        require(machine == 0x8664, f'{path}: expected AMD64')
        optional = offset + 24
        require(self.unpack('<H', optional)[0] == 0x20b, f'{path}: expected PE32+')
        self.image_base = self.unpack('<Q', optional + 24)[0]
        self.directories = [self.unpack('<II', optional + 112 + 8 * i)
                            for i in range(min(16, self.unpack('<I', optional + 108)[0]))]
        self.sections = []
        for index in range(count):
            at = optional + optional_size + 40 * index
            virtual_size, virtual_address, raw_size, raw_offset = self.unpack('<IIII', at + 8)
            self.sections.append((virtual_address, virtual_size, raw_size, raw_offset))
        self.headers_size = self.unpack('<I', optional + 60)[0]
        dll_chars = self.unpack('<H', optional + 70)[0]
        self.info = {'path': relative(path), 'bytes': len(self.data),
            'sha256': hashlib.sha256(self.data).hexdigest(), 'machine': 'AMD64',
            'format': 'PE32+', 'subsystem': self.unpack('<H', optional + 68)[0],
            'timestamp': timestamp, 'large_address_aware': bool(chars & 0x20),
            'dynamic_base': bool(dll_chars & 0x40),
            'high_entropy_va': bool(dll_chars & 0x20), 'nx_compatible': bool(dll_chars & 0x100),
            'authenticode_directory_present': bool(self.directory(4)[1]),
            'imported_dlls': self.imports(False), 'delay_imported_dlls': self.imports(True)}

    def unpack(self, fmt, at):
        require(0 <= at <= len(self.data) - struct.calcsize(fmt), f'{self.path}: truncated PE structure')
        return struct.unpack_from(fmt, self.data, at)

    def directory(self, index):
        return self.directories[index] if index < len(self.directories) else (0, 0)

    def offset(self, rva, size=1):
        if rva < self.headers_size and rva + size <= len(self.data):
            return rva
        for virtual, _, raw_size, raw in self.sections:
            delta = rva - virtual
            if 0 <= delta and delta + size <= raw_size:
                require(raw + delta + size <= len(self.data), f'{self.path}: truncated PE section')
                return raw + delta
        raise ValueError(f'{self.path}: unmapped RVA {rva:x}')

    def string(self, rva):
        at = self.offset(rva)
        end = self.data.find(b'\0', at, min(len(self.data), at + 4096))
        require(end >= at, f'{self.path}: unterminated import name')
        return self.data[at:end].decode('ascii')

    def imports(self, delayed):
        rva, size = self.directory(13 if delayed else 1)
        if not rva:
            return []
        width = 32 if delayed else 20
        names = []
        for index in range(size // width + 1):
            at = self.offset(rva + index * width, width)
            words = self.unpack('<' + 'I' * (width // 4), at)
            if not any(words):
                return sorted(set(names), key=str.lower)
            name_rva = words[1] if delayed else words[3]
            if delayed and not (words[0] & 1):
                name_rva -= self.image_base
            names.append(self.string(name_rva))
        raise ValueError(f'{self.path}: unterminated import directory')

    def resources(self, kind):
        rva, size = self.directory(2)
        if not rva:
            return []
        base = self.offset(rva, size)
        results = []

        def visit(relative_offset, depth):
            require(depth < 5 and relative_offset + 16 <= size, f'{self.path}: malformed resource directory')
            at = base + relative_offset
            named, numbered = self.unpack('<HH', at + 12)
            require(relative_offset + 16 + 8 * (named + numbered) <= size,
                    f'{self.path}: truncated resource entries')
            for index in range(named + numbered):
                name, entry = self.unpack('<II', at + 16 + index * 8)
                if depth == 0 and name != kind:
                    continue
                if entry & 0x80000000:
                    visit(entry & 0x7fffffff, depth + 1)
                else:
                    require(entry + 16 <= size, f'{self.path}: truncated resource payload descriptor')
                    payload, length, _, _ = self.unpack('<IIII', base + entry)
                    start = self.offset(payload, length)
                    results.append(self.data[start:start + length])
        visit(0, 0)
        return results

    def versions(self):
        resources = self.resources(16)
        if not resources:
            return None
        require(len(resources) == 1, f'{self.path}: ambiguous version resource')
        data = resources[0]
        at = data.find(struct.pack('<I', 0xFEEF04BD))
        require(at >= 0 and at + 52 <= len(data), f'{self.path}: missing fixed version information')
        words = struct.unpack_from('<13I', data, at)
        version = lambda ms, ls: '.'.join(map(str, (ms >> 16, ms & 65535, ls >> 16, ls & 65535)))
        return {'file_version': version(words[2], words[3]),
                'product_version': version(words[4], words[5]), 'file_flags': words[7]}


def dependencies(pe, bundled=None):
    bundled = bundled or {}
    result = []
    for name in pe.info['imported_dlls'] + pe.info['delay_imported_dlls']:
        lower = name.lower()
        system = lower in SYSTEM_DLLS or lower.startswith(('api-ms-win-', 'ext-ms-win-'))
        require(system or lower in bundled, f'{pe.path}: unbundled dependency {name}')
        result.append({'dll': name, 'resolution': 'Windows system' if system else relative(bundled[lower])})
    pe.info['dependency_resolution'] = result
    return pe.info


def desktop(path, subsystem, main=False):
    pe = PE(path)
    dependencies(pe)
    info = pe.info
    require(info['subsystem'] == subsystem and info['timestamp'] == 0,
            f'{path}: unexpected subsystem or nonzero build timestamp')
    for key in ('large_address_aware', 'dynamic_base', 'high_entropy_va', 'nx_compatible'):
        require(info[key], f'{path}: expected PE flag {key}')
    info['embedded_versions'] = pe.versions()
    manifests = pe.resources(24)
    info['embedded_manifest_present'] = bool(manifests)
    if main:
        require(info['embedded_versions'] == {'file_version': VERSION + '.0',
            'product_version': VERSION + '.0', 'file_flags': 0}, 'Desktop version resource mismatch')
        require(len(manifests) == 1, 'Desktop must have exactly one application manifest')
        manifest = ET.fromstring(manifests[0].rstrip(b'\0'))
        values = {}
        for element in manifest.iter():
            local = element.tag.rsplit('}', 1)[-1]
            if local == 'assemblyIdentity' and element.attrib.get('name') == 'NativeWorkbench.Desktop':
                values['identity'] = element.attrib
            elif local == 'assemblyIdentity' and element.attrib.get('name') == 'Microsoft.Windows.Common-Controls':
                values['common_controls_version'] = element.attrib.get('version')
            elif local == 'requestedExecutionLevel':
                values['execution_level'] = element.attrib
            elif local in ('dpiAware', 'dpiAwareness', 'longPathAware'):
                values[local] = element.text
        require(values['identity']['version'] == VERSION + '.0', 'Desktop assembly identity version mismatch')
        require(values['identity']['processorArchitecture'] == 'amd64', 'Desktop manifest architecture mismatch')
        require(values['execution_level'] == {'level': 'asInvoker', 'uiAccess': 'false'}, 'Desktop elevation flags changed')
        require(values['common_controls_version'] == '6.0.0.0', 'Common controls v6 manifest missing')
        require(values['dpiAware'] == 'true/pm' and values['dpiAwareness'] == 'PerMonitorV2, PerMonitor', 'DPI manifest flags changed')
        require(values['longPathAware'] == 'true', 'Long-path manifest flag missing')
        info['manifest'] = values
    else:
        info['resource_note'] = 'Companion build has no version or manifest resources; absence is recorded, not a runtime test.'
    return info


def private_python(folder, config):
    runtime = folder / 'runtime/python'
    pth = runtime / 'python313._pth'
    entries = [line.strip() for line in pth.read_text(encoding='utf-8').splitlines()
               if line.strip() and not line.lstrip().startswith('#')]
    require(entries == ['python313.zip', '.', 'packages'], f'{pth}: Python isolation paths changed')
    require(not any('import ' in line for line in entries), f'{pth}: site imports enabled')
    for entry in entries:
        require((runtime / entry).exists(), f'{pth}: missing isolated search path {entry}')
    require(not list(runtime.rglob('*.pyc')) and not list(runtime.rglob('__pycache__')),
            f'{runtime}: generated Python bytecode in release')
    with zipfile.ZipFile(runtime / 'python313.zip') as standard_library:
        require(standard_library.testzip() is None, 'Python standard library ZIP integrity failure')
        require('encodings/__init__.pyc' in standard_library.namelist(), 'Python encodings package missing')
    metadata = []
    installed = {}
    for path in sorted((runtime / 'packages').glob('*.dist-info')):
        fields = BytesParser().parsebytes((path / 'METADATA').read_bytes())
        wheel = BytesParser().parsebytes((path / 'WHEEL').read_bytes())
        name = canonicalize_name(fields['Name'])
        require(name not in installed, f'Duplicate Python distribution: {name}')
        installed[name] = fields['Version']
        tags = wheel.get_all('Tag', [])
        require(tags and all(tag in ('cp313-cp313-win_amd64', 'py3-none-any') for tag in tags),
                f'{name}: incompatible wheel tags {tags}')
        requires_python = fields.get('Requires-Python', '')
        require('3.13.16' in SpecifierSet(requires_python), f'{name}: Python version constraint failed')
        metadata.append({'name': name, 'version': fields['Version'], 'tags': tags,
            'requires_python': requires_python, 'requires_dist': fields.get_all('Requires-Dist', [])})
    require(installed == PYTHON_DISTRIBUTIONS, f'Private Python distribution inventory mismatch: {installed}')
    environment = default_environment()
    environment.update(implementation_name='cpython', implementation_version='3.13.16',
        os_name='nt', platform_machine='AMD64', platform_python_implementation='CPython',
        platform_system='Windows', python_full_version='3.13.16', python_version='3.13',
        sys_platform='win32', extra='')
    dependency_checks = []
    for distribution in metadata:
        for text in distribution['requires_dist']:
            requirement = Requirement(text)
            active = not requirement.marker or requirement.marker.evaluate(environment)
            dependency = canonicalize_name(requirement.name)
            version = installed.get(dependency)
            if active:
                require(version is not None and version in requirement.specifier,
                        f"{distribution['name']}: unmet dependency {text}")
            dependency_checks.append({'distribution': distribution['name'], 'requirement': text,
                'active_for_windows_runtime': active, 'installed_version': version})
    invocations = []
    for section in config.sections():
        if section.startswith('step:') and config[section].get('tool') == 'python':
            args = [config[section][f'arg.{i}'] for i in range(4)]
            require(args == ['-I', '-B', '-m', 'cutadapt'], f'{section}: Python isolation arguments changed')
            invocations.append(section)
    require(invocations, 'Private Python runtime has no declared Cutadapt invocation')
    return {'path': relative(runtime), 'python_version_declared': '3.13.16',
        'pth_path': relative(pth), 'pth_sha256': sha(pth), 'pth_entries': entries,
        'site_import_enabled': False, 'python_invocations_isolated': invocations,
        'stdlib_zip_crc_checked': True, 'distributions': metadata,
        'dependency_marker_environment': environment, 'dependency_checks': dependency_checks,
        'windows_runtime_executed': False}


def pack(folder, identity, tool_hashes):
    config = configparser.ConfigParser(interpolation=None, strict=True)
    config.read(folder / 'pack.ini', encoding='utf-8')
    require(config['pack']['id'] == identity and config['pack']['version'] == PACK_VERSIONS.get(identity, '0.4.0'),
            f'{folder}: pack identity mismatch')
    require(config['pack']['format'] == '2' and config['pack']['platform'] == 'windows-x86_64',
            f'{folder}: incompatible pack format/platform')
    actual_tools = {section[5:] for section in config.sections() if section.startswith('tool:')}
    require(actual_tools == PACK_TOOLS[identity], f'{folder}: tool inventory mismatch')
    declared, items = {}, []
    for section in config.sections():
        if not section.startswith(('tool:', 'asset:')):
            continue
        item = config[section]
        rel = item['path'].replace('\\', '/')
        winpath = PureWindowsPath(rel)
        require(not winpath.is_absolute() and not winpath.drive and '..' not in winpath.parts,
                f'{folder}: unsafe declared path {rel}')
        require(rel.lower() not in declared, f'{folder}: duplicate declared path {rel}')
        path = folder / rel
        require(path.is_file() and not path.is_symlink(), f'{path}: missing or symlinked payload')
        require(not any(parent.is_symlink() for parent in path.parents if parent != ROOT.parent),
                f'{path}: symlinked ancestor')
        digest = sha(path)
        require(re.fullmatch('[0-9a-f]{64}', item['sha256']) and digest == item['sha256'], f'{path}: hash mismatch')
        declared[rel.lower()] = path
        record = {'id': section.split(':', 1)[1], 'kind': section.split(':', 1)[0],
                  'path': rel, 'bytes': path.stat().st_size, 'sha256': digest}
        if section.startswith('tool:'):
            tool = section[5:]
            require(item['version'] == TOOL_VERSIONS[tool], f'{path}: declared tool version mismatch')
            require(tool not in tool_hashes or tool_hashes[tool] == digest, f'{tool}: inconsistent binaries across packs')
            tool_hashes[tool] = digest
            record['version_declared'] = item['version']
            record['version_executed'] = False
        items.append(record)
    inventory = []
    for path in sorted(folder.rglob('*')):
        require(not path.is_symlink(), f'{path}: symlink in pack')
        if path.is_file():
            rel = path.relative_to(folder).as_posix()
            require(rel.lower() in declared or rel in ('pack.ini', 'PACK-README.md') or rel.startswith('licenses/'),
                    f'{folder}: undeclared file {rel}')
            inventory.append(rel)
    require((folder / 'licenses').is_dir() and (folder / 'PACK-README.md').is_file(), f'{folder}: missing notices/readme')
    bundled = {path.name.lower(): path for path in declared.values() if path.suffix.lower() == '.dll'}
    binaries = []
    for path in declared.values():
        if path.suffix.lower() in ('.exe', '.dll', '.pyd'):
            binary = PE(path)
            binaries.append(dependencies(binary, bundled))
    workflows = [section.split(':', 1)[1] for section in config.sections() if section.startswith('workflow:')]
    result = {'id': identity, 'version': config['pack']['version'], 'path': relative(folder),
        'manifest_sha256': sha(folder / 'pack.ini'), 'workflow_ids': workflows,
        'tools_count': len(actual_tools), 'assets_count': len(items) - len(actual_tools),
        'declared_payloads': items, 'pack_file_count_including_notices': len(inventory),
        'undeclared_files': [], 'portable_executable_inspection': binaries}
    if 'python' in actual_tools:
        result['private_python'] = private_python(folder, config)
    return result


def inspect(report):
    report['application'] = desktop(ROOT / 'build/desktop/NativeWorkbench.exe', 2, main=True)
    report['pipeline_companion'] = desktop(ROOT / 'build/pipeline-checks/WindowsPipelineChecks.exe', 3)
    tool_hashes = {}
    report['packs'] = []
    for identity in sorted(PACK_TOOLS):
        report['packs'].append(pack(ROOT / 'packs' / f"{identity}-{PACK_VERSIONS.get(identity, '0.4.0')}", identity, tool_hashes))
    release_names = {f"{name}-{PACK_VERSIONS.get(name, '0.4.0')}" for name in PACK_TOOLS}
    report['excluded_workspace_pack_directories'] = sorted(path.name for path in (ROOT / 'packs').iterdir()
        if path.is_dir() and path.name not in release_names)
    report['workflow_count'] = sum(len(item['workflow_ids']) for item in report['packs'])
    require(report['workflow_count'] == 43, 'Expected 43 release workflows')
    report['pack_count'] = len(report['packs'])
    report['tool_entries_verified'] = sum(item['tools_count'] for item in report['packs'])
    report['asset_entries_verified'] = sum(item['assets_count'] for item in report['packs'])
    report['unique_tool_hashes'] = tool_hashes
    report['notes'] = [
        'Declared tool versions are checked against release pins; no tool --version command was executed.',
        'DLL inspection covers static and delay imports. It does not prove dynamic LoadLibrary calls or Windows loader behavior.',
        'Authenticode directory presence is metadata only; signatures and certificate chains are not validated.',
        'Older workspace packs listed as excluded are not part of the ten-pack 0.4 release.']


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'validation/desktop-build-0.4.1.json')
    args = parser.parse_args()
    report = {'release': VERSION, 'audit': 'static desktop, PE and declared pack inventory',
        'checked_at_utc': datetime.now(timezone.utc).isoformat(), 'status': 'failed',
        'native_desktop_execution_tested': False, 'native_windows_tool_execution_tested': False,
        'evidence': 'Static build artifact inspection only; this is not Windows runtime validation.'}
    try:
        inspect(report)
        report['status'] = 'passed'
    except (OSError, ValueError, KeyError, configparser.Error, struct.error, ET.ParseError, zipfile.BadZipFile) as error:
        report['error'] = str(error)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({key: report.get(key) for key in ('status', 'pack_count', 'workflow_count',
        'tool_entries_verified', 'asset_entries_verified', 'error')}, indent=2))
    print(f'Report: {args.output}')
    return 0 if report['status'] == 'passed' else 1


if __name__ == '__main__':
    sys.exit(main())
