"""Explicit, release-pinned discovery of public Ensembl archive references.

This provider downloads public metadata only. It never reads analysis inputs,
constructs an arbitrary user URL, or contacts the network at construction.
Archive releases are distinct from the replacement Ensembl platform launched
in 2026. CHECKSUMS uses BSD sum over compressed bytes, not MD5 or a signature.
"""
from __future__ import annotations

import csv
import hashlib
from html.parser import HTMLParser
import io
import re
import urllib.error
import urllib.parse
import urllib.request


BASE_URL = 'https://ftp.ensembl.org/pub/'
MIN_RELEASE = 100
MAX_RELEASE = 116
DEFAULT_RELEASE = 116
MAX_METADATA_BYTES = 4 * 1024 * 1024
NOTICE = ('Ensembl archive releases 100–116: vertebrates and selected model '
          'organisms. Release 116 is the final classic Ensembl release. Newer '
          'data on the replacement Ensembl platform is not included. Downloads '
          'are public reference data; analysis files stay on this computer.')
DATA_NOTICE_URL = 'https://jun2026.archive.ensembl.org/info/about/legal/disclaimer.html'
TRANSITION_URL = ('https://www.ensembl.info/2025/12/02/updates-to-programmatic-access-'
                  'to-ensembl-and-transitioning-to-the-new-ensembl-platform/')
_SLUG = re.compile(r'[a-z][a-z0-9_]{0,159}\Z')
_FILENAME = re.compile(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,239}\Z')
_ACCESSION = re.compile(r'GC[AF]_[0-9]{9}\.[0-9]+\Z')


class ReferenceProviderError(ValueError):
    """An actionable discovery or public-reference transport failure."""


class ReferenceCancelled(ReferenceProviderError, InterruptedError):
    pass


class ReferenceHTTPError(ReferenceProviderError):
    def __init__(self, status, url):
        self.status = status
        self.url = url
        super().__init__(f'Ensembl returned HTTP {status} for {url}')


def cancelled(cancel):
    if cancel is not None and (cancel.is_set() if hasattr(cancel, 'is_set') else cancel()):
        raise ReferenceCancelled('Reference operation cancelled')


def _event(callback, phase, **fields):
    if callback:
        callback({'phase': phase, **fields})


def _release(value):
    if type(value) is not int or not MIN_RELEASE <= value <= MAX_RELEASE:
        raise ReferenceProviderError(f'Choose an Ensembl archive release from {MIN_RELEASE} to {MAX_RELEASE}')
    return value


def _text(value, maximum=240):
    return (isinstance(value, str) and 0 < len(value) <= maximum
            and all(ord(c) >= 32 and ord(c) != 127 for c in value))


def validate_url(url):
    """Validate and return the canonical archive object path, including host.

    Only the two official HTTPS archive aliases are permitted. Percent escapes,
    query strings, credentials, ports, traversal, current_* aliases and other
    EBI services are deliberately outside this narrow provider's authority.
    """
    if not isinstance(url, str) or len(url) > 2048 or any(ord(c) <= 32 or ord(c) >= 127 for c in url):
        raise ReferenceProviderError('Invalid Ensembl reference URL')
    try:
        parsed = urllib.parse.urlsplit(url)
        if (parsed.scheme != 'https' or parsed.username or parsed.password
                or parsed.port is not None or parsed.query or parsed.fragment):
            raise ReferenceProviderError('Reference URLs must use approved HTTPS archive paths')
    except (ValueError, UnicodeError) as exc:
        raise ReferenceProviderError('Invalid Ensembl reference URL') from exc
    roots = {'ftp.ensembl.org': '/pub/', 'ftp.ebi.ac.uk': '/pub/ensembl/'}
    prefix = roots.get(parsed.netloc)
    if prefix is None or not parsed.path.startswith(prefix):
        raise ReferenceProviderError('Reference URL is outside the approved Ensembl archive')
    tail = parsed.path[len(prefix):]
    if not tail:
        return ''
    if any(c in tail for c in ('%', '\\', ':')) or '//' in tail:
        raise ReferenceProviderError('Unsafe Ensembl archive path')
    components = tail.rstrip('/').split('/')
    if any(not _FILENAME.fullmatch(c) or c in ('.', '..') or c.startswith('current') for c in components):
        raise ReferenceProviderError('Unsafe Ensembl archive path')
    match = re.fullmatch(r'release-([0-9]+)', components[0])
    if not match or not MIN_RELEASE <= int(match[1]) <= MAX_RELEASE:
        raise ReferenceProviderError('Reference URL must name a supported numbered archive release')
    return tail


