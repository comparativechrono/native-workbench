#!/usr/bin/env python3
"""Validate an exact installed 0.15 reference-management candidate on Windows.

Live provider/analysis checks, deterministic hostile-transfer fixtures, private
host operations and observed native controls have separately labelled evidence.
Fixtures substitute only the provider response boundary in the gate process;
installed production files are never changed. This is not a release/update gate.
"""
from __future__ import annotations

import argparse
import copy
import ctypes
from datetime import datetime, timezone
import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import platform
import random
import shutil
import sys
import threading
import time
import traceback

sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_references_windows import (EXPECTED, PrivateHost, fasta_dictionary, require,
    run_reference_checks, sha256, wait_reference, write_json)
from check_batch_windows import NativeList, add_job, check, frozen_hashes, read_json, until, wait_jobs
from check_workspace_ui_windows import NativeUI
from native_tree import NativeTree
from ctypes import wintypes

# Independently retrieved on 2026-10-08 by the upstream/provider research gate.
# RefSeq annotation objects may change under the same assembly accession. A
# changed pin fails this gate; it is not automatically replaced by a new value.
NCBI_EXPECTED = {
    'genome': {'compressed_bytes': 3843460, 'compressed_sha256': '1ec41f951b35f2752d5065edeafe6972455609d4383fb36dae12519a60b27a73',
               'bytes': 12310392, 'sha256': 'fe42735d3e6242f8c40b457a232940e34ef15eb4502717e54a34ed118face4c1'},
    'annotation': {'compressed_bytes': 2293663, 'compressed_sha256': 'b43af4bd39ae4d53afe6addb957b448ebdcfba48dd7c18066259b3322fbc8b8c',
                   'bytes': 27121814, 'sha256': '16da5a5d60a6bd3fdd00eda8dbab64bbbe92294d88ee0a9ac7c3415cd6da1546'},
    'protein': {'compressed_bytes': 1848181, 'compressed_sha256': '43b97707ae1a08a4b30c200aba6e5c39be47c674321b096478065a2400b1494e',
                'bytes': 3400039, 'sha256': 'a376bcbd87c6caa8c0d81c2b1feb2d04246b438023bab3ced3821a61db718aac'},
}


def rejected(callback, message):
    try:
        callback()
    except (ValueError, OSError) as error:
        return str(error)
    raise AssertionError(message)


def operation(host, action, params=None, expected='completed'):
    host.call('references/' + action, params)
    return wait_reference(host, expected=expected)


def import_preview(host, files, metadata, destination):
    state = operation(host, 'import-preview', {'files': files, 'metadata': metadata, 'destination': str(destination)})
    review = state['review']
    require(review['kind'] == 'import' and review['token'] and review['files'], 'Explicit local import did not return a private reviewed selection.')
    return review


