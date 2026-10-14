#!/usr/bin/env python3
"""Promote immutable accepted 0.11.0 archives; never rebuild or replace assets."""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile

REPOSITORY = 'comparativechrono/workbench'
VERSION = '0.11.0'
TAG = 'app-v' + VERSION
BRANCH = 'release/app-' + VERSION
ROOT = Path(__file__).resolve().parents[1]
LOCK_PATH = ROOT / 'knowledge/evidence/tool-library-0.11.0-release-lock.json'
SOURCE = 'acfa060c9a400d82509278b657ee37853c7922b0'
UPDATER_SOURCE = 'f13e2c6dde1c1792405617af943dc706dfd42176'
VALIDATOR_SOURCE = '0c880d1060f22edb7e9c663743a1966a2f8f2eea'
STARTER = 'native-workbench-0.11.0-starter-windows.zip'
SOURCES = 'native-workbench-0.11.0-source.zip'
UPDATE = 'native-workbench-0.11.0-update-from-0.10.1.zip'
BASELINE_SHA = 'a8c4d374104d62fdf46dbd405e9d5bc36f5e2ea191f573faa63cfb29b433ba79'
TRUST_SHA = '240cef994004c040584d3b8806bb361683693b1e7c0e92c9aedeaddc683fbefc'
PROFILE_SHA = '4cad899dcc1f6541f6edecc3ace7d0d4dd5d6103b1b16218fece0c0b68d2a4ba'
FINGERPRINT = '8d2093f9fafd71de56fea2038faeb2efa0964767d3235430b06428132cdc8505'
CANDIDATE_MEMBERS = {STARTER, SOURCES, 'BUILD-PROVENANCE.json', 'source-metadata.json', 'SHA256SUMS.txt'}
UPDATE_MEMBERS = {UPDATE, 'BUILD-UPDATE-PROVENANCE.json', 'SHA256SUMS.txt'}
ASSET_NAMES = CANDIDATE_MEMBERS | {UPDATE, 'BUILD-UPDATE-PROVENANCE.json',
    'UPDATE-SHA256SUMS.txt', 'WINDOWS-EVIDENCE.zip', 'RELEASE-VALIDATION.json', 'EVIDENCE-SHA256SUMS.txt'}
NON_APP = {
    'README.md', '.github/workflows/native-tool-library-candidate.yml',
    '.github/workflows/native-tool-library-verify.yml', '.github/workflows/native-update-0.11.0.yml',
    '.github/workflows/native-library-release-check.yml', '.github/workflows/publish-app-0.11.0.yml',
    'scripts/native_tree.py', 'scripts/check_tool_library_windows.py',
    'scripts/check_workspace_ui_windows.py', 'scripts/check_results_windows.py',
    'scripts/check_scroll_frames_windows.py', 'scripts/check_references_windows.py',
    'scripts/build_update_0110.py', 'scripts/check_update_0110_windows.py',
    'scripts/publish_app_0110.py', 'tests/test_publish_app_0110.py',
}

def require(value, message):
    if not value:
        raise ValueError(message)

def sha(raw):
    return hashlib.sha256(raw).hexdigest()

def json_bytes(value):
    return (json.dumps(value, indent=2, ensure_ascii=False) + '\n').encode()

def exact_hash(value, length=64):
    return isinstance(value, str) and re.fullmatch('[0-9a-f]{' + str(length) + '}', value) is not None

def acceptance_lock():
    lock = json.loads(LOCK_PATH.read_bytes())
    require(lock.get('schema') == 1 and lock.get('sourceCommit') == SOURCE
            and lock.get('prNumber') == 6 and lock.get('coreFiles') == 72
            and lock.get('authorization', {}).get('authorized') is True
            and lock['authorization'].get('message') == 'Please release 0.11.0 properly',
            'Accepted release authorization/source identity differs.')
    require(set(lock.get('archives', {})) == {STARTER, SOURCES, UPDATE}, 'Incomplete archive lock.')
    for value in lock['archives'].values():
        require(type(value.get('bytes')) is int and value['bytes'] > 0 and exact_hash(value.get('sha256')),
                'Incomplete archive identity.')
    require(lock['archives'][STARTER] == {'bytes': 17044022,
        'sha256': 'e816e2f7cd5efe98af752fbf072fab00344ebaa2b6963795c2fbf4a86b5fa81c'}, 'Starter lock differs.')
    require(lock['archives'][SOURCES] == {'bytes': 46875983,
        'sha256': 'a45ad640f0767bb56458b59ce50d263537e54ebb401a0e809f31a5453adb2f2b'}, 'Source lock differs.')
    require(lock['archives'][UPDATE] == {'bytes': 12857609,
        'sha256': '720d79aac5ddfd15dd3d06096950f3e56eff911981643eb6440ecb0f9911ecfe'}, 'Updater lock differs.')
    require(set(lock.get('runs', {})) == {'candidate', 'categories', 'updater', 'regressions'},
            'Incomplete run acceptance.')
    require(len(lock.get('artifacts', {})) == 10 and len(lock.get('reports', {})) == 12,
            'Incomplete artifact/report acceptance.')
    ids, files = set(), set()
    for item in lock['artifacts'].values():
        require(type(item.get('id')) is int and item['id'] > 0 and item['id'] not in ids
                and type(item.get('bytes')) is int and item['bytes'] > 0 and exact_hash(item.get('sha256'))
                and re.fullmatch(r'[a-z0-9-]+\.zip', item.get('file', '')) and item['file'] not in files,
                'Invalid or duplicate artifact identity.')
        require(item.get('run') in lock['runs'] and bool(item.get('name')), 'Missing artifact provenance.')
        ids.add(item['id']); files.add(item['file'])
    for item in lock['reports'].values():
        require(item.get('artifact') in lock['artifacts'] and exact_hash(item.get('sha256'))
                and type(item.get('passed')) is int and item['passed'] > 0
                and item.get('sourceCommit') == SOURCE and exact_hash(item.get('gateCommit'), 40)
                and isinstance(item.get('skips'), list), 'Incomplete report binding.')
    return lock

