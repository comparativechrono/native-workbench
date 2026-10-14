"""Local, explicitly scoped measurements; no telemetry or scientific input paths.

Elapsed durations use a monotonic clock. Inclusive totals overlap component
phases and must not be added to them. Resource counters are supplied only by the
native runner; absence is never represented as zero CPU or zero memory use.
"""
from __future__ import annotations

from contextlib import contextmanager
import copy
import math
import os
import sys
import time

try:
    from .app_version import APP_VERSION
except ImportError:
    from app_version import APP_VERSION


PREPARATION_PHASES = ("validation", "freezing", "input_hashing", "reference_provenance", "export")
STEP_PHASES = ("input_verification", "scientific_preflight", "backend_runner", "output_validation_and_hashing")


def phases(names):
    return {name: {"status": "not_run", "elapsedSeconds": None} for name in names}


def elapsed(start, clock):
    return max(0.0, clock() - start)


@contextmanager
def measure(target, name, clock=None):
    """Measure one non-overlapping phase, retaining partial elapsed on failure."""
    clock = clock or time.perf_counter
    start = clock()
    target[name] = {"status": "running", "elapsedSeconds": None}
    try:
        yield
    except InterruptedError:
        target[name]["status"] = "cancelled"
        raise
    except BaseException:
        target[name]["status"] = "failed"
        raise
    else:
        target[name]["status"] = "completed"
    finally:
        target[name]["elapsedSeconds"] = elapsed(start, clock)


def _native_architecture():
    """Ask the kernel directly; platform.uname() also looks up a hostname."""
    try:
        if os.name != "nt":
            return os.uname().machine
        import ctypes
        class ProcessorInfo(ctypes.Structure):
            _fields_ = [("architecture", ctypes.c_uint16), ("reserved", ctypes.c_uint16)]
        class ProcessorUnion(ctypes.Union):
            _anonymous_ = ("processor",)
            _fields_ = [("oemId", ctypes.c_uint32), ("processor", ProcessorInfo)]
        class SystemInfo(ctypes.Structure):
            _anonymous_ = ("processor",)
            _fields_ = [("processor", ProcessorUnion), ("pageSize", ctypes.c_uint32),
                        ("minimumAddress", ctypes.c_void_p), ("maximumAddress", ctypes.c_void_p),
                        ("activeProcessorMask", ctypes.c_size_t), ("processorCount", ctypes.c_uint32),
                        ("processorType", ctypes.c_uint32), ("allocationGranularity", ctypes.c_uint32),
                        ("processorLevel", ctypes.c_uint16), ("processorRevision", ctypes.c_uint16)]
        information = SystemInfo()
        # The API has no failure return. An unmodified/unknown architecture is
        # unavailable, rather than accidentally reporting the zero value x86.
        information.architecture = 0xffff
        function = ctypes.WinDLL("kernel32", use_last_error=True).GetNativeSystemInfo
        function.argtypes = [ctypes.POINTER(SystemInfo)]
        function.restype = None
        function(ctypes.byref(information))
        return {0: "x86", 5: "ARM", 6: "IA64", 9: "AMD64", 12: "ARM64"}.get(information.architecture)
    except (AttributeError, OSError, ValueError):
        return None


def safe_system_identity():
    """Kernel version and architecture without socket, host or environment calls.

    Windows version numbers are kernel API values, not inferred marketing names.
    POSIX uname's nodename is deliberately never serialized or returned.
    """
    identity = {"name": "Windows" if os.name == "nt" else sys.platform, "release": None, "version": None}
    try:
        if os.name == "nt":
            version = sys.getwindowsversion()
            identity.update(release=f"{version.major}.{version.minor}", version=f"{version.major}.{version.minor}.{version.build}")
        else:
            version = os.uname()
            identity.update(name=version.sysname, release=version.release, version=version.version)
    except (AttributeError, OSError, ValueError):
        pass
    return {"os": identity, "architecture": _native_architecture()}


