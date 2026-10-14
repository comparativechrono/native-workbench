"""Bounded summaries of recorded scientific outputs; never a QC verdict.

Only declared SAMtools stats/flagstat and BCFtools stats stdout products from
successful steps are parsed. The frozen plan and recorded output SHA-256 values
bind the interpretation to the original operation and bytes. No tools are run.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
import re
import stat

try:
    from .engine import _io_path, _resolved_path, _safe_relative, canonical, display_id, pin_for
except ImportError:
    from engine import _io_path, _resolved_path, _safe_relative, canonical, display_id, pin_for


MAX_PLAN_BYTES = 16 * 1024 * 1024
MAX_REPORT_BYTES = 2 * 1024 * 1024
MAX_TOTAL_REPORT_BYTES = 8 * 1024 * 1024
MAX_REPORTS = 32
MAX_NODES = 512
MAX_LIST_BYTES = 160 * 1024
MAX_DETAILS_CHARS = 60000
SHA256 = re.compile(r"[0-9a-f]{64}\Z")
INTERPRETATION = (
    "These are recorded measurements, not a QC pass/fail assessment. Execution "
    "success does not establish sample quality. SAMtools QC-passed/QC-failed "
    "counts describe the reads' QC flag. BCFtools counts describe their recorded "
    "input, including LowQual calls unless the operation explicitly selected a subset. "
    "No quality thresholds or clinical conclusions are inferred."
)

# Labels are upstream SN keys, not guessed from filenames or scientific values.
SAMTOOLS_STATS = {
    "raw total sequences": ("raw_total_sequences", "Raw total sequences", "sequences", True),
    "reads mapped": ("reads_mapped", "Reads mapped", "reads", True),
    "reads unmapped": ("reads_unmapped", "Reads unmapped", "reads", True),
    "reads duplicated": ("reads_duplicated", "Reads duplicated", "reads", True),
    "average length": ("average_length", "Average read length", "bases", False),
    "error rate": ("error_rate", "Alignment error rate", "ratio", False),
}
BCFTOOLS_STATS = {
    "number of samples": ("number_of_samples", "Samples in variant file", "samples", True),
    "number of records": ("number_of_records", "Variant records", "records", True),
    "number of SNPs": ("number_of_snps", "SNP records", "records", True),
    "number of MNPs": ("number_of_mnps", "MNP records", "records", True),
    "number of indels": ("number_of_indels", "Indel records", "records", True),
    "number of others": ("number_of_others", "Other variant records", "records", True),
}
FLAG_LABELS = {
    "in total": ("total", "Total alignment records"),
    "primary": ("primary", "Primary alignment records"),
    "secondary": ("secondary", "Secondary alignment records"),
    "supplementary": ("supplementary", "Supplementary alignment records"),
    "duplicates": ("duplicates", "Duplicate alignment records"),
    "mapped": ("mapped", "Mapped alignment records"),
    "properly paired": ("properly_paired", "Properly paired alignment records"),
}
FLAG_LINE = re.compile(r"([0-9]+) \+ ([0-9]+) ([^\r\n]+)")


class Unavailable(ValueError):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def _text(value, maximum=2000):
    return value if isinstance(value, str) and len(value) <= maximum else ""


def _dict(value):
    return value if isinstance(value, dict) else {}


def _list(value):
    return value if isinstance(value, list) else []


def _path(value):
    value = _text(value, 30000)
    if not value or "\x00" in value:
        raise Unavailable("invalid_path", "The recorded file path is missing or malformed.")
    path = Path(value)
    if not path.is_absolute():
        raise Unavailable("invalid_path", "The recorded file path is not absolute.")
    return path


def _bounded_read(path, limit, root=None):
    """Reject links/escapes, bound bytes, and detect mutation during one read."""
    physical = _io_path(path)
    try:
        for part in [path, *path.parents]:
            candidate = _io_path(part)
            if candidate.is_symlink() or (hasattr(candidate, "is_junction") and candidate.is_junction()):
                raise Unavailable("unsafe_path", "A recorded file or parent folder is now a link or junction.")
        if root is not None and not physical.resolve().is_relative_to(_io_path(root).resolve()):
            raise Unavailable("unsafe_path", "The recorded output is outside its result folder.")
        before = physical.stat()
        if not stat.S_ISREG(before.st_mode):
            raise Unavailable("not_file", "The recorded path is not an ordinary file.")
        if before.st_size > limit:
            raise Unavailable("read_limit", "The file exceeds the bounded summary read limit.")
        with open(physical, "rb") as stream:
            opened = os.fstat(stream.fileno())
            data = stream.read(limit + 1)
            after = os.fstat(stream.fileno())
        final = physical.stat()
        # Windows CPython currently reports creation time in path stat's ctime
        # and change time in fstat's ctime (cpython issue #157671). Compare ctime
        # before/after only within the same API. Device/inode, length and mtime
        # still bind the opened handle to the pathname across the complete read.
        identity = lambda item: (item.st_dev, item.st_ino, item.st_size, item.st_mtime_ns)
        stable = lambda first, last: (identity(first) == identity(last)
                                     and first.st_ctime_ns == last.st_ctime_ns)
        if (not stable(before, final) or not stable(opened, after)
                or identity(before) != identity(opened)):
            raise Unavailable("changed_file", "The file changed while its summary was being read.")
        if len(data) > limit:
            raise Unavailable("read_limit", "The file exceeds the bounded summary read limit.")
        return data
    except Unavailable:
        raise
    except FileNotFoundError as error:
        raise Unavailable("missing_file", "The recorded file is missing.") from error
    except (OSError, ValueError, RuntimeError) as error:
        raise Unavailable("unreadable_file", "The recorded file cannot be read: " + str(error)) from error


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON key")
        result[key] = value
    return result


def _plan(record, folder):
    data = _bounded_read(folder / "plan.json", MAX_PLAN_BYTES, folder)
    try:
        plan = json.loads(data.decode("utf-8"), object_pairs_hook=_unique_object,
                          parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)))
        if not isinstance(plan, dict):
            raise ValueError("Expected an object")
        claimed = plan.pop("sha256", None)
        actual = hashlib.sha256(canonical(plan).encode("utf-8")).hexdigest()
        if (not isinstance(claimed, str) or not SHA256.fullmatch(claimed) or claimed != actual
                or claimed != record.get("planSha256") or plan.get("id") != record.get("id")
                or _resolved_path(_path(plan.get("folder"))) != _resolved_path(folder)):
            raise Unavailable("changed_plan", "The frozen plan does not match this recorded run.")
        if not isinstance(plan.get("nodes"), list) or len(plan["nodes"]) > MAX_NODES:
            raise ValueError("Invalid or oversized node list")
        identities = [node.get("id") for node in plan["nodes"] if isinstance(node, dict)]
        if (len(identities) != len(plan["nodes"]) or not all(isinstance(identity, str) for identity in identities)
                or len(set(identities)) != len(identities)):
            raise ValueError("Invalid or duplicate nodes")
        for node in plan["nodes"]:
            tool = node.get("tool")
            if not isinstance(tool, dict) or not isinstance(tool.get("id"), str):
                raise ValueError("Invalid operation definition")
            for key, maximum in (("steps", 256), ("outputs", 128), ("params", 128)):
                if not isinstance(tool.get(key, []), list) or len(tool.get(key, [])) > maximum:
                    raise ValueError("Invalid or oversized operation declarations")
            for command in _list(tool.get("steps")):
                if not isinstance(command, dict) or not isinstance(command.get("stdout", ""), str):
                    raise ValueError("Invalid command declaration")
            for output in _list(tool.get("outputs")):
                if (not isinstance(output, dict) or not isinstance(output.get("id"), str)
                        or not isinstance(output.get("files", {}), dict)
                        or len(output.get("files", {})) > 128):
                    raise ValueError("Invalid output declaration")
        return plan
    except Unavailable:
        raise
    except (UnicodeError, ValueError, TypeError, OSError, RuntimeError) as error:
        raise Unavailable("malformed_plan", "The frozen plan is malformed; its definitions are unavailable.") from error


def _number(value, integer):
    if integer:
        if not re.fullmatch(r"[0-9]{1,20}", value):
            raise ValueError("Expected a nonnegative integer")
        return int(value)
    if not re.fullmatch(r"[+]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?", value):
        raise ValueError("Expected a finite nonnegative number")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError("Expected a finite nonnegative number")
    return result


def _parse_report(data, kind):
    try:
        text = data.decode("utf-8-sig")
        if "\x00" in text:
            raise ValueError("NUL in report")
        rows, seen = [], set()
        spec = SAMTOOLS_STATS if kind == "samtools.stats" else BCFTOOLS_STATS
        for line in text.splitlines():
            if len(line) > 32768:
                raise ValueError("Oversized report line")
            if kind == "samtools.flagstat":
                if not line.strip():
                    continue
                match = FLAG_LINE.fullmatch(line)
                if not match:
                    raise ValueError("Invalid flagstat record")
                label = match[3].split(" (", 1)[0]
                if label not in FLAG_LABELS:
                    continue
                identity, title = FLAG_LABELS[label]
                if identity in seen:
                    raise ValueError("Duplicate flagstat count")
                seen.add(identity)
                for index, flag in enumerate(("qc_passed", "qc_failed"), 1):
                    rows.append({"id": kind + "." + identity + "." + flag,
                                 "label": title + " (" + flag.replace("_", "-") + ")",
                                 "value": _number(match[index], True), "unit": "records"})
                continue
            if not line.startswith("SN\t"):
                continue
            fields = line.split("\t")
            if kind == "bcftools.stats":
                if len(fields) < 4 or fields[1] != "0":
                    raise ValueError("Only one BCFtools summary set (ID 0) is supported")
                key, value = fields[2].rstrip(":"), fields[3]
            else:
                if len(fields) < 3:
                    raise ValueError("Invalid SAMtools SN row")
                key, value = fields[1].rstrip(":"), fields[2]
            if key not in spec:
                continue
            if key in seen:
                raise ValueError("Duplicate summary count")
            seen.add(key)
            identity, title, unit, integer = spec[key]
            rows.append({"id": kind + "." + identity, "label": title,
                         "value": _number(value, integer), "unit": unit})
        required = {"total", "mapped"} if kind == "samtools.flagstat" else set(spec)
        missing = sorted(required - seen)
        if not rows or missing:
            raise ValueError("Missing required summary rows: " + ", ".join(missing))
        return rows
    except (UnicodeError, ValueError, OverflowError) as error:
        raise Unavailable("malformed_report", "The recorded report cannot be summarized: " + str(error)) from error


def _sample_identities(record, plan=None):
    identities = []
    sample = _text(_dict(record.get("batch")).get("sampleId"), 128)
    if sample:
        identities.append({"value": sample, "source": "recorded sample table"})
    if plan:
        for node in plan["nodes"]:
            tool = _dict(node.get("tool"))
            for field in _list(tool.get("params")):
                field = _dict(field)
                if field.get("id") == "sample" and field.get("binding") is True:
                    sample = _text(_dict(node.get("params")).get("sample"), 2000)
                    if sample:
                        identities.append({"value": sample, "source": "frozen sample option", "step_id": node["id"]})
                    break
    return identities


def _bounded_join(values, limit=8192):
    kept, used, omitted = [], 0, 0
    for value in dict.fromkeys(values):
        if not value:
            continue
        if used + len(value) + 2 > limit:
            omitted += 1
            continue
        kept.append(value)
        used += len(value) + 2
    return ", ".join(kept), omitted


def search_entry(record):
    """Metadata-only search record. This never reads result folders or inputs."""
    record = _dict(record)
    samples = [item["value"] for item in _sample_identities(record)]
    graph = _dict(record.get("graph"))
    tools = []
    for node in _list(record.get("nodes"))[:MAX_NODES] + _list(graph.get("nodes"))[:MAX_NODES]:
        node = _dict(node)
        tool = node.get("tool")
        if isinstance(tool, str):
            tools.append(_text(tool))
        elif isinstance(tool, dict):
            tools += [_text(tool.get("id")), _text(tool.get("name"))]
        tools.append(_text(node.get("name")))
        sample = _text(_dict(node.get("params")).get("sample"), 2000)
        if sample:
            samples.append(sample)
    aliases = {"align": "minimap2", "bam": "SAMtools", "variants": "BCFtools"}
    for tool in list(tools):
        if tool.split("/", 1)[0] in aliases:
            tools.append(aliases[tool.split("/", 1)[0]])
    samples, omitted_samples = _bounded_join(samples)
    tools, omitted_tools = _bounded_join(tools)
    return {"run_id": _text(record.get("run_id") or record.get("id")),
            "name": _text(record.get("name")), "status": _text(record.get("status")),
            "folder": _text(record.get("folder"), 30000),
            "started_at": _text(record.get("started_at") or record.get("started")),
            "sample": samples, "tools": tools, "metadata_omitted": omitted_samples + omitted_tools}


def matches(entry, query):
    """All whitespace-separated terms must match name, sample, status or tool."""
    if not isinstance(query, str) or len(query) > 500:
        raise ValueError("Search must be text no longer than 500 characters.")
    haystack = " ".join(_text(entry.get(key), 100000) for key in ("name", "sample", "status", "tools")).casefold()
    return all(term in haystack for term in query.casefold().split())


def _report_products(node):
    tool = _dict(node.get("tool"))
    products = {}
    for output in _list(tool.get("outputs")):
        output = _dict(output)
        for key in _dict(output.get("files")):
            products.setdefault(key, []).append(output)
    for command in _list(tool.get("steps")):
        command = _dict(command)
        args = _list(command.get("args"))
        executable = command.get("tool")
        kind = str(executable) + "." + str(args[0] if args else "")
        if kind not in {"samtools.stats", "samtools.flagstat", "bcftools.stats"}:
            continue
        stdout = command.get("stdout")
        if stdout:
            for output in products.get(stdout, []):
                yield kind, output, stdout


def _failure_action(status, message):
    """Advice follows the recorded state/error, never an inferred QC diagnosis."""
    lower = message.casefold()
    if status == "blocked":
        return "Review the failed upstream step first. Correct its recorded cause before preparing a new run or reviewing a completed-step restart."
    if status == "cancelled":
        return "This analysis was cancelled. Review its completed steps and original inputs before explicitly preparing a new run or reviewing a completed-step restart."
    if status == "interrupted":
        return "The previous session ended without a completed outcome. Preserve the run folder, review completed-step restart eligibility, and start a reviewed new run explicitly."
    if any(term in lower for term in ("input changed", "input is missing", "input file is missing", "reference is missing", "upstream output changed", "select an existing ordinary file")):
        return "Restore the exact recorded input bytes at their original paths, or prepare a new run with explicitly selected replacement inputs. Do not edit recorded hashes."
    if any(term in lower for term in ("pack", "manifest", "installed operation", "executable")):
        return "Inspect the recorded tool error and exact pack/version/manifest pin. Restore that trusted pack version before preparing a new run; an update must not silently replace the pin."
    if any(term in lower for term in ("permission", "access denied", "read-only", "disk", "space", "storage", "output folder")):
        return "Check the output and temporary folders named by the recorded error for available space and write access. Select an accessible folder in a new run and retain this failed run's evidence."
    return "Inspect this step's run record and command logs; correct the reported cause before preparing a new run or reviewing a completed-step restart."


def build_summary(run_record):
    """Return current verified measurements plus explicit unavailable evidence."""
    record = _dict(run_record)
    entry = search_entry(record)
    result = {"schema": 1, **{key: entry[key] for key in ("run_id", "name", "status", "folder")},
              "sample": {"available": False, "identities": []}, "tools": [], "metrics": [],
              "unavailable": [], "failures": [], "artifacts": [], "omitted": {},
              "interpretation": INTERPRETATION}
    used = 0
    def add(key, item):
        nonlocal used
        size = len(json.dumps(item, ensure_ascii=True).encode("utf-8"))
        if used + size > MAX_LIST_BYTES:
            result["omitted"][key] = result["omitted"].get(key, 0) + 1
            return
        result[key].append(item)
        used += size
    def unavailable(error, step_id="", path=""):
        add("unavailable", {"code": error.code, "message": str(error), "step_id": step_id,
                            "source_path": str(path), "action": "Inspect the recorded file and run folder. Restore the original bytes, or prepare a new run; do not edit its recorded hashes."})
    folder, plan = None, None
    try:
        folder = _path(record.get("folder"))
        plan = _plan(record, folder)
    except Unavailable as error:
        unavailable(error, path=str(folder / "plan.json") if folder else "")
    identities, sample_bytes = [], 0
    for sample in _sample_identities(record, plan):
        size = len(json.dumps(sample, ensure_ascii=True).encode("utf-8"))
        if sample_bytes + size > 16384:
            result["omitted"]["sample_identities"] = result["omitted"].get("sample_identities", 0) + 1
            continue
        identities.append(sample)
        sample_bytes += size
    result["sample"] = {"available": bool(identities), "identities": identities,
                        "reason": "" if identities else "No explicit sample identity is available; filenames are not sample identities."}
    nodes = _list(record.get("nodes"))
    frozen = {node["id"]: node for node in plan["nodes"]} if plan else {}
    if len(nodes) > MAX_NODES:
        unavailable(Unavailable("node_limit", "The recorded step list exceeds the summary limit."))
    report_count, report_bytes = 0, 0
    for node in nodes[:MAX_NODES]:
        if (not isinstance(node, dict) or not all(isinstance(node.get(key), str) for key in ("id", "tool", "status"))):
            unavailable(Unavailable("malformed_step", "A recorded step identity, operation or status is malformed."))
            continue
        node = _dict(node)
        identity = _text(node.get("id"))
        definition = frozen.get(identity)
        tool = _dict(_dict(definition).get("tool"))
        pin = {key: _text(_dict(node.get("pin")).get(key)) for key in ("packId", "packVersion", "manifestSha256")}
        item = {"step_id": identity, "name": _text(node.get("name")), "tool": _text(node.get("tool")),
                "status": _text(node.get("status")), "pin": pin}
        compatible = bool(definition and node.get("tool") == tool.get("id") and pin == pin_for(tool))
        if compatible:
            item["executables"] = [{key: _text(_dict(value).get(key)) for key in ("id", "version", "sha256")}
                                   for value in _list(tool.get("executables"))[:32]]
        add("tools", item)
        if node.get("status") in {"failed", "blocked", "cancelled", "interrupted"}:
            add("failures", {"step_id": identity, "status": node["status"],
                             "message": _text(node.get("message")) or "This step did not complete.",
                             "action": _failure_action(node["status"], _text(node.get("message")))})
        if not plan:
            continue
        if not compatible:
            unavailable(Unavailable("step_mismatch", "The recorded operation or exact pack pin differs from the frozen plan."), identity)
            continue
        for kind, output, key in _report_products(definition):
            if node.get("status") != "success":
                unavailable(Unavailable("step_not_complete", "Metrics are unavailable because the producing step did not complete successfully."), identity)
                continue
            ref = identity + "::" + str(output.get("id", ""))
            product = _dict(_dict(node.get("outputs")).get(ref))
            raw_path = _dict(product.get("files")).get(key)
            raw_hash = _dict(product.get("sha256")).get(key)
            source = _text(raw_path, 30000)
            artifact = {"kind": "raw_metrics", "label": kind, "path": source, "status": "unavailable"}
            try:
                if (product != _dict(record.get("outputs")).get(ref) or product.get("producer") != identity
                        or product.get("id") != ref or not isinstance(raw_hash, str) or not SHA256.fullmatch(raw_hash)):
                    raise Unavailable("unbound_output", "The metric output does not have matching recorded producer and SHA-256 evidence.")
                path = _path(raw_path)
                if not _resolved_path(path).is_relative_to(_resolved_path(folder)):
                    raise Unavailable("unsafe_path", "The recorded output is outside its result folder.")
                step_root = folder / display_id(identity)
                actual_folder = _path(node.get("folder", str(step_root)))
                try:
                    expected_path = _safe_relative(actual_folder, _dict(output.get("files")).get(key))
                    if (not _resolved_path(actual_folder).is_relative_to(_resolved_path(step_root))
                            or _resolved_path(path) != _resolved_path(expected_path)):
                        raise ValueError("Output location differs")
                except (OSError, ValueError, RuntimeError) as error:
                    raise Unavailable("unbound_output", "The metric output path differs from its frozen step/output declaration.") from error
                report_count += 1
                if report_count > MAX_REPORTS or report_bytes >= MAX_TOTAL_REPORT_BYTES:
                    raise Unavailable("report_limit", "The result exceeds the bounded number or total bytes of metric reports.")
                data = _bounded_read(path, min(MAX_REPORT_BYTES, MAX_TOTAL_REPORT_BYTES - report_bytes), folder)
                report_bytes += len(data)
                if hashlib.sha256(data).hexdigest() != raw_hash:
                    raise Unavailable("changed_output", "The metric file's SHA-256 differs from its recorded output hash.")
                rows = _parse_report(data, kind)
                artifact.update(status="verified", sha256=raw_hash)
                for row in rows:
                    add("metrics", {**row, "tool": item["tool"], "step_id": identity, "source_path": source,
                                    "sha256": raw_hash, "scope": "Recorded " + str(output.get("label", output.get("id", "output")))})
            except Unavailable as error:
                unavailable(error, identity, source)
            except (OSError, ValueError, TypeError, RuntimeError) as error:
                unavailable(Unavailable("unreadable_output", "The recorded metric output or its declaration cannot be read: " + str(error)), identity, source)
            add("artifacts", artifact)
    if result["status"] in {"failed", "cancelled", "interrupted"} and not result["failures"]:
        add("failures", {"step_id": "", "status": record["status"],
                         "message": _text(record.get("message")) or "The analysis did not complete.",
                         "action": _failure_action(result["status"], _text(record.get("message")))})
    if folder:
        for kind, filename in (("methods_planned", "methods-planned.txt"), ("methods_completed", "methods-completed.txt"),
                               ("plan", "plan.json"), ("run", "run.json"), ("commands", "workflow.cwl")):
            path = folder / filename
            artifact = {"kind": kind, "label": filename, "path": str(path), "status": "unavailable"}
            try:
                if kind.startswith("methods"):
                    expected = record.get("methods") if kind == "methods_completed" else _dict(plan).get("methods")
                    data = _bounded_read(path, MAX_REPORT_BYTES, folder)
                    actual = data.decode("utf-8").replace("\r\n", "\n")
                    if not isinstance(expected, str) or actual != expected.replace("\r\n", "\n"):
                        raise Unavailable("changed_methods", "The methods file does not match the frozen or completed methods text.")
                    artifact["status"] = "verified"
                else:
                    artifact["status"] = "recorded" if _io_path(path).is_file() else "missing"
            except (Unavailable, UnicodeError) as error:
                if isinstance(error, UnicodeError):
                    error = Unavailable("malformed_methods", "The methods file is not valid UTF-8.")
                artifact["reason"] = str(error)
            add("artifacts", artifact)
    if not result["metrics"]:
        unavailable(Unavailable("no_metrics", "No supported hash-verified scientific measurements are available for this run."))
    result["details"] = _details(result)
    return result


def _details(summary):
    lines = [summary["name"] or "Recorded analysis", "Execution status: " + summary["status"],
             "Sample: " + (", ".join(item["value"] + " (" + item["source"] + ")" for item in summary["sample"]["identities"])
                            or summary["sample"]["reason"]), "", "Recorded measurements (not a QC pass/fail assessment)"]
    for metric in summary["metrics"]:
        lines.append(metric["step_id"] + ": " + metric["label"] + ": " + str(metric["value"]) + " " + metric["unit"])
    for item in summary["failures"]:
        lines += ["", "Execution issue " + item["step_id"] + ": " + item["message"], item["action"]]
    for item in summary["unavailable"]:
        lines += ["", "Unavailable " + item["step_id"] + ": " + item["message"], item["action"]]
        if item["source_path"]:
            lines.append("Source: " + item["source_path"])
    lines += ["", INTERPRETATION]
    for tool in summary["tools"]:
        pin = tool["pin"]
        lines += ["", tool["step_id"] + ": " + (tool["name"] or tool["tool"]) + " — " + tool["status"],
                  "Operation: " + tool["tool"] + "; pack " + pin["packId"] + " " + pin["packVersion"],
                  "Manifest SHA-256: " + (pin["manifestSha256"] or "unavailable")]
        for executable in tool.get("executables", []):
            lines.append(executable["id"] + " " + executable["version"] + "; SHA-256 " + executable["sha256"])
    for artifact in summary["artifacts"]:
        lines += ["", artifact["label"] + " (" + artifact["status"] + "): " + artifact["path"]]
        if artifact.get("reason"):
            lines.append(artifact["reason"])
        if artifact.get("sha256"):
            lines.append("Verified SHA-256: " + artifact["sha256"])
    if summary["omitted"]:
        lines += ["", "Some summary entries exceed the display limit: " + json.dumps(summary["omitted"]) + ". Inspect the recorded result folder."]
    text = "\r\n".join(lines)
    if len(text) > MAX_DETAILS_CHARS:
        text = text[:MAX_DETAILS_CHARS] + "\r\nDisplay text truncated. Inspect structured summary entries and the recorded result folder."
    return text
