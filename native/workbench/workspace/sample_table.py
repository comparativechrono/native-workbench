"""Bounded local sample tables and explicitly mapped, independent graph copies.

This module does not run or queue an analysis and never guesses mate filenames,
biological independence, pooling or cohort membership. The caller must show the
preview and freeze every accepted graph with Engine.prepare before execution.
"""
from __future__ import annotations

import copy
import csv
import hashlib
import io
import os
from pathlib import Path
import re

try:
    from .engine import _io_path, _ordinary, _resolved_path, clean_text, pin_for, safe_json
except ImportError:
    from engine import _io_path, _ordinary, _resolved_path, clean_text, pin_for, safe_json

MAX_TABLE_BYTES = 8 * 1024 * 1024
MAX_ROWS = 1000
METRICS_TYPES = {"metrics", "text"}
MAX_COLUMNS = 64
MAX_CELL = 4096
MAX_EXPANDED_BYTES = 32 * 1024 * 1024
MAX_SAMPLE_METADATA_BYTES = 16 * 1024
COLUMN = re.compile(r"[A-Za-z][A-Za-z0-9_.-]{0,63}\Z")
SAMPLE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}\Z")
REFERENCE_TYPES = {"reference", "reference-index"}
NEVER_SHARED_TYPES = {"pair", "reads", "sam", "bam", "sam-rna", "bam-rna",
                      "vcf", "vcf-pass", "bcf", "bcf-likelihoods"}


def _directory(value):
    if value is None:
        return None
    path = Path(value)
    if not path.is_absolute() or not _io_path(path).is_dir():
        raise ValueError("Select an existing absolute folder for relative sample-table paths.")
    for item in [path, *path.parents]:
        physical = _io_path(item)
        if physical.is_symlink() or (hasattr(physical, "is_junction") and physical.is_junction()):
            raise ValueError("Sample-table folders must not use symbolic links or junctions.")
    return str(_resolved_path(path))


def parse_table(content, *, delimiter=None, base_directory=None):
    """Parse UTF-8 CSV/TSV. Relative file cells need an explicit base folder.

    Column names are case-sensitive and explicit; case-only duplicate headers
    and sample identifiers are rejected to avoid ambiguity on Windows. Row data
    stay as text, including condition/replicate and third-party metadata columns.
    No file cell is interpreted until the user supplies its binding.
    """
    if isinstance(content, str):
        try:
            raw = content.encode("utf-8")
        except UnicodeError as exc:
            raise ValueError("The sample table must be UTF-8 text.") from exc
    elif isinstance(content, bytes):
        raw = content
    else:
        raise ValueError("The sample table must be UTF-8 text.")
    if len(raw) > MAX_TABLE_BYTES:
        raise ValueError("The sample table exceeds the 8 MiB limit.")
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeError as exc:
        raise ValueError("The sample table must be UTF-8 text.") from exc
    if not text or "\0" in text:
        raise ValueError("Choose a non-empty CSV or TSV sample table without NUL characters.")
    if delimiter is None:
        # Only inspect the actual parsed first record in each supported dialect.
        # Sniffer's probabilistic field guessing is inappropriate for file roles.
        candidates = []
        for candidate in (",", "\t"):
            try:
                header = next(csv.reader(io.StringIO(text, newline=""), delimiter=candidate, strict=True))
            except (csv.Error, StopIteration):
                continue
            if "sample_id" in header:
                candidates.append(candidate)
        if len(candidates) == 2 and candidates:
            # A one-column sample_id table has the same interpretation in either
            # dialect. It is valid metadata but cannot bind a file column.
            first_line = text.splitlines()[0].lstrip("\ufeff")
            if first_line in ("sample_id", '"sample_id"'):
                delimiter = ","
            else:
                raise ValueError("Choose CSV or TSV explicitly; the header is ambiguous.")
        elif len(candidates) == 1:
            delimiter = candidates[0]
        else:
            raise ValueError("The sample table needs a sample_id column and a CSV or TSV header.")
    if delimiter not in (",", "\t"):
        raise ValueError("Only comma-separated CSV and tab-separated TSV tables are supported.")
    try:
        reader = csv.reader(io.StringIO(text, newline=""), delimiter=delimiter, strict=True)
        columns = next(reader)
        if not 1 <= len(columns) <= MAX_COLUMNS:
            raise ValueError("The sample table must contain 1–64 columns.")
        if any(not COLUMN.fullmatch(name) for name in columns):
            raise ValueError("Column names must use letters, digits, underscores, hyphens or dots, with no surrounding spaces.")
        if len({name.casefold() for name in columns}) != len(columns):
            raise ValueError("The sample table has duplicated or case-ambiguous column names.")
        if "sample_id" not in columns:
            raise ValueError("The sample table needs an exact sample_id column.")
        rows, identities = [], set()
        for index, values in enumerate(reader, 2):
            if len(rows) >= MAX_ROWS:
                raise ValueError("The sample table exceeds the 1,000 sample limit.")
            if len(values) != len(columns):
                raise ValueError(f"Sample row {index} has {len(values)} fields; the header has {len(columns)}.")
            if any(not clean_text(value, MAX_CELL) for value in values):
                raise ValueError(f"Sample row {index} has an oversized cell or control characters.")
            row = dict(zip(columns, values))
            identity = row["sample_id"]
            if not SAMPLE_ID.fullmatch(identity):
                raise ValueError(f"Sample row {index} needs a sample_id of 1–128 letters, digits, underscores, hyphens or dots, starting with a letter or digit.")
            if identity.casefold() in identities:
                raise ValueError("Sample identifiers must be unique, including letter case: " + identity)
            identities.add(identity.casefold())
            rows.append(row)
        if not rows:
            raise ValueError("The sample table has no samples.")
    except csv.Error as exc:
        raise ValueError("The sample table has invalid CSV/TSV quoting.") from exc
    return {"schema": 1, "columns": columns, "rows": rows, "delimiter": delimiter,
            "baseDirectory": _directory(base_directory), "sha256": hashlib.sha256(raw).hexdigest()}


