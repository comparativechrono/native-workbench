#!/usr/bin/env python3
"""Build the narrowly scoped GATK 4.7.0.0 local temporary-path adaptation.

The original GATK JAR remains unchanged. A deterministic, first-in-classpath
compatibility JAR replaces only IOUtils, changing one method for local paths.
Its manifest retains upstream launch settings and references adjacent gatk.jar.
"""
import argparse
import difflib
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]
COMPILER_NAME = 'OpenJDK17U-jdk_x64_linux_hotspot_17.0.20.1_1.tar.gz'
COMPILER_SHA256 = '3808d1d15e3ec6bd5b84057fb5d84c33d8a1536a258146bcea2e603fc726e08e'
COMPILER_URL = 'https://github.com/adoptium/temurin17-binaries/releases/download/jdk-17.0.20.1%2B1/' + COMPILER_NAME
SOURCE_SHA256 = '35ffd523a378374aabdb29321bdad90fe48eba31f7c251592cd6305e950016d3'
ORIGINAL_JAR_SHA256 = '882e180707e0e6887885853fc486fa54098620fe9a80bdcdaaa655c7e3861365'
ORIGINAL_ZIP_SHA256 = 'd093d2693b1626361a413ca59d6d4a0bf968717f280a8fd9ce060b25eb2ed1db'
JAVA_SOURCE = 'src/main/java/org/broadinstitute/hellbender/utils/io/IOUtils.java'
OLD_METHOD = '''    public static String getAbsolutePathWithoutFileProtocol(final Path path) {
        return path.toAbsolutePath().toUri().toString().replaceFirst("^file://", "");
    }'''
NEW_METHOD = '''    public static String getAbsolutePathWithoutFileProtocol(final Path path) {
        // Native Workbench compatibility: a local Java temporary directory must
        // retain native drive/UNC syntax and unescaped spaces/Unicode. The
        // upstream URI conversion otherwise introduces %20 and /C:/ on Windows.
        if ("file".equalsIgnoreCase(path.getFileSystem().provider().getScheme())) {
            return path.toAbsolutePath().toString();
        }
        return path.toAbsolutePath().toUri().toString().replaceFirst("^file://", "");
    }'''


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def checked(path, expected):
    if digest(path) != expected:
        raise ValueError('Pinned input differs: ' + str(path))


def put(archive, name, data):
    info = zipfile.ZipInfo(name, (2026, 1, 1, 0, 0, 0))
    info.compress_type = zipfile.ZIP_DEFLATED
    info.create_system = 3
    info.external_attr = 0o100644 << 16
    archive.writestr(info, data)


