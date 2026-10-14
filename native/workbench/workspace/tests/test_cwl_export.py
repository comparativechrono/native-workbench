"""Export contracts and standalone execution; NW_CWLTOOL enables cwltool."""
from __future__ import annotations
import copy
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from catalog import builtin_report, describe_workflow, parse_pack
from cwl_export import export_workflow, update_run_status, definition_sha256, _file_uri

SCRIPT = """import pathlib, sys
mode, *args = sys.argv[1:]
if mode == "pair":
    left, right, out1, out2, metrics, label = args
    pathlib.Path(out1).write_bytes(pathlib.Path(left).read_bytes() + b"LEFT")
    pathlib.Path(out2).write_bytes(pathlib.Path(right).read_bytes() + b"RIGHT")
    pathlib.Path(metrics).write_text(label, encoding="utf-8")
elif mode == "merge":
    target, *sources = args
    pathlib.Path(target).write_bytes(b"|".join(pathlib.Path(p).read_bytes() for p in sources))
elif mode == "emit":
    sys.stdout.buffer.write(b"A\\x00B\\xff\\n")
elif mode == "sink":
    sys.stdout.buffer.write(sys.stdin.buffer.read())
elif mode == "fail":
    sys.exit(9)
"""

def fixture(root):
    pack_root = root / 'packs' / 'fixture 100% # space-1.0.0'
    (pack_root / 'bin').mkdir(parents=True)
    # Host-only fixture launcher, not a redistributed Python runtime/Windows PE.
    (pack_root / 'bin/python.exe').write_text('#!' + sys.executable + '\nimport os,sys\nos.execv(' + repr(sys.executable) + ', [' + repr(sys.executable) + '] + sys.argv[1:])\n')
    (pack_root / 'bin/python.exe').chmod(0o755)
    (pack_root / 'fixture.py').write_text(SCRIPT, encoding='utf-8')
    lines = []
    def section(heading, **fields):
        lines.append('[' + heading + ']')
        lines.extend(key.replace('_', '-') + '=' + str(value) for key, value in fields.items())
    section('pack', format=2, id='fixture', version='1.0.0', name='Export fixture', platform='windows-x86_64')
    section('tool:python', path='bin/python.exe', version='3.12', sha256=hashlib.sha256((pack_root / 'bin/python.exe').read_bytes()).hexdigest())
    section('asset:script', path='fixture.py', sha256=hashlib.sha256(SCRIPT.encode()).hexdigest())
    section('workflow:pair', name='Pair transformation', inputs='reads1,reads2,label', outputs='trimmed1,trimmed2,metrics', steps='pair')
    section('input:pair:reads1', label='Left mate', type='file')
    section('input:pair:reads2', label='Right mate', type='file')
    section('input:pair:label', label='Label', type='text', default='fixture')
    for key, path in (('trimmed1', 'left [1].fq'), ('trimmed2', 'right.fq'), ('metrics', 'metrics.txt')):
        section('output:pair:' + key, label=key, path=path)
    section('step:pair:pair', label='Transform both mates', kind='exec', tool='python', produces='trimmed1,trimmed2,metrics')
    args = ['{asset:script}', 'pair', '{input:reads1}', '{input:reads2}', '{output:trimmed1}', '{output:trimmed2}', '{output:metrics}', '{input:label}']
    lines.extend('arg.' + str(i) + '=' + value for i, value in enumerate(args))
    section('workflow:merge', name='Ordered merge', inputs='files', outputs='merged', steps='merge')
    section('input:merge:files', label='Files', type='files')
    section('output:merge:merged', label='Merged', path='merged.txt')
    section('step:merge:merge', label='Merge', kind='exec', tool='python', produces='merged')
    lines.extend('arg.' + str(i) + '=' + value for i, value in enumerate(['{asset:script}', 'merge', '{output:merged}', '{inputs:files}']))
    section('workflow:pipe', name='Binary pipe', inputs='', outputs='stream,copied', steps='pipe,copy')
    section('output:pipe:stream', label='Stream', path='stream.bin')
    section('output:pipe:copied', label='Copy', path='nested/copied.bin')
    section('step:pipe:pipe', label='Pipe', kind='pipe', tool='python', sink_tool='python', stdout='stream')
    lines.extend(['arg.0={asset:script}', 'arg.1=emit', 'sink-arg.0={asset:script}', 'sink-arg.1=sink'])
    section('step:pipe:copy', label='Copy stream', kind='copy', source='{output:stream}', destination='copied')
    manifest = '\n'.join(lines) + '\n'
    (pack_root / 'pack.ini').write_text(manifest, encoding='utf-8')
    sha = hashlib.sha256(manifest.encode()).hexdigest()
    pack = parse_pack(manifest)
    tools = {key: describe_workflow(pack, value, str(pack_root.relative_to(root)), sha) for key, value in pack['workflows'].items()}
    tools['report'] = builtin_report()
    left, right = root / 'left #%.fq', root / 'right é.fq'
    left.write_bytes(b'R1'); right.write_bytes(b'R2')
    sources = [{'id': 'input-1', 'type': 'pair', 'label': 'Paired reads', 'files': {'read2': str(right), 'read1': str(left)}}]
    nodes = []
    for index, key, refs in (
        (1, 'pair', {'reads': ['input-1']}),
        (2, 'pair', {'reads': ['step-1::trimmed']}),
        (3, 'merge', {'files': ['step-2::metrics', 'step-1::metrics']}),
        (4, 'report', {'metrics': ['step-1::metrics', 'step-2::metrics']}),
        (5, 'pipe', {})):
        tool = tools[key]
        params = {p['id']: p['default'] for p in tool['params']}
        if key == 'pair':
            params['label'] = 'branch ' + str(index) + ' $(literal) braces; \\ "'
        nodes.append({'id': 'step-' + str(index), 'label': tool['name'], 'tool': tool, 'params': params, 'inputs': refs, 'dependencies': []})
    inputs = {str(path): {'path': str(path), 'bytes': path.stat().st_size, 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()} for path in (left, right)}
    return {'schema': 1, 'id': 'run-export-fixture', 'created': '2026-10-06T15:00:00Z',
            'graph': {'name': 'Paired branches and ordered merge', 'sources': sources, 'nodes': []},
            'nodes': nodes, 'inputs': inputs, 'references': {}, 'sha256': 'a' * 64}, pack_root