def read_table(path):
    """Read one explicitly selected ordinary file, with a bounded byte read."""
    path = _ordinary(path)
    with open(_io_path(path), "rb") as stream:
        raw = stream.read(MAX_TABLE_BYTES + 1)
    extension = path.suffix.lower()
    delimiter = "\t" if extension == ".tsv" else "," if extension == ".csv" else None
    return parse_table(raw, delimiter=delimiter, base_directory=path.parent)


def _validated_table(table):
    # Tables also arrive through IPC. Revalidate the supplied object rather than
    # trusting a prior parser call, and keep a strict total serialised bound.
    import json
    safe_json(table)
    if not isinstance(table, dict) or table.get("schema") != 1:
        raise ValueError("Unsupported sample-table schema.")
    columns, rows = table.get("columns"), table.get("rows")
    if not isinstance(columns, list) or not isinstance(rows, list):
        raise ValueError("A sample table needs named columns and rows.")
    if not 1 <= len(rows) <= MAX_ROWS or not 1 <= len(columns) <= MAX_COLUMNS:
        raise ValueError("Sample-table row or column limits were exceeded.")
    if any(not isinstance(row, dict) or set(row) != set(columns) for row in rows):
        raise ValueError("Every sample row must contain exactly the declared columns.")
    if len(json.dumps(table, ensure_ascii=False).encode("utf-8")) > MAX_TABLE_BYTES * 2:
        raise ValueError("The sample-table object exceeds its supported size.")
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(columns)
    for row in rows:
        if any(not isinstance(value, str) for value in row.values()):
            raise ValueError("Sample-table cells must be text.")
        writer.writerow([row[name] for name in columns])
    checked = parse_table(output.getvalue(), delimiter=",", base_directory=table.get("baseDirectory"))
    digest = table.get("sha256")
    if not isinstance(digest, str) or not re.fullmatch(r"[a-f0-9]{64}", digest):
        raise ValueError("The sample table has no valid source checksum.")
    # The parsed object is editable data, not authenticated evidence. This digest
    # identifies the originally imported bytes; accepted row metadata is frozen
    # separately in queue records and never verified using this import digest.
    checked["sha256"] = digest
    return checked


