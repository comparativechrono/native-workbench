"""Acceptance records do not turn integrity/hosted evidence into human passes.

Small fixtures test ownership and evidence contracts; real bundled executable
and PowerShell observations have separate native Windows gates.
"""
import copy
import hashlib
import json
import os
from pathlib import Path
import socket
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import deployment_acceptance as acceptance


class AcceptanceContracts(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.parent = Path(self.temp.name).resolve()
        self.root = self.parent / 'kit with spaces ü'
        self.root.mkdir()
        self.rows = []
        self.archives = []
        pins = {}
        for role in ('starter', 'updater', 'source', 'baseline'):
            name = role + '.zip'
            row = self.put('archives/' + name, (role + ' fixture').encode())
            self.archives.append({'role': role, 'file': name, 'bytes': row['bytes'],
                'sha256': row['sha256'], 'url': 'https://example.invalid/' + name})
            pins[role] = (name, row['bytes'], row['sha256'])
        self.put('native-workbench/NativeWorkbench.exe', b'fixture executable')
        self.put('native-workbench/runtime/python/python.exe', b'fixture private runtime')
        self.put('native-workbench/workspace/app.py', b'fixture source')
        self.put('toolkit/scripts/deployment_acceptance.py', b'fixture acceptance helper')
        self.put('toolkit/scripts/collect_deployment_signatures.ps1', b'fixture signature helper')
        self.manifest = {'schema': 1, 'sourceCommit': acceptance.SOURCE_COMMIT,
            'toolkitCommit': 'a' * 40, 'toolkitDirty': False,
            'inputArchives': self.archives, 'files': self.rows}
        self.save_manifest()
        self.pins = patch.object(acceptance, 'PUBLISHED_ARCHIVES', pins)
        self.pins.start()
        self.bundle = acceptance.verify_bundle(self.root)
        self.report_path = self.parent / 'reports ü' / 'PC-A.json'
        self.report = acceptance.new_report(self.bundle, 'PC-A')

    def tearDown(self):
        self.pins.stop()
        self.temp.cleanup()

    def put(self, name, content):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        row = {'path': name, 'bytes': len(content), 'sha256': hashlib.sha256(content).hexdigest()}
        self.rows.append(row)
        return row

    def save_manifest(self):
        (self.root / acceptance.MANIFEST).write_text(json.dumps(self.manifest), encoding='utf-8')

    def automatic_summary(self):
        return {'schemaVersion': 1, 'kind': 'native-deployment-gate',
            'sourceCommit': self.bundle['sourceCommit'], 'toolkitCommit': self.bundle['toolkitCommit'],
            'bundleManifestSha256': self.bundle['manifestSha256'], 'observedAt': '2026-10-09T18:00:00Z',
            'checks': [{'id': 'updater-picker', 'status': 'pass',
                        'observedAt': '2026-10-09T18:00:00Z', 'note': 'Native hosted observation.'}],
            'limits': ['Physical trackpad and representative-PC acceptance not established.']}

    def write_automatic(self, value):
        path = self.parent / 'automated.json'
        path.write_text(json.dumps(value), encoding='utf-8')
        return path

    def test_verifier_accepts_exact_unicode_space_path_and_digest(self):
        found = acceptance.verify_bundle(self.root, self.bundle['manifestSha256'])
        self.assertEqual(len(found['filesByPath']), len(self.rows))
        self.assertEqual(found['toolkitCommit'], 'a' * 40)

    def test_modified_helper_is_rejected_before_execution(self):
        (self.root / 'toolkit/scripts/collect_deployment_signatures.ps1').write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError, 'integrity failure'):
            acceptance.verify_bundle(self.root)

    def test_uninventoried_data_and_missing_file_are_rejected(self):
        extra = self.root / 'native-workbench/user-data/private.json'
        extra.parent.mkdir()
        extra.write_text('unrecorded')
        with self.assertRaisesRegex(ValueError, 'unrecorded'):
            acceptance.verify_bundle(self.root)
        extra.unlink()
        (self.root / self.rows[0]['path']).unlink()
        with self.assertRaisesRegex(ValueError, 'missing'):
            acceptance.verify_bundle(self.root)

    def test_wrong_manifest_source_or_dirty_toolkit_is_rejected(self):
        for key, value in [('sourceCommit', 'b' * 40), ('toolkitCommit', 'main'), ('toolkitDirty', True)]:
            original = self.manifest[key]
            self.manifest[key] = value
            self.save_manifest()
            with self.assertRaises(ValueError):
                acceptance.verify_bundle(self.root)
            self.manifest[key] = original

    def test_independent_manifest_digest_is_checked(self):
        with self.assertRaisesRegex(ValueError, 'expected value'):
            acceptance.verify_bundle(self.root, '0' * 64)

    def test_duplicate_case_paths_and_json_keys_rejected(self):
        duplicate = dict(self.rows[0], path=self.rows[0]['path'].upper())
        self.rows.append(duplicate)
        self.save_manifest()
        with self.assertRaisesRegex(ValueError, 'Duplicate'):
            acceptance.verify_bundle(self.root)
        (self.root / acceptance.MANIFEST).write_text('{"schema":1,"schema":1}', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'Duplicate JSON'):
            acceptance.verify_bundle(self.root)

    def test_changed_archive_cannot_be_relabelled_as_published(self):
        changed = b'changed archive consistently relabelled in both inventories'
        (self.root / self.rows[0]['path']).write_bytes(changed)
        for row in (self.archives[0], self.rows[0]):
            row['sha256'] = hashlib.sha256(changed).hexdigest()
            row['bytes'] = len(changed)
        self.save_manifest()
        with self.assertRaisesRegex(ValueError, 'published release'):
            acceptance.verify_bundle(self.root)

    def test_traversal_windows_devices_and_ambiguous_paths_rejected(self):
        for name in ('../outside', '/absolute', 'a/../b', 'a//b', 'a/./b', 'a\\b',
                     'C:/data', 'file:stream', 'a/CON.txt', 'a/NUL', 'a/LPT3.exe', 'a/end.', 'a/end '):
            with self.subTest(path=name), self.assertRaises(ValueError):
                acceptance.relative_path(name)

    @unittest.skipIf(os.name == 'nt', 'Windows symlink permission is an explicit native prerequisite.')
    def test_symlink_inventory_and_report_parent_rejected(self):
        original = self.root / 'native-workbench/NativeWorkbench.exe'
        source = self.parent / 'outside.exe'
        source.write_bytes(original.read_bytes())
        original.unlink()
        original.symlink_to(source)
        with self.assertRaisesRegex(ValueError, 'Symlinks'):
            acceptance.verify_bundle(self.root)
        link = self.parent / 'linked'
        link.symlink_to(self.root, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, 'Symlinks'):
            acceptance.outside_bundle(link / 'report.json', self.bundle)

    def test_new_manual_report_does_not_claim_acceptance(self):
        self.assertTrue(all(row['status'] == 'not-tested' and row['observedAt'] is None
                            for row in self.report['manualChecks']))
        self.assertEqual(self.report['summary']['manualAcceptance'], 'not-tested')
        self.assertEqual(self.report['signatures']['status'], 'not-tested')
        self.assertEqual(self.report['bundleManifestSha256'], self.bundle['manifestSha256'])
        self.assertTrue(self.report['helpers'])

    def test_machine_observation_does_not_query_identity(self):
        with patch.object(socket, 'gethostname', side_effect=AssertionError('hostname queried')), \
                patch.object(os, 'getlogin', side_effect=AssertionError('username queried')):
            report = acceptance.new_report(self.bundle, 'Teaching-PC-02')
        encoded = json.dumps(report)
        self.assertNotIn(str(self.root), encoded)
        self.assertNotIn(str(self.parent), encoded)
        self.assertEqual(set(report['observations']), {'system', 'release', 'version', 'architecture', 'displays'})

    def test_alias_is_explicit_not_an_automatic_account_name(self):
        for alias in ('', None, 'Name @ Institution', 'a' * 49, '../tester'):
            with self.subTest(alias=alias), self.assertRaises(ValueError):
                acceptance.new_report(self.bundle, alias)

    def test_report_refuses_bundle_and_existing_file(self):
        with self.assertRaisesRegex(ValueError, 'outside'):
            acceptance.write_report(self.root / 'report.json', self.report, self.bundle, create=True)
        acceptance.write_report(self.report_path, self.report, self.bundle, create=True)
        with self.assertRaisesRegex(ValueError, 'already exists'):
            acceptance.write_report(self.report_path, self.report, self.bundle, create=True)

    def test_record_needs_observation_and_keeps_old_failure(self):
        with self.assertRaisesRegex(ValueError, 'observation'):
            acceptance.record_check(self.report_path, self.report, self.bundle, 'keyboard', 'pass', '')
        acceptance.record_check(self.report_path, self.report, self.bundle, 'keyboard', 'failed', 'Focus lost on Escape.')
        acceptance.record_check(self.report_path, self.report, self.bundle, 'keyboard', 'pass', 'Rechecked exact Tab and Escape sequence.')
        row = next(item for item in self.report['manualChecks'] if item['id'] == 'keyboard')
        self.assertEqual(row['history'][0]['status'], 'failed')
        self.assertEqual(row['status'], 'pass')
        acceptance.write_report(self.report_path, self.report, self.bundle, create=True)
        self.assertEqual(self.report['summary']['manualAcceptance'], 'incomplete')
        self.assertEqual(self.report['summary']['institutionalApproval'], 'not-established')

    def test_failed_and_blocked_are_distinct_from_not_tested(self):
        acceptance.record_check(self.report_path, self.report, self.bundle, 'keyboard', 'blocked', 'No physical keyboard available.')
        acceptance.write_report(self.report_path, self.report, self.bundle, create=True)
        self.assertEqual(self.report['summary']['manualAcceptance'], 'blocked')
        acceptance.record_check(self.report_path, self.report, self.bundle, 'first-launch', 'failed', 'Launch failed under existing policy.')
        acceptance.write_report(self.report_path, self.report, self.bundle)
        self.assertEqual(self.report['summary']['manualAcceptance'], 'failed')

    def test_explicit_attachment_copy_hash_and_path_privacy(self):
        attachment = self.parent / 'private-person-named-screenshot.bmp'
        attachment.write_bytes(b'selected synthetic screenshot')
        acceptance.record_check(self.report_path, self.report, self.bundle, 'keyboard', 'failed',
                                'Visible focus absent.', [attachment])
        item = self.report['attachments'][0]
        self.assertEqual(acceptance.sha256(self.report_path.parent / item['file']), item['sha256'])
        encoded = json.dumps(self.report)
        self.assertNotIn(str(attachment), encoded)
        self.assertNotIn(attachment.name, encoded)
        self.assertTrue(item['selectedAt'].endswith('Z'))

    def test_attachment_bounds_reject_without_partial_copy(self):
        attachment = self.parent / 'large.txt'
        attachment.write_bytes(b'12345')
        with patch.object(acceptance, 'MAX_ATTACHMENT', 4), self.assertRaisesRegex(ValueError, 'limit'):
            acceptance.attach_files(self.report_path, self.report, self.bundle, [attachment])
        self.assertEqual(self.report['attachments'], [])

    def test_hosted_pass_never_promotes_manual_check(self):
        value = self.automatic_summary()
        acceptance.import_automated(self.write_automatic(value), self.report, self.bundle)
        self.assertEqual(len(self.report['automatedReports']), 1)
        self.assertTrue(all(row['status'] == 'not-tested' for row in self.report['manualChecks']))
        self.assertEqual(self.report['summary']['manualAcceptance'], 'not-tested')

    def test_automated_import_requires_exact_bundle_source_and_helper_commit(self):
        for key in ('bundleManifestSha256', 'sourceCommit', 'toolkitCommit'):
            value = self.automatic_summary()
            value[key] = 'b' * len(value[key])
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, 'different source'):
                acceptance.import_automated(self.write_automatic(value), self.report, self.bundle)

    def test_automated_unexpected_fields_and_ambiguous_passes_rejected(self):
        for mutation in ('hostname', 'state', 'duplicate', 'time'):
            value = self.automatic_summary()
            if mutation == 'hostname':
                value['hostname'] = 'must-not-import'
            elif mutation == 'state':
                value['checks'][0]['status'] = True
            elif mutation == 'duplicate':
                value['checks'].append(copy.deepcopy(value['checks'][0]))
            else:
                value['checks'][0]['observedAt'] = 'today'
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                acceptance.import_automated(self.write_automatic(value), self.report, self.bundle)

    def test_report_from_other_bundle_is_rejected(self):
        acceptance.write_report(self.report_path, self.report, self.bundle, create=True)
        altered = dict(self.bundle, manifestSha256='f' * 64)
        with self.assertRaisesRegex(ValueError, 'different bundle'):
            acceptance.load_report(self.report_path, altered)

    def test_fresh_disposable_copy_is_verified_and_bundle_unchanged(self):
        destination = self.parent / 'disposable app ü'
        copied = acceptance.prepare_installation(destination, self.bundle, self.report)
        self.assertEqual(copied, destination)
        self.assertEqual(self.report['testInstallation']['files'], 3)
        self.assertEqual((destination / 'NativeWorkbench.exe').read_bytes(), b'fixture executable')
        self.assertNotIn(str(destination), json.dumps(self.report))
        self.assertEqual(acceptance.verify_bundle(self.root)['manifestSha256'], self.bundle['manifestSha256'])
        self.assertTrue(all(item['status'] == 'not-tested' for item in self.report['manualChecks']))

    def test_disposable_copy_rejects_existing_destination_or_bundle(self):
        for destination in (self.root / 'copy', self.parent):
            with self.subTest(destination=destination), self.assertRaises(ValueError):
                acceptance.prepare_installation(destination, self.bundle, self.report)

    @unittest.skipIf(os.name == 'nt', 'Non-Windows unavailable behavior only.')
    def test_signatures_unavailable_is_not_a_pass(self):
        acceptance.collect_signatures(self.report_path, self.report, self.bundle)
        self.assertEqual(self.report['signatures']['status'], 'unavailable')
        self.assertTrue(all(row['status'] == 'not-tested' for row in self.report['manualChecks']))

    def test_powershell_source_has_no_policy_override_or_directory_discovery(self):
        script = (Path(__file__).resolve().parents[1] / 'scripts/collect_deployment_signatures.ps1').read_text()
        self.assertIn('Get-AuthenticodeSignature -LiteralPath', script)
        self.assertIn('Get-FileHash -LiteralPath', script)
        self.assertNotIn('Get-ChildItem', script)
        self.assertNotIn('Set-ExecutionPolicy', script)
        self.assertNotIn('-ExecutionPolicy', script)
        self.assertNotIn('SignTool', script)
        self.assertIn("[IO.Path]::Combine($PSHOME, 'Modules', $moduleName, $moduleName + '.psd1')", script)
        self.assertIn('Import-Module -Name $modulePath -ErrorAction Stop', script)
        self.assertNotIn('$env:PSModulePath =', script)

    def test_signature_targets_include_extensionless_pe_update_blobs(self):
        pe = bytearray(80)
        pe[:2] = b'MZ'
        pe[60:64] = (64).to_bytes(4, 'little')
        pe[64:68] = b'PE\0\0'
        row = self.put('updater/update/blobs/abc123', bytes(pe))
        self.put('updater/update/blobs/not-a-pe', b'MZ' + b'\0' * 100)
        self.save_manifest()
        bundle = acceptance.verify_bundle(self.root)
        targets = acceptance.signature_targets(bundle)
        self.assertEqual(targets[row['path']], row)
        self.assertIn('native-workbench/NativeWorkbench.exe', targets)
        self.assertNotIn('updater/update/blobs/not-a-pe', targets)

    def test_bad_manifest_container_and_archive_types_rejected(self):
        (self.root / acceptance.MANIFEST).write_text('[]', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'JSON object'):
            acceptance.verify_bundle(self.root)
        self.manifest['inputArchives'] = [1, 2, 3, 4]
        self.save_manifest()
        with self.assertRaisesRegex(ValueError, 'four identified'):
            acceptance.verify_bundle(self.root)

    def test_collector_diagnostic_retains_only_stage_type_and_line(self):
        value = {'schemaVersion': 1, 'stage': 'root-check',
                 'errorType': 'System.Management.Automation.MethodException', 'scriptLine': 50}
        raw = ('Unexpected private path C:\\Users\\private\\work\nNW_SIGNATURE_DIAGNOSTIC ' + json.dumps(value)).encode()
        result = acceptance.collector_diagnostic(raw, 2)
        self.assertEqual(result, {'stage': 'root-check', 'errorType': value['errorType'],
                                  'scriptLine': 50, 'exitCode': 2})
        self.assertNotIn('private', json.dumps(result))

    def test_system_module_load_failure_remains_diagnosable(self):
        value = {'schemaVersion': 1, 'stage': 'system-modules',
                 'errorType': 'System.IO.FileNotFoundException', 'scriptLine': 59}
        result = acceptance.collector_diagnostic(('NW_SIGNATURE_DIAGNOSTIC ' + json.dumps(value)).encode(), 2)
        self.assertEqual(result['stage'], 'system-modules')
        self.assertEqual(result['errorType'], 'System.IO.FileNotFoundException')

    def test_collector_diagnostic_rejects_raw_paths_extra_fields_and_unbounded_output(self):
        good = {'schemaVersion': 1, 'stage': 'root-check',
                'errorType': 'System.Management.Automation.MethodException', 'scriptLine': 50}
        bad = [dict(good, message='C:\\Users\\private'), dict(good, errorType='C:\\Users\\private'),
               dict(good, stage='C:\\Users\\private'), dict(good, scriptLine=-1)]
        for value in bad:
            with self.subTest(value=value):
                result = acceptance.collector_diagnostic(('NW_SIGNATURE_DIAGNOSTIC ' + json.dumps(value)).encode(), 2)
                self.assertEqual(result['errorType'], 'NoStructuredDiagnostic')
                self.assertNotIn('private', json.dumps(result))
        self.assertEqual(acceptance.collector_diagnostic(b'x' * 4097, 1)['stage'], 'collector-launch')
        self.assertEqual(acceptance.collector_diagnostic(b'', None, 'TimeoutExpired')['errorType'], 'TimeoutExpired')


if __name__ == '__main__':
    unittest.main()
