#!/usr/bin/env python3
"""Freeze and validate unpublished Prodigal/FastTree packs without rebuilding core.

The freeze command binds installable ZIPs, all tracked recipe sources and actual
build evidence. The native command uses only modules in the separately pinned
application for imports, graph execution and results; checkout modules are gate
helpers, never replacement application code.
"""
from __future__ import annotations

import argparse
import copy
from datetime import datetime, timezone
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path, PurePosixPath
import platform
import re
import subprocess
import sys
import traceback
import tarfile
import zipfile

sys.dont_write_bytecode = True
SOURCE = Path(__file__).resolve().parents[1]
PACK_IDS = ('prodigal', 'fasttree')
VERSIONS = {identity: '1.0.0' for identity in PACK_IDS}
APPLICATIONS = {
    '0.16.0': {'sha256': 'f96e03e43cac92ba8ca9a0a3807eb671f9924d5e624cadbba94d1a5ca1309073',
               'sourceCommit': 'e855dc4396e0c16ae35f4e840eb9cc734adb4441'},
    '0.16.1': {'sha256': '28f1362287991621dde030da54eb444846142c0243be6b9d86c4b4f1bf99dd47',
               'sourceCommit': 'ff13db729a6215e9fe5dfa4a4efdb9c769880287'},
}
OPERATIONS = {'prodigal': {'predict-genome', 'predict-metagenome'},
              'fasttree': {'infer-nucleotide', 'infer-protein'}}
FROZEN_GATE_PATHS = {
    'scripts/check_prodigal_fasttree_windows.py', 'scripts/check_prodigal_fasttree_gui.py',
    'scripts/audit_prodigal_fasttree_candidate.py', 'tests/test_prodigal_fasttree_validation.py',
    '.github/workflows/native-prodigal-fasttree-recheck.yml',
}


def allowed_gate_change(name):
    return name in FROZEN_GATE_PATHS or name.startswith(('knowledge/', 'docs/evidence/'))


def frozen_source_changes(candidate_commit, gate_commit):
    require(all(re.fullmatch(r'[a-f0-9]{40}', value) for value in (candidate_commit, gate_commit)),
            'Frozen recheck requires exact candidate and gate commits.')
    require(subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=SOURCE, text=True).strip() == gate_commit,
            'Gate checkout does not match its recorded commit.')
    names = subprocess.check_output(['git', 'diff', '--name-only', '-z', candidate_commit, gate_commit], cwd=SOURCE).decode().split('\0')
    changed = sorted(filter(None, names))
    require(all(allowed_gate_change(name) for name in changed),
            'Frozen candidate production or recipe sources changed: ' + ', '.join(name for name in changed if not allowed_gate_change(name)))
    return changed


def git_source_files(commit):
    archive = subprocess.check_output(['git', 'archive', '--format=tar', commit], cwd=SOURCE)
    with tarfile.open(fileobj=io.BytesIO(archive), mode='r:') as source:
        require(all(item.isfile() or item.isdir() for item in source.getmembers()), 'Git source contains unsupported file types.')
        return {item.name: source.extractfile(item).read() for item in source.getmembers() if item.isfile()}



def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')


def file_record(path):
    path = Path(path)
    return {'file': path.name, 'bytes': path.stat().st_size, 'sha256': sha(path)}


def safe_member(name):
    parts = PurePosixPath(name).parts
    require(name and not name.startswith('/') and '\\' not in name and ':' not in name and
            all(part not in ('', '.', '..') for part in name.split('/')), 'Unsafe archive member: ' + name)
    return parts


def verify_file(path, expected):
    require(path.is_file() and not path.is_symlink() and path.stat().st_size == expected['bytes'] and
            sha(path) == expected['sha256'], 'Frozen artifact differs: ' + path.name)


def verify_extracted(archive, root):
    """Bind every original file to the immutable app archive, allowing user data."""
    count = 0
    with zipfile.ZipFile(archive) as zipped:
        for item in zipped.infolist():
            if item.is_dir():
                continue
            parts = safe_member(item.filename)
            require(parts[0] == 'native-workbench', 'Unexpected application ZIP root.')
            path = root.joinpath(*parts[1:])
            require(path.is_file() and not path.is_symlink() and path.stat().st_size == item.file_size and
                    sha(path) == hashlib.sha256(zipped.read(item)).hexdigest(),
                    'Application file changed: ' + item.filename)
            count += 1
    require(count > 0, 'Empty application archive.')
    return count