def system_information():
    """General local hardware/OS facts; no socket, host, user or path lookup."""
    memory = None
    try:
        if os.name == "nt":
            import ctypes
            from ctypes import wintypes
            class MemoryStatus(ctypes.Structure):
                _fields_ = [("length", wintypes.DWORD), ("load", wintypes.DWORD)] + [
                    (name, ctypes.c_ulonglong) for name in
                    ("physical", "availablePhysical", "pageFile", "availablePageFile", "virtual", "availableVirtual", "extendedVirtual")]
            status = MemoryStatus()
            status.length = ctypes.sizeof(status)
            function = ctypes.WinDLL("kernel32", use_last_error=True).GlobalMemoryStatusEx
            function.argtypes = [ctypes.POINTER(MemoryStatus)]
            function.restype = wintypes.BOOL
            if function(ctypes.byref(status)):
                memory = int(status.physical)
        else:
            pages, page_size = os.sysconf("SC_PHYS_PAGES"), os.sysconf("SC_PAGE_SIZE")
            if pages > 0 and page_size > 0:
                memory = pages * page_size
    except (AttributeError, OSError, ValueError):
        pass
    count = os.cpu_count()
    identity = safe_system_identity()
    return {**identity, "logicalCpuCount": count,
            "physicalMemoryBytes": memory,
            "unavailable": [name for name, value in (("logicalCpuCount", count), ("physicalMemoryBytes", memory),
                ("architecture", identity["architecture"]), ("os.release", identity["os"]["release"]), ("os.version", identity["os"]["version"])) if value is None]}


def unavailable_metrics(reason="runner_did_not_report_resource_metrics"):
    return {"available": False, "reason": reason, "data": None}


def native_metrics(value):
    """Keep only the versioned native counter contract, never arbitrary messages.

    The caller records the source OS separately. This does not manufacture native
    counters for Python, mocked backends, or results from older bridge versions.
    """
    if not isinstance(value, dict) or value.get("schema") != 1 or value.get("source") != "windows-job-object" or value.get("scope") != "workflow-command-stages":
        return unavailable_metrics()
    stages = value.get("stages")
    if not isinstance(stages, list) or len(stages) > 4096:
        return unavailable_metrics("invalid_runner_resource_metrics")
    result = {"schema": 1, "source": "windows-job-object", "scope": "workflow-command-stages", "stages": []}
    numeric = ("wall_ms", "user_cpu_seconds", "kernel_cpu_seconds", "peak_job_memory_bytes", "processes_total", "processes_active_at_snapshot", "accounting_error", "memory_error")
    integer = set(numeric) - {"user_cpu_seconds", "kernel_cpu_seconds"}
    for stage in stages:
        if not isinstance(stage, dict) or not isinstance(stage.get("id"), str) or len(stage["id"]) > 256 or any(ord(c) < 32 for c in stage["id"]):
            return unavailable_metrics("invalid_runner_resource_metrics")
        if stage.get("kind") not in {"exec", "pipe", "copy"} or stage.get("status") not in {"success", "failed", "cancelled", "skipped", "pending", "running", "blocked", "not_run"}:
            return unavailable_metrics("invalid_runner_resource_metrics")
        item = {key: stage[key] for key in ("id", "kind", "status")}
        raw = stage.get("resources")
        if raw is None:
            item["resources"] = None
        else:
            if (not isinstance(raw, dict) or raw.get("schema") != 1 or raw.get("source") != "windows-job-object"
                    or raw.get("scope") not in {"command-process-tree", "pipeline-process-tree"}
                    or raw.get("coverage") not in {"complete", "partial", "unavailable", "not-started"}
                    or raw.get("memory_kind") != "committed" or raw.get("snapshot") != "before-job-close"):
                return unavailable_metrics("invalid_runner_resource_metrics")
            resources = {key: raw[key] for key in ("schema", "source", "scope", "coverage", "memory_kind", "snapshot")}
            for key in numeric:
                number = raw.get(key)
                if number is not None and (isinstance(number, bool) or not isinstance(number, (int, float)) or number < 0 or number > 2**64 - 1 or not math.isfinite(number) or (key in integer and not isinstance(number, int))):
                    return unavailable_metrics("invalid_runner_resource_metrics")
                resources[key] = number
            for key in ("accounting_available", "memory_available"):
                if not isinstance(raw.get(key), bool):
                    return unavailable_metrics("invalid_runner_resource_metrics")
                resources[key] = raw[key]
            item["resources"] = resources
        result["stages"].append(item)
    measured = any(stage["resources"] and (stage["resources"]["accounting_available"] or stage["resources"]["memory_available"]) for stage in result["stages"])
    return {"available": measured, "reason": None if measured else "no_native_resource_counters_available", "data": result}


