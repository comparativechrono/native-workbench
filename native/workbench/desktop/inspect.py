#!/usr/bin/env python3
"""Inspect desktop packaging and PE dependencies. Does not run Windows code."""
import configparser
import hashlib
import json
from pathlib import Path
import re
import struct
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def pe(path):
    data = path.read_bytes()
    assert data[:2] == b'MZ', path
    at = struct.unpack_from('<I', data, 60)[0]
    assert data[at:at + 4] == b'PE\0\0', path
    assert struct.unpack_from('<H', data, at + 4)[0] == 0x8664, path
    assert struct.unpack_from('<H', data, at + 24)[0] == 0x20b, path
    return {'path': str(path.relative_to(ROOT)), 'bytes': len(data),
            'sha256': hashlib.sha256(data).hexdigest(), 'machine': 'AMD64',
            'format': 'PE32+', 'subsystem': struct.unpack_from('<H', data, at + 24 + 68)[0],
            'timestamp': struct.unpack_from('<I', data, at + 8)[0]}


def inspect():
    exe = ROOT / 'build/desktop/NativeWorkbench.exe'
    report = {'application': pe(exe), 'native_desktop_execution_tested': False,
              'evidence': 'Cross-compilation and static package/PE checks only', 'packs': []}
    assert report['application']['subsystem'] == 2
    assert report['application']['timestamp'] == 0
    raw = exe.read_bytes()
    for marker in (b'Microsoft.Windows.Common-Controls', b'PerMonitorV2', b'asInvoker'):
        assert marker in raw, marker
    imports = subprocess.run(['objdump', '-p', str(exe)], check=True, capture_output=True, text=True).stdout
    dlls = re.findall(r'DLL Name:\s*(\S+)', imports)
    allowed = {'comctl32.dll', 'ole32.dll', 'shell32.dll', 'user32.dll', 'gdi32.dll', 'bcrypt.dll', 'kernel32.dll'}
    assert dlls
    for dll in dlls:
        assert dll.lower() in allowed or dll.lower().startswith('api-ms-win-crt-'), dll
    report['application']['imported_dlls'] = dlls
    report['application']['external_compiler_runtime_dlls_required'] = False
    for pack in sorted((ROOT / 'packs').iterdir()):
        cfg = configparser.ConfigParser(interpolation=None, strict=True)
        cfg.read(pack / 'pack.ini', encoding='utf-8')
        assert set(cfg.sections()) == {'pack', 'bwfastq', 'seqtk', 'minimap2'}
        assert cfg['pack']['format'] == '1' and cfg['pack']['platform'] == 'windows-x86_64'
        assert pack.name == cfg['pack']['id'] + '-' + cfg['pack']['version']
        tools = []
        for tool in ('bwfastq', 'seqtk', 'minimap2'):
            assert cfg[tool]['path'] == 'bin\\' + tool + '.exe'
            data = pe(pack / 'bin' / (tool + '.exe'))
            assert data['sha256'] == cfg[tool]['sha256']
            data['version'] = cfg[tool]['version']
            tools.append(data)
        assert (pack / 'licenses').is_dir()
        assert (pack / 'PACK-README.md').is_file()
        report['packs'].append({'id': cfg['pack']['id'], 'version': cfg['pack']['version'], 'tools': tools})
    for filename in ('START-WINDOWS.cmd', 'CHECK-WINDOWS.cmd'):
        content = (ROOT / filename).read_text().lower()
        assert 'nativeworkbench.exe' in content and 'powershell' not in content
        assert 'executionpolicy' not in content
    checks = re.findall(r'check\(L"([^"]+)"', (ROOT / 'desktop/validation.cpp').read_text())
    # Installed hash verification is recorded separately before the individual cases.
    report['native_check_names'] = ['Installed tool pack checksums'] + checks
    report['native_check_count'] = len(report['native_check_names'])
    assert report['native_check_count'] == 17
    destination = ROOT / 'results/desktop-build.json'
    destination.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({'desktop_bytes': len(raw), 'desktop_sha256': report['application']['sha256'],
                      'pack_tools_verified': 3 * len(report['packs']), 'native_check_count': report['native_check_count'],
                      'native_desktop_execution_tested': False}, indent=2))


if __name__ == '__main__':
    inspect()
