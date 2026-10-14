# The local runner

The workbench's programs, run on this computer, with the files of an analysis in a folder on disk. The page is the
same workbench; only where its programs run, and where their files are, changes. Neither the size of a file nor the
memory of a browser tab limits an analysis any more: a program reads and writes the files on disk, a block at a time,
and the page never holds their bytes.

```
node runner/runner.mjs --workspace ~/my-analysis
```

It prints an address – open it in a browser:

```
The workbench's local runner 0.1.0 (Node 22.22.0)
  your files (~ in the terminal): /home/me/my-analysis
  open: http://127.0.0.1:8780/?backend=local#runner-token=…
```

Node.js 18 or later; nothing to install (no packages). The runner serves the workbench from the checkout it is part of.

| Option | |
| --- | --- |
| `--workspace FOLDER` | the folder of the analysis: the terminal's home folder (`~`). It is made if it is not there. Default `~/workbench`. It may not be inside the workbench's own folder. |
| `--port N` | default 8780 |
| `--token KEY` | the key of the session (or `WORKBENCH_RUNNER_TOKEN`); by default a new random one each time |

## What it does

- **The folder is `~`.** What is in it when the runner starts is in the terminal and the Files tab: small text files
  as text, everything else as a name and a size (the bytes stay on disk). A symbolic link to data kept elsewhere –
  a disk of sequencing runs – is followed. What the programs write is written there; what the page changes itself
  (`echo … >`, `mv`, `rm`, the editor) is written there within a moment. Reload the page, or start the runner again
  tomorrow: the files are where they were.
- **The programs** are the same WebAssembly builds as in the browser (`assets/vendor/biowasm`), run under Node.js. Each
  run is a worker thread of its own with a fresh instance of the program (as a process is on Linux), and its file
  system is the disk (`diskfs.mjs`, mounted by `tool-host.mjs`): no copy of a file is made in memory. The terminal
  behaves as it does in the browser – the page's shell drives the runner exactly as it drives the programs in the
  page (`assets/js/exec-engine.js`), and the parity suite checks that the results are the same.
- **One program at a time.** A run goes on when the page is closed or reloaded; the page says so when it comes back,
  and takes the files when the run ends. Every run is written to `.workbench/runs.jsonl` (the command, exit status,
  time, the program's WebAssembly memory, the runner's peak memory).
- **Its own things** are in `.workbench/` in the folder, which the page does not show: the page's `/tmp` and
  `/galaxy`, the pipes between programs, the AI agent's copies, the log.
- **The page adds little to the folder.** A new, empty folder gets the starter notebooks (`notebooks/`), as a first
  visit does in the browser; a folder with files in it gets none. If there is no notebook in the folder at all, the
  Notebook tab makes `notebooks/Untitled.ipynb` (it always has one open).

### Where the programs' paths are on disk

| The programs' path | On disk |
| --- | --- |
| `/home/user` (`~`) | the folder (`--workspace`), without `.workbench` |
| `/data/examples` | the workbench's example data – **read-only** |
| `/tmp`, `/galaxy` | `.workbench/tmp`, `.workbench/galaxy` |
| `/data` (the rest) | `.workbench/root/data` (as in the page: what a program puts there is removed again, and the terminal says so) |
| anything else | `.workbench/root`, `.workbench/top` |

## Safety

The runner can read and write the files of one folder, and run the workbench's own programs; it is reached by one
page.

- It listens on `127.0.0.1` only – not on the network.
- Every request about files or programs needs the key of the session (`Authorization: Bearer KEY`). The key is in the
  address the runner prints, after `#` (a browser does not send that part to any server); the page keeps it for that
  tab only and takes it out of the address.
- It answers only requests addressed to `127.0.0.1:PORT` or `localhost:PORT` (another name that points to this
  computer – DNS rebinding – is refused), and refuses requests that another web page sends (`Origin`).
- A path is always resolved within the folders above; `..` cannot leave them, and `.workbench` is not reachable from
  the page.
- It runs only the programs in `assets/vendor/biowasm`, by name and version.
- Anyone who can run programs as you on this computer can already read your files; the key keeps out web pages, not
  people with an account on the machine.

## Limits of this version

- **The programs that run in a worker of their own in the browser** – featureCounts, Salmon, PLINK 2, Cutadapt,
  MACS3, LoFreq, SomaticSniper, Strelka2, Kraken2, Bracken, Prodigal, HMMER, bustools – are not in the runner yet. The
  terminal says so; open the workbench without `?backend=local` to use them.
- **2 GiB of memory per program, one thread**: the builds are those of the browser (32-bit WebAssembly). A sort, an
  index or a pile-up of a large file needs little memory; a program that must hold its whole input (an assembler, a
  large index build) does not fit yet. 64-bit builds are the review's step 5.
- **One page at a time** per runner, and one program at a time.
- **Stopping a program** (Ctrl+C twice, Stop) ends that program only; its files stay as it left them – nothing else is
  lost (in the browser a forced stop can lose the files the programs held).
- **The example data is read-only on disk**: a program that tries to write there is told "Permission denied" by the
  system (in the browser the change is undone after the program has run).
- **Notebooks, viewers and downloads** read a file of the folder whole, through the page: use the terminal for large
  files (step 6 of the review gives them ranged reads).

## The protocol (version 1)

Every request but the site's files needs the key; JSON in and out. Paths are the programs' paths (`/shared/vfs/…`,
see `ROOT` in `exec-engine.js`).

| Request | Answer |
| --- | --- |
| `GET /api/v1/hello` | `{ protocol: 1, runner, version, node, workspace: { root }, busy, last }` |
| `GET /api/v1/run` | `{ busy: { id, program, args, started } \| null, last }` – the run in progress, and the last one |
| `POST /api/v1/exec` `{ spec: [tool, version, program], args, io, cwd }` | when the program has ended: `{ ok: { code, error, stdinPos, stdinMax, order, memory, secs } }`. `io`: `{ stdin, stdout, stderr, merge, links, lines, fifo, env, zone, zoneName }`, as execIO takes them in the page |
| `POST /api/v1/kill` | stops the program that is running |
| `POST /api/v1/fs` `{ op, … }` | `lstat`, `readdir`, `mkdir`, `unlink`, `rmdir`, `chmod`, `utime`, `rename`, `copy` (on disk: a clone where the file system can), `redirect` (what a program printed becomes a file, or is added to one), `tree` (every file below a folder: path, size, time), `peek` (the first and last megabytes of a long output, for the screen), `readSmall` (the text of small text files) |
| `GET /api/v1/file?path=P` (and `HEAD`) | the bytes of a file, with `Range` |
| `PUT /api/v1/file?path=P` | the body becomes the file (written to a file of its own first, then renamed) |

`GET /…` anything else: the workbench itself, with the headers of cross-origin isolation.
