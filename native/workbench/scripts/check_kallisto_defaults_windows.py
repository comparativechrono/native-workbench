#!/usr/bin/env python3
"""Run the installed immutable kallisto pack's paired fixture at its UI default.

Run after check_pack_release_windows.py imported the release. This helper makes
no network requests and never edits installed pack files. Only the in-memory
fixture parameters change: threads=2. It uses the released app's native engine
and the original hash-verified scientific output assertions.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import sys
import threading
import time


def snapshot(folder):
    """Hash all installed files so accidental writes/additions cannot pass."""
    result = {}
    for path in sorted(folder.rglob('*')):
        if path.is_symlink():
            raise ValueError('Installed pack unexpectedly contains a symbolic link.')
        if path.is_file():
            value = hashlib.sha256()
            with path.open('rb') as stream:
                for block in iter(lambda: stream.read(1024 * 1024), b''):
                    value.update(block)
            result[path.relative_to(folder).as_posix()] = value.hexdigest()
    return result


def build_graph(case, tool, pin, asset_path):
    """Copy the trusted case and change only its explicit thread parameter."""
    if case.get('workflow') != 'index-quant-paired':
        raise ValueError('The default-thread gate requires the paired indexing/quantification fixture.')
    parameters = {item['id']: item for item in tool.get('params', [])}
    if str(parameters.get('threads', {}).get('default', '')) != '2':
        raise ValueError('Expected this immutable pack to have UI default threads=2.')
    if str(case.get('params', {}).get('threads', '')) != '1':
        raise ValueError('Expected the original scientific fixture to request one thread.')
    selected = copy.deepcopy(case)
    selected['params']['threads'] = 2
    ports = {port['id']: port for port in tool['ports']}
    bindings, sources = {}, []
    for port_id, members in selected['inputs'].items():
        if port_id not in ports:
            raise ValueError('Scientific fixture names an unknown input port.')
        bindings[port_id] = []
        for member in members:
            if set(member) != set(ports[port_id]['manifestInputs']):
                raise ValueError('Scientific fixture fields do not match their declared port.')
            identity = 'input-' + str(len(sources) + 1)
            files = {key: str(asset_path(value)) for key, value in member.items()}
            sources.append({'id': identity, 'label': ports[port_id]['label'], 'type': ports[port_id]['type'], 'files': files})
            bindings[port_id].append(identity)
    if not isinstance(selected.get('expect'), list) or not selected['expect']:
        raise ValueError('Original scientific fixture must assert expected outputs.')
    graph = {'schema': 1, 'name': 'kallisto native Windows UI default: two threads',
             'nodes': [{'id': 'step-1', 'tool': tool['id'], 'pin': dict(pin),
                        'params': selected['params'], 'inputs': bindings}],
             'sources': sources, 'nextNode': 2, 'nextSource': len(sources) + 1}
    return graph, selected['expect']


def diagnostic_tails(folder, max_files=12, max_bytes=8192):
    """Read bounded tails from this fixture's private run only."""
    root = Path(folder).resolve()
    result = []
    for path in sorted(root.rglob('*')):
        if len(result) >= max_files:
            break
        lower = path.name.lower()
        if (not path.is_file() or path.is_symlink() or
                not any(token in lower for token in ('stdout', 'stderr', 'workbench.log', 'log.out')) and path.suffix.lower() != '.log'):
            continue
        if not path.resolve().is_relative_to(root):
            continue
        try:
            size = path.stat().st_size
            with path.open('rb') as stream:
                stream.seek(max(0, size - max_bytes))
                data = stream.read(max_bytes)
            result.append({'path': path.relative_to(root).as_posix(), 'bytes': size,
                           'truncated': size > max_bytes, 'tail': data.decode('utf-8', errors='replace')})
        except OSError as error:
            result.append({'path': path.relative_to(root).as_posix(), 'readError': str(error)})
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--app-root', type=Path, required=True)
    parser.add_argument('--report', type=Path, required=True)
    parser.add_argument('--pack-version', default='1.0.0')
    parser.add_argument('--timeout-seconds', type=int, default=120)
    args = parser.parse_args(argv)
    if os.name != 'nt':
        parser.exit(1, 'This default-thread gate must run on native Windows.\n')
    if not 10 <= args.timeout_seconds <= 300:
        parser.error('--timeout-seconds must be between 10 and 300')
    root = args.app_root.resolve()
    if not (root / 'WorkbenchBridge.exe').is_file():
        parser.exit(1, 'Expected an extracted native Workbench application.\n')
    sys.path.insert(0, str(root / 'workspace'))
    from catalog import load_catalog, load_pack
    from engine import Engine, NativeBackend, resolve_tool, pin_for
    from pack_checks import _asset, _json, _assert_output

    report = {'schema': 1, 'packId': 'kallisto', 'packVersion': args.pack_version,
              'nativeWindowsHost': True, 'nativeWindowsExecuted': False,
              'threads': 2, 'timeoutSeconds': args.timeout_seconds, 'success': False, 'passed': 0, 'failed': 1,
              'scope': 'Original paired scientific fixture at the actual UI default threads=2; immutable installed pack.'}
    backend = None
    timer = None
    pack_root = None
    before = None
    cancel = threading.Event()
    started = time.monotonic()
    class ObservedBackend(NativeBackend):
        def _spawn(self, *arguments, **options):
            process = super()._spawn(*arguments, **options)
            report['nativeWindowsExecuted'] = True
            return process
        def run(self, request, event, cancel):
            report.setdefault('nativeRequests', []).append({
                'workflow': request['workflow_id'], 'values': request['values'],
                'outputFolder': request['output_folder'], 'packSha256': request['pack_sha256']})
            result = super().run(request, event, cancel)
            report.setdefault('nativeResults', []).append({key: result.get(key) for key in
                ('success', 'cancelled', 'message', 'folder', 'exitCode', 'exit_code') if key in result})
            return result
    try:
        catalog = load_catalog(root)
        candidates = [row for row in catalog['packs'] if row['id'] == 'kallisto' and row['version'] == args.pack_version]
        if len(candidates) != 1:
            raise ValueError('Expected exactly one already-installed kallisto pack at the requested version.')
        candidate = candidates[0]
        pack_root = root / candidate['folder']
        before = snapshot(pack_root)
        pack = load_pack(pack_root / 'pack.ini')
        pin = {'packId': 'kallisto', 'packVersion': args.pack_version, 'manifestSha256': pack['manifestSha256']}
        specification = _json(_asset(pack_root, pack, 'workbench-checks', cancel))
        cases = [case for case in specification['checks'] if case.get('workflow') == 'index-quant-paired']
        if len(cases) != 1:
            raise ValueError('Expected exactly one original paired scientific fixture.')
        tool = resolve_tool(catalog, 'kallisto/index-quant-paired', pin)
        graph, expectations = build_graph(cases[0], tool, pin_for(tool), lambda name: _asset(pack_root, pack, name, cancel))
        report.update(manifestSha256=pack['manifestSha256'], originalCheck=cases[0]['id'],
                      originalThreads=cases[0]['params']['threads'], assertions=len(expectations),
                      installedFiles=len(before), parameters=graph['nodes'][0]['params'])
        backend = ObservedBackend(root)
        engine = Engine(root, catalog, backend=backend)
        results = root / 'results'
        results.mkdir(exist_ok=True)
        def expire():
            cancel.set()
            # Closing the native bridge closes its kill-on-close Job Object,
            # bounding the check even if a child tool cannot cancel cleanly.
            backend.shutdown()
        timer = threading.Timer(args.timeout_seconds, expire)
        timer.daemon = True
        timer.start()
        plan = engine.prepare(graph, results, cancel=cancel)
        result = engine.execute(plan, cancel=cancel)
        report.update(folder=result.get('folder', plan['folder']), status=result.get('status'))
        report['resultNodes'] = [{key: node.get(key) for key in
            ('id', 'tool', 'status', 'message', 'folder', 'started', 'finished') if key in node}
            for node in result.get('nodes', [])]
        if cancel.is_set():
            raise ValueError('The bounded default-thread scientific check timed out.')
        if result.get('success') is not True or result.get('status') != 'success':
            raise ValueError('Native tool did not complete: ' + str(result.get('message', result.get('status'))))
        for expected in expectations:
            _assert_output(expected, result)
        if not report['nativeWindowsExecuted']:
            raise ValueError('No native Windows process executed.')
        report.update(success=True, passed=1, failed=0)
    except Exception as error:
        report['error'] = str(error)
    finally:
        if timer is not None:
            timer.cancel()
        if backend is not None:
            backend.shutdown()
        if pack_root is not None and before is not None:
            try:
                after = snapshot(pack_root)
                report['installedPackUnchanged'] = after == before
                if after != before:
                    report['installedFilesChanged'] = sorted(key for key in set(before) | set(after) if before.get(key) != after.get(key))[:30]
                    report.update(success=False, passed=0, failed=1, error='Running the default-thread fixture changed installed pack files.')
            except Exception as error:
                report.update(success=False, passed=0, failed=1, installedPackUnchanged=False,
                              installedSnapshotError=str(error))
        if not report['success'] and report.get('folder'):
            report['diagnosticTails'] = diagnostic_tails(report['folder'])
        report['elapsedSeconds'] = round(time.monotonic() - started, 3)
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    print(json.dumps({key: report[key] for key in ('success', 'nativeWindowsExecuted', 'threads', 'passed', 'failed', 'elapsedSeconds')}))
    return 0 if report['success'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
