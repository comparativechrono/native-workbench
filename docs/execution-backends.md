# Execution backends

This is step 1 of the plan in the memory review of 13 October 2026: **an execution-backend boundary**. Every
part of the workbench that runs a program, or touches the bytes that programs read and write, now does so through
one object, `MG.exec` (`assets/js/exec.js`). Behind it sits a *backend*:

| Backend | File | Status |
| --- | --- | --- |
| `browser` | `assets/js/exec-browser.js` | The default. The programs run in the page, compiled to WebAssembly, exactly as before this change. |
| `local` | `assets/js/exec-local.js` | Being built. The page can find and connect to a local runner; running programs comes with the runner (steps 2–4). |

The browser backend is the code that used to be the first half of `tools-wasm.js` (the runner object that was
`MG.wasm`, its workers, its workflows' plumbing), moved unchanged apart from the contract members listed below.
`tools-wasm.js` now holds only the terminal's commands for those programs (the wrappers, the options these builds
cannot take, gzip, grep -P, where a program's output goes), and reaches the programs through `MG.exec` alone.

## Where things live

- **The page** keeps the names of the files (`vfs.js`): folders, sizes, times, permissions, and the text of small
  text files. The shell, the editor, the file panel and globbing all work on these names, synchronously.
- **The backend** keeps the bytes of the files that programs write (BAM, `.gz`, anything over 256 KiB or not UTF-8
  text). The page's entry for such a file has the backend's `entryKind` (`aioli` for the browser backend), and the
  page reads it only through `MG.exec.entryText` / `entryBytes`.
- **Handles** (`MG.FileRef`) carry bytes that the backend keeps between commands: what a program printed, the bytes of
  a pipe, a file given with `< FILE`, a temporary file. A handle means something only to the backend that made it.
  Code outside a backend never looks inside one; it hands the `FileRef` back to `MG.exec`, and asks
  `MG.exec.argPath(ref)` for the name to give a program as an argument.

In the local backend the workspace on disk will be where the files really are; the page's names will mirror it.

## Choosing a backend

- The browser backend is used unless another is asked for.
- `?backend=local` in the address, or `backend: 'local'` in `config.js`, asks for the local backend. The local
  runner serves the workbench itself, so the page asks for it at its own address (`GET /api/v1/hello`). Until the
  runner has answered, every program waits; this takes a few milliseconds and at most four seconds.
- If no runner answers, or it refuses the page, or it speaks another version of the protocol, the page uses the
  browser backend and the terminal says why, once.
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
| `capabilities` *(optional)* | `{ where, persistentFiles, threads }`. |

### Programs

| Member | What it must do |
| --- | --- |
| `ensure(status)` | Start, if it has not started. `status(text)` may report progress. |
| `run(ctx, program, args, opts)` | Run one program to its end and return a **RunResult** (below). Programs run one at a time. |
| `kill(fs)` | Stop the running program by force. Return the paths of the page's files whose bytes were lost with it. Set `lastKill` to `'threads'` (only that program stopped) or `'runner'` (every program, and the files they held); after a `'runner'` stop, increase `gen` and fill `lostTimes` and `lostEntries`. |
| `needsIsolation(program)` | True when the program cannot run in this page as it is: in the browser, the programs that start threads need a cross-origin isolated page. |
| `tidy(text, name)` | What a program printed, with paths as the person knows them (the browser backend removes `/shared/vfs`; a local backend would remove its workspace's root). |

**RunResult**: `{ code, statusKnown, stdout, stderr, parts, tail, out, stdoutSize, created, secs, stdinUsed }`.
`out` is a handle to everything the program printed; `stdout` is that output as text (empty when `opts.binaryOut`).
`parts` gives stdout and stderr in the order the program wrote them (`[1|2, bytes]` pairs), when known. `tail` is
what the backend adds after the program's messages (for instance, that a change to the example data was undone).
`created` lists the files the program made. `stdinUsed` says how far the program read a piped input.

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
`metagenomics.js`) are run by the backend: it calls the workflow with a helper `h` – `spawn(T, opts)` runs one
program of the workflow, `inputsOf`, `readText`, `isFile`, `isDir`, `abs`, `stage`, `pretty`. A program is described
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
| `writeOutput(fs, abs, ref, { tail, append })` | What a program printed becomes the file at `abs`, or is added to its end. Return `false` and leave the file as it is when nothing was printed. In the browser this copies the bytes; a local backend should move or append them on disk without sending them through the page. |
| `settle(fs)` | `cp` and `mv` change only names in the page; before a program reads, each copied or moved file must get bytes of its own. |

### The AI agent (optional)

| Member | Default | What it must do |
| --- | --- | --- |
| `keep(list)` | keeps nothing | Before an agent's command: copy the given held files, so that they can be put back. |
| `putBack(abs, entry, since)` | `false` | After the command: the file is as it was before. |
| `dropKept()` | nothing | The agent has finished: the copies go. |
| `gen`, `lastKill`, `lostTimes`, `lostEntries` | `0`, `''`, empty | See `kill`. |

## The local backend

### What exists now

`exec-local.js` registers the local backend. When it is asked for, it:

1. takes the session's token from the address (`#runner-token=TOKEN`), keeps it for this tab only, and removes it
   from the address;
2. asks `GET /api/v1/hello` at the page's own address, with `Authorization: Bearer TOKEN`, waiting at most four
   seconds;
3. uses the runner if it answers with `{ protocol: 1, runner, version, programs, workspace }`. Otherwise it gives
   the reason (no runner, an ordinary web server, the token refused, another protocol version) and the page uses
   the browser backend.

A runner that answers is used, but in this version every operation except the shell's own commands is refused in
words (“samtools: the local runner answered, but this version of the workbench cannot use it for that yet”). Each
method is the place where the next steps plug in.

### The protocol (version 1, a draft)

Only `hello` exists on the page's side. The rest is a proposal for steps 2–4, written so that each method of the
contract maps to one request. The runner listens on `127.0.0.1` only, serves the workbench, and refuses any request
without the session's token.

| Request | For | Notes |
| --- | --- | --- |
| `GET /api/v1/hello` | `connect` | `{ protocol: 1, runner, version, programs: { name: version }, workspace: { root } }` |
| `POST /api/v1/jobs` | `run` | A job: `{ program, args, cwd, env, stdin: null \| { handle } \| { path }, mergeStderr }`. Arguments as the terminal hands them over; paths are workspace paths (`/home/user/…`, `/data/…`). Returns `{ job }`. |
| `GET /api/v1/jobs/ID` (or `/events`) | `run`, `running` | Progress, then `{ state, code, out: { handle, size }, stderr (bounded), order, stdinPos, changes }`. `changes` lists what the program did to the workspace: `{ path, op: 'write' \| 'remove' \| 'mkdir', size, mtime, text? }`, with `text` only for small UTF-8 files. The page applies them to its names. |
| `POST /api/v1/jobs/ID/cancel` | `kill` | The job's own process only: other files are not lost. |
| `GET /api/v1/files?handle=H` or `?path=P` | `readBytes`, `entryBytes` | Supports `Range`, so viewers and previews can read part of a large file. |
| `PUT /api/v1/files?path=P` | `writeBytes` | |
| `POST /api/v1/files/temp` | `tempBytes`, `tempFile` | Returns `{ handle, argPath }`. |
| `POST /api/v1/fs` | `writeOutput`, `settle`, `discard` | `{ op: 'redirect', from: handle, to: path, append, tail }`; `{ op: 'copy' \| 'move' \| 'remove', … }`. |
| `GET /api/v1/tree` | the page's names | The workspace's files, for the page's `vfs.js` when it starts. |

## Tests

`tests/` (see `tests/README.md`) checks this boundary in headless Chromium:

- **Parity suite** (`run-suite.mjs`, `compare.mjs`): 67 steps that between them cross every point of the
  boundary. These include pipes and redirections of every kind, blocks, loops and functions reading program output,
  `< FILE` and `< <(…)`, the shell's own commands writing bytes, copies and moves of program-written files, the
  programs with a worker of their own, the Strelka2 and Kraken2 workflows, and both kinds of forced stop. Each
  command's exit status, output and messages are compared, and so is every file in the home folder (bytes, size,
  kind, permissions). The suite is run twice on the version before the change, to find what varies by itself (times,
  durations), and once on the version after it.
