#!/usr/bin/env python3
"""Promote one accepted 0.10.1 candidate without rebuilding or replacing assets.

The acceptance lock records the exact patch candidate and completed Windows
regression evidence reviewed on 2026-10-07. Only the release branch at
the locked patch PR merge commit may publish. Preparation and published-release
verification make no remote mutations.
"""
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
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile

REPOSITORY = 'comparativechrono/workbench'
TAG = 'app-v0.10.1'
VERSION = '0.10.1'
BRANCH = 'release/app-0.10.1'
FINGERPRINT = '8d2093f9fafd71de56fea2038faeb2efa0964767d3235430b06428132cdc8505'
BASELINE_SHA = '659a08911cec65b8dc1ce0dd9f47fea25350a39b619c7f0aea663bae71a871ae'
BASELINE_SOURCE = '5a390acd8440856e3f4e32de237322a18bb82d7e'
BASELINE_TESTED_FILES_SHA = '2b5e945a6a0a8a9402bfc5723a2641bcb198d31f94f9c2424b780ee14c3e0591'
PUBLISHED_TRUST_SHA = '240cef994004c040584d3b8806bb361683693b1e7c0e92c9aedeaddc683fbefc'
PUBLISHED_PROFILE_SHA = '4cad899dcc1f6541f6edecc3ace7d0d4dd5d6103b1b16218fece0c0b68d2a4ba'
STARTER = 'native-workbench-0.10.1-starter-windows.zip'
UPDATE = 'native-workbench-0.10.1-update-from-0.10.0.zip'
SOURCES = 'native-workbench-0.10.1-source.zip'
ROOT = Path(__file__).resolve().parents[1]
# Frozen after independent archive/report review and successful run37634723095.
# Every promotion/preparation path validates this completed acceptance lock.
# Artifacts are the exact GitHub artifact ZIP identities, not their contents.
ACCEPTED = {
    "sourceCommit": "00b53cdded5db3bb176ee7e5a06546b8a0c66fff",
    "runId": 37634723095,
    "prNumber": 5,
    "fingerprint": "8d2093f9fafd71de56fea2038faeb2efa0964767d3235430b06428132cdc8505",
    "coreFiles": 72,
    "archives": {
        "native-workbench-0.10.1-source.zip": {
            "bytes": 46832829,
            "sha256": "4130c105e0ce0956c234718f93926d1f9b3f6bfd81048b8fc6e8823617c583ab"
        },
        "native-workbench-0.10.1-starter-windows.zip": {
            "bytes": 17032722,
            "sha256": "a8c4d374104d62fdf46dbd405e9d5bc36f5e2ea191f573faa63cfb29b433ba79"
        },
        "native-workbench-0.10.1-update-from-0.10.0.zip": {
            "bytes": 12858983,
            "sha256": "fbf1f20d93c1fe781608cba6d48c948979986c06cdb9a4ce5b825b088d2fc3fb"
        }
    },
    "artifacts": {
        "candidate": {
            "id": 11488695103,
            "name": "setup-patch-candidate-00b53cdded5db3bb176ee7e5a06546b8a0c66fff",
            "bytes": 76212926,
            "sha256": "50b995aa56e50d05cfcbf2a3dc59eea60ee4af657e2749191ddf80db75e74822",
            "file": "candidate.zip"
        },
        "ordinary": {
            "id": 11489175077,
            "name": "setup-patch-windows-ordinary-1",
            "bytes": 7869073,
            "sha256": "98557aa03aca4f2e244392f66e473c7f09b1342e50de0ec4ba53bb53c686ac6b",
            "file": "ordinary.zip"
        },
        "spaces": {
            "id": 11487569680,
            "name": "setup-patch-windows-path with spaces-1",
            "bytes": 7868005,
            "sha256": "9218df6d9082cf9d22d7e49fe362ccf82740d94b52cdb3bafb5fd7902be9774e",
            "file": "spaces.zip"
        },
        "production-full": {
            "id": 11489622944,
            "name": "setup-patch-production-full-00b53cdded5db3bb176ee7e5a06546b8a0c66fff-1",
            "bytes": 467522,
            "sha256": "5a5a332cc1e88bbdf0906720ea8453e49c1f303b29fe25e7c1ed62e60229f99b",
            "file": "production-full.zip"
        }
    },
    "reportHashes": {
        "ordinary-setup": "0557f1cbce8c6f7a0dce66a66dfeb8d6925f5a6322a927edb3febc36c74a23d4",
        "ordinary-workspace": "d581084de2702ef0b7a4607650830646535ef88b8517b46e6fcf15f163d97d50",
        "ordinary-references": "88747e7d0a87a2ec5153130597a1c1942563d59447721962637a11963c0b5f13",
        "ordinary-results": "a6a90285887fce30bd662a371764cf61c6fcfbc81b24e3905e3b3db10b81ed8d",
        "ordinary-update": "8636a0c36c939e2453b2465c70d18a0ffbd2b469d4ef005760dc9ab7958c8397",
        "ordinary-negative-control": "52a0b36d29fd8386061b997e0ddd60678a210f7c7128d86da00a55aa8c3e01b3",
        "spaces-setup": "ae3e0dd68b2b4e7ad1f4a9a69ba2e59990fff0e5a2dfb7e4786d4f018bea14ec",
        "spaces-workspace": "5128b75f6a982ab4a8821563a15b49d85646646634f6692cb983ecb1afa76eef",
        "spaces-references": "64cdca36db2fd1140889826161b1a7495c3df10874b9ee8795b196075334e670",
        "spaces-results": "1c30a04b0703da62d2a5d29dc5a28167a3c40a8a6a86978257134329794d54b2",
        "spaces-update": "e96a733f79ed1cd8d1200d9ef44cbc6a0daad9b4c424ff45dd39be72204aa0bc",
        "spaces-negative-control": "a528b72055a5c43d525886175dd51022a48311bd3b8efe39dfcfba5455cfd304",
        "production-full": "ebcfd285acfbe48a59bf2ef61927698319fd3e4acfda7555d5b7bfc7917ad41f"
    }
}

