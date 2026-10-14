#!/usr/bin/env python3
"""Fetch unmodified SeqKit release artifacts and their pinned dependency notices.

The cache is deliberately outside the application source. No Go installation is
needed: module versions and checksums are read from the upstream Go build info.
"""
import argparse
import base64
import concurrent.futures
import hashlib
import io
import json
from pathlib import Path
import re
import tarfile
import urllib.request
import zipfile

VERSION = '2.14.0'
COMMIT = 'facf0f7120483f9e39725c66dd83f5f14e048afd'
ARTIFACTS = {
    'seqkit_windows_amd64.exe.tar.gz': 'f4501cff43292059d8a49b93289a365cd433626cac6d5a704541f080ad56773f',
    'seqkit_linux_amd64.tar.gz': '3d664ffb48438d1fbd3f3cfc060c71d00368a26435f1c876944aea7fcdff86b5',
    'source-v2.14.0.tar.gz': '7df95904ce438c1a1a7b1fc06f20479a169e69209ac59abae8e80c60a1e65d60',
}


def sha(data):
    return hashlib.sha256(data).hexdigest()


def fetch(cache, name, url, expected=None):
    path = cache / name
    if not path.is_file():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(urllib.request.urlopen(url, timeout=120).read())
    data = path.read_bytes()
    if expected and sha(data) != expected:
        raise ValueError(f'Checksum mismatch: {name}')
    return data


def build_info(binary):
    data = binary.read_bytes()
    offset = data.index(b'\xff Go buildinf:')
    if not data[offset + 15] & 2:
        raise ValueError('Expected inline Go build info')
    offset += 32
    def string():
        nonlocal offset
        size = shift = 0
        while True:
            b = data[offset]
            offset += 1
            size |= (b & 127) << shift
            shift += 7
            if not b & 128:
                break
        result = data[offset:offset + size]
        offset += size
        return result
    version = string().decode()
    info = string()[16:-16].decode()
    return version, info


def escaped(value):
    return ''.join('!' + c.lower() if c.isupper() else c for c in value)


def notices(cache, module, version, expected):
    key = sha(f'{module}@{version}'.encode())[:12]
    url = f'https://proxy.golang.org/{escaped(module)}/@v/{escaped(version)}.zip'
    data = fetch(cache, 'modules/' + key + '.zip', url)
    out = cache / 'licenses' / 'modules' / key
    out.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        files = sorted(n for n in z.namelist() if not n.endswith('/'))
        h = hashlib.sha256()
        for name in files:
            h.update(f'{sha(z.read(name))}  {name}\n'.encode())
        actual = 'h1:' + base64.b64encode(h.digest()).decode()
        if actual != expected:
            raise ValueError(f'Module checksum mismatch: {module}: {actual} != {expected}')
        selected = []
        for name in files:
            leaf = name.rsplit('/', 1)[-1]
            if not re.match(r'(?i)^(unlicense|ofl|sil_open_font_license|licen[cs]es?|copying|notice|copyright|patents|authors)([.\-_]|$)', leaf):
                continue
            relative = name.split('/', 1)[1] if '/' in name else name
            dest = out / (str(len(selected) + 1).zfill(3) + '-' + leaf[:70])
            content = z.read(name)
            dest.write_bytes(content)
            selected.append({'source': name, 'file': dest.relative_to(cache / 'licenses').as_posix(), 'sha256': sha(content)})
        if not selected:
            raise ValueError(f'No license files: {module}')
    return {'module': module, 'version': version, 'goSum': expected, 'url': url, 'archiveSha256': sha(data), 'notices': selected}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--cache', type=Path, required=True)
    args = p.parse_args()
    cache = args.cache.resolve()
    cache.mkdir(parents=True, exist_ok=True)
    artifacts = []
    for name, digest in ARTIFACTS.items():
        url = (f'https://codeload.github.com/shenwei356/seqkit/tar.gz/refs/tags/v{VERSION}' if name.startswith('source-')
               else f'https://github.com/shenwei356/seqkit/releases/download/v{VERSION}/{name}')
        data = fetch(cache, name, url, digest)
        artifacts.append({'name': name, 'url': url, 'sha256': sha(data), 'bytes': len(data)})
        dest = cache / ('source' if name.startswith('source-') else 'windows' if 'windows' in name else 'linux')
        with tarfile.open(fileobj=io.BytesIO(data)) as t:
            t.extractall(dest, filter='data')
    licenses = cache / 'licenses'
    licenses.mkdir(exist_ok=True)
    source = cache / 'source' / f'seqkit-{VERSION}'
    (licenses / 'SeqKit-LICENSE').write_bytes((source / 'LICENSE').read_bytes())
    for name in ['go.mod', 'go.sum']:
        (licenses / name).write_bytes((source / name).read_bytes())
    deps = {}
    builds = {}
    for target, binary in [('windows-amd64', cache / 'windows/seqkit.exe'), ('linux-amd64', cache / 'linux/seqkit')]:
        goversion, info = build_info(binary)
        builds[target] = {'goVersion': goversion, 'sha256': sha(binary.read_bytes()), 'bytes': binary.stat().st_size, 'buildInfo': info}
        for line in info.splitlines():
            if line.startswith('dep\t'):
                _, module, version, checksum = line.split('\t')
                deps[module, version] = checksum
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as executor:
        modules = list(executor.map(lambda v: notices(cache, *v[0], v[1]), sorted(deps.items())))
    # Go's bundled runtime and vendored notices come from its exact source tag.
    gv = builds['windows-amd64']['goVersion']
    go_url = f'https://codeload.github.com/golang/go/tar.gz/refs/tags/{gv}'
    if gv != 'go1.27.0':
        raise ValueError('Unexpected upstream Go version')
    go_source = fetch(cache, f'{gv}-source.tar.gz', go_url, '56418054e83f1edae5f365c2cd5c4b6dd5943ce7dd7c26a2994b082f36f9dbc1')
    go_notices = []
    with tarfile.open(fileobj=io.BytesIO(go_source)) as t:
        for m in t.getmembers():
            if m.isfile() and re.match(r'(?i)^(license|copying|notice|copyright|patents)([.\-_]|$)', m.name.rsplit('/', 1)[-1]):
                content = t.extractfile(m).read()
                dest = licenses / 'go' / (str(len(go_notices) + 1).zfill(3) + '-' + m.name.rsplit('/', 1)[-1])
                dest.parent.mkdir(exist_ok=True)
                dest.write_bytes(content)
                go_notices.append({'source': m.name, 'file': dest.relative_to(licenses).as_posix(), 'sha256': sha(content)})
    record = {'schema': 1, 'upstream': 'SeqKit', 'version': VERSION, 'sourceCommit': COMMIT,
              'artifacts': artifacts, 'builds': builds, 'modules': modules,
              'go': {'version': gv, 'sourceUrl': go_url, 'sourceSha256': sha(go_source), 'notices': go_notices},
              'note': 'Official unmodified release binaries; embedded vcs.modified=true is retained. This package does not claim bit-for-bit reproduction from the release source tag. Module archives were verified against the Go h1 checksums embedded in the binaries. Release binary archive SHA256 digests match GitHub release metadata.'}
    (licenses / 'provenance.json').write_text(json.dumps(record, indent=2) + '\n')
    print(json.dumps({'modules': len(modules), 'goNotices': len(go_notices), 'licenses': str(licenses), 'builds': {k: {n:v for n,v in b.items() if n != 'buildInfo'} for k,b in builds.items()}}, indent=2))


if __name__ == '__main__':
    main()
