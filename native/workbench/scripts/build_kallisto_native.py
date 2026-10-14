#!/usr/bin/env python3
"""Reproduce native kallisto 0.52.0-workbench2 without a Unix runtime on Windows."""
import argparse, concurrent.futures, difflib, hashlib, json, os, re, shutil, subprocess, tarfile, urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VERSION = '0.52.0-workbench2'
SOURCE_COMMIT = '4e9f29cf3b021260415430c057a22469ca081391'
SOURCES = {
    'kallisto-v0.52.0.tar.gz': ('https://codeload.github.com/pachterlab/kallisto/tar.gz/refs/tags/v0.52.0', '68184e41706d77e409f05a598a87dacdf3cf227f18c028175e2bce8b284bdea4'),
    'zlib-1.3.2.tar.gz': ('https://zlib.net/fossils/zlib-1.3.2.tar.gz', 'b99a0b86c0ba9360ec7e78c4f1e43b1cbdf1e6936c8fa0f6835c0cd694a495a1'),
}
TC_NAME = 'llvm-mingw-20260922-ucrt-ubuntu-22.04-x86_64'

def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def prepare(cache, fetch=False):
    cache.mkdir(parents=True, exist_ok=True)
    pristine = {}
    for name, (url, checksum) in SOURCES.items():
        archive = cache / name
        if not archive.exists() and fetch:
            with urllib.request.urlopen(url, timeout=120) as response:
                archive.write_bytes(response.read())
        if not archive.exists() or sha(archive) != checksum:
            raise ValueError('Missing or changed source: ' + name + '; use --fetch')
        with tarfile.open(archive) as tar:
            for member in tar.getmembers():
                path = Path(member.name)
                if path.is_absolute() or '..' in path.parts or not (member.isfile() or member.isdir()):
                    raise ValueError('Unexpected source archive member: ' + member.name)
                if member.isfile():
                    contents = tar.extractfile(member).read()
                    destination = cache / path
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    if not destination.exists() or destination.read_bytes() != contents:
                        destination.write_bytes(contents)
                    if path.parts[0] == 'kallisto-0.52.0': pristine[str(path.relative_to('kallisto-0.52.0'))] = contents
    source = cache / 'kallisto-0.52.0'
    def change(relative, old, new, count=1):
        path = source / relative
        text = path.read_text()
        if text.count(old) != count: raise ValueError('Upstream patch context differs: ' + relative)
        path.write_text(text.replace(old, new))
    change('src/common.h', '#define KALLISTO_VERSION "0.52.0"', '#define KALLISTO_VERSION "' + VERSION + '"')
    change('ext/bifrost/src/BooPHF.h', '#include <sys/time.h>', '#include <sys/time.h>\n#include <pthread.h>')
    change('ext/bifrost/src/DataStorage.tcc', 'o.sz_link[i].load()', 'o.unitig_cs_link[i].load()')
    change('ext/bifrost/src/TinyBitmap.cpp', '#endif\n\n\n\nTinyBitmap', '#else\n#define posix_memalign_free(ptr) free(ptr)\n#endif\n\n\n\nTinyBitmap')
    change('ext/bifrost/src/TinyBitmap.cpp', 'free(tiny_bmp);', 'posix_memalign_free(tiny_bmp);', 5)
    change('ext/bifrost/src/TinyBitmap.cpp', 'free(tiny_bmp_new);', 'posix_memalign_free(tiny_bmp_new);')
    change('ext/bifrost/src/roaring.h', 'inline bool roaring_bitmap_contains(const roaring_bitmap_t *r, uint32_t val)', 'static inline bool roaring_bitmap_contains(const roaring_bitmap_t *r, uint32_t val)')
    change('ext/bifrost/src/roaring.c', 'extern inline bool roaring_bitmap_contains(const roaring_bitmap_t *r,\n                                           uint32_t val);', '/* Header contains a private inline definition for portable COFF linkage. */')
    # Upstream 0.52.0 skips *all* multithreaded bootstraps without USE_HDF5,
    # even for --plaintext. Dispatch the unchanged worker pool for plaintext
    # with no HDF5 writer; its plaintext branch never dereferences that pointer.
    change('src/main.cpp',
           '#ifdef USE_HDF5\n            BootstrapThreadPool pool(opt.threads, seeds, collection.counts, index, collection,\n                                     em.eff_lens_, opt, &writer, fl_means);\n#endif',
           '#ifdef USE_HDF5\n            BootstrapThreadPool pool(n_threads, seeds, collection.counts, index, collection,\n                                     em.eff_lens_, opt, &writer, fl_means);\n#else\n            if (opt.plaintext) {\n              BootstrapThreadPool pool(n_threads, seeds, collection.counts, index, collection,\n                                       em.eff_lens_, opt, nullptr, fl_means);\n            }\n#endif')
    changes = []
    for relative, old in sorted(pristine.items()):
        new = (source / relative).read_bytes()
        if old != new:
            changes += difflib.unified_diff(old.decode().splitlines(True), new.decode().splitlines(True), fromfile='a/' + relative, tofile='b/' + relative)
    (cache / 'workbench2.patch').write_text(''.join(changes))
    return source

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cache', type=Path, default=ROOT / 'vendor-expanded/kallisto')
    parser.add_argument('--toolchain', type=Path, default=ROOT.parent / 'toolchains' / TC_NAME)
    parser.add_argument('--fetch', action='store_true')
    parser.add_argument('--linux', action='store_true')
    parser.add_argument('--jobs', type=int, default=2)
    args = parser.parse_args()
    cache, tc = args.cache.resolve(), args.toolchain.resolve()
    source = prepare(cache, args.fetch)
    out = cache / ('build-linux' if args.linux else 'build-windows')
    out.mkdir(exist_ok=True)
    env = dict(os.environ, SOURCE_DATE_EPOCH='1740499200')
    if not args.linux: env['LD_LIBRARY_PATH'] = str(tc / 'lib')
    cxx = 'g++' if args.linux else str(tc / 'bin/x86_64-w64-mingw32-clang++')
    cc = 'gcc' if args.linux else str(tc / 'bin/x86_64-w64-mingw32-clang')
    zlib = cache / 'zlib-1.3.2'
    flags = ['-O2', '-DNDEBUG', '-DMAX_KMER_SIZE=32', '-DMAX_GMER_SIZE=32', '-DNO_HTSLIB=ON', '-DCOMPILATION_ARCH=OFF', '-DENABLE_AVX2=OFF', '-march=x86-64', '-mtune=generic', '-mno-avx', '-mno-avx2', '-I' + str(source / 'src'), '-I' + str(source / 'ext/bifrost/src'), '-I' + str(zlib), '-Wno-deprecated-declarations', '-Wno-unused-result', '-Wno-format']
    zfiles = [zlib / (name + '.c') for name in 'adler32 compress crc32 deflate gzclose gzlib gzread gzwrite infback inffast inflate inftrees trees uncompr zutil'.split()]
    files = sorted((source / 'src').glob('*.cpp')) + [p for p in sorted((source / 'ext/bifrost/src').glob('*.cpp')) if p.name != 'Bifrost.cpp'] + [source / 'ext/bifrost/src/roaring.c'] + zfiles
    helpers = [ROOT / 'tools/kallisto/adapter.cpp', ROOT / 'tools/kallisto/readcheck.c']
    def compile(path):
        obj = out / (path.name + '.o')
        command = [cxx if path.suffix == '.cpp' else cc, *(['-std=c++17'] if path.suffix == '.cpp' else ['-std=c11']), *flags, '-c', str(path), '-o', str(obj)]
        result = subprocess.run(command, env=env, capture_output=True, text=True)
        if result.returncode: raise RuntimeError(path.name + '\n' + result.stdout + result.stderr)
        return obj
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.jobs) as pool:
        objects = list(pool.map(compile, files + helpers))
    build = {'tool': 'kallisto', 'version': VERSION, 'upstreamVersion': '0.52.0', 'sourceCommit': SOURCE_COMMIT, 'sources': {name: {'url': url, 'sha256': checksum} for name, (url, checksum) in SOURCES.items()}, 'patchSha256': sha(cache / 'workbench2.patch'), 'compiler': subprocess.check_output([cxx, '--version'], env=env, text=True).splitlines()[0], 'flags': flags, 'hdf5': False, 'bam': False, 'cpu': 'x86-64 baseline; no AVX/AVX2 required', 'windowsExecuted': False, 'helperSources': {p.name: sha(p) for p in helpers}, 'files': {}}
    targets = {'kallisto': objects[:len(files)], 'kallisto-adapter': [out / 'adapter.cpp.o'], 'readcheck': [out / 'readcheck.c.o', *[out / (p.name + '.o') for p in zfiles]]}
    for name, target_objects in targets.items():
        binary = out / (name + ('' if args.linux else '.exe'))
        link = ['-pthread'] if args.linux else ['-static', '-pthread', '-lpsapi', '-Wl,--no-insert-timestamp']
        subprocess.run([cxx, *map(str, target_objects), *link, '-o', str(binary)], env=env, check=True)
        item = {'sha256': sha(binary), 'bytes': binary.stat().st_size}
        if not args.linux:
            imports = subprocess.check_output([str(tc / 'bin/llvm-readobj'), '--coff-imports', str(binary)], env=env, text=True)
            item['imports'] = re.findall(r'^  Name: (.+)$', imports, re.M)
            allowed = {'kernel32.dll', 'psapi.dll'}
            if any(value.lower() not in allowed and not value.lower().startswith('api-ms-win-crt-') for value in item['imports']):
                raise ValueError('Unexpected non-system Windows DLL import: ' + name)
            (out / (name + '.imports.txt')).write_text(imports)
        build['files'][binary.name] = item
    (out / 'build.json').write_text(json.dumps(build, indent=2) + '\n')
    print(json.dumps(build['files'], indent=2))

if __name__ == '__main__':
    main()