CANDIDATE_MEMBERS = {STARTER, UPDATE, SOURCES, 'BUILD-PROVENANCE.json',
                     'BUILD-UPDATE-PROVENANCE.json', 'source-metadata.json', 'SHA256SUMS.txt'}
ASSET_NAMES = CANDIDATE_MEMBERS | {'WINDOWS-EVIDENCE.zip', 'RELEASE-VALIDATION.json', 'EVIDENCE-SHA256SUMS.txt'}
NON_APPLICATION_FILES = {
    'README.md', 'scripts/publish_app_0101.py', 'tests/test_publish_app_0101.py',
    '.github/workflows/publish-app-0.10.1.yml',
}
REPORTS = {
    'setup': ('setup-evidence/native-setup.json', 14, 'scripts/check_setup_windows.py'),
    'workspace': ('workspace-evidence/native-ui.json', 32, 'scripts/check_workspace_ui_windows.py'),
    'references': ('references-evidence/native-references.json', 8, 'scripts/check_references_windows.py'),
    'results': ('results-evidence/native-results.json', 9, 'scripts/check_results_windows.py'),
    'update': ('update-evidence/native-update.json', 13, 'scripts/check_update_0101_windows.py'),
}

NEGATIVE_REPORT = 'setup-negative-control/native-setup-negative-control.json'
REPORT_KEYS = {label + '-' + kind for label in ('ordinary', 'spaces')
               for kind in (*REPORTS, 'negative-control')} | {'production-full'}


def require(value, message):
    if not value:
        raise ValueError(message)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def json_bytes(value):
    return (json.dumps(value, indent=2, ensure_ascii=False) + '\n').encode()


def exact_hash(value, length=64):
    return isinstance(value, str) and re.fullmatch('[0-9a-f]{' + str(length) + '}', value) is not None


def acceptance_lock():
    require(exact_hash(ACCEPTED.get('sourceCommit'), 40) and
            type(ACCEPTED.get('runId')) is int and ACCEPTED['runId'] > 0,
            'No completed, pinned production candidate; refusing promotion.')
    require(type(ACCEPTED.get('prNumber')) is int and ACCEPTED['prNumber'] > 0,
            'Accepted patch PR identity is missing.')
    require(ACCEPTED.get('fingerprint') == FINGERPRINT,
            'Accepted production publisher fingerprint differs.')
    require(type(ACCEPTED.get('coreFiles')) is int and ACCEPTED['coreFiles'] >= 72,
            'Accepted core inventory is missing.')
    archives = ACCEPTED.get('archives', {})
    require(set(archives) == {STARTER, UPDATE, SOURCES}, 'Accepted archive inventory is incomplete.')
    for value in archives.values():
        require(type(value.get('bytes')) is int and value['bytes'] > 0 and exact_hash(value.get('sha256')),
                'Accepted archive identity is incomplete.')
    artifacts = ACCEPTED.get('artifacts', {})
    require(set(artifacts) == {'candidate', 'ordinary', 'spaces', 'production-full'},
            'Accepted artifact inventory is incomplete.')
    ids, files = set(), set()
    for value in artifacts.values():
        require(type(value.get('id')) is int and value['id'] > 0 and value['id'] not in ids and
                type(value.get('bytes')) is int and value['bytes'] > 0 and exact_hash(value.get('sha256')) and
                isinstance(value.get('file'), str) and re.fullmatch(r'[a-z0-9-]+\.zip', value['file']) and
                value['file'] not in files and isinstance(value.get('name'), str) and value['name'],
                'Accepted artifact identity is incomplete or duplicated.')
        ids.add(value['id']); files.add(value['file'])
    require(set(ACCEPTED.get('reportHashes', {})) == REPORT_KEYS and
            all(exact_hash(value) for value in ACCEPTED['reportHashes'].values()),
            'Accepted native report identities are incomplete.')
    return ACCEPTED


def checked_zip(raw):
    archive = zipfile.ZipFile(io.BytesIO(raw))
    names = archive.namelist()
    require(len(names) == len(set(names)), 'Duplicate ZIP members.')
    require(all(not PurePosixPath(n).is_absolute() and '..' not in PurePosixPath(n).parts
                and '\\' not in n and ':' not in n for n in names), 'Unsafe ZIP member.')
    require(archive.testzip() is None, 'ZIP CRC validation failed.')
    return archive


def verify_source_identity(publish_sha):
    acceptance_lock()
    require(exact_hash(publish_sha, 40), 'Expected exact publishing commit.')
    subprocess.run(['git', 'merge-base', '--is-ancestor', ACCEPTED['sourceCommit'], publish_sha], cwd=ROOT, check=True)
    changed = subprocess.check_output(['git', 'diff', '--name-only', ACCEPTED['sourceCommit'], publish_sha],
                                      cwd=ROOT, text=True).splitlines()
    require(all(p.startswith(('knowledge/', 'docs/')) or p in NON_APPLICATION_FILES for p in changed),
            'Application, build or pack code changed after accepted candidate: ' + repr(changed))


def source_bytes(path):
    return subprocess.check_output(['git', 'show', ACCEPTED['sourceCommit'] + ':' + path], cwd=ROOT)


