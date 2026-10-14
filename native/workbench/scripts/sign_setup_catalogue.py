#!/usr/bin/env python3
"""Sign the official setup catalogue using an already provisioned CI secret.

No key generation or upload occurs. The private key environment variable is
removed before any child process starts. Only verified public documents leave
the temporary staging directory. Run --fingerprint --private-key PATH on the
maintainer's existing external key to obtain the independent public fingerprint.
"""
from __future__ import annotations

import argparse
from contextlib import redirect_stderr, redirect_stdout
import hmac
import io
import json
import os
from pathlib import Path
import re
import stat
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'scripts'), str(ROOT / 'workspace')]
import publish_pack_catalog as publisher
from pack_manager import validate_catalog, validate_source
from pack_security import key_fingerprint, public_key, strict_json

SECRET_VARIABLE = 'WORKBENCH_CATALOGUE_RSA_PRIVATE_KEY'
FINGERPRINT_VARIABLE = 'WORKBENCH_CATALOGUE_KEY_FINGERPRINT'
MAX_KEY_BYTES = 32 * 1024
SOURCE_ID = 'native-workbench-official'
SOURCE_NAME = 'Native Workbench official tools'
CATALOGUE_URL = 'https://raw.githubusercontent.com/comparativechrono/workbench/catalogue/catalogue.json'
PUBLIC_FILES = {'catalogue.json', 'source.json', 'publication-report.json'}


class SigningError(ValueError):
    """A deliberately constant diagnostic that cannot contain key material."""


def require(condition, message):
    if not condition:
        raise SigningError(message)


def external_key_path(path):
    path = Path(path)
    require(not path.is_symlink(), 'The private key must be a regular external file.')
    resolved = path.resolve(strict=True)
    info = resolved.stat()
    require(not resolved.is_relative_to(ROOT) and stat.S_ISREG(info.st_mode)
            and 0 < info.st_size <= MAX_KEY_BYTES,
            'The private key must be a bounded regular file outside the checkout.')
    return resolved


def public_fingerprint(path):
    """Read only public OpenSSL output; never request a private key text dump."""
    path = external_key_path(path)
    modulus = publisher._openssl(['rsa', '-in', str(path), '-passin', 'pass:',
                                 '-modulus', '-noout']).decode('ascii').strip()
    require(re.fullmatch(r'Modulus=[0-9A-Fa-f]+', modulus), 'Cannot read the RSA public modulus.')
    public_pem = publisher._openssl(['rsa', '-in', str(path), '-passin', 'pass:', '-pubout'])
    description = publisher._openssl(['rsa', '-pubin', '-text', '-noout'], public_pem).decode('ascii')
    exponent = re.search(r'^Exponent: ([0-9]+) \(0x[0-9a-fA-F]+\)$', description, re.MULTILINE)
    require(exponent is not None and exponent.group(1) == '65537', 'The RSA exponent must be 65537.')
    key = {'n': modulus.split('=', 1)[1].lower(), 'e': 65537}
    public_key(key)
    return key_fingerprint(key)


