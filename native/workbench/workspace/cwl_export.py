"""Export a frozen analysis as an executable, packed CWL v1.2 document.

The embedded runner is deliberately independent of Workbench. Pack operations
may contain copies, binary pipes, private interpreters and multiple commands;
preserving those declarations is safer than guessing an upstream CLI mapping.
"""
from __future__ import annotations

import copy
import glob
import hashlib
import json
import ntpath
from pathlib import Path, PureWindowsPath
import re

try:
    from .catalog import parse_pack
    from .pack_manager import filesystem_path
except ImportError:
    from catalog import parse_pack
    from pack_manager import filesystem_path

NAMESPACE = "https://github.com/comparativechrono/workbench/ns#"

# This source is embedded in each CommandLineTool, not imported by the app.
# No shell, network client, Workbench module or CWL-specific Python dependency.
RUNNER = r'''
import hashlib, html, json, os, pathlib, re, shutil, subprocess, sys

def digest(path):
    h = hashlib.sha256()
    with open(path, 'rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()

def verify(path, expected):
    if digest(path) != expected:
        raise ValueError('Pinned file SHA-256 mismatch: ' + str(path))

def local(item):
    # CWL engines commonly stage symlinks. Native adapters require ordinary
    # canonical files; resolving also retains descriptor-relative resources.
    return str(pathlib.Path(item['path']).resolve())

def path_under(root, relative):
    target = (root / relative).resolve()
    if not target.is_relative_to(root.resolve()):
        raise ValueError('Declared path escapes its folder: ' + relative)
    return target

def report(config, values, out):
    sections = []
    for item, attribution in zip(values.get('metrics', []), config['reportSections']):
        path = pathlib.Path(item)
        raw = path.read_bytes() if path.stat().st_size <= 4 * 1024 * 1024 else b'Report exceeds inline size limit; open the named original file.'
        try:
            content = raw.decode('utf-8')
        except UnicodeDecodeError:
            content = 'Binary output; open the named original file.'
        sections.append(dict(attribution, file=str(path), content=content))
    title = html.escape(values.get('title', 'Pipeline report'))
    body = "<!doctype html><html lang='en'><meta charset='utf-8'><title>" + title + "</title><style>body{font:16px system-ui;max-width:1100px;margin:40px auto;padding:0 24px;color:#172638}section{border:1px solid #ccd3dc;border-radius:14px;padding:20px;margin:24px 0}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#f5f7fa;padding:16px}small{overflow-wrap:anywhere}</style><h1>" + title + "</h1><p>Each tool's results are shown separately. Counts from different callers or analyses have not been pooled.</p>"
    for section in sections:
        heading = section['source'] + ' · ' + section['label']
        if 'producer' in section:
            heading = 'S' + section['producer'].split('-')[-1] + ' · ' + section['producerName'] + ' · ' + section['label']
        body += '<section><h2>' + html.escape(heading) + '</h2><small>' + html.escape(section['source'] + ' · ' + section['file']) + '</small><pre>' + html.escape(section['content']) + '</pre></section>'
    body += '</html>'
    for name, filename in out.items():
        if filename.suffix.lower() == '.json':
            filename.write_text(json.dumps({'schema': 1, 'aggregation': 'separate-sections-no-pooled-statistics', 'sections': sections}, indent=2) + '\n', encoding='utf-8')
        else:
            filename.write_text(body, encoding='utf-8')

def run(config, supplied):
    cwd = pathlib.Path.cwd()
    values = {}
    for key, kind in config['inputTypes'].items():
        item = supplied['i_' + key]
        values[key] = ([local(f) for f in item] if kind == 'files' else local(item) if item else '')
    for key in config['parameters']:
        values[key] = supplied['p_' + key]
    input_hashes = {}
    for key, kind in config['inputTypes'].items():
        if kind == 'directory':
            if values[key] and not pathlib.Path(values[key]).is_dir():
                raise ValueError('Directory input is unavailable: ' + values[key])
            continue
        for filename in (values[key] if kind == 'files' else [values[key]]):
            if filename:
                input_hashes[filename] = digest(filename)
    out = {item['id']: path_under(cwd, item['path']) for item in config['outputs']}
    for path in out.values():
        path.parent.mkdir(parents=True, exist_ok=True)
    if config.get('builtin'):
        report(config, values, out)
        return
    pack = pathlib.Path(local(supplied['nw_pack']))
    verify(pack / 'pack.ini', config['manifestSha256'])
    assets = {key: path_under(pack, item['path']) for key, item in config['assets'].items()}
    for key, path in assets.items():
        verify(path, config['assets'][key]['sha256'])
    programs = {}
    for key, item in config['executables'].items():
        override = supplied['exe_' + key]
        programs[key] = local(override) if override else str(path_under(pack, item['path']))
        if not override:
            verify(programs[key], item['sha256'])
    logs = cwd / config['logDirectory']
    logs.mkdir()
    env = {key: value for key, value in os.environ.items() if key.upper() not in config['filteredEnvironment']}
    def expand(text):
        def replace(match):
            kind, _, key = match.group(1).partition(':')
            if kind == 'run': return str(cwd)
            return str({'input': values, 'output': out, 'asset': assets}[kind][key])
        return re.sub(r'\{([^{}]+)\}', replace, text)
    def arguments(items):
        result = []
        for value in items:
            many = re.fullmatch(r'\{inputs:([^{}]+)\}', value)
            if many:
                result.extend(values[many.group(1)])
            else:
                result.append(expand(value))
        return result
    completed = {}
    def check_unchanged():
        for filename, expected in input_hashes.items():
            verify(filename, expected)
        for key, expected in completed.items():
            verify(out[key], expected)
    for step in config['steps']:
        check_unchanged()
        produced = ([step['destination']] if step['kind'] == 'copy' else step['produces'] + ([step['stdout']] if step.get('stdout') else []))
        for key in produced:
            if out[key].exists() or key in completed:
                raise ValueError('Output would be overwritten: ' + str(out[key]))
        if step['kind'] == 'copy':
            shutil.copyfile(expand(step['source']), out[step['destination']])
        else:
            argv = [programs[step['tool']]] + arguments(step['args'])
            stdout = out[step['stdout']] if step.get('stdout') else logs / (step['id'] + '.stdout.log')
            with open(stdout, 'wb') as target, open(logs / (step['id'] + '.stderr.log'), 'wb') as errors:
                if step['kind'] == 'pipe':
                    sink = [programs[step['sinkTool']]] + arguments(step['sinkArgs'])
                    with open(logs / (step['id'] + '.sink.stderr.log'), 'wb') as sink_errors:
                        producer = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=errors, env=env)
                        try:
                            consumer = subprocess.Popen(sink, stdin=producer.stdout, stdout=target, stderr=sink_errors, env=env)
                        except BaseException:
                            producer.stdout.close(); producer.kill(); producer.wait()
                            raise
                        producer.stdout.close()
                        second = consumer.wait()
                        first = producer.wait()
                        if first or second:
                            raise RuntimeError('Pipe failed (producer %d, sink %d)' % (first, second))
                else:
                    subprocess.run(argv, stdout=target, stderr=errors, env=env, check=True)
        for key in produced:
            item = next(item for item in config['outputs'] if item['id'] == key)
            if out[key].is_symlink() or not out[key].resolve().is_relative_to(cwd.resolve()):
                raise ValueError('Declared output is not an ordinary file in its assigned folder: ' + str(out[key]))
            if not out[key].is_file() or (item.get('nonempty', True) and not out[key].stat().st_size):
                raise ValueError('Declared output is missing or empty: ' + str(out[key]))
        check_unchanged()
        completed.update({key: digest(out[key]) for key in produced})
    check_unchanged()

if __name__ == '__main__':
    run(CONFIG, json.loads(pathlib.Path(sys.argv[1]).read_text(encoding='utf-8')))
'''.lstrip()