def checksums(raw, expected, read):
    rows = [line.split('  ', 1) for line in raw.decode().splitlines()]
    require(all(len(row) == 2 for row in rows) and len(rows) == len(expected)
            and {row[1] for row in rows} == set(expected), 'Checksum inventory differs.')
    require(all(exact_hash(digest) and sha(read(name)) == digest for digest, name in rows),
            'Checksum verification failed.')


def verify_merged(client, publish_sha):
    main = client.api('/git/ref/heads/main')['object']['sha']
    require(main == publish_sha, 'Publication must promote the exact merged main commit.')
    pr = client.api('/pulls/' + str(acceptance_lock()['prNumber']))
    require(pr.get('merged') is True and pr.get('merge_commit_sha') == publish_sha
            and pr.get('base', {}).get('ref') == 'main'
            and pr.get('head', {}).get('ref') == 'fix/tool-setup-0.10.1',
            'Accepted patch PR is not merged at the publication commit.')


def verify_runs(client):
    lock = acceptance_lock()
    run = client.api('/actions/runs/' + str(lock['runId']))
    require(run['head_sha'] == lock['sourceCommit'] and run['status'] == 'completed'
            and run['conclusion'] == 'success' and run['path'] == '.github/workflows/native-setup-patch-candidate.yml',
            'Accepted candidate workflow identity or conclusion differs.')
    names = {'build', 'native (ordinary)', 'native (path with spaces)', 'production-full'}
    data = client.api('/actions/runs/' + str(lock['runId']) + '/jobs?filter=latest&per_page=100')
    jobs = data['jobs']
    require(data['total_count'] == len(jobs) == len(names) and {j['name'] for j in jobs} == names,
            'Unexpected validation job inventory.')
    for job in jobs:
        require(job['conclusion'] == 'success' and job.get('steps'), 'A required validation job did not pass.')
        for step in job['steps']:
            expected = 'skipped' if job['name'] == 'native (path with spaces)' and step['name'] == \
                'Native Windows source pack-manager filesystem regressions' else 'success'
            require(step['conclusion'] == expected, 'Validation contains an unexpected failed or skipped step.')
    return {'runId': lock['runId'], 'sourceCommit': lock['sourceCommit'], 'conclusion': 'success',
            'jobs': [{'id': j['id'], 'name': j['name'], 'conclusion': j['conclusion']} for j in jobs]}


def check_report(report, kind, core_files, gate_bytes):
    count = 4 if kind == 'production' else REPORTS[kind][1]
    expected_skips = ['Optional native core updater gate was not requested.'] if kind == 'references' else []
    require(report.get('success') is True and report.get('nativeWindowsExecuted') is True
            and report.get('passed') == count and report.get('skips') == expected_skips
            and report.get('failed', 0) == 0 and not report.get('failures') and not report.get('error'),
            'Native gate did not pass its required scope: ' + kind)
    require(report.get('sourceCommit') == ACCEPTED['sourceCommit'], 'Native gate source differs.')
    if kind == 'update':
        check_update_report(report)
    else:
        require(report.get('assetSha256') == ACCEPTED['archives'][STARTER]['sha256'],
                'Native gate identifies different application bytes.')
        require(report.get('gateSha256') == sha(gate_bytes), 'Native gate script differs from accepted source.')
        require(bool(report.get('appFiles')), 'Report has no tested application file identities.')
        for name, digest in report['appFiles'].items():
            require(core_files.get(name.replace('\\', '/')) == digest, 'Tested application file differs: ' + name)
    if kind == 'setup':
        require(report.get('gui', {}).get('nativeGUIValidated') is True,
                'Native setup interface was not validated.')
        check_ui_polling(report.get('uiPolling', {}), negative=False)
    if kind == 'workspace':
        require(report.get('nativeGUIValidated') is True, 'Native workspace interface was not validated.')
    if kind == 'results':
        require(report.get('nativeGUIValidated') is True, 'Native results interface was not validated.')
        check_science(report['science'])
    if kind == 'production':
        require(report.get('productionTrustValidated') is True and report.get('unrun') == []
                and report.get('full', {}).get('productionTrustValidated') is True
                and report['full'].get('configuration', 'missing') is None,
                'Production Full used unavailable or substituted publisher trust.')
        science = report['full']['science']
        require(science.get('nativeWindowsExecuted') is True and science.get('networkSocketOperationsDenied') is True
                and science.get('records') == 202, 'Production offline scientific evidence is incomplete.')



def check_ui_polling(observations, negative=False):
    require(observations.get('expectedRegression') is negative and
            isinstance(observations.get('defects'), list) and
            bool(observations['defects']) is negative and
            isinstance(observations.get('navigationDefects'), list) and
            bool(observations['navigationDefects']) is negative and
            all(item in observations['defects'] for item in observations['navigationDefects']),
            'Sustained UI observations do not establish the required fixed or negative-control scope.')
    require(observations.get('immediateCustomFullChecks') is True,
            'Immediate Custom/Full checkbox synchronization was not validated.')
    polling = observations.get('polling', {})
    progress = polling.get('progressStates', [])
    require(isinstance(progress, list) and len(progress) >= 2 and
            len({json.dumps(state, sort_keys=True) for state in progress}) >= 2,
            'Changing live setup status/progress was not observed.')
    require(polling.get('busySamples', 0) >= 20 and polling.get('observedBusySeconds', 0) >= 3,
            'Live setup did not establish sustained status polling.')
    for name in ('idle', 'idleWheel', 'polling'):
        require(observations.get(name, {}).get('frames', 0) > 0, 'Sustained UI sampling is missing: ' + name)
    if negative:
        return
    require(polling.get('disabledSamples') == 0 and polling.get('positionChanges') == [] and
            observations['idle'].get('positionChanges') == [] and
            observations['idleWheel'].get('positionChanges') == [] and
            len(observations['idle'].get('headerHashes', {})) == len(polling.get('headerHashes', {})) == 1,
            'Fixed UI still redraws headers or changes/disables the scroll position.')
    reference = set(observations['idle']['headerHashes'])
    require(set(observations['idleWheel'].get('headerHashes', {})) == reference and
            set(polling.get('headerHashes', {})) == reference and
            all(observations[name].get('pixelComparison') ==
                'BGR bytes only; undefined BitBlt alpha ignored' for name in ('idle', 'idleWheel', 'polling')),
            'Fixed UI header pixels differ from the normalized idle reference.')
    wheel = observations.get('busyWheel', {})
    require(type(wheel.get('before', {}).get('top')) is int and
            type(wheel.get('after', {}).get('top')) is int and
            wheel['before']['top'] > wheel['after']['top'], 'Fixed UI did not scroll during active setup.')


