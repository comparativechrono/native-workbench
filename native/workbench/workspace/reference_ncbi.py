"""Explicit lookup of one versioned NCBI RefSeq assembly and public references.

The Datasets v2 report supplies assembly/annotation metadata. Only the matching
versioned GCF FTP directory and its published md5checksums.txt are used for data.
Annotations may change without an assembly version change: preserve the observed
annotation identity and checksum snapshot, never describe this as an immutable
annotation archive. Construction and the local descriptor do not use network.
"""
from __future__ import annotations

import hashlib
from html.parser import HTMLParser
import json
import re
import urllib.error
import urllib.parse
import urllib.request

from reference_provider import ReferenceHTTPError, ReferenceProviderError, cancelled

PROVIDER_ID = 'ncbi-refseq'
PROVIDER_NAME = 'NCBI RefSeq assembly lookup'
DEFAULT_RELEASE = 'assembly'
API_BASE = 'https://api.ncbi.nlm.nih.gov/datasets/v2/genome/accession/'
FTP_BASE = 'https://ftp.ncbi.nlm.nih.gov/genomes/all/GCF/'
MAX_METADATA_BYTES = 4 * 1024 * 1024
NOTICE = ('Look up an exact versioned RefSeq assembly accession, for example '
          'GCF_000146045.2. Genome FASTA, GTF and protein are offered when present. '
          'NCBI may update annotations for the same assembly; observed annotation '
          'metadata and downloaded file hashes are retained. Combined RNA files '
          'are not offered as cDNA or ncRNA. Analysis files stay on this computer.')
DATA_NOTICE_URL = 'https://www.ncbi.nlm.nih.gov/home/about/policies/'
DOCUMENTATION_URL = 'https://www.ncbi.nlm.nih.gov/datasets/docs/v2/data-processing/policies-annotation/genomeftp/'
_ACCESSION = re.compile(r'GCF_([0-9]{9})\.([1-9][0-9]{0,5})\Z')
_COMPONENT = re.compile(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,179}\Z')
_SUFFIXES = {'genome': '_genomic.fna.gz', 'annotation': '_genomic.gtf.gz',
             'protein': '_protein.faa.gz'}


class NCBIHTTPError(ReferenceHTTPError):
    def __init__(self, status, url):
        self.status = status
        self.url = url
        ReferenceProviderError.__init__(self, f'NCBI returned HTTP {status} for {url}')


def _require(condition, message):
    if not condition:
        raise ReferenceProviderError(message)


def _accession(value):
    _require(isinstance(value, str) and _ACCESSION.fullmatch(value),
             'Enter one versioned RefSeq assembly accession, for example GCF_000146045.2.')
    return value


def _release(value):
    _require(value == DEFAULT_RELEASE, 'Choose the NCBI RefSeq assembly lookup.')


def _text(value, maximum=500):
    return (isinstance(value, str) and 0 < len(value) <= maximum and
            all(ord(char) >= 32 and ord(char) != 127 for char in value))


def _component(value):
    return bool(_COMPONENT.fullmatch(value)) and not value.endswith('.')