def binding_targets(engine, graph):
    """Describe explicit source fields and per-step parameters for a mapping UI.

    Existing legacy single-field bindings keep their original keys. A legacy
    pair is always two complete, named roles; no file-order guessing is used.
    """
    nodes, sources = engine._structure(graph)
    result, parameter_targets, combined_targets = [], [], []
    consumers = {identity: [] for identity in sources}
    for node in nodes.values():
        tool = engine._tool(node)
        for parameter in tool.get("params", []):
            parameter_targets.append({"nodeId": node["id"], "parameterId": parameter["id"],
                                      "label": parameter.get("label", parameter["id"]),
                                      "type": parameter.get("type", "text"),
                                      "binding": bool(parameter.get("binding")),
                                      "value": node.get("params", {}).get(parameter["id"], "")})
        for port in tool.get("ports", []):
            fields = port.get("fields", [])
            if port.get("type") in METRICS_TYPES and int(port.get("max", 1)) > 1 and len(fields) == 1 and fields[0].get("type") in ("file", "files"):
                combined_targets.append({"nodeId": node["id"], "portId": port["id"],
                                         "fieldId": fields[0]["id"], "type": port["type"],
                                         "label": tool.get("name", node["tool"]) + " · " + port.get("label", port["id"]),
                                         "min": int(port.get("min", 1)), "max": int(port.get("max", 1))})
            for identity in node.get("inputs", {}).get(port["id"], []):
                if identity in sources:
                    consumers[identity].append(port)
    for identity, source in sources.items():
        ports = consumers[identity]
        if not ports:
            continue
        fields = source.get("fields")
        files = source.get("files", {})
        if fields:
            if not isinstance(fields, list) or any(not isinstance(field, dict) for field in fields):
                raise ValueError("Workflow input field metadata must be a list of named fields.")
            fields = copy.deepcopy(fields)
        elif source.get("type") == "pair":
            if set(files) == {"read1", "read2"}:
                names = ("read1", "read2")
            elif not files or set(files) == {"reads1", "reads2"}:
                names = ("reads1", "reads2")
            else:
                raise ValueError("A legacy paired input needs explicit read1/read2 field roles before sample mapping.")
            fields = [{"id": name, "type": "file", "role": role, "label": role}
                      for name, role in zip(names, ("read1", "read2"))]
        elif len(files) == 1:
            name = next(iter(files))
            fields = [{"id": name, "type": "file", "label": name}]
        else:
            schemas = [[field for field in port.get("fields", []) if field.get("type") in ("file", "files", "directory")] for port in ports]
            if not schemas or any(len(fields) != 1 for fields in schemas):
                raise ValueError("This workflow input needs an explicit field schema before sample mapping: " + identity)
            names = {fields[0]["id"] for fields in schemas}
            if len(names) != 1:
                raise ValueError("This unbound shared input has ambiguous field names; bind or define it explicitly first: " + identity)
            fields = copy.deepcopy(schemas[0])
        if not fields or len({field.get("id") for field in fields}) != len(fields):
            raise ValueError("Workflow inputs need distinct named file fields.")
        if source.get("type") == "pair":
            roles = {field.get("role"): field.get("id") for field in fields}
            if set(roles) != {"read1", "read2"} or len(fields) != 2:
                # Existing manifests sometimes omit the role property but use
                # the canonical pair field names. Their names are unambiguous.
                names = {field.get("id") for field in fields}
                if names not in ({"reads1", "reads2"}, {"read1", "read2"}):
                    raise ValueError("Paired input fields must identify read 1 and read 2 explicitly.")
                for field in fields:
                    field["role"] = "read1" if field["id"] in ("read1", "reads1") else "read2"
        for field in fields:
            if not isinstance(field.get("id"), str) or not clean_text(field["id"], 128):
                raise ValueError("A workflow input has an invalid field identifier.")
            result.append({"sourceId": identity, "fieldId": field["id"],
                           "label": source.get("label", identity) + " · " + field.get("label", field["id"]),
                           "type": field.get("type", "file"), "sourceType": source.get("type"),
                           "role": field.get("role", ""), "value": files.get(field["id"], ""),
                           "shared": source.get("type") in REFERENCE_TYPES})
    return {"files": result, "parameters": parameter_targets, "combined": combined_targets}