def check_negative_report(report, gate_bytes):
    require(report.get('success') is True and report.get('nativeWindowsExecuted') is True and
            report.get('passed') == 1 and report.get('skips') == [] and
            report.get('failed', 0) == 0 and not report.get('failures') and not report.get('error'),
            'Published negative control did not complete its required scope.')
    require(report.get('sourceCommit') == BASELINE_SOURCE and report.get('appVersion') == '0.10.0' and
            report.get('assetSha256') == BASELINE_SHA and report.get('gateSha256') == sha(gate_bytes),
            'Published negative-control identity differs.')
    normalized = {name.replace('\\', '/'): digest for name, digest in report.get('appFiles', {}).items()}
    identity = sha(json.dumps(normalized, sort_keys=True, separators=(',', ':')).encode())
    require(identity == BASELINE_TESTED_FILES_SHA, 'Published negative-control application files differ.')
    require(report.get('productionTrustValidated') is False, 'Negative control is not a completed Full gate.')
    check_ui_polling(report.get('uiPolling', {}), negative=True)


def check_science(science):
    require(science.get('networkSocketOperationsDeniedForHost') is True and science.get('nativeWindowsExecuted') is True
            and science.get('outputsIndependentlyHashed') == 20 and science.get('nativeCommandsCompared') == 18
            and len(science.get('cwlRunnerReplays', [])) == 5, 'Offline scientific/CWL evidence is incomplete.')


def check_update_report(report):
    require(report.get('nativeWindowsHost') is True and report.get('validationCommit') == ACCEPTED['sourceCommit']
            and report.get('starterSha256') == ACCEPTED['archives'][STARTER]['sha256']
            and report.get('baselineSha256') == BASELINE_SHA
            and report.get('updateSha256') == ACCEPTED['archives'][UPDATE]['sha256']
            and report.get('appVersion') == VERSION and report.get('baseVersion') == '0.10.0'
            and report.get('coreFilesVerified') == ACCEPTED['coreFiles'], 'Updater native identity differs.')
    require(report['updateAttempts']['install']['status'] == 'installed'
            and report['updateAttempts']['repeat']['status'] == 'already-installed', 'Updater transaction differs.')
    preserved = report['preservation']
    require(preserved['files'] > 0 and not preserved['changes'] and all(
        name == 'user-data/session.lock' and digest == sha(b'\0') for name, digest in preserved['additions'].items()),
        'Updater did not preserve existing user files.')
    before, after = report['baselineReferenceRun'], report['updatedReferenceRun']
    require(before['nativeWindowsExecuted'] is True and after['nativeWindowsExecuted'] is True
            and before['referenceSha256'] == after['referenceSha256'] and before['contigs'] == after['contigs'] > 0
            and before['cwlChecked'] is False and after['cwlChecked'] is True,
            'Updated reference provenance evidence differs.')
    check_science(report['science'])


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
    receipt = {"success": False, "phase": "public-download-verification", "verificationOnly": verification_only,
               "release": published["html_url"], "releaseId": release_id, "publicationCommit": publish_sha,
               "packagedSourceCommit": ACCEPTED["sourceCommit"], "publicDownloads": []}
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



def check_packaged_trust(raw):
    sys.path.insert(0, str(ROOT / 'workspace'))
    from pack_manager import validate_source
    from pack_security import key_fingerprint, strict_json
    values = strict_json(raw)
    require(isinstance(values, list) and len(values) == 1, 'Package must contain exactly the reviewed official source.')
    source = validate_source(values[0])
    require(source['id'] == 'native-workbench-official' and source['name'] == 'Native Workbench official tools'
            and source['catalogUrl'] == 'https://raw.githubusercontent.com/comparativechrono/workbench/catalogue/catalogue.json'
            and sorted(source['allowedHosts']) == ['github.com', 'raw.githubusercontent.com', 'release-assets.githubusercontent.com']
            and key_fingerprint(source['publicKey']) == FINGERPRINT,
            'Packaged production source or publisher fingerprint differs.')
    return source


