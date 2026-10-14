#!/usr/bin/env python3
"""Fetch SHA-pinned, unmodified Bowtie 2 binaries and corresponding sources.

Network use is limited to explicit preparation of an external vendor cache.
The generated pack performs no downloads and uses no interpreter wrappers.
"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import tarfile
import urllib.request
import zipfile

VERSION = '2.5.5'
COMMIT = '0c6a1c75e047ad8bf70c178fa3cb1528fba6adc2'
GALAXY_COMMIT = '405eb069a3f4888ba19d9be7e3e7d9f23e54c5d0'
ARTIFACTS = [
    ('bowtie2-2.5.5-mingw-x86_64.zip', 'https://github.com/BenLangmead/bowtie2/releases/download/v2.5.5/bowtie2-2.5.5-mingw-x86_64.zip', '77bfac3a84c54f4032ee851c19917802decc1b28083ce17a5f92a0c4d729bdba'),
    ('bowtie2-2.5.5-linux-x86_64.zip', 'https://github.com/BenLangmead/bowtie2/releases/download/v2.5.5/bowtie2-2.5.5-linux-x86_64.zip', '38472e806f56ed23d32cbe7a7fe1b7260680f892647aa78c2f6882f8f272a026'),
    ('bowtie2-2.5.5-source.tar.gz', 'https://codeload.github.com/BenLangmead/bowtie2/tar.gz/refs/tags/v2.5.5', 'e38d1833ec235ca27fa57589d32d897c9addf87085b7cb7bc978662954662da2'),
    ('zlib-1.3.2.tar.gz', 'https://codeload.github.com/madler/zlib/tar.gz/refs/tags/v1.3.2', 'b99a0b86c0ba9360ec7e78c4f1e43b1cbdf1e6936c8fa0f6835c0cd694a495a1'),
    ('zstd-1.5.5.tar.gz', 'https://codeload.github.com/facebook/zstd/tar.gz/refs/tags/v1.5.5', '98e9c3d949d1b924e28e01eccb7deed865eefebf25c2f21c702e5cd5b63b85e1'),
    ('GCC-COPYING.RUNTIME', 'https://raw.githubusercontent.com/gcc-mirror/gcc/releases/gcc-12.2.0/COPYING.RUNTIME', '9d6b43ce4d8de0c878bf16b54d8e7a10d9bd42b75178153e3af6a815bdc90f74'),
    ('GCC-COPYING3', 'https://raw.githubusercontent.com/gcc-mirror/gcc/releases/gcc-12.2.0/COPYING3', '8ceb4b9ee5adedde47b31e975c1d90c73ad27b6b165a1dcd80c7c545eb65b903'),
    ('mingw-runtime-COPYING', 'https://raw.githubusercontent.com/mingw-w64/mingw-w64/v10.0.0/COPYING.MinGW-w64-runtime/COPYING.MinGW-w64-runtime.txt', 'e9b2dc02451ea29092a1f25fa0f3c07207ed421f1807dffb0c4e6dce69dee7bd'),
    ('mingw-COPYING', 'https://raw.githubusercontent.com/mingw-w64/mingw-w64/v10.0.0/COPYING.MinGW-w64/COPYING.MinGW-w64.txt', 'f38e6194bd3bfa1b654f118e5acefe0aead437bbe669eee43957ccc65a7127f1'),
    ('winpthreads-COPYING', 'https://raw.githubusercontent.com/mingw-w64/mingw-w64/v10.0.0/mingw-w64-libraries/winpthreads/COPYING', '63263614cdd29f2f93cba85e992f041b31f9fc7b4033692f31269489a8a1b177'),
    ('galaxy-bowtie2_wrapper.xml', f'https://raw.githubusercontent.com/galaxyproject/tools-iuc/{GALAXY_COMMIT}/tools/bowtie2/bowtie2_wrapper.xml', '04ac53eb221f0c0e8a78c9454f4a5109e7c25117a98c7ffb9bfff52088994d79'),
    ('galaxy-bowtie2_macros.xml', f'https://raw.githubusercontent.com/galaxyproject/tools-iuc/{GALAXY_COMMIT}/tools/bowtie2/bowtie2_macros.xml', '679e19d09eabd70e23ffe63841fd14e884ddd455932498b05987a02f26c40b79'),
    ('galaxy-LICENSE', f'https://raw.githubusercontent.com/galaxyproject/tools-iuc/{GALAXY_COMMIT}/LICENSE', '06276304c423a835d843f55c62288aee7e5d6e474f301fe51a6e78481c39ca5b'),
]
WINDOWS = {
    'bowtie2-align-s.exe': 'd9b13685cf659903071be0531349e124865d0e48b7be314e69b5bbacfad6ffb1',
    'bowtie2-align-l.exe': '4a06c29533a2c3ee18687d2034a0406b12ecf1d34630c29c3816958d18c08d6e',
    'bowtie2-build-s.exe': 'af2d87fb75f9b7ac70f398ed359e9b1caca044f2c70cfc9801dc4d7910b331fb',
    'bowtie2-build-l.exe': 'f72393d73da773322f1c965710a7b8e47a95649546f4f519bcab6d0e2516b762',
}
LINUX = {
    'bowtie2-align-s': 'e24a717f95d4d1403f69844ebd257f1d3b14c600679a2943fd2a3161f2ec0dab',
    'bowtie2-align-l': '39bbceff23a89acddc7ea4c6deab10757c6ac37fc1ac4f0888d562a92a293b7b',
    'bowtie2-build-s': '4006e604ca4e2146a6f0c8be40993c7590df68a001ae35b50fb1496ef7e20f2c',
    'bowtie2-build-l': 'a7a57dc4bd2232855ed6bff928a968563a3326c5b4c0feddefdc86f1c360e24a',
}


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def prepare(cache):
    cache.mkdir(parents=True, exist_ok=True)
    records = []
    for name,url,digest in ARTIFACTS:
        path = cache/name
        if not path.is_file():
            path.write_bytes(urllib.request.urlopen(url, timeout=180).read())
        if sha(path) != digest:
            raise ValueError('Upstream artifact hash mismatch: '+name)
        records.append(dict(name=name,url=url,sha256=digest,bytes=path.stat().st_size))
    for platform,mapping,archive,prefix in [
        ('windows-bin',WINDOWS,'bowtie2-2.5.5-mingw-x86_64.zip','bowtie2-2.5.5-mingw-x86_64'),
        ('linux-bin',LINUX,'bowtie2-2.5.5-linux-x86_64.zip','bowtie2-2.5.5-linux-x86_64')]:
        dest=cache/platform
        dest.mkdir(exist_ok=True)
        with zipfile.ZipFile(cache/archive) as z:
            for name,digest in mapping.items():
                path=dest/name
                path.write_bytes(z.read(prefix+'/'+name))
                if sha(path)!=digest:
                    raise ValueError('Executable hash differs: '+name)
                if platform=='linux-bin': path.chmod(0o755)
        # Do not extract AVX2 variants beside the Linux reference aligners: the
        # generic official binary would auto-exec them, changing the tested code.
    licenses=cache/'licenses'
    licenses.mkdir(exist_ok=True)
    for name,_,_ in ARTIFACTS:
        if name.endswith('.zip'): continue
        shutil.copy2(cache/name,licenses/name)
    for archive,documents in [
        ('bowtie2-2.5.5-source.tar.gz',['LICENSE','AUTHORS','Makefile','MANUAL.markdown','BOWTIE2_VERSION']),
        ('zlib-1.3.2.tar.gz',['LICENSE']),('zstd-1.5.5.tar.gz',['LICENSE','COPYING'])]:
        with tarfile.open(cache/archive) as tar:
            prefix=tar.getmembers()[0].name.split('/')[0]
            for name in documents:
                data=tar.extractfile(prefix+'/'+name).read()
                (licenses/(prefix+'-'+name)).write_bytes(data)
    record=dict(schema=1,tool='Bowtie 2',version=VERSION,sourceCommit=COMMIT,artifacts=records,
        windowsBinaries=WINDOWS,linuxBinaries=LINUX,
        windowsImports=['KERNEL32.dll','msvcrt.dll'],
        compilerEvidence='Embedded Windows version strings report gcc version 12-posix (GCC), static libgcc/libstdc++ linkage, WITH_ZSTD, no USE_SAIS, and build date 2026-03-07.',
        linkedCompressionEvidence='Windows binary strings identify zlib 1.3.2 and zstd 1.5.5. Their complete sources accompany this pack.',
        runtimeNoticeScope='GCC12 runtime exception and MinGW-w64 runtime/winpthreads notices are included. The upstream binary does not identify an exact MinGW source revision; v10.0.0 notices are supplied without claiming that revision was used for the upstream build.',
        sourceScope='Unmodified upstream GPLv3-or-later Bowtie2 source archive and linked compression-library sources are included. The standard x86_64 blockwise index build does not enable optional libsais or SIMDe. Upstream Makefile and embedded build evidence are preserved; exact byte-for-byte reproduction of the published binary is not claimed.',
        wrappers='The pack invokes the selected -s/-l native build/align executables directly and explicitly selects small/large indices; no upstream Python wrapper, shell, SRA client or network fetch is used during analysis.',
        galaxyCommit=GALAXY_COMMIT,nativeWindowsExecuted=False)
    (licenses/'provenance.json').write_text(json.dumps(record,indent=2)+'\n')
    return record


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cache',type=Path,required=True)
    args=parser.parse_args()
    prepare(args.cache.resolve())
    print('Verified Bowtie 2 vendor cache:',args.cache.resolve())
