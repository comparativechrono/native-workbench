"""Explicit, offline portable projects: exact dependencies, never executable packs.

The ZIP is a transport, not a new trust root. Import copies verified ordinary
input files into a new project folder and never installs, downloads or executes
anything. Its on-disk graph uses dependency IDs; open_project binds them relative
to the project's current location, so moving that folder remains supported.
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import tempfile
import uuid
import zipfile
from urllib.parse import quote

try:
    from .app_version import APP_VERSION
    from .catalog import _relative, parse_pack
    from .engine import canonical, digest_file, pin_for, safe_json, _ordinary, _io_path, _parameter, _field_default
    from .reference_provenance import collect_references
    from .cwl_export import export_workflow
except ImportError:
    from app_version import APP_VERSION
    from catalog import _relative, parse_pack
    from engine import canonical, digest_file, pin_for, safe_json, _ordinary, _io_path, _parameter, _field_default
    from reference_provenance import collect_references
    from cwl_export import export_workflow


MAX_MANIFEST = 4 * 1024 * 1024
MAX_METADATA = 1024 * 1024
MAX_MEMBERS = 4096
MAX_FILE_BYTES = 16 * 1024 ** 3
MAX_TOTAL_BYTES = 64 * 1024 ** 3
MAX_RATIO = 1000
SHA = re.compile(r"[a-f0-9]{64}\Z")
DEPENDENCY = re.compile(r"data-[0-9]{6}\Z")
TOKEN = "nw-input:"
BLOCKED_SUFFIXES = {".exe", ".dll", ".pyd", ".so", ".dylib", ".com", ".scr", ".msi",
                    ".py", ".pyw", ".ps1", ".bat", ".cmd", ".sh", ".vbs", ".js"}
UNSUPPORTED_TYPES = {"file", "directory", "script", "metagenomics-resource", "kraken-database", "bracken-model"}
WARNINGS = [
    "Pack binaries, private runtimes, trust settings and credentials are not included. Install the exact required packs separately.",
    "Reference receipts and sample metadata are historical project metadata, not authenticated publisher identity or a new local reference-library registration.",
    "Only explicitly bound ordinary input files are supported. Database descriptors and files naming external resources need their own portable contract.",
    "Keep new analysis results outside the imported project folder. Reopening verifies its complete inventory and rejects missing, changed or extra files.",
    "Import never executes a workflow. Review readiness before running. Linux scientific equivalence is not established by this bundle.",
]


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _json_bytes(value):
    safe_json(value)
    return (canonical(value) + "\n").encode("utf-8")


def _json(raw):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            _require(key not in result, "Duplicate project JSON field.")
            result[key] = value
        return result
    def invalid(value):
        raise ValueError("Non-finite project JSON value.")
    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=unique, parse_constant=invalid)
        safe_json(value)
        return value
    except (UnicodeError, RecursionError, TypeError) as exc:
        raise ValueError("Invalid project JSON.") from exc


def _safe_name(value):
    _require(isinstance(value, str) and "\\" not in value, "Unsafe project member path.")
    try:
        _relative(value)
    except ValueError as exc:
        raise ValueError("Unsafe project member path: " + value) from exc
    return value


def _no_links(path, *, directory=False, exists=True):
    path = Path(path).absolute()
    for part in (path, *path.parents):
        physical = _io_path(part)
        _require(not physical.is_symlink() and not (hasattr(physical, "is_junction") and physical.is_junction()),
                 "Project paths must not use symbolic links or junctions.")
    if exists:
        _require(_io_path(path).is_dir() if directory else _io_path(path).is_file(),
                 "Choose an existing ordinary project " + ("folder." if directory else "file."))
    return path


def _data_file(path):
    path = _ordinary(path)
    _require(path.suffix.lower() not in BLOCKED_SUFFIXES, "Executable or script inputs are not portable project data: " + path.name)
    with _io_path(path).open("rb") as stream:
        head = stream.read(4)
    _require(not head.startswith((b"MZ", b"\x7fELF", b"#!")), "Executable or script inputs are not portable project data: " + path.name)
    return path


def _identity(path):
    path = _data_file(path)
    before = _io_path(path).stat()
    _require(0 <= before.st_size <= MAX_FILE_BYTES, "Project input exceeds the per-file limit.")
    checksum = digest_file(path)
    after = _io_path(path).stat()
    _require((before.st_size, before.st_mtime_ns, before.st_ino) ==
             (after.st_size, after.st_mtime_ns, after.st_ino), "Project input changed while hashing.")
    return {"bytes": after.st_size, "sha256": checksum}


def _verify_data(path, expected):
    actual = _identity(path)
    _require(actual == {key: expected[key] for key in ("bytes", "sha256")},
             "Input bytes do not match the project's recorded SHA-256 and size.")


def _file_key(path):
    """One ordinary-file identity across explicit short/long or lexical aliases.

    Resolve only caller-selected paths which already exist, never infer files
    from a basename or a metadata string. The ordinary-file guard still rejects
    symbolic links and junctions before resolution.
    """
    return os.path.normcase(str(_ordinary(path)))


def _copy_verified(source, destination, expected):
    _data_file(source)
    digest, total = hashlib.sha256(), 0
    with _io_path(source).open("rb") as src, _io_path(destination).open("xb") as out:
        for block in iter(lambda: src.read(1024 * 1024), b""):
            total += len(block)
            _require(total <= expected["bytes"], "Project input changed while copying.")
            digest.update(block)
            out.write(block)
        out.flush()
        os.fsync(out.fileno())
    _require(total == expected["bytes"] and digest.hexdigest() == expected["sha256"], "Project input changed while copying.")


def _verify_stream(stream, expected, target=None):
    digest, total = hashlib.sha256(), 0
    for block in iter(lambda: stream.read(1024 * 1024), b""):
        total += len(block)
        _require(total <= expected["bytes"], "Project member expands beyond its declared size.")
        digest.update(block)
        if target is not None:
            target.write(block)
    _require(total == expected["bytes"] and digest.hexdigest() == expected["sha256"], "Project member checksum mismatch.")


def _validation_helpers(helpers, node_ids=None):
    _require(isinstance(helpers, dict) and len(helpers) <= 512 and
             all(isinstance(key, str) and re.fullmatch(r"step-[1-9][0-9]{0,8}", key) for key in helpers) and
             (node_ids is None or set(helpers) <= node_ids), "Invalid project validation helper requirements.")
    for item in helpers.values():
        _require(isinstance(item, dict) and set(item) == {"operation", "pin", "executable"} and isinstance(item["operation"], str),
                 "Malformed project validation helper.")
        _require(isinstance(item["pin"], dict) and set(item["pin"]) == {"packId", "packVersion", "manifestSha256"} and
                 all(isinstance(v, str) for v in item["pin"].values()) and SHA.fullmatch(item["pin"]["manifestSha256"]), "Invalid helper pack pin.")
        executable = item["executable"]
        _require(isinstance(executable, dict) and set(executable) == {"id", "path", "version", "sha256"} and
                 executable["id"] == "samtools" and isinstance(executable["version"], str) and
                 isinstance(executable["sha256"], str) and SHA.fullmatch(executable["sha256"]), "Invalid helper executable identity.")
        _safe_name(executable["path"])


def validate_project_metadata(value):
    """Shape validation only: Engine verifies bindings against fresh input hashes.

    Archive reference descriptions remain historical metadata even when their
    bytes match. This function neither authenticates a publisher nor registers a
    receipt in the local reference library.
    """
    _require(isinstance(value, dict) and set(value) == {"schema", "id", "manifestSha256", "sampleMetadata",
             "referencesAreHistorical", "dependencies", "validationTools"}, "Malformed historical project metadata.")
    _require(len(_json_bytes(value)) <= MAX_MANIFEST, "Historical project metadata exceeds its limit.")
    _require(type(value["schema"]) is int and value["schema"] == 1 and value["referencesAreHistorical"] is True and
             isinstance(value["id"], str) and re.fullmatch(r"[0-9a-f]{32}", value["id"]) and
             isinstance(value["manifestSha256"], str) and SHA.fullmatch(value["manifestSha256"]), "Invalid historical project identity.")
    _require(value["sampleMetadata"] is None or isinstance(value["sampleMetadata"], dict), "Invalid historical sample metadata.")
    _require(len(_json_bytes(value["sampleMetadata"])) <= MAX_METADATA, "Historical sample metadata exceeds its limit.")
    deps = value["dependencies"]
    _require(isinstance(deps, list) and len(deps) <= 2048, "Historical project data limit exceeded.")
    ids, paths = set(), set()
    for item in deps:
        _require(isinstance(item, dict) and set(item) == {"id", "bytes", "sha256", "references", "boundPath"}, "Malformed historical data identity.")
        _require(isinstance(item["id"], str) and DEPENDENCY.fullmatch(item["id"]) and item["id"] not in ids and
                 isinstance(item["boundPath"], str) and Path(item["boundPath"]).is_absolute() and
                 os.path.normcase(item["boundPath"]) not in paths and type(item["bytes"]) is int and
                 0 <= item["bytes"] <= MAX_FILE_BYTES and isinstance(item["sha256"], str) and SHA.fullmatch(item["sha256"]) and
                 isinstance(item["references"], dict), "Invalid or duplicate historical data identity.")
        ids.add(item["id"])
        paths.add(os.path.normcase(item["boundPath"]))
    _require(sum(item["bytes"] for item in deps) <= MAX_TOTAL_BYTES, "Historical project data exceeds its limit.")
    _validation_helpers(value["validationTools"])
    return copy.deepcopy(value)


def _manifest(value):
    _require(isinstance(value, dict) and set(value) == {"schema", "format", "id", "appVersion", "name", "graph",
             "dependencies", "packs", "sampleMetadata", "files", "warnings", "linuxProfile", "validationTools"}, "Malformed project manifest.")
    _require(type(value["schema"]) is int and value["schema"] == 1 and value["format"] == "native-workbench-project",
             "Unsupported project format.")
    _require(isinstance(value["id"], str) and re.fullmatch(r"[0-9a-f]{32}", value["id"]), "Invalid project identity.")
    graph = value["graph"]
    _require(isinstance(graph, dict) and isinstance(graph.get("nodes"), list) and isinstance(graph.get("sources"), list),
             "Project workflow is malformed.")
    _require(value["name"] == graph.get("name", "Native Workbench project") and isinstance(value["name"], str), "Invalid project name.")
    _require(all(isinstance(node, dict) and isinstance(node.get("tool"), str) for node in graph["nodes"]), "Invalid project tool requirement.")
    _require(isinstance(value["packs"], list) and len(value["packs"]) <= 512 and
             isinstance(value["dependencies"], list) and len(value["dependencies"]) <= 2048, "Project dependency limit exceeded.")
    deps = {}
    for item in value["dependencies"]:
        _require(isinstance(item, dict) and set(item) == {"id", "filename", "path", "bytes", "sha256", "included", "references"},
                 "Malformed project data dependency.")
        identity = item["id"]
        _require(isinstance(identity, str) and DEPENDENCY.fullmatch(identity) and identity not in deps, "Duplicate or invalid data dependency.")
        _require(_safe_name(item["path"]) == "data/" + identity + "/" + _safe_name(item["filename"]) and "/" not in item["filename"],
                 "Invalid portable input path.")
        _require(Path(item["filename"]).suffix.lower() not in BLOCKED_SUFFIXES, "Executable or script members are not project data.")
        _require(type(item["bytes"]) is int and 0 <= item["bytes"] <= MAX_FILE_BYTES and
                 isinstance(item["sha256"], str) and SHA.fullmatch(item["sha256"]) and type(item["included"]) is bool and
                 isinstance(item["references"], dict), "Invalid project input identity.")
        deps[identity] = item
    _require(sum(item["bytes"] for item in deps.values()) <= MAX_TOTAL_BYTES, "Project data limit exceeded.")
    used = set()
    for source in graph["sources"]:
        _require(isinstance(source, dict) and isinstance(source.get("files"), dict), "Invalid project workflow source.")
        _require(isinstance(source.get("type"), str) and source["type"] not in UNSUPPORTED_TYPES,
                 "This input type needs an explicit portable resource contract: " + str(source.get("type")))
        for reference in source["files"].values():
            _require(isinstance(reference, str) and reference.startswith(TOKEN) and reference[len(TOKEN):] in deps,
                     "Project workflow contains a nonportable or unknown input binding.")
            used.add(reference[len(TOKEN):])
    _require(used == set(deps), "Project dependencies do not match workflow inputs.")
    pins = {}
    for item in value["packs"]:
        _require(isinstance(item, dict) and set(item) == {"tool", "pin", "executables"} and isinstance(item["tool"], str), "Malformed project pack requirement.")
        pin = item["pin"]
        _require(isinstance(pin, dict) and set(pin) == {"packId", "packVersion", "manifestSha256"} and
                 all(isinstance(v, str) for v in pin.values()) and SHA.fullmatch(pin["manifestSha256"]), "Invalid exact pack pin.")
        key = (item["tool"], canonical(pin))
        _require(key not in pins, "Duplicate project pack requirement.")
        pins[key] = item
    _require({(node.get("tool"), canonical(node.get("pin"))) for node in graph["nodes"]} == set(pins),
             "Project pack requirements differ from the workflow's exact pins.")
    helpers = value["validationTools"]
    _validation_helpers(helpers, {node.get("id") for node in graph["nodes"]})
    files = value["files"]
    _require(isinstance(files, dict) and 1 <= len(files) < MAX_MEMBERS, "Invalid project inventory.")
    expected = {"workflow.cwl"} | {item["path"] for item in deps.values() if item["included"]}
    _require(set(files) == expected, "Project file inventory has undeclared or missing members.")
    for name, item in files.items():
        _safe_name(name)
        _require(isinstance(item, dict) and set(item) == {"bytes", "sha256"} and type(item["bytes"]) is int and
                 0 <= item["bytes"] <= MAX_FILE_BYTES and isinstance(item["sha256"], str) and SHA.fullmatch(item["sha256"]),
                 "Malformed project file inventory.")
        if name == "workflow.cwl":
            _require(item["bytes"] <= MAX_MANIFEST, "Project CWL exceeds the metadata limit.")
    for item in deps.values():
        if item["included"]:
            _require(files[item["path"]] == {key: item[key] for key in ("bytes", "sha256")}, "Project data inventory disagrees with dependency identity.")
    _require(len(_json_bytes(value["sampleMetadata"])) <= MAX_METADATA, "Project sample metadata exceeds its limit.")
    return value


def _archive(path):
    """Verify every member, CRC and SHA before exposing any import operation."""
    path = _no_links(path)
    _require(_io_path(path).stat().st_size <= MAX_TOTAL_BYTES + MAX_MANIFEST * 2, "Project archive exceeds the size limit.")
    with zipfile.ZipFile(_io_path(path)) as archive:
        members = archive.infolist()
        _require(1 <= len(members) <= MAX_MEMBERS, "Project archive member limit exceeded.")
        names, seen, total = {}, set(), 0
        for member in members:
            name = _safe_name(member.filename)
            _require(member.orig_filename == member.filename and name.casefold() not in seen, "Duplicate or case-colliding project member.")
            seen.add(name.casefold())
            mode = member.external_attr >> 16
            _require(not member.is_dir() and (not stat.S_IFMT(mode) or stat.S_ISREG(mode)) and not member.flag_bits & 1,
                     "Project members must be unencrypted ordinary files.")
            _require(member.compress_type in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED), "Unsupported project compression.")
            _require(0 <= member.file_size <= MAX_FILE_BYTES and member.file_size <= max(1024 * 1024, member.compress_size * MAX_RATIO),
                     "Project member exceeds size or compression limits.")
            total += member.file_size
            _require(total <= MAX_TOTAL_BYTES + MAX_MANIFEST * 2, "Project expanded data exceeds the size limit.")
            names[name] = member
        _require("project.json" in names and names["project.json"].file_size <= MAX_MANIFEST, "Missing or oversized project manifest.")
        document = _manifest(_json(archive.read("project.json")))
        _require(set(names) == {"project.json"} | set(document["files"]), "Archive inventory differs from the complete project inventory.")
        for name, expected in document["files"].items():
            _require(names[name].file_size == expected["bytes"], "Project member size mismatch.")
            with archive.open(name) as stream:
                if name != "workflow.cwl":
                    _require(not stream.read(4).startswith((b"MZ", b"\x7fELF", b"#!")), "Executable or script members are not project data.")
                    stream.seek(0)
                _verify_stream(stream, expected)
    return document


class ProjectManager:
    def __init__(self, engine):
        self.engine = engine

    def _packs(self, manifest):
        result = []
        expected_helpers = set()
        for item in manifest["packs"]:
            row = {"tool": item["tool"], "pin": copy.deepcopy(item["pin"]), "status": "available", "message": "Exact installed pack verified."}
            try:
                tool = self.engine._tool({"tool": item["tool"], "pin": item["pin"]})
                self._verify_pack(tool)
                _require(item["executables"] == self._programs(tool), "Executable requirements differ from the exact installed pack.")
                if self.engine._alignment_ports(tool):
                    expected_helpers.update(node["id"] for node in manifest["graph"]["nodes"]
                                            if node["tool"] == item["tool"] and node["pin"] == item["pin"])
            except (OSError, ValueError) as exc:
                row.update(status="missing-or-incompatible", message=str(exc))
            result.append(row)
        for node_id, item in manifest["validationTools"].items():
            row = {"tool": item["operation"], "pin": copy.deepcopy(item["pin"]), "helperFor": node_id,
                   "status": "available", "message": "Exact scientific-preflight SAMtools helper verified."}
            try:
                tool = self.engine._tool({"tool": item["operation"], "pin": item["pin"]})
                self._verify_pack(tool)
                _require(item["executable"] in tool.get("executables", []), "Exact validation helper executable differs.")
            except (OSError, ValueError) as exc:
                row.update(status="missing-or-incompatible", message=str(exc))
            result.append(row)
        if set(manifest["validationTools"]) != expected_helpers and all(row["status"] == "available" for row in result):
            result.append({"tool": "scientific-preflight", "pin": {}, "status": "missing-or-incompatible",
                           "message": "Project validation helper requirements differ from its scientific operations."})
        return result

    @staticmethod
    def _programs(tool):
        return [{key: item[key] for key in ("id", "version", "sha256")} for item in tool.get("executables", [])]

    def _verify_pack(self, tool):
        self.engine._verify_manifest(tool)
        if tool.get("builtin"):
            return
        folder = self.engine.app_root / tool["packFolder"]
        pack = parse_pack(_io_path(folder / "pack.ini").read_text(encoding="utf-8-sig"))
        for item in list(pack["tools"].values()) + list(pack["assets"].values()):
            path = _ordinary(folder / item["path"])
            _require(digest_file(path) == item["sha256"], "Exact installed pack file changed: " + item["path"])

    def export_preview(self, graph, include_data=False, sample_metadata=None, project_metadata=None,
                       reference_metadata=None, validation_tools=None):
        graph = copy.deepcopy(graph)
        review = self.engine.validate(graph)
        _require(review["ok"], "; ".join(item["message"] for item in review["errors"]))
        _require(sample_metadata is None or isinstance(sample_metadata, dict), "Sample metadata must be an explicit JSON object.")
        _require(len(_json_bytes(sample_metadata)) <= MAX_METADATA, "Project sample metadata exceeds its limit.")
        graph = {key: value for key, value in graph.items() if key in ("schema", "name", "nextNode", "nextSource", "nodes", "sources")}
        if project_metadata is not None:
            project_metadata = validate_project_metadata(project_metadata)
        historical = {}
        for item in (project_metadata or {}).get("dependencies", []):
            key = _file_key(item["boundPath"])
            _require(key not in historical, "Historical project metadata contains duplicate aliases for one input file.")
            historical[key] = item
        reference_metadata = {} if reference_metadata is None else copy.deepcopy(reference_metadata)
        _require(isinstance(reference_metadata, dict) and len(_json_bytes(reference_metadata)) <= MAX_MANIFEST, "Invalid historical reference metadata.")
        reference_identities = {}
        for path, receipt in reference_metadata.items():
            key = _file_key(path)
            _require(key not in reference_identities, "Historical reference metadata contains duplicate aliases for one input file.")
            reference_identities[key] = receipt
        if validation_tools is not None:
            _validation_helpers(validation_tools, {node["id"] for node in graph["nodes"]})
        deps, paths, by_path, pack_rows, frozen, helpers, aliases = [], {}, {}, {}, [], {}, {}
        for node in graph["nodes"]:
            tool = self.engine._tool(node)
            self._verify_pack(tool)
            node["pin"] = pin_for(tool)
            node["params"] = {p["id"]: _parameter(p, node.get("params", {}).get(p["id"], _field_default(p))) for p in tool.get("params", [])}
            for key in list(node):
                if key not in ("id", "tool", "pin", "params", "inputs", "label"):
                    del node[key]
            pack_rows[(node["tool"], canonical(node["pin"]))] = {"tool": node["tool"], "pin": copy.deepcopy(node["pin"]), "executables": self._programs(tool)}
            if self.engine._alignment_ports(tool):
                recorded = (validation_tools if validation_tools is not None else (project_metadata or {}).get("validationTools", {})).get(node["id"])
                _require(validation_tools is None or recorded is not None, "Recorded result is missing its exact validation helper.")
                helpers[node["id"]] = copy.deepcopy(recorded if recorded is not None else self.engine._samtools_selection(tool))
            frozen.append({"id": node["id"], "tool": copy.deepcopy(tool), "params": node["params"],
                           "label": node.get("label") or tool["name"], "inputs": node.get("inputs", {})})
        used = {ref for node in graph["nodes"] for refs in node.get("inputs", {}).values() for ref in refs if "::" not in ref}
        graph["sources"] = [source for source in graph["sources"] if source["id"] in used]
        for source in graph["sources"]:
            _require(source["type"] not in UNSUPPORTED_TYPES,
                     "This input type needs an explicit portable resource contract: " + source["type"])
            for key in list(source):
                if key not in ("id", "type", "label", "files", "fields", "state"):
                    del source[key]
            for field in source.get("fields", []):
                field["default"] = ""
            for field, original in source["files"].items():
                path = _data_file(original)
                key = os.path.normcase(str(path))
                if key not in by_path:
                    identity = "data-" + str(len(deps) + 1).zfill(6)
                    filename = _safe_name(path.name)
                    item = {"id": identity, "filename": filename, "path": "data/" + identity + "/" + filename,
                            **_identity(path), "included": False, "references": {}}
                    refs = collect_references(self.engine.app_root, [str(path)], evidence={str(path): item})
                    item["references"] = refs.get(str(path), {})
                    if key in historical:
                        previous = historical[key]
                        _require(all(previous.get(k) == item[k] for k in ("bytes", "sha256")), "Imported project input changed since its historical identity was recorded.")
                        item["references"] = copy.deepcopy(previous.get("references", {}))
                    if key in reference_identities:
                        previous = reference_identities[key]
                        _require(isinstance(previous, dict) and isinstance(previous.get("file"), dict) and
                                 previous["file"].get("sha256") == item["sha256"], "Historical reference receipt differs from the selected input bytes.")
                        item["references"] = copy.deepcopy(previous)
                    item["references"].pop("receipt_path", None)
                    if isinstance(item["references"].get("file"), dict):
                        item["references"]["file"].pop("path", None)
                    deps.append(item)
                    by_path[key] = identity
                    paths[identity] = str(path)
                for alias in (original, str(Path(original).absolute()), str(path)):
                    aliases[os.path.normcase(alias)] = TOKEN + by_path[key]
                source["files"][field] = TOKEN + by_path[key]
        selected = {item["id"] for item in deps} if include_data is True else set()
        if isinstance(include_data, list):
            _require(all(isinstance(value, str) for value in include_data) and len(include_data) == len(set(include_data)), "Invalid selected project inputs.")
            selected = set(include_data)
        else:
            _require(type(include_data) is bool, "Choose whether to bundle data or select explicit dependency IDs.")
        _require(selected <= set(paths), "Unknown selected project data dependency.")
        for item in deps:
            item["included"] = item["id"] in selected
        # Mapped sample-table columns may contain original absolute input paths.
        # Preserve their relation to the data without retaining machine paths.
        def portable_metadata(value):
            if isinstance(value, dict):
                return {key: portable_metadata(item) for key, item in value.items()}
            if isinstance(value, list):
                return [portable_metadata(item) for item in value]
            if isinstance(value, str):
                return aliases.get(os.path.normcase(value), value)
            return value
        sample_metadata = portable_metadata(sample_metadata)
        manifest = {"schema": 1, "format": "native-workbench-project", "id": uuid.uuid4().hex,
                    "appVersion": APP_VERSION, "name": graph.get("name", "Native Workbench project"), "graph": graph,
                    "dependencies": deps, "packs": list(pack_rows.values()), "sampleMetadata": copy.deepcopy(sample_metadata),
                    "validationTools": helpers,
                    "files": {}, "warnings": list(WARNINGS),
                    "linuxProfile": {"schema": 1, "status": "requires-explicit-compatible-executables",
                                     "scientificEquivalenceValidated": False, "engine": "CWL v1.2", "python": "3.10+",
                                     "packRequirement": "Exact original manifests and assets; explicit executable overrides change binary identity.",
                                     "executablesBundled": False}}
        # Export the same standard CWL command contracts, but remove original
        # machine paths and make data defaults relative to this project folder.
        plan = {"id": "project-" + manifest["id"], "graph": graph, "nodes": frozen, "references": {}, "inputs": {},
                "scheduler": "external-CWL-engine", "batch": sample_metadata} if sample_metadata else {
                "id": "project-" + manifest["id"], "graph": graph, "nodes": frozen, "references": {}, "inputs": {}, "scheduler": "external-CWL-engine"}
        workflow = export_workflow(plan, self.engine.app_root)
        main = workflow["$graph"][0]
        for entry in main["inputs"].values():
            if "nw:source" in entry:
                source = json.loads(entry["nw:source"])
                slot = next(s for s in graph["sources"] if s["id"] == source["id"])
                dep = next(d for d in deps if TOKEN + d["id"] == slot["files"][source["field"]])
                entry["default"] = {"class": "File", "location": quote(dep["path"], safe="/"), "basename": dep["filename"]}
                source["evidence"] = {key: dep[key] for key in ("bytes", "sha256")}
                entry["nw:source"] = canonical(source)
            elif entry.get("type") == "Directory":
                entry.pop("default", None)
        cwl = _json_bytes(workflow)
        manifest["files"] = {"workflow.cwl": {"bytes": len(cwl), "sha256": hashlib.sha256(cwl).hexdigest()}}
        for item in deps:
            if item["included"]:
                manifest["files"][item["path"]] = {key: item[key] for key in ("bytes", "sha256")}
        _manifest(manifest)
        _require(all(row["status"] == "available" for row in self._packs(manifest)), "An exact scientific-preflight helper requirement is unavailable.")
        _require(len(_json_bytes(manifest)) <= MAX_MANIFEST, "Project manifest exceeds its limit.")
        return {"manifest": manifest, "paths": paths, "cwl": workflow, "summary": {
            "name": manifest["name"], "dependencies": copy.deepcopy(deps), "packs": self._packs(manifest),
            "includedBytes": sum(item["bytes"] for item in deps if item["included"]),
            "sampleMetadataIncluded": sample_metadata is not None, "warnings": list(WARNINGS)}}

    def export(self, preview, destination):
        manifest = _manifest(copy.deepcopy(preview["manifest"]))
        _require(all(row["status"] == "available" for row in self._packs(manifest)), "Project pack requirements changed after preview.")
        destination = _no_links(destination, exists=False)
        _no_links(destination.parent, directory=True)
        _require(not _io_path(destination).exists(), "Choose a new project archive; existing files are preserved.")
        cwl = _json_bytes(preview["cwl"])
        _require(manifest["files"]["workflow.cwl"] == {"bytes": len(cwl), "sha256": hashlib.sha256(cwl).hexdigest()}, "Project CWL changed after preview.")
        temporary = destination.with_name(".nw-project-" + uuid.uuid4().hex + ".tmp")
        needed = sum(item["bytes"] for item in manifest["files"].values()) + len(_json_bytes(manifest)) + 1024 * 1024
        _require(shutil.disk_usage(_io_path(destination.parent)).free >= 2 * needed, "Not enough free space to write and verify this project archive.")
        created = False
        try:
            with zipfile.ZipFile(_io_path(temporary), "x", compression=zipfile.ZIP_STORED, allowZip64=True) as archive:
                archive.writestr("project.json", _json_bytes(manifest))
                archive.writestr("workflow.cwl", cwl)
                for item in manifest["dependencies"]:
                    source = preview["paths"][item["id"]]
                    _verify_data(source, item)
                    if item["included"]:
                        with _io_path(source).open("rb") as stream, archive.open(item["path"], "w", force_zip64=True) as target:
                            _verify_stream(stream, item, target)
            _archive(temporary)
            # Exclusive copy is deliberate: replace/rename can overwrite a file
            # created by another process after the review, especially on POSIX.
            with _io_path(temporary).open("rb") as src, _io_path(destination).open("xb") as out:
                created = True
                shutil.copyfileobj(src, out, 1024 * 1024)
                out.flush()
                os.fsync(out.fileno())
        except BaseException:
            if created:
                _io_path(destination).unlink(missing_ok=True)
            raise
        finally:
            _io_path(temporary).unlink(missing_ok=True)
        return {"path": str(destination), "sha256": digest_file(destination), "bytes": _io_path(destination).stat().st_size,
                "dependencies": len(manifest["dependencies"])}

    def preview_import(self, archive, mappings=None):
        archive = _no_links(archive)
        before = digest_file(archive)
        document = _archive(archive)
        _require(digest_file(archive) == before, "Project archive changed during inspection.")
        mappings = {} if mappings is None else copy.deepcopy(mappings)
        _require(isinstance(mappings, dict) and set(mappings) <= {item["id"] for item in document["dependencies"]} and
                 all(isinstance(value, str) for value in mappings.values()), "Map project dependency IDs to explicit local file paths.")
        rows = []
        for item in document["dependencies"]:
            row = {key: copy.deepcopy(item[key]) for key in ("id", "filename", "bytes", "sha256", "included", "references")}
            row.update(status="bundled" if item["included"] else "missing", message="Verified bundled file." if item["included"] else "Choose the original file or a byte-identical relocated copy.")
            if item["id"] in mappings:
                try:
                    _verify_data(mappings[item["id"]], item)
                    row.update(status="mapped", message="Explicitly selected local file matches the original bytes.")
                except (ValueError, OSError) as exc:
                    row.update(status="mismatch", message=str(exc))
            rows.append(row)
        packs = self._packs(document)
        ready = all(row["status"] in ("bundled", "mapped") for row in rows) and all(row["status"] == "available" for row in packs)
        validation = self.engine.validate(document["graph"], check_files=False)
        ready = ready and validation["ok"]
        return {"archive": str(archive), "archiveSha256": before, "manifest": document, "mappings": mappings,
                "summary": {"name": document["name"], "ready": ready, "dependencies": rows, "packs": packs,
                            "validation": validation, "sampleMetadataIncluded": document["sampleMetadata"] is not None,
                            "warnings": list(WARNINGS)}}

    def import_project(self, preview, destination_folder):
        _require(digest_file(preview["archive"]) == preview["archiveSha256"], "Project archive changed since preview.")
        current = self.preview_import(preview["archive"], preview["mappings"])
        _require(current["archiveSha256"] == preview["archiveSha256"] and current["summary"]["ready"], "Resolve every missing or incompatible dependency before import.")
        destination = _no_links(destination_folder, exists=False)
        _no_links(destination.parent, directory=True)
        _require(not _io_path(destination).exists(), "Choose a new project folder; existing files are preserved.")
        needed = sum(item["bytes"] for item in current["manifest"]["dependencies"]) + MAX_MANIFEST * 2
        _require(shutil.disk_usage(_io_path(destination.parent)).free >= needed, "Not enough free space for the imported project data.")
        stage = Path(tempfile.mkdtemp(prefix=".nw-project-", dir=_io_path(destination.parent)))
        document = copy.deepcopy(current["manifest"])
        try:
            with zipfile.ZipFile(_io_path(current["archive"])) as archive:
                for name, expected in document["files"].items():
                    target = stage / name
                    _io_path(target.parent).mkdir(parents=True, exist_ok=True)
                    with archive.open(name) as src, _io_path(target).open("xb") as out:
                        _verify_stream(src, expected, out)
                for item in document["dependencies"]:
                    if not item["included"]:
                        target = stage / item["path"]
                        _io_path(target.parent).mkdir(parents=True, exist_ok=True)
                        _copy_verified(current["mappings"][item["id"]], target, item)
                        item["included"] = True
                        document["files"][item["path"]] = {key: item[key] for key in ("bytes", "sha256")}
            # Keep the imported workflow relative on disk. Absolute paths exist
            # only in the explicitly opened in-memory draft.
            _io_path(stage / "project.json").write_bytes(_json_bytes(document))
            self.open_project(stage)
            _require(not _io_path(destination).exists(), "The requested new project folder already exists.")
            # A target folder is reserved exclusively before moving members; no
            # existing directory can be replaced by rename's POSIX semantics.
            _io_path(destination).mkdir()
            try:
                for child in _io_path(stage).iterdir():
                    os.rename(child, _io_path(destination / child.name))
            except BaseException:
                shutil.rmtree(_io_path(destination))
                raise
        finally:
            shutil.rmtree(_io_path(stage), ignore_errors=True)
        return self.open_project(destination)

    def open_project(self, folder):
        folder = _no_links(folder, directory=True)
        manifest_file = _no_links(folder / "project.json")
        _require(_io_path(manifest_file).stat().st_size <= MAX_MANIFEST, "Project manifest exceeds its limit.")
        document = _manifest(_json(_io_path(manifest_file).read_bytes()))
        _require(all(item["included"] for item in document["dependencies"]), "This project still needs its external data resolved through import.")
        actual = set()
        for root, directories, files in os.walk(_io_path(folder), followlinks=False):
            for child in directories:
                _no_links(Path(root) / child, directory=True)
            for child in files:
                path = _no_links(Path(root) / child)
                # Use lexical paths for extended Windows namespace consistency.
                actual.add(path.relative_to(_io_path(folder)).as_posix())
        _require(actual == {"project.json"} | set(document["files"]), "The project folder has missing or unlisted files; keep analysis results outside it.")
        for name, expected in document["files"].items():
            path = _no_links(folder / name)
            _require(_io_path(path).stat().st_size == expected["bytes"] and digest_file(path) == expected["sha256"], "Local project file changed: " + name)
        graph = copy.deepcopy(document["graph"])
        deps = {item["id"]: item for item in document["dependencies"]}
        for source in graph["sources"]:
            for field, reference in source["files"].items():
                source["files"][field] = str(folder / deps[reference[len(TOKEN):]]["path"])
        packs = self._packs(document)
        _require(all(row["status"] == "available" for row in packs), "An exact project pack is missing or incompatible; install it without changing the saved pins.")
        review = self.engine.validate(graph)
        _require(review["ok"], "; ".join(item["message"] for item in review["errors"]))
        manifest_hash = digest_file(manifest_file)
        context = {"schema": 1, "id": document["id"], "manifestSha256": manifest_hash,
                   "sampleMetadata": copy.deepcopy(document["sampleMetadata"]), "referencesAreHistorical": True,
                   "validationTools": copy.deepcopy(document["validationTools"]),
                   "dependencies": [{key: copy.deepcopy(item[key]) for key in ("id", "bytes", "sha256", "references")} |
                                    {"boundPath": str(folder / item["path"])} for item in document["dependencies"]]}
        return {"folder": str(folder), "graph": graph, "sampleMetadata": copy.deepcopy(document["sampleMetadata"]),
                "manifestSha256": manifest_hash, "projectMetadata": context, "packs": packs, "warnings": list(WARNINGS)}
