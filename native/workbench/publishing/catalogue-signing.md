# Protected official catalogue publication

This workflow signs the reviewed pack catalogue and publishes its **public**
documents. It does not release an application, generate a signing key, execute
downloaded tools or change users' installed packs. Existing pack URLs and bytes
remain immutable. App 0.10.0 must still be built with the resulting reviewed
public source and pass live Windows setup before publication.

The owner authorized establishing this process on **2026-10-07**. The GitHub
connection available to the development agent can write source and releases,
but cannot administer environments or provision secrets. The one-time owner
steps below must therefore be completed using the owner's normal GitHub access.
No production key has been created or installed by this implementation.

## One-time owner setup

Open [repository environments](https://github.com/comparativechrono/workbench/settings/environments)
and create **`catalogue-production`**. Configure:

1. **Selected branches and tags**, with a **Branch** rule exactly `main`.
   Selecting "Protected branches only" does not restrict access when no branch
   protection rules exist, so use the explicit rule.
2. A required maintainer reviewer. If this repository has only one maintainer,
   keep self-review allowed so that person can approve a manually started run.
   With another release maintainer available, independent review can be required.
3. Disable administrator bypass of the protection rules.
4. Environment secret **`WORKBENCH_CATALOGUE_RSA_PRIVATE_KEY`** and environment
   variable **`WORKBENCH_CATALOGUE_KEY_FINGERPRINT`**, as described below.

These are GitHub's environment controls, not controls created by a workflow YAML
file. A workflow naming an absent environment can create an **unprotected**
environment; it does not provision the protections or signing credentials. The
publication workflow fails when its independently configured identity is absent.
It also rejects the repository's deliberately public SDK test-key fingerprint.
See GitHub's [environment setup documentation](https://docs.github.com/en/actions/how-tos/deploy/configure-and-manage-deployments/manage-environments).

Use an existing dedicated, protected RSA key if one already exists. The supported
format is an unencrypted PEM, RSA 2048–4096 bits, exponent 65537. The key must be
outside the checkout and any output directory. Keep a protected backup under the
maintainer's control; no private material belongs in Git, chat or an artifact.

If this project has never had a production key, the following **maintainer-run**
example provisions a new 3072-bit key locally. Run it only on your own trusted
machine. It deliberately refuses to overwrite an existing file. These commands
use a POSIX maintainer shell with OpenSSL, Python 3 and an authenticated GitHub
CLI; these are release-maintenance prerequisites, not application prerequisites.

```sh
umask 077
key_dir="$HOME/.config/native-workbench/keys"
mkdir -p "$key_dir"
chmod 700 "$key_dir"
key_file="$key_dir/catalogue-rsa.pem"
if [ -e "$key_file" ]; then
  echo 'Existing key found; keep it and skip generation.'
else
  openssl genpkey -algorithm RSA -pkeyopt rsa_keygen_bits:3072 \
    -pkeyopt rsa_keygen_pubexp:65537 -out "$key_file"
  chmod 600 "$key_file"
fi
```

From the reviewed repository checkout, derive and inspect the **public**
fingerprint using the application format, then provision the environment directly:

```sh
fingerprint="$(python3 scripts/sign_setup_catalogue.py \
  --fingerprint --private-key "$key_file")"
printf '%s\n' "$fingerprint"
gh variable set WORKBENCH_CATALOGUE_KEY_FINGERPRINT \
  --repo comparativechrono/workbench --env catalogue-production \
  --body "$fingerprint"
gh secret set WORKBENCH_CATALOGUE_RSA_PRIVATE_KEY \
  --repo comparativechrono/workbench --env catalogue-production < "$key_file"
```

Check that each command succeeds. The fingerprint is SHA-256 of the canonical
JSON public modulus/exponent used by `pack_security.key_fingerprint`; an OpenSSL
PEM/SPKI fingerprint is a different value. The secret travels through stdin,
not a command argument or public file. GitHub CLI encrypts secret values locally
before upload; see [`gh secret set`](https://cli.github.com/manual/gh_secret_set).
Alternatively, enter the key directly in GitHub's environment-secret UI and put
the inspected public fingerprint in the environment variable.

Only the public fingerprint and confirmation that setup succeeded need to be
shared with a release agent. Never paste the private key into a conversation.

## Publish a catalogue

The workflow must first be present on the default `main` branch. From GitHub
Actions, run **Publish official tool catalogue** on `main`, or use:

```sh
gh workflow run publish-setup-catalogue.yml \
  --repo comparativechrono/workbench --ref main
```

Review the exact commit and approve its `catalogue-production` deployment when
GitHub prompts. A new catalogue or changed release script warrants a fresh review.
The job checks out the dispatch commit, never an input-selected ref. It acquires
the current locked pack archives (about 3.8 GB for this initial selection), checks
their hashes/inventories and runs focused publishing regressions before the key
is exposed to its signing step. It does not execute the downloaded pack programs.

Signing uses a mode-0600 temporary PEM in a dedicated mode-restricted runner
directory outside checkout/output. The helper removes the secret from child
environments, checks the independent public fingerprint, self-verifies with the
application verifier, and cleans up on failure. An additional `always()` step
removes the dedicated temporary directory. A forcibly lost runner cannot run
cleanup; its disposable lifetime is part of the hosting trust boundary.

Only three explicitly named public documents leave the signing job:
`catalogue.json`, `source.json`, and `publication-report.json`. Preparation
evidence is a separate public artifact. The publication job has no signing
environment or private secret. It revalidates signature, official URL/hosts,
reviewed fingerprint, exact pack pins/URLs and prior signed history, then updates
the `catalogue` branch without force and retains dated history and provenance.
Concurrent or stale publications fail rather than overwrite newer state.

The final check anonymously downloads the published public documents and verifies
their exact bytes. A receipt records the catalogue commit and download results.
If publication succeeds but public-download verification fails, retain that
receipt and investigate the existing branch; do not assume the write rolled back
or replace pack assets.

For a retry, start a new dispatch or choose **Re-run all jobs**. Artifacts include
the run attempt in their names; rerunning only the publication job cannot consume
the previous attempt's signing artifact. A retry signs with a fresh timestamp and
still verifies the existing branch before any write.

The public source is expected at:

`https://raw.githubusercontent.com/comparativechrono/workbench/catalogue/source.json`

The official source ID is `native-workbench-official`, with catalogue URL
`https://raw.githubusercontent.com/comparativechrono/workbench/catalogue/catalogue.json`
and exactly `github.com`, `raw.githubusercontent.com` and
`release-assets.githubusercontent.com` as allowed hosts. Changing the publisher
key or these trust boundaries requires a separately reviewed change; it is not
an automatic catalogue update.

## Complete the application release

After the public download receipt passes, compare the source fingerprint with the
owner's reviewed value. Put that exact source object into the new application's
`workspace/catalog-sources.json`. Build a new 0.10.0 candidate, run live production
Full setup and the affected native UI/upgrade checks against its exact archives,
then publish and independently verify public application downloads. Earlier
empty-trust candidate passes remain valuable regression evidence, but do not
validate the new trust configuration or constitute a completed release.

The new source-only signing/deployment tests use the existing deliberately public
SDK key; the established publisher suite also creates ephemeral test-only keys.
GitHub/public-download transports are mocked. No production key is created or
used by these tests, and they do not establish that the production environment
exists, that a production key has been provisioned, or that a production
catalogue/app release is live.
