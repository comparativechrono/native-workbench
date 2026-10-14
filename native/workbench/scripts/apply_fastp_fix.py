#!/usr/bin/env python3
"""Offline, staged fastp report fix for the original Native Workbench 0.4.0.

Run with the unaffected trimming pack's Python, with Native Workbench closed.
Metadata and payload checksums establish package consistency, not a signature.
Only the two affected pack directories and explicitly named application files
are replaced. Existing analysis inputs, work directories and results are unused.
"""

import argparse
import configparser
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import sys
import time
import uuid


PATCH_ID = "fastp-report-fix-0.4.1"
PACK_IDS = {"fastp", "research-variants"}
APPLICATIONS = {"NativeWorkbench.exe", "WindowsPipelineChecks.exe", "manifest.json", "README.txt"}
REQUIRED_APPLICATIONS = {"NativeWorkbench.exe", "WindowsPipelineChecks.exe"}
SHA256 = re.compile(r"[0-9a-f]{64}\Z")
RESERVED = re.compile(r"(?:CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?\Z", re.I)


class UpdateError(RuntimeError):
    pass


def fail(message):
    raise UpdateError(message)


def relative(value):
    """Accept portable file names, with one spelling on Windows and Linux."""
    if not isinstance(value, str) or not value or "\\" in value or ":" in value:
        fail("Unsafe relative path: %r" % value)
    parts = value.split("/")
    if any(not p or p in (".", "..") or p[-1] in " ." or RESERVED.fullmatch(p)
           or any(ord(c) < 32 or c in '<>\"|?*' for c in p) for p in parts):
        fail("Unsafe relative path: %r" % value)
    return value


def digest_value(value):
    if not isinstance(value, str) or not SHA256.fullmatch(value):
        fail("Invalid SHA-256 in patch metadata or pack manifest")
    return value


def clean_path(value):
    value = os.path.abspath(os.fspath(value))
    if os.name == "nt":
        # Extended local paths work without requiring the machine's long-path policy.
        if value.startswith("\\\\?\\"):
            value = value[4:]
        if value.startswith("\\\\") or not re.match(r"[A-Za-z]:\\", value):
            fail("Install the patch in a local drive folder, not a UNC/device path")
        value = "\\\\?\\" + value
    return Path(value)


def inspect_path(path, kind=None):
    try:
        info = path.lstat()
    except FileNotFoundError:
        fail("Required path is missing: " + str(path))
    if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
        fail("Symbolic links and reparse points are not allowed: " + str(path))
    if not stat.S_ISDIR(info.st_mode) and not stat.S_ISREG(info.st_mode):
        fail("Path is not an ordinary file or directory: " + str(path))
    if kind == "file" and not stat.S_ISREG(info.st_mode):
        fail("Expected an ordinary file: " + str(path))
    if kind == "directory" and not stat.S_ISDIR(info.st_mode):
        fail("Expected an ordinary directory: " + str(path))
    return info


def inspect_ancestors(path):
    for parent in reversed((path, *path.parents)):
        inspect_path(parent, "directory")


def exists(path):
    # lexists catches broken symlinks, which must never be treated as free paths.
    return os.path.lexists(path)


def hash_file(path):
    inspect_ancestors(path.parent)
    inspect_path(path, "file")
    result = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            result.update(block)
    return result.hexdigest()


def require_hash(path, expected):
    if hash_file(path) != digest_value(expected):
        fail("SHA-256 mismatch: " + str(path))


def inventory(root):
    inspect_ancestors(root)
    result = {}
    seen = set()
    pending = [root]
    while pending:
        directory = pending.pop()
        inspect_path(directory, "directory")
        for child in directory.iterdir():
            name = relative(child.relative_to(root).as_posix())
            key = name.casefold()
            if key in seen:
                fail("Case-insensitive duplicate path: " + name)
            seen.add(key)
            info = inspect_path(child)
            if stat.S_ISDIR(info.st_mode):
                pending.append(child)
            else:
                result[name] = child
    return result


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            fail("Duplicate JSON key: " + key)
        result[key] = value
    return result


