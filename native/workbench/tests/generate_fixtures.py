#!/usr/bin/env python3
"""Generate deterministic FASTQ fixtures and independently calculated answers.

Usage: python3 tests/generate_fixtures.py build/test-fixtures
The manifest is a test-data interface, not a runner for either native host.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from reference_fastq import MAX_LINE, FastqError, analyze_path, reverse_complement_path


def stats(records: int, bases: int, gc: int, n: int, minimum: int,
          maximum: int, phred_sum: int) -> dict[str, int]:
    return dict(records=records, bases=bases, gc_bases=gc, n_bases=n,
                min_length=minimum, max_length=maximum, phred33_sum=phred_sum)


def record(name: bytes, sequence: bytes, quality: bytes,
           newline: bytes = b"\n", final_newline: bool = True) -> bytes:
    value = newline.join([b"@" + name, sequence, b"+", quality])
    return value + (newline if final_newline else b"")


def generate(destination: Path) -> dict:
    destination.mkdir(parents=True, exist_ok=True)
    cases: list[dict] = []

    def add(name: str, payload: bytes, *, expected: dict | None = None,
            error: str | None = None, reason: str = "") -> None:
        path = destination / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)
        case = {
            "path": name,
            "bytes": len(payload),
            "sha256": hashlib.sha256(payload).hexdigest(),
            "valid": error is None,
            "reason": reason,
        }
        if error is None:
            if expected is None:
                raise AssertionError("valid fixture needs an independent expected result")
            actual = analyze_path(path)
            if actual != expected:
                raise AssertionError(f"bad fixture arithmetic for {name}: {actual} != {expected}")
            case["stats"] = expected
            reverse_path = destination / "expected revcomp" / name
            reverse_path.parent.mkdir(parents=True, exist_ok=True)
            reverse_complement_path(path, reverse_path)
            case["revcomp_path"] = reverse_path.relative_to(destination).as_posix()
            case["revcomp_sha256"] = hashlib.sha256(reverse_path.read_bytes()).hexdigest()
        else:
            try:
                analyze_path(path)
            except FastqError as actual:
                if actual.kind != error:
                    raise AssertionError(f"bad error fixture {name}: {actual.kind} != {error}")
                case["error_kind"] = error
            else:
                raise AssertionError(f"invalid fixture accepted: {name}")
        cases.append(case)

    add("empty.fastq", b"", expected=stats(0, 0, 0, 0, 0, 0, 0),
        reason="Empty input is a valid zero-record dataset.")
    basic = record(b"one", b"ACGTN", b"IIIII") + record(b"two", b"acgtnn", b'!"#$%&')
    add("basic.fastq", basic, expected=stats(2, 11, 4, 3, 5, 6, 215),
        reason="Independent arithmetic: 5*40 + (0+1+2+3+4+5) = 215.")
    add("reads with spaces/échantillon Δ.fastq", basic,
        expected=stats(2, 11, 4, 3, 5, 6, 215), reason="Unicode and spaces in host paths.")
    add("crlf.fastq", record(b"crlf", b"ACgtNn", b"~!I#0?", b"\r\n"),
        expected=stats(1, 6, 2, 2, 6, 6, 180),
        reason="CRLF is stripped as a line ending; qualities span low and high Phred values.")
    add("no final newline.fastq", record(b"eof", b"ATGC", b"!~!~", final_newline=False),
        expected=stats(1, 4, 2, 0, 4, 4, 186), reason="Last quality line may end at EOF.")
    add("empty read.fastq", record(b"empty", b"", b""),
        expected=stats(1, 0, 0, 0, 0, 0, 0), reason="A four-line empty read is valid.")
    add("metadata.fastq", b"@name has spaces\nGC\n+different optional text\n@+\n",
        expected=stats(1, 2, 2, 0, 2, 2, 41),
        reason="Optional plus text need not match; @ and + can appear in quality.")
    add("mixed line endings.fastq", b"@mixed\r\nAC\n+\r\nII\n",
        expected=stats(1, 2, 1, 0, 2, 2, 80), reason="Each line accepts LF or CRLF.")

    # Arithmetic uses complete ACGTN cycles and positions in the final cycle;
    # it is independent of the parser's per-byte counting.
    lengths = (65_535, 65_536, 65_537)
    boundary = bytearray()
    expected_gc = expected_n = 0
    for length in lengths:
        cycles, tail = divmod(length, 5)
        sequence = (b"ACGTN" * (cycles + 1))[:length]
        boundary.extend(record(str(length).encode(), sequence, b"I" * length))
        expected_gc += 2 * cycles + int(tail >= 2) + int(tail >= 3)
        expected_n += cycles
    add("chunk boundaries.fastq", bytes(boundary),
        expected=stats(3, sum(lengths), expected_gc, expected_n,
                       min(lengths), max(lengths), 40 * sum(lengths)),
        reason="Records cross 64 KiB read boundaries at several offsets.")

    repeats = 300_000
    sequence = b"ACGTNacgtn" * repeats
    add("large single record.fastq", record(b"large", sequence, b"I" * len(sequence)),
        expected=stats(1, 10 * repeats, 4 * repeats, 2 * repeats,
                       10 * repeats, 10 * repeats, 400 * repeats),
        reason="A three-million-base record must not depend on a small fixed line buffer.")
    small_records = 10_000
    add("many records.fastq", record(b"r", b"ACGTN", b"55555") * small_records,
        expected=stats(small_records, 5 * small_records, 2 * small_records,
                       small_records, 5, 5, 100 * small_records),
        reason="Many records exercise parser state resets and aggregate counters.")

    add("maximum line.fastq", record(b"limit", b"C" * MAX_LINE, b"!" * MAX_LINE, b"\r\n"),
        expected=stats(1, MAX_LINE, MAX_LINE, 0, MAX_LINE, MAX_LINE, 0),
        reason="Exactly 16 MiB of logical sequence/quality is accepted, excluding CRLF.")
    add("invalid/overlong sequence.fastq", record(b"over", b"C" * (MAX_LINE + 1),
                                                 b"!" * (MAX_LINE + 1)),
        error="LINE_LIMIT", reason="A sequence one byte over the documented limit fails.")

    malformed = {
        "bad header.fastq": (b"read\nAC\n+\nII\n", "HEADER"),
        "empty identifier.fastq": (b"@\nAC\n+\nII\n", "HEADER"),
        "leading header space.fastq": (b"@ name\nAC\n+\nII\n", "HEADER"),
        "header nonascii.fastq": (b"@r\xff\nAC\n+\nII\n", "HEADER"),
        "bad separator.fastq": (b"@r\nAC\n-\nII\n", "SEPARATOR"),
        "separator nonascii.fastq": (b"@r\nAC\n+\xff\nII\n", "SEPARATOR"),
        "short quality.fastq": (b"@r\nAC\n+\nI\n", "LENGTH"),
        "long quality.fastq": (b"@r\nAC\n+\nIII\n", "LENGTH"),
        "quality space.fastq": (b"@r\nAC\n+\nI \n", "QUALITY"),
        "quality del.fastq": (b"@r\nAC\n+\nI\x7f\n", "QUALITY"),
        "quality nonascii.fastq": (b"@r\nAC\n+\nI\xff\n", "QUALITY"),
        "quality nul.fastq": (b"@r\nAC\n+\nI\x00\n", "QUALITY"),
        "bare CR at EOF.fastq": (b"@r\nAC\n+\nI\r", "QUALITY"),
        "sequence ambiguity.fastq": (b"@r\nAR\n+\nII\n", "SEQUENCE"),
        "sequence space.fastq": (b"@r\nA \n+\nII\n", "SEQUENCE"),
        "sequence nonascii.fastq": (b"@r\nA\xff\n+\nII\n", "SEQUENCE"),
        "embedded carriage return.fastq": (b"@r\nA\rC\n+\nIII\n", "SEQUENCE"),
        "missing sequence.fastq": (b"@r\n", "TRUNCATED"),
        "missing separator.fastq": (b"@r\nAC\n", "TRUNCATED"),
        "missing quality.fastq": (b"@r\nAC\n+\n", "TRUNCATED"),
        "missing empty quality.fastq": (b"@r\n\n+\n", "TRUNCATED"),
        "trailing blank line.fastq": (record(b"r", b"AC", b"II") + b"\n", "TRUNCATED"),
        "second record truncated.fastq": (record(b"r", b"AC", b"II") + b"@r2\nAC\n", "TRUNCATED"),
        "wrapped sequence.fastq": (b"@r\nAC\nGT\n+\nIIII\n", "SEPARATOR"),
    }
    for name, (payload, error) in malformed.items():
        add("invalid/" + name, payload, error=error,
            reason="Intentionally invalid under the restricted four-line contract.")

    manifest = {"schema": 1, "format": "restricted-four-line-fastq-phred33", "cases": cases}
    (destination / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
                                               encoding="utf-8")
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    manifest = generate(args.destination)
    print(json.dumps({"destination": str(args.destination), "cases": len(manifest["cases"]),
                      "valid": sum(case["valid"] for case in manifest["cases"])}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
