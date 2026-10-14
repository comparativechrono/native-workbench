Native Workbench 0.6.0 development release

The application and scientific tool packs now have separate release lifecycles.
The starter installation includes minimap2, SAMtools and BCFtools, a small example
pipeline and synthetic validation data. Existing pack IDs and manifest hashes
are preserved, including the previously corrected fastp builds in optional packs.

Manage tools is a native Windows window. It lists installed packs, browses
configured signed catalogues, downloads verified compatible versions, imports
offline ZIPs or folders, and reports progress and cancellation. The development
build has an empty default catalogue configuration. A real GitHub repository,
release URLs and publisher public key must be configured before an official
online catalogue can be used. No production signing key is included.

Saved pipelines resolve exact pack versions and manifest hashes. New versions
install alongside old ones. Missing-pack pipelines retain their settings and
connections and offer a route to Manage tools; execution remains blocked until
the required exact versions are installed. Methods and run records retain tool
version provenance, including the SAMtools helper used for validation.

Application updates own core files only. The 0.5.4-to-0.6.0 updater preserves
installed optional packs, user settings, results, existing source material and
validation evidence. Its private interpreter is separate from the application
being updated. A fresh starter installation contains only the three starter
packs; updating a full installation deliberately retains its installed tools.

Developer entry points:
  docs/pack-development-0.6.md
  docs/catalogue-publishing-0.6.md
  scripts/package_split.py
  scripts/publish_pack_catalog.py
  pack-examples/independent-pack/

Validation distinguishes Linux reference execution and static Windows binary
inspection from native Windows execution. The native interface is cross-compiled
with warnings treated as errors; the new GUI and Windows filesystem tests still
need execution on Windows. Use File > Check installation on the target machine.

Source is distributed separately with exact recovery references to the retained
0.5.4 source and matching independent pack/source archives. Keep the source
companion alongside the published application and pack release assets.
