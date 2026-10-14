"""Readiness/diagnostic transport checks; no native Windows claim."""
from pathlib import Path
import json
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from desktop_host import DesktopHost
from service import Workbench


class ReviewEngine:
    def review(self, graph):
        return {"valid": True, "ok": True, "issues": [], "methods": graph["name"], "order": []}


class Model:
    graph = {"name": "PRIVATE_SAMPLE_CANARY", "nodes": [], "sources": []}


class ReadinessServiceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="PRIVATE_PATH_CANARY-")
        self.root = Path(self.tmp.name)
        self.app = Workbench(self.root, engine=ReviewEngine(), catalog={"tools": {}})
        self.host = DesktopHost(self.root, app=self.app, model=Model())

    def tearDown(self):
        self.host.close(grace=.1)
        self.tmp.cleanup()

    def test_review_preserves_methods_but_missing_or_invalid_destination_is_honest(self):
        result = self.host.dispatch("review", {})
        self.assertEqual(result["methods"], "PRIVATE_SAMPLE_CANARY")
        self.assertEqual(result["readiness"]["status"], "incomplete")
        result = self.host.dispatch("review", {"output_folder": str(self.root / "absent")})
        self.assertFalse(result["valid"])
        self.assertEqual(result["readiness"]["status"], "blocked")
        self.assertFalse((self.root / "absent").exists())

    def test_preview_is_immutable_private_and_export_is_explicit(self):
        self.host.dispatch("review", {"output_folder": str(self.root)})
        preview = self.host.dispatch("diagnostics/review", {})
        self.assertEqual(list(self.root.glob("*.zip")), [])
        for secret in (str(self.root), "PRIVATE_PATH_CANARY", "PRIVATE_SAMPLE_CANARY"):
            self.assertNotIn(secret, preview["preview"])
        self.app._last_readiness = {"status": "blocked", "checks": [{"status": "failed"}]}
        self.app.catalog["private"] = "PRIVATE_SAMPLE_CANARY"
        saved = self.host.dispatch("diagnostics/save", {"token": preview["token"], "output_folder": str(self.root)})
        self.assertFalse(saved["uploaded"])
        with zipfile.ZipFile(saved["path"]) as archive:
            self.assertEqual(archive.read("report.json"), preview["preview"].encode("utf-8"))
            self.assertEqual(set(archive.namelist()), {"report.json", "README.txt", "SHA256SUMS.txt"})
        with self.assertRaises(ValueError):
            self.app.save_diagnostics(preview["token"], str(self.root))

    def test_unknown_expired_and_injected_reports_cannot_be_exported(self):
        with self.assertRaises(ValueError):
            self.app.save_diagnostics("not-a-reviewed-token", str(self.root))
        with patch("service.time.monotonic", return_value=10):
            preview = self.app.review_diagnostics()
        with patch("service.time.monotonic", return_value=911):
            with self.assertRaises(ValueError):
                self.app.save_diagnostics(preview["token"], str(self.root))
        for method, params in (("diagnostics/review", {"report": {}}),
                               ("diagnostics/save", {"token": "x", "output_folder": str(self.root), "report": {}}),
                               ("review", {"unknown": True})):
            with self.assertRaises(ValueError):
                self.host.dispatch(method, params)
        self.assertEqual(list(self.root.glob("*.zip")), [])

    def test_failed_export_can_be_retried_without_replacing_existing_files(self):
        existing = self.root / "keep.txt"
        existing.write_text("unchanged")
        preview = self.app.review_diagnostics()
        with self.assertRaises((ValueError, OSError)):
            self.app.save_diagnostics(preview["token"], str(self.root / "absent"))
        self.app.save_diagnostics(preview["token"], str(self.root))
        self.assertEqual(existing.read_text(), "unchanged")

    def test_historical_run_does_not_inherit_unrelated_workspace_readiness(self):
        self.app.runs["private-run"] = {"run_id": "private-run", "status": "completed",
                                      "events": [], "folder": str(self.root), "nodes": []}
        self.app._last_readiness = {"status": "blocked", "checks": [{"status": "failed"}]}
        preview = self.app.review_diagnostics("private-run")
        report = json.loads(preview["preview"])
        self.assertNotIn("private-run", preview["preview"])
        self.assertIsNone(report["readiness"])
        self.assertEqual(report["run"]["status"], "completed")
        with self.assertRaises(ValueError):
            self.app.review_diagnostics("unknown-run")

    def test_slow_export_reserves_token_without_blocking_run_lock(self):
        preview = self.app.review_diagnostics()
        entered, finish, observed = threading.Event(), threading.Event(), threading.Event()
        errors = []
        def export(*args):
            entered.set()
            if not finish.wait(5):
                raise RuntimeError("Test did not release export")
            return self.root / "fixture.zip"
        def save():
            try:
                self.app.save_diagnostics(preview["token"], str(self.root))
            except Exception as exc:
                errors.append(exc)
        def observe():
            self.app.activity()
            observed.set()
        with patch("diagnostics.export_report", side_effect=export):
            worker = threading.Thread(target=save)
            worker.start()
            try:
                self.assertTrue(entered.wait(2))
                observer = threading.Thread(target=observe)
                observer.start()
                self.assertTrue(observed.wait(2), "Diagnostic I/O held the run lock")
                with self.assertRaises(ValueError):
                    self.app.save_diagnostics(preview["token"], str(self.root))
            finally:
                finish.set()
                worker.join(5)
                observer.join(5)
        self.assertEqual(errors, [])


if __name__ == "__main__":
    unittest.main()
