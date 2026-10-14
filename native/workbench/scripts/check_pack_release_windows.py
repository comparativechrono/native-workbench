#!/usr/bin/env python3
"""Import one release into a disposable Windows app and run its scientific checks.

Requires an extracted 0.6+ Windows application. Makes no network requests.
The disposable application is modified; use a fresh copy for every CI job.
"""
from __future__ import annotations

import argparse
import copy
import json
import os
from pathlib import Path
import sys


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--app-root', type=Path, required=True)
    parser.add_argument('--archive', type=Path, required=True)
    parser.add_argument('--report', type=Path, required=True)
    args = parser.parse_args(argv)
    if os.name != 'nt':
        parser.exit(1, 'This scientific release gate must run on native Windows.\n')
    root = args.app_root.resolve()
    if not (root / 'WorkbenchBridge.exe').is_file():
        parser.exit(1, 'Expected an extracted native Workbench app at --app-root.\n')
    # Test the released application's implementation, not the SDK checkout.
    sys.path.insert(0, str(root / 'workspace'))
    from catalog import load_catalog, load_pack
    from pack_manager import PackManager
    from pack_checks import run_pack_checks
    from engine import NativeBackend
    from service import Workbench
    app = None
    backend = None
    report = {'schema': 1, 'nativeWindowsHost': True, 'nativeWindowsExecuted': False, 'success': False}
    class ObservedBackend(NativeBackend):
        def _spawn(self, *arguments, **options):
            process = super()._spawn(*arguments, **options)
            report['nativeWindowsExecuted'] = True
            return process
    try:
        app = Workbench(root)
        manager = PackManager(root, app._install_pack_folder)
        installed = manager.import_archive(args.archive.resolve())
        identity, version = installed['packId'], installed['packVersion']
        report.update(packId=identity, packVersion=version, installation=installed)
        catalog = load_catalog(root)
        candidate = next(row for row in catalog['packs'] if row['id'] == identity and row['version'] == version)
        pack = load_pack(root / candidate['folder'] / 'pack.ini')
        if 'workbench-checks' not in pack['assets']:
            raise ValueError('Release gate requires declared scientific self-checks; zero checks cannot pass.')
        selected = copy.deepcopy(catalog)
        selected['tools'] = {key: tool for key, versions in catalog['toolVersions'].items()
                             for tool in versions if tool.get('packId') == identity and tool.get('packVersion') == version}
        selected['toolVersions'] = {key: [tool] for key, tool in selected['tools'].items()}
        selected['packs'] = [candidate]
        results = root / 'results'
        results.mkdir(exist_ok=True)
        backend = ObservedBackend(root)
        checks = run_pack_checks(root, selected, results, backend=backend)
        report['scientificChecks'] = checks
        if not checks.get('success') or checks.get('passed', 0) == 0:
            raise ValueError('Candidate pack scientific checks failed or did not execute.')
        try:
            manager.import_archive(args.archive.resolve())
        except ValueError as exc:
            if 'already installed' not in str(exc).lower():
                raise
            report['duplicateVersionRejected'] = True
        else:
            raise ValueError('Duplicate version unexpectedly installed.')
        if load_pack(root / candidate['folder'] / 'pack.ini')['manifestSha256'] != candidate['manifestSha256']:
            raise ValueError('Duplicate import changed the installed manifest.')
        report['success'] = True
    except Exception as exc:
        report['error'] = str(exc)
    finally:
        if app is not None:
            app.shutdown()
        if backend is not None:
            backend.shutdown()
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    print(json.dumps({'success': report['success'], 'nativeWindowsHost': True, 'nativeWindowsExecuted': report['nativeWindowsExecuted'], 'report': str(args.report.resolve())}))
    return 0 if report['success'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
