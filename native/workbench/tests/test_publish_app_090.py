#!/usr/bin/env python3
"""Fail-closed controls for this one accepted release; no network or publishing."""
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

spec = importlib.util.spec_from_file_location("promotion", Path(__file__).resolve().parents[1] / "scripts/publish_app_090.py")
promotion = importlib.util.module_from_spec(spec)
spec.loader.exec_module(promotion)


class PromotionControls(unittest.TestCase):
    def test_wrong_repository_refuses_before_client_creation(self):
        with patch.dict(os.environ, {"GITHUB_REPOSITORY": "wrong/repo", "GITHUB_REF": "refs/heads/release/app-0.9.0"}), \
             patch.object(promotion, "GitHub") as client:
            with self.assertRaisesRegex(ValueError, "Wrong publication"):
                promotion.publish(types.SimpleNamespace())
            client.assert_not_called()

    def test_existing_tag_refuses_before_any_mutation(self):
        requests = []
        class Client:
            def __init__(self, token):
                pass
            def api(self, path, method="GET", **kwargs):
                requests.append((path, method))
                return {"ref": "refs/tags/" + promotion.TAG}
        with patch.dict(os.environ, {"GITHUB_REPOSITORY": promotion.REPOSITORY,
                                     "GITHUB_REF": "refs/heads/release/app-0.9.0", "GITHUB_SHA": promotion.SOURCE}), \
             patch.object(promotion, "GitHub", Client), patch.object(promotion, "update_lock"), \
             patch.object(promotion, "verify_source_identity"), patch.object(Path, "read_text", return_value="0.9.0 " + "notes " * 100):
            with self.assertRaisesRegex(ValueError, "already exists"):
                promotion.publish(types.SimpleNamespace(publish_sha=promotion.SOURCE))
        self.assertEqual(requests, [("/git/ref/tags/" + promotion.TAG, "GET")])

    def test_unpinned_updater_refuses_before_network(self):
        with patch.dict(os.environ, {"GITHUB_REPOSITORY": promotion.REPOSITORY,
                                     "GITHUB_REF": "refs/heads/release/app-0.9.0", "GITHUB_SHA": promotion.SOURCE}), \
             patch.object(promotion, "UPDATE", {"run": 0}), patch.object(promotion, "GitHub") as client:
            with self.assertRaisesRegex(ValueError, "no completed, pinned"):
                promotion.publish(types.SimpleNamespace(publish_sha=promotion.SOURCE))
            client.assert_not_called()

    def test_recorded_fixture_failure_reused_only_after_final_success(self):
        class Client:
            def __init__(self, bad_step=False):
                self.bad_step = bad_step
            def api(self, path):
                run = int(path.split('/')[3])
                initial = run == promotion.INITIAL_RUN
                if '/jobs' not in path:
                    return {'head_sha': promotion.SOURCE if initial else promotion.FINAL_VALIDATOR if run == promotion.FINAL_RUN else 'a' * 40,
                            'status': 'completed', 'conclusion': 'failure' if initial else 'success'}
                names = ['native (ordinary)', 'native (path with spaces)']
                if initial:
                    names += ['build', 'native-long-paths']
                elif run != promotion.FINAL_RUN:
                    names += ['build']
                jobs = []
                for number, name in enumerate(names):
                    failed = initial and name.startswith('native (')
                    steps = [{'name': 'ordinary step', 'conclusion': 'success'}]
                    if failed:
                        steps.append({'name': 'Verify CWL results, routed DAGs and native application icons', 'conclusion': 'failure'})
                    if self.bad_step and run == promotion.FINAL_RUN:
                        steps.append({'name': 'Unexpected skip', 'conclusion': 'skipped'})
                    jobs.append({'id': number, 'name': name, 'conclusion': 'failure' if failed else 'success', 'steps': steps})
                return {'total_count': len(jobs), 'jobs': jobs}
        with patch.object(promotion, 'update_lock'), patch.object(promotion, 'UPDATE', {'run': 987, 'commit': 'a' * 40}):
            result = promotion.verify_runs(Client())
            self.assertEqual([r['conclusion'] for r in result], ['failure', 'success', 'success'])
            with self.assertRaisesRegex(ValueError, 'failed or skipped'):
                promotion.verify_runs(Client(True))

    def test_application_change_after_candidate_refuses(self):
        with patch.object(promotion.subprocess, 'run'), \
             patch.object(promotion.subprocess, 'check_output', return_value='workspace/engine.py\n'):
            with self.assertRaisesRegex(ValueError, 'Application, build or pack code changed'):
                promotion.verify_source_identity(promotion.SOURCE)

    def test_validation_only_changes_are_allowed(self):
        with patch.object(promotion.subprocess, 'run'), \
             patch.object(promotion.subprocess, 'check_output', return_value='scripts/check_results_windows.py\nknowledge/current-state.md\n'):
            promotion.verify_source_identity(promotion.SOURCE)

    def test_unmerged_pr_refuses(self):
        class Client:
            def api(self, path):
                if path.startswith('/git/'):
                    return {'object': {'sha': promotion.SOURCE}}
                return {'merged': False, 'merge_commit_sha': None}
        with self.assertRaisesRegex(ValueError, 'not merged'):
            promotion.verify_merged(Client(), promotion.SOURCE)

    def test_final_gui_success_requires_exact_gate(self):
        report = {'success': True, 'nativeWindowsExecuted': True, 'passed': 9, 'skips': [],
                  'sourceCommit': promotion.SOURCE, 'assetSha256': promotion.STARTER_SHA,
                  'nativeGUIValidated': True, 'gateSha256': '0' * 64}
        with self.assertRaisesRegex(ValueError, 'Final native GUI'):
            promotion.check_report(report, 9, True)

    def test_missing_reference_cwl_or_changed_user_data_refuses(self):
        from copy import deepcopy
        report = {'success': True, 'nativeWindowsExecuted': True, 'nativeWindowsHost': True,
                  'passed': 13, 'skips': [], 'failures': [], 'sourceCommit': promotion.SOURCE,
                  'validationCommit': 'a' * 40, 'starterSha256': promotion.STARTER_SHA,
                  'baselineSha256': promotion.BASELINE_SHA, 'updateSha256': 'b' * 64,
                  'appVersion': '0.9.0', 'coreFilesVerified': 70,
                  'updateAttempts': {'install': {'status': 'installed'}, 'repeat': {'status': 'already-installed'}},
                  'preservation': {'files': 300, 'changes': {}, 'additions': {'user-data/session.lock': promotion.sha(b'\0')}},
                  'baselineReferenceRun': {'nativeWindowsExecuted': True, 'referenceSha256': 'c' * 64, 'contigs': 2, 'cwlChecked': False},
                  'updatedReferenceRun': {'nativeWindowsExecuted': True, 'referenceSha256': 'c' * 64, 'contigs': 2, 'cwlChecked': True},
                  'science': {'networkSocketOperationsDeniedForHost': True, 'nativeWindowsExecuted': True,
                              'outputsIndependentlyHashed': 20, 'nativeCommandsCompared': 18, 'cwlRunnerReplays': [0] * 5}}
        with patch.object(promotion, 'UPDATE', {'checks': 13, 'commit': 'a' * 40, 'archive': {'sha256': 'b' * 64}}):
            promotion.check_update_report(report)
            missing_cwl = deepcopy(report)
            missing_cwl['updatedReferenceRun']['cwlChecked'] = False
            with self.assertRaisesRegex(ValueError, 'reference provenance'):
                promotion.check_update_report(missing_cwl)
            changed_data = deepcopy(report)
            changed_data['preservation']['changes'] = {'user-data/saved.json': {'before': 'd', 'after': 'e'}}
            with self.assertRaisesRegex(ValueError, 'preserve existing user files'):
                promotion.check_update_report(changed_data)

    def test_public_404_retry_is_bounded(self):
        content = b'exact asset'
        canonical = f'https://github.com/{promotion.REPOSITORY}/releases/download/{promotion.TAG}/asset.txt'
        class Client:
            calls = 0
            def api(self, path):
                if path.startswith('/git/ref/'):
                    return {'object': {'sha': promotion.SOURCE}}
                return {'id': 12345, 'tag_name': promotion.TAG, 'draft': False, 'prerelease': True,
                        'html_url': 'https://github.com/example/release', 'assets': [{
                            'name': 'asset.txt', 'state': 'uploaded', 'size': len(content),
                            'digest': 'sha256:' + promotion.sha(content), 'browser_download_url': canonical}]}
            def download(self, *args):
                self.calls += 1
                raise RuntimeError('Download failed: HTTP 404')
        with tempfile.TemporaryDirectory() as temporary, patch.object(promotion.time, 'sleep') as sleep:
            asset = Path(temporary) / 'asset.txt'
            asset.write_bytes(content)
            client = Client()
            with self.assertRaisesRegex(RuntimeError, 'HTTP 404'):
                promotion.verify_public_downloads(client, 12345, [asset], promotion.SOURCE, Path(temporary) / 'receipt.json')
            self.assertEqual(client.calls, 5)
            self.assertEqual([call.args[0] for call in sleep.call_args_list], [2, 5, 10, 20])

    def test_different_packaged_identity_refuses(self):
        report = {"success": True, "nativeWindowsExecuted": True, "passed": 32, "skips": [],
                  "sourceCommit": promotion.SOURCE, "assetSha256": "0" * 64}
        with self.assertRaisesRegex(ValueError, "different application bytes"):
            promotion.check_report(report, 32)

    def test_zip_traversal_refuses(self):
        raw = io.BytesIO()
        with zipfile.ZipFile(raw, "w") as archive:
            archive.writestr("../escape", "untrusted")
        with self.assertRaisesRegex(ValueError, "Unsafe ZIP"):
            promotion.checked_zip(raw.getvalue())

    def test_api_redirect_refuses_without_forwarding_credentials(self):
        with patch.object(promotion.urllib.request, "build_opener") as opener, \
             patch.object(promotion.urllib.request, "urlopen") as default_open:
            opener.return_value.open.side_effect = urllib.error.HTTPError(
                "https://api.github.com/example", 302, "redirect", {"Location": "https://outside.invalid"}, None)
            with self.assertRaisesRegex(RuntimeError, "HTTP 302"):
                promotion.GitHub("dummy-token").api("/releases")
            opener.assert_called_once_with(promotion.NoRedirect)
            default_open.assert_not_called()

    def test_download_media_types_and_redirect_authentication(self):
        client = promotion.GitHub("dummy-token")
        content = b"pinned downloadable bytes"
        for endpoint, accept in [("/actions/artifacts/11408021439/zip", "application/vnd.github+json"),
                                 ("/releases/assets/123", "application/octet-stream")]:
            with self.subTest(endpoint=endpoint), tempfile.TemporaryDirectory() as temporary, \
                 patch.object(promotion.urllib.request, "build_opener") as opener:
                requests = []
                def open_request(request, timeout):
                    requests.append(request)
                    if len(requests) == 1:
                        raise urllib.error.HTTPError(request.full_url, 302, "redirect", {
                            "Location": "https://test.blob.core.windows.net/artifacts/pinned.zip?signature=synthetic"}, None)
                    return io.BytesIO(content)
                opener.return_value.open.side_effect = open_request
                destination = Path(temporary) / "download.zip"
                client.download(client.base + endpoint, destination, promotion.sha(content), len(content), True)
                self.assertEqual(destination.read_bytes(), content)
                self.assertEqual(len(requests), 2)
                self.assertEqual(requests[0].get_header("Accept"), accept)
                self.assertEqual(requests[0].get_header("Authorization"), "Bearer dummy-token")
                self.assertEqual(requests[1].get_header("Accept"), "application/octet-stream")
                self.assertIsNone(requests[1].get_header("Authorization"))

    def test_early_publication_failure_retains_diagnostic(self):
        with tempfile.TemporaryDirectory() as temporary:
            receipt = Path(temporary) / "receipt.json"
            argv = ["promotion", "--input-dir", temporary, "--output-dir", str(Path(temporary) / "assets"),
                    "--publish-sha", promotion.SOURCE, "--receipt", str(receipt)]
            with patch("sys.argv", argv), patch.object(promotion, "publish", side_effect=RuntimeError("Download failed: HTTP 415")):
                with self.assertRaisesRegex(RuntimeError, "HTTP 415"):
                    promotion.main()
            report = json.loads(receipt.read_bytes())
            self.assertFalse(report["success"])
            self.assertEqual(report["publicDownloads"], [])
            self.assertEqual(report["error"], "Download failed: HTTP 415")

    def test_read_only_client_rejects_mutations_before_request(self):
        with patch.object(promotion.GitHub, "api") as request:
            for method in ["POST", "PATCH", "DELETE"]:
                with self.subTest(method=method), self.assertRaisesRegex(ValueError, "GET requests only"):
                    promotion.ReadOnlyGitHub("dummy-token").api("/releases", method)
            request.assert_not_called()

    def test_public_verification_refreshes_metadata_and_retries_anonymous_404(self):
        content = b"exact public asset"
        canonical = f"https://github.com/{promotion.REPOSITORY}/releases/download/{promotion.TAG}/asset.txt"
        requests, downloads = [], []
        class Client:
            def api(self, path, method="GET"):
                requests.append((path, method))
                if path.startswith("/git/ref/"):
                    return {"object": {"sha": promotion.SOURCE}}
                return {"id": 12345, "tag_name": promotion.TAG, "draft": False,
                        "prerelease": True, "html_url": "https://github.com/example/release", "assets": [
                            {"name": "asset.txt", "state": "uploaded", "size": len(content),
                             "digest": "sha256:" + promotion.sha(content), "browser_download_url": canonical}]}
            def download(self, url, path, digest, size, authenticated=False):
                downloads.append((url, authenticated))
                if len(downloads) == 1:
                    raise RuntimeError("Download failed: HTTP 404")
                assert digest == promotion.sha(content) and size == len(content)
                path.write_bytes(content)
        with tempfile.TemporaryDirectory() as temporary, patch.object(promotion.time, "sleep") as sleep:
            asset = Path(temporary) / "asset.txt"
            asset.write_bytes(content)
            receipt = Path(temporary) / "receipt.json"
            result = promotion.verify_public_downloads(Client(), 12345, [asset],
                                                        promotion.SOURCE, receipt, True)
            self.assertTrue(result["success"])
            self.assertTrue(result["verificationOnly"])
            self.assertEqual(len(result["publicDownloads"]), 1)
            self.assertEqual(requests[0], (f"/releases/{12345}", "GET"))
            self.assertTrue(all(method == "GET" for _, method in requests))
            self.assertEqual(downloads, [(canonical, False), (canonical, False)])
            sleep.assert_called_once_with(2)

    def test_public_verification_rejects_temporary_draft_url(self):
        content = b"exact public asset"
        class Client:
            def api(self, path):
                if path.startswith("/git/ref/"):
                    return {"object": {"sha": promotion.SOURCE}}
                return {"id": 12345, "tag_name": promotion.TAG, "draft": False,
                        "prerelease": True, "html_url": "https://github.com/example/release", "assets": [
                            {"name": "asset.txt", "state": "uploaded", "size": len(content),
                             "digest": "sha256:" + promotion.sha(content),
                             "browser_download_url": "https://github.com/example/releases/download/untagged-test/asset.txt"}]}
            def download(self, *args):
                raise AssertionError("Must not download an unexpected URL")
        with tempfile.TemporaryDirectory() as temporary:
            asset = Path(temporary) / "asset.txt"
            asset.write_bytes(content)
            with self.assertRaisesRegex(ValueError, "canonical URL differs"):
                promotion.verify_public_downloads(Client(), 12345, [asset],
                    promotion.SOURCE, Path(temporary) / "receipt.json", True)


if __name__ == "__main__":
    unittest.main(verbosity=2)