def fixture_transfer_checks(root, evidence, report):
    from reference_manager import ReferenceManager, ReferencePaused
    raw = b'>deterministic_transfer_fixture\n' + bytes(b'ACGT'[value % 4] for value in random.Random(192).randbytes(5 * 1024 * 1024)) + b'\n'
    compressed = gzip.compress(raw, mtime=0)
    require(len(compressed) > 1024 * 1024, 'Transfer fixture must span at least two production chunks.')
    logs = []

    class Response(io.BytesIO):
        def __init__(self, body, code, headers):
            super().__init__(body)
            self.code, self.headers = code, headers
        def getcode(self): return self.code
        def geturl(self): return 'https://fixture.invalid/reference.fa.gz'

    class Provider:
        def __init__(self, mode='normal'):
            self.mode, self.requests = mode, []
        def descriptor(self): return {'id': 'ensembl-archive', 'name': 'Gate-only deterministic transfer fixture'}
        def discover(self, release, species_id, **_):
            return {'provider': 'ensembl-archive', 'provider_name': 'Gate-only deterministic transfer fixture',
                    'release': 116, 'species': {'id': 'synthetic', 'name': 'Synthetic transfer fixture'}, 'assembly': 'fixture-v1',
                    'files': [{'id': 'genome', 'kind': 'genome', 'filename': 'fixture.fa.gz',
                               'label': 'Genome FASTA', 'url': 'https://fixture.invalid/reference.fa.gz',
                               'bytes': len(compressed), 'checksum': {'algorithm': 'md5', 'value': hashlib.md5(compressed).hexdigest()}}]}
        def open_url(self, url, cancel=None, headers=None):
            self.requests.append(copy.deepcopy(headers))
            start = int(headers['Range'][6:-1]) if headers else 0
            response_headers = {'ETag': '"fixture-v1"', 'Content-Length': str(len(compressed) - start)}
            if headers:
                response_headers['Content-Range'] = 'bytes %d-%d/%d' % (start, len(compressed) - 1, len(compressed))
                if self.mode == 'malformed-range': response_headers['Content-Range'] = 'bytes 0-1/2'
                if self.mode == 'changed-validator': response_headers['ETag'] = '"changed-version"'
            return Response(compressed[start:], 206 if headers else 200, response_headers)

    fixture_root = evidence / 'transport-fixture-app'
    destination = evidence / 'transport-fixture-destination'
    destination.mkdir()
    (destination / 'existing-user-file.txt').write_text('Preserved user file.\n')
    fixture_root.mkdir()

    def paused(provider):
        manager = ReferenceManager(fixture_root, provider=provider)
        selection = manager.discover(116, 'synthetic')['discovery']['selection_id']
        def pause_after_first_chunk(event):
            if event.get('phase') == 'downloading' and event.get('bytes', 0) > 0:
                manager.pause()
        try:
            manager.download(selection, ['genome'], str(destination), event=pause_after_first_chunk)
        except ReferencePaused:
            pass
        else:
            raise AssertionError('Pause did not retain a transfer before completion.')
        pending = manager.snapshot()['pending']
        require(len(pending) == 1 and pending[0]['status'] == 'paused' and 0 < pending[0]['bytes'] < len(compressed),
                'Pause did not retain an incomplete compressed checkpoint.')
        return manager, pending[0]

    provider = Provider()
    manager, pending = paused(provider)
    require(not manager.snapshot()['local'], 'An incomplete transfer entered the ready library.')
    job = pending['id']
    prefix = fixture_root / 'user-data/references/pending' / job / 'genome.gz'
    checkpoint = read_json(prefix.with_name('job.json'))
    require(sha256(prefix) == checkpoint['states']['genome']['sha256'], 'Persisted compressed prefix is not hash-bound.')
    with prefix.open('ab') as stream: stream.write(b'uncheckpointed crash suffix')
    fresh = ReferenceManager(fixture_root, provider=provider)
    state = fresh.resume(job)
    record = state['local'][0]
    require(not state['pending'] and sha256(record['files'][0]['path']) == hashlib.sha256(raw).hexdigest(),
            'Fresh-manager resumed bytes differ from the independent complete fixture.')
    require(provider.requests[-1] == {'Range': 'bytes=%d-' % pending['bytes'], 'If-Range': '"fixture-v1"'},
            'Resume did not bind its rehashed compressed offset and strong validator.')
    logs.append({'case': 'resume-after-reopen-and-uncheckpointed-suffix', 'requests': provider.requests, 'checkpoint': checkpoint,
                 'expandedSha256': sha256(record['files'][0]['path'])})
    check(report, 'Exact packaged transfer code pauses after a production chunk, publishes no incomplete record, reopens and rehashes its checkpoint, truncates an uncheckpointed crash suffix and resumes with exact Range/If-Range into independently verified complete bytes; deterministic provider fixture only.')

    for mode in ('malformed-range', 'changed-validator'):
        provider = Provider(mode)
        manager, pending = paused(provider)
        before = len(manager.snapshot()['local'])
        state = ReferenceManager(fixture_root, provider=provider).resume(pending['id'])
        require(provider.requests[-2] is not None and provider.requests[-1] is None and len(state['local']) == before + 1,
                'Invalid partial response was not rejected in favour of a verified full transfer.')
        require(sha256(state['local'][-1]['files'][0]['path']) == hashlib.sha256(raw).hexdigest(), 'Full retry accepted different bytes.')
        logs.append({'case': mode, 'requests': provider.requests})
    check(report, 'Malformed Content-Range and changed entity validators are never appended; deterministic responses force a fresh full request whose final bytes still match the independently pinned fixture.')

    provider = Provider()
    manager, pending = paused(provider)
    before = len(manager.snapshot()['local'])
    prefix = fixture_root / 'user-data/references/pending' / pending['id'] / 'genome.gz'
    with prefix.open('r+b') as stream: stream.write(b'changed-prefix')
    error = rejected(lambda: manager.resume(pending['id']), 'Changed compressed prefix was accepted.')
    require(len(manager.snapshot()['local']) == before, 'Changed prefix published a reference.')
    logs.append({'case': 'changed-prefix', 'error': error})
    if manager.snapshot()['pending']: manager.discard(pending['id'])
    manager, pending = paused(Provider())
    job_path = fixture_root / 'user-data/references/pending' / pending['id'] / 'job.json'
    job_path.write_text('{"schema":1,"schema":1}', encoding='utf-8')
    require(manager.snapshot()['pending'][0]['status'] == 'damaged', 'Malformed checkpoint was not identified as damaged.')
    error = rejected(lambda: manager.resume(pending['id']), 'Malformed checkpoint was resumed.')
    manager.discard(pending['id'])
    require(not manager.snapshot()['pending'] and len(manager.snapshot()['local']) == before,
            'Discard changed completed references or retained damaged state.')
    require((destination / 'existing-user-file.txt').read_text() == 'Preserved user file.\n', 'Discard changed unrelated user content.')
    logs.append({'case': 'malformed-checkpoint-discard', 'error': error})
    write_json(evidence / 'deterministic-transfer-observations.json', logs)
    check(report, 'Changed checkpointed compressed bytes and malformed checkpoint JSON fail closed; explicit discard removes only pending state and preserves ready bundles and unrelated user content.')


