# Publishing independent packs and catalogues

Version 0.6 adds an explicit-trust catalogue manager. The application initially
has no invented GitHub organization, production signing key or implicitly trusted
source. A maintainer must publish real release assets and distribute a reviewed
source configuration before online installation is available. Offline ZIP import
works without adding a catalogue and verifies its file inventory; it does not
claim to authenticate the publisher.

For an official or institutional application build, place reviewed production
source definitions in `workspace/catalog-sources.json`, a JSON list of complete
source objects. Then the source is present for students without each student
importing a file. The development release starts with `[]`: it cannot promise a
working official catalogue until a real repository, URLs and publisher key have
been configured. The application release that includes the source is the trust
delivery mechanism; do not add an unreviewed source merely to populate the list.

## Repository and release layout

This project keeps application source and pack recipes in one repository with
independent tags: `app-v<version>` and `pack-<id>-v<version>`. A pack release need
not update the application or rebuild another pack. A separate pack repository
is optional. See the [repository publication guide](github-publication.md) for
the accepted layout. Preserve old release assets. Attach compiled pack
ZIPs, licence/source companions, build provenance and Windows validation evidence
to the corresponding release.

Publish a signed `catalogue.json` and public `source.json` at deliberate HTTPS
locations, for example GitHub Release asset URLs or an institutional mirror.
The initial URL must not contain credentials, a query or fragment. The source
configuration names exact allowed hosts, including any redirect destinations.
The publisher automatically includes `release-assets.githubusercontent.com` when
using `github.com` release URLs. An institutional mirror should use its own source
ID, explicit hosts and controlled signing key.

The catalogue is curated metadata, not a GitHub search result. It contains
multiple independently released versions. The desktop reads it only on request;
normal analysis remains local. A cached, previously verified catalogue lets users
inspect available versions without a successful refresh. Downloads still require
connectivity, or a separately obtained offline archive.

## Keys and explicit trust

Supply an existing external RSA private key (2048–4096 bits, exponent 65537).
The publisher requires it outside the checkout and output directory, and never
generates, uploads, prints or embeds a private key. Protect it in your established
release process. The current CLI accepts an unencrypted PEM provisioned by that
process; it fails rather than interactively asking for a passphrase. Delete any
temporary unencrypted copy after signing using your secret-handling procedure.

The emitted `source.json` contains only its public modulus/exponent. Review its
catalogue URL, allowed hosts and public-key fingerprint through a trusted channel
before a user imports it through Manage tools. The source configuration is the
trust root: signatures cannot authenticate a source file supplied by an unknown
party. Do not ship the SDK's test keys, fake example hosts or automatically added
trust. Key replacement requires explicit source trust replacement; it is not an
automatic signed-catalogue update.

## Prepare a multi-release map

Store a local, reviewable mapping from each prepared archive to its immutable
release URL. Relative archive paths resolve against the map's directory.

```json
{
  "schema": 1,
  "releases": [
    {
      "archive": "seqkit-1.0.0.zip",
      "downloadURL": "https://github.com/YOUR-ORG/YOUR-PACK-REPO/releases/download/seqkit-pack-1.0.0/seqkit-1.0.0.zip"
    },
    {
      "archive": "seqkit-1.0.1.zip",
      "downloadURL": "https://github.com/YOUR-ORG/YOUR-PACK-REPO/releases/download/seqkit-pack-1.0.1/seqkit-1.0.1.zip"
    }
  ]
}
```

These are placeholders to replace before publication. The local archives must
exist. The publisher recomputes archive, file-inventory and manifest hashes,
checks runtime declarations and scientific metadata, and rejects duplicate
pack/version identities. It derives tool versions, description and category from
the pack rather than trusting copied catalogue text.

First inspect an unsigned preview:

```powershell
python scripts/publish_pack_catalog.py --release-map C:/release/release-map.json --unsigned-preview --output C:/release/preview-001
```

It emits only `catalogue-preview.UNSIGNED.json`. This is deliberately not a
trusted application catalogue and cannot be imported as a source.

Then sign using the intended final catalogue location:

```powershell
python scripts/publish_pack_catalog.py --release-map C:/release/release-map.json --private-key C:/protected-release-keys/catalogue.pem --source-id university-tools --source-name "University bioinformatics tools" --catalog-url https://github.com/YOUR-ORG/YOUR-PACK-REPO/releases/download/catalogue/catalogue.json --output C:/release/signed-001
```

Use repeated `--allow-host` options for extra exact redirect hosts when needed.
`--published-at 2026-10-03T12:00:00Z` supplies an explicit timestamp for repeatable
signing; ordinary publication uses the current UTC time. The client rejects an
older timestamp than its verified cached catalogue, so do not reuse an old date
when releasing an update.

For several assets in a single release, this shorter form is also supported:

```powershell
python scripts/publish_pack_catalog.py C:/release/seqkit-1.0.0.zip --github YOUR-ORG YOUR-PACK-REPO seqkit-pack-1.0.0 --private-key C:/protected-release-keys/catalogue.pem --catalog-url https://example.org/workbench/catalogue.json --output C:/release/signed-002
```

`--base-url https://example.org/packs` is an alternative for a mirror. Both
shortcuts append the archive filename; use the release map when versions live
under different tags. Existing output documents are never overwritten: create a
new publication directory for each signing attempt.

## Outputs and publication order

The signed output directory contains:

| File | Purpose |
| --- | --- |
| `catalogue.json` | Signed wrapper verified by the application |
| `source.json` | Explicitly imported public source/trust definition |
| `publication-report.json` | Pack count, public-key fingerprint, timestamp; records `uploaded: false` |

The wrapper is `{schema:1,payload:<base64>,signature:<base64>}`. Its signature is
RSASSA-PKCS1-v1_5 with SHA-256 over the exact decoded payload bytes. The payload
contains `schema`, `publishedAt` and `packs`. Each pack row includes stable ID,
pack version, upstream tool versions, description, category, platform, API,
minimum application version, download URL, compressed size and archive/manifest
SHA-256. The publisher verifies its output through the same verifier and schema
validators used by the application before writing any public document.

Upload the immutable pack archives and source companions first, then test their
public URLs and hashes, then publish the new signed catalogue. A catalogue is
the last publication step so it never intentionally advertises missing assets.
The supplied CLI does not perform network access or upload anything. It cannot
verify that a URL exists, that GitHub permissions are correct or that a workplace
allows the download host. Record a separate clean-client download/install test
before announcing availability.

For restricted environments, IT can mirror approved archives and signed
catalogues or distribute pack ZIPs offline. Importing a source does not upload
sample data. Installing a pack does not authorize web access by an analysis tool.

## Maintainer checks

```powershell
python -m unittest discover -s tests -p test_publish_pack_catalog.py -v
```

These tests create a temporary RSA test key, sign real catalogue bytes and verify
them through the app. They cover payload/signature tampering, changed archive
members, unsafe paths, extra files, duplicate identities, independent version
URLs and refusal to overwrite output. Test keys are ephemeral and never become
production source trust. Run the separate Windows scientific gate documented in
`pack-development-0.6.md` for every executable pack release.