class _ArchiveRedirect(urllib.request.HTTPRedirectHandler):
    max_redirections = 5
    max_repeats = 2

    def __init__(self, original, cancel):
        self.object_path = validate_url(original)
        self.cancel = cancel

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        try:
            cancelled(self.cancel)
            if validate_url(newurl) != self.object_path:
                raise ReferenceProviderError('Ensembl redirect changed the pinned archive object')
        except BaseException:
            fp.close()
            raise
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def range_headers(headers, method='GET'):
    """Accept only the deliberately narrow resumable-download header contract."""
    if headers is None or headers == {}:
        return {}
    if (not isinstance(headers, dict) or set(headers) != {'Range', 'If-Range'} or method != 'GET'
            or not isinstance(headers['Range'], str)
            or not re.fullmatch(r'bytes=[0-9]{1,15}-', headers['Range'])
            or not isinstance(headers['If-Range'], str)
            or len(headers['If-Range']) > 500
            or any(ord(c) < 32 or ord(c) == 127 for c in headers['If-Range'])):
        raise ReferenceProviderError('Invalid reference resume headers')
    validator = headers['If-Range']
    if not (re.fullmatch(r'"[^"\\]+"', validator) or
            re.fullmatch(r'[A-Z][a-z]{2}, [0-9]{2} [A-Z][a-z]{2} [0-9]{4} [0-9]{2}:[0-9]{2}:[0-9]{2} GMT', validator)):
        raise ReferenceProviderError('Reference resume requires a strong ETag or HTTP modification date')
    return dict(headers)


class RestrictedEnsemblHTTPS:
    """Standard-library HTTPS transport, preserving OS proxy/TLS validation."""
    def __init__(self, timeout=20):
        self.timeout = timeout

    def open_url(self, url, method='GET', cancel=None, headers=None):
        object_path = validate_url(url)
        if method not in ('GET', 'HEAD'):
            raise ReferenceProviderError('Reference transport only permits GET and HEAD')
        cancelled(cancel)
        extra = range_headers(headers, method)
        request = urllib.request.Request(url, method=method, headers={
            'User-Agent': 'NativeWorkbench-reference-discovery/1',
            'Accept-Encoding': 'identity', **extra,
        })
        opener = urllib.request.build_opener(_ArchiveRedirect(url, cancel))
        try:
            response = opener.open(request, timeout=self.timeout)
        except urllib.error.HTTPError as exc:
            exc.close()
            raise ReferenceHTTPError(exc.code, url) from exc
        except (urllib.error.URLError, OSError) as exc:
            cancelled(cancel)
            raise ReferenceProviderError(f'Cannot connect to Ensembl: {exc}') from exc
        try:
            cancelled(cancel)
            if validate_url(response.geturl()) != object_path:
                raise ReferenceProviderError('Ensembl response changed the pinned archive object')
            if response.getcode() not in ((200, 206) if extra else (200,)):
                raise ReferenceHTTPError(response.getcode(), url)
            if response.headers.get('Content-Encoding', 'identity').lower() not in ('', 'identity'):
                raise ReferenceProviderError('Unexpected HTTP content encoding for an Ensembl reference')
            _content_length(response.headers)
            return response
        except BaseException:
            response.close()
            raise

    def read_metadata(self, url, cancel=None, max_bytes=MAX_METADATA_BYTES):
        return _read_metadata(self.open_url, url, cancel, max_bytes)


def _content_length(headers):
    raw = headers.get('Content-Length')
    if raw is None:
        return None
    if not re.fullmatch(r'[0-9]{1,20}', raw) or int(raw) > 2**63 - 1:
        raise ReferenceProviderError('Invalid Ensembl Content-Length')
    return int(raw)


