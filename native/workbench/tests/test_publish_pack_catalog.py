"""Release signing interoperability and refusal to publish damaged archives."""
import base64
import copy
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'scripts'), str(ROOT / 'workspace')]
from publish_pack_catalog import canonical, main, make_payload, release_inputs, sign_payload
from validate_pack_release import inspect_release
from pack_manager import validate_catalog, validate_source, extract_archive


def pack_zip(folder, version='1.0.0', mutation=None):
    binary = b'not an executable: static fixture only\n'
    manifest = ('''[pack]
format=2
id=release-test
version=VERSION
name=Release test fixture
platform=windows-x86_64
description=Only tests metadata integrity.
[tool:example]
path=bin/example.exe
version=2.0
sha256=SHA
[workflow:version]
name=Version
description=Test fixture
inputs=
outputs=version
steps=run
[output:version:version]
label=Version output
path=version.txt
[step:version:run]
label=Version
tool=example
stdout=version
arg.0=--version
'''.replace('VERSION', version).replace('SHA', hashlib.sha256(binary).hexdigest())).encode()
    files = {'pack.ini': manifest, 'bin/example.exe': binary, 'licenses/NOTICE.txt': b'Public-domain test fixture\n'}
    envelope = {'schema': 1, 'id': 'release-test', 'version': version, 'packApi': 1, 'minAppVersion': '0.6.0',
                'platform': 'windows-x86_64', 'manifestSha256': hashlib.sha256(manifest).hexdigest(),
                'files': [{'path': name, 'size': len(data), 'sha256': hashlib.sha256(data).hexdigest()} for name, data in files.items()]}
    if mutation:
        mutation(files, envelope)
    path = folder / ('release-test-' + version + '.zip')
    with zipfile.ZipFile(path, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('workbench-pack.json', canonical(envelope))
        for name, data in files.items():
            archive.writestr('pack/' + name, data)
    return path


class ArchiveTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def test_static_audit_and_application_extraction_agree(self):
        path = pack_zip(self.root)
        row = inspect_release(path)
        row['downloadURL'] = 'https://example.org/test.zip'
        pack, envelope, parsed = extract_archive(path, self.root / 'expanded', expected=row)
        self.assertEqual(row['manifestSha256'], parsed['manifestSha256'])
        self.assertEqual(row['toolVersions'], {'example': '2.0'})
        self.assertEqual(row['version'], envelope['version'])

    def test_payload_keeps_independent_versions_and_release_urls(self):
        first, second = pack_zip(self.root), pack_zip(self.root, '1.1.0')
        mapping = self.root / 'releases.json'
        mapping.write_text(json.dumps({'schema': 1, 'releases': [
            {'archive': first.name, 'downloadURL': 'https://github.com/team/packs/releases/download/release-test-1.0.0/a.zip'},
            {'archive': second.name, 'downloadURL': 'https://github.com/team/packs/releases/download/release-test-1.1.0/b.zip'}]}))
        payload = make_payload(release_inputs([], mapping), {'github.com'}, '2026-10-03T12:00:00Z')
        self.assertEqual([row['version'] for row in payload['packs']], ['1.0.0', '1.1.0'])
        self.assertNotEqual(payload['packs'][0]['downloadURL'], payload['packs'][1]['downloadURL'])

    def test_tampered_member_fails_before_publication(self):
        path = pack_zip(self.root, mutation=lambda files, envelope: files.update({'bin/example.exe': b'tampered'}))
        with self.assertRaisesRegex(ValueError, 'size differs|hash differs'):
            inspect_release(path)

    def test_inventory_cannot_hide_an_extra_file(self):
        path = pack_zip(self.root, mutation=lambda files, envelope: files.update({'hidden.exe': b'surprise'}))
        with self.assertRaisesRegex(ValueError, 'inventory differ'):
            inspect_release(path)

    def test_unsafe_path_and_case_collision_are_rejected(self):
        for extra in ('../escape', 'BIN/EXAMPLE.EXE'):
            path = pack_zip(self.root, mutation=lambda files, envelope: files.update({extra: b'bad'}))
            with self.subTest(extra=extra), self.assertRaises(ValueError):
                inspect_release(path)

    def test_duplicate_id_version_and_insecure_url_are_rejected(self):
        path = pack_zip(self.root)
        for entries in ([(path, 'http://example.org/a.zip')], [(path, 'https://example.org/a.zip'), (path, 'https://example.org/b.zip')]):
            with self.subTest(entries=entries), self.assertRaises(ValueError):
                make_payload(entries, {'example.org'})

    def test_unsigned_preview_is_separate_and_never_emits_trust_source(self):
        path = pack_zip(self.root)
        output = self.root / 'preview'
        self.assertEqual(main([str(path), '--base-url', 'https://example.org/packs', '--unsigned-preview', '--output', str(output)]), 0)
        self.assertEqual([item.name for item in output.iterdir()], ['catalogue-preview.UNSIGNED.json'])

    def test_example_template_builds_with_shared_archive_builder(self):
        from package_split import build_pack
        binary = self.root / 'seqtk.exe'
        binary.write_bytes(b'static template test only; no executable code')
        licence, provenance = self.root / 'LICENSE', self.root / 'provenance.json'
        licence.write_text('Test fixture only')
        provenance.write_text('{"testFixture": true}')
        prepared = self.root / 'example-seqtk-1.0.0'
        subprocess.run([sys.executable, str(ROOT / 'pack-examples/independent-pack/prepare.py'),
                        '--tool-exe', str(binary), '--tool-version', '1.4-r122', '--license', str(licence),
                        '--provenance', str(provenance), '--output', str(prepared)], check=True, stdout=subprocess.PIPE)
        archive = self.root / 'example-seqtk-1.0.0.zip'
        built = build_pack(prepared, archive)
        validated = inspect_release(archive)
        self.assertEqual(built['sha256'], validated['sha256'])
        self.assertEqual(validated['category'], 'Sequence utilities')
        self.assertEqual(validated['version'], '1.0.0')


@unittest.skipUnless(shutil.which('openssl'), 'OpenSSL required for real temporary RSA signing tests')
class SigningTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix='workbench-signing-test-', dir=ROOT.parents[1])
        cls.root = Path(cls.temp.name)
        cls.key = cls.root / 'test-key.pem'
        subprocess.run(['openssl', 'genpkey', '-algorithm', 'RSA', '-pkeyopt', 'rsa_keygen_bits:2048', '-out', str(cls.key)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
        cls.archive = pack_zip(cls.root)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def payload(self):
        return make_payload([(self.archive, 'https://example.org/test.zip')], {'example.org'}, '2026-10-03T12:00:00Z')

    def source(self, key):
        return validate_source({'schema': 1, 'id': 'test-source', 'name': 'Test only', 'catalogUrl': 'https://example.org/catalogue.json', 'publicKey': key, 'allowedHosts': ['example.org']})

    def test_real_signature_is_verified_by_application(self):
        payload = self.payload()
        wrapper, key = sign_payload(payload, self.key)
        self.assertEqual(validate_catalog(canonical(wrapper), self.source(key)), payload)

    def test_payload_or_signature_tampering_fails(self):
        wrapper, key = sign_payload(self.payload(), self.key)
        for field in ('payload', 'signature'):
            damaged = copy.deepcopy(wrapper)
            raw = bytearray(base64.b64decode(damaged[field]))
            raw[len(raw) // 2] ^= 1
            damaged[field] = base64.b64encode(raw).decode('ascii')
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, 'signature'):
                validate_catalog(canonical(damaged), self.source(key))

    def test_full_cli_emits_public_material_and_refuses_overwrite(self):
        output = self.root / 'signed'
        args = [str(self.archive), '--github', 'test-team', 'pack-releases', 'release-test-1.0.0', '--catalog-url', 'https://example.org/catalogue.json', '--private-key', str(self.key), '--output', str(output)]
        self.assertEqual(main(args), 0)
        source = json.loads((output / 'source.json').read_text())
        self.assertIn('release-assets.githubusercontent.com', source['allowedHosts'])
        payload = validate_catalog((output / 'catalogue.json').read_bytes(), validate_source(source))
        self.assertEqual(len(payload['packs']), 1)
        self.assertNotIn(b'PRIVATE KEY', b''.join(item.read_bytes() for item in output.iterdir()))
        original = (output / 'catalogue.json').read_bytes()
        with self.assertRaises(SystemExit):
            main(args)
        self.assertEqual((output / 'catalogue.json').read_bytes(), original)


if __name__ == '__main__':
    unittest.main()
