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

spec = importlib.util.spec_from_file_location("promotion", Path(__file__).resolve().parents[1] / "scripts/publish_app_080.py")
promotion = importlib.util.module_from_spec(spec)
spec.loader.exec_module(promotion)


class PromotionControls(unittest.TestCase):
    def test_wrong_repository_refuses_before_client_creation(self):
        with patch.dict(os.environ, {"GITHUB_REPOSITORY": "wrong/repo", "GITHUB_REF": "refs/heads/release/app-0.8.0"}), \
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
                                     "GITHUB_REF": "refs/heads/release/app-0.8.0", "GITHUB_SHA": promotion.SOURCE}), \
             patch.object(promotion, "GitHub", Client), patch.object(Path, "read_text", return_value="0.8.0 " + "notes " * 100):
            with self.assertRaisesRegex(ValueError, "already exists"):
                promotion.publish(types.SimpleNamespace(publish_sha=promotion.SOURCE))
        self.assertEqual(requests, [("/git/ref/tags/" + promotion.TAG, "GET")])

    def test_skipped_job_step_refuses(self):
        class Client:
            def api(self, path):
                if "/jobs" not in path:
                    return {"head_sha": promotion.SOURCE, "status": "completed", "conclusion": "success"}
                return {"total_count": 5, "jobs": [{"name": name, "conclusion": "success", "steps": [
                    {"conclusion": "skipped" if name == "native-scroll-frames" else "success"}]} for name in promotion.JOBS]}
        with self.assertRaisesRegex(ValueError, "failed or skipped"):
            promotion.verify_run(Client())

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
                    return {"object": {"sha": promotion.PUBLISHED_COMMIT}}
                return {"id": promotion.PUBLISHED_RELEASE, "tag_name": promotion.TAG, "draft": False,
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
            result = promotion.verify_public_downloads(Client(), promotion.PUBLISHED_RELEASE, [asset],
                                                        promotion.PUBLISHED_COMMIT, receipt, True)
            self.assertTrue(result["success"])
            self.assertTrue(result["verificationOnly"])
            self.assertEqual(len(result["publicDownloads"]), 1)
            self.assertEqual(requests[0], (f"/releases/{promotion.PUBLISHED_RELEASE}", "GET"))
            self.assertTrue(all(method == "GET" for _, method in requests))
            self.assertEqual(downloads, [(canonical, False), (canonical, False)])
            sleep.assert_called_once_with(2)

    def test_public_verification_rejects_temporary_draft_url(self):
        content = b"exact public asset"
        class Client:
            def api(self, path):
                if path.startswith("/git/ref/"):
                    return {"object": {"sha": promotion.PUBLISHED_COMMIT}}
                return {"id": promotion.PUBLISHED_RELEASE, "tag_name": promotion.TAG, "draft": False,
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
                promotion.verify_public_downloads(Client(), promotion.PUBLISHED_RELEASE, [asset],
                    promotion.PUBLISHED_COMMIT, Path(temporary) / "receipt.json", True)


if __name__ == "__main__":
    unittest.main(verbosity=2)
