#!/usr/bin/env python3
"""Read-only deployment inventory for a fresh, explicitly selected extraction.

Public API: ``inventory_tree(root: Path, role: str) -> dict``. Schema 1 returns
``role``, sorted ``files`` (path/size/SHA-256/componentIds), ``components``
(descriptor identities and declared versions/tools), ``executables`` (observed
format, bounded static PE machine/direct imports, parse and signature status),
``licenceFiles``, ``sourceAvailabilityFiles``, ``unknowns`` and ``limitations``.
Every path is relative to root, including updater blob aliases in ``destinations``.
Output contains no timestamps, absolute paths, host/user identifiers or network
observations. Identical extracted bytes yield identical output after relocation.

Use an untouched application, pack or updater extraction, never a live user
installation. Known user-data directories, links/reparse points, special files,
Windows-ambiguous paths and descriptor traversal are rejected. Descriptor claims
are compared with observed bytes; missing/wrong files remain explicit findings.
An inventory is not an installability, dependency-closure, Authenticode, licence
completeness, source-completeness, security or institutional approval decision.
The parser never loads an executable, follows a DLL search path or fetches a URL.
"""
from __future__ import annotations

import argparse
import configparser
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import struct
from typing import BinaryIO

MAX_FILES = 100_000
MAX_DEPTH = 48
MAX_METADATA_BYTES = 8 * 1024 * 1024
MAX_SECTIONS = 96
MAX_IMPORTS = 4096
MAX_DLL_NAME = 512
EXECUTABLE_SUFFIXES = {'.exe', '.dll', '.pyd', '.com', '.scr', '.cpl', '.sys', '.ocx'}
SCRIPT_SUFFIXES = {'.bat', '.cmd', '.ps1', '.py', '.pyw', '.sh', '.vbs', '.js'}
PRIVATE_DIRS = {'user-data', 'results', 'references', 'updates', 'reference-library'}
MACHINES = {0x14c: 'x86', 0x8664: 'x86-64', 0x1c0: 'ARM', 0x1c4: 'ARMv7',
            0xaa64: 'ARM64', 0xa641: 'ARM64EC', 0xa64e: 'ARM64X', 0x200: 'IA64'}


class InventoryError(ValueError):
    """Unsafe extraction, descriptor or unbounded input; no approval inferred."""


class PEError(ValueError):
    """Malformed or unsupported static PE metadata."""


def _safe_relative(value: object) -> str:
    if not isinstance(value, str) or not value or len(value) > 4096:
        raise InventoryError('Descriptor path must be a nonempty relative path')
    parts = value.split('/')
    if ('\\' in value or ':' in value or value.startswith('/') or
            any(part in ('', '.', '..') or part.endswith((' ', '.')) or
                any(ord(c) < 32 or c in '<>"|?*' for c in part) or
                re.fullmatch(r'(?i)(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?', part)
                for part in parts)):
        raise InventoryError('Unsafe or Windows-ambiguous relative path: ' + repr(value))
    return value


def _is_link(info: os.stat_result) -> bool:
    return stat.S_ISLNK(info.st_mode) or bool(getattr(info, 'st_file_attributes', 0) & 0x400)


def _ordinary_path(path: Path, relative: str) -> os.stat_result:
    try:
        info = path.lstat()
    except OSError:
        raise InventoryError('Cannot inspect inventory entry: ' + relative) from None
    if _is_link(info):
        raise InventoryError('Link or reparse point is not an extraction file: ' + relative)
    return info


def _root(root: Path) -> Path:
    # Check the lexical ancestors before resolving: resolve() alone hides a link.
    absolute = Path(os.path.abspath(root))
    for ancestor in reversed((absolute, *absolute.parents)):
        info = _ordinary_path(ancestor, '.')
        if not stat.S_ISDIR(info.st_mode):
            raise InventoryError('Inventory root must be an ordinary directory')
    return absolute


