"""Versioned local pack installation and opt-in, signed catalogue downloads.

No network is used at construction or while reading the default snapshot. An
explicit source import establishes trust; refreshing and installing are separate
user actions. The host owns background threads and calls these synchronous APIs.
"""
from __future__ import annotations

from datetime import datetime, timezone
import errno
import hashlib
import http.client
import json
import os
import ntpath
from pathlib import Path
import re
import socket
import ssl
import stat
import tempfile
import threading
import time
import urllib.error
import urllib.request
from urllib.parse import urlsplit
import zipfile

try:
    from .app_version import APP_VERSION, PACK_API
    from .catalog import ID, VERSION, SHA, _relative, load_pack, load_catalog
    from .pack_security import PackError, require, strict_json, public_key, key_fingerprint, signed_payload, https_url
except ImportError:
    from app_version import APP_VERSION, PACK_API
    from catalog import ID, VERSION, SHA, _relative, load_pack, load_catalog
    from pack_security import PackError, require, strict_json, public_key, key_fingerprint, signed_payload, https_url

MAX_PACK_BYTES = 1024 * 1024 * 1024
MAX_ARCHIVE_BYTES = MAX_PACK_BYTES + 8 * 1024 * 1024
MAX_FILES = 2000
MAX_CATALOG_BYTES = 4 * 1024 * 1024
CHUNK = 1024 * 1024
PLATFORM = 'windows-x86_64'


class PackCancelled(PackError, InterruptedError):
    pass


def cancelled(cancel):
    if cancel is not None and cancel.is_set():
        raise PackCancelled('Pack installation cancelled before publication')


def _event(callback, phase, **fields):
    if callback:
        callback({'phase': phase, **fields})


def _text(value, maximum, empty=False):
    return isinstance(value, str) and (empty or bool(value)) and len(value) <= maximum and all(ord(c) >= 32 and ord(c) != 127 for c in value)


def _version(value):
    require(isinstance(value, str) and VERSION.fullmatch(value), 'Invalid semantic version')
    return tuple(map(int, value.split('.')))


def ordinary_windows_path(value):
    slash = chr(92)
    value = os.fspath(value).replace('/', slash)
    prefix = slash*2+'?'+slash
    if value.upper().startswith((prefix+'UNC'+slash).upper()):
        return slash*2+value[8:]
    if value.startswith(prefix):
        value = value[4:]
        require(len(value)>=3 and value[0].isalpha() and value[1:3]==':'+slash,
                'Unsupported Windows filesystem namespace')
    require(not value.startswith((slash*2+'.'+slash,slash+'??'+slash)), 'Windows device paths are not supported')
    return value


def extended_windows_path(value):
    slash = chr(92)
    ordinary = ordinary_windows_path(value)
    absolute = ntpath.normpath(ntpath.abspath(ordinary))
    prefix = slash*2+'?'+slash
    if absolute.startswith(slash*2):
        result = prefix+'UNC'+slash+absolute[2:]
    else:
        require(len(absolute)>=3 and absolute[0].isalpha() and absolute[1:3]==':'+slash,
                'Expected an absolute Windows filesystem path')
        result = prefix+absolute
    require(len(result) < 32767, 'Windows filesystem path is too long')
    return result


def filesystem_path(value):
    """Use Windows long-path IO without assuming a machine registry setting."""
    return Path(extended_windows_path(value)) if os.name == 'nt' else Path(value)


def _safe_directory(path):
    path = filesystem_path(path)
    require(not any(p.is_symlink() or (hasattr(p, 'is_junction') and p.is_junction()) for p in (path, *path.parents)), 'Pack manager folders cannot use links or junctions')
    path.mkdir(parents=True, exist_ok=True)
    require(path.is_dir(), 'Expected a pack manager directory')
    return path


