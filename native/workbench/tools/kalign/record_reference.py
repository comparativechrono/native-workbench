"""Record/re-execute the pinned pristine Linux CLI on independent indel fixtures."""
import argparse
import hashlib
import json
import subprocess
import tempfile
from pathlib import Path

SOURCE_COMMIT = "3e6de1df29d111c5fa5beb4c4294ef681978fd23"
SOURCE_SHA256 = "01bacb2205e7b6792c570b163b5ccc0713284737ba862ca3b500a96a8a4d1bd9"


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def fasta(path):
    rows = {}
    name = None
    for line in Path(path).read_text(encoding="ascii").splitlines():
        if line.startswith(">"):
            name = line[1:].split()[0]
            if name in rows:
                raise ValueError("Duplicate output identifier")
            rows[name] = ""
        elif line:
            if name is None:
                raise ValueError("Missing FASTA header")
            rows[name] += line
    return rows


def record(binary, fixtures):
    binary, fixtures = Path(binary).resolve(), Path(fixtures).resolve()
    build = json.loads((binary.parent / "build.json").read_text())
    if (build["upstreamCommit"] != SOURCE_COMMIT or not build["upstreamSourceUnmodified"]
            or build["files"][binary.name]["sha256"] != sha(binary)
            or build["sources"]["kalign-3.5.1.tar.gz"]["sha256"] != SOURCE_SHA256):
        raise ValueError("Pristine pinned reference provenance does not match executable")
    result = {
        "schema": 1,
        "toolVersion": "3.5.1",
        "sourceCommit": SOURCE_COMMIT,
        "sourceArchiveSha256": SOURCE_SHA256,
        "referenceExecutableSha256": sha(binary),
        "scope": "Pristine upstream serial baseline Linux execution on ordinary DNA/protein fixtures. CLI alphabet-override correction cases are tested separately; this reference is not independent biological truth.",
        "cases": {},
    }
    with tempfile.TemporaryDirectory(prefix="kalign-reference-") as directory:
        for datatype, upstream_type in [("nucleotide", "dna"), ("protein", "protein")]:
            source = fixtures / f"{datatype}.fa"
            output = Path(directory) / f"{datatype}.afa"
            arguments = [str(binary), "-i", str(source), "-o", str(output),
                         "--type", upstream_type, "-n", "1", "-f", "fasta"]
            child = subprocess.run(arguments, capture_output=True, text=True, timeout=60)
            if child.returncode:
                raise RuntimeError(child.stdout + child.stderr)
            alignment = fasta(output)
            if alignment != fasta(fixtures / f"{datatype}-truth.afa"):
                raise ValueError(f"Pristine {datatype} alignment does not match independent indel truth")
            result["cases"][datatype] = {
                "fixtureSha256": sha(source),
                "truthSha256": sha(fixtures / f"{datatype}-truth.afa"),
                "alignment": alignment,
                "independentHomologyTruthPassed": True,
            }
    return result


def verify(actual, expected):
    # Compiler/platform differences may alter reference executable bytes; each
    # actual execution is bound to its own source and executable build record.
    for key in ["toolVersion", "sourceCommit", "sourceArchiveSha256", "cases"]:
        if actual[key] != expected[key]:
            raise ValueError("Live pristine Linux reference changed: " + key)
    return len(actual["cases"])


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path, required=True)
    parser.add_argument("--fixtures", type=Path, default=Path(__file__).parent / "fixtures")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(record(args.binary, args.fixtures), indent=2) + "\n", encoding="utf-8")
