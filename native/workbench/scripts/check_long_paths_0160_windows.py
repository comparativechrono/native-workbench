#!/usr/bin/env python3
"""Check 0.16.0 scientific execution with Windows long-path opt-in off.

Release-specific copy of check_long_paths_windows.py. Preserve every original
scientific assertion, retain additional-pack diagnostics, and independently check
the pinned alignment self-check's completed graph and known-answer SAM. An
additional-pack failure is still a failed gate.

The workflow changes only a disposable CI runner's policy before starting this
fresh private interpreter. This gate does not change policy, patch application
binaries, or require a user to enable Windows long paths.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import ntpath
import os
from pathlib import Path
import platform
import shutil
import sys
import time
import traceback
import winreg

sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_references_windows import PrivateHost, require, write_json


def io_path(path):
    value = ntpath.abspath(os.fspath(path))
    if value.startswith('\\\\?\\'):
        return Path(value)
    return Path('\\\\?\\UNC\\' + value[2:] if value.startswith('\\\\') else '\\\\?\\' + value)


def digest(path):
    h = hashlib.sha256()
    with io_path(path).open('rb') as handle:
        for data in iter(lambda: handle.read(1024*1024), b''):
            h.update(data)
    return h.hexdigest()


def read_json(path):
    return json.loads(io_path(path).read_text(encoding='utf-8'))


def policy():
    with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r'SYSTEM\CurrentControlSet\Control\FileSystem') as key:
        return winreg.QueryValueEx(key, 'LongPathsEnabled')[0]



def retain_additional_pack_evidence(run, evidence, report):
    """Retain bounded synthetic diagnostics before an overall failure assertion."""
    result = {"checks": [], "files": [], "errors": [], "bytes": 0}
    report["additionalPackDiagnostics"] = result
    base = run.get("folder")
    if not isinstance(base, str) or not ntpath.isabs(base):
        return
    allowed_root = ntpath.normcase(ntpath.abspath(base))
    checks = run.get("pack_checks", {}).get("checks", [])
    for index, check in enumerate(checks[:32]):
        result["checks"].append({key: check[key] for key in ("id", "status", "message", "folder") if key in check})
        folder = check.get("folder")
        if not isinstance(folder, str) or not ntpath.isabs(folder):
            continue
        canonical = ntpath.normcase(ntpath.abspath(folder))
        if ntpath.commonpath([allowed_root, canonical]) != allowed_root:
            result["errors"].append("Additional check folder is outside the installation-check result.")
            continue
        try:
            for current, directories, names in os.walk(io_path(folder), followlinks=False):
                directories[:] = [name for name in directories if not (Path(current)/name).is_symlink()
                    and not getattr(Path(current)/name, "is_junction", lambda: False)()]
                for name in sorted(names):
                    source = Path(current)/name
                    if source.suffix.lower() not in (".json", ".jsonl", ".log", ".txt", ".sam", ".csv", ".tsv"):
                        continue
                    if source.is_symlink() or getattr(source, "is_junction", lambda: False)():
                        continue
                    size = source.stat().st_size
                    if size > 4*1024*1024 or result["bytes"] + size > 64*1024*1024 or len(result["files"]) >= 200:
                        result["errors"].append("Additional diagnostic file exceeded the bounded retention limit: " + name)
                        continue
                    relative = source.relative_to(io_path(folder))
                    target = evidence/"additional-pack-diagnostics"/str(index)/relative
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(source, target)
                    result["bytes"] += size
                    result["files"].append({"file": str(target.relative_to(evidence)), "bytes": size, "sha256": digest(target)})
                    if name == "run.json":
                        record = read_json(source)
                        if record.get("status") not in ("success", "completed"):
                            result["checks"][-1].setdefault("failureRecords", []).append({
                                "file": str(target.relative_to(evidence)), "status": record.get("status"),
                                "message": record.get("message"), "nodes": [{key: node[key] for key in
                                    ("id", "status", "message", "folder") if key in node} for node in record.get("nodes", [])]})
        except Exception as error:
            result["errors"].append(str(error))


def check_additional_pack_success(run, evidence, report):
    """Verify the exact extra pack operation that exposed the nested-cwd bug."""
    packs = run.get('pack_checks', {})
    require(packs.get('nativeWindowsExecuted') is True and packs.get('success') is True
            and packs.get('passed') == 1 and packs.get('failed') == 0 and not packs.get('cancelled'),
            'The additional native alignment pack check must pass without cancellation or failures.')
    checks = packs.get('checks', [])
    expected_pin = {'packId': 'align', 'packVersion': '0.4.1',
                    'manifestSha256': '7f8f36efbfd6a8255a98eabb06746fbcc5bbdb872f392a65ca3e79a586d04939'}
    require(len(checks) == 1 and checks[0].get('id') == 'align/paired-mapping-known-answer@0.4.1'
            and checks[0].get('status') == 'passed' and checks[0].get('pin') == expected_pin,
            'The additional check must execute the exact pinned align 0.4.1 known-answer operation.')
    require(not report['additionalPackDiagnostics']['errors'],
            'The additional pack diagnostic evidence could not be retained completely.')
    retained = evidence/'additional-pack-diagnostics'/'0'
    graph = read_json(retained/'run.json')
    plan = read_json(retained/'plan.json')
    require(graph.get('status') == 'success' and graph.get('success') is True
            and graph.get('folder') == checks[0]['folder'] and graph.get('planSha256') == plan['sha256'],
            'The retained additional pack graph must bind its completed frozen plan and recorded folder.')
    nodes = graph.get('nodes', [])
    require(len(nodes) == 1 and nodes[0].get('id') == 'step-1' and nodes[0].get('tool') == 'align/paired-end'
            and nodes[0].get('status') == 'success' and nodes[0].get('pin') == expected_pin,
            'The additional pack graph must successfully execute its one pinned alignment step.')
    native_folder = nodes[0]['folder']
    require(ntpath.isabs(native_folder) and not native_folder.startswith('\\\\?\\') and len(native_folder) < 260,
            'The additional native working directory must remain an ordinary absolute path below MAX_PATH.')
    native = read_json(Path(native_folder)/'run.json')
    steps = native.get('steps', [])
    require(native.get('status') == 'success' and [step.get('id') for step in steps] == ['check-pairs', 'align']
            and all(step.get('status') == 'success' and step.get('exit_code') == 0
                    and step.get('working_directory') == native_folder for step in steps),
            'Pair validation and minimap2 must both actually finish in the bounded native working directory.')
    outputs = graph['outputs']
    require(set(outputs) == {'step-1::sam', 'step-1::pair-check'},
            'The additional alignment graph must retain its SAM and paired-read validation outputs.')
    output_files = []
    for product in outputs.values():
        for field, path in product['files'].items():
            require(not path.startswith('\\\\?\\') and io_path(path).is_file()
                    and digest(path) == product['sha256'][field],
                    'An additional pack output failed independent rehashing or changed its ordinary identity.')
            output_files.append({'output': product['id'], 'field': field, 'characters': len(path),
                                 'sha256': product['sha256'][field]})
    sam = outputs['step-1::sam']
    sam_path = sam['files']['sam']
    require(len(sam_path) > 260 and not Path(sam_path).is_file(),
            'The additional known-answer SAM must cross the disabled-policy ordinary I/O boundary.')
    artifact = next((item for item in native.get('artifacts', []) if item.get('id') == 'sam'), {})
    require(artifact.get('checked') is True and artifact.get('path') == sam_path
            and artifact.get('sha256') == sam['sha256']['sam']
            and artifact.get('bytes') == io_path(sam_path).stat().st_size,
            'The additional SAM must match the native bridge artifact identity and byte count.')
    text = io_path(sam_path).read_text(encoding='utf-8')
    rows = [line.split('\t') for line in text.splitlines() if line and not line.startswith('@')]
    require(len(rows) == 202 and all(len(row) >= 11 and int(row[1]) & 1 and int(row[1]) & 2
            and not int(row[1]) & (4 | 256 | 2048) and row[2] == 'starter' for row in rows),
            'The additional known-answer SAM must contain 202 primary mapped proper-pair records on starter.')
    require(any(line.startswith('@SQ\tSN:starter\tLN:3000') for line in text.splitlines()),
            'The additional known-answer SAM lost its 3000-base synthetic reference dictionary.')
    report['additionalAlignment'] = {'checkId': checks[0]['id'], 'pin': expected_pin,
        'graphRecordSha256': digest(retained/'run.json'), 'nativeWorkingDirectoryCharacters': len(native_folder),
        'samCharacters': len(sam_path), 'samSha256': sam['sha256']['sam'],
        'alignmentRecords': len(rows), 'mappedProperPairs': len(rows), 'outputFiles': output_files}
    report['checks'].append('The exact align 0.4.1 additional pack check passes with a native working directory below MAX_PATH; its >260-character SAM independently rehashes and contains 202 primary mapped proper-pair records.')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--app-root', type=Path, required=True)
    parser.add_argument('--output-root', type=Path, required=True)
    parser.add_argument('--report', type=Path, required=True)
    parser.add_argument('--source-commit', required=True)
    parser.add_argument('--asset-sha256', required=True)
    parser.add_argument('--expect-missing-output', action='store_true')
    args = parser.parse_args(argv)
    root, evidence = args.app_root.resolve(), args.report.resolve().parent
    evidence.mkdir(parents=True, exist_ok=True)
    report = {'schema':1, 'success':False, 'sourceCommit':args.source_commit,
              'assetSha256':args.asset_sha256, 'gateSha256':digest(__file__), 'startedUtc':datetime.now(timezone.utc).isoformat(),
              'platform':platform.platform(), 'python':sys.version, 'checks':[], 'skips':[],
              'expectedApplicationFailure':args.expect_missing_output, 'nativeWindowsExecuted':False,
              'scope':'Exact packaged private host, complete starter chain and pinned additional alignment installation check; no GUI claim.'}
    host = None
    try:
        require(os.name == 'nt', 'This gate requires native Windows; unavailable checks cannot pass.')
        require(Path(sys.executable).resolve() == (root/'runtime/python/python.exe').resolve(),
                'Use the exact packaged private interpreter, launched after the policy was disabled.')
        report['longPathsEnabled'] = policy()
        require(report['longPathsEnabled'] == 0, 'This regression requires the runner long-path policy to be disabled.')
        report['appFiles'] = {str(p.relative_to(root)):digest(p) for p in
                              (root/'NativeWorkbench.exe', root/'WorkbenchBridge.exe', root/'runtime/python/python.exe', root/'workspace/engine.py')}
        # 152 characters reproduces the observed threshold without containing
        # any tester path. The nested native outputs exceed MAX_PATH while the
        # ordinary output parent and installation/check records remain below it.
        output = args.output_root.resolve()
        require(len(str(output)) < 130, 'Choose a short synthetic gate output root.')
        output = output / ('synthetic nested results ' + 'x'*(152-len(str(output))-1-len('synthetic nested results ')))
        require(len(str(output)) == 152, 'Synthetic output parent length must be exactly 152.')
        io_path(output).mkdir(parents=True)
        probe = output / ('policy-probe-' + 'p'*110) / 'exists.txt'
        io_path(probe.parent).mkdir()
        io_path(probe).write_text('Synthetic MAX_PATH policy probe.\n', encoding='utf-8')
        report['policyProbe'] = {'characters':len(str(probe)), 'ordinaryIsFile':probe.is_file(),
                                 'extendedIsFile':io_path(probe).is_file()}
        require(not report['policyProbe']['ordinaryIsFile'] and report['policyProbe']['extendedIsFile'],
                'The fresh process did not reproduce the plain-path MAX_PATH boundary.')
        report['checks'].append('Long-path opt-in is disabled and a real >260-character file requires explicit extended I/O.')
        host = PrivateHost(root, evidence, 'long-path-host', offline=True)
        state = host.call('init')
        report['appVersion'] = state.get('app_version')
        started = host.call('check', {'output_folder':str(output)})
        deadline = time.monotonic()+240
        while time.monotonic() < deadline:
            run = host.call('run/get', {'run_id':started['run_id']})
            if run['status'] not in ('preparing','running','cancelling'):
                break
            time.sleep(.1)
        else:
            raise TimeoutError('The full native installation scientific check did not finish.')
        write_json(evidence/'installation-service-result.json', run)
        retain_additional_pack_evidence(run, evidence, report)
        require(run.get('core_checks',{}).get('success') and run['core_checks']['passed']==7,
                'The exact packaged core must pass all 7 integrity checks before the scientific regression.')
        starter = run.get('starter_checks',{})
        require(starter.get('nativeWindowsExecuted') and starter.get('analysisExecuted'),
                'The starter check did not actually execute native scientific tools.')
        require(starter.get('skipped')==0, 'The starter scientific profile must not be skipped.')
        graph_folder = Path(starter['checks'][0]['folder'])
        graph_record = read_json(graph_folder/'run.json')
        write_json(evidence/'scientific-graph-run.json', graph_record)
        report['nativeWindowsExecuted'] = True
        report['applicationCheck'] = {'status':run['status'], 'corePassed':run['core_checks']['passed'],
                                      'starterPassed':starter['passed'], 'starterFailed':starter['failed'],
                                      'starterSkipped':starter['skipped']}
        first = graph_record['nodes'][0]
        require(len(first['folder']) < 260, 'Keep the native process working directory below MAX_PATH to isolate the reported file-boundary regression.')
        report['nativeWorkingDirectoryCharacters'] = len(first['folder'])
        native_record = read_json(Path(first['folder'])/'run.json')
        write_json(evidence/'first-native-run.json', native_record)
        require(native_record.get('status') == 'success', 'The native alignment tool itself failed.')
        sam = next(item for item in native_record['artifacts'] if item['id']=='sam')
        sam_path = Path(sam['path'])
        require(len(str(sam_path)) > 260 and io_path(sam_path).is_file(),
                'The native scientific output did not cross the actual Windows path boundary.')
        require(io_path(sam_path).stat().st_size == sam['bytes'] and digest(sam_path)==sam['sha256'],
                'The native long-path SAM differs from the bridge-verified bytes.')
        shutil.copyfile(io_path(sam_path), evidence/'native-alignment.sam')
        report['alignmentOutput'] = {'characters':len(str(sam_path)), 'bytes':sam['bytes'],
                                     'sha256':sam['sha256'], 'ordinaryIsFile':sam_path.is_file(),
                                     'extendedIsFile':True}
        require(not sam_path.is_file(), 'Plain Python path unexpectedly bypassed the disabled-policy boundary.')
        if args.expect_missing_output:
            require(run['status']=='failed' and starter['failed']==1,
                    'The unchanged negative-control package did not exhibit the expected failure.')
            require('did not produce declared output sam' in first.get('message',''),
                    'The negative control failed for a different reason: '+first.get('message',''))
            require(all(node['status']=='blocked' for node in graph_record['nodes'][1:]),
                    'The negative-control downstream state differed from the observed failure.')
            report['checks'].append('Unchanged prior package reproduces false missing-SAM rejection although native bytes and bridge hash exist.')
        else:
            require(run['status']=='completed' and run.get('success') and starter['passed']==1 and starter['failed']==0,
                    'The full Check installation operation failed: '+str(run.get('message')))
            check_additional_pack_success(run, evidence, report)
            require(len(graph_record['nodes'])==5 and all(node['status']=='success' for node in graph_record['nodes']),
                    'Alignment, SAMtools preparation, BCFtools calling/statistics and combined reporting must all succeed.')
            output_files=[]
            for product in graph_record['outputs'].values():
                for key,path in product['files'].items():
                    require(not path.startswith('\\\\?\\'), 'Run records must retain ordinary file identities rather than extended I/O namespaces.')
                    require(io_path(path).is_file() and digest(path)==product['sha256'][key],
                            'A completed long-path output failed independent rehashing.')
                    target = evidence/'completed-outputs'/(product['id'].replace('::','-')+'-'+key+Path(path).suffix)
                    target.parent.mkdir(exist_ok=True)
                    shutil.copyfile(io_path(path), target)
                    output_files.append({'evidenceFile':str(target.relative_to(evidence)), 'characters':len(path),'sha256':product['sha256'][key],'output':product['id'],'field':key})
            report['outputFiles']=output_files
            report['checks'].extend([
                'All 7 exact-package integrity checks and the full five-step native starter scientific oracle pass with Windows long-path opt-in disabled.',
                'Every completed long-path result is present and independently rehashed; native alignments, BAM preparation, variant truth and report creation all pass.'
            ])
        require(policy()==0, 'The app changed Windows long-path policy during the regression.')
        report['success']=True
    except Exception as exc:
        report.update(error=str(exc), traceback=traceback.format_exc())
    finally:
        if host:
            host.close()
        report['passed']=len(report['checks'])
        report['completedUtc']=datetime.now(timezone.utc).isoformat()
        write_json(args.report, report)
    print(json.dumps({'success':report['success'],'passed':report['passed'],
                      'expectedApplicationFailure':args.expect_missing_output,'report':str(args.report)}), flush=True)
    return 0 if report['success'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
