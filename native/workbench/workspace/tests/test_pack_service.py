"""Private native RPC lifecycle tests; no Windows execution is implied."""
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from service import Workbench
from desktop_host import DesktopHost


class Model:
    def __init__(self):
        self.graph = {"nodes": [], "sources": [], "name": "Untitled"}
        self.updates = 0
    def snapshot(self):
        return {"graph": self.graph}
    def update_catalog(self, catalog):
        self.updates += 1


class Manager:
    def __init__(self):
        self.started = threading.Event()
        self.release = threading.Event()
        self.calls = []
        self.fail = False
    def snapshot(self, refresh=False, **kwargs):
        return {"packs": [], "sources": [], "notice": "Offline"}
    def add_source(self, path):
        self.calls.append(("source", path))
        return {"success": True}
    def install(self, source, pack, version, cancel, event):
        self.calls.append((source, pack, version))
        self.started.set()
        event({"bytes": 1, "total": 10, "message": "Downloading"})
        while not self.release.wait(.01):
            if cancel.is_set():
                raise InterruptedError("Cancelled download")
        if self.fail:
            raise ValueError("Checksum mismatch")
        return {"success": True}
    def import_archive(self, path, cancel, event):
        return self.install("offline", str(path), "1.0.0", cancel, event)


class PackServiceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.app = Workbench(self.root, catalog={"tools": {}, "packs": []})
        self.manager = Manager()
        self.app._pack_manager = self.manager
        self.model = Model()
        self.host = DesktopHost(self.root, app=self.app, model=self.model)
    def tearDown(self):
        self.manager.release.set()
        self.host.close(grace=2)
        self.tmp.cleanup()
    def start(self):
        result = self.host.dispatch("packs/install", {"source_id": "approved", "pack_id": "fixture", "version": "1.0.0"})
        self.assertTrue(self.manager.started.wait(2))
        return result
    def join(self):
        self.app._pack_worker.join(2)
        self.assertFalse(self.app._pack_worker.is_alive())
        return self.host.dispatch("packs/status", {})
    def test_install_runs_in_background_and_serializes_workspace_changes(self):
        self.start()
        status = self.host.dispatch("packs/status", {})
        self.assertTrue(status["operation"]["active"])
        self.assertEqual(status["operation"]["bytes"], 1)
        with self.assertRaisesRegex(ValueError, "pack operation"):
            self.app.ensure_editable()
        with self.assertRaisesRegex(ValueError, "pack operation"):
            self.host.dispatch("packs/refresh", {})
        self.host.dispatch("packs/cancel", {})
        self.assertEqual(self.join()["operation"]["status"], "cancelled")
        self.assertEqual(self.model.updates, 0)
        self.app.ensure_editable()
    def test_success_reloads_model_once_without_editing_saved_graph(self):
        self.start()
        self.manager.release.set()
        result = self.join()
        self.assertEqual(result["operation"]["status"], "completed")
        self.assertIn("model", result)
        self.assertEqual(self.model.updates, 1)
        self.host.dispatch("packs/status", {})
        self.assertEqual(self.model.updates, 1)
        self.assertEqual(self.model.graph["name"], "Untitled")
    def test_failed_checksum_does_not_report_completion_or_reload_model(self):
        self.manager.fail = True
        self.start()
        self.manager.release.set()
        result = self.join()
        self.assertEqual(result["operation"]["status"], "failed")
        self.assertIn("Checksum", result["operation"]["message"])
        self.assertEqual(self.model.updates, 0)
        self.app.ensure_editable()
    def test_shutdown_cancels_and_joins_download(self):
        self.start()
        self.assertTrue(self.host.close(grace=2))
        self.assertFalse(self.app._pack_worker.is_alive())
        self.assertEqual(self.app._pack_operation["status"], "cancelled")
    def test_pack_changes_rejected_while_analysis_is_running(self):
        self.app.runs["running"] = {"run_id": "running", "status": "running"}
        try:
            with self.assertRaisesRegex(ValueError, "active analysis"):
                self.host.dispatch("packs/source", {"path": "source.json"})
            self.assertFalse(self.manager.calls)
        finally:
            self.app.runs.clear()
    def test_python_metadata_validation_precedes_native_publication(self):
        source = self.root / "bad"
        source.mkdir()
        (source / "pack.ini").write_text("invalid")
        with patch.object(self.app, "bridge") as bridge:
            with self.assertRaises(ValueError):
                self.app.import_pack({"source": str(source)})
            bridge.assert_not_called()
        self.app.ensure_editable()


if __name__ == "__main__":
    unittest.main()