def _read_metadata(opener, url, cancel, max_bytes):
    if type(max_bytes) is not int or not 1 <= max_bytes <= 16 * 1024 * 1024:
        raise ReferenceProviderError('Invalid reference metadata size limit')
    with opener(url, cancel=cancel) as response:
        size = _content_length(response.headers)
        if size is not None and size > max_bytes:
            raise ReferenceProviderError('Ensembl metadata exceeds the supported size limit')
        chunks = []
        total = 0
        while True:
            cancelled(cancel)
            block = response.read(min(65536, max_bytes + 1 - total))
            if not block:
                break
            total += len(block)
            if total > max_bytes:
                raise ReferenceProviderError('Ensembl metadata exceeds the supported size limit')
            chunks.append(block)
        cancelled(cancel)
        if size is not None and total != size:
            raise ReferenceProviderError('Ensembl metadata download was incomplete')
        return b''.join(chunks)


def open_url(url, method='GET', cancel=None, headers=None):
    return RestrictedEnsemblHTTPS().open_url(url, method=method, cancel=cancel, headers=headers)


def read_metadata(url, cancel=None, max_bytes=MAX_METADATA_BYTES):
    return RestrictedEnsemblHTTPS().read_metadata(url, cancel=cancel, max_bytes=max_bytes)


def _decode(data):
    try:
        return data.decode('utf-8-sig')
    except UnicodeError as exc:
        raise ReferenceProviderError('Ensembl metadata is not valid UTF-8') from exc