def host_library_checks(root, evidence, report):
    data = evidence / 'local-reference-inputs'
    data.mkdir()
    genome = data / 'local-reference.fa'
    shutil.copyfile(root / 'examples/starter/reference.fa', genome)
    annotation = data / 'local-annotation.gtf.gz'
    annotation.write_bytes(gzip.compress(b'fixture\tlocal\tgene\t1\t10\t.\t+\t.\tgene_id "fixture-gene";\n', mtime=0))
    original_hashes = {str(path): sha256(path) for path in (genome, annotation)}
    destination = evidence / 'local-library'
    destination.mkdir()
    sentinel = destination / 'existing-user-content.txt'
    sentinel.write_text('Preserve during import and relocation.\n')
    metadata = {'label': 'Synthetic local import', 'species': 'Synthetic scientific fixture', 'assembly': 'fixture-v1',
                'assembly_accession': 'LOCAL-FIXTURE', 'source': 'Local laboratory fixture; user supplied', 'release': '2026-test'}
    files = [{'kind': 'genome', 'path': str(genome)}, {'kind': 'annotation', 'path': str(annotation)}]
    host = PrivateHost(root, evidence, 'reference-management-offline-host', offline=True)
    host.gate_queue_state_path = root / 'user-data/run-queue.json'
    try:
        require(host.call('init')['app_version'] == report['appVersion'], 'Host and exact package versions differ.')
        state = host.call('references/list')
        require({provider['id'] for provider in state['providers']} == {'ensembl-archive', 'ncbi-refseq'}, 'Both named providers are not available offline.')
        before = state['local']
        review = import_preview(host, files, metadata, destination)
        require(host.call('references/list')['local'] == before and list(destination.iterdir()) == [sentinel],
                'Review copied or registered local input data before explicit confirmation.')
        write_json(evidence / 'local-import-review.json', review)
        old_token = review['token']
        newer = import_preview(host, files, metadata, destination)
        stale_error = rejected(lambda: host.call('references/import', {'token': old_token}), 'Stale import review token was accepted.')
        genome.write_bytes(genome.read_bytes() + b'\n')
        failed = operation(host, 'import', {'token': newer['token']}, expected='failed')
        require(not failed['local'] and list(destination.iterdir()) == [sentinel], 'Changed reviewed input was copied or published.')
        shutil.copyfile(root / 'examples/starter/reference.fa', genome)
        review = import_preview(host, files, metadata, destination)
        state = operation(host, 'import', {'token': review['token']})
        require(len(state['local']) == 1 and state['local'][0]['available'], 'Reviewed local import did not publish exactly one ready bundle.')
        record = state['local'][0]
        require(record['provider'] == 'local-import' and record['origin'] == 'local-import' and record['user_declared'] == metadata,
                'Local import falsely claimed provider authentication or lost user-declared source context.')
        require('imported_at' in record and 'downloaded_at' not in record, 'Local import was mislabelled as an online download.')
        for file in record['files']:
            require(sha256(file['path']) == file['sha256'] and file['source_sha256'] == original_hashes[file['original_path']],
                    'Imported source/expanded file identities differ from independently observed input bytes.')
        require({path: sha256(path) for path in original_hashes} == original_hashes, 'Import changed original local files.')
        reused_error = rejected(lambda: host.call('references/import', {'token': review['token']}), 'An already-consumed import token was accepted.')
        report['localImport'] = {'record': record, 'originalHashes': original_hashes, 'staleTokenError': stale_error,
                                 'changedFileError': failed['operation']['message'], 'reusedTokenError': reused_error}
        check(report, 'Socket-denied exact private host reviews without copying; stale/replayed review tokens and changed reviewed files fail closed; explicit confirmation copies FASTA and gzip GTF with independently checked source/expanded hashes and clearly user-declared provenance.')

        host.call('workspace/tool', {'toolId': 'bam/reference-index'})
        require(not host.call('references/targets', {'record_id': record['id'], 'file_id': 'annotation'})['targets'],
                'A GTF was offered to a FASTA-only reference indexing input.')
        targets = host.call('references/targets', {'record_id': record['id'], 'file_id': 'genome'})['targets']
        require(len(targets) == 1 and targets[0]['type'] == 'reference', 'Imported FASTA was not offered to the compatible input.')
        target = targets[0]
        state = host.call('references/use', {'record_id': record['id'], 'file_id': 'genome',
                                           'source_id': target['source_id'], 'field_id': target['field_id']})
        graph = state['model']['graph']
        output = evidence / 'frozen-reference-results'
        output.mkdir()
        queued = add_job(host, graph, output)
        frozen = frozen_hashes(queued)
        old_paths = {file['id']: file['path'] for file in record['files']}
        old_receipt_sha = sha256(record['receipt_path'])
        plan_before = read_json(Path(queued['folder']) / 'plan.json')
        relocated = evidence / 'relocated-library'
        relocated.mkdir()
        relocation = operation(host, 'relocate-preview', {'destination': str(relocated)})['review']
        require(relocation['kind'] == 'relocate' and not list(relocated.iterdir()), 'Relocation review copied files before confirmation.')
        write_json(evidence / 'local-relocation-review.json', relocation)
        state = operation(host, 'relocate', {'token': relocation['token']})
        current = next(item for item in state['local'] if item['id'] == record['id'])
        require(Path(state['default_destination']).samefile(relocated), 'Verified relocation did not switch the library default.')
        require(sha256(record['receipt_path']) == old_receipt_sha and frozen_hashes(queued) == frozen,
                'Relocation changed the old receipt or an already frozen queued plan.')
        for file in current['files']:
            require(Path(file['path']).is_relative_to(relocated) and file['path'] != old_paths[file['id']] and
                    sha256(file['path']) == sha256(old_paths[file['id']]) == file['sha256'],
                    'Library relocation did not retain original bytes and verify distinct new copies.')
        require(sentinel.read_text() == 'Preserve during import and relocation.\n', 'Relocation changed unrelated old destination content.')
        host.call('queue/start')
        finished = wait_jobs(host, {queued['job_id']})[0]
        require(finished['status'] == 'completed', 'Queued old-path analysis failed after library relocation: ' + json.dumps(finished))
        folder = Path(queued['folder'])
        plan = read_json(folder / 'plan.json')
        run = read_json(folder / 'run.json')
        require(plan == plan_before and plan['references'], 'Execution changed or lost the frozen reference provenance.')
        require(run['references'] == plan['references'] and read_json(folder / 'reference-provenance.json')['inputs'] == plan['references'] and
                all(plan['inputs'][path]['reference'] == provenance for path, provenance in plan['references'].items()),
                'Completed run, frozen input evidence or result reference receipt differs from the reviewed plan.')
        require(all(path in plan['references'] for path in [str(Path(old_paths['genome']).resolve())]), 'Frozen plan rebound to new library paths.')
        methods = (folder / 'methods-completed.txt').read_text(encoding='utf-8')
        cwl = read_json(folder / 'workflow.cwl')['$graph'][0]
        require(json.loads(cwl['nw:references']) == plan['references'] and 'Local reference import' in methods and 'fixture-v1' in methods,
                'Native run lost local import provenance in CWL or completed methods.')
        index = next(folder.rglob('*.fai'))
        dictionary = [[parts[0], int(parts[1])] for line in index.read_text().splitlines() if (parts := line.split('\t'))]
        require(dictionary == fasta_dictionary(old_paths['genome']), 'Native SAMtools indexing differs from the independent local FASTA dictionary.')
        for name in ('plan.json', 'run.json', 'workflow.cwl', 'methods-completed.txt', 'reference-provenance.json'):
            shutil.copyfile(folder / name, evidence / ('local-reference-' + name))
        report['relocation'] = {'oldPaths': old_paths, 'newRecord': current, 'oldReceiptSha256': old_receipt_sha,
                                'queuedJob': queued, 'frozenCompanions': frozen, 'completedJob': finished, 'indexDictionary': dictionary}
        report['guiFixture'] = {'files': files, 'metadata': metadata, 'defaultDestination': str(relocated)}
        check(report, 'Socket-denied typed selection rejects GTF for a FASTA input; reviewed relocation copies and verifies the library while retaining old paths/receipts and exact queued companions. The previously frozen old-path plan then executes native SAMtools with the correct FASTA dictionary and unchanged reference provenance in methods, plan, results and CWL.')
    finally:
        host.close()
    host = PrivateHost(root, evidence, 'relocated-library-reopened-offline', offline=True)
    try:
        host.call('init')
        state = host.call('references/list')
        require(state['local'][0]['available'] and Path(state['default_destination']).samefile(relocated), 'Offline reopen lost the relocated library.')
        host.call('workspace/tool', {'toolId': 'bam/reference-index'})
        require(host.call('references/targets', {'record_id': record['id'], 'file_id': 'genome'})['targets'], 'Offline reopen lost typed selection of relocated FASTA.')
        check(report, 'A fresh socket-denied private host reopens the relocated local library and offers its verified FASTA to a compatible native tool without contacting either provider.')
    finally:
        host.close()


