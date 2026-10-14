#!/usr/bin/env python3
"""Promote the exact accepted 0.9.0 application and separately tested 0.8 updater.

Preparation has no network writes. Publication never overwrites a tag/release or
asset: any failure after remote creation leaves evidence and the draft/public
release for inspection. --verify-published performs GET requests only and uses
the immutable retained promotion artifact, not a reconstruction of timestamps.
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
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile

REPOSITORY = 'comparativechrono/workbench'
TAG = 'app-v0.9.0'
SOURCE = 'beea34ab29f3e7cb9a7e79dbcfa11c89f40ee59d'
INITIAL_RUN = 37485987457
FINAL_RUN = 37489208656
FINAL_VALIDATOR = 'bc972125814c1f24dca86391d0c5f240716a52f3'
FINAL_GATE_SHA = 'd543240a8f44ddd587f35854938f0484b6546bc33c77ba233631f3fa7b06afbb'
CANDIDATE_ID = 11424165351
# (local file, bytes, SHA256, workflow run, workflow head)
ARTIFACTS = {
    CANDIDATE_ID: ('candidate.zip', 75880943, '26f1f2070de5ffae4cdb219bd22579f22a3af943eab6e93048fa6e38ad041071', INITIAL_RUN, SOURCE),
    11424060736: ('initial-ordinary.zip', 1543142, '80524be2df80e73f854a2176156e6d9d808b028c2d005ab2d6029411ef1abec8', INITIAL_RUN, SOURCE),
    11424185653: ('initial-spaces.zip', 1542320, '537febe47691043087376810374c965974a8117d52d3e0c09238281aabfe8f02', INITIAL_RUN, SOURCE),
    11422654753: ('long-paths.zip', 74617, 'fa473e5729b322dc6b78e11fd70b4d80bb119a2620b529ef8380cae51388c2aa', INITIAL_RUN, SOURCE),
    11425145308: ('final-ordinary.zip', 395645, '66c2c7bd8446de029007d954d4f510744812390bda7d176eb50007105a831033', FINAL_RUN, FINAL_VALIDATOR),
    11425275080: ('final-spaces.zip', 395894, 'f32a89e1d3aae5a69efe9423702a0ff60e411b7377c414b9dd903f1c27dda80e', FINAL_RUN, FINAL_VALIDATOR),
}
ARCHIVES = {
    'native-workbench-0.9.0-source.zip': (46423298, '7bfc3802cad3b476300ae7075214e2c06ee320d987df66945ff0809cb3218824'),
    'native-workbench-0.9.0-starter-windows.zip': (17002821, 'c2661c144e073c4efdd190ffd186bacd9398b6413b81770d7a057c3947eecf02'),
    'native-workbench-0.9.0-update-from-0.6.0.zip': (12951447, 'eed778882bed560e765c1f2c03d6473b2ea07f2b219e4bd81bff7297e67b177d'),
}
STARTER_SHA = ARCHIVES['native-workbench-0.9.0-starter-windows.zip'][1]
BASELINE_SHA = 'df001a80033ff8e834045ec683c79672e0efdbd4880fb89fca8bf8c36d830fdc'
UPDATE_NAME = 'native-workbench-0.9.0-update-from-0.8.0.zip'
# Frozen after the newly built updater and BOTH native cases passed.
# Identities come from completed workflow/artifact metadata and exact ZIP/reports.
UPDATE = {
    'run': 37527359533, 'commit': '648676c4388f1c4dc9f9af0476bf31f9cfca8c92', 'checks': 13,
    'archive': {'bytes': 12864532, 'sha256': 'caa50ff7807be889fd9f4fbb617a458b1d2b38f397ce365d4fc7fc17a2511d9e'},
    'artifacts': {
        11442014825: ('update-candidate.zip', 12845983, '0edfa07d0287b6712b3391081c8cda8988974435123e64aa9601e973eef8f7af',
                     37527359533, '648676c4388f1c4dc9f9af0476bf31f9cfca8c92'),
        11442039933: ('update-ordinary.zip', 279601, '572f55e5e17118a4fa4e7d907301554bdf4c7d2f68697427ed2086dbbc319744',
                     37527359533, '648676c4388f1c4dc9f9af0476bf31f9cfca8c92'),
        11442179764: ('update-spaces.zip', 279925, '88837d0abbeae9a8518fbfe4238d5c9599a9e2b1995b513bb3c8d12a10f8f85b',
                     37527359533, '648676c4388f1c4dc9f9af0476bf31f9cfca8c92'),
    },
    'candidateId': 11442014825, 'ordinaryId': 11442039933, 'spacesId': 11442179764,
}
ROOT = Path(__file__).resolve().parents[1]
NON_APPLICATION_FILES = {
    'README.md', 'scripts/check_results_windows.py',
    '.github/workflows/native-results-verify.yml',
    'scripts/publish_app_090.py', 'tests/test_publish_app_090.py',
    '.github/workflows/publish-app-0.9.0.yml', '.github/workflows/verify-app-0.9.0.yml',
    'scripts/build_update_090.py', 'scripts/check_update_090_windows.py',
    'tests/test_update_090.py', '.github/workflows/native-update-0.9.0.yml',
}
CANDIDATE_MEMBERS = set(ARCHIVES) | {'BUILD-PROVENANCE.json', 'SHA256SUMS.txt', 'source-metadata.json'}
ASSET_NAMES = CANDIDATE_MEMBERS | {UPDATE_NAME, 'UPDATE-SHA256SUMS.txt', 'BUILD-UPDATE-PROVENANCE.json',
                                  'WINDOWS-EVIDENCE.zip', 'RELEASE-VALIDATION.json', 'EVIDENCE-SHA256SUMS.txt'}


def require(value, message):
    if not value:
        raise ValueError(message)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def json_bytes(value):
    return (json.dumps(value, indent=2, ensure_ascii=False) + '\n').encode()


def checked_zip(raw):
    archive = zipfile.ZipFile(io.BytesIO(raw))
    names = archive.namelist()
    require(len(names) == len(set(names)), 'Duplicate ZIP members.')
    require(all(not PurePosixPath(n).is_absolute() and '..' not in PurePosixPath(n).parts
                and '\\' not in n and ':' not in n for n in names), 'Unsafe ZIP member.')
    require(archive.testzip() is None, 'ZIP CRC validation failed.')
    return archive


def verify_source_identity(publish_sha):
    require(re.fullmatch(r'[0-9a-f]{40}', publish_sha), 'Expected exact publishing commit.')
    subprocess.run(['git', 'merge-base', '--is-ancestor', SOURCE, publish_sha], cwd=ROOT, check=True)
    changed = subprocess.check_output(['git', 'diff', '--name-only', SOURCE, publish_sha], cwd=ROOT, text=True).splitlines()
    require(all(p.startswith(('knowledge/', 'docs/')) or p in NON_APPLICATION_FILES for p in changed),
            'Application, build or pack code changed after accepted candidate: ' + repr(changed))


def update_lock():
    require(isinstance(UPDATE['run'], int) and UPDATE['run'] > 0 and re.fullmatch(r'[0-9a-f]{40}', UPDATE['commit'])
            and UPDATE['checks'] > 0 and UPDATE['archive']['bytes'] > 0
            and re.fullmatch(r'[0-9a-f]{64}', UPDATE['archive']['sha256']),
            '0.8.0 updater has no completed, pinned native validation; refusing promotion.')
    ids = [UPDATE[k] for k in ('candidateId', 'ordinaryId', 'spacesId')]
    require(len(set(ids)) == 3 and all(isinstance(i, int) and i > 0 for i in ids)
            and set(ids) == set(UPDATE['artifacts']), 'Updater artifact inventory is incomplete.')
    for name, size, digest, run, commit in UPDATE['artifacts'].values():
        require(name.endswith('.zip') and '/' not in name and size > 0 and re.fullmatch(r'[0-9a-f]{64}', digest)
                and run == UPDATE['run'] and commit == UPDATE['commit'], 'Updater artifact identity is incomplete.')
    return UPDATE


def all_artifacts():
    update_lock()
    require(not (set(ARTIFACTS) & set(UPDATE['artifacts'])), 'Duplicate artifact identity.')
    result = {**ARTIFACTS, **UPDATE['artifacts']}
    require(len({v[0] for v in result.values()}) == len(result), 'Duplicate artifact filename.')
    return result


def check_report(report, count, native_gui=False):
    require(report.get('success') is True and report.get('nativeWindowsExecuted') is True
            and report.get('passed') == count and report.get('skips') == []
            and report.get('failed', 0) == 0 and not report.get('failures'), 'Native gate did not pass completely.')
    require(report.get('sourceCommit') == SOURCE and report.get('assetSha256') == STARTER_SHA,
            'Native gate identifies different application bytes.')
    require(not native_gui or (report.get('nativeGUIValidated') is True and report.get('gateSha256') == FINAL_GATE_SHA),
            'Final native GUI gate identity or result differs.')


def checked_report(archive, path, count, core_files, gui=False):
    raw = archive.read(path)
    report = json.loads(raw)
    check_report(report, count, gui)
    for name, digest in report.get('appFiles', {}).items():
        require(core_files.get(name.replace('\\', '/')) == digest, 'Tested application file differs: ' + name)
    require(bool(report.get('appFiles')), 'Report has no tested application file identities.')
    prefix = path.rsplit('/', 1)[0] + '/' if '/' in path else ''
    for item in report.get('evidenceFiles', []):
        content = archive.read(prefix + item['file'].replace('\\', '/'))
        require(len(content) == item['bytes'] and sha(content) == item['sha256'], 'Retained native evidence differs.')
    return report, {'passed': count, 'failed': 0, 'skips': [], 'sha256': sha(raw), 'path': path}


def checksums(raw, expected, read):
    rows = [line.split('  ', 1) for line in raw.decode().splitlines()]
    require(all(len(row) == 2 for row in rows) and len(rows) == len(expected)
            and {row[1] for row in rows} == set(expected), 'Checksum inventory differs.')
    require(all(re.fullmatch(r'[0-9a-f]{64}', digest) and sha(read(name)) == digest for digest, name in rows),
            'Checksum verification failed.')


def verify_runs(client):
    update_lock()
    results = []
    for identity, source, conclusion, names in [
            (INITIAL_RUN, SOURCE, 'failure', {'build', 'native-long-paths', 'native (ordinary)', 'native (path with spaces)'}),
            (FINAL_RUN, FINAL_VALIDATOR, 'success', {'native (ordinary)', 'native (path with spaces)'}),
            (UPDATE['run'], UPDATE['commit'], 'success', {'build', 'native (ordinary)', 'native (path with spaces)'})]:
        run = client.api(f'/actions/runs/{identity}')
        require(run['head_sha'] == source and run['status'] == 'completed' and run['conclusion'] == conclusion,
                'Recorded workflow identity or conclusion differs.')
        data = client.api(f'/actions/runs/{identity}/jobs?filter=latest&per_page=100')
        jobs = data['jobs']
        require(data['total_count'] == len(jobs) == len(names) and {j['name'] for j in jobs} == names,
                'Unexpected validation job inventory.')
        for job in jobs:
            initial_fixture = identity == INITIAL_RUN and job['name'].startswith('native (')
            expected = 'failure' if initial_fixture else 'success'
            require(job['conclusion'] == expected and job.get('steps'), 'Validation job conclusion differs.')
            for step in job['steps']:
                expected = 'failure' if initial_fixture and step['name'] == 'Verify CWL results, routed DAGs and native application icons' else 'success'
                require(step['conclusion'] == expected, 'Validation contains an unexpected failed or skipped step.')
            if initial_fixture:
                require(sum(s['conclusion'] == 'failure' for s in job['steps']) == 1, 'Recorded initial fixture failure disappeared.')
        results.append({'runId': identity, 'sourceCommit': source, 'conclusion': conclusion,
                        'jobs': [{'id': j['id'], 'name': j['name'], 'conclusion': j['conclusion']} for j in jobs]})
    return results


def verify_merged(client, publish_sha):
    main = client.api('/git/ref/heads/main')['object']['sha']
    require(main == publish_sha, 'Publication must promote the exact merged main commit.')
    pr = client.api('/pulls/2')
    require(pr.get('merged') is True and pr.get('merge_commit_sha') == publish_sha
            and pr.get('base', {}).get('ref') == 'main' and pr.get('head', {}).get('ref') == 'feature/cwl-dag-icon',
            'Accepted feature PR is not merged at the publication commit.')


def check_update_report(report):
    require(report.get('success') is True and report.get('nativeWindowsExecuted') is True
            and report.get('nativeWindowsHost') is True and report.get('passed') == UPDATE['checks']
            and report.get('skips') == [] and report.get('failures') == [],
            '0.8 updater native gate did not pass completely.')
    require(report['sourceCommit'] == SOURCE and report['validationCommit'] == UPDATE['commit']
            and report['starterSha256'] == STARTER_SHA and report['baselineSha256'] == BASELINE_SHA
            and report['updateSha256'] == UPDATE['archive']['sha256'], '0.8 updater native gate identity differs.')
    require(report['appVersion'] == '0.9.0' and report['coreFilesVerified'] == 70
            and report['updateAttempts']['install']['status'] == 'installed'
            and report['updateAttempts']['repeat']['status'] == 'already-installed', 'Updater transaction or target differs.')
    preserved = report['preservation']
    require(preserved['files'] > 0 and not preserved['changes'] and all(
        name == 'user-data/session.lock' and digest == sha(b'\0') for name, digest in preserved['additions'].items()),
        'Updater did not preserve existing user files.')
    before, after = report['baselineReferenceRun'], report['updatedReferenceRun']
    require(before['nativeWindowsExecuted'] is True and after['nativeWindowsExecuted'] is True
            and before['referenceSha256'] == after['referenceSha256'] and before['contigs'] == after['contigs'] > 0
            and before['cwlChecked'] is False and after['cwlChecked'] is True, 'Updated reference provenance evidence differs.')
    science = report['science']
    require(science['networkSocketOperationsDeniedForHost'] is True and science['nativeWindowsExecuted'] is True
            and science['outputsIndependentlyHashed'] == 20 and science['nativeCommandsCompared'] == 18
            and len(science['cwlRunnerReplays']) == 5, 'Updated offline scientific/CWL evidence incomplete.')


def prepare(input_dir, output_dir, publish_sha, online_evidence=None):
    artifacts = all_artifacts()
    verify_source_identity(publish_sha)
    require(not output_dir.exists() or not any(output_dir.iterdir()), 'Promotion output must be empty.')
    output_dir.mkdir(parents=True, exist_ok=True)
    blobs = {}
    for identity, (name, size, digest, _, _) in artifacts.items():
        raw = (input_dir / name).read_bytes()
        require(len(raw) == size and sha(raw) == digest, 'Artifact identity mismatch: ' + name)
        with checked_zip(raw):
            pass
        blobs[identity] = raw
    with checked_zip(blobs[CANDIDATE_ID]) as candidate:
        require(set(candidate.namelist()) == CANDIDATE_MEMBERS, 'Candidate member inventory changed.')
        require(json.loads(candidate.read('BUILD-PROVENANCE.json'))['sourceCommit'] == SOURCE, 'Packaged source differs.')
        checksums(candidate.read('SHA256SUMS.txt'), ARCHIVES, candidate.read)
        core_files = {}
        for name, (size, digest) in ARCHIVES.items():
            raw = candidate.read(name)
            require(len(raw) == size and sha(raw) == digest, 'Accepted archive identity differs: ' + name)
            with checked_zip(raw) as archive:
                if name.endswith('starter-windows.zip'):
                    manifest = json.loads(archive.read('native-workbench/manifest.json'))
                    require(manifest['version'] == '0.9.0' and len(manifest['files']) == 70, 'Unexpected accepted core inventory.')
                    for item in manifest['files']:
                        content = archive.read('native-workbench/' + item['path'])
                        require(len(content) == item['bytes'] and sha(content) == item['sha256'], 'Core inventory identity differs.')
                    core_files = {n.removeprefix('native-workbench/'): sha(archive.read(n)) for n in archive.namelist() if not n.endswith('/')}
        for name in candidate.namelist():
            (output_dir / name).write_bytes(candidate.read(name))
    reports = {}
    for identity, label in [(11424060736, 'ordinary'), (11424185653, 'spaces')]:
        with checked_zip(blobs[identity]) as archive:
            for kind, path, count in [('workspace', 'workspace-ui-evidence/native-ui.json', 32),
                                      ('references', 'workspace-reference-evidence/native-references.json', 9)]:
                _, reports[label + '-' + kind] = checked_report(archive, path, count, core_files)
            failure = json.loads(archive.read('results-feature-evidence/native-results.json'))
            require(failure['success'] is False and failure['passed'] == 7 and failure['failed'] == 1
                    and failure['sourceCommit'] == SOURCE and failure['assetSha256'] == STARTER_SHA,
                    'Original failed fixture record differs; cannot relabel it a pass.')
    for identity, label in [(11425145308, 'ordinary'), (11425275080, 'spaces')]:
        with checked_zip(blobs[identity]) as archive:
            report, reports[label + '-results'] = checked_report(archive, 'native-results.json', 9, core_files, True)
            require(len(report['evidenceFiles']) == 22 and report['science']['outputsIndependentlyHashed'] == 20
                    and report['science']['nativeCommandsCompared'] == 18 and len(report['science']['cwlRunnerReplays']) == 5,
                    'Final science/export evidence incomplete.')
    with checked_zip(blobs[11422654753]) as archive:
        report, reports['longPaths'] = checked_report(archive, 'native-long-paths.json', 3, core_files)
        require(len(report['outputFiles']) == 20 and report['longPathsEnabled'] == 0
                and report['applicationCheck']['corePassed'] == 7 and report['applicationCheck']['starterFailed'] == 0
                and report['applicationCheck']['starterSkipped'] == 0, 'Long-path scientific gate incomplete.')
        for item in report['outputFiles']:
            require(sha(archive.read(item['evidenceFile'].replace('\\', '/'))) == item['sha256'], 'Scientific output differs.')
    with checked_zip(blobs[UPDATE['candidateId']]) as archive:
        require(set(archive.namelist()) == {UPDATE_NAME, 'BUILD-UPDATE-PROVENANCE.json', 'SHA256SUMS.txt'}, 'Updater candidate members differ.')
        checksums(archive.read('SHA256SUMS.txt'), {UPDATE_NAME}, archive.read)
        raw = archive.read(UPDATE_NAME)
        require(len(raw) == UPDATE['archive']['bytes'] and sha(raw) == UPDATE['archive']['sha256'], 'Updater archive differs.')
        provenance = json.loads(archive.read('BUILD-UPDATE-PROVENANCE.json'))
        require(provenance['sourceCommit'] == SOURCE and provenance['packagingCommit'] == UPDATE['commit']
                and provenance['applicationRebuilt'] is False and provenance['baseVersion'] == '0.8.0'
                and provenance['targetVersion'] == '0.9.0' and provenance['baselineSha256'] == BASELINE_SHA
                and provenance['starterSha256'] == STARTER_SHA and provenance['updateSha256'] == UPDATE['archive']['sha256']
                and provenance['archive'] == {'file': UPDATE_NAME, **UPDATE['archive']}
                and provenance['coreFilesVerified'] == 70 and provenance['unchangedPackFiles'] == 143,
                'Updater build provenance contradicts frozen identities.')
        with checked_zip(raw) as update_zip:
            recipe = json.loads(update_zip.read('update/update-manifest.json'))
            require(recipe['kind'] == 'native-core-update' and recipe['base_version'] == '0.8.0'
                    and recipe['target_version'] == '0.9.0'
                    and recipe['base_manifest_sha256'] == '2624183924564bc92f9146448c3a2a8d336a379034e168a25cd0c8c43c5ae573'
                    and recipe['target_manifest_sha256'] == core_files['manifest.json']
                    and len(recipe['operations']) == 7 and recipe['obsolete'] == [], 'Updater manifest differs.')
            for item in json.loads(update_zip.read('update-inventory.json'))['files']:
                content = update_zip.read(item['path'])
                require(len(content) == item['bytes'] and sha(content) == item['sha256'], 'Updater inventory differs.')
            for operation in recipe['operations']:
                content = update_zip.read('update/blobs/' + operation['blob'])
                require(len(content) == operation['bytes'] and sha(content) == operation['sha256']
                        and operation['sha256'] == core_files[operation['path']], 'Updater payload differs from accepted starter.')
            require(sha(update_zip.read('update/blobs/' + recipe['target_manifest_blob'])) == core_files['manifest.json'],
                    'Updater target manifest blob differs.')
        (output_dir / UPDATE_NAME).write_bytes(raw)
        (output_dir / 'BUILD-UPDATE-PROVENANCE.json').write_bytes(archive.read('BUILD-UPDATE-PROVENANCE.json'))
        (output_dir / 'UPDATE-SHA256SUMS.txt').write_bytes(archive.read('SHA256SUMS.txt'))
    for label in ('ordinary', 'spaces'):
        with checked_zip(blobs[UPDATE[label + 'Id']]) as archive:
            raw = archive.read('update-native.json')
            report = json.loads(raw)
            check_update_report(report)
            reports[label + '-update-from-0.8.0'] = {'passed': report['passed'], 'sha256': sha(raw), 'skips': []}
    with zipfile.ZipFile(output_dir / 'WINDOWS-EVIDENCE.zip', 'w', zipfile.ZIP_DEFLATED) as evidence:
        for identity, (name, _, _, _, _) in artifacts.items():
            if identity != CANDIDATE_ID:
                evidence.writestr('original-ci-artifacts/' + name, blobs[identity])
        # The dated ledger retains all three failed attempts and their scope.
        for path in sorted((ROOT / 'knowledge/evidence').glob('cwl-dag-icon-0.9.0-*.json')):
            evidence.write(path, 'repository-evidence/' + path.name)
        for name in sorted(NON_APPLICATION_FILES):
            path = ROOT / name
            if path.is_file():
                evidence.write(path, 'validation-sources/' + name)
        if online_evidence:
            evidence.writestr('promotion-run-verification.json', json_bytes(online_evidence))
    validation = {
        'schema': 1, 'version': '0.9.0', 'releaseTag': TAG, 'packagedSourceCommit': SOURCE,
        'publicationCommit': publish_sha, 'recordedUtc': datetime.now(timezone.utc).isoformat(),
        'acceptedApplicationArchivesRebuilt': False, 'newUpdaterFrom': '0.8.0',
        'initialRunId': INITIAL_RUN, 'initialRunConclusion': 'failure', 'finalFeatureRunId': FINAL_RUN,
        'updateRunId': UPDATE['run'], 'updateValidationCommit': UPDATE['commit'],
        'candidateArtifacts': [{'id': i, 'file': v[0], 'bytes': v[1], 'sha256': v[2], 'runId': v[3], 'headSha': v[4]} for i, v in artifacts.items()],
        'sourceChecks': {'passed': 125, 'failures': 0, 'skips': 0, 'platform': 'Linux CI',
                         'stockCwltoolValidationAndExecution': '3.3.20260925135507'},
        'nativeReports': reports,
        'retainedFailedUpdaterReports': [{'file': p.name, 'sha256': sha(p.read_bytes())}
            for p in sorted((ROOT / 'knowledge/evidence').glob('cwl-dag-icon-0.9.0-updater-attempt-*.json'))],
        'testerAcceptance': {'reportedBy': 'Project owner', 'date': '2026-10-06',
                             'statement': 'Go ahead accept and release, the testers are happy with it'},
        'scope': 'Reuses exact accepted application evidence; newly builds and validates only the 0.8-to-0.9 updater. Promotion verifies immutable artifacts and downloads.',
        'limits': [
            'The initial feature workflow and two intermediate GUI validator workflows failed. Their reports are retained; final corrected fixture passes on unchanged application bytes.',
            'Earlier updater fixture failures remain failed historical reports; only the pinned successful final updater workflow supplies migration evidence.',
            'Final zoom screenshot uses native BM_CLICK because the hosted desktop taskbar occluded the physical button. Physical zoom interactions passed the separate workspace gate.',
            'External CWL execution requires a compatible engine, Python 3.10+, matching packs/runtime and input data. Windows native helper replay is separate from the Linux stock CWL-engine fixture.',
            'No execution of all optional packs or broad physical-trackpad/high-DPI/multi-monitor survey is claimed. Tester acceptance is user-reported.',
            'Updater migration is provided from 0.6.0 and 0.8.0 only; no 0.7.0-to-0.9.0 updater is included.'
        ],
        'originalCompanions': 'All six original candidate members, including source/build provenance and SHA256SUMS, retain unchanged creation-time statements. This later validation record supersedes pending acceptance/release status.',
        'assets': [{'file': p.name, 'bytes': p.stat().st_size, 'sha256': sha(p.read_bytes())} for p in sorted(output_dir.iterdir())],
    }
    (output_dir / 'RELEASE-VALIDATION.json').write_bytes(json_bytes(validation))
    (output_dir / 'EVIDENCE-SHA256SUMS.txt').write_text(''.join(
        sha(p.read_bytes()) + '  ' + p.name + '\n' for p in sorted(output_dir.iterdir()) if p.name not in ARCHIVES), encoding='utf-8')
    require({p.name for p in output_dir.iterdir()} == ASSET_NAMES, 'Prepared release member inventory differs.')
    return validation
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
               "packagedSourceCommit": SOURCE, "publicDownloads": []}
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



def download_artifacts(client, input_dir):
    input_dir.mkdir(parents=True, exist_ok=True)
    for identity, (name, size, digest, run, commit) in all_artifacts().items():
        metadata = client.api(f'/actions/artifacts/{identity}')
        require(metadata['workflow_run']['id'] == run and metadata['workflow_run']['head_sha'] == commit
                and not metadata['expired'] and metadata['size_in_bytes'] == size
                and metadata['digest'] == 'sha256:' + digest, 'Artifact metadata changed or expired.')
        client.download(client.base + f'/actions/artifacts/{identity}/zip', input_dir / name, digest, size, True)


def publish(args):
    require(os.environ.get('GITHUB_REPOSITORY') == REPOSITORY and
            os.environ.get('GITHUB_REF') == 'refs/heads/release/app-0.9.0', 'Wrong publication repository or branch.')
    require(os.environ.get('GITHUB_SHA') == args.publish_sha, 'Publishing commit differs from workflow SHA.')
    update_lock()
    verify_source_identity(args.publish_sha)
    notes = (ROOT / 'docs/releases/0.9.0.md').read_text(encoding='utf-8')
    require('0.9.0' in notes and len(notes) >= 200, 'Release notes are missing or incomplete.')
    client = GitHub(os.environ.get('GH_TOKEN'))
    require(client.api('/git/ref/tags/' + TAG, absent_ok=True) is None and
            client.api('/releases/tags/' + TAG, absent_ok=True) is None, 'Tag/release already exists; refusing replacement.')
    verify_merged(client, args.publish_sha)
    runs = verify_runs(client)
    download_artifacts(client, args.input_dir)
    prepare(args.input_dir, args.output_dir, args.publish_sha, runs)
    # Repeat branch and absence guards immediately before the first mutation.
    verify_merged(client, args.publish_sha)
    require(client.api('/git/ref/tags/' + TAG, absent_ok=True) is None and
            client.api('/releases/tags/' + TAG, absent_ok=True) is None, 'Release appeared during preparation.')
    client.api('/git/refs', 'POST', {'ref': 'refs/tags/' + TAG, 'sha': args.publish_sha})
    release = client.api('/releases', 'POST', {'tag_name': TAG, 'target_commitish': args.publish_sha,
        'name': 'Native Workbench 0.9.0', 'body': notes, 'draft': True, 'prerelease': True, 'make_latest': 'false'})
    files = sorted(args.output_dir.iterdir())
    subprocess.run(['gh', 'release', 'upload', TAG, *map(str, files), '--repo', REPOSITORY], check=True)
    uploaded = client.api(f"/releases/{release['id']}")
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
    published = client.api(f"/releases/{release['id']}", 'PATCH', {'draft': False, 'prerelease': True, 'make_latest': 'false'})
    require(not published['draft'] and published['prerelease'], 'Release was not published as a prerelease.')
    verify_public_downloads(client, release['id'], files, args.publish_sha, args.receipt)
    print(json.dumps({'published': published['html_url'], 'verifiedAssets': len(files)}))


def recover_promotion_assets(raw, output_dir, publish_sha):
    require(not output_dir.exists() or not any(output_dir.iterdir()), 'Verification output must be empty.')
    output_dir.mkdir(parents=True, exist_ok=True)
    with checked_zip(raw) as archive:
        expected = {'promotion-assets/' + name for name in ASSET_NAMES} | {'public-download-verification.json'}
        require(set(archive.namelist()) == expected, 'Retained promotion artifact inventory differs.')
        for name in ASSET_NAMES:
            (output_dir / name).write_bytes(archive.read('promotion-assets/' + name))
        prior = json.loads(archive.read('public-download-verification.json'))
        require(prior['publicationCommit'] == publish_sha and prior['packagedSourceCommit'] == SOURCE,
                'Retained publication receipt source differs.')
    read = lambda name: (output_dir / name).read_bytes()
    for name, (size, digest) in {**ARCHIVES, UPDATE_NAME: (UPDATE['archive']['bytes'], UPDATE['archive']['sha256'])}.items():
        content = read(name)
        require(len(content) == size and sha(content) == digest, 'Frozen archive changed: ' + name)
        with checked_zip(content):
            pass
    checksums(read('SHA256SUMS.txt'), ARCHIVES, read)
    checksums(read('UPDATE-SHA256SUMS.txt'), {UPDATE_NAME}, read)
    checksums(read('EVIDENCE-SHA256SUMS.txt'), ASSET_NAMES - set(ARCHIVES) - {'EVIDENCE-SHA256SUMS.txt'}, read)
    validation = json.loads(read('RELEASE-VALIDATION.json'))
    require(validation['packagedSourceCommit'] == SOURCE and validation['publicationCommit'] == publish_sha
            and validation['finalFeatureRunId'] == FINAL_RUN and validation['updateRunId'] == UPDATE['run']
            and validation['acceptedApplicationArchivesRebuilt'] is False, 'Retained release validation differs.')
    require(len(validation['assets']) == len(ASSET_NAMES) - 2 and {a['file'] for a in validation['assets']} ==
            ASSET_NAMES - {'RELEASE-VALIDATION.json', 'EVIDENCE-SHA256SUMS.txt'}, 'Retained validation inventory differs.')
    for item in validation['assets']:
        content = read(item['file'])
        require(len(content) == item['bytes'] and sha(content) == item['sha256'], 'Retained evidence asset differs.')
    return sorted(output_dir.iterdir())


def verify_published(args):
    require(os.environ.get('GITHUB_REPOSITORY') == REPOSITORY and
            os.environ.get('GITHUB_REF') == 'refs/heads/release/verify-app-0.9.0', 'Wrong verification repository or branch.')
    update_lock()
    verify_source_identity(args.publish_sha)
    require(args.retained_artifact > 0 and args.retained_run > 0 and args.retained_bytes > 0
            and re.fullmatch(r'[0-9a-f]{64}', args.retained_sha256), 'Retained promotion identity is incomplete.')
    client = ReadOnlyGitHub(os.environ.get('GH_TOKEN'))
    metadata = client.api(f'/actions/artifacts/{args.retained_artifact}')
    require(metadata['workflow_run']['id'] == args.retained_run and metadata['workflow_run']['head_sha'] == args.publish_sha
            and not metadata['expired'] and metadata['size_in_bytes'] == args.retained_bytes
            and metadata['digest'] == 'sha256:' + args.retained_sha256, 'Retained promotion metadata differs or expired.')
    args.input_dir.mkdir(parents=True, exist_ok=True)
    path = args.input_dir / 'retained-promotion.zip'
    client.download(client.base + f'/actions/artifacts/{args.retained_artifact}/zip', path, args.retained_sha256, args.retained_bytes, True)
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
        else:
            (verify_published if args.verify_published else publish)(args)
    except Exception as error:
        # Preserve partial public verification if publishing already happened.
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