def checked_zip(raw):
    archive = zipfile.ZipFile(io.BytesIO(raw))
    names = archive.namelist()
    require(len(names) == len(set(names)), 'Duplicate ZIP members.')
    require(all(not PurePosixPath(n).is_absolute() and '..' not in PurePosixPath(n).parts
                and '\\' not in n and ':' not in n for n in names), 'Unsafe ZIP member.')
    require(archive.testzip() is None, 'ZIP CRC validation failed.')
    return archive

def source_bytes(path, commit=SOURCE):
    require(exact_hash(commit, 40), 'An exact source commit is required.')
    return subprocess.check_output(['git', 'show', commit + ':' + path], cwd=ROOT)

def verify_source_identity(publish_sha):
    require(exact_hash(publish_sha, 40), 'An exact publication commit is required.')
    subprocess.run(['git', 'merge-base', '--is-ancestor', SOURCE, publish_sha], cwd=ROOT, check=True)
    changed = subprocess.check_output(['git', 'diff', '--name-only', SOURCE, publish_sha], cwd=ROOT,
                                     text=True).splitlines()
    require(all(name.startswith(('knowledge/', 'docs/')) or name in NON_APP for name in changed),
            'Application/build/pack code changed after accepted candidate: ' + repr(changed))
    publication_files = {'README.md', 'scripts/publish_app_0110.py',
        'tests/test_publish_app_0110.py', '.github/workflows/publish-app-0.11.0.yml'}
    for name in sorted(NON_APP - publication_files):
        require(source_bytes(name, publish_sha) == source_bytes(name, VALIDATOR_SOURCE),
                'Validated helper/workflow changed after acceptance: ' + name)

def checksums(raw, expected, read):
    rows = [line.split('  ', 1) for line in raw.decode().splitlines()]
    require(len(rows) == len(expected) and all(len(row) == 2 for row in rows)
            and {row[1] for row in rows} == set(expected), 'Checksum inventory differs.')
    require(all(exact_hash(digest) and sha(read(name)) == digest for digest, name in rows),
            'Checksum identity differs.')

def verify_merged(client, publish_sha):
    require(client.api('/git/ref/heads/main')['object']['sha'] == publish_sha,
            'Publication must promote exact merged main.')
    pr = client.api('/pulls/6')
    require(pr.get('merged') is True and pr.get('merge_commit_sha') == publish_sha
            and pr.get('base', {}).get('ref') == 'main'
            and pr.get('head', {}).get('ref') == 'feature/expandable-tool-library',
            'Accepted feature PR is not merged at the publication commit.')