def _file_path(value, base_directory):
    if not value or value != value.strip() or not clean_text(value, MAX_CELL):
        raise ValueError("Choose a non-empty file path without surrounding spaces.")
    path = Path(value)
    if not path.is_absolute():
        if base_directory is None:
            raise ValueError("Relative file paths need the selected sample table's folder.")
        path = Path(base_directory) / path
    return _ordinary(path)


def _verify_pins(engine, nodes):
    for node in nodes.values():
        pin = node.get("pin")
        actual = pin_for(engine._tool(node))
        # Historical saved graphs omit packId but already pin the exact version
        # and manifest. Retain them as-is; resolving the tool verifies identity.
        required = ("packVersion", "manifestSha256")
        if not isinstance(pin, dict) or any(pin.get(key) != actual[key] for key in required) or ("packId" in pin and pin["packId"] != actual["packId"]):
            raise ValueError("Every batch step must retain its exact installed pack pin. Review and save the workflow first: " + node["id"])


def _metadata_size(metadata):
    import json
    wrapper = {"batchId": "0" * 32, "sampleId": metadata["sampleId"], "metadata": metadata}
    if len(json.dumps(wrapper, ensure_ascii=False, separators=(",", ":")).encode("utf-8")) > MAX_SAMPLE_METADATA_BYTES:
        raise ValueError("Sample metadata exceeds the 16 KiB limit per queued job. Use a smaller combined-report table or shorten metadata cells; no sample metadata is discarded automatically.")


