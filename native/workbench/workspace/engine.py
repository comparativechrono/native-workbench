"""Local, typed DAG execution using the existing Windows workflow runner.

Only installed catalogue operations can execute. A frozen plan is the single source
for methods, graph diagrams and execution; no client command or shell is accepted.
"""
from __future__ import annotations

import copy
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
import gzip
import hashlib
import html
import json
import os
from pathlib import Path
import re
import subprocess
import threading
import time
import uuid
from datetime import datetime, timezone
from decimal import Decimal

try:
    from .catalog import resolve_tool
    from . import performance, reference_indexes, recovery, execution_resources
    from .cwl_export import definition_sha256, export_workflow, update_run_status
    from .reference_provenance import collect_references, used_paths, methods_text as reference_methods
except ImportError:
    from catalog import resolve_tool
    import performance
    import reference_indexes
    import recovery
    import execution_resources
    from cwl_export import definition_sha256, export_workflow, update_run_status
    from reference_provenance import collect_references, used_paths, methods_text as reference_methods


MAX_NODES = 512
MAX_SOURCES = 1024
ALIGNMENT_TYPES = {'sam', 'bam', 'sam-rna', 'bam-rna'}
ID_RE = re.compile(r"(?:step|input)-[1-9][0-9]{0,8}\Z")
FORBIDDEN_KEYS = {"__proto__", "prototype", "constructor"}


def utc():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _io_path(value):
    """Use extended Windows paths only at filesystem-call boundaries.

    A native tool may create a valid output beyond MAX_PATH even when the host
    machine has not opted Python into long ordinary paths. Keep the same
    registry-independent I/O policy as the pack/reference managers, without
    leaking the Windows namespace prefix into plans, provenance or tool argv.
    """
    if os.name != "nt":
        return Path(value)
    try:
        from .pack_manager import filesystem_path
    except ImportError:
        from pack_manager import filesystem_path
    return filesystem_path(value)


def _display_path(value):
    if os.name == "nt":
        try:
            from .pack_manager import ordinary_windows_path
        except ImportError:
            from pack_manager import ordinary_windows_path
        value = ordinary_windows_path(value)
    return Path(value)


def _resolved_path(value):
    # Resolve reparse points through the physical namespace, then compare and
    # serialize ordinary absolute identities consistently with existing runs.
    return _display_path(_io_path(value).resolve())


