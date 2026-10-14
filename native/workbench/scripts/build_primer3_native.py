#!/usr/bin/env python3
"""Build unmodified pinned Primer3 CLI and its bounded I/O adapter on x86-64.

This compiles the pinned upstream Makefile CLI source list. No system Python, CMake, shell or network is needed at analysis time.
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
UPSTREAM_VERSION = '2.6.1'
VERSION = UPSTREAM_VERSION
SOURCE_COMMIT = '7f9f17d6012f404e83bbf0f931a4d06eb4af465b'
SOURCE_NAME = 'primer3-2.6.1.tar.gz'
SOURCE_URL = 'https://codeload.github.com/primer3-org/primer3/tar.gz/' + SOURCE_COMMIT
SOURCE_SHA256 = 'c981e42765ceb525f56607c6a7cf989ac5068483731c6e083b1e9fb22816463b'
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
        raise ValueError('Missing/changed pinned Primer3 source; use --fetch with an empty cache')
    source = cache / ('source-pristine' if upstream else 'source-workbench')
    if source.exists():
        shutil.rmtree(source)  # Disposable, exact source tree; never the repository.
    source.mkdir()
    pristine = {}
    with tarfile.open(archive) as stream:
        for member in stream.getmembers():
            parts = Path(member.name).parts
            if not parts or parts[0] != 'primer3-' + SOURCE_COMMIT or '..' in parts or not (member.isfile() or member.isdir()):
                raise ValueError('Unsafe Primer3 source archive')
            if member.isfile():
                relative = Path(*parts[1:])
                data = stream.extractfile(member).read()
                destination = source / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(data)
                pristine[relative.as_posix()] = data
    return source


def source_files(source, linux):
    # Exact upstream Makefile primer3_core object list; masker is excluded by
    # upstream's own Windows OS_WIN conditionals, and unused by this operation.
    names = ['primer3_boulder_main.c', 'format_output.c', 'read_boulder.c',
             'print_boulder.c', 'libprimer3.cc', 'p3_seq_lib.c', 'dpal.c',
             'thal.c', 'thal_parameters.c', 'oligotm.c', 'amplicontm.c']
    if linux:
        names.append('masker.c')
    return [source / 'src' / name for name in names]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cache', type=Path, default=ROOT / 'build/primer3-cache')
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
    out = (args.build or ROOT / ('build/primer3-' + target)).resolve()
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
    flags = ['-O2', '-march=x86-64', '-mtune=generic', '-mno-avx', '-mno-avx2', '-fno-fast-math', '-I' + str(source / 'src')]
    commands = []

    def compile_one(path):
        obj = out / (path.stem + '.o')
        cmd = [cxx if path.suffix == '.cc' else cc, *flags, '-std=c++11' if path.suffix == '.cc' else '-std=gnu11', '-c', str(path), '-o', str(obj)]
        result = subprocess.run(cmd, cwd=out, env=env, text=True, capture_output=True)
        (out / (path.stem + '.compile.log')).write_text(result.stdout + result.stderr)
        if result.returncode:
            raise RuntimeError('Compile failed for ' + path.name + ':\n' + result.stderr)
        return obj, cmd

    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, args.jobs)) as pool:
        built = list(pool.map(compile_one, source_files(source, args.linux)))
    commands.extend(item[1] for item in built)
    suffix = '' if args.linux else '.exe'
    binary = out / ('primer3_core' + suffix)
    link = [] if args.linux else ['-static', '-Wl,--no-insert-timestamp', '-Xlinker', '--stack', '-Xlinker', str(WINDOWS_STACK_RESERVE) + ',' + str(WINDOWS_STACK_COMMIT)]
    cmd = [cxx, *[str(item[0]) for item in built], '-lm', *link, '-o', str(binary)]
    subprocess.run(cmd, cwd=out, env=env, check=True)
    commands.append(cmd)
    files = [binary]
    guard = ROOT / 'tools/primer3/guard.cpp'
    if not args.upstream and not args.without_guard:
        output = out / ('primer3-guard' + suffix)
        cmd = [cxx, '-O2', '-std=c++17', '-march=x86-64', '-mtune=generic', '-mno-avx', '-mno-avx2', '-Wall', '-Wextra', '-Werror', str(guard), *link, '-o', str(output)]
        subprocess.run(cmd, cwd=out, env=env, check=True)
        commands.append(cmd)
        files.append(output)
    record = {'schema': 1, 'tool': 'primer3', 'version': version, 'upstreamVersion': UPSTREAM_VERSION, 'sourceCommit': SOURCE_COMMIT, 'upstreamCommit': SOURCE_COMMIT, 'sources': {SOURCE_NAME: {'url': SOURCE_URL, 'sha256': SOURCE_SHA256}}, 'platform': 'linux-x86_64' if args.linux else 'windows-x86_64', 'serial': True, 'openmp': False, 'cpuBaseline': 'baseline x86-64; no SSE4.1/AVX/AVX2 required', 'upstreamScientificAlgorithmsUnmodified': True, 'upstreamSourceUnmodified': True, 'executionTestsPerformedByBuild': False, 'builderSha256': sha(Path(__file__)), 'compiler': subprocess.check_output([cc, '--version'], env=env, text=True).splitlines()[0], 'compilerSha256': sha(cc), 'commands': commands, 'files': {}, 'buildRoute': 'Direct compilation of pinned upstream Makefile primer3_core object list; upstream OS_WIN conditionals omit unsupported masker; no source patches'}
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
    config = out / 'primer3_config'
    if config.exists():
        shutil.rmtree(config)
    shutil.copytree(source / 'src/primer3_config', config)
    record['configurationFiles'] = {p.relative_to(config).as_posix(): sha(p) for p in sorted(config.rglob('*')) if p.is_file()}
    (out / 'build.json').write_text(json.dumps(record, indent=2) + '\n')
    print(json.dumps({'build': str(out), 'files': record['files']}, indent=2))


if __name__ == '__main__':
    main()