def preview_batch(engine, graph, table, bindings, *, parameter_bindings=None,
                  shared_sources=None, mode="independent", combined_target=None):
    """Return an all-row review; valid is false if any binding/sample is unsafe.

    bindings: [{sourceId, fieldId, column, shared?: bool}]. A shared mapping must
    contain the same ordinary file in every row. Reference inputs may be reused
    between rows; other reuse needs explicit shared=true/shared_sources consent.
    parameter_bindings: [{nodeId, parameterId, column}] for sample IDs/conditions.
    Existing connected non-reference fields cannot silently carry over. Shared
    references retain the original graph binding and provenance lookup identity.
    Combined mode instead takes combined_target={nodeId,portId,column} and empty
    mapping lists, and constructs one explicit many-valued report job. Imported
    metadata is bounded to 16 KiB per job, never truncated or silently omitted.
    """
    import json
    result = {"schema": 1, "mode": mode, "valid": False, "errors": [], "warnings": [],
              "sampleCount": 0, "samples": [], "notice": "Each sample is an independent analysis. No reads are pooled and no cohort analysis is inferred. Input hashes and final checks are recorded during preparation."}

    def fail(message, **details):
        result["errors"].append(dict(message=message, **details))

    if mode == "combined":
        return _preview_combined(engine, graph, table, bindings, parameter_bindings, shared_sources, combined_target, result)
    try:
        if combined_target is not None:
            raise ValueError("A combined-report target is only valid in combined mode.")
        if mode != "independent":
            raise ValueError("Sample-table expansion supports independent analyses only. Build an explicit pooling or cohort workflow with the required pack inputs; samples are never combined automatically.")
        table = _validated_table(table)
        targets = binding_targets(engine, graph)
        nodes, sources = engine._structure(graph)
        _verify_pins(engine, nodes)
        fields = {(target["sourceId"], target["fieldId"]): target for target in targets["files"]}
        parameters = {(target["nodeId"], target["parameterId"]): target for target in targets["parameters"]}
        if not isinstance(bindings, list) or not 1 <= len(bindings) <= MAX_COLUMNS:
            raise ValueError("Choose 1–64 explicit file-column bindings.")
        parameter_bindings = [] if parameter_bindings is None else parameter_bindings
        shared_sources = [] if shared_sources is None else shared_sources
        if not isinstance(parameter_bindings, list) or len(parameter_bindings) > 512:
            raise ValueError("Too many parameter-column bindings.")
        if not isinstance(shared_sources, list) or any(not isinstance(value, str) or value not in sources for value in shared_sources) or len(set(shared_sources)) != len(shared_sources):
            raise ValueError("Shared input selections must name distinct existing workflow sources.")
        for identity in shared_sources:
            if sources[identity].get("type") in NEVER_SHARED_TYPES:
                raise ValueError("Reads and sample result inputs cannot be shared across independent sample rows: " + identity)
        bound, parameter_bound, used_columns = {}, {}, {}
        for binding in bindings:
            if not isinstance(binding, dict) or set(binding) - {"sourceId", "fieldId", "column", "shared"}:
                raise ValueError("Each file binding needs a sourceId, fieldId and column.")
            key = (binding.get("sourceId"), binding.get("fieldId"))
            column = binding.get("column")
            if any(not isinstance(value, str) for value in key) or key not in fields or not isinstance(column, str) or column not in table["columns"]:
                raise ValueError("A file binding names an unknown workflow field or table column.")
            if fields[key]["type"] not in ("file", "files"):
                raise ValueError("One table cell binds one file. Directory inputs require an explicit workflow outside sample-table expansion.")
            if key in bound:
                raise ValueError("A workflow field cannot be mapped twice.")
            if column in used_columns:
                raise ValueError("A file column cannot fill multiple workflow fields. Share one workflow input with multiple tools instead: " + column)
            if column in {"sample_id", "condition", "replicate"}:
                raise ValueError("Sample identity/design columns cannot be used as file paths: " + column)
            shared = binding.get("shared", False)
            if not isinstance(shared, bool) or (shared and fields[key]["sourceType"] in NEVER_SHARED_TYPES):
                raise ValueError("Read/sample inputs cannot be marked as a shared reference.")
            bound[key] = dict(binding)
            used_columns[column] = key
        for binding in parameter_bindings:
            if not isinstance(binding, dict) or set(binding) != {"nodeId", "parameterId", "column"}:
                raise ValueError("Each parameter binding needs a nodeId, parameterId and column.")
            key = (binding.get("nodeId"), binding.get("parameterId"))
            column = binding.get("column")
            if any(not isinstance(value, str) for value in key) or key not in parameters or not isinstance(column, str) or column not in table["columns"] or key in parameter_bound:
                raise ValueError("A parameter binding is unknown, duplicated or uses an unknown column.")
            parameter_bound[key] = dict(binding)
        for key, field in fields.items():
            if key not in bound and not field["shared"] and key[0] not in shared_sources:
                raise ValueError("Map every sample input, or explicitly identify a shared reference/resource: " + key[0] + "/" + key[1])
        if len(table["rows"]) > 1:
            for key, parameter in parameters.items():
                if key[1] == "sample" and parameter.get("binding") and (key not in parameter_bound or parameter_bound[key]["column"] != "sample_id"):
                    raise ValueError("Map the tool's sample parameter to sample_id so independent samples retain distinct scientific identities: " + key[0])
        # Limit before allocating graph copies, not after materialising them.
        if len(json.dumps(graph, ensure_ascii=False).encode("utf-8")) * len(table["rows"]) > MAX_EXPANDED_BYTES:
            raise ValueError("The expanded batch is too large. Split this sample table into smaller batches.")
    except (ValueError, TypeError, OSError, KeyError, AttributeError) as exc:
        fail(str(exc))
        return result

    result["sampleCount"] = len(table["rows"])
    seen_paths, shared_paths = {}, {}
    for row_number, row in enumerate(table["rows"], 2):
        sample_id = row["sample_id"]
        expanded = copy.deepcopy(graph)
        expanded["name"] = (str(graph.get("name", "Analysis"))[:65] + " · " + sample_id)[:200]
        row_sources = {source["id"]: source for source in expanded["sources"]}
        row_nodes = {node["id"]: node for node in expanded["nodes"]}
        error_start = len(result["errors"])
        for key, binding in bound.items():
            try:
                path = _file_path(row[binding["column"]], table["baseDirectory"])
                stat = _io_path(path).stat()
                # Physical file identity catches hard-linked/repeated reads;
                # the resolved path also protects filesystems with no inode.
                identity = ("inode", stat.st_dev, stat.st_ino) if stat.st_ino else ("path", os.path.normcase(str(path)))
                is_shared = bool(binding.get("shared") or fields[key]["shared"] or key[0] in shared_sources)
                if binding.get("shared") or key[0] in shared_sources:
                    if key in shared_paths and shared_paths[key] != identity:
                        raise ValueError("An explicitly shared resource must be the same file in every sample row.")
                    shared_paths[key] = identity
                previous = seen_paths.get(identity)
                if previous and not (previous["shared"] and is_shared):
                    raise ValueError("The same input file is assigned more than once (including hard links): " + previous["sampleId"] + "/" + previous["column"])
                seen_paths[identity] = {"sampleId": sample_id, "column": binding["column"], "shared": is_shared}
                row_sources[key[0]].setdefault("files", {})[key[1]] = str(path)
            except (ValueError, OSError) as exc:
                fail(str(exc), sampleId=sample_id, row=row_number, column=binding["column"])
        for key, binding in parameter_bound.items():
            row_nodes[key[0]].setdefault("params", {})[key[1]] = row[binding["column"]]
        review = engine.validate(expanded)
        for issue in review.get("errors", []):
            fail(issue["message"], sampleId=sample_id, row=row_number, **{key: value for key, value in issue.items() if key != "message"})
        result["warnings"].extend(dict(issue, sampleId=sample_id) for issue in review.get("warnings", []))
        # Keep all imported text, not merely a predefined design subset. This is
        # local reproducibility metadata and must not enter redacted diagnostics.
        metadata = {"schema": 1, "sampleId": sample_id, "mode": "independent", "row": row_number,
                    "columns": copy.deepcopy(row), "tableSha256": table["sha256"],
                    "fileBindings": copy.deepcopy(bindings), "parameterBindings": copy.deepcopy(parameter_bindings),
                    "sharedSources": list(shared_sources)}
        try:
            _metadata_size(metadata)
        except ValueError as exc:
            fail(str(exc), sampleId=sample_id, row=row_number)
        result["samples"].append({"sampleId": sample_id, "metadata": metadata, "graph": expanded,
                                  "validation": review, "valid": len(result["errors"]) == error_start})
    result["valid"] = not result["errors"]
    return result


