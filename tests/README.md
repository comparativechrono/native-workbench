# Tests

Headless checks of the workbench in Chromium (Playwright). They need Node.js 18 or later and Python 3 (for
`serve.py`).

```
cd tests
npm install                     # Playwright
npx playwright install chromium # once: the browser it drives
```

## The execution-backend boundary

See `docs/execution-backends.md` for what these check.

```
node boundary-lint.mjs          # no code outside the backends reaches the programs or their bytes directly
node contract.mjs               # MG.exec and the local backend's connection (no runner, a runner that cannot give its
                                # files, a wrong token, another protocol version)
```

## The parity suite

The same commands, run in the real terminal (`MG.app.term.exec`, as if typed), before and after a change. Each
step's exit status, output and messages are recorded, and so are the kind, size, permissions and a hash of the bytes
of every file in the home folder. The commands are in `suite.mjs`; together they take about a minute and a half.

```
# the version before the change, twice (what differs between the two runs varies by itself: times, durations)
git worktree add ../../wb-before main
node run-suite.mjs --root ../../wb-before --out results/before-1.json
node run-suite.mjs --root ../../wb-before --out results/before-2.json

# the version after it – and the same with every handle replaced by a meaningless token
node run-suite.mjs --root .. --out results/after.json
node run-suite.mjs --root .. --init opaque-backend.js --out results/after-opaque.json

node compare.mjs results/before-1.json results/before-2.json results/after.json
node compare.mjs results/before-1.json results/before-2.json results/after-opaque.json
```

`compare.mjs` exits with status 1 and lists every difference. Where the two runs of the version before the change
already differ, the output is compared with its digits masked, and a file by its kind and permissions only. Files
that carry the time of the run are named in `suite.mjs` (`timeStamped`) and always compared that way – Strelka2's
VCF files (a `##startTime` header line, compressed) and its `runStats.tsv` (the wall-clock time) – and the step that
makes them prints what else is in them (a checksum of the VCF records without that line; the statistics without the
time), so that their content is still compared exactly.

### The local runner against the browser

The same suite, with the programs in the local runner (a new, empty workspace): `--runner`. `--subset local` leaves
out the steps whose programs are not in the runner yet (those with a worker of their own: `own` in `suite.mjs`) and
the forced stop of every program, which loses nothing with the runner (`allPrograms`). The kind of a program-written
entry (`aioli` or `local`) is compared as the same.

```
node run-suite.mjs --root .. --subset local --out results/browser-1.json
node run-suite.mjs --root .. --subset local --out results/browser-2.json
node run-suite.mjs --root .. --subset local --runner --out results/local.json
node compare.mjs results/browser-1.json results/browser-2.json results/local.json
```

## The local runner

```
node local-runner.mjs           # files already in the folder (and behind a link), what programs and the page write,
                                # a reload, a run that goes on through a reload, a forced stop, and the runner's safety
```

## The SAMtools prototype

The review's first prototype (`docs/execution-backends.md`): from the page, with the runner, SAMtools sorts a BAM file
larger than the 2 GiB a program may have; the result is compared with native SAMtools 1.17's, and what it takes is
measured. It needs about three times the input's size free on the disk (input, temporary files, output; and the
native sort's), a native `samtools` 1.17 for the comparison (`--native`; without it the comparison is left out), and
Linux (it reads the memory of the processes in `/proc`).

```
node prototype/make-unsorted-sam.mjs --reads 60000000 | samtools view -b -o /data/unsorted.bam -     # 5.0 GiB
node prototype/sort-big-bam.mjs --bam /data/unsorted.bam --workspace /data/ws --native samtools \
    --out results/prototype-sort.json
```