def validate_url(url):
    """Allow only exact API accession reports and bounded GCF FTP objects.

    No URL query, credentials, port, percent encoding, host alias or alternate
    protocol is permitted. Redirects must retain the identical approved URL.
    """
    _require(isinstance(url, str) and len(url) <= 2048 and
             all(32 < ord(char) < 127 for char in url), 'Invalid NCBI reference URL.')
    try:
        parsed = urllib.parse.urlsplit(url)
        _require(parsed.scheme == 'https' and not parsed.username and not parsed.password and
                 parsed.port is None and not parsed.query and not parsed.fragment,
                 'NCBI references must use approved HTTPS paths.')
    except (ValueError, UnicodeError) as exc:
        raise ReferenceProviderError('Invalid NCBI reference URL.') from exc
    path = parsed.path
    _require(not any(char in path for char in ('%', '\\', ':')) and '//' not in path,
             'Unsafe NCBI reference path.')
    if parsed.netloc == 'api.ncbi.nlm.nih.gov':
        match = re.fullmatch(r'/datasets/v2/genome/accession/(GCF_[0-9]{9}\.[1-9][0-9]{0,5})/dataset_report', path)
        _require(match is not None, 'Only exact RefSeq accession reports are supported.')
        return url
    _require(parsed.netloc == 'ftp.ncbi.nlm.nih.gov', 'NCBI reference host is not approved.')
    match = re.fullmatch(r'/genomes/all/GCF/([0-9]{3})/([0-9]{3})/([0-9]{3})/(.*)', path)
    _require(match is not None, 'NCBI reference is outside the approved GCF directory.')
    digits, tail = ''.join(match.group(index) for index in (1, 2, 3)), match[4]
    if not tail:
        return url  # bounded directory listing for one accession number
    parts = tail.rstrip('/').split('/')
    _require(len(parts) <= 2 and all(_component(part) for part in parts),
             'Unsafe NCBI assembly directory or filename.')
    folder = parts[0]
    folder_match = re.fullmatch(r'(GCF_([0-9]{9})\.[1-9][0-9]{0,5})_(.+)', folder)
    _require(folder_match is not None and folder_match[2] == digits,
             'NCBI assembly directory does not match its accession prefix.')
    if len(parts) == 1:
        _require(tail.endswith('/'), 'NCBI assembly directory must end in a slash.')
    else:
        _require(not tail.endswith('/') and (parts[1] == 'md5checksums.txt' or
                 parts[1] in {folder + suffix for suffix in _SUFFIXES.values()}),
                 'NCBI reference filename is outside the supported assembly resources.')
    return url


def _headers(headers, url, method):
    if headers is None:
        return {}
    _require(isinstance(headers, dict) and set(headers) <= {'Range', 'If-Range'},
             'Unsupported NCBI reference request headers.')
    if not headers:
        return {}
    _require(method == 'GET' and url.endswith(tuple(_SUFFIXES.values())) and
             isinstance(headers.get('Range'), str) and
             re.fullmatch(r'bytes=[0-9]{1,20}-', headers['Range']) and
             int(headers['Range'][6:-1]) < 2**63,
             'Invalid NCBI reference resume range.')
    if 'If-Range' in headers:
        value = headers['If-Range']
        _require(isinstance(value, str) and len(value) <= 512 and
                 (re.fullmatch(r'"[\x21\x23-\x7e]*"', value) or
                  re.fullmatch(r'(Mon|Tue|Wed|Thu|Fri|Sat|Sun), [0-9]{2} '
                               r'(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec) '
                               r'[0-9]{4} [0-9]{2}:[0-9]{2}:[0-9]{2} GMT', value)),
                 'Invalid NCBI reference resume validator.')
    return dict(headers)


def _content_length(headers):
    raw = headers.get('Content-Length')
    if raw is None:
        return None
    _require(isinstance(raw, str) and re.fullmatch(r'[0-9]{1,20}', raw) and
             int(raw) < 2**63, 'Invalid NCBI Content-Length.')
    return int(raw)


class _NCBIRedirect(urllib.request.HTTPRedirectHandler):
    max_redirections = 5
    max_repeats = 2

    def __init__(self, original, cancel):
        self.original = validate_url(original)
        self.cancel = cancel

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        try:
            cancelled(self.cancel)
            _require(validate_url(newurl) == self.original,
                     'NCBI redirect changed the selected reference object.')
        except BaseException:
            fp.close()
            raise
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class RestrictedNCBIHTTPS:
    """Standard library HTTPS with normal system proxy and certificate checks."""
    def __init__(self, timeout=20):
        self.timeout = timeout

    def open_url(self, url, method='GET', cancel=None, headers=None):
        validate_url(url)
        _require(method in ('GET', 'HEAD'), 'NCBI transport only permits GET and HEAD.')
        extra = _headers(headers, url, method)
        cancelled(cancel)
        request = urllib.request.Request(url, method=method, headers={
            'User-Agent': 'NativeWorkbench-reference-discovery/1',
            'Accept-Encoding': 'identity', **extra})
        opener = urllib.request.build_opener(_NCBIRedirect(url, cancel))
        try:
            response = opener.open(request, timeout=self.timeout)
        except urllib.error.HTTPError as exc:
            exc.close()
            raise NCBIHTTPError(exc.code, url) from exc
        except (urllib.error.URLError, OSError) as exc:
            cancelled(cancel)
            raise ReferenceProviderError(f'Cannot connect to NCBI: {exc}') from exc
        try:
            cancelled(cancel)
            _require(validate_url(response.geturl()) == url,
                     'NCBI response changed the selected reference object.')
            code = response.getcode()
            if code != 200 and not (code == 206 and 'Range' in extra):
                raise NCBIHTTPError(code, url)
            _require(response.headers.get('Content-Encoding', 'identity').lower() in ('', 'identity'),
                     'Unexpected HTTP content encoding for an NCBI reference.')
            _content_length(response.headers)
            return response
        except BaseException:
            response.close()
            raise