def _preview_combined(engine, graph, table, bindings, parameter_bindings, shared_sources, target, result):
    """One explicit many-valued report port; never generic biological pooling."""
    result["notice"] = "Combined reports: one analysis receives one separately named report per sample row. The selected tool combines reports; reads are not pooled and no biological cohort design is inferred."
    try:
        table = _validated_table(table)
        nodes, sources = engine._structure(graph)
        targets = binding_targets(engine, graph)
        _verify_pins(engine, nodes)
        if bindings or parameter_bindings:
            raise ValueError("Combined reports use one explicit report-column target, without per-sample file or parameter mappings.")
        if not isinstance(target, dict) or set(target) != {"nodeId", "portId", "column"}:
            raise ValueError("Choose an explicit combined-report nodeId, portId and column. Samples are never combined automatically.")
        if any(not isinstance(value, str) for value in target.values()) or target["column"] not in table["columns"]:
            raise ValueError("The combined-report target or table column is invalid.")
        if target["column"] in {"sample_id", "condition", "replicate"}:
            raise ValueError("Sample identity/design columns cannot be used as report file paths.")
        port = next((item for item in targets["combined"] if item["nodeId"] == target["nodeId"] and item["portId"] == target["portId"]), None)
        if port is None:
            raise ValueError("Combined reports require a pack-declared many-valued metrics/text port with one file per source. Reads, alignments and cohort inputs need an explicit workflow.")
        if not port["min"] <= len(table["rows"]) <= port["max"]:
            raise ValueError(f"This report port accepts {port['min']}–{port['max']} files; the table contains {len(table['rows'])} samples.")
        shared_sources = [] if shared_sources is None else shared_sources
        if not isinstance(shared_sources, list) or any(not isinstance(value, str) or value not in sources for value in shared_sources) or len(set(shared_sources)) != len(shared_sources):
            raise ValueError("Shared input selections must name distinct existing workflow sources.")
        for identity in shared_sources:
            if sources[identity].get("type") in NEVER_SHARED_TYPES:
                raise ValueError("Combined reports cannot silently reuse read or alignment inputs.")
        expanded = copy.deepcopy(graph)
        node = next(item for item in expanded["nodes"] if item["id"] == port["nodeId"])
        previous = node.get("inputs", {}).get(port["portId"], [])
        for identity in previous:
            if identity not in sources or any(sources[identity].get("files", {}).values()):
                raise ValueError("Disconnect existing report inputs before mapping the sample table; selected files are never silently replaced.")
            if any(identity in references for other in nodes.values() for port_id, references in other.get("inputs", {}).items()
                   if (other["id"], port_id) != (port["nodeId"], port["portId"])):
                raise ValueError("An empty report placeholder is shared elsewhere. Disconnect it before combined mapping.")
        for field in targets["files"]:
            if field["sourceId"] not in previous and not field["shared"] and field["sourceId"] not in shared_sources:
                raise ValueError("Explicitly identify every additional combined-report input as shared: " + field["sourceId"])
        expanded["sources"] = [source for source in expanded["sources"] if source["id"] not in previous]
        next_source = max([int(identity.split("-")[1]) for identity in sources] + [0]) + 1
        bound_refs, seen, paths = [], set(), []
        for row_number, row in enumerate(table["rows"], 2):
            path = _file_path(row[target["column"]], table["baseDirectory"])
            stat = _io_path(path).stat()
            physical = ("inode", stat.st_dev, stat.st_ino) if stat.st_ino else ("path", os.path.normcase(str(path)))
            if physical in seen:
                raise ValueError("Combined reports need distinct files; the same file or hard link is repeated at sample " + row["sample_id"])
            seen.add(physical)
            identity = "input-" + str(next_source)
            next_source += 1
            bound_refs.append(identity)
            expanded["sources"].append({"id": identity, "type": port["type"], "label": row["sample_id"] + " report",
                                        "files": {port["fieldId"]: str(path)},
                                        "fields": [{"id": port["fieldId"], "type": "file", "label": "Sample report", "required": True}]})
            paths.append({"sampleId": row["sample_id"], "sourceId": identity, "fieldId": port["fieldId"], "path": str(path)})
        node.setdefault("inputs", {})[port["portId"]] = bound_refs
        expanded["nextSource"] = max(next_source, expanded.get("nextSource", 1))
        expanded["name"] = str(graph.get("name", "Analysis"))[:175] + " · combined reports"
        review = engine.validate(expanded)
        result["sampleCount"] = len(table["rows"])
        result["errors"].extend(copy.deepcopy(review.get("errors", [])))
        result["warnings"].extend(copy.deepcopy(review.get("warnings", [])))
        result["warnings"].append({"message": "This is one combined-report job. Conditions and replicates are recorded as metadata; they do not configure a statistical design or establish biological independence."})
        metadata = {"schema": 1, "sampleId": "combined", "mode": "combined", "tableSha256": table["sha256"],
                    "rows": copy.deepcopy(table["rows"]), "combinedTarget": copy.deepcopy(target),
                    "sourceBindings": paths, "sharedSources": list(shared_sources)}
        _metadata_size(metadata)
        result["samples"].append({"sampleId": "combined", "metadata": metadata, "graph": expanded,
                                  "validation": review, "valid": review.get("valid", False)})
        result["valid"] = bool(review.get("valid"))
    except (ValueError, TypeError, OSError, KeyError, AttributeError) as exc:
        result["errors"].append({"message": str(exc)})
    return result
