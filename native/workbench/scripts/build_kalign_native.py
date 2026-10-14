#!/usr/bin/env python3
"""Build pinned Kalign with documented CLI/I/O boundaries and baseline x86-64.

This directly compiles the exact CMake CLI source list with OpenMP and AVX2
disabled. No system Python, CMake, shell or network is needed at analysis time.
Building/PE inspection alone does not establish native Windows execution.
"""
import argparse
import concurrent.futures
import difflib
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import struct
import subprocess
import tarfile
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
UPSTREAM_VERSION = '3.5.1'
VERSION = UPSTREAM_VERSION + '-workbench1'
SOURCE_COMMIT = '3e6de1df29d111c5fa5beb4c4294ef681978fd23'
SOURCE_NAME = 'kalign-3.5.1.tar.gz'
SOURCE_URL = 'https://codeload.github.com/TimoLassmann/kalign/tar.gz/' + SOURCE_COMMIT
SOURCE_SHA256 = '01bacb2205e7b6792c570b163b5ccc0713284737ba862ca3b500a96a8a4d1bd9'
TC_NAME = 'llvm-mingw-20260922-ucrt-ubuntu-22.04-x86_64'
WINDOWS_STACK_RESERVE = 8 * 1024 * 1024
WINDOWS_STACK_COMMIT = 64 * 1024


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for part in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(part)
    return digest.hexdigest()


def prepare(cache, fetch=False, upstream=False):
    cache.mkdir(parents=True, exist_ok=True)
    archive = cache / SOURCE_NAME
    if not archive.exists() and fetch:
        with urllib.request.urlopen(SOURCE_URL, timeout=120) as response:
            archive.write_bytes(response.read())
    if not archive.is_file() or sha(archive) != SOURCE_SHA256:
        raise ValueError('Missing/changed pinned Kalign source; use --fetch with an empty cache')
    source = cache / ('source-pristine' if upstream else 'source-workbench')
    if source.exists():
        shutil.rmtree(source)  # Disposable, exact source tree; never the repository.
    source.mkdir()
    pristine = {}
    with tarfile.open(archive) as stream:
        for member in stream.getmembers():
            parts = Path(member.name).parts
            if not parts or parts[0] != 'kalign-' + SOURCE_COMMIT or '..' in parts or not (member.isfile() or member.isdir()):
                raise ValueError('Unsafe Kalign source archive')
            if member.isfile():
                relative = Path(*parts[1:])
                data = stream.extractfile(member).read()
                destination = source / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(data)
                pristine[relative.as_posix()] = data
    if not upstream:
        path = source / 'src/run_kalign.c'
        text = path.read_text()
        old = '#include "parameters.h"\n'
        if text.count(old) != 1:
            raise ValueError('Explicit alphabet include patch context changed')
        text = text.replace(old, old + '#include "msa_struct.h"\n')
        old = '        if(param->load_poar != NULL){'
        if text.count(old) != 1:
            raise ValueError('Explicit alphabet patch context changed')
        text = text.replace(old, '''        /* Native Workbench: an explicit CLI type declares the input alphabet.
         * The pack guard validates residues before this boundary. Upstream's
         * composition guess can misclassify low-complexity proteins or DNA
         * rich in ambiguity codes. No scoring/alignment routine is changed. */
        switch(param->type){
        case KALIGN_TYPE_DNA:
        case KALIGN_TYPE_DNA_INTERNAL:
        case KALIGN_TYPE_RNA:
                msa->biotype = ALN_BIOTYPE_DNA;
                if(!param->quiet){
                        LOG_MSG("Native Workbench: explicit nucleotide alphabet selected.");
                }
                break;
        case KALIGN_TYPE_PROTEIN:
        case KALIGN_TYPE_PROTEIN_DIVERGENT:
        case KALIGN_TYPE_PROTEIN_PFASUM43:
        case KALIGN_TYPE_PROTEIN_PFASUM60:
        case KALIGN_TYPE_PROTEIN_PFASUM_AUTO:
                msa->biotype = ALN_BIOTYPE_PROTEIN;
                if(!param->quiet){
                        LOG_MSG("Native Workbench: explicit protein alphabet selected.");
                }
                break;
        default:
                break;
        }

''' + old)
        path.write_text(text)
        changes = []
        for relative, old_bytes in sorted(pristine.items()):
            new_bytes = (source / relative).read_bytes()
            if old_bytes != new_bytes:
                changes.extend(difflib.unified_diff(old_bytes.decode().splitlines(True), new_bytes.decode().splitlines(True), fromfile='a/' + relative, tofile='b/' + relative))
        (cache / 'workbench1.patch').write_text(''.join(changes))
    return source