def _walk(root: Path) -> list[Path]:
    files = []
    folded: set[str] = set()
    stack = [(root, 0)]
    while stack:
        directory, depth = stack.pop()
        if depth > MAX_DEPTH:
            raise InventoryError('Extraction exceeds inventory directory-depth limit')
        try:
            entries = sorted(directory.iterdir(), key=lambda p: p.name)
        except OSError:
            raise InventoryError('Cannot enumerate extraction directory') from None
        for path in entries:
            name = _safe_relative(path.relative_to(root).as_posix())
            key = name.casefold()
            if key in folded:
                raise InventoryError('Case-insensitive path collision: ' + name)
            folded.add(key)
            if len(folded) > MAX_FILES:
                raise InventoryError('Extraction exceeds inventory entry limit')
            info = _ordinary_path(path, name)
            if stat.S_ISDIR(info.st_mode):
                if depth == 0 and path.name.casefold() in PRIVATE_DIRS:
                    raise InventoryError('Use a fresh extraction, not user data: ' + name)
                stack.append((path, depth + 1))
            elif stat.S_ISREG(info.st_mode):
                files.append(path)
            else:
                raise InventoryError('Special file is not an extraction file: ' + name)
    return sorted(files, key=lambda p: p.relative_to(root).as_posix())


def _open_file(root: Path, name: str) -> tuple[BinaryIO, os.stat_result]:
    path = root / name
    # Recheck ancestors on every open rather than accepting an earlier tree walk.
    if not stat.S_ISDIR(_ordinary_path(root, '.').st_mode):
        raise InventoryError('Inventory root changed during inspection')
    for depth in range(1, len(PurePosixPath(name).parts)):
        ancestor = root.joinpath(*PurePosixPath(name).parts[:depth])
        if not stat.S_ISDIR(_ordinary_path(ancestor, ancestor.relative_to(root).as_posix()).st_mode):
            raise InventoryError('Inventory directory changed during inspection')
    before = _ordinary_path(path, name)
    if not stat.S_ISREG(before.st_mode):
        raise InventoryError('Inventory file changed during inspection: ' + name)
    try:
        descriptor = os.open(path, os.O_RDONLY | getattr(os, 'O_BINARY', 0) | getattr(os, 'O_NOFOLLOW', 0))
        stream = os.fdopen(descriptor, 'rb')
    except OSError:
        raise InventoryError('Cannot read ordinary inventory file: ' + name) from None
    current = os.fstat(stream.fileno())
    if ((before.st_dev, before.st_ino) != (current.st_dev, current.st_ino) or
            not stat.S_ISREG(current.st_mode) or _is_link(current)):
        stream.close()
        raise InventoryError('Inventory file changed during inspection: ' + name)
    return stream, current


def _unchanged(before: os.stat_result, after: os.stat_result, name: str) -> None:
    if ((before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns) !=
            (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns)):
        raise InventoryError('Inventory file changed during inspection: ' + name)


def _metadata(root: Path, name: str, records: dict) -> bytes:
    if records[name]['size'] > MAX_METADATA_BYTES:
        raise InventoryError('Descriptor exceeds metadata byte limit: ' + name)
    stream, before = _open_file(root, name)
    with stream:
        raw = stream.read(MAX_METADATA_BYTES + 1)
        _unchanged(before, os.fstat(stream.fileno()), name)
    if hashlib.sha256(raw).hexdigest() != records[name]['sha256']:
        raise InventoryError('Descriptor changed after inventory hashing: ' + name)
    return raw


def _json(root: Path, name: str, records: dict) -> dict:
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('duplicate key')
            result[key] = value
        return result
    raw = _metadata(root, name, records)
    try:
        value = json.loads(raw, object_pairs_hook=unique)
    except (UnicodeError, ValueError, RecursionError):
        raise InventoryError('Malformed JSON descriptor: ' + name) from None
    if not isinstance(value, dict):
        raise InventoryError('Descriptor is not a JSON object: ' + name)
    return value


def _text(value: object) -> str | None:
    return value if isinstance(value, str) and value.strip() and len(value) <= 4096 else None


class _PEReader:
    def __init__(self, stream: BinaryIO, size: int):
        self.stream, self.size = stream, size

    def get(self, offset: int, length: int) -> bytes:
        if offset < 0 or length < 0 or offset > self.size or length > self.size - offset:
            raise PEError('PE field lies outside file bounds')
        self.stream.seek(offset)
        raw = self.stream.read(length)
        if len(raw) != length:
            raise PEError('Truncated PE field')
        return raw