def _read_metadata(opener, url, cancel, max_bytes):
    _require(type(max_bytes) is int and 1 <= max_bytes <= MAX_METADATA_BYTES,
             'Invalid NCBI metadata size limit.')
    with opener(url, cancel=cancel) as response:
        size = _content_length(response.headers)
        _require(size is None or size <= max_bytes, 'NCBI metadata exceeds the supported size limit.')
        chunks, total = [], 0
        while True:
            cancelled(cancel)
            block = response.read(min(65536, max_bytes + 1 - total))
            if not block:
                break
            total += len(block)
            _require(total <= max_bytes, 'NCBI metadata exceeds the supported size limit.')
            chunks.append(block)
        cancelled(cancel)
        _require(size is None or total == size, 'NCBI metadata download was incomplete.')
        return b''.join(chunks)


def _decode(raw):
    try:
        return raw.decode('utf-8-sig')
    except UnicodeError as exc:
        raise ReferenceProviderError('NCBI metadata is not valid UTF-8.') from exc


def _object(pairs):
    result = {}
    for key, value in pairs:
        _require(key not in result, 'NCBI metadata repeats a JSON key.')
        result[key] = value
    return result


def _invalid_constant(value):
    raise ReferenceProviderError('NCBI metadata contains an invalid JSON number.')


def _json(raw):
    try:
        value = json.loads(_decode(raw), object_pairs_hook=_object, parse_constant=_invalid_constant)
    except (ValueError, RecursionError) as exc:
        raise ReferenceProviderError('NCBI returned unsupported assembly metadata.') from exc
    _require(isinstance(value, dict), 'NCBI returned unsupported assembly metadata.')
    return value