- **Opaque handles** (`opaque-backend.js`): the same suite with a backend in front of the browser's that replaces
  every handle with a meaningless token. If any code outside a backend still treated a handle as a path, its
  results would differ.
- **Boundary check** (`boundary-lint.mjs`): outside the backends' files, no code may name the browser runner, its
  file system, its handles or its kind of entry.
- **Contract checks** (`contract.mjs`): registration refuses an incomplete backend; the defaults; what the AI agent
  does around each command (a copy kept, the file overwritten, put back with its bytes); the local backend with no
  runner, with a (mock) runner, with a wrong token and with another protocol version.

## What the next steps change

| Step (review) | Where it plugs in |
| --- | --- |
| 2. The runner owns an on-disk workspace | The runner: `hello`'s `workspace`, `GET /api/v1/tree`, the `changes` of a job. The page: entries of kind `local`, applied from `changes`; `inputRef` and `argPath` become workspace paths with no copying; `writeOutput` and `settle` become operations on disk. |
| 3. Emscripten tools under Node with a disk file system | The runner. The page needs nothing new: the same `run(ctx, …)`. The job preparation that now lives inside the browser backend's `run` (which arguments are paths, the environment, `/dev/stdin`) should move into a shared job builder that both backends use. |
| 4. Isolate jobs, keep their results | The runner: a process per job, the job's state on disk. The page: `kill` cancels one job and loses no files (`lastKill = 'threads'`); `persistentFiles: true` should stop `project.js` copying held files into the browser's storage. |
| 5. True wasm64 builds | The runner and the builds. `capabilities` can tell the terminal what memory a program has, in place of the browser's limits (the notes of `oneThread`, `plink2Args` and `bustoolsMemory` speak of “the browser”). |
| 6. Notebooks and viewers | `entryBytes` reads whole files. Large files need `Range` reads (`GET /api/v1/files`) and an explicit way for Python and R to open workspace files, in place of mirroring them. |