def verify_runs(client, lock):
    evidence = {}
    for key, item in lock['runs'].items():
        run = client.api('/actions/runs/' + str(item['id']))
        require(run['head_sha'] == item['sourceCommit'] and run['status'] == 'completed'
                and run['conclusion'] == item['conclusion'] and run['path'] == item['path'],
                'Run identity or conclusion differs: ' + key)
        data = client.api('/actions/runs/' + str(item['id']) + '/jobs?filter=latest&per_page=100')
        jobs = data['jobs']
        require(data['total_count'] == len(jobs), 'Incomplete job inventory.')
        observed = [{'id': job['id'], 'name': job['name'], 'conclusion': job['conclusion'],
                     'nonSuccessSteps': [{'name': step['name'], 'conclusion': step['conclusion']}
                         for step in job.get('steps', []) if step['conclusion'] != 'success']}
                    for job in jobs]
        require(sorted(observed, key=lambda j: j['id']) == sorted(item['jobs'], key=lambda j: j['id']),
                'Reviewed job or step inventory differs: ' + key)
        if key != 'candidate':
            require(jobs and all(job['conclusion'] == 'success' for job in jobs),
                    'Required native run contains a failed job.')
            require(all(step['conclusion'] == 'success' for job in jobs for step in job.get('steps', [])),
                    'Required native run contains a failed/skipped step.')
        else:
            require(item['conclusion'] == 'failure' and any(job['name'] == 'build' and
                    job['conclusion'] == 'success' for job in jobs),
                    'Original candidate build did not pass.')
            # The retained failure is the superseded state-bit validator; its
            # successful workspace reports are accepted separately by exact hash.
            require(sum(job['name'].startswith('native (') for job in jobs) == 2,
                    'Original native workspace jobs are missing.')
        evidence[key] = {'id': item['id'], 'sourceCommit': run['head_sha'],
                         'conclusion': run['conclusion'],
                         'jobs': [{'id': job['id'], 'name': job['name'],
                                   'conclusion': job['conclusion']} for job in jobs]}
    return evidence

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class GitHub:
    def __init__(self, token):
        require(bool(token), "GitHub token is required for publication.")
        self.token = token
        self.base = "https://api.github.com/repos/" + REPOSITORY

    def api(self, path, method="GET", data=None, absent_ok=False):
        request = urllib.request.Request(self.base + path, method=method,
            data=None if data is None else json_bytes(data), headers={"Authorization": "Bearer " + self.token,
                "Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28",
                "Content-Type": "application/json"})
        try:
            # API requests never follow redirects with the credential header.
            with urllib.request.build_opener(NoRedirect).open(request, timeout=60) as response:
                return json.load(response)
        except urllib.error.HTTPError as error:
            if error.code == 404 and absent_ok:
                return None
            raise RuntimeError(f"GitHub {method} {path} failed: HTTP {error.code}") from None

    def download(self, url, destination, expected_sha, expected_size, authenticated=False):
        # Actions' archive endpoint returns a storage redirect using the JSON
        # API media type. Release-asset endpoints instead need octet-stream.
        artifact_endpoint = re.fullmatch(re.escape(self.base) + r"/actions/artifacts/[0-9]+/zip", url)
        headers = {"Accept": "application/vnd.github+json" if artifact_endpoint else "application/octet-stream"}
        if authenticated:
            require(url.startswith(self.base + "/"), "Credentials only belong on this repository's API.")
            headers["Authorization"] = "Bearer " + self.token
            headers["X-GitHub-Api-Version"] = "2022-11-28"
        opener = urllib.request.build_opener(NoRedirect)
        for _ in range(6):
            parsed = urllib.parse.urlparse(url)
            host = parsed.hostname or ""
            require(parsed.scheme == "https" and not parsed.username and not parsed.password and
                    (host in {"api.github.com", "github.com"} or
                     any(host.endswith(suffix) for suffix in
                         (".githubusercontent.com", ".blob.core.windows.net", ".amazonaws.com"))),
                    "Download left trusted HTTPS GitHub/storage hosts.")
            try:
                response = opener.open(urllib.request.Request(url, headers=headers), timeout=90)
                break
            except urllib.error.HTTPError as error:
                if error.code in (301, 302, 303, 307, 308):
                    url = urllib.parse.urljoin(url, error.headers["Location"])
                    # Signed GitHub storage redirects never receive the API token.
                    headers = {"Accept": "application/octet-stream"}
                    continue
                raise RuntimeError(f"Download failed: HTTP {error.code}") from None
        else:
            raise ValueError("Too many download redirects.")
        partial = destination.with_name(destination.name + ".partial")
        total = 0
        digest = hashlib.sha256()
        try:
            with response, partial.open("xb") as out:
                while chunk := response.read(1024 * 1024):
                    total += len(chunk)
                    require(total <= expected_size, "Download exceeded pinned length.")
                    digest.update(chunk)
                    out.write(chunk)
            require(total == expected_size and digest.hexdigest() == expected_sha, "Downloaded identity differs.")
            partial.replace(destination)
        finally:
            partial.unlink(missing_ok=True)


class ReadOnlyGitHub(GitHub):
    def api(self, path, method="GET", data=None, absent_ok=False):
        require(method == "GET" and data is None, "Published-release verification permits GET requests only.")
        return super().api(path, method, data, absent_ok)



