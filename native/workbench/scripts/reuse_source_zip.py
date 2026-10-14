#!/usr/bin/env python3
"""Rebuild a ZIP with target member metadata, reusing identical base DEFLATE bodies.

No input is modified. Reuse requires matching decompressed SHA256, length, CRC,
and compression method; every result is independently decompressed and verified.
This is packaging byte reuse, not a patch to any application or scientific binary.
"""
from __future__ import annotations
import argparse
import copy
import hashlib
import json
from pathlib import Path
import struct
import zipfile

CHUNK = 1024 * 1024
META = ("filename", "date_time", "compress_type", "flag_bits", "comment", "extra",
        "create_version", "create_system", "extract_version", "reserved", "volume",
        "internal_attr", "external_attr", "CRC", "file_size")


def checksum(stream):
    h = hashlib.sha256()
    while part := stream.read(CHUNK):
        h.update(part)
    return h.hexdigest()


def member_hash(archive, info):
    with archive.open(info) as stream:
        return checksum(stream)


def body_offset(archive, info):
    archive.fp.seek(info.header_offset)
    header = archive.fp.read(30)
    if len(header) != 30 or header[:4] != b"PK\x03\x04":
        raise ValueError("Invalid local member header: " + info.filename)
    fields = struct.unpack("<4s5H3L2H", header)
    return info.header_offset + 30 + fields[-2] + fields[-1]


def body_hash(archive, info):
    archive.fp.seek(body_offset(archive, info))
    remain, h = info.compress_size, hashlib.sha256()
    while remain:
        part = archive.fp.read(min(CHUNK, remain))
        if not part:
            raise ValueError("Truncated compressed member: " + info.filename)
        h.update(part)
        remain -= len(part)
    return h.hexdigest()


def reuse(base_path, target_path, output_path):
    base_path, target_path, output_path = map(Path, (base_path, target_path, output_path))
    if output_path.resolve() in (base_path.resolve(), target_path.resolve()):
        raise ValueError("Output must be a separate candidate file.")
    if output_path.exists():
        raise ValueError("Candidate already exists; choose a new path.")
    report = {"base": str(base_path), "target": str(target_path), "output": str(output_path),
              "reused_members": 0, "new_members": 0, "reused_compressed_bytes": 0,
              "new_compressed_bytes": 0, "entries": []}
    with zipfile.ZipFile(base_path) as base, zipfile.ZipFile(target_path) as target:
        bases, targets = base.infolist(), target.infolist()
        if len({i.filename for i in bases}) != len(bases) or len({i.filename for i in targets}) != len(targets):
            raise ValueError("Duplicate ZIP member names are not supported.")
        by_content, base_raw = {}, {}
        for info in bases:
            key = (member_hash(base, info), info.file_size, info.CRC, info.compress_type)
            by_content.setdefault(key, []).append(info)
            base_raw[info.filename] = body_hash(base, info)
        target_digests = {}
        with zipfile.ZipFile(output_path, "x", allowZip64=True) as output:
            output.comment = target.comment
            for wanted in targets:
                if wanted.flag_bits & (1 | 8):
                    raise ValueError("Encrypted or data-descriptor target members are not supported.")
                if wanted.extra:
                    raise ValueError("This exact-metadata builder requires target members without extra fields.")
                digest = member_hash(target, wanted)
                target_digests[wanted.filename] = digest
                key = (digest, wanted.file_size, wanted.CRC, wanted.compress_type)
                candidates = by_content.get(key, [])
                donor = next((i for i in candidates if i.filename == wanted.filename), candidates[0] if candidates else wanted)
                archive = base if candidates else target
                if donor.flag_bits & 1:
                    raise ValueError("Encrypted donor members are not supported.")
                info = copy.copy(wanted)
                info.compress_size = donor.compress_size
                zip64 = info.file_size >= zipfile.ZIP64_LIMIT or info.compress_size >= zipfile.ZIP64_LIMIT
                if zip64:
                    raise ValueError("A member requires ZIP64; exact target metadata must be reconsidered.")
                # Avoid unnecessary ZIP64 headers: forcing them would change the
                # target's extract_version and extra fields (20 -> 45).
                output._writecheck(info)
                output._didModify = True
                output.fp.seek(output.start_dir)
                info.header_offset = output.fp.tell()
                output.fp.write(info.FileHeader(zip64=False))
                archive.fp.seek(body_offset(archive, donor))
                remain = donor.compress_size
                while remain:
                    part = archive.fp.read(min(CHUNK, remain))
                    if not part:
                        raise ValueError("Truncated compressed data: " + donor.filename)
                    output.fp.write(part)
                    remain -= len(part)
                output.start_dir = output.fp.tell()
                output.filelist.append(info)
                output.NameToInfo[info.filename] = info
                reused = archive is base
                report["reused_members" if reused else "new_members"] += 1
                report["reused_compressed_bytes" if reused else "new_compressed_bytes"] += info.compress_size
                report["entries"].append({"filename": info.filename, "donor": "base" if reused else "target",
                                           "donor_member": donor.filename, "sha256": digest,
                                           "compressed_bytes": info.compress_size})
        # Full independent round trip, order and all persisted metadata checks.
        with zipfile.ZipFile(output_path) as candidate:
            if candidate.comment != target.comment or candidate.namelist() != target.namelist():
                raise ValueError("Archive comment or member ordering changed.")
            differences = []
            same_name_bytes, same_name_members = 0, 0
            for wanted, actual in zip(targets, candidate.infolist()):
                for field in META:
                    if getattr(wanted, field) != getattr(actual, field):
                        differences.append((wanted.filename, field, repr(getattr(wanted, field)), repr(getattr(actual, field))))
                if member_hash(candidate, actual) != target_digests[wanted.filename]:
                    raise ValueError("Candidate member content differs from target: " + wanted.filename)
                if base_raw.get(actual.filename) == body_hash(candidate, actual):
                    same_name_bytes += actual.compress_size
                    same_name_members += 1
            if differences:
                raise ValueError("Target metadata differs: " + repr(differences[:10]))
            bad = candidate.testzip()
            if bad:
                raise ValueError("Candidate ZIP integrity failure: " + bad)
            report.update(same_name_reusable_members=same_name_members,
                          same_name_reusable_compressed_bytes=same_name_bytes,
                          same_name_delta_compressed_bytes=sum(i.compress_size for i in candidate.infolist())-same_name_bytes,
                          verified_members=len(candidate.infolist()), metadata_equal=True, integrity="passed")
    with output_path.open("rb") as stream:
        report["sha256"] = checksum(stream)
    report["bytes"] = output_path.stat().st_size
    report["new_compressed_fraction"] = report["new_compressed_bytes"] / report["bytes"]
    evidence = output_path.with_suffix(".json")
    evidence.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report



def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", type=Path, required=True)
    parser.add_argument("--target", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = reuse(args.base, args.target, args.output)
    print(json.dumps({k: v for k, v in report.items() if k != "entries"}, indent=2))


if __name__ == "__main__":
    main()
