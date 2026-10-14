"""Bounded sample-table editing and explicit, create-new CSV/TSV exports.

The editor never guesses file columns, read pairing or biological replicates.
Declared file cells are made absolute on export so a different destination
folder cannot change their meaning. All other columns remain plain metadata.
"""
from __future__ import annotations

import copy
import csv
import io
import json
import os
from pathlib import Path
import re
import secrets

try:
    from .engine import _io_path, safe_json
    from .sample_table import (COLUMN, MAX_CELL, MAX_COLUMNS, MAX_ROWS,
                               _directory, _file_path, parse_table)
except ImportError:
    from engine import _io_path, safe_json
    from sample_table import (COLUMN, MAX_CELL, MAX_COLUMNS, MAX_ROWS,
                              _directory, _file_path, parse_table)

MAX_EDITOR_BYTES = 1024 * 1024
LIMITS = {"maxRows": MAX_ROWS, "maxColumns": MAX_COLUMNS, "maxCell": MAX_CELL,
          "maxEditorBytes": MAX_EDITOR_BYTES}
EXPORT_NOTICE = ("Only columns explicitly marked as file paths are resolved against the selected base folder "
                 "and saved as absolute paths. Other columns are unchanged metadata. Existing files are never replaced.")


def _editor_bound(value):
    size = len(json.dumps(value, ensure_ascii=True, allow_nan=False).encode("utf-8"))
    if size > MAX_EDITOR_BYTES:
        raise ValueError("This table exceeds the native editor's 1 MiB JSON limit. Its imported rows are retained; "
                         "edit the complete CSV/TSV externally and import it again. No rows were truncated.")
    return size


def file_columns(columns, selected):
    if (not isinstance(selected, list) or any(not isinstance(name, str) for name in selected)
            or len(set(selected)) != len(selected) or any(name not in columns or name == "sample_id" for name in selected)):
        raise ValueError("Mark distinct file-path columns explicitly; sample_id must remain an identifier.")
    return list(selected)


def _bytes(columns, rows, delimiter):
    output = io.StringIO(newline="")
    writer = csv.writer(output, delimiter=delimiter, lineterminator="\n")
    writer.writerow(columns)
    writer.writerows([row[name] for name in columns] for row in rows)
    return output.getvalue().encode("utf-8")


def apply_draft(draft):
    """Validate every edited row with the existing import rules and new bytes."""
    safe_json(draft)
    allowed = {"columns", "rows", "baseDirectory", "delimiter", "fileColumns"}
    if (not isinstance(draft, dict) or set(draft) - allowed
            or not {"columns", "rows", "baseDirectory"} <= set(draft)):
        raise ValueError("A table draft needs columns, all rows and an explicit baseDirectory (or null).")
    _editor_bound(draft)
    columns, rows = draft["columns"], draft["rows"]
    if (not isinstance(columns, list) or not 1 <= len(columns) <= MAX_COLUMNS
            or any(not isinstance(name, str) or not COLUMN.fullmatch(name) for name in columns)):
        raise ValueError("Choose 1–64 valid column names, beginning with a letter.")
    if (not isinstance(rows, list) or not 1 <= len(rows) <= MAX_ROWS
            or any(not isinstance(row, dict) or set(row) != set(columns) for row in rows)):
        raise ValueError("A table needs 1–1,000 rows, each with exactly the declared columns.")
    if any(not isinstance(value, str) for row in rows for value in row.values()):
        raise ValueError("Sample-table cells must be text.")
    delimiter = draft.get("delimiter", ",")
    if delimiter not in (",", "\t"):
        raise ValueError("Choose comma-separated CSV or tab-separated TSV.")
    selected = file_columns(columns, draft.get("fileColumns", []))
    table = parse_table(_bytes(columns, rows, delimiter), delimiter=delimiter,
                        base_directory=draft["baseDirectory"])
    table["fileColumns"] = selected
    return table


def editable_table(table):
    """Return the full immutable snapshot or reject it; never edit a preview."""
    draft = {key: copy.deepcopy(table[key]) for key in ("columns", "rows", "baseDirectory", "delimiter")}
    draft["fileColumns"] = copy.deepcopy(table.get("fileColumns", []))
    _editor_bound(draft)
    return dict(draft, limits=copy.deepcopy(LIMITS), exportNotice=EXPORT_NOTICE,
                exampleNotice=table.get("exampleNotice", ""))


