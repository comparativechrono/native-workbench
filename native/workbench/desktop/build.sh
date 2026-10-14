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
"$windres" -I desktop desktop/workbench.rc -O coff -o build/desktop/workbench-res.o
"$compiler" -std=c++17 -O2 -Wall -Wextra -Werror -D_WIN32_WINNT=0x0A00 -DWINVER=0x0A00 \
    -municode -mwindows -static -Idesktop desktop/common.cpp desktop/pack_model.cpp desktop/packs.cpp \
    desktop/runner.cpp desktop/process_pipeline.cpp desktop/workflow_runner.cpp desktop/modular_validation.cpp desktop/gui.cpp build/desktop/workbench-res.o \
    -lcomctl32 -lole32 -lshell32 -luuid -luser32 -lgdi32 -lgdiplus -luxtheme -ldwmapi -lbcrypt \
    -Wl,--no-insert-timestamp,--strip-all -o build/desktop/NativeWorkbench.exe
echo "Built $project_dir/build/desktop/NativeWorkbench.exe"