def ncbi_live_checks(root, evidence, report):
    destination = evidence / 'ncbi-live-downloads'
    destination.mkdir()
    host = PrivateHost(root, evidence, 'ncbi-live-host')
    try:
        host.call('init')
        state = operation(host, 'search', {'provider_id': 'ncbi-refseq', 'release': 'assembly', 'query': 'GCF_000146045.2'})
        require([item['id'] for item in state['species']] == ['GCF_000146045.2'], 'NCBI lookup did not preserve exact versioned accession.')
        state = operation(host, 'discover', {'provider_id': 'ncbi-refseq', 'release': 'assembly', 'species_id': 'GCF_000146045.2'})
        discovery = state['discovery']
        require(discovery['assembly_accession'] == 'GCF_000146045.2' and {file['id'] for file in discovery['files']} == set(NCBI_EXPECTED),
                'NCBI discovery lost its versioned accession or offered unsupported RNA roles.')
        write_json(evidence / 'ncbi-live-discovery.json', discovery)
        previous = {record['id'] for record in state['local']}
        state = operation(host, 'download', {'selection_id': discovery['selection_id'], 'file_ids': list(NCBI_EXPECTED), 'destination': str(destination)})
        added = [record for record in state['local'] if record['id'] not in previous]
        require(len(added) == 1 and added[0]['available'], 'NCBI download did not publish one verified ready bundle.')
        record = added[0]
        for file in record['files']:
            require(all(file.get(key) == value for key, value in NCBI_EXPECTED[file['id']].items()),
                    'NCBI dated independent source pin changed: ' + file['id'])
            require(sha256(file['path']) == file['sha256'] and file['validation']['gzip_crc'] == 'passed' and file['validation']['provider_md5'] == 'passed',
                    'NCBI compressed transfer or expanded identity check is missing.')
        require(record['assembly_accession'] == discovery['assembly_accession'] and record['annotation'] == discovery['annotation'],
                'NCBI receipt lost observed annotation metadata.')
        report['ncbiLive'] = {'record': record, 'independentPinsDate': '2026-10-08', 'expected': NCBI_EXPECTED}
        check(report, 'Live NCBI exact GCF_000146045.2 lookup discovers genome, GTF and protein only; all three downloaded compressed/expanded identities match independently dated pins with MD5 and gzip verification and observed annotation metadata retained.')
    finally:
        host.close()
    host = PrivateHost(root, evidence, 'ncbi-offline-host', offline=True)
    try:
        host.call('init')
        require(any(item['id'] == record['id'] and item['available'] for item in host.call('references/list')['local']), 'NCBI bundle unavailable on offline reopen.')
        host.call('workspace/tool', {'toolId': 'bam/reference-index'})
        target = host.call('references/targets', {'record_id': record['id'], 'file_id': 'genome'})['targets'][0]
        host.call('references/use', {'record_id': record['id'], 'file_id': 'genome', 'source_id': target['source_id'], 'field_id': target['field_id']})
        review = host.call('review')
        require(review['valid'] and 'NCBI' in review['methods'] and 'GCF_000146045.2' in review['methods'], 'NCBI offline typed reuse lost accession provenance.')
        for field in ('name', 'release_date'):
            value = record['annotation'].get(field)
            require(not value or value in review['methods'], 'NCBI methods lost observed annotation ' + field + '.')
        (evidence / 'ncbi-offline-methods.txt').write_text(review['methods'], encoding='utf-8')
        check(report, 'A socket-denied fresh host reuses the downloaded NCBI genome through its compatible FASTA input and retains provider/accession provenance in reviewed methods.')
    finally:
        host.close()