def read_metadata(patch):
    inspect_ancestors(patch)
    inspect_path(patch / "patch-metadata.json", "file")
    with (patch / "patch-metadata.json").open(encoding="utf-8") as handle:
        data = json.load(handle, object_pairs_hook=unique_object)
    if not isinstance(data, dict) or data.get("schema_version") != 1 or data.get("patch_id") != PATCH_ID:
        fail("Unsupported patch metadata")
    files, apps, packs = data.get("files"), data.get("applications"), data.get("packs")
    if not isinstance(files, dict) or not files or not isinstance(apps, list) or not isinstance(packs, list):
        fail("Incomplete patch metadata")
    seen = set()
    for name, value in files.items():
        relative(name)
        if name == "patch-metadata.json" or name.casefold() in seen:
            fail("Invalid or duplicate payload path: " + name)
        seen.add(name.casefold())
        require_hash(patch / name, value)
    actual_payload = set(inventory(patch)) - {"patch-metadata.json"}
    if actual_payload != set(files):
        fail("The payload file inventory does not match patch metadata")

    def source(name):
        if not isinstance(name, str) or not name.startswith("files/") or name not in files:
            fail("Replacement does not reference a verified payload file")

    seen = set()
    for app in apps:
        if not isinstance(app, dict) or app.get("path") not in APPLICATIONS or app["path"] in seen:
            fail("Invalid or duplicate application replacement")
        seen.add(app["path"])
        source(app.get("source"))
        digest_value(app.get("old_sha256"))
        digest_value(app.get("new_sha256"))
        if app["new_sha256"] != files[app["source"]]:
            fail("Application and payload hashes disagree")
    if not REQUIRED_APPLICATIONS <= seen:
        fail("Both application executables must be included")
    seen = set()
    for pack in packs:
        if not isinstance(pack, dict) or pack.get("id") not in PACK_IDS or pack["id"] in seen:
            fail("Invalid or duplicate pack replacement")
        seen.add(pack["id"])
        if pack.get("old_version") != "0.4.0" or pack.get("new_version") != "0.4.1":
            fail("This patch only upgrades pack version 0.4.0 to 0.4.1")
        digest_value(pack.get("old_manifest_sha256"))
        digest_value(pack.get("new_manifest_sha256"))
        replacements = pack.get("replacements")
        if not isinstance(replacements, dict) or not {"pack.ini", "PACK-README.md", "bin/fastp.exe"} <= set(replacements):
            fail("Pack replacements must include manifest, README and fastp executable")
        names = set()
        for destination, origin in replacements.items():
            relative(destination)
            if destination.casefold() in names:
                fail("Duplicate pack replacement path")
            names.add(destination.casefold())
            source(origin)
        if files[replacements["pack.ini"]] != pack["new_manifest_sha256"]:
            fail("Pack manifest and payload hashes disagree")
    if seen != PACK_IDS:
        fail("Both fastp and research-variants packs must be included")
    return data


def verify_pack(root, pack, version, manifest_hash, replacements=None, files=None):
    paths = inventory(root)
    require_hash(root / "pack.ini", manifest_hash)
    config = configparser.ConfigParser(interpolation=None, strict=True)
    with (root / "pack.ini").open(encoding="utf-8") as handle:
        config.read_file(handle)
    if config.defaults() or not config.has_section("pack"):
        fail("Invalid pack manifest")
    identity = config["pack"]
    if any(identity.get(key) != value for key, value in {
            "format": "2", "id": pack["id"], "version": version,
            "platform": "windows-x86_64"}.items()):
        fail("Pack identity/version/platform mismatch: " + str(root))
    declared = {"pack.ini", "PACK-README.md", "PACK-README.txt", "README.txt"}
    seen = {name.casefold() for name in declared}
    for section in config.sections():
        if not section.startswith(("tool:", "asset:")):
            continue
        name = relative(config[section].get("path"))
        if name.casefold() in seen:
            fail("Duplicate declared pack path: " + name)
        seen.add(name.casefold())
        declared.add(name)
        require_hash(root / name, config[section].get("sha256"))
    for name in paths:
        if name not in declared and not name.startswith("licenses/"):
            fail("Undeclared file in pack: " + str(root / name))
    if not any(name.startswith("licenses/") for name in paths):
        fail("Pack license notices are missing: " + str(root))
    if replacements is not None:
        for name, origin in replacements.items():
            require_hash(root / name, files[origin])


def copy_file(source, destination):
    inspect_ancestors(source.parent)
    inspect_path(source, "file")
    destination.parent.mkdir(parents=True, exist_ok=True)
    inspect_ancestors(destination.parent)
    if exists(destination):
        inspect_path(destination, "file")
    # All destinations are private staged copies; no original file is written.
    with source.open("rb") as reader, destination.open("wb") as writer:
        shutil.copyfileobj(reader, writer, 1024 * 1024)


def copy_pack(source, destination):
    paths = inventory(source)
    destination.mkdir()
    for name, path in paths.items():
        copy_file(path, destination / name)


def rename(source, destination):
    """Separate function so tests can inject a failure during publication."""
    inspect_ancestors(source.parent)
    inspect_path(source)
    inspect_ancestors(destination.parent)
    if exists(destination):
        fail("Refusing to overwrite an existing destination: " + str(destination))
    os.rename(source, destination)


