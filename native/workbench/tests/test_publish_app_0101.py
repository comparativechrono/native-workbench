#!/usr/bin/env python3
"""Fail-closed exact-release controls; synthetic inputs, no network or publication."""
from copy import deepcopy
import importlib.util
import io
import json
import os
from pathlib import Path
import tempfile
import types
import unittest
from unittest.mock import patch
import urllib.error
import zipfile

spec = importlib.util.spec_from_file_location('promotion0101', Path(__file__).resolve().parents[1] / 'scripts/publish_app_0101.py')
p = importlib.util.module_from_spec(spec)
spec.loader.exec_module(p)


def accepted():
    return {'sourceCommit': 'a' * 40, 'runId': 123, 'prNumber': 5,
            'reportHashes': {key: 'f' * 64 for key in p.REPORT_KEYS}, 'fingerprint': p.FINGERPRINT, 'coreFiles': 72,
            'archives': {name: {'bytes': 100, 'sha256': str(number) * 64}
                         for number, name in enumerate((p.STARTER, p.UPDATE, p.SOURCES), 1)},
            'artifacts': {role: {'id': index, 'file': role + '.zip', 'bytes': 100,
                                'sha256': 'b' * 64, 'name': 'setup-' + role}
                          for index, role in enumerate(('candidate', 'ordinary', 'spaces', 'production-full'), 1)}}


def science():
    return {'networkSocketOperationsDeniedForHost': True, 'nativeWindowsExecuted': True,
            'outputsIndependentlyHashed': 20, 'nativeCommandsCompared': 18, 'cwlRunnerReplays': [0] * 5}


def polling(negative=False):
    stable = {'frames': 40, 'positionChanges': [], 'headerHashes': {'hash': 40},
              'pixelComparison': 'BGR bytes only; undefined BitBlt alpha ignored'}
    return {'expectedRegression': negative, 'defects': ['Disabled package list'] if negative else [],
            'navigationDefects': ['Disabled package list'] if negative else [],
            'immediateCustomFullChecks': True,
            'idle': deepcopy(stable), 'idleWheel': deepcopy(stable),
            'polling': {**deepcopy(stable), 'busySamples': 40, 'observedBusySeconds': 4,
                        'disabledSamples': 40 if negative else 0,
                        'progressStates': [{'notice': 'Downloading', 'position': 1},
                                           {'notice': 'Downloading', 'position': 2}]},
            'busyWheel': {'before': {'top': 20}, 'after': {'top': 17}}}


def report(kind='production'):
    count = 4 if kind == 'production' else p.REPORTS[kind][1]
    data = {'success': True, 'nativeWindowsExecuted': True, 'passed': count, 'skips': [], 'unrun': [],
            'sourceCommit': 'a' * 40, 'assetSha256': '1' * 64, 'gateSha256': p.sha(b'gate'),
            'appFiles': {'workspace\\core.py': p.sha(b'core')}, 'nativeGUIValidated': True}
    if kind == 'references':
        data['skips'] = ['Optional native core updater gate was not requested.']
    if kind == 'setup':
        data['gui'] = {'nativeGUIValidated': True}
        data['uiPolling'] = polling()
    if kind == 'results':
        data['science'] = science()
    if kind == 'production':
        data['productionTrustValidated'] = kind == 'production'
        data['full'] = {'productionTrustValidated': kind == 'production', 'configuration': None,
                        'science': {'nativeWindowsExecuted': True, 'networkSocketOperationsDenied': True, 'records': 202}}
    return data