class _Links(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.links = []

    def handle_starttag(self, tag, attrs):
        if tag == 'a':
            self.links.extend(value for key, value in attrs if key == 'href' and value)


def _checksums(data):
    text = _decode(data)
    result = {}
    for line in text.splitlines():
        if not line.strip():
            continue
        match = re.fullmatch(r'\s*([0-9]{1,5})\s+([0-9]{1,16})\s+([^\s]+)\s*', line)
        if not match:
            raise ReferenceProviderError('Ensembl CHECKSUMS contains an invalid record')
        checksum, blocks, filename = int(match[1]), int(match[2]), match[3]
        if checksum > 65535 or blocks > 2**53 or not _FILENAME.fullmatch(filename) or filename in ('.', '..'):
            raise ReferenceProviderError('Ensembl CHECKSUMS contains an unsafe filename or value')
        if filename in result:
            raise ReferenceProviderError('Ensembl CHECKSUMS repeats a filename')
        result[filename] = {'algorithm': 'bsd-sum', 'value': checksum, 'blocks': blocks}
    if not result:
        raise ReferenceProviderError('Ensembl CHECKSUMS is empty')
    return result, text


class EnsemblArchiveProvider:
    def __init__(self, transport=None):
        self.transport = transport or RestrictedEnsemblHTTPS()

    def descriptor(self):
        return {'id': 'ensembl-archive', 'provider': 'ensembl-archive',
                'name': 'Ensembl archive', 'provider_name': 'Ensembl archive',
                'default_release': DEFAULT_RELEASE, 'min_release': MIN_RELEASE,
                'max_release': MAX_RELEASE, 'notice': NOTICE,
                'data_notice_url': DATA_NOTICE_URL, 'transition_url': TRANSITION_URL}

    def open_url(self, url, method='GET', cancel=None, headers=None):
        validate_url(url)
        extra = range_headers(headers, method)
        return self.transport.open_url(url, method=method, cancel=cancel, **({'headers': extra} if extra else {}))

    def read_metadata(self, url, cancel=None, max_bytes=MAX_METADATA_BYTES):
        validate_url(url)
        return _read_metadata(self.open_url, url, cancel, max_bytes)

    def releases(self, cancel=None, event=None):
        _event(event, 'discovery', message='Reading available Ensembl archive releases')
        data = self.read_metadata(BASE_URL, cancel=cancel, max_bytes=1024 * 1024)
        parser = _Links()
        parser.feed(_decode(data))
        releases = {int(m[1]) for link in parser.links
                    if (m := re.fullmatch(r'release-([0-9]+)/', link))
                    and MIN_RELEASE <= int(m[1]) <= MAX_RELEASE}
        if not releases:
            raise ReferenceProviderError('No supported numbered Ensembl archive releases were found')
        return sorted(releases, reverse=True)

    def _species(self, release, cancel=None):
        release = _release(release)
        url = f'{BASE_URL}release-{release}/species_EnsemblVertebrates.txt'
        data = self.read_metadata(url, cancel=cancel)
        rows = list(csv.reader(io.StringIO(_decode(data)), delimiter='\t', quoting=csv.QUOTE_NONE))
        required = ('#name', 'species', 'division', 'taxonomy_id', 'assembly', 'assembly_accession', 'genebuild')
        if not rows or any(rows[0].count(key) != 1 for key in required):
            raise ReferenceProviderError('Ensembl species catalogue has an unsupported header')
        header = rows[0]
        if len(set(header)) != len(header):
            raise ReferenceProviderError('Ensembl species catalogue repeats a column')
        result, seen = [], set()
        for row in rows[1:]:
            cancelled(cancel)
            if not row or not any(row):
                continue
            if len(row) < len(header) or any(row[len(header):]):
                raise ReferenceProviderError('Ensembl species catalogue has an invalid row')
            record = dict(zip(header, row))
            slug = record['species']
            if (not _SLUG.fullmatch(slug) or slug in seen or record['division'] != 'EnsemblVertebrates'
                    or not _text(record['#name']) or not _text(record['assembly'])
                    or (record['assembly_accession'] and not _ACCESSION.fullmatch(record['assembly_accession']))
                    or not re.fullmatch(r'[0-9]{1,12}', record['taxonomy_id'])
                    or int(record['taxonomy_id']) < 1 or not _text(record['genebuild'], 500)):
                raise ReferenceProviderError('Ensembl species catalogue contains invalid or duplicate metadata')
            seen.add(slug)
            result.append({'id': slug, 'name': record['#name'], 'assembly': record['assembly'],
                           'assembly_accession': record['assembly_accession'],
                           'taxon_id': int(record['taxonomy_id']), 'release': release,
                           'division': record['division'], 'genebuild': record['genebuild']})
        if not result:
            raise ReferenceProviderError('Ensembl species catalogue contains no species')
        return sorted(result, key=lambda item: (item['name'].casefold(), item['assembly'], item['id'])), {
            'url': url, 'sha256': hashlib.sha256(data).hexdigest()}

    def species(self, release, query='', cancel=None, event=None):
        if not isinstance(query, str) or len(query) > 200 or any(ord(c) < 32 or ord(c) == 127 for c in query):
            raise ReferenceProviderError('Enter a species name, assembly or accession (up to 200 characters)')
        _event(event, 'discovery', message='Reading the release-pinned species catalogue')
        values, _ = self._species(release, cancel)
        tokens = query.casefold().split()
        return [item for item in values if all(token in ' '.join(str(v) for v in item.values()).casefold()
                                               for token in tokens)]

    search = species

    def discover(self, release, species_id, cancel=None, event=None):
        release = _release(release)
        if not isinstance(species_id, str) or not _SLUG.fullmatch(species_id):
            raise ReferenceProviderError('Choose a species from the Ensembl catalogue')
        values, source_catalog = self._species(release, cancel)
        species = next((item for item in values if item['id'] == species_id), None)
        if species is None:
            raise ReferenceProviderError('The selected species is not in this archive release')
        root = f'{BASE_URL}release-{release}/'
        prefix = species_id[0].upper() + species_id[1:] + '.'
        declared_assembly = species['assembly']
        allowed_assemblies = {declared_assembly, re.sub(r'\.p[0-9]+$', '', declared_assembly)}
        # These legacy archive spelling differences are explicit, observed
        # aliases, not a general lossy normalization of scientific identities.
        allowed_assemblies.update({'CSAV 2.0': {'CSAV2.0'},
                                   'TETRAODON 8.0': {'TETRAODON8'}}.get(declared_assembly, set()))
        files, warnings = [], []
        if not species['assembly_accession']:
            warnings.append('Ensembl does not supply an assembly accession for this older assembly; its archive assembly name and downloaded file hashes are recorded.')
        chosen_assembly = None
        roles = (
            ('genome', 'dna', 'Genome FASTA', 'fasta', 'genome'),
            ('annotation', 'gtf', 'Gene annotations (GTF)', 'gtf', 'annotation'),
            ('cdna', 'cdna', 'Transcripts (excluding ncRNA)', 'fasta', 'cdna'),
            ('ncrna', 'ncrna', 'Non-coding RNA transcripts', 'fasta', 'ncrna'),
            ('protein', 'pep', 'Protein sequences', 'fasta', 'protein'),
        )
        for identity, directory, label, file_format, kind in roles:
            cancelled(cancel)
            _event(event, 'discovery', resource=identity, message=f'Finding {label.lower()}')
            folder = root + (f'gtf/{species_id}/' if directory == 'gtf' else f'fasta/{species_id}/{directory}/')
            manifest_url = folder + 'CHECKSUMS'
            try:
                data = self.read_metadata(manifest_url, cancel=cancel, max_bytes=2 * 1024 * 1024)
            except ReferenceHTTPError as exc:
                if exc.status != 404:
                    raise
                warnings.append(f'{label} is not available for this species and release.')
                continue
            entries, manifest_text = _checksums(data)
            candidates = []
            for filename in entries:
                if not filename.startswith(prefix):
                    continue
                remainder = filename[len(prefix):]
                pattern = {
                    'genome': r'(.+)\.dna\.(primary_assembly|toplevel)\.fa\.gz',
                    'annotation': r'(.+)\.([0-9]+)\.gtf\.gz',
                    'cdna': r'(.+)\.cdna\.all\.fa\.gz',
                    'ncrna': r'(.+)\.ncrna\.fa\.gz',
                    'protein': r'(.+)\.pep\.all\.fa\.gz',
                }[identity]
                match = re.fullmatch(pattern, remainder)
                if match:
                    if match[1] not in allowed_assemblies:
                        raise ReferenceProviderError('Ensembl resource assembly does not match the release catalogue')
                    candidates.append((filename, match))
            if identity == 'genome':
                primary = [item for item in candidates if item[1][2] == 'primary_assembly']
                if primary:
                    candidates = primary
            if not candidates:
                warnings.append(f'{label} is not available for this species and release.')
                continue
            if len(candidates) != 1:
                raise ReferenceProviderError(f'Ensembl has ambiguous {label.lower()} files; no file was selected')
            filename, match = candidates[0]
            file_assembly = match[1]
            if chosen_assembly is None:
                chosen_assembly = file_assembly
            if file_assembly != chosen_assembly:
                raise ReferenceProviderError('Ensembl resource files do not share an assembly name')
            url = folder + filename
            size = None
            try:
                with self.open_url(url, method='HEAD', cancel=cancel) as response:
                    size = _content_length(response.headers)
            except ReferenceHTTPError as exc:
                if exc.status not in (405, 501):
                    raise
            checksum = dict(entries[filename])
            if size is not None and (size <= 0 or (size + 1023) // 1024 != checksum['blocks']):
                raise ReferenceProviderError('Ensembl file size disagrees with its CHECKSUMS record')
            manifest_sha = hashlib.sha256(data).hexdigest()
            checksum.update(manifest_url=manifest_url, manifest_sha256=manifest_sha)
            selection = match[2] if identity == 'genome' else None
            detail = {
                'genome': ('Unmasked primary assembly; excludes alternative haplotypes and patches.'
                           if selection == 'primary_assembly' else
                           'Unmasked toplevel genome. No primary-assembly file is supplied; Ensembl documents these as equivalent when no haplotypes or patches exist.'),
                'annotation': 'Annotations from the same numbered archive and assembly; sequence identifiers are preserved.',
                'cdna': 'Annotated transcripts excluding ncRNA genes; includes pseudogene and NMD transcripts. This is not a complete transcriptome.',
                'ncrna': 'Transcript sequences for non-coding RNA genes, supplied separately from cDNA.',
                'protein': 'Annotated protein translations; excludes separate ab initio predictions.',
            }[identity]
            item = {'id': identity, 'kind': kind, 'label': label, 'filename': filename, 'url': url,
                    'bytes': size, 'size': size, 'format': file_format, 'checksum': checksum,
                    'checksum_manifest': {'url': manifest_url, 'sha256': manifest_sha, 'text': manifest_text},
                    'assembly': file_assembly, 'detail': detail}
            if selection:
                item.update(sequence_scope=selection, masking='unmasked')
            if identity == 'annotation':
                item['annotation_file_release'] = int(match[2])
            files.append(item)
        if not files:
            raise ReferenceProviderError('No supported reference files were found for this species and release')
        return {'provider': 'ensembl-archive', 'provider_name': 'Ensembl archive', 'release': release,
                'species': species, 'source_catalog': source_catalog, 'files': files,
                'assembly': species['assembly'], 'assembly_accession': species['assembly_accession'],
                'notice': NOTICE, 'warnings': warnings, 'data_notice_url': DATA_NOTICE_URL,
                'transition_url': TRANSITION_URL}