def _atomic_bytes(path, data):
    path = filesystem_path(path)
    _safe_directory(path.parent)
    require(not path.is_symlink(), 'Pack manager state cannot be a symbolic link')
    handle, temporary = tempfile.mkstemp(prefix='_write-', dir=path.parent)
    try:
        with os.fdopen(handle, 'wb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def validate_source(value):
    require(isinstance(value, dict) and set(value) == {'schema','id','name','catalogUrl','publicKey','allowedHosts'}, 'Invalid catalogue source definition')
    require(type(value['schema']) is int and value['schema'] == 1, 'Unsupported source format')
    require(isinstance(value['id'], str) and ID.fullmatch(value['id']), 'Invalid source identifier')
    require(_text(value['name'], 100), 'Invalid source name')
    hosts = value['allowedHosts']
    require(isinstance(hosts, list) and 1 <= len(hosts) <= 16 and len(set(hosts)) == len(hosts), 'Expected 1 to 16 distinct approved hosts')
    require(all(isinstance(host, str) and host == host.lower() and len(host) <= 253 and re.fullmatch(r'[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?', host) and '..' not in host for host in hosts), 'Invalid approved host')
    https_url(value['catalogUrl'], hosts)
    public_key(value['publicKey'])
    return value


def validate_entry(entry, hosts):
    fields = {'id','name','version','toolVersions','description','category','platform','packApi','minAppVersion','downloadURL','size','sha256','manifestSha256'}
    require(isinstance(entry, dict) and set(entry) == fields, 'Invalid catalogue pack entry')
    require(isinstance(entry['id'], str) and ID.fullmatch(entry['id']), 'Invalid pack identifier')
    _version(entry['version']); _version(entry['minAppVersion'])
    for field, maximum in (('name',100), ('description',2048), ('category',100), ('platform',64)):
        require(_text(entry[field], maximum, field == 'description'), 'Invalid pack ' + field)
    require(type(entry['packApi']) is int and 1 <= entry['packApi'] <= 100000, 'Invalid pack API version')
    require(type(entry['size']) is int and 0 < entry['size'] <= MAX_ARCHIVE_BYTES, 'Pack archive exceeds the supported size')
    require(all(isinstance(entry[field], str) and SHA.fullmatch(entry[field]) for field in ('sha256','manifestSha256')), 'Invalid pack digest')
    versions = entry['toolVersions']
    require(isinstance(versions, dict) and len(versions) <= 128 and all(isinstance(key,str) and ID.fullmatch(key) and _text(version,64) for key,version in versions.items()), 'Invalid upstream tool versions')
    https_url(entry['downloadURL'], hosts)
    return entry


def _published(value):
    require(isinstance(value, str) and len(value) <= 40, 'Invalid catalogue publication date')
    try:
        date = datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError as exc:
        raise PackError('Invalid catalogue publication date') from exc
    require(date.tzinfo is not None and date.utcoffset().total_seconds() == 0, 'Catalogue publication date must use UTC')
    return date


def validate_catalog(raw, source):
    document = signed_payload(raw, source['publicKey'], MAX_CATALOG_BYTES)
    require(isinstance(document, dict) and set(document) == {'schema','publishedAt','packs'}, 'Invalid catalogue payload')
    require(type(document['schema']) is int and document['schema'] == 1, 'Unsupported catalogue payload')
    _published(document['publishedAt'])
    require(isinstance(document['packs'], list) and len(document['packs']) <= MAX_FILES, 'Too many catalogue entries')
    identities = set()
    for entry in document['packs']:
        validate_entry(entry, source['allowedHosts'])
        identity = (entry['id'], entry['version'])
        require(identity not in identities, 'Duplicate catalogue pack version')
        identities.add(identity)
    return document


def compatibility(item):
    if item['platform'] != PLATFORM:
        return False, 'This pack targets a different operating system or processor.'
    if item['packApi'] != PACK_API:
        return False, 'This pack requires a different pack API.'
    if _version(item['minAppVersion']) > _version(APP_VERSION):
        return False, 'Requires Workbench ' + item['minAppVersion'] + ' or newer.'
    return True, ''


class _Redirects(urllib.request.HTTPRedirectHandler):
    def __init__(self, hosts, initial_url=None):
        self.hosts = hosts
        self.host = urlsplit(initial_url).hostname if initial_url else None
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        # GitHub Release assets redirect to short-lived, signed HTTPS URLs.
        # Their query is used for this request only and is never cached/logged.
        https_url(newurl, self.hosts, redirect=True)
        self.host = urlsplit(newurl).hostname
        return super().redirect_request(request, fp, code, msg, headers, newurl)


def _download_error(error, host):
    """Expose bounded failure categories, never exception text or request URLs."""
    reason = error
    for _ in range(4):
        if not isinstance(reason, urllib.error.URLError) or isinstance(reason, urllib.error.HTTPError):
            break
        reason = reason.reason
    status = reason.code if isinstance(reason, urllib.error.HTTPError) else None
    # urllib's CONNECT tunnel error wraps a status in OSError rather than
    # HTTPError. Extract only the bounded numeric status, never its text.
    if status is None and isinstance(reason, OSError):
        tunnel = re.match(r'^Tunnel connection failed: ([0-9]{3})\b', str(reason))
        if tunnel:
            status = int(tunnel.group(1))
    prefix = 'Download from ' + host + ' failed. '
    if type(status) is int and 100 <= status <= 599:
        if status == 407:
            detail = 'The proxy requires authentication (HTTP 407). Ask your network administrator about approved access for Workbench.'
        elif status in (401, 403):
            detail = 'Access was denied (HTTP ' + str(status) + '). Check access to this host with your network administrator.'
        elif status == 404:
            detail = 'The selected download is unavailable (HTTP 404). Refresh the catalogue and retry; report this if it persists.'
        elif status == 429:
            detail = 'The service limited download requests (HTTP 429). Wait before retrying.'
        elif status >= 500:
            detail = 'The service or proxy returned HTTP ' + str(status) + '. Retry later.'
        else:
            detail = 'The service or proxy returned HTTP ' + str(status) + '. Check approved network access or report this status.'
    elif isinstance(reason, ssl.SSLCertVerificationError):
        detail = 'The HTTPS certificate could not be verified. Check the Windows date and time; ask your network administrator to check trusted certificates.'
    elif isinstance(reason, ssl.SSLError):
        detail = 'The secure HTTPS connection failed. Ask your network administrator to check TLS access to this host.'
    elif isinstance(reason, socket.gaierror):
        detail = 'The server or configured proxy name could not be resolved. Check your connection and approved DNS/proxy settings.'
    elif isinstance(reason, TimeoutError) or getattr(reason, 'winerror', None) == 10060:
        detail = 'The connection timed out. Check your connection and retry.'
    elif isinstance(reason, ConnectionRefusedError) or getattr(reason, 'winerror', None) == 10061:
        detail = 'The connection was refused. Check approved access to this host and your proxy settings.'
    elif isinstance(reason, (ConnectionError, http.client.IncompleteRead, http.client.RemoteDisconnected)):
        detail = 'The connection ended before the download completed. Check your connection and retry.'
    elif isinstance(reason, PermissionError) or getattr(reason, 'winerror', None) == 10013:
        detail = 'Network access was denied. Ask your network administrator about approved access for Workbench.'
    else:
        code = getattr(reason, 'winerror', None) or getattr(reason, 'errno', None)
        suffix = ' (error ' + str(code) + ')' if type(code) is int and -65535 <= code <= 65535 else ''
        detail = 'The network request failed' + suffix + '. Check your connection and approved proxy/host access.'
    return prefix + detail


def _download_storage_error(error):
    code, windows = getattr(error, 'errno', None), getattr(error, 'winerror', None)
    if code == errno.ENOSPC or windows in (39, 112):
        detail = 'There is not enough free disk space.'
    elif windows in (32, 33):
        detail = 'The temporary download file is locked by another process. Close other Workbench instances and retry.'
    elif isinstance(error, PermissionError) or code in (errno.EACCES, errno.EPERM, errno.EROFS) or windows == 5:
        detail = 'Write access was denied. Check that your Workbench folder is writable.'
    elif isinstance(error, FileNotFoundError):
        detail = 'The download folder is no longer available. Check that the drive is connected and restart Workbench.'
    else:
        detail = 'A local file operation failed. Check free space and write access, then retry.'
    return 'Download could not be saved in the Workbench user-data folder. ' + detail


def _download(url, hosts, destination, limit, cancel=None, event=None, expected_size=None, expected_sha=None):
    https_url(url, hosts)
    cancelled(cancel)
    redirects = _Redirects(hosts, url)
    opener = urllib.request.build_opener(redirects)
    request = urllib.request.Request(url, headers={'User-Agent':'NativeWorkbench/' + APP_VERSION, 'Accept-Encoding':'identity'})
    digest = hashlib.sha256()
    count = 0
    started = time.monotonic()
    try:
        with opener.open(request, timeout=20) as response:
            require(response.getcode() == 200, 'Download did not return an ordinary file')
            https_url(response.geturl(), hosts, redirect=True)
            redirects.host = urlsplit(response.geturl()).hostname
            require(response.headers.get('Content-Encoding', 'identity').lower() == 'identity', 'Encoded downloads are not supported')
            length = response.headers.get('Content-Length')
            if length is not None:
                require(length.isdecimal() and int(length) <= limit, 'Download exceeds the size limit')
                if expected_size is not None:
                    require(int(length) == expected_size, 'Download size differs from the signed catalogue')
            try:
                with filesystem_path(destination).open('xb') as output:
                    while True:
                        cancelled(cancel)
                        require(time.monotonic() - started < 3600, 'Download exceeded the one hour time limit')
                        try:
                            block = response.read1(min(CHUNK, limit - count + 1))
                        except (urllib.error.URLError, OSError, http.client.HTTPException) as exc:
                            raise PackError(_download_error(exc, redirects.host)) from None
                        if not block:
                            break
                        count += len(block)
                        require(count <= limit, 'Download exceeds the size limit')
                        digest.update(block)
                        output.write(block)
                        _event(event, 'downloading', bytes=count, total=expected_size or (int(length) if length else None), cancellable=True)
            except PackCancelled:
                raise
            except OSError as exc:
                raise PackError(_download_storage_error(exc)) from None
        cancelled(cancel)
        if expected_size is not None:
            require(count == expected_size, 'Incomplete download: size differs from the signed catalogue')
        if expected_sha is not None:
            require(digest.hexdigest() == expected_sha, 'Download checksum differs from the signed catalogue')
        return count, digest.hexdigest()
    except PackCancelled:
        raise
    except (urllib.error.URLError, OSError, http.client.HTTPException) as exc:
        # Do not leak signed redirect URLs/proxy credentials into logs or the UI.
        raise PackError(_download_error(exc, redirects.host)) from None


def _archive_envelope(value):
    fields = {'schema','id','version','packApi','minAppVersion','platform','manifestSha256','files'}
    require(isinstance(value, dict) and set(value) == fields, 'Invalid pack archive envelope')
    require(type(value['schema']) is int and value['schema'] == 1, 'Unsupported pack archive format')
    require(isinstance(value['id'], str) and ID.fullmatch(value['id']), 'Invalid archive pack identifier')
    _version(value['version']); _version(value['minAppVersion'])
    require(type(value['packApi']) is int and _text(value['platform'],64), 'Invalid archive compatibility fields')
    require(isinstance(value['manifestSha256'], str) and SHA.fullmatch(value['manifestSha256']), 'Invalid archive manifest digest')
    good, reason = compatibility(value)
    require(good, reason)
    require(isinstance(value['files'], list) and 1 <= len(value['files']) <= MAX_FILES, 'Invalid pack archive inventory')
    inventory, folded, total = {}, set(), 0
    dirs, directory_case = set(), {}
    for item in value['files']:
        require(isinstance(item,dict) and set(item) == {'path','size','sha256'}, 'Invalid pack file inventory entry')
        require(isinstance(item['path'], str) and '\\' not in item['path'], 'Invalid inventory path')
        path = _relative(item['path'])
        require(path.casefold() not in folded, 'Duplicate or case-colliding inventory path')
        folded.add(path.casefold())
        require(type(item['size']) is int and 0 <= item['size'] <= MAX_PACK_BYTES, 'Invalid pack file size')
        require(isinstance(item['sha256'], str) and SHA.fullmatch(item['sha256']), 'Invalid pack file digest')
        inventory[path] = item
        total += item['size']
        parts = path.split('/')
        for at in range(1,len(parts)):
            directory = '/'.join(parts[:at])
            folded_dir = directory.casefold()
            require(folded_dir not in directory_case or directory_case[folded_dir] == directory, 'Case-colliding inventory directories')
            directory_case[folded_dir] = directory
            dirs.add(folded_dir)
    require(total <= MAX_PACK_BYTES and len(inventory) + len(dirs) <= MAX_FILES, 'Pack exceeds 1024 MiB or 2000 files and folders')
    require(not folded.intersection(dirs), 'Pack inventory contains a file/directory collision')
    require('pack.ini' in inventory and inventory['pack.ini']['sha256'] == value['manifestSha256'], 'Pack inventory does not pin its manifest')
    return inventory


def extract_archive(archive, destination, expected=None, cancel=None, event=None):
    """Verify all payload bytes and semantics before exposing a folder to import."""
    archive, destination = filesystem_path(archive), filesystem_path(destination)
    require(archive.is_file() and not archive.is_symlink() and archive.stat().st_size <= MAX_ARCHIVE_BYTES, 'Invalid or overlarge pack archive')
    cancelled(cancel)
    _safe_directory(destination)
    require(not any(destination.iterdir()), 'Archive staging folder must be empty')
    if expected:
        require(archive.stat().st_size == expected['size'], 'Pack archive size differs from the signed catalogue')
        digest = hashlib.sha256()
        with archive.open('rb') as stream:
            while block := stream.read(CHUNK):
                cancelled(cancel); digest.update(block)
        require(digest.hexdigest() == expected['sha256'], 'Pack archive checksum differs from the signed catalogue')
    try:
        with zipfile.ZipFile(archive) as zipped:
            members = zipped.infolist()
            require(len(members) <= MAX_FILES + 2, 'Too many ZIP entries')
            by_name, folded, total = {}, set(), 0
            for member in members:
                name = member.filename
                require(name and name == member.orig_filename and '\\' not in name and '\x00' not in name, 'Unsafe ZIP path')
                normalized = _relative(name[:-1] if member.is_dir() else name)
                require(normalized.casefold() not in folded, 'Duplicate or case-colliding ZIP path')
                folded.add(normalized.casefold())
                mode = (member.external_attr >> 16) & 0xffff
                require(stat.S_IFMT(mode) in (0, stat.S_IFREG, stat.S_IFDIR) and not (member.external_attr & 0x400), 'Links and special files are not allowed in pack archives')
                require(not (member.flag_bits & 1) and member.compress_type in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED), 'Encrypted or unsupported ZIP entry')
                if member.is_dir():
                    require(name.startswith('pack/') or name == 'pack/', 'Unexpected ZIP directory')
                    require(member.file_size == 0, 'ZIP directory contains data')
                else:
                    require(name == 'workbench-pack.json' or name.startswith('pack/'), 'Unexpected file outside the pack root')
                    by_name[name] = member
                    total += member.file_size
            require(total <= MAX_PACK_BYTES + 2*1024*1024, 'ZIP exceeds the expanded size limit')
            require('workbench-pack.json' in by_name and by_name['workbench-pack.json'].file_size <= 2*1024*1024, 'Missing or overlarge pack envelope')
            envelope = strict_json(zipped.read(by_name['workbench-pack.json']))
            inventory = _archive_envelope(envelope)
            allowed_dirs = {'pack'}
            for name in inventory:
                parts = ('pack/'+name).split('/')
                allowed_dirs.update('/'.join(parts[:at]) for at in range(1,len(parts)))
            require(all(member.filename[:-1] in allowed_dirs for member in members if member.is_dir()), 'ZIP contains undeclared directories')
            require(set(by_name) == {'workbench-pack.json'} | {'pack/'+name for name in inventory}, 'ZIP files differ from the declared inventory')
            if expected:
                for key in ('id','version','platform','packApi','minAppVersion','manifestSha256'):
                    require(envelope[key] == expected[key], 'Pack archive metadata differs from the signed catalogue: ' + key)
            pack_root = destination / 'pack'
            pack_root.mkdir()
            copied = 0
            for name, item in inventory.items():
                cancelled(cancel)
                member = by_name['pack/'+name]
                require(member.file_size == item['size'], 'ZIP member size differs from its inventory')
                target = pack_root.joinpath(*name.split('/'))
                target.parent.mkdir(parents=True, exist_ok=True)
                digest = hashlib.sha256()
                count = 0
                with zipped.open(member) as source, target.open('xb') as output:
                    while block := source.read(CHUNK):
                        cancelled(cancel)
                        count += len(block)
                        require(count <= item['size'], 'ZIP member exceeds its declared size')
                        digest.update(block); output.write(block)
                require(count == item['size'] and digest.hexdigest() == item['sha256'], 'Pack file checksum differs: ' + name)
                copied += count
                _event(event, 'verifying', bytes=copied, total=total-by_name['workbench-pack.json'].file_size, cancellable=True)
            pack = load_pack(pack_root / 'pack.ini')
            require(pack['id'] == envelope['id'] and pack['version'] == envelope['version'] and pack['manifestSha256'] == envelope['manifestSha256'], 'Manifest identity differs from archive metadata')
            for item in [*pack['tools'].values(), *pack['assets'].values()]:
                require(item['path'] in inventory and inventory[item['path']]['sha256'] == item['sha256'], 'Manifest executable or asset differs from its inventory')
            cancelled(cancel)
            return pack_root, envelope, pack
    except PackCancelled:
        raise
    except (zipfile.BadZipFile, RuntimeError, UnicodeError, OSError) as exc:
        raise PackError('Unable to read a complete, valid pack ZIP archive') from exc


