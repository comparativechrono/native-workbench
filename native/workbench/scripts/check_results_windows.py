#!/usr/bin/env python3
"""Validate exact packaged CWL results, routed DAGs and native application icons.

Run with the disposable application's bundled Python on native Windows. The
CWL embedded runners are executed independently, but this gate is not a CWL
engine interoperability test; the separate cwltool gate establishes that scope.
"""
from __future__ import annotations

import argparse
import copy
import ast
from collections import Counter
import ctypes
from ctypes import wintypes
from datetime import datetime, timezone
import gzip
import glob
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
import struct
import subprocess
import sys
import time
import traceback
from urllib.parse import urlsplit
from urllib.request import url2pathname
import xml.etree.ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_references_windows import PrivateHost, require, sha256, stop_process_tree, write_json
from check_workspace_ui_windows import NativeUI, canonical_sam_record


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def plain_id(value):
    return re.sub(r'[^A-Za-z0-9_]', '_', value)


def local_default(value):
    if isinstance(value, dict) and value.get('class') in ('File', 'Directory'):
        result = dict(value)
        location = urlsplit(result.pop('location'))
        require(location.scheme == 'file', 'CWL default must use a local file URI.')
        # url2pathname performs URI decoding once, including drive and UNC forms.
        path = ('//' + location.netloc if location.netloc else '') + location.path
        result['path'] = url2pathname(path)
        return result
    return value


def resolve_bindings(bindings, values):
    supplied = {}
    for key, binding in bindings.items():
        if isinstance(binding, str):
            supplied[key] = values[binding]
        elif 'source' in binding:
            require(binding.get('linkMerge') == 'merge_flattened', 'Unexpected CWL multiple-input binding.')
            supplied[key] = []
            for source in binding['source']:
                item = values[source]
                supplied[key].extend(item if isinstance(item, list) else [item])
        else:
            supplied[key] = binding['default']
    return supplied


def runner_definition(process):
    listing = process['requirements']['InitialWorkDirRequirement']['listing']
    entry = listing[0]['entry']
    require(entry.startswith('${return ') and entry.endswith(';}'), 'Unexpected embedded runner expression.')
    script = json.loads(entry[len('${return '):-2])
    first, _ = script.split('\n', 1)
    require(first.startswith('CONFIG = '), 'Exported command runner lacks a frozen configuration.')
    config = ast.literal_eval(first[len('CONFIG = '):])
    return config, script, listing[0]['entryname'], listing[1]['entryname']


def check_svg(path, graph):
    """Independent geometric oracle; does not import the production router."""
    svg = ET.parse(path).getroot()
    namespace = {'s': 'http://www.w3.org/2000/svg'}
    cards = {}
    for group in svg.findall('s:g', namespace):
        rectangle = group.find('s:rect', namespace)
        if group.get('data-node') and rectangle is not None:
            x, y, w, h = (float(rectangle.get(key)) for key in ('x', 'y', 'width', 'height'))
            cards[group.get('data-node')] = (x, y, x+w, y+h)
    expected = Counter((ref.split('::', 1)[0], node['id']) for node in graph['nodes']
                       for refs in node['inputs'].values() for ref in refs)
    observed, segments, detours = Counter(), 0, 0
    require(set(cards) == {item['id'] for item in graph['nodes'] + graph['sources']},
            'Saved SVG omitted workflow cards.')
    for edge in svg.findall('s:path', namespace):
        if edge.get('class') != 'dependency':
            continue
        source, target = edge.get('data-source'), edge.get('data-target')
        observed[source, target] += 1
        text = edge.get('d', '')
        require(re.fullmatch(r'M-?\d+(?:\.\d+)?,-?\d+(?:\.\d+)?(?: L-?\d+(?:\.\d+)?,-?\d+(?:\.\d+)?)+', text),
                'Saved DAG dependency must be an explicit orthogonal path.')
        points = [tuple(map(float, point.split(','))) for point in text[1:].split(' L')]
        require(points[0][1] == cards[source][3] and cards[source][0] <= points[0][0] <= cards[source][2],
                'DAG edge does not start at its actual producer card.')
        require(points[-1][1] == cards[target][1] and cards[target][0] <= points[-1][0] <= cards[target][2],
                'DAG edge does not end at its actual consumer card.')
        for index, (a, b) in enumerate(zip(points, points[1:])):
            require(a[0] == b[0] or a[1] == b[1], 'DAG route is not orthogonal.')
            segments += 1
            for identity, (left, top, right, bottom) in cards.items():
                # Endpoint attachment crosses padding, but never card interiors.
                padding = 0 if ((index == 0 and identity == source) or
                                (index == len(points)-2 and identity == target)) else 9
                left, top, right, bottom = left-padding, top-padding, right+padding, bottom+padding
                crossing = (left < a[0] < right and max(min(a[1], b[1]), top) < min(max(a[1], b[1]), bottom)
                            if a[0] == b[0] else
                            top < a[1] < bottom and max(min(a[0], b[0]), left) < min(max(a[0], b[0]), right))
                require(not crossing, 'Saved SVG dependency crosses card: ' + identity)
        if cards[target][1] - cards[source][1] > 150:
            detours += 1
            require(len(points) >= 4, 'Skip-rank dependency did not route around intervening ranks.')
    require(observed == expected, 'Saved DAG dependency count/endpoints differ from the frozen graph.')
    require(detours >= 2, 'Scientific DAG did not cover shared-reference/report skipped ranks.')
    return {'cards': len(cards), 'edges': sum(observed.values()), 'segments': segments,
            'skipRankEdges': detours, 'paddingChecked': 9, 'sha256': sha256(path)}


