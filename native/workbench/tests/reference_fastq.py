#!/usr/bin/env python3
"""Independent, readable oracle for the prototype's restricted FASTQ format.

This deliberately uses Python's line reader, rather than reproducing the native
module's byte/chunk parser. It holds one record at a time and never stages input
to another file. The format contract is in tests/README.md.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Iterator

MAX_LINE = 16 * 1024 * 1024
COMPLEMENT = bytes.maketrans(b"ACGTNacgtn", b"TGCANtgcan")


@dataclass
class FastqError(ValueError):
    kind: str
    record: int
    line: int
    detail: str

    def as_dict(self) -> dict[str, str | int]:
        return {
            "kind": self.kind,
            "record": self.record,
            "line": self.line,
            "detail": self.detail,
        }

    def __str__(self) -> str:
        return f"{self.kind}: record {self.record}, line {self.line}: {self.detail}"


def _line(stream: BinaryIO, record: int, line: int) -> bytes | None:
    raw = stream.readline(MAX_LINE + 3)
    if raw == b"":
        return None
    if raw.endswith(b"\n"):
        raw = raw[:-1]
        if raw.endswith(b"\r"):
            raw = raw[:-1]
    if len(raw) > MAX_LINE:
        raise FastqError("LINE_LIMIT", record, line, "logical line exceeds 16 MiB")
    return raw


def iter_records(stream: BinaryIO) -> Iterator[tuple[bytes, bytes, bytes, bytes]]:
    record = 1
    while (header := _line(stream, record, (record - 1) * 4 + 1)) is not None:
        first_line = (record - 1) * 4 + 1
        lines = [header]
        for offset in range(1, 4):
            value = _line(stream, record, first_line + offset)
            if value is None:
                raise FastqError("TRUNCATED", record, first_line + offset,
                                 "record must contain four lines")
            lines.append(value)
        header, sequence, separator, quality = lines
        if not header.startswith(b"@") or len(header) == 1 or not 33 <= header[1] <= 126:
            raise FastqError("HEADER", record, first_line,
                             "header must start with @ and contain an identifier")
        if any(value < 32 or value > 126 for value in header):
            raise FastqError("HEADER", record, first_line,
                             "header must contain printable ASCII")
        if any(value not in b"ACGTNacgtn" for value in sequence):
            raise FastqError("SEQUENCE", record, first_line + 1,
                             "sequence alphabet is ACGTN, case-insensitive")
        if not separator.startswith(b"+"):
            raise FastqError("SEPARATOR", record, first_line + 2,
                             "separator must start with +")
        if any(value < 32 or value > 126 for value in separator):
            raise FastqError("SEPARATOR", record, first_line + 2,
                             "separator must contain printable ASCII")
        if len(sequence) != len(quality):
            raise FastqError("LENGTH", record, first_line + 3,
                             "sequence and quality lengths differ")
        if any(value < 33 or value > 126 for value in quality):
            raise FastqError("QUALITY", record, first_line + 3,
                             "Phred+33 bytes must be in the range 33 through 126")

        yield header, sequence, separator, quality
        record += 1


def analyze_stream(stream: BinaryIO) -> dict[str, int]:
    stats = {
        "records": 0,
        "bases": 0,
        "gc_bases": 0,
        "n_bases": 0,
        "min_length": 0,
        "max_length": 0,
        "phred33_sum": 0,
    }
    for _, sequence, _, quality in iter_records(stream):
        length = len(sequence)
        upper = sequence.upper()
        stats["records"] += 1
        stats["bases"] += length
        stats["gc_bases"] += upper.count(b"G") + upper.count(b"C")
        stats["n_bases"] += upper.count(b"N")
        stats["phred33_sum"] += sum(quality) - 33 * length
        stats["min_length"] = (length if stats["records"] == 1
                               else min(stats["min_length"], length))
        stats["max_length"] = max(stats["max_length"], length)
    return stats


def analyze_path(path: str | Path) -> dict[str, int]:
    with open(path, "rb") as stream:
        return analyze_stream(stream)


def reverse_complement_stream(source: BinaryIO, destination: BinaryIO) -> None:
    """Preserve metadata and base case; reverse qualities; normalize to LF."""
    for header, sequence, separator, quality in iter_records(source):
        destination.write(b"\n".join((header, sequence.translate(COMPLEMENT)[::-1],
                                       separator, quality[::-1])) + b"\n")


def reverse_complement_path(source: str | Path, destination: str | Path) -> None:
    if Path(source).resolve() == Path(destination).resolve():
        raise ValueError("reference output must differ from input")
    with open(source, "rb") as input_stream, open(destination, "wb") as output_stream:
        reverse_complement_stream(input_stream, output_stream)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("--revcomp-output", type=Path,
                        help="also write independent reverse-complement output")
    args = parser.parse_args()
    try:
        stats = analyze_path(args.input)
        if args.revcomp_output is not None:
            reverse_complement_path(args.input, args.revcomp_output)
    except FastqError as error:
        print(json.dumps({"ok": False, "error": error.as_dict()}))
        return 2
    except OSError as error:
        print(json.dumps({"ok": False, "error": {"kind": "IO", "detail": str(error)}}))
        return 3
    print(json.dumps({"ok": True, "stats": stats}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
