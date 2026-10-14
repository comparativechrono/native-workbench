"""Stateful, transport-independent model for the genuine native desktop UI.

The native window renders snapshots and sends named actions. No HTML, browser,
network server, window toolkit, or tool subprocess is required by this module.
"""
from __future__ import annotations
import copy
import fnmatch
from pathlib import Path
import re

from catalog import TYPES, validate_parameter, resolve_tool
from engine import Engine, display_id, pin_for, clean_text, _binding_parameter


class DesktopModel:
    def __init__(self, app_root, catalog, *, auto_sources=True):
        self.root = Path(app_root).resolve()
        self.catalog = catalog
        self.engine = Engine(self.root, catalog)
        # Standalone forms allocate their file slots. Workflow sessions leave
        # ports unconnected until the user chooses an input or an upstream tool.
        self.auto_sources = auto_sources
        self.graph = {"schema": 1, "name": "Untitled analysis", "nodes": [], "sources": [], "nextNode": 1, "nextSource": 1}
        self.selected = None
        self.pending_source = None
        self.notice = ""
        self._undo = []
        self._next_node = 1
        self._next_source = 1

    def update_catalog(self, catalog):
        self.catalog = catalog
        self.engine = Engine(self.root, catalog)
        # Existing pins intentionally remain unchanged; importing a new version
        # must never silently change what a saved or configured analysis runs.
        return self.snapshot()

    def _tool(self, identity, pin=None, optional=False):
        if isinstance(identity, dict):
            pin = identity.get("pin")
            identity = identity.get("tool")
        try:
            return resolve_tool(self.catalog, identity, pin)
        except ValueError:
            if optional:
                return {}
            raise

    def _node(self, identity=None):
        identity = identity or self.selected
        for node in self.graph["nodes"]:
            if node["id"] == identity:
                return node
        raise ValueError("Select an existing step.")

    def _source(self, identity):
        for source in self.graph["sources"]:
            if source["id"] == identity:
                return source
        raise ValueError("This external input slot no longer exists.")

    def _port(self, node, identity):
        for port in self._tool(node).get("ports", []):
            if port["id"] == identity:
                return port
        raise ValueError("This input port is not part of the selected tool.")

    def _name(self, node):
        return node.get("label") or self._tool(node, optional=True).get("name", "Unavailable tool: " + node["tool"])

    def _fields(self, source):
        # An explicitly created input owns its schema. Sharing it between tools
        # must not change its field names when a consumer is added or removed.
        if source.get("fields"):
            return self._file_schema(source["fields"])
        for node in self.graph["nodes"]:
            tool = self._tool(node, optional=True)
            for port in tool.get("ports", []):
                if source["id"] in node.get("inputs", {}).get(port["id"], []):
                    return copy.deepcopy(port.get("fields", []))
        # Empty, detached slots can later be reconnected. Only structural file
        # metadata is retained; values always live in source.files.
        return next((copy.deepcopy(item["fields"]) for item in self.input_types()
                     if item["id"] == source.get("type")), [])

    @staticmethod
    def _file_schema(fields):
        # Paths/defaults belong to bindings, never reusable input metadata.
        return [{key: copy.deepcopy(field[key]) for key in
                 ("id", "label", "type", "role", "filter", "required", "help", "differentFrom") if key in field}
                for field in fields if isinstance(field, dict) and isinstance(field.get("id"), str)]

    def input_types(self):
        """One explicit input kind per installed semantic contract.

        Port metadata remains authoritative. Paired reads stay atomic with
        named read-1/read-2 roles; the engine maps those roles to each receiver.
        """
        available = {}
        for tool in self.catalog["tools"].values():
            for port in tool.get("ports", []):
                # This declared port requires producer provenance, so an
                # arbitrary external file can never satisfy its contract.
                if tool.get('requiresReferenceIndex', {}).get('port') == port['id']:
                    continue
                fields = self._file_schema(port.get("fields", []))
                if not fields or any(field.get("type") not in ("file", "files", "directory") for field in fields):
                    continue
                for kind in dict.fromkeys([port["type"], *port.get("accepts", [])]):
                    if kind == "*":
                        continue
                    schema = copy.deepcopy(fields)
                    if kind == "pair":
                        if len(schema) != 2 or any(field.get("type") != "file" for field in schema):
                            continue
                        # Paired semantic ports declare read 1/read 2 in their
                        # manifest input order, also used by engine mapping.
                        schema = [dict(field, id=identity, role=role)
                                  for field, role, identity in zip(schema, ("read1", "read2"), ("reads1", "reads2"))]
                        schema[0]["differentFrom"] = "reads2"
                        schema[1]["differentFrom"] = "reads1"
                    elif len(schema) != 1:
                        # Unknown composite contracts need an explicit pack
                        # schema; never invent a positional file mapping.
                        continue
                    if kind not in available:
                        available[kind] = {"id": kind, "type": kind, "label": TYPES.get(kind, port.get("label", kind)),
                                           "fields": schema}
        priority = {"reference": 0, "pair": 1, "reads": 2}
        return sorted(available.values(), key=lambda item: (priority.get(item["id"], 3), item["label"].casefold()))

    @staticmethod
    def _reference_matches(source, field, resource):
        """Conservative convenience binding, not proof of biological suitability.

        Pack semantic types and explicit filename filters are authoritative.
        Current nucleotide ports do not distinguish genomes from transcriptomes;
        only an explicitly genome-labelled nucleotide field receives a genome.
        A user can still browse manually for other scientifically reviewed uses.
        """
        if field.get("type") not in ("file", "files"):
            return False
        kind, semantic = resource.get("kind"), source.get("type")
        expected = {"genome": {"reference", "fasta-nucleotide", "file"},
                    "cdna": {"fasta-nucleotide", "file"},
                    "ncrna": {"fasta-nucleotide", "file"},
                    "protein": {"fasta-protein", "file"},
                    "annotation": {"text", "file"}}
        if semantic not in expected.get(kind, set()):
            return False
        words = set(re.findall(r"[a-z]+", " ".join(str(value) for value in
                    (field.get("id", ""), field.get("label", ""))).lower()))
        if words & {"cds", "aligned", "alignment"}:
            return False
        if kind == "genome" and semantic != "reference" and not words & {"genome", "genomic"}:
            return False
        if kind in ("cdna", "ncrna") and words & {"genome", "genomic"}:
            return False
        patterns = [pattern.strip().lower() for group in str(field.get("filter", "")).split("|")[1::2]
                    for pattern in group.split(";") if pattern.strip() not in ("*", "*.*", "")]
        name = str(resource.get("filename") or Path(resource.get("path", "")).name).lower()
        if patterns:
            return any(fnmatch.fnmatchcase(name, pattern) for pattern in patterns)
        # Unqualified generic file/text ports are not a reference contract.
        return semantic not in ("file", "text")

    def reference_targets(self, resource):
        connected = {ref for node in self.graph["nodes"] for refs in node.get("inputs", {}).values()
                     for ref in refs if "::" not in ref}
        targets = []
        for source in self.graph["sources"]:
            if self.auto_sources and source["id"] not in connected:
                continue
            for field in self._fields(source):
                if self._reference_matches(source, field, resource):
                    targets.append({"source_id": source["id"], "field_id": field["id"],
                                    "label": display_id(source["id"]) + " · " + source.get("label", "Input")
                                             + " → " + field.get("label", field["id"]),
                                    "type": source["type"], "current_path": source.get("files", {}).get(field["id"], "")})
        return targets

    def use_reference(self, resource, source_id, field_id):
        targets = self.reference_targets(resource)
        if not any(target["source_id"] == source_id and target["field_id"] == field_id for target in targets):
            raise ValueError("The selected reference no longer matches that input. Add a compatible tool and select its input again.")
        return self.dispatch("bind_files", {"sourceId": source_id, "files": {field_id: resource["path"]}})

    def _sync_counters(self):
        self.engine._counters(self.graph)
        self._next_node = max(self._next_node, self.graph["nextNode"])
        self._next_source = max(self._next_source, self.graph["nextSource"])
        self.graph["nextNode"] = self._next_node
        self.graph["nextSource"] = self._next_source

    def _new_source(self, port, label=None):
        self._sync_counters()
        identity = "input-" + str(self._next_source)
        self._next_source += 1
        source = {"id": identity, "type": port["type"], "label": label or port.get("label", port["id"]),
                  "files": {}, "fields": copy.deepcopy(port.get("fields", []))}
        self.graph["sources"].append(source)
        self._sync_counters()
        return source

    def _default_source(self, port):
        if port.get("type") == "reference":
            references = [s for s in self.graph["sources"] if s.get("type") == "reference"]
            if len(references) == 1:
                return references[0]
        return self._new_source(port)

    def _ref(self, ref):
        if not isinstance(ref, str):
            raise ValueError("Choose a named input or output.")
        if "::" not in ref:
            source = self._source(ref)
            return {"ref": ref, "id": ref, "sourceId": ref, "displayId": display_id(ref), "type": source["type"],
                    "label": display_id(ref) + " · " + source.get("label", "Input"), "name": source.get("label", "Input"), "external": True, "state": {}}
        identity, output_id = ref.split("::", 1)
        node = self._node(identity)
        for output in self._tool(node).get("outputs", []):
            if output["id"] == output_id:
                return {"ref": ref, "id": ref, "nodeId": identity, "outputId": output_id, "displayId": display_id(identity), "type": output["type"],
                        "label": display_id(identity) + " · " + self._name(node) + " → " + output.get("label", output_id),
                        "name": output.get("label", output_id), "external": False, "state": copy.deepcopy(output.get("state", {}))}
        raise ValueError("This named output is no longer available.")

    def _descendants(self, identity):
        descendants, pending = set(), [identity]
        while pending:
            current = pending.pop()
            for node in self.graph["nodes"]:
                if node["id"] not in descendants and any(isinstance(ref, str) and ref.startswith(current + "::") for refs in node.get("inputs", {}).values() for ref in refs):
                    descendants.add(node["id"])
                    pending.append(node["id"])
        return descendants

    def _accepts(self, port, descriptor):
        if descriptor["type"] not in port.get("accepts", [port["type"]]):
            return False
        state = descriptor.get("state", {})
        return not any(key in state and state[key] != value for key, value in port.get("requiredState", {}).items())

    def _choices(self, node, port):
        excluded = self._descendants(node["id"]) | {node["id"]}
        choices = []
        for source in self.graph["sources"]:
            descriptor = self._ref(source["id"])
            if self._accepts(port, descriptor):
                choices.append(descriptor)
        for candidate in self.graph["nodes"]:
            if candidate["id"] in excluded:
                continue
            for output in self._tool(candidate, optional=True).get("outputs", []):
                descriptor = self._ref(candidate["id"] + "::" + output["id"])
                if self._accepts(port, descriptor):
                    choices.append(descriptor)
        return choices

    def connection_targets(self, ref):
        """Bounded preview for one dragged source; connect remains authoritative.

        Publishing every source choice on every node made snapshots quadratic.
        Walk the producer's ancestors once instead: connecting it to itself or
        an ancestor would create a cycle, exactly as excluded by _choices().
        """
        descriptor = self._ref(ref)
        nodes = {node["id"]: node for node in self.graph["nodes"]}
        excluded, pending = set(), [descriptor["nodeId"]] if descriptor.get("nodeId") else []
        while pending:
            identity = pending.pop()
            if identity in excluded:
                continue
            excluded.add(identity)
            node = nodes.get(identity, {})
            pending.extend(source.split("::", 1)[0] for refs in node.get("inputs", {}).values()
                           for source in refs if "::" in source)
        targets = []
        for node in self.graph["nodes"]:
            if node["id"] in excluded:
                continue
            for port in self._tool(node, optional=True).get("ports", []):
                refs = node.get("inputs", {}).get(port["id"], [])
                maximum = int(port.get("max", 1))
                capacity = maximum == 1 or len(refs) < maximum or ref in refs
                if capacity and self._accepts(port, descriptor):
                    targets.append({"nodeId": node["id"], "portId": port["id"]})
        return targets

    def _set_inputs(self, node, port, refs):
        if not isinstance(refs, list) or not all(isinstance(ref, str) for ref in refs):
            raise ValueError("Connections must be a list of named sources.")
        if len(refs) != len(set(refs)):
            raise ValueError("The same source cannot appear twice in one input.")
        if len(refs) > int(port.get("max", 1)):
            raise ValueError("This input accepts at most " + str(port.get("max", 1)) + " source(s).")
        allowed = {item["ref"] for item in self._choices(node, port)}
        if any(ref not in allowed for ref in refs):
            raise ValueError("Choose a compatible source that does not create a cycle.")
        node.setdefault("inputs", {})[port["id"]] = list(refs)
        if not node.get("label") and self._tool(node).get("workflowId") in ("statistics", "quality-profile") and len(refs) == 1:
            descriptor = self._ref(refs[0])
            producer = self._name(self._node(descriptor["nodeId"])) if descriptor.get("nodeId") else descriptor["name"]
            node["label"] = (producer + " · " + self._tool(node)["name"])[:200]

    def _add(self, tool_id, from_ref=None, port_id=None, pin=None):
        tool = self._tool(tool_id, pin)
        if from_ref is not None:
            descriptor = self._ref(from_ref)
            compatible = [p for p in tool.get("ports", []) if self._accepts(p, descriptor) and (port_id is None or p["id"] == port_id)]
            if not compatible:
                raise ValueError("This tool has no compatible input for the selected output.")
            chosen_port = compatible[0]["id"]
        else:
            chosen_port = None
        self._sync_counters()
        identity = "step-" + str(self._next_node)
        self._next_node += 1
        node = {"id": identity, "tool": tool_id, "params": copy.deepcopy(tool.get("defaults", {})), "inputs": {}, "pin": pin_for(tool)}
        if from_ref and tool.get("workflowId") in ("statistics", "quality-profile"):
            provenance = self._ref(from_ref)
            if provenance.get("nodeId"):
                producer = self._node(provenance["nodeId"])
                node["label"] = self._name(producer) + " · " + tool["name"]
            else:
                node["label"] = provenance["name"] + " · " + tool["name"]
            node["label"] = node["label"][:200]
        self.graph["nodes"].append(node)
        for port in tool.get("ports", []):
            refs = [from_ref] if port["id"] == chosen_port else []
            while self.auto_sources and len(refs) < int(port.get("min", 1)):
                refs.append(self._default_source(port)["id"])
            node["inputs"][port["id"]] = refs
        self.selected, self.pending_source = identity, None
        self._sync_counters()
        return node

    def _capture(self):
        return {"graph": copy.deepcopy(self.graph), "selected": self.selected, "pendingSource": self.pending_source}

    def _restore(self, previous):
        self.graph = copy.deepcopy(previous["graph"])
        self.selected = previous["selected"]
        self.pending_source = previous["pendingSource"]
        self._sync_counters()

    def dispatch(self, action, payload=None):
        payload = {} if payload is None else payload
        if not isinstance(payload, dict):
            raise ValueError("Action payload must be an object.")
        if action in ("snapshot", "select", "use_output") and not (action == "use_output" and payload.get("toolId")):
            if action == "select":
                identity = payload.get("nodeId", payload.get("sourceId"))
                if identity is not None and not isinstance(identity, str):
                    raise ValueError("Select a named workflow step or input.")
                self.selected = (self._source(identity) if identity and identity.startswith("input-") else self._node(identity))["id"]
                self.pending_source = None
            elif action == "use_output":
                self.pending_source = self._ref(payload.get("ref"))["ref"]
            return self.snapshot()
        if action == "undo":
            if self._undo:
                self._restore(self._undo.pop())
                self.notice = "Previous change restored. Existing step and input identifiers have been preserved."
            return self.snapshot()
        previous = self._capture()
        self.notice = ""
        try:
            self._mutate(action, payload)
            self.engine._structure(self.graph)
            self.engine._topology(self.graph)
            self._sync_counters()
        except Exception:
            self._restore(previous)
            raise
        self._undo.append(previous)
        self._undo = self._undo[-64:]
        return self.snapshot()

    def _mutate(self, action, payload):
        if action == "apply_fields":
            if set(payload) - {"nodeId", "sourceId", "params", "files", "name", "graphName"}:
                raise ValueError("Unknown form update field.")
            params, files = payload.get("params", {}), payload.get("files", {})
            if not isinstance(params, dict) or not isinstance(files, dict):
                raise ValueError("Form parameters and file bindings must be named objects.")
            if not params and not files and "name" not in payload:
                if "graphName" in payload:
                    self._mutate("rename_graph", {"name": payload["graphName"]})
                return
            if "sourceId" in payload:
                if "nodeId" in payload or params:
                    raise ValueError("An input form cannot change tool options.")
                source = self._source(payload["sourceId"])
                if set(files) - {source["id"]}:
                    raise ValueError("An input form can only edit its own files.")
                if source["id"] in files:
                    self._mutate("bind_files", {"sourceId": source["id"], "files": files[source["id"]]})
                if "name" in payload:
                    self._mutate("rename_source", {"sourceId": source["id"], "name": payload["name"]})
                if "graphName" in payload:
                    self._mutate("rename_graph", {"name": payload["graphName"]})
                return
            node = self._node(payload.get("nodeId"))
            for key, value in params.items():
                self._mutate("set_param", {"nodeId": node["id"], "paramId": key, "value": value})
            connected = {ref for refs in node.get("inputs", {}).values() for ref in refs if "::" not in ref}
            for source_id, source_files in files.items():
                if source_id not in connected:
                    raise ValueError("A form can only edit input slots connected to this step.")
                self._mutate("bind_files", {"sourceId": source_id, "files": source_files})
            if "name" in payload:
                self._mutate("rename_step", {"nodeId": node["id"], "name": payload["name"]})
            if "graphName" in payload:
                self._mutate("rename_graph", {"name": payload["graphName"]})
        elif action == "add_tool":
            self._add(payload.get("toolId"), payload.get("fromRef", self.pending_source), payload.get("portId"), payload.get("pin"))
        elif action == "add_input":
            if set(payload) - {"inputType", "label"}:
                raise ValueError("Unknown workflow input field.")
            item = next((item for item in self.input_types() if item["id"] == payload.get("inputType")), None)
            if item is None:
                raise ValueError("Choose an input type supported by an installed tool.")
            label = payload.get("label", item["label"])
            if not clean_text(label, 200) or not label.strip():
                raise ValueError("Give this input a short plain-text name.")
            source = self._new_source(item, label.strip())
            self.selected, self.pending_source = source["id"], None
        elif action == "remove_source":
            source = self._source(payload.get("sourceId"))
            affected = []
            for node in self.graph["nodes"]:
                for port, refs in node.get("inputs", {}).items():
                    if source["id"] in refs:
                        node["inputs"][port] = [ref for ref in refs if ref != source["id"]]
                        affected.append(display_id(node["id"]) + " · " + port)
            self.graph["sources"].remove(source)
            if self.selected == source["id"]:
                self.selected = None
            self.pending_source = None
            self.notice = "Removed " + display_id(source["id"]) + "." + (" Reconnect: " + "; ".join(affected) + "." if affected else "")
        elif action == "use_output":
            self._add(payload.get("toolId"), payload.get("ref"), payload.get("portId"), payload.get("pin"))
        elif action == "remove_step":
            node = self._node(payload.get("nodeId"))
            index = self.graph["nodes"].index(node)
            removed = node["id"]
            self.graph["nodes"].remove(node)
            affected = []
            for other in self.graph["nodes"]:
                for port, refs in other.get("inputs", {}).items():
                    kept = [r for r in refs if not r.startswith(removed + "::")]
                    if kept != refs:
                        affected.append(display_id(other["id"]) + " · " + port)
                        other["inputs"][port] = kept
            self.selected = self.graph["nodes"][min(index, len(self.graph["nodes"])-1)]["id"] if self.graph["nodes"] else None
            self.pending_source = None
            self.notice = "Removed " + display_id(removed) + "." + (" Reconnect: " + "; ".join(affected) + "." if affected else "")
        elif action in ("rename_step", "rename_graph", "rename_source"):
            name = payload.get("name", "")
            if not clean_text(name, 200):
                raise ValueError("Names must be short plain text.")
            name = name.strip()
            if action == "rename_step":
                node = self._node(payload.get("nodeId"))
                if name:
                    node["label"] = name
                else:
                    node.pop("label", None)
            elif action == "rename_source":
                if not name:
                    raise ValueError("Give this input a name.")
                self._source(payload.get("sourceId"))["label"] = name
            else:
                self.graph["name"] = name or "Untitled analysis"
        elif action == "set_param":
            node = self._node(payload.get("nodeId"))
            field = next((p for p in self._tool(node).get("params", []) if p["id"] == payload.get("paramId")), None)
            if field is None:
                raise ValueError("This parameter is not part of the installed tool.")
            value = payload.get("value", "")
            # Permit blank required fields while editing. Run/review enforces
            # completeness; nonblank values must already obey the manifest.
            node.setdefault("params", {})[field["id"]] = "" if value == "" else validate_parameter(field, value)
        elif action == "bind_files":
            source = self._source(payload.get("sourceId"))
            files = payload.get("files")
            if not isinstance(files, dict):
                raise ValueError("Choose named local files for this input.")
            fields = {field["id"] for field in self._fields(source)}
            if not set(files).issubset(fields):
                raise ValueError("The selected files do not match this input's named fields.")
            for key, value in files.items():
                if not clean_text(value, 32768):
                    raise ValueError("A file path contains invalid characters.")
            source.setdefault("files", {}).update(files)
        elif action in ("connect", "disconnect"):
            node = self._node(payload.get("nodeId"))
            port = self._port(node, payload.get("portId"))
            refs = payload.get("refs") if action == "connect" else [r for r in node.get("inputs", {}).get(port["id"], []) if r != payload.get("ref")]
            self._set_inputs(node, port, refs)
        elif action == "add_source":
            node = self._node(payload.get("nodeId"))
            port = self._port(node, payload.get("portId"))
            label = payload.get("label")
            if label is not None and not clean_text(label, 200):
                raise ValueError("Input names must be short plain text.")
            refs = list(node.get("inputs", {}).get(port["id"], []))
            if len(refs) >= int(port.get("max", 1)):
                # A single-input tool's New input control explicitly replaces
                # its current source; multi-input joins require room to add.
                if int(port.get("max", 1)) != 1:
                    raise ValueError("Remove one source before adding another.")
                refs = []
            refs.append(self._new_source(port, label)["id"])
            self._set_inputs(node, port, refs)
        elif action == "change_tool":
            node = self._node(payload.get("nodeId"))
            old = copy.deepcopy(node)
            tool = self._tool(payload.get("toolId"), payload.get("pin"))
            node["tool"], node["pin"] = tool["id"], pin_for(tool)
            node["params"] = copy.deepcopy(tool.get("defaults", {}))
            for field in tool.get("params", []):
                if field["id"] in old.get("params", {}):
                    try:
                        node["params"][field["id"]] = validate_parameter(field, old["params"][field["id"]])
                    except ValueError:
                        pass
            node["inputs"] = {}
            for port in tool.get("ports", []):
                refs = []
                for ref in old.get("inputs", {}).get(port["id"], []):
                    if self._accepts(port, self._ref(ref)):
                        refs.append(ref)
                refs = refs[:int(port.get("max", 1))]
                while self.auto_sources and len(refs) < int(port.get("min", 1)):
                    refs.append(self._default_source(port)["id"])
                node["inputs"][port["id"]] = refs
            affected = []
            for downstream in self.graph["nodes"]:
                if downstream["id"] == node["id"]:
                    continue
                for port in self._tool(downstream, optional=True).get("ports", []):
                    kept = []
                    for ref in downstream.get("inputs", {}).get(port["id"], []):
                        try:
                            valid = self._accepts(port, self._ref(ref))
                        except ValueError:
                            valid = False
                        if valid:
                            kept.append(ref)
                        else:
                            affected.append(display_id(downstream["id"]) + " · " + port["label"])
                    downstream["inputs"][port["id"]] = kept
            self.notice = "Tool changed. Existing compatible sources were retained." + (" Reconnect: " + "; ".join(affected) + "." if affected else "")
            self.pending_source = None
        elif action == "move_step":
            node = self._node(payload.get("nodeId"))
            direction = payload.get("direction")
            if direction not in ("up", "down"):
                raise ValueError("Choose up or down.")
            group = next((group["nodes"] for group in self.engine.rank_groups(self.graph) if node["id"] in group["nodes"]), [])
            position = group.index(node["id"])
            neighbor = position + (-1 if direction == "up" else 1)
            if 0 <= neighbor < len(group):
                nodes = self.graph["nodes"]
                a = nodes.index(node)
                b = next(i for i, n in enumerate(nodes) if n["id"] == group[neighbor])
                nodes[a], nodes[b] = nodes[b], nodes[a]
            self.notice = "Display order changed within this dependency level. Connections are unchanged."
        elif action == "load_graph":
            graph = copy.deepcopy(payload.get("graph"))
            self.engine._structure(graph)
            self.engine._topology(graph)
            if payload.get("template", True):
                source_fields = {source["id"]: self._file_schema(source.get("fields", [])) for source in graph["sources"]}
                graph = {"schema": 1, "name": graph.get("name", "Untitled analysis"), "nodes": [
                    {key: copy.deepcopy(node[key]) for key in ("id", "tool", "params", "label", "inputs", "pin") if key in node}
                    for node in graph["nodes"]], "sources": [
                    {key: copy.deepcopy(source[key]) for key in ("id", "type", "label") if key in source}
                    for source in graph["sources"]], "nextNode": graph.get("nextNode", 1), "nextSource": graph.get("nextSource", 1)}
                for node in graph["nodes"]:
                    for field in self._tool(node, optional=True).get("params", []):
                        if _binding_parameter(field):
                            node.setdefault("params", {})[field["id"]] = ""
                for source in graph["sources"]:
                    source["files"] = {}
                    if source_fields[source["id"]]:
                        source["fields"] = source_fields[source["id"]]
            self.graph = graph
            self.selected = graph["nodes"][0]["id"] if graph["nodes"] else None
            self.pending_source = None
            self.notice = "Pipeline loaded. Bind local inputs and review the planned methods." if payload.get("template", True) else "Analysis loaded. Review inputs and planned methods before running."
            missing = [node for node in graph['nodes'] if not self._tool(node, optional=True)]
            if missing:
                self.notice += ' '+str(len(missing))+' step(s) need unavailable tool versions. Open Manage tools to install the exact saved packs; their settings and connections have been preserved.'
        elif action == "apply_preset":
            node = self._node(payload.get("nodeId"))
            preset = payload.get("preset")
            if not isinstance(preset, dict) or preset.get("tool") != node["tool"]:
                raise ValueError("This preset belongs to a different tool.")
            tool = self._tool(node)
            preset_tool = resolve_tool(self.catalog, preset["tool"], preset.get("pin"))
            if pin_for(preset_tool) != pin_for(tool):
                raise ValueError("This preset requires a different installed pack version.")
            allowed = {field["id"]: field for field in tool.get("params", []) if not _binding_parameter(field)}
            for key, value in preset.get("params", {}).items():
                if key not in allowed:
                    raise ValueError("Presets cannot set file, sample, library or read-group bindings.")
                node.setdefault("params", {})[key] = validate_parameter(allowed[key], value)
            self.notice = "Tool settings applied. Local inputs and sample bindings were preserved."
        elif action == "clear":
            self.graph = {"schema": 1, "name": "Untitled analysis", "nodes": [], "sources": [], "nextNode": self._next_node, "nextSource": self._next_source}
            self.selected, self.pending_source = None, None
        else:
            raise ValueError("Unknown desktop action: " + str(action))

    def snapshot(self):
        self._sync_counters()
        ranks = self.engine.rank_groups(self.graph)
        rank_of = {identity: group["rank"] for group in ranks for identity in group["nodes"]}
        consumers = {}
        for node in self.graph["nodes"]:
            for port_id, refs in node.get("inputs", {}).items():
                port = next((p for p in self._tool(node, optional=True).get("ports", []) if p["id"] == port_id), {})
                for ref in refs:
                    consumers.setdefault(ref, []).append({"nodeId": node["id"], "displayId": display_id(node["id"]), "name": self._name(node), "portId": port_id, "portLabel": port.get("label", port_id)})
        source_items = []
        for source in self.graph["sources"]:
            fields = self._fields(source)
            for field in fields:
                field["value"] = source.get("files", {}).get(field["id"], "")
            source_items.append({**copy.deepcopy(source), "displayId": display_id(source["id"]), "fields": fields,
                                 "selected": source["id"] == self.selected,
                                 "consumers": copy.deepcopy(consumers.get(source["id"], []))})
        source_map = {source["id"]: source for source in source_items}
        nodes, inspector = [], None
        if self.selected in source_map:
            source = source_map[self.selected]
            inspector = {"kind": "source", "sourceId": source["id"], "displayId": source["displayId"],
                         "name": source.get("label", "Input"), "type": source["type"],
                         "fields": copy.deepcopy(source["fields"]), "consumers": copy.deepcopy(source["consumers"])}
        for node in self.graph["nodes"]:
            missing_reason = ''
            try:
                tool = self._tool(node)
            except ValueError as exc:
                missing_reason = str(exc)
                tool = {"id": node["tool"], "name": "Unavailable tool", "ports": [], "params": [], "outputs": []}
            ports, compact_ports = [], []
            for port in tool.get("ports", []):
                refs = []
                for ref in node.get("inputs", {}).get(port["id"], []):
                    try:
                        refs.append(self._ref(ref))
                    except ValueError:
                        refs.append({"ref": ref, "label": "Unavailable source: " + ref, "type": "unknown", "external": "::" not in ref})
                compact_ports.append({key: copy.deepcopy(port[key]) for key in ("id", "label", "type", "min", "max") if key in port})
                compact_ports[-1]["refs"] = refs
                if node["id"] == self.selected:
                    ports.append({**copy.deepcopy(port), "refs": refs,
                                  "sources": [copy.deepcopy(source_map[r["ref"]]) for r in refs if self.auto_sources and r["ref"] in source_map],
                                  "choices": self._choices(node, port)})
            outputs = [{**copy.deepcopy(output), "ref": node["id"] + "::" + output["id"],
                        "consumers": copy.deepcopy(consumers.get(node["id"] + "::" + output["id"], []))}
                       for output in tool.get("outputs", [])]
            item = {"id": node["id"], "displayId": display_id(node["id"]), "name": self._name(node), "toolId": node["tool"],
                    "toolName": tool["name"], "packVersion": tool.get("packVersion", ""), "rank": rank_of[node["id"]],
                    "unavailable": bool(missing_reason),
                    "category": tool.get("category", ""), "selected": node["id"] == self.selected, "inputs": compact_ports,
                    "outputs": [{key: copy.deepcopy(output[key]) for key in ("id", "ref", "label", "type", "state", "consumers") if key in output} for output in outputs]}
            nodes.append(item)
            if node["id"] == self.selected:
                params = []
                for field in tool.get("params", []):
                    params.append({**copy.deepcopy(field), "value": node.get("params", {}).get(field["id"], field.get("default", ""))})
                inspector = {"kind": "tool", "nodeId": node["id"], "displayId": display_id(node["id"]), "name": self._name(node),
                             "tool": copy.deepcopy(tool), "ports": ports, "params": params, "outputs": outputs,
                             "sources": [copy.deepcopy(source_map[ref["ref"]]) for port in ports for ref in port["refs"] if self.auto_sources and ref["ref"] in source_map]}
                if missing_reason:
                    inspector.update(unavailable=True, missingPin=copy.deepcopy(node.get('pin')), missingReason=missing_reason)
        review = self.engine.validate(self.graph, check_files=False)
        # Keep editing responsive: snapshot checks required bindings but does
        # not read file contents. Explicit review/run performs full file checks.
        for source in source_items:
            if source["consumers"] and any(field.get("required", True) and not field.get("value") for field in source["fields"]):
                review["errors"].append({"sourceId": source["id"], "message": source["displayId"] + " · " + source.get("label", "Input") + ": choose the required file(s)."})
        review["ok"] = review["valid"] = not review["errors"]
        review["issues"] = [dict(item, severity="error") for item in review["errors"]] + [dict(item, severity="warning") for item in review["warnings"]]
        review["filesChecked"] = False
        review["methods"] = self.engine.methods(self.graph)
        compatible = []
        if self.pending_source:
            try:
                descriptor = self._ref(self.pending_source)
                compatible = [tool["id"] for tool in self.catalog["tools"].values() if any(self._accepts(port, descriptor) for port in tool.get("ports", []))]
            except ValueError:
                self.pending_source = None
        return {"schema": 1, "catalog": copy.deepcopy(self.catalog), "graph": copy.deepcopy(self.graph), "selected": self.selected,
                "nodes": nodes, "sources": source_items, "inputTypes": self.input_types(), "ranks": ranks, "inspector": inspector, "review": review,
                "canUndo": bool(self._undo), "pendingSource": self.pending_source, "compatibleTools": compatible, "notice": self.notice}