def embedded_script(process):
    entry = process['requirements']['InitialWorkDirRequirement']['listing'][0]['entry']
    return json.loads(entry[len('$' + '{return '):-2])

def direct_inputs(document, process):
    main = document['$graph'][0]
    node = next(value for value in main['steps'].values() if value['run'] == process['id'])
    values = {}
    for key, source in node['in'].items():
        if isinstance(source, str) and source in main['inputs']:
            value = copy.deepcopy(main['inputs'][source]['default'])
            if isinstance(value, dict) and 'location' in value:
                from urllib.parse import unquote, urlparse
                value['path'] = unquote(urlparse(value['location']).path)
            values[key] = value
        elif isinstance(source, dict) and 'default' in source:
            values[key] = source['default']
    values['nw_python'] = sys.executable
    return values

class CWLExportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='workbench-cwl-')
        self.root = Path(self.temp.name)
        self.plan, self.pack = fixture(self.root)
        self.document = export_workflow(self.plan, self.root)

    def tearDown(self):
        self.temp.cleanup()

    def test_pairs_preserve_explicit_roles_and_downstream_member_mapping(self):
        main = self.document['$graph'][0]
        self.assertEqual(main['steps']['step_1']['in']['i_reads1'], 'input_1_file_2')
        self.assertEqual(main['steps']['step_1']['in']['i_reads2'], 'input_1_file_1')
        self.assertEqual(main['steps']['step_2']['in']['i_reads1'], 'step_1/o_trimmed1')
        self.assertEqual(main['steps']['step_2']['in']['i_reads2'], 'step_1/o_trimmed2')

    def test_fanin_preserves_order_and_shared_producers(self):
        steps = self.document['$graph'][0]['steps']
        self.assertEqual(steps['step_3']['in']['i_files'], {'source': ['step_2/o_metrics', 'step_1/o_metrics'], 'linkMerge': 'merge_flattened'})
        self.assertEqual(steps['step_4']['in']['i_metrics']['source'], ['step_1/o_metrics', 'step_2/o_metrics'])
        self.assertEqual(len(steps), 5)

    def test_optional_files_empty_lists_and_directory_inputs_keep_types(self):
        # Exercise the manifest contract independently of a specific pack recipe.
        plan = copy.deepcopy(self.plan)
        node = plan['nodes'][2]
        node['inputs']['files'] = []
        node['tool']['ports'].append({'id': 'scratch', 'label': 'Scratch', 'type': 'directory', 'manifestInputs': ['scratch'],
                                     'fields': [{'id': 'scratch', 'label': 'Scratch', 'type': 'directory', 'required': False}]})
        node['inputs']['scratch'] = []
        document = export_workflow(plan, self.root)
        main, process = document['$graph'][0], document['$graph'][3]
        self.assertEqual(process['inputs']['i_scratch']['type'], ['null', 'Directory'])
        self.assertEqual(main['steps']['step_3']['in']['i_scratch'], {'default': None})
        self.assertEqual(main['steps']['step_3']['in']['i_files'], {'default': []})

    def test_frozen_commands_parameters_and_provenance_are_retained(self):
        process = self.document['$graph'][1]
        self.assertEqual(json.loads(process['nw:operation']), self.plan['nodes'][0]['tool'])
        self.assertEqual(json.loads(process['nw:parameters']), self.plan['nodes'][0]['params'])
        self.assertEqual(self.document['$graph'][0]['nw:execution']['status'], 'planned')
        self.assertEqual(self.document['$graph'][0]['nw:planSha256'], self.plan['sha256'])

    def test_file_uris_encode_windows_unc_unicode_reserved_characters(self):
        self.assertEqual(_file_uri(r'C:\My data\reads #%é.fq'), 'file:///C:/My%20data/reads%20%23%25%C3%A9.fq')
        self.assertEqual(_file_uri(r'\\server\share\reads #1.fq'), 'file://server/share/reads%20%231.fq')
        self.assertIn('%C3%A9', self.document['$graph'][0]['inputs']['input_1_file_1']['default']['location'])

    def test_outcome_update_preserves_frozen_definitions_and_failed_nodes(self):
        before = copy.deepcopy(self.document)
        self.pack.joinpath('pack.ini').unlink()
        run = {'status': 'failed', 'success': False, 'nodes': [{'id': 'step-1', 'status': 'failed'}, {'id': 'step-2', 'status': 'blocked'}]}
        final = update_run_status(self.document, run)
        self.assertEqual(self.document, before)
        self.assertEqual(final['$graph'][1:], before['$graph'][1:])
        self.assertEqual(json.loads(final['$graph'][0]['nw:execution']['recordJson']), run)

    def test_changed_manifest_fails_before_export(self):
        with (self.pack / 'pack.ini').open('a') as stream:
            stream.write('\n')
        with self.assertRaisesRegex(ValueError, 'manifest changed'):
            export_workflow(self.plan, self.root)

    def test_definition_digest_only_excludes_reciprocal_hash_and_outcome(self):
        baseline = definition_sha256(self.document)
        changed = update_run_status(self.document, {'status': 'success', 'success': True})
        changed['$graph'][0]['nw:planSha256'] = 'b' * 64
        self.assertEqual(definition_sha256(changed), baseline)
        changed['$graph'][1]['arguments'].append('tampered')
        self.assertNotEqual(definition_sha256(changed), baseline)
        changed = copy.deepcopy(self.document)
        changed['$graph'][1]['nw:execution'] = 'must not be ignored on tools'
        self.assertNotEqual(definition_sha256(changed), baseline)

    def invoke(self, process_index, values=None, script_override=None):
        process = self.document['$graph'][process_index]
        work = self.root / ('execute-' + str(process_index))
        work.mkdir()
        script = work / 'runner.py'
        script.write_text(script_override or embedded_script(process), encoding='utf-8')
        (work / 'inputs.json').write_text(json.dumps(values or direct_inputs(self.document, process)), encoding='utf-8')
        result = subprocess.run([sys.executable, str(script), str(work / 'inputs.json')], cwd=work, capture_output=True)
        return result, work

    def test_embedded_runner_executes_exact_pair_arguments_without_workbench(self):
        result, work = self.invoke(1)
        self.assertEqual(result.returncode, 0, result.stderr.decode())
        self.assertEqual((work / 'left [1].fq').read_bytes(), b'R1LEFT')
        self.assertEqual((work / 'right.fq').read_bytes(), b'R2RIGHT')
        self.assertEqual((work / 'metrics.txt').read_text(), self.plan['nodes'][0]['params']['label'])

    def test_binary_pipe_and_copy_preserve_bytes(self):
        result, work = self.invoke(5)
        self.assertEqual(result.returncode, 0, result.stderr.decode())
        self.assertEqual((work / 'stream.bin').read_bytes(), b'A\x00B\xff\n')
        self.assertEqual((work / 'nested/copied.bin').read_bytes(), b'A\x00B\xff\n')

    def test_pipe_producer_failure_is_not_hidden_by_successful_sink(self):
        script = embedded_script(self.document['$graph'][5]).replace("'emit'", "'fail'")
        result, _ = self.invoke(5, script_override=script)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(b'producer 9, sink 0', result.stderr)

    def test_asset_integrity_mismatch_stops_external_execution(self):
        (self.pack / 'fixture.py').write_text('raise Exception("must not execute")')
        result, _ = self.invoke(1)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(b'Pinned file SHA-256 mismatch', result.stderr)
        self.assertNotIn(b'must not execute', result.stderr)

    def test_later_command_cannot_mutate_completed_output(self):
        process = self.document['$graph'][5]
        namespace = {'__name__': 'fixture'}
        exec(embedded_script(process), namespace)
        config = namespace['CONFIG']
        config['steps'].append({'id': 'mutate', 'kind': 'exec', 'tool': 'python', 'stdout': '', 'produces': [],
                                'args': ['-c', 'import pathlib,sys;pathlib.Path(sys.argv[1]).write_bytes(b"MUTATED")', '{output:stream}']})
        from cwl_export import RUNNER
        result, work = self.invoke(5, script_override='CONFIG = ' + repr(config) + '\n' + RUNNER)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(b'Pinned file SHA-256 mismatch', result.stderr)
        self.assertEqual((work / 'nested/copied.bin').read_bytes(), b'A\x00B\xff\n')

    @unittest.skipUnless(os.environ.get('NW_CWLTOOL'), 'Set NW_CWLTOOL for independent CWL validation/execution')
    def test_independent_cwltool_validates_and_executes_branch_pair_merge_report(self):
        cwl = self.root / 'workflow.cwl'
        cwl.write_text(json.dumps(self.document, indent=2), encoding='utf-8')
        command = os.environ['NW_CWLTOOL']
        validation = subprocess.run([command, '--validate', str(cwl)], capture_output=True, text=True)
        self.assertEqual(validation.returncode, 0, validation.stderr)
        output = self.root / 'cwl outputs'
        output.mkdir()
        job = self.root / 'job.json'
        job.write_text(json.dumps({'nw_python': sys.executable}), encoding='utf-8')
        execution = subprocess.run([command, '--no-container', '--outdir', str(output), str(cwl), str(job)], capture_output=True, text=True)
        self.assertEqual(execution.returncode, 0, execution.stderr)
        products = json.loads(execution.stdout)
        from urllib.parse import unquote, urlparse
        def read(key):
            return Path(unquote(urlparse(products[key]['location']).path)).read_bytes()
        self.assertEqual(read('step_2_o_trimmed1'), b'R1LEFTLEFT')
        self.assertEqual(read('step_2_o_trimmed2'), b'R2RIGHTRIGHT')
        self.assertEqual(read('step_3_o_merged'), (self.plan['nodes'][1]['params']['label'] + '|' + self.plan['nodes'][0]['params']['label']).encode())
        self.assertIn(b'Counts from different callers or analyses have not been pooled.', read('step_4_o_report'))
        self.assertEqual(read('step_5_o_copied'), b'A\x00B\xff\n')

if __name__ == '__main__':
    unittest.main()
