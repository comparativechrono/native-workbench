#!/usr/bin/env bash
set -euo pipefail
project_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
toolchain_dir=${BW_MINGW_ROOT:-"$project_dir/../toolchains/llvm-mingw-20260922-ucrt-ubuntu-22.04-x86_64"}
export LD_LIBRARY_PATH="$toolchain_dir/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
cd "$project_dir"
mkdir -p build/performance-checks/tmp
export TMPDIR="$project_dir/build/performance-checks/tmp"
"$toolchain_dir/bin/x86_64-w64-mingw32-clang++" -std=c++17 -O2 -Wall -Wextra -Werror \
    -D_WIN32_WINNT=0x0A00 -DWINVER=0x0A00 -municode -static -ffunction-sections -fdata-sections -Idesktop \
    tests/windows_performance.cpp desktop/process_pipeline.cpp desktop/runner.cpp desktop/common.cpp \
    desktop/packs.cpp desktop/pack_model.cpp -lbcrypt \
    -Wl,--gc-sections,--no-insert-timestamp,--strip-all -o build/performance-checks/WindowsPerformanceChecks.exe
echo "Cross-compiled WindowsPerformanceChecks.exe; native Windows execution is still required."
