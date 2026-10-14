#!/usr/bin/env python3
"""Check prepared-module and direct hosts against independent FASTQ answers.

Run from the project root: python3 tests/run_correctness.py
This is a correctness/host-I/O suite, not a performance benchmark.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import signal
import subprocess
import tempfile
import time
from pathlib import Path

from generate_fixtures import generate, record


def sha256(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--fixtures", type=Path)
    parser.add_argument("--result", type=Path)
    args = parser.parse_args()
    root = args.root.resolve()
    fixtures = args.fixtures or root / "build/test-fixtures"
    result_path = args.result or root / "results/correctness.json"
    manifest_path = fixtures / "manifest.json"
    manifest = (json.loads(manifest_path.read_text(encoding="utf-8"))
                if manifest_path.exists() else generate(fixtures))
    hosts = [root / "build/bwfastq-linux", root / "build/bwfastq-linux-direct"]
    for host in hosts:
        if not host.is_file():
            parser.error(f"missing host: {host}")
    checks: list[dict] = []

    def check(name: str, action, *, host: Path | None = None) -> None:
        try:
            detail = action()
            item = {"name": name, "ok": True}
            if detail is not None:
                item["detail"] = detail
        except Exception as error:
            item = {"name": name, "ok": False,
                    "error": f"{type(error).__name__}: {error}"}
        if host is not None:
            item["host"] = host.name
        checks.append(item)

    def run(host: Path, mode: str, source: str | Path, output: str | Path,
            threads: int = 1, **kwargs) -> subprocess.CompletedProcess:
        process = subprocess.run([str(host), mode, "--input", str(source), "--output", str(output),
                                  "--threads", str(threads)], stderr=subprocess.PIPE,
                                 stdout=kwargs.pop("stdout", subprocess.PIPE),
                                 timeout=30, **kwargs)
        if str(output) != "-" and partials(Path(output)):
            raise AssertionError("completed run left a temporary output file")
        return process

    def partials(output: Path) -> list[Path]:
        return list(output.parent.glob(output.name + ".partial.*"))

    def require_code(process: subprocess.CompletedProcess, code: int) -> None:
        if process.returncode != code:
            raise AssertionError(f"exit {process.returncode}, expected {code}; "
                                 f"stderr={process.stderr[:500]!r}")

    build = root / "build"
    build.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="correctness-", dir=build) as temporary:
        work = Path(temporary)
        counter = 0

        def fresh(label="output") -> Path:
            nonlocal counter
            counter += 1
            return work / f"{counter}-{label}"

        for host in hosts:
            for case in manifest["cases"]:
                for mode in ("stats", "revcomp"):
                    def fixture_check(case=case, mode=mode, host=host, threads=1):
                        output = fresh("result with spaces Δ")
                        process = run(host, mode, fixtures / case["path"], output, threads)
                        require_code(process, 0 if case["valid"] else 2)
                        if case["valid"]:
                            if mode == "stats":
                                actual = json.loads(output.read_text(encoding="ascii"))
                                if actual != case["stats"]:
                                    raise AssertionError(f"stats {actual} != {case['stats']}")
                            elif sha256(output) != case["revcomp_sha256"]:
                                raise AssertionError("reverse complement differs from independent reference")
                        elif output.exists():
                            raise AssertionError("failed run left a partial output file")
                        if output.exists():
                            output.unlink()
                    check(f"fixture/{mode}/threads1/{case['path']}", fixture_check, host=host)
                    # Only rerun representative parallel workloads, not all fixtures.
                    if case["path"] in ("chunk boundaries.fastq", "large single record.fastq",
                                        "maximum line.fastq"):
                        check(f"fixture/{mode}/threads4/{case['path']}",
                              lambda action=fixture_check: action(threads=4), host=host)

            valid = fixtures / "basic.fastq"

            def refuse_overwrite():
                output = fresh()
                sentinel = b"keep existing output unchanged\x00\xff"
                output.write_bytes(sentinel)
                require_code(run(host, "revcomp", valid, output), 3)
                if output.read_bytes() != sentinel:
                    raise AssertionError("existing output was changed")
            check("host/refuse-existing-output", refuse_overwrite, host=host)

            def refuse_in_place():
                before = sha256(valid)
                require_code(run(host, "revcomp", valid, valid), 3)
                if sha256(valid) != before:
                    raise AssertionError("in-place attempt changed input")
            check("host/refuse-input-as-output", refuse_in_place, host=host)

            def refuse_output_symlink():
                target = fresh()
                target.write_bytes(b"target preserved")
                link = fresh()
                link.symlink_to(target)
                require_code(run(host, "stats", valid, link), 3)
                if not link.is_symlink() or target.read_bytes() != b"target preserved":
                    raise AssertionError("existing output symlink or target was changed")
            check("host/refuse-existing-output-symlink", refuse_output_symlink, host=host)

            def refuse_publication_race():
                output = fresh()
                process = subprocess.Popen([str(host), "stats", "--input", "-", "--output", str(output)],
                                           stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                           stderr=subprocess.PIPE)
                sentinel = b"a different writer published this while computation was active"
                try:
                    process.stdin.write(record(b"race", b"ACGT", b"IIII"))
                    process.stdin.flush()
                    deadline = time.monotonic() + 3
                    while not partials(output):
                        if process.poll() is not None or time.monotonic() >= deadline:
                            raise AssertionError("host did not create temporary output")
                        time.sleep(0.01)
                    if output.exists():
                        raise AssertionError("final output became visible before successful completion")
                    output.write_bytes(sentinel)
                    process.stdin.close()
                    code = process.wait(timeout=3)
                    if code != 3:
                        raise AssertionError(f"publication collision exited {code}, expected 3")
                    if output.read_bytes() != sentinel or partials(output):
                        raise AssertionError("publication replaced existing output or left temporary data")
                finally:
                    if process.poll() is None:
                        process.kill()
                        process.wait()
                    if not process.stdin.closed:
                        process.stdin.close()
                    process.stdout.close()
                    process.stderr.close()
            check("host/atomic-publication-refuses-concurrent-output", refuse_publication_race, host=host)

            def missing_input():
                output = fresh()
                require_code(run(host, "stats", work / "missing.fastq", output), 3)
                if output.exists():
                    raise AssertionError("missing input created output")
            check("host/missing-input", missing_input, host=host)

            def directory_input():
                output = fresh()
                require_code(run(host, "stats", work, output), 3)
                if output.exists():
                    raise AssertionError("directory input created output")
            check("host/directory-input", directory_input, host=host)

            def failing_read():
                output = fresh()
                unreadable = fresh()
                # stdin is deliberately a write-only descriptor; read must fail,
                # not turn a host I/O error into a valid empty dataset.
                with unreadable.open("wb") as stream:
                    require_code(run(host, "stats", "-", output, stdin=stream), 3)
                if output.exists():
                    raise AssertionError("read error left a result file")
            check("host/read-error-and-cleanup", failing_read, host=host)

            def failing_write():
                with open("/dev/full", "wb", buffering=0) as full:
                    require_code(run(host, "stats", valid, "-", stdout=full), 3)
            check("host/write-error", failing_write, host=host)

            def pipeline(source: Path, expected_producer: int):
                producer = subprocess.Popen([str(host), "revcomp", "--input", str(source),
                                             "--output", "-", "--threads", "4"],
                                            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                consumer = subprocess.Popen([str(host), "stats", "--input", "-", "--output", "-"],
                                            stdin=producer.stdout, stdout=subprocess.PIPE,
                                            stderr=subprocess.PIPE)
                producer.stdout.close()
                try:
                    stdout, consumer_error = consumer.communicate(timeout=10)
                    producer_error = producer.stderr.read()
                    producer_code = producer.wait(timeout=10)
                finally:
                    for child in (producer, consumer):
                        if child.poll() is None:
                            child.kill()
                            child.wait()
                    producer.stderr.close()
                if producer_code != expected_producer or consumer.returncode != 0:
                    raise AssertionError(f"producer={producer_code} consumer={consumer.returncode}; "
                                         f"errors={producer_error!r} {consumer_error!r}")
                actual = json.loads(stdout)
                if expected_producer == 0:
                    expected = next(c["stats"] for c in manifest["cases"] if c["path"] == "basic.fastq")
                    if actual != expected:
                        raise AssertionError("pipeline statistics differ")
                elif actual["records"] != 1:
                    raise AssertionError("failed producer should have streamed its first complete record")
                return {"producer_exit": producer_code, "consumer_exit": consumer.returncode,
                        "pipeline_success": producer_code == consumer.returncode == 0}
            check("pipeline/revcomp-to-stats", lambda: pipeline(valid, 0), host=host)
            check("pipeline/detect-failed-producer-even-if-consumer-succeeds",
                  lambda: pipeline(fixtures / "invalid/second record truncated.fastq", 2), host=host)

            def cancellation():
                output = fresh()
                process = subprocess.Popen([str(host), "revcomp", "--input", "-", "--output", str(output)],
                                           stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                           stderr=subprocess.PIPE)
                try:
                    process.stdin.write(record(b"waiting", b"ACGT", b"IIII"))
                    process.stdin.flush()
                    deadline = time.monotonic() + 3
                    while not any(path.stat().st_size > 0 for path in partials(output)):
                        if process.poll() is not None or time.monotonic() >= deadline:
                            raise AssertionError("host did not reach blocked-read cancellation checkpoint")
                        time.sleep(0.01)
                    if output.exists():
                        raise AssertionError("final output visible before completion")
                    process.send_signal(signal.SIGINT)
                    code = process.wait(timeout=3)
                    if code != 130:
                        raise AssertionError(f"cancelled process exited {code}, expected 130")
                    if output.exists() or partials(output):
                        raise AssertionError("cancelled run left partial output")
                finally:
                    if process.poll() is None:
                        process.kill()
                        process.wait()
                    process.stdin.close()
                    process.stdout.close()
                    process.stderr.close()
                return {"signal": "SIGINT", "exit": code, "deadline_seconds": 3,
                        "checkpoint": "blocked stdin read after one output record"}
            check("host/cancellation-is-bounded-and-cleans-output", cancellation, host=host)

            def double_reverse():
                rng = random.Random(0xB10F457)
                source = fresh("random reads Δ.fastq")
                expected = bytearray()
                payload = bytearray()
                lengths = [0, 1, 2, 3, 7, 31, 32, 33, 255, 256, 257, 4095, 4096, 4097, 65537]
                for index, length in enumerate(lengths):
                    sequence = bytes(rng.choice(b"ACGTNacgtn") for _ in range(length))
                    quality = bytes(rng.randrange(33, 127) for _ in range(length))
                    name = f"deterministic-{index}".encode()
                    payload.extend(record(name, sequence, quality,
                                          newline=b"\r\n" if index % 2 else b"\n",
                                          final_newline=index != len(lengths) - 1))
                    expected.extend(record(name, sequence, quality))
                source.write_bytes(payload)
                first, second = fresh(), fresh()
                require_code(run(host, "revcomp", source, first, 4), 0)
                require_code(run(host, "revcomp", first, second, 4), 0)
                if second.read_bytes() != bytes(expected):
                    raise AssertionError("double reverse complement differs from LF-normalized original")
                if source.read_bytes() != bytes(payload):
                    raise AssertionError("source was modified")
            check("property/double-revcomp-normalizes-and-preserves-input", double_reverse, host=host)

            def invalid_threads():
                for threads in (0, 65):
                    output = fresh()
                    require_code(run(host, "stats", valid, output, threads), 4)
                    if output.exists():
                        raise AssertionError("invalid option created output")
            check("host/invalid-thread-count", invalid_threads, host=host)

        def unchanged_inputs():
            for case in manifest["cases"]:
                if sha256(fixtures / case["path"]) != case["sha256"]:
                    raise AssertionError(f"input changed: {case['path']}")
        check("all-fixture-inputs-unchanged", unchanged_inputs)

    passed = sum(item["ok"] for item in checks)
    report = {
        "schema": 1,
        "scope": "Linux prepared-module and direct hosts; not native Windows execution or performance",
        "suite": "restricted-four-line-fastq",
        "fixture_count": len(manifest["cases"]),
        "hosts": [{"name": host.name, "sha256": sha256(host)} for host in hosts],
        "module_sha256": sha256(root / "build/fastq.module"),
        "checks": len(checks), "passed": passed, "failed": len(checks) - passed,
        "results": checks,
    }
    result_path.parent.mkdir(parents=True, exist_ok=True)
    result_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({"checks": len(checks), "passed": passed, "failed": len(checks) - passed,
                      "result": str(result_path)}))
    for item in checks:
        if not item["ok"]:
            print(json.dumps(item, ensure_ascii=False))
    return int(passed != len(checks))


if __name__ == "__main__":
    raise SystemExit(main())
