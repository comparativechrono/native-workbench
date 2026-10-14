# Reusable reference indexes, development 0.13.0

This is the bounded first implementation, not a claim of support for every
aligner's index format. Published packs, the three historical Starter pins and
the official 32-pack setup profile remain unchanged. The separate **align 0.4.1
candidate** adds minimap2 short-read indexing and indexed mapping, requires
Workbench 0.13.0, and reuses the exact minimap2 2.28-r1209 and paircheck 1.0.1
executable bytes from align 0.4.0. Its recipe is
[`scripts/package_reusable_index.py`](../scripts/package_reusable_index.py).

## User operation

Add **Build short-read reference index**, connect the genomic FASTA, and connect
its **Verified short-read reference index** output to **Single-end alignment
with verified index** or **Paired-end alignment with verified index**. Supply
the reads and sample options normally. Selecting this builder explicitly
requests verified local reuse: the first successful run builds the index;
later runs with the same reference bytes and indexing identity verify and copy
the existing index. The builder remains visible in the workflow.

The existing FASTA-based alignment operations keep their declared commands.
They do not silently start using an index. Saved graphs retain their exact
pack pins. The new `minimap2-sr-index` type is distinct from a generic index,
SAMtools `.fai`, BWA index or STAR genome directory. Arbitrary external `.mmi`
files are rejected because their indexing preset/tool identity is not proven.
The workflow must contain the declared compatible producer; a subsequent run
may reuse that producer's previously completed index.

Minimap2's pinned [v2.28 upstream documentation](https://github.com/lh3/minimap2/blob/v2.28/README.md#general)
states that an index fixes its indexing parameters, including `-k`, `-w`, `-H`
and `-I`. The candidate therefore builds with `-x sr` and maps with `-a -x sr`.
It does not treat indexes prepared for other read types as interchangeable.

## Identity, completeness and recovery

`workspace/reference_indexes.py` stores immutable entries in
`user-data/reference-indexes/v1/<key>/`. The key is SHA-256 of canonical JSON
binding the reference SHA-256/size, exact pack ID/version/manifest hash,
executable IDs/versions/hashes, scientific command templates, all parameter
values, declared output paths and the versioned index-format contract. Even
thread-count changes conservatively create a separate identity.

`index.json` inventories every cached scientific product with relative path,
byte count and SHA-256. Only a successful backend result with an unchanged
reference and validated nonempty minimap2 output is eligible. Files are copied
and flushed into a private staging directory, the receipt is written last, and
the directory is renamed to publish atomically. Staging directories are never
listed as completed indexes. Failure or cancellation before publication leaves
no registered entry. A cancellation after atomic publication can leave the
complete verified cache even if that run is recorded as cancelled; subsequent
reuse still rechecks the full identity and inventory.

Every reuse checks the identity, complete inventory, every output hash and
the currently installed executable hash, then verifies the copied run-local
bytes. Corruption, missing/undeclared files, malformed receipts, links/junctions
and an incompatible consumer fail closed. The application does not delete or
silently replace uncertain cache entries. Index verification is local and does
not download or upload anything. The list labels entries **not verified** until
their bytes are checked; simply reading a receipt is not a passed integrity check.

A per-key OS file lease serializes build/publication across processes. Windows
uses `msvcrt` byte-range locking; POSIX tests use `flock`. The lock filename is
retained so two processes cannot lock different inodes for the same key. Process
death releases the lease without stale-PID guesses or manual lock deletion.
An interrupted private staging directory remains unlisted and is not reused.
There is no automatic cache deletion or size eviction in this tranche.

`Engine.prepare(..., index_policy='reuse')` freezes the policy in the plan.
`rebuild` deliberately runs the builder again, preserving an existing valid
entry; different bytes for an identical identity cause an error. This is an
engine option, not permission to overwrite a corrupted entry.

## Result provenance and portability

Each successful builder node and its index output carry `referenceIndex`
evidence with `action` (`built` or `reused`), identity/key, complete inventory
and receipt hash. Its step directory contains `reference-index.json`. The
reference itself remains a frozen workflow input, including downloaded-reference
provenance where available. Methods explicitly say when indexing was not run.
Reused steps record unavailable native command metrics with the reason
`reference_index_reused_without_native_command`; they do not invent CPU or
memory measurements. Verification/copy time remains included in elapsed time.

Each result receives its own index copy, so deleting a cache entry cannot break
already retained results. This requires space for both cache and result copies.
The CWL retains the declared builder and mapping commands and exact scientific
pins; original-run metadata records reuse. External CWL execution can rebuild
the index from the supplied reference and does not depend on Workbench's cache.

## Evidence and limits

Linux source tests exercise the real local filesystem/store and a deliberately
synthetic backend. They establish cache identity, build/hit distinction,
fail-closed corruption/missing/extra-file behavior, cancellation, executable
integrity on hits, frozen batch/CWL metadata, unchanged legacy workflow commands,
and subprocess-lock recovery after killing the owner. They do **not** establish
minimap2 scientific equivalence or Windows behavior.

The exact packaged Windows candidate gate must run real index creation and
reuse, compare mapping records with ordinary FASTA-based alignment, preserve
the Starter alignment/BAM/variant truth, test altered reference/options,
reject damaged cache/executable bytes, and retain both ordinary/spaced-path
reports. Record its actual result in the tranche's dated evidence before
claiming native success. Realistic indexing benchmarks, very large genomes,
STAR/directory indexes, arbitrary external-index import and cache relocation
remain outside this first implementation.

The candidate pack declares a separate **Check installation** known-answer
case using the pinned Starter fixture: its ordinary paired-end operation must
produce 202 mapped, paired, properly paired SAM records with the expected
reference and sample/read-group metadata. This verifies the candidate binary
and ordinary mapping path. The current single-operation pack-check schema does
not represent build-then-map graphs, so it does not claim to establish indexed
mapping/cache behavior; the separate candidate scientific gate does that.