def verify_candidate(blobs, lock):
    candidate_role = next(key for key, value in lock['artifacts'].items()
                          if value['id'] == 11507920876)
    update_role = next(key for key, value in lock['artifacts'].items()
                       if value['id'] == 11510267028)
    with checked_zip(blobs[candidate_role]) as candidate:
        require(set(candidate.namelist()) == CANDIDATE_MEMBERS, 'Candidate inventory differs.')
        contents = {name: candidate.read(name) for name in CANDIDATE_MEMBERS}
    with checked_zip(blobs[update_role]) as updater:
        require(set(updater.namelist()) == UPDATE_MEMBERS, 'Updater artifact inventory differs.')
        contents.update({name: updater.read(name) for name in UPDATE_MEMBERS if name != 'SHA256SUMS.txt'})
        contents['UPDATE-SHA256SUMS.txt'] = updater.read('SHA256SUMS.txt')
    for name, identity in lock['archives'].items():
        raw = contents[name]
        require(len(raw) == identity['bytes'] and sha(raw) == identity['sha256'], 'Frozen archive differs: ' + name)
        with checked_zip(raw):
            pass
    checksums(contents['SHA256SUMS.txt'], {STARTER, SOURCES}, contents.__getitem__)
    checksums(contents['UPDATE-SHA256SUMS.txt'], {UPDATE}, contents.__getitem__)
    build = json.loads(contents['BUILD-PROVENANCE.json'])
    require(build['sourceCommit'] == SOURCE, 'Candidate build source differs.')
    with checked_zip(contents[STARTER]) as starter:
        core_files = {name.removeprefix('native-workbench/'): sha(starter.read(name))
                      for name in starter.namelist() if not name.endswith('/')}
        manifest = json.loads(starter.read('native-workbench/manifest.json'))
        require(manifest['version'] == VERSION and len(manifest['files']) == 72
                and len({item['path'] for item in manifest['files']}) == 72, 'Core inventory differs.')
        for item in manifest['files']:
            raw = starter.read('native-workbench/' + item['path'])
            require(len(raw) == item['bytes'] and sha(raw) == item['sha256'], 'Core inventory mismatch.')
        for path, digest in [('workspace/catalog-sources.json', TRUST_SHA),
                             ('workspace/setup-profile.json', PROFILE_SHA)]:
            raw = starter.read('native-workbench/' + path)
            require(sha(raw) == digest and raw == source_bytes(path), 'Published pack trust/selection differs.')
        source = json.loads(starter.read('native-workbench/SOURCE-AVAILABILITY.json'))['sourceArtifact']
        require(source['bytes'] == lock['archives'][SOURCES]['bytes']
                and source['sha256'] == lock['archives'][SOURCES]['sha256'], 'Starter source companion differs.')
    with checked_zip(contents[SOURCES]) as archive:
        recovery = json.loads(archive.read('SOURCE-RECOVERY.json'))
        require(recovery['release'] == VERSION, 'Source recovery version differs.')
        entries = recovery['current_source_files']
        require(len(entries) == len({item['path'] for item in entries}), 'Duplicate source inventory entries.')
        for item in entries:
            raw = archive.read(item['path'])
            require(len(raw) == item['bytes'] and sha(raw) == item['sha256'], 'Source inventory differs.')
            require(item['path'].startswith('current/') and
                    raw == source_bytes(item['path'].removeprefix('current/')), 'Source bytes differ from accepted Git source.')
    update = json.loads(contents['BUILD-UPDATE-PROVENANCE.json'])
    require(update['sourceCommit'] == SOURCE and update['packagingCommit'] == UPDATER_SOURCE
            and update['applicationRebuilt'] is False and update['baseVersion'] == '0.10.1'
            and update['targetVersion'] == VERSION and update['baselineSha256'] == BASELINE_SHA
            and update['starterSha256'] == lock['archives'][STARTER]['sha256']
            and update['updateSha256'] == lock['archives'][UPDATE]['sha256']
            and update['archive'] == {'file': UPDATE, **lock['archives'][UPDATE]}
            and update['coreFilesVerified'] == 72 and update['unchangedPackFiles'] == 143
            and update['productionTrustUnchanged'] is True and update['setupSelectionUnchanged'] is True
            and update['launcherSourceCommit'] == SOURCE, 'Updater provenance differs.')
    for name, digest in update['updaterImplementationSha256'].items():
        require(sha(source_bytes('scripts/' + name)) == digest, 'Updater helper source differs.')
    with checked_zip(contents[UPDATE]) as archive:
        recipe = json.loads(archive.read('update/update-manifest.json'))
        require(recipe['kind'] == 'native-core-update' and recipe['base_version'] == '0.10.1'
                and recipe['target_version'] == VERSION and recipe['obsolete'] == []
                and recipe['base_manifest_sha256'] == update['baseManifestSha256']
                and recipe['target_manifest_sha256'] == core_files['manifest.json'],
                'Updater recipe differs.')
        inventory = json.loads(archive.read('update-inventory.json'))['files']
        require(len(inventory) == len({item['path'] for item in inventory}), 'Duplicate updater inventory.')
        for item in inventory:
            raw = archive.read(item['path'])
            require(len(raw) == item['bytes'] and sha(raw) == item['sha256'], 'Updater inventory mismatch.')
        require(sha(archive.read('UpdateWorkbench.exe')) == update['launcherSha256'], 'Updater launcher differs.')
        for item in recipe['operations']:
            raw = archive.read('update/blobs/' + item['blob'])
            require(len(raw) == item['bytes'] and sha(raw) == item['sha256']
                    and item['sha256'] == core_files[item['path']], 'Updater payload differs from accepted starter.')
        require(sha(archive.read('update/blobs/' + recipe['target_manifest_blob'])) == core_files['manifest.json'],
                'Updater manifest blob differs.')
    return contents, core_files

