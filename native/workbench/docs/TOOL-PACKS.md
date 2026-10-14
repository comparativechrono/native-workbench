# Offline, versioned tool packs

Native Workbench 0.2.1 ships a prepared pack for Windows x86-64. The desktop application discovers packs immediately below its own `packs` folder. It never executes tools merely to discover a pack. SHA-256 verification runs before a job or an installation check; importing also verifies before and after copying.

This release supports a fixed set of tools and workflows. A pack supplies compatible builds of `bwfastq`, `seqtk`, and `minimap2`; it cannot add an arbitrary new workflow or convert a Linux executable. No Linux kernel, VM, Docker daemon, or WSL installation is involved. The bundled upstream tools use Cosmopolitan, an existing portable native runtime. See the bundled build scripts and provenance records for exact upstream versions and build inputs.

## Layout

An installed pack has this layout:

```text
packs/
  core-bio-0.2.0/
    pack.ini
    PACK-README.md
    bin/
      bwfastq.exe
      seqtk.exe
      minimap2.exe
    licenses/
      ... publisher-supplied license and attribution files ...
```

`PACK-README.md` is optional. `licenses` is required when importing. Directory names for installed packs must be exactly `<id>-<version>`. An import source folder may have any ordinary folder name; the application chooses the installed name from its manifest. Pack IDs are sorted alphabetically, with versions sorted numerically from newest to oldest within each ID. Selecting a version is explicit; there are no background updates or automatic downloads.

## Manifest format

The following is a schema example. The SHA-256 placeholders must be replaced by each executable's actual hash; this example is not directly importable.

```ini
[pack]
format=1
id=core-bio
version=0.2.0
name=Bioinformatics essentials
platform=windows-x86_64

[bwfastq]
version=1
path=bin\bwfastq.exe
sha256=<64 hexadecimal digits>

[seqtk]
version=1.4-r122
path=bin\seqtk.exe
sha256=<64 hexadecimal digits>

[minimap2]
version=2.28-r1209
path=bin\minimap2.exe
sha256=<64 hexadecimal digits>
```

Rules:

- `pack.ini` is UTF-8, with an optional UTF-8 BOM, and at most 16 KiB. LF and CRLF are accepted. Lines are limited to 512 UTF-16 code units after surrounding spaces and tabs are removed.
- The four section names and their keys are exact and case-sensitive. Every displayed key is required. Unknown sections or keys, repeated sections or keys, empty values, NUL characters, and embedded control characters are rejected.
- Empty lines and whole-line comments starting with `;` or `#` are accepted. Inline comments are not interpreted. Surrounding spaces and tabs are ignored around keys and values.
- `format` is exactly `1`, and `platform` is exactly `windows-x86_64`.
- `id` is 1–48 characters, starts with a lowercase ASCII letter, contains only lowercase letters, digits, and hyphens, and does not end in a hyphen.
- Pack `version` has exactly three decimal components, such as `0.2.0`. Each component has 1–9 digits, with no leading zero unless it is zero. Prerelease labels are not supported in pack versions.
- `name` is a nonempty display name of at most 100 UTF-16 code units, without control characters. Unicode display names and ordinary Unicode folder paths are supported.
- Tool `version` is 1–64 characters drawn from ASCII letters, digits, `.`, `+`, `_`, and `-`. It is metadata supplied by the publisher. Verification does not execute a tool to confirm its version label.
- Tool paths are exactly the three lower-case, backslash-separated paths shown above. Absolute paths, alternative filenames, traversal, drive names, environment variables, and command arguments are not accepted.
- `sha256` has exactly 64 hexadecimal digits; upper-case hexadecimal is accepted and normalized to lower case. Hashes cover the complete executable bytes.
- Each tool must have an x86-64 Windows PE32+ header and be no larger than 64 MiB. Header validation is a basic format check, not a guarantee that the program will execute correctly.

## Importing a pack

Use **Add pack folder...** and select an extracted pack folder from a publisher you trust. The application asks for confirmation before installing native code. It reads and validates the manifest and executable headers, verifies all three executable hashes, and copies the supported contents to a unique staging folder under `packs`. It then validates and hashes the copied executables before publishing the folder with a same-volume rename.

Only `pack.ini`, the three named executable files, optional `PACK-README.md`, and the recursively copied `licenses` folder are imported. Other source files are ignored and are never executed. The imported contents are limited to 500 files and folders in the counted copy set, 64 MiB of file data in total, and 12 nested license subfolder levels. License and README files are carried along for attribution; the manifest does not authenticate their contents.

An existing `<id>-<version>` is never replaced. Publish changed executables under a new pack version. A failed or cancelled import removes its own temporary staging directory where possible. A crash or interruption can leave a `_import-*` staging folder; discovery ignores those folders. An installed pack is never deleted as part of failed-import cleanup.

Packs must reside on an ordinary local drive path such as `C:\NativeWorkbench`; UNC paths, mapped network drives, device paths, symlinks, junctions, and other reparse points in checked pack paths are rejected. This includes OneDrive placeholders or redirected directories implemented as reparse points. Copy the application or import folder to a regular local directory if this check reports a problem. Names with trailing spaces or periods and unsafe Windows filename forms are not accepted.

Pack discovery, hashing, import, and failed-import cleanup use explicit extended-length Win32 paths internally. Deep license folders can therefore be copied without enabling Windows' system-wide long-path policy. Displayed paths, pack metadata, and arguments passed to tools retain ordinary Windows path spelling. Individual filesystem components remain subject to the volume's filename limits, and each tool has its own path-handling behavior.

Cancellation is checked between hash and copy chunks. The copied executable bytes are unchanged; the importer does not patch, recompile, or wrap the tools. Move or unzip the application to a writable folder before importing, because imported packs are stored beside it.

## Trust and local processing

**These are trusted native executables, not sandboxed Linux containers.** Imported tools run with your Windows account's permissions. A manifest hash detects damage or a change relative to that manifest; it does not establish who published a pack, because an attacker could replace both an executable and its hash. There is no signing, publisher trust store, privilege isolation, or native-code security boundary in this prototype.

The workbench's pack discovery, verification, and import code performs local file operations and does not download packs or upload input data. That statement does not constrain arbitrary imported executables: native tools can access the network or other files like any other program with your account's permissions. Only install packs from sources you trust. The Windows process Job Object supports stopping child processes; it is not a file-access or network sandbox.

The application checks known pack paths for reparse points and keeps checked folders open during operations. This protects the normal import and verification path from ordinary link substitution. It is not a hardened defense against a malicious administrator, kernel component, or another process with the user's full privileges continually modifying the installation. Keep installed packs in a directory controlled by the intended user.

## Implementation references

The implementation uses the Windows CNG SHA-256 API ([BCryptCreateHash](https://learn.microsoft.com/en-us/windows/win32/api/bcrypt/nf-bcrypt-bcryptcreatehash), [BCryptHashData](https://learn.microsoft.com/en-us/windows/win32/api/bcrypt/nf-bcrypt-bcrypthashdata), and [BCryptFinishHash](https://learn.microsoft.com/en-us/windows/win32/api/bcrypt/nf-bcrypt-bcryptfinishhash)). Files are opened with `FILE_FLAG_OPEN_REPARSE_POINT` and checked using handle attributes; see Microsoft's [reparse points and file operations](https://learn.microsoft.com/en-us/windows/win32/fileio/reparse-points-and-file-operations) documentation.
