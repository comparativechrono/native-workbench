#!/usr/bin/env python3
"""Build the native programs of native-workbench from the recipes taken over from Native Workbench, and install them.

  python3 native/build.py                 # build (in /tmp/native-workbench-build, kept for next time)
  python3 native/build.py --install       # … and put the programs into native/bin

The build tree's folder is written into some programs (SAMtools, BCFtools and HTSlib record the compiler and its
options, with their paths, for --version), so the same sources give the same bytes only in the same folder: the
programs in native/bin were built in /tmp/native-workbench-build, the default.

1. The build tree: native/workbench made complete by restore_build_tree.py, outside the repository (or one made before).
2. The toolchain, cosmocc 3.3.10, and the sources the tree lacks – SAMtools 1.24's release archive, and Cosmopolitan's
   source archive (fastp's recipe reads three licence texts from it) – each downloaded once into --cache and checked
   against its SHA-256.
3. Each program by its recipe: the Cosmopolitan executable (one file for Windows, Linux and macOS), and from the same
   sources a Linux build, the reference that tests/native-programs.mjs compares it with. bgzip and tabix are built here
   from the HTSlib of the SAMtools recipe (Native Workbench used SAMtools' own).
4. --install: each Cosmopolitan executable into native/bin/<tool>/<version>/, with its licences and a NOTICE.txt; the
   loaders that start them on Linux and macOS; programs.json (what the local runner reads) and SHA256SUMS; the source
   code of the programs under the GNU GPL into native/sources/. The Linux references stay in the build tree
   (baselines/bin/*-linux).

Linux x86-64 with gcc, g++, make, ar, bzip2, Python 3.12 or later and zlib's headers. Standard library only.
"""
import argparse
import datetime
import hashlib
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import urllib.request
import zipfile
import stat

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
BIN = HERE / 'bin'
SOURCES_DIR = HERE / 'sources'

COSMOCC = ('https://cosmo.zip/pub/cosmocc/cosmocc-3.3.10.zip', '00d61c1215667314f66e288c8285bae38cc6137fca083e5bba6c74e3a52439de')
DOWNLOADS = {
    'cosmocc-3.3.10.zip': COSMOCC,
    'samtools-1.24.tar.bz2': ('https://github.com/samtools/samtools/releases/download/1.24/samtools-1.24.tar.bz2', '89b2a440123eeaa400392ce1736e7d60ce9041843027d76819753c5a8246bfdd'),
    'cosmopolitan-3.3.10.tar.gz': ('https://cosmo.zip/pub/cosmo/cosmopolitan-3.3.10.tar.gz', '0d048b3e3928832d877a51781d2442a521c38be46965a1bc0fe2c6e82b45ed85'),
}

