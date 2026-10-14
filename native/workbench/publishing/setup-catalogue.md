# Official setup catalogue preparation

**Status, 2026-10-07:** the protected publishing workflow and concrete
[owner setup guide](catalogue-signing.md) are merged into `main` through
[PR #4](https://github.com/comparativechrono/workbench/pull/4). Owner environment
and key provisioning remain unavailable to the agent and unverified. Application
0.10.0 is unreleased; its recorded candidate still has an empty production source
list, and its historical Windows results do not establish live official trust.

The native Full/Starter/Custom setup keeps independently versioned packs. Its
reviewed selection is `workspace/setup-profile.json`; that file supplies labels,
estimates and exact pack pins, **not publisher trust**. The corresponding
`publishing/setup-assets.json` locks the 32 current immutable release URLs and
expected archive/manifest hashes. Existing application and pack releases remain
unchanged. Installed scientific databases and user references are separate.

The source ID for this implementation is `native-workbench-official`. It replaces
the earlier unpublished plan's `comparativechrono-workbench` identifier; neither
identifier previously established production trust. The planned catalogue URL
remains:

`https://raw.githubusercontent.com/comparativechrono/workbench/catalogue/catalogue.json`

## Acquire, inspect and prepare

From the repository root, use a scratch/release directory outside the checkout:

```sh
python3 scripts/prepare_setup_catalogue.py \
  --archives /release/setup/archives \
  --output /release/setup/preview-001 \
  --download --workers 4
```

`--download` explicitly permits retrieving missing archives. Without it, every
archive must already be present. Existing archives are rehashed and validated;
an invalid cache is rejected without overwriting it. Completed downloads survive
a later interruption. Partial downloads are deleted. All redirects are confined
to `github.com` and `release-assets.githubusercontent.com` using the existing
application downloader. No downloaded program is executed.

The script checks complete archive SHA-256s and byte sizes, every member's CRC,
inventory SHA-256s, manifest identities, runtime declarations and scientific
metadata. It also rejects a changed or inconsistent setup profile. It writes:

- `release-map.json`, accepted by the established publisher.
- `catalogue-preview.UNSIGNED.json`, deliberately not importable as trusted data.
- `preparation-report.json`, distinguishing successful static checks from native
  execution, signing and publication.

The supplied 32-pack archives total **3,799,806,535 bytes**. Starter already has
three of these; a Full setup on a fresh Starter downloads the other 29, totaling
**3,795,572,848 bytes**. Reusing completed installations changes that total. All
licence trees in the original packs remain intact. This preparation changes no
pack bytes and does not replace or redistribute companion assets. Existing
matching source/evidence companions remain at the original pack releases; in
particular preserve the DESeq2 R source companion described in
[`tools/deseq2/R-RUNTIME-SOURCES.md`](../tools/deseq2/R-RUNTIME-SOURCES.md).

The [2026-10-06 preparation record](../knowledge/evidence/setup-catalogue-preparation-2026-10-06.json)
records successful full acquisition and static validation of all 32 archives.
The resulting [`setup-catalogue.UNSIGNED.json`](setup-catalogue.UNSIGNED.json)
is checked in for review and isolated validation fixtures only. It is not a
production feed, a source definition, or a replacement for catalogue signatures.

## Production trust remains a maintainer prerequisite

Use the [protected signing guide](catalogue-signing.md) for the current automated
workflow. The owner must configure environment `catalogue-production`, secret
`WORKBENCH_CATALOGUE_RSA_PRIVATE_KEY` and the independently reviewed public
variable `WORKBENCH_CATALOGUE_KEY_FINGERPRINT`. The workflow's presence does not
create those protections or credentials. No production key was generated or
provisioned during this work. The direct command below remains the underlying
publisher interface for a maintainer-controlled external signing process.

The preparation command never generates, reads or uses a signing key. The
documented publisher requires an existing maintainer-controlled RSA key outside
the checkout and output directory (2048–4096 bits, exponent 65537). Do not use a
test key or treat archive checksums as authentication.

After provisioning that key through the established protected release process,
sign the fully validated release map:

```sh
python3 scripts/publish_pack_catalog.py \
  --release-map /release/setup/preview-001/release-map.json \
  --private-key /protected-release-keys/workbench-catalogue.pem \
  --source-id native-workbench-official \
  --source-name "Native Workbench official tools" \
  --catalog-url https://raw.githubusercontent.com/comparativechrono/workbench/catalogue/catalogue.json \
  --output /release/setup/signed-001
```

The paths above are placeholders, not supplied key locations. Do not paste a
private key into a conversation or place it in repository files. The publisher
prints no key content. It emits only the signed catalogue, public source object
and publication report, verifying them with the application's verifier.

Before release:

1. Review the public-key fingerprint and source URL/allowed hosts with the
   maintainer. Record the public fingerprint and key custody procedure, not the
   private key or its contents.
2. Publish the signed documents to the `catalogue` branch, retain dated signed
   history, and preserve increasing publication timestamps. Do not replace a
   published pack archive under an existing identity.
3. Download the public signed catalogue and verify it against the reviewed
   source. Include that exact source object in the new app's
   `workspace/catalog-sources.json`; do not modify an old app archive.
4. Build the new application, validate the exact Windows package with live
   trusted catalogue downloads and native setup interactions, interruption,
   retries, all-pack coexistence, offline reuse and upgrade preservation.

An isolated validation catalogue signed with an ephemeral test key can exercise
the install mechanism, but it cannot pass steps 1–4 for production trust or
establish that the official source is available. The bundled production source
list remains empty until the real source has been reviewed and deployed.

## Observed readiness, 2026-10-07

Initial GitHub inspection before implementation found `main` at
`1abd62b49acc841502c9714d12a2470b7e48f8d6`, no open pull requests and no
`catalogue` branch. At that 2026-10-06 checkpoint, no documented key locator,
catalogue-signing workflow secret reference or environment configuration was
available. The source configuration remains `[]`. No production key file was
searched for or read. The GitHub connector cannot administer environments or
secrets, so owner provisioning remains **unknown**, not evidence that no GitHub
secret exists. See the dated preparation evidence for completed acquisition
checks; this page is not a live deployment registry.

The infrastructure source in PR #4 is
`6e973db73953a5ef1f7d221a79ce94887f2fb366`.
[CI run 37583926483](https://github.com/comparativechrono/workbench/actions/runs/37583926483)
passed 56 source tests (14 signing, 25 deployment, 11 publication and six
preparation), with no failures or skips. These cover isolated test signing and
mocked publication/download transports. They do not establish a
provisioned production environment, published catalogue or application release.
The owner guide is the concrete next step; once provisioning is confirmed, the
manual workflow can publish and verify the real signed documents.

Implementation is now retained in [draft PR #3](https://github.com/comparativechrono/workbench/pull/3).
The exact 0.10.0 candidate passed native setup and 0.9.0 upgrade checks in both
Windows paths, and installed all 32 real packs under isolated test-only trust.
The [candidate handover](../knowledge/tool-setup-0.10.0-handover.md) records the
evidence and original validator failures. These checks do not remove the
production signing prerequisite. The current candidate has empty production
trust and must be rebuilt with the reviewed source before live production
validation and publication.