DOC = """Frozen Native Workbench analysis in standard CWL v1.2 (JSON is valid CWL).
The Workflow contains the actual named data dependencies; every CommandLineTool
embeds a standalone Python 3.10+ runner for the exact pack command arrays, copies
and binary pipes. No Workbench installation/module is needed by that runner.

To rerun with a CWL v1.2 engine, supply Python 3.10+ on PATH as python3 (or bind
nw_python to its executable), and keep/rebind the File and pack Directory inputs.
For example: cwltool --no-container workflow.cwl, or pass a CWL job JSON/YAML.
File/Directory defaults are original local file: URIs; move/rebind them when
sharing. Pack folders and analysis data are NOT embedded or downloaded. Standard
containers are not specified and network access is disabled for command tools.
Database/resource descriptors can name additional files or directories; those
resources must also remain available or be relocated/rebound consistently. CWL
cannot infer such dependencies from an arbitrary descriptor's contents.

Original packs contain pinned Windows x86-64 programs/private runtimes. CWL does
not translate those binaries: use a suitable CWL execution environment or bind
the explicitly exposed exe_* inputs to compatible executable Files on the
target platform. Overrides deliberately replace original executable identity;
their scientific equivalence must be checked. Assets and manifest stay pinned.
SoftwareRequirement hints document versions; they do not install software.

The exporter preserves scientific state/port contracts and original hashes in
nw: metadata. CWL File typing alone does not reproduce Workbench's biological
preflight, reference/header compatibility checks, cancellation/job ownership or
execution scheduler. Independently validate rebinding or changed software. Pack
commands remain trusted native code. Parameters retain their exact CLI strings.
The original run's actual success/failure/cancellation is in nw:execution; a
planned workflow does not assert successful completion. Original run.json and
methods remain the detailed outcome/provenance record.
Complex nw: metadata values are literal JSON strings so CWL schema loaders do
not rewrite Workbench's id/type/path fields as CWL identifiers. Decode these
strings as JSON to inspect complete commands, roles and provenance. nw:execution
has a status plus recordJson containing the original outcome details.
"""