def build(output, download=False):
    output = output.resolve()
    vendor = ROOT / 'vendor-expanded/gatk'
    compiler_cache = ROOT / 'vendor-expanded/gatk-compat'
    compiler_cache.mkdir(parents=True, exist_ok=True)
    compiler_archive = compiler_cache / COMPILER_NAME
    if not compiler_archive.exists():
        if not download:
            raise FileNotFoundError('Pinned compiler missing; rerun with --download-compiler')
        partial = compiler_archive.with_suffix('.partial')
        try:
            with urllib.request.urlopen(COMPILER_URL, timeout=180) as response, partial.open('wb') as stream:
                shutil.copyfileobj(response, stream, length=1024 * 1024)
            checked(partial, COMPILER_SHA256)
            partial.replace(compiler_archive)
        finally:
            partial.unlink(missing_ok=True)
    checked(compiler_archive, COMPILER_SHA256)
    source_archive = vendor / 'gatk-4.7.0.0-source.tar.gz'
    original_jar = vendor / 'gatk-package-4.7.0.0-local.jar'
    checked(source_archive, SOURCE_SHA256)
    if not original_jar.exists():
        release_zip = vendor / 'gatk-4.7.0.0.zip'
        checked(release_zip, ORIGINAL_ZIP_SHA256)
        with zipfile.ZipFile(release_zip) as archive:
            data = archive.read('gatk-4.7.0.0/gatk-package-4.7.0.0-local.jar')
        if hashlib.sha256(data).hexdigest() != ORIGINAL_JAR_SHA256:
            raise ValueError('Pinned GATK local JAR differs inside release ZIP')
        original_jar.write_bytes(data)
    checked(original_jar, ORIGINAL_JAR_SHA256)
    jdk = compiler_cache / 'jdk-17.0.20.1+1'
    if not (jdk / 'bin/javac').exists():
        with tarfile.open(compiler_archive) as archive:
            archive.extractall(compiler_cache, filter='data')
    if output.exists():
        raise ValueError('Output directory already exists: ' + str(output))
    output.mkdir(parents=True)
    with tarfile.open(source_archive) as archive:
        member = next(m for m in archive if m.name.endswith('/' + JAVA_SOURCE))
        original_source = archive.extractfile(member).read().decode('utf-8')
    if original_source.count(OLD_METHOD) != 1:
        raise ValueError('Expected exact upstream method not found once')
    modified_source = original_source.replace(OLD_METHOD, NEW_METHOD)
    source = output / JAVA_SOURCE
    source.parent.mkdir(parents=True)
    source.write_text(modified_source, encoding='utf-8')
    patch = ''.join(difflib.unified_diff(original_source.splitlines(True), modified_source.splitlines(True),
                                      fromfile='a/' + JAVA_SOURCE, tofile='b/' + JAVA_SOURCE))
    (output / 'gatk-local-path.patch').write_text(patch, encoding='utf-8')
    classes = output / 'classes'
    classes.mkdir()
    env = dict(os.environ)
    env['LD_LIBRARY_PATH'] = str(jdk / 'lib') + ':' + str(jdk / 'lib/server')
    command = [str(jdk / 'bin/javac'), '--release', '17', '-encoding', 'UTF-8', '-proc:none',
               '-g:source,lines', '-cp', str(original_jar), '-d', str(classes), str(source)]
    result = subprocess.run(command, env=env, capture_output=True, text=True)
    (output / 'compiler.log').write_text(result.stdout + result.stderr, encoding='utf-8')
    if result.returncode:
        raise RuntimeError('Compatibility compilation failed; see compiler.log')
    with zipfile.ZipFile(original_jar) as archive:
        manifest = archive.read('META-INF/MANIFEST.MF')
    if b'Class-Path:' in manifest:
        raise ValueError('Unexpected upstream Class-Path')
    manifest = manifest.rstrip(b'\r\n') + b'\r\nClass-Path: gatk.jar\r\n\r\n'
    artifact = output / 'gatk-path-compat.jar'
    class_records = []
    with zipfile.ZipFile(artifact, 'w') as archive:
        put(archive, 'META-INF/MANIFEST.MF', manifest)
        for path in sorted(classes.rglob('*.class')):
            name = path.relative_to(classes).as_posix()
            if not name.startswith('org/broadinstitute/hellbender/utils/io/IOUtils'):
                raise ValueError('Unexpected compiled class: ' + name)
            data = path.read_bytes()
            if int.from_bytes(data[6:8], 'big') != 61:
                raise ValueError('Expected Java 17 bytecode')
            put(archive, name, data)
            class_records.append({'path': name, 'sha256': hashlib.sha256(data).hexdigest(), 'majorVersion': 61})
    provenance = {
        'adaptation': 'gatk-4.7.0.0-workbench-local-path-1',
        'scope': 'One local-filesystem path conversion method; no variant-calling algorithms or model parameters changed.',
        'compiler': {'name': COMPILER_NAME, 'url': COMPILER_URL, 'sha256': COMPILER_SHA256},
        'sourceArchiveSHA256': SOURCE_SHA256, 'originalGatkJarSHA256': ORIGINAL_JAR_SHA256,
        'originalSourceSHA256': hashlib.sha256(original_source.encode()).hexdigest(),
        'modifiedSourceSHA256': digest(source), 'patchSHA256': digest(output / 'gatk-local-path.patch'),
        'compatibilityJarSHA256': digest(artifact), 'classes': class_records,
        'reproduction': 'Run scripts/build_mutect2_compat.py --output NEW_EMPTY_DIRECTORY. ZIP timestamps, entry order and class compilation settings are fixed.',
        'launch': 'Place this JAR beside the unchanged gatk.jar and run the explicitly bundled Java 17 executable with -jar gatk-path-compat.jar and the original GATK arguments.',
        'manifest': 'Original upstream Main-Class and Add-Opens retained, with relative Class-Path: gatk.jar appended.',
        'nativeWindowsExecuted': False,
    }
    (output / 'compatibility-provenance.json').write_text(json.dumps(provenance, indent=2) + '\n')
    print(json.dumps({'jar': str(artifact), 'sha256': digest(artifact), 'classCount': len(class_records)}))
    return artifact


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'build/mutect2/path-compat')
    parser.add_argument('--download-compiler', action='store_true')
    arguments = parser.parse_args()
    build(arguments.output, arguments.download_compiler)
