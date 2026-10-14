"""Local Kraken2/Bracken resource and classification contracts, version 1.

No network access or database copying. Database identity is a content fingerprint,
not publisher authentication. The Bracken consumer need not open the enormous
Kraken indexes that it does not consume. See docs/METAGENOMICS-RESOURCES.md.
"""
from __future__ import annotations

import hashlib
import gzip
import json
import math
import os
from pathlib import Path, PureWindowsPath
import re
import stat
import shutil
import tarfile
import tempfile
from urllib.parse import urlsplit


SCHEMA = 1
DATABASE_KIND = 'native-workbench-kraken2-database'
CLASSIFICATION_KIND = 'native-workbench-kraken2-classification'
DATABASE_FILES = ('hash.k2d', 'opts.k2d', 'taxo.k2d')
MAX_JSON_BYTES = 4 * 1024 * 1024
MAX_INTEGER = 2 ** 63 - 1
SHA = re.compile(r'[0-9a-f]{64}\Z')
VERSION = re.compile(r'[0-9]+(?:\.[0-9]+){1,3}(?:[-+][A-Za-z0-9._-]+)?\Z')
RESERVED = {'con', 'prn', 'aux', 'nul', 'conin$', 'conout$'} | {
    prefix + str(n) for prefix in ('com', 'lpt') for n in (*range(1, 10), '¹', '²', '³')}


class ResourceError(ValueError):
    """An external local resource is missing, changed or incompatible."""


def require(condition, message):
    if not condition:
        raise ResourceError(message)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'),
                      ensure_ascii=True, allow_nan=False).encode('utf-8')


def _object(value, required, optional=(), label='Object'):
    require(isinstance(value, dict), label + ' must be an object')
    require(set(required) <= set(value) <= set(required) | set(optional),
            label + ' has missing or unknown fields')


def _text(value, label, maximum=2048, empty=False):
    require(isinstance(value, str) and (empty or bool(value)) and len(value) <= maximum
            and all(ord(c) >= 32 and ord(c) != 127 for c in value),
            label + ' must be short plain text')
    return value


def _integer(value, label, minimum=0, maximum=MAX_INTEGER):
    require(type(value) is int and minimum <= value <= maximum,
            label + ' must be an integer from ' + str(minimum) + ' to ' + str(maximum))
    return value


def _checksum(value, label='SHA-256'):
    require(isinstance(value, str) and SHA.fullmatch(value), label + ' must be lowercase SHA-256')


def _file_record(value, label='File', extra=()):
    _object(value, {'bytes', 'sha256'} | set(extra), label=label)
    _integer(value['bytes'], label + ' size', minimum=1)
    _checksum(value['sha256'], label + ' checksum')


def _source(value):
    _object(value, {'description', 'url', 'release'}, optional={'archive'}, label='Resource source')
    _text(value['description'], 'Source description')
    _text(value['release'], 'Source release', maximum=256)
    url = _text(value['url'], 'Source URL', maximum=2048, empty=True)
    if url:
        parsed = urlsplit(url)
        require(parsed.scheme in ('https', 'http') and parsed.hostname
                and not parsed.username and not parsed.password,
                'Source URL must be ordinary HTTP(S), without credentials')
    if 'archive' in value:
        _file_record(value['archive'], 'Original database archive', extra={'name'})
        _safe_relative(value['archive']['name'], sibling=True)


def _safe_relative(value, allow_dot=False, sibling=False):
    _text(value, 'Relative resource path', maximum=32767)
    if allow_dot and value == '.':
        return Path('.')
    require('\\' not in value and not value.startswith('/') and not PureWindowsPath(value).drive,
            'Relative resource path must use safe forward-slash components')
    parts = value.split('/')
    require(len(parts) <= 32 and (not sibling or len(parts) == 1),
            'Report must be a sibling file' if sibling else 'Resource path is nested too deeply')
    for part in parts:
        require(part not in ('', '.', '..') and len(part) <= 180
                and part[-1] not in '. ' and not any(c in part for c in ':<>"|?*')
                and part.split('.')[0].lower() not in RESERVED,
                'Unsafe relative resource path')
    return Path(*parts)


