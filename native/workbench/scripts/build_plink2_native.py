#!/usr/bin/env python3
"""Build unmodified pinned PLINK2 for the bounded summary pack, without LAPACK.

Pinned Makefile source lists, baseline x86-64, private static zlib. Compilation
and PE inspection are distinct from native execution and scientific validation.
"""
import argparse
import concurrent.futures
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tarfile
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
VERSION = UPSTREAM_VERSION = '2.0.0-a.7.12'
SOURCE_COMMIT = '5c1f185d4144e62fa23087d68760162f712cd2a8'
SOURCE_NAME = 'plink-ng-2.00a7.12.tar.gz'
SOURCE_SHA256 = 'bcfa30a7cfca2e117bacb94c94a2248ab190396ff8d2711f600ef42ebf5f9198'
SOURCE_URL = 'https://codeload.github.com/chrchang/plink-ng/tar.gz/' + SOURCE_COMMIT
ZLIB_NAME = 'zlib-1.3.2.tar.gz'
ZLIB_SHA256 = 'bb329a0a2cd0274d05519d61c667c062e06990d72e125ee2dfa8de64f0119d16'
SOURCES = {SOURCE_NAME: {'url': SOURCE_URL, 'sha256': SOURCE_SHA256}, ZLIB_NAME: {'url': 'https://zlib.net/fossils/' + ZLIB_NAME, 'sha256': ZLIB_SHA256}}
TC_NAME = 'llvm-mingw-20260922-ucrt-ubuntu-22.04-x86_64'


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for part in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(part)
    return h.hexdigest()


def prepare(cache, fetch=False):
    cache.mkdir(parents=True, exist_ok=True)
    for name, source in SOURCES.items():
        archive = cache / name
        if not archive.exists() and fetch:
            with urllib.request.urlopen(source['url'], timeout=120) as response:
                archive.write_bytes(response.read())
        if not archive.is_file() or sha(archive) != source['sha256']:
            raise ValueError('Missing/changed pinned source: ' + name)
        destination = cache / ('source' if name == SOURCE_NAME else 'zlib')
        if destination.exists():
            shutil.rmtree(destination)
        destination.mkdir()
        prefix = 'plink-ng-' + SOURCE_COMMIT if name == SOURCE_NAME else 'zlib-1.3.2'
        with tarfile.open(archive) as tar:
            for member in tar.getmembers():
                parts = Path(member.name).parts
                if member.issym() and name == SOURCE_NAME and len(parts) > 2 and parts[1] == '2.0' and parts[2] in {'Python', 'cindex', 'pgenlibr'}:
                    continue  # Unbuilt language-binding links; original archive is retained.
                if not parts or parts[0] != prefix or '..' in parts or not (member.isfile() or member.isdir()):
                    raise ValueError('Unsafe pinned source archive member')
                if member.isfile():
                    target = destination.joinpath(*parts[1:])
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(tar.extractfile(member).read())
    return cache / 'source/2.0', cache / 'zlib'