def preparation():
    return {"status": "running", "elapsedSeconds": None, "phases": phases(PREPARATION_PHASES),
            "scope": "Preparation through CWL definition export; excludes writing the frozen plan and result companion files.",
            "system": system_information()}


def make_record(plan):
    sources = {ref for node in plan["nodes"] for refs in node["inputs"].values() for ref in refs if "::" not in ref}
    inputs = [{"sha256": item["sha256"], "bytes": item["bytes"]} for item in plan["inputs"].values()]
    steps = []
    for node in plan["nodes"]:
        # Numeric thread controls only; labels, free text, and arbitrary options
        # may contain sample names and do not belong in a measurement record.
        threads = {}
        for name, value in node["params"].items():
            if name.lower() in {"threads", "thread", "thread_count", "num_threads", "nthreads", "cpus"}:
                text = str(value)
                if text.isascii() and text.isdigit() and len(text) < 10:
                    threads[name] = int(text)
        steps.append({"id": node["id"], "tool": node["tool"]["id"],
                      "pin": {key: node["tool"].get(key, "") for key in ("packId", "packVersion", "manifestSha256")},
                      "threadParameters": threads, "status": "not_run", "elapsedSeconds": None,
                      "phases": phases(STEP_PHASES), "backendMetrics": unavailable_metrics("step_not_run")})
    return {"schema": 1, "kind": "native-workbench-performance", "appVersion": APP_VERSION,
            "runId": plan["id"], "planSha256": plan["sha256"], "status": "planned",
            "system": system_information(), "inputSummary": {"sourceCount": len(sources), "uniqueFileCount": len(inputs),
                "totalBytes": sum(item["bytes"] for item in inputs), "files": inputs},
            "preparation": copy.deepcopy(plan.get("performancePreparation", {"status": "unavailable", "elapsedSeconds": None,
                "phases": phases(PREPARATION_PHASES), "reason": "prepared_by_older_application"})),
            "execution": {"status": "not_run", "elapsedSeconds": None, "phases": phases(("startup", "finalization")),
                "scope": "Inclusive engine execution through methods/CWL finalization; excludes final performance and run record writes."},
            "steps": steps,
            "interpretation": {"clock": "monotonic-perf-counter", "elapsedUnit": "seconds",
                "inclusiveTotalsOverlapPhases": True,
                "parallelStepDurationsOverlap": True,
                "cpuReservationMeaning": "Declared admission allocation, not OS CPU enforcement or observed utilisation; unknown requirements run exclusively.",
                "backendRunnerScope": "Bridge invocation including native checks, command stages and result collection; not pure scientific compute time.",
                "nativeMemoryMeaning": "Peak Job Object committed memory, not resident set size (RSS).",
                "cpuAndMemoryAggregation": "Per native command stage only; no summed peak-memory or estimated CPU totals.",
                "unmeasured": ["disk_io_bytes", "temporary_disk_peak_bytes", "system_load", "tool_thread_utilisation"]}}
