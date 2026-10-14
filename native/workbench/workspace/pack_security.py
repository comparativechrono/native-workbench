"""Dependency-free verification of explicitly trusted pack catalogue signatures.

The signature format is RSASSA-PKCS1-v1_5 with SHA-256 (RFC 8017). This module
only verifies. Signing keys belong in the publisher's release environment.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
from urllib.parse import urlsplit


class PackError(ValueError):
    pass


def require(condition, message):
    if not condition:
        raise PackError(message)


def strict_json(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, 'Duplicate JSON field: ' + key)
            result[key] = value
        return result
    def bad(value):
        raise PackError('Non-finite JSON value is not allowed')
    try:
        return json.loads(raw, object_pairs_hook=pairs, parse_constant=bad)
    except (UnicodeError, json.JSONDecodeError, RecursionError) as exc:
        raise PackError('Malformed JSON document') from exc


def public_key(value):
    require(isinstance(value, dict) and set(value) == {'n', 'e'}, 'Expected RSA public modulus n and exponent e')
    n = value['n']
    require(isinstance(n, str) and re.fullmatch(r'[1-9a-f][0-9a-f]{511,1023}', n), 'RSA modulus must be 2048 to 4096 bits in lowercase hexadecimal')
    number = int(n, 16)
    require(2048 <= number.bit_length() <= 4096 and number % 2 == 1, 'Invalid RSA public modulus')
    require(type(value['e']) is int and value['e'] == 65537, 'RSA exponent must be 65537')
    return number, value['e']


def key_fingerprint(value):
    public_key(value)
    data = json.dumps(value, sort_keys=True, separators=(',', ':')).encode('ascii')
    return hashlib.sha256(data).hexdigest()


def verify_signature(payload, signature, key):
    n, e = public_key(key)
    width = (n.bit_length() + 7) // 8
    require(isinstance(signature, bytes) and len(signature) == width, 'Invalid catalogue signature size')
    integer = int.from_bytes(signature, 'big')
    require(integer < n, 'Invalid catalogue signature')
    actual = pow(integer, e, n).to_bytes(width, 'big')
    digest_info = bytes.fromhex('3031300d060960864801650304020105000420') + hashlib.sha256(payload).digest()
    expected = b'\x00\x01' + b'\xff' * (width - len(digest_info) - 3) + b'\x00' + digest_info
    require(hmac.compare_digest(actual, expected), 'Catalogue signature verification failed')


def signed_payload(raw, key, limit=4 * 1024 * 1024):
    require(len(raw) <= limit, 'Signed catalogue exceeds the size limit')
    document = strict_json(raw)
    require(isinstance(document, dict) and set(document) == {'schema', 'payload', 'signature'}, 'Invalid signed catalogue wrapper')
    require(type(document['schema']) is int and document['schema'] == 1, 'Unsupported signed catalogue format')
    require(isinstance(document['payload'], str) and isinstance(document['signature'], str), 'Invalid catalogue encoding')
    try:
        payload = base64.b64decode(document['payload'], validate=True)
        signature = base64.b64decode(document['signature'], validate=True)
    except (ValueError, TypeError) as exc:
        raise PackError('Invalid catalogue base64 encoding') from exc
    verify_signature(payload, signature, key)
    return strict_json(payload)


def https_url(value, allowed_hosts, *, redirect=False):
    require(isinstance(value, str) and 0 < len(value) <= 4096 and all(ord(c) > 32 and ord(c) < 127 for c in value), 'Expected an HTTPS download URL')
    require('\\' not in value, 'Backslashes are not allowed in download URLs')
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError as exc:
        raise PackError('Invalid download URL') from exc
    require(parsed.scheme == 'https' and parsed.hostname and parsed.hostname.lower() in allowed_hosts, 'Download host is not approved by this source')
    require(not parsed.username and not parsed.password and port in (None, 443), 'URL credentials and nonstandard ports are not allowed')
    require((redirect or not parsed.query) and not parsed.fragment, 'Source and download URLs must not contain queries or fragments')
    return value
