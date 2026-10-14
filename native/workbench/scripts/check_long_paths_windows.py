#!/usr/bin/env python3
"""Check exact packaged scientific execution with Windows long-path opt-in off.

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
              'assetSha256':args.asset_sha256, 'startedUtc':datetime.now(timezone.utc).isoformat(),
              'platform':platform.platform(), 'python':sys.version, 'checks':[], 'skips':[],
              'expectedApplicationFailure':args.expect_missing_output, 'nativeWindowsExecuted':False,
              'scope':'Exact packaged private host and complete starter installation-check chain; no GUI claim.'}
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
