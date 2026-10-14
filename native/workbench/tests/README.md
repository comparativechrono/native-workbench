# Independent FASTQ fixtures

Generate test inputs and a JSON manifest with independently calculated answers:

```sh
python3 tests/generate_fixtures.py build/test-fixtures
python3 tests/reference_fastq.py build/test-fixtures/basic.fastq
python3 tests/reference_fastq.py build/test-fixtures/basic.fastq --revcomp-output build/reference.fastq
python3 tests/run_correctness.py
```

The oracle uses Python's binary line reader rather than the native module's
chunk parser. Each valid fixture also has an answer calculated explicitly or
from pattern arithmetic. Generation verifies the oracle agrees with those
answers; expected results are not obtained just by running the implementation
being tested.

## Restricted format contract

- Exactly four lines per record, with LF or CRLF line endings.
- The final nonempty quality line may end at EOF without a newline.
- Header starts with `@`; the next byte must be printable, nonspace ASCII. The
  remainder contains printable ASCII (spaces allowed).
- Sequence contains only `ACGTNacgtn`; a zero-length sequence is accepted.
- Separator starts with `+` and contains printable ASCII. Optional text does not
  have to match the header.
- Quality contains exactly as many bytes as sequence, all in `[33,126]`.
- An empty read still requires an explicit fourth, blank quality line.
- Empty files are valid. Blank lines between/after records are not ignored.
- Raw carriage returns inside lines are invalid. Only CRLF is normalized.
- GC/N counts ignore case. Phred sum is the sum of `quality_byte - 33`.
- Minimum and maximum read lengths are zero for empty input.
- Each logical line is at most 16 MiB, excluding its LF/CRLF ending.
- Reverse complement preserves base case and header/plus text, reverses quality
  bytes, and writes LF after every line.

This intentionally does not accept every FASTQ dialect (such as wrapped records
or other IUPAC sequence symbols). These are format limitations of the prototype,
not claims that such datasets are invalid in general.

`manifest.json` contains relative paths, byte counts, SHA-256 checksums, validity,
and either exact aggregate statistics or an error category. Valid cases also
identify an independently generated reverse-complement file and its checksum.
Error strings and
error-priority ordering need not match a native implementation. Invalid input
must fail; any partial statistics must not be presented as a successful result.

Large-record and boundary fixtures are generated on demand rather than stored
in source control. The generator only creates test data; it does not stage any
user input. A 3-million-base single record checks that the native parser is not
limited to a small fixed line buffer. Unicode/space filenames exercise the host
path adapter separately from the FASTQ byte format.

The exact-16-MiB and over-limit cases require roughly 100 MiB of generated test
files in total (including reference reverse-complement output). They are boundary
tests, not representative sequencing data or a performance benchmark.

The correctness runner compares both Linux entry paths (embedded prepared module
and directly linked computation) with the independent answers. It checks all
fixtures in both modes, representative workloads with four threads, cancellation
while blocked on input, output cleanup, read/write failures, overwrite refusal,
pipelines, unchanged input bytes, and deterministic double reverse complement.
Pipeline checks inspect both processes: a downstream command can succeed after
an upstream command emitted a valid prefix and then failed. The report is written
to `results/correctness.json`. These tests do not claim native Windows execution.