def inspect_archive(path):
    with tempfile.TemporaryDirectory(prefix='workbench-pack-audit-') as temporary:
        _, envelope, pack = extract_archive(path, Path(temporary)/'extracted')
        return {'envelope':envelope, 'pack':pack}


class PackManager:
    def __init__(self, root, import_callback=None, catalog_callback=None):
        self.root = Path(root).resolve()
        self.data = filesystem_path(self.root / 'user-data' / 'pack-manager')
        self.sources_path = self.data / 'sources.json'
        self.bundled_sources_path = filesystem_path(self.root / 'workspace' / 'catalog-sources.json')
        self.import_callback = import_callback
        self.catalog_callback = catalog_callback
        self.lock = threading.RLock()
        self.source_errors = {}

    @staticmethod
    def _read_sources(path):
        if not path.exists():
            return []
        require(not path.is_symlink() and path.is_file() and path.stat().st_size <= 256*1024, 'Invalid source settings file')
        value = strict_json(path.read_bytes())
        require(isinstance(value, list) and len(value) <= 16, 'Invalid saved catalogue sources')
        sources = [validate_source(source) for source in value]
        require(len({source['id'] for source in sources}) == len(sources), 'Duplicate source identifier')
        return sources

    def _sources(self):
        # Application-bundled trust may be updated only by application release.
        # User additions cannot replace its identifiers or rewrite this file.
        bundled = self._read_sources(self.bundled_sources_path)
        users = self._read_sources(self.sources_path)
        merged = {source['id']:source for source in bundled}
        for source in users:
            existing = merged.get(source['id'])
            require(existing is None or existing == source,
                    'User source conflicts with a bundled catalogue identifier; bundled trust cannot be overridden')
            merged[source['id']] = source
        require(len(merged) <= 16, 'At most 16 catalogue sources can be configured')
        return list(merged.values())

    def add_source(self, path):
        path = filesystem_path(path)
        require(path.is_file() and path.stat().st_size <= 64*1024, 'Invalid source definition file')
        source = validate_source(strict_json(path.read_bytes()))
        with self.lock:
            sources = self._sources()
            existing = next((item for item in sources if item['id'] == source['id']), None)
            require(existing is None or existing == source, 'A different source already uses this identifier; existing trust was preserved')
            if existing is None:
                require(len(sources) < 16, 'At most 16 sources can be configured')
                additions = self._read_sources(self.sources_path)
                additions.append(source)
                _atomic_bytes(self.sources_path, json.dumps(additions, ensure_ascii=False, indent=2).encode('utf-8'))
        return {'id':source['id'], 'name':source['name'], 'keyFingerprint':key_fingerprint(source['publicKey']), 'added':existing is None}

    def _cached(self, source):
        path = self.data / 'cache' / (source['id']+'.json')
        if not path.exists():
            return None
        require(not path.is_symlink() and path.stat().st_size <= MAX_CATALOG_BYTES, 'Invalid catalogue cache file')
        return validate_catalog(path.read_bytes(), source)

    def _refresh(self, source, cancel=None, event=None):
        _safe_directory(self.data)
        old = None
        try:
            old = self._cached(source)
        except PackError:
            pass  # A damaged cache must not prevent a fresh verified download.
        with tempfile.TemporaryDirectory(prefix='_catalog-', dir=self.data) as directory:
            path = Path(directory)/'catalog.json'
            _download(source['catalogUrl'], source['allowedHosts'], path, MAX_CATALOG_BYTES, cancel, event)
            raw = path.read_bytes()
            document = validate_catalog(raw, source)
            if old:
                require(_published(document['publishedAt']) >= _published(old['publishedAt']), 'Catalogue rollback rejected; existing verified catalogue retained')
            _atomic_bytes(self.data/'cache'/(source['id']+'.json'), raw)
        return document

    def snapshot(self, refresh=False, cancel=None, event=None):
        with self.lock:
            sources = self._sources()
        local = self.catalog_callback() if self.catalog_callback else load_catalog(self.root)
        installed = local.get('packs', [])
        by_id = {}
        for item in installed:
            by_id.setdefault(item['id'], []).append(item)
        rows, source_rows = [], []
        for source in sources:
            cancelled(cancel)
            document, error = None, self.source_errors.get(source['id'], '')
            if refresh:
                try:
                    document = self._refresh(source, cancel, event)
                    error = ''
                except PackCancelled:
                    raise
                except (PackError, OSError, ValueError) as exc:
                    error = str(exc)
                self.source_errors[source['id']] = error
            if document is None:
                try:
                    document = self._cached(source)
                except (PackError, OSError, ValueError) as exc:
                    error = str(exc)
            source_rows.append({'id':source['id'],'name':source['name'],'catalogUrl':source['catalogUrl'],
                                'keyFingerprint':key_fingerprint(source['publicKey']), 'status':'cached' if document else 'not-loaded',
                                'error':error, 'publishedAt':document['publishedAt'] if document else None})
            for entry in document['packs'] if document else []:
                versions = sorted((item['version'] for item in by_id.get(entry['id'], [])), key=_version)
                good, reason = compatibility(entry)
                exact = next((item for item in by_id.get(entry['id'], []) if item['version']==entry['version']), None)
                same = exact is not None and exact['manifestSha256'] == entry['manifestSha256']
                if exact is not None and not same:
                    good, reason = False, 'An installed pack has this version but a different manifest. Existing files will not be overwritten.'
                rows.append({**entry,'sourceId':source['id'],'sourceName':source['name'],'publisherVerified':True,
                             'installed':same,'installedVersions':versions,'compatible':good,'reason':reason,
                             'updateAvailable':bool(versions and _version(entry['version']) > max(map(_version,versions)))})
        represented = {(row['id'],row['version'],row['manifestSha256']) for row in rows}
        tools = list(local.get('tools', {}).values())
        for item in installed:
            if (item['id'],item['version'],item['manifestSha256']) in represented:
                continue
            descriptions = [tool for tool in tools if tool.get('packId') == item['id'] and tool.get('packVersion') == item['version']]
            first = descriptions[0] if descriptions else {}
            rows.append({**item,'sourceId':'','sourceName':'Local installation','name':item.get('name',first.get('packName',item['id'])),
                         'description':item.get('description',first.get('description','')),'category':first.get('category','Installed tools'),
                         'toolVersions':{},'size':0,'platform':PLATFORM,'packApi':PACK_API,'minAppVersion':APP_VERSION,
                         'publisherVerified':False,'installed':True,'installedVersions':sorted((p['version'] for p in by_id[item['id']]),key=_version),
                         'compatible':True,'reason':'','updateAvailable':False})
        rows.sort(key=lambda row:(row['name'].casefold(),row['id'],_version(row['version']),row['sourceId']))
        errors = local.get('errors', [])
        notice = ('No online catalogue is configured. Installed tools work offline. Import a pack ZIP, or add a catalogue source supplied by your organisation.' if not sources else 'Catalogues refresh only when requested. Tool data stays on this computer.')
        if errors:
            notice += ' '+str(len(errors))+' installed pack version(s) could not be loaded; see installation errors.'
        if any(source['error'] for source in source_rows):
            notice += ' One or more catalogue sources could not be refreshed or verified; any previously verified catalogue is retained.'
        return {'schema':1,'applicationVersion':APP_VERSION,'packApi':PACK_API,'sources':source_rows,'packs':rows,'errors':errors,'notice':notice}

    def _publish(self, pack_root, envelope, cancel, event, verified):
        cancelled(cancel)
        require(self.import_callback is not None, 'No pack installation callback is configured')
        # Native importer stages and atomically publishes. Cancellation becomes
        # unavailable once this short transaction has begun.
        receipt = {key:envelope[key] for key in ('schema','id','version','packApi','minAppVersion','platform','manifestSha256')}
        receipt_path = filesystem_path(self.root/'user-data'/'pack-receipts'/(envelope['id']+'-'+envelope['version']+'.json'))
        _safe_directory(receipt_path.parent)
        require(not receipt_path.is_symlink(), 'Pack receipt cannot be a symbolic link')
        # Install compatibility metadata before the native folder rename. A
        # receipt without a matching pack folder is harmless after interruption.
        # Never change the receipt of an already installed version.
        require(self._existing_manifest(envelope['id'],envelope['version']) is None,
                'This pack version is already installed. Existing packs and receipts were preserved.')
        receipt_raw = json.dumps(receipt,sort_keys=True).encode('utf-8')
        _atomic_bytes(receipt_path, receipt_raw)
        published = False
        try:
            cancelled(cancel)
            _event(event, 'publishing', message='Finishing installation. Please keep Workbench open.', cancellable=False)
            source = ordinary_windows_path(pack_root) if os.name == 'nt' else str(pack_root)
            result = self.import_callback(source)
            require(isinstance(result, dict), 'Pack importer returned an invalid response')
            published = bool(result.get('success'))
            return {**result,'packId':envelope['id'],'packVersion':envelope['version'],
                    'publisherVerified':verified,'verification':'Signed catalogue and complete file inventory verified' if verified else 'Complete file inventory verified; publisher identity not verified'}
        finally:
            if not published:
                actual = self._existing_manifest(envelope['id'],envelope['version'])
                # A host error after native publication must retain its receipt.
                if actual != envelope['manifestSha256'] and receipt_path.exists() and receipt_path.read_bytes() == receipt_raw:
                    receipt_path.unlink()

    def _existing_manifest(self, identity, version):
        folder = filesystem_path(self.root/'packs')
        if not folder.exists():
            return None
        direct = folder / (identity+'-'+version)
        # The native importer publishes canonical directories. Avoid parsing
        # every preceding pack for each row of a Full-installation status poll.
        # Retain the legacy discovery fallback and its case-folded collision
        # detection when the canonical path is absent.
        if direct.exists() or direct.is_symlink():
            try:
                return load_pack(direct/'pack.ini')['manifestSha256']
            except (OSError, ValueError, KeyError):
                return 'occupied-invalid-pack-destination'
        canonical = (identity+'-'+version).casefold()
        for child in folder.iterdir():
            if child.name.casefold() == canonical:
                try:
                    return load_pack(child/'pack.ini')['manifestSha256']
                except (OSError,ValueError,KeyError):
                    return 'occupied-invalid-pack-destination'
            if child.name.startswith(('_','.')) or not child.is_dir() or child.is_symlink():
                continue
            manifest = child/'pack.ini'
            if not manifest.is_file() or manifest.is_symlink():
                continue
            try:
                pack = load_pack(manifest)
            except (OSError,ValueError,KeyError):
                continue
            if pack['id'] == identity and pack['version'] == version:
                return pack['manifestSha256']
        return None

    def install(self, source_id, pack_id, version, cancel=None, event=None,
                expected_entry=None, expected_source_fingerprint=None):
        with self.lock:
            source = next((item for item in self._sources() if item['id'] == source_id), None)
        require(source is not None, 'Unknown catalogue source')
        if expected_source_fingerprint is not None:
            require(key_fingerprint(source['publicKey']) == expected_source_fingerprint,
                    'Catalogue publisher key differs from the saved setup selection')
        document = self._cached(source)
        require(document is not None, 'Refresh this catalogue before installing a pack')
        entry = next((item for item in document['packs'] if item['id']==pack_id and item['version']==version),None)
        require(entry is not None, 'This pack version is not in the verified catalogue')
        if expected_entry is not None:
            # Setup retries must never silently switch even same-version bytes.
            # Check the exact entry used below, avoiding a cache-check/download race.
            require(all(entry[key] == expected_entry.get(key) for key in
                        ('id', 'version', 'size', 'sha256', 'manifestSha256')),
                    'Catalogue pack bytes differ from the saved setup selection')
        good, reason = compatibility(entry)
        require(good, reason)
        _safe_directory(self.data)
        with tempfile.TemporaryDirectory(prefix='_install-',dir=self.data) as directory:
            archive = Path(directory)/'download.zip'
            _download(entry['downloadURL'],source['allowedHosts'],archive,entry['size'],cancel,event,entry['size'],entry['sha256'])
            pack_root, envelope, _ = extract_archive(archive,Path(directory)/'extracted',entry,cancel,event)
            return self._publish(pack_root,envelope,cancel,event,True)

    def import_archive(self, path, cancel=None, event=None):
        _safe_directory(self.data)
        with tempfile.TemporaryDirectory(prefix='_import-',dir=self.data) as directory:
            pack_root, envelope, _ = extract_archive(path,Path(directory)/'extracted',None,cancel,event)
            return self._publish(pack_root,envelope,cancel,event,False)
