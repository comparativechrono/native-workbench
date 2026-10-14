#!/usr/bin/env python3
"""Build and exercise the small, source-only independent-pack developer SDK."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
PREFIX = 'native-workbench-pack-sdk/'
FILES = [
    'LICENSE',
    'scripts/package_sdk.py', 'scripts/package_split.py', 'scripts/apply_core_update.py',
    'scripts/apply_desktop_update.py', 'scripts/publish_pack_catalog.py',
    'scripts/validate_pack_release.py', 'scripts/check_pack_release_windows.py',
    'workspace/catalog.py', 'workspace/pack_manager.py', 'workspace/pack_security.py',
    'workspace/app_version.py', 'workspace/PACK-METADATA.md',
    'docs/pack-development-0.6.md', 'docs/catalogue-publishing-0.6.md',
    'tests/test_publish_pack_catalog.py',
]
README = '''# Native Workbench 0.6.0 pack developer SDK

This small source-only SDK prepares independent pack ZIPs, validates their
contents and creates signed catalogues for the native Windows application.
It contains no scientific executable, Python interpreter, private key, production
source trust or sample data from real users. Python 3.12 or newer is required for
the developer scripts; OpenSSL is additionally required for catalogue signing.
End users do not need this SDK to install or use a pack.

Start with docs/pack-development-0.6.md and
docs/catalogue-publishing-0.6.md. The independent-pack template includes a Seqtk
operation, typed ports, methods text, fixtures and scientific assertions. Supply
your own pinned Windows Seqtk build, original licence and build provenance to
pack-examples/independent-pack/prepare.py. No executable is included in that
template. Existing tools' full build recipes, patches, source archives and
licences are in the separate application source companion, not this small SDK.

From this extracted directory:

    python scripts/package_split.py pack --help
    python scripts/validate_pack_release.py --help
    python scripts/publish_pack_catalog.py --help
    python -m unittest discover -s tests -p test_publish_pack_catalog.py -v

Only the `pack` subcommand of package_split.py is a standalone SDK target. Its
source/core/starter commands and the application updater scripts need full
application release inputs; those helper modules are retained here because the
pack builder shares their checked path and hashing code. Do not run updater
scripts against a working installation as part of pack development.

Publish uses an existing external RSA key. It does not upload to GitHub or create
trust automatically. Unsigned previews cannot be used as trusted catalogues.
Archive validation is static: it does not establish native Windows scientific
correctness. Run scripts/check_pack_release_windows.py against a disposable
released Windows application to perform import and scientific assertions through
the released runner. The CI template uses explicit SHA-pinned release downloads.

This archive's SDK-MANIFEST.json records exact source-file hashes. Its build was
extracted into a fresh directory and exercised without the full source checkout:
publisher help, template preparation with a deliberately non-executable test
fixture, pack construction, validation, unsigned preview, and the publisher test
suite. Temporary test files and RSA test keys are not part of this archive.
These checks do not claim that a Windows executable was run on the build host.

Native Workbench source in this SDK is under the included MIT LICENSE. Third-party
tool binaries and tool source are not distributed in this SDK; their original
licences must accompany packs you build.
'''


def digest(data):
    return hashlib.sha256(data).hexdigest()


def run(root, *arguments):
    result = subprocess.run([sys.executable, *map(str, arguments)], cwd=root,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            text=True, check=False, env={**os.environ, 'PYTHONDONTWRITEBYTECODE': '1'})
    if result.returncode:
        raise RuntimeError('Extracted SDK check failed: ' + ' '.join(map(str, arguments)) + '\n' + result.stdout + result.stderr)
    return result


def exercise(archive, temporary_parent):
    with tempfile.TemporaryDirectory(prefix='sdk-isolation-', dir=temporary_parent) as temporary:
        temporary = Path(temporary)
        with zipfile.ZipFile(archive) as zipped:
            zipped.extractall(temporary)
        sdk = temporary / PREFIX.rstrip('/')
        run(sdk, 'scripts/publish_pack_catalog.py', '--help')
        fixture = temporary / 'static-fixture.exe'
        fixture.write_bytes(b'NOT EXECUTABLE. Static SDK integration fixture only.\n')
        licence, provenance = temporary / 'LICENSE-fixture', temporary / 'provenance.json'
        licence.write_text('Temporary test fixture only.\n')
        provenance.write_text('{"testFixture": true, "nativeExecuted": false}\n')
        prepared = temporary / 'example-seqtk-1.0.0'
        packed = temporary / 'example-seqtk-1.0.0.zip'
        run(sdk, 'pack-examples/independent-pack/prepare.py', '--tool-exe', fixture,
            '--tool-version', '1.4-r122', '--license', licence,
            '--provenance', provenance, '--output', prepared)
        run(sdk, 'scripts/package_split.py', 'pack', '--pack-root', prepared, '--output', packed)
        validation = json.loads(run(sdk, 'scripts/validate_pack_release.py', packed).stdout)
        if validation['pack']['id'] != 'example-seqtk' or validation['validation'] != 'static-integrity-only':
            raise RuntimeError('Extracted SDK emitted unexpected validation evidence')
        run(sdk, 'scripts/publish_pack_catalog.py', packed, '--base-url', 'https://example.org/fixtures',
            '--unsigned-preview', '--output', temporary / 'preview')
        tests = run(sdk, '-m', 'unittest', 'discover', '-s', 'tests', '-p', 'test_publish_pack_catalog.py', '-v')
        return {'isolatedExtraction': True, 'publisherHelp': True, 'templatePrepared': True,
                'packBuiltAndValidated': True, 'unsignedPreview': True,
                'publisherTests': tests.stderr.strip(), 'nativeWindowsExecuted': False}


def build(source, output):
    source, output = Path(source).resolve(), Path(output).absolute()
    if output.exists() or output.with_name(output.name + '.partial').exists():
        raise ValueError('Output or partial output already exists')
    paths = list(FILES)
    example = source / 'pack-examples/independent-pack'
    for path in sorted(example.rglob('*')):
        if any(part == '__pycache__' or part.startswith('.') for part in path.relative_to(example).parts):
            continue
        if path.is_file() and path.suffix not in ('.pyc', '.pyo', '.exe', '.dll', '.pem', '.key'):
            paths.append(path.relative_to(source).as_posix())
    contents = {}
    for relative in sorted(paths):
        path = source / relative
        if not path.is_file() or path.is_symlink():
            raise ValueError('Required ordinary SDK source file missing: ' + relative)
        contents[relative] = path.read_bytes()
    contents['README.md'] = README.encode('utf-8')
    manifest = {'schema': 1, 'sdkVersion': '0.6.0', 'packApi': 1,
                'files': [{'path': name, 'bytes': len(data), 'sha256': digest(data)} for name, data in sorted(contents.items())],
                'includesManifestItself': False, 'containsScientificExecutables': False}
    contents['SDK-MANIFEST.json'] = (json.dumps(manifest, indent=2) + '\n').encode()
    output.parent.mkdir(parents=True, exist_ok=True)
    partial = output.with_name(output.name + '.partial')
    try:
        with zipfile.ZipFile(partial, 'x', compression=zipfile.ZIP_DEFLATED, compresslevel=9) as zipped:
            for name, data in sorted(contents.items()):
                info = zipfile.ZipInfo(PREFIX + name, (2026, 10, 3, 0, 0, 0))
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = 0o100644 << 16
                zipped.writestr(info, data)
        with zipfile.ZipFile(partial) as zipped:
            if zipped.testzip() is not None:
                raise ValueError('SDK ZIP CRC check failed')
            for name, data in contents.items():
                if zipped.read(PREFIX + name) != data:
                    raise ValueError('SDK ZIP source bytes differ: ' + name)
        evidence = exercise(partial, output.parent)
        os.replace(partial, output)
    except BaseException:
        partial.unlink(missing_ok=True)
        raise
    return {'file': str(output), 'bytes': output.stat().st_size, 'sha256': digest(output.read_bytes()),
            'members': len(contents), 'crcVerified': True, 'sourceBytesVerified': True, 'evidence': evidence}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', type=Path, default=ROOT)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(build(args.source_root, args.output), indent=2))


if __name__ == '__main__':
    main()
