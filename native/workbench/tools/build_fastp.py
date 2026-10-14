#!/usr/bin/env python3
"""Build pinned real fastp with static upstream dependencies.

No trimming algorithm is replaced. ISA-L uses its upstream C/noarch backend;
Highway and libdeflate retain runtime x86 dispatch. Reporting-only patches
use local HTML chart assets and escape command/title text for JSON and HTML.
Builds require GCC/G++, ar and the existing Cosmopolitan 3.3.10 toolchain.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
import difflib
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tarfile

ROOT = Path(__file__).resolve().parents[1]
VENDOR = ROOT / 'vendor-expanded'
BUILD = ROOT / 'fastp-build'
SOURCES = {
    'fastp-1.3.7': ('fastp-v1.3.7.tar.gz', '5b7d6880c66e9e10e5923c68ee0c0b5a30f59bd252d836c379c74f8533c26993',
                    'https://codeload.github.com/OpenGene/fastp/tar.gz/refs/tags/v1.3.7'),
    'isa-l-2.32.1': ('isa-l-v2.32.1.tar.gz', 'd9f7179ab0e14a3db9b610fac22793854a1435e8423ec9ce07f4cbedc5f92f5e',
                    'https://codeload.github.com/intel/isa-l/tar.gz/refs/tags/v2.32.1'),
    'libdeflate-1.26': ('libdeflate-v1.26.tar.gz', 'bba03fffc5538576213675ce6968fcff6ce2e67d82e4d5febea2d05f9f13cf85',
                       'https://codeload.github.com/ebiggers/libdeflate/tar.gz/refs/tags/v1.26'),
    'highway-1.3.0': ('highway-1.3.0.tar.gz', '07b3c1ba2c1096878a85a31a5b9b3757427af963b1141ca904db2f9f4afe0bc2',
                    'https://codeload.github.com/google/highway/tar.gz/refs/tags/1.3.0'),
}
PLOTLY_SHA = '60169d9df25530f1d5e29c663ceb18ea7492862acb308800fc5ab0f0bf31a41e'
PLOTLY_SOURCE_SHA = '1169b79526878ee915c12fefc375930f9249f4ac9c265b0300da7c9d14569f9d'
PLOTLY_LICENSE_SHA = '891d94cad73e4fdf9abc46c39468d145545f74e2d4ab43abe74b7ed299f2e484'
COSMO_SOURCE_SHA = '1ecfd628305e844f7d8ded53742e4a7f2b908b4ad2e9fb423c81595986f5b2ff'
ISAL_SOURCES = [
    'igzip/igzip.c', 'igzip/hufftables_c.c', 'igzip/igzip_base.c',
    'igzip/igzip_icf_base.c', 'igzip/adler32_base.c', 'igzip/flatten_ll.c',
    'igzip/encode_df.c', 'igzip/igzip_icf_body.c', 'igzip/igzip_base_aliases.c',
    'igzip/proc_heap_base.c', 'igzip/huff_codes.c', 'igzip/igzip_inflate.c',
    'crc/crc_base.c', 'crc/crc64_base.c', 'crc/crc_base_aliases.c',
]
DEFLATE_SOURCES = ['lib/utils.c', 'lib/x86/cpu_features.c', 'lib/arm/cpu_features.c',
    'lib/deflate_compress.c', 'lib/deflate_decompress.c', 'lib/adler32.c',
    'lib/zlib_compress.c', 'lib/zlib_decompress.c', 'lib/crc32.c',
    'lib/gzip_compress.c', 'lib/gzip_decompress.c']
HWY_SOURCES = ['hwy/abort.cc', 'hwy/aligned_allocator.cc', 'hwy/targets.cc', 'hwy/per_target.cc']
JSON_ESCAPE = r'''
// Native Workbench reporting-only fix: preserve Windows paths and UTF-8 text.
static string escapeReportJson(const string& value) {
    static const char hex[] = "0123456789abcdef";
    string escaped;
    for (unsigned char c : value) {
        if (c == '"' || c == '\\') {
            escaped += '\\';
            escaped += static_cast<char>(c);
        } else if (c < 0x20) {
            escaped += "\\u00";
            escaped += hex[c >> 4];
            escaped += hex[c & 15];
        } else {
            escaped += static_cast<char>(c);
        }
    }
    return escaped;
}
'''
HTML_ESCAPE = r'''
// Native Workbench reporting-only fix: dynamic text is not HTML markup.
static string escapeReportHtml(const string& value) {
    string escaped;
    for (char c : value) {
        switch (c) {
            case '&': escaped += "&amp;"; break;
            case '<': escaped += "&lt;"; break;
            case '>': escaped += "&gt;"; break;
            case '"': escaped += "&quot;"; break;
            case '\'': escaped += "&#39;"; break;
            default: escaped += c;
        }
    }
    return escaped;
}
'''
PATCH_NOTES = [
    'HTML charts use bundled Plotly; no remote fallback or cloud-sharing controls.',
    'JSON command text escapes backslashes, double quotes and all control bytes; UTF-8 is preserved.',
    'HTML command and report-title text is escaped as text, not interpreted as markup.',
    'No adapter trimming, quality filtering, read processing or compression algorithms changed.',
]


def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def prepare(cosmo_source_archive):
    BUILD.mkdir(parents=True, exist_ok=True)
    for name, (archive, digest, _) in SOURCES.items():
        path = VENDOR / 'archives' / archive
        if sha(path) != digest:
            raise RuntimeError(f'Source archive SHA-256 mismatch: {path}')
        destination = BUILD / 'sources' / name
        if not destination.exists():
            destination.parent.mkdir(parents=True, exist_ok=True)
            with tarfile.open(path) as stream:
                stream.extractall(destination.parent, filter='data')
    source = BUILD / 'sources/fastp-1.3.7/src/htmlreporter.cpp'
    # Reconstruct the reporting files from the pinned archive every time, so
    # reruns cannot silently stack transformations or retain an older patch.
    reporting_files = ['htmlreporter.cpp', 'stats.cpp', 'jsonreporter.cpp']
    with tarfile.open(VENDOR / 'archives' / SOURCES['fastp-1.3.7'][0]) as archive:
        for name in reporting_files:
            (source.parent / name).write_bytes(archive.extractfile('fastp-1.3.7/src/' + name).read())
    text = source.read_text()
    if 'https://opengene.org/plotly-1.2.0.min.js' in text:
        text = text.replace('https://opengene.org/plotly-1.2.0.min.js', 'plotly-1.2.0.min.js')
        text = '\n'.join(line for line in text.split('\n') if 'window.Plotly || document.write' not in line)
        source.write_text(text)
    if 'cdn.plot.ly' in text or 'https://opengene.org/plotly' in text:
        raise RuntimeError('Offline HTML patch did not remove remote script loading')
    for name in ['htmlreporter.cpp', 'stats.cpp']:
        path = source.parent / name
        text = path.read_text()
        text = text.replace('data, layout);', "data, layout, {showLink:false, sendData:false, modeBarButtonsToRemove:['sendDataToCloud']});")
        path.write_text(text)
    text = source.read_text()
    text = text.replace('#include "htmlreporter.h"', '#include "htmlreporter.h"\n' + HTML_ESCAPE, 1)
    text = text.replace('<<command<<', '<<escapeReportHtml(command)<<')
    text = text.replace('+ mOptions->reportTitle +', '+ escapeReportHtml(mOptions->reportTitle) +')
    if '<<command<<' in text or '+ mOptions->reportTitle +' in text:
        raise RuntimeError('HTML text escaping patch failed')
    source.write_text(text)
    json_source = source.parent / 'jsonreporter.cpp'
    text = json_source.read_text()
    if text.count('<< command <<') != 1:
        raise RuntimeError('Unexpected upstream JSON command serialization')
    text = text.replace('#include "jsonreporter.h"', '#include "jsonreporter.h"\n' + JSON_ESCAPE, 1)
    text = text.replace('<< command <<', '<< escapeReportJson(command) <<')
    json_source.write_text(text)
    with tarfile.open(VENDOR / 'archives' / SOURCES['fastp-1.3.7'][0]) as archive:
        patch = []
        for name in reporting_files:
            original = archive.extractfile('fastp-1.3.7/src/' + name).read().decode().splitlines(True)
            updated = (source.parent / name).read_text().splitlines(True)
            patch.extend(difflib.unified_diff(original, updated, fromfile='a/src/'+name, tofile='b/src/'+name))
        (VENDOR / 'fastp-offline-report.patch').write_text(''.join(patch))
    plotly = VENDOR / 'archives/plotly-1.2.0.min.js'
    if sha(plotly) != PLOTLY_SHA:
        raise RuntimeError('Plotly asset SHA-256 mismatch')
    if sha(VENDOR / 'archives/plotly-1.2.0.js') != PLOTLY_SOURCE_SHA or \
       sha(VENDOR / 'archives/plotly-1.2.0-LICENSE.txt') != PLOTLY_LICENSE_SHA:
        raise RuntimeError('Plotly readable source/license SHA-256 mismatch')
    assets = VENDOR / 'fastp-assets'
    assets.mkdir(exist_ok=True)
    shutil.copy2(plotly, assets / plotly.name)
    licenses = VENDOR / 'fastp-licenses'
    licenses.mkdir(exist_ok=True)
    for name, src in {
        'fastp-MIT-LICENSE.txt': BUILD / 'sources/fastp-1.3.7/LICENSE',
        'isa-l-BSD3-LICENSE.txt': BUILD / 'sources/isa-l-2.32.1/LICENSE',
        'libdeflate-MIT-LICENSE.txt': BUILD / 'sources/libdeflate-1.26/COPYING',
        'highway-Apache2-LICENSE.txt': BUILD / 'sources/highway-1.3.0/LICENSE',
        'highway-BSD3-LICENSE.txt': BUILD / 'sources/highway-1.3.0/LICENSE-BSD3',
        'plotly-MIT-LICENSE.txt': VENDOR / 'archives/plotly-1.2.0-LICENSE.txt',
    }.items():
        shutil.copy2(src, licenses / name)
    if sha(cosmo_source_archive) != COSMO_SOURCE_SHA:
        raise RuntimeError('Cosmopolitan source archive SHA-256 mismatch')
    with tarfile.open(cosmo_source_archive) as archive:
        for name in ['libcxx', 'libcxxabi', 'libunwind']:
            data = archive.extractfile(f'cosmopolitan-3.3.10/third_party/{name}/LICENSE.TXT').read()
            (licenses / f'cosmopolitan-{name}-LICENSE.txt').write_bytes(data)
    patch = ('Fastp 1.3.7: src/htmlreporter.cpp remote Plotly script URL replaced with '
             'plotly-1.2.0.min.js; remote CDN fallback removed. Place the bundled '
             'Plotly asset beside each HTML report. All plots disable cloud-sharing '
             'controls and links. JSON command text escapes backslashes, quotes '
             'and control bytes while preserving UTF-8. HTML command and report '
             'title are escaped as text. No adapter/quality algorithms changed.\n'
             'ISA-L 2.32.1 uses its upstream noarch C source backend. Highway 1.3.0 '
             'and libdeflate 1.26 retain x86 runtime SIMD dispatch. All dependency '
             'libraries are statically linked into each fastp binary.\n')
    (licenses / 'BUILD-NOTES.txt').write_text(patch)


def build(target, cosmo, jobs):
    directory = BUILD / target
    directory.mkdir(exist_ok=True)
    temporary = BUILD / 'tmp'
    temporary.mkdir(exist_ok=True)
    env = {**os.environ, 'TMPDIR': str(temporary)}
    if target == 'cosmo':
        cc, cxx = [str(cosmo / 'bin' / name) for name in
                   ['x86_64-unknown-cosmo-cc', 'x86_64-unknown-cosmo-c++']]
        ar = 'ar'  # ordinary archives of Cosmopolitan ELF objects
    else:
        cc, cxx, ar = 'gcc', 'g++', 'ar'
    commands = []

    def run(command, log):
        commands.append(command)
        with log.open('wb') as stream:
            stream.write((json.dumps(command) + '\n').encode())
            stream.flush()
            subprocess.run(command, env=env, cwd=directory, stdout=stream, stderr=stream, check=True)

    def compile_group(name, root, sources, flags, compiler):
        out = directory / name
        out.mkdir(exist_ok=True)
        objects = []

        def one(source):
            obj = out / (source.replace('/', '_') + '.o')
            command = [compiler, '-O2', '-g0', '-ffunction-sections', '-fdata-sections',
                       *flags, '-c', str(root / source), '-o', str(obj)]
            # Cache is per command, archive hashes and actual source bytes;
            # the build uses unchanged pinned dependency headers.
            key = hashlib.sha256(json.dumps(command).encode() + (root/source).read_bytes() +
                                 json.dumps(SOURCES).encode()).hexdigest()
            stamp = obj.with_suffix('.key')
            if not obj.exists() or not stamp.exists() or stamp.read_text() != key:
                run(command, obj.with_suffix('.log'))
                stamp.write_text(key)
            return obj

        with ThreadPoolExecutor(max_workers=jobs) as pool:
            objects = list(pool.map(one, sources))
        archive = directory / f'lib{name}.a'
        if archive.exists(): archive.unlink()
        run([ar, 'rcs', str(archive), *map(str, objects)], directory / f'{name}-archive.log')
        return archive

    sources = BUILD / 'sources'
    fastp, isal, deflate, highway = [sources / name for name in SOURCES]
    include = directory / 'include'
    shutil.copytree(isal / 'include', include / 'isa-l', dirs_exist_ok=True)
    isal_lib = compile_group('isal', isal, ISAL_SOURCES,
        ['-std=c11', '-Dbase_aliases', '-I'+str(isal/'include'), '-I'+str(isal/'igzip'), '-I'+str(isal/'crc')], cc)
    deflate_lib = compile_group('deflate', deflate, DEFLATE_SOURCES,
        ['-std=c11', '-I'+str(deflate)], cc)
    hwy_flags = ['-std=c++11', '-fexceptions', '-frtti', '-pthread', '-DHWY_STATIC_DEFINE', '-I'+str(highway)]
    hwy_lib = compile_group('hwy', highway, HWY_SOURCES, hwy_flags, cxx)
    fastp_flags = [*hwy_flags, '-I'+str(fastp), '-I'+str(fastp/'inc'),
                   '-I'+str(include), '-I'+str(deflate)]
    fastp_lib = compile_group('fastp', fastp,
        [str(path.relative_to(fastp)) for path in sorted((fastp/'src').glob('*.cpp'))], fastp_flags, cxx)
    output = ROOT / 'baselines/bin' / f'fastp-{target}{".exe" if target == "cosmo" else ""}'
    output.parent.mkdir(parents=True, exist_ok=True)
    run([cxx, '-fexceptions', '-frtti', '-pthread', '-Wl,--gc-sections', '-o', str(output), str(fastp_lib),
         str(isal_lib), str(deflate_lib), str(hwy_lib), '-lm'], directory/'link.log')
    return {'target': target, 'path': str(output), 'sha256': sha(output), 'bytes': output.stat().st_size,
            'compiler': subprocess.check_output([cxx, '--version'], text=True).splitlines()[0],
            'build_commands': commands}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--build', choices=['linux', 'cosmo', 'all'], default='all')
    parser.add_argument('--cosmocc-root', type=Path,
                        default=ROOT/'variant-build/cosmocc-3.3.10')
    parser.add_argument('--cosmo-source-archive', type=Path,
                        default=ROOT/'variant-build/cosmopolitan-3.3.10.tar.gz')
    parser.add_argument('--jobs', type=int, default=2)
    args = parser.parse_args()
    prepare(args.cosmo_source_archive.resolve())
    results = []
    for target in ['cosmo', 'linux'] if args.build == 'all' else [args.build]:
        print(f'Building fastp: {target}', flush=True)
        result = build(target, args.cosmocc_root.resolve(), max(1, min(args.jobs, 4)))
        results.append(result)
        print(json.dumps({key: result[key] for key in ['target', 'path', 'sha256', 'bytes']}, indent=2), flush=True)
        (BUILD/f'provenance-{target}.json').write_text(json.dumps({
            'tool': 'fastp', 'version': '1.3.7', 'sources': SOURCES,
            'patches': PATCH_NOTES,
            'patch_sha256': sha(VENDOR / 'fastp-offline-report.patch'),
            'isa_l_backend': 'upstream noarch C', 'plotly_sha256': PLOTLY_SHA,
            'build': result, 'windows_execution_tested': False}, indent=2)+'\n')


if __name__ == '__main__':
    main()
