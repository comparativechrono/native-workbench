"""Opt-in installation profiles over the existing, signed pack manager.

The bundled profile is a selection lock and size estimate, never a trust root.
Only the independently verified, application-bundled official source can supply
downloads. Construction and snapshots use local files only.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path
import threading
import uuid

from catalog import ID, VERSION, SHA
from pack_manager import (PackError, MAX_ARCHIVE_BYTES, _atomic_bytes, cancelled,
                          compatibility, filesystem_path)
from pack_security import require, strict_json, key_fingerprint

OFFICIAL_SOURCE = "native-workbench-official"
PIN_FIELDS = ("id", "version", "size", "sha256", "manifestSha256")
PROFILES = [{"id": "full", "name": "Full — all tools (recommended)"},
            {"id": "starter", "name": "Starter — use installed core tools"},
            {"id": "custom", "name": "Custom — choose tools"}]


def _read(path, limit):
    require(path.is_file() and not path.is_symlink() and path.stat().st_size <= limit,
            "Invalid tool setup file: " + path.name)
    return strict_json(path.read_bytes())


def _pin(item):
    return tuple(item[field] for field in PIN_FIELDS)


class SetupManager:
    def __init__(self, root, manager):
        self.root = Path(root).resolve()
        self.manager = manager
        self.path = filesystem_path(self.root / "user-data" / "tool-setup.json")
        self.profile_path = filesystem_path(self.root / "workspace" / "setup-profile.json")
        self.lock = threading.RLock()
        self.profile = self._profile()
        self.operation = self._idle()
        self.revision = uuid.uuid4().hex
        self.queue = []
        self.selection = {"profile": "full", "pack_ids": []}
        self.dismissed = False
        self.source_fingerprint = ""
        self.previous_user = self._previous_user()
        if self.path.exists():
            self._restore(_read(self.path, 512 * 1024))

    @staticmethod
    def _idle():
        return {"id": "", "active": False, "status": "idle", "action": "",
                "message": "Choose the tools to install.", "bytes": 0, "total": 0,
                "cancellable": False, "completed": 0, "count": 0, "current": "",
                "currentBytes": 0, "currentTotal": 0, "phase": "idle"}

    def _profile(self):
        if not self.profile_path.exists():
            return {"schema": 1, "sourceId": OFFICIAL_SOURCE, "packs": []}
        value = _read(self.profile_path, 256 * 1024)
        require(isinstance(value, dict) and set(value) == {"schema", "sourceId", "packs"}
                and type(value["schema"]) is int and value["schema"] == 1
                and value["sourceId"] == OFFICIAL_SOURCE, "Invalid tool setup profile")
        require(isinstance(value["packs"], list) and 1 <= len(value["packs"]) <= 256,
                "Invalid tool setup pack selection")
        identities = set()
        for item in value["packs"]:
            require(isinstance(item, dict) and set(item) == {*PIN_FIELDS, "name", "starter"},
                    "Invalid tool setup pack entry")
            require(isinstance(item["id"], str) and ID.fullmatch(item["id"])
                    and item["id"] not in identities, "Invalid or duplicate setup pack")
            require(isinstance(item["version"], str) and VERSION.fullmatch(item["version"]),
                    "Invalid setup pack version")
            require(isinstance(item["name"], str) and 0 < len(item["name"]) <= 100
                    and all(ord(char) >= 32 for char in item["name"]), "Invalid setup pack name")
            require(type(item["size"]) is int and 0 < item["size"] <= MAX_ARCHIVE_BYTES,
                    "Invalid setup download size")
            require(type(item["starter"]) is bool and all(isinstance(item[key], str)
                    and SHA.fullmatch(item[key]) for key in ("sha256", "manifestSha256")),
                    "Invalid setup pack identity")
            identities.add(item["id"])
        return value

    def _previous_user(self):
        # Startup creates user-data, its stderr log and the OS queue lock.
        # None means the user configured an installation. Real queue records
        # and other existing records/preferences do.
        data = self.root / "user-data"
        ignored = {"desktop-host.stderr.txt", "tool-setup.json", "run-queue.lock"}
        return data.exists() and any(path.name not in ignored for path in data.iterdir())

    def _restore(self, value):
        require(isinstance(value, dict) and set(value) == {"schema", "dismissed", "selection", "queue", "operation", "sourceFingerprint"}
                and value["schema"] == 1 and type(value["dismissed"]) is bool,
                "Saved tool setup cannot be read; existing packs were preserved.")
        selection = value["selection"]
        require(isinstance(selection, dict) and set(selection) == {"profile", "pack_ids"}
                and selection["profile"] in ("full", "starter", "custom")
                and isinstance(selection["pack_ids"], list), "Invalid saved setup selection")
        queue = value["queue"]
        require(isinstance(queue, list) and len(queue) <= 256, "Invalid saved setup queue")
        seen = set()
        for item in queue:
            require(isinstance(item, dict) and set(item) == {*PIN_FIELDS, "name", "starter", "status", "error"},
                    "Invalid saved setup pack")
            # A later application may update its curated selection. Old queue
            # identities remain frozen, and still need signed verification.
            require(isinstance(item["id"], str) and ID.fullmatch(item["id"])
                    and item["id"] not in seen and isinstance(item["version"], str)
                    and VERSION.fullmatch(item["version"]), "Invalid saved setup identity")
            require(all(isinstance(item[key], str) and SHA.fullmatch(item[key])
                        for key in ("sha256", "manifestSha256"))
                    and type(item["size"]) is int and 0 < item["size"] <= MAX_ARCHIVE_BYTES,
                    "Invalid saved setup digest or size")
            require(isinstance(item["name"], str) and len(item["name"]) <= 100
                    and type(item["starter"]) is bool and isinstance(item["error"], str)
                    and len(item["error"]) <= 4096 and item["status"] in
                    ("pending", "completed", "failed", "cancelled", "interrupted", "running"),
                    "Invalid saved setup state")
            if item["status"] == "running":
                item["status"] = "interrupted"
                item["error"] = "The previous setup ended before this pack was completed. Retry to continue."
            seen.add(item["id"])
        require(selection["pack_ids"] == [item["id"] for item in queue],
                "Saved setup selection and queue differ")
        previous = value["operation"]
        require(isinstance(previous, dict) and set(previous) == set(self.operation), "Invalid saved setup operation")
        require(all(type(previous[field]) is int and previous[field] >= 0 for field in
                    ("bytes", "total", "completed", "count", "currentBytes", "currentTotal"))
                and type(previous["active"]) is bool and type(previous["cancellable"]) is bool
                and all(isinstance(previous[field], str) and len(previous[field]) <= 4096 for field in
                        ("id", "status", "action", "message", "current", "phase")), "Invalid saved setup progress")
        self.dismissed, self.selection, self.queue = value["dismissed"], selection, queue
        require(isinstance(value["sourceFingerprint"], str) and len(value["sourceFingerprint"]) <= 100,
                "Invalid saved setup publisher identity")
        self.source_fingerprint = value["sourceFingerprint"]
        self.operation = previous
        if previous["active"]:
            self.operation.update(active=False, cancellable=False, status="interrupted",
                                  message="Setup was interrupted. Completed tools remain installed; retry to continue.")

    def _save(self):
        value = {"schema": 1, "dismissed": self.dismissed, "selection": self.selection,
                 "sourceFingerprint": self.source_fingerprint,
                 "queue": self.queue, "operation": self.operation}
        _atomic_bytes(self.path, json.dumps(value, ensure_ascii=False, indent=2).encode("utf-8"))

    def _source(self):
        # A user-imported source with the same ID is insufficient. Only trust
        # distributed with this application can power its recommended setup.
        sources = self.manager._read_sources(self.manager.bundled_sources_path)
        return next((source for source in sources if source["id"] == OFFICIAL_SOURCE), None)

    def _entries(self, source):
        document = self.manager._cached(source) if source else None
        return {_pin(item): item for item in document["packs"]
                if any(_pin(item) == _pin(pack) for pack in [*self.profile["packs"], *self.queue])} if document else {}

    def _installed(self, item):
        return self.manager._existing_manifest(item["id"], item["version"]) == item["manifestSha256"]

    def snapshot(self):
        with self.lock:
            error = ""
            source = None
            try:
                source = self._source()
                entries = self._entries(source)
            except (PackError, OSError, ValueError) as exc:
                entries, error = {}, str(exc)
            queue = {item["id"]: item for item in self.queue}
            rows = []
            for item in self.profile["packs"]:
                existing = self.manager._existing_manifest(item["id"], item["version"])
                installed = existing == item["manifestSha256"]
                entry = entries.get(_pin(item))
                available = bool(entry and _pin(item) == _pin(entry))
                good, reason = compatibility(entry) if available else (False, "Refresh the official catalogue to verify this pack.")
                if existing is not None and not installed:
                    good, reason = False, "This version has a different installed manifest. Existing files will not be overwritten."
                record = queue.get(item["id"], {})
                rows.append({**copy.deepcopy(item), "installed": installed, "available": available,
                             "compatible": bool(installed or good), "reason": "" if installed else reason,
                             "status": record.get("status", "completed" if installed else "pending"),
                             "error": record.get("error", "")})
            notice = ("Choose Full, Starter or Custom. Downloads start only when requested. Installed tools work offline."
                      if source else "The official signed tool catalogue is not configured in this application. Starter and offline pack imports remain available.")
            if error:
                notice += " " + error
            return {"schema": 1, "offered": bool(self.profile["packs"] and not self.dismissed and not self.previous_user),
                    "configured": source is not None, "profiles": copy.deepcopy(PROFILES), "rows": rows,
                    "selection": copy.deepcopy(self.selection), "operation": copy.deepcopy(self.operation),
                    "revision": self.revision, "notice": notice}

    def dismiss(self):
        with self.lock:
            require(not self.operation["active"], "Cancel setup or wait for it to finish before closing it.")
            self.dismissed = True
            self._save()

    def prepare(self, action, request):
        """Validate and persist the exact queue before the host starts a worker."""
        with self.lock:
            require(not self.operation["active"], "Tool setup is already running.")
            require(action in ("refresh", "start", "retry"), "Unknown tool setup action")
            require(isinstance(request, dict), "Invalid tool setup request")
            if action == "start":
                require(set(request) <= {"profile", "pack_ids"}, "Unknown tool setup field")
                profile = request.get("profile")
                require(profile in ("full", "starter", "custom"), "Choose Full, Starter or Custom.")
                require(profile == "custom" or "pack_ids" not in request, "Only Custom accepts a pack selection.")
                ids = request.get("pack_ids", [])
                require(isinstance(ids, list) and len(ids) <= 256 and all(isinstance(item, str) for item in ids)
                        and len(set(ids)) == len(ids), "Invalid Custom pack selection")
                known = {item["id"] for item in self.profile["packs"]}
                require(set(ids) <= known, "The Custom selection contains an unknown pack.")
                require(bool(self.profile["packs"]), "This application does not include a tool setup profile.")
                selected = [item for item in self.profile["packs"] if profile == "full" or item["starter"]
                            or profile == "custom" and item["id"] in ids]
                queue = [{**copy.deepcopy(item), "status": "completed" if self._installed(item) else "pending", "error": ""}
                         for item in selected]
                if profile == "starter":
                    require(all(item["status"] == "completed" for item in queue),
                            "The Starter installation is incomplete. Restore the application from its verified Starter download.")
            else:
                require(not request, "Unknown tool setup field")
                queue, profile = copy.deepcopy(self.queue), self.selection["profile"]
                if action == "retry":
                    require(bool(queue), "There is no previous tool setup to retry.")
                    for item in queue:
                        item.update(status="completed" if self._installed(item) else "pending", error="")
            if action == "refresh" or any(item["status"] != "completed" for item in queue):
                source = self._source()
                require(source is not None, "The official signed tool catalogue is not configured. Use Starter or Import pack ZIP.")
                if action != "refresh":
                    fingerprint = key_fingerprint(source["publicKey"])
                    require(action != "retry" or fingerprint == self.source_fingerprint,
                            "The official publisher key has changed since this setup was selected. Existing tools were preserved; review a new selection.")
                    entries = self._entries(source)
                    for item in queue:
                        if item["status"] == "completed":
                            continue
                        entry = entries.get(_pin(item))
                        require(entry is not None and _pin(entry) == _pin(item),
                                "Refresh the official catalogue before installing " + item["name"] + ". Its exact signed version is required.")
                        good, reason = compatibility(entry)
                        require(good, reason)
                        require(self.manager._existing_manifest(item["id"], item["version"]) is None,
                                "An installed version has a different manifest. Existing packs were preserved.")
            if action != "refresh":
                self.queue, self.selection = queue, {"profile": profile, "pack_ids": [item["id"] for item in queue]}
                if any(item["status"] != "completed" for item in queue):
                    self.source_fingerprint = key_fingerprint(source["publicKey"])
                elif action == "start":
                    self.source_fingerprint = ""
            self.dismissed = True
            self.operation = self._idle()
            self.operation.update(id=uuid.uuid4().hex, active=True, status="running", action=action,
                                  message="Checking the official catalogue…" if action == "refresh" else "Preparing tool installation…",
                                  total=sum(item["size"] for item in queue if item["status"] != "completed"),
                                  completed=sum(item["status"] == "completed" for item in queue), count=len(queue),
                                  cancellable=True, phase="refreshing" if action == "refresh" else "preparing")
            try:
                self._save()
            except (OSError, ValueError) as error:
                # No worker exists yet. Failed persistence must not leave a
                # phantom active operation which can never finish or cancel.
                self.operation.update(active=False, cancellable=False, status="failed", message=str(error)[:4096])
                raise

    def run(self, cancel):
        try:
            cancelled(cancel)
            if self.operation["action"] == "refresh":
                source = self._source()
                require(source is not None, "The official signed tool catalogue is not configured.")
                self.manager._refresh(source, cancel=cancel)
                with self.lock:
                    self.operation.update(status="completed", message="Official catalogue verified. Choose Install to download your selected tools.")
                return
            downloaded = 0
            for item in self.queue:
                if item["status"] == "completed":
                    continue
                cancelled(cancel)
                with self.lock:
                    item["status"] = "running"
                    self.operation.update(current=item["name"], currentBytes=0, currentTotal=item["size"],
                                          cancellable=True, phase="preparing")
                    self._save()
                try:
                    source = self._source()
                    require(source is not None, "The official signed tool catalogue is not configured.")
                    require(key_fingerprint(source["publicKey"]) == self.source_fingerprint,
                            "The official publisher key differs from the saved setup selection.")
                    entry = self._entries(source).get(_pin(item))
                    require(entry is not None and _pin(entry) == _pin(item),
                            "The signed catalogue no longer contains the exact selected pack. Refresh and retry; no versions were changed.")
                    def event(value):
                        with self.lock:
                            phase = value.get("phase", "")
                            self.operation.update(phase=phase, cancellable=value.get("cancellable", True),
                                                  message=value.get("message") or phase.capitalize() + " " + item["name"] + "…")
                            if phase == "downloading":
                                count = min(item["size"], max(0, value.get("bytes", 0)))
                                self.operation.update(bytes=downloaded + count, currentBytes=count)
                    result = self.manager.install(OFFICIAL_SOURCE, item["id"], item["version"], cancel=cancel, event=event,
                                                  expected_entry=item, expected_source_fingerprint=self.source_fingerprint)
                    require(isinstance(result, dict) and result.get("success") is True,
                            result.get("message", "Tool installation failed.") if isinstance(result, dict) else "Tool installation failed.")
                    require(self._installed(item), "The installed tool does not match its selected manifest.")
                    with self.lock:
                        item.update(status="completed", error="")
                        downloaded += item["size"]
                        self.operation.update(bytes=downloaded, currentBytes=item["size"],
                                              completed=sum(pack["status"] == "completed" for pack in self.queue))
                        self.revision = uuid.uuid4().hex
                        self._save()
                except Exception as exc:
                    with self.lock:
                        # A worker can fail after atomic publication. Preserve
                        # and expose an installed exact version, never redownload it.
                        if self._installed(item):
                            item.update(status="completed", error="")
                            self.revision = uuid.uuid4().hex
                        else:
                            item.update(status="cancelled" if isinstance(exc, InterruptedError) else "failed", error=str(exc)[:4096])
                    raise
            with self.lock:
                self.operation.update(status="completed", message="Your selected tools are ready. You can add more tools at any time.")
        except Exception as exc:
            with self.lock:
                self.operation.update(status="cancelled" if isinstance(exc, InterruptedError) else "failed",
                                      message=str(exc)[:4096])
        finally:
            with self.lock:
                self.operation.update(active=False, cancellable=False,
                                      completed=sum(item["status"] == "completed" for item in self.queue))
                self._save()

    def cancel(self, event):
        with self.lock:
            if self.operation["active"]:
                require(self.operation["cancellable"], "Installation is being committed. Wait for it to finish.")
                event.set()
                self.operation["message"] = "Cancelling setup. Completed tools will remain installed…"

    def host_failure(self, error):
        """Expose host/catalogue/state-write failures without stranding busy UI."""
        with self.lock:
            self.operation.update(active=False, cancellable=False, status="failed", message=str(error)[:4096])
            try:
                self._save()
            except (OSError, ValueError):
                # Preserve the in-memory failure when the disk itself is full
                # or unwritable. Never label an unpersisted operation completed.
                pass