def command_comparison(root, node, process, step_binding, actual, evidence):
    config, _, _, _ = runner_definition(process)
    tool = node['tool']
    require(json.loads(process['nw:operation']) == tool and json.loads(process['nw:parameters']) == node['params'],
            'CWL operation/parameter provenance differs from its frozen plan.')
    require(config['steps'] == tool.get('steps', []), 'CWL command definitions changed from the frozen pack operation.')
    require(config['outputs'] == [field for group in tool.get('outputs', []) for field in group.get('fields', [])],
            'CWL runner output files differ from the frozen pack operation.')
    for key, value in node['params'].items():
        require(step_binding['p_' + key] == str(value), 'CWL command parameter changed.')
    if tool.get('builtin') or tool['id'] == 'builtin/report':
        return 0
    pack = root / tool['packFolder']
    require(sha256(pack / 'pack.ini') == config['manifestSha256'] == tool['manifestSha256'],
            'CWL pack manifest differs from the exact installed bytes.')
    for item in list(config['assets'].values()) + list(config['executables'].values()):
        require(sha256(pack / item['path']) == item['sha256'], 'CWL pinned pack file failed an independent hash.')
    bridge = read_json(Path(actual['folder']) / 'run.json')
    write_json(evidence / (plain_id(node['id']) + '-native-run.json'), bridge)
    require(bridge['status'] == 'success' and len(bridge['steps']) == len(config['steps']),
            'Native bridge did not complete all frozen commands.')
    values = {key: step_binding['p_' + key] for key in node['params']}
    for key, kind in config['inputTypes'].items():
        item = step_binding['i_' + key]
        values[key] = [x['path'] for x in item] if kind == 'files' else item['path'] if item else ''
    out = {item['id']: str(Path(actual['folder']) / item['path']) for item in config['outputs']}
    assets = {key: str(pack / item['path']) for key, item in config['assets'].items()}
    def expand(value):
        def substitute(match):
            kind, _, key = match.group(1).partition(':')
            return str(actual['folder']) if kind == 'run' else str({'input': values, 'output': out, 'asset': assets}[kind][key])
        return re.sub(r'\{([^{}]+)\}', substitute, value)
    def arguments(items):
        result = []
        for value in items:
            match = re.fullmatch(r'\{inputs:([^{}]+)\}', value)
            result.extend(values[match.group(1)] if match else [expand(value)])
        return result
    for definition, ran in zip(config['steps'], bridge['steps']):
        require(ran['id'] == definition['id'] and ran['kind'] == definition['kind'] and ran['status'] == 'success',
                'CWL/native command identity differs.')
        if definition['kind'] == 'copy':
            require(ran['source'] == expand(definition['source']) and ran['destination'] == out[definition['destination']],
                    'CWL/native copy endpoints differ.')
        else:
            require(ran['arguments'] == arguments(definition['args']), 'CWL/native argument arrays differ.')
            require(Path(ran['executable']) == pack / config['executables'][definition['tool']]['path'],
                    'CWL/native executable paths differ.')
            if definition['kind'] == 'pipe':
                require(ran['sink_arguments'] == arguments(definition['sinkArgs']) and
                        Path(ran['sink_executable']) == pack / config['executables'][definition['sinkTool']]['path'],
                        'CWL/native binary-pipe sink differs.')
    return len(bridge['steps'])