def verify_candidate(raw):
    with checked_zip(raw) as candidate:
        require(set(candidate.namelist()) == CANDIDATE_MEMBERS, 'Candidate member inventory changed.')
        provenance = json.loads(candidate.read('BUILD-PROVENANCE.json'))
        require(provenance.get('sourceCommit') == ACCEPTED['sourceCommit']
                and provenance.get('productionCatalogueConfigured') is True, 'Packaged production source differs.')
        checksums(candidate.read('SHA256SUMS.txt'), ACCEPTED['archives'], candidate.read)
        for name, identity in ACCEPTED['archives'].items():
            content = candidate.read(name)
            require(len(content) == identity['bytes'] and sha(content) == identity['sha256'],
                    'Accepted archive identity differs: ' + name)
            with checked_zip(content):
                pass
        with checked_zip(candidate.read(STARTER)) as starter:
            manifest = json.loads(starter.read('native-workbench/manifest.json'))
            require(manifest['version'] == VERSION and len(manifest['files']) == ACCEPTED['coreFiles'],
                    'Unexpected accepted core inventory.')
            require(len({i['path'] for i in manifest['files']}) == len(manifest['files']), 'Duplicate core inventory path.')
            core_files = {n.removeprefix('native-workbench/'): sha(starter.read(n))
                          for n in starter.namelist() if not n.endswith('/')}
            for item in manifest['files']:
                content = starter.read('native-workbench/' + item['path'])
                require(len(content) == item['bytes'] and sha(content) == item['sha256'], 'Core inventory identity differs.')
            trust = starter.read('native-workbench/workspace/catalog-sources.json')
            check_packaged_trust(trust)
            require(sha(trust) == PUBLISHED_TRUST_SHA, 'Patch changed the published production trust.')
            require(trust == source_bytes('workspace/catalog-sources.json'), 'Packaged publisher trust differs from accepted source.')
            profile_raw = starter.read('native-workbench/workspace/setup-profile.json')
            require(sha(profile_raw) == PUBLISHED_PROFILE_SHA, 'Patch changed the published pack selection.')
            profile = json.loads(profile_raw)
            require(profile == json.loads(source_bytes('workspace/setup-profile.json')) and len(profile['packs']) == 32,
                    'Packaged Full selection differs from accepted source.')
            source_info = json.loads(starter.read('native-workbench/SOURCE-AVAILABILITY.json'))['sourceArtifact']
            require(source_info['bytes'] == ACCEPTED['archives'][SOURCES]['bytes'] and
                    source_info['sha256'] == ACCEPTED['archives'][SOURCES]['sha256'], 'Starter source companion identity differs.')
        with checked_zip(candidate.read(SOURCES)) as archive:
            recovery = json.loads(archive.read('SOURCE-RECOVERY.json'))
            require(recovery['release'] == VERSION, 'Source companion version differs.')
            entries = recovery['current_source_files']
            require(len(entries) == len({i['path'] for i in entries}), 'Duplicate source inventory path.')
            for item in entries:
                content = archive.read(item['path'])
                require(len(content) == item['bytes'] and sha(content) == item['sha256'], 'Source companion inventory differs.')
                path = item['path'].removeprefix('current/')
                if path.startswith(('desktop/', 'workspace/', 'scripts/')):
                    require(content == source_bytes(path), 'Source companion differs from frozen checkout: ' + path)
        update_provenance = json.loads(candidate.read('BUILD-UPDATE-PROVENANCE.json'))
        require(update_provenance['sourceCommit'] == ACCEPTED['sourceCommit'] and
                update_provenance['applicationRebuilt'] is False and
                update_provenance.get('productionTrustUnchanged') is True and
                update_provenance.get('setupSelectionUnchanged') is True and update_provenance['baseVersion'] == '0.10.0' and
                update_provenance['targetVersion'] == VERSION and update_provenance['baselineSha256'] == BASELINE_SHA and
                update_provenance['starterSha256'] == ACCEPTED['archives'][STARTER]['sha256'] and
                update_provenance['updateSha256'] == ACCEPTED['archives'][UPDATE]['sha256'] and
                update_provenance['archive'] == {'file': UPDATE, **ACCEPTED['archives'][UPDATE]} and
                update_provenance['coreFilesVerified'] == ACCEPTED['coreFiles'] and update_provenance['unchangedPackFiles'] == 143,
                'Updater build provenance contradicts frozen identities.')
        with checked_zip(candidate.read(UPDATE)) as archive:
            recipe = json.loads(archive.read('update/update-manifest.json'))
            require(recipe['kind'] == 'native-core-update' and recipe['base_version'] == '0.10.0' and
                    recipe['target_version'] == VERSION and recipe['target_manifest_sha256'] == core_files['manifest.json'] and
                    recipe['base_manifest_sha256'] == update_provenance['baseManifestSha256'] and recipe['obsolete'] == [],
                    'Updater manifest differs.')
            for item in json.loads(archive.read('update-inventory.json'))['files']:
                content = archive.read(item['path'])
                require(len(content) == item['bytes'] and sha(content) == item['sha256'], 'Updater inventory differs.')
            for operation in recipe['operations']:
                content = archive.read('update/blobs/' + operation['blob'])
                require(len(content) == operation['bytes'] and sha(content) == operation['sha256'] and
                        operation['sha256'] == core_files[operation['path']], 'Updater payload differs from accepted starter.')
            require(sha(archive.read('update/blobs/' + recipe['target_manifest_blob'])) == core_files['manifest.json'],
                    'Updater target manifest blob differs.')
        return {name: candidate.read(name) for name in CANDIDATE_MEMBERS}, core_files, profile


def verify_full_state(state, profile):
    fields = ('id', 'version', 'size', 'sha256', 'manifestSha256')
    rows = state.get('rows', [])
    require(state.get('configured') is True and len(rows) == 32 and all(row.get('installed') is True for row in rows)
            and {tuple(row[key] for key in fields) for row in rows} ==
                {tuple(row[key] for key in fields) for row in profile['packs']},
            'Production Full installed selection differs from packaged pins.')
    operation = state['operation']
    require(operation.get('active') is False and operation.get('status') == 'completed'
            and operation.get('completed') == operation.get('count') == 32,
            'Production Full transaction is incomplete.')


