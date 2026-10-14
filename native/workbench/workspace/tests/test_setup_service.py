"""Private setup RPC worker and shutdown lifecycle; no native execution claim."""
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from service import Workbench
from desktop_host import DesktopHost
from test_pack_service import Model


class Setup:
    def __init__(self):
        self.started = threading.Event()
        self.release = threading.Event()
        self.operation = {"active": False, "status": "idle"}
        self.revision = "initial"
        self.fail = False
    def prepare(self, action, request):
        self.operation.update(active=True, status="running", action=action, cancellable=True)
    def snapshot(self):
        return {"operation": dict(self.operation), "revision": self.revision, "rows": []}
    def run(self, cancel):
        self.started.set()
        while not self.release.wait(.01):
            if cancel.is_set():
                self.operation.update(active=False, status="cancelled")
                return
        if self.fail:
            raise OSError("Fixture state write failed")
        self.revision = "installed-one"
        self.operation.update(active=False, status="failed", message="Second pack failed; first installed")
    def cancel(self, event):
        event.set()
    def dismiss(self):
        self.operation["dismissed"] = True
    def host_failure(self, error):
        self.operation.update(active=False, status="failed", message=str(error))


class SetupServiceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.app = Workbench(self.root, catalog={"packs": [], "tools": {}})
        self.setup = Setup()
        self.app._setup_manager = self.setup
        self.model = Model()
        self.host = DesktopHost(self.root, app=self.app, model=self.model)
        self.host.dispatch("setup/status", {})
        self.model.updates = 0
    def tearDown(self):
        self.setup.release.set()
        self.host.close(grace=2)
        self.tmp.cleanup()
    def start(self):
        self.host.dispatch("setup/start", {"profile": "full"})
        self.assertTrue(self.setup.started.wait(2))
    def join(self):
        self.app._setup_worker.join(2)
        self.assertFalse(self.app._setup_worker.is_alive())
        return self.host.dispatch("setup/status", {})

    def test_background_setup_serializes_packs_references_and_analyses(self):
        self.start()
        for action in (lambda: self.app.ensure_editable(),
                       lambda: self.host.dispatch("packs/refresh", {}),
                       lambda: self.host.dispatch("setup/refresh", {})):
            with self.assertRaisesRegex(ValueError, "pack operation"):
                action()
        self.host.dispatch("setup/cancel", {})
        self.assertEqual(self.join()["operation"]["status"], "cancelled")
        self.app.ensure_editable()

    def test_partial_batch_refreshes_models_once_even_when_later_pack_fails(self):
        self.start()
        self.setup.release.set()
        result = self.join()
        self.assertEqual(result["operation"]["status"], "failed")
        self.assertIn("model", result)
        self.assertEqual(self.model.updates, 1)
        self.host.dispatch("setup/status", {})
        self.assertEqual(self.model.updates, 1)
        self.assertEqual(self.model.graph["name"], "Untitled")

    def test_shutdown_cancels_and_joins_setup_worker(self):
        self.start()
        self.assertTrue(self.host.close(grace=2))
        self.assertFalse(self.app._setup_worker.is_alive())
        self.assertEqual(self.setup.operation["status"], "cancelled")

    def test_state_write_failure_exposes_error_and_releases_busy_flag(self):
        self.setup.fail = True
        self.start()
        self.setup.release.set()
        result = self.join()
        self.assertIn("state write failed", result["operation"]["message"])
        self.app.ensure_editable()

    def test_catalogue_reload_failure_releases_busy_flag(self):
        self.start()
        with patch("service.load_catalog", side_effect=ValueError("Fixture catalogue invalid")):
            self.setup.release.set()
            result = self.join()
        self.assertEqual(result["operation"]["status"], "failed")
        self.assertIn("catalogue invalid", result["operation"]["message"])
        self.app.ensure_editable()

    def test_unknown_status_fields_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "Unknown tool setup request field"):
            self.host.dispatch("setup/status", {"refresh": True})
        with self.assertRaisesRegex(ValueError, "Unknown tool setup action"):
            self.host.dispatch("setup/arbitrary", {})

    def test_corrupt_optional_setup_state_does_not_prevent_app_initialization(self):
        (self.root / "user-data/tool-setup.json").write_text("invalid JSON")
        self.app.shutdown(grace=1)
        app = Workbench(self.root, catalog={"packs": [], "tools": {}})
        host = DesktopHost(self.root, app=app)
        try:
            self.assertIn("app_version", host.dispatch("init", {}))
            with self.assertRaises(ValueError):
                host.dispatch("setup/status", {})
            app.ensure_editable()
        finally:
            host.close(grace=2)


if __name__ == "__main__":
    unittest.main()
