#!/usr/bin/env python3
"""Network-free refusal, evidence-binding and immutable publication tests."""
import copy
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import types
import unittest
from unittest.mock import Mock, patch
import warnings
import zipfile

spec = importlib.util.spec_from_file_location('publisher0160', Path(__file__).resolve().parents[1] / 'scripts/publish_app_0160.py')
p = importlib.util.module_from_spec(spec)
spec.loader.exec_module(p)


def valid_lock():
    """Synthetic lock with real immutable app identities and fake CI identities."""
    updater = 'b' * 40
    regression = 'c' * 40
    lock = {'schema': 1, 'sourceCommit': p.SOURCE, 'prNumber': 12, 'featureBranch': 'release/update-app-0.16.0',
            'coreFiles': p.CORE_FILES, 'updaterSourceCommit': updater,
            'authorization': {'authorized': True, 'message': 'Great lets do a new release at this point', 'date': '2026-10-09'},
            'archives': {**copy.deepcopy(p.FROZEN_ARCHIVES), p.UPDATE: {'bytes': 100, 'sha256': 'a' * 64}},
            'runs': {}, 'artifacts': {}, 'reports': {}}
    for index, (key, commit, path) in enumerate((
        ('candidate', p.SOURCE, '.github/workflows/native-curated-candidate.yml'),
        ('updater', updater, '.github/workflows/native-update-0.16.0.yml'),
        ('regressions', regression, '.github/workflows/native-curated-release-check.yml')), 1):
        lock['runs'][key] = {'id': p.CANDIDATE_RUN if key == 'candidate' else index,
            'sourceCommit': commit, 'path': path, 'conclusion': 'success',
            'jobs': [{'id': index, 'name': 'test', 'conclusion': 'success', 'nonSuccessSteps': []}]}
    roles = {'candidate': 'candidate', 'native-ordinary': 'candidate', 'native-spaces': 'candidate',
             'updater': 'updater', 'update-ordinary': 'updater', 'update-spaces': 'updater',
             'regressions-ordinary': 'regressions', 'regressions-spaces': 'regressions', 'long-paths': 'regressions'}
    for index, (key, run) in enumerate(roles.items(), 100):
        lock['artifacts'][key] = {'id': p.CANDIDATE_ARTIFACT['id'] if key == 'candidate' else index, 'run': run,
            'bytes': p.CANDIDATE_ARTIFACT['bytes'] if key == 'candidate' else 100,
            'sha256': p.CANDIDATE_ARTIFACT['sha256'] if key == 'candidate' else 'a' * 64,
            'name': key, 'file': key + '.zip'}
    for case in ('ordinary', 'spaces'):
        for kind, passed in p.REPORT_COUNTS.items():
            run = 'updater' if kind == 'update' else 'regressions' if kind in ('results', 'scroll') else 'candidate'
            artifact = ('update-' if run == 'updater' else 'regressions-' if run == 'regressions' else 'native-') + case
            lock['reports'][case + '-' + kind] = {'case': case, 'kind': kind, 'artifact': artifact,
                'path': kind + '/report.json', 'sha256': 'a' * 64, 'passed': passed, 'skips': [],
                'sourceCommit': p.SOURCE, 'validatorCommit': lock['runs'][run]['sourceCommit'],
                'gateCommit': lock['runs'][run]['sourceCommit'], 'gate': p.REPORT_GATES[kind]}
    lock['reports']['long-paths'] = {'case': 'long-paths', 'kind': 'long-paths', 'artifact': 'long-paths',
        'path': 'native-long-paths.json', 'sha256': 'a' * 64, 'passed': p.LONG_PATH_CHECKS, 'skips': [],
        'sourceCommit': p.SOURCE, 'validatorCommit': regression, 'gateCommit': regression,
        'gate': p.REPORT_GATES['long-paths']}
    return lock


