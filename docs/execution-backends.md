# Execution backends

These are steps 1 and 2 of the plan in the memory review of 13 October 2026, and phase 1 of the roadmap that
followed it (native programs in the local runner).

- **Step 1, an execution-backend boundary.** Every part of the workbench that runs a program, or touches the bytes
  that programs read and write, does so through one object, `MG.exec` (`assets/js/exec.js`).
- **Step 2, a local runner that owns an on-disk workspace.** Behind that object, the programs can run on the user's
  own computer, in a companion program (`runner/`), with the files of an analysis in a folder on disk. The page never
  holds their bytes, so a file can be larger than a browser tab's memory. The first proof is the review's prototype.
  From the page, SAMtools sorted a 5 GiB BAM file (18.8 GiB of records) in 380 MiB of memory. That is more than twice
  the 2 GiB a program may have, and nine times as much uncompressed. The result is the same as native SAMtools'
  (see below).
- **Phase 1, native programs in the local runner.** Where `native/bin` has a program built for the computer itself,
  the runner runs that one in place of the WebAssembly build: SAMtools, BCFtools, bgzip, tabix, minimap2, BWA,
  FreeBayes, fastp and seqtk, as Cosmopolitan executables that run on Windows, Linux and macOS (see
  [Native programs](#native-programs-in-the-local-runner) below).

| Backend | Files | Status |
| --- | --- | --- |
| `browser` | `assets/js/exec-browser.js` | The default. The programs run in the page, compiled to WebAssembly, exactly as before. |
| `local` | `assets/js/exec-local.js`, `runner/` | The programs run on this computer, in the local runner, with their files in a folder on disk. Every program of the Biowasm builds (SAMtools, BCFtools, minimap2, BWA, HISAT2, …, the GNU tools) – nine of them as native programs; not yet the programs with a worker of their own (below). |

`tools-wasm.js` holds only the terminal's commands for the programs (the wrappers, the options these builds cannot
take, gzip, grep -P, where a program's output goes). It reaches the programs through `MG.exec` alone.

## One engine, two machines

The browser backend was a single object: Aioli (the programs, in a worker of the page) and everything the page does
around a run, which makes the programs behave as they do on Linux. That second part is the larger one. It decides
which arguments are paths, provides `/dev/stdin`, the environment and the time zone, and tracks how far a program
read a pipe and in which order it wrote its output and its messages. It also makes the page's files the same as the
programs' before a run, takes in what the program changed afterwards, and gives copies and moves bytes of their own.
In step 2 it moved into a shared **engine** (`assets/js/exec-engine.js`), its behaviour unchanged. A backend is now
the engine and a **machine**:

| Machine | File | What it is |
| --- | --- | --- |
| browser | `exec-browser.js` | Aioli in the page, and the programs with a worker of their own (featureCounts, Salmon, HMMER …) |
| local | `exec-local.js` | the runner's folder on disk, reached over HTTP (`RemoteCli`): every call of the programs' file system is a request |

A machine has `id`, `label`, `entryKind`, `capabilities`, `needsIsolation`, `start(status, specs)` (which returns the
programs' file system, `cli`), `ownWorker`/`execWorker` (programs that do not run through `cli.execIO`) and `kill`.
`cli` has Aioli's calls: `fs.{readFile, writeFile, lstat, readdir, unlink, rmdir, chmod, utime}`, `mkdir`, `cd`,
`statTree`, `execIO`. A machine whose files can be larger than the page should hold sets `keepsBytes: true`. It then
also has `fs.copyFile`, `fs.rename`, `fs.redirect`, `fs.readTextBounded`, `fs.readSmall` and `siteFile`. The engine
then does copies, moves, the AI agent's copies and redirections (`> FILE`) on the machine's side. Of a long output it
fetches only the first 8 MiB and the last 2 MiB, for the screen (the terminal shows the first 2,000 lines and the
last 1,000 anyway).

Because both backends are the same engine, the local backend inherits every behaviour of the terminal. The parity
suite checks this: its 51 steps for the programs the runner has give the same results, file for file and byte for
byte, in local mode as in the browser.

## Where things live

- **The page** keeps the names of the files (`vfs.js`): folders, sizes, times, permissions, and the text of small
  text files. The shell, the editor, the file panel and globbing all work on these names, synchronously.
- **The backend** keeps the bytes of the files that programs write (BAM, `.gz`, anything over 256 KiB or not UTF-8
  text). The page's entry for such a file has the backend's `entryKind`: `aioli` in the browser, `local` with the
  runner. The page reads it only through `MG.exec.entryText` / `entryBytes`.
- **Handles** (`MG.FileRef`) carry bytes that the backend keeps between commands: what a program printed, the bytes of
  a pipe, a file given with `< FILE`, a temporary file. A handle means something only to the backend that made it.
  Code outside a backend never looks inside one; it hands the `FileRef` back to `MG.exec`, and asks
  `MG.exec.argPath(ref)` for the name to give a program as an argument.
- **With the local runner, the folder on disk is the work.** When the page starts, it takes its files from the folder
  (`MG.exec.restore`). It does not use the browser's own storage (`project.js`) for them. What the page changes itself
  (`echo … > f`, `mv`, `rm`, the editor) is written to the folder within a moment (`MG.exec.watch`). What a program
  writes is there already.

## Choosing a backend

- The browser backend is used unless another is asked for.
- `?backend=local` in the address, or `backend: 'local'` in `config.js`, asks for the local backend. The local
  runner serves the workbench itself, so the page asks for it at its own address (`GET /api/v1/hello`). Until the
  runner has answered, every program waits; this takes a few milliseconds and at most four seconds.
- If no runner answers, or it refuses the page, or it speaks another version of the protocol, or the files of its
  folder cannot be read, the page uses the browser backend and the terminal says why, once.
- When the runner is used, the terminal says so, names the folder, and says which programs are not in the runner yet.
- One backend is active in a page. `MG.exec.use(id)` switches, but only before any program has run.
- An entry is always read by the backend that holds it, whichever backend is active.

## The contract

`exec.js` checks every backend against this list when it is registered, and refuses one that lacks a member.
Optional members have defaults in the facade.

### Identity

| Member | What it is |
| --- | --- |
| `id` | `'browser'`, `'local'`, … |
| `label` | How the page names it to a person (“this browser tab”, “the local runner (NAME VERSION)”). |
| `entryKind` | The `kind` of the page's file entries whose bytes it holds. |
| `versions` | Program → version, for the programs it runs (`--version` texts, the AI assistant's prompt). |
| `ready` | It has started (`ensure`) and has not been stopped since. |
| `running` | The name of the program that is running, or `null` (the terminal's Stop button asks). |
| `capabilities` *(optional)* | `{ where: 'browser' \| 'local', persistentFiles, threads }`. |

### Programs

| Member | What it must do |
| --- | --- |
| `ensure(status)` | Start, if it has not started. `status(text)` may report progress. |
| `run(ctx, program, args, opts)` | Run one program to its end and return a **RunResult** (below). Programs run one at a time. |
| `kill(fs)` | Stop the running program by force. Return the paths of the page's files whose bytes were lost with it. Set `lastKill` to `'threads'` (only that program stopped) or `'runner'` (every program, and the files they held); after a `'runner'` stop, increase `gen` and fill `lostTimes` and `lostEntries`. |
| `needsIsolation(program)` | True when the program cannot run in this page as it is: in the browser, the programs that start threads need a cross-origin isolated page. |
| `tidy(text, name)` | What a program printed, with paths as the person knows them (`/shared/vfs` removed). |

**RunResult**: `{ code, statusKnown, stdout, stderr, parts, tail, out, stdoutSize, created, secs, stdinUsed }`.
`out` is a handle to everything the program printed. `stdout` is that output as text. It is empty when
`opts.binaryOut`, or when `opts.textOut` is `false`: the output then goes into a file or on into a pipe, by its
handle. With the local runner it is the first 8 MiB and the last 2 MiB of a longer output. `parts` gives stdout and
stderr in the order the program wrote them (`[1|2, bytes]` pairs), when known. `tail` is what the backend adds after
the program's messages (for instance, that a change to the example data was undone). `created` lists the files the
program made. `stdinUsed` says how far the program read a piped input.

**What `run` may read from `ctx`**: `fs` (the shell's view of the page's files), `name`, `stdin` (text or a
handle), `inherit` (the input stream of the block the command stands in: `{ text, pos, pipe, path, handle }`; the run
moves `pos` on by what the program read), `mergeStderr`, `hereInput`, `env` and `opts.st` (the variables the shell
exports), `shell.oldpwd`, `io` (notes, and the workflows' messages) and `term.statusEl`. It must not write to `ctx`.

**After `run`, the page's files must show what the program did**: new and changed files (small UTF-8 text files as
`text` entries, the rest as the backend's `entryKind`), removed files, new folders, and the times of the files. The
rules of the page apply: nothing new in the example data (`fs.refusesNew`: the file is removed again and the run
says so), the example data's files are not changed (`protected`), a file that a program renamed keeps its
permissions.

**Workflows** (`lofreq somatic`, Strelka2's `runWorkflow.py`, Kraken2's and Bracken's scripts in `somatic.js` and
`metagenomics.js`) are run by the backend. It calls the workflow with a helper `h`: `spawn(T, opts)` runs one program
of the workflow, and `inputsOf`, `readText`, `isFile`, `isDir`, `abs`, `stage` and `pretty` reach its files. A program is described
by `T = { name, module, worker?, pyodide? }`, where `module` names the build (relative to `threadsBase`) and `worker`
says that a Python host is needed. A local backend that provides the same `h` runs these workflows unchanged.

### Handles

| Member | What it must do |
| --- | --- |
| `readText(ref)`, `readBytes(ref)`, `sizeOf(ref)` | The bytes of a handle. |
| `tempBytes(bytes, binary)` | Keep bytes for the next command of a pipe; return a handle. |
| `tempFile()` | A handle to a file that a program can be told to write (via `argPath`); empty until it is written. |
| `discard(ref)` | The bytes of a temporary file are no longer needed. |
| `argPath(ref)` | The name to give a program for the file of a handle, as an argument (`hisat2` gets its unpacked reads that way, `tee /dev/stdout` its copy). |
| `hold(ref)`, `release(ref)` | Keep a handle's bytes until released (the input of a block or a script whose commands have not all run). |
| `inputRef(fs, abs)` | A handle to the file at `abs` for `< FILE`, with `fromFile = true` and `path = abs`: a program may go back in it. Copies and moves must be settled first (see `settle`). |

### The bytes of the page's files

| Member | What it must do |
| --- | --- |
| `holds(entry)` | True when the bytes of this entry are this backend's. |
| `entryText(entry)`, `entryBytes(entry)` | The bytes of such an entry (the editor, the viewers, downloads, notebooks, the shell's own commands). |
| `writeBytes(fs, abs, bytes)` | Bytes in hand become the file at `abs` (a block's binary output written with `>`, `split`, `truncate`, `gunzip` of an odd suffix). |
| `writeOutput(fs, abs, ref, { tail, append })` | What a program printed becomes the file at `abs`, or is added to its end. Return `false` and leave the file as it is when nothing was printed. In the browser this copies the bytes; the local runner moves or appends them on disk. |
| `settle(fs)` | `cp` and `mv` change only names in the page; before a program reads, each copied or moved file must get bytes of its own (with the runner: a copy or a rename on disk). |

### A backend whose files stay (optional)

| Member | Default | What it must do |
| --- | --- | --- |
| `restore(fs, roots)` | nothing | When the page starts: the files below `roots` (the home folder, `/galaxy`) become the page's (small text files as text, the rest as the backend's entries). Used when `capabilities.persistentFiles`. |
| `watch(fs)` | nothing | From then on, what the page changes goes to the backend's files soon after. |

### The AI agent (optional)

| Member | Default | What it must do |
| --- | --- | --- |
| `keep(list)` | keeps nothing | Before an agent's command: copy the given held files, so that they can be put back. |
| `putBack(abs, entry, since)` | `false` | After the command: the file is as it was before. |
| `dropKept()` | nothing | The agent has finished: the copies go. |
| `gen`, `lastKill`, `lostTimes`, `lostEntries` | `0`, `''`, empty | See `kill`. |

## The local runner

`runner/README.md` describes how to start it, what it does and its safety. In short:

```
node runner/runner.mjs --workspace ~/my-analysis     # then open the address it prints
```

- Node.js 18 or later, no packages. It serves the workbench at `http://127.0.0.1:PORT/` with the headers of
  cross-origin isolation. The address it prints carries the key of the session (`#runner-token=…`).
- **The programs are the browser's builds**, run under Node.js. The Biowasm builds were made for web pages
  (`ENVIRONMENT=web,worker`) and have no Node file system in them. The runner gives them one: `runner/diskfs.mjs` is
  an Emscripten file system whose files are the files on disk. A program reads and writes the real file, block by
  block; nothing is copied into its memory. `runner/tool-host.mjs` runs one program in a worker thread, in a fresh
  instance, as Aioli's `execIO` does in the page. It handles the descriptors 0–2 bound to files, the order of the
  output, line-at-a-time input, the environment and the time zone. No program was rebuilt.
- **The folder is `~`**; the example data is mounted read-only; the runner's own things (the page's `/tmp`, the pipes,
  the agent's copies, the log of runs) are in `.workbench/` inside the folder, hidden from the page.
- **One program at a time; a run goes on when the page is closed or reloaded.** When the page comes back it says so,
  and takes the run's files when it ends.

### What is different from the browser

| | Browser | Local runner |
| --- | --- | --- |
| Where the files are | in the browser's memory (kept in its storage between visits) | in a folder on disk |
| Largest file | what a browser tab can hold, in all | what the disk can hold |
| The programs | WebAssembly builds | the nine native programs of `native/bin` (newer versions: see [Native programs](#native-programs-in-the-local-runner)); the rest the same WebAssembly builds |
| A program's memory | 2 GiB (32-bit WebAssembly) | the computer's, for a native program; 2 GiB for a WebAssembly build |
| Threads | featureCounts, Salmon …; the Biowasm programs run on one | minimap2, BWA and fastp natively; one for the HTSlib programs and the WebAssembly builds |
| Forced stop | can lose the files the programs held (the terminal lists them) | only the program stops; nothing is lost |
| Writing into the example data | undone after the run, with a message | a WebAssembly build: refused ("Permission denied"); a native program: undone in its copy after the run, with the browser's message |
| featureCounts, Salmon, PLINK 2, Cutadapt, MACS3, LoFreq, SomaticSniper, Strelka2, Kraken2, Bracken, Prodigal, HMMER, bustools | yes | not yet: the terminal says so |
| Pages | any number of tabs | one page per runner |

Notebooks, viewers and downloads still read a file whole, through the page. With the runner, large files are for
the terminal until step 6.

### The protocol (version 1)

| Request | For |
| --- | --- |
| `GET /api/v1/hello` | `connect`: `{ protocol, runner, version, node, workspace: { root }, busy, last, programs, native }` (`programs`: the native ones, name → `{ tool, version, threads }`) |
| `GET /api/v1/run` | a run that went on while the page was away: `{ busy, last }` |
| `POST /api/v1/exec` | `cli.execIO`: `{ spec: [tool, version, program], args, io, cwd }` → when it has ended, `{ code, error, stdinPos, stdinMax, order, memory, secs }`; a native program's also `native`, `refused`, `denied` |
| `POST /api/v1/kill` | `kill` |
| `POST /api/v1/fs` | `cli.fs` and `statTree`: `{ op: lstat \| readdir \| mkdir \| unlink \| rmdir \| chmod \| utime \| rename \| copy \| redirect \| tree \| peek \| readSmall, … }` |
| `GET`/`HEAD /api/v1/file?path=P` | `cli.fs.readFile` (with `Range`, for viewers later) |
| `PUT /api/v1/file?path=P` | `cli.fs.writeFile` |

The draft of step 1 proposed jobs with their own handles (`POST /api/v1/jobs`). Step 2 took the simpler route: the
engine's calls, one request each, with paths of the programs' file system. Jobs as objects, with their state on disk
and a process each, are step 4.

## The SAMtools prototype

The review's first prototype: from the page, with the local runner, `samtools sort` of a BAM file substantially
larger than the 2 GiB a program may have, with the sort's memory bounded and its temporary files on disk. The page
must hold none of the data, and the result must survive a reload of the page. The result must be the same as that of
native SAMtools of the same version, under defined rules. `tests/prototype/sort-big-bam.mjs` does all of this and
measures it; `tests/prototype/make-unsorted-sam.mjs` makes the input.

### The result (14 October 2026)

`samtools sort -m 256M -o sorted.bam unsorted.bam`, typed into the workbench's terminal, with the local runner:

| | |
| --- | --- |
| Input | `unsorted.bam`, **5.01 GiB** (5,376,906,970 bytes): 60,000,000 reads of 150 bases in the order an aligner writes them, **18.79 GiB of BAM records** uncompressed (25.2 GB as SAM). It was made by `make-unsorted-sam.mjs --reads 60000000 --seed 1` and native `samtools view -b`. |
| Output | `sorted.bam`, 3.63 GiB, sorted by coordinate |
| Wall time | **1,776 s** (29.6 min). Native SAMtools 1.17 with the same options (one thread, `-m 256M`) took 1,297 s, so the WebAssembly build took 1.37× as long. |
| Memory of the program | **379.7 MiB** of WebAssembly memory, out of the 2 GiB this build can grow to |
| Peak resident memory | the runner's process (Node.js, the program and its memory): 461.6 MiB; native samtools: 364.6 MiB |
| The browser | JavaScript heap: 5.2 MiB before the sort, **5.8 MiB at most** during it. Its processes held 488 MiB before and 808 MiB at most, then about 760 MiB for the rest of the half hour. That rise was the page's own start: the sort began a second after the page had loaded, and the same page with no command at all reaches 782 MiB in the same seconds. |
| Between page and runner, during the sort | **16 requests: 1.3 KiB sent, 49.6 KiB received** (the listings of the files before and after the run) |
| Temporary files | 5.85 GiB at most, up to 36 at once (`sorted.bam.tmp.NNNN.bam` next to the output). samtools merges them as it goes and removes them at the end. |
| Disk | input, temporary files and output together: 13.59 GiB at most |
| Then | `samtools index sorted.bam`: 101 s, 27.8 MiB of memory. `samtools idxstats` and the count of a region (`chr21:20000000-30000000`: 138,146 reads) answered at once. |
| A reload of the page | the page found `unsorted.bam`, `sorted.bam` and `sorted.bam.bai` again (0.9 s), still on disk, and samtools read them |

**The same result as native SAMtools 1.17.** The native build sorted the same file with the same options. The rules
of equivalence, all met:

- the header is the same, but for its `@PG` lines, which name the command and its paths;
- the records are the same, in the same order: `samtools view` of both files, 23.46 GiB of SAM, has the same SHA-256;
- `samtools quickcheck` passes; `idxstats` are the same; the count of a region is the same, before and after the reload.

Beyond these rules, after the header the two files are **byte for byte the same** (3,899,605,701 bytes of BGZF
blocks): the WebAssembly build compresses exactly as the native one.

**Versions and builds**

- samtools 1.17 with htslib 1.17, compiled by Biowasm with Emscripten 2.0.25:
  - `-O2`, zlib and bzip2 (Emscripten's ports), liblzma 5.2.5;
  - `-s MODULARIZE=1 -s ENVIRONMENT="web,worker" -s ALLOW_MEMORY_GROWTH=1 -s INVOKE_RUN=0 -s FORCE_FILESYSTEM=1`;
  - wasm32: 16 MiB at the start, growing to 2 GiB at most;
  - `samtools.wasm` SHA-256 `816ea4dc5fdcbea45d160289383a6b845e4dd0e3f35f93fd3bd4c9b159680c76`. This is the page's own
    file: nothing was rebuilt for the runner.
- Native: samtools 1.17 built from `samtools-1.17.tar.bz2` (with htslib 1.17): `./configure --without-curses
  --disable-libcurl CFLAGS=-O2`, gcc 13.3.0, zlib 1.3.
- Node.js 22.22.0; Chromium 156.0.8078.4 (headless shell, Playwright 1.64.1).
- Linux 6.18, 2 virtual CPUs (Intel Xeon, 2.80 GHz), 7.8 GiB of memory.

**What it shows.** The program's memory is set by the sort's `-m`, not by the data: 380 MiB for 18.8 GiB of records,
about a fiftieth. The page holds nothing of the files, and nothing of them passes through it. The analysis is on disk,
where a reload finds it. The browser build of SAMtools needs no change to do this. It ran at 0.73 of the native
speed on one thread. Native SAMtools would sort with several threads (`-@`); these builds cannot yet (step 5 and the
threaded builds of step 3).

The full measurements of this run, with a sample of the memory, disk and traffic every five seconds, are in
`docs/prototype-sort-2026-10-14.json` (the script writes them to `tests/results/prototype-sort.json`).

## Native programs in the local runner

Phase 1 of the roadmap. The runner runs a program built for the computer itself where `native/bin` has one, and the
program's WebAssembly build otherwise (`runner/native.mjs`; `runner.mjs --no-native` turns it off).

| Program | Native | The browser's build | Threads natively |
| --- | --- | --- | --- |
| SAMtools | 1.24 | 1.17 | no (`-@` is left out, with a note) |
| BCFtools | 1.24 | 1.10 | no |
| bgzip, tabix (and gzip, gunzip, zcat, which bgzip carries out) | HTSlib 1.24 | HTSlib 1.17 | no |
| minimap2 | 2.28 | 2.22 | yes (`-t`) |
| BWA | 0.7.19 | 0.7.19 | yes (`-t`) |
| FreeBayes | 1.3.10 | 1.3.6 | – |
| fastp | 1.3.7 | 0.20.1 | yes (`-w`) |
| seqtk | 1.4 | 1.4 | – |

**The programs.** They are Native Workbench's Cosmopolitan builds, made again from its recipes by `native/build.py`
(`native/README.md`): one executable per program, which is a Windows program and, started by a 9 KB loader, a Linux
and a macOS (x86-64) one. `native/bin/programs.json` lists them with their SHA-256, which the runner checks when it
starts. The HTSlib programs cannot use threads: HTSlib's thread pool waits on a condition variable with a recursive
mutex, which Cosmopolitan 3.3.10 refuses (`nsync panic: pthread cond needs normal mutex`, at once). The terminal
already leaves `-@` out for the browser's builds; it now says why for the native ones.

**How a run goes.** The page asks for a run exactly as before (`POST /api/v1/exec` with the program's WebAssembly
spec, its arguments, the files of its input, output and messages, its working folder and environment). For a program
that `native/bin` has, the runner:

- gives it the folder on disk as its working folder, and the paths on disk for the page's absolute paths in its
  arguments – whole, glued to a one-letter option (`-o/home/user/x.bam`) or after `--option=`. A relative path that
  would leave the page's folder (`../..`) or reach `.workbench` gets the place the page's programs would reach;
- binds its standard input, output and error to the files the page named (the input stays open in the runner too: the
  position the program left it at is how far it read, which `while read` loops and blocks need);
- gives it the variables the shell exports (paths among them on disk), a temporary folder (`.workbench/tmp`) and the
  folder as `HOME`;
- starts it – on Windows the executable itself, with its name as `argv[0]`; elsewhere the loader, `ape - PROGRAM NAME
  ARGS…`, which sets `argv[0]` too (BWA and minimap2 print it in their `@PG` lines);
- afterwards gives the paths on disk in its messages the page's names back; puts what fastp's report needs next to it
  (Plotly's script: the report was changed to load it from there, not from the web); and undoes anything the program
  did to the example data.

A forced stop ends the program's process group (on Windows, its process tree: `taskkill /T`). What the program wrote so
far stays; nothing else is lost.

**The AI agent's commands stay confined.** A native program runs with the user's rights; the runner keeps its
arguments inside the page's folders, but cannot stop a program that makes up a path itself. So a command that the AI
agent runs (the engine sees its file system, which notes every path) is marked `confined`, and the runner runs the
WebAssembly build for it, whose files are only the runner's folders – as the roadmap's risks require until native
programs can be confined too.

**The example data.** A native program writes real files, so the runner gives it a copy of the example data of its
own (`.workbench/examples`, its files read-only where the system allows) and compares the copy with the site's after
every run. What a program made there is removed, what it changed or removed is put back, and the run says which
(`refused`, `denied`): the terminal says what it says in the browser ("… is read-only (the example data): the change
to it was undone"). The site's own example data is never written.

**What a user sees differ from the browser.** The native programs are newer versions, and that shows:

- minimap2 2.28 writes an `@HD` line at the top of its SAM output (2.22 did not); the records are the same;
- BCFtools 1.24 annotates its calls as current BCFtools does (Mann-Whitney U-z tests, `AD`, a sanity warning about
  `MQ` from HTSlib 1.24) and finds 62 variants in the parity suite's example where 1.10 finds 60;
- a program records the paths it was given, as on any computer: the `@PG` line of a BAM file names the folder on disk
  (for the example data, the runner's copy of it);
- compressed files (BAM, `.vcf.gz`, `.gz`) hold the same, but their bytes – and the indexes that point into them – can
  differ from the browser's: Cosmopolitan's zlib is Chromium's, which compresses differently.

**Tests.** Each checks one claim (`tests/README.md`):

| Test | What it shows | Result (14 October 2026) |
| --- | --- | --- |
| `native-programs.mjs` | The runner runs a native program as it runs when started by hand – 37 commands of all nine programs, typed into the terminal and run in bash with the same executables: output, messages, exit status and every file, byte for byte (times masked) | 37 steps, 1,774 comparisons: the same |
| … the same commands, by hand | The Cosmopolitan builds compute what the Linux builds of the same sources compute (`native/build.py` makes both): every file's content, unpacked | the same; their compressed bytes differ (zlib) |
| `local-runner.mjs` | The native programs' versions in the page; paths in and messages out; the example data kept; threads where a build has them; fastp's report; the AI agent's commands confined; a forced stop that leaves no process | 33 checks passed (9 of them new) |
| Parity suite, `--runner` against `--runner --wasm` | The terminal around the programs behaves the same with native programs – pipes, blocks, `< FILE`, redirections, loops reading program output, copies and moves | 51 steps: the same, but where the versions differ – every difference comes from minimap2's `@HD` line and BCFtools 1.24's calls (`compare.mjs --content`) |
| Parity suite in the browser, before and after | The browser's backend is unchanged | 67 steps, 2,996 comparisons: identical |
| `prototype/sort-big-bam.mjs` | The 5 GiB sort, with native SAMtools 1.24 | 19 checks passed; below |
| `native/build.py`, twice | The programs of `native/bin` can be made again | built twice in `/tmp/native-workbench-build`: all nine byte for byte the same |

**The 5 GiB sort, natively.** The prototype again (`tests/prototype/sort-big-bam.mjs`), on the same machine and the
same input (60,000,000 reads, 5.01 GiB; made again by `make-unsorted-sam.mjs --seed 1`), with the runner's native
SAMtools 1.24. The full measurements: `docs/prototype-sort-native-2026-10-14.json`.

| | Native SAMtools 1.24, from the page | WebAssembly SAMtools 1.17, from the page (first prototype) | SAMtools 1.24 built for Linux, by hand |
| --- | --- | --- | --- |
| `samtools sort -m 256M` | **1,079 s** (18.0 min) | 1,776 s (29.6 min) | 1,247 s |
| Memory of the program at its peak | 345 MiB | 380 MiB of WebAssembly memory | 364 MiB |
| The runner at its peak | 83 MiB | 462 MiB (it held the program) | – |
| `samtools index` | 47 s | 101 s | – |
| Between page and runner during the sort | 13 requests, 1.1 KiB sent, 37.5 KiB received | 16 requests, 1.3 KiB sent, 49.6 KiB received | – |
| The page's JavaScript heap | 5.0 MiB before, 5.5 MiB at most | 5.2 MiB before, 5.8 MiB at most | – |

The result is that of the Linux build: the same header but for its `@PG` lines, the same records in the same order
(`samtools view` of both: 23.46 GiB, the same SHA-256), the same `idxstats` and counts of a region, before and after a
reload of the page. Only the compressed bytes differ (zlib). The Cosmopolitan build is faster than the Linux build of
the same source, by 13 %: its zlib is Chromium's. All on one thread: `-@` does not work in these builds, and with it a
sort spreads its compression over the processor's cores.

**Not yet.** The programs with a worker of their own (featureCounts, Salmon, LoFreq …); the native programs of Native
Workbench that are Windows programs only (LLVM-MinGW, MSVC and upstream builds: HISAT2, Bowtie 2, Kraken2 …), and
those that need Java, Python or R. None of this has run on Windows yet: the Cosmopolitan executables are Windows
programs, and the runner has the Windows code paths (the executable started by itself, `taskkill`, the system's
variables), but phase 2 is where they are tested, on the reference laptop.

## Tests

`tests/` (see `tests/README.md`) checks both backends in headless Chromium:

- **Parity suite** (`run-suite.mjs`, `compare.mjs`): 67 steps that between them cross every point of the
  boundary. These include pipes and redirections of every kind, blocks, loops and functions reading program output,
  `< FILE` and `< <(…)`, the shell's own commands writing bytes, copies and moves of program-written files, the
  programs with a worker of their own, the Strelka2 and Kraken2 workflows, and both kinds of forced stop. Each
  command's exit status, output and messages are compared, and so is every file in the home folder (bytes, size,
  kind, permissions). The suite is run twice on the version before a change, to find what varies by itself (times,
  durations), and once on the version after it.
- **Local mode against the browser** (`run-suite.mjs --runner --subset local`): the 51 steps for the programs the
  runner has, run with the runner, compared with the same steps in the browser.
- **Opaque handles** (`opaque-backend.js`): the same suite with a backend in front of the browser's that replaces
  every handle with a meaningless token. If any code outside a backend still treated a handle as a path, its
  results would differ.
- **Boundary check** (`boundary-lint.mjs`): outside the backends' files, no code may name the browser runner, its
  file system, its handles or its kind of entry.
- **Contract checks** (`contract.mjs`): registration refuses an incomplete backend; the defaults; what the AI agent
  does around each command (a copy kept, the file overwritten, put back with its bytes); the local backend with no
  runner, with a runner that cannot give its files, with a wrong token and with another protocol version.
- **The runner** (`local-runner.mjs`): the files already in a folder (and behind a link) are the terminal's; what
  programs and the page write is in the folder, and a reload finds it; a run goes on through a reload; a forced stop
  ends that program only and loses nothing; and the runner's safety. It answers only with the key, only at its own address, only to its own page and only about its
  own folders; it keeps the example data read-only and runs only the workbench's programs.

## What the next steps change

| Step (review) | Where it plugs in |
| --- | --- |
| 3. Emscripten tools under Node with a disk file system | Done for the Biowasm builds (step 2 needed it). Next: the programs with a worker of their own (`OWN_WORKER` in `exec-browser.js`), whose builds are threaded (pthreads) or need Pyodide. The local machine's `ownWorker`/`execWorker` is where they plug in, with `diskfs.mjs` and `tool-host.mjs` as the base. |
| 4. Isolate jobs, keep their results | The runner: a process per job instead of a worker thread (a program that crashes the process, or exhausts its memory, then ends alone), the job's state on disk, several pages. |
| 5. True wasm64 builds | The builds, and `capabilities`: the terminal's notes about memory (`plink2Args`, `bustoolsMemory`) can say what the runner allows. |
| 6. Notebooks and viewers | `entryBytes` reads whole files. Large files need `Range` reads (`GET /api/v1/file` has them) and a way for Python and R to open the folder's files where they are. |
