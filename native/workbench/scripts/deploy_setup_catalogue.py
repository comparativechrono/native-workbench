#!/usr/bin/env python3
"""Verify and publish the reviewed official setup catalogue's public documents.

Signing is a separate protected job. This command accepts only the three public
publisher outputs; it never reads a signing key or a GitHub secrets endpoint.
--verify-only is entirely offline and does not need a GitHub token. Deployment
requires GITHUB_TOKEN and appends signed history on the catalogue branch without
force-pushing. A fresh anonymous read verifies the published bytes afterwards.
"""
from __future__ import annotations

import argparse
import base64
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'workspace'))
from pack_manager import validate_catalog, validate_source
from pack_security import key_fingerprint, require, strict_json
from prepare_setup_catalogue import read_lock

REPOSITORY = 'comparativechrono/workbench'
API = 'https://api.github.com/repos/' + REPOSITORY
RAW = 'https://raw.githubusercontent.com/' + REPOSITORY + '/'
CATALOG_URL = RAW + 'catalogue/catalogue.json'
SOURCE_ID = 'native-workbench-official'
SOURCE_NAME = 'Native Workbench official tools'
HOSTS = sorted(['github.com', 'raw.githubusercontent.com', 'release-assets.githubusercontent.com'])
DOCUMENTS = ('catalogue.json', 'source.json', 'publication-report.json')
PUBLIC_RECEIPT = 'deployment-receipt.json'
MAX_DOCUMENT = 4 * 1024 * 1024
MAX_RESPONSE = 16 * 1024 * 1024
SHA1 = re.compile(r'[0-9a-f]{40}')
SHA256 = re.compile(r'[0-9a-f]{64}')
STAMP = re.compile(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z')
HISTORY_STAMP = re.compile(r'\d{8}T\d{6}Z')
ARCHIVE_IDENTITY_FIELDS = ('size', 'sha256', 'manifestSha256', 'downloadURL')


def encoded(value):
    return (json.dumps(value, indent=2, sort_keys=True, ensure_ascii=True,
                       allow_nan=False) + '\n').encode('ascii')


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def blob_sha(raw):
    return hashlib.sha1(b'blob ' + str(len(raw)).encode('ascii') + b'\0' + raw).hexdigest()


def date(value):
    require(isinstance(value, str) and STAMP.fullmatch(value),
            'Publication timestamp must use UTC YYYY-MM-DDTHH:MM:SSZ')
    try:
        return datetime.strptime(value, '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=timezone.utc)
    except ValueError as exc:
        raise ValueError('Invalid publication timestamp') from exc


def history_stamp(value):
    return date(value).strftime('%Y%m%dT%H%M%SZ')


def validate_documents(documents, expected_fingerprint, lock=None):
    """Verify explicit public fields, signature, report, and optional current pins."""
    require(isinstance(expected_fingerprint, str) and SHA256.fullmatch(expected_fingerprint),
            'Expected a reviewed lowercase SHA-256 public-key fingerprint')
    require(set(documents) == set(DOCUMENTS), 'Expected exactly the three public publisher documents')
    require(all(isinstance(raw, bytes) and 0 < len(raw) <= MAX_DOCUMENT for raw in documents.values()),
            'Invalid public document size')
    source = validate_source(strict_json(documents['source.json']))
    require(source['id'] == SOURCE_ID and source['name'] == SOURCE_NAME and
            source['catalogUrl'] == CATALOG_URL and source['allowedHosts'] == HOSTS,
            'Source does not match the reviewed official source identity, URL and exact hosts')
    require(key_fingerprint(source['publicKey']) == expected_fingerprint,
            'Source public-key fingerprint differs from the reviewed fingerprint')
    payload = validate_catalog(documents['catalogue.json'], source)
    date(payload['publishedAt'])
    report = strict_json(documents['publication-report.json'])
    require(isinstance(report, dict) and set(report) ==
            {'schema', 'packs', 'sourceKeyFingerprint', 'publishedAt', 'uploaded'} and
            type(report['schema']) is int and report['schema'] == 1 and
            type(report['packs']) is int and report['packs'] == len(payload['packs']) and
            report['sourceKeyFingerprint'] == expected_fingerprint and
            report['publishedAt'] == payload['publishedAt'] and report['uploaded'] is False,
            'Public publisher report differs from the verified catalogue')
    require(payload['packs'], 'An official setup catalogue must contain packs')
    if lock is not None:
        pins = {(row['id'], row['version']): row for row in lock['packs']}
        require({(row['id'], row['version']) for row in payload['packs']} == set(pins),
                'Catalogue pack identities differ from the reviewed setup selection')
        for row in payload['packs']:
            pin = pins[(row['id'], row['version'])]
            require(all(row[field] == pin[field] for field in
                        ('size', 'sha256', 'manifestSha256', 'downloadURL')),
                    'Catalogue archive pins or immutable URLs differ from the setup lock')
    return payload


def load_documents(directory):
    directory = Path(directory)
    require(directory.is_dir() and not any(p.is_symlink() for p in (directory, *directory.parents)),
            'Public documents must be in a regular directory without symlinks')
    require({p.name for p in directory.iterdir()} == set(DOCUMENTS),
            'Public documents directory must contain only the three publisher outputs')
    result = {}
    for name in DOCUMENTS:
        path = directory / name
        require(path.is_file() and not path.is_symlink() and 0 < path.stat().st_size <= MAX_DOCUMENT,
                'Expected a bounded regular public document')
        result[name] = path.read_bytes()
    return result


class APIError(ValueError):
    def __init__(self, status=None):
        self.status = status
        # Never include the URL, request, API response body or exception repr.
        super().__init__('GitHub API request failed' + (f' (HTTP {status})' if status else ''))


class NoRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        raise APIError(code)


class GitHub:
    def __init__(self, token):
        require(isinstance(token, str) and token and not any(c.isspace() for c in token),
                'Deployment requires a valid GITHUB_TOKEN')
        self._token = token
        self._opener = urllib.request.build_opener(NoRedirects())

    def request(self, method, path, document=None):
        # No caller-supplied URLs or secrets endpoints. Authentication never
        # reaches a redirect destination, including another GitHub hostname.
        allowed = {'GET': r'/git/(?:ref/heads/catalogue|commits/[0-9a-f]{40}|'
                           r'trees/[0-9a-f]{40}\?recursive=1|blobs/[0-9a-f]{40})',
                   'POST': r'/git/(?:blobs|trees|commits|refs)',
                   'PATCH': r'/git/refs/heads/catalogue'}
        require(method in allowed and isinstance(path, str) and
                re.fullmatch(allowed[method], path), 'Unexpected GitHub API operation')
        request = urllib.request.Request(API + path, method=method,
            data=encoded(document) if document is not None else None,
            headers={'Authorization': 'Bearer ' + self._token,
                     'Accept': 'application/vnd.github+json',
                     'X-GitHub-Api-Version': '2022-11-28',
                     'Content-Type': 'application/json', 'User-Agent': 'NativeWorkbench-Catalogue-Publisher'})
        try:
            with self._opener.open(request, timeout=30) as response:
                require(response.geturl() == API + path, 'GitHub API redirected unexpectedly')
                raw = response.read(MAX_RESPONSE + 1)
                require(len(raw) <= MAX_RESPONSE, 'GitHub API response exceeds the size limit')
                try:
                    return strict_json(raw)
                except ValueError:
                    raise APIError() from None
        except urllib.error.HTTPError as exc:
            raise APIError(exc.code) from None
        except (urllib.error.URLError, TimeoutError, OSError):
            raise APIError() from None


def checked_sha(value):
    require(isinstance(value, str) and SHA1.fullmatch(value), 'GitHub returned an invalid Git object ID')
    return value


def branch_head(api):
    try:
        result = api.request('GET', '/git/ref/heads/catalogue')
    except APIError as exc:
        if exc.status == 404:
            return None
        raise
    require(isinstance(result, dict) and result.get('ref') == 'refs/heads/catalogue' and
            isinstance(result.get('object'), dict) and result['object'].get('type') == 'commit',
            'Malformed existing catalogue branch reference')
    return checked_sha(result['object'].get('sha'))


def read_blob(api, entry):
    require(entry.get('type') == 'blob' and entry.get('mode') == '100644' and
            type(entry.get('size')) is int and 0 < entry['size'] <= MAX_DOCUMENT,
            'Published catalogue documents must be bounded regular Git blobs')
    sha = checked_sha(entry.get('sha'))
    result = api.request('GET', '/git/blobs/' + sha)
    require(isinstance(result, dict) and result.get('sha') == sha and result.get('encoding') == 'base64' and
            isinstance(result.get('content'), str), 'Malformed public Git blob response')
    try:
        raw = base64.b64decode(''.join(result['content'].split()), validate=True)
    except ValueError as exc:
        raise ValueError('Malformed public Git blob encoding') from exc
    require(len(raw) == entry['size'] and blob_sha(raw) == sha, 'Public Git blob integrity check failed')
    return raw


def validate_public_receipt(raw, documents, fingerprint, stamp):
    receipt = strict_json(raw)
    require(isinstance(receipt, dict) and set(receipt) ==
            {'schema', 'repository', 'sourceCommit', 'sourceKeyFingerprint', 'publishedAt',
             'documents', 'lockSha256', 'profileSha256', 'signaturesVerified'},
            'Unexpected fields in public deployment receipt')
    require(type(receipt['schema']) is int and receipt['schema'] == 1 and
            receipt['repository'] == REPOSITORY and isinstance(receipt['sourceCommit'], str) and
            SHA1.fullmatch(receipt['sourceCommit']) and receipt['sourceKeyFingerprint'] == fingerprint and
            receipt['publishedAt'] == stamp and receipt['signaturesVerified'] is True and
            all(isinstance(receipt[field], str) and SHA256.fullmatch(receipt[field])
                for field in ('lockSha256', 'profileSha256')) and
            receipt['documents'] == {name: digest(documents[name]) for name in DOCUMENTS},
            'Public deployment receipt differs from signed history')


def existing_catalogue(api, head, fingerprint):
    """Reject malformed history and retain every published pack version's pins."""
    if head is None:
        return None, {}, None, {}
    commit = api.request('GET', '/git/commits/' + head)
    require(isinstance(commit, dict) and commit.get('sha') == head and isinstance(commit.get('tree'), dict),
            'Malformed catalogue commit')
    tree_sha = checked_sha(commit['tree'].get('sha'))
    result = api.request('GET', '/git/trees/' + tree_sha + '?recursive=1')
    require(isinstance(result, dict) and result.get('sha') == tree_sha and result.get('truncated') is False and
            isinstance(result.get('tree'), list) and len(result['tree']) <= 20000,
            'Catalogue tree is malformed, truncated or too large')
    paths = {}
    for entry in result['tree']:
        require(isinstance(entry, dict) and isinstance(entry.get('path'), str) and
                entry['path'] not in paths, 'Catalogue tree contains malformed or duplicate paths')
        paths[entry['path']] = entry
    require(set(DOCUMENTS) <= set(paths), 'Existing catalogue branch lacks its public documents')
    current = {name: read_blob(api, paths[name]) for name in DOCUMENTS}
    payload = validate_documents(current, fingerprint)
    groups = {}
    for path, entry in paths.items():
        if path == 'history':
            require(entry.get('type') == 'tree' and entry.get('mode') == '040000',
                    'Published history root is not a Git tree')
        elif path.startswith('history/'):
            parts = path.split('/')
            require(len(parts) in (2, 3) and HISTORY_STAMP.fullmatch(parts[1]),
                    'Malformed published history path')
            if len(parts) == 2:
                require(entry.get('type') == 'tree' and entry.get('mode') == '040000',
                        'Published history directory is not a Git tree')
            else:
                require(parts[2] in (*DOCUMENTS, PUBLIC_RECEIPT), 'Unexpected file in signed history')
                groups.setdefault(parts[1], {})[parts[2]] = entry
    require(groups and history_stamp(payload['publishedAt']) in groups,
            'Existing catalogue has no matching immutable signed history')
    historical_pins = {}
    for stamp, entries in groups.items():
        require(set(entries) == set(DOCUMENTS) | {PUBLIC_RECEIPT},
                'Published history lacks its public documents or provenance receipt')
        documents = {name: read_blob(api, entries[name]) for name in DOCUMENTS}
        historical = validate_documents(documents, fingerprint)
        require(history_stamp(historical['publishedAt']) == stamp and
                date(historical['publishedAt']) <= date(payload['publishedAt']),
                'Published history timestamp is inconsistent with current catalogue')
        validate_public_receipt(read_blob(api, entries[PUBLIC_RECEIPT]), documents,
                                fingerprint, historical['publishedAt'])
        if stamp == history_stamp(payload['publishedAt']):
            require(documents == current, 'Current catalogue differs from its immutable history')
        for row in historical['packs']:
            identity = (row['id'], row['version'])
            pins = tuple(row[field] for field in ARCHIVE_IDENTITY_FIELDS)
            require(identity not in historical_pins or historical_pins[identity] == pins,
                    'Signed history contains inconsistent archive identities for a published pack version')
            historical_pins[identity] = pins
    return tree_sha, paths, payload, historical_pins


def anonymous_get(url):
    require(isinstance(url, str) and url.startswith(RAW) and
            re.fullmatch(re.escape(RAW) + r'(?:catalogue|[0-9a-f]{40})/(?:history/[0-9TZ]+/)?'
                         r'(?:catalogue|source|publication-report|deployment-receipt)\.json', url),
            'Unexpected anonymous catalogue URL')
    request = urllib.request.Request(url, headers={'User-Agent': 'NativeWorkbench-Catalogue-Verifier',
                                                  'Accept-Encoding': 'identity', 'Cache-Control': 'no-cache'})
    opener = urllib.request.build_opener(NoRedirects())
    try:
        with opener.open(request, timeout=20) as response:
            require(response.getcode() == 200 and response.geturl() == url and
                    response.headers.get('Content-Encoding', 'identity').lower() == 'identity',
                    'Anonymous download did not return the public document')
            raw = response.read(MAX_DOCUMENT + 1)
            require(0 < len(raw) <= MAX_DOCUMENT, 'Anonymous public document exceeds its size limit')
            return raw
    except (urllib.error.URLError, TimeoutError, OSError):
        raise ValueError('Anonymous public document download failed') from None


def verify_live(documents, receipt_raw, stamp, commit, fingerprint, lock, get=anonymous_get, pause=time.sleep):
    """Check moving URLs and commit-pinned history, allowing bounded CDN delay."""
    expected = {RAW + 'catalogue/' + name: raw for name, raw in documents.items()}
    expected.update({RAW + commit + '/history/' + stamp + '/' + name: raw
                     for name, raw in {**documents, PUBLIC_RECEIPT: receipt_raw}.items()})
    for attempt in range(7):
        try:
            retrieved = {url: get(url) for url in expected}
            require(retrieved == expected, 'Anonymous published bytes differ from verified deployment')
            validate_documents({name: retrieved[RAW + 'catalogue/' + name] for name in DOCUMENTS},
                               fingerprint, lock)
            validate_documents({name: retrieved[RAW + commit + '/history/' + stamp + '/' + name]
                                for name in DOCUMENTS}, fingerprint, lock)
            return {'anonymousDownloadsVerified': True, 'anonymousVerificationAttempts': attempt + 1,
                    'verifiedPublicUrls': sorted(expected)}
        except ValueError:
            if attempt == 6:
                raise ValueError('Publication committed, but fresh anonymous verification failed; inspect the external receipt before retrying') from None
            pause(10)


def deploy(documents, fingerprint, source_commit, lock, lock_sha, profile_sha,
           api, get=anonymous_get, pause=time.sleep, checkpoint=None):
    payload = validate_documents(documents, fingerprint, lock)
    require(isinstance(source_commit, str) and SHA1.fullmatch(source_commit), 'Expected an exact source commit')
    require(all(isinstance(value, str) and SHA256.fullmatch(value) for value in (lock_sha, profile_sha)),
            'Expected exact source lock and profile hashes')
    # Source commit must exist in the intended repository before publication.
    source_record = api.request('GET', '/git/commits/' + source_commit)
    require(isinstance(source_record, dict) and source_record.get('sha') == source_commit,
            'Source commit does not exist in the publication repository')
    old_head = branch_head(api)
    base_tree, paths, old_payload, historical_pins = existing_catalogue(api, old_head, fingerprint)
    require(old_payload is None or date(payload['publishedAt']) > date(old_payload['publishedAt']),
            'Publication timestamp must strictly increase; existing catalogue is retained')
    for row in payload['packs']:
        previous = historical_pins.get((row['id'], row['version']))
        require(previous is None or tuple(row[field] for field in ARCHIVE_IDENTITY_FIELDS) == previous,
                'A published pack version cannot change its archive identity or URL')
    stamp = history_stamp(payload['publishedAt'])
    prefix = 'history/' + stamp + '/'
    require('history/' + stamp not in paths and not any(path.startswith(prefix) for path in paths),
            'Published history already exists and cannot be overwritten')
    public_receipt = {'schema': 1, 'repository': REPOSITORY, 'sourceCommit': source_commit,
                      'sourceKeyFingerprint': fingerprint, 'publishedAt': payload['publishedAt'],
                      'documents': {name: digest(documents[name]) for name in DOCUMENTS},
                      'lockSha256': lock_sha, 'profileSha256': profile_sha, 'signaturesVerified': True}
    receipt_raw = encoded(public_receipt)
    additions = {**documents, **{prefix + name: raw for name, raw in documents.items()},
                 prefix + PUBLIC_RECEIPT: receipt_raw}
    tree_entries, blobs = [], {}
    for path, raw in additions.items():
        wanted = blob_sha(raw)
        if wanted not in blobs:
            result = api.request('POST', '/git/blobs', {'content': base64.b64encode(raw).decode('ascii'), 'encoding': 'base64'})
            require(isinstance(result, dict) and result.get('sha') == wanted,
                    'GitHub stored an unexpected public document blob')
            blobs[wanted] = True
        tree_entries.append({'path': path, 'mode': '100644', 'type': 'blob', 'sha': wanted})
    body = {'tree': tree_entries}
    if base_tree is not None:
        body['base_tree'] = base_tree
    tree = api.request('POST', '/git/trees', body)
    tree_sha = checked_sha(tree.get('sha') if isinstance(tree, dict) else None)
    commit = api.request('POST', '/git/commits', {
        'message': 'Publish official setup catalogue ' + payload['publishedAt'] + '\n\nSource-Commit: ' + source_commit,
        'tree': tree_sha, 'parents': [old_head] if old_head else []})
    new_head = checked_sha(commit.get('sha') if isinstance(commit, dict) else None)
    # Recheck before the non-force update. A race after this read is rejected by
    # GitHub because our one-parent commit cannot descend from another writer.
    require(branch_head(api) == old_head, 'Catalogue branch changed during publication; no ref was updated')
    external = {**public_receipt, 'catalogueCommit': new_head, 'previousCatalogueCommit': old_head,
                'published': None, 'publicationAttempted': True, 'anonymousDownloadsVerified': False,
                'historyPath': prefix, 'publicationUrl': CATALOG_URL}
    if checkpoint:
        # If the connection fails after GitHub accepted the ref, preserve the
        # intended exact commit and explicitly unknown status for investigation.
        checkpoint(external)
    if old_head is None:
        ref = api.request('POST', '/git/refs', {'ref': 'refs/heads/catalogue', 'sha': new_head})
    else:
        ref = api.request('PATCH', '/git/refs/heads/catalogue', {'sha': new_head, 'force': False})
    require(isinstance(ref, dict) and ref.get('ref') == 'refs/heads/catalogue' and
            isinstance(ref.get('object'), dict) and ref['object'].get('sha') == new_head,
            'Unexpected publication ref response; inspect catalogue branch before retrying')
    external['published'] = True
    if checkpoint:
        checkpoint(external)
    external.update(verify_live(documents, receipt_raw, stamp, new_head, fingerprint, lock, get, pause))
    if checkpoint:
        checkpoint(external)
    return external


def source_inputs(source_commit):
    """Tie checked lock/profile bytes to the exact clean checkout named in receipt."""
    require(isinstance(source_commit, str) and SHA1.fullmatch(source_commit), 'Expected an exact source commit')
    paths = ('publishing/setup-assets.json', 'workspace/setup-profile.json')
    try:
        head = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=ROOT, check=True,
                              stdout=subprocess.PIPE, stderr=subprocess.DEVNULL).stdout.decode('ascii').strip()
        require(head == source_commit, 'Source commit differs from the checked-out commit')
        for path in paths:
            committed = subprocess.run(['git', 'show', source_commit + ':' + path], cwd=ROOT, check=True,
                                       stdout=subprocess.PIPE, stderr=subprocess.DEVNULL).stdout
            require(committed == (ROOT / path).read_bytes(), 'Setup lock/profile differs from the named source commit')
    except (OSError, subprocess.CalledProcessError):
        raise ValueError('Cannot verify the named source checkout') from None
    return read_lock(ROOT / paths[0], ROOT / paths[1]), *(digest((ROOT / p).read_bytes()) for p in paths)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--documents', type=Path, required=True)
    parser.add_argument('--expected-fingerprint', required=True)
    parser.add_argument('--source-commit', required=True)
    parser.add_argument('--verify-only', action='store_true')
    parser.add_argument('--receipt', type=Path, help='New external JSON receipt, preserved even if post-publication checks fail')
    args = parser.parse_args(argv)
    stream = None
    try:
        documents = load_documents(args.documents)
        lock, lock_sha, profile_sha = source_inputs(args.source_commit)
        payload = validate_documents(documents, args.expected_fingerprint, lock)
        if args.receipt:
            path = args.receipt.absolute()
            require(not path.resolve().is_relative_to(ROOT) and
                    not path.resolve().is_relative_to(args.documents.resolve()) and
                    not any(p.is_symlink() for p in (path, *path.parents)),
                    'Receipt must be external to the checkout and public documents directory, without symlinks')
            stream = path.open('x+b')
        def checkpoint(receipt):
            if stream:
                stream.seek(0)
                stream.write(encoded(receipt))
                stream.truncate()
                stream.flush()
                os.fsync(stream.fileno())
        if args.verify_only:
            result = {'schema': 1, 'verified': True, 'published': False, 'networkAccessed': False,
                      'sourceCommit': args.source_commit, 'sourceKeyFingerprint': args.expected_fingerprint,
                      'packs': len(payload['packs']), 'publishedAt': payload['publishedAt'],
                      'documents': {name: digest(raw) for name, raw in documents.items()},
                      'lockSha256': lock_sha, 'profileSha256': profile_sha}
            checkpoint(result)
        else:
            require(args.receipt is not None, 'Deployment requires an external --receipt for partial-publication evidence')
            result = deploy(documents, args.expected_fingerprint, args.source_commit, lock,
                            lock_sha, profile_sha, GitHub(os.environ.get('GITHUB_TOKEN', '')), checkpoint=checkpoint)
        print(json.dumps(result, sort_keys=True))
    except (OSError, ValueError, KeyError, TypeError) as exc:
        parser.exit(1, 'Official catalogue deployment failed: ' + str(exc) + '\n')
    finally:
        if stream:
            stream.close()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