def zip_bytes(members):
    raw = io.BytesIO()
    with zipfile.ZipFile(raw, 'w') as archive:
        for name, value in members:
            archive.writestr(name, value)
    return raw.getvalue()


class PromotionGuards(unittest.TestCase):
    def test_complete_lock_and_missing_or_changed_frozen_identities(self):
        value = valid_lock()
        with patch.object(p, 'LOCK_PATH', Mock(read_bytes=lambda: json.dumps(value).encode())):
            self.assertEqual(p.acceptance_lock(), value)
        mutations = (
            lambda v: v.update(sourceCommit='0' * 40),
            lambda v: v['archives'][p.STARTER].update(sha256='0' * 64),
            lambda v: v['archives'].pop(p.ALIGN),
            lambda v: v['artifacts']['candidate'].update(id=p.CANDIDATE_ARTIFACT['id'] + 1),
            lambda v: v['artifacts']['candidate'].update(sha256='0' * 64),
            lambda v: v['reports'].pop('ordinary-curated'),
            lambda v: v['reports']['spaces-curated'].update(artifact='native-ordinary'),
            lambda v: v['reports']['ordinary-update'].update(passed=0),
            lambda v: v['reports']['ordinary-results'].update(gate='scripts/other.py'),
            lambda v: v['reports']['ordinary-scroll'].update(gateCommit=p.SOURCE),
            lambda v: v['reports']['long-paths'].update(gateCommit=p.SOURCE),
            lambda v: v['reports']['ordinary-workspace'].update(skips=['GUI unavailable']),
            lambda v: v['artifacts']['native-ordinary'].update(id=v['artifacts']['candidate']['id']),
            lambda v: v['authorization'].update(authorized=False),
            lambda v: v['runs']['regressions']['jobs'][0].update(nonSuccessSteps=[{'conclusion': 'skipped'}]),
        )
        for mutate in mutations:
            value = valid_lock(); mutate(value)
            with self.subTest(mutation=mutate), patch.object(p, 'LOCK_PATH', Mock(read_bytes=lambda: json.dumps(value).encode())):
                with self.assertRaises(ValueError): p.acceptance_lock()

    def test_read_only_client_refuses_all_remote_writes_before_network(self):
        client = p.ReadOnlyGitHub('fixture-token')
        with patch.object(p.GitHub, 'api') as network:
            for method in ('POST', 'PATCH', 'DELETE', 'PUT'):
                with self.assertRaises(ValueError): client.api('/releases', method, {})
            with self.assertRaises(ValueError): client.api('/releases', data={})
            network.assert_not_called()

    def test_unsafe_zip_names_duplicates_and_wrong_checksum_inventory(self):
        with warnings.catch_warnings():
            warnings.simplefilter('ignore', UserWarning)
            for names in (['../escape'], ['/absolute'], ['C:/drive'], ['back\\slash'], ['same', 'same']):
                with self.subTest(names=names), self.assertRaises(ValueError):
                    p.checked_zip(zip_bytes([(name, b'fixture') for name in names]))
        raw = b'fixture'; good = (p.sha(raw) + '  asset.zip\n').encode()
        p.checksums(good, {'asset.zip'}, lambda _: raw)
        for value in (good + good, good.replace(b'asset.zip', b'other.zip'), good.replace(p.sha(raw).encode(), b'0' * 64)):
            with self.assertRaises(ValueError): p.checksums(value, {'asset.zip'}, lambda _: raw)

    def test_candidate_artifact_cannot_omit_independent_pack_or_substitute_content(self):
        raw = zip_bytes([(p.STARTER, b'not-an-archive')])
        with self.assertRaisesRegex(ValueError, 'Candidate inventory'):
            p.verify_candidate({'candidate': raw}, valid_lock())

    def test_application_change_after_frozen_candidate_is_rejected(self):
        with patch.object(p.subprocess, 'run'), patch.object(p.subprocess, 'check_output', return_value='workspace/service.py\n'):
            with self.assertRaisesRegex(ValueError, 'Application/build/pack code changed'):
                p.verify_source_identity('d' * 40, valid_lock())

    def test_updater_source_must_match_its_successful_locked_commit(self):
        with patch.object(p.subprocess, 'run'), patch.object(p.subprocess, 'check_output', return_value='scripts/build_update_0160.py\n'), \
                patch.object(p, 'source_bytes', side_effect=[b'changed', b'accepted']):
            with self.assertRaisesRegex(ValueError, 'Validated helper'):
                p.verify_source_identity('d' * 40, valid_lock())

    def test_publication_requires_exact_main_and_actual_locked_merged_pr(self):
        client = Mock()
        client.api.side_effect = [{'object': {'sha': 'd' * 40}}, {'merged': True, 'merge_commit_sha': 'd' * 40,
            'base': {'ref': 'main'}, 'head': {'ref': 'release/update-app-0.16.0'}}]
        p.verify_merged(client, 'd' * 40, valid_lock())
        self.assertEqual(client.api.call_args_list[1].args[0], '/pulls/12')
        for pr in ({'merged': False}, {'merged': True, 'merge_commit_sha': 'c' * 40}):
            client.api.side_effect = [{'object': {'sha': 'd' * 40}}, pr]
            with self.assertRaises(ValueError): p.verify_merged(client, 'd' * 40, valid_lock())

    def test_release_regression_helpers_must_match_the_successful_run(self):
        published = 'd' * 40
        helpers = ('scripts/check_scroll_frames_0160_windows.py', 'scripts/check_long_paths_0160_windows.py')
        for helper in helpers:
            def source(path, commit):
                return b'changed' if path == helper and commit == published else b'accepted'
            with self.subTest(helper=helper), patch.object(p.subprocess, 'run'), \
                    patch.object(p.subprocess, 'check_output', return_value=helper + '\n'), \
                    patch.object(p, 'source_bytes', side_effect=source):
                with self.assertRaisesRegex(ValueError, 'Validated helper'):
                    p.verify_source_identity(published, valid_lock())

    def test_wrong_branch_stops_before_network_and_existing_tag_is_never_replaced(self):
        args = types.SimpleNamespace(publish_sha='d' * 40)
        with patch.dict(p.os.environ, {'GITHUB_REPOSITORY': p.REPOSITORY, 'GITHUB_REF': 'refs/heads/main', 'GITHUB_SHA': args.publish_sha}, clear=True), \
                patch.object(p, 'GitHub') as network:
            with self.assertRaises(ValueError): p.publish(args)
            network.assert_not_called()
        client = Mock(); client.api.return_value = {'object': {'sha': 'a' * 40}}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); (root / 'docs/releases').mkdir(parents=True)
            (root / 'docs/releases/0.16.0.md').write_text('0.16.0 ' + 'release ' * 40)
            with patch.dict(p.os.environ, {'GITHUB_REPOSITORY': p.REPOSITORY, 'GITHUB_REF': 'refs/heads/' + p.BRANCH,
                'GITHUB_SHA': args.publish_sha}, clear=True), patch.object(p, 'ROOT', root), \
                patch.object(p, 'acceptance_lock', return_value=valid_lock()), patch.object(p, 'verify_source_identity'), \
                patch.object(p, 'GitHub', return_value=client), patch.object(p, 'download_artifacts') as downloads:
                with self.assertRaisesRegex(ValueError, 'refusing replacement'): p.publish(args)
                downloads.assert_not_called()
                self.assertTrue(all(call.args[1:] == () for call in client.api.call_args_list))

    def test_required_native_report_cannot_hide_skip_or_wrong_archive(self):
        lock = valid_lock(); spec = lock['reports']['ordinary-curated']
        base = {'success': True, 'nativeWindowsExecuted': True, 'passed': 11, 'failed': 0, 'skips': [],
                'sourceCommit': p.SOURCE, 'gateSha256': p.sha(b'gate'), 'assetSha256': p.FROZEN_ARCHIVES[p.STARTER]['sha256']}
        for change in ({}, {'skips': ['Unavailable GUI']}, {'nativeWindowsExecuted': False}, {'assetSha256': '0' * 64}):
            report = {**base, **change}; raw = json.dumps(report).encode(); bound = {**spec, 'sha256': p.sha(raw)}
            with patch.object(p, 'source_bytes', return_value=b'gate'):
                if not change: self.assertEqual(p.check_report(raw, bound, {}, lock), report)
                else:
                    with self.assertRaises(ValueError): p.check_report(raw, bound, {}, lock)

    def test_failed_preparation_stops_before_creating_any_tag_release_or_asset(self):
        args = types.SimpleNamespace(publish_sha='d' * 40, input_dir=Path('inputs'), output_dir=Path('outputs'))
        client = Mock(); client.api.return_value = None
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); (root / 'docs/releases').mkdir(parents=True)
            (root / 'docs/releases/0.16.0.md').write_text('0.16.0 ' + 'release ' * 40)
            with patch.dict(p.os.environ, {'GITHUB_REPOSITORY': p.REPOSITORY, 'GITHUB_REF': 'refs/heads/' + p.BRANCH,
                'GITHUB_SHA': args.publish_sha}, clear=True), patch.object(p, 'ROOT', root), \
                patch.object(p, 'acceptance_lock', return_value=valid_lock()), patch.object(p, 'verify_source_identity'), \
                patch.object(p, 'verify_merged'), patch.object(p, 'verify_runs', return_value={}), \
                patch.object(p, 'download_artifacts'), patch.object(p, 'GitHub', return_value=client), \
                patch.object(p, 'prepare', side_effect=ValueError('Native report identity differs')):
                with self.assertRaisesRegex(ValueError, 'Native report identity'): p.publish(args)
                self.assertTrue(all(call.args[1:] == () for call in client.api.call_args_list))

    def test_long_path_gate_requires_additional_pack_truth_and_bounded_child_directory(self):
        lock = valid_lock(); spec = lock['reports']['long-paths']
        base = {'success': True, 'nativeWindowsExecuted': True, 'passed': p.LONG_PATH_CHECKS,
                'failed': 0, 'skips': [], 'sourceCommit': p.SOURCE, 'gateSha256': p.sha(b'gate'),
                'assetSha256': p.FROZEN_ARCHIVES[p.STARTER]['sha256'],
                'longPathsEnabled': 0, 'expectedApplicationFailure': False,
                'policyProbe': {'ordinaryIsFile': False, 'extendedIsFile': True},
                'applicationCheck': {'status': 'completed', 'corePassed': 7, 'starterPassed': 1, 'starterFailed': 0},
                'additionalAlignment': {'checkId': 'align/paired-mapping-known-answer@0.4.1',
                    'pin': {'packId': 'align', 'packVersion': '0.4.1', 'manifestSha256': p.ALIGN_MANIFEST},
                    'nativeWorkingDirectoryCharacters': 254, 'samCharacters': 263,
                    'alignmentRecords': 202, 'mappedProperPairs': 202,
                    'graphRecordSha256': 'a' * 64, 'samSha256': 'b' * 64},
                'additionalPackDiagnostics': {'errors': []}}
        mutations = (None, lambda r: r.pop('additionalAlignment'), lambda r: r.pop('gateSha256'),
            lambda r: r['additionalAlignment'].update(nativeWorkingDirectoryCharacters=291),
            lambda r: r['additionalAlignment'].update(mappedProperPairs=0),
            lambda r: r['additionalAlignment']['pin'].update(packVersion='0.4.0'),
            lambda r: r['additionalPackDiagnostics'].update(errors=['Missing diagnostic']),
            lambda r: r.update(expectedApplicationFailure=True))
        for mutate in mutations:
            report = copy.deepcopy(base)
            if mutate: mutate(report)
            raw = json.dumps(report).encode(); bound = {**spec, 'sha256': p.sha(raw)}
            with self.subTest(mutation=mutate), patch.object(p, 'source_bytes', return_value=b'gate'):
                if mutate:
                    with self.assertRaises(ValueError): p.check_report(raw, bound, {}, lock)
                else:
                    self.assertEqual(p.check_report(raw, bound, {}, lock), report)

    def test_update_kind_requires_update_evidence_even_when_identity_fields_are_missing(self):
        lock = valid_lock(); spec = lock['reports']['ordinary-update']
        base = {'success': True, 'nativeWindowsExecuted': True, 'passed': spec['passed'],
                'failed': 0, 'skips': [], 'sourceCommit': p.SOURCE,
                'gateSha256': p.sha(b'gate'), 'assetSha256': p.FROZEN_ARCHIVES[p.STARTER]['sha256']}
        identities = {'nativeWindowsHost': True, 'baseVersion': '0.11.0', 'appVersion': p.VERSION,
                      'coreFilesVerified': p.CORE_FILES, 'starterSha256': lock['archives'][p.STARTER]['sha256'],
                      'updateSha256': lock['archives'][p.UPDATE]['sha256'], 'baselineSha256': p.BASELINE_SHA}
        cases = [('generic native report', base)]
        for field in ('starterSha256', 'updateSha256', 'baselineSha256'):
            report = {**base, **identities}; report.pop(field)
            cases.append(('missing ' + field, report))
        for label, report in cases:
            raw = json.dumps(report).encode(); bound = {**spec, 'sha256': p.sha(raw)}
            with self.subTest(report=label), patch.object(p, 'source_bytes', return_value=b'gate'):
                with self.assertRaisesRegex(ValueError, 'Native update identities differ'):
                    p.check_report(raw, bound, {}, lock)

    def test_performance_schema_is_bound_without_invented_success_or_gate_fields(self):
        lock = valid_lock(); spec = lock['reports']['ordinary-performance']
        report = {'native_windows_execution': True, 'passed': 14, 'failed': 0, 'skipped': 0, 'error': None}
        raw = json.dumps(report).encode(); spec['sha256'] = p.sha(raw)
        self.assertEqual(p.check_report(raw, spec, {}, lock), report)
        report['skipped'] = 1; raw = json.dumps(report).encode(); spec['sha256'] = p.sha(raw)
        with self.assertRaises(ValueError): p.check_report(raw, spec, {}, lock)

    def test_failed_or_skipped_ci_job_cannot_be_accepted_even_with_locked_inventory(self):
        lock = valid_lock(); entry = lock['runs']['candidate']
        run = {'head_sha': p.SOURCE, 'status': 'completed', 'conclusion': 'success', 'path': entry['path']}
        job = {'id': 1, 'name': 'test', 'conclusion': 'success', 'steps': [{'name': 'required', 'conclusion': 'skipped'}]}
        entry['jobs'][0]['nonSuccessSteps'] = [{'name': 'required', 'conclusion': 'skipped'}]
        client = Mock(); client.api.side_effect = [run, {'total_count': 1, 'jobs': [job]}]
        with self.assertRaisesRegex(ValueError, 'failed/skipped step'): p.verify_runs(client, lock)

    def test_release_has_thirteen_assets_and_keeps_test_helper_in_evidence_only(self):
        self.assertEqual(len(p.ASSET_NAMES), 13)
        self.assertTrue({p.STARTER, p.SOURCES, p.UPDATE, p.ALIGN, 'align-0.4.1-metadata.json'} <= p.ASSET_NAMES)
        self.assertNotIn('WindowsPerformanceChecks.exe', p.ASSET_NAMES)


if __name__ == '__main__':
    unittest.main(verbosity=2)
