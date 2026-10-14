"""Source-only opt-in setup, signed selection, resume and preservation checks."""
import copy
import importlib.util
import json
from pathlib import Path
import shutil
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "workspace"))
spec = importlib.util.spec_from_file_location("setup_pack_fixtures", ROOT / "tests" / "test_pack_manager.py")
fixture = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixture)
import pack_manager as pm
from setup_manager import SetupManager, OFFICIAL_SOURCE, PIN_FIELDS


class SetupTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        (self.root / "workspace").mkdir()
        self.entries, self.archives, self.files = [], {}, {}
        for name in ("core", "alpha", "beta"):
            files, envelope = fixture.fixture()
            files["pack.ini"] = files["pack.ini"].replace(b"id=demo", ("id=" + name).encode())
            envelope.update(id=name, manifestSha256=fixture.sha(files["pack.ini"]))
            envelope["files"] = [{"path": key, "size": len(value), "sha256": fixture.sha(value)}
                                 for key, value in files.items()]
            raw = fixture.archive_bytes(files, envelope)
            entry = fixture.entry_for(raw, envelope)
            entry.update(name=name.title(), downloadURL="https://example.invalid/" + name + ".zip")
            self.entries.append(entry)
            self.archives[entry["downloadURL"]] = raw
            self.files[name] = files
        self.profile = {"schema": 1, "sourceId": OFFICIAL_SOURCE,
                        "packs": [{**{key: row[key] for key in PIN_FIELDS}, "name": row["name"],
                                   "starter": row["id"] == "core"} for row in self.entries]}
        self.write_profile()
        self.source = copy.deepcopy(fixture.SOURCE)
        self.source["id"] = OFFICIAL_SOURCE
        self.write_source()
        self.install_files("core")
        self.manager = pm.PackManager(self.root, self.import_pack)
        self.setup = SetupManager(self.root, self.manager)
        self.requests = []
        self.failure = None
        self.cancel_at = None
        self.cancel_event = threading.Event()
        self.downloader = patch.object(pm, "_download", self.download)
        self.downloader.start()

    def tearDown(self):
        self.downloader.stop()
        self.temporary.cleanup()

    def write_profile(self):
        (self.root / "workspace" / "setup-profile.json").write_text(json.dumps(self.profile))

    def write_source(self, source=None):
        (self.root / "workspace" / "catalog-sources.json").write_text(json.dumps([source or self.source]))

    def install_files(self, name):
        folder = self.root / "packs" / (name + "-1.0.0")
        for relative, raw in self.files[name].items():
            path = folder / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(raw)

    def import_pack(self, source):
        pack = pm.load_pack(Path(source) / "pack.ini")
        shutil.copytree(source, self.root / "packs" / (pack["id"] + "-" + pack["version"]))
        return {"success": True}

    def signed(self):
        return fixture.sign({"schema": 1, "publishedAt": "2026-10-06T12:00:00Z", "packs": self.entries})

    def download(self, url, hosts, destination, limit, cancel=None, event=None, expected_size=None, expected_sha=None):
        self.requests.append(url)
        if url == self.failure:
            raise pm.PackError("Fixture connection failed")
        raw = self.signed() if url == self.source["catalogUrl"] else self.archives[url]
        if event:
            event({"phase": "downloading", "bytes": len(raw), "total": len(raw), "cancellable": True})
        if url == self.cancel_at:
            cancel.set()
        pm.cancelled(cancel)
        if expected_size is not None:
            self.assertEqual(len(raw), expected_size)
            self.assertEqual(fixture.sha(raw), expected_sha)
        Path(destination).write_bytes(raw)

    def run_action(self, action, **request):
        self.setup.prepare(action, request)
        self.setup.run(self.cancel_event)
        return self.setup.snapshot()

    def refresh(self):
        return self.run_action("refresh")

    def test_startup_and_starter_are_offline_without_official_source(self):
        (self.root / "workspace" / "catalog-sources.json").write_text("[]")
        state = self.setup.snapshot()
        self.assertTrue(state["offered"])
        self.assertFalse(state["configured"])
        result = self.run_action("start", profile="starter")
        self.assertEqual(result["operation"]["status"], "completed")
        self.assertFalse(self.requests)
        self.assertFalse(SetupManager(self.root, self.manager).snapshot()["offered"])
        with self.assertRaisesRegex(pm.PackError, "not configured"):
            self.setup.prepare("start", {"profile": "full"})

    def test_full_explicit_refresh_and_install_preserves_starter(self):
        with self.assertRaisesRegex(pm.PackError, "Refresh"):
            self.setup.prepare("start", {"profile": "full"})
        self.assertFalse(self.requests)
        original = (self.root / "packs/core-1.0.0/pack.ini").read_bytes()
        self.refresh()
        result = self.run_action("start", profile="full")
        self.assertEqual(result["operation"]["status"], "completed")
        self.assertEqual(result["operation"]["completed"], 3)
        self.assertEqual(result["operation"]["bytes"], sum(row["size"] for row in self.entries[1:]))
        self.assertEqual(result["operation"]["bytes"], result["operation"]["total"])
        self.assertEqual((self.root / "packs/core-1.0.0/pack.ini").read_bytes(), original)
        self.assertEqual(len(self.requests), 3)
        self.assertTrue(all(row["installed"] for row in result["rows"]))
        self.assertEqual(len(list((self.root / "user-data/pack-receipts").glob("*.json"))), 2)

    def test_prepare_write_failure_does_not_leave_an_active_workerless_operation(self):
        self.refresh()
        before = len(self.requests)
        with patch("setup_manager._atomic_bytes", side_effect=OSError("Fixture disk full")):
            with self.assertRaisesRegex(OSError, "disk full"):
                self.setup.prepare("start", {"profile": "full"})
        self.assertFalse(self.setup.snapshot()["operation"]["active"])
        self.assertEqual(self.setup.snapshot()["operation"]["status"], "failed")
        self.assertEqual(len(self.requests), before)
        self.assertEqual(self.run_action("start", profile="full")["operation"]["status"], "completed")

    def test_custom_includes_starter_and_only_selected_optional_pack(self):
        self.refresh()
        result = self.run_action("start", profile="custom", pack_ids=["beta"])
        self.assertEqual(result["selection"]["pack_ids"], ["core", "beta"])
        self.assertFalse((self.root / "packs/alpha-1.0.0").exists())
        with self.assertRaisesRegex(pm.PackError, "unknown pack"):
            self.setup.prepare("start", {"profile": "custom", "pack_ids": ["untrusted"]})

    def test_failure_reopen_retry_downloads_only_missing_exact_pack(self):
        self.refresh()
        self.failure = self.entries[2]["downloadURL"]
        result = self.run_action("start", profile="full")
        self.assertEqual(result["operation"]["status"], "failed")
        self.assertEqual([row["status"] for row in result["rows"]], ["completed", "completed", "failed"])
        alpha = (self.root / "packs/alpha-1.0.0/pack.ini").read_bytes()
        before = len(self.requests)
        self.setup = SetupManager(self.root, self.manager)
        self.setup.snapshot()
        self.assertEqual(len(self.requests), before)
        self.failure = None
        result = self.run_action("retry")
        self.assertEqual(result["operation"]["status"], "completed")
        self.assertEqual(self.requests[before:], [self.entries[2]["downloadURL"]])
        self.assertEqual((self.root / "packs/alpha-1.0.0/pack.ini").read_bytes(), alpha)

    def test_cancellation_preserves_completed_and_cleans_partial_staging(self):
        self.refresh()
        self.cancel_at = self.entries[2]["downloadURL"]
        result = self.run_action("start", profile="full")
        self.assertEqual(result["operation"]["status"], "cancelled")
        self.assertEqual(result["operation"]["completed"], 2)
        self.assertFalse((self.root / "packs/beta-1.0.0").exists())
        self.assertFalse(list((self.root / "user-data/pack-manager").glob("_install-*")))
        self.cancel_at = None
        self.cancel_event.clear()
        self.assertEqual(self.run_action("retry")["operation"]["status"], "completed")

    def test_abrupt_interruption_after_publication_reconciles_without_download(self):
        self.refresh()
        self.setup.prepare("start", {"profile": "full"})
        self.setup.queue[1]["status"] = "running"
        self.setup._save()
        self.install_files("alpha")  # Published just before previous host ended.
        self.setup = SetupManager(self.root, self.manager)
        self.assertEqual(self.setup.snapshot()["operation"]["status"], "interrupted")
        before = len(self.requests)
        self.assertEqual(self.run_action("retry")["operation"]["status"], "completed")
        self.assertEqual(self.requests[before:], [self.entries[2]["downloadURL"]])

    def test_installed_conflict_is_preserved_and_rejected_before_network(self):
        self.refresh()
        target = self.root / "packs/alpha-1.0.0"
        target.mkdir()
        (target / "pack.ini").write_text("invalid; preserve me")
        before = len(self.requests)
        with self.assertRaisesRegex(pm.PackError, "different manifest"):
            self.setup.prepare("start", {"profile": "full"})
        self.assertEqual(len(self.requests), before)
        self.assertEqual((target / "pack.ini").read_text(), "invalid; preserve me")

    def test_changed_signed_bytes_cannot_retarget_saved_selection(self):
        self.refresh()
        self.setup.prepare("start", {"profile": "full"})
        self.entries[1]["sha256"] = "f" * 64
        (self.manager.data / "cache" / (OFFICIAL_SOURCE + ".json")).write_bytes(self.signed())
        before = len(self.requests)
        self.setup.run(self.cancel_event)
        self.assertEqual(self.setup.snapshot()["operation"]["status"], "failed")
        self.assertEqual(len(self.requests), before)

    def test_pack_manager_checks_expected_identity_at_resolution_boundary(self):
        self.refresh()
        entry = copy.deepcopy(self.entries[1])
        entry["sha256"] = "f" * 64
        before = len(self.requests)
        with self.assertRaisesRegex(pm.PackError, "bytes differ"):
            self.manager.install(OFFICIAL_SOURCE, "alpha", "1.0.0", expected_entry=entry)
        self.assertEqual(len(self.requests), before)

    def test_trust_rotation_rejects_retry_without_contacting_network(self):
        self.refresh()
        self.failure = self.entries[1]["downloadURL"]
        self.run_action("start", profile="full")
        changed = copy.deepcopy(self.source)
        number = int(changed["publicKey"]["n"], 16) ^ 2
        changed["publicKey"]["n"] = format(number, "x")
        self.write_source(changed)
        before = len(self.requests)
        with self.assertRaisesRegex(pm.PackError, "publisher key has changed"):
            self.setup.prepare("retry", {})
        self.assertEqual(len(self.requests), before)

    def test_bad_cache_remains_refreshable_and_signature_failure_never_installs(self):
        self.refresh()
        cache = self.manager.data / "cache" / (OFFICIAL_SOURCE + ".json")
        cache.write_text('{"schema":1,"payload":"bad","signature":"bad"}')
        state = self.setup.snapshot()
        self.assertTrue(state["configured"])
        self.assertFalse(next(row for row in state["rows"] if row["id"] == "alpha")["available"])
        self.assertEqual(self.refresh()["operation"]["status"], "completed")

    def test_user_source_cannot_substitute_for_bundled_official_trust(self):
        (self.root / "workspace/catalog-sources.json").write_text("[]")
        self.manager.data.mkdir(parents=True)
        self.manager.sources_path.write_text(json.dumps([self.source]))
        self.assertFalse(self.setup.snapshot()["configured"])
        with self.assertRaisesRegex(pm.PackError, "not configured"):
            self.setup.prepare("refresh", {})
        self.assertFalse(self.requests)

    def test_startup_queue_lock_does_not_suppress_welcome_but_real_queue_does(self):
        from run_queue import RunQueue
        data = self.root / "user-data"
        data.mkdir(exist_ok=True)
        store = RunQueue(data)
        try:
            fresh = SetupManager(self.root, self.manager)
            self.assertFalse(fresh.previous_user)
            self.assertTrue(fresh.snapshot()["offered"])
            store.add([{"graph": {"name": "Explicit first analysis"}}], "1" * 32)
            returning = SetupManager(self.root, self.manager)
            self.assertTrue(returning.previous_user)
            self.assertFalse(returning.snapshot()["offered"])
        finally:
            store.close()

    def test_first_run_detection_ignores_launch_log_but_preserves_existing_workspace(self):
        data = self.root / "user-data"
        data.mkdir(exist_ok=True)
        (data / "desktop-host.stderr.txt").write_text("")
        self.assertTrue(SetupManager(self.root, self.manager).snapshot()["offered"])
        (data / "saved.json").write_text('{"pipelines":[],"presets":[]}')
        self.assertFalse(SetupManager(self.root, self.manager).snapshot()["offered"])

    def test_retry_old_queue_survives_new_curated_version_without_switching(self):
        self.refresh()
        self.failure = self.entries[1]["downloadURL"]
        self.run_action("start", profile="custom", pack_ids=["alpha"])
        new = copy.deepcopy(self.entries[1])
        new["version"] = "1.1.0"
        self.entries.append(new)
        self.profile["packs"][1]["version"] = "1.1.0"
        self.write_profile()
        (self.manager.data / "cache" / (OFFICIAL_SOURCE + ".json")).write_bytes(self.signed())
        self.setup = SetupManager(self.root, self.manager)
        self.failure = None
        self.assertEqual(self.run_action("retry")["operation"]["status"], "completed")
        self.assertTrue((self.root / "packs/alpha-1.0.0").is_dir())
        self.assertFalse((self.root / "packs/alpha-1.1.0").exists())


if __name__ == "__main__":
    unittest.main()
