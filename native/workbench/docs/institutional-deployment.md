# Institutional review of Native Workbench

Native Workbench 0.16.0 is a local Windows x86-64 development prerelease for
research and teaching. This document accompanies the deployment/acceptance kit;
it does not grant organisational approval or claim clinical validation.

## Package scope and operation

The exact Starter application and core updater remain unchanged from their
published archives. The kit contains the Starter pack selection, matching source
companion, companion acceptance tools and a disposable older baseline for update
testing. The archived 0.11.0 installation is a test fixture, not a deployment
recommendation. An administrator can distribute the reviewed Starter ZIP alone
when the test fixture and acceptance tools are not wanted on end-user machines.

Normal analysis runs locally. The native desktop communicates with its private
Python host through anonymous pipes, which starts declared scientific tools
through the native bridge. It does not require a browser, HTTP listener, Docker,
WSL, system Python or elevated privileges. Public references and additional tools
are obtained only through explicit user actions. The kit does not upload reports.

The application writes user settings, results and reference state to its selected
local locations. Give the user write access to the intended installation/state
and analysis locations; do not assume that an extracted portable application is
compatible with a read-only managed installation layout. Institutional deployment
and backup policies should review those locations before acceptance.

## Executable, dependency and licence inventory

`inventory/app.json` and `inventory/update.json` describe every inventoried file
by relative path, byte count and SHA-256. The accompanying readable inventory
summarises components and points to their actual licence and source-availability
documents. The application, bridge, private runtimes, scientific tools and
helper modules must all be considered during review.

For supported PE images, the inventory records the declared machine type and
direct imported DLL names without loading the executable. These are static
imports, not a complete runtime dependency graph. Delay loading, plugins,
dynamic imports and non-PE executable formats can need additional review.
Unknown metadata and parse limitations remain explicit. A DLL name is not a
promise that a compatible dependency is installed or approved.

Licence-file presence and declared metadata are evidence to inspect, not an
automated licence-compliance verdict. The kit retains actual notices and source
references. Some complete third-party source materials are distributed in
separate immutable source companions referenced by those records; the application
source ZIP alone must not be described as containing every optional tool's source.

The inventory is intended for a software review and allowlisting conversation.
It is not presented as a complete SPDX/CycloneDX SBOM or a vulnerability audit.

## Signatures and approval

Run `signatures.cmd` to request read-only Windows Authenticode observations for
inventoried `.exe`, `.dll` and `.pyd` files and PE content, including updater
payload blobs without filename extensions. Python, CMD and PowerShell scripts
remain in the complete hash inventory but are outside this signature check.
Review the recorded status,
file hash, public signer identity where available, and observation environment.
Unavailable trust-chain or timestamp information remains unavailable. Certificate
chain/revocation evaluation can depend on Windows trust configuration and network
availability; do not infer an offline trust guarantee from an online result.

The signed pack catalogue authenticates its catalogue publisher and pinned
archives. It does not sign each Windows executable or establish acceptance by
endpoint-security software. Checksums detect changes; they do not establish a
publisher identity. An Authenticode result is also not institutional approval.

This kit neither signs executables nor changes trust stores, application-control
rules, antivirus exclusions, PowerShell execution policy or firewall rules. Record
the observed block and submit the exact executable identity and provenance to IT.
The previously reported bridge-security block remains an approval matter.

A future executable-signing implementation needs a controlled signing identity,
secure signing service or key custody, and a reviewed release process. Signing
changes file bytes: signed application/pack builds need new versioned artifacts,
fresh inventories and exact-package validation. Never overwrite the published
0.16.0 archives or change a saved pack's identity silently.

## Installation, update and evidence

For a fresh installation, extract the approved Starter into a new writable
directory. Do not overlay it on existing user state. The supplied updater supports
only the published 0.11.0 installation. Close Workbench, extract the updater
separately, run `UpdateWorkbench.exe` and select the existing `native-workbench`
folder. Test the organisation's backup and recovery procedure before rollout.

The updater owns core files and preserves packs, exact workflow pins, settings,
results and references. It does not automatically add align 0.4.1 to an older
installation; that independent ZIP needs explicit import when required.

Use the [acceptance guide](deployment-acceptance.md) to retain a machine-specific
report, exact file identities, screenshots and actual outcomes. The kit's source
and hosted Windows checks support only their recorded conditions. Select target
Windows versions, display configurations and managed-machine policies for the
organisation's own acceptance matrix; no general support matrix is inferred.