def sign(release_map, output, key_directory, secret, expected):
    require(isinstance(expected, str) and re.fullmatch(r'[0-9a-f]{64}', expected),
            'Configure the independently reviewed lowercase public-key fingerprint.')
    require(os.name == 'posix', 'CI signing requires a POSIX runner with private file permissions.')
    require(isinstance(secret, str) and 0 < len(secret) <= MAX_KEY_BYTES,
            'Configure the bounded private-key secret in the protected release environment.')
    pem = secret.encode('ascii')
    require(len(pem) <= MAX_KEY_BYTES and b'\0' not in pem and
            (pem.startswith(b'-----BEGIN PRIVATE KEY-----') or
             pem.startswith(b'-----BEGIN RSA PRIVATE KEY-----')),
            'The private-key secret must contain an unencrypted RSA PEM.')
    output = Path(output)
    require(not output.is_symlink() and not output.exists(), 'Use a new public output directory.')
    output = output.resolve()
    key_directory = Path(key_directory)
    require(not key_directory.is_symlink(), 'Use an external regular key directory.')
    key_directory = key_directory.resolve(strict=True)
    require(key_directory.is_dir() and not key_directory.is_relative_to(ROOT)
            and not key_directory.is_relative_to(output) and not output.is_relative_to(key_directory),
            'Keep the key directory outside the checkout and public output directory.')
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.workbench-public-', dir=output.parent) as staging:
        public_output = Path(staging) / 'signed'
        with tempfile.TemporaryDirectory(prefix='workbench-signing-', dir=key_directory) as private:
            private = Path(private)
            os.chmod(private, 0o700)
            key_path = private / 'catalogue-key.pem'
            flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_NOFOLLOW', 0)
            descriptor = os.open(key_path, flags, 0o600)
            with os.fdopen(descriptor, 'wb') as stream:
                stream.write(pem)
                stream.flush()
                os.fsync(stream.fileno())
            require(stat.S_IMODE(private.stat().st_mode) == 0o700 and
                    stat.S_IMODE(key_path.stat().st_mode) == 0o600 and key_path.is_file(),
                    'Private key permissions could not be established.')
            actual = public_fingerprint(key_path)
            require(hmac.compare_digest(actual, expected), 'The private key does not match the reviewed public fingerprint.')
            # The established publisher rechecks the complete archives and signs
            # and self-verifies the catalogue. Do not forward any diagnostics.
            with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                try:
                    result = publisher.main([
                        '--release-map', str(release_map), '--output', str(public_output),
                        '--private-key', str(key_path), '--source-id', SOURCE_ID,
                        '--source-name', SOURCE_NAME, '--catalog-url', CATALOGUE_URL,
                    ])
                except SystemExit:
                    raise SigningError('The established publisher rejected the release inputs or signing operation.') from None
            require(result == 0 and {p.name for p in public_output.iterdir()} == PUBLIC_FILES,
                    'The publisher did not produce exactly the required public documents.')
            source = validate_source(strict_json((public_output / 'source.json').read_bytes()))
            payload = validate_catalog((public_output / 'catalogue.json').read_bytes(), source)
            report = strict_json((public_output / 'publication-report.json').read_bytes())
            require(source['id'] == SOURCE_ID and source['name'] == SOURCE_NAME
                    and source['catalogUrl'] == CATALOGUE_URL
                    and hmac.compare_digest(key_fingerprint(source['publicKey']), expected)
                    and report['sourceKeyFingerprint'] == expected
                    and report['packs'] == len(payload['packs']),
                    'The generated public documents did not pass independent verification.')
        # The key has been deleted before the public documents become visible.
        require(not output.exists() and not output.is_symlink(), 'The public output directory already exists.')
        public_output.rename(output)
    return {'output': str(output), 'files': sorted(PUBLIC_FILES),
            'packs': len(payload['packs']), 'sourceKeyFingerprint': expected,
            'signed': True, 'uploaded': False}


def main(argv=None):
    # Also remove the secret for --help, invalid arguments and fingerprint-only
    # mode. No OpenSSL child can inherit it from this process's environment.
    secret = os.environ.pop(SECRET_VARIABLE, None)
    expected = os.environ.get(FINGERPRINT_VARIABLE)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--release-map', type=Path)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--key-directory', type=Path, help='Existing external RUNNER_TEMP subdirectory')
    parser.add_argument('--fingerprint', action='store_true', help='Print only an existing external key public fingerprint')
    parser.add_argument('--private-key', type=Path, help='External existing key; only allowed with --fingerprint')
    args = parser.parse_args(argv)
    try:
        if args.fingerprint:
            require(args.private_key is not None and all(value is None for value in
                    (args.release_map, args.output, args.key_directory)),
                    'Fingerprint mode requires only --fingerprint --private-key PATH.')
            print(public_fingerprint(args.private_key))
        else:
            require(args.private_key is None and all(value is not None for value in
                    (args.release_map, args.output, args.key_directory)),
                    'Signing requires --release-map, --output and --key-directory.')
            print(json.dumps(sign(args.release_map, args.output, args.key_directory, secret, expected)))
    except SigningError as exc:
        print('Catalogue signing failed: ' + str(exc), file=sys.stderr)
        return 1
    except Exception:
        # OpenSSL, malformed JSON, OS and publisher diagnostics can contain
        # untrusted bytes or sensitive paths. Never include them or a traceback.
        print('Catalogue signing failed; check the protected key configuration, release inputs and OpenSSL.', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
