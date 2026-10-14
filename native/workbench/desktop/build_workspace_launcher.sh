#!/usr/bin/env bash
set -euo pipefail
project_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
toolchain_dir=${BW_MINGW_ROOT:-"$project_dir/../toolchains/llvm-mingw-20260922-ucrt-ubuntu-22.04-x86_64"}
compiler="$toolchain_dir/bin/x86_64-w64-mingw32-clang++"
windres="$toolchain_dir/bin/x86_64-w64-mingw32-windres"
if [[ ! -x "$compiler" ]]; then
    echo "Set BW_MINGW_ROOT to the pinned llvm-mingw compiler folder." >&2
    exit 1
fi
export LD_LIBRARY_PATH="$toolchain_dir/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
cd "$project_dir"
mkdir -p build/desktop/tmp
export TMPDIR="$project_dir/build/desktop/tmp"
cat > build/desktop/workspace-launcher.rc <<'RESOURCE'
#include <windows.h>
1 RT_MANIFEST "workbench.manifest"
1 VERSIONINFO
FILEVERSION 0,5,0,0
PRODUCTVERSION 0,5,0,0
FILEFLAGSMASK 0x3fL
FILEFLAGS 0x0L
FILEOS VOS_NT_WINDOWS32
FILETYPE VFT_APP
BEGIN
  BLOCK "StringFileInfo"
  BEGIN
    BLOCK "040904b0"
    BEGIN
      VALUE "FileDescription", "Native Workbench workspace launcher\0"
      VALUE "FileVersion", "0.5.0\0"
      VALUE "InternalName", "NativeWorkbench\0"
      VALUE "OriginalFilename", "NativeWorkbench.exe\0"
      VALUE "ProductName", "Native Workbench\0"
      VALUE "ProductVersion", "0.5.0\0"
    END
  END
  BLOCK "VarFileInfo"
  BEGIN
    VALUE "Translation", 0x0409, 1200
  END
END
RESOURCE
"$windres" -I desktop build/desktop/workspace-launcher.rc -O coff -o build/desktop/workspace-launcher-res.o
"$compiler" -std=c++17 -O2 -Wall -Wextra -Werror -D_WIN32_WINNT=0x0A00 -DWINVER=0x0A00 \
    -DUNICODE -D_UNICODE -municode -mwindows -static desktop/workspace_launcher.cpp \
    build/desktop/workspace-launcher-res.o -lshell32 -luser32 \
    -Wl,--no-insert-timestamp,--strip-all -o build/desktop/WorkspaceLauncher.exe
echo "Built $project_dir/build/desktop/WorkspaceLauncher.exe"
