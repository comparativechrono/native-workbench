"""Indel homology specified before running any sequence aligner.

All input residues and true alignment columns derive from this deterministic
construction; an aligner's output is never used to create expected answers.
"""
import json
import random
from pathlib import Path


def fixtures(destination):
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    cases = {}
    for datatype, alphabet, length, insertion_length in [
        ("nucleotide", "ACGT", 240, 10),
        ("protein", "ACDEFGHIKLMNPQRSTVWY", 240, 8),
    ]:
        rng = random.Random(643)
        ancestor = "".join(rng.choice(alphabet) for _ in range(length))
        insertion = "".join(rng.choice(alphabet) for _ in range(insertion_length))
        rows = []
        for number, (deleted, inserted) in enumerate(
            [(False, False), (True, False), (False, True),
             (True, True), (False, False), (False, True)], 1
        ):
            sequence = list(ancestor)
            # Private changes away from either indel distinguish related rows.
            position = 20 + number * 3
            sequence[position] = rng.choice(alphabet.replace(sequence[position], ""))
            if deleted:
                sequence[70:82] = "-" * 12
            sequence[160:160] = insertion if inserted else "-" * insertion_length
            rows.append((f"sample_{number}", "".join(sequence)))
        headers = {name: f"{name} synthetic {datatype} training sequence {index}"
                   for index, (name, _) in enumerate(rows, 1)}
        (destination / f"{datatype}.fa").write_bytes(
            "".join(f">{headers[name]}\n{sequence.replace('-', '')}\n"
                    for name, sequence in rows).encode("utf-8"))
        (destination / f"{datatype}-truth.afa").write_bytes(
            "".join(f">{headers[name]}\n{sequence}\n" for name, sequence in rows).encode("utf-8"))
        cases[datatype] = {
            "sequenceIds": [name for name, _ in rows],
            "headers": headers,
            "sequences": 6,
            "columns": length + insertion_length,
            "inputResidues": sum(len(sequence.replace("-", "")) for _, sequence in rows),
            "gapCharacters": sum(sequence.count("-") for _, sequence in rows),
            "deletionAncestorColumnsZeroBased": [70, 82],
            "insertionBeforeAncestorColumnZeroBased": 160,
            "insertedResidues": insertion,
            "homologyTruthFile": f"{datatype}-truth.afa",
        }
    truth = {
        "schema": 1,
        "source": "Independent deterministic construction: random seed 643; 240-residue ancestor; six related sequences with independently assigned private substitutions, a 12-residue deletion and a shared insertion. Expected alignment columns are constructed before executing Kalign.",
        "cases": cases,
        "scope": "Small synthetic known-indel homology and residue preservation; no real-data accuracy, phylogenetic inference, time/memory prediction or QC pass threshold.",
    }
    # Canonical UTF-8/LF bytes on every host, including Windows text-mode defaults.
    (destination / "truth.json").write_bytes((json.dumps(truth, indent=2) + "\n").encode("utf-8"))
    return truth


if __name__ == "__main__":
    fixtures(Path(__file__).parent / "fixtures")
