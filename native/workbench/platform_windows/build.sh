#!/usr/bin/env bash
set -euo pipefail
project_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
toolchain_dir=${BW_MINGW_ROOT:-"$project_dir/../toolchains/llvm-mingw-20260922-ucrt-ubuntu-22.04-x86_64"}
compiler=${BW_WINDOWS_CC:-"$toolchain_dir/bin/x86_64-w64-mingw32-clang"}
if [[ ! -x "$compiler" ]]; then
    echo "Set BW_MINGW_ROOT to an extracted llvm-mingw toolchain, or BW_WINDOWS_CC to a MinGW compiler." >&2
    exit 1
fi
if [[ -d "$toolchain_dir/lib" ]]; then
    export LD_LIBRARY_PATH="$toolchain_dir/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
fi
cd "$project_dir"
mkdir -p build/windows
mkdir -p build/windows/tmp
export TMPDIR="$project_dir/build/windows/tmp"
"$compiler" -std=c11 -O2 -Wall -Wextra -Werror \
    -Iinclude platform_windows/host.c scripts/module_embed.S \
    -lcomdlg32 -lshell32 -Wl,--no-insert-timestamp,--strip-all \
    -o build/windows/bwfastq.exe
echo "Built $project_dir/build/windows/bwfastq.exe"
python3 platform_windows/inspect.py --exe build/windows/bwfastq.exe \
    --module build/fastq.module --compiler "$compiler"