def source_files(source):
    text = (source / 'Makefile.src').read_text()
    values = {}
    for line in text.replace('\\\n', ' ').splitlines():
        match = re.match(r'^(\w+)\s*=\s*(.*)$', line)
        if match:
            values[match[1]] = match[2]
    def expand(key):
        result = values[key]
        while '$(' in result:
            result = re.sub(r'\$\((\w+)\)', lambda m: values[m[1]], result)
        return result.split()
    names = sum((expand(key) for key in ('CSRC', 'ZCSRC', 'ZSSRC', 'CCSRC')), []) + ['plink2_cpu.cc']
    if len(names) != 87 or len(names) != len(set(names)):
        raise ValueError('Unexpected pinned Makefile CLI source inventory: ' + str(len(names)))
    return [source / name for name in names]


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--cache', type=Path, default=ROOT / 'build/plink2-cache')
    p.add_argument('--build', type=Path)
    p.add_argument('--toolchain', type=Path, default=ROOT / 'build/toolchains' / TC_NAME)
    p.add_argument('--fetch', action='store_true')
    p.add_argument('--linux', action='store_true')
    p.add_argument('--jobs', type=int, default=2)
    p.add_argument('--without-guard', action='store_true')
    a = p.parse_args()
    cache = a.cache.resolve()
    source, zlib = prepare(cache, a.fetch)
    out = (a.build or ROOT / ('build/plink2-linux' if a.linux else 'build/plink2-windows')).resolve()
    out.mkdir(parents=True, exist_ok=True)
    (out / 'tmp').mkdir(exist_ok=True)
    tc = a.toolchain.resolve()
    env = dict(os.environ, TMPDIR=str(out / 'tmp'))
    if a.linux:
        cc, cxx = shutil.which('gcc'), shutil.which('g++')
    else:
        suffix = '.exe' if os.name == 'nt' else ''
        cc, cxx = (str(tc / ('bin/x86_64-w64-mingw32-clang' + suffix)), str(tc / ('bin/x86_64-w64-mingw32-clang++' + suffix)))
        env['LD_LIBRARY_PATH'] = str(tc / 'lib')
        env['PATH'] = str(tc / 'bin') + os.pathsep + env.get('PATH', '')
    if not cc or not cxx:
        raise ValueError('Missing host GCC or pinned LLVM/MinGW compiler')
    flags = ['-O2', '-march=x86-64', '-mtune=generic', '-mno-avx', '-mno-avx2', '-mno-sse4.2', '-ffp-contract=off', '-DLIBDEFLATE_STATIC', '-DSTATIC_ZLIB', '-DNOLAPACK', '-I' + str(source / 'libdeflate'), '-I' + str(zlib)]
    zlib_sources = ['adler32', 'compress', 'crc32', 'deflate', 'gzclose', 'gzlib', 'gzread', 'gzwrite', 'infback', 'inffast', 'inflate', 'inftrees', 'trees', 'uncompr', 'zutil']
    inputs = source_files(source) + [zlib / (name + '.c') for name in zlib_sources]
    def compile_one(index_path):
        index, path = index_path
        obj = out / ('source-' + str(index) + '.o')
        cpp = path.suffix == '.cc'
        cmd = [cxx if cpp else cc, *flags, '-std=gnu++17' if cpp else '-std=gnu99', *(['-fno-exceptions', '-include', 'math.h'] if cpp else []), '-c', str(path), '-o', str(obj)]
        result = subprocess.run(cmd, cwd=out, env=env, text=True, capture_output=True)
        (out / ('source-' + str(index) + '.log')).write_text(result.stdout + result.stderr)
        if result.returncode:
            raise RuntimeError('Compile failed for ' + str(path) + ':\n' + result.stderr)
        return obj, cmd
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, a.jobs)) as pool:
        built = list(pool.map(compile_one, enumerate(inputs)))
    commands = [item[1] for item in built]
    suffix = '' if a.linux else '.exe'
    binary = out / ('plink2' + suffix)
    link = ['-pthread'] if a.linux else ['-static', '-Wl,--no-insert-timestamp', '-Xlinker', '--stack', '-Xlinker', '8388608,65536']
    cmd = [cxx, *[str(item[0]) for item in built], '-lm', *link, '-o', str(binary)]
    subprocess.run(cmd, cwd=out, env=env, check=True)
    commands.append(cmd)
    files = [binary]
    guard = ROOT / 'tools/plink2/guard.cpp'
    if not a.without_guard:
        executable = out / ('plink2-guard' + suffix)
        cmd = [cxx, '-O2', '-std=c++17', '-march=x86-64', '-mno-avx', '-mno-avx2', '-Wall', '-Wextra', '-Werror', str(guard), *link, '-o', str(executable)]
        subprocess.run(cmd, cwd=out, env=env, check=True)
        commands.append(cmd)
        files.append(executable)
    record = {'schema': 1, 'tool': 'plink2', 'version': VERSION, 'upstreamVersion': UPSTREAM_VERSION, 'sourceCommit': SOURCE_COMMIT, 'upstreamCommit': SOURCE_COMMIT, 'sources': SOURCES, 'platform': 'linux-x86_64' if a.linux else 'windows-x86_64', 'cpuBaseline': 'baseline x86-64; no SSE4.2/AVX/AVX2 requirement', 'lapack': False, 'buildRoute': 'Pinned upstream Makefile.src CLI inventory; NOLAPACK, static bundled compression libraries and pinned zlib; no source modifications', 'upstreamSourceUnmodified': True, 'upstreamScientificAlgorithmsUnmodified': True, 'executionTestsPerformedByBuild': False, 'builderSha256': sha(Path(__file__)), 'compiler': subprocess.check_output([cc, '--version'], env=env, text=True).splitlines()[0], 'compilerSha256': sha(cc), 'commands': commands, 'files': {}}
    if len(files) == 2:
        record.update(guardSourceSha256=sha(guard), guardCompiler=subprocess.check_output([cxx, '--version'], env=env, text=True).splitlines()[0], guardCompilerSha256=sha(cxx))
    for file in files:
        info = {'bytes': file.stat().st_size, 'sha256': sha(file)}
        if not a.linux:
            inspect = tc / ('bin/llvm-readobj' + ('.exe' if os.name == 'nt' else ''))
            data = subprocess.check_output([str(inspect), '--coff-imports', str(file)], env=env, text=True)
            (out / (file.stem + '.imports.txt')).write_text(data)
            imports = re.findall(r'^\s*Name:\s*(\S+)\s*$', data, re.M)
            if not imports or any(name.lower() not in {'kernel32.dll', 'msvcrt.dll', 'ucrtbase.dll', 'advapi32.dll', 'user32.dll'} and not name.lower().startswith('api-ms-win-crt-') for name in imports):
                raise ValueError('Unexpected Windows dependency: ' + repr(imports))
            info['imports'] = sorted(imports)
        record['files'][file.name] = info
    notices = out / 'compiler-notices'
    notices.mkdir(exist_ok=True)
    if not a.linux:
        candidates = [tc / 'LICENSE.TXT', *sorted((tc / 'x86_64-w64-mingw32/share/mingw32').glob('COPYING*'))]
        if not all(path.is_file() for path in candidates) or len(candidates) < 2:
            raise ValueError('Missing compiler/runtime notices')
        for path in candidates:
            shutil.copyfile(path, notices / path.name)
        record['toolchainFiles'] = {str(path.relative_to(tc)): sha(path) for path in (tc / 'bin/clang', tc / 'bin/lld', tc / 'LICENSE.TXT') if path.is_file()}
    record['compilerNotices'] = {path.name: sha(path) for path in sorted(notices.iterdir()) if path.is_file()}
    (out / 'build.json').write_text(json.dumps(record, indent=2) + '\n')
    print(json.dumps({'build': str(out), 'files': record['files']}, indent=2))


if __name__ == '__main__':
    main()