def save_table(table, destination, selected, *, before_write=None):
    """Atomically publish one complete new CSV/TSV without replacing a file."""
    selected = file_columns(table["columns"], selected)
    path = Path(destination)
    if not path.is_absolute() or path.suffix.lower() not in (".csv", ".tsv"):
        raise ValueError("Choose an absolute destination filename ending in .csv or .tsv.")
    stem = path.name.split(".", 1)[0].rstrip(" .").upper()
    if (any(character in '<>:"/\\|?*' or ord(character) < 32 or ord(character) == 127 for character in path.name)
            or path.name.endswith((".", " ")) or stem in {"CON", "PRN", "AUX", "NUL", "CONIN$", "CONOUT$"}
            or re.fullmatch(r"(?:COM|LPT)[1-9¹²³]", stem)):
        raise ValueError("Choose an ordinary Windows filename without reserved device names, alternate streams or unsafe characters.")
    parent = _directory(path.parent)
    path = Path(parent) / path.name
    if _io_path(path).exists() or _io_path(path).is_symlink():
        raise ValueError("Choose a new filename. Existing sample tables are never overwritten.")
    delimiter = "\t" if path.suffix.lower() == ".tsv" else ","
    rows = copy.deepcopy(table["rows"])
    export = {"columns": table["columns"], "rows": rows, "baseDirectory": parent,
              "delimiter": delimiter, "fileColumns": selected}
    editor_size = _editor_bound(export)
    resolved = {}
    for row in rows:
        for column in selected:
            original = row[column]
            if original not in resolved:
                resolved[original] = str(_file_path(original, table["baseDirectory"]))
            absolute = resolved[original]
            if len(absolute) > MAX_CELL:
                raise ValueError("A resolved file path exceeds the 4,096-character cell limit. Choose a shorter input path.")
            editor_size += len(json.dumps(absolute, ensure_ascii=True)) - len(json.dumps(original, ensure_ascii=True))
            if editor_size > MAX_EDITOR_BYTES:
                raise ValueError("Saving these absolute paths would exceed the native editor's 1 MiB JSON limit. "
                                 "No file was created; use fewer rows or shorter input paths.")
            row[column] = absolute
    raw = _bytes(table["columns"], rows, delimiter)
    result = parse_table(raw, delimiter=delimiter, base_directory=parent)
    result["fileColumns"] = selected
    # The native editor reloads this exact saved token. Never publish a table
    # that its next complete-table read would have to reject or truncate.
    editable_table(result)
    if before_write is not None:
        before_write(result)
    temporary = path.with_name(".workbench-samples-" + secrets.token_hex(16) + ".tmp")
    try:
        with _io_path(temporary).open("xb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        if os.name == "nt":
            # Windows rename fails if the destination exists; POSIX rename
            # replaces it, so use an exclusive hard-link publication there.
            os.rename(_io_path(temporary), _io_path(path))
        else:
            os.link(_io_path(temporary), _io_path(path))
    except FileExistsError as error:
        raise ValueError("Choose a new filename. Existing sample tables are never overwritten.") from error
    finally:
        _io_path(temporary).unlink(missing_ok=True)
    return result


def synthetic_example(app_root, catalog):
    """One verified synthetic sample, using exactly the curated fixture bytes."""
    try:
        from .catalog import resolve_tool
        from .curated_workflows import _fixture_status, _pin
    except ImportError:
        from catalog import resolve_tool
        from curated_workflows import _fixture_status, _pin
    inputs, issues = _fixture_status(app_root)
    try:
        resolve_tool(catalog, "align/paired-end", _pin("align"))
    except (ValueError, KeyError, TypeError):
        issues.append("Open Manage tools and install align 0.4.0, or import the official "
                      "native-workbench-pack-align-0.4.0.zip. This example requires the exact recorded manifest; "
                      "keep other installed versions.")
    if issues:
        raise ValueError("The synthetic sample example is unavailable. " + " ".join(issues))
    paths = {item["name"]: item["path"] for item in inputs}
    table = apply_draft({"columns": ["sample_id", "read1", "read2", "reference"],
                         "rows": [{"sample_id": "starter", "read1": paths["reads1.fastq"],
                                   "read2": paths["reads2.fastq"], "reference": paths["reference.fa"]}],
                         "baseDirectory": str(Path(paths["reference.fa"]).parent),
                         "fileColumns": ["read1", "read2", "reference"]})
    table["exampleNotice"] = (
        "One synthetic training sample: 101 paired reads and the artificial starter reference. "
        "This is the same dataset used by the training workflows, not independent biological replicates. "
        "Map read1 and read2 separately to the workflow's paired-read fields, and reference to its reference field. "
        "Map sample_id to the pack's sample option where required. A table does not select a workflow, "
        "download tools or run an analysis. Known answers apply only to the unchanged curated workflows.")
    return table
