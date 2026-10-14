#!/usr/bin/env python3
"""Build pinned SAMtools/BCFtools 1.24 for Linux and Cosmopolitan x86-64.

Release source archives include HTSlib 1.24 and htscodecs. No shell pipeline
or external service is required at runtime. Run with --build linux or cosmo.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import tarfile
import stat
import zipfile

ROOT = Path(__file__).resolve().parent
VENDOR = ROOT / 'vendor-variant'
BUILD = ROOT / 'variant-build'
SOURCES = {
    'samtools': '89b2a440123eeaa400392ce1736e7d60ce9041843027d76819753c5a8246bfdd',
    'bcftools': '8caddc22610ee2851666047c859bb91da0c1e32d0c2ec553db6f153ad130e46f',
}
COSMO_SHA256 = '00d61c1215667314f66e288c8285bae38cc6137fca083e5bba6c74e3a52439de'

def extract_cosmocc(archive, destination):
    """Verify the pinned compiler archive and safely preserve its symlinks."""
    with archive.open('rb') as f:
        if hashlib.file_digest(f, 'sha256').hexdigest() != COSMO_SHA256:
            raise RuntimeError('Cosmopolitan toolchain SHA256 mismatch')
    destination.mkdir(parents=True, exist_ok=True)
    root = destination.resolve()
    with zipfile.ZipFile(archive) as z:
        for member in z.infolist():
            out = root/member.filename
            if not out.resolve().is_relative_to(root): raise RuntimeError('Unsafe compiler archive path')
            if member.is_dir(): out.mkdir(parents=True, exist_ok=True); continue
            out.parent.mkdir(parents=True, exist_ok=True)
            mode = member.external_attr >> 16
            data = z.read(member)
            if stat.S_ISLNK(mode):
                target = data.decode()
                if not (out.parent/target).resolve().is_relative_to(root): raise RuntimeError('Unsafe compiler symlink')
                if out.exists() or out.is_symlink(): out.unlink()
                out.symlink_to(target)
            else:
                if out.is_symlink(): out.unlink()
                out.write_bytes(data); out.chmod(mode & 0o777 or 0o644)

def run(cmd, cwd, log, env):
    with log.open('ab') as f:
        f.write((json.dumps(list(map(str, cmd))) + '\n').encode()); f.flush()
        subprocess.run(list(map(str, cmd)), cwd=cwd, env=env, stdout=f, stderr=f, check=True)

def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--build', choices=['linux', 'cosmo', 'all'], default='all')
    ap.add_argument('--tool', choices=['samtools', 'bcftools', 'all'], default='all')
    ap.add_argument('--cosmocc-root', type=Path, default=BUILD/'cosmocc-3.3.10')
    ap.add_argument('--toolchain-archive', type=Path, help='Verify and extract pinned cosmocc-3.3.10.zip first')
    args = ap.parse_args()
    BUILD.mkdir(exist_ok=True)
    (BUILD/'tmp').mkdir(exist_ok=True)
    if args.toolchain_archive: extract_cosmocc(args.toolchain_archive.resolve(), args.cosmocc_root.resolve())
    for build in (['cosmo', 'linux'] if args.build == 'all' else [args.build]):
        for tool in (list(SOURCES) if args.tool == 'all' else [args.tool]):
            archive = VENDOR/'archives'/f'{tool}-1.24.tar.bz2'
            with archive.open('rb') as f:
                if hashlib.file_digest(f, 'sha256').hexdigest() != SOURCES[tool]:
                    raise RuntimeError(f'Source SHA256 mismatch: {archive}')
            dst = BUILD/build/tool
            if dst.exists(): shutil.rmtree(dst)
            dst.mkdir(parents=True)
            with tarfile.open(archive) as tf: tf.extractall(dst, filter='data')
            src = dst/f'{tool}-1.24'
            # Python's safe tar extraction drops execute permission. Upstream
            # configure/version scripts are explicit trusted release members.
            for script in src.rglob('*'):
                if script.is_file() and (script.name in ['configure', 'config.guess', 'config.sub', 'install-sh'] or script.suffix == '.sh'):
                    script.chmod(script.stat().st_mode | 0o111)
            log = BUILD/f'{tool}-{build}.log'; log.write_text('')
            env = {**os.environ, 'TMPDIR': str(BUILD/'tmp')}
            config = ['--disable-bz2','--disable-lzma','--disable-libcurl','--disable-gcs','--disable-s3','--disable-plugins','--disable-ref-cache','--without-libdeflate']
            config += ['--without-curses'] if tool == 'samtools' else ['--disable-bcftools-plugins','--disable-libgsl','--disable-perl-filters']
            config += ['CFLAGS=-O2 -g']
            if build == 'cosmo':
                cosmo = args.cosmocc_root.resolve()
                env['CC'] = str(cosmo/'bin/x86_64-unknown-cosmo-cc')
                env['AR'] = str(cosmo/'bin/x86_64-unknown-cosmo-ar')
                # Autoconf probes declare inflate without zlib.h; Cosmo's
                # header maps zlib names to namespaced bundled symbols.
                env['ac_cv_lib_z_inflate'] = 'yes'
                # zlib is supplied by Cosmopolitan libc; configure tests still
                # expect -lz, so provide an empty archive, not alternate code.
                shim = BUILD/'cosmo-link'; shim.mkdir(exist_ok=True)
                subprocess.run(['ar','rcs',str(shim/'libz.a')],check=True)
                config += ['CPPFLAGS=-I'+str(cosmo/'include/third_party/zlib'), 'LDFLAGS=-L'+str(shim)]
            else:
                env['CC'] = 'gcc'
            run(['sh', './configure', *config], src, log, env)
            # The expression engine is a large translation unit: compile it
            # alone to keep peak build memory bounded on teaching laptops.
            if tool == 'bcftools': run(['make', '-j1', 'filter.o'], src, log, env)
            run(['make', '-j2', tool], src, log, env)
            out = ROOT/'baselines/bin'/f'{tool}-{build}{".exe" if build == "cosmo" else ""}'
            if build == 'cosmo':
                # Output naming selects APE (PE + ELF) instead of a debug ELF.
                command = subprocess.check_output(['make', '-n', '-W', f'{tool}.c', '-W', 'version.h', tool],cwd=src,env=env,text=True)
                candidates = [shlex.split(line) for line in command.splitlines() if ' -o '+tool+' ' in line]
                if not candidates: raise RuntimeError('Final linker command not found')
                link = candidates[-1]; link[link.index('-o')+1] = str(out)
                run(link, src, log, env)
            else: shutil.copy2(src/tool, out)
            print(out, flush=True)

if __name__ == '__main__': main()