def check_report(raw, spec, core_files, lock):
    require(sha(raw) == spec['sha256'], 'Accepted native report hash differs.')
    report = json.loads(raw)
    require(report.get('success') is True and report.get('nativeWindowsExecuted') is True
            and report.get('passed') == spec['passed'] and report.get('skips') == spec['skips']
            and report.get('failed', 0) == 0 and not report.get('failures') and not report.get('error'),
            'Native report did not pass its locked scope.')
    require(report.get('sourceCommit') == SOURCE and
            report.get('gateSha256') == sha(source_bytes(spec['gate'], spec['gateCommit'])),
            'Report source/gate identity differs.')
    recorded_validator = report.get('validatorCommit', report.get('validationCommit'))
    if recorded_validator is not None:
        require(recorded_validator == spec.get('validatorCommit'), 'Native validator commit differs.')
    # Older gates recorded only sourceCommit. Their exact gate hash, artifact
    # digest and artifact run commit provide the separate validator binding.
    artifact_run = lock['runs'][lock['artifacts'][spec['artifact']]['run']]
    require(spec.get('validatorCommit') == artifact_run['sourceCommit'] == spec['gateCommit'],
            'Validator gate and retained artifact run differ.')
    if 'updateSha256' in report:
        require(report.get('nativeWindowsHost') is True and report.get('baseVersion') == '0.10.1'
                and report.get('appVersion') == VERSION and report.get('coreFilesVerified') == 72
                and report['starterSha256'] == lock['archives'][STARTER]['sha256']
                and report['updateSha256'] == lock['archives'][UPDATE]['sha256']
                and report['baselineSha256'] == BASELINE_SHA, 'Native update identities differ.')
        require(report['updateAttempts']['install']['status'] == 'installed'
                and report['updateAttempts']['repeat']['status'] == 'already-installed',
                'Native update/repeat did not succeed.')
        preserved = report['preservation']
        require(preserved['files'] > 0 and not preserved['changes']
                and all(name == 'user-data/session.lock' and digest == sha(b'\0')
                        for name, digest in preserved['additions'].items()), 'User files were not preserved.')
    else:
        require(report.get('assetSha256') == lock['archives'][STARTER]['sha256'], 'Tested application archive differs.')
        files = report.get('appFiles', report.get('applicationFiles', {}))
        if isinstance(files, dict):
            for name, digest in files.items():
                require(core_files.get(name.replace('\\', '/')) == digest, 'Tested core file differs: ' + name)
        for key in ('appSha256', 'executableSha256'):
            if key in report:
                require(report[key] == core_files['NativeWorkbench.exe'], 'Tested native executable differs.')
    return report

def collect_reports(blobs, lock, core_files):
    result = {}
    for key, spec in lock['reports'].items():
        with checked_zip(blobs[spec['artifact']]) as archive:
            raw = archive.read(spec['path'])
            report = check_report(raw, spec, core_files, lock)
            prefix = spec['path'].rsplit('/', 1)[0] + '/' if '/' in spec['path'] else ''
            for item in report.get('evidenceFiles', []):
                raw_item = archive.read(prefix + item['file'].replace('\\', '/'))
                require(len(raw_item) == item['bytes'] and sha(raw_item) == item['sha256'],
                        'Retained native evidence mismatch.')
        result[key] = {'path': spec['path'], 'artifact': spec['artifact'], 'sha256': sha(raw),
                       'passed': report['passed'], 'skips': report['skips'],
                       'sourceCommit': SOURCE, 'gateCommit': spec['gateCommit'], 'success': True}
    return result

def download_artifacts(client, input_dir, lock):
    input_dir.mkdir(parents=True, exist_ok=True)
    for item in lock['artifacts'].values():
        metadata = client.api('/actions/artifacts/' + str(item['id']))
        require(metadata['workflow_run']['id'] == lock['runs'][item['run']]['id']
                and metadata['workflow_run']['head_sha'] == lock['runs'][item['run']]['sourceCommit'] and not metadata['expired']
                and metadata['name'] == item['name'] and metadata['size_in_bytes'] == item['bytes']
                and metadata['digest'] == 'sha256:' + item['sha256'], 'Artifact metadata differs or expired.')
        client.download(client.base + '/actions/artifacts/' + str(item['id']) + '/zip',
                        input_dir / item['file'], item['sha256'], item['bytes'], True)