def _parse_pe(stream: BinaryIO, size: int) -> dict:
    """Read only bounded headers and ordinary import descriptors (not a loader)."""
    reader = _PEReader(stream, size)
    dos = reader.get(0, 64)
    offset = struct.unpack_from('<I', dos, 60)[0]
    if offset < 64:
        raise PEError('PE header overlaps DOS header')
    header = reader.get(offset, 24)
    if header[:4] != b'PE\0\0':
        raise PEError('MZ image has no PE signature at its declared offset')
    machine, count = struct.unpack_from('<HH', header, 4)
    optional_size = struct.unpack_from('<H', header, 20)[0]
    if not 1 <= count <= MAX_SECTIONS:
        raise PEError('PE section count exceeds supported bounds')
    if not 96 <= optional_size <= 4096:
        raise PEError('PE optional-header size exceeds supported bounds')
    optional = reader.get(offset + 24, optional_size)
    magic = struct.unpack_from('<H', optional)[0]
    if magic not in (0x10b, 0x20b):
        raise PEError('Unsupported PE optional-header magic')
    directory_offset = 96 if magic == 0x10b else 112
    if optional_size < directory_offset:
        raise PEError('Truncated PE optional header')
    directory_count = struct.unpack_from('<I', optional, directory_offset - 4)[0]
    if directory_count > (optional_size - directory_offset) // 8:
        raise PEError('PE data-directory count exceeds optional header')
    header_size = struct.unpack_from('<I', optional, 60)[0]
    table_offset = offset + 24 + optional_size
    section_bytes = reader.get(table_offset, count * 40)
    if not table_offset + count * 40 <= header_size <= size:
        raise PEError('Invalid PE SizeOfHeaders')
    sections = []
    for index in range(count):
        virtual_size, address, raw_size, pointer = struct.unpack_from('<IIII', section_bytes, index * 40 + 8)
        if raw_size and (pointer < header_size or pointer > size or raw_size > size - pointer):
            raise PEError('PE section raw data lies outside valid file bounds')
        if address + max(virtual_size, raw_size) > 0x100000000:
            raise PEError('PE section virtual range overflows')
        sections.append((address, raw_size, pointer))

    def rva(value: int, length: int) -> int:
        matches = []
        if value < header_size and length <= header_size - value:
            matches.append(value)
        for address, raw_size, pointer in sections:
            if address <= value and value - address < raw_size and length <= raw_size - (value - address):
                matches.append(pointer + value - address)
        if len(matches) != 1:
            raise PEError('PE RVA is unmapped, truncated or ambiguous')
        return matches[0]

    imports = []
    if directory_count > 1:
        import_rva, import_size = struct.unpack_from('<II', optional, directory_offset + 8)
        if bool(import_rva) != bool(import_size):
            raise PEError('Inconsistent PE import-directory address/size')
        if import_rva:
            if import_size < 20 or import_size > (MAX_IMPORTS + 1) * 20:
                raise PEError('PE import-directory size exceeds supported bounds')
            # Validate the complete declared directory, not just descriptors used.
            directory = reader.get(rva(import_rva, import_size), import_size)
            terminated = False
            for index in range(min(import_size // 20, MAX_IMPORTS + 1)):
                descriptor = directory[index * 20:(index + 1) * 20]
                if not any(descriptor):
                    terminated = True
                    break
                if index >= MAX_IMPORTS:
                    raise PEError('PE import count exceeds supported bounds')
                name_rva = struct.unpack_from('<I', descriptor, 12)[0]
                if not name_rva:
                    raise PEError('PE import descriptor has no DLL name')
                name = bytearray()
                for byte_index in range(MAX_DLL_NAME + 1):
                    byte = reader.get(rva(name_rva + byte_index, 1), 1)[0]
                    if byte == 0:
                        break
                    if byte_index == MAX_DLL_NAME or not 32 <= byte < 127:
                        raise PEError('PE imported DLL name is not bounded printable ASCII')
                    name.append(byte)
                if not name:
                    raise PEError('PE imported DLL name is empty')
                imports.append(name.decode('ascii'))
            if not terminated:
                raise PEError('PE import directory lacks a terminating descriptor')
    certificate = False
    if directory_count > 4:
        cert_offset, cert_size = struct.unpack_from('<II', optional, directory_offset + 32)
        if bool(cert_offset) != bool(cert_size):
            raise PEError('Inconsistent PE certificate-table address/size')
        if cert_offset:
            if cert_offset > size or cert_size > size - cert_offset:
                raise PEError('PE certificate table lies outside file bounds')
            certificate = True
    delayed = False
    if directory_count > 13:
        delayed = any(struct.unpack_from('<II', optional, directory_offset + 13 * 8))
    return {'machine': MACHINES.get(machine, 'unknown'), 'machineCode': f'0x{machine:04x}',
            'peKind': 'PE32+' if magic == 0x20b else 'PE32',
            'directImports': sorted(set(imports), key=lambda name: (name.casefold(), name)),
            'certificateTablePresent': certificate, 'delayImportDirectoryPresent': delayed,
            'parseStatus': 'parsed'}


def _executable(stream: BinaryIO, size: int, path: str) -> dict | None:
    stream.seek(0)
    first = stream.read(64)
    suffix = PurePosixPath(path).suffix.lower()
    result = {'path': path, 'signatureStatus': 'not-checked', 'machine': None,
              'directImports': None, 'parseStatus': 'not-applicable'}
    if first.startswith(b'MZ'):
        result['format'] = 'MZ/PE-candidate'
        if first.startswith(b"MZqFpD='"):
            result['containerObservation'] = 'Cosmopolitan APE signature with Windows PE view'
        try:
            result.update(_parse_pe(stream, size))
            result['format'] = 'PE'
        except PEError as error:
            result.update(parseStatus='error', parseError=str(error))
    elif first.startswith(b'\x7fELF'):
        result.update(format='ELF', parseStatus='format-only')
    elif first[:4] in (b'\xfe\xed\xfa\xce', b'\xce\xfa\xed\xfe', b'\xfe\xed\xfa\xcf',
                       b'\xcf\xfa\xed\xfe', b'\xbe\xba\xfe\xca'):
        result.update(format='Mach-O-or-fat', parseStatus='format-only')
    elif first[:4] == b'\xca\xfe\xba\xbe':
        result.update(format='fat-Mach-O-or-Java-class', parseStatus='format-only')
    elif first.startswith(b'\x00asm'):
        result.update(format='WebAssembly', parseStatus='format-only')
    elif first.startswith(b'#!') or suffix in SCRIPT_SUFFIXES:
        result.update(format='script', parseStatus='format-only')
    elif suffix == '.jar':
        result.update(format='Java-archive-candidate', parseStatus='format-only')
    elif suffix in EXECUTABLE_SUFFIXES:
        result.update(format='unknown', parseStatus='unrecognized-executable-suffix')
    else:
        return None
    return result


def _claim(name: str, declaration: dict, records: dict) -> dict:
    name = _safe_relative(name)
    result = {'path': name, 'declaredSha256': _text(declaration.get('sha256')),
              'declaredSize': declaration.get('bytes', declaration.get('size'))}
    actual = records.get(name)
    if actual is None:
        result['status'] = 'missing'
    elif result['declaredSha256'] is None:
        result['status'] = 'identity-unknown'
    elif actual['sha256'] != result['declaredSha256']:
        result['status'] = 'sha256-mismatch'
    elif result['declaredSize'] is not None and actual['size'] != result['declaredSize']:
        result['status'] = 'size-mismatch'
    else:
        result['status'] = 'verified'
    return result


def _file_ref(record: dict) -> dict:
    return {key: record[key] for key in ('path', 'size', 'sha256')}


def _licence_path(name: str) -> bool:
    path = PurePosixPath(name)
    return (any(part.casefold() in ('licenses', 'licences', 'notices') for part in path.parts[:-1]) or
            bool(re.search(r'(?i)(?:^|[-_.])(licen[cs]e|copying|notice)(?:$|[-_.])', path.name)))


def _source_path(name: str) -> bool:
    return PurePosixPath(name).name.casefold() in ('source-availability.json', 'source-availability.txt',
                                                'source-recovery.json', 'r-runtime-sources.md')


def inventory_tree(root: Path, role: str) -> dict:
    """Inventory only the selected untouched extraction; see module schema above."""
    if not isinstance(role, str) or not re.fullmatch(r'[a-z][a-z0-9-]{0,63}', role):
        raise InventoryError('Role must be a short lowercase descriptive token')
    root = _root(root)
    markers = ('manifest.json', 'update-inventory.json', 'pack.ini', 'workbench-pack.json')
    if not any((root / name).exists() for name in markers):
        raise InventoryError('Choose a fresh application, updater or pack extraction root')
    paths = _walk(root)
    records, executable_records = {}, {}
    for path in paths:
        name = path.relative_to(root).as_posix()
        stream, before = _open_file(root, name)
        with stream:
            digest = hashlib.sha256()
            size = 0
            while chunk := stream.read(1024 * 1024):
                digest.update(chunk)
                size += len(chunk)
            binary = _executable(stream, size, name)
            _unchanged(before, os.fstat(stream.fileno()), name)
        _unchanged(before, _ordinary_path(path, name), name)
        records[name] = {'path': name, 'size': size, 'sha256': digest.hexdigest(), 'componentIds': []}
        if binary is not None:
            executable_records[name] = binary
    components, unknowns = [], []
    aliases: dict[str, list[str]] = {}

    def component(identifier, kind, name, version, descriptor):
        value = {'id': identifier, 'kind': kind, 'name': name, 'version': version,
                 'descriptor': _file_ref(records[descriptor]) if descriptor else None,
                 'metadataStatus': 'declared' if descriptor else 'unknown',
                 'licenceExpression': None, 'sourceCompleteness': 'not-assessed',
                 'tools': [], 'fileClaims': []}
        components.append(value)
        if version is None:
            unknowns.append({'componentId': identifier, 'field': 'version', 'status': 'unknown'})
        return value

    def own(identifier, names):
        for name in names:
            if name in records and identifier not in records[name]['componentIds']:
                records[name]['componentIds'].append(identifier)

    if 'manifest.json' in records:
        descriptor = _json(root, 'manifest.json', records)
        app = component('application', 'application', 'Native Workbench', _text(descriptor.get('version')), 'manifest.json')
        entries = descriptor.get('files', [])
        if not isinstance(entries, list):
            raise InventoryError('Application manifest files must be an array')
        seen = set()
        for entry in entries:
            if not isinstance(entry, dict):
                raise InventoryError('Malformed application manifest file claim')
            name = _safe_relative(entry.get('path'))
            if name.casefold() in seen:
                raise InventoryError('Duplicate application file claim: ' + name)
            seen.add(name.casefold())
            # Published core ownership is deliberately independent of packs/data.
            if PurePosixPath(name).parts[0].casefold() in PRIVATE_DIRS | {'packs'}:
                raise InventoryError('Application core cannot claim independent pack/user files: ' + name)
            app['fileClaims'].append(_claim(name, entry, records))
            own('application', [name])
        own('application', ['manifest.json'])
        if not entries:
            unknowns.append({'componentId': 'application', 'field': 'fileClaims', 'status': 'unknown'})

    for name in records:
        if PurePosixPath(name).name != 'pack.ini':
            continue
        # Do not treat an arbitrary nested copy as an installed pack descriptor.
        parts = PurePosixPath(name).parts
        if not (name == 'pack.ini' or name == 'pack/pack.ini' or
                (len(parts) == 3 and parts[0] == 'packs')):
            continue
        parser = configparser.ConfigParser(interpolation=None, strict=True)
        try:
            parser.read_string(_metadata(root, name, records).decode('utf-8-sig'))
        except (configparser.Error, UnicodeError):
            raise InventoryError('Malformed pack descriptor: ' + name) from None
        prefix = name[:-len('pack.ini')]
        declared = dict(parser['pack']) if parser.has_section('pack') else {}
        identifier = 'pack:' + (prefix.rstrip('/') or '.')
        pack = component(identifier, 'pack', _text(declared.get('name')), _text(declared.get('version')), name)
        pack['packId'] = _text(declared.get('id'))
        pack['platform'] = _text(declared.get('platform'))
        if not declared:
            pack['metadataStatus'] = 'unknown'
            unknowns.append({'componentId': identifier, 'field': 'pack', 'status': 'unknown'})
        own(identifier, [item for item in records if item.startswith(prefix)])
        for section in sorted(parser.sections()):
            if not section.startswith('tool:'):
                continue
            declaration = dict(parser[section])
            tool_path = declaration.get('path')
            claim = _claim(prefix + _safe_relative(tool_path), declaration, records) if tool_path else None
            pack['tools'].append({'id': section[5:], 'version': _text(declaration.get('version')),
                                  'file': claim, 'versionStatus': 'declared' if _text(declaration.get('version')) else 'unknown'})
            if claim is not None:
                pack['fileClaims'].append(claim)
            else:
                unknowns.append({'componentId': identifier, 'tool': section[5:], 'field': 'path', 'status': 'unknown'})

    if 'workbench-pack.json' in records:
        envelope = _json(root, 'workbench-pack.json', records)
        container = component('pack-envelope', 'pack-archive', _text(envelope.get('id')),
                              _text(envelope.get('version')), 'workbench-pack.json')
        container['packId'] = _text(envelope.get('id'))
        container['minimumAppVersion'] = _text(envelope.get('minAppVersion'))
        container['manifestClaim'] = _claim('pack/pack.ini', {'sha256': envelope.get('manifestSha256')}, records)
        entries = envelope.get('files', [])
        if not isinstance(entries, list):
            raise InventoryError('Pack envelope files must be an array')
        seen = set()
        for entry in entries:
            if not isinstance(entry, dict):
                raise InventoryError('Malformed pack envelope file claim')
            name = 'pack/' + _safe_relative(entry.get('path'))
            if name.casefold() in seen:
                raise InventoryError('Duplicate pack envelope file claim: ' + name)
            seen.add(name.casefold())
            container['fileClaims'].append(_claim(name, entry, records))
            own('pack-envelope', [name])
        own('pack-envelope', ['workbench-pack.json'])

    if 'update-inventory.json' in records:
        descriptor = _json(root, 'update-inventory.json', records)
        recipe_name = 'update/update-manifest.json'
        recipe = _json(root, recipe_name, records) if recipe_name in records else {}
        updater = component('updater', 'updater', 'Native Workbench core updater',
                            _text(recipe.get('target_version')), 'update-inventory.json')
        updater['baseVersion'] = _text(recipe.get('base_version'))
        updater['recipe'] = _file_ref(records[recipe_name]) if recipe_name in records else None
        entries = descriptor.get('files', [])
        if not isinstance(entries, list):
            raise InventoryError('Updater inventory files must be an array')
        seen = set()
        for entry in entries:
            if not isinstance(entry, dict):
                raise InventoryError('Malformed updater inventory file claim')
            name = _safe_relative(entry.get('path'))
            if name.casefold() in seen:
                raise InventoryError('Duplicate updater inventory file claim: ' + name)
            seen.add(name.casefold())
            updater['fileClaims'].append(_claim(name, entry, records))
            own('updater', [name])
        own('updater', ['update-inventory.json'])
        operations = recipe.get('operations', [])
        if not isinstance(operations, list):
            raise InventoryError('Updater operations must be an array')
        destinations_seen = set()
        for operation in operations:
            if not isinstance(operation, dict):
                raise InventoryError('Malformed updater operation')
            destination = _safe_relative(operation.get('path'))
            if PurePosixPath(destination).parts[0].casefold() in PRIVATE_DIRS | {'packs'}:
                raise InventoryError('Core update cannot claim independent pack/user files: ' + destination)
            if destination.casefold() in destinations_seen:
                raise InventoryError('Duplicate updater destination: ' + destination)
            destinations_seen.add(destination.casefold())
            blob = operation.get('blob')
            if not isinstance(blob, str) or not re.fullmatch('[0-9a-f]{64}', blob):
                raise InventoryError('Updater blob must be a SHA-256 filename')
            name = 'update/blobs/' + blob
            updater['fileClaims'].append({**_claim(name, operation, records), 'destination': destination})
            aliases.setdefault(name, []).append(destination)
        for name, destinations in aliases.items():
            if name not in executable_records and name in records:
                stream, before = _open_file(root, name)
                with stream:
                    binary = None
                    for destination in sorted(destinations):
                        binary = _executable(stream, records[name]['size'], destination)
                        if binary is not None:
                            break
                    _unchanged(before, os.fstat(stream.fileno()), name)
                if binary:
                    binary['path'] = name
                    executable_records[name] = binary

    runtime_files = [name for name in records if name.startswith('runtime/python/')]
    if runtime_files:
        component('private-python-runtime', 'runtime', 'Private Python runtime', None, None)
        own('private-python-runtime', runtime_files)

    licence_files, source_files = [], []
    for name, record in records.items():
        destinations = sorted(set(aliases.get(name, [])))
        candidates = [name, *destinations]
        if destinations:
            record['destinations'] = destinations
        if any(_licence_path(candidate) for candidate in candidates):
            licence_files.append({**_file_ref(record), 'componentIds': sorted(record['componentIds']),
                                  **({'destinations': destinations} if destinations else {})})
        if any(_source_path(candidate) for candidate in candidates):
            source_files.append({**_file_ref(record), 'componentIds': sorted(record['componentIds']),
                                 **({'destinations': destinations} if destinations else {})})
        record['componentIds'].sort()
        if not record['componentIds']:
            unknowns.append({'path': name, 'field': 'component', 'status': 'unknown'})
        if name in executable_records:
            executable_records[name]['componentIds'] = record['componentIds'][:]
            if destinations:
                executable_records[name]['destinations'] = destinations
    for item in components:
        item['fileClaims'].sort(key=lambda claim: (claim['path'], claim.get('destination', '')))
        item['licenceFiles'] = [entry['path'] for entry in licence_files if item['id'] in entry['componentIds']]
        item['sourceAvailabilityFiles'] = [entry['path'] for entry in source_files if item['id'] in entry['componentIds']]
    if not licence_files:
        unknowns.append({'field': 'licenceFiles', 'status': 'none-observed'})
    if not source_files:
        unknowns.append({'field': 'sourceAvailabilityFiles', 'status': 'none-observed'})
    return {'schema': 1, 'role': role, 'scope': 'fresh-selected-extraction',
            'files': list(records.values()), 'components': sorted(components, key=lambda item: item['id']),
            'executables': [executable_records[name] for name in sorted(executable_records)],
            'licenceFiles': licence_files, 'sourceAvailabilityFiles': source_files,
            'unknowns': sorted(unknowns, key=lambda item: json.dumps(item, sort_keys=True)),
            'limitations': [
                'Only the explicitly selected extraction is inventoried; no installed-machine scan is performed.',
                'Declared component/tool versions are metadata observations, not executed version probes.',
                'Private runtime version is unknown without an explicit version descriptor; filenames do not prove a patch version.',
                'PE imports are ordinary direct static imports only; delay/dynamic loads, API-set resolution, transitive dependencies and dependency availability are not assessed.',
                'PE parse errors retain unknown imports rather than implying an empty dependency list.',
                'Authenticode signatures and publisher trust were not checked; a certificate table alone does not establish a valid signature.',
                'Licence/source paths identify included material; no SPDX licence, completeness, legal conclusion or institutional approval is inferred.',
                'Source-availability documents may name external archives; this inventory does not fetch or establish their availability.',
                'Static format inspection does not establish native execution, scientific validity or security.'
            ]}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--role', required=True)
    parser.add_argument('--output', type=Path, help='New JSON path outside the inspected extraction; stdout if omitted')
    args = parser.parse_args()
    if args.output and args.output.resolve().is_relative_to(args.root.resolve()):
        parser.error('Write the report outside the inspected extraction')
    report = inventory_tree(args.root, args.role)
    text = json.dumps(report, indent=2, sort_keys=True) + '\n'
    if args.output:
        with args.output.open('x', encoding='utf-8') as stream:
            stream.write(text)
    else:
        print(text, end='')


if __name__ == '__main__':
    main()
