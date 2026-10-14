# Windows deployment and acceptance kit

This companion kit exercises the **published 0.16.0 development prerelease**.
It does not rebuild the application, replace its packs, or establish institutional
approval. Its application, updater, source companion and disposable 0.11.0
baseline have exact identities in `packaging/deployment-0.16.0-lock.json`.

The kit uses the Starter selection: align, bam and variants 0.4.0, plus additional
align 0.4.1 already present in the published Starter. Other packs can be reviewed
and imported separately using Workbench's existing pack manager. Full setup still
requires explicitly requested downloads; this kit does not contain all 32 packs.

## First use

1. Compare the downloaded kit's SHA-256 with the separately supplied review
   record, then extract the complete ZIP into a new folder. Do not overlay an
   existing Workbench installation.
2. Run `verify.cmd`. It uses the included private Python interpreter to check
   every listed bundle file and reject missing, changed or unexpected files.
   The manifest hash can also be compared with the separately supplied record.
3. Run `acceptance.cmd`. Choose a non-identifying machine alias and a new report
   location outside the kit. The guided flow prepares a fresh, verified copy of
   the application for testing outside the immutable bundle.
4. Follow the checklist using that disposable application. Record what you
   actually observed, including failures, blocked actions and untested items.
   Close Workbench before assessing update or preservation behavior.
5. Review the resulting JSON report and selected attachments before sharing them.
   Nothing is uploaded automatically. Only attach files you explicitly select
   and have checked for private data.

Keep the extracted kit unchanged. Launching its `native-workbench` folder
directly creates application state inside the kit and will invalidate a strict
bundle check. Use the verified disposable copy for application interaction.
The 0.11.0 archive exists solely to reproduce an upgrade in a fresh test directory;
it is not the application recommended for a new installation.

Normal Workbench use and the Python acceptance tools require no system Python,
Docker, WSL, browser, administrator rights or network listener. The optional
signature collector additionally uses the Windows-provided PowerShell command
`Get-AuthenticodeSignature`. Existing execution and endpoint-security policies
remain in force; a blocked collector is recorded as unavailable or blocked.

## What the report means

The report binds the bundle manifest, application/source/archive identities and
helper hashes. It records limited operating-system, architecture and display
observations. It does not automatically collect the user name, machine name,
domain, addresses, reference contents or application logs. A tester supplies the
machine alias. Notes and selected attachments can contain sensitive information,
so review them before sharing.

Manual and automated evidence are separate. A hosted automation pass never
fills in a manual pass. An unperformed check remains untested; an environmental
restriction remains blocked. A report is an observation from one machine, not
a declaration of supported Windows versions or institutional approval.

The manual checklist covers:

| Scenario | Observation to retain |
| --- | --- |
| Installation and first launch | Exact kit identity, fresh extraction, ordinary user account and actual startup outcome. |
| Scientific smoke | Check installation and the curated synthetic workflows; expected answers and raw outputs, without invented QC thresholds. |
| Keyboard use | Focus visibility, Tab/Shift+Tab, dialog cancellation and usable navigation. |
| Display scaling | Actual scale/DPI, window dimensions, readable labels and usable controls after resizing. |
| Multiple monitors | Monitor/scaling configuration and behavior when moving the app between monitors. |
| Physical trackpad | Observed pan, zoom and scrolling on the actual device. Injected Windows messages do not replace this. |
| Paths | Ordinary, spaced and Unicode locations; declared long-path refusals distinguished from successful analysis. Native child working directories of 260 characters or more remain unsupported. |
| Update interaction | Actual folder-picker cancellation, invalid-folder recovery, successful selection and update, preserved user state and repeat behavior. |
| Offline and managed machine | Which actions were performed offline, any proxy/application-control blocks, and the exact executable affected. No policy changes are requested. |

Use synthetic examples for shared evidence. Testing clinical/private datasets is
not required by this kit. Record a limitation rather than changing security
controls to obtain a pass.

## Automated native gate

`scripts/check_deployment_ui_windows.py` drives the actual published
`UpdateWorkbench.exe` and its Windows folder picker. It uses a disposable
0.11.0 installation, checks cancellation and invalid selection, completes an
update through the picker, compares the resulting core with the accepted Starter,
checks preservation and repeats the operation. It also records bounded desktop
keyboard/resize observations and screenshots.

The companion CI workflow runs the exact generated kit in ordinary and
space-containing Windows paths and reruns the curated workflow/results gate
on a separate disposable extraction. Source tests, archive inspection, native
execution, visual review and manual acceptance have separate evidence scopes.
See the [online review handover](https://github.com/comparativechrono/workbench/blob/feature/deployment-acceptance/knowledge/deployment-acceptance-handover.md) for
actual results, source commits, archive hashes, failures and skips.

High-DPI, multi-monitor, physical-trackpad and managed-PC acceptance require
observations from those environments. A hosted 96-DPI capture does not close
them. Benchmarking and scientific Linux CWL execution are separate work.

## Known observations in the published application

Hosted tests of the unchanged 0.16.0 application found that **Escape after a
keyboard search did not close the Results window**. Use its visible **Close**
button when necessary. Keep the failed Escape observation in the report;
successful use of Close does not make that keyboard check pass. The internal
cause and behavior on representative PCs still need investigation.

The hosted desktop was 1024 pixels wide at 96 DPI, while the application's
minimum width was 1040 pixels, leaving its right window edge clipped. Check
the actual available display area and scaling on each target machine. The
hosted resize observations do not establish acceptance on that narrower display.

## Maintainer build

Retrieve the four canonical archives in the input lock and verify their sizes
and SHA-256 values. The builder does not download inputs or accept a substitute
with the same filename. From a clean checkout:

```sh
python3 scripts/build_deployment_bundle.py --inputs /path/to/verified-archives --output /path/to/new-output
```

The output is a deployment ZIP, build provenance and checksum file. Existing
output destinations are refused. The kit includes its companion scripts,
source/test materials and documentation alongside the original application
source archive. Its tooling commit is distinct from packaged application source
`e855dc4396e0c16ae35f4e840eb9cc734adb4441`.

The kit manifest is an integrity inventory, not a signature or trust root.
Authenticate its distribution channel and independently supplied expected hash
before executing any included program.