class _Links(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.links = []

    def handle_starttag(self, tag, attrs):
        if tag == 'a':
            self.links.extend(value for key, value in attrs if key == 'href' and value)


def _checksums(data):
    text, result = _decode(data), {}
    for line in text.splitlines():
        if not line.strip():
            continue
        match = re.fullmatch(r'([0-9a-fA-F]{32}) [ *](?:\./)?([^\s]+)', line)
        _require(match is not None, 'NCBI md5checksums.txt contains an invalid record.')
        path = match[2]
        parts = path.split('/')
        _require(len(path) <= 2048 and len(parts) <= 20 and all(_component(part) for part in parts),
                 'NCBI checksum manifest contains an unsafe relative filename.')
        _require(path not in result, 'NCBI checksum manifest repeats a filename.')
        result[path] = {'algorithm': 'md5', 'value': match[1].lower()}
    _require(bool(result), 'NCBI checksum manifest is empty.')
    return result, text


class NCBIRefSeqProvider:
    def __init__(self, transport=None):
        self.transport = transport or RestrictedNCBIHTTPS()

    def descriptor(self):
        return {'id': PROVIDER_ID, 'provider': PROVIDER_ID, 'name': PROVIDER_NAME,
                'provider_name': PROVIDER_NAME, 'default_release': DEFAULT_RELEASE,
                'release_label': 'Assembly lookup',
                'search_label': 'Versioned RefSeq assembly accession',
                'search_example': 'GCF_000146045.2', 'notice': NOTICE,
                'data_notice_url': DATA_NOTICE_URL, 'documentation_url': DOCUMENTATION_URL}

    def open_url(self, url, method='GET', cancel=None, headers=None):
        validate_url(url)
        _require(method in ('GET', 'HEAD'), 'NCBI transport only permits GET and HEAD.')
        extra = _headers(headers, url, method)
        return self.transport.open_url(url, method=method, cancel=cancel, headers=extra)

    def read_metadata(self, url, cancel=None, max_bytes=MAX_METADATA_BYTES):
        return _read_metadata(self.open_url, url, cancel, max_bytes)

    def validate_download_prefix(self, item, prefix, selection):
        """Check GTF self-identification against the reviewed metadata snapshot.

        RefSeq bacterial GTF files may omit annotation-source/date. When present,
        these are compared; missing optional fields are not invented. The two
        assembly headers are required for this bounded GTF download provider.
        """
        if item.get('kind') != 'annotation':
            return
        headers = {}
        for line in bytes(prefix).splitlines():
            if not line.strip():
                continue
            if not line.startswith(b'#'):
                break
            for key in ('genome-build', 'genome-build-accession', 'annotation-source', 'annotation-date'):
                marker = ('#!' + key + ' ').encode('ascii')
                if line.startswith(marker):
                    _require(key not in headers, 'NCBI GTF repeats an identity header.')
                    headers[key] = _decode(line[len(marker):]).strip()
        _require(headers.get('genome-build') == selection.get('assembly') and
                 headers.get('genome-build-accession') == 'NCBI_Assembly:' + selection.get('assembly_accession', ''),
                 'NCBI GTF assembly headers differ from the selected assembly; discover the files again.')
        annotation = selection.get('annotation', {})
        expected_name = annotation.get('name')
        if expected_name and 'annotation-source' in headers:
            expected = {expected_name}
            if annotation.get('provider'):
                expected.add(annotation['provider'] + ' ' + expected_name)
            _require(headers['annotation-source'] in expected,
                     'NCBI GTF annotation differs from the metadata snapshot; discover the files again.')
        if annotation.get('release_date') and 'annotation-date' in headers:
            from datetime import date
            try:
                month, day, year = (int(part) for part in headers['annotation-date'].split('/'))
                observed_date = date(year, month, day).isoformat()
            except (ValueError, TypeError) as exc:
                raise ReferenceProviderError('NCBI GTF has an unsupported annotation date.') from exc
            _require(observed_date == annotation['release_date'],
                     'NCBI GTF annotation date differs from the metadata snapshot; discover the files again.')

    def releases(self, cancel=None, event=None):
        cancelled(cancel)
        return [DEFAULT_RELEASE]

    def _species(self, accession, cancel=None):
        accession = _accession(accession)
        url = API_BASE + accession + '/dataset_report'
        raw = self.read_metadata(url, cancel=cancel)
        document = _json(raw)
        reports = document.get('reports', [])
        _require(isinstance(reports, list) and len(reports) == 1 and
                 type(document.get('total_count')) is int and document['total_count'] == 1 and
                 not document.get('next_page_token'),
                 'No unique NCBI report was found for that exact versioned accession.')
        report = reports[0]
        _require(isinstance(report, dict) and report.get('accession') == accession and
                 report.get('source_database') == 'SOURCE_DATABASE_REFSEQ',
                 'NCBI did not return the exact selected RefSeq accession.')
        organism, assembly = report.get('organism'), report.get('assembly_info')
        _require(isinstance(organism, dict) and isinstance(assembly, dict) and
                 _text(organism.get('organism_name')) and
                 type(organism.get('tax_id')) is int and 0 < organism['tax_id'] < 2**53 and
                 _text(assembly.get('assembly_name')) and _text(assembly.get('assembly_status'), 80),
                 'NCBI assembly metadata is incomplete or invalid.')
        _require(assembly['assembly_status'].lower() != 'suppressed',
                 'This RefSeq assembly is suppressed; select a supported versioned accession.')
        annotation = report.get('annotation_info', {})
        _require(isinstance(annotation, dict), 'NCBI annotation metadata is invalid.')
        observed = {}
        for key in ('name', 'provider', 'release_date', 'report_url', 'status'):
            value = annotation.get(key)
            if value is not None:
                _require(_text(value, 2048 if key == 'report_url' else 500),
                         'NCBI annotation identity is invalid.')
                observed[key] = value
        row = {'id': accession, 'name': organism['organism_name'], 'assembly': assembly['assembly_name'],
               'assembly_accession': accession, 'taxon_id': organism['tax_id'],
               'release': accession, 'division': 'RefSeq', 'genebuild': observed.get('name', 'Not supplied'),
               'annotation': observed, 'assembly_status': assembly['assembly_status']}
        return row, {'url': url, 'sha256': hashlib.sha256(raw).hexdigest()}

    def species(self, release, query='', cancel=None, event=None):
        _release(release)
        accession = _accession(query.strip() if isinstance(query, str) else query)
        if event:
            event({'phase': 'discovery', 'message': 'Looking up the exact RefSeq assembly accession'})
        value, _ = self._species(accession, cancel)
        return [value]

    search = species

    def discover(self, release, species_id, cancel=None, event=None):
        _release(release)
        accession = _accession(species_id)
        species, catalog = self._species(accession, cancel)
        digits = _ACCESSION.fullmatch(accession)[1]
        parent = FTP_BASE + '/'.join(digits[index:index + 3] for index in (0, 3, 6)) + '/'
        listing = self.read_metadata(parent, cancel=cancel, max_bytes=1024 * 1024)
        parser = _Links()
        parser.feed(_decode(listing))
        folders = {link[:-1] for link in parser.links if link.endswith('/') and
                   link.startswith(accession + '_') and _component(link[:-1])}
        _require(len(folders) == 1, 'No unique FTP directory exists for the exact RefSeq assembly version.')
        folder = folders.pop()
        root = parent + folder + '/'
        validate_url(root)
        manifest_url = root + 'md5checksums.txt'
        raw = self.read_metadata(manifest_url, cancel=cancel)
        entries, manifest_text = _checksums(raw)
        manifest_sha = hashlib.sha256(raw).hexdigest()
        files, warnings = [], []
        for kind, label, format_name in (('genome', 'Genome FASTA', 'fasta'),
                                         ('annotation', 'Gene annotations (GTF)', 'gtf'),
                                         ('protein', 'Protein sequences', 'fasta')):
            cancelled(cancel)
            filename = folder + _SUFFIXES[kind]
            _require(_component(filename), 'The NCBI resource filename is too long for the local library.')
            if filename not in entries:
                warnings.append(f'{label} is not available for this assembly.')
                continue
            if event:
                event({'phase': 'discovery', 'resource': kind, 'message': f'Finding {label.lower()}'})
            url, size = root + filename, None
            try:
                with self.open_url(url, method='HEAD', cancel=cancel) as response:
                    size = _content_length(response.headers)
                    _require(size is None or size > 0, 'NCBI reference file is empty.')
            except NCBIHTTPError as exc:
                if exc.status not in (405, 501):
                    raise
            checksum = {**entries[filename], 'manifest_url': manifest_url,
                        'manifest_sha256': manifest_sha}
            detail = {'genome': 'Complete genomic sequence file; eukaryotic repeats may be masked to lowercase. Sequence identifiers and case are preserved.',
                      'annotation': 'Observed GTF annotation for this exact assembly; NCBI may update annotation without changing the assembly accession.',
                      'protein': 'Accessioned protein products annotated on this assembly; combined RNA files are not included.'}[kind]
            item = {'id': kind, 'kind': kind, 'label': label, 'filename': filename, 'url': url,
                    'bytes': size, 'size': size, 'format': format_name, 'checksum': checksum,
                    'checksum_manifest': {'url': manifest_url, 'sha256': manifest_sha, 'text': manifest_text},
                    'assembly': species['assembly'], 'detail': detail,
                    'annotation': dict(species['annotation'])}
            if kind == 'genome':
                item.update(sequence_scope='NCBI assembly genomic sequence file', masking='provider supplied; case preserved')
            files.append(item)
        _require(files, 'No supported FASTA, GTF or protein files were found for this RefSeq assembly.')
        if not species['annotation'].get('name'):
            warnings.append('NCBI did not supply an annotation release name; observed metadata and exact file checksums are retained.')
        return {'provider': PROVIDER_ID, 'provider_name': PROVIDER_NAME, 'release': accession,
                'species': species, 'source_catalog': {**catalog, 'directory_url': parent,
                'directory_sha256': hashlib.sha256(listing).hexdigest()}, 'files': files,
                'assembly': species['assembly'], 'assembly_accession': accession,
                'annotation': dict(species['annotation']), 'notice': NOTICE, 'warnings': warnings,
                'data_notice_url': DATA_NOTICE_URL, 'documentation_url': DOCUMENTATION_URL}