def checkout_sources(commit):
    require(re.fullmatch(r'[a-f0-9]{40}', commit), 'Expected an exact source commit.')
    actual = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=SOURCE, text=True).strip()
    require(actual == commit, 'Source checkout is not the requested commit.')
    names = subprocess.check_output(['git', 'ls-files', '-z'], cwd=SOURCE).decode().split('\0')
    result = []
    for name in sorted(filter(None, names)):
        safe_member(name)
        path = SOURCE / name
        original = subprocess.check_output(['git', 'show', commit + ':' + name], cwd=SOURCE)
        require(path.is_file() and not path.is_symlink() and path.read_bytes() == original,
                'Tracked source differs from commit: ' + name)
        result.append((name, path))
    return result


def zip_files(destination, entries, documents):
    names = [name for name, _ in entries] + list(documents)
    require(len(names) == len(set(name.casefold() for name in names)), 'Companion member collision.')
    with zipfile.ZipFile(destination, 'x', compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for name, path in entries:
            safe_member(name)
            archive.write(path, name)
        for name, value in documents.items():
            safe_member(name)
            archive.writestr(name, json.dumps(value, indent=2) + '\n')


def freeze(args):
    sys.path.insert(0, str(SOURCE / 'scripts'))
    from package_split import build_pack
    from validate_pack_release import inspect_release
    source = checkout_sources(args.source_commit)
    require(not args.output.exists(), 'Choose a new candidate output directory.')
    args.output.mkdir(parents=True)
    packs, entries = {}, [('source/' + name, path) for name, path in source]
    for identity in PACK_IDS:
        folder = getattr(args, identity + '_pack').resolve()
        archive = args.output / ('native-workbench-pack-' + identity + '-' + VERSIONS[identity] + '.zip')
        built = build_pack(folder, archive, '0.16.0')
        inspected = inspect_release(archive)
        require((inspected['id'], inspected['version']) == (identity, VERSIONS[identity]), 'Unexpected pack identity.')
        require(built['sha256'] == inspected['sha256'], 'Pack static audit changed archive identity.')
        packs[identity] = {**file_record(archive), 'id': identity, 'version': VERSIONS[identity],
                           'manifestSha256': inspected['manifestSha256'], 'staticValidation': inspected}
        for path in sorted((folder / 'licenses').rglob('*')):
            if path.is_file():
                entries.append(('corresponding-sources/' + identity + '/' + path.relative_to(folder / 'licenses').as_posix(), path))
    for number, root in enumerate(args.build_evidence):
        require(root.is_dir(), 'Build evidence directory is absent.')
        for path in sorted(root.rglob('*')):
            if path.is_file():
                require(not path.is_symlink(), 'Build evidence contains symbolic links.')
                entries.append(('build-evidence/' + str(number + 1) + '/' + path.relative_to(root).as_posix(), path))
    inventory = [{'path': name, 'bytes': path.stat().st_size, 'sha256': sha(path)} for name, path in entries]
    provenance = {'schema': 1, 'kind': 'unpublished-prodigal-fasttree-candidate',
                  'sourceCommit': args.source_commit,
                  'sourceTree': subprocess.check_output(['git', 'rev-parse', 'HEAD^{tree}'], cwd=SOURCE, text=True).strip(),
                  'createdUtc': datetime.now(timezone.utc).isoformat(), 'buildHost': platform.platform(),
                  'python': sys.version, 'packs': packs, 'applications': APPLICATIONS,
                  'nativeWindowsExecuted': False, 'published': False,
                  'limits': ['Build-time source/static evidence only. Native Windows reports are separate and must bind these exact archive hashes.',
                             'Application binaries and published catalogues are unchanged.']}
    companion = args.output / 'native-workbench-prodigal-fasttree-1.0.0-source-evidence.zip'
    zip_files(companion, entries, {'SOURCE-INVENTORY.json': {'schema': 1, 'sourceCommit': args.source_commit, 'files': inventory},
                                  'BUILD-PROVENANCE.json': provenance})
    provenance['sourceCompanion'] = file_record(companion)
    write_json(args.output / 'BUILD-PROVENANCE.json', provenance)
    lines = [item['sha256'] + '  ' + item['file'] for item in [*packs.values(), provenance['sourceCompanion']]]
    (args.output / 'SHA256SUMS.txt').write_text('\n'.join(lines) + '\n', encoding='ascii')
    return provenance


def verify_candidate(folder, commit, gate_commit=None):
    gate_commit = gate_commit or commit
    changes = frozen_source_changes(commit, gate_commit) if commit != gate_commit else []
    original_sources = git_source_files(commit) if commit != gate_commit else None
    record = read_json(folder / 'BUILD-PROVENANCE.json')
    require(record['sourceCommit'] == commit and set(record['packs']) == set(PACK_IDS), 'Wrong frozen candidate source/packs.')
    for identity, item in record['packs'].items():
        require((item['id'], item['version']) == (identity, VERSIONS[identity]), 'Frozen pack identity differs.')
        verify_file(folder / item['file'], item)
    companion = folder / record['sourceCompanion']['file']
    verify_file(companion, record['sourceCompanion'])
    with zipfile.ZipFile(companion) as archive:
        inventory = json.loads(archive.read('SOURCE-INVENTORY.json'))
        require(inventory['sourceCommit'] == commit, 'Companion commit differs.')
        names = [row['path'] for row in inventory['files']]
        require(len(names) == len(set(x.casefold() for x in names)) and
                set(archive.namelist()) == set(names) | {'SOURCE-INVENTORY.json', 'BUILD-PROVENANCE.json'},
                'Source companion inventory differs.')
        if original_sources is not None:
            require({name[7:] for name in names if name.startswith('source/')} == set(original_sources),
                    'Frozen companion does not contain the complete original Git source inventory.')
        for row in inventory['files']:
            safe_member(row['path'])
            data = archive.read(row['path'])
            require(len(data) == row['bytes'] and hashlib.sha256(data).hexdigest() == row['sha256'], 'Companion member differs.')
            if row['path'].startswith('source/'):
                relative = row['path'][7:]
                local = SOURCE / relative
                if original_sources is not None:
                    require(data == original_sources[relative], 'Frozen source differs from original Git commit: ' + relative)
                if relative not in changes:
                    require(local.is_file() and sha(local) == row['sha256'], 'Companion production source differs from gate checkout: ' + relative)
        # Bind the validator revisions themselves, including newly added files,
        # to the separate gate commit rather than silently treating them as pack
        # build source. All other archived files already match the checkout.
        if changes:
            current_sources = git_source_files(gate_commit)
            for relative in changes:
                local = SOURCE / relative
                require((local.is_file() and local.read_bytes() == current_sources[relative]) if relative in current_sources else not local.exists(),
                        'Validator working file differs from gate commit: ' + relative)
    return record


def run_command(command, log, timeout=600):
    result = subprocess.run([str(value) for value in command], stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            encoding='utf-8', errors='replace', timeout=timeout)
    log.write_text(result.stdout, encoding='utf-8')
    require(result.returncode == 0, 'Command failed; see ' + log.name + ': ' + result.stdout[-2000:])


def fixture_graph(root, catalog, identity):
    """Create an ordinary exact-pin graph from the first declared positive case."""
    from catalog import load_pack, resolve_tool
    from engine import pin_for
    item = next(item for item in catalog['packs'] if item['id'] == identity and item['version'] == VERSIONS[identity])
    folder = root / item['folder']
    pack = load_pack(folder / 'pack.ini')
    case = read_json(folder / pack['assets']['workbench-checks']['path'])['checks'][0]
    tool = resolve_tool(catalog, identity + '/' + case['workflow'])
    sources, inputs = [], {}
    ports = {port['id']: port for port in tool['ports']}
    for port_id, members in case['inputs'].items():
        inputs[port_id] = []
        for member in members:
            source_id = 'input-' + str(len(sources) + 1)
            files = {key: str(folder / pack['assets'][asset]['path']) for key, asset in member.items()}
            sources.append({'id': source_id, 'label': ports[port_id]['label'], 'type': ports[port_id]['type'], 'files': files})
            inputs[port_id].append(source_id)
    return {'schema': 1, 'name': 'Pack candidate ' + identity,
            'nodes': [{'id': 'step-1', 'tool': tool['id'], 'pin': pin_for(tool), 'params': case.get('params', {}), 'inputs': inputs}],
            'sources': sources, 'nextNode': 2, 'nextSource': len(sources) + 1}


def completed(host, method, request):
    from check_batch_windows import until
    started = host.call(method, request)
    def finished():
        item = host.call('run/get', {'run_id': started['run_id']})
        return item if item['status'] not in {'preparing', 'running', 'cancelling'} else None
    result = until('Native candidate execution timed out.', finished, 300)
    require(result['status'] == 'completed' and result.get('success'), 'Native candidate execution failed: ' + json.dumps(result))
    return result


def graph_checks(root, evidence, report, *, starter=False):
    from catalog import load_catalog
    from check_references_windows import PrivateHost
    catalog = load_catalog(root)
    for identity in PACK_IDS:
        require({key.split('/', 1)[1] for key, value in catalog['tools'].items() if value.get('packId') == identity} == OPERATIONS[identity],
                'Pack operation catalogue differs: ' + identity)
    host = PrivateHost(root, evidence, 'candidate-host', offline=True)
    output = evidence / 'analysis-results'
    output.mkdir()
    report['recordedRuns'] = {}
    report['guiRunTools'] = {}
    try:
        require(host.call('init')['app_version'] == report['applicationVersion'], 'Wrong application process.')
        for identity in PACK_IDS:
            graph = fixture_graph(root, catalog, identity)
            report['guiRunTools'][identity] = graph['nodes'][0]['tool']
            require(host.call('review', {'graph': graph})['valid'], 'Exact-pin graph is not ready.')
            wrong = copy.deepcopy(graph)
            wrong['sources'][0]['type'] = 'bam-rna'
            require(not host.call('review', {'graph': wrong})['valid'], 'Incompatible RNA BAM type accepted by sequence operation.')
            stale = copy.deepcopy(graph)
            stale['nodes'][0]['pin']['manifestSha256'] = '0' * 64
            require(not host.call('review', {'graph': stale})['valid'], 'Stale saved manifest pin accepted.')
            record = completed(host, 'run', {'graph': graph, 'output_folder': str(output)})
            folder = Path(record['folder'])
            frozen = read_json(folder / 'plan.json')
            require(frozen['graph']['nodes'][0]['pin'] == graph['nodes'][0]['pin'], 'Run changed the exact selected pack pin.')
            for name in ('run.json', 'methods-completed.txt', 'workflow.cwl'):
                require((folder / name).is_file(), 'Missing run provenance: ' + name)
            summary = host.call('results/summary', {'id': record['run_id']})
            require(not summary.get('failures'), 'Successful result reports failure.')
            found = host.call('results/search', {'query': 'Pack candidate ' + identity})
            require({row['run_id'] for row in found['runs']} == {record['run_id']}, 'Result search did not isolate the pack run.')
            write_json(evidence / (identity + '-result-summary.json'), summary)
            write_json(evidence / (identity + '-graph.json'), graph)
            report['recordedRuns'][identity] = {'runId': record['run_id'], 'name': graph['name'], 'planSha256': sha(folder / 'plan.json'),
                                              'runSha256': sha(folder / 'run.json'), 'pin': graph['nodes'][0]['pin']}
            report['checks'].append(identity + ': exact-pin normal graph execution, incompatible input/stale pin rejection, methods/CWL and searchable results.')
        if starter:
            from engine import pin_for
            # The two new packs do not invent a homology relation. Only the
            # explicit synthetic homolog fixtures pass through the real saved
            # MUSCLE MSA output contract into FastTree.
            spec = importlib.util.spec_from_file_location('fasttree_independent_gate_oracle', SOURCE / 'tests/test_fasttree_pack.py')
            oracle = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(oracle)
            fasttree_folder = root / next(row['folder'] for row in catalog['packs'] if row['id'] == 'fasttree')
            truth = read_json(fasttree_folder / 'fixtures/truth.json')
            report['muscleGraphChains'] = []
            for datatype, model in (('nucleotide', 'GTR'), ('protein', 'LG')):
                aligner = catalog['tools']['muscle/super5-' + datatype]
                inference = catalog['tools']['fasttree/infer-' + datatype]
                chain = {'schema': 1, 'name': 'MUSCLE to FastTree ' + datatype, 'nextNode': 3, 'nextSource': 2,
                         'sources': [{'id': 'input-1', 'type': 'fasta-' + datatype, 'label': 'Synthetic homologous ' + datatype + ' sequences',
                                      'files': {'sequences': str(fasttree_folder / ('fixtures/' + datatype + '.afa'))}}],
                         'nodes': [{'id': 'step-1', 'tool': aligner['id'], 'pin': pin_for(aligner),
                                    'params': {'threads': 1, 'perturb': 0, 'permutation': 'none'}, 'inputs': {'sequences': ['input-1']}},
                                   {'id': 'step-2', 'tool': inference['id'], 'pin': pin_for(inference),
                                    'params': {'model': model, 'rates': 'cat', 'support': 'sh', 'seed': 42},
                                    'inputs': {'alignment': ['step-1::aligned']}}]}
                require(host.call('review', {'graph': chain})['valid'], 'Published MUSCLE output does not satisfy FastTree MSA contract.')
                record = completed(host, 'run', {'graph': chain, 'output_folder': str(output)})
                run = read_json(Path(record['folder']) / 'run.json')
                aligned = Path(run['outputs']['step-1::aligned']['files']['aligned'])
                tree = Path(run['outputs']['step-2::tree']['files']['tree'])
                source = fasttree_folder / ('fixtures/' + datatype + '.afa')
                require({key: value.replace('-', '') for key, value in oracle.fasta(aligned).items()} == oracle.fasta(source),
                        'MUSCLE graph changed homologous fixture residues.')
                leaves, pairs, _, _ = oracle.newick(tree.read_text())
                require(sorted(leaves) == sorted(truth['taxa']) and pairs == {frozenset(pair) for pair in truth['unrootedPairs']},
                        'Real MUSCLE-to-FastTree graph lost independently constructed taxa/topology truth.')
                write_json(evidence / ('muscle-fasttree-' + datatype + '-graph.json'), chain)
                report['muscleGraphChains'].append({'datatype': datatype, 'pins': [pin_for(aligner), pin_for(inference)],
                                                    'alignmentSha256': sha(aligned), 'treeSha256': sha(tree),
                                                    'runSha256': sha(Path(record['folder']) / 'run.json'),
                                                    'residuesPreserved': True, 'knownTaxaAndUnrootedPairs': True})
                report['checks'].append('Published MUSCLE Super5 ' + datatype + ' output feeds FastTree through the real typed Workbench graph; residues, taxa and known unrooted pairs agree.')
            record = completed(host, 'check', {'output_folder': str(output)})
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
    report = {'schema': 1, 'kind': 'native-prodigal-fasttree-candidate', 'success': False,
              'candidateSourceCommit': candidate_commit, 'gateSourceCommit': args.source_commit, 'applicationVersion': args.app_version,
              'applicationSourceCommit': APPLICATIONS[args.app_version]['sourceCommit'],
              'applicationArchive': file_record(args.app_archive), 'mode': args.mode,
              'nativeWindowsHost': True, 'nativeWindowsExecuted': False,
              'python': sys.version, 'platform': platform.platform(), 'checks': [], 'captures': [],
              'limitations': ['Synthetic bounded fixtures only; no representative-PC or large-data performance acceptance.',
                             'No release, catalogue publication, signing, institutional deployment or updater validation.',
                             'Offline private host denies Python socket calls; not operating-system network isolation.']}
    try:
        require(sha(args.app_archive) == APPLICATIONS[args.app_version]['sha256'], 'Unexpected application archive.')
        report['coreFilesVerifiedBefore'] = verify_extracted(args.app_archive, root)
        frozen = verify_candidate(args.candidate, candidate_commit, args.source_commit)
        report['frozenCandidateRecheck'] = candidate_commit != args.source_commit
        report['gateSourceDifferences'] = frozen_source_changes(candidate_commit, args.source_commit) if candidate_commit != args.source_commit else []
        report['packs'] = frozen['packs']
        report['sourceCompanion'] = frozen['sourceCompanion']
        sys.path.insert(0, str(root / 'workspace'))
        sys.path.insert(1, str(SOURCE / 'scripts'))
        python = root / 'runtime/python/python.exe'
        installed = {}
        for identity in PACK_IDS:
            archive = args.candidate / frozen['packs'][identity]['file']
            run_command([python, '-I', '-B', SOURCE / 'scripts/check_pack_release_windows.py', '--app-root', root,
                         '--archive', archive, '--report', evidence / (identity + '-installation.json')],
                        evidence / (identity + '-installation.log'))
            result = read_json(evidence / (identity + '-installation.json'))
            require(result['success'] and result['nativeWindowsExecuted'] and result['duplicateVersionRejected'], 'Native import/check did not fully execute.')
            report['nativeWindowsExecuted'] = True
            installed[identity] = root / 'packs' / (identity + '-' + VERSIONS[identity])
            report['checks'].append(identity + ': exact ZIP native import, declared scientific checks and duplicate-version rejection.')
            if args.mode == 'science':
                command = [python, '-I', '-B', SOURCE / ('tests/test_' + identity + '_pack.py'),
                           '--pack', installed[identity], '--report', evidence / (identity + '-regressions.json')]
                if identity == 'fasttree':
                    require(args.muscle_archive and sha(args.muscle_archive) ==
                            'c07d3e398f48df683926c0970ef77c3b7d2bdab6426b80c80186f2360ed25258',
                            'Science gate requires exact published MUSCLE 0.5.2 archive.')
                    command += ['--muscle-archive', args.muscle_archive]
                    report['muscleDependency'] = file_record(args.muscle_archive)
                run_command(command, evidence / (identity + '-regressions.log'))
                regression = read_json(evidence / (identity + '-regressions.json'))
                require(regression.get('success') and regression.get('nativeWindowsExecuted') and
                        regression.get('testsRun', 0) > 0 and not regression.get('skipped') and regression.get('executions'),
                        'Selected native scientific regressions must execute with no skips: ' + identity)
                report['checks'].append(identity + ': exact installed scientific and failure regressions.')
        if args.mode == 'science':
            from service import Workbench
            from pack_manager import PackManager
            app = Workbench(root)
            try:
                manager = PackManager(root, app._install_pack_folder)
                dependency = manager.import_archive(args.muscle_archive.resolve())
                require((dependency['packId'], dependency['packVersion']) == ('muscle', '0.5.2'), 'Unexpected native MUSCLE dependency.')
                report['muscleNativeImport'] = dependency
            finally:
                app.shutdown()
        before = {}
        for identity in PACK_IDS:
            with zipfile.ZipFile(args.candidate / frozen['packs'][identity]['file']) as archive:
                envelope = json.loads(archive.read('workbench-pack.json'))
                before[identity] = {row['path']: row['sha256'] for row in envelope['files']}
            require({path.relative_to(installed[identity]).as_posix(): sha(path)
                     for path in installed[identity].rglob('*') if path.is_file()} == before[identity],
                    'Installed pack differs from frozen archive after import/regressions: ' + identity)
        graph_checks(root, evidence, report, starter=args.mode == 'science')
        if args.mode == 'gui':
            from check_prodigal_fasttree_gui import run_gui
            run_gui(root, evidence, report)
        for identity, folder in installed.items():
            after = {path.relative_to(folder).as_posix(): sha(path) for path in folder.rglob('*') if path.is_file()}
            require(after == before[identity], 'Installed pack files changed during graph/GUI checks: ' + identity)
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
    create.add_argument('--prodigal-pack', type=Path, required=True)
    create.add_argument('--fasttree-pack', type=Path, required=True)
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
    check.add_argument('--muscle-archive', type=Path)
    args = parser.parse_args(argv)
    report = freeze(args) if args.command == 'freeze' else native(args)
    print(json.dumps({'success': report.get('success', True), 'command': args.command,
                      'checks': len(report.get('checks', [])), 'sourceCommit': args.source_commit}))
    return 0 if report.get('success', True) else 1


if __name__ == '__main__':
    raise SystemExit(main())
