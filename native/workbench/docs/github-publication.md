# Publishing Native Workbench and its packs

The [0.6.0 application prerelease](https://github.com/comparativechrono/workbench/releases/tag/app-v0.6.0)
and all 18 independent pack archives are published in
`https://github.com/comparativechrono/workbench`. The application has seven release
assets. Public downloads have been checked against the original byte sizes and
SHA-256 checksums.

**The signed online catalogue and `source.json` trust file are not published or
configured.** Completing them requires a maintainer-controlled signing key. No
production key or public trust file has been created or supplied here. The
catalogue URLs below remain planned locations; they are not working feed links.

To install now, download a pack ZIP from its tagged GitHub release and choose
**Manage tools > Import pack ZIP** in Workbench 0.6.0 or later. A ZIP can be copied
to an offline machine and imported there. The starter includes `align`, `bam`
and `variants`; other packs are separate downloads.

One repository is sufficient. Separate tags and release assets give the app and
packs independent lifecycles; a second repository is not required. This layout
supersedes the SDK documentation's earlier suggestion to use two repositories.

| Component | Tag or branch | Contents |
| --- | --- | --- |
| Application | release tag `app-v0.6.0` | Starter, 0.5.4 updater, SDK, full source companion, README, checksums and verification report |
| Each pack | release tag `pack-<id>-v<version>` | Its existing independently installable ZIP; release notes link the corresponding source companion |
| Catalogue (pending) | planned branch `catalogue` | Signed `catalogue.json`, public `source.json`, publication report and retained catalogue history |

`publishing/publication-layout-0.6.0.json` lists every exact asset URL and all 18 pack release
tags. Existing pack IDs and versions are preserved, including `align`, `bam`,
`variants` and `fastp` 0.4.1. A future app release uses another app tag; a future
tool release uses another pack tag. Neither requires rebuilding the other.
Never replace a published pack ZIP under an existing pack/version identity.

The planned stable catalogue URL is (not yet published):

`https://raw.githubusercontent.com/comparativechrono/workbench/catalogue/catalogue.json`

The planned public source/trust file URL is (not yet published):

`https://raw.githubusercontent.com/comparativechrono/workbench/catalogue/source.json`

The published source companion is:

`https://github.com/comparativechrono/workbench/releases/download/app-v0.6.0/native-workbench-0.6.0-source.zip`

Each pack already retains its own licence/source materials. Preserve this full
source companion too: it includes application source and recovery references to
the exact companion pack archives. Future pack releases need their own matching
source/provenance records; do not point a changed pack to unrelated old sources.

## Release files and catalogue generation

`publishing/releases-0.6.0.json` maps all 18 existing pack ZIPs to their independent release
URLs. Relative local paths resolve against the `publishing/` directory. Place the unchanged application and pack assets in an ignored `release-assets/` directory at the repository root, preserving its `packs/` subdirectory. The unsigned preview
was produced by the real publisher, which re-reads archives and validates hashes,
inventories, manifest identities and metadata. It is not an application-trusted
catalogue.

From the repository root, the preview command is:

```bash
python3 scripts/publish_pack_catalog.py \
  --release-map publishing/releases-0.6.0.json \
  --unsigned-preview \
  --output release-assets/catalogue-preview-001
```

A preview was validated during preparation. Use a new output directory for each generation; the publisher deliberately refuses to overwrite output.

Once the publisher's external private key is available, generate the signed
catalogue and actual source file with this command. Replace the example private
key path with its real protected location outside the source checkout and output
directory; this command has not been run:

```bash
python3 scripts/publish_pack_catalog.py \
  --release-map publishing/releases-0.6.0.json \
  --private-key /protected-release-keys/workbench-catalogue.pem \
  --source-id comparativechrono-workbench \
  --source-name "Comparative Chrono Workbench tools" \
  --catalog-url https://raw.githubusercontent.com/comparativechrono/workbench/catalogue/catalogue.json \
  --output release-assets/signed-001
```

The publisher derives public-key material from the supplied RSA key, signs the
catalogue and verifies it through the application validator. It emits
`catalogue.json`, `source.json` and `publication-report.json`. The resulting
source permits the exact hosts `github.com`, `raw.githubusercontent.com` and
`release-assets.githubusercontent.com`. It performs no uploads. Do not manually
invent a public key or publish the unsigned preview in place of a signed wrapper.

## Catalogue publication steps

The source and release assets are published and their public downloads have been
verified. Keep the published archives byte-for-byte intact, preserve old tags and
assets for saved pipelines, and retain the matching source/licence companions.

1. Provision the maintainer-controlled RSA signing key outside the repository,
   archives and catalogue output directory. Record its public-key fingerprint.
2. Generate the signed documents with the command above. Commit them to the
   `catalogue` branch after checking that every referenced release asset remains
   downloadable. Preserve previous signed catalogues under dated history paths
   and keep publication timestamps increasing.
3. Verify the public-key fingerprint independently, import the real `source.json`
   into a clean app, refresh and install a small pack. Run a native Windows
   scientific check and an offline check before announcing the online catalogue.

The unchanged 0.6.0 archives contain an empty default source list. Once the signed catalogue is published, users can
import its actual `source.json` once. To remove that setup step in a later
app build, include the reviewed source object in
`workspace/catalog-sources.json` and produce a new versioned app release; do not
silently modify the already checksummed 0.6.0 archives.

## Still required

- A publisher-controlled RSA signing key: 2048–4096 bits, exponent 65537. The
  current CLI consumes an externally provisioned unencrypted PEM; it never
  creates or uploads the key. No key has been supplied or generated here.
- A recorded source-key fingerprint, publication of the signed catalogue and
  actual `source.json`, and a clean live catalogue download/install test.
- Native Windows GUI and long-path validation. The current evidence includes
  214 passing automated tests with one Windows-only skip, eight starter checks
  and the 0.5.4 migration check on Linux. Scientific execution used the Linux
  portable reference backend; it is not evidence of native Windows execution.

GitHub credentials and the catalogue signing key serve different purposes.
Neither belongs in the repository, pack ZIPs, source archive or public catalogue.
