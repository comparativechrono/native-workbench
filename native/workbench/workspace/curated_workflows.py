"""Two local, exactly pinned synthetic training workflows.

The catalogue is application-owned teaching material, not an online pack feed.
Listing and loading never install tools, execute a workflow or rewrite inputs.
Known answers apply only to the recorded fixture, parameters and pack pins.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
from pathlib import Path

try:
    from .catalog import resolve_tool
    from .engine import _io_path, _resolved_path
except ImportError:
    from catalog import resolve_tool
    from engine import _io_path, _resolved_path


_PACKS = {
    "align": {
        "packId": "align", "packVersion": "0.4.0",
        "manifestSha256": "81c962222c93356a4f7727b23193c71d7dcd515859e62a179574781f411824d3",
        "name": "minimap2 alignment",
        "tools": [{"id": "minimap2", "name": "minimap2", "version": "2.28-r1209"},
                  {"id": "paircheck", "name": "Read-pair validator", "version": "1.0.1"}],
    },
    "bam": {
        "packId": "bam", "packVersion": "0.4.0",
        "manifestSha256": "45b3f9d5092b0b3014f67b29331003e1214c72919f85695a571fb371030a9888",
        "name": "SAMtools alignment files",
        "tools": [{"id": "samtools", "name": "SAMtools", "version": "1.24"}],
    },
    "variants": {
        "packId": "variants", "packVersion": "0.4.0",
        "manifestSha256": "ea4b7f0a6c28709e4190b6514c07cbf7bdd58e1a4f2a2d931f2cae3ce6ec3795",
        "name": "BCFtools variants",
        "tools": [{"id": "bcftools", "name": "BCFtools", "version": "1.24"},
                  {"id": "samtools", "name": "SAMtools", "version": "1.24"}],
    },
    "builtin": {
        "packId": "builtin", "packVersion": "0.5.0",
        "manifestSha256": hashlib.sha256(b"native-workbench-report-v1").hexdigest(),
        "name": "Workbench statistics report",
        "tools": [],
    },
}

# These are the unchanged, redistributable repository starter fixture bytes.
# Do not substitute a newer fixture or read expected answers from mutable files.
_FIXTURES = (
    ("reads1.fastq", 22011, "33053fdfd6ca5abbe34883f869958a2e621e7d513ada06f401e91ad256e9cc21",
     "Read 1", "101 synthetic uncompressed FASTQ reads, each 100 bases; Phred+33 quality 40."),
    ("reads2.fastq", 22011, "18b5ceeefb0115120830005a21808489f2c471c78af4aaaf724cdf99697a80e1",
     "Read 2", "101 matching synthetic mates, in the same order; each 100 bases."),
    ("reference.fa", 3059, "3dd9031bc90515d274079fd7135da6fd8129315a9c364558bf9ec030c9e36dee",
     "Reference", "One artificial DNA contig named starter, 3,000 bases long."),
    ("truth.json", 261, "dbef1c9f40205f38fb8c51cd2109db009a006e8ae15485235aff31263a85f977",
     "Known answers", "Recorded fixture seed 2026100306 and the synthetic variant; not an analysis input."),
)

_NOTICE = (
    "Synthetic training only. These small artificial datasets teach workflow operation; "
    "they do not establish suitability for biological or clinical samples. Expected answers "
    "are fixture checks, not QC pass thresholds. Loading is local and does not run or download anything."
)

_COMMON_EXPECTED = [
    "101 matched read pairs: 202 reads and 20,200 input bases; each read is 100 bases long.",
    "202 mapped, paired and properly paired alignment records on starter (3,000 bases), with sample starter.",
    "A coordinate-sorted, duplicate-marked BAM and CSI index. Duplicate records are retained, not removed.",
    "Read-pair validation, SAMtools flag counts and alignment statistics remain available as raw outputs. "
    "Interpret recorded measurements in context; no overall sample QC pass/fail is assigned.",
]

_DEFINITIONS = (
    {
        "id": "alignment-qc", "name": "Synthetic training: alignment with QC",
        "summary": "Align paired reads and inspect measured alignment and read-pair statistics.",
        "description": "Learn how paired FASTQ inputs connect to an artificial reference, "
                       "a prepared BAM and a report. minimap2 validates pairing and aligns the reads; "
                       "SAMtools sorts, fixes mates, marks duplicates and records alignment statistics. "
                       "There is no trimming or automatic sample-quality decision.",
        "expectedAnswers": _COMMON_EXPECTED,
        "steps": (
            ("align/paired-end", "Align synthetic paired reads", {"reads": ["input-1"], "reference": ["input-2"]},
             {"sample": "starter", "threads": "2"}),
            ("bam/prepare", "Prepare alignments and record QC", {"alignment": ["step-1::sam"]}, {}),
            ("builtin/report", "Collect alignment measurements", {"metrics": ["step-2::flagstat", "step-2::alignment-stats"]},
             {"title": "Synthetic training: alignment measurements"}),
        ),
    },
    {
        "id": "variant-calling", "name": "Synthetic training: variant calling",
        "summary": "Follow paired reads through alignment to a known homozygous single-base variant.",
        "description": "Learn a small-variant workflow on the same artificial reads. "
                       "After alignment and BAM preparation, BCFtools calculates genotype likelihoods, "
                       "calls diploid variants, normalizes alleles and labels low-quality calls. "
                       "The ploidy is explicitly set to 2 for this fixture. The calling parameters "
                       "are teaching settings, not recommendations for another assay.",
        "expectedAnswers": _COMMON_EXPECTED + [
            "One normalized SNP: starter:1351 G>A, with sample starter genotype 1/1; "
            "the VCF and CSI index, intermediate calls and BCFtools statistics are retained.",
            "Calling settings: mapping quality at least 20, base quality at least 20, "
            "maximum pileup depth 1,000. QUAL below 20 or sample DP below 5 receives LowQual; "
            "calls are retained. These explicit variant-filter settings are not a sample QC verdict.",
        ],
        "steps": (
            ("align/paired-end", "Align synthetic paired reads", {"reads": ["input-1"], "reference": ["input-2"]},
             {"sample": "starter", "threads": "2"}),
            ("bam/prepare", "Prepare alignments and record QC", {"alignment": ["step-1::sam"]}, {}),
            ("variants/call", "Call the synthetic variant", {"alignment": ["step-2::bam"], "reference": ["input-2"]},
             {"ploidy": "2", "min-mapq": "20", "min-baseq": "20", "max-depth": "1000", "min-qual": "20", "min-depth": "5"}),
            ("variants/statistics", "Summarize variant calls", {"variants": ["step-3::variants"]}, {}),
            ("builtin/report", "Collect alignment and variant measurements", {"metrics": ["step-2::alignment-stats", "step-4::statistics"]},
             {"title": "Synthetic training: alignment and variant measurements"}),
        ),
    },
)


def _pin(pack_id):
    return {key: _PACKS[pack_id][key] for key in ("packId", "packVersion", "manifestSha256")}


def _fixture_status(app_root):
    """Inspect four fixed small paths, with exact sizes and bounded reads."""
    root = _resolved_path(app_root)
    inputs, issues = [], []
    for name, size, digest, label, description in _FIXTURES:
        relative = "examples/starter/" + name
        path = root / relative
        entry = {"name": name, "label": label, "description": description,
                 "relativePath": relative, "path": str(path), "bytes": size, "sha256": digest,
                 "available": False}
        try:
            for part in (root / "examples", root / "examples/starter", path):
                physical = _io_path(part)
                if physical.is_symlink() or getattr(physical, "is_junction", lambda: False)():
                    raise ValueError("a linked fixture path is not supported")
            physical = _io_path(path)
            if not physical.is_file():
                raise ValueError("the fixture file is missing")
            if physical.stat().st_size != size:
                raise ValueError("the fixture size differs")
            with physical.open("rb") as stream:
                data = stream.read(size + 1)
            if len(data) != size or hashlib.sha256(data).hexdigest() != digest:
                raise ValueError("the fixture bytes differ")
            entry["available"] = True
        except (OSError, ValueError) as error:
            entry["issue"] = ("Restore " + relative + " from this application's original archive: " + str(error) +
                              ". Your analysis inputs and previous results need not be replaced.")
            issues.append(entry["issue"])
        inputs.append(entry)
    return inputs, issues


def _requirements(definition, catalog):
    requirements = []
    for operation, _, _, _ in definition["steps"]:
        pack_id = operation.split("/", 1)[0]
        requirement = next((item for item in requirements if item["packId"] == pack_id), None)
        if requirement is None:
            requirement = deepcopy(_PACKS[pack_id])
            requirement.update(operations=[], available=True, missingOperations=[])
            requirement["guidance"] = (
                "Restore the original application archive to recover its built-in report operation."
                if pack_id == "builtin" else
                "Open Manage tools and install " + pack_id + " 0.4.0, or import the official "
                "native-workbench-pack-" + pack_id + "-0.4.0.zip. Keep other installed versions; "
                "this training workflow requires the exact recorded manifest.")
            requirements.append(requirement)
        requirement["operations"].append(operation)
        try:
            resolve_tool(catalog, operation, _pin(pack_id))
        except (ValueError, KeyError, TypeError):
            requirement["available"] = False
            requirement["missingOperations"].append(operation)
    return requirements


def _entry(definition, catalog, inputs, fixture_issues):
    requirements = _requirements(definition, catalog)
    issues = list(fixture_issues)
    for requirement in requirements:
        if not requirement["available"]:
            issues.append("Missing exact dependency: " + requirement["name"] + " (" + requirement["packId"] +
                          " " + requirement["packVersion"] + "). " + requirement["guidance"])
    entry = {key: deepcopy(definition[key]) for key in ("id", "name", "summary", "description", "expectedAnswers")}
    entry.update(inputs=deepcopy(inputs), requirements=requirements, available=not issues, issues=issues,
                 notice=_NOTICE, datasetLicense="MIT; repository LICENSE", stepCount=len(definition["steps"]))
    lines = [entry["name"], "", entry["description"], "", "Inputs (bundled synthetic data)"]
    lines.extend(item["label"] + ": " + item["description"] for item in inputs)
    lines += ["", "Expected answers for these exact inputs and settings"] + entry["expectedAnswers"]
    lines += ["", "Exact dependencies"]
    for requirement in requirements:
        versions = ", ".join(tool["name"] + " " + tool["version"] for tool in requirement["tools"])
        lines.append(requirement["packId"] + " " + requirement["packVersion"] +
                     (" — " + versions if versions else " — application report renderer") +
                     (" (available)" if requirement["available"] else " (missing exact version)"))
        lines.append("Manifest SHA-256: " + requirement["manifestSha256"])
    lines += ["", _NOTICE, "The synthetic fixture is redistributable under the repository MIT license.",
              "Recorded methods and original named outputs remain in each run folder. "
              "Known answers no longer apply after editing inputs, tool versions or parameters."]
    if issues:
        lines += ["", "Before loading"] + issues
    entry["details"] = "\n".join(lines)
    return entry


def list_catalogue(app_root, catalog):
    """Return readable local entries, including actionable missing dependencies.

    Availability covers exact operation pins and fixture bytes, not executable
    integrity, successful scientific execution or output-folder readiness.
    """
    inputs, issues = _fixture_status(app_root)
    return {"schema": 1, "workflows": [_entry(item, catalog, inputs, issues) for item in _DEFINITIONS],
            "notice": _NOTICE, "availabilityScope": "Exact operation pins and fixture bytes; run readiness and tool execution are separate."}


def load_workflow(app_root, catalog, identity):
    """Create a normal editable graph after rechecking its fixed dependencies."""
    if not isinstance(identity, str) or len(identity) > 80:
        raise ValueError("Choose a workflow from the curated training catalogue.")
    definition = next((item for item in _DEFINITIONS if item["id"] == identity), None)
    if definition is None:
        raise ValueError("Unknown curated training workflow. Choose a listed workflow.")
    inputs, issues = _fixture_status(app_root)
    entry = _entry(definition, catalog, inputs, issues)
    if not entry["available"]:
        raise ValueError("This training workflow is not available. " + " ".join(entry["issues"]))
    files = {item["name"]: item["path"] for item in inputs}
    graph = {"schema": 1, "name": definition["name"], "sources": [
        {"id": "input-1", "label": "Synthetic paired reads (101 pairs)", "type": "pair",
         "files": {"reads1": files["reads1.fastq"], "reads2": files["reads2.fastq"]}},
        {"id": "input-2", "label": "Synthetic reference (starter, 3000 bases)", "type": "reference",
         "files": {"reference": files["reference.fa"]}}],
        "nodes": [], "nextNode": len(definition["steps"]) + 1, "nextSource": 3}
    for index, (operation, label, bindings, overrides) in enumerate(definition["steps"], 1):
        pin = _pin(operation.split("/", 1)[0])
        tool = resolve_tool(catalog, operation, pin)
        params = deepcopy(tool["defaults"])
        params.update(overrides)
        graph["nodes"].append({"id": "step-" + str(index), "tool": operation, "label": label,
                               "inputs": deepcopy(bindings), "params": params, "pin": pin})
    return graph