def digest_file(path, cancel=None):
    h = hashlib.sha256()
    with open(_io_path(path), "rb") as stream:
        for part in iter(lambda: stream.read(1024 * 1024), b""):
            if cancel is not None and cancel.is_set():
                raise InterruptedError("Cancelled while verifying files.")
            h.update(part)
    return h.hexdigest()


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def write_json(path, value):
    path = Path(path)
    temporary = path.with_name(path.name + ".pending")
    with open(_io_path(temporary), "w", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(_io_path(temporary), _io_path(path))


def clean_text(value, maximum=8192):
    return isinstance(value, str) and len(value) <= maximum and not any(ord(c) < 32 or ord(c) == 127 for c in value)


def safe_json(value, depth=0):
    if depth > 32:
        raise ValueError("The workspace JSON is nested too deeply.")
    if isinstance(value, dict):
        for key, item in value.items():
            if not clean_text(key, 256) or key in FORBIDDEN_KEYS:
                raise ValueError("The workspace contains an unsafe field name.")
            safe_json(item, depth + 1)
    elif isinstance(value, list):
        if len(value) > 4096:
            raise ValueError("The workspace contains an excessively long list.")
        for item in value:
            safe_json(item, depth + 1)
    elif isinstance(value, str):
        if len(value) > 32768 or "\0" in value:
            raise ValueError("The workspace contains invalid text.")
    elif value is not None and not isinstance(value, (bool, int, float)):
        raise ValueError("The workspace contains a non-JSON value.")
    canonical(value)


def display_id(identity):
    return ("S" if identity.startswith("step-") else "I") + identity.rsplit("-", 1)[-1]


def node_name(node, tool):
    return node.get("label") or tool["name"]


def pin_for(tool):
    return {key: tool.get(key, "") for key in ("packId", "packVersion", "manifestSha256")}


def _ordinary(path):
    path = Path(path).absolute()
    physical = _io_path(path)
    if not physical.is_file() or physical.is_symlink():
        raise ValueError("Select an existing ordinary file: " + str(path))
    for parent in path.parents:
        ancestor = _io_path(parent)
        if ancestor.is_symlink() or (hasattr(ancestor, "is_junction") and ancestor.is_junction()):
            raise ValueError("Input folders must not be symbolic links or junctions: " + str(parent))
    return _resolved_path(path)


def _safe_relative(root, relative):
    if not isinstance(relative, str) or not clean_text(relative) or re.match(r"^[A-Za-z]:", relative):
        raise ValueError("Invalid declared output path.")
    normalized = relative.replace("\\", "/")
    if normalized.startswith("/") or any(part in ("", ".", "..") for part in normalized.split("/")):
        raise ValueError("Unsafe declared output path: " + relative)
    return Path(root).joinpath(*normalized.split("/"))


def _field_default(field):
    return field.get("default", field.get("defaultValue", field.get("default_value", "")))


def _parameter(field, value):
    # Reuse catalogue constraints where available; those are also enforced by
    # the native manifest runner at execution time.
    try:
        from .catalog import validate_parameter
    except ImportError:
        from catalog import validate_parameter
    return validate_parameter(field, value)


def _check_distinct_files(tool, values):
    """Mirror manifest file-identity constraints before calling the native runner."""
    fields = {field['id']: field for port in tool.get('ports', []) for field in port.get('fields', [])}
    for identity, field in fields.items():
        other = field.get('differentFrom')
        left, right = values.get(identity, ''), values.get(other, '')
        if other and left and right and os.path.samefile(_io_path(left), _io_path(right)):
            raise ValueError(field['label']+' must be a different file from '+fields[other]['label']+'. Different names or hard links to the same file do not count.')


def _check_parameter_ranges(tool, values):
    """Compare decimal text exactly while retaining the original command value."""
    fields={field['id']:field for field in tool.get('params',[])}
    for bounds in tool.get('parameterRanges',[]):
        value=values.get(bounds['parameter'],'')
        if value=='':
            continue
        label=fields[bounds['parameter']]['label']
        text=str(value)
        if len(text)>128 or not re.fullmatch(r'[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]{1,4})?',text):
            raise ValueError(label+' must be a finite decimal number.')
        number=Decimal(text)
        if not Decimal(str(bounds['min']))<=number<=Decimal(str(bounds['max'])):
            raise ValueError(label+' must be between '+str(bounds['min'])+' and '+str(bounds['max'])+'.')


def _source_fields(source, port):
    """Map pair roles positionally only after the complete atomic pair exists."""
    files = source.get("files", {})
    wanted = port.get("manifestInputs", [port["id"]])
    if not isinstance(files, dict):
        raise ValueError("Input file bindings must be a named object.")
    if all(field in files for field in wanted):
        return {field: files[field] for field in wanted}
    ordered = list(files.values())
    if len(wanted) == 1 and len(ordered) == 1:
        return {wanted[0]: ordered[0]}
    if len(wanted) == 2:
        for first, second in (("reads1", "reads2"), ("read1", "read2")):
            if set(files) == {first, second}:
                return {wanted[0]: files[first], wanted[1]: files[second]}
    raise ValueError("Choose " + ("both paired read files with explicit read 1/read 2 roles" if len(wanted) == 2 else "the input file") + ".")


def _head(path, count=4096):
    with open(_io_path(path), "rb") as stream:
        magic = stream.read(2)
        stream.seek(0)
        if magic == b"\x1f\x8b":
            with gzip.GzipFile(fileobj=stream) as compressed:
                return compressed.read(count), True
        return stream.read(count), False


def _compression_kind(path, compressed=None):
    if compressed is False:
        return "none"
    with open(_io_path(path), "rb") as stream:
        header = stream.read(12)
        if not header.startswith(b"\x1f\x8b"):
            return "none"
        if len(header) == 12 and header[3] & 4:
            extra = stream.read(int.from_bytes(header[10:12], "little"))
            offset = 0
            while offset + 4 <= len(extra):
                identifier = extra[offset:offset+2]
                length = int.from_bytes(extra[offset+2:offset+4], "little")
                if offset + 4 + length > len(extra):
                    break
                if identifier == b"BC" and length == 2:
                    return "bgzf"
                offset += 4 + length
        return "gzip"


def _check_file_kind(path, kind, required_state=None, allowed_types=None):
    # Content signatures are an early diagnostic; the installed tool validates
    # complete records, compression integrity and pair synchronization.
    data, compressed = _head(path)
    lowered = kind.lower()
    sequence_fasta = {"fasta-nucleotide", "fasta-protein", "msa-nucleotide", "msa-protein", "fasta-nucleotide-abundance"}
    allowed = set(allowed_types or [lowered])
    # A broad FASTA/FASTQ statistics port can accept either content format.
    # Alphabet and alignment semantics are checked fully before execution.
    fasta_allowed = bool(allowed & (sequence_fasta | {"reference", "fasta"}))
    reads_allowed = "reads" in allowed
    if lowered in sequence_fasta:
        if not data:
            raise ValueError("No sequence records are available for this input: " + str(path))
        if not data.startswith(b">") and not (reads_allowed and data.startswith(b"@")):
            raise ValueError("Expected FASTA sequences" + (" or FASTQ reads" if reads_allowed else "") + ": " + str(path))
    if lowered in ("pair", "paired-reads", "reads", "fastq", "fastq-pair", "single-reads") and not data.startswith(b"@") and not (lowered == "reads" and fasta_allowed and data.startswith(b">")):
        raise ValueError("Expected FASTQ reads: " + str(path))
    if lowered in ("reference", "fasta"):
        if not data.startswith(b">") or compressed:
            raise ValueError("Expected an uncompressed FASTA reference: " + str(path))
    if lowered in ALIGNMENT_TYPES:
        actual = "bam" if data.startswith(b"BAM\x01") else "sam" if b"\t" in data and not compressed else None
        # RNA is a biological workflow type, not a different on-disk SAM/BAM
        # encoding. Keep that semantic type when recognizing the file format.
        allowed_formats = {value.removesuffix('-rna') for value in (allowed_types or [lowered])}
        if actual not in allowed_formats:
            raise ValueError("Expected a compatible SAM/BAM alignment file: " + str(path))
    if lowered in ("bcf", "bcf-likelihoods") and not data.startswith(b"BCF\x02"):
        raise ValueError("Expected a BCF file: " + str(path))
    if lowered in ("vcf", "vcf-all", "vcf-pass"):
        if not data.startswith(b"##fileformat=VCF") and not ("bcf" in (allowed_types or []) and data.startswith(b"BCF\x02")):
            raise ValueError("Expected a compatible VCF/BCF variant file: " + str(path))
    if (required_state or {}).get("compression") == "none" and compressed:
        raise ValueError("This operation requires uncompressed input: " + str(path))
    if (required_state or {}).get("compression") == "bgzf" and _compression_kind(path, compressed) != "bgzf":
        raise ValueError("This operation requires BGZF-compressed input: " + str(path))


def _check_path_policy(tool, paths):
    """Enforce declared native filename limitations before launching a tool."""
    policy = tool.get('pathPolicy', {})
    for path in paths:
        value = str(path)
        if policy.get('asciiOnly') and not value.isascii():
            raise ValueError(tool['name'] + ' requires ASCII-only installation, input and results paths: ' + value)
        forbidden = [c for c in policy.get('forbiddenCharacters', []) if c in value]
        if forbidden:
            raise ValueError(tool['name'] + ' cannot use paths containing ' + ', '.join(repr(c) for c in forbidden) + ': ' + value)


class NativeBackend:
    """JSON-lines bridge into the existing manifest runner and Job Object."""
    def __init__(self, app_root):
        self.app_root = _resolved_path(app_root)
        self._process_lock = threading.RLock()
        self._processes = set()
        self._closed = False

    def _spawn(self, *args, **kwargs):
        with self._process_lock:
            if self._closed:
                raise InterruptedError("The workbench is closing.")
            process = subprocess.Popen(*args, **kwargs)
            self._processes.add(process)
            return process

    def _release(self, process):
        with self._process_lock:
            self._processes.discard(process)

    def shutdown(self):
        """Bounded fallback after cooperative cancellation on desktop EOF."""
        with self._process_lock:
            self._closed = True
            processes = list(self._processes)
        for process in processes:
            if process.poll() is None:
                try:
                    process.terminate()
                    process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=2)
                except OSError:
                    pass
            self._release(process)

    def run(self, request, event, cancel):
        request_path = Path(request["output_folder"]) / "bridge-request.json"
        # Temporary environment is host-owned orchestration, not an extension
        # of the bridge's strictly enumerated native request schema.
        write_json(request_path, {key: value for key, value in request.items() if key != 'temporary_folder'})
        stopped = threading.Event()
        def watch():
            while not stopped.wait(0.1):
                if cancel.is_set():
                    _io_path(request["cancel_file"]).write_text("cancel\n", encoding="ascii")
                    return
        watcher = threading.Thread(target=watch, daemon=True)
        watcher.start()
        process = None
        result = None
        try:
            environment = None
            if request.get('temporary_folder'):
                environment = dict(os.environ)
                environment.update(TMP=request['temporary_folder'], TEMP=request['temporary_folder'], TMPDIR=request['temporary_folder'])
            process = self._spawn([str(self.app_root / "WorkbenchBridge.exe"), "run", "--request", str(request_path)],
                                       cwd=None if os.name == "nt" else str(self.app_root), stdin=subprocess.DEVNULL,
                                       stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                       text=True, encoding="utf-8", errors="replace", env=environment,
                                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            for line in process.stdout:
                try:
                    item = json.loads(line)
                except (ValueError, TypeError):
                    event({"type": "log", "message": line.rstrip()})
                    continue
                if "success" in item or item.get("type") == "result":
                    result = item.get("result", item)
                else:
                    event(item)
            code = process.wait()
            if result is None:
                result = {"success": False, "cancelled": cancel.is_set(), "message": f"Native runner exited without a result (exit {code}).", "outputs": []}
            if code and result.get("success"):
                result = dict(result, success=False, message=f"Native runner exited with code {code}.")
            return result
        finally:
            stopped.set()
            watcher.join(timeout=1)
            if process and process.poll() is None:
                process.terminate()  # Closing the bridge closes its kill-on-close job.
                try:
                    process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=2)
            if process:
                self._release(process)

    def inspect_alignment(self, executable, path, cancel):
        if cancel.is_set():
            raise InterruptedError("Cancelled before alignment preflight.")
        process = self._spawn([str(executable), "view", "-H", str(path)], stdin=subprocess.DEVNULL,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                              creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        try:
            while True:
                try:
                    out, err = process.communicate(timeout=0.2)
                    break
                except subprocess.TimeoutExpired:
                    if cancel.is_set():
                        process.terminate()
                        try:
                            process.communicate(timeout=2)
                        except subprocess.TimeoutExpired:
                            process.kill()
                            process.communicate(timeout=2)
                        raise InterruptedError("Cancelled during alignment preflight.")
            if cancel.is_set() or self._closed:
                raise InterruptedError("Cancelled during alignment preflight.")
            if process.returncode:
                raise ValueError("Cannot inspect alignment header: " + err.decode("utf-8", "replace")[:2000])
            if len(out) > 32 * 1024 * 1024:
                raise ValueError("Alignment header is too large.")
            return out.decode("utf-8", "strict")
        finally:
            self._release(process)


class Engine:
    def __init__(self, app_root, catalog=None, backend=None):
        self.app_root = _resolved_path(app_root)
        if catalog is None:
            try:
                from .catalog import load_catalog
            except ImportError:
                from catalog import load_catalog
            catalog = load_catalog(self.app_root)
        self.catalog = catalog
        self.tools = catalog["tools"]
        self.backend = backend or NativeBackend(self.app_root)
        # Cache publication retains its interprocess lease. Serializing builders
        # inside this engine avoids treating two ready local consumers of the
        # same index as conflicting application processes.
        self._index_build_lock = threading.Lock()

    def _tool(self, node, optional=False):
        try:
            return resolve_tool(self.catalog,node.get('tool'),node.get('pin'))
        except ValueError:
            if optional:
                return {}
            raise

    def _structure(self, graph):
        safe_json(graph)
        if not isinstance(graph, dict) or not isinstance(graph.get("nodes"), list) or not isinstance(graph.get("sources"), list):
            raise ValueError("A workspace must contain nodes and input slots.")
        if len(graph["nodes"]) > MAX_NODES or len(graph["sources"]) > MAX_SOURCES:
            raise ValueError("This workspace exceeds the supported step or input limit.")
        if not clean_text(graph.get("name", "Workspace"), 200):
            raise ValueError("The workspace name must be short plain text.")
        identities = set()
        for item, prefix in [(n, "step-") for n in graph["nodes"]] + [(s, "input-") for s in graph["sources"]]:
            if not isinstance(item, dict) or not ID_RE.fullmatch(str(item.get("id", ""))) or not item["id"].startswith(prefix):
                raise ValueError("Every step and input needs a valid stable identifier.")
            if item["id"] in identities:
                raise ValueError("A stable identifier is used more than once.")
            identities.add(item["id"])
            if item.get("label") is not None and not clean_text(item["label"], 200):
                raise ValueError("Labels must be short plain text.")
        for node in graph["nodes"]:
            if not clean_text(node.get("tool", ""), 200) or not isinstance(node.get("params", {}), dict) or not isinstance(node.get("inputs", {}), dict):
                raise ValueError("Each step needs an installed tool, named parameters and named input connections.")
        for source in graph["sources"]:
            if not clean_text(source.get("type", ""), 64) or not isinstance(source.get("files", {}), dict):
                raise ValueError("Each input slot needs a data type and named file bindings.")
        return {n["id"]: n for n in graph["nodes"]}, {s["id"]: s for s in graph["sources"]}

    def _outputs(self, node):
        return {o["id"]: o for o in self._tool(node,optional=True).get("outputs", [])}

    def _descriptor(self, ref, nodes, sources):
        if ref in sources:
            return sources[ref]
        if "::" not in ref:
            raise ValueError("Unknown source " + ref + ". Choose a named output.")
        identity, output = ref.split("::", 1)
        if identity not in nodes or output not in self._outputs(nodes[identity]):
            raise ValueError("The selected output is no longer available: " + ref)
        return self._outputs(nodes[identity])[output]

    def _topology(self, graph):
        nodes = {n["id"]: n for n in graph["nodes"]}
        deps = {identity: set() for identity in nodes}
        for node in graph["nodes"]:
            for refs in node.get("inputs", {}).values():
                if isinstance(refs, list):
                    deps[node["id"]].update(r.split("::", 1)[0] for r in refs if isinstance(r, str) and "::" in r and r.split("::", 1)[0] in nodes)
        order = []
        remaining = set(nodes)
        while remaining:
            ready = [n["id"] for n in graph["nodes"] if n["id"] in remaining and not (deps[n["id"]] & remaining)]
            if not ready:
                raise ValueError("The pipeline contains a cycle. Connect an earlier output or remove the cyclic connection.")
            order.extend(ready)
            remaining.difference_update(ready)
        return order, deps

    def validate(self, graph, check_files=True):
        errors, warnings = [], []
        def error(message, node=None, port=None):
            errors.append(dict(message=message, **({"nodeId": node} if node else {}), **({"portId": port} if port else {})))
        try:
            nodes, sources = self._structure(graph)
        except (ValueError, TypeError, AttributeError) as exc:
            return {"ok": False, "valid": False, "errors": [{"message": str(exc)}], "warnings": [], "issues": [{"severity": "error", "message": str(exc)}], "order": []}
        if not nodes:
            error("Add a tool to this workspace.")
        for node in nodes.values():
            identity = node["id"]
            try:
                tool = self._tool(node)
            except ValueError as exc:
                error(str(exc), identity)
                continue
            try:
                _check_path_policy(tool, [self.app_root, self.app_root / tool.get('packFolder', '')])
            except ValueError as exc:
                error(str(exc), identity)
            params = node.get("params", {})
            inputs = node.get("inputs", {})
            if not isinstance(params, dict) or not isinstance(inputs, dict):
                error("Parameters and input connections must be named objects.", identity)
                continue
            fields = {p["id"]: p for p in tool.get("params", [])}
            resolved_params = {}
            for key in params:
                if key not in fields:
                    error("Unknown parameter: " + key, identity)
            for field in fields.values():
                try:
                    resolved_params[field['id']] = _parameter(field, params.get(field["id"], _field_default(field)))
                except (ValueError, TypeError) as exc:
                    error(str(exc), identity)
            for constraint in tool.get('parameterConstraints', []):
                left, right = constraint['left'], constraint['right']
                if resolved_params.get(left, '')!='' and resolved_params.get(right, '')!='':
                    if constraint['operator']=='<=' and int(resolved_params[left])>int(resolved_params[right]):
                        error(fields[left]['label']+' must be less than or equal to '+fields[right]['label']+'.',identity)
                    elif constraint['operator']=='!=' and resolved_params[left]==resolved_params[right]:
                        error(fields[left]['label']+' must differ from '+fields[right]['label']+'.',identity)
            try:
                _check_parameter_ranges(tool,resolved_params)
            except ValueError as exc:
                error(str(exc),identity)
            ports = {p["id"]: p for p in tool.get("ports", [])}
            local_values = {}
            for key in inputs:
                if key not in ports:
                    error("Unknown input port: " + key, identity)
            for port in ports.values():
                refs = inputs.get(port["id"], [])
                if not isinstance(refs, list) or not all(isinstance(r, str) for r in refs):
                    error("An input connection must be a list of named sources.", identity, port["id"])
                    continue
                minimum, maximum = int(port.get("min", 1)), int(port.get("max", 1))
                if not minimum <= len(refs) <= maximum:
                    error(f"{port.get('label', port['id'])} needs {minimum}" + (f"–{maximum}" if maximum != minimum else "") + " source(s).", identity, port["id"])
                if len(set(refs)) != len(refs):
                    error("The same output cannot be connected twice to one input.", identity, port["id"])
                for ref in refs:
                    try:
                        desc = self._descriptor(ref, nodes, sources)
                        accepts = port.get("accepts", [port.get("type")])
                        if desc.get("type") not in accepts and "*" not in accepts:
                            raise ValueError("Incompatible input: " + str(desc.get("type")) + " cannot feed " + str(port.get("type")) + ".")
                        if ref.startswith(identity + "::"):
                            raise ValueError("A tool cannot consume its own output.")
                        contract=tool.get('requiresReferenceIndex')
                        if contract and port['id']==contract['port']:
                            if '::' not in ref:
                                raise ValueError('Connect the verified Build short-read reference index output; an arbitrary .mmi file is not supported.')
                            producer=self._tool(nodes[ref.split('::',1)[0]])
                            built=producer.get('referenceIndex',{})
                            expected=next((e for e in tool['executables'] if e['id']==contract['tool']),None)
                            actual=next((e for e in producer.get('executables',[]) if e['id']==built.get('tool')),None)
                            if (built.get('format')!=contract['format'] or built.get('outputPort')!=ref.split('::',1)[1] or
                                    not actual or not expected or any(actual.get(k)!=expected.get(k) for k in ('id','version','sha256'))):
                                raise ValueError('The index producer is incompatible with this exact mapping tool and format.')
                        required_state = port.get("requiredState", {})
                        known_state = desc.get("state", {}) if "::" in ref else {}
                        for key, value in required_state.items():
                            if key in known_state and known_state[key] != value:
                                raise ValueError("This input requires " + key + "=" + str(value) + ". Add the appropriate preparation step.")
                        if ref in sources and check_files:
                            mapped = _source_fields(desc, port)
                            filenames = list(mapped.values())
                            if len(filenames) > 1 and len(set(os.path.normcase(str(Path(p).absolute())) for p in filenames)) != len(filenames):
                                raise ValueError("Paired inputs must be two different files.")
                            for filename in filenames:
                                if not clean_text(filename, 32768):
                                    raise ValueError("Choose a valid local input file.")
                                path = _ordinary(filename)
                                _check_path_policy(tool, [path])
                                _check_file_kind(path, desc.get("type", "file"), required_state, accepts)
                            local_values.update(mapped)
                    except (ValueError, OSError, TypeError, EOFError, UnicodeError) as exc:
                        error(str(exc), identity, port["id"])
            if check_files:
                try:
                    _check_distinct_files(tool, local_values)
                except (ValueError, OSError) as exc:
                    error(str(exc), identity)
        try:
            order, _ = self._topology(graph)
        except (ValueError, TypeError, AttributeError) as exc:
            error(str(exc))
            order = []
        if order:
            lineages = {}
            reference_lineages = {}
            for identity in order:
                node = nodes[identity]
                sets = []
                for refs in node.get("inputs", {}).values():
                    if not isinstance(refs, list):
                        continue
                    for ref in refs:
                        if not isinstance(ref, str):
                            continue
                        if ref in sources:
                            source = sources[ref]
                            if source.get("type") in ("reference", "fasta", "reference-index", "minimap2-sr-index", "metrics", "report", "text", "json"):
                                continue
                            files = source.get("files", {})
                            keys = {os.path.normcase(str(Path(p).absolute())) for p in files.values() if isinstance(p, str) and p} if isinstance(files, dict) else set()
                            sets.append(keys or {ref})
                        elif "::" in ref:
                            sets.append(lineages.get(ref.split("::", 1)[0], set()))
                tool = self._tool(node, optional=True)
                if tool.get("merge") or node.get("tool") == "bam/merge":
                    seen = set()
                    for lineage in sets:
                        if seen & lineage:
                            error("Merge inputs share original reads or an alignment file. Merging alternate analyses would count those reads twice.", identity)
                            break
                        seen.update(lineage)
                    warnings.append({"nodeId": identity, "message": "BAM merge requires coordinate order, matching reference dictionaries, and one sample with distinct read groups. Headers are checked before execution. Mark duplicates after merging lanes."})
                lineages[identity] = set().union(*sets) if sets else set()
                explicit_reference, alignment_reference = set(), set()
                for port in tool.get("ports", []):
                    for ref in node.get("inputs", {}).get(port["id"], []):
                        if port.get("type") == "reference":
                            explicit_reference.update({ref} if ref in sources else reference_lineages.get(ref.split("::", 1)[0], set()))
                        elif port.get("type") in ALIGNMENT_TYPES | {'minimap2-sr-index'} and "::" in ref:
                            alignment_reference.update(reference_lineages.get(ref.split("::", 1)[0], set()))
                if explicit_reference and alignment_reference and explicit_reference != alignment_reference:
                    error("The alignment and this operation use different reference input slots. Connect the same reference slot throughout the pipeline.", identity)
                reference_lineages[identity] = explicit_reference or alignment_reference
        issues = [dict(item, severity="error") for item in errors] + [dict(item, severity="warning") for item in warnings]
        return {"ok": not errors, "valid": not errors, "errors": errors, "warnings": warnings, "issues": issues, "order": order}

    def review(self, graph):
        result = self.validate(graph)
        try:
            result["methods"] = self.methods(graph)
        except (ValueError, TypeError, AttributeError, KeyError):
            result["methods"] = "Correct the workspace validation errors to generate planned methods."
        return result

    def rank_groups(self, graph):
        order, dependencies = self._topology(graph)
        rank = {}
        groups = {}
        for identity in order:
            rank[identity] = max([rank[d] for d in dependencies[identity]] + [0]) + 1
            groups.setdefault(rank[identity], []).append(identity)
        return [{"rank": level, "nodes": identities} for level, identities in sorted(groups.items())]

    def methods(self, graph, completed=False, statuses=None, references=None, index_actions=None, recovered=None):
        nodes = {n["id"]: n for n in graph.get("nodes", []) if isinstance(n, dict)}
        sources = {s["id"]: s for s in graph.get("sources", []) if isinstance(s, dict)}
        try:
            order, _ = self._topology(graph)
        except (ValueError, TypeError, AttributeError):
            order = list(nodes)
        lines = []
        if completed:
            lines.append("Executed methods (only successfully completed operations are described):")
        else:
            lines.append("Planned methods (review before use; this describes the selected analysis, not completed results):")
        for identity in order:
            if statuses is not None and statuses.get(identity) != "success":
                continue
            node = nodes[identity]
            tool = self._tool(node, optional=True)
            if not tool:
                continue
            versions = "; ".join(f"{e['id']} {e.get('version', '')}" for e in tool.get("executables", []))
            operation = node_name(node, tool)
            verbs = "was performed" if completed else "will be performed"
            line = f"Step {display_id(identity)} ({operation}) {verbs} using {versions or tool['name']} (pack {tool.get('packId', 'builtin')} {tool.get('packVersion', '')})."
            if completed and identity in (recovered or set()):
                line = f"Step {display_id(identity)} ({operation}) reused verified completed output bytes previously produced using {versions or tool['name']} (pack {tool.get('packId', 'builtin')} {tool.get('packVersion', '')}). The scientific command was not run in this analysis."
            elif completed and (index_actions or {}).get(identity)=='reused':
                line=f"Step {display_id(identity)} ({operation}) reused a verified reference index previously produced using {versions or tool['name']} (pack {tool.get('packId', 'builtin')} {tool.get('packVersion', '')}). The indexing command was not run in this analysis."
            description = (tool.get("methodsDescription") or tool.get("description", "")).strip()
            if description:
                line += " " + description
            params = []
            for field in tool.get("params", []):
                value = node.get("params", {}).get(field["id"], _field_default(field))
                if str(value):
                    params.append(field.get("label", field["id"]) + "=" + str(value))
            if params:
                line += " Settings: " + "; ".join(params) + "."
            bindings = []
            for port in tool.get("ports", []):
                names = []
                for ref in node.get("inputs", {}).get(port["id"], []):
                    if ref in sources:
                        names.append(display_id(ref) + " · " + sources[ref].get("label", "Input"))
                    elif "::" in ref:
                        producer_id, output_id = ref.split("::", 1)
                        if producer_id in nodes:
                            producer = nodes[producer_id]
                            producer_tool = (self._tool(producer, optional=True) or {"name": "Unavailable tool"})
                            output = self._outputs(producer).get(output_id, {})
                            names.append(display_id(producer_id) + " · " + node_name(producer, producer_tool) + " → " + output.get("label", output_id))
                if names:
                    bindings.append(port.get("label", port["id"]) + ": " + "; ".join(names))
            if bindings:
                line += " Inputs: " + " | ".join(bindings) + "."
            lines.append(line)
        reference_paths = used_paths(graph, statuses)
        # A preview reads only local receipt metadata. Completed methods receive
        # frozen evidence explicitly and must never consult a changed library.
        verified_references = references is not None
        if references is None:
            references = {} if completed else collect_references(self.app_root, reference_paths)
        description = reference_methods(references, reference_paths, verified=verified_references)
        if description:
            lines.append(description)
        citations = []
        for identity in order:
            if statuses is not None and statuses.get(identity) != "success":
                continue
            tool = self._tool(nodes[identity], optional=True)
            for citation in tool.get("citations", []):
                text = citation["text"] + (" " + citation["url"] if citation.get("url") else "")
                if text not in citations:
                    citations.append(text)
        if citations:
            lines.append("Tool references:\n" + "\n".join(citations))
        lines.append("Operations run locally in dependency order under the frozen scheduling policy. CPU reservations govern admission, not operating-system CPU limits; unknown requirements run exclusively. The run record records exact packs, parameters, input identities, outputs and completion states.")
        return "\n\n".join(lines) + "\n"

    def save_pipeline(self, graph):
        # Bindings never enter a reusable pipeline. Validate only their schema
        # defaults in this throwaway copy so an unbound loaded template can be
        # saved again; review/prepare still validate the actual supplied graph.
        validation_graph = copy.deepcopy(graph)
        if isinstance(validation_graph, dict) and isinstance(validation_graph.get("nodes"), list):
            for node in validation_graph["nodes"]:
                if not isinstance(node, dict) or not isinstance(node.get("params", {}), dict):
                    continue
                tool_id = node.get("tool")
                tool = self._tool(node, optional=True) if isinstance(tool_id, str) else {}
                for field in tool.get("params", []):
                    if _binding_parameter(field):
                        node.setdefault("params", {})[field["id"]] = _field_default(field)
        review = self.validate(validation_graph, check_files=False)
        if not review["ok"]:
            raise ValueError("; ".join(i["message"] for i in review["errors"]))
        if len(graph["nodes"]) < 2:
            raise ValueError("A pipeline needs at least two connected tools. Save one tool's settings as a preset.")
        neighbors = {item["id"]: set() for item in graph["nodes"] + graph["sources"]}
        for node in graph["nodes"]:
            for refs in node.get("inputs", {}).values():
                for ref in refs:
                    parent = ref.split("::", 1)[0]
                    neighbors[node["id"]].add(parent)
                    neighbors[parent].add(node["id"])
        seen, pending = set(), [graph["nodes"][0]["id"]]
        while pending:
            current = pending.pop()
            if current not in seen:
                seen.add(current)
                pending.extend(neighbors[current] - seen)
        if any(n["id"] not in seen for n in graph["nodes"]):
            raise ValueError("Save a connected pipeline. Unrelated tools do not form one workflow.")
        saved = {key: copy.deepcopy(graph[key]) for key in ("name", "nextNode", "nextSource") if key in graph}
        saved.update(schema=1, nodes=[], sources=[])
        for node in graph["nodes"]:
            saved["nodes"].append({key: copy.deepcopy(node[key]) for key in ("id", "tool", "params", "label", "inputs", "pin") if key in node})
        for source in graph["sources"]:
            slot = {key: copy.deepcopy(source[key]) for key in ("id", "type", "label") if key in source}
            # Reconstruct picker schema from the installed receiving port,
            # excluding any user-supplied nested file/default binding metadata.
            for node in graph["nodes"]:
                for port in self._tool(node).get("ports", []):
                    if source["id"] in node.get("inputs", {}).get(port["id"], []):
                        slot["fields"] = copy.deepcopy(port.get("fields", []))
                        for field in slot["fields"]:
                            field["default"] = ""
                        # Explicit paired workflow inputs own canonical read
                        # roles across tools whose manifest field IDs differ.
                        # Retain those IDs using trusted receiving-port schema;
                        # never copy nested user-supplied values/defaults.
                        canonical_pair = {"read1": "reads1", "read2": "reads2"}
                        source_schema = source.get("fields", [])
                        source_pair = {field.get("role"): field.get("id") for field in (source_schema if isinstance(source_schema, list) else [])
                                       if isinstance(field, dict)}
                        if source.get("type") == "pair" and source_pair == canonical_pair and port.get("type") == "pair" and len(slot["fields"]) == 2:
                            for field, role in zip(slot["fields"], ("read1", "read2")):
                                field["role"], field["id"] = role, canonical_pair[role]
                                field["differentFrom"] = "reads2" if role == "read1" else "reads1"
                        break
                if "fields" in slot:
                    break
            saved["sources"].append(slot)
        for node in saved["nodes"]:
            node["pin"] = pin_for(self._tool(node))
            # Sample and library labels are analysis bindings, not reusable settings.
            for field in self._tool(node).get("params", []):
                if _binding_parameter(field):
                    node.get("params", {}).pop(field["id"], None)
        self._counters(saved)
        return saved

    def save_preset(self, node):
        tool = self._tool(node)
        if not tool:
            raise ValueError("Select an installed tool.")
        values = {}
        for field in tool.get("params", []):
            if not _binding_parameter(field):
                values[field["id"]] = _parameter(field, node.get("params", {}).get(field["id"], _field_default(field)))
        _check_parameter_ranges(tool,values)
        return {"schema": 1, "kind": "tool-preset", "tool": tool["id"], "pin": pin_for(tool), "params": values}

    def _counters(self, graph):
        for field, collection in (("nextNode", "nodes"), ("nextSource", "sources")):
            minimum = max([int(n["id"].rsplit("-", 1)[1]) for n in graph[collection]] + [0]) + 1
            value = graph.get(field, minimum)
            graph[field] = max(minimum, value if isinstance(value, int) and 0 < value < 1000000000 else minimum)

    def prepare(self, graph, output_parent, cancel=None, index_policy='reuse', run_metadata=None, resource_policy=None, restart_from=None, project_metadata=None, _preview=False):
        if restart_from is not None:
            source_folder = restart_from.get('sourceFolder') if isinstance(restart_from, dict) else restart_from
            prior, _, _ = recovery._source(source_folder)
            if run_metadata is None:
                run_metadata = prior.get('batch')
            if project_metadata is None:
                project_metadata = prior.get('project')
            if index_policy == 'reuse':
                index_policy = prior.get('referenceIndexPolicy', 'reuse')
        if index_policy not in ('reuse','rebuild'):
            raise ValueError('Unknown reference index reuse policy.')
        if project_metadata is not None:
            try:
                from .project_manager import validate_project_metadata
            except ImportError:
                from project_manager import validate_project_metadata
            project_metadata = validate_project_metadata(project_metadata)
        if run_metadata is not None:
            if (not isinstance(run_metadata,dict) or set(run_metadata)!={'batchId','sampleId','metadata'} or
                    not isinstance(run_metadata['batchId'],str) or not re.fullmatch(r'[0-9a-f]{32}',run_metadata['batchId']) or
                    not clean_text(run_metadata['sampleId'],128) or not run_metadata['sampleId'] or
                    not isinstance(run_metadata['metadata'],dict) or
                    len(canonical(run_metadata).encode('utf-8'))>16*1024):
                raise ValueError('Invalid frozen batch metadata.')
            safe_json(run_metadata)
            run_metadata=copy.deepcopy(run_metadata)
        preparation_started = time.perf_counter()
        measurements = performance.preparation()
        with performance.measure(measurements["phases"], "validation"):
            graph = copy.deepcopy(graph)
            review = self.validate(graph)
            if not review["ok"]:
                raise ValueError("; ".join(i["message"] for i in review["errors"]))
            resource_policy = execution_resources.normalize(resource_policy, graph['nodes'])
        with performance.measure(measurements["phases"], "freezing"):
            parent = Path(output_parent).absolute()
            if not _io_path(parent).is_dir() or _io_path(parent).is_symlink():
                raise ValueError("Select an existing output folder.")
            for ancestor in [parent] + list(parent.parents):
                physical = _io_path(ancestor)
                if physical.is_symlink() or (hasattr(physical, "is_junction") and physical.is_junction()):
                    raise ValueError("The output folder must not use symbolic links or junctions.")
            parent = _resolved_path(parent)
            storage_evidence = {'output': execution_resources.storage(parent)}
            if resource_policy['temporaryFolder']:
                storage_evidence['temporary'] = execution_resources.storage(resource_policy['temporaryFolder'])
            nodes = {n["id"]: n for n in graph["nodes"]}
            _, dependencies = self._topology(graph)
            frozen_nodes = []
            for identity in review["order"]:
                node = nodes[identity]
                tool = copy.deepcopy(self._tool(node))
                self._verify_manifest(tool)
                _check_path_policy(tool, [parent] + [parent / relative for output in tool.get('outputs', [])
                                                   for relative in output.get('files', {}).values()])
                node["pin"] = pin_for(tool)
                node["params"] = {p["id"]: _parameter(p, node.get("params", {}).get(p["id"], _field_default(p))) for p in tool.get("params", [])}
                frozen = {"id": identity, "tool": tool, "params": copy.deepcopy(node["params"]), "label": node_name(node, tool), "inputs": copy.deepcopy(node.get("inputs", {})), "dependencies": sorted(dependencies[identity])}
                if self._alignment_ports(tool):
                    # Header inspection is part of the analysis contract too. Freeze
                    # the helper before execution so later installations cannot
                    # change which SAMtools inspects the selected BAMs.
                    helper = ((project_metadata or {}).get('validationTools', {}).get(identity)
                              or self._samtools_selection(tool))
                    frozen['validationTools'] = {'samtools': copy.deepcopy(helper)}
                    if project_metadata is not None:
                        self._samtools(frozen)
                frozen_nodes.append(frozen)
            if project_metadata is not None:
                required = {node['id'] for node in frozen_nodes if node.get('validationTools')}
                if set(project_metadata['validationTools']) != required:
                    raise ValueError('Historical project validation helpers differ from this workflow.')
        with performance.measure(measurements["phases"], "input_hashing"):
            evidence = {}
            used_sources = {r for n in graph["nodes"] for rs in n.get("inputs", {}).values() for r in rs if "::" not in r}
            for source in graph["sources"]:
                if source["id"] not in used_sources:
                    continue
                for key, filename in source.get("files", {}).items():
                    path = _ordinary(filename)
                    if source.get("type") in ALIGNMENT_TYPES | {"vcf", "vcf-pass", "bcf"}:
                        rna = source.get('type', '').endswith('-rna')
                        signature, _ = _head(path)
                        if signature.startswith(b"BAM\x01"):
                            source["type"] = "bam-rna" if rna else "bam"
                        elif signature.startswith(b"BCF\x02"):
                            source["type"] = "bcf"
                        elif signature.startswith(b"##fileformat=VCF"):
                            # PASS-only is a declared subset, not established by a header.
                            source["type"] = "vcf"
                        elif source.get("type") in ALIGNMENT_TYPES:
                            source["type"] = "sam-rna" if rna else "sam"
                    source["files"][key] = str(path)
                    if str(path) not in evidence:
                        before = _io_path(path).stat()
                        checksum = digest_file(path, cancel)
                        after = _io_path(path).stat()
                        if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
                            raise ValueError("An input changed while preparing the run: " + str(path))
                        evidence[str(path)] = {"path": str(path), "bytes": after.st_size, "mtime_ns": after.st_mtime_ns, "sha256": checksum}
            if project_metadata is not None:
                bound = {str(_resolved_path(item['boundPath'])): item for item in project_metadata['dependencies']}
                if set(bound) != set(evidence) or len(bound) != len(project_metadata['dependencies']):
                    raise ValueError('Historical project files differ from this workflow’s actual input bindings.')
                for path, item in bound.items():
                    if any(evidence[path][key] != item[key] for key in ('bytes', 'sha256')):
                        raise ValueError('A historical project input differs from its recorded bytes: ' + path)
        with performance.measure(measurements["phases"], "reference_provenance"):
            references = collect_references(self.app_root, evidence, evidence=evidence)
            for path, reference in references.items():
                evidence[path]["reference"] = copy.deepcopy(reference)
            self._assert_disjoint_hashes(graph, evidence)
            if cancel is not None and cancel.is_set():
                raise InterruptedError("Cancelled before creating the run.")
        with performance.measure(measurements["phases"], "export"):
            self._counters(graph)
            run_id = "run-" + datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:8]
            folder = parent / run_id
            plan = {"schema": 1, "id": run_id, "created": utc(), "folder": str(folder), "graph": graph, "nodes": frozen_nodes, "inputs": evidence, "references": references, "warnings": review["warnings"], "scheduler": "resource-budgeted-ready-dag", "methods": self.methods(graph, references=references)}
            plan['resources'] = resource_policy
            plan['storageReadiness'] = storage_evidence
            if project_metadata is not None:
                plan['project'] = project_metadata
                plan['methods'] += '\nImported project '+project_metadata['id']+' (manifest SHA-256 '+project_metadata['manifestSha256']+'). The frozen project section retains descriptive sample metadata and historical reference receipts separately from the current local reference library. Input bytes were verified; those receipts do not authenticate a publisher or create a local reference registration.\n'
            plan['referenceIndexPolicy']=index_policy
            if run_metadata is not None:
                plan['batch']=run_metadata
                plan['methods']+='\nBatch '+run_metadata['batchId']+', sample '+run_metadata['sampleId']+'. The frozen plan and CWL retain the selected sample-table metadata and file bindings.\n'
            if restart_from is not None:
                plan['recovery'] = recovery.review(self, plan, restart_from, cancel)
                plan['methods'] += '\nCompleted-step restart from '+plan['recovery']['sourceRunId']+'. Only selected verified complete products will be copied into this new result; other steps will run. No within-tool checkpoint is resumed.\n'
            workflow = export_workflow(plan, self.app_root)
        measurements.update(status="completed", elapsedSeconds=performance.elapsed(preparation_started, time.perf_counter))
        plan["performancePreparation"] = measurements
        # Bind the executable export to the frozen plan without a circular hash:
        # its definition excludes only the plan digest and execution outcome.
        plan["workflowExport"] = {"file": "workflow.cwl", "format": "CWL v1.2", "definitionSha256": definition_sha256(workflow)}
        plan["sha256"] = hashlib.sha256(canonical(plan).encode("utf-8")).hexdigest()
        workflow["$graph"][0]["nw:planSha256"] = plan["sha256"]
        if _preview:
            return plan
        _io_path(folder).mkdir(mode=0o700)
        write_json(folder / "plan.json", plan)
        write_json(folder / "graph.json", graph)
        write_json(folder / "workflow.cwl", workflow)
        if references:
            write_json(folder / "reference-provenance.json", {"schema": 1, "inputs": references})
        _io_path(folder / "methods-planned.txt").write_text(plan["methods"], encoding="utf-8")
        _io_path(folder / "pipeline.svg").write_text(self.diagram(plan), encoding="utf-8")
        write_json(folder / "performance.json", performance.make_record(plan))
        return plan

    def review_restart(self, graph, source_folder, cancel=None, resource_policy=None):
        source, _, _ = recovery._source(source_folder)
        return self.prepare(graph, Path(source_folder).absolute().parent, cancel=cancel,
                            index_policy=source.get('referenceIndexPolicy', 'reuse'),
                            run_metadata=source.get('batch'), resource_policy=resource_policy,
                            restart_from=source_folder, _preview=True)['recovery']

    def _assert_disjoint_hashes(self, graph, evidence):
        sources = {s["id"]: s for s in graph["sources"]}
        nodes = {n["id"]: n for n in graph["nodes"]}
        order, _ = self._topology(graph)
        lineages = {}
        for identity in order:
            node = nodes[identity]
            groups = []
            for refs in node.get("inputs", {}).values():
                for ref in refs:
                    if ref in sources:
                        source = sources[ref]
                        if source.get("type") not in ALIGNMENT_TYPES | {"pair", "reads"}:
                            continue
                        groups.append({evidence[str(_resolved_path(path))]["sha256"] for path in source.get("files", {}).values()})
                    else:
                        groups.append(lineages.get(ref.split("::", 1)[0], set()))
            if self._tool(node).get("merge") or node["tool"] == "bam/merge":
                seen = set()
                for group in groups:
                    if seen & group:
                        raise ValueError("Merge inputs contain identical original file content, even though filenames differ. This would count those reads twice.")
                    seen.update(group)
            lineages[identity] = set().union(*groups) if groups else set()

    def _verify_manifest(self, tool):
        if tool.get("builtin") or tool["id"].startswith("builtin/"):
            return
        folder = Path(tool["packFolder"])
        if not folder.is_absolute():
            folder = self.app_root / folder
        folder = _resolved_path(folder)
        packs = _resolved_path(self.app_root / "packs")
        if not folder.is_relative_to(packs):
            raise ValueError("Tool pack is outside the installed pack directory.")
        if digest_file(folder / "pack.ini") != tool["manifestSha256"]:
            raise ValueError("The tool pack manifest changed. Reload the catalogue before running.")
        if tool.get("schemaAsset"):
            asset = tool["schemaAsset"]
            path = _safe_relative(folder, asset["path"])
            _ordinary(path)
            if digest_file(path) != asset["sha256"]:
                raise ValueError("The pack's typed workflow schema changed. Reinstall the original pack before running.")

    def _resolve_values(self, node, sources, outputs):
        values = dict(node["params"])
        for port in node["tool"].get("ports", []):
            collections = {field: [] for field in port.get("manifestInputs", [port["id"]])}
            for ref in node["inputs"].get(port["id"], []):
                if ref in sources:
                    mapped = _source_fields(sources[ref], port)
                else:
                    produced = outputs.get(ref)
                    if not produced:
                        raise ValueError("The required named output was not produced: " + ref)
                    wanted = port.get("manifestInputs", [port["id"]])
                    ordered = produced.get("manifestOutputs", list(produced["files"]))
                    if len(wanted) != len(ordered):
                        raise ValueError("The named output does not match this input's file roles.")
                    mapped = dict(zip(wanted, [produced["files"][key] for key in ordered]))
                for key, value in mapped.items():
                    collections[key].append(str(value))
            for key, paths in collections.items():
                values[key] = "\n".join(paths)
        return values

    def _schema_preflight(self, node, values, cancel, input_types=None, reference_dictionary=None):
        checks = []
        for port in node["tool"].get("ports", []):
            accepted = port.get("accepts", [port["type"]])
            for field in port.get("manifestInputs", [port["id"]]):
                for filename in values.get(field, "").splitlines():
                    path = _ordinary(filename)
                    _check_path_policy(node['tool'], [path])
                    _check_file_kind(path, port["type"], port.get("requiredState", {}), accepted)
                    if port['type']=='bed':
                        evidence = _bed_evidence(path, port.get('validation', {}), reference_dictionary, cancel)
                        checks.append(dict(evidence, portId=port['id'], path=str(path)))
                    elif port['type'] in ('vcf','vcf-pass') and port.get('validation'):
                        evidence = _vcf_header_evidence(path, port['validation'], cancel)
                        checks.append(dict(evidence, portId=port['id'], path=str(path)))
                    elif port["type"] in {"fasta-nucleotide", "fasta-protein", "msa-nucleotide", "msa-protein", "fasta-nucleotide-abundance", "id-list"} or any(kind.startswith(("fasta-", "msa-")) for kind in accepted):
                        actual_type = (input_types or {}).get(str(path), port["type"])
                        evidence = _sequence_evidence(path, actual_type, accepted, port.get("requiredState", {}), cancel, allow_empty=False, rules=port.get("validation", {}))
                        checks.append(dict(evidence, portId=port["id"], path=str(path)))
                    elif port["type"] in {"reads", "pair"} and _io_path(path).stat().st_size == 0:
                        raise ValueError("No sequence records are available for this input: " + str(path))
        return checks

    @staticmethod
    def _alignment_ports(tool):
        return [p for p in tool.get('ports', []) if p.get('type') in ALIGNMENT_TYPES and
                (p.get('requiredState', {}).get('sort') or p.get('validation') or tool.get('merge') or tool['id']=='bam/merge')]

    def _samtools_selection(self, owner):
        """Prefer the node's exact pack; otherwise choose a deterministic version."""
        registry = self.catalog.get('toolVersions')
        operations = [tool for versions in registry.values() for tool in versions] if registry is not None else list(self.tools.values())
        candidates = []
        for tool in operations:
            for executable in tool.get('executables', []):
                if executable.get('id') == 'samtools':
                    candidates.append((tool, executable))
        local = [item for item in candidates if pin_for(item[0]) == pin_for(owner)]
        # The selected workflow might be a legacy caller-supplied descriptor
        # absent from a lightweight catalogue used by an integration adapter.
        local += [(owner, e) for e in owner.get('executables', []) if e.get('id')=='samtools']
        candidates = local or candidates
        if not candidates:
            raise ValueError('Install a SAMtools pack to check alignment prerequisites.')
        def order(item):
            tool, executable = item
            numbers = tuple(int(n) for n in re.findall(r'[0-9]+', executable.get('version', '')))
            return (numbers, tuple(map(int,tool.get('packVersion','0.0.0').split('.'))),
                    tool.get('packId',''), tool['id'], executable['sha256'])
        tool, executable = max(candidates, key=order)
        return {'operation':tool['id'], 'pin':pin_for(tool), 'executable':copy.deepcopy(executable)}

    def _samtools(self, node):
        selection = node.get('validationTools', {}).get('samtools') or self._samtools_selection(node['tool'])
        tool = resolve_tool(self.catalog, selection['operation'], selection['pin'])
        executable = selection['executable']
        if executable not in tool.get('executables', []) or executable.get('id')!='samtools':
            raise ValueError('The pinned SAMtools validation helper differs from the installed pack.')
        self._verify_manifest(tool)
        folder = Path(tool['packFolder'])
        if not folder.is_absolute():
            folder = self.app_root / folder
        path = _safe_relative(folder, executable['path'])
        if digest_file(path) != executable['sha256']:
            raise ValueError('SAMtools integrity verification failed.')
        # Direct preflight callers also retain the selected helper's identity.
        node.setdefault('validationTools', {})['samtools'] = selection
        return path

    def _preflight(self, node, values, cancel, input_types=None):
        _check_distinct_files(node['tool'], values)
        required = self._alignment_ports(node['tool'])
        reference_values = [filename for port in node['tool'].get('ports',[]) if port.get('type')=='reference'
                            for field in port.get('manifestInputs',[port['id']]) for filename in values.get(field,'').splitlines()]
        needs_reference = bool(required) or any(p.get('type')=='bed' and p.get('validation',{}).get('referenceBounds') for p in node['tool'].get('ports',[]))
        if needs_reference and len(set(reference_values))>1:
            raise ValueError('This operation requires one consistent reference FASTA.')
        reference_path = reference_values[0] if reference_values and needs_reference else None
        reference = _fasta_dictionary(reference_path, cancel) if reference_path else None
        sequence_checks = self._schema_preflight(node, values, cancel, input_types, reference) if node["tool"].get("schemaAsset") else []
        if node['tool'].get('referenceIndex'):
            port=next(p for p in node['tool']['ports'] if p['id']==node['tool']['referenceIndex']['referencePort'])
            path=values[port['manifestInputs'][0]]
            sequence_checks.append(_sequence_evidence(path,'fasta-nucleotide',['fasta-nucleotide'],{'compression':'none'},cancel))
            _fasta_dictionary(path,cancel)
        if not required:
            return {"sequenceChecks": sequence_checks} if sequence_checks else None
        executable = self._samtools(node)
        headers = []
        reference_checks = []
        for port in required:
            for field in port.get("manifestInputs", [port["id"]]):
                for path in values.get(field, "").splitlines():
                    header = self.backend.inspect_alignment(executable, path, cancel)
                    parsed = _parse_header(header)
                    rules = port.get('validation', {})
                    if rules.get('singleSample'):
                        groups = parsed['readgroups']
                        if not groups or any(not g.get('ID') or not g.get('SM') for g in groups) or len({g['ID'] for g in groups})!=len(groups):
                            raise ValueError('This caller requires read groups with distinct IDs and sample (SM) metadata: '+path)
                        samples = {g['SM'] for g in groups}
                        if len(samples)!=1:
                            raise ValueError('This caller requires exactly one sample in the BAM read-group metadata: '+path)
                        parameter = rules.get('sampleParameter')
                        if parameter and values.get(parameter) not in samples:
                            raise ValueError('The selected sample name differs from the BAM read-group sample (SM): '+path)
                    wanted_sort = port.get("requiredState", {}).get("sort")
                    if (node["tool"].get("merge") or node["tool"]["id"] == "bam/merge"):
                        wanted_sort = "coordinate"
                    if wanted_sort and parsed["sort"] != wanted_sort:
                        raise ValueError("Alignment header is not " + wanted_sort + " sorted: " + path)
                    if port.get("requiredState", {}).get("mateFixed") and not any("fixmate" in pg for pg in parsed["programs"]):
                        raise ValueError("This BAM has no recorded fixmate preparation. Use Prepare paired alignments before marking duplicates.")
                    if reference is not None:
                        dictionary = parsed["dictionary"]
                        if [(row[0], int(row[1] or 0)) for row in dictionary] != [(row[0], row[1]) for row in reference]:
                            raise ValueError("The alignment reference names or lengths differ from the selected FASTA: " + path)
                        if any(row[2] and row[2].lower() != ref[2] for row, ref in zip(dictionary, reference)):
                            raise ValueError("The alignment reference MD5 differs from the selected FASTA: " + path)
                        reference_checks.append({"alignment": path, "reference": reference_path, "check": "sequence-MD5" if dictionary and all(row[2] for row in dictionary) else "contig-names-and-lengths", "note": "Headers without M5 hashes cannot prove reference sequence identity."})
                    headers.append((path, parsed))
        if node["tool"].get("merge") or node["tool"]["id"] == "bam/merge":
            dictionaries = [h["dictionary"] for _, h in headers]
            if not dictionaries or not dictionaries[0] or any(d != dictionaries[0] for d in dictionaries[1:]):
                raise ValueError("Merge inputs have different or missing reference dictionaries.")
            samples, readgroups = set(), set()
            for path, header in headers:
                if not header["readgroups"] or any(not row.get("SM") or not row.get("ID") for row in header["readgroups"]):
                    raise ValueError("Every merge input needs read groups with sample (SM) and read-group (ID) metadata: " + path)
                for row in header["readgroups"]:
                    samples.add(row["SM"])
                    if row["ID"] in readgroups:
                        raise ValueError("Merge input read-group IDs overlap. Supply distinct lane read groups before merging.")
                    readgroups.add(row["ID"])
            if len(samples) != 1:
                raise ValueError("Lane merging requires one sample; these inputs identify different samples.")
        return {"alignmentHeaders": len(headers), "referenceChecks": reference_checks, "sequenceChecks": sequence_checks,
                "validationTools":copy.deepcopy(node.get('validationTools', {}))}

    def _execute_node(self, plan, node, available_outputs, event, cancel, measurement, temporary_root):
        identity = node['id']
        folder = Path(plan['folder'])
        sources = {source['id']: source for source in plan['graph']['sources']}
        node_names = {item['id']: item['label'] for item in plan['nodes']}
        outputs = available_outputs
        measured_step = copy.deepcopy(measurement)
        entry = {'id': identity, 'name': node['label'], 'tool': node['tool']['id'],
                 'pin': pin_for(node['tool']), 'started': utc(), 'status': 'running',
                 'inputs': node['inputs'], 'outputs': {}}
        started = time.perf_counter()
        try:
            if cancel.is_set():
                raise InterruptedError('Cancelled before this step started.')
            with performance.measure(measured_step["phases"], "input_verification"):
                trusted = resolve_tool(self.catalog, node["tool"]["id"], pin_for(node["tool"]))
                if trusted is None or canonical(trusted) != canonical(node["tool"]):
                    raise ValueError("The installed operation differs from the frozen plan.")
                self._verify_manifest(node["tool"])
                values = self._resolve_values(node, sources, outputs)
                for value in values.values():
                    for filename in str(value).splitlines():
                        if filename in plan["inputs"]:
                            evidence = plan["inputs"][filename]
                            if not _io_path(filename).is_file() or digest_file(filename, cancel) != evidence["sha256"]:
                                raise ValueError("An external input changed after the plan was frozen: " + filename)
                for refs in node["inputs"].values():
                    for ref in refs:
                        if ref in outputs:
                            for key, filename in outputs[ref]["files"].items():
                                if digest_file(filename, cancel) != outputs[ref]["sha256"][key]:
                                    raise ValueError("An upstream output changed before it could be consumed: " + ref)
                step_folder = folder / display_id(identity)
                _io_path(step_folder).mkdir()
            decision = next((item for item in plan.get('recovery', {}).get('nodes', []) if item['id'] == identity), None)
            if decision and decision['action'] == 'reuse':
                recovery.verify_source(plan['recovery'])
                recovery.verify_tool_bytes(self, node, cancel)
                with performance.measure(measured_step['phases'], 'output_validation_and_hashing'):
                    entry['outputs'] = recovery.copy_outputs(decision, step_folder, cancel)
                entry.update(status='success', folder=str(step_folder), message='Reused verified completed output bytes.',
                             recovery={'action': 'reused', 'sourceRunId': plan['recovery']['sourceRunId'],
                                       'sourcePlanSha256': plan['recovery']['sourcePlanSha256']})
                if decision.get('referenceIndex'):
                    entry['referenceIndex'] = copy.deepcopy(decision['referenceIndex'])
                measured_step['backendMetrics'] = performance.unavailable_metrics('completed_step_reused_without_native_command')
                measured_step['phases']['scientific_preflight']['status'] = 'not_applicable'
                measured_step['phases']['backend_runner']['status'] = 'not_applicable'
                return entry, measured_step
            if node["tool"].get("builtin") or node["tool"]["id"] == "builtin/report":
                measured_step["phases"]["scientific_preflight"]["status"] = "not_applicable"
                measured_step["backendMetrics"] = performance.unavailable_metrics("builtin_operation_without_native_command")
                with performance.measure(measured_step["phases"], "backend_runner"):
                    result = self._report(node, values, step_folder, outputs, sources, node_names)
            else:
                with performance.measure(measured_step["phases"], "scientific_preflight"):
                    input_types = {}
                    for refs in node["inputs"].values():
                        for ref in refs:
                            descriptor = sources.get(ref) or outputs.get(ref)
                            if descriptor:
                                for filename in descriptor.get("files", {}).values():
                                    input_types[str(_resolved_path(filename))] = descriptor["type"]
                    entry["preflight"] = self._preflight(node, values, cancel, input_types)
                if node['tool'].get('requiresReferenceIndex'):
                    contract=node['tool']['requiresReferenceIndex']
                    for ref in node['inputs'][contract['port']]:
                        reference_indexes.compatible(node['tool'],outputs.get(ref,{}).get('referenceIndex'))
                measured_step["backendMetrics"] = performance.unavailable_metrics()
                with performance.measure(measured_step["phases"], "backend_runner"):
                    request = {"app_root": str(self.app_root), "pack_folder": str(_resolved_path(self.app_root / node["tool"]["packFolder"])), "pack_sha256": node["tool"]["manifestSha256"], "workflow_id": node["tool"]["workflowId"], "output_folder": str(step_folder), "values": values, "cancel_file": str(folder / "cancel.request")}
                    if temporary_root:
                        temporary = temporary_root / display_id(identity)
                        _io_path(temporary).mkdir()
                        request['temporary_folder'] = str(temporary)
                    run_backend=lambda:self.backend.run(request, lambda item: event(dict(item, nodeId=identity)), cancel)
                    if node['tool'].get('referenceIndex'):
                        contract=node['tool']['referenceIndex']
                        port=next(p for p in node['tool']['ports'] if p['id']==contract['referencePort'])
                        reference_path=values[port['manifestInputs'][0]]
                        expected=plan['inputs'].get(reference_path,{}).get('sha256')
                        if expected is None:
                            producer=outputs[node['inputs'][port['id']][0]]
                            expected=next(producer['sha256'][key] for key,path in producer['files'].items() if path==reference_path)
                        while not self._index_build_lock.acquire(timeout=0.1):
                            if cancel.is_set():
                                raise InterruptedError('Cancelled while waiting for reference-index preparation.')
                        try:
                            if cancel.is_set():
                                raise InterruptedError('Cancelled before reference-index preparation.')
                            result,index_evidence=reference_indexes.ReferenceIndexStore(self.app_root).run(
                                self.app_root,node,values,step_folder,run_backend,cancel,plan.get('referenceIndexPolicy','reuse'),expected)
                        finally:
                            self._index_build_lock.release()
                        if index_evidence is not None:
                            entry['referenceIndex']=index_evidence
                    else:
                        result=run_backend()
                if entry.get('referenceIndex',{}).get('action')=='reused':
                    measured_step['backendMetrics']=performance.unavailable_metrics('reference_index_reused_without_native_command')
                else:
                    measured_step["backendMetrics"] = performance.native_metrics(result.get("performance"))
            entry.update(status="success" if result.get("success") else "cancelled" if result.get("cancelled") else "failed", message=result.get("message", ""), folder=result.get("folder", str(step_folder)))
            if entry["status"] == "success":
                with performance.measure(measured_step["phases"], "output_validation_and_hashing"):
                    actual_folder = _resolved_path(entry["folder"])
                    if not actual_folder.is_relative_to(_resolved_path(step_folder)):
                        raise ValueError("Runner returned a result outside this step's private folder.")
                    for output in node["tool"].get("outputs", []):
                        files, hashes = {}, {}
                        for key, relative in output.get("files", {}).items():
                            path = _safe_relative(actual_folder, relative)
                            if not _io_path(path).is_file():
                                raise ValueError("The runner did not produce declared output " + output["id"] + ": " + str(path))
                            if node["tool"].get("schemaAsset") and output["type"] in {"fasta-nucleotide", "fasta-protein", "msa-nucleotide", "msa-protein", "fasta-nucleotide-abundance", "id-list"}:
                                declared = next((f for f in output.get("fields", []) if f["id"] == key), {})
                                evidence = _sequence_evidence(path, output["type"], [output["type"]], output.get("state", {}), cancel, allow_empty=not declared.get("nonempty", True))
                                entry.setdefault("outputValidation", {})[key] = evidence
                            files[key] = str(path)
                            hashes[key] = digest_file(path, cancel)
                            if entry.get('referenceIndex'):
                                expected=entry['referenceIndex']['files'][relative]
                                if hashes[key]!=expected['sha256'] or _io_path(path).stat().st_size!=expected['bytes']:
                                    raise ValueError('The registered reference index changed before output publication.')
                        ref = identity + "::" + output["id"]
                        item = {"id": ref, "label": output.get("label", output["id"]), "type": output["type"], "state": output.get("state", {}), "files": files, "sha256": hashes, "producer": identity, "manifestOutputs": output.get("manifestOutputs", list(files))}
                        if entry.get('referenceIndex'):
                            item['referenceIndex']=copy.deepcopy(entry['referenceIndex'])
                        entry["outputs"][ref] = item
        except InterruptedError as exc:
            entry.update(status='cancelled', message=str(exc), outputs={})
        except Exception as exc:
            entry.update(status='failed', message=str(exc), outputs={})
        finally:
            entry['finished'] = utc()
            measured_step['status'] = entry['status']
            measured_step['elapsedSeconds'] = performance.elapsed(started, time.perf_counter)
        return entry, measured_step

    def execute(self, plan, event=None, cancel=None):
        execution_started = time.perf_counter()
        event = event or (lambda item: None)
        cancel = cancel or threading.Event()
        plan = copy.deepcopy(plan)
        claimed = plan.pop("sha256", None)
        actual = hashlib.sha256(canonical(plan).encode("utf-8")).hexdigest()
        if claimed != actual:
            raise ValueError("The frozen execution plan has changed.")
        plan["sha256"] = claimed
        folder = Path(plan["folder"])
        stored = json.loads(_io_path(folder / "plan.json").read_text(encoding="utf-8"))
        stored_claim = stored.pop("sha256", None)
        stored_actual = hashlib.sha256(canonical(stored).encode("utf-8")).hexdigest()
        if stored_claim != claimed or stored_actual != claimed:
            raise ValueError("The stored execution plan does not match this run.")
        if _io_path(folder / "run.json").exists():
            raise ValueError("This plan has already started. Prepare a new run to execute again.")
        workflow = json.loads(_io_path(folder / "workflow.cwl").read_text(encoding="utf-8"))
        if (definition_sha256(workflow) != plan["workflowExport"]["definitionSha256"]
                or workflow["$graph"][0].get("nw:planSha256") != claimed):
            raise ValueError("The CWL workflow export does not match the frozen execution plan.")
        measurements = performance.make_record(plan)
        measurements["status"] = "running"
        measurements["execution"]["status"] = "running"
        measured_steps = {step["id"]: step for step in measurements["steps"]}
        outputs, statuses = {}, {}
        record = {"schema": 1, "id": plan["id"], "planSha256": claimed, "name": plan["graph"].get("name", "Workspace"), "folder": str(folder), "started": utc(), "status": "running", "nodes": [], "outputs": {}, "scheduler": plan["scheduler"]}
        record["references"] = copy.deepcopy(plan.get("references", {}))
        if 'batch' in plan:
            record['batch']=copy.deepcopy(plan['batch'])
        if 'project' in plan:
            record['project'] = copy.deepcopy(plan['project'])
        workflow = update_run_status(workflow, record)
        write_json(folder / "workflow.cwl", workflow)
        record["workflowExport"] = dict(plan["workflowExport"], sha256=digest_file(folder / "workflow.cwl"))
        write_json(folder / "run.json", record)
        measurements["execution"]["phases"]["startup"] = {"status": "completed", "elapsedSeconds": performance.elapsed(execution_started, time.perf_counter)}
        write_json(folder / "performance.json", measurements)
        event({"type": "run", "status": "running", "folder": str(folder)})
        policy = execution_resources.normalize(plan.get('resources'), plan['nodes'])
        record['resources'] = copy.deepcopy(policy)
        record['resourceScope'] = 'CPU admission reservations, not OS CPU limits; unknown requirements are exclusive. Memory and temporary expansion are unknown.'
        if 'recovery' in plan:
            record['recovery'] = {key: copy.deepcopy(value) for key, value in plan['recovery'].items() if key != 'nodes'}
        temporary_root = None
        if policy['temporaryFolder']:
            execution_resources.storage(policy['temporaryFolder'])
            temporary_root = Path(policy['temporaryFolder']) / ('native-workbench-' + plan['id'])
            _io_path(temporary_root).mkdir(mode=0o700)
            record['temporaryStorage'] = {'folder': str(temporary_root), 'cleanup': 'Preserved for inspection; only this run-owned subfolder was created.'}
        execution_resources.storage(folder)
        pending = list(plan['nodes'])
        active = {}
        used_cpus = 0
        entries = {}
        event_lock = threading.Lock()
        original_event = event
        def serialized_event(item):
            with event_lock:
                original_event(item)
        event = serialized_event
        def persist():
            record['nodes'] = [entries[node['id']] for node in plan['nodes'] if node['id'] in entries]
            record['outputs'] = outputs
            write_json(folder / 'run.json', record)
            write_json(folder / 'performance.json', measurements)
        def finish(entry, measurement):
            identity = entry['id']
            entries[identity] = entry
            measured_steps[identity].clear()
            measured_steps[identity].update(measurement)
            statuses[identity] = entry['status']
            if entry['status'] == 'success':
                outputs.update(entry['outputs'])
            persist()
            event({'type': 'step', 'nodeId': identity, 'status': entry['status'], 'message': entry.get('message', '')})
        with ThreadPoolExecutor(max_workers=policy['maxParallel'], thread_name_prefix='workbench-step') as executor:
            try:
                while pending or active:
                    for node in list(pending):
                        identity = node['id']
                        if cancel.is_set() or any(statuses.get(dep) in {'failed', 'blocked', 'cancelled'} for dep in node['dependencies']):
                            pending.remove(node)
                            status = 'cancelled' if cancel.is_set() else 'blocked'
                            entry = {'id': identity, 'name': node['label'], 'tool': node['tool']['id'], 'pin': pin_for(node['tool']),
                                     'inputs': node['inputs'], 'outputs': {}, 'status': status, 'finished': utc(),
                                     'message': 'Cancelled before this step started.' if status == 'cancelled' else 'An upstream step did not complete successfully.'}
                            measured = copy.deepcopy(measured_steps[identity]); measured['status'] = status
                            finish(entry, measured)
                            continue
                        if any(statuses.get(dep) != 'success' for dep in node['dependencies']):
                            continue
                        reserved = execution_resources.reservation(policy, identity)
                        if len(active) >= policy['maxParallel'] or used_cpus + reserved['cpus'] > policy['cpuBudget']:
                            continue
                        pending.remove(node)
                        measured_steps[identity]['status'] = 'running'
                        measured_steps[identity]['reservation'] = reserved
                        entries[identity] = {'id': identity, 'name': node['label'], 'tool': node['tool']['id'],
                                             'pin': pin_for(node['tool']), 'inputs': node['inputs'], 'outputs': {},
                                             'status': 'running', 'started': utc(), 'reservation': reserved}
                        persist()
                        event({'type': 'step', 'nodeId': identity, 'status': 'running'})
                        if cancel.is_set():
                            # Cancellation can arrive through the admission event before a worker begins.
                            pending.insert(0, node)
                            continue
                        future = executor.submit(self._execute_node, plan, copy.deepcopy(node), copy.deepcopy(outputs),
                                                 event, cancel, measured_steps[identity], temporary_root)
                        active[future] = (identity, reserved)
                        used_cpus += reserved['cpus']
                    if active:
                        completed, _ = wait(active, timeout=0.1, return_when=FIRST_COMPLETED)
                        for future in completed:
                            identity, reserved = active.pop(future)
                            used_cpus -= reserved['cpus']
                            entry, measured = future.result()
                            entry['reservation'] = reserved
                            finish(entry, measured)
                    elif pending and not cancel.is_set():
                        raise ValueError('No pending workflow step can be admitted under this resource policy.')
            except BaseException:
                # Release every admitted native process before propagating a
                # record-write or orchestration failure to the durable queue.
                cancel.set()
                raise
        with performance.measure(measurements["execution"]["phases"], "finalization"):
            record["finished"] = utc()
            record["status"] = "cancelled" if cancel.is_set() or any(v == "cancelled" for v in statuses.values()) else "success" if all(v == "success" for v in statuses.values()) else "failed"
            record["success"] = record["status"] == "success"
            record["methods"] = self.methods(plan["graph"], completed=True, statuses=statuses, references=plan.get("references", {}),
                                              index_actions={entry['id']:entry['referenceIndex']['action'] for entry in record['nodes'] if entry.get('referenceIndex')},
                                              recovered={entry['id'] for entry in record['nodes'] if entry.get('recovery', {}).get('action') == 'reused'})
            if 'batch' in plan:
                record['methods']+='\nBatch '+plan['batch']['batchId']+', sample '+plan['batch']['sampleId']+'. The frozen plan and CWL retain the selected sample-table metadata and file bindings.\n'
            if 'project' in plan:
                record['methods'] += '\nImported project '+plan['project']['id']+' (manifest SHA-256 '+plan['project']['manifestSha256']+'). Historical reference receipts and descriptive sample metadata are retained in the project section of the frozen plan, run record and CWL. Input bytes were verified; historical descriptions are not publisher authentication or a new local reference-library registration.\n'
            for entry in record['nodes']:
                index=entry.get('referenceIndex')
                if entry['status']=='success' and index and not entry.get('recovery'):
                    action='reused after verifying the complete stored inventory; the indexing command was not run' if index['action']=='reused' else 'built and registered with a complete verified inventory'
                    record['methods']+='\nReference index at step '+display_id(entry['id'])+' was '+action+'. Identity SHA-256: '+index['key']+'. Reference SHA-256: '+index['identity']['reference']['sha256']+'.\n'
            _io_path(folder / "methods-completed.txt").write_text(record["methods"], encoding="utf-8")
            write_json(folder / "workflow.cwl", update_run_status(workflow, record))
            record["workflowExport"]["sha256"] = digest_file(folder / "workflow.cwl")
        measurements["status"] = record["status"]
        measurements["execution"].update(status=record["status"], elapsedSeconds=performance.elapsed(execution_started, time.perf_counter))
        write_json(folder / "performance.json", measurements)
        # This final pointer is added after CWL outcome serialization: the CWL
        # file and performance sidecar cannot acquire circular reciprocal hashes.
        record["performance"] = {"file": "performance.json", "schema": 1, "sha256": digest_file(folder / "performance.json")}
        write_json(folder / "run.json", record)
        event({"type": "run", "status": record["status"], "folder": str(folder)})
        return record

    def _report(self, node, values, folder, outputs, sources, node_names):
        sections = []
        for port, refs in node["inputs"].items():
            for ref in refs:
                item = outputs.get(ref)
                if item is None:
                    # External report files still retain their named input slot.
                    item = {"label": sources[ref].get("label", ref), "files": sources[ref].get("files", {})}
                for key, filename in item["files"].items():
                    path = _ordinary(filename)
                    raw = _io_path(path).read_bytes() if _io_path(path).stat().st_size <= 4 * 1024 * 1024 else b"Report exceeds inline size limit; open the named original file."
                    try:
                        content = raw.decode("utf-8")
                    except UnicodeDecodeError:
                        content = "Binary output; open the named original file."
                    section = {"source": ref, "label": item["label"], "file": str(path), "content": content}
                    producer = item.get("producer")
                    if producer:
                        section["producer"] = producer
                        section["producerName"] = node_names[producer]
                    sections.append(section)
        title = html.escape(node["params"].get("title", "Pipeline report"))
        body = "<!doctype html><html lang='en'><meta charset='utf-8'><title>" + title + "</title><style>body{font:16px system-ui;max-width:1100px;margin:40px auto;padding:0 24px;color:#172638}section{border:1px solid #ccd3dc;border-radius:14px;padding:20px;margin:24px 0}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#f5f7fa;padding:16px}small{overflow-wrap:anywhere}</style><h1>" + title + "</h1><p>Each tool's results are shown separately. Counts from different callers or analyses have not been pooled.</p>"
        for section in sections:
            heading = section["source"] + " · " + section["label"]
            if "producer" in section:
                heading = display_id(section["producer"]) + " · " + section["producerName"] + " · " + section["label"]
            body += "<section><h2>" + html.escape(heading) + "</h2><small>" + html.escape(section["source"] + " · " + section["file"]) + "</small><pre>" + html.escape(section["content"]) + "</pre></section>"
        body += "</html>"
        for output in node["tool"].get("outputs", []):
            for relative in output.get("files", {}).values():
                target = _safe_relative(folder, relative)
                _io_path(target.parent).mkdir(parents=True, exist_ok=True)
                if target.suffix.lower() == ".json":
                    write_json(target, {"schema": 1, "aggregation": "separate-sections-no-pooled-statistics", "sections": sections})
                else:
                    _io_path(target).write_text(body, encoding="utf-8")
        return {"success": True, "cancelled": False, "folder": str(folder), "message": "Separate report sections written."}

    def diagram(self, plan):
        try:
            from .dag_routing import MAX_COSMETIC_CARDS, route, simplify
        except ImportError:
            from dag_routing import MAX_COSMETIC_CARDS, route, simplify
        graph = plan["graph"]
        nodes = {n["id"]: n for n in graph["nodes"]}
        sources = {s["id"]: s for s in graph["sources"]}
        order, deps = self._topology(graph)
        ranks = {identity: 0 for identity in sources}
        for identity in order:
            ranks[identity] = max([ranks[d] for d in deps[identity]] + [0]) + 1
        groups = {}
        for identity, rank in ranks.items():
            groups.setdefault(rank, []).append(identity)
        width = max(800, max([len(items) for items in groups.values()] + [1]) * 280 + 40)
        height = (max(groups.keys(), default=0) + 1) * 150 + 40
        positions = {}
        for rank, items in groups.items():
            for index, identity in enumerate(items):
                positions[identity] = ((width - len(items) * 280) // 2 + index * 280 + 20, rank * 150 + 24)
        obstacles = [(x - 10, y - 10, x + 250, y + 86) for x, y in positions.values()]
        edges, incoming, outgoing = [], {}, {}
        for node in graph["nodes"]:
            for port, refs in node.get("inputs", {}).items():
                for ref in refs:
                    source = ref.split("::", 1)[0]
                    if source not in positions:
                        continue
                    edge = (source, ref, node["id"], port)
                    edges.append(edge)
                    if ref not in outgoing.setdefault(source, []):
                        outgoing[source].append(ref)
                    if port not in incoming.setdefault(node["id"], []):
                        incoming[node["id"]].append(port)
        svg = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img" aria-label="Pipeline dependency graph"><rect width="100%" height="100%" fill="#f5f7fb"/><defs><marker id="arrow" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto" markerUnits="userSpaceOnUse"><path d="M0,0 L8,4 L0,8 Z" fill="#687f98"/></marker></defs>']
        routed = []
        for source, ref, target, port in edges:
            x1, y1 = positions[source]
            x2, y2 = positions[target]
            # Named outputs share an exit and named inputs share an entry, while
            # separate ports get separate attachment points. All intermediate
            # segments avoid every padded card, including skipped ranks.
            sx = x1 + 240 * (outgoing[source].index(ref) + 1) // (len(outgoing[source]) + 1)
            tx = x2 + 240 * (incoming[target].index(port) + 1) // (len(incoming[target]) + 1)
            start, end = (sx, y1 + 76), (tx, y2)
            occupied = ([segment for other_ref, points in routed if other_ref != ref for segment in zip(points, points[1:])]
                        if len(positions) <= MAX_COSMETIC_CARDS else [])
            middle = route((sx, y1 + 90), (tx, y2 - 14), obstacles, occupied=occupied)
            if not middle:
                raise ValueError("Unable to route pipeline dependency: " + ref + " → " + target)
            points = simplify([start, *middle, end])
            routed.append((ref, points))
            path = "M" + " L".join(f"{x},{y}" for x, y in points)
            title = html.escape(ref + " → " + target + ":" + port)
            svg.append(f'<path class="dependency-halo" d="{path}" fill="none" stroke="#f5f7fb" stroke-width="6" stroke-linejoin="round"/>')
            svg.append(f'<path class="dependency" data-source="{html.escape(source, quote=True)}" data-target="{html.escape(target, quote=True)}" d="{path}" fill="none" stroke="#687f98" stroke-width="2" stroke-linejoin="round" marker-end="url(#arrow)"><title>{title}</title></path>')
        for identity, (x, y) in positions.items():
            source = identity in sources
            label = sources[identity].get("label", "Input") if source else node_name(nodes[identity], self._tool(nodes[identity]))
            svg.append(f'<g data-node="{html.escape(identity, quote=True)}"><rect x="{x}" y="{y}" width="240" height="76" rx="14" fill="{"#e6edf5" if source else "#ffffff"}" stroke="#a7b4c5"/><text x="{x+14}" y="{y+25}" font-family="sans-serif" font-size="12" fill="#4b5f78">{html.escape(display_id(identity))}</text>')
            words, lines, line = label.split(), [], ""
            for word in words:
                if len(line + " " + word) > 28 and line:
                    lines.append(line)
                    line = word
                else:
                    line = (line + " " + word).strip()
            if line:
                lines.append(line)
            for row, line in enumerate(lines[:2]):
                svg.append(f'<text x="{x+14}" y="{y+45+row*17}" font-family="sans-serif" font-size="13" fill="#172b45">{html.escape(line)}</text>')
            svg.append('<title>' + html.escape(label) + '</title></g>')
        svg.append('</svg>')
        return "".join(svg)


def _binding_parameter(field):
    return field.get("binding", False) or field.get("preset") is False or re.search(r"sample|read.?group|library|(?:^|_)rg(?:_|$)", field["id"], re.I) is not None


def _parse_header(text):
    result = {"sort": "unknown", "dictionary": [], "readgroups": [], "programs": []}
    for line in text.splitlines():
        parts = line.split("\t")
        values = dict(part.split(":", 1) for part in parts[1:] if ":" in part)
        if parts[0] == "@HD":
            result["sort"] = values.get("SO", "unknown")
        elif parts[0] == "@SQ":
            result["dictionary"].append((values.get("SN"), values.get("LN"), values.get("M5")))
        elif parts[0] == "@RG":
            result["readgroups"].append(values)
        elif parts[0] == "@PG":
            result["programs"].append(line)
    return result


def _fasta_dictionary(filename, cancel=None):
    """Names, lengths and SAM-style uppercase sequence MD5, streamed locally."""
    result = []
    name, length, checksum = None, 0, hashlib.md5()
    with open(_io_path(filename), "rb") as stream:
        for line in stream:
            if cancel is not None and cancel.is_set():
                raise InterruptedError("Cancelled while checking the reference FASTA.")
            if line.startswith(b">"):
                if name is not None:
                    result.append((name, length, checksum.hexdigest()))
                name = line[1:].split(None, 1)[0].decode("utf-8", "strict")
                length, checksum = 0, hashlib.md5()
            else:
                sequence = b"".join(line.split()).upper()
                if sequence and name is None:
                    raise ValueError("Reference sequence appears before a FASTA header.")
                length += len(sequence)
                checksum.update(sequence)
    if name is not None:
        result.append((name, length, checksum.hexdigest()))
    if not result or len({row[0] for row in result}) != len(result):
        raise ValueError("Reference FASTA is empty or has repeated contig names.")
    return result


def _vcf_header_attributes(text):
    """Split VCF angle-bracket metadata without splitting quoted descriptions."""
    fields, start, quoted, escaped = [], 0, False, False
    for at, character in enumerate(text):
        if escaped:
            escaped=False
        elif character=='\\' and quoted:
            escaped=True
        elif character=='"':
            quoted=not quoted
        elif character==',' and not quoted:
            fields.append(text[start:at]);start=at+1
    if quoted or escaped:
        raise ValueError('Malformed quoted VCF INFO declaration.')
    fields.append(text[start:])
    result={}
    for field in fields:
        if '=' not in field:
            raise ValueError('Malformed VCF INFO declaration.')
        key,value=field.split('=',1)
        if not key or not value or key in result:
            raise ValueError('Missing or duplicate VCF INFO declaration attribute.')
        result[key]=value
    return result


def _vcf_header_evidence(path, rules, cancel):
    """Check declared INFO header types, without claiming per-record validity."""
    declarations={};total=0
    with open(_io_path(path),'rb') as probe:
        compressed=probe.read(2)==b'\x1f\x8b'
    with (gzip.open(_io_path(path),'rb') if compressed else open(_io_path(path),'rb')) as stream:
        while True:
            if cancel.is_set():
                raise InterruptedError('Cancelled while checking the VCF resource header.')
            raw=stream.readline(1024*1024+1)
            total+=len(raw)
            if len(raw)>1024*1024 or total>8*1024*1024:
                raise ValueError('VCF resource header exceeds the validation size limit.')
            if not raw:
                raise ValueError('VCF resource is missing its column header.')
            line=raw.decode('utf-8','strict').rstrip('\r\n')
            if line.startswith('##INFO=<'):
                if not line.endswith('>'):
                    raise ValueError('Malformed VCF INFO declaration.')
                fields=_vcf_header_attributes(line[8:-1])
                identity=fields.get('ID')
                if not identity or identity in declarations:
                    raise ValueError('Missing or duplicate VCF INFO field ID.')
                declarations[identity]=fields
            elif line.startswith('#CHROM\t'):
                if line.split('\t')[:8]!=['#CHROM','POS','ID','REF','ALT','QUAL','FILTER','INFO']:
                    raise ValueError('Malformed VCF resource column header.')
                break
            elif not line.startswith('##'):
                raise ValueError('VCF resource is missing its column header.')
    checked=[]
    for wanted in rules['requiredInfoFields']:
        actual=declarations.get(wanted['id'],{})
        if actual.get('Number')!=wanted['number'] or actual.get('Type')!=wanted['type']:
            raise ValueError('VCF resource requires INFO/'+wanted['id']+' declared with Number='+wanted['number']+' and Type='+wanted['type']+': '+str(path))
        checked.append(dict(wanted))
    return {'check':'VCF-INFO-header','requiredInfoFields':checked,
            'note':'Header declarations do not verify every record value, reference build or population suitability.'}


def _bed_evidence(path, rules, reference_dictionary, cancel):
    """Validate zero-based half-open target intervals against the chosen FASTA."""
    reference = {name:length for name,length,_ in (reference_dictionary or [])}
    if rules.get('referenceBounds') and not reference:
        raise ValueError('BED interval validation requires a selected reference FASTA.')
    minimum = rules.get('minColumns',3)
    count, intervals = 0, {}
    with open(_io_path(path),'r',encoding='utf-8-sig') as stream:
        for number,line in enumerate(stream,1):
            if cancel.is_set():
                raise InterruptedError('Cancelled while validating BED intervals.')
            if len(line)>1024*1024:
                raise ValueError('A BED line is unexpectedly long: '+str(path))
            stripped = line.strip()
            if not stripped or stripped.startswith(('#','track ','browser ')):
                continue
            fields = line.rstrip('\r\n').split('\t')
            if len(fields)<minimum or not fields[0] or any(c.isspace() for c in fields[0]):
                raise ValueError('BED line '+str(number)+' requires at least '+str(minimum)+' tab-separated columns and a reference name.')
            if not re.fullmatch(r'[0-9]+',fields[1]) or not re.fullmatch(r'[0-9]+',fields[2]):
                raise ValueError('BED start/end coordinates must be nonnegative integers (zero-based, half-open): line '+str(number))
            start,end = int(fields[1]),int(fields[2])
            if end<=start or end>9223372036854775807:
                raise ValueError('BED intervals require end > start within the supported coordinate range: line '+str(number))
            if minimum>=4 and not fields[3].strip():
                raise ValueError('BED target intervals require a nonempty region name in column 4: line '+str(number))
            if rules.get('referenceBounds') and (fields[0] not in reference or end>reference[fields[0]]):
                raise ValueError('BED interval exceeds or names a contig absent from the selected reference: line '+str(number))
            if rules.get('nonOverlapping'):
                intervals.setdefault(fields[0],[]).append((start,end))
            count += 1
            if count>1000000:
                raise ValueError('This target BED validator supports at most 1,000,000 intervals.')
    if not count:
        raise ValueError('The BED file contains no target intervals: '+str(path))
    for name, spans in intervals.items():
        previous_end = -1
        for start,end in sorted(spans):
            if start<previous_end:
                raise ValueError('Target BED intervals overlap on '+name+'; merge or remove overlaps before calling to avoid repeated calls.')
            previous_end = end
    return {'type':'bed','records':count,'coordinateSystem':'zero-based-half-open',
            'referenceBoundsChecked':bool(rules.get('referenceBounds')),'nonOverlapping':bool(rules.get('nonOverlapping'))}


def _sequence_evidence(path, declared_type, accepted, state, cancel, allow_empty=False, rules=None):
    """Stream complete FASTA alphabet/alignment/count evidence without guessing
    that ordinary sequences are genomic references or paired observations.
    """
    rules = rules or {}
    sequence_types = {"fasta-nucleotide", "fasta-protein", "msa-nucleotide", "msa-protein", "fasta-nucleotide-abundance"}
    data, compressed = _head(path)
    compression = _compression_kind(path, compressed)
    if state.get("compression") == "none" and compressed:
        raise ValueError("This operation requires uncompressed sequences: " + str(path))
    if state.get("compression") in ("gzip", "bgzf") and not compressed:
        raise ValueError("This operation requires compressed sequences: " + str(path))
    if state.get("compression") == "bgzf" and compression != "bgzf":
        raise ValueError("This operation requires BGZF-compressed sequences: " + str(path))
    if not data:
        if allow_empty:
            return {"records": 0, "compression": compression, "type": declared_type}
        raise ValueError("No sequence records are available for this input: " + str(path))
    if declared_type == "id-list":
        count = 0
        with (gzip.open(_io_path(path), "rt", encoding="utf-8") if compressed else open(_io_path(path), "r", encoding="utf-8")) as stream:
            for line in stream:
                if cancel.is_set():
                    raise InterruptedError("Cancelled while checking identifier list.")
                value = line.rstrip("\r\n")
                if not value:
                    continue
                if len(value) > 4096 or any(c.isspace() or ord(c) < 32 for c in value):
                    raise ValueError("Sequence identifier lists require one identifier without whitespace per line: " + str(path))
                count += 1
        if not count and not allow_empty:
            raise ValueError("The sequence identifier list contains no identifiers: " + str(path))
        return {"records": count, "type": "id-list", "compression": compression}
    if data.startswith(b"@") and "reads" in accepted:
        # Full FASTQ record structure/qualities are checked by the actual read
        # tools; do not incorrectly reject multiline FASTQ here.
        return {"type": "reads", "compression": compression, "validation": "FASTQ signature; records validated by the tool"}
    if not data.startswith(b">"):
        raise ValueError("Expected FASTA sequence records: " + str(path))
    allowed_types = set(accepted)
    # Prefer the explicitly selected semantic type. A statistics port accepting
    # both alphabets permits protein letters; DNA-only consumers do not.
    aligned = declared_type.startswith("msa-")
    protein_allowed = declared_type in {"fasta-protein", "msa-protein"} if declared_type in sequence_types else bool(allowed_types & {"fasta-protein", "msa-protein"})
    nucleotide_allowed = declared_type in {"fasta-nucleotide", "msa-nucleotide", "fasta-nucleotide-abundance"} if declared_type in sequence_types else bool(allowed_types & {"fasta-nucleotide", "msa-nucleotide", "fasta-nucleotide-abundance", "reference"})
    require_abundance = declared_type == "fasta-nucleotide-abundance" or state.get("abundance") is True or state.get("sort") == "abundance"
    dna = set(b"ACGTRYSWKMBDHVNU")
    amino = set(b"ABCDEFGHIKLMNPQRSTVWXYZUOJ*")
    allowed_letters = amino if protein_allowed else dna
    if aligned:
        allowed_letters = allowed_letters | set(b"-.")
    count = 0
    length = 0
    width = None
    total = 0
    abundance_total = 0
    previous_abundance = None
    saw_protein_only = False
    identifiers = set()
    def finish():
        nonlocal width, total
        if length == 0:
            raise ValueError("A FASTA record contains no sequence: " + str(path))
        if length < rules.get("minLength", 0) or length > rules.get("maxLength", 1000000000):
            raise ValueError("FASTA sequence length falls outside this pack's declared input limits: " + str(path))
        if aligned and width is not None and length != width:
            raise ValueError("Aligned FASTA records have different column counts: " + str(path))
        if width is None:
            width = length
        total += length
    with (gzip.open(_io_path(path), "rb") if compressed else open(_io_path(path), "rb")) as stream:
        for line in stream:
            if cancel.is_set():
                raise InterruptedError("Cancelled while validating FASTA sequences.")
            if line.startswith(b">"):
                if count:
                    finish()
                header = line[1:].strip()
                if not header or len(header) > 1024 * 1024:
                    raise ValueError("FASTA records require a nonempty, bounded identifier: " + str(path))
                identifier = header.split(None, 1)[0]
                if rules.get("uniqueIds"):
                    if identifier in identifiers:
                        raise ValueError("This operation requires unique FASTA sequence identifiers: " + str(path))
                    identifiers.add(identifier)
                if rules.get("rejectAbundance") and b";size=" in identifier:
                    raise ValueError("This operation treats every record as one observation and cannot accept existing abundance annotations. Choose the abundance-aware workflow: " + str(path))
                if require_abundance:
                    if identifier.count(b";size=") != 1:
                        raise ValueError("Every abundance FASTA identifier needs exactly one ;size=N; count: " + str(path))
                    match = re.search(rb"(?:^|;)size=([1-9][0-9]*)(?:;|$)", identifier)
                    if not match or int(match.group(1)) > 9223372036854775807:
                        raise ValueError("Every abundance FASTA identifier needs a positive ;size=N; count: " + str(path))
                    abundance = int(match.group(1))
                    if state.get("sort") == "abundance" and previous_abundance is not None and abundance > previous_abundance:
                        raise ValueError("Abundance FASTA records must be sorted from highest to lowest count: " + str(path))
                    previous_abundance = abundance
                    abundance_total += abundance
                    if abundance_total > 9223372036854775807:
                        raise ValueError("Total FASTA abundance exceeds the supported count range: " + str(path))
                count += 1
                if count > rules.get("maxRecords", 1000000000):
                    raise ValueError("FASTA record count exceeds this pack's declared limit: " + str(path))
                length = 0
            else:
                sequence = b"".join(line.split()).upper()
                if not sequence:
                    continue
                if not count:
                    raise ValueError("FASTA sequence appears before its identifier: " + str(path))
                if not set(sequence).issubset(allowed_letters):
                    expected = "protein" if protein_allowed else "nucleotide"
                    raise ValueError("Unexpected characters in " + expected + (" alignment" if aligned else " sequences (gaps require an aligned FASTA type)") + ": " + str(path))
                if set(sequence) - dna - set(b"-."):
                    saw_protein_only = True
                length += len(sequence)
    if count:
        finish()
    if not count and not allow_empty:
        raise ValueError("No FASTA sequence records are available: " + str(path))
    if count < rules.get("minRecords", 0):
        raise ValueError("This operation requires at least " + str(rules["minRecords"]) + " FASTA records: " + str(path))
    kind = declared_type
    if kind not in sequence_types:
        kind = "fasta-protein" if saw_protein_only or not nucleotide_allowed else "fasta-nucleotide"
    evidence = {"records": count, "symbols": total, "type": kind, "compression": compression, "validation": "complete FASTA records and permitted alphabet"}
    if aligned:
        evidence["columns"] = width or 0
    if require_abundance:
        evidence["abundanceTotal"] = abundance_total
    return evidence
