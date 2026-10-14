#!/usr/bin/env python3
"""Prepare a verified, signed pack catalogue and explicit-trust source file.

No network calls, uploads, key generation, or implicit trust changes occur.
Run --help for input formats. Keep the signing key outside the checkout and
output directory. An unsigned preview is deliberately not importable as a source.
"""
from __future__ import annotations

import argparse
import base64
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import subprocess
import sys
import zipfile
from urllib.parse import quote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'workspace'))
from catalog import ID
from pack_security import require, strict_json, public_key, key_fingerprint, https_url, signed_payload
from pack_manager import validate_source, validate_entry, validate_catalog
from validate_pack_release import inspect_release


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True, allow_nan=False).encode('ascii')


def release_inputs(archives, release_map=None, base_url=None, github=None):
    """Map each archive to its immutable URL, retaining every selected version."""
    if release_map:
        require(not archives and base_url is None and github is None, '--release-map cannot be combined with archive URL shortcuts')
        document = strict_json(Path(release_map).read_bytes())
        require(isinstance(document, dict) and set(document) == {'schema', 'releases'} and type(document['schema']) is int and document['schema'] == 1, 'Invalid release map')
        rows = document['releases']
        require(isinstance(rows, list) and 1 <= len(rows) <= 2000, 'Release map requires 1 to 2000 releases')
        result = []
        for row in rows:
            require(isinstance(row, dict) and set(row) == {'archive', 'downloadURL'} and isinstance(row['archive'], str) and row['archive'], 'Each release needs archive and downloadURL')
            path = Path(row['archive'])
            if not path.is_absolute():
                path = Path(release_map).resolve().parent / path
            result.append((path, row['downloadURL']))
        return result
    require(archives and bool(base_url) != bool(github), 'Supply archives and exactly one of --base-url or --github OWNER REPOSITORY TAG, or use --release-map')
    if github:
        owner, repo, tag = github
        require(re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9-]{0,99}', owner) and re.fullmatch(r'[A-Za-z0-9_.-]{1,100}', repo), 'Invalid GitHub owner or repository')
        require(tag and len(tag) <= 200 and all(ord(c) > 32 for c in tag) and tag not in ('.', '..'), 'Invalid release tag')
        base_url = 'https://github.com/' + owner + '/' + repo + '/releases/download/' + quote(tag, safe='')
    return [(Path(path), str(base_url).rstrip('/') + '/' + quote(Path(path).name, safe='')) for path in archives]