def _file_uri(value):
    text = str(value)
    if ntpath.isabs(text) and (ntpath.splitdrive(text)[0] or text.startswith('\\\\')):
        return PureWindowsPath(text).as_uri()
    return Path(text).absolute().as_uri()


def _plain_id(value):
    # Valid graph IDs are exactly input-N/step-N; reject rather than collapse
    # unexpected IDs into a colliding CWL identifier.
    if not re.fullmatch(r'(?:input|step)-[0-9]+', value):
        raise ValueError('Invalid graph identity for CWL export: ' + value)
    return value.replace('-', '_')


def _metadata(value):
    # Schema Salad recursively interprets unqualified id/type/path/source keys
    # even inside extensions. Opaque JSON preserves their literal provenance.
    return json.dumps(value, ensure_ascii=True, separators=(',', ':'))


def _basename(value):
    return re.sub(r'[^A-Za-z0-9._+-]', '_', ntpath.basename(str(value))) or 'input'


def _source_fields(source, port):
    files = source.get('files', {})
    wanted = port.get('manifestInputs', [port['id']])
    if all(key in files for key in wanted):
        return dict(zip(wanted, wanted))
    if len(wanted) == len(files) == 1:
        return {wanted[0]: next(iter(files))}
    if len(wanted) == 2:
        for first, second in (('reads1', 'reads2'), ('read1', 'read2')):
            if set(files) == {first, second}:
                return dict(zip(wanted, (first, second)))
    raise ValueError('CWL export cannot resolve explicit file roles for ' + source['id'])


