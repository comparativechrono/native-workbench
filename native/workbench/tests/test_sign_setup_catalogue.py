"""Protected signing adapter: public fixture only, real OpenSSL and archives."""
import ast
import base64
from contextlib import redirect_stderr, redirect_stdout
import io
import json
import math
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'scripts'), str(ROOT / 'workspace'), str(ROOT / 'tests')]
import sign_setup_catalogue as signer
from pack_manager import validate_catalog, validate_source
from pack_security import key_fingerprint
from test_publish_pack_catalog import pack_zip


def public_test_pem():
    """Serialize the existing, deliberately public N/D fixture, not a new key."""
    values = {}
    for node in ast.parse((ROOT / 'tests/test_pack_manager.py').read_text()).body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            name = getattr(node.targets[0], 'id', '')
            if name in ('N', 'D'):
                values[name] = int(ast.literal_eval(node.value), 16)
    n, d, e = values['N'], values['D'], 65537
    # Recover this known test key's CRT factors from its public test exponent.
    odd, powers = e * d - 1, 0
    while odd % 2 == 0:
        odd //= 2
        powers += 1
    p = None
    for base in range(2, 100):
        value = pow(base, odd, n)
        for _ in range(powers):
            squared = value * value % n
            if squared == 1 and value not in (1, n - 1):
                p = math.gcd(value - 1, n)
                break
            value = squared
        if p is not None:
            break
    if p is None or n % p:
        raise AssertionError('The public test fixture could not be serialized.')
    q = n // p

    def der(tag, content):
        count = len(content)
        length = bytes([count]) if count < 128 else count.to_bytes((count.bit_length() + 7) // 8, 'big')
        if count >= 128:
            length = bytes([0x80 | len(length)]) + length
        return bytes([tag]) + length + content

    def integer(value):
        encoded = value.to_bytes(max(1, (value.bit_length() + 7) // 8), 'big')
        if encoded[0] & 0x80:
            encoded = b'\0' + encoded
        return der(2, encoded)

    encoded = base64.b64encode(der(0x30, b''.join(integer(value) for value in
        (0, n, e, d, p, q, d % (p - 1), d % (q - 1), pow(q, -1, p))))).decode('ascii')
    pem = '-----BEGIN RSA PRIVATE KEY-----\n' + '\n'.join(encoded[i:i+64] for i in range(0, len(encoded), 64)) + '\n-----END RSA PRIVATE KEY-----\n'
    return pem, key_fingerprint({'n': format(n, 'x'), 'e': e})


@unittest.skipUnless(shutil.which('openssl') and os.name == 'posix', 'POSIX and OpenSSL required for protected CI signing')
class SigningAdapterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pem, cls.fingerprint = public_test_pem()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='workbench-ci-sign-test-', dir=ROOT.parent)
        self.root = Path(self.temp.name)
        self.key_directory = self.root / 'runner-private'
        self.key_directory.mkdir(mode=0o700)
        self.output = self.root / 'public'
        archive = pack_zip(self.root)
        self.release_map = self.root / 'release-map.json'
        self.release_map.write_text(json.dumps({'schema': 1, 'releases': [{
            'archive': str(archive),
            'downloadURL': 'https://github.com/comparativechrono/workbench/releases/download/test-fixture/test.zip',
        }]}))
        self.args = ['--release-map', str(self.release_map), '--output', str(self.output),
                     '--key-directory', str(self.key_directory)]

    def tearDown(self):
        self.temp.cleanup()

    def invoke(self, args=None, secret=None, fingerprint=None):
        out, err = io.StringIO(), io.StringIO()
        environment = {signer.SECRET_VARIABLE: self.pem if secret is None else secret,
                       signer.FINGERPRINT_VARIABLE: self.fingerprint if fingerprint is None else fingerprint}
        with patch.dict(os.environ, environment), redirect_stdout(out), redirect_stderr(err):
            result = signer.main(self.args if args is None else args)
            self.assertNotIn(signer.SECRET_VARIABLE, os.environ)
        text = out.getvalue() + err.getvalue()
        self.assertNotIn(self.pem, text)
        self.assertNotIn(self.pem.splitlines()[1], text)
        self.assertEqual(list(self.key_directory.iterdir()), [])
        self.assertFalse(any(self.root.glob('.workbench-public-*')))
        return result, out.getvalue(), err.getvalue()

    def test_signs_real_archive_with_private_permissions_and_no_secret_child_environment(self):
        real_run, observations = subprocess.run, []

        def checked_child(*args, **kwargs):
            environment = kwargs.get('env', os.environ)
            self.assertNotIn(signer.SECRET_VARIABLE, environment)
            for path in self.key_directory.rglob('catalogue-key.pem'):
                observations.append(path)
                self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
                self.assertEqual(stat.S_IMODE(path.parent.stat().st_mode), 0o700)
                self.assertFalse(path.is_symlink())
                self.assertFalse(path.is_relative_to(ROOT))
                self.assertFalse(path.is_relative_to(self.output))
            return real_run(*args, **kwargs)

        with patch.object(subprocess, 'run', side_effect=checked_child):
            status, out, err = self.invoke()
        self.assertEqual((status, err), (0, ''))
        self.assertTrue(observations)
        self.assertTrue(all(not path.exists() for path in observations))
        self.assertEqual({p.name for p in self.output.iterdir()}, signer.PUBLIC_FILES)
        source = validate_source(json.loads((self.output / 'source.json').read_text()))
        payload = validate_catalog((self.output / 'catalogue.json').read_bytes(), source)
        self.assertEqual(source['id'], signer.SOURCE_ID)
        self.assertEqual(source['catalogUrl'], signer.CATALOGUE_URL)
        self.assertEqual(key_fingerprint(source['publicKey']), self.fingerprint)
        self.assertEqual([row['id'] for row in payload['packs']], ['release-test'])
        self.assertEqual(json.loads(out)['sourceKeyFingerprint'], self.fingerprint)
        self.assertNotIn(b'PRIVATE KEY', b''.join(path.read_bytes() for path in self.output.iterdir()))

    def test_wrong_fingerprint_fails_before_signing_and_leaves_no_public_output(self):
        with patch.object(signer.publisher, 'sign_payload') as signing:
            status, _, err = self.invoke(fingerprint='0' * 64)
        self.assertEqual(status, 1)
        self.assertIn('does not match', err)
        signing.assert_not_called()
        self.assertFalse(self.output.exists())

    def test_missing_or_malformed_fingerprint_never_materializes_key_or_spawns_child(self):
        for fingerprint in ('', 'A' * 64, '../not-a-fingerprint'):
            with self.subTest(fingerprint=fingerprint), patch.object(subprocess, 'run') as child:
                status, _, _ = self.invoke(fingerprint=fingerprint)
            self.assertEqual(status, 1)
            child.assert_not_called()
            self.assertFalse(self.output.exists())

    def test_missing_malformed_and_oversized_secret_fail_without_children(self):
        for secret in ('', 'not a PEM', self.pem + 'X' * signer.MAX_KEY_BYTES):
            with self.subTest(length=len(secret)), patch.object(subprocess, 'run') as child:
                status, _, _ = self.invoke(secret=secret)
            self.assertEqual(status, 1)
            child.assert_not_called()
            self.assertFalse(self.output.exists())

    def test_absent_environment_prerequisites_fail_closed(self):
        for missing in (signer.SECRET_VARIABLE, signer.FINGERPRINT_VARIABLE):
            environment = dict(os.environ)
            environment.update({signer.SECRET_VARIABLE: self.pem,
                                signer.FINGERPRINT_VARIABLE: self.fingerprint})
            environment.pop(missing)
            out, err = io.StringIO(), io.StringIO()
            with self.subTest(missing=missing), patch.dict(os.environ, environment, clear=True), \
                    patch.object(subprocess, 'run') as child, redirect_stdout(out), redirect_stderr(err):
                self.assertEqual(signer.main(self.args), 1)
                self.assertNotIn(signer.SECRET_VARIABLE, os.environ)
            child.assert_not_called()
            self.assertEqual(out.getvalue(), '')
            self.assertNotIn(self.pem, err.getvalue())
            self.assertFalse(self.output.exists())
            self.assertEqual(list(self.key_directory.iterdir()), [])

    def test_invalid_arguments_also_remove_secret(self):
        with patch.dict(os.environ, {signer.SECRET_VARIABLE: self.pem}), redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                signer.main(['--unknown-option'])
            self.assertNotIn(signer.SECRET_VARIABLE, os.environ)
        self.assertFalse(self.output.exists())

    def test_publisher_failure_cleans_key_and_suppresses_untrusted_diagnostics(self):
        with patch.object(signer.publisher, 'sign_payload', side_effect=ValueError(self.pem)):
            status, out, _ = self.invoke()
        self.assertEqual((status, out), (1, ''))
        self.assertFalse(self.output.exists())

    def test_real_damaged_archive_is_rejected_without_publication(self):
        archive = next(self.root.glob('*.zip'))
        archive.write_bytes(b'not a ZIP')
        status, out, _ = self.invoke()
        self.assertEqual((status, out), (1, ''))
        self.assertFalse(self.output.exists())

    def test_independent_verification_rejects_tampered_staged_signature(self):
        publish = signer.publisher.main

        def tamper(args):
            result = publish(args)
            output = Path(args[args.index('--output') + 1])
            path = output / 'catalogue.json'
            wrapper = json.loads(path.read_text())
            signature = bytearray(base64.b64decode(wrapper['signature']))
            signature[0] ^= 1
            wrapper['signature'] = base64.b64encode(signature).decode()
            path.write_text(json.dumps(wrapper))
            return result

        with patch.object(signer.publisher, 'main', side_effect=tamper):
            status, out, _ = self.invoke()
        self.assertEqual((status, out), (1, ''))
        self.assertFalse(self.output.exists())

    def test_existing_public_output_is_unchanged(self):
        self.output.mkdir()
        sentinel = self.output / 'catalogue.json'
        sentinel.write_bytes(b'published bytes')
        with patch.object(subprocess, 'run') as child:
            status, _, _ = self.invoke()
        self.assertEqual(status, 1)
        child.assert_not_called()
        self.assertEqual(sentinel.read_bytes(), b'published bytes')

    def test_key_directory_cannot_be_checkout_or_output(self):
        for directory in (ROOT, self.output):
            directory.mkdir(exist_ok=True)
            args = self.args.copy()
            args[-1] = str(directory)
            with self.subTest(directory=directory), patch.object(subprocess, 'run') as child:
                status, _, _ = self.invoke(args=args)
            self.assertEqual(status, 1)
            child.assert_not_called()

    def test_public_output_cannot_be_inside_ephemeral_key_directory(self):
        args = self.args.copy()
        args[args.index('--output') + 1] = str(self.key_directory / 'public')
        with patch.object(subprocess, 'run') as child:
            status, out, _ = self.invoke(args=args)
        self.assertEqual((status, out), (1, ''))
        child.assert_not_called()

    def test_fingerprint_mode_prints_only_authoritative_public_fingerprint(self):
        key = self.root / 'public-test-fixture.pem'
        key.write_text(self.pem)
        status, out, err = self.invoke(args=['--fingerprint', '--private-key', str(key)])
        self.assertEqual((status, out, err), (0, self.fingerprint + '\n', ''))
        self.assertFalse(self.output.exists())
        self.assertEqual(key.read_text(), self.pem)

    def test_fingerprint_mode_rejects_symlink_key_and_combined_sign_arguments(self):
        key = self.root / 'public-test-fixture.pem'
        key.write_text(self.pem)
        link = self.root / 'key-link.pem'
        link.symlink_to(key)
        for args in (['--fingerprint', '--private-key', str(link)],
                     ['--fingerprint', '--private-key', str(key), *self.args]):
            with self.subTest(args=args):
                status, out, _ = self.invoke(args=args)
            self.assertEqual((status, out), (1, ''))
        self.assertFalse(self.output.exists())


if __name__ == '__main__':
    unittest.main()