def make_payload(inputs, allowed_hosts, published_at=None):
    rows, identities, urls = [], set(), set()
    require(1 <= len(inputs) <= 2000, 'Expected 1 to 2000 pack releases')
    for path, url in inputs:
        https_url(url, allowed_hosts)
        row = inspect_release(path)
        identity = (row['id'], row['version'])
        require(identity not in identities, 'Duplicate pack ID/version in catalogue')
        require(url not in urls, 'A download URL cannot identify multiple archives')
        identities.add(identity)
        urls.add(url)
        row['downloadURL'] = url
        validate_entry(row, allowed_hosts)
        rows.append(row)
    stamp = published_at or datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace('+00:00', 'Z')
    require(isinstance(stamp, str) and re.fullmatch(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z', stamp), 'publishedAt must be UTC YYYY-MM-DDTHH:MM:SSZ')
    datetime.strptime(stamp, '%Y-%m-%dT%H:%M:%SZ')
    rows.sort(key=lambda row: (row['id'], tuple(map(int, row['version'].split('.')))))
    return {'schema': 1, 'publishedAt': stamp, 'packs': rows}


def _openssl(args, stdin=None):
    result = subprocess.run(['openssl', *args], input=stdin, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    require(result.returncode == 0, 'OpenSSL failed; check the external RSA key and OpenSSL installation')
    return result.stdout


def sign_payload(payload, private_key):
    key_path = Path(private_key).resolve()
    require(key_path.is_file() and not Path(private_key).is_symlink(), 'Expected a regular external RSA private key file')
    # The key itself and OpenSSL diagnostics are never printed or copied.
    modulus = _openssl(['rsa', '-in', str(key_path), '-passin', 'pass:', '-modulus', '-noout']).decode('ascii').strip()
    require(re.fullmatch(r'Modulus=[0-9A-Fa-f]+', modulus), 'Cannot read RSA public modulus')
    key = {'n': modulus.split('=', 1)[1].lower(), 'e': 65537}
    public_key(key)
    encoded = canonical(payload)
    signature = _openssl(['dgst', '-sha256', '-sign', str(key_path), '-passin', 'pass:'], encoded)
    wrapper = {'schema': 1, 'payload': base64.b64encode(encoded).decode('ascii'), 'signature': base64.b64encode(signature).decode('ascii')}
    # Also rejects a private key with an exponent other than 65537.
    require(signed_payload(canonical(wrapper), key) == payload, 'Signed catalogue self-verification failed')
    return wrapper, key


def _write_new(path, document):
    path = Path(path)
    with path.open('xb') as stream:
        stream.write(json.dumps(document, indent=2, ensure_ascii=True, allow_nan=False).encode('ascii') + b'\n')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('archives', nargs='*', type=Path)
    parser.add_argument('--release-map', type=Path, help='JSON {schema:1,releases:[{archive,downloadURL}]} with per-version release URLs')
    parser.add_argument('--base-url', help='HTTPS directory containing the explicitly supplied archives')
    parser.add_argument('--github', nargs=3, metavar=('OWNER', 'REPOSITORY', 'TAG'), help='One release tag for the supplied archives; use --release-map for independent releases')
    parser.add_argument('--allow-host', action='append', default=[], help='Approved exact HTTPS host; repeat for redirect destinations')
    parser.add_argument('--output', type=Path, required=True, help='New output directory; existing output files are never overwritten')
    parser.add_argument('--private-key', type=Path, help='External unencrypted RSA PEM signing key, 2048–4096 bits with exponent 65537')
    parser.add_argument('--source-id', default='workbench-tools')
    parser.add_argument('--source-name', default='Native Workbench tools')
    parser.add_argument('--catalog-url', help='Final HTTPS URL of the signed catalogue')
    parser.add_argument('--published-at', help='Fixed UTC timestamp for repeatable signing')
    parser.add_argument('--unsigned-preview', action='store_true', help='Write catalogue-preview.UNSIGNED.json only; cannot be trusted or imported by the app')
    args = parser.parse_args(argv)
    try:
        require(bool(args.private_key) != args.unsigned_preview, 'Choose --private-key or --unsigned-preview')
        require(ID.fullmatch(args.source_id), 'Invalid source ID')
        require(0 < len(args.source_name) <= 100 and all(ord(c) >= 32 and ord(c) != 127 for c in args.source_name), 'Invalid source name')
        inputs = release_inputs(args.archives, args.release_map, args.base_url, args.github)
        hosts = set(args.allow_host)
        for _, url in inputs:
            require(isinstance(url, str), 'Invalid release downloadURL')
            hostname = urlsplit(url).hostname
            if hostname:
                hosts.add(hostname.lower())
        if args.catalog_url:
            hostname = urlsplit(args.catalog_url).hostname
            if hostname:
                hosts.add(hostname.lower())
        require(all(isinstance(host, str) and re.fullmatch(r'[a-z0-9](?:[a-z0-9.-]{0,251}[a-z0-9])?', host) and '..' not in host for host in hosts), 'Invalid approved hostname')
        # GitHub release asset downloads redirect here. No wildcard hosts.
        if 'github.com' in hosts:
            hosts.add('release-assets.githubusercontent.com')
        payload = make_payload(inputs, hosts, args.published_at)
        if args.unsigned_preview:
            require(args.catalog_url is None, '--catalog-url is only for a signed publication')
            documents = {'catalogue-preview.UNSIGNED.json': payload}
        else:
            require(args.catalog_url, 'Signing requires the intended --catalog-url')
            https_url(args.catalog_url, hosts)
            key_path = args.private_key.resolve()
            require(not key_path.is_relative_to(ROOT) and not key_path.is_relative_to(args.output.resolve()), 'Keep the signing key outside the checkout and output directory')
            wrapper, key = sign_payload(payload, args.private_key)
            source = {'schema': 1, 'id': args.source_id, 'name': args.source_name,
                      'catalogUrl': args.catalog_url, 'publicKey': key, 'allowedHosts': sorted(hosts)}
            validate_source(source)
            require(validate_catalog(canonical(wrapper), source) == payload, 'Application rejected the generated catalogue')
            documents = {'catalogue.json': wrapper, 'source.json': source,
                         'publication-report.json': {'schema': 1, 'packs': len(payload['packs']), 'sourceKeyFingerprint': key_fingerprint(key), 'publishedAt': payload['publishedAt'], 'uploaded': False}}
        require(all(not (args.output / name).exists() for name in documents), 'Output exists; use a new directory to preserve published catalogues')
        args.output.mkdir(parents=True, exist_ok=True)
        for name, document in documents.items():
            _write_new(args.output / name, document)
    except (OSError, ValueError, KeyError, UnicodeError, zipfile.BadZipFile) as exc:
        parser.exit(1, 'Catalogue preparation failed: ' + str(exc) + '\n')
    print(json.dumps({'output': str(args.output.resolve()), 'files': list(documents), 'packs': len(payload['packs']), 'signed': not args.unsigned_preview, 'uploaded': False}))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
