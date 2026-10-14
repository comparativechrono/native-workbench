#!/usr/bin/env python3
"""Build pinned classic BWA 0.7.19 unchanged for Linux and Cosmopolitan 3.3.10.

Requirements: Linux x86-64, Python 3.12+, GCC, GNU make/binutils, zlib headers.
The source archive is included. Supply an extracted pinned Cosmopolitan compiler
with --cosmocc-root; compiler archives are not redistributed here.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tarfile

ROOT = Path(__file__).resolve().parents[1]
VENDOR = ROOT / 'vendor-expanded/bwa'
BUILD = ROOT / 'bwa-build'
URL = 'https://codeload.github.com/lh3/bwa/tar.gz/refs/tags/v0.7.19'
SOURCE_SHA256 = 'cdff5db67652c5b805a3df08c4e813a822c65791913eccfb3cf7d528588f37bc'
COSMO_SHA256 = '00d61c1215667314f66e288c8285bae38cc6137fca083e5bba6c74e3a52439de'
CFLAGS = '-g -Wall -Wno-unused-function -O3 -march=x86-64 -mtune=generic'


def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def run(command, cwd, log, env):
    with log.open('ab') as stream:
        stream.write((json.dumps(list(map(str, command))) + '\n').encode())
        stream.flush()
        subprocess.run(list(map(str, command)), cwd=cwd, env=env,
                       stdout=stream, stderr=subprocess.STDOUT, check=True)


def build(args):
    archive = VENDOR / 'archives/bwa-v0.7.19.tar.gz'
    if sha(archive) != SOURCE_SHA256:
        raise RuntimeError('Pinned BWA source archive checksum mismatch')
    (BUILD / 'tmp').mkdir(parents=True, exist_ok=True)
    binaries = ROOT / 'baselines/bin'
    binaries.mkdir(parents=True, exist_ok=True)
    env = {**os.environ, 'TMPDIR': str(BUILD / 'tmp')}
    records = []
    for target in ('linux', 'cosmo') if args.build == 'all' else (args.build,):
        directory = BUILD / target
        if directory.exists():
            shutil.rmtree(directory)
        directory.mkdir()
        with tarfile.open(archive) as tf:
            tf.extractall(directory, filter='data')
        source = directory / 'bwa-0.7.19'
        log = BUILD / f'{target}-build.log'
        log.write_text('')
        output = binaries / ('bwa-linux' if target == 'linux' else 'bwa-cosmo.exe')
        if target == 'linux':
            compiler, archiver = 'gcc', 'ar'
            includes, libs = '', '-lm -lz -lpthread -lrt'
        else:
            toolchain = args.cosmocc_root.resolve()
            compiler = str(toolchain / 'bin/x86_64-unknown-cosmo-cc')
            archiver = str(toolchain / 'bin/x86_64-unknown-cosmo-ar')
            # Upstream relies on glibc's transitive declarations; supply their
            # standard headers explicitly without editing upstream source.
            includes = ('-I' + str(toolchain / 'include/third_party/zlib') +
                        ' -D_GNU_SOURCE -include sys/select.h -include strings.h')
            libs = '-lm -lpthread'
        command = ['make', '-j2', 'bwa', 'CC=' + compiler, 'AR=' + archiver,
                   'CFLAGS=' + CFLAGS, 'INCLUDES=' + includes, 'LIBS=' + libs]
        run(command, source, log, env)
        if target == 'linux':
            shutil.copy2(source / 'bwa', output)
            link = None
        else:
            # The .exe suffix requests an APE rather than the intermediate ELF.
            # Read the object list from the verified, unmodified upstream Makefile.
            makefile = (source / 'Makefile').read_text().replace('\\\n', '')
            objects = re.search(r'^AOBJS\s*=\s*(.+)$', makefile, re.M).group(1).split()
            link = [compiler, *CFLAGS.split(), *objects, 'main.o', '-o', str(output),
                    '-L.', '-lbwa', *libs.split()]
            run(link, source, log, env)
            shutil.copy2(toolchain / 'bin/ape-x86_64.elf', binaries / 'ape-loader-linux')
        records.append({'target': target, 'file': str(output.relative_to(ROOT)),
                        'sha256': sha(output), 'bytes': output.stat().st_size,
                        'compiler': subprocess.check_output([compiler, '--version'], text=True).splitlines()[0],
                        'make_command': command, 'ape_link_command': link})
    provenance = {
        'tool': 'BWA (classic BWA-MEM)', 'version': '0.7.19-r1273',
        'source_url': URL, 'source_archive': 'archives/bwa-v0.7.19.tar.gz',
        'source_sha256': SOURCE_SHA256, 'source_changes': 'none',
        'upstream_release': 'https://github.com/lh3/bwa/releases/tag/v0.7.19',
        'license': 'GPL-3.0 (full program); bundled components retain their notices',
        'cosmopolitan': {'version': '3.3.10', 'archive_sha256': COSMO_SHA256,
                        'url': 'https://cosmo.zip/pub/cosmocc/cosmocc-3.3.10.zip'},
        'cpu': 'x86-64 baseline with SSE2; no -march=native, AVX or AVX2 requirement introduced',
        'build_changes': ['Compiler/archiver, zlib include and linker flags only',
                          'Force-include sys/select.h and strings.h for POSIX declarations',
                          'Enable _GNU_SOURCE declarations in Cosmopolitan headers',
                          'Cosmopolitan bundled namespaced zlib replaces separate -lz',
                          'Final .exe output selects APE'],
        'native_windows_execution_verified': False, 'builds': records,
    }
    (VENDOR / 'provenance.json').write_text(json.dumps(provenance, indent=2) + '\n')
    return provenance


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--build', choices=['all', 'linux', 'cosmo'], default='all')
    parser.add_argument('--cosmocc-root', type=Path, default=ROOT / 'variant-build/cosmocc-3.3.10')
    args = parser.parse_args()
    print(json.dumps(build(args), indent=2))


if __name__ == '__main__':
    main()