def installed_state(app_root, data):
    old = [app_root / "packs" / (p["id"] + "-" + p["old_version"]) for p in data["packs"]]
    new = [app_root / "packs" / (p["id"] + "-" + p["new_version"]) for p in data["packs"]]
    old_exists, new_exists = [exists(p) for p in old], [exists(p) for p in new]
    if all(old_exists) and not any(new_exists):
        for path, pack in zip(old, data["packs"]):
            verify_pack(path, pack, pack["old_version"], pack["old_manifest_sha256"])
        for app in data["applications"]:
            require_hash(app_root / app["path"], app["old_sha256"])
        return "original"
    if not any(old_exists) and all(new_exists):
        for path, pack in zip(new, data["packs"]):
            verify_pack(path, pack, pack["new_version"], pack["new_manifest_sha256"],
                        pack["replacements"], data["files"])
        for app in data["applications"]:
            require_hash(app_root / app["path"], app["new_sha256"])
        return "updated"
    fail("The installed packs have a mixed or unsupported version state; no files were replaced")


def write_json(path, value):
    with path.open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(value, handle, indent=2)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())


def apply_update(app_root, patch_dir):
    app_root, patch_dir = clean_path(app_root), clean_path(patch_dir)
    inspect_ancestors(app_root)
    inspect_ancestors(app_root / "packs")
    updates = app_root / "updates"
    updates.mkdir(exist_ok=True)
    inspect_ancestors(updates)
    lock = updates / ".fastp-report-fix.lock"
    try:
        descriptor = os.open(lock, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        fail("Another patch run has the update lock. Close it first; do not run two installers together: " + str(lock))
    try:
        os.write(descriptor, ("PID %d\n" % os.getpid()).encode("ascii"))
        data = read_metadata(patch_dir)
        if installed_state(app_root, data) == "updated":
            return {"status": "already-installed", "patch_id": PATCH_ID}
        backup = updates / ("fastp-report-fix-" + time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:12])
        backup.mkdir()
        staging = backup / "staging"
        staging.mkdir()
        (staging / "packs").mkdir()
        (backup / "old" / "packs").mkdir(parents=True)
        for pack in data["packs"]:
            source = app_root / "packs" / (pack["id"] + "-" + pack["old_version"])
            candidate = staging / "packs" / (pack["id"] + "-" + pack["new_version"])
            copy_pack(source, candidate)
            for destination, origin in pack["replacements"].items():
                copy_file(patch_dir / origin, candidate / destination)
            verify_pack(candidate, pack, pack["new_version"], pack["new_manifest_sha256"],
                        pack["replacements"], data["files"])
        for app in data["applications"]:
            copy_file(patch_dir / app["source"], staging / app["path"])
            require_hash(staging / app["path"], app["new_sha256"])
        # Check originals again after staging and before the first rename.
        if installed_state(app_root, data) != "original":
            fail("The installation changed while the patch was being staged")
        write_json(backup / "patch-metadata.json", data)
        operations = []

        def move(source, destination):
            rename(source, destination)
            operations.append((source, destination))

        try:
            for pack in data["packs"]:
                name = pack["id"] + "-" + pack["old_version"]
                move(app_root / "packs" / name, backup / "old" / "packs" / name)
            for app in data["applications"]:
                move(app_root / app["path"], backup / "old" / app["path"])
            for pack in data["packs"]:
                name = pack["id"] + "-" + pack["new_version"]
                move(staging / "packs" / name, app_root / "packs" / name)
            for app in data["applications"]:
                move(staging / app["path"], app_root / app["path"])
            if installed_state(app_root, data) != "updated":
                fail("Post-install verification failed")
            result = {"status": "installed", "patch_id": PATCH_ID, "backup": str(backup)}
            write_json(backup / "installed.json", result)
            return result
        except BaseException as error:
            rollback_errors = []
            for original, moved in reversed(operations):
                try:
                    rename(moved, original)
                except BaseException as rollback_error:
                    rollback_errors.append(str(rollback_error))
            if rollback_errors:
                fail("Patch failed and restoration needs attention. Keep this backup: %s\nOriginal error: %s\nRestoration errors: %s" %
                     (backup, error, "; ".join(rollback_errors)))
            fail("Patch failed; all original application files and packs were restored. Close Native Workbench and try again. Backup/staging: %s\nReason: %s" %
                 (backup, error))
    finally:
        os.close(descriptor)
        lock.unlink()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app-root", required=True, type=Path)
    parser.add_argument("--patch-dir", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        result = apply_update(args.app_root, args.patch_dir)
    except (OSError, ValueError, configparser.Error, UpdateError) as error:
        print("UPDATE FAILED: " + str(error), file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2))
    print("The fastp report fix is verified. You can open Native Workbench and run Check installation.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