def source_files(source):
    # Read the pinned authoritative list rather than compiling dormant variants,
    # test mains, or the unused pthread scheduler with different semantics.
    text = (source / 'lib/CMakeLists.txt').read_text()
    match = re.search(r'set\(source_files\s+(.*?)\)', text, re.S)
    if not match:
        raise ValueError('Pinned CMake library source list missing')
    names = re.findall(r'^\s*(src/[^ #]+\.c)\s*$', match[1], re.M)
    if len(names) != 36 or len(set(names)) != 36:
        raise ValueError('Unexpected pinned CMake source list')
    return [source / 'lib' / name for name in names] + [source / 'src/run_kalign.c', source / 'src/parameters.c']


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cache', type=Path, default=ROOT / 'build/kalign-cache')
    parser.add_argument('--build', type=Path)
    parser.add_argument('--toolchain', type=Path, default=ROOT / 'build/toolchains' / TC_NAME)
    parser.add_argument('--fetch', action='store_true')
    parser.add_argument('--linux', action='store_true')
    parser.add_argument('--upstream', action='store_true', help='Pristine Linux CLI reference only')
    parser.add_argument('--jobs', type=int, default=2)
    parser.add_argument('--without-guard', action='store_true', help='Development science build; cannot prepare a pack')
    args = parser.parse_args()
    if args.upstream and not args.linux:
        parser.error('--upstream is the pristine Linux reference only')
    cache = args.cache.resolve()
    source = prepare(cache, args.fetch, args.upstream)
    target = 'reference-linux' if args.upstream else ('linux' if args.linux else 'windows')
    out = (args.build or ROOT / ('build/kalign-' + target)).resolve()
    out.mkdir(parents=True, exist_ok=True)
    (out / 'tmp').mkdir(exist_ok=True)
    tc = args.toolchain.resolve()
    env = dict(os.environ, TMPDIR=str(out / 'tmp'))
    if args.linux:
        cc, cxx = shutil.which('gcc'), shutil.which('g++')
    else:
        suffix = '.exe' if os.name == 'nt' else ''
        cc, cxx = (str(tc / ('bin/x86_64-w64-mingw32-clang' + suffix)), str(tc / ('bin/x86_64-w64-mingw32-clang++' + suffix)))
        env['LD_LIBRARY_PATH'] = str(tc / 'lib')
        env['PATH'] = str(tc / 'bin') + os.pathsep + env.get('PATH', '')
    if not cc or not cxx:
        raise ValueError('GCC/G++ or the pinned LLVM/MinGW toolchain is required')
    version = UPSTREAM_VERSION if args.upstream else VERSION
    flags = ['-O2', '-std=gnu11', '-march=x86-64', '-mtune=generic', '-mno-avx', '-mno-avx2', '-fno-fast-math', '-DNOHAVE_AVX2', '-DKALIGN_PACKAGE_NAME="kalign"', '-DKALIGN_PACKAGE_VERSION="' + version + '"', '-DKALIGN_ALN_SERIAL_THRESHOLD=250', '-DKALIGN_KMEANS_UPGMA_THRESHOLD=50', '-I' + str(source / 'lib/src'), '-I' + str(source / 'lib/include')]
    compat = ROOT / 'tools/kalign/upstream_windows_compat.h'
    if not args.linux:
        flags += ['-include', str(compat)]
    commands = []

    def compile_one(path):
        obj = out / (path.stem + '.o')
        cmd = [cc, *flags, '-c', str(path), '-o', str(obj)]
        result = subprocess.run(cmd, cwd=out, env=env, text=True, capture_output=True)
        (out / (path.stem + '.compile.log')).write_text(result.stdout + result.stderr)
        if result.returncode:
            raise RuntimeError('Compile failed for ' + path.name + ':\n' + result.stderr)
        return obj, cmd

    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, args.jobs)) as pool:
        built = list(pool.map(compile_one, source_files(source)))
    commands.extend(item[1] for item in built)
    suffix = '' if args.linux else '.exe'
    binary = out / ('kalign' + suffix)
    link = [] if args.linux else ['-static', '-Wl,--no-insert-timestamp', '-Xlinker', '--stack', '-Xlinker', str(WINDOWS_STACK_RESERVE) + ',' + str(WINDOWS_STACK_COMMIT)]
    cmd = [cc, *[str(item[0]) for item in built], '-lm', *link, '-o', str(binary)]
    subprocess.run(cmd, cwd=out, env=env, check=True)
    commands.append(cmd)
    files = [binary]
    guard = ROOT / 'tools/kalign/guard.cpp'
    if not args.upstream and not args.without_guard:
        output = out / ('kalign-guard' + suffix)
        cmd = [cxx, '-O2', '-std=c++17', '-march=x86-64', '-mtune=generic', '-mno-avx', '-mno-avx2', '-Wall', '-Wextra', '-Werror', str(guard), *link, '-o', str(output)]
        subprocess.run(cmd, cwd=out, env=env, check=True)
        commands.append(cmd)
        files.append(output)
    record = {'schema': 1, 'tool': 'kalign', 'version': version, 'upstreamVersion': UPSTREAM_VERSION, 'sourceCommit': SOURCE_COMMIT, 'upstreamCommit': SOURCE_COMMIT, 'sources': {SOURCE_NAME: {'url': SOURCE_URL, 'sha256': SOURCE_SHA256}}, 'platform': 'linux-x86_64' if args.linux else 'windows-x86_64', 'serial': True, 'openmp': False, 'cpuBaseline': 'baseline x86-64; no SSE4.1/AVX/AVX2 required', 'upstreamScientificAlgorithmsUnmodified': True, 'upstreamSourceUnmodified': args.upstream, 'executionTestsPerformedByBuild': False, 'builderSha256': sha(Path(__file__)), 'compiler': subprocess.check_output([cc, '--version'], env=env, text=True).splitlines()[0], 'compilerSha256': sha(cc), 'commands': commands, 'files': {}, 'buildRoute': 'Direct compilation of pinned CMake CLI source list; USE_OPENMP=OFF, ENABLE_SSE=OFF, ENABLE_AVX=OFF, ENABLE_AVX2=OFF equivalents'}
    if not args.upstream:
        record.update(patchSha256=sha(cache / 'workbench1.patch'), windowsCompatibilityHeaderSha256=sha(compat), changes=['Explicit CLI type overrides initial input alphabet detection for the supported default DNA/protein operations. Unsupported ensemble/precise paths may redetect copied MSAs and are not covered by this boundary guarantee.', 'Windows getline and localtime_r boundary implementations; ERROR macro removal.', 'Build-time version suffix 3.5.1-workbench1.'])
    if len(files) == 2:
        record.update(guardSourceSha256=sha(guard), guardCompiler=subprocess.check_output([cxx, '--version'], env=env, text=True).splitlines()[0], guardCompilerSha256=sha(cxx))
    for file in files:
        info = {'bytes': file.stat().st_size, 'sha256': sha(file)}
        if not args.linux:
            pe = file.read_bytes()
            pe_offset = struct.unpack_from('<I', pe, 60)[0]
            optional_offset = pe_offset + 24
            if pe[:2] != b'MZ' or pe[pe_offset:pe_offset + 4] != b'PE\0\0' or struct.unpack_from('<H', pe, optional_offset)[0] != 0x20b:
                raise ValueError('Expected PE32+ executable')
            reserve, commit = struct.unpack_from('<QQ', pe, optional_offset + 72)
            if (reserve, commit) != (WINDOWS_STACK_RESERVE, WINDOWS_STACK_COMMIT):
                raise ValueError('Unexpected native stack configuration')
            info.update(stackReserveBytes=reserve, stackCommitBytes=commit)
            inspect = tc / ('bin/llvm-readobj' + ('.exe' if os.name == 'nt' else ''))
            data = subprocess.check_output([str(inspect), '--coff-imports', str(file)], env=env, text=True)
            (out / (file.stem + '.imports.txt')).write_text(data)
            imports = re.findall(r'^\s*Name:\s*(\S+)\s*$', data, re.M)
            if not imports or any(name.lower() not in {'kernel32.dll', 'msvcrt.dll', 'ucrtbase.dll', 'advapi32.dll', 'user32.dll'} and not name.lower().startswith('api-ms-win-crt-') for name in imports):
                raise ValueError('Unexpected Windows runtime dependency: ' + repr(imports))
            info['imports'] = sorted(imports)
        record['files'][file.name] = info
    notices = out / 'compiler-notices'
    notices.mkdir(exist_ok=True)
    if not args.linux:
        candidates = [tc / 'LICENSE.TXT', *sorted((tc / 'x86_64-w64-mingw32/share/mingw32').glob('COPYING*'))]
        if not all(path.is_file() for path in candidates) or len(candidates) < 2:
            raise ValueError('Pinned compiler/runtime licensing notices missing')
        for path in candidates:
            shutil.copyfile(path, notices / path.name)
        record['toolchainFiles'] = {str(path.relative_to(tc)): sha(path) for path in (tc / 'bin/clang', tc / 'bin/lld', tc / 'LICENSE.TXT') if path.is_file()}
    record['compilerNotices'] = {path.name: sha(path) for path in sorted(notices.iterdir()) if path.is_file()}
    (out / 'build.json').write_text(json.dumps(record, indent=2) + '\n')
    print(json.dumps({'build': str(out), 'files': record['files']}, indent=2))


if __name__ == '__main__':
    main()