def retained_report(archive, path, kind, core_files, gate_bytes, record_key):
    raw = archive.read(path)
    require(sha(raw) == ACCEPTED['reportHashes'][record_key], 'Reviewed native report hash differs: ' + record_key)
    report = json.loads(raw)
    check_report(report, kind, core_files, gate_bytes)
    prefix = path.rsplit('/', 1)[0] + '/' if '/' in path else ''
    for item in report.get('evidenceFiles', []):
        content = archive.read(prefix + item['file'].replace('\\', '/'))
        require(len(content) == item['bytes'] and sha(content) == item['sha256'], 'Retained native evidence differs.')
    return {'path': path, 'sha256': sha(raw), 'passed': report['passed'],
            'skips': report['skips'], 'unrun': report.get('unrun', []), 'success': True}


def prepare(input_dir, output_dir, publish_sha, online_evidence=None):
    lock = acceptance_lock()
    verify_source_identity(publish_sha)
    require(not output_dir.exists() or not any(output_dir.iterdir()), 'Promotion output must be empty.')
    blobs = {}
    for role, identity in lock['artifacts'].items():
        raw = (input_dir / identity['file']).read_bytes()
        require(len(raw) == identity['bytes'] and sha(raw) == identity['sha256'], 'Artifact identity mismatch: ' + role)
        with checked_zip(raw):
            pass
        blobs[role] = raw
    candidate, core_files, profile = verify_candidate(blobs['candidate'])
    reports = {}
    for label in ('ordinary', 'spaces'):
        with checked_zip(blobs[label]) as archive:
            for kind, (path, _, script) in REPORTS.items():
                reports[label + '-' + kind] = retained_report(archive, path, kind, core_files, source_bytes(script), label + '-' + kind)
            raw = archive.read(NEGATIVE_REPORT)
            record_key = label + '-negative-control'
            require(sha(raw) == lock['reportHashes'][record_key], 'Reviewed negative-control hash differs.')
            negative = json.loads(raw)
            check_negative_report(negative, source_bytes('scripts/check_setup_windows.py'))
            reports[record_key] = {'path': NEGATIVE_REPORT, 'sha256': sha(raw), 'passed': 1,
                                   'success': True, 'scope': 'Published 0.10.0 negative control, not patch validation.'}
    with checked_zip(blobs['production-full']) as archive:
        reports['production-full'] = retained_report(archive, 'native-production-full.json', 'production',
            core_files, source_bytes('scripts/check_setup_windows.py'), 'production-full')
        verify_full_state(json.loads(archive.read('full-final-state.json')), profile)
    output_dir.mkdir(parents=True, exist_ok=True)
    for name, content in candidate.items():
        (output_dir / name).write_bytes(content)
    with zipfile.ZipFile(output_dir / 'WINDOWS-EVIDENCE.zip', 'w', zipfile.ZIP_DEFLATED) as evidence:
        for role, identity in lock['artifacts'].items():
            if role != 'candidate':
                evidence.writestr('original-ci-artifacts/' + identity['file'], blobs[role])
        # Keep old failed/pre-production attempts explicitly separate from final gates.
        for path in sorted((ROOT / 'knowledge/evidence').glob('tool-setup-0.10.1-*.json')):
            evidence.write(path, 'repository-evidence/' + path.name)
        for path in sorted({item[2] for item in REPORTS.values()}):
            evidence.writestr('validation-sources/' + path, source_bytes(path))
        evidence.writestr('accepted-promotion-lock.json', json_bytes(lock))
        if online_evidence:
            evidence.writestr('promotion-run-verification.json', json_bytes(online_evidence))
    validation = {
        'schema': 1, 'version': VERSION, 'releaseTag': TAG, 'packagedSourceCommit': lock['sourceCommit'],
        'publicationCommit': publish_sha, 'recordedUtc': datetime.now(timezone.utc).isoformat(),
        'acceptedApplicationArchivesRebuilt': False, 'acceptedRunId': lock['runId'],
        'productionPublisherFingerprint': FINGERPRINT, 'productionTrustValidated': True,
        'acceptedArtifacts': lock['artifacts'], 'nativeReports': reports,
        'scope': 'Exact patch candidate, old-package negative controls and fixed sustained UI checks in ordinary and space-containing native paths, live official Full setup and 0.10.0 migration. No rebuild during publication.',
        'limits': [
            'Full setup validates installation/coexistence of all 32 packs and starter scientific truth; it does not rerun every optional pack scientific fixture.',
            'Offline checks deny Python host socket operations; native subprocesses are not OS-firewalled.',
            'Physical trackpad, broad high-DPI/multi-monitor deployment and institutional proxies are not validated by these hosted Windows gates.',
            'Only the published 0.10.0 baseline has an updater in this release.',
            'Historical test-trust and failed validator evidence remains historical; it does not supply production acceptance.'
        ],
        'originalCompanions': 'All seven original candidate members retain their creation-time bytes and statements. This later validation records final publication readiness.',
        'assets': [{'file': p.name, 'bytes': p.stat().st_size, 'sha256': sha(p.read_bytes())}
                   for p in sorted(output_dir.iterdir())],
    }
    (output_dir / 'RELEASE-VALIDATION.json').write_bytes(json_bytes(validation))
    (output_dir / 'EVIDENCE-SHA256SUMS.txt').write_text(''.join(
        sha(p.read_bytes()) + '  ' + p.name + '\n' for p in sorted(output_dir.iterdir())
        if p.name not in ACCEPTED['archives']), encoding='utf-8')
    require({p.name for p in output_dir.iterdir()} == ASSET_NAMES, 'Prepared release member inventory differs.')
    return validation


