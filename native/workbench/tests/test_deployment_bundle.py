"""Packaging boundary tests; native execution is covered by the Windows gate."""
import hashlib
import importlib.util
import json
from pathlib import Path
import stat
import tempfile
import unittest
from unittest import mock
import subprocess
import warnings
import zipfile

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/build_deployment_bundle.py'
spec = importlib.util.spec_from_file_location('deployment_bundle', SCRIPT)
bundle = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bundle)


class DeploymentBundleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()

    def tearDown(self):
        self.temp.cleanup()

    def archive(self, rows, name='test.zip'):
        path = self.root / name
        with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED) as archive:
            for member, raw in rows:
                with warnings.catch_warnings():
                    warnings.simplefilter('ignore', UserWarning)
                    archive.writestr(member, raw)
        return path

    def reject(self, rows):
        path = self.archive(rows)
        with self.assertRaises(bundle.BundleError):
            bundle.extract_zip(path, self.root / 'output')
        self.assertFalse((self.root / 'output').exists(), 'Names/types must fail before any extraction')

    def test_safe_extraction_preserves_exact_binary_bytes_and_spaces(self):
        raw = bytes(range(256)) * 37
        path = self.archive([('native-workbench/space folder/tool.exe', raw)])
        target = self.root / 'space destination'
        bundle.extract_zip(path, target, strip_prefix='native-workbench/')
        self.assertEqual((target / 'space folder/tool.exe').read_bytes(), raw)
        self.assertEqual(bundle.tree_files(target), [{'path': 'space folder/tool.exe', 'bytes': len(raw),
                                                    'sha256': hashlib.sha256(raw).hexdigest()}])

    def test_rejects_traversal_and_windows_ambiguous_paths(self):
        names = ['../escape', '/absolute', 'C:/outside', 'folder\\outside', 'foo/../bar',
                 './file', 'foo//bar', 'name.', 'name /file', 'file:stream', 'NUL.txt',
                 'aux/file', 'COM1', 'LPT².txt', 'CON .txt', 'tab\tname', 'foo?bar']
        for number, name in enumerate(names):
            with self.subTest(name=name):
                path = self.archive([(name, b'bad')], f'unsafe-{number}.zip')
                with self.assertRaises(bundle.BundleError):
                    bundle.extract_zip(path, self.root / f'out-{number}')
                self.assertFalse((self.root / f'out-{number}').exists())

    def test_rejects_duplicate_members(self):
        self.reject([('file', b'one'), ('file', b'two')])

    def test_rejects_case_collisions(self):
        self.reject([('File', b'one'), ('file', b'two')])

    def test_rejects_implicit_directory_case_collisions(self):
        self.reject([('Directory/file', b'one'), ('directory/other', b'two')])

    def test_rejects_file_directory_collisions(self):
        self.reject([('folder', b'file'), ('folder/child', b'child')])

    def test_rejects_explicit_directory_case_collisions(self):
        self.reject([('Folder/', b''), ('folder/child', b'child')])

    def test_rejects_symlinks_and_special_files(self):
        for number, kind in enumerate((stat.S_IFLNK, stat.S_IFIFO, stat.S_IFCHR, stat.S_IFSOCK)):
            with self.subTest(kind=kind):
                info = zipfile.ZipInfo('bad')
                info.create_system = 3
                info.external_attr = (kind | 0o777) << 16
                path = self.archive([(info, b'elsewhere')], f'special-{number}.zip')
                with self.assertRaises(bundle.BundleError):
                    bundle.extract_zip(path, self.root / f'out-{number}')
                self.assertFalse((self.root / f'out-{number}').exists())

    def test_rejects_reparse_attribute(self):
        info = zipfile.ZipInfo('bad')
        info.external_attr = ((stat.S_IFREG | 0o644) << 16) | 0x400
        self.reject([(info, b'content')])

    def test_rejects_member_count_and_expanded_size_limits(self):
        path = self.archive([('a', b'abc'), ('b', b'def')])
        for limits in ({'max_members': 1}, {'max_member_bytes': 2}, {'max_total_bytes': 5}):
            with self.subTest(limits=limits), self.assertRaises(bundle.BundleError):
                with bundle.checked_zip(path, **limits):
                    pass

    def test_rejects_malformed_zip(self):
        path = self.root / 'bad.zip'
        path.write_bytes(b'not a zip')
        with self.assertRaises(bundle.BundleError):
            with bundle.checked_zip(path):
                pass

    def test_rejects_wrong_root_before_extraction(self):
        path = self.archive([('other/file', b'bad')])
        with self.assertRaises(bundle.BundleError):
            bundle.extract_zip(path, self.root / 'output', strip_prefix='native-workbench/')
        self.assertFalse((self.root / 'output').exists())

    def test_existing_destination_never_overwritten(self):
        path = self.archive([('file', b'new')])
        target = self.root / 'output'
        target.mkdir()
        (target / 'file').write_bytes(b'original')
        with self.assertRaises(bundle.BundleError):
            bundle.extract_zip(path, target)
        self.assertEqual((target / 'file').read_bytes(), b'original')
        with self.assertRaises(bundle.BundleError):
            bundle.build(self.root, target)
        self.assertEqual((target / 'file').read_bytes(), b'original')

    def test_pin_rejects_valid_but_tampered_zip(self):
        original = self.archive([('file', b'approved')], 'input.zip')
        pin = {'role': 'starter', 'file': 'input.zip', **bundle.identity(original)}
        with zipfile.ZipFile(original, 'w') as archive:
            archive.writestr('file', b'tampered')
        with self.assertRaisesRegex(bundle.BundleError, 'hash/size differs'):
            bundle.verify_inputs(self.root, {'inputArchives': [pin]})

    def test_pin_rejects_crc_failure_even_when_outer_hash_matches(self):
        path = self.root / 'bad-crc.zip'
        with zipfile.ZipFile(path, 'w', zipfile.ZIP_STORED) as archive:
            archive.writestr('file', b'unique-body-123')
        path.write_bytes(path.read_bytes().replace(b'unique-body-123', b'unique-body-124'))
        pin = {'role': 'starter', 'file': path.name, **bundle.identity(path)}
        with self.assertRaises(bundle.BundleError):
            bundle.verify_inputs(self.root, {'inputArchives': [pin]})

    def test_pin_accepts_exact_valid_zip(self):
        path = self.archive([('file', b'approved')], 'input.zip')
        pin = {'role': 'starter', 'file': path.name, **bundle.identity(path)}
        self.assertEqual(bundle.verify_inputs(self.root, {'inputArchives': [pin]}), {'starter': path})

    def test_inventory_rejects_tampering_duplicate_and_bad_size(self):
        path = self.root / 'file'
        path.write_bytes(b'approved')
        pin = {'path': 'file', **bundle.identity(path)}
        self.assertEqual(bundle.checked_inventory(self.root, [pin]), {'file'})
        for entries in ([pin, pin], [{**pin, 'bytes': True}], [{**pin, 'path': '../escape'}]):
            with self.subTest(entries=entries), self.assertRaises(bundle.BundleError):
                bundle.checked_inventory(self.root, entries)
        path.write_bytes(b'tampered')
        with self.assertRaisesRegex(bundle.BundleError, 'identity differs'):
            bundle.checked_inventory(self.root, [pin])

    def test_rejects_linked_input_and_tree_files(self):
        actual = self.root / 'actual'
        actual.write_bytes(b'payload')
        link = self.root / 'link'
        try:
            link.symlink_to(actual)
        except OSError as exc:
            self.skipTest('OS did not permit test symlink creation: ' + str(exc))
        with self.assertRaises(bundle.BundleError):
            bundle.regular_file(link)
        with self.assertRaises(bundle.BundleError):
            bundle.tree_files(self.root)

    def test_zip_creation_is_deterministic_and_complete(self):
        root = self.root / 'bundle'
        root.mkdir()
        (root / 'space file.txt').write_bytes(b'bytes')
        (root / 'manifest.json').write_bytes(b'{}')
        first, second = self.root / 'first.zip', self.root / 'second.zip'
        bundle.make_zip(root, first)
        bundle.make_zip(root, second)
        self.assertEqual(first.read_bytes(), second.read_bytes())
        with bundle.checked_zip(first) as archive:
            self.assertEqual(set(archive.namelist()), {bundle.BUNDLE_NAME + '/space file.txt',
                                                     bundle.BUNDLE_NAME + '/manifest.json'})
            self.assertEqual(archive.read(bundle.BUNDLE_NAME + '/space file.txt'), b'bytes')

    def test_launchers_use_quoted_private_python_without_policy_bypass(self):
        bundle.launchers(self.root)
        for filename, command in [('verify.cmd', 'verify'), ('acceptance.cmd', 'guided'), ('signatures.cmd', 'signatures')]:
            text = (self.root / filename).read_text()
            self.assertIn('"%~dp0native-workbench\\runtime\\python\\python.exe" -I -B', text)
            self.assertIn('deployment_acceptance.py" ' + command + ' --bundle-root "%~dp0."', text)
            self.assertIn('DisableDelayedExpansion', text)
            self.assertIn('set "toolkit_exit=%errorlevel%"', text)
            self.assertIn('pause\nexit /b %toolkit_exit%', text)
            self.assertNotIn('ExecutionPolicy', text)

    def test_duplicate_json_keys_and_nonfinite_numbers_rejected(self):
        for raw in (b'{"x":1,"x":2}', b'{"x":NaN}', b'{bad'):
            with self.subTest(raw=raw), self.assertRaises(bundle.BundleError):
                bundle.strict_json(raw)

    def test_rejects_nul_truncated_names(self):
        path = self.archive([('badXname', b'body')])
        path.write_bytes(path.read_bytes().replace(b'badXname', b'bad\x00name'))
        with self.assertRaisesRegex(bundle.BundleError, 'truncated'):
            bundle.extract_zip(path, self.root / 'output')
        self.assertFalse((self.root / 'output').exists())

    def test_toolkit_source_binding_rejects_uncommitted_or_different_bytes(self):
        (self.root / 'tool.py').write_bytes(b'local')
        commit = 'a' * 40
        def git(command, **kwargs):
            if command[3:] == ['rev-parse', 'HEAD']:
                return (commit + '\n').encode()
            if command[3] == 'show':
                return b'committed'
            return ('b' * 40 + '\n').encode()
        with mock.patch.object(bundle, 'TOOLKIT_FILES', ('tool.py',)), \
                mock.patch.object(bundle.subprocess, 'check_output', side_effect=git):
            with self.assertRaisesRegex(bundle.BundleError, 'differs from checkout commit'):
                bundle.source_identity(self.root, commit)
            with self.assertRaisesRegex(bundle.BundleError, 'must equal'):
                bundle.source_identity(self.root, 'c' * 40)
        def untracked(command, **kwargs):
            if command[3:] == ['rev-parse', 'HEAD']:
                return (commit + '\n').encode()
            raise subprocess.CalledProcessError(128, command)
        with mock.patch.object(bundle, 'TOOLKIT_FILES', ('tool.py',)), \
                mock.patch.object(bundle.subprocess, 'check_output', side_effect=untracked):
            with self.assertRaisesRegex(bundle.BundleError, 'not committed'):
                bundle.source_identity(self.root, commit)

    def test_toolkit_source_binding_records_exact_git_and_sha256_identity(self):
        raw = b'committed'
        (self.root / 'tool.py').write_bytes(raw)
        commit, blob = 'a' * 40, 'b' * 40
        def git(command, **kwargs):
            if command[3:] == ['rev-parse', 'HEAD']:
                return (commit + '\n').encode()
            if command[3] == 'show':
                return raw
            if command[3] == 'status':
                return b''
            return (blob + '\n').encode()
        with mock.patch.object(bundle, 'TOOLKIT_FILES', ('tool.py',)), \
                mock.patch.object(bundle.subprocess, 'check_output', side_effect=git):
            actual, dirty, files = bundle.source_identity(self.root, commit)
        self.assertEqual((actual, dirty), (commit, False))
        self.assertEqual(files, [{'path': 'tool.py', 'gitBlobSha1': blob, 'bytes': len(raw),
                                 'sha256': hashlib.sha256(raw).hexdigest()}])

    def test_lock_contains_exact_four_public_archive_roles(self):
        lock = bundle.load_lock()
        self.assertEqual({row['role'] for row in lock['inputArchives']}, {'starter', 'updater', 'source', 'baseline'})
        self.assertEqual(len(lock['packs']), 4)
        self.assertEqual(lock['sourceCommit'], 'e855dc4396e0c16ae35f4e840eb9cc734adb4441')


if __name__ == '__main__':
    unittest.main()
