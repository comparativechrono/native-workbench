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
node contract.mjs               # MG.exec and the local backend's connection (no runner, a mock runner, a wrong token)
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