def prepare(input_dir, output_dir, publish_sha, online_evidence=None):
    lock = acceptance_lock()
    verify_source_identity(publish_sha)
    require(not output_dir.exists() or not any(output_dir.iterdir()), 'Preparation output must be empty.')
    blobs = {}
    for key, item in lock['artifacts'].items():
        raw = (input_dir / item['file']).read_bytes()
        require(len(raw) == item['bytes'] and sha(raw) == item['sha256'], 'Artifact identity differs: ' + key)
        with checked_zip(raw):
            pass
        blobs[key] = raw
    contents, core_files = verify_candidate(blobs, lock)
    reports = collect_reports(blobs, lock, core_files)
    output_dir.mkdir(parents=True, exist_ok=True)
    for name, raw in contents.items():
        (output_dir / name).write_bytes(raw)
    with zipfile.ZipFile(output_dir / 'WINDOWS-EVIDENCE.zip', 'w', zipfile.ZIP_DEFLATED) as archive:
        for key, item in lock['artifacts'].items():
            if item['id'] not in {11507920876, 11510267028}:
                archive.writestr('original-ci-artifacts/' + item['file'], blobs[key])
        for item in lock['reports'].values():
            name = 'validation-sources/' + item['gateCommit'] + '/' + item['gate']
            if name not in archive.namelist():
                archive.writestr(name, source_bytes(item['gate'], item['gateCommit']))
        # Validators import shared helpers and the updater has additional build
        # sources. Retain complete script trees at each exact supporting commit.
        commits = {SOURCE, UPDATER_SOURCE, VALIDATOR_SOURCE} | {item['gateCommit'] for item in lock['reports'].values()}
        for commit in sorted(commits):
            listing = subprocess.check_output(['git', 'ls-tree', '-r', '--name-only', commit, 'scripts'], cwd=ROOT, text=True)
            for path in listing.splitlines():
                archive.writestr('helper-sources/' + commit + '/' + path, source_bytes(path, commit))
        for path in sorted((ROOT / 'knowledge/evidence').glob('tool-library-0.11.0-*.json')):
            archive.write(path, 'repository-evidence/' + path.name)
        archive.writestr('accepted-promotion-lock.json', json_bytes(lock))
        if online_evidence:
            archive.writestr('promotion-run-verification.json', json_bytes(online_evidence))
    validation = {
        'schema': 1, 'version': VERSION, 'releaseTag': TAG, 'packagedSourceCommit': SOURCE,
        'updaterPackagingCommit': UPDATER_SOURCE, 'publicationCommit': publish_sha,
        'recordedUtc': datetime.now(timezone.utc).isoformat(), 'acceptedApplicationArchivesRebuilt': False,
        'acceptedRuns': lock['runs'], 'acceptedArtifacts': lock['artifacts'], 'nativeReports': reports,
        'productionPublisherFingerprint': FINGERPRINT, 'productionTrustUnchanged': True,
        'scope': 'Exact category candidate and matching source, exact 0.10.1 updater, native Windows evidence in ordinary and space-containing paths; no rebuilding during publication.',
        'limits': [
            'Original candidate workflow failed its superseded category validator; its build and 32 workspace checks per path passed. Final category validation is separately retained.',
            'References omitted its optional embedded updater helper; the separate exact 0.10.1 updater passed.',
            'No new all-32-pack Full download or complete optional-pack scientific rerun is claimed; pack payloads and publisher trust are unchanged.',
            'Offline gates deny Python host socket operations; native subprocesses are not OS-firewalled.',
            'Finite hosted Windows captures do not establish physical trackpad, high-DPI, institutional proxy or endpoint-security approval.',
            'Updater supports only the published 0.10.1 baseline. Its private-runtime transaction is tested; its interactive picker was not tested.'
        ],
        'originalCompanions': 'Frozen candidate and updater companions retain their creation-time bytes. Original checksum files are retained separately; this release record supersedes their pending validation status.',
        'assets': [{'file': p.name, 'bytes': p.stat().st_size, 'sha256': sha(p.read_bytes())}
                   for p in sorted(output_dir.iterdir())]
    }
    (output_dir / 'RELEASE-VALIDATION.json').write_bytes(json_bytes(validation))
    (output_dir / 'EVIDENCE-SHA256SUMS.txt').write_text(''.join(
        sha(p.read_bytes()) + '  ' + p.name + '\n' for p in sorted(output_dir.iterdir())
        if p.name not in lock['archives']), encoding='utf-8')
    require({p.name for p in output_dir.iterdir()} == ASSET_NAMES, 'Prepared release inventory differs.')
    return validation

