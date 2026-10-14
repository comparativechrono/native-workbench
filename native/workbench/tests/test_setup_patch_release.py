"""Exact setup-update packaging guards; synthetic payloads, no native execution."""
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import build_update_0101 as build
from apply_core_update import NATIVE_NOTICE_FILES


def put(root, name, data):
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def starter(root, archive, version, pack=b'unchanged scientific pack',
            trust=b'published public trust', profile=b'published exact selection'):
    files = {'NativeWorkbench.exe': b'ui-' + version.encode(), 'WorkbenchBridge.exe': b'bridge',
             'workspace/desktop_host.py': b'host', 'LICENSE': b'application license',
             'runtime/python/python.exe': b'private interpreter',
             **{'runtime/licenses/native/' + name: b'notice' for name in NATIVE_NOTICE_FILES}}
    files.update({'workspace/setup_manager.py': b'setup manager-' + version.encode(),
                  'workspace/catalog-sources.json': trust,
                  'workspace/setup-profile.json': profile})
    for name, data in files.items():
        put(root, name, data)
    put(root, 'packs/example-1.0.0/pack.ini', pack)
    manifest = {'schema_version': 2, 'version': version, 'ownership': 'core',
                'pack_management': 'independent', 'interface': 'native-win32',
                'requires_browser': False, 'transport': 'anonymous-pipes', 'manifest_includes_itself': False,
                'files': [{'path': name, 'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}
                          for name, data in files.items()]}
    put(root, 'manifest.json', json.dumps(manifest).encode())
    with zipfile.ZipFile(archive, 'x') as zipped:
        for path in sorted(root.rglob('*')):
            if path.is_file():
                zipped.write(path, 'native-workbench/' + path.relative_to(root).as_posix())


class SetupPatchRelease(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.base = self.root / 'baseline.zip'
        self.target = self.root / 'target.zip'
        starter(self.root / 'baseline', self.base, '0.10.0')
        starter(self.root / 'target', self.target, '0.10.1')
        self.launcher = self.root / 'UpdateWorkbench.exe'
        self.launcher.write_bytes(b'native updater fixture')

    def tearDown(self):
        self.temp.cleanup()

    def run_build(self):
        with mock.patch.object(build, 'BASELINE_SHA', build.sha256(self.base)), \
             mock.patch.object(build, 'BASELINE_BYTES', self.base.stat().st_size):
            return build.build(self.target, build.sha256(self.target), self.base, self.launcher,
                               build.sha256(self.launcher), 'a' * 40, self.root / 'output', self.root / 'work')

    def test_update_payload_matches_target_without_rebuilding_or_touching_packs(self):
        before = self.target.read_bytes()
        report = self.run_build()
        self.assertEqual((report['baseVersion'], report['targetVersion']), ('0.10.0', '0.10.1'))
        self.assertFalse(report['applicationRebuilt'])
        self.assertFalse(report['nativeWindowsExecutedByBuilder'])
        self.assertEqual(report['unchangedPackFiles'], 1)
        self.assertEqual(self.target.read_bytes(), before)
        self.assertEqual(build.sha256(self.root / 'output' / build.UPDATE_NAME), report['updateSha256'])
        recipe = json.loads((self.root / 'work/new-updater/update/update-manifest.json').read_text())
        self.assertFalse(any(row['path'].startswith(('packs/', 'user-data/')) for row in recipe['operations']))
        self.assertIn('workspace/setup_manager.py', {row['path'] for row in recipe['operations']})
        self.assertTrue(report['productionTrustUnchanged'])
        self.assertTrue(report['setupSelectionUnchanged'])
        self.assertFalse({'workspace/catalog-sources.json', 'workspace/setup-profile.json'} &
                         {row['path'] for row in recipe['operations']})

    def test_published_baseline_hash_is_mandatory_before_extraction(self):
        with self.assertRaisesRegex(ValueError, 'Frozen input differs'):
            build.build(self.target, build.sha256(self.target), self.base, self.launcher,
                        build.sha256(self.launcher), 'a' * 40, self.root / 'output', self.root / 'work')
        self.assertFalse((self.root / 'work').exists())

    def test_changed_starter_pack_rejected(self):
        changed = self.root / 'changed.zip'
        starter(self.root / 'changed', changed, '0.10.1', b'changed scientific pack')
        self.target = changed
        with self.assertRaisesRegex(ValueError, 'Starter pack bytes changed'):
            self.run_build()
        self.assertFalse((self.root / 'output').exists())


    def test_patch_rejects_changed_production_trust_before_output(self):
        changed = self.root / 'changed-trust.zip'
        starter(self.root / 'changed-trust', changed, '0.10.1', trust=b'replacement public trust')
        self.target = changed
        with self.assertRaisesRegex(ValueError, 'preserve the published production trust'):
            self.run_build()
        self.assertFalse((self.root / 'output').exists())

    def test_patch_rejects_changed_pack_selection_before_output(self):
        changed = self.root / 'changed-profile.zip'
        starter(self.root / 'changed-profile', changed, '0.10.1', profile=b'different pack pins')
        self.target = changed
        with self.assertRaisesRegex(ValueError, 'preserve the published production trust'):
            self.run_build()
        self.assertFalse((self.root / 'output').exists())

    def test_wrong_target_version_is_rejected(self):
        changed = self.root / 'wrong-version.zip'
        starter(self.root / 'wrong-version', changed, '0.11.0')
        self.target = changed
        with self.assertRaisesRegex(ValueError, 'Unexpected app version'):
            self.run_build()
        self.assertFalse((self.root / 'output').exists())

    def test_inexact_candidate_input_hash_rejected_before_extraction(self):
        with mock.patch.object(build, 'BASELINE_SHA', build.sha256(self.base)), \
             mock.patch.object(build, 'BASELINE_BYTES', self.base.stat().st_size):
            with self.assertRaisesRegex(ValueError, 'Frozen input differs'):
                build.build(self.target, '0' * 64, self.base, self.launcher,
                            build.sha256(self.launcher), 'a' * 40, self.root / 'output', self.root / 'work')
        self.assertFalse((self.root / 'work').exists())


if __name__ == '__main__':
    unittest.main()