def download_artifacts(client, input_dir):
    input_dir.mkdir(parents=True, exist_ok=True)
    for identity in acceptance_lock()['artifacts'].values():
        metadata = client.api('/actions/artifacts/' + str(identity['id']))
        require(metadata['workflow_run']['id'] == ACCEPTED['runId'] and
                metadata['workflow_run']['head_sha'] == ACCEPTED['sourceCommit'] and not metadata['expired'] and
                metadata['name'] == identity['name'] and metadata['size_in_bytes'] == identity['bytes'] and
                metadata['digest'] == 'sha256:' + identity['sha256'], 'Artifact metadata changed or expired.')
        client.download(client.base + '/actions/artifacts/' + str(identity['id']) + '/zip',
                        input_dir / identity['file'], identity['sha256'], identity['bytes'], True)



def verify_candidate_online(args):
    """Download and prepare exact accepted evidence using a GET-only client."""
    require(os.environ.get('GITHUB_REPOSITORY') == REPOSITORY and
            os.environ.get('GITHUB_REF') == 'refs/heads/release/verify-app-0.10.1',
            'Wrong candidate verification repository or branch.')
    require(os.environ.get('GITHUB_SHA') == args.publish_sha, 'Verification commit differs from workflow SHA.')
    acceptance_lock()
    verify_source_identity(args.publish_sha)
    client = ReadOnlyGitHub(os.environ.get('GH_TOKEN'))
    runs = verify_runs(client)
    download_artifacts(client, args.input_dir)
    validation = prepare(args.input_dir, args.output_dir, args.publish_sha, runs)
    receipt = {'success': True, 'phase': 'candidate-preparation', 'remoteMutations': False,
               'publicationCommit': None, 'verificationCommit': args.publish_sha,
               'packagedSourceCommit': ACCEPTED['sourceCommit'], 'acceptedRunId': ACCEPTED['runId'],
               'productionPublisherFingerprint': FINGERPRINT, 'productionTrustValidated': True,
               'preparedAssets': len(list(args.output_dir.iterdir())),
               'validationSha256': sha((args.output_dir / 'RELEASE-VALIDATION.json').read_bytes()),
               'publicDownloads': [], 'releasePublished': False}
    args.receipt.parent.mkdir(parents=True, exist_ok=True)
    args.receipt.write_bytes(json_bytes(receipt))
    print(json.dumps(receipt))
    return validation

def publish(args):
    require(os.environ.get('GITHUB_REPOSITORY') == REPOSITORY and
            os.environ.get('GITHUB_REF') == 'refs/heads/' + BRANCH, 'Wrong publication repository or branch.')
    require(os.environ.get('GITHUB_SHA') == args.publish_sha, 'Publishing commit differs from workflow SHA.')
    acceptance_lock()
    verify_source_identity(args.publish_sha)
    notes = (ROOT / 'docs/releases/0.10.1.md').read_text(encoding='utf-8')
    require(VERSION in notes and len(notes) >= 200, 'Release notes are missing or incomplete.')
    client = GitHub(os.environ.get('GH_TOKEN'))
    require(client.api('/git/ref/tags/' + TAG, absent_ok=True) is None and
            client.api('/releases/tags/' + TAG, absent_ok=True) is None, 'Tag/release already exists; refusing replacement.')
    verify_merged(client, args.publish_sha)
    runs = verify_runs(client)
    download_artifacts(client, args.input_dir)
    prepare(args.input_dir, args.output_dir, args.publish_sha, runs)
    verify_merged(client, args.publish_sha)
    require(client.api('/git/ref/tags/' + TAG, absent_ok=True) is None and
            client.api('/releases/tags/' + TAG, absent_ok=True) is None, 'Release appeared during preparation.')
    # The first mutation occurs only after all exact artifact and native evidence checks.
    client.api('/git/refs', 'POST', {'ref': 'refs/tags/' + TAG, 'sha': args.publish_sha})
    release = client.api('/releases', 'POST', {'tag_name': TAG, 'target_commitish': args.publish_sha,
        'name': 'Native Workbench ' + VERSION, 'body': notes, 'draft': True, 'prerelease': True, 'make_latest': 'false'})
    files = sorted(args.output_dir.iterdir())
    subprocess.run(['gh', 'release', 'upload', TAG, *map(str, files), '--repo', REPOSITORY], check=True)
    uploaded = client.api('/releases/' + str(release['id']))
    require(uploaded['draft'] and uploaded['prerelease'] and uploaded['tag_name'] == TAG, 'Unexpected draft state.')
    by_name = {a['name']: a for a in uploaded['assets']}
    require(len(by_name) == len(uploaded['assets']) == len(files) and set(by_name) == {p.name for p in files},
            'Uploaded asset inventory differs.')
    with tempfile.TemporaryDirectory(prefix='verify-workbench-release-') as temporary:
        for path in files:
            asset = by_name[path.name]
            require(asset['state'] == 'uploaded' and asset['size'] == path.stat().st_size
                    and asset['digest'] == 'sha256:' + sha(path.read_bytes()), 'Asset upload identity differs.')
            client.download(asset['url'], Path(temporary) / path.name, sha(path.read_bytes()), path.stat().st_size, True)
    require(client.api('/git/ref/tags/' + TAG)['object']['sha'] == args.publish_sha,
            'Tag changed before publication; leaving verified assets in draft.')
    published = client.api('/releases/' + str(release['id']), 'PATCH', {'draft': False, 'prerelease': True, 'make_latest': 'false'})
    require(not published['draft'] and published['prerelease'], 'Release was not published as a prerelease.')
    verify_public_downloads(client, release['id'], files, args.publish_sha, args.receipt)
    print(json.dumps({'published': published['html_url'], 'verifiedAssets': len(files)}))