def update_report():
    return {'nativeWindowsHost': True, 'validationCommit': 'a' * 40, 'starterSha256': '1' * 64,
            'baselineSha256': p.BASELINE_SHA, 'updateSha256': '2' * 64, 'appVersion': p.VERSION,
            'baseVersion': '0.10.0', 'coreFilesVerified': 72,
            'updateAttempts': {'install': {'status': 'installed'}, 'repeat': {'status': 'already-installed'}},
            'preservation': {'files': 203, 'changes': {}, 'additions': {'user-data/session.lock': p.sha(b'\0')}},
            'baselineReferenceRun': {'nativeWindowsExecuted': True, 'referenceSha256': 'c' * 64, 'contigs': 2, 'cwlChecked': False},
            'updatedReferenceRun': {'nativeWindowsExecuted': True, 'referenceSha256': 'c' * 64, 'contigs': 2, 'cwlChecked': True},
            'science': science()}


class PromotionControls(unittest.TestCase):
    def setUp(self):
        self.lock_patch = patch.object(p, 'ACCEPTED', accepted())
        self.lock_patch.start()
        self.addCleanup(self.lock_patch.stop)
        self.core = {'workspace/core.py': p.sha(b'core')}

    def test_missing_acceptance_refuses_before_network(self):
        with patch.object(p, 'ACCEPTED', {}), patch.object(p, 'GitHub') as client, \
             patch.dict(os.environ, {'GITHUB_REPOSITORY': p.REPOSITORY, 'GITHUB_REF': 'refs/heads/' + p.BRANCH,
                                     'GITHUB_SHA': 'a' * 40}):
            with self.assertRaisesRegex(ValueError, 'No completed, pinned'):
                p.publish(types.SimpleNamespace(publish_sha='a' * 40))
            client.assert_not_called()

    def test_wrong_repository_refuses_before_network(self):
        with patch.object(p, 'GitHub') as client, patch.dict(os.environ, {'GITHUB_REPOSITORY': 'wrong/repo'}):
            with self.assertRaisesRegex(ValueError, 'Wrong publication'):
                p.publish(types.SimpleNamespace())
            client.assert_not_called()

    def test_bad_lock_fingerprint_missing_production_and_duplicate_artifact_refuse(self):
        p.acceptance_lock()
        for change in ('fingerprint', 'missing-production', 'duplicate'):
            lock = accepted()
            if change == 'fingerprint':
                lock['fingerprint'] = '0' * 64
            elif change == 'missing-production':
                del lock['artifacts']['production-full']
            else:
                lock['artifacts']['spaces']['id'] = lock['artifacts']['ordinary']['id']
            with self.subTest(change=change), patch.object(p, 'ACCEPTED', lock), self.assertRaises(ValueError):
                p.acceptance_lock()

    def test_missing_pr_or_report_identity_refuses_acceptance(self):
        for change in ('pr', 'missing-report', 'bad-report'):
            lock = accepted()
            if change == 'pr':
                lock['prNumber'] = 0
            elif change == 'missing-report':
                del lock['reportHashes']['ordinary-negative-control']
            else:
                lock['reportHashes']['spaces-setup'] = 'not-a-digest'
            with self.subTest(change=change), patch.object(p, 'ACCEPTED', lock), self.assertRaises(ValueError):
                p.acceptance_lock()

    def test_fixed_ui_requires_sustained_stable_and_scrollable_live_observations(self):
        p.check_ui_polling(polling())
        for change in ('no-live-polls', 'disabled', 'redraw', 'reset', 'no-scroll', 'defect'):
            data = polling()
            if change == 'no-live-polls':
                data['polling']['observedBusySeconds'] = 0
            elif change == 'disabled':
                data['polling']['disabledSamples'] = 1
            elif change == 'redraw':
                data['polling']['headerHashes']['blank'] = 1
            elif change == 'reset':
                data['idleWheel']['positionChanges'].append({'top': 0})
            elif change == 'no-scroll':
                data['busyWheel']['after']['top'] = data['busyWheel']['before']['top']
            else:
                data['defects'].append('Visible failure')
            with self.subTest(change=change), self.assertRaises(ValueError):
                p.check_ui_polling(data)

    def test_final_ui_schema_rejects_static_progress_and_mismatched_reference_pixels(self):
        for change in ('missing-progress', 'static-progress', 'no-immediate-check', 'wheel-reference',
                       'polling-reference', 'unnormalized-pixels'):
            data = polling()
            if change == 'missing-progress':
                del data['polling']['progressStates']
            elif change == 'static-progress':
                data['polling']['progressStates'] = [data['polling']['progressStates'][0]] * 2
            elif change == 'no-immediate-check':
                data['immediateCustomFullChecks'] = False
            elif change == 'wheel-reference':
                data['idleWheel']['headerHashes'] = {'different-header': 40}
            elif change == 'polling-reference':
                data['polling']['headerHashes'] = {'different-header': 40}
            else:
                del data['idle']['pixelComparison']
            with self.subTest(change=change), self.assertRaises(ValueError):
                p.check_ui_polling(data)
        negative = polling(negative=True)
        negative['navigationDefects'] = []
        with self.assertRaisesRegex(ValueError, 'required fixed or negative-control scope'):
            p.check_ui_polling(negative, negative=True)

    def test_negative_control_is_bound_to_old_archive_and_must_reproduce(self):
        files = {'NativeWorkbench.exe': p.sha(b'published native UI')}
        identity = p.sha(json.dumps(files, sort_keys=True, separators=(',', ':')).encode())
        data = {'success': True, 'nativeWindowsExecuted': True, 'passed': 1, 'skips': [],
                'sourceCommit': p.BASELINE_SOURCE, 'appVersion': '0.10.0',
                'assetSha256': p.BASELINE_SHA, 'gateSha256': p.sha(b'gate'), 'appFiles': files,
                'productionTrustValidated': False, 'uiPolling': polling(negative=True)}
        with patch.object(p, 'BASELINE_TESTED_FILES_SHA', identity):
            p.check_negative_report(data, b'gate')
            for change in ('source', 'bytes', 'files', 'no-defect', 'no-live-polls', 'failed-prerequisite'):
                wrong = deepcopy(data)
                if change == 'source':
                    wrong['sourceCommit'] = 'a' * 40
                elif change == 'bytes':
                    wrong['assetSha256'] = '1' * 64
                elif change == 'files':
                    wrong['appFiles']['NativeWorkbench.exe'] = p.sha(b'patched UI')
                elif change == 'no-defect':
                    wrong['uiPolling']['defects'] = []
                elif change == 'no-live-polls':
                    wrong['uiPolling']['polling']['busySamples'] = 0
                else:
                    wrong['error'] = 'Network unavailable'
                with self.subTest(change=change), self.assertRaises(ValueError):
                    p.check_negative_report(wrong, b'gate')

    def test_retained_report_must_match_independently_reviewed_digest(self):
        data = report('setup')
        raw = p.json_bytes(data)
        lock = accepted()
        lock['reportHashes']['ordinary-setup'] = p.sha(raw)
        blob = io.BytesIO()
        with zipfile.ZipFile(blob, 'w') as archive:
            archive.writestr('setup-evidence/native-setup.json', raw)
        with zipfile.ZipFile(io.BytesIO(blob.getvalue())) as archive, patch.object(p, 'ACCEPTED', lock):
            p.retained_report(archive, 'setup-evidence/native-setup.json', 'setup', self.core, b'gate', 'ordinary-setup')
            lock['reportHashes']['ordinary-setup'] = '0' * 64
            with self.assertRaisesRegex(ValueError, 'Reviewed native report hash differs'):
                p.retained_report(archive, 'setup-evidence/native-setup.json', 'setup', self.core, b'gate', 'ordinary-setup')

    def test_existing_tag_refuses_before_any_mutation(self):
        requests = []
        class Client:
            def __init__(self, token):
                pass
            def api(self, path, method='GET', **kwargs):
                requests.append((path, method))
                return {'ref': 'refs/tags/' + p.TAG}
        with patch.dict(os.environ, {'GITHUB_REPOSITORY': p.REPOSITORY, 'GITHUB_REF': 'refs/heads/' + p.BRANCH,
                                     'GITHUB_SHA': 'a' * 40}), patch.object(p, 'GitHub', Client), \
             patch.object(p, 'verify_source_identity'), patch.object(Path, 'read_text', return_value='0.10.1 ' + 'notes ' * 100):
            with self.assertRaisesRegex(ValueError, 'already exists'):
                p.publish(types.SimpleNamespace(publish_sha='a' * 40))
        self.assertEqual(requests, [('/git/ref/tags/' + p.TAG, 'GET')])

    def test_app_or_gate_change_after_candidate_refuses_but_notes_allowed(self):
        with patch.object(p.subprocess, 'run'), patch.object(p.subprocess, 'check_output') as changed:
            for path in ('workspace/engine.py', 'scripts/check_setup_windows.py', '.github/workflows/native-setup-patch-candidate.yml'):
                changed.return_value = path + '\n'
                with self.subTest(path=path), self.assertRaisesRegex(ValueError, 'Application, build or pack code changed'):
                    p.verify_source_identity('b' * 40)
            changed.return_value = 'knowledge/current-state.md\ndocs/releases/0.10.1.md\nscripts/publish_app_0101.py\n'
            p.verify_source_identity('b' * 40)

    def test_unmerged_pr_refuses(self):
        class Client:
            def api(self, path):
                return {'object': {'sha': 'a' * 40}} if path.startswith('/git/') else {'merged': False}
        with self.assertRaisesRegex(ValueError, 'not merged'):
            p.verify_merged(Client(), 'a' * 40)

    def test_candidate_gate_job_inventory_and_unexpected_skip_refuse(self):
        names = ['build', 'native (ordinary)', 'native (path with spaces)', 'production-full']
        class Client:
            bad = False
            missing = False
            def api(self, path):
                if '/jobs?' not in path:
                    return {'head_sha': 'a' * 40, 'status': 'completed', 'conclusion': 'success',
                            'path': '.github/workflows/native-setup-patch-candidate.yml'}
                jobs = [{'id': i, 'name': name, 'conclusion': 'success', 'steps': [{'name': 'gate', 'conclusion': 'success'}]}
                        for i, name in enumerate(names)]
                jobs[2]['steps'].append({'name': 'Native Windows source pack-manager filesystem regressions', 'conclusion': 'skipped'})
                if self.bad:
                    jobs[-1]['steps'][0]['conclusion'] = 'skipped'
                if self.missing:
                    jobs.pop()
                return {'total_count': len(jobs), 'jobs': jobs}
        client = Client()
        self.assertEqual(p.verify_runs(client)['runId'], 123)
        client.bad = True
        with self.assertRaisesRegex(ValueError, 'failed or skipped'):
            p.verify_runs(client)
        client.bad, client.missing = False, True
        with self.assertRaisesRegex(ValueError, 'job inventory'):
            p.verify_runs(client)

    def test_required_gates_accept_exact_scope_and_reject_different_bytes(self):
        for kind in ('setup', 'workspace', 'references', 'results', 'production'):
            data = report(kind)
            with self.subTest(kind=kind):
                p.check_report(data, kind, self.core, b'gate')
                data['assetSha256'] = '0' * 64
                with self.assertRaisesRegex(ValueError, 'different application bytes'):
                    p.check_report(data, kind, self.core, b'gate')

    def test_production_refuses_test_trust_unrun_and_missing_scientific_truth(self):
        for field in ('test-trust', 'substitution', 'unrun', 'science'):
            data = report()
            if field == 'test-trust':
                data['productionTrustValidated'] = False
            elif field == 'substitution':
                data['full']['configuration'] = {'notice': 'fixture'}
            elif field == 'unrun':
                data['unrun'] = ['production absent']
            else:
                data['full']['science']['records'] = 201
            with self.subTest(field=field), self.assertRaises(ValueError):
                p.check_report(data, 'production', self.core, b'gate')

    def test_report_gate_and_application_file_hashes_are_bound(self):
        data = report()
        with self.assertRaisesRegex(ValueError, 'gate script differs'):
            p.check_report(data, 'production', self.core, b'other gate')
        data['appFiles']['workspace\\core.py'] = 'e' * 64
        with self.assertRaisesRegex(ValueError, 'application file differs'):
            p.check_report(data, 'production', self.core, b'gate')

    def test_references_only_known_separate_updater_skip_is_permitted(self):
        data = report('references')
        data['skips'].append('Native GUI smoke was explicitly skipped.')
        with self.assertRaisesRegex(ValueError, 'required scope'):
            p.check_report(data, 'references', self.core, b'gate')

    def test_update_data_and_reference_provenance_survive(self):
        p.check_update_report(update_report())
        for change in ('changed-files', 'missing-cwl', 'wrong-updater', 'lost-source'):
            data = update_report()
            if change == 'changed-files':
                data['preservation']['changes']['user-data/saved.json'] = {'before': 'x', 'after': 'y'}
            elif change == 'missing-cwl':
                data['updatedReferenceRun']['cwlChecked'] = False
            elif change == 'wrong-updater':
                data['updateSha256'] = '0' * 64
            else:
                data['validationCommit'] = '0' * 40
            with self.subTest(change=change), self.assertRaises(ValueError):
                p.check_update_report(data)

    def test_full_state_requires_all32_exact_pins_and_completed_transaction(self):
        packs = [{'id': str(i), 'version': '1.0.0', 'size': 100, 'sha256': 'a' * 64,
                  'manifestSha256': 'b' * 64} for i in range(32)]
        state = {'configured': True, 'rows': [{**row, 'installed': True} for row in packs],
                 'operation': {'active': False, 'status': 'completed', 'completed': 32, 'count': 32}}
        p.verify_full_state(state, {'packs': packs})
        for change in ('missing', 'wrong-pin', 'incomplete'):
            wrong = deepcopy(state)
            if change == 'missing':
                wrong['rows'].pop()
            elif change == 'wrong-pin':
                wrong['rows'][0]['sha256'] = 'c' * 64
            else:
                wrong['operation']['active'] = True
            with self.subTest(change=change), self.assertRaises(ValueError):
                p.verify_full_state(wrong, {'packs': packs})

    def test_public_source_rejects_empty_and_fixture_key(self):
        with self.assertRaisesRegex(ValueError, 'exactly the reviewed'):
            p.check_packaged_trust(b'[]')
        # The public SDK fixture is not production trust even with the right ID/URL.
        import ast
        literals = {node.targets[0].id: ast.literal_eval(node.value)
                    for node in ast.parse((p.ROOT / 'tests/test_pack_manager.py').read_text()).body
                    if isinstance(node, ast.Assign) and len(node.targets) == 1
                    and getattr(node.targets[0], 'id', '') == 'N'}
        source = {'schema': 1, 'id': 'native-workbench-official', 'name': 'Native Workbench official tools',
                  'catalogUrl': 'https://raw.githubusercontent.com/comparativechrono/workbench/catalogue/catalogue.json',
                  'publicKey': {'n': literals['N'], 'e': 65537},
                  'allowedHosts': ['github.com', 'raw.githubusercontent.com', 'release-assets.githubusercontent.com']}
        with self.assertRaisesRegex(ValueError, 'fingerprint differs'):
            p.check_packaged_trust(p.json_bytes([source]))

    def test_zip_traversal_and_duplicate_members_refuse(self):
        for names in (['../escape'], ['safe', 'safe']):
            raw = io.BytesIO()
            with zipfile.ZipFile(raw, 'w') as archive:
                for name in names:
                    archive.writestr(name, b'data')
            with self.subTest(names=names), self.assertRaises(ValueError):
                p.checked_zip(raw.getvalue())

    def test_artifact_wrong_run_refuses_before_download(self):
        class Client:
            base = 'https://api.github.com/repos/' + p.REPOSITORY
            def api(self, path):
                return {'workflow_run': {'id': 999, 'head_sha': 'a' * 40}, 'expired': False}
            def download(self, *args):
                raise AssertionError('Must not download unrelated artifact')
        with tempfile.TemporaryDirectory() as directory, self.assertRaisesRegex(ValueError, 'metadata changed'):
            p.download_artifacts(Client(), Path(directory))

    def test_api_redirect_never_forwards_credentials(self):
        with patch.object(p.urllib.request, 'build_opener') as opener, patch.object(p.urllib.request, 'urlopen') as default:
            opener.return_value.open.side_effect = urllib.error.HTTPError('https://api.github.com/example', 302, 'redirect',
                                                                         {'Location': 'https://outside.invalid'}, None)
            with self.assertRaisesRegex(RuntimeError, 'HTTP 302'):
                p.GitHub('dummy-token').api('/releases')
            opener.assert_called_once_with(p.NoRedirect)
            default.assert_not_called()

    def test_artifact_redirect_drops_authorization_and_uses_correct_media_type(self):
        client = p.GitHub('dummy-token')
        content, requests = b'exact bytes', []
        with tempfile.TemporaryDirectory() as temporary, patch.object(p.urllib.request, 'build_opener') as opener:
            def open_request(request, timeout):
                requests.append(request)
                if len(requests) == 1:
                    raise urllib.error.HTTPError(request.full_url, 302, 'redirect',
                        {'Location': 'https://test.blob.core.windows.net/artifacts/pinned.zip?signature=synthetic'}, None)
                return io.BytesIO(content)
            opener.return_value.open.side_effect = open_request
            client.download(client.base + '/actions/artifacts/123/zip', Path(temporary) / 'file.zip',
                            p.sha(content), len(content), True)
        self.assertEqual(requests[0].get_header('Accept'), 'application/vnd.github+json')
        self.assertEqual(requests[0].get_header('Authorization'), 'Bearer dummy-token')
        self.assertIsNone(requests[1].get_header('Authorization'))

    def test_read_only_client_refuses_mutations(self):
        with patch.object(p.GitHub, 'api') as request:
            for method in ('POST', 'PATCH', 'DELETE'):
                with self.subTest(method=method), self.assertRaisesRegex(ValueError, 'GET requests only'):
                    p.ReadOnlyGitHub('dummy-token').api('/releases', method)
            request.assert_not_called()

    def test_public_anonymous_readback_retries_404_and_keeps_exact_identity(self):
        content, downloads = b'exact public asset', []
        canonical = f'https://github.com/{p.REPOSITORY}/releases/download/{p.TAG}/asset.txt'
        class Client:
            def api(self, path):
                if path.startswith('/git/ref/'):
                    return {'object': {'sha': 'a' * 40}}
                return {'id': 12, 'tag_name': p.TAG, 'draft': False, 'prerelease': True,
                        'html_url': 'https://github.com/example/release', 'assets': [{'name': 'asset.txt',
                            'state': 'uploaded', 'size': len(content), 'digest': 'sha256:' + p.sha(content),
                            'browser_download_url': canonical}]}
            def download(self, url, path, digest, size, authenticated=False):
                downloads.append((url, authenticated))
                if len(downloads) == 1:
                    raise RuntimeError('Download failed: HTTP 404')
                self_test.assertEqual((digest, size), (p.sha(content), len(content)))
                path.write_bytes(content)
        self_test = self
        with tempfile.TemporaryDirectory() as temporary, patch.object(p.time, 'sleep') as sleep:
            path = Path(temporary) / 'asset.txt'
            path.write_bytes(content)
            receipt = p.verify_public_downloads(Client(), 12, [path], 'a' * 40, Path(temporary) / 'receipt.json', True)
            self.assertTrue(receipt['success'])
            self.assertTrue(receipt['verificationOnly'])
            self.assertEqual(downloads, [(canonical, False), (canonical, False)])
            sleep.assert_called_once_with(2)

    def test_online_candidate_preparation_is_get_only_and_records_no_publication(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            output = directory / 'assets'
            output.mkdir()
            (output / 'RELEASE-VALIDATION.json').write_bytes(b'{"prepared":true}')
            args = types.SimpleNamespace(publish_sha='a' * 40, input_dir=directory / 'inputs',
                                         output_dir=output, receipt=directory / 'receipt.json')
            client = p.ReadOnlyGitHub('dummy-token')
            requests = []
            def verified_runs(value):
                value.api('/actions/runs/123')
                return {'runId': 123}
            def get_api(instance, endpoint, method='GET', data=None, absent_ok=False):
                requests.append((endpoint, method))
                return {}
            with patch.dict(os.environ, {'GITHUB_REPOSITORY': p.REPOSITORY,
                                         'GITHUB_REF': 'refs/heads/release/verify-app-0.10.1',
                                         'GITHUB_SHA': 'a' * 40}), patch.object(p, 'verify_source_identity'), \
                 patch.object(p, 'ReadOnlyGitHub', return_value=client), patch.object(p.GitHub, 'api', get_api), \
                 patch.object(p, 'verify_runs', side_effect=verified_runs), patch.object(p, 'download_artifacts'), \
                 patch.object(p, 'prepare', return_value={'prepared': True}), patch.object(p, 'publish') as publish:
                p.verify_candidate_online(args)
                publish.assert_not_called()
            receipt = json.loads(args.receipt.read_bytes())
            self.assertTrue(receipt['success'])
            self.assertFalse(receipt['remoteMutations'])
            self.assertFalse(receipt['releasePublished'])
            self.assertIsNone(receipt['publicationCommit'])
            self.assertEqual(receipt['publicDownloads'], [])
            self.assertEqual(requests, [('/actions/runs/123', 'GET')])

    def test_candidate_mode_has_separate_branch_and_cli_never_routes_to_publish(self):
        with patch.dict(os.environ, {'GITHUB_REPOSITORY': p.REPOSITORY, 'GITHUB_REF': 'refs/heads/' + p.BRANCH}), \
             patch.object(p, 'ReadOnlyGitHub') as client:
            with self.assertRaisesRegex(ValueError, 'Wrong candidate verification'):
                p.verify_candidate_online(types.SimpleNamespace())
            client.assert_not_called()
        argv = ['promotion', '--verify-candidate', '--input-dir', 'inputs', '--output-dir', 'outputs',
                '--publish-sha', 'a' * 40]
        with patch('sys.argv', argv), patch.object(p, 'verify_candidate_online') as verify, \
             patch.object(p, 'publish') as publish, patch.object(p, 'verify_published') as published:
            p.main()
            verify.assert_called_once()
            publish.assert_not_called()
            published.assert_not_called()

    def test_early_failure_keeps_diagnostic_without_fabricated_publication(self):
        with tempfile.TemporaryDirectory() as temporary:
            receipt = Path(temporary) / 'receipt.json'
            argv = ['promotion', '--input-dir', temporary, '--output-dir', str(Path(temporary) / 'assets'),
                    '--publish-sha', 'a' * 40, '--receipt', str(receipt)]
            with patch('sys.argv', argv), patch.object(p, 'publish', side_effect=RuntimeError('Download failed: HTTP 415')):
                with self.assertRaisesRegex(RuntimeError, 'HTTP 415'):
                    p.main()
            data = json.loads(receipt.read_bytes())
            self.assertFalse(data['success'])
            self.assertEqual(data['publicDownloads'], [])
            self.assertEqual(data['error'], 'Download failed: HTTP 415')


if __name__ == '__main__':
    unittest.main(verbosity=2)