def scientific_checks(root, evidence, report):
    host = PrivateHost(root, evidence, 'results-host', offline=True)
    try:
        report['appVersion'] = host.call('init').get('app_version')
        parent = evidence / 'native-results'
        parent.mkdir()
        started = host.call('check', {'output_folder': str(parent)})
        deadline = time.monotonic()+240
        while time.monotonic() < deadline:
            result = host.call('run/get', {'run_id': started['run_id']})
            if result['status'] not in ('preparing', 'running', 'cancelling'):
                break
            time.sleep(.1)
        else:
            raise TimeoutError('Native starter scientific check did not finish.')
        write_json(evidence / 'installation-service-result.json', result)
        require(result['status'] == 'completed' and result.get('success'), 'Exact-package Check installation failed.')
        require(result['core_checks']['success'] and result['core_checks']['failed'] == 0,
                'Exact-package core integrity check failed.')
        checks = result['starter_checks']
        require(checks['nativeWindowsExecuted'] and checks['analysisExecuted'] and
                checks['passed'] == 1 and checks['failed'] == checks['skipped'] == 0,
                'Full native starter scientific profile must execute without failure or skip.')
        report['nativeWindowsExecuted'] = True
        folder = Path(checks['checks'][0]['folder'])
        plan, run, cwl = (read_json(folder / name) for name in ('plan.json', 'run.json', 'workflow.cwl'))
        for name in ('plan.json', 'run.json', 'workflow.cwl', 'pipeline.svg', 'methods-completed.txt'):
            shutil.copyfile(folder / name, evidence / name)
        main = cwl['$graph'][0]
        require(cwl['cwlVersion'] == 'v1.2' and main['class'] == 'Workflow' and main['id'] == '#main', 'Result lacks a packed CWL v1.2 Workflow.')
        unsigned = dict(plan)
        claimed = unsigned.pop('sha256')
        actual_hash = hashlib.sha256(json.dumps(unsigned, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()).hexdigest()
        require(actual_hash == claimed == main['nw:planSha256'] == run['planSha256'], 'CWL/frozen-plan identity differs.')
        definition = copy.deepcopy(cwl)
        definition['$graph'][0].pop('nw:execution', None)
        definition['$graph'][0].pop('nw:planSha256', None)
        definition_hash = hashlib.sha256(json.dumps(definition, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf-8')).hexdigest()
        require(definition_hash == plan['workflowExport']['definitionSha256'] == run['workflowExport']['definitionSha256'],
                'Executable CWL definitions are not pinned by the original frozen plan and completed run.')
        require(run['workflowExport']['file'] == 'workflow.cwl' and run['workflowExport']['sha256'] == sha256(folder / 'workflow.cwl'), 'Run record does not hash the final CWL file.')
        require(main['nw:execution']['status'] == run['status'] == 'success' and main['nw:execution']['success'] is True and
                json.loads(main['nw:execution']['recordJson'])['nodes'] == run['nodes'] and
                json.loads(main['nw:execution']['recordJson'])['outputs'] == run['outputs'],
                'CWL completion metadata differs from the actual run.')
        require(json.loads(main['nw:references']) == plan.get('references', {}), 'CWL reference provenance differs from the frozen plan.')
        require(len(main['steps']) == len(plan['nodes']) == 5, 'CWL did not preserve all five native workflow operations.')
        expected_sources = {(source['id'], field): path for source in plan['graph']['sources'] for field, path in source['files'].items()}
        seen_sources = {}
        for key, field in main['inputs'].items():
            if 'nw:source' in field:
                meta = json.loads(field['nw:source'])
                path = local_default(field['default'])['path']
                require(meta['evidence'] == plan['inputs'][path] and sha256(path) == meta['evidence']['sha256'], 'CWL input provenance/hash differs.')
                seen_sources[meta['id'], meta['field']] = path
        require(seen_sources == expected_sources, 'CWL source file roles differ from the native graph.')
        processes = {item['id']: item for item in cwl['$graph'][1:]}
        originals = {key: local_default(field.get('default')) for key, field in main['inputs'].items()}
        replay_values = dict(originals)
        replay_values['nw_python'] = str(root / 'runtime/python/python.exe')
        actual_nodes = {item['id']: item for item in run['nodes']}
        native_commands, output_count, replays = 0, 0, []
        for node in plan['nodes']:
            identity = plain_id(node['id'])
            workflow_step = main['steps'][identity]
            process = processes[workflow_step['run']]
            supplied = resolve_bindings(workflow_step['in'], originals)
            native_commands += command_comparison(root, node, process, supplied, actual_nodes[node['id']], evidence)
            config, script, script_name, input_name = runner_definition(process)
            expected_output_ids = ['o_' + item['id'] for item in config['outputs']]
            require(workflow_step['out'] == expected_output_ids and set(process['outputs']) == set(expected_output_ids),
                    'CWL step/process output ports differ from frozen command outputs.')
            for item in config['outputs']:
                key = 'o_' + item['id']
                declaration = process['outputs'][key]
                expression = declaration['outputBinding']['glob']
                require(declaration['type'] == 'File' and expression.startswith('${return ') and expression.endswith(';}') and
                        json.loads(expression[len('${return '):-2]) == glob.escape(item['path']),
                        'CWL output collection does not name the actual declared file.')
                exposed = main['outputs'][identity + '_' + key]
                require(exposed['type'] == 'File' and exposed['outputSource'] == identity + '/' + key,
                        'CWL workflow output points to a different producing step or file port.')
            replay = evidence / 'cwl-replay' / identity
            replay.mkdir(parents=True)
            (replay / script_name).write_text(script, encoding='utf-8')
            replay_input = resolve_bindings(workflow_step['in'], replay_values)
            write_json(replay / input_name, replay_input)
            command = [str(root / 'runtime/python/python.exe'), '-I', '-u', script_name, input_name]
            with (replay / 'runner.stdout.txt').open('wb') as stdout, (replay / 'runner.stderr.txt').open('wb') as stderr:
                completed = subprocess.run(command, cwd=replay, stdout=stdout, stderr=stderr, timeout=180)
            require(completed.returncode == 0, 'Independent embedded CWL runner failed: ' + identity)
            for output in config['outputs']:
                generated = replay / output['path']
                require(generated.is_file() and (generated.stat().st_size or not output.get('nonempty', True)), 'Independent CWL runner output missing.')
                key = identity + '/o_' + output['id']
                replay_values[key] = {'class': 'File', 'path': str(generated)}
                original = next(product for product in run['outputs'].values()
                                if product['producer'] == node['id'] and output['id'] in product['files'])
                original_path = original['files'][output['id']]
                require(sha256(original_path) == original['sha256'][output['id']], 'Native output hash differs from run provenance.')
                originals[key] = {'class': 'File', 'path': original_path}
                output_count += 1
            replays.append({'step': identity, 'scriptSha256': sha256(replay / script_name), 'exitCode': completed.returncode,
                            'outputs': [{'id': item['id'], 'sha256': sha256(replay / item['path'])} for item in config['outputs']]})
        require(set(main['outputs']) == {plain_id(node['id']) + '_o_' + output['id'] for node in plan['nodes']
                                       for group in node['tool']['outputs'] for output in group['fields']}, 'CWL omitted declared result outputs.')
        # Independent known-answer oracle, not a byte comparison to rerun headers.
        replay_sam = Path(replay_values['step_1/o_sam']['path'])
        replay_bam = Path(replay_values['step_2/o_bam']['path'])
        replay_vcf = Path(replay_values['step_3/o_variants']['path'])
        sam_lines = [line for line in replay_sam.read_text(encoding='utf-8').splitlines() if line and not line.startswith('@')]
        rows = [line.split('\t') for line in sam_lines]
        require(len(rows) == 202 and all(int(row[1]) & 1 and int(row[1]) & 2 and not int(row[1]) & 4 and row[2] == 'starter' for row in rows),
                'CWL replay did not reproduce all 202 mapped proper-pair records.')
        with gzip.open(replay_bam, 'rb') as stream:
            require(stream.read(4) == b'BAM\x01', 'CWL replay did not produce actual binary BAM.')
        samtools = root / 'packs/bam-0.4.0/bin/samtools.exe'
        converted = subprocess.run([str(samtools), 'view', str(replay_bam)], capture_output=True, timeout=60)
        require(converted.returncode == 0, 'CWL replay BAM could not be decoded.')
        bam_lines = converted.stdout.decode('utf-8').splitlines()
        native_bam = originals['step_2/o_bam']['path']
        native_decoded = subprocess.run([str(samtools), 'view', native_bam], capture_output=True, timeout=60)
        require(native_decoded.returncode == 0, 'Native prepared BAM could not be decoded for independent comparison.')
        require(Counter(map(canonical_sam_record, native_decoded.stdout.decode('utf-8').splitlines())) ==
                Counter(map(canonical_sam_record, bam_lines)), 'CWL replay differs from native mate-fixing/duplicate-marking results.')
        prepared_rows = [line.split('\t') for line in bam_lines]
        require(len(prepared_rows) == 202 and all(int(row[1]) & 1 and int(row[1]) & 2 and not int(row[1]) & 4 for row in prepared_rows),
                'CWL prepared BAM lost mapped proper-pair records.')
        with gzip.open(replay_vcf, 'rt', encoding='utf-8') as stream:
            variant_rows = [line.split('\t') for line in stream.read().splitlines() if line and not line.startswith('#')]
        require(len(variant_rows) == 1 and variant_rows[0][:2] == ['starter', '1351'] and variant_rows[0][3:5] == ['G', 'A'], 'CWL replay did not reproduce the known SNP.')
        require(variant_rows[0][9].split(':')[variant_rows[0][8].split(':').index('GT')] == '1/1', 'CWL replay genotype differs from known truth.')
        report['dag'] = check_svg(folder / 'pipeline.svg', plan['graph'])
        report['science'] = {'networkSocketOperationsDeniedForHost': True, 'nativeWindowsExecuted': True,
                             'nativeCommandsCompared': native_commands, 'outputsIndependentlyHashed': output_count,
                             'cwlRunnerReplays': replays, 'alignmentRecords': 202,
                             'variantTruth': 'starter:1351 G>A; GT=1/1',
                             'scope': 'Native private-host execution plus embedded-runner replay; not a Windows cwltool invocation.'}
        report['checks'].extend([
            'Exact packaged integrity check and all five starter scientific operations execute without failures or skips.',
            'Results include a packed CWL v1.2 workflow tied to the frozen plan, real completion record and final export hash.',
            'CWL source hashes, file roles, scientific parameters, complete output set, pack pins and reference metadata match frozen native provenance.',
            'Every exported command/copy/binary-pipe definition expands to the actual native bridge argument record.',
            'All five embedded CWL runners execute independently with packaged private Python and pinned native pack programs.',
            'Independent CWL replay preserves 202 proper-pair SAM/BAM records and known starter:1351 G>A homozygous SNP truth.',
            'Saved scientific DAG includes every actual dependency and avoids all unrelated cards with padding, including skipped ranks.'
        ])
    finally:
        host.close()


def icon_checks(ui, root, evidence):
    user, gdi = ui.user, ui.gdi
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.LoadLibraryExW.argtypes = [wintypes.LPCWSTR, wintypes.HANDLE, wintypes.DWORD]
    kernel.LoadLibraryExW.restype = wintypes.HMODULE
    kernel.FindResourceW.argtypes = [wintypes.HMODULE, ctypes.c_void_p, ctypes.c_void_p]
    kernel.FindResourceW.restype = wintypes.HANDLE
    kernel.SizeofResource.argtypes = [wintypes.HMODULE, wintypes.HANDLE]
    kernel.SizeofResource.restype = wintypes.DWORD
    kernel.LoadResource.argtypes = [wintypes.HMODULE, wintypes.HANDLE]
    kernel.LoadResource.restype = wintypes.HANDLE
    kernel.LockResource.argtypes = [wintypes.HANDLE]
    kernel.LockResource.restype = ctypes.c_void_p
    kernel.FreeLibrary.argtypes = [wintypes.HMODULE]
    user.LoadImageW.argtypes = [wintypes.HINSTANCE, ctypes.c_void_p, wintypes.UINT, ctypes.c_int, ctypes.c_int, wintypes.UINT]
    user.LoadImageW.restype = wintypes.HANDLE
    user.GetClassLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int]
    user.GetClassLongPtrW.restype = ctypes.c_size_t
    user.DrawIconEx.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int, wintypes.HANDLE, ctypes.c_int, ctypes.c_int,
                                wintypes.UINT, wintypes.HBRUSH, wintypes.UINT]
    user.DestroyIcon.argtypes = [wintypes.HANDLE]
    class IconInfo(ctypes.Structure):
        _fields_ = [('fIcon', wintypes.BOOL), ('xHotspot', wintypes.DWORD), ('yHotspot', wintypes.DWORD),
                    ('hbmMask', wintypes.HBITMAP), ('hbmColor', wintypes.HBITMAP)]
    class Bitmap(ctypes.Structure):
        _fields_ = [('bmType', wintypes.LONG), ('bmWidth', wintypes.LONG), ('bmHeight', wintypes.LONG),
                    ('bmWidthBytes', wintypes.LONG), ('bmPlanes', wintypes.WORD),
                    ('bmBitsPixel', wintypes.WORD), ('bmBits', ctypes.c_void_p)]
    user.GetIconInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(IconInfo)]
    user.GetIconInfo.restype = wintypes.BOOL
    gdi.GetObjectW.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p]
    gdi.GetObjectW.restype = ctypes.c_int
    def dimensions(icon):
        info = IconInfo()
        require(user.GetIconInfo(icon, ctypes.byref(info)), 'Native class icon metadata unavailable.')
        try:
            bitmap = Bitmap()
            require(info.hbmColor and gdi.GetObjectW(info.hbmColor, ctypes.sizeof(bitmap), ctypes.byref(bitmap)) == ctypes.sizeof(bitmap),
                    'Native class icon lacks an inspectable color bitmap.')
            return bitmap.bmWidth, bitmap.bmHeight
        finally:
            if info.hbmColor: gdi.DeleteObject(info.hbmColor)
            if info.hbmMask: gdi.DeleteObject(info.hbmMask)
    gdi.PatBlt.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.DWORD]
    module = kernel.LoadLibraryExW(str(root / 'NativeWorkbench.exe'), None, 0x22)
    require(module, 'Packaged native executable could not be opened as an icon resource.')
    def render(icon, size):
        require(icon, 'Native application icon handle is absent.')
        dc = user.GetDC(ui.main)
        memory = gdi.CreateCompatibleDC(dc)
        bitmap = gdi.CreateCompatibleBitmap(dc, size, size)
        old = gdi.SelectObject(memory, bitmap)
        try:
            require(gdi.PatBlt(memory, 0, 0, size, size, 0x00FF0062), 'Icon background could not be drawn.')
            require(user.DrawIconEx(memory, 0, 0, icon, size, size, 0, None, 3), 'Native icon could not be rendered.')
            header = struct.pack('<IiiHHIIiiII', 40, size, -size, 1, 32, 0, size*size*4, 0, 0, 0, 0)
            info, pixels = ctypes.create_string_buffer(header + bytes(1024)), ctypes.create_string_buffer(size*size*4)
            gdi.SelectObject(memory, old)
            require(gdi.GetDIBits(memory, bitmap, 0, size, pixels, info, 0) == size, 'Native icon pixels unavailable.')
            # GDI does not define the unused alpha byte; compare visible RGB only.
            raw = bytes(value for index, value in enumerate(pixels.raw) if index % 4 != 3)
            return hashlib.sha256(raw).hexdigest()
        finally:
            gdi.SelectObject(memory, old)
            gdi.DeleteObject(bitmap)
            gdi.DeleteDC(memory)
            user.ReleaseDC(ui.main, dc)
    try:
        resource = kernel.FindResourceW(module, ctypes.c_void_p(101), ctypes.c_void_p(14))
        require(resource, 'Packaged native executable lacks its branded group icon resource 101.')
        size = kernel.SizeofResource(module, resource)
        handle = kernel.LoadResource(module, resource)
        address = kernel.LockResource(handle)
        require(address and size >= 6, 'Packaged group icon resource is unreadable.')
        data = ctypes.string_at(address, size)
        reserved, kind, count = struct.unpack_from('<HHH', data)
        require(reserved == 0 and kind == 1 and len(data) == 6+14*count, 'Malformed native icon group.')
        frames = []
        for index in range(count):
            w, h, colors, reserved, planes, depth, length, identity = struct.unpack_from('<BBBBHHIH', data, 6+index*14)
            frames.append({'width': w or 256, 'height': h or 256, 'bitDepth': depth, 'bytes': length, 'resourceId': identity})
            require(kernel.FindResourceW(module, ctypes.c_void_p(identity), ctypes.c_void_p(3)), 'Native icon group references a missing frame.')
        require([frame['width'] for frame in frames] == [16, 20, 24, 32, 40, 48, 64, 128, 256] and
                all(frame['width'] == frame['height'] for frame in frames), 'Native icon resource resolutions differ from the SVG-derived set.')
        rendered = []
        for label, class_index, metric in [('large', -14, 11), ('small', -34, 49)]:
            side = user.GetSystemMetrics(metric)
            live = user.GetClassLongPtrW(ui.main, class_index)
            width, height = dimensions(live)
            require((width, height) == (side, side), 'Native ' + label + ' icon did not use its own system-sized bitmap.')
            expected = user.LoadImageW(module, ctypes.c_void_p(101), 1, side, side, 0)
            stock = user.LoadImageW(None, ctypes.c_void_p(32512), 1, side, side, 0x8000)  # LR_SHARED is required for stock icons.
            try:
                observed, branded, default = (render(icon, side) for icon in (live, expected, stock))
                require(observed == branded and observed != default, 'Native class icon does not render the packaged brand resource: ' + label)
                rendered.append({'kind': label, 'pixels': side, 'bitmapWidth': width, 'bitmapHeight': height, 'visibleRgbSha256': observed, 'stockRgbSha256': default})
            finally:
                if expected: user.DestroyIcon(expected)
                # Stock LR_SHARED handles belong to Windows and are not destroyed.
        return {'groupResource': 101, 'frames': frames, 'windowClassIcons': rendered}
    finally:
        kernel.FreeLibrary(module)


