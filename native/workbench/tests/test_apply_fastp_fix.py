#!/usr/bin/env python3
"""Filesystem transaction tests; these do not execute Windows binaries."""

import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "apply_fastp_fix.py"
SPEC = importlib.util.spec_from_file_location("apply_fastp_fix", SCRIPT)
updater = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(updater)


def sha(value):
    return hashlib.sha256(value).hexdigest()


def put(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(value)
    return sha(value)


def manifest(identifier, version, executable):
    return ("[pack]\nformat=2\nid=%s\nversion=%s\nplatform=windows-x86_64\n"
            "[tool:fastp]\npath=bin/fastp.exe\nsha256=%s\n"
            "[asset:runtime]\npath=runtime/unchanged.dat\nsha256=%s\n" %
            (identifier, version, sha(executable), sha(b"unchanged asset"))).encode()


class PatchFixture:
    def __init__(self, directory):
        self.root = directory / "app with spaces éΔ"
        self.patch = self.root / "fastp-report-fix"
        self.data = {"schema_version": 1, "patch_id": updater.PATCH_ID,
                     "files": {}, "applications": [], "packs": []}
        self.payload("source/changed-source.py", b"source supplement is checked too")
        self.payload("LICENSE", b"patch distribution notice")
        put(self.root / "work" / "private-input.fastq", b"do not change the user's work")
        put(self.root / "results" / "run.json", b"existing analysis")
        for name in sorted(updater.APPLICATIONS):
            old, new = (name + " original").encode(), (name + " updated").encode()
            put(self.root / name, old)
            source = "files/" + name
            self.payload(source, new)
            self.data["applications"].append({"path": name, "source": source,
                                              "old_sha256": sha(old), "new_sha256": sha(new)})
        for identifier in sorted(updater.PACK_IDS):
            pack = self.root / "packs" / (identifier + "-0.4.0")
            old_ini = manifest(identifier, "0.4.0", b"original fastp")
            new_ini = manifest(identifier, "0.4.1", b"updated fastp")
            put(pack / "pack.ini", old_ini)
            put(pack / "bin" / "fastp.exe", b"original fastp")
            put(pack / "runtime" / "unchanged.dat", b"unchanged asset")
            put(pack / "licenses" / "fastp" / "LICENSE", b"original license")
            put(pack / "licenses" / "fastp" / "BUILD-NOTES.txt", b"original notice")
            put(pack / "PACK-README.md", b"original readme")
            entries = {"pack.ini": ("files/" + identifier + ".pack.ini", new_ini),
                       "bin/fastp.exe": ("files/fastp.exe", b"updated fastp"),
                       "PACK-README.md": ("files/" + identifier + "-README.md", b"updated readme"),
                       "licenses/fastp/BUILD-NOTES.txt": ("files/BUILD-NOTES.txt", b"updated notice")}
            for source, contents in entries.values():
                self.payload(source, contents)
            self.data["packs"].append({"id": identifier, "old_version": "0.4.0", "new_version": "0.4.1",
                                        "old_manifest_sha256": sha(old_ini), "new_manifest_sha256": sha(new_ini),
                                        "replacements": {target: value[0] for target, value in entries.items()}})
        self.write_metadata()

    def payload(self, source, contents):
        self.data["files"][source] = put(self.patch / source, contents)

    def write_metadata(self):
        (self.patch / "patch-metadata.json").write_text(json.dumps(self.data), encoding="utf-8")

    def snapshot(self):
        return {p.relative_to(self.root).as_posix(): p.read_bytes() for p in self.root.rglob("*")
                if p.is_file() and p.relative_to(self.root).parts[0] not in {"updates", "fastp-report-fix"}}

    def run(self):
        return updater.apply_update(self.root, self.patch)


class TransactionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.fixture = PatchFixture(Path(self.temp.name))

    def test_install_backup_unchanged_data_and_idempotence(self):
        f = self.fixture
        before = f.snapshot()
        result = f.run()
        self.assertEqual(result["status"], "installed")
        backup = Path(result["backup"])
        for relative, contents in before.items():
            if relative.startswith(("work/", "results/")):
                self.assertEqual((f.root / relative).read_bytes(), contents)
            else:
                self.assertEqual((backup / "old" / relative).read_bytes(), contents)
        after = f.snapshot()
        self.assertFalse((f.root / "packs" / "fastp-0.4.0").exists())
        self.assertTrue((f.root / "packs" / "fastp-0.4.1").is_dir())
        self.assertEqual(f.run()["status"], "already-installed")
        self.assertEqual(f.snapshot(), after)
        self.assertEqual(len(list((f.root / "updates").glob("fastp-report-fix-*"))), 1)

    def test_failure_at_every_rename_rolls_back(self):
        original_rename = updater.rename
        for failing_call in range(1, 13):
            with self.subTest(failing_call=failing_call), tempfile.TemporaryDirectory() as folder:
                f = PatchFixture(Path(folder))
                before = f.snapshot()
                calls = 0

                def interrupted(source, destination):
                    nonlocal calls
                    calls += 1
                    if calls == failing_call:
                        raise OSError("simulated Windows sharing violation or disk failure")
                    return original_rename(source, destination)

                with mock.patch.object(updater, "rename", interrupted):
                    with self.assertRaisesRegex(updater.UpdateError, "all original.*restored"):
                        f.run()
                self.assertEqual(f.snapshot(), before)
                self.assertFalse((f.root / "updates" / ".fastp-report-fix.lock").exists())

    def test_bad_source_hash_does_not_modify_installation(self):
        f = self.fixture
        put(f.root / "packs" / "research-variants-0.4.0" / "runtime" / "unchanged.dat", b"corrupt")
        before = f.snapshot()
        with self.assertRaisesRegex(updater.UpdateError, "SHA-256 mismatch"):
            f.run()
        self.assertEqual(f.snapshot(), before)

    def test_bad_payload_and_undeclared_payload_are_rejected(self):
        f = self.fixture
        before = f.snapshot()
        put(f.patch / "files" / "fastp.exe", b"corrupt")
        with self.assertRaisesRegex(updater.UpdateError, "SHA-256 mismatch"):
            f.run()
        put(f.patch / "files" / "fastp.exe", b"updated fastp")
        put(f.patch / "files" / "unexpected.exe", b"unexpected")
        with self.assertRaisesRegex(updater.UpdateError, "inventory"):
            f.run()
        self.assertEqual(f.snapshot(), before)

    def test_undeclared_pack_file_is_rejected(self):
        f = self.fixture
        put(f.root / "packs" / "fastp-0.4.0" / "extra.exe", b"unexpected")
        before = f.snapshot()
        with self.assertRaisesRegex(updater.UpdateError, "Undeclared file"):
            f.run()
        self.assertEqual(f.snapshot(), before)

    def test_installed_patch_tampering_cannot_become_noop(self):
        f = self.fixture
        f.run()
        put(f.root / "packs" / "fastp-0.4.1" / "bin" / "fastp.exe", b"changed afterwards")
        before = f.snapshot()
        with self.assertRaisesRegex(updater.UpdateError, "SHA-256 mismatch"):
            f.run()
        self.assertEqual(f.snapshot(), before)

    def test_mixed_versions_are_rejected(self):
        f = self.fixture
        (f.root / "packs" / "fastp-0.4.1").mkdir()
        before = f.snapshot()
        with self.assertRaisesRegex(updater.UpdateError, "mixed or unsupported"):
            f.run()
        self.assertEqual(f.snapshot(), before)

    def test_exclusive_lock_is_preserved(self):
        f = self.fixture
        lock = f.root / "updates" / ".fastp-report-fix.lock"
        put(lock, b"another installer owns this")
        before = f.snapshot()
        with self.assertRaisesRegex(updater.UpdateError, "update lock"):
            f.run()
        self.assertEqual(lock.read_bytes(), b"another installer owns this")
        self.assertEqual(f.snapshot(), before)

    def test_symlink_inside_pack_is_rejected_without_following(self):
        f = self.fixture
        target = Path(self.temp.name) / "outside"
        target.mkdir()
        put(target / "precious.txt", b"unchanged outside data")
        link = f.root / "packs" / "fastp-0.4.0" / "licenses" / "link"
        try:
            link.symlink_to(target, target_is_directory=True)
        except OSError as error:
            self.skipTest("Symlink creation unavailable: " + str(error))
        with self.assertRaisesRegex(updater.UpdateError, "links and reparse"):
            f.run()
        self.assertEqual((target / "precious.txt").read_bytes(), b"unchanged outside data")

    def test_metadata_traversal_and_nonallowlisted_application_rejected(self):
        f = self.fixture
        before = f.snapshot()
        f.data["packs"][0]["replacements"]["../escape.exe"] = "files/fastp.exe"
        f.write_metadata()
        with self.assertRaisesRegex(updater.UpdateError, "Unsafe relative"):
            f.run()
        del f.data["packs"][0]["replacements"]["../escape.exe"]
        f.data["applications"][0]["path"] = "user-results.json"
        f.write_metadata()
        with self.assertRaisesRegex(updater.UpdateError, "application replacement"):
            f.run()
        self.assertEqual(f.snapshot(), before)


if __name__ == "__main__":
    unittest.main()