def _outputs(tool):
    return [copy.deepcopy(field) for output in tool.get('outputs', []) for field in output.get('fields', [])]


def _execution(run):
    if run is None:
        return {'status': 'planned', 'description': 'Prepared workflow; execution has not completed.'}
    result = {key: copy.deepcopy(run[key]) for key in ('status', 'success', 'started', 'finished', 'planSha256') if key in run}
    result['recordJson'] = _metadata({key: run[key] for key in ('id', 'status', 'success', 'started', 'finished', 'planSha256', 'nodes', 'outputs', 'batch', 'project', 'recovery', 'resources', 'resourceScope', 'temporaryStorage') if key in run})
    return result


def update_run_status(document, run):
    """Update outcome metadata without rediscovering or changing frozen commands."""
    result = copy.deepcopy(document)
    result['$graph'][0]['nw:execution'] = _execution(run)
    return result


def definition_sha256(document):
    """Bind CWL commands/bindings to the plan without a recursive hash.

    Only the main workflow's reciprocal plan hash and changing outcome are
    excluded. Process bodies, inputs, parameters and all other metadata remain
    covered, including similarly named fields on any other process.
    """
    definition = copy.deepcopy(document)
    main = definition['$graph'][0]
    if main.get('id') != '#main' or main.get('class') != 'Workflow':
        raise ValueError('CWL export has no expected main workflow')
    main.pop('nw:planSha256', None)
    main.pop('nw:execution', None)
    raw = json.dumps(definition, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf-8')
    return hashlib.sha256(raw).hexdigest()


def export_workflow(plan, app_root, run=None):
    """Create one self-contained CWL document from a validated, frozen plan."""
    app_root = Path(app_root)
    sources = {item['id']: item for item in plan['graph']['sources']}
    nodes = {item['id']: item for item in plan['nodes']}
    main = {'id': '#main', 'class': 'Workflow', 'label': plan['graph'].get('name', 'Native Workbench analysis'),
            'doc': DOC, 'inputs': {}, 'outputs': {}, 'steps': {},
            'requirements': {'MultipleInputFeatureRequirement': {}},
            'nw:planSha256': plan.get('sha256', ''), 'nw:runId': plan['id'],
            'nw:created': plan.get('created', ''), 'nw:execution': _execution(run),
            'nw:references': _metadata(plan.get('references', {})),
            'nw:scheduler': plan.get('scheduler', 'sequential-independent-branches')}
    if 'batch' in plan:
        main['nw:batch'] = _metadata(plan['batch'])
    for key in ('recovery', 'resources', 'project'):
        if key in plan:
            main['nw:' + key] = _metadata(plan[key])
    if 'referenceIndexPolicy' in plan:
        main['nw:referenceIndexPolicy'] = plan['referenceIndexPolicy']
    main['inputs']['nw_python'] = {'type': 'string', 'default': 'python3', 'label': 'Python 3.10+ executable for CWL runner'}
    processes, links, manifests = [], {}, {}
    used = {ref for node in nodes.values() for refs in node['inputs'].values() for ref in refs if '::' not in ref}
    for source_id, source in sources.items():
        if source_id not in used:
            continue
        for index, (field, path) in enumerate(source['files'].items()):
            identity = _plain_id(source_id) + '_file_' + str(index + 1)
            evidence = plan.get('inputs', {}).get(path, {})
            source_class = 'Directory' if source.get('type') == 'directory' else 'File'
            main['inputs'][identity] = {'type': source_class, 'label': source.get('label', source_id) + ' · ' + field,
                'default': {'class': source_class, 'location': _file_uri(path), 'basename': _basename(path)},
                'nw:source': _metadata({'id': source_id, 'field': field, 'type': source.get('type'), 'state': source.get('state', {}), 'evidence': evidence})}
            links[(source_id, field)] = identity
    for node in nodes.values():
        tool = node['tool']
        node_id = _plain_id(node['id'])
        process_id = 'operation_' + node_id
        outputs = _outputs(tool)
        config = {'inputTypes': {}, 'parameters': list(node['params']), 'outputs': outputs,
                  'steps': copy.deepcopy(tool.get('steps', [])), 'manifestSha256': tool['manifestSha256'],
                  'executables': {}, 'assets': {}, 'filteredEnvironment': ['JAVA_TOOL_OPTIONS', '_JAVA_OPTIONS', 'JDK_JAVA_OPTIONS', 'CLASSPATH', 'PERL5OPT', 'PERL5LIB', 'PERLLIB', 'PERL5SHELL', 'PERL_UNICODE', 'PERLIO', 'PERLIO_DEBUG']}
        process = {'id': '#' + process_id, 'class': 'CommandLineTool', 'label': node['label'],
                   'doc': 'Exact frozen pack operation. ' + tool.get('description', ''),
                   'inputs': {'nw_python': 'string'}, 'outputs': {}, 'arguments': [],
                   'requirements': {'InlineJavascriptRequirement': {}, 'NetworkAccess': {'networkAccess': False}},
                   'nw:operation': _metadata(tool), 'nw:parameters': _metadata(node['params'])}
        bindings = {'nw_python': 'nw_python'}
        if tool.get('builtin') or tool['id'] == 'builtin/report':
            if tool.get('builtin') not in (None, 'report'):
                raise ValueError('Unsupported built-in CWL export operation: ' + tool['id'])
            config['builtin'] = 'report'
            config['reportSections'] = []
            for refs in node['inputs'].values():
                for ref in refs:
                    if ref in sources:
                        item = sources[ref]
                        section = {'source': ref, 'label': item.get('label', ref)}
                    else:
                        producer, output_id = ref.split('::', 1)
                        item = next(output for output in nodes[producer]['tool']['outputs'] if output['id'] == output_id)
                        section = {'source': ref, 'label': item['label'], 'producer': producer, 'producerName': nodes[producer]['label']}
                    config['reportSections'].extend(copy.deepcopy(section) for _ in item.get('files', {}))
        else:
            pack_key = (tool['packFolder'], tool['manifestSha256'])
            if pack_key not in manifests:
                folder = app_root / tool['packFolder']
                raw = filesystem_path(folder / 'pack.ini').read_bytes()
                if hashlib.sha256(raw).hexdigest() != tool['manifestSha256']:
                    raise ValueError('Pack manifest changed before CWL export: ' + tool['packId'])
                manifests[pack_key] = parse_pack(raw.decode('utf-8-sig'))
            pack = manifests[pack_key]
            config['assets'] = copy.deepcopy(pack['assets'])
            config['executables'] = {item['id']: copy.deepcopy(item) for item in tool['executables']}
            pack_input = node_id + '_pack'
            main['inputs'][pack_input] = {'type': 'Directory', 'label': tool['packId'] + ' ' + tool['packVersion'] + ' pack directory',
                'default': {'class': 'Directory', 'location': _file_uri(app_root / tool['packFolder']), 'basename': node_id + '_pack'},
                'nw:manifestSha256': tool['manifestSha256'], 'nw:platform': 'windows-x86_64'}
            process['inputs']['nw_pack'] = {'type': 'Directory', 'loadListing': 'no_listing'}
            bindings['nw_pack'] = pack_input
            packages = [{'package': item['id'], 'version': [item['version']]} for item in tool['executables']]
            process['hints'] = [{'class': 'SoftwareRequirement', 'packages': packages}]
            for executable in tool['executables']:
                key = 'exe_' + executable['id']
                override = node_id + '_' + key
                main['inputs'][override] = {'type': ['null', 'File'], 'default': None,
                    'label': 'Optional compatible replacement for ' + executable['id'],
                    'doc': 'Leave null to use/hash-check the original pinned executable in the pack.'}
                process['inputs'][key] = ['null', 'File']
                bindings[key] = override
        for parameter in tool.get('params', []):
            key = 'p_' + parameter['id']
            external = node_id + '_' + key
            main['inputs'][external] = {'type': 'string', 'default': str(node['params'][parameter['id']]),
                'label': node['label'] + ' · ' + parameter['label'], 'nw:parameter': _metadata(parameter)}
            process['inputs'][key] = 'string'
            bindings[key] = external
        for port in tool.get('ports', []):
            wanted = port.get('manifestInputs', [port['id']])
            collected = {field: [] for field in wanted}
            for ref in node['inputs'].get(port['id'], []):
                if ref in sources:
                    mapping = _source_fields(sources[ref], port)
                    for field, source_field in mapping.items():
                        collected[field].append(links[(ref, source_field)])
                else:
                    producer, output_id = ref.split('::', 1)
                    output = next(item for item in nodes[producer]['tool']['outputs'] if item['id'] == output_id)
                    actual = output.get('manifestOutputs', list(output['files']))
                    if len(wanted) != len(actual):
                        raise ValueError('CWL output/input file roles differ: ' + ref)
                    for field, produced in zip(wanted, actual):
                        collected[field].append(_plain_id(producer) + '/o_' + produced)
            for field in port['fields']:
                key = 'i_' + field['id']
                many = field['type'] == 'files'
                item_class = 'Directory' if field['type'] == 'directory' else 'File'
                config['inputTypes'][field['id']] = field['type']
                process['inputs'][key] = {'type': {'type': 'array', 'items': 'File'} if many else item_class if field.get('required', True) else ['null', item_class],
                                          'label': field['label'], 'nw:port': _metadata(port)}
                connected = collected[field['id']]
                if many:
                    bindings[key] = {'source': connected, 'linkMerge': 'merge_flattened'} if connected else {'default': []}
                else:
                    if len(connected) > 1:
                        raise ValueError('Multiple sources connected to scalar CWL input: ' + key)
                    bindings[key] = connected[0] if connected else {'default': None}
        for output in outputs:
            key = 'o_' + output['id']
            process['outputs'][key] = {'type': 'File', 'label': output['label'], 'outputBinding': {
                'glob': '${return ' + json.dumps(glob.escape(output['path'])) + ';}',
                'outputEval': '${if (self.length !== 1) {throw new Error("Expected one declared output");} var f = self[0]; f.basename = ' + json.dumps(_basename(output['path'])) + '; return f;}'}}
            main['outputs'][node_id + '_' + key] = {'type': 'File', 'label': node['label'] + ' · ' + output['label'], 'outputSource': node_id + '/' + key}
        prefix = '.native-workbench-cwl-' + hashlib.sha256(node['id'].encode()).hexdigest()[:12]
        # Keep helpers clear of every manifest-owned path, including directories.
        while any(item['path'].split('/')[0].startswith(prefix) for item in outputs):
            prefix += '_'
        config['logDirectory'] = prefix + '-logs'
        script = 'CONFIG = ' + repr(config) + '\n' + RUNNER
        process['requirements']['InitialWorkDirRequirement'] = {'listing': [
            {'entryname': prefix + '.py', 'entry': '${return ' + json.dumps(script, ensure_ascii=True) + ';}'},
            {'entryname': prefix + '.json', 'entry': '$(JSON.stringify(inputs))'}]}
        process['arguments'] = [
            {'position': 0, 'valueFrom': '$(inputs.nw_python)'},
            {'position': 1, 'valueFrom': prefix + '.py'},
            {'position': 2, 'valueFrom': prefix + '.json'}]
        main['steps'][node_id] = {'label': node['label'], 'run': '#' + process_id, 'in': bindings, 'out': list(process['outputs'])}
        processes.append(process)
    return {'cwlVersion': 'v1.2', '$namespaces': {'nw': NAMESPACE}, '$graph': [main] + processes}