def _reject_links(path, must_exist=False, ordinary=False):
    """Reject symlinks and all Windows reparse points, including ancestors."""
    path = Path(path).absolute()
    for member in [path, *path.parents]:
        try:
            evidence = member.lstat()
        except FileNotFoundError:
            require(member != path or not must_exist, 'Selected local file does not exist: ' + str(path))
            continue
        require(not stat.S_ISLNK(evidence.st_mode)
                and not (getattr(evidence, 'st_file_attributes', 0) & 0x400),
                'Resource paths must not use symbolic links, junctions or reparse points: ' + str(member))
        if member == path and ordinary:
            require(stat.S_ISREG(evidence.st_mode), 'Selected path is not an ordinary file: ' + str(path))
    return path


def ordinary_file(path):
    return _reject_links(path, must_exist=True, ordinary=True)


def _resolve(value, parent, allow_dot=False, sibling=False, check_links=True):
    _text(value, 'Resource path', maximum=32767)
    candidate = Path(value)
    if candidate.is_absolute():
        require(not sibling, 'Report path must name a sibling file, not an absolute path')
        require('..' not in candidate.parts, 'Resource path must not contain parent traversal')
        # Drive-qualified Windows paths are supported on Windows; never interpret
        # one as a relative filename on another OS.
        return _reject_links(candidate) if check_links else candidate.absolute()
    require(not PureWindowsPath(value).drive, 'Resource uses a path from another operating system; register it again here')
    candidate = Path(parent) / _safe_relative(value, allow_dot=allow_dot, sibling=sibling)
    return _reject_links(candidate) if check_links else candidate.absolute()


