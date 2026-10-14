#!/usr/bin/env python3
"""Verify pinned VarDict inputs; download only with --download.

Corresponding-source archives may first be restored from the shipped pack's
licenses directory with --restore-sources PATH. No downloaded code is executed.
"""
import argparse
from pathlib import Path
import shutil
import urllib.request

from prepare_vardict_pack import PINS, VENDOR, digest

TEMURIN = 'https://github.com/adoptium/temurin8-binaries/releases/download/jdk8u504-b01/'
URLS = {
    'VarDict-1.8.3.zip': 'https://github.com/AstraZeneca-NGS/VarDictJava/releases/download/v1.8.3/VarDict-1.8.3.zip',
    'OpenJDK8U-jre_x64_windows_hotspot_8u504b01.zip': TEMURIN + 'OpenJDK8U-jre_x64_windows_hotspot_8u504b01.zip',
    'OpenJDK8U-jdk-sources_8u504b01.tar.gz': TEMURIN + 'OpenJDK8U-jdk-sources_8u504b01.tar.gz',
    'strawberry-perl-5.42.3.1-64bit-portable.zip': 'https://github.com/StrawberryPerl/Perl-Dist-Strawberry/releases/download/SP_54231_64bit/strawberry-perl-5.42.3.1-64bit-portable.zip',
    'perl-5.42.3.tar.xz': 'https://www.cpan.org/src/5.0/perl-5.42.3.tar.xz',
    'strawberry-5.42.3.1-source.tar.gz': 'https://api.github.com/repos/StrawberryPerl/Perl-Dist-Strawberry/tarball/SP_54231_64bit',
    'gcc-13.2.0.tar.xz': 'https://gcc.gnu.org/pub/gcc/releases/gcc-13.2.0/gcc-13.2.0.tar.xz',
    'VarDictJava-1.8.3-source.tar.gz': 'https://api.github.com/repos/AstraZeneca-NGS/VarDictJava/tarball/v1.8.3',
    'VarDict-009e017-source.tar.gz': 'https://api.github.com/repos/AstraZeneca-NGS/VarDict/tarball/009e017d90b25e497ddd50645dc4fa27c484a193',
    'build-extlibs-source.tar.gz': 'https://api.github.com/repos/StrawberryPerl/build-extlibs/tarball/gcc13.2_ucrt_posix',
    'mingw-w64-11.0.1-source.tar.gz': 'https://api.github.com/repos/mingw-w64/mingw-w64/tarball/v11.0.1',
    'jregex-1.2_01-sources.jar': 'https://repo.maven.apache.org/maven2/com/edropple/jregex/jregex/1.2_01/jregex-1.2_01-sources.jar',
    'htsjdk-source.jar': 'https://repo.maven.apache.org/maven2/com/github/samtools/htsjdk/2.21.1/htsjdk-2.21.1-sources.jar',
    'Microsoft-VC-Runtime-2015-2022-License.docx': 'https://visualstudio.microsoft.com/wp-content/uploads/2021/09/Visual-C-Runtime-2015-2022-License-1.docx',
}
REFERENCE = {
    'OpenJDK8U-jre_x64_linux_hotspot_8u504b01.tar.gz': (
        TEMURIN + 'OpenJDK8U-jre_x64_linux_hotspot_8u504b01.tar.gz',
        '52dcd578baca1d3e449ea86768a9129c0ee04d7b22565695498353cc66940c61'),
    'ecj-3.26.0.jar': (
        'https://repo.maven.apache.org/maven2/org/eclipse/jdt/ecj/3.26.0/ecj-3.26.0.jar',
        'ac0ba5876eaf7ebb47749a0d1be179c51f194b9dd0b875d1c09e1b530f5a2db5'),
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--download', action='store_true')
    parser.add_argument('--restore-sources', type=Path)
    parser.add_argument('--reference-linux', action='store_true')
    parser.add_argument('--directory', type=Path, default=VENDOR)
    args = parser.parse_args()
    assert PINS.keys() == URLS.keys()
    assets = {name: (URLS[name], pin) for name, pin in PINS.items()}
    if args.reference_linux:
        assets.update(REFERENCE)
    args.directory.mkdir(parents=True, exist_ok=True)
    for name, (url, pin) in assets.items():
        target = args.directory / name
        if not target.exists() and args.restore_sources:
            source = args.restore_sources / name
            if source.is_file():
                if digest(source) != pin:
                    raise ValueError('Restored source checksum mismatch: ' + name)
                shutil.copyfile(source, target)
        if not target.exists():
            if not args.download:
                raise FileNotFoundError('Missing ' + name + '; use --download or --restore-sources')
            temporary = target.with_name(target.name + '.partial')
            try:
                request = urllib.request.Request(url, headers={'User-Agent': 'Native-Workbench-source-fetch/0.5.3'})
                with urllib.request.urlopen(request, timeout=120) as response, temporary.open('wb') as stream:
                    shutil.copyfileobj(response, stream, length=1024 * 1024)
                if digest(temporary) != pin:
                    raise ValueError('Downloaded checksum mismatch: ' + name)
                temporary.replace(target)
            finally:
                temporary.unlink(missing_ok=True)
        if digest(target) != pin:
            raise ValueError('Existing file checksum mismatch: ' + name)
        print('Verified ' + name)


if __name__ == '__main__':
    main()