# The programs: what the runner calls them (name), their tool and version, the recipe, where the recipe leaves the two
# builds (in the tree), whether they can use threads (the HTSlib programs cannot: its thread pool needs a recursive
# mutex with a condition variable, which Cosmopolitan 3.3.10 refuses – "nsync panic: pthread cond needs normal mutex"),
# their licence, their upstream source, and what changed for Windows (TOOLS.md).
PROGRAMS = [
    dict(name='samtools', tool='samtools', version='1.24', recipe='variant', threads=False, licence='MIT/Expat (SAMtools); HTSlib: MIT/Expat and modified BSD',
         source=('https://github.com/samtools/samtools/releases/download/1.24/samtools-1.24.tar.bz2', '89b2a440123eeaa400392ce1736e7d60ce9041843027d76819753c5a8246bfdd'),
         recipe_files=['native/workbench/build_variant.py'], licences={'LICENSE': 'variant-build/linux/samtools/samtools-1.24/LICENSE', 'LICENSE.htslib': 'variant-build/linux/samtools/samtools-1.24/htslib-1.24/LICENSE'},
         changes='None to the source. Built without bzip2, lzma, libcurl, plugins and the reference cache; zlib is Cosmopolitan\'s. No threads (-@): see above.'),
    dict(name='bcftools', tool='bcftools', version='1.24', recipe='variant', threads=False, licence='MIT/Expat (built without GSL, so not the GPL variant); HTSlib: MIT/Expat and modified BSD',
         source=('https://github.com/samtools/bcftools/releases/download/1.24/bcftools-1.24.tar.bz2', '8caddc22610ee2851666047c859bb91da0c1e32d0c2ec553db6f153ad130e46f'),
         recipe_files=['native/workbench/build_variant.py'], licences={'LICENSE': 'variant-build/linux/bcftools/bcftools-1.24/LICENSE', 'LICENSE.htslib': 'variant-build/linux/bcftools/bcftools-1.24/htslib-1.24/LICENSE'},
         changes='None to the source. Built without plugins, GSL, Perl filters, bzip2, lzma and libcurl. No threads (--threads).'),
    dict(name='bgzip', tool='htslib', version='1.24', recipe='htslib', threads=False, licence='MIT/Expat and modified BSD',
         source=('https://github.com/samtools/samtools/releases/download/1.24/samtools-1.24.tar.bz2', '89b2a440123eeaa400392ce1736e7d60ce9041843027d76819753c5a8246bfdd'),
         recipe_files=['native/build.py', 'native/workbench/build_variant.py'], licences={'LICENSE': 'variant-build/linux/samtools/samtools-1.24/htslib-1.24/LICENSE'},
         changes='None to the source: the HTSlib 1.24 inside SAMtools 1.24\'s release, as configured by the SAMtools recipe. No threads (-@).'),
    dict(name='tabix', tool='htslib', version='1.24', recipe='htslib', threads=False, licence='MIT/Expat and modified BSD',
         source=('https://github.com/samtools/samtools/releases/download/1.24/samtools-1.24.tar.bz2', '89b2a440123eeaa400392ce1736e7d60ce9041843027d76819753c5a8246bfdd'),
         recipe_files=['native/build.py', 'native/workbench/build_variant.py'], licences={'LICENSE': 'variant-build/linux/samtools/samtools-1.24/htslib-1.24/LICENSE'},
         changes='None to the source (as bgzip).'),
    dict(name='minimap2', tool='minimap2', version='2.28', recipe='upstream', threads=True, licence='MIT',
         source=('https://codeload.github.com/lh3/minimap2/tar.gz/refs/tags/v2.28', '5ea6683b4184b5c49f6dbaef2bc5b66155e405888a0790d1b21fd3c93e474278'),
         recipe_files=['native/workbench/baselines/build_upstream.py', 'native/workbench/vendor/provenance.json'], licences={'LICENSE': 'baselines/build/rebuild-linux/minimap2-2.28/LICENSE.txt'},
         changes='None to the source. Mapping threads (-t) work.'),
    dict(name='seqtk', tool='seqtk', version='1.4', recipe='upstream', threads=False, licence='MIT',
         source=('https://codeload.github.com/lh3/seqtk/tar.gz/refs/tags/v1.4', 'd124604ec24f29ed14ce127426ab90e0f3a2c0280c80d1a3ff8b1c09feede19c'),
         recipe_files=['native/workbench/baselines/build_upstream.py', 'native/workbench/vendor/provenance.json'], licences={'LICENSE': 'baselines/build/rebuild-linux/seqtk-1.4/LICENSE'},
         changes='None to the source.'),
    dict(name='bwa', tool='bwa', version='0.7.19', recipe='bwa', threads=True, licence='GNU GPL 3', gpl=True,
         source=('https://codeload.github.com/lh3/bwa/tar.gz/refs/tags/v0.7.19', 'cdff5db67652c5b805a3df08c4e813a822c65791913eccfb3cf7d528588f37bc'),
         recipe_files=['native/workbench/tools/build_bwa.py'], licences={'COPYING': 'bwa-build/linux/bwa-0.7.19/COPYING'},
         gpl_sources=['vendor-expanded/bwa/archives/bwa-v0.7.19.tar.gz'],
         changes='None to the source. Mapping threads (-t) work.'),
    dict(name='freebayes', tool='freebayes', version='1.3.10', recipe='freebayes', threads=False, licence='MIT; it contains libdisorder (GNU GPL 2 or later), so the program is distributed under the GPL', gpl=True,
         source=('https://github.com/freebayes/freebayes/releases/download/v1.3.10/freebayes-1.3.10-src.tar.gz', 'f828738176b38987d40cd8180d68d77af90163384f4ed9a16bb05cfa2fdb5a71'),
         recipe_files=['native/workbench/tools/build_freebayes.py', 'native/workbench/vendor-expanded/freebayes/compat/'], licences={'licenses': 'vendor-expanded/freebayes/licenses'},
         gpl_sources=['vendor-expanded/freebayes/archives/freebayes-1.3.10-src.tar.gz', 'vendor-expanded/freebayes/archives/tabixpp-v1.1.2.tar.gz', 'vendor-expanded/freebayes/archives/intervaltree-aa593775.tar.gz', 'vendor-expanded/freebayes/archives/simde-v0.8.2.tar.gz'],
         changes='off_t in place of glibc\'s __off64_t; no backtrace after a crash (it prints the signal instead); llrintl from musl 1.2.5. Built with the HTSlib 1.24 of the SAMtools recipe.'),
    dict(name='fastp', tool='fastp', version='1.3.7', recipe='fastp', threads=True, licence='MIT; ISA-L: BSD 3-clause; libdeflate: MIT; Highway: Apache 2.0 or BSD 3-clause; Plotly.js 1.2.0 (the report\'s plots): MIT; libc++, libc++abi, libunwind: Apache 2.0 with LLVM exceptions',
         source=('https://codeload.github.com/OpenGene/fastp/tar.gz/refs/tags/v1.3.7', '5b7d6880c66e9e10e5923c68ee0c0b5a30f59bd252d836c379c74f8533c26993'),
         recipe_files=['native/workbench/tools/build_fastp.py', 'native/workbench/vendor-expanded/fastp-offline-report.patch'], licences={'licenses': 'vendor-expanded/fastp-licenses'},
         assets={'plotly-1.2.0.min.js': 'vendor-expanded/fastp-assets/plotly-1.2.0.min.js'},
         changes='The HTML report loads Plotly from a file next to it (plotly-1.2.0.min.js, which the runner puts there) instead of from the web, and its command line and title are escaped; the JSON report escapes the command line. No change to trimming or filtering.'),
]
OUTPUTS = {  # recipe → where it leaves the builds of a program (relative to the tree): {target: path}
    'variant': lambda n: {'cosmo': f'baselines/bin/{n}-cosmo.exe', 'linux': f'baselines/bin/{n}-linux'},
    'htslib': lambda n: {'cosmo': f'baselines/bin/{n}-cosmo.exe', 'linux': f'baselines/bin/{n}-linux'},
    'upstream': lambda n: {'cosmo': f'baselines/bin/{n}-cosmo.exe', 'linux': f'baselines/bin/{n}-linux'},
    'bwa': lambda n: {'cosmo': 'baselines/bin/bwa-cosmo.exe', 'linux': 'baselines/bin/bwa-linux'},
    'freebayes': lambda n: {'cosmo': 'baselines/bin/freebayes-cosmo.exe', 'linux': 'baselines/bin/freebayes-linux'},
    'fastp': lambda n: {'cosmo': 'baselines/bin/fastp-cosmo.exe', 'linux': 'baselines/bin/fastp-linux'},
}