def gui_checks(root, evidence, report):
    from reference_manager import ReferenceManager, ReferencePaused
    manager = ReferenceManager(root)
    discovery = manager.discover(116, 'saccharomyces_cerevisiae')['discovery']
    # These are genuine approved Ensembl transfers paused synchronously at the
    # first durable production progress event, not edited checkpoint fixtures.
    # Reopening the actual GUI must use the persisted normal application path.
    original = {record['id'] for record in manager.snapshot()['local']}
    prepared = []
    for _ in range(2):
        def pause(event):
            if event.get('phase') == 'downloading' and event.get('bytes', 0) > 0:
                manager.pause()
        try:
            manager.download(discovery['selection_id'], ['genome'], report['guiFixture']['defaultDestination'], event=pause)
        except ReferencePaused:
            pass
        else:
            raise AssertionError('Live native pending fixture completed before its synchronous pause.')
    prepared = manager.snapshot()['pending']
    require(len(prepared) == 2 and all(item['status'] == 'paused' and item['bytes'] > 0 for item in prepared),
            'Native pending fixtures were not durably paused real transfers.')
    report['nativePendingFixture'] = prepared
    ui = NativeUI(root, evidence)
    report['nativeGUILaunched'] = True
    try:
        def window(title):
            return next((handle for handle in ui.windows() if ui.label(handle) == title), None)
        def button(parent, identity, *, modal=False):
            handle = ui.child(identity, parent)
            ui.wait('enabled reference control ' + str(identity), lambda: ui.user.IsWindowVisible(handle) and ui.user.IsWindowEnabled(handle))
            (ui.post if modal else ui.send)(handle, 0x00F5)
        def capture(name, parent):
            rows = ui.controls(parent)
            bounds = ui.bounds(parent)
            for row in rows:
                if row['class'].lower() in ('button', 'edit', 'syslistview32'):
                    left, top, right, bottom = row['bounds']
                    require(bounds[0] <= left < right <= bounds[2] and bounds[1] <= top < bottom <= bounds[3],
                            'Visible reference control escaped its native window: ' + str(row['id']))
            report['captures'].append(ui.capture(name + '.bmp', parent))
            write_json(evidence / (name + '-controls.json'), rows)
        def tab(index):
            # Ordinary keyboard navigation causes native selection notifications;
            # no private app state or synthetic WM_NOTIFY is injected.
            handle = ui.child(601, references)
            current = ui.send(handle, 0x130B)
            direction = 1 if index > current else -1
            for target in range(current + direction, index + direction, direction):
                ui.key(handle, 0x27 if direction > 0 else 0x25)
                until('Reference tab keyboard selection did not change.', lambda target=target: ui.send(handle, 0x130B) == target, 10)

        ui.wait('returning workspace ready', lambda: ui.user.IsWindowEnabled(ui.child(410)) and ui.library().tools())
        ui.fit_window(1280, 900)
        ui.click_button(410)
        ui.set_text(ui.child(102), 'FASTA lookup index')
        ui.wait('one native SAMtools FASTA indexing operation', lambda: len(ui.library().tools()) == 1)
        selected_tool = ui.library().tools()[0]
        require('SAMtools' in ui.library().label(selected_tool), 'The native indexing selection is not SAMtools.')
        ui.click_at(*ui.library().point(selected_tool))
        ui.wait('native standalone FASTA input ready', lambda: ui.user.IsWindowEnabled(ui.child(403)) and
                any(row['id'] >= 2000 and row['class'].lower() == 'edit' for row in ui.controls()))
        ui.post(ui.main, 0x0111, 403)
        ui.wait('native References window', lambda: window('References · Native Workbench'))
        references = window('References · Native Workbench')
        provider = ui.child(620, references)
        ui.wait('two native providers loaded offline', lambda: ui.send(provider, 0x0146) == 2 and ui.user.IsWindowEnabled(provider))
        initial_destination = ui.label(ui.child(609, references))
        require(initial_destination and Path(initial_destination).samefile(report['guiFixture']['defaultDestination']),
                'First native References open did not load the persisted relocated library destination.')
        report['nativeLibraryDefault'] = {'firstOpen': initial_destination, 'expected': report['guiFixture']['defaultDestination']}
        names = []
        for index in range(2):
            buffer = ctypes.create_unicode_buffer(1024)
            ui.send(provider, 0x0148, index, ctypes.addressof(buffer))
            names.append(buffer.value)
        require(any('Ensembl archive' in label for label in names) and any('NCBI' in label for label in names),
                'Native selector does not label both reviewed providers.')
        ui.key(provider, 0x24)
        until('Ensembl provider selection failed.', lambda: ui.send(provider, 0x0147) == 0, 10)
        ui.key(provider, 0x28)
        ui.wait('native NCBI lookup controls', lambda: ui.send(provider, 0x0147) == 1 and ui.label(ui.child(602, references)) == 'assembly')
        ui.set_text(ui.child(603, references), 'GCF_000146045.2')
        button(references, 604)
        species = NativeList(ui, ui.child(605, references))
        ui.wait('native exact NCBI assembly row', lambda: species.count() == 1 and ui.user.IsWindowEnabled(ui.child(606, references)), seconds=120)
        button(references, 606)
        products = NativeList(ui, ui.child(607, references))
        ui.wait('three native NCBI reference products', lambda: products.count() == 3 and ui.user.IsWindowEnabled(ui.child(607, references)), seconds=120)
        require(not ui.user.IsWindowEnabled(ui.child(611, references)), 'Native download enabled before any explicit file selection.')
        products.click(0)
        ui.key(ui.child(607, references), 0x20)  # Space toggles the focused native checkbox.
        ui.wait('explicit native genome selection enables download', lambda: ui.user.IsWindowEnabled(ui.child(611, references)))
        text = ui.label(ui.child(608, references))
        require('GCF_000146045.2' in text and 'NCBI' in text, 'Native discovery detail omitted exact assembly/provider identity.')
        capture('references-native-ncbi-discovery', references)
        report['nativeProviders'] = names
        check(report, 'Native References provider selector offers labelled Ensembl archive and NCBI lookup; ordinary control interaction discovers the exact versioned RefSeq assembly and its three products with assembly/provider details visible.')

        tab(2)
        pending = NativeList(ui, ui.child(621, references))
        ui.wait('two paused native downloads visible', lambda: pending.count() == 2)
        pending.click(0)
        capture('references-native-paused-downloads', references)
        button(references, 622)
        # Poll the actual enabled Pause affordance promptly. A completed tiny
        # download cannot be substituted for a successful Pause observation.
        until('Native resumed download never exposed Pause.', lambda: ui.user.IsWindowEnabled(ui.child(624, references)), 30)
        ui.send(ui.child(624, references), 0x00F5)
        ui.wait('native download paused explicitly', lambda: 'paused' in ui.label(ui.child(618, references)).lower() and ui.user.IsWindowEnabled(ui.child(622, references)), seconds=90)
        require(len(manager.snapshot()['pending']) == 2, 'Native Pause discarded rather than retained unfinished work.')
        capture('references-native-pause-confirmed', references)
        button(references, 622)
        ui.wait('native resumed download completed', lambda: pending.count() == 1 and 'completed' in ui.label(ui.child(618, references)).lower(), seconds=240)
        completed = [record for record in manager.snapshot()['local'] if record['id'] not in original]
        require(len(completed) == 1 and completed[0]['files'][0]['sha256'] == EXPECTED['genome']['sha256'] and
                sha256(completed[0]['files'][0]['path']) == EXPECTED['genome']['sha256'],
                'Native Resume did not finish the exact independently pinned Ensembl genome.')
        tab(2)  # Successful Resume deliberately opens Local library.
        ui.wait('remaining paused download visible again', lambda: ui.user.IsWindowVisible(ui.child(621, references)) and pending.count() == 1)
        pending.click(0)
        button(references, 623, modal=True)
        confirm = until('Discard confirmation did not appear.', lambda: window('Discard unfinished download'), 20)
        ui.send(ui.child(6, confirm), 0x00F5)  # Standard MessageBox IDYES.
        ui.wait('native pending discard completed', lambda: pending.count() == 0 and not manager.snapshot()['pending'])
        require(len(manager.snapshot()['local']) == len(original) + 1, 'Native discard changed completed local bundles.')
        capture('references-native-downloads-cleared', references)
        check(report, 'Actual native Downloads lists durable paused live Ensembl transfers; Pause retains one resumed transfer, explicit Resume completes the independently pinned genome, and confirmed Discard removes the other partial transfer without changing ready references.')

        tab(3)
        files = report['guiFixture']['files']
        for identity, file in zip((660, 661), files):
            ui.set_text(ui.child(identity, references), file['path'])
        metadata = dict(report['guiFixture']['metadata'], label='Native GUI imported fixture', species='Native GUI imported species fixture')
        for identity, name in enumerate(('label', 'species', 'assembly', 'assembly_accession', 'source', 'release'), 670):
            ui.set_text(ui.child(identity, references), metadata[name])
        ui.set_text(ui.child(609, references), report['guiFixture']['defaultDestination'])
        before = {record['id'] for record in manager.snapshot()['local']}
        button(references, 625)
        ui.wait('native local import review available', lambda: ui.user.IsWindowEnabled(ui.child(627, references)))
        require({record['id'] for record in manager.snapshot()['local']} == before, 'Native Check for import copied before confirmation.')
        metadata['label'] = 'Native GUI imported fixture after edit'
        ui.set_text(ui.child(670, references), metadata['label'])
        ui.wait('editing reviewed metadata invalidates native confirmation', lambda: not ui.user.IsWindowEnabled(ui.child(627, references)))
        capture('references-native-edited-review-disabled', references)
        button(references, 619)
        ui.wait('References closed after editing reviewed metadata', lambda: not window('References · Native Workbench'))
        ui.post(ui.main, 0x0111, 403)
        ui.wait('References reopened for real server list refresh', lambda: window('References · Native Workbench'))
        references = window('References · Native Workbench')
        # Idle References does not poll. Reopening deliberately performs the
        # normal references/list RPC, which still carries the server's older
        # review. Once the loaded controls are enabled, it must remain rejected.
        ui.wait('reopened reference list response applied', lambda: ui.send(ui.child(620, references), 0x0146) == 2 and
                ui.user.IsWindowVisible(ui.child(604, references)) and ui.user.IsWindowEnabled(ui.child(604, references)))
        require(not ui.user.IsWindowEnabled(ui.child(627, references)), 'A real server list refresh revived the invalidated native review token.')
        reopened_destination = ui.label(ui.child(609, references))
        require(reopened_destination and Path(reopened_destination).samefile(report['guiFixture']['defaultDestination']),
                'Reopened native References lost the persisted relocated library destination.')
        report['nativeLibraryDefault']['reopened'] = reopened_destination
        require({record['id'] for record in manager.snapshot()['local']} == before, 'Closing or reopening stale review imported data.')
        tab(3)
        for identity, file in zip((660, 661), files):
            ui.set_text(ui.child(identity, references), file['path'])
        for identity, name in enumerate(('label', 'species', 'assembly', 'assembly_accession', 'source', 'release'), 670):
            ui.set_text(ui.child(identity, references), metadata[name])
        ui.set_text(ui.child(609, references), report['guiFixture']['defaultDestination'])
        require(not ui.user.IsWindowEnabled(ui.child(627, references)), 'Reentering import fields revived a stale review before a fresh check.')
        button(references, 625)
        ui.wait('freshly checked edited native import review available', lambda: ui.user.IsWindowEnabled(ui.child(627, references)))
        report['nativeReviewInvalidation'] = {'metadataEdited': 'label', 'serverRefresh': 'references/list on close and reopen',
                                             'invalidatedReviewStayedDisabled': True, 'freshPreviewExplicitlyRequested': True,
                                             'reviewedLabel': metadata['label']}
        capture('references-native-import-fields', references)
        button(references, 627, modal=True)
        review = until('Native import review did not open.', lambda: window('Review local reference import'), 20)
        details = ui.label(ui.child(105, review))
        require('SHA-256:' in details and 'fixture-v1' in details and metadata['label'] in details and 'declaration' in details.lower(),
                'Native local import review omitted hashes, assembly or user-declared provenance notice.')
        capture('references-native-import-review', review)
        ui.send(ui.child(2, review), 0x00F5)
        ui.wait('import review closed without copying', lambda: not window('Review local reference import'))
        require({record['id'] for record in manager.snapshot()['local']} == before, 'Closing native import review copied files.')
        button(references, 627, modal=True)
        review = until('Native import review did not reopen.', lambda: window('Review local reference import'), 20)
        ui.send(ui.child(1, review), 0x00F5)
        ui.wait('native confirmed import completed', lambda: 'Local references copied and verified' in ui.label(ui.child(618, references)) and not window('Review local reference import'), seconds=120)
        imported = next(record for record in manager.snapshot()['local'] if record['id'] not in before)
        require(imported['user_declared'] == metadata and imported['available'], 'Native import did not preserve its reviewed metadata/verified status.')
        tab(1)
        local = NativeList(ui, ui.child(612, references))
        ui.wait('native local list refreshed', lambda: local.count() == 5)
        candidates = [index for index in range(local.count()) if 'Native GUI imported species fixture' in local.text(index, 0)]
        require(len(candidates) == 2, 'Native imported files are not both listed.')
        genome_row = next(index for index in candidates if 'Genome' in local.text(index, 2) or 'genome' in local.text(index, 2))
        local.click(genome_row)
        ui.wait('native imported genome has compatible input', lambda: ui.user.IsWindowEnabled(ui.child(614, references)))
        capture('references-native-local-compatible-input', references)
        button(references, 614)
        genome_path = next(file['path'] for file in imported['files'] if file['id'] == 'genome')
        ui.wait('native reference binding completed', lambda: 'Reference assigned.' in ui.label(ui.child(618, references)) and
                any(row['id'] >= 2000 and row['class'].lower() == 'edit' and row['text'] == genome_path for row in ui.controls()))
        report['nativeReferenceBinding'] = {'tool': 'bam/reference-index', 'path': genome_path,
                'sha256': sha256(genome_path), 'nativeNotice': ui.label(ui.child(618, references)),
                'inspectorEdits': [row for row in ui.controls() if row['id'] >= 2000 and row['class'].lower() == 'edit']}
        capture('references-native-bound-input', references)
        check(report, 'Native Import local edits explicit roles/metadata and previews hashes without copying; editing metadata invalidates confirmation even after a real close/reopen server refresh, and a fresh explicit preview includes the edited declaration. Closing review imports nothing; confirmation then creates one verified bundle. Local library refresh lists both imported products and offers/uses its FASTA in a compatible standalone SAMtools input, with the exact bound path independently read back from the native inspector.')

        # The system folder picker is exercised through its normal text control;
        # UI enumeration records the real control IDs rather than assuming a
        # host-specific shell dialog layout.
        new_location = evidence / 'native-relocated-library'
        new_location.mkdir()
        button(references, 626, modal=True)
        picker = until('Native relocation folder chooser did not open.', lambda: window('Choose a new reference library location'), 20)
        controls = ui.controls(picker)
        write_json(evidence / 'native-relocation-picker-controls.json', controls)
        edits = [row for row in controls if row['class'].lower() == 'edit' and ui.user.IsWindowEnabled(row['hwnd'])]
        require(edits, 'Native relocation folder chooser has no editable folder selection.')
        # Common Item Dialog's file/folder name edit is the lowest visible edit;
        # the navigation/search edits, if present, are above it.
        edit = max(edits, key=lambda row: row['bounds'][1])['hwnd']
        # NativeUI.set_text deliberately rejects unexpected system dialogs;
        # this particular expected folder picker is observed and handled here.
        require(ui.user.IsWindowEnabled(edit), 'Expected folder edit is disabled.')
        buffer = ctypes.create_unicode_buffer(str(new_location))
        require(ui.send(edit, 0x000C, 0, ctypes.addressof(buffer)), 'Could not enter the native folder selection.')
        ui.send(ui.child(1, picker), 0x00F5)
        until('Native relocation folder chooser did not accept the existing directory.', lambda: not window('Choose a new reference library location'), 20)
        ui.wait('native relocation review available', lambda: ui.user.IsWindowEnabled(ui.child(627, references)), seconds=120)
        button(references, 627, modal=True)
        review = until('Native relocation review did not open.', lambda: window('Review library relocation'), 20)
        details = ui.label(ui.child(105, review))
        require(str(new_location) in details and 'retained' in details.lower() and 'SHA-256:' in details,
                'Native relocation review omitted its destination, retained-original notice or verified identities.')
        capture('references-native-relocation-review', review)
        ui.send(ui.child(1, review), 0x00F5)
        ui.wait('native copy and switch completed', lambda: 'Library location changed after verification' in ui.label(ui.child(618, references)), seconds=120)
        capture('references-native-relocation-complete', references)
        final_library = manager.snapshot()
        require(Path(final_library['default_destination']).samefile(new_location) and all(record['available'] for record in final_library['local']), 'Native relocation left unavailable library entries or failed to switch destinations.')
        check(report, 'Native Relocate library chooses an existing directory, presents exact destination/file hashes and original-retention notice, and explicit Copy and switch moves the active library only after all copies verify.')
        report['dpi'] = ui.user.GetDpiForWindow(references)
        button(references, 619)
        report['nativeGUIValidated'] = True
    except Exception:
        try:
            ui.desktop_evidence('reference management gate failure')
            for number, handle in enumerate(ui.windows()):
                ui.capture('reference-management-failure-%d.bmp' % number, handle)
                write_json(evidence / ('reference-management-failure-%d.json' % number), {'title': ui.label(handle), 'controls': ui.controls(handle)})
        except Exception as error:
            report['failureCaptureError'] = str(error)
        raise
    finally:
        ui.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--app-root', type=Path, required=True)
    parser.add_argument('--report', type=Path, required=True)
    parser.add_argument('--source-commit', required=True)
    parser.add_argument('--asset-sha256', required=True)
    parser.add_argument('--asset-name', required=True)
    parser.add_argument('--app-version', default='0.15.0')
    parser.add_argument('--suite', choices=['live', 'management'], required=True)
    args = parser.parse_args()
    args.report = args.report.resolve()
    args.skip_analysis = False
    root, evidence = args.app_root.resolve(), args.report.parent
    evidence.mkdir(parents=True, exist_ok=True)
    report = {'schema': 1, 'success': False, 'suite': args.suite, 'appVersion': args.app_version,
              'sourceCommit': args.source_commit, 'assetName': args.asset_name, 'assetSha256': args.asset_sha256,
              'gateSha256': sha256(__file__), 'platform': platform.platform(), 'python': sys.version,
              'startedUtc': datetime.now(timezone.utc).isoformat(), 'nativeWindowsExecuted': False,
              'nativeGUILaunched': False, 'nativeGUIValidated': False, 'checks': [], 'skips': [], 'captures': [],
              'limits': ['Only the named hosted Windows image, ordinary/spaced path case and observed desktop DPI are established.',
                         'Deterministic hostile transfer cases inject only a gate-owned provider response boundary, not live upstream responses.',
                         'RefSeq dated hashes bind observed annotation bytes; a versioned assembly does not make its annotation directory immutable.',
                         'No updater, release promotion, institutional endpoint acceptance or realistic scientific benchmark is exercised.']}
    try:
        require(os.name == 'nt', 'This exact-package gate requires native Windows.')
        require(Path(sys.executable).resolve() == (root / 'runtime/python/python.exe').resolve(), 'Use the exact installed private Python.')
        require(read_json(root / 'manifest.json')['version'] == args.app_version, 'Manifest differs from candidate identity.')
        report['appFiles'] = {str(path.relative_to(root)): sha256(path) for path in [root / 'NativeWorkbench.exe', root / 'WorkbenchBridge.exe', *sorted((root / 'workspace').glob('*.py'))]}
        sys.path.insert(0, str(root / 'workspace'))
        if args.suite == 'live':
            run_reference_checks(root, evidence, report, args)
            ncbi_live_checks(root, evidence, report)
        else:
            fixture_transfer_checks(root, evidence, report)
            host_library_checks(root, evidence, report)
            gui_checks(root, evidence, report)
        require(all(sha256(root / name) == digest for name, digest in report['appFiles'].items()), 'Gate changed installed production bytes.')
        report['nativeWindowsExecuted'] = True
        report['success'] = True
    except Exception as error:
        report['failure'] = {'type': type(error).__name__, 'message': str(error), 'traceback': traceback.format_exc()}
        traceback.print_exc()
    finally:
        report['passed'] = len(report['checks'])
        report['finishedUtc'] = datetime.now(timezone.utc).isoformat()
        write_json(args.report, report)
        print(json.dumps({'success': report['success'], 'passed': report['passed'], 'report': str(args.report)}), flush=True)
    return 0 if report['success'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