def verify_public_downloads(client, release_id, files, publish_sha, receipt_path, verification_only=False):
    # Draft asset browser URLs can name a temporary untagged release. Refresh
    # after publication and accept only the final canonical tagged URLs.
    published = client.api(f"/releases/{release_id}")
    require(published["id"] == release_id and published["tag_name"] == TAG and
            not published["draft"] and published["prerelease"], "Expected the existing published prerelease.")
    require(client.api("/git/ref/tags/" + TAG)["object"]["sha"] == publish_sha, "Published tag identity differs.")
    by_name = {a["name"]: a for a in published["assets"]}
    require(len(by_name) == len(published["assets"]) == len(files) and set(by_name) == {p.name for p in files},
            "Published asset inventory differs.")
    receipt = json.loads(receipt_path.read_bytes()) if receipt_path.is_file() else {}
    receipt.update(success=False, phase="public-download-verification", verificationOnly=verification_only,
                   release=published["html_url"], releaseId=release_id, publicationCommit=publish_sha,
                   packagedSourceCommit=SOURCE, releasePublished=True, releaseDraft=False, publicDownloads=[])
    receipt_path.write_bytes(json_bytes(receipt))
    with tempfile.TemporaryDirectory(prefix="verify-workbench-public-") as temporary:
        for path in files:
            asset = by_name[path.name]
            digest = sha(path.read_bytes())
            expected_url = f"https://github.com/{REPOSITORY}/releases/download/{TAG}/" + urllib.parse.quote(path.name)
            require(asset["browser_download_url"] == expected_url and asset["state"] == "uploaded"
                    and asset["size"] == path.stat().st_size and asset["digest"] == "sha256:" + digest,
                    "Published asset metadata or canonical URL differs: " + path.name)
            for attempt in range(5):
                try:
                    client.download(expected_url, Path(temporary) / path.name, digest, path.stat().st_size)
                    break
                except RuntimeError as error:
                    if str(error) != "Download failed: HTTP 404" or attempt == 4:
                        raise
                    time.sleep((2, 5, 10, 20)[attempt])
            receipt["publicDownloads"].append({"file": path.name, "bytes": path.stat().st_size,
                                                "sha256": digest, "url": expected_url})
            receipt_path.write_bytes(json_bytes(receipt))
    require(client.api("/git/ref/tags/" + TAG)["object"]["sha"] == publish_sha, "Published tag identity changed.")
    receipt.update(success=True, phase="completed")
    receipt_path.write_bytes(json_bytes(receipt))
    return receipt




def verify_candidate_online(args):
    require(os.environ.get('GITHUB_REPOSITORY') == REPOSITORY
            and os.environ.get('GITHUB_REF') == 'refs/heads/release/verify-app-' + VERSION
            and os.environ.get('GITHUB_SHA') == args.publish_sha, 'Wrong verification branch, repository or commit.')
    lock = acceptance_lock()
    verify_source_identity(args.publish_sha)
    client = ReadOnlyGitHub(os.environ.get('GH_TOKEN'))
    runs = verify_runs(client, lock)
    download_artifacts(client, args.input_dir, lock)
    prepare(args.input_dir, args.output_dir, args.publish_sha, runs)
    receipt = {'success': True, 'phase': 'candidate-preparation', 'remoteMutations': False,
               'verificationCommit': args.publish_sha, 'packagedSourceCommit': SOURCE,
               'preparedAssets': len(list(args.output_dir.iterdir())), 'releasePublished': False,
               'validationSha256': sha((args.output_dir / 'RELEASE-VALIDATION.json').read_bytes())}
    args.receipt.parent.mkdir(parents=True, exist_ok=True)
    args.receipt.write_bytes(json_bytes(receipt))
    print(json.dumps(receipt))