def sha256(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def fetch(cache, name):
    url, digest = DOWNLOADS[name]
    cache.mkdir(parents=True, exist_ok=True)
    path = cache / name
    if not path.exists():
        print(f'downloading {url}', flush=True)
        part = path.with_suffix(path.suffix + '.part')
        with urllib.request.urlopen(url, timeout=300) as r, open(part, 'wb') as f:
            shutil.copyfileobj(r, f)
        part.rename(path)
    if sha256(path) != digest:
        sys.exit(f'{path}: not the expected SHA-256 ({digest})')
    return path


def run(cmd, cwd, log=None):
    print('  $ ' + ' '.join(shlex.quote(str(c)) for c in cmd), flush=True)
    if log:
        with open(log, 'ab') as f:
            subprocess.run([str(c) for c in cmd], cwd=cwd, stdout=f, stderr=f, check=True)
    else:
        subprocess.run([str(c) for c in cmd], cwd=cwd, check=True)


def prepare_tree(tree, cache):
    if not tree.exists():
        companion = cache / 'native-workbench-0.16.0-source.zip'
        args = [sys.executable, str(HERE / 'restore_build_tree.py'), '--out', str(tree)]
        if companion.exists():
            args += ['--companion', str(companion)]
        run(args, REPO)
    cosmo = tree / 'variant-build' / 'cosmocc-3.3.10'
    if not (cosmo / 'bin' / 'x86_64-unknown-cosmo-cc').exists():
        archive = fetch(cache, 'cosmocc-3.3.10.zip')
        # (the recipe's own extraction: it keeps the toolchain's links and checks every path)
        sys.path.insert(0, str(tree))
        try:
            from build_variant import extract_cosmocc
        finally:
            sys.path.pop(0)
        extract_cosmocc(archive, cosmo)
    loader = tree / 'baselines' / 'bin' / 'ape-loader-linux'
    if not loader.exists():
        loader.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(cosmo / 'bin' / 'ape-x86_64.elf', loader)
    archives = tree / 'vendor-variant' / 'archives'
    archives.mkdir(parents=True, exist_ok=True)
    if not (archives / 'samtools-1.24.tar.bz2').exists():
        shutil.copy2(fetch(cache, 'samtools-1.24.tar.bz2'), archives / 'samtools-1.24.tar.bz2')
    if not (tree / 'variant-build' / 'cosmopolitan-3.3.10.tar.gz').exists():
        shutil.copy2(fetch(cache, 'cosmopolitan-3.3.10.tar.gz'), tree / 'variant-build' / 'cosmopolitan-3.3.10.tar.gz')
    return cosmo


def link_command(src_dir, target, out):
    """the command make would link `target` with in src_dir, writing `out` instead (an .exe name: Cosmopolitan then
    writes the portable executable)"""
    text = subprocess.check_output(['make', '-n', '-W', f'{target}.o', target], cwd=src_dir, text=True)
    lines = [shlex.split(l) for l in text.splitlines() if f' -o {target} ' in l]
    if not lines:
        raise SystemExit(f'the command that links {target} was not found')
    cmd = lines[-1]
    cmd[cmd.index('-o') + 1] = str(out)
    return cmd


def build_htslib_tools(tree, names):
    for target in ('cosmo', 'linux'):
        src = tree / 'variant-build' / target / 'samtools' / 'samtools-1.24' / 'htslib-1.24'
        if not (src / 'libhts.a').exists():
            raise SystemExit(f'build SAMtools first (its HTSlib): {src}')
        log = tree / 'variant-build' / f'htslib-tools-{target}.log'
        run(['make', '-j2', 'libhts.a'] + [f'{n}.o' for n in names], src, log)
        for n in names:
            out = tree / 'baselines' / 'bin' / (f'{n}-cosmo.exe' if target == 'cosmo' else f'{n}-linux')
            if target == 'cosmo':
                run(link_command(src, n, out), src, log)
            else:
                run(['make', n], src, log)
                shutil.copy2(src / n, out)


def build(tree, cosmo, recipe, names, jobs):
    py = sys.executable
    if recipe == 'variant':
        for n in names:
            run([py, 'build_variant.py', '--build', 'all', '--tool', n], tree)
    elif recipe == 'htslib':
        build_htslib_tools(tree, names)
    elif recipe == 'upstream':
        run([py, 'baselines/build_upstream.py', '--cosmocc-root', str(cosmo)], tree)
    elif recipe == 'bwa':
        run([py, 'tools/build_bwa.py', '--build', 'all', '--cosmocc-root', str(cosmo)], tree)
    elif recipe == 'freebayes':
        run([py, 'tools/build_freebayes.py', '--target', 'all', '--cosmocc-root', str(cosmo), '--jobs', str(jobs)], tree)
    elif recipe == 'fastp':
        run([py, 'tools/build_fastp.py', '--build', 'all', '--cosmocc-root', str(cosmo), '--cosmo-source-archive', str(tree / 'variant-build' / 'cosmopolitan-3.3.10.tar.gz'), '--jobs', str(jobs)], tree)
    else:
        raise SystemExit('no recipe ' + recipe)


def copy_licences(tree, prog, dest):
    for name, rel in prog.get('licences', {}).items():
        src = tree / rel
        if src.is_dir():
            shutil.copytree(src, dest / name, dirs_exist_ok=True)
        elif src.exists():
            shutil.copy2(src, dest / name)
        else:
            raise SystemExit(f'{prog["name"]}: licence file {rel} not found in the build tree')


def install(tree, progs):
    BIN.mkdir(exist_ok=True)
    cosmo = tree / 'variant-build' / 'cosmocc-3.3.10'
    manifest_path = BIN / 'programs.json'
    manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {}
    manifest.update({
        'schema': 1,
        'about': 'The native programs of the local runner (runner/native.mjs), written by native/build.py. Each is a '
                 'Cosmopolitan "actually portable executable": a Windows program, and on Linux and macOS (x86-64) one '
                 'that the loader for that system starts.',
        'toolchain': {'name': 'cosmocc', 'version': '3.3.10', 'url': COSMOCC[0], 'sha256': COSMOCC[1]},
    })
    loaders = {}
    for key, name in (('linux-x64', 'ape-x86_64.elf'), ('darwin-x64', 'ape-x86_64.macho')):
        shutil.copy2(cosmo / 'bin' / name, BIN / name)
        os.chmod(BIN / name, 0o755)
        loaders[key] = {'file': name, 'sha256': sha256(BIN / name)}
    manifest['loaders'] = loaders
    # the notices of Cosmopolitan's own C library, which every program contains (ISC, and its parts' licences)
    shutil.copytree(tree / 'baselines' / 'licenses' / 'cosmopolitan-3.3.10', BIN / 'licenses' / 'cosmopolitan-3.3.10', dirs_exist_ok=True)
    entries = {e['name']: e for e in manifest.get('programs', [])}
    today = datetime.date.today().isoformat()
    for p in progs:
        out = tree / OUTPUTS[p['recipe']](p['name'])['cosmo']
        dest = BIN / p['tool'] / p['version']
        dest.mkdir(parents=True, exist_ok=True)
        exe = dest / f'{p["name"]}.exe'
        shutil.copy2(out, exe)
        os.chmod(exe, 0o644)
        copy_licences(tree, p, dest)
        for name, rel in p.get('assets', {}).items():
            shutil.copy2(tree / rel, dest / name)
        digest = sha256(exe)
        url, src_sha = p['source']
        notice = [f'{p["name"]} {p["version"]} – native build for the local runner of native-workbench', '',
                  f'File: {exe.name} ({exe.stat().st_size} bytes), SHA-256 {digest}',
                  'What it is: a Cosmopolitan "actually portable executable" – a Windows program; on Linux and macOS (x86-64) '
                  'the loader in native/bin starts it.',
                  f'Licence: {p["licence"]} (the licence files in this folder); Cosmopolitan\'s C library, which it contains: '
                  'ISC, with the notices of its parts in native/bin/licenses/cosmopolitan-3.3.10.',
                  f'Source: {url}' + (f' (SHA-256 {src_sha})' if src_sha else ' (pinned in the recipe\'s provenance file)'),
                  f'Recipe: {", ".join(p["recipe_files"])}, run by native/build.py with cosmocc 3.3.10 ({COSMOCC[0]}, SHA-256 {COSMOCC[1]}).',
                  f'Changes: {p["changes"]}',
                  f'Threads: {"yes" if p["threads"] else "no – the terminal leaves the option out, with a note"}.']
        if p.get('gpl'):
            notice.append('Its source code, as the GNU GPL asks, is in native/sources/ (see the README there); the recipe and '
                          'any changes are in this repository.')
        notice.append(f'Built and installed on {today}.')
        (dest / 'NOTICE.txt').write_text('\n'.join(notice) + '\n')
        entries[p['name']] = {'name': p['name'], 'tool': p['tool'], 'version': p['version'], 'kind': 'cosmopolitan',
                              'file': f'{p["tool"]}/{p["version"]}/{exe.name}', 'sha256': digest, 'bytes': exe.stat().st_size,
                              'threads': p['threads'], 'licence': p['licence'], 'source': url, 'sourceSha256': src_sha,
                              'recipe': p['recipe_files'], 'assets': sorted(p.get('assets', {}))}
        if p.get('gpl'):
            SOURCES_DIR.mkdir(exist_ok=True)
            for rel in p['gpl_sources']:
                shutil.copy2(tree / rel, SOURCES_DIR / Path(rel).name)
        print(f'installed {p["name"]} {p["version"]}: {exe.relative_to(REPO)} {digest[:16]}…', flush=True)
    manifest['programs'] = [entries[k] for k in sorted(entries)]
    manifest_path.write_text(json.dumps(manifest, indent=1) + '\n')
    sums = []
    for f in sorted(BIN.rglob('*')):
        if f.is_file() and f.name != 'SHA256SUMS':
            sums.append(f'{sha256(f)}  {f.relative_to(BIN).as_posix()}')
    (BIN / 'SHA256SUMS').write_text('\n'.join(sums) + '\n')
    if SOURCES_DIR.exists():
        (SOURCES_DIR / 'SHA256SUMS').write_text(''.join(f'{sha256(f)}  {f.name}\n' for f in sorted(SOURCES_DIR.iterdir()) if f.is_file() and f.suffix in ('.gz', '.bz2', '.xz')))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--tree', type=Path, default=Path('/tmp/native-workbench-build'), help='the build tree (made if it is not there; outside the repository). Default /tmp/native-workbench-build: the folder the programs in native/bin were built in')
    ap.add_argument('--cache', type=Path, default=Path.home() / '.cache' / 'native-workbench', help='downloads (default ~/.cache/native-workbench)')
    ap.add_argument('--programs', default='all', help='comma-separated names (default all: ' + ','.join(p['name'] for p in PROGRAMS) + ')')
    ap.add_argument('--jobs', type=int, default=2)
    ap.add_argument('--rebuild', action='store_true', help='build again what is built already')
    ap.add_argument('--install', action='store_true', help='put the Cosmopolitan executables into native/bin')
    ap.add_argument('--install-only', action='store_true', help='install what the tree has built, without building')
    a = ap.parse_args()
    tree = a.tree.resolve()
    if tree == REPO or REPO in tree.parents:
        sys.exit('the build tree must be outside the repository')
    wanted = [p for p in PROGRAMS if a.programs == 'all' or p['name'] in a.programs.split(',')]
    if not wanted:
        sys.exit('no such program: ' + a.programs)
    cosmo = prepare_tree(tree, a.cache.resolve())
    if not a.install_only:
        # one recipe at a time, in this order (bgzip and tabix and FreeBayes use the HTSlib of the SAMtools recipe)
        order = ['variant', 'htslib', 'upstream', 'bwa', 'freebayes', 'fastp']
        if any(p['recipe'] in ('htslib', 'freebayes') for p in wanted) and not (tree / 'variant-build/linux/samtools/samtools-1.24/htslib-1.24/libhts.a').exists():
            wanted = [p for p in PROGRAMS if p['name'] == 'samtools'] + [p for p in wanted if p['name'] != 'samtools']
        for recipe in order:
            names = [p['name'] for p in wanted if p['recipe'] == recipe]
            if not names:
                continue
            missing = [n for n in names for t in OUTPUTS[recipe](n).values() if not (tree / t).exists()]
            if missing or a.rebuild:
                print(f'== {recipe}: {", ".join(names)}', flush=True)
                build(tree, cosmo, recipe, names, a.jobs)
            else:
                print(f'== {recipe}: {", ".join(names)} (built already)', flush=True)
    for p in wanted:
        for target, rel in OUTPUTS[p['recipe']](p['name']).items():
            if not (tree / rel).exists():
                sys.exit(f'{p["name"]}: the {target} build is missing ({rel})')
    if a.install or a.install_only:
        install(tree, wanted)
    print('done. Linux references: ' + str(tree / 'baselines' / 'bin'))


if __name__ == '__main__':
    main()
