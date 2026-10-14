#!/usr/bin/env python3
"""Inspect the Windows artifact without claiming to execute it."""
import argparse
import hashlib
import json
from pathlib import Path
import struct
import subprocess


def inspect(executable: Path, module_path: Path, compiler: str) -> dict:
    image = executable.read_bytes()
    module = module_path.read_bytes()
    assert image[:2] == b'MZ', 'Missing DOS signature'
    pe = struct.unpack_from('<I', image, 0x3C)[0]
    assert image[pe:pe+4] == b'PE\0\0', 'Missing PE signature'
    machine, count, timestamp = struct.unpack_from('<HHI', image, pe+4)
    optional_size = struct.unpack_from('<H', image, pe+20)[0]
    optional = pe + 24
    assert machine == 0x8664, 'Expected AMD64'
    assert struct.unpack_from('<H', image, optional)[0] == 0x20B, 'Expected PE32+'
    sections = []
    section_table = optional + optional_size
    for index in range(count):
        at = section_table + 40*index
        name = image[at:at+8].split(b'\0')[0].decode('ascii')
        virtual_size, rva, raw_size, offset = struct.unpack_from('<IIII', image, at+8)
        flags = struct.unpack_from('<I', image, at+36)[0]
        sections.append({
            'name': name, 'rva': rva, 'virtual_size': virtual_size,
            'file_offset': offset, 'file_size': raw_size,
            'readable': bool(flags & 0x40000000),
            'writable': bool(flags & 0x80000000),
            'executable': bool(flags & 0x20000000),
        })

    def file_offset(rva):
        for section in sections:
            delta = rva-section['rva']
            if 0 <= delta < section['file_size']:
                return section['file_offset'] + delta
        raise ValueError(f'RVA is not backed by file data: {rva:#x}')

    def string_at(rva):
        at = file_offset(rva)
        end = image.index(b'\0', at)
        return image[at:end].decode('ascii')

    import_rva, import_size = struct.unpack_from('<II', image, optional+112+8)
    imports = []
    if import_rva:
        at = file_offset(import_rva)
        for index in range(import_size//20):
            entry = struct.unpack_from('<IIIII', image, at+20*index)
            if not any(entry):
                break
            lookup, _, _, name, address = entry
            functions = []
            table = file_offset(lookup or address)
            for n in range(65536):
                value = struct.unpack_from('<Q', image, table+8*n)[0]
                if not value:
                    break
                if value & (1 << 63):
                    functions.append({'ordinal': value & 0xFFFF})
                else:
                    functions.append(string_at(value+2))
            imports.append({'dll': string_at(name), 'functions': functions})

    offset = image.find(module)
    assert module and offset >= 0, 'Prepared module missing from executable'
    assert image.find(module, offset+1) == -1, 'Expected exactly one module copy'
    containing = [s for s in sections if s['file_offset'] <= offset and
                  offset+len(module) <= s['file_offset']+s['file_size']]
    assert len(containing) == 1
    section = containing[0]
    assert section['readable'] and section['executable'] and not section['writable']
    sha = lambda data: hashlib.sha256(data).hexdigest()
    version = subprocess.run([compiler, '--version'], check=True, capture_output=True,
                             text=True).stdout.splitlines()[0]
    return {
        'schema': 1,
        'artifact': executable.name,
        'format': 'PE32+', 'machine': 'AMD64',
        'size_bytes': len(image), 'sha256': sha(image),
        'pe_timestamp': timestamp,
        'subsystem': struct.unpack_from('<H', image, optional+68)[0],
        'image_size_bytes': struct.unpack_from('<I', image, optional+56)[0],
        'compiler': version,
        'runtime': 'Native Win32 APIs and Windows Universal C Runtime; no VM or WSL runtime',
        'module': {
            'source_artifact': module_path.name,
            'size_bytes': len(module), 'sha256': sha(module),
            'byte_for_byte_identical': True, 'copies_in_executable': 1,
            'section': section['name'], 'file_offset': offset,
            'rva': section['rva']+offset-section['file_offset'],
            'executable': True, 'writable': False,
            'abi': 'BW ABI 1; SysV x86-64 functions called by a Windows host',
            'unwind_limit': 'No Windows unwind metadata for the module; no exceptions or longjmp across ABI',
            'stack_limit': 'Guest module requires small prechecked stack frames; Windows stack probing is not supplied by the module',
        },
        'imports': imports, 'sections': sections,
        'native_windows_tested': False,
        'runtime_tested': False,
        'validation': 'Cross-compilation and static PE/module inspection only; native Windows runtime remains unverified',
    }


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--exe', type=Path, required=True)
    parser.add_argument('--module', type=Path, required=True)
    parser.add_argument('--compiler', required=True)
    args = parser.parse_args()
    report = inspect(args.exe, args.module, args.compiler)
    path = args.exe.parent / 'structural-report.json'
    path.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(f'PE and exact embedded module verified: {path}')
