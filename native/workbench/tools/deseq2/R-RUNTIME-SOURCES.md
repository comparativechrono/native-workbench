# Private R runtime: corresponding third-party sources

This companion accompanies the unmodified Windows R 4.6.1 runtime in the DESeq2
pack. The pack itself contains the matching official R source release (including
recommended-package sources), Python source, all R-package sources, adapter
source and build recipes. This separate download contains the external libraries
and compiler runtime sources used by Rtools45, plus the Tcl/Tk bundle sources and
the R project's patches and build instructions. It does not install a runtime.

The machine-readable lock binds every downloaded source and recipe to its exact
SHA-256 and byte count, the original R installer and the recovered runtime ZIP.
All notices and license files inside the original source archives are retained.
The R-project/MXE recipes come from immutable R-dev-web Subversion revision 6768:

https://svn.r-project.org/R-dev-web/!svn/bc/6768/trunk/WindowsBuilds/winutf8/ucrt3/

R 4.6 uses Rtools45. The bundled R runtime reports GCC 14.3.0; the gcc14 overlay
selects that release and its patches. The generic gcc.mk's older default is
overridden by settings.mk and is not the compiler supplied with this runtime.
The archive includes GCC 14.3.0 source, including libgcc, libstdc++, libgfortran
and libgomp, and MinGW-w64 source including winpthreads. General compiler and
build-tool dependencies are included conservatively; their presence does not
assert that every library is linked into R.

The selected Rtools45 library versions match the runtime's reported versions or
embedded identifying strings: zlib 1.3.1, bzip2 1.0.8, xz 5.8.2, libdeflate 1.25,
zstd 1.5.7, PCRE2 10.47, ICU 77.1, Cairo 1.18.4, libpng 1.6.54, JPEG 9f,
libtiff 4.7.1, curl 8.18.0 and OpenSSL 3.6.0. The source closure conservatively
includes the recipes' transitive library dependencies, including GNU libiconv,
gettext, GLib, font/font-shaping libraries and compression/network libraries.
The version correspondence is supported by runtime reports and binary strings;
this is not a claim that the upstream runtime has been rebuilt bit-for-bit.

The exact R-project Tcl bundle recipe selects Tcl 8.6.17, Tk 8.6.17,
BWidget 1.10.1 and the historical ActiveState Tktable source snapshot. Those
archives and tcl.diff, tk.diff and tktable.diff are included. Tcl's source archive
also includes the sources for the bundled itcl, SQLite, TDBC, thread, dde and
registry extensions. The Tcl zlib1.dll reports zlib 1.3.1, whose source is present.
TRE, win_iconv and code copied into R itself are covered by the R source release
and its component notices retained in the installed runtime.

To recover this same source companion using only Python's standard library:

```sh
python tools/deseq2/prepare_runtime_sources.py --cache SOURCE_CACHE \
  --destination native-workbench-deseq2-1.0.0-r-runtime-sources.zip --fetch
```

Omit `--fetch` for an offline, fully verified cache. Source archives remain in
their original upstream form under sources/. R-project build scripts and the
selected MXE recipes/patches are under recipes/; Tcl bundle scripts/patches are
under tcl-recipes/. Their original full tree is available at the immutable
Subversion URL above. Consult build_in_docker.sh and the R installation manual
for the system build prerequisites. Use the gcc14 overlay selected by settings.mk
when rebuilding Rtools libraries; do not substitute the default gcc.mk version.
The unmodified upstream build.sh loops over both `base` and `full` toolchains.
This companion covers the base runtime closure, not unrelated libraries in the
full Rtools distribution. To rebuild that subset after placing source archives
in the MXE package cache, invoke the `local-pkg-list` target from recipes/mxe with
`R_TARGET=x86_64 R_TOOLCHAIN_TYPE=base`; for example,
`make R_TARGET=x86_64 R_TOOLCHAIN_TYPE=base local-pkg-list`.
The general system build prerequisites still apply. Do not expect the unmodified
full-toolchain build.sh loop to finish offline using only this companion.
The Windows R extraction recipe supplied in the pack reproduces the distributed
private runtime from the pinned official installer without rebuilding R.

The source companion must be published alongside every release distributing this
runtime, with its exact byte count and SHA-256 in the release metadata. It is a
source download rather than an installable tool pack. No additional network
access or source download is needed to run an already installed DESeq2 pack.
