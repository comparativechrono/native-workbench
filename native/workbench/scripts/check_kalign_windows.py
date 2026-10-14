#!/usr/bin/env python3
"""Freeze and validate the unpublished Kalign pack against exact Windows apps.

The established pack-candidate module is loaded privately for its archive,
source-binding, import and normal-graph helpers. Its original configuration and
first-batch entry points are not changed. Application code always comes from the
separately hashed extracted app, never from this validation checkout.
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
_spec = importlib.util.spec_from_file_location('kalign_candidate_common', SOURCE / 'scripts/check_prodigal_fasttree_windows.py')
common = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(common)
common.PACK_IDS = ('kalign',)
common.VERSIONS = {'kalign': '1.0.0'}
common.OPERATIONS = {'kalign': {'align-nucleotide', 'align-protein'}}
common.FROZEN_GATE_PATHS = {
    'scripts/check_kalign_windows.py', 'scripts/check_kalign_gui.py',
    'scripts/audit_kalign_candidate.py', 'tests/test_kalign_validation.py',
    '.github/workflows/native-kalign-recheck.yml',
}
APPLICATIONS = common.APPLICATIONS
FASTTREE = {'id': 'fasttree', 'version': '1.0.0',
            'sha256': '4525aa8001b7b190eecbee5a164bb9586ce9f78d8672635df25ae4e462165c20',
            'manifestSha256': '83e45c8c7222bea53e4023861450aa79db0a2f003f7e2a82f6c6362923bcdc55',
            'sourceCommit': 'd175076d57f4c84743cb375369c604085a720204',
            'run': 38387733137, 'artifact': 11806999226,
            'publicationStatus': 'unpublished merged review candidate'}
require, sha, read_json, write_json = common.require, common.sha, common.read_json, common.write_json
file_record, verify_extracted, run_command = common.file_record, common.verify_extracted, common.run_command


def freeze(args):
    sys.path.insert(0, str(SOURCE / 'scripts'))
    from package_split import build_pack
    from validate_pack_release import inspect_release
    source = common.checkout_sources(args.source_commit)
    require(not args.output.exists(), 'Choose a new candidate output directory.')
    args.output.mkdir(parents=True)
    folder = args.kalign_pack.resolve()
    archive = args.output / 'native-workbench-pack-kalign-1.0.0.zip'
    built = build_pack(folder, archive, '0.16.0')
    inspected = inspect_release(archive)
    require((inspected['id'], inspected['version']) == ('kalign', '1.0.0'), 'Unexpected Kalign identity.')
    require(built['sha256'] == inspected['sha256'], 'Static validation changed archive identity.')
    packs = {'kalign': {**file_record(archive), 'id': 'kalign', 'version': '1.0.0',
                        'manifestSha256': inspected['manifestSha256'], 'staticValidation': inspected}}
    entries = [('source/' + name, path) for name, path in source]
    for path in sorted((folder / 'licenses').rglob('*')):
        if path.is_file():
            require(not path.is_symlink(), 'Corresponding source contains a symbolic link.')
            entries.append(('corresponding-sources/kalign/' + path.relative_to(folder / 'licenses').as_posix(), path))
    for number, root in enumerate(args.build_evidence):
        require(root.is_dir(), 'Build evidence directory is absent.')
        for path in sorted(root.rglob('*')):
            if path.is_file():
                require(not path.is_symlink(), 'Build evidence contains a symbolic link.')
                entries.append(('build-evidence/' + str(number + 1) + '/' + path.relative_to(root).as_posix(), path))
    inventory = [{'path': name, 'bytes': path.stat().st_size, 'sha256': sha(path)} for name, path in entries]
    provenance = {'schema': 1, 'kind': 'unpublished-kalign-candidate',
                  'sourceCommit': args.source_commit,
                  'sourceTree': subprocess.check_output(['git', 'rev-parse', 'HEAD^{tree}'], cwd=SOURCE, text=True).strip(),
                  'createdUtc': datetime.now(timezone.utc).isoformat(), 'buildHost': platform.platform(),
                  'python': sys.version, 'packs': packs, 'applications': APPLICATIONS,
                  'integrationDependency': FASTTREE, 'nativeWindowsExecuted': False, 'published': False,
                  'limits': ['Build-time source/static evidence only. Separate native reports must bind these exact archive hashes.',
                             'Application binaries and published catalogues are unchanged.']}
    companion = args.output / 'native-workbench-kalign-1.0.0-source-evidence.zip'
    common.zip_files(companion, entries, {'SOURCE-INVENTORY.json': {'schema': 1, 'sourceCommit': args.source_commit, 'files': inventory},
                                        'BUILD-PROVENANCE.json': provenance})
    provenance['sourceCompanion'] = file_record(companion)
    write_json(args.output / 'BUILD-PROVENANCE.json', provenance)
    (args.output / 'SHA256SUMS.txt').write_text('\n'.join(row['sha256'] + '  ' + row['file']
        for row in [packs['kalign'], provenance['sourceCompanion']]) + '\n', encoding='ascii')
    return provenance


def installed_inventory(folder):
    return {path.relative_to(folder).as_posix(): sha(path) for path in folder.rglob('*') if path.is_file()}


def archive_inventory(archive):
    with zipfile.ZipFile(archive) as zipped:
        envelope = json.loads(zipped.read('workbench-pack.json'))
        return {row['path']: row['sha256'] for row in envelope['files']}


def fasttree_graph_checks(root, evidence, report):
    """Execute both real typed Kalign-to-FastTree graphs on synthetic homologs."""
    from catalog import load_catalog
    from engine import pin_for
    from check_references_windows import PrivateHost
    catalog = load_catalog(root)
    dependency = next(row for row in catalog['packs'] if row['id'] == 'fasttree')
    require(dependency['version'] == FASTTREE['version'], 'Unexpected FastTree dependency version.')
    fasttree_folder = root / dependency['folder']
    truth = read_json(fasttree_folder / 'fixtures/truth.json')
    spec = importlib.util.spec_from_file_location('kalign_fasttree_independent_oracle', SOURCE / 'tests/test_fasttree_pack.py')
    oracle = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(oracle)
    output = evidence / 'analysis-results'
    host = PrivateHost(root, evidence, 'kalign-chain-host', offline=True)
    report['kalignFasttreeGraphChains'] = []
    try:
        require(host.call('init')['app_version'] == report['applicationVersion'], 'Wrong application process.')
        for datatype, model in (('nucleotide', 'GTR'), ('protein', 'LG')):
            aligner = catalog['tools']['kalign/align-' + datatype]
            inference = catalog['tools']['fasttree/infer-' + datatype]
            require(inference['manifestSha256'] == FASTTREE['manifestSha256'], 'FastTree manifest changed.')
            source = fasttree_folder / ('fixtures/' + datatype + '.afa')
            chain = {'schema': 1, 'name': 'Kalign to FastTree ' + datatype, 'nextNode': 3, 'nextSource': 2,
                     'sources': [{'id': 'input-1', 'type': 'fasta-' + datatype,
                                  'label': 'Synthetic homologous ' + datatype + ' sequences',
                                  'files': {'sequences': str(source)}}],
                     'nodes': [{'id': 'step-1', 'tool': aligner['id'], 'pin': pin_for(aligner),
                                'params': {}, 'inputs': {'sequences': ['input-1']}},
                               {'id': 'step-2', 'tool': inference['id'], 'pin': pin_for(inference),
                                'params': {'model': model, 'rates': 'cat', 'support': 'sh', 'seed': 42},
                                'inputs': {'alignment': ['step-1::aligned']}}]}
            require(host.call('review', {'graph': chain})['valid'], 'Kalign output does not satisfy FastTree MSA contract.')
            record = common.completed(host, 'run', {'graph': chain, 'output_folder': str(output)})
            folder = Path(record['folder'])
            run = read_json(folder / 'run.json')
            aligned = Path(run['outputs']['step-1::aligned']['files']['aligned'])
            tree = Path(run['outputs']['step-2::tree']['files']['tree'])
            require({key: value.replace('-', '') for key, value in oracle.fasta(aligned).items()} == oracle.fasta(source),
                    'Kalign graph changed homologous fixture residues.')
            leaves, pairs, _, _ = oracle.newick(tree.read_text())
            require(sorted(leaves) == sorted(truth['taxa']) and pairs == {frozenset(pair) for pair in truth['unrootedPairs']},
                    'Kalign-to-FastTree graph lost independently constructed taxa/topology truth.')
            write_json(evidence / ('kalign-fasttree-' + datatype + '-graph.json'), chain)
            report['kalignFasttreeGraphChains'].append({'datatype': datatype,
                'pins': [pin_for(aligner), pin_for(inference)], 'alignmentSha256': sha(aligned), 'treeSha256': sha(tree),
                'runSha256': sha(folder / 'run.json'), 'planSha256': sha(folder / 'plan.json'),
                'residuesPreserved': True, 'knownTaxaAndUnrootedPairs': True})
            report['checks'].append('Kalign ' + datatype + ' output feeds the immutable FastTree candidate through the real typed graph; residues, taxa and known unrooted pairs agree.')
        record = common.completed(host, 'check', {'output_folder': str(output)})
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
    report = {'schema': 1, 'kind': 'native-kalign-candidate', 'success': False,
              'candidateSourceCommit': candidate_commit, 'gateSourceCommit': args.source_commit,
              'applicationVersion': args.app_version, 'applicationSourceCommit': APPLICATIONS[args.app_version]['sourceCommit'],
              'applicationArchive': file_record(args.app_archive), 'mode': args.mode,
              'nativeWindowsHost': True, 'nativeWindowsExecuted': False, 'python': sys.version,
              'platform': platform.platform(), 'checks': [], 'captures': [],
              'limitations': ['Synthetic bounded fixtures only; no representative-PC or large-data performance acceptance.',
                             'No release, catalogue publication, signing, institutional deployment or updater validation.',
                             'Offline private host denies Python socket calls; not operating-system network isolation.',
                             'FastTree integration uses an immutable unpublished merged candidate, not a published release.']}
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
        archive = args.candidate / frozen['packs']['kalign']['file']
        run_command([python, '-I', '-B', SOURCE / 'scripts/check_pack_release_windows.py', '--app-root', root,
                     '--archive', archive, '--report', evidence / 'kalign-installation.json'], evidence / 'kalign-installation.log')
        result = read_json(evidence / 'kalign-installation.json')
        require(result['success'] and result['nativeWindowsExecuted'] and result['duplicateVersionRejected'], 'Native import/check did not fully execute.')
        report['nativeWindowsExecuted'] = True
        report['checks'].append('kalign: exact ZIP native import, declared scientific checks and duplicate-version rejection.')
        installed = {'kalign': root / 'packs/kalign-1.0.0'}
        expected = {'kalign': archive_inventory(archive)}
        if args.mode == 'science':
            run_command([python, '-I', '-B', SOURCE / 'tests/test_kalign_pack.py', '--pack', installed['kalign'],
                         '--report', evidence / 'kalign-regressions.json'], evidence / 'kalign-regressions.log')
            regression = read_json(evidence / 'kalign-regressions.json')
            require(regression.get('success') and regression.get('nativeWindowsExecuted') and
                    regression.get('testsRun', 0) > 0 and not regression.get('skipped') and regression.get('executions'),
                    'Selected native scientific regressions must execute with no skips.')
            report['checks'].append('kalign: exact installed scientific and failure regressions.')
            require(args.fasttree_archive and sha(args.fasttree_archive) == FASTTREE['sha256'], 'Science requires the exact immutable FastTree candidate archive.')
            from service import Workbench
            from pack_manager import PackManager
            app = Workbench(root)
            try:
                dependency = PackManager(root, app._install_pack_folder).import_archive(args.fasttree_archive.resolve())
                require((dependency['packId'], dependency['packVersion']) == ('fasttree', '1.0.0'), 'Unexpected native FastTree dependency.')
                report['fasttreeNativeImport'] = dependency
                report['fasttreeDependency'] = {**FASTTREE, **file_record(args.fasttree_archive)}
            finally:
                app.shutdown()
            installed['fasttree'] = root / 'packs/fasttree-1.0.0'
            expected['fasttree'] = archive_inventory(args.fasttree_archive)
        for identity, folder in installed.items():
            require(installed_inventory(folder) == expected[identity], 'Installed pack differs from exact archive: ' + identity)
        common.graph_checks(root, evidence, report, starter=False)
        if args.mode == 'science':
            fasttree_graph_checks(root, evidence, report)
        else:
            from check_kalign_gui import run_gui
            run_gui(root, evidence, report)
        for identity, folder in installed.items():
            require(installed_inventory(folder) == expected[identity], 'Installed pack changed during graph/GUI checks: ' + identity)
        report['coreFilesVerifiedAfter'] = verify_extracted(args.app_archive, root)
        report['checks'].append('Pinned application and installed pack/dependency bytes remain unchanged after execution.')
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
    create.add_argument('--kalign-pack', type=Path, required=True)
    create.add_argument('--output', type=Path, required=True)
    create.add_argument('--build-evidence', type=Path, action='append', default=[])
    create.add_argument('--source-commit', required=True)
    check = commands.add_parser('native')
    check.add_argument('--candidate', type=Path, required=True)
    check.add_argument('--app-root', type=Path, required=True)
    check.add_argument('--app-archive', type=Path, required=True)
    check.add_argument('--app-version', choices=APPLICATIONS, required=True)
    check.add_argument('--mode', choices=('science', 'gui'), required=True)
    check.add_argument('--source-commit', required=True, help='Actual gate checkout commit.')
    check.add_argument('--candidate-source-commit', help='Frozen pack source; defaults to the gate commit.')
    check.add_argument('--report', type=Path, required=True)
    check.add_argument('--fasttree-archive', type=Path)
    args = parser.parse_args(argv)
    report = freeze(args) if args.command == 'freeze' else native(args)
    print(json.dumps({'success': report.get('success', True), 'command': args.command,
                      'checks': len(report.get('checks', [])), 'sourceCommit': args.source_commit}))
    return 0 if report.get('success', True) else 1


if __name__ == '__main__':
    raise SystemExit(main())
