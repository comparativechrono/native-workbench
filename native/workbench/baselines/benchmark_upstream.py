#!/usr/bin/env python3
"""Compare pinned upstream native and portable builds on reproducible fixtures.

This measures Linux host execution only. It is not Windows validation.
"""
import argparse
import hashlib
import json
import platform
import random
import statistics
import subprocess
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fixtures(read_count):
    data = HERE / ("data" if read_count == 10_000 else f"data-{read_count}")
    data.mkdir(exist_ok=True)
    rng = random.Random(1729)
    reference = "".join(rng.choices("ACGT", k=2_000_000))
    ref = data / "reference.fa"
    ref.write_text(">synthetic_seed1729\n" + "\n".join(reference[i:i+80] for i in range(0, len(reference), 80)) + "\n")
    reads = data / "reads.fastq"
    expected = data / "reads.revcomp.expected.fastq"
    complement = str.maketrans("ACGTN", "TGCAN")
    with reads.open("w") as inp, expected.open("w") as out:
        for i in range(read_count):
            start = rng.randrange(len(reference)-150)
            sequence = list(reference[start:start+150])
            if i % 7 == 0:
                position = rng.randrange(150)
                sequence[position] = rng.choice([x for x in "ACGT" if x != sequence[position]])
            sequence = "".join(sequence)
            quality = "".join(chr(33+rng.randrange(20, 41)) for _ in range(150))
            inp.write(f"@read{i:05d}\n{sequence}\n+\n{quality}\n")
            out.write(f"@read{i:05d}\n{sequence.translate(complement)[::-1]}\n+\n{quality[::-1]}\n")
    return ref, reads, expected


def normalized_sam(path):
    # @PG embeds the invocation path, which intentionally differs by build.
    return b"".join(line for line in path.read_bytes().splitlines(keepends=True) if not line.startswith(b"@PG\t"))


def benchmark(name, executable, arguments, repetitions, results_dir):
    times = []
    max_rss_kib = []
    output = results_dir / (name + ".out")
    error = results_dir / (name + ".stderr")
    invocation = [str(executable), *map(str, arguments)]
    if executable.name.endswith("-cosmo.exe") and platform.system() == "Linux":
        invocation.insert(0, str(HERE / "bin" / "ape-loader-linux"))
    for index in range(repetitions):
        measured_invocation = invocation
        rss_file = results_dir / (name + ".maxrss")
        if Path("/usr/bin/time").is_file():
            measured_invocation = ["/usr/bin/time", "-f", "%M", "-o", str(rss_file), *invocation]
        before = time.perf_counter()
        with output.open("wb") as stdout, error.open("wb") as stderr:
            result = subprocess.run(measured_invocation, stdout=stdout, stderr=stderr)
        elapsed = time.perf_counter() - before
        if result.returncode != 0:
            raise RuntimeError(f"{name} failed with exit {result.returncode}; see {error}")
        times.append(elapsed)
        if rss_file.exists():
            max_rss_kib.append(int(rss_file.read_text().strip()))
    return {
        "binary": str(executable.relative_to(HERE)),
        "binary_bytes": executable.stat().st_size,
        "binary_sha256": sha256(executable),
        "arguments": list(map(str, arguments)),
        "invocation": invocation,
        "seconds": times,
        "median_seconds": statistics.median(times),
        "max_rss_kib": max_rss_kib,
        "median_max_rss_kib": statistics.median(max_rss_kib) if max_rss_kib else None,
        "output_sha256": sha256(output),
        "output_bytes": output.stat().st_size,
    }, output


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--repetitions", type=int, default=3)
    parser.add_argument("--read-count", type=int, default=10_000)
    args = parser.parse_args()
    ref, reads, expected = fixtures(args.read_count)
    results_dir = HERE / ("results" if args.read_count == 10_000 else f"results-{args.read_count}")
    results_dir.mkdir(exist_ok=True)
    results = {
        "host": platform.platform(),
        "scope": "Linux only; prepared native source builds, not arbitrary ELF or Windows validation",
        "fixture": {"seed": 1729, "reference_bases": 2_000_000, "reads": args.read_count, "read_bases": 150,
                    "reference_sha256": sha256(ref), "reads_sha256": sha256(reads)},
        "runs": {}, "comparisons": {},
    }
    outputs = {}
    for build in ("linux", "cosmo"):
        suffix = "-cosmo.exe" if build == "cosmo" else "-linux"
        for tool in ("seqtk", "minimap2"):
            executable = HERE / "bin" / (tool + suffix)
            if not executable.exists():
                continue
            name = tool + "-" + build
            arguments = ["seq", "-r", reads] if tool == "seqtk" else ["-ax", "sr", "-t", "2", ref, reads]
            results["runs"][name], outputs[name] = benchmark(name, executable, arguments, args.repetitions, results_dir)
            if tool == "seqtk":
                results["comparisons"][name + "_matches_python_revcomp"] = outputs[name].read_bytes() == expected.read_bytes()
            else:
                records = [line for line in outputs[name].read_text().splitlines() if not line.startswith("@")]
                results["comparisons"][name + "_primary_records"] = sum(not (int(line.split("\t")[1]) & (256 | 2048)) for line in records)
                results["comparisons"][name + "_mapped_records"] = sum(not (int(line.split("\t")[1]) & 4) for line in records)
    if "seqtk-cosmo" in outputs:
        results["comparisons"]["seqtk_exact_output_equal"] = outputs["seqtk-linux"].read_bytes() == outputs["seqtk-cosmo"].read_bytes()
    if "minimap2-cosmo" in outputs:
        results["comparisons"]["minimap2_sam_equal_except_program_header"] = normalized_sam(outputs["minimap2-linux"]) == normalized_sam(outputs["minimap2-cosmo"])
    if "minimap2-cosmo" in outputs and args.read_count == 10_000:
        vendor_test = HERE.parent / "vendor" / "minimap2-2.28" / "test"
        mitochondrial = {}
        for build in ("linux", "cosmo"):
            suffix = "-cosmo.exe" if build == "cosmo" else "-linux"
            name = "minimap2-mito-" + build
            results["runs"][name], mitochondrial[build] = benchmark(name, HERE/"bin"/("minimap2"+suffix),
                ["-a", "-t", "2", vendor_test/"MT-human.fa", vendor_test/"MT-orang.fa"], 1, results_dir)
        results["comparisons"]["mitochondrial_sam_equal_except_program_header"] = normalized_sam(mitochondrial["linux"]) == normalized_sam(mitochondrial["cosmo"])
    report = results_dir / "benchmark.json"
    report.write_text(json.dumps(results, indent=2) + "\n")
    print(json.dumps(results, indent=2))
    if any(value is False for value in results["comparisons"].values()):
        raise SystemExit("An output comparison failed")


if __name__ == "__main__":
    main()
