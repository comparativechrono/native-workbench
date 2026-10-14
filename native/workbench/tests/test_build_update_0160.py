"""Source contracts for the app-only update with a separately owned new pack.

These synthetic installations prove ownership and rejection behavior, not native
execution. Exact real archives and Windows behavior have their separate gates.
"""
import copy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import apply_core_update
import build_update_0160 as release
import make_core_update


def put(root, name, data):
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return {'path': name, 'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}


class IndependentPackUpdate(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.parent = Path(self.temp.name)
        self.base, self.target = self.parent / 'base', self.parent / 'target'
        pins = [{'id': 'align', 'version': '0.4.0', 'folder': 'packs/align-0.4.0',
                 'manifestSha256': hashlib.sha256(b'old pack').hexdigest()}]
        self.manifests = []
        for root, version, ui in ((self.base, '0.11.0', b'old-ui'), (self.target, '0.16.0', b'new-ui')):
            files = [put(root, name, data) for name, data in (
                ('NativeWorkbench.exe', ui), ('WorkbenchBridge.exe', b'bridge'),
                ('workspace/desktop_host.py', b'host'))]
            put(root, 'packs/align-0.4.0/pack.ini', b'old pack')
            self.manifests.append({'schema_version': 2, 'version': version, 'interface': 'native-win32',
                'requires_browser': False, 'transport': 'anonymous-pipes', 'manifest_includes_itself': False,
                'ownership': 'core', 'pack_management': 'independent', 'starter_packs': copy.deepcopy(pins),
                'files': files})
        self.old, self.new = self.manifests
        extra = put(self.target, 'packs/align-0.4.1/pack.ini', b'independent new pack')
        self.new['additional_packs'] = [{'id': 'align', 'version': '0.4.1', 'folder': 'packs/align-0.4.1',
            'manifestSha256': extra['sha256'],
            'files': [{'path': 'pack.ini', 'sha256': extra['sha256'], 'size': extra['bytes']}]}]
        self.pin = patch.object(release, 'ALIGN_MANIFEST_SHA', extra['sha256'])
        self.pin.start()

    def tearDown(self):
        self.pin.stop()
        self.temp.cleanup()

    def scope(self):
        return release.verify_pack_scope(self.base, self.target, self.old, self.new)

    def test_target_additional_pack_is_explicitly_excluded_from_update(self):
        preserved, excluded = self.scope()
        self.assertEqual(set(preserved), {'packs/align-0.4.0/pack.ini'})
        self.assertEqual(set(excluded), {'packs/align-0.4.1/pack.ini'})
        for root, value in ((self.base, self.old), (self.target, self.new)):
            put(root, 'manifest.json', json.dumps(value).encode())
        personal = put(self.base, 'user-data/saved.json', b'personal exact pins')
        put(self.base, 'packs/reads-0.4.0/pack.ini', b'previous optional pack')
        before = release.pack_hashes(self.base)
        output = self.parent / 'updater'
        make_core_update.make(self.base, self.target, output)
        result = apply_core_update.apply(self.base, output / 'update')
        self.assertEqual(result['status'], 'installed')
        self.assertEqual(release.pack_hashes(self.base), before)
        self.assertFalse((self.base / 'packs/align-0.4.1').exists())
        self.assertEqual(release.sha256(self.base / personal['path']), personal['sha256'])
        self.assertEqual((self.base / 'manifest.json').read_bytes(), (self.target / 'manifest.json').read_bytes())
        self.assertEqual(apply_core_update.apply(self.base, output / 'update')['status'], 'already-installed')

    def test_changed_published_pack_is_rejected(self):
        put(self.target, 'packs/align-0.4.0/pack.ini', b'changed published pack')
        with self.assertRaisesRegex(ValueError, 'Published Starter pack bytes changed'):
            self.scope()

    def test_removed_published_pack_is_rejected(self):
        (self.target / 'packs/align-0.4.0/pack.ini').unlink()
        with self.assertRaisesRegex(ValueError, 'Published Starter pack bytes changed'):
            self.scope()

    def test_extra_uninventoried_pack_file_is_rejected(self):
        put(self.target, 'packs/align-0.4.1/unrecorded.exe', b'extra executable')
        with self.assertRaisesRegex(ValueError, 'Additional pack bytes differ'):
            self.scope()

    def test_modified_additional_pack_is_rejected(self):
        put(self.target, 'packs/align-0.4.1/pack.ini', b'changed optional bytes')
        with self.assertRaisesRegex(ValueError, 'Additional pack bytes differ'):
            self.scope()

    def test_core_cannot_claim_an_independent_pack(self):
        self.new['files'].append({'path': 'packs/align-0.4.1/pack.ini'})
        with self.assertRaisesRegex(ValueError, 'cannot be a core update destination'):
            self.scope()

    def test_published_starter_pin_change_is_rejected(self):
        self.new['starter_packs'][0]['version'] = '0.4.1'
        with self.assertRaisesRegex(ValueError, 'Published Starter pins changed'):
            self.scope()


if __name__ == '__main__':
    unittest.main(verbosity=2)
