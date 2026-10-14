# Native Workbench application mark

`native-workbench.svg` is the original, editable artwork. Five linked modules
form a **W**, representing independently installed local tools connected into a
scientific workflow. The navy tile, teal links and pale nodes use a restrained
palette that works with the native interface. No third-party logo or generated
image is used. The artwork is covered by the repository's MIT licence.

The current native desktop build runs:

```sh
python3 scripts/build_app_icon.py
```

The script reads the SVG and creates `build/desktop/native-workbench.ico` with
16, 20, 24, 32, 40, 48, 64, 128 and 256 pixel frames. It supports only the solid
circles, rounded rectangles and round-joined polylines used in this artwork;
unsupported SVG features fail explicitly. Rasterization uses deterministic
four-by-four supersampling. Small frames use 32-bit DIB images with alpha and
legacy masks; the two largest use PNG. Both are standard Windows icon formats.
All generation uses Python's standard library at build time. The installed app
loads the embedded icon resource and needs no SVG renderer or additional package.

`desktop/resource.h` assigns resource 101. `build_desktop_workspace.sh` embeds
that resource in `NativeWorkbench.exe`; the window class loads its large and
small icons for the title bar, taskbar and Alt+Tab. Windows Explorer obtains the
same embedded resource. Older historical launchers are not the current desktop
entry point and are not changed.

To review the artwork as a PNG, add
`--preview build/desktop/native-workbench-preview.png`. The SVG remains the source
of truth. Generated ICO/PNG files are build outputs and are not committed. Run
`python3 tests/test_app_icon.py` to check independent decoding of all nine sizes,
alpha masks, orientation, repeatable output and rejection of unsupported edits.
These checks and cross-compilation are separate from a native Windows check of
the actual packaged window and shell icons.
