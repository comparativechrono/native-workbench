#!/usr/bin/env python3
"""Freeze independent Primer3/PLINK2 packs and check exact Windows applications.

The prior candidate's archive and normal-graph helpers are loaded privately.
Neither its configuration nor the immutable application modules are changed.
The two tools remain scientifically independent; this gate does not invent a
primer-design to population-genetics pipeline.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import importlib.util
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import traceback
import zipfile

sys.dont_write_bytecode = True
SOURCE = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location('primer3_plink2_candidate_common', SOURCE / 'scripts/check_prodigal_fasttree_windows.py')
common = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(common)
common.PACK_IDS = ('primer3', 'plink2')
common.VERSIONS = {identity: '1.0.0' for identity in common.PACK_IDS}
common.OPERATIONS = {'primer3': {'design-pcr'}, 'plink2': {'summarize-vcf'}}
common.FROZEN_GATE_PATHS = {
    'scripts/check_primer3_plink2_windows.py', 'scripts/check_primer3_plink2_gui.py',
    'scripts/audit_primer3_plink2_candidate.py', 'tests/test_primer3_plink2_validation.py',
    '.github/workflows/native-primer3-plink2-recheck.yml',
}
PACK_IDS, VERSIONS, APPLICATIONS = common.PACK_IDS, common.VERSIONS, common.APPLICATIONS
require, sha, read_json, write_json = common.require, common.sha, common.read_json, common.write_json
file_record, verify_extracted, run_command = common.file_record, common.verify_extracted, common.run_command


def freeze(args):
    sys.path.insert(0, str(SOURCE / 'scripts'))
    from package_split import build_pack
    from validate_pack_release import inspect_release
    source = common.checkout_sources(args.source_commit)
    require(not args.output.exists(), 'Choose a new candidate output directory.')
    args.output.mkdir(parents=True)
    packs, entries = {}, [('source/' + name, path) for name, path in source]
    for identity in PACK_IDS:
        folder = getattr(args, identity + '_pack').resolve()
        archive = args.output / ('native-workbench-pack-' + identity + '-' + VERSIONS[identity] + '.zip')
        built = build_pack(folder, archive, '0.16.0')
        inspected = inspect_release(archive)
        require((inspected['id'], inspected['version']) == (identity, VERSIONS[identity]), 'Unexpected pack identity.')
        require(built['sha256'] == inspected['sha256'], 'Static validation changed archive identity.')
        packs[identity] = {**file_record(archive), 'id': identity, 'version': VERSIONS[identity],
                           'manifestSha256': inspected['manifestSha256'], 'staticValidation': inspected}
        for path in sorted((folder / 'licenses').rglob('*')):
            if path.is_file():
                require(not path.is_symlink(), 'Corresponding source contains a symbolic link.')
                entries.append(('corresponding-sources/' + identity + '/' + path.relative_to(folder / 'licenses').as_posix(), path))
    for number, root in enumerate(args.build_evidence):
        require(root.is_dir(), 'Build evidence directory is absent.')
        for path in sorted(root.rglob('*')):
            if path.is_file():
                require(not path.is_symlink(), 'Build evidence contains a symbolic link.')
                entries.append(('build-evidence/' + str(number + 1) + '/' + path.relative_to(root).as_posix(), path))
    inventory = [{'path': name, 'bytes': path.stat().st_size, 'sha256': sha(path)} for name, path in entries]
    provenance = {'schema': 1, 'kind': 'unpublished-primer3-plink2-candidate',
                  'sourceCommit': args.source_commit,
                  'sourceTree': subprocess.check_output(['git', 'rev-parse', 'HEAD^{tree}'], cwd=SOURCE, text=True).strip(),
                  'createdUtc': datetime.now(timezone.utc).isoformat(), 'buildHost': platform.platform(),
                  'python': sys.version, 'packs': packs, 'applications': APPLICATIONS,
                  'nativeWindowsExecuted': False, 'published': False,
                  'limits': ['Build-time source/static evidence only. Separate native reports must bind these exact archive hashes.',
                             'The packs are independently importable and do not imply a shared scientific workflow.',
                             'Application binaries and published catalogues are unchanged.']}
    companion = args.output / 'native-workbench-primer3-plink2-1.0.0-source-evidence.zip'
    common.zip_files(companion, entries, {'SOURCE-INVENTORY.json': {'schema': 1, 'sourceCommit': args.source_commit, 'files': inventory},
                                        'BUILD-PROVENANCE.json': provenance})
    provenance['sourceCompanion'] = file_record(companion)
    write_json(args.output / 'BUILD-PROVENANCE.json', provenance)
    (args.output / 'SHA256SUMS.txt').write_text('\n'.join(row['sha256'] + '  ' + row['file']
        for row in [*packs.values(), provenance['sourceCompanion']]) + '\n', encoding='ascii')
    return provenance


def installed_inventory(folder):
    return {path.relative_to(folder).as_posix(): sha(path) for path in folder.rglob('*') if path.is_file()}


def archive_inventory(archive):
    with zipfile.ZipFile(archive) as zipped:
        envelope = json.loads(zipped.read('workbench-pack.json'))
        return {row['path']: row['sha256'] for row in envelope['files']}


def scientific_report_passed(report):
    """Fail closed when a selected scientific suite did not actually execute."""
    return (report.get('success') is True and report.get('nativeWindowsExecuted') is True and
            isinstance(report.get('testsRun'), int) and report['testsRun'] > 0 and
            not report.get('skipped') and bool(report.get('executions')))


def installation_regression(root, evidence, report):
    from check_references_windows import PrivateHost
    host = PrivateHost(root, evidence, 'primer3-plink2-regression-host', offline=True)
    try:
        require(host.call('init')['app_version'] == report['applicationVersion'], 'Wrong application process.')
        record = common.completed(host, 'check', {'output_folder': str(evidence / 'analysis-results')})
        write_json(evidence / 'installation-regression.json', record)
        require(record.get('pack_checks', {}).get('success'), 'Combined installed pack checks failed.')
        require(record.get('starter_checks', {}).get('nativeWindowsExecuted') and
                record['starter_checks'].get('passed', 0) > 0 and record.get('skipped') == 0,
                'Starter science must execute natively; skipped checks cannot pass.')
        report['checks'].append('Unchanged Starter science and all installed declared pack checks pass together.')
    finally:
        host.close()


def native(args):
    require(os.name == 'nt', 'This gate requires native Windows; Linux is not equivalent.')
    root, evidence = args.app_root.resolve(), args.report.resolve().parent
    require(not evidence.is_relative_to(root), 'Evidence must be outside the immutable application tree.')
    evidence.mkdir(parents=True, exist_ok=True)
    candidate_commit = args.candidate_source_commit or args.source_commit
    report = {'schema': 1, 'kind': 'native-primer3-plink2-candidate', 'success': False,
              'candidateSourceCommit': candidate_commit, 'gateSourceCommit': args.source_commit,
              'applicationVersion': args.app_version, 'applicationSourceCommit': APPLICATIONS[args.app_version]['sourceCommit'],
              'applicationArchive': file_record(args.app_archive), 'mode': args.mode,
              'nativeWindowsHost': True, 'nativeWindowsExecuted': False, 'python': sys.version,
              'platform': platform.platform(), 'checks': [], 'captures': [],
              'limitations': ['Synthetic bounded fixtures only; no representative-PC or large-data performance acceptance.',
                             'No release, catalogue publication, signing, institutional deployment or updater validation.',
                             'Offline private host denies Python socket calls; not operating-system network isolation.',
                             'Primer3 candidate selection is not an experimental validation or off-target specificity check.',
                             'PLINK2 reports supported hard-call measurements without inferred QC acceptance thresholds.']}
    try:
        require(sha(args.app_archive) == APPLICATIONS[args.app_version]['sha256'], 'Unexpected application archive.')
        report['coreFilesVerifiedBefore'] = verify_extracted(args.app_archive, root)
        frozen = common.verify_candidate(args.candidate, candidate_commit, args.source_commit)
        report['frozenCandidateRecheck'] = candidate_commit != args.source_commit
        report['gateSourceDifferences'] = common.frozen_source_changes(candidate_commit, args.source_commit) if candidate_commit != args.source_commit else []
        report['packs'], report['sourceCompanion'] = frozen['packs'], frozen['sourceCompanion']
        sys.path.insert(0, str(root / 'workspace'))
        sys.path.insert(1, str(SOURCE / 'scripts'))
        import catalog
        require(Path(catalog.__file__).resolve().parent == root / 'workspace',
                'Native graph expectations must use the exact packaged application modules.')
        python = root / 'runtime/python/python.exe'
        installed, expected = {}, {}
        for identity in PACK_IDS:
            archive = args.candidate / frozen['packs'][identity]['file']
            run_command([python, '-I', '-B', SOURCE / 'scripts/check_pack_release_windows.py', '--app-root', root,
                         '--archive', archive, '--report', evidence / (identity + '-installation.json')],
                        evidence / (identity + '-installation.log'))
            result = read_json(evidence / (identity + '-installation.json'))
            require(result['success'] and result['nativeWindowsExecuted'] and result['duplicateVersionRejected'],
                    'Native import/check did not fully execute: ' + identity)
            report['nativeWindowsExecuted'] = True
            report['checks'].append(identity + ': exact ZIP native import, declared scientific checks and duplicate-version rejection.')
            installed[identity] = root / 'packs' / (identity + '-' + VERSIONS[identity])
            expected[identity] = archive_inventory(archive)
            if args.mode == 'science':
                run_command([python, '-I', '-B', SOURCE / ('tests/test_' + identity + '_pack.py'),
                             '--pack', installed[identity], '--report', evidence / (identity + '-regressions.json')],
                            evidence / (identity + '-regressions.log'))
                regression = read_json(evidence / (identity + '-regressions.json'))
                require(scientific_report_passed(regression),
                        'Selected native scientific regressions must execute with no skips: ' + identity)
                report['checks'].append(identity + ': exact installed scientific and failure regressions.')
        for identity, folder in installed.items():
            require(installed_inventory(folder) == expected[identity], 'Installed pack differs from exact archive: ' + identity)
        common.graph_checks(root, evidence, report, starter=False)
        if args.mode == 'science':
            installation_regression(root, evidence, report)
        else:
            from check_primer3_plink2_gui import run_gui
            run_gui(root, evidence, report)
        for identity, folder in installed.items():
            require(installed_inventory(folder) == expected[identity], 'Installed pack changed during graph/GUI checks: ' + identity)
        report['coreFilesVerifiedAfter'] = verify_extracted(args.app_archive, root)
        report['checks'].append('Pinned application and installed pack bytes remain unchanged after execution.')
        report['success'] = True
    except Exception:
        report['error'] = traceback.format_exc()
    finally:
        write_json(args.report, report)
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    create = commands.add_parser('freeze')
    for identity in PACK_IDS:
        create.add_argument('--' + identity + '-pack', type=Path, required=True)
    create.add_argument('--output', type=Path, required=True)
    create.add_argument('--build-evidence', type=Path, action='append', default=[])
    create.add_argument('--source-commit', required=True)
    check = commands.add_parser('native')
    check.add_argument('--candidate', type=Path, required=True)
    check.add_argument('--app-root', type=Path, required=True)
    check.add_argument('--app-archive', type=Path, required=True)
    check.add_argument('--app-version', choices=APPLICATIONS, required=True)
    check.add_argument('--mode', choices=('science', 'gui'), required=True)
    check.add_argument('--source-commit', required=True, help='Actual validator/gate checkout commit.')
    check.add_argument('--candidate-source-commit', help='Frozen pack build commit; defaults to the gate commit.')
    check.add_argument('--report', type=Path, required=True)
    args = parser.parse_args(argv)
    report = freeze(args) if args.command == 'freeze' else native(args)
    print(json.dumps({'success': report.get('success', True), 'command': args.command,
                      'checks': len(report.get('checks', [])), 'sourceCommit': args.source_commit}))
    return 0 if report.get('success', True) else 1


if __name__ == '__main__':
    raise SystemExit(main())