def publish(args):
    require(os.environ.get('GITHUB_REPOSITORY') == REPOSITORY
            and os.environ.get('GITHUB_REF') == 'refs/heads/' + BRANCH
            and os.environ.get('GITHUB_SHA') == args.publish_sha, 'Wrong publication branch, repository or commit.')
    lock = acceptance_lock()
    verify_source_identity(args.publish_sha)
    notes = (ROOT / 'docs/releases/0.11.0.md').read_text(encoding='utf-8')
    require(VERSION in notes and len(notes) >= 200, 'Release notes are missing or incomplete.')
    client = GitHub(os.environ.get('GH_TOKEN'))
    require(client.api('/git/ref/tags/' + TAG, absent_ok=True) is None
            and client.api('/releases/tags/' + TAG, absent_ok=True) is None,
            'Tag/release already exists; refusing replacement.')
    verify_merged(client, args.publish_sha)
    runs = verify_runs(client, lock)
    download_artifacts(client, args.input_dir, lock)
    prepare(args.input_dir, args.output_dir, args.publish_sha, runs)
    verify_merged(client, args.publish_sha)
    require(client.api('/git/ref/tags/' + TAG, absent_ok=True) is None
            and client.api('/releases/tags/' + TAG, absent_ok=True) is None,
            'Tag/release appeared during preparation; refusing replacement.')
    receipt = {'success': False, 'phase': 'prepared', 'publicationCommit': args.publish_sha,
               'packagedSourceCommit': SOURCE, 'releaseId': None, 'releaseDraft': None,
               'releasePublished': False, 'remoteMutations': [], 'publicDownloads': []}
    args.receipt.parent.mkdir(parents=True, exist_ok=True)
    def checkpoint(phase, **values):
        receipt.update(phase=phase, recordedUtc=datetime.now(timezone.utc).isoformat(), **values)
        args.receipt.write_bytes(json_bytes(receipt))
    checkpoint('prepared')
    # All artifact identities, inventories and completed native evidence have
    # passed before the first mutation. Never force tags or clobber assets.
    receipt['remoteMutations'].append({'action': 'create-tag', 'status': 'requested', 'tag': TAG})
    checkpoint('create-tag-requested', tagCreated=None)
    client.api('/git/refs', 'POST', {'ref': 'refs/tags/' + TAG, 'sha': args.publish_sha})
    receipt['remoteMutations'][-1]['status'] = 'confirmed'
    checkpoint('tag-created', tagCreated=True)
    receipt['remoteMutations'].append({'action': 'create-draft', 'status': 'requested'})
    checkpoint('create-draft-requested', releaseDraft=None)
    release = client.api('/releases', 'POST', {'tag_name': TAG, 'target_commitish': args.publish_sha,
        'name': 'Native Workbench ' + VERSION, 'body': notes, 'draft': True,
        'prerelease': True, 'make_latest': 'false'})
    receipt['remoteMutations'][-1]['status'] = 'confirmed'
    checkpoint('draft-created', releaseId=release['id'], releaseDraft=True, releasePublished=False)
    files = sorted(args.output_dir.iterdir())
    receipt['remoteMutations'].append({'action': 'upload-assets', 'status': 'requested',
                                      'files': [path.name for path in files]})
    checkpoint('asset-upload-requested')
    subprocess.run(['gh', 'release', 'upload', TAG, *map(str, files), '--repo', REPOSITORY], check=True)
    receipt['remoteMutations'][-1]['status'] = 'confirmed'
    checkpoint('asset-upload-completed')
    uploaded = client.api('/releases/' + str(release['id']))
    require(uploaded['draft'] and uploaded['prerelease'] and uploaded['tag_name'] == TAG, 'Draft state differs.')
    by_name = {a['name']: a for a in uploaded['assets']}
    require(len(by_name) == len(uploaded['assets']) == len(files)
            and set(by_name) == {p.name for p in files}, 'Uploaded inventory differs.')
    with tempfile.TemporaryDirectory(prefix='verify-workbench-release-') as temporary:
        for path in files:
            asset = by_name[path.name]
            require(asset['state'] == 'uploaded' and asset['size'] == path.stat().st_size
                    and asset['digest'] == 'sha256:' + sha(path.read_bytes()), 'Upload identity differs.')
            client.download(asset['url'], Path(temporary) / path.name,
                            sha(path.read_bytes()), path.stat().st_size, True)
    verify_merged(client, args.publish_sha)
    require(client.api('/git/ref/tags/' + TAG)['object']['sha'] == args.publish_sha,
            'Tag changed before publication; leaving assets in draft.')
    receipt['remoteMutations'].append({'action': 'publish-draft', 'status': 'requested'})
    checkpoint('publication-requested', releasePublished=None, releaseDraft=None)
    published = client.api('/releases/' + str(release['id']), 'PATCH',
                           {'draft': False, 'prerelease': True, 'make_latest': 'false'})
    receipt['remoteMutations'][-1]['status'] = 'confirmed'
    checkpoint('publication-response', releasePublished=not published['draft'],
               releaseDraft=published['draft'], releaseId=published['id'])
    require(not published['draft'] and published['prerelease'], 'Release was not published.')
    verify_public_downloads(client, release['id'], files, args.publish_sha, args.receipt)
    print(json.dumps({'published': published['html_url'], 'verifiedAssets': len(files)}))

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input-dir', required=True, type=Path)
    parser.add_argument('--output-dir', required=True, type=Path)
    parser.add_argument('--publish-sha', required=True)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--prepare-only', action='store_true')
    mode.add_argument('--verify-candidate', action='store_true')
    parser.add_argument('--receipt', type=Path, default=Path('public-download-verification.json'))
    args = parser.parse_args()
    try:
        if args.prepare_only:
            prepare(args.input_dir, args.output_dir, args.publish_sha)
            print(json.dumps({'prepared': True, 'remoteMutations': False}))
        elif args.verify_candidate:
            verify_candidate_online(args)
        else:
            publish(args)
    except Exception as error:
        receipt = json.loads(args.receipt.read_bytes()) if args.receipt.is_file() else {
            'phase': 'promotion', 'publicationCommit': args.publish_sha,
            'packagedSourceCommit': SOURCE, 'publicDownloads': []}
        receipt.update(success=False, failureType=type(error).__name__,
                       error=str(error) if isinstance(error, (ValueError, RuntimeError)) else 'See workflow log.',
                       recordedUtc=datetime.now(timezone.utc).isoformat())
        args.receipt.parent.mkdir(parents=True, exist_ok=True)
        args.receipt.write_bytes(json_bytes(receipt))
        raise

if __name__ == '__main__':
    main()