def file_record(path):
    """Hash an ordinary file and reject observed changes during the read."""
    path = ordinary_file(path)
    before = path.stat()
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    after = path.stat()
    require((before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
            == (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns),
            'Resource changed while hashing: ' + str(path))
    return {'bytes': after.st_size, 'sha256': digest.hexdigest()}


def verify_file(path, expected):
    ordinary_file(path)
    require(Path(path).stat().st_size == expected['bytes'], 'Resource size changed: ' + str(path))
    actual = file_record(path)
    require(actual['bytes'] == expected['bytes'] and actual['sha256'] == expected['sha256'],
            'Resource checksum changed: ' + str(path))
    return Path(path)


def _unique_pairs(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, 'Resource JSON contains a duplicate key: ' + key)
        result[key] = value
    return result


def read_json(path):
    path = ordinary_file(path)
    require(0 < path.stat().st_size <= MAX_JSON_BYTES, 'Resource JSON must be nonempty and at most 4 MiB')
    with path.open('rb') as stream:
        data = stream.read(MAX_JSON_BYTES + 1)
    require(len(data) <= MAX_JSON_BYTES, 'Resource JSON exceeds 4 MiB')
    try:
        return json.loads(data.decode('utf-8'), object_pairs_hook=_unique_pairs,
                          parse_constant=lambda value: (_ for _ in ()).throw(ResourceError('Nonfinite JSON number')))
    except (UnicodeError, json.JSONDecodeError, RecursionError) as exc:
        raise ResourceError('Invalid UTF-8 resource JSON: ' + str(exc)) from exc


def _read_document(path):
    path = ordinary_file(path)
    require(0 < path.stat().st_size <= MAX_JSON_BYTES, 'Resource JSON must be nonempty and at most 4 MiB')
    before = file_record(path)
    document = read_json(path)
    verify_file(path, before)
    return document, before


def write_json(path, document):
    """Write LF-terminated JSON; never overwrite an existing descriptor/result."""
    data = json.dumps(document, ensure_ascii=False, indent=2, allow_nan=False).encode('utf-8') + b'\n'
    require(len(data) <= MAX_JSON_BYTES, 'Resource JSON exceeds 4 MiB')
    path = Path(path)
    _reject_links(path)
    with path.open('xb') as stream:
        stream.write(data)


def database_fingerprint(files):
    _object(files, DATABASE_FILES, label='Kraken2 database inventory')
    for name in DATABASE_FILES:
        _file_record(files[name], name)
    return hashlib.sha256(canonical(files)).hexdigest()


def validate_resource(path, verify_database=False):
    """Validate a descriptor; only Kraken consumers request index-file hashing.

    Return {document, path, sha256, root, paths}; paths maps the three k2d names
    to absolute Path objects. Default does not require the unused indexes to be
    present, enabling Bracken analysis with a retained classification record.
    """
    path = ordinary_file(path)
    doc, descriptor_record = _read_document(path)
    _object(doc, {'schema', 'kind', 'databaseRoot', 'label', 'source', 'files',
                  'databaseFingerprint', 'kmerLength', 'minimizerLength', 'alphabet',
                  'brackenDistributions'}, label='Kraken2 database resource')
    require(type(doc['schema']) is int and doc['schema'] == SCHEMA and doc['kind'] == DATABASE_KIND,
            'Unsupported Kraken2 database resource schema/kind')
    _text(doc['label'], 'Database label', maximum=256)
    _source(doc['source'])
    require(doc['alphabet'] == 'nucleotide', 'Only nucleotide Kraken2 databases are supported')
    _integer(doc['kmerLength'], 'Database k-mer length', 1, 4096)
    _integer(doc['minimizerLength'], 'Database minimizer length', 1, doc['kmerLength'])
    require(doc['databaseFingerprint'] == database_fingerprint(doc['files']),
            'Database fingerprint does not match its three-file inventory')
    root = _resolve(doc['databaseRoot'], path.parent, allow_dot=True, check_links=verify_database)
    paths = {name: root / name for name in DATABASE_FILES}
    distributions = doc['brackenDistributions']
    require(isinstance(distributions, list) and len(distributions) <= 64,
            'A resource supports at most 64 Bracken read lengths')
    lengths, selected_paths = set(), set()
    for item in distributions:
        _object(item, {'readLength', 'kmerLength', 'path', 'bytes', 'sha256',
                       'databaseFingerprint', 'association', 'source', 'classifierSettings'}, label='Bracken distribution')
        length = _integer(item['readLength'], 'Bracken read length', doc['kmerLength'], 10000000)
        require(length not in lengths, 'Repeated Bracken read length')
        lengths.add(length)
        require(type(item['kmerLength']) is int and item['kmerLength'] == doc['kmerLength'],
                'Bracken distribution k-mer length differs from Kraken2 database')
        _integer(item['bytes'], 'Bracken distribution size', 1)
        _checksum(item['sha256'], 'Bracken distribution checksum')
        require(item['databaseFingerprint'] == doc['databaseFingerprint'],
                'Bracken distribution refers to another database fingerprint')
        require(item['association'] in ('user-attested-external', 'locally-built'),
                'Bracken distribution association must be explicitly recorded')
        _source(item['source'])
        _classifier_settings(item['classifierSettings'])
        selected = _resolve(item['path'], root, check_links=False)
        normalized = os.path.normcase(str(selected)).casefold()
        require(normalized not in selected_paths, 'One distribution file cannot declare several read lengths')
        require(normalized not in {os.path.normcase(str(p)).casefold() for p in paths.values()},
                'A Bracken distribution cannot be a Kraken2 index file')
        selected_paths.add(normalized)
    if verify_database:
        for name in DATABASE_FILES:
            verify_file(paths[name], doc['files'][name])
    verify_file(path, descriptor_record)
    return {'document': doc, 'path': path, 'sha256': descriptor_record['sha256'],
            'root': root, 'paths': paths}


def choose_distribution(resource, read_length, verify=True):
    _integer(read_length, 'Selected Bracken read length', 1, 10000000)
    doc = resource['document']
    choices = [item for item in doc['brackenDistributions'] if item['readLength'] == read_length]
    require(len(choices) == 1, 'No registered Bracken distribution matches read length ' + str(read_length))
    item = choices[0]
    path = _resolve(item['path'], resource['root'], check_links=verify)
    if verify:
        verify_file(path, item)
    return {'document': item, 'path': path}


def _mate_stats(value, label, fragments):
    _object(value, {'records', 'bases', 'minLength', 'maxLength'}, label=label)
    require(type(value['records']) is int and value['records'] == fragments,
            label + ' record count differs from fragment count')
    bases = _integer(value['bases'], label + ' bases', fragments)
    minimum = _integer(value['minLength'], label + ' minimum length', 1, 10000000)
    maximum = _integer(value['maxLength'], label + ' maximum length', minimum, 10000000)
    require(fragments * minimum <= bases <= fragments * maximum,
            label + ' base total contradicts observed lengths')
    return bases


def _classifier_settings(value, identity=False):
    fields = {'confidence', 'minimumHitGroups', 'minimumBaseQuality', 'quick'}
    _object(value, fields | ({'name', 'version'} if identity else set()), label='Classifier settings')
    if identity:
        require(value['name'] == 'Kraken2' and isinstance(value['version'], str)
                and VERSION.fullmatch(value['version']), 'Classifier must identify an exact Kraken2 version')
    confidence = value['confidence']
    require(type(confidence) in (int, float) and math.isfinite(confidence) and 0 <= confidence <= 1,
            'Kraken2 confidence must be between zero and one')
    _integer(value['minimumHitGroups'], 'Minimum hit groups', 1, 1000000)
    _integer(value['minimumBaseQuality'], 'Minimum base quality', 0, 93)
    require(type(value['quick']) is bool, 'Quick classification setting must be boolean')


def validate_classification(path, resource):
    """Verify a Workbench classification record and its sibling six-column report.

    Return {document, path, sha256, report}. This is integrity/provenance checking,
    not proof against forged JSON or verification of the distribution's origin.
    """
    path = ordinary_file(path)
    doc, descriptor_record = _read_document(path)
    _object(doc, {'schema', 'kind', 'success', 'databaseFingerprint', 'report',
                  'classifier', 'reads'}, label='Kraken2 classification record')
    require(type(doc['schema']) is int and doc['schema'] == SCHEMA
            and doc['kind'] == CLASSIFICATION_KIND and doc['success'] is True,
            'Unsupported or unsuccessful Kraken2 classification record')
    require(doc['databaseFingerprint'] == resource['document']['databaseFingerprint'],
            'Classification and selected resource use different Kraken2 database fingerprints')
    report = doc['report']
    _file_record(report, 'Classification report', extra={'path', 'format'})
    require(report['format'] == 'kraken2-six-column', 'Bracken requires an ordinary six-column Kraken2 report')
    report_path = _resolve(report['path'], path.parent, sibling=True)
    require(report_path != path, 'A classification record cannot be its own report')
    classifier = doc['classifier']
    _classifier_settings(classifier, identity=True)
    reads = doc['reads']
    _object(reads, {'paired', 'unit', 'fragments', 'reads', 'bases', 'classifiedFragments',
                   'unclassifiedFragments', 'mate1', 'mate2'}, label='Observed reads')
    require(type(reads['paired']) is bool, 'Paired setting must be boolean')
    require(reads['unit'] == ('fragments' if reads['paired'] else 'reads'),
            'Paired classifications count fragments, not individual mates')
    fragments = _integer(reads['fragments'], 'Fragment count', 1)
    require(type(reads['reads']) is int and reads['reads'] == fragments * (2 if reads['paired'] else 1),
            'Read count contradicts paired/single fragment count')
    classified = _integer(reads['classifiedFragments'], 'Classified fragment count')
    unclassified = _integer(reads['unclassifiedFragments'], 'Unclassified fragment count')
    require(classified + unclassified == fragments, 'Classified and unclassified counts do not partition input fragments')
    bases = _mate_stats(reads['mate1'], 'Mate 1', fragments)
    if reads['paired']:
        bases += _mate_stats(reads['mate2'], 'Mate 2', fragments)
    else:
        require(reads['mate2'] is None, 'Single-read classification cannot contain mate 2 statistics')
    require(type(reads['bases']) is int and reads['bases'] == bases, 'Total bases contradict mate statistics')
    verify_file(report_path, report)
    verify_file(path, descriptor_record)
    return {'document': doc, 'path': path, 'sha256': descriptor_record['sha256'], 'report': report_path}


def validate_registration_metadata(*, label, source_description, source_url, source_release, archive=None):
    """Validate inexpensive declarations before extraction or index hashing."""
    _text(label, 'Database label', maximum=256)
    source = {'description': source_description, 'url': source_url, 'release': source_release}
    if archive is not None:
        source['archive'] = dict(archive)
    _source(source)
    return source


def register_database(anchor, output, *, label, source_description, source_url,
                      source_release, kmer_length, minimizer_length,
                      distributions=(), attest_distributions=False, archive=None):
    """Register existing index bytes, without changing/copying the database.

    The calling Kraken adapter must inspect opts.k2d and reject protein or
    incompatible databases before providing kmer_length/minimizer_length.
    External distributions require an explicit declaration of matching source
    database, exact filename read length, and standard Kraken model settings.
    """
    source = validate_registration_metadata(label=label, source_description=source_description,
        source_url=source_url, source_release=source_release, archive=archive)
    _integer(kmer_length, 'Database k-mer length', 1, 4096)
    _integer(minimizer_length, 'Database minimizer length', 1, kmer_length)
    require(isinstance(distributions, (list, tuple)) and len(distributions) <= 64,
            'Select at most 64 Bracken distribution files')
    require(not distributions or attest_distributions is True,
            'Confirm the distributions were made for these exact database files, read lengths and standard Kraken2 settings')
    selected_distributions, lengths, selected_paths = [], set(), set()
    for selected in distributions:
        selected = ordinary_file(selected)
        match = re.fullmatch(r'database([1-9][0-9]{0,7})mers\.kmer_distrib', selected.name)
        require(match is not None, 'Distribution filename must be database<N>mers.kmer_distrib')
        length = _integer(int(match.group(1)), 'Bracken read length', kmer_length, 10000000)
        require(length not in lengths, 'Repeated Bracken read length')
        lengths.add(length)
        normalized = os.path.normcase(str(selected)).casefold()
        require(normalized not in selected_paths, 'One distribution file cannot declare several read lengths')
        selected_paths.add(normalized)
        selected_distributions.append((selected, length))
    anchor = ordinary_file(anchor)
    require(anchor.name == 'hash.k2d', 'Select the hash.k2d file in the Kraken2 database folder')
    root = anchor.parent
    for name in DATABASE_FILES:
        ordinary_file(root / name)
    output = Path(output).absolute()
    _reject_links(output)
    require(not output.exists(), 'Refusing to overwrite an existing database descriptor: ' + str(output))
    require(_reject_links(output.parent, must_exist=True).is_dir(), 'Database descriptor output parent must be a folder')
    # Only after all inexpensive choices and file-presence checks have passed do
    # we scan potentially hundreds of gigabytes of immutable database content.
    files = {name: file_record(root / name) for name in DATABASE_FILES}
    fingerprint = database_fingerprint(files)
    doc = {'schema': SCHEMA, 'kind': DATABASE_KIND, 'databaseRoot': str(root),
           'label': label, 'source': source, 'files': files,
           'databaseFingerprint': fingerprint, 'kmerLength': kmer_length,
           'minimizerLength': minimizer_length, 'alphabet': 'nucleotide',
           'brackenDistributions': []}
    for selected, length in selected_distributions:
        doc['brackenDistributions'].append({
            'readLength': length, 'kmerLength': kmer_length,
            'path': str(selected), **file_record(selected), 'databaseFingerprint': fingerprint,
            'association': 'user-attested-external', 'source': dict(source),
            'classifierSettings': {'confidence': 0, 'minimumHitGroups': 2,
                                   'minimumBaseQuality': 0, 'quick': False}})
    doc['brackenDistributions'].sort(key=lambda item: item['readLength'])
    write_json(output, doc)
    try:
        return validate_resource(output, verify_database=True)
    except BaseException:
        output.unlink(missing_ok=True)
        raise


def extract_database_archive(archive, output_parent, include_distributions=False):
    """Safely extract a local prebuilt .tar/.tar.gz into an owned result child.

    Select the three k2d files. With include_distributions=True, also select
    database<N>mers.kmer_distrib files for explicitly attested Bracken use.
    They must occupy the archive root or one common directory prefix. Ancillary
    ordinary files are ignored, but unsafe/link/special entries are rejected.
    Return {root, anchor, distributions, archive}; caller supplies scientific
    opts inspection and explicit source/model attestation before registration.
    """
    require(type(include_distributions) is bool, 'Archive distribution selection must be boolean')
    archive = ordinary_file(archive)
    suffix = archive.name.lower()
    require(suffix.endswith(('.tar', '.tar.gz', '.tgz')), 'Select a local .tar, .tar.gz or .tgz database archive')
    original = file_record(archive)
    parent = _reject_links(output_parent, must_exist=True)
    require(parent.is_dir(), 'Archive extraction parent must be an existing folder')
    root = Path(tempfile.mkdtemp(prefix='database-resource-', dir=parent))
    selected, seen, prefix = {}, set(), None
    entries = 0
    try:
        # Streaming mode avoids an unbounded member list for large archives.
        # Keep PAX/GNU extension allocation bounded before TarInfo parses it.
        class BoundedTarInfo(tarfile.TarInfo):
            def _proc_member(self, tar):
                tar._workbench_header_count = getattr(tar, '_workbench_header_count', 0) + 1
                require(tar._workbench_header_count <= 100000,
                        'Database archive has more than 100,000 headers')
                require(self.type != tarfile.GNUTYPE_SPARSE, 'GNU sparse archive members are unsupported')
                if self.type in (tarfile.XHDTYPE, tarfile.XGLTYPE, tarfile.SOLARIS_XHDTYPE,
                                 tarfile.GNUTYPE_LONGNAME, tarfile.GNUTYPE_LONGLINK):
                    require(self.size <= 1024 * 1024, 'Archive extension header exceeds 1 MiB')
                    tar._workbench_extension_bytes = getattr(tar, '_workbench_extension_bytes', 0) + self.size
                    require(tar._workbench_extension_bytes <= 16 * 1024 * 1024,
                            'Archive extension metadata exceeds 16 MiB')
                    tar._workbench_extension_depth = getattr(tar, '_workbench_extension_depth', 0) + 1
                    require(tar._workbench_extension_depth <= 32,
                            'Archive extension headers are nested too deeply')
                    try:
                        return super()._proc_member(tar)
                    finally:
                        tar._workbench_extension_depth -= 1
                return super()._proc_member(tar)

            # Reject before the stdlib sparse map parsers allocate/read their
            # extension chains. Header-size bounds alone do not bound v1 maps.
            def _proc_sparse(self, *args, **kwargs):
                raise ResourceError('GNU sparse archive members are unsupported')

            def _proc_gnusparse_00(self, *args, **kwargs):
                raise ResourceError('PAX GNU sparse archive members are unsupported')

            def _proc_gnusparse_01(self, *args, **kwargs):
                raise ResourceError('PAX GNU sparse archive members are unsupported')

            def _proc_gnusparse_10(self, *args, **kwargs):
                raise ResourceError('PAX GNU sparse archive members are unsupported')

        # gzip.GzipFile validates CRC/length trailers; tarfile's internal r|gz
        # decoder does not provide the same full-stream integrity check.
        opener = gzip.open if suffix.endswith(('.gz', '.tgz')) else open
        with opener(archive, 'rb') as payload, tarfile.open(fileobj=payload, mode='r|',
                                                         tarinfo=BoundedTarInfo) as incoming:
            for member in incoming:
                entries += 1
                require(entries <= 100000, 'Database archive has more than 100,000 entries')
                name = member.name
                require(len(name) <= 1024, 'Database archive member path exceeds 1,024 characters')
                incoming.members.clear()
                # A leading ./ is standard tar output, not a traversal.
                if name.startswith('./'):
                    name = name[2:]
                if member.isdir() and name in ('', '.'):
                    continue
                if member.isdir():
                    name = name.rstrip('/')
                safe = _safe_relative(name)
                folded = safe.as_posix().casefold()
                require(folded not in seen, 'Archive contains a duplicate or case-colliding path: ' + name)
                seen.add(folded)
                require(member.isdir() or member.isreg(), 'Archive contains a link or nonregular member: ' + name)
                require(not getattr(member, 'sparse', None), 'Sparse database archive members are unsupported')
                require(not any(key.startswith('GNU.sparse.') for key in member.pax_headers),
                        'PAX GNU sparse archive members are unsupported')
                _integer(member.size, 'Archive member size', 0)
                if not member.isreg():
                    continue
                basename = safe.name
                wanted = basename in DATABASE_FILES or (include_distributions and
                    re.fullmatch(r'database[1-9][0-9]{0,7}mers\.kmer_distrib', basename))
                if not wanted:
                    continue
                require(len(safe.parts) <= 2, 'Database files must share the archive root or one directory prefix')
                current_prefix = safe.parent.as_posix()
                if prefix is None:
                    prefix = current_prefix
                require(current_prefix == prefix, 'Required database files use inconsistent archive prefixes')
                require(basename.casefold() not in selected, 'Archive repeats a required database file')
                require(len(selected) < len(DATABASE_FILES) + 64, 'Archive contains more than 64 Bracken distributions')
                require(member.size > 0, 'Required database file is empty: ' + name)
                require(shutil.disk_usage(root).free >= member.size + 16 * 1024 * 1024,
                        'Insufficient free disk space for database file ' + name)
                destination = root / basename
                stream = incoming.extractfile(member)
                require(stream is not None, 'Cannot read database member ' + name)
                copied = 0
                with stream, destination.open('xb') as output:
                    while copied < member.size:
                        data = stream.read(min(1024 * 1024, member.size - copied))
                        require(bool(data), 'Database archive member is truncated: ' + name)
                        output.write(data)
                        copied += len(data)
                require(copied == member.size, 'Database archive member size differs: ' + name)
                selected[basename.casefold()] = destination
            # Consume beyond tar's end blocks so gzip validates its trailer and
            # all concatenated members, including otherwise ignored tail data.
            for _ in iter(lambda: payload.read(1024 * 1024), b''):
                pass
        require(set(DATABASE_FILES) <= set(selected), 'Archive is missing hash.k2d, opts.k2d or taxo.k2d')
        verify_file(archive, original)
        return {'root': root, 'anchor': root / 'hash.k2d',
                'distributions': sorted((path for name, path in selected.items() if name not in DATABASE_FILES),
                                        key=lambda path: path.name),
                'archive': {'name': archive.name, **original}}
    except BaseException as error:
        try:
            shutil.rmtree(root)
        except OSError as cleanup_error:
            raise ResourceError('Database archive preparation failed and its partial folder could not be removed: '
                                + str(root) + '. Close programs using that folder, then remove it.') from cleanup_error
        if isinstance(error, (EOFError, tarfile.TarError, OSError)):
            raise ResourceError('Cannot read the database archive. Check that the download is complete and is a valid '
                                '.tar or .tar.gz file. Details: ' + str(error)[:512]) from error
        raise