def recover_promotion_assets(raw, output_dir, publish_sha):
    acceptance_lock()
    require(not output_dir.exists() or not any(output_dir.iterdir()), 'Verification output must be empty.')
    with checked_zip(raw) as archive:
        expected = {'promotion-assets/' + name for name in ASSET_NAMES} | {'public-download-verification.json'}
        require(set(archive.namelist()) == expected, 'Retained promotion artifact inventory differs.')
        prior = json.loads(archive.read('public-download-verification.json'))
        require(prior['publicationCommit'] == publish_sha and prior['packagedSourceCommit'] == ACCEPTED['sourceCommit'],
                'Retained publication receipt source differs.')
        contents = {name: archive.read('promotion-assets/' + name) for name in ASSET_NAMES}
    for name, identity in ACCEPTED['archives'].items():
        content = contents[name]
        require(len(content) == identity['bytes'] and sha(content) == identity['sha256'], 'Frozen archive changed: ' + name)
        with checked_zip(content):
            pass
    checksums(contents['SHA256SUMS.txt'], ACCEPTED['archives'], contents.__getitem__)
    checksums(contents['EVIDENCE-SHA256SUMS.txt'], ASSET_NAMES - set(ACCEPTED['archives']) - {'EVIDENCE-SHA256SUMS.txt'}, contents.__getitem__)
    validation = json.loads(contents['RELEASE-VALIDATION.json'])
    require(validation['packagedSourceCommit'] == ACCEPTED['sourceCommit'] and validation['publicationCommit'] == publish_sha
            and validation['acceptedRunId'] == ACCEPTED['runId'] and validation['productionTrustValidated'] is True
            and validation['productionPublisherFingerprint'] == FINGERPRINT
            and validation['acceptedApplicationArchivesRebuilt'] is False, 'Retained release validation differs.')
    require(len(validation['assets']) == len(ASSET_NAMES) - 2 and {a['file'] for a in validation['assets']} ==
            ASSET_NAMES - {'RELEASE-VALIDATION.json', 'EVIDENCE-SHA256SUMS.txt'}, 'Retained validation inventory differs.')
    for item in validation['assets']:
        content = contents[item['file']]
        require(len(content) == item['bytes'] and sha(content) == item['sha256'], 'Retained evidence asset differs.')
    output_dir.mkdir(parents=True, exist_ok=True)
    for name, content in contents.items():
        (output_dir / name).write_bytes(content)
    return sorted(output_dir.iterdir())


def verify_published(args):
    acceptance_lock()
    verify_source_identity(args.publish_sha)
    require(args.retained_artifact > 0 and args.retained_run > 0 and args.retained_bytes > 0
            and exact_hash(args.retained_sha256), 'Retained promotion identity is incomplete.')
    client = ReadOnlyGitHub(os.environ.get('GH_TOKEN'))
    metadata = client.api('/actions/artifacts/' + str(args.retained_artifact))
    require(metadata['workflow_run']['id'] == args.retained_run and metadata['workflow_run']['head_sha'] == args.publish_sha
            and not metadata['expired'] and metadata['size_in_bytes'] == args.retained_bytes
            and metadata['digest'] == 'sha256:' + args.retained_sha256, 'Retained promotion metadata differs or expired.')
    args.input_dir.mkdir(parents=True, exist_ok=True)
    path = args.input_dir / 'retained-promotion.zip'
    client.download(client.base + '/actions/artifacts/' + str(args.retained_artifact) + '/zip', path,
                    args.retained_sha256, args.retained_bytes, True)
    files = recover_promotion_assets(path.read_bytes(), args.output_dir, args.publish_sha)
    release = client.api('/releases/tags/' + TAG)
    receipt = verify_public_downloads(client, release['id'], files, args.publish_sha, args.receipt, True)
    print(json.dumps({'verifiedExistingRelease': receipt['release'], 'verifiedAssets': len(files), 'remoteMutations': False}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input-dir', required=True, type=Path)
    parser.add_argument('--output-dir', required=True, type=Path)
    parser.add_argument('--publish-sha', required=True)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--prepare-only', action='store_true')
    mode.add_argument('--verify-published', action='store_true')
    mode.add_argument('--verify-candidate', action='store_true')
    parser.add_argument('--receipt', type=Path, default=Path('public-download-verification.json'))
    parser.add_argument('--retained-artifact', type=int, default=0)
    parser.add_argument('--retained-run', type=int, default=0)
    parser.add_argument('--retained-bytes', type=int, default=0)
    parser.add_argument('--retained-sha256', default='')
    args = parser.parse_args()
    try:
        if args.prepare_only:
            prepare(args.input_dir, args.output_dir, args.publish_sha)
            print(json.dumps({'prepared': str(args.output_dir), 'assets': len(list(args.output_dir.iterdir())), 'networkWrites': False}))
        elif args.verify_candidate:
            verify_candidate_online(args)
        else:
            (verify_published if args.verify_published else publish)(args)
    except Exception as error:
        receipt = json.loads(args.receipt.read_bytes()) if args.receipt.is_file() else {
            'phase': 'promotion', 'publicationCommit': args.publish_sha,
            'packagedSourceCommit': ACCEPTED.get('sourceCommit'), 'publicDownloads': []}
        receipt.update(success=False, failureType=type(error).__name__,
                       error=str(error) if isinstance(error, (ValueError, RuntimeError)) else 'See workflow log.',
                       recordedUtc=datetime.now(timezone.utc).isoformat())
        args.receipt.parent.mkdir(parents=True, exist_ok=True)
        args.receipt.write_bytes(json_bytes(receipt))
        raise


if __name__ == '__main__':
    main()