def gui_checks(root, evidence, report):
    ui = NativeUI(root, evidence)
    report['nativeGUILaunched'] = True
    try:
        ui.wait('native library ready for results gate', lambda: ui.user.IsWindowEnabled(ui.child(410)) and len(ui.library().tools()) > 0)
        ui.user.MoveWindow(ui.main, 0, 0, 1280, 900, True)
        icons = icon_checks(ui, root, evidence)
        write_json(evidence / 'native-icon-checks.json', icons)
        report['nativeWindowsExecuted'] = True
        captures = [ui.capture('application-icon-normal.bmp')]
        scale = ui.user.GetDpiForWindow(ui.main) / 96
        def point(x, y):
            left, top, _, _ = ui.bounds(ui.child(117))
            return round(left + x*scale), round(top + y*scale)
        def edits():
            return [row for row in ui.controls() if row['id'] >= 2000 and row['class'].lower() == 'edit']
        def has_name(name):
            return any(row['text'] == name for row in edits())
        ui.click_button(411)
        ui.wait('workflow canvas ready', lambda: ui.user.IsWindowVisible(ui.child(117)))
        canvas = ui.child(117)
        # Hosted desktops may clamp a requested 1280x900 window to their work
        # area (observed 1044x788, 457x538 canvas client at 96 DPI). Fit three
        # staggered rows to the real viewport instead of requiring two cards
        # side by side. The final connection still runs backwards from the
        # right-hand output to the next row's left-hand input.
        client = wintypes.RECT()
        require(ui.user.GetClientRect(canvas, ctypes.byref(client)), 'Could not measure actual native canvas client area.')
        canvas_width, canvas_height = client.right/scale, client.bottom/scale
        card_width, card_height = 242, 140  # Coordinate sort: one input + one output.
        right_x = min(294, int(canvas_width-card_width-24))
        gap = min(30, int((canvas_height-3*card_height-48)/2))
        require(right_x >= 110 and gap >= 20, 'Actual native viewport cannot contain the three-row routing fixture.')
        cards = [{'name': 'Route producer', 'x': 24, 'y': 24},
                 {'name': 'Route middle', 'x': right_x, 'y': 24+card_height+gap},
                 {'name': 'Route backward consumer', 'x': 24, 'y': 24+2*(card_height+gap)}]
        work_area = wintypes.RECT()
        ui.user.SystemParametersInfoW.argtypes = [wintypes.UINT, wintypes.UINT, ctypes.c_void_p, wintypes.UINT]
        ui.user.SystemParametersInfoW.restype = wintypes.BOOL
        require(ui.user.SystemParametersInfoW(0x0030, 0, ctypes.byref(work_area), 0), 'Could not inspect the native desktop work area.')
        geometry = {'windowBounds': ui.bounds(ui.main), 'canvasBounds': ui.bounds(canvas),
                    'screenPixels': [ui.user.GetSystemMetrics(0), ui.user.GetSystemMetrics(1)],
                    'desktopWorkArea': [work_area.left, work_area.top, work_area.right, work_area.bottom],
                    'canvasClientLogicalSize': [canvas_width, canvas_height],
                    'dpi': ui.user.GetDpiForWindow(ui.main), 'cards': cards,
                    'cardLogicalSize': [card_width, card_height]}
        write_json(evidence / 'routing-fixture-geometry.json', geometry)
        def add_card(name, x, y):
            ui.set_text(ui.child(102), 'Coordinate sort')
            ui.wait('single coordinate-sort library row', lambda: len(ui.library().tools()) == 1)
            ui.drag(ui.library().first_tool_point(), point(x+120, y+20))
            ui.wait('new routing fixture tool', lambda: has_name('Coordinate sort'))
            edit = next(row for row in edits() if row['text'] == 'Coordinate sort')
            ui.set_text(edit['hwnd'], name)
        for card in cards:
            add_card(card['name'], card['x'], card['y'])
        producer, middle, consumer = cards
        # Socket drops are private-host requests. Select the producer first
        # so its changed 'Used by' text provides an observable completion
        # condition before the next card-selection pointer event.
        ui.click_at(*point(producer['x']+100, producer['y']+20))
        ui.wait('select forward connection producer', lambda: has_name(producer['name']))
        ui.drag(point(producer['x']+card_width, producer['y']+107), point(middle['x'], middle['y']+65))
        ui.wait('forward connection applied before receiver selection', lambda: any(
            row['class'].lower() == 'static' and 'Used by:' in row['text'] and
            middle['name'] in row['text'] for row in ui.controls()))
        # Connecting sockets preserves the selected card. Select the receiver
        # explicitly before checking its own inspector's connection description.
        ui.click_at(*point(middle['x']+100, middle['y']+20))
        ui.wait('select forward connection receiver', lambda: has_name(middle['name']))
        ui.wait('native forward port connection', lambda: any(row['class'].lower() == 'static' and 'From:' in row['text'] and 'Route producer' in row['text'] for row in ui.controls()))
        ui.drag(point(middle['x']+card_width, middle['y']+107), point(consumer['x'], consumer['y']+65))
        ui.wait('backward connection applied before receiver selection', lambda: any(
            row['class'].lower() == 'static' and 'Used by:' in row['text'] and
            consumer['name'] in row['text'] for row in ui.controls()))
        ui.click_at(*point(consumer['x']+100, consumer['y']+20))
        ui.wait('select backward connection receiver', lambda: has_name(consumer['name']))
        ui.wait('native backward port connection', lambda: any(row['class'].lower() == 'static' and 'From:' in row['text'] and 'Route middle' in row['text'] for row in ui.controls()))
        ui.mouse(*point(canvas_width-12, 20))
        captures.append(ui.capture('workflow-backward-routing.bmp'))
        # The hosted desktop can put its taskbar over an oversized test window's
        # footer. Pointer connections above remain real SendInput interactions;
        # this view-only capture invokes the documented native button message.
        zoom_button = ui.child(420)
        require(ui.user.IsWindowVisible(zoom_button) and ui.user.IsWindowEnabled(zoom_button), 'Native zoom button unavailable.')
        bounds = ui.bounds(zoom_button)
        center = wintypes.POINT((bounds[0]+bounds[2])//2, (bounds[1]+bounds[3])//2)
        ui.user.WindowFromPoint.argtypes = [wintypes.POINT]
        ui.user.WindowFromPoint.restype = wintypes.HWND
        hit = ui.user.WindowFromPoint(center)
        geometry['zoomActivation'] = {'method': 'BM_CLICK', 'buttonBounds': bounds,
                                      'physicalCenter': [center.x, center.y],
                                      'centerHitsButton': hit == zoom_button,
                                      'centerWindowClass': ui.label(hit, True) if hit else None}
        write_json(evidence / 'routing-fixture-geometry.json', geometry)
        ui.send(zoom_button, 0x00F5)  # BM_CLICK; no application-specific testing hook.
        ui.wait('routed canvas zooms after native BM_CLICK', lambda: int(ui.label(ui.child(422)).rstrip('%')) < 100)
        captures.append(ui.capture('workflow-backward-routing-zoomed.bmp'))
        return {'icons': icons, 'captures': captures, 'dpi': ui.user.GetDpiForWindow(ui.main),
                'routingFixture': {'cards': cards, 'geometryFile': 'routing-fixture-geometry.json',
                                   'connections': ['producer -> middle', 'middle -> backward consumer'],
                                   'scope': 'Real native pointer drags and compatibility confirmation; normal and BM_CLICK-activated zoomed pixel captures for visual review. Physical zoom-button clicks are covered by the separate workspace gate. No native route-coordinate introspection or automatic pixel geometry assertion.'},
                'checks': ['Packaged executable contains all nine SVG-derived icon resolutions; actual large/small class icons match that resource and differ from Windows default.',
                           'Real native canvas accepts compatible forward and backward connections across manually positioned cards and retains normal/zoomed captures.']}
    finally:
        ui.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--app-root', type=Path, required=True)
    parser.add_argument('--report', type=Path, required=True)
    parser.add_argument('--source-commit', required=True)
    parser.add_argument('--asset-sha256', required=True)
    parser.add_argument('--gui-worker', action='store_true', help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    root, evidence = args.app_root.resolve(), args.report.resolve().parent
    evidence.mkdir(parents=True, exist_ok=True)
    report = {'schema': 1, 'success': False, 'startedUtc': datetime.now(timezone.utc).isoformat(),
              'sourceCommit': args.source_commit, 'assetSha256': args.asset_sha256, 'gateSha256': sha256(__file__),
              'platform': platform.platform(), 'python': sys.version, 'checks': [], 'skips': [],
              'nativeWindowsExecuted': False, 'nativeGUILaunched': False, 'nativeGUIValidated': False}
    try:
        if os.name != 'nt':
            report['skips'].append('Native Windows application, scientific execution and GUI unavailable on this platform.')
            raise RuntimeError('This gate has no passing non-Windows mode; native checks are unrun.')
        require(Path(sys.executable).resolve() == (root / 'runtime/python/python.exe').resolve(), 'Run with the exact packaged private Python.')
        report['appFiles'] = {str(path.relative_to(root)): sha256(path) for path in
                              [root/'NativeWorkbench.exe', root/'WorkbenchBridge.exe', root/'runtime/python/python.exe',
                               root/'workspace/engine.py', root/'workspace/cwl_export.py', root/'workspace/dag_routing.py']}
        if args.gui_worker:
            report['gui'] = gui_checks(root, evidence, report)
            report['checks'].extend(report['gui']['checks'])
            report['nativeGUIValidated'] = True
        else:
            scientific_checks(root, evidence, report)
            worker_report = evidence / 'results-ui-worker.json'
            command = [sys.executable, '-I', '-u', str(Path(__file__).resolve()), '--gui-worker',
                       '--app-root', str(root), '--report', str(worker_report), '--source-commit', args.source_commit,
                       '--asset-sha256', args.asset_sha256]
            with (evidence/'results-ui-worker.stderr.txt').open('wb') as stderr:
                worker = subprocess.Popen(command, stderr=stderr)
                try:
                    worker.wait(timeout=180)
                finally:
                    stop_process_tree(worker)
            require(worker_report.is_file(), 'Native results GUI worker produced no report.')
            result = read_json(worker_report)
            report['nativeGUILaunched'] = result.get('nativeGUILaunched', False)
            report['nativeGUIValidated'] = result.get('nativeGUIValidated', False)
            require(worker.returncode == 0 and result.get('success'), 'Native results GUI worker failed: ' + json.dumps(result))
            report['gui'] = result['gui']
            report['checks'].extend(result['checks'])
        report['nativeWindowsExecuted'] = True
        report['success'] = True
    except Exception as exc:
        report.update(error=str(exc), traceback=traceback.format_exc())
    finally:
        report['passed'] = len(report['checks'])
        report['failed'] = int(not report['success'] and not report['skips'])
        report['completedUtc'] = datetime.now(timezone.utc).isoformat()
        report['evidenceFiles'] = [{'file': str(path.relative_to(evidence)), 'bytes': path.stat().st_size, 'sha256': sha256(path)}
                                   for path in sorted(evidence.iterdir()) if path.is_file() and path.resolve() != args.report.resolve()]
        write_json(args.report, report)
    print(json.dumps({'success': report['success'], 'passed': report['passed'], 'failed': report['failed'], 'skipped': len(report['skips']), 'report': str(args.report)}), flush=True)
    return 0 if report['success'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
