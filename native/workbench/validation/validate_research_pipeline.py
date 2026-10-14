#!/usr/bin/env python3
"""Execute actual pack manifests with Linux/portable argv overrides and truth.

Generate fixtures: --output NEW_DIRECTORY --fixtures-only
Run checks: --output NEW_DIRECTORY --plan plan.json
Plan shape:
{"tools":{"linux":{"python":["/venv/bin/python"],"bwa":["/bwa-linux"]},
          "portable":{"python":["/venv/bin/python"],"bwa":["/ape","/bwa.exe"]}},
 "runs":[{"id":"tiny-bwa","pack":"/packs/research/pack.ini",
           "workflow":"cutadapt-bwa-bcftools","inputs":{"reads1":"..."},
           "checks":{"variants":"variants","truth_tsv":"..."}}]}

The plan can specify checks.trim_truth plus trim_outputs mapping expected
logical files (paired1/paired2/rejected1/rejected2) to manifest output IDs.
No network or shell execution. This validates tools/manifest steps on Linux,
not the native Windows runner. Each test directory must be new.
"""
import argparse
import configparser
import gzip
import hashlib
import json
import os
from pathlib import Path
import platform
import random
import re
import shutil
import signal
import subprocess
import sys
import time

from validate_variant_pipeline import fixture as variant_fixture
from validate_variant_pipeline import sam_signature


def digest(path):
    with Path(path).open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def save(path, value):
    Path(path).write_text(json.dumps(value, indent=2) + '\n', encoding='utf-8')


def artifact_snapshot(path):
    """Check gzip framing independently and retain immutable produced bytes."""
    path = Path(path)
    result = {'path': str(path), 'bytes': path.stat().st_size, 'sha256': digest(path)}
    if path.name.endswith(('.fastq.gz', '.fq.gz')):
        decoded, size = hashlib.sha256(), 0
        with gzip.open(path, 'rb') as stream:
            while block := stream.read(1024 * 1024):
                decoded.update(block)
                size += len(block)
        result.update(gzip_complete=True, decoded_bytes=size, decoded_sha256=decoded.hexdigest())
    return result


def fastq_records(path):
    path = Path(path)
    opener = gzip.open if path.suffix == '.gz' else open
    result = []
    with opener(path, 'rt', encoding='ascii', newline='') as f:
        while True:
            name = f.readline()
            if not name:
                break
            sequence, plus, quality = f.readline(), f.readline(), f.readline()
            name, sequence, plus, quality = (x.rstrip('\r\n') for x in (name, sequence, plus, quality))
            if not name.startswith('@') or not plus.startswith('+') or len(sequence) != len(quality):
                raise ValueError('Invalid FASTQ: ' + str(path))
            result.append({'name': name[1:], 'sequence': sequence, 'quality': quality})
    return result


def write_fastq(path, records):
    with Path(path).open('w', encoding='ascii', newline='\n') as f:
        for r in records:
            f.write('@' + r['name'] + '\n' + r['sequence'] + '\n+\n' + r['quality'] + '\n')


def trimming_fixture(folder):
    folder.mkdir()
    rng = random.Random(40420261002)
    adapters = ['CTGTCTCTTATACACATCTCCGAGCCCACGAGAC', 'GATCGTCGGACTGTAGAACTCTGAACGTGTACG']
    expected = {k: [] for k in ('paired1', 'paired2', 'rejected1', 'rejected2')}
    adapter_only = {k: [] for k in expected}
    quality_only = {k: [] for k in expected}
    raw = [[], []]
    cases = [
        ('clean', (120, 120), (False, False), (0, 0), False),
        ('adapter', (80, 90), (True, True), (0, 0), False),
        ('quality_tail', (75, 90), (False, False), (12, 18), False),
        ('mate2_short', (80, 30), (True, True), (0, 0), True),
        ('mate1_short', (30, 80), (True, True), (0, 0), True),
        ('both_short', (30, 30), (True, True), (0, 0), True),
        ('boundary', (50, 50), (True, True), (0, 0), False),
    ]
    for name, lengths, contaminated, tails, rejected in cases:
        for mate in (0, 1):
            # Avoid incidental short adapter-prefix matches at clean endpoints.
            while True:
                clean = ''.join(rng.choice('ACGT') for _ in range(lengths[mate]))
                if not any(clean.endswith(adapters[mate][:n]) for n in range(3, 12)):
                    break
            suffix = adapters[mate] if contaminated[mate] else ''
            tail = ''.join(rng.choice('ACGT') for _ in range(tails[mate]))
            record_name = f'{name}/{mate + 1}'
            raw[mate].append({'name': record_name, 'sequence': clean + suffix + tail,
                              'quality': 'I' * (len(clean) + len(suffix)) + '!' * len(tail)})
            expected[('rejected' if rejected else 'paired') + str(mate + 1)].append(
                {'name': record_name, 'sequence': clean, 'quality': 'I' * len(clean)})
            adapter_only[('rejected' if rejected else 'paired') + str(mate + 1)].append(
                {'name': record_name, 'sequence': clean + tail,
                 'quality': 'I' * len(clean) + '!' * len(tail)})
            quality_only['paired' + str(mate + 1)].append(
                {'name': record_name, 'sequence': clean + suffix, 'quality': 'I' * (len(clean) + len(suffix))})
    for mate in (1, 2):
        write_fastq(folder / f'reads{mate}.fastq', raw[mate - 1])
    for name, records in expected.items():
        write_fastq(folder / ('expected-' + name + '.fastq'), records)
    (folder / 'adapters.fa').write_text('>synthetic_R1\n' + adapters[0] + '\n>synthetic_R2\n' + adapters[1] + '\n')
    truth = {'seed': 40420261002, 'adapters': adapters, 'quality_cutoff': 20, 'minimum_length': 50,
             'pair_filter': 'any', 'input_pairs': 7, 'retained_pairs': 4, 'rejected_pairs': 3,
             'note': 'Constructed clean inserts define exact endpoints independently of trimmer output. Synthetic adapters are not kit recommendations.',
             'expected': expected, 'expected_adapter_only': adapter_only, 'expected_quality_only': quality_only}
    save(folder / 'truth.json', truth)
    return truth


def check_cutadapt_fixture(python, fixture_folder, output):
    """Focused independent oracle check while generated full packs are building."""
    truth = json.loads((fixture_folder / 'truth.json').read_text())
    report = {'status': 'running', 'cutadapt_python': str(python), 'runs': [],
              'note': 'Linux reference Cutadapt 5.2 algorithm checks; Windows private runtime is not executed here.'}
    for mode in ('adapter_quality', 'adapter_only', 'quality_only'):
        folder = output / mode
        folder.mkdir()
        files = {name: folder / (name + '.fastq.gz') for name in truth['expected']}
        args = [str(python), '-I', '-B', '-m', 'cutadapt', '--cores', '2', '--quality-base', '33',
                '--minimum-length', '50', '--pair-filter', 'any', '--json', str(folder / 'cutadapt.json'),
                '-o', str(files['paired1']), '-p', str(files['paired2']),
                '--too-short-output', str(files['rejected1']), '--too-short-paired-output', str(files['rejected2'])]
        if mode != 'quality_only': args += ['-a', truth['adapters'][0], '-A', truth['adapters'][1], '-O', '3', '-e', '0.1']
        if mode != 'adapter_only': args += ['-q', '20', '-Q', '20']
        args += [str(fixture_folder / 'reads1.fastq'), str(fixture_folder / 'reads2.fastq')]
        with (folder / 'stdout.log').open('xb') as out, (folder / 'stderr.log').open('xb') as err:
            process = subprocess.run(args, stdout=out, stderr=err, check=False, timeout=120)
        oracle = truth[{'adapter_quality': 'expected', 'adapter_only': 'expected_adapter_only', 'quality_only': 'expected_quality_only'}[mode]]
        comparisons = {name: files[name].is_file() and fastq_records(files[name]) == records for name, records in oracle.items()}
        report['runs'].append({'mode': mode, 'argv': args, 'exit_code': process.returncode, 'exact_cleaned_sequences_and_qualities': comparisons,
                               'passed': process.returncode == 0 and all(comparisons.values())})
    report['status'] = 'passed' if all(x['passed'] for x in report['runs']) else 'failed'
    save(output / 'cutadapt-fixture-validation.json', report)
    return report


def load_manifest(path, workflow):
    config = configparser.ConfigParser(interpolation=None, strict=True)
    config.optionxform = str
    with Path(path).open(encoding='utf-8-sig') as f:
        config.read_file(f)
    section = config['workflow:' + workflow]
    ids = lambda key: [x.strip() for x in section.get(key, '').split(',') if x.strip()]
    return config, {key: ids(key) for key in ('inputs', 'outputs', 'steps')}


def beneath(folder, relative):
    relative = relative.replace('\\', '/')
    path = (folder / relative).resolve()
    if Path(relative).is_absolute() or not path.is_relative_to(folder.resolve()) or path == folder.resolve():
        raise ValueError('Output escapes run directory: ' + relative)
    return path


def normalized_vcf(path):
    h = hashlib.sha256()
    rows, metadata = [], []
    opener = gzip.open if str(path).endswith('.gz') else open
    with opener(path, 'rb') as f:
        for line in f:
            if (re.match(rb'##bcftools[^=]*(?:Version|Command)=', line)
                    or line.startswith((b'##reference=', b'##fileDate=', b'##commandline=', b'##commandLine='))):
                metadata.append(line.split(b'=', 1)[0].decode())
                continue
            h.update(line)
            if line.startswith(b'#'):
                continue
            fields = line.decode().rstrip('\r\n').split('\t')
            if len(fields) != 10:
                raise ValueError('Expected a single-sample VCF')
            fmt = dict(zip(fields[8].split(':'), fields[9].split(':')))
            rows.append({'chrom': fields[0], 'pos': int(fields[1]), 'ref': fields[3], 'alt': fields[4],
                         'gt': fmt.get('GT'), 'filter': fields[6], 'record': line.decode().rstrip('\r\n')})
    return {'sha256': h.hexdigest(), 'records': len(rows), 'pass_records': sum(x['filter'] == 'PASS' for x in rows),
            'omitted_metadata_keys': sorted(set(metadata))}, rows


def run_workflow(run, backend, tools, destination):
    destination.mkdir(parents=True, exist_ok=False)
    packfile = Path(run['pack']).resolve(strict=True)
    pack = packfile.parent
    workflow = run['workflow']
    config, ids = load_manifest(packfile, workflow)
    inputs = {key: config[f'input:{workflow}:{key}'].get('default', '') for key in ids['inputs']}
    inputs.update(run['inputs'])
    for key in ids['inputs']:
        definition = config[f'input:{workflow}:{key}']
        if definition.get('required', 'true') == 'true' and inputs.get(key, '') == '':
            raise ValueError('Missing input: ' + key)
        if definition['type'] in ('file', 'directory'):
            inputs[key] = str(Path(inputs[key]).resolve(strict=True))
        elif definition['type'] == 'files':
            inputs[key] = [str(Path(x).resolve(strict=True)) for x in inputs[key]]
        else:
            inputs[key] = str(inputs[key])
    outputs = {key: beneath(destination, config[f'output:{workflow}:{key}']['path']) for key in ids['outputs']}
    assets = {name[6:]: str((pack / config[name]['path'].replace('\\', '/')).resolve(strict=True))
              for name in config.sections() if name.startswith('asset:')}
    evidence = {'id': run['id'], 'backend': backend, 'pack_sha256': digest(packfile), 'workflow': workflow,
                'inputs': inputs, 'steps': [], 'status': 'running', 'artifacts': {}}
    input_paths = []
    for key in ids['inputs']:
        kind = config[f'input:{workflow}:{key}']['type']
        if kind == 'file': input_paths.append(Path(inputs[key]))
        if kind == 'files': input_paths.extend(map(Path, inputs[key]))
    source_hashes = {str(p): digest(p) for p in input_paths}
    evidence['input_sha256_before'] = source_hashes
    produced_snapshots = {}

    def verify_produced(key):
        previous = produced_snapshots.get(key)
        if previous and (not outputs[key].is_file() or digest(outputs[key]) != previous['sha256']):
            raise ValueError('Previously produced output changed: ' + key)

    def expand(value):
        def replace(m):
            token = m[1]
            if token == 'run': return str(destination)
            kind, key = token.split(':', 1)
            return str({'input': inputs, 'output': outputs, 'asset': assets}[kind][key])
        return re.sub(r'\{([^{}]+)\}', replace, value)

    def invoke(tool, args, stdout, stderr):
        command = list(tools[tool]) + list(map(str, args))
        with Path(stdout).open('xb') as out, Path(stderr).open('xb') as err:
            done = subprocess.run(command, cwd=destination, stdin=subprocess.DEVNULL, stdout=out, stderr=err, timeout=1800)
        if done.returncode:
            raise RuntimeError(f'{tool}: exit {done.returncode}; see {stderr}')
        return command

    def pipe(row, producer, sink, stdout, producer_stderr, sink_stderr):
        children = []
        row.update(argv=producer, sink_argv=sink, producer_stderr=str(producer_stderr), sink_stderr=str(sink_stderr))
        try:
            with Path(stdout).open('xb') as out, Path(producer_stderr).open('xb') as err1, Path(sink_stderr).open('xb') as err2:
                first = subprocess.Popen(producer, cwd=destination, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                         stderr=err1, start_new_session=True)
                children.append(first)
                try:
                    second = subprocess.Popen(sink, cwd=destination, stdin=first.stdout, stdout=out,
                                              stderr=err2, start_new_session=True)
                    children.append(second)
                finally:
                    first.stdout.close()
                row['sink_exit_code'] = second.wait(timeout=1800)
                if row['sink_exit_code'] and first.poll() is None:
                    os.killpg(first.pid, signal.SIGTERM)
                row['producer_exit_code'] = first.wait(timeout=30)
                if row['producer_exit_code'] or row['sink_exit_code']:
                    raise RuntimeError(f'Pipeline producer={row["producer_exit_code"]}, sink={row["sink_exit_code"]}')
        finally:
            for child in children:
                if child.poll() is None:
                    os.killpg(child.pid, signal.SIGTERM)
            for child in children:
                try: child.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    os.killpg(child.pid, signal.SIGKILL)
                    child.wait()

    try:
        for step_id in ids['steps']:
            step = config[f'step:{workflow}:{step_id}']
            row = {'id': step_id, 'kind': step['kind']}
            evidence['steps'].append(row)
            # Recheck every previously produced artifact referenced by this
            # step before a consumer can accept stale or altered bytes.
            for value in step.values():
                for key in re.findall(r'\{output:([^{}]+)\}', value):
                    verify_produced(key)
            if step['kind'] == 'copy':
                source, target = Path(expand(step['source'])), outputs[step['destination']]
                if target.exists(): raise FileExistsError(target)
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, target)
                row.update(source=str(source), destination=str(target))
                produces = [step['destination']]
            elif step['kind'] in ('exec', 'pipe'):
                def arguments(prefix):
                    values = []
                    for _, value in sorted((int(k[len(prefix):]), v) for k, v in step.items() if k.startswith(prefix)):
                        multiple = re.fullmatch(r'\{inputs:([^}]+)\}', value)
                        values.extend(inputs[multiple[1]] if multiple else [expand(value)])
                    return values
                args = arguments('arg.')
                tool = step['tool']
                if tool in ('samtools', 'bcftools') and any(x in ('-@', '--threads') for x in args):
                    raise ValueError('Unsupported portable HTSlib compression threading requested')
                stdout = outputs[step['stdout']] if step.get('stdout') else destination / (step_id + '.stdout.log')
                stderr = destination / (step_id + '.stderr.log')
                stdout.parent.mkdir(parents=True, exist_ok=True)
                row.update(tool=tool, argv=list(tools[tool]) + args, stderr=str(stderr), stdout=str(stdout))
                if step['kind'] == 'pipe':
                    sink_args = arguments('sink-arg.')
                    sink_tool = step['sink-tool']
                    if sink_tool in ('samtools', 'bcftools') and any(x in ('-@', '--threads') for x in sink_args):
                        raise ValueError('Unsupported portable HTSlib compression threading requested')
                    pipe(row, list(tools[tool]) + args, list(tools[sink_tool]) + sink_args,
                         stdout, stderr, destination / (step_id + '.sink.stderr.log'))
                else:
                    row['argv'] = invoke(tool, args, stdout, stderr)
                    row['exit_code'] = 0
                produces = [x for x in step.get('produces', '').split(',') if x]
                if step.get('stdout'): produces.append(step['stdout'])
            else:
                raise ValueError('Unsupported step kind: ' + step['kind'])
            row['produced_artifacts'] = {}
            for key in dict.fromkeys(produces):
                if not outputs[key].is_file(): raise ValueError('Missing output: ' + key)
                snapshot = artifact_snapshot(outputs[key])
                row['produced_artifacts'][key] = snapshot
                produced_snapshots[key] = snapshot
            row['status'] = 'success'
        for key, path in outputs.items():
            definition = config[f'output:{workflow}:{key}']
            if not path.is_file() or (definition.get('nonempty', 'true') == 'true' and not path.stat().st_size):
                raise ValueError('Missing/empty required output: ' + key)
            verify_produced(key)
            evidence['artifacts'][key] = artifact_snapshot(path)
        checks = run.get('checks', {})
        if checks.get('trim_truth'):
            truth = json.loads(Path(checks['trim_truth']).read_text())
            for logical, output_id in checks['trim_outputs'].items():
                if fastq_records(outputs[output_id]) != truth['expected'][logical]:
                    raise ValueError('Independent trimming truth mismatch: ' + logical)
            evidence['trim_truth'] = {'passed': True, 'checked_outputs': list(checks['trim_outputs'])}
        if checks.get('bam'):
            bam = outputs[checks['bam']]
            decoded = destination / 'validation.decoded.sam'
            invoke('samtools', ['view', '-h', bam], decoded, destination / 'validation.decode-bam.stderr.log')
            evidence['bam'] = sam_signature(decoded)
            invoke('samtools', ['quickcheck', '-v', bam], destination / 'validation.quickcheck.stdout.log', destination / 'validation.quickcheck.stderr.log')
            if checks.get('bam_index'):
                contig, length = None, None
                with decoded.open() as f:
                    for line in f:
                        if line.startswith('@SQ\t'):
                            tags = dict(x.split(':', 1) for x in line.rstrip().split('\t')[1:])
                            contig, length = tags['SN'], int(tags['LN'])
                            break
                if contig is None: raise ValueError('BAM has no reference sequences')
                end = min(length, 10000)
                region = f'{contig}:1-{end}'
                streamed_count = 0
                with decoded.open() as f:
                    for line in f:
                        if line.startswith('@'): continue
                        fields = line.rstrip().split('\t')
                        streamed_count += fields[2] == contig and 0 < int(fields[3]) <= end
                indexed = destination / 'validation.indexed-bam-count.txt'
                invoke('samtools', ['view', '-c', '-X', bam, outputs[checks['bam_index']], region],
                       indexed, destination / 'validation.indexed-bam.stderr.log')
                if int(indexed.read_text().strip()) != streamed_count:
                    raise ValueError('BAM indexed query disagrees with decoded records')
                evidence['bam_index'] = {'region': region, 'count': streamed_count, 'passed': True}
        if checks.get('variants'):
            decoded = destination / 'validation.decoded.vcf'
            invoke('bcftools', ['view', '-Ov', outputs[checks['variants']]], decoded, destination / 'validation.decode-vcf.stderr.log')
            evidence['vcf'], rows = normalized_vcf(decoded)
            if checks.get('variants_index'):
                # Explicit CSI selection ensures that this checks the declared
                # index, not a different neighbouring index chosen implicitly.
                region = evidence.get('bam_index', {}).get('region', checks.get('region'))
                if not region: raise ValueError('An index query region is required without a BAM index check')
                contig, interval = region.rsplit(':', 1)
                begin, end = map(int, interval.split('-'))
                queried = destination / 'validation.indexed-vcf.txt'
                indexed_path = str(outputs[checks['variants']]) + '##idx##' + str(outputs[checks['variants_index']])
                fmt = '%CHROM\t%POS\t%REF\t%ALT[\t%GT]\n'
                invoke('bcftools', ['query', '-r', region, '--regions-overlap', '0', '-f', fmt, indexed_path],
                       queried, destination / 'validation.indexed-vcf.stderr.log')
                expected_query = ''.join(f'{r["chrom"]}\t{r["pos"]}\t{r["ref"]}\t{r["alt"]}\t{r["gt"]}\n'
                                         for r in rows if r['chrom'] == contig and begin <= r['pos'] <= end)
                if queried.read_text() != expected_query:
                    raise ValueError('VCF indexed query disagrees with decoded records')
                evidence['vcf_index'] = {'region': region, 'passed': True}
            if checks.get('truth_tsv'):
                actual = [f'{r["chrom"]}\t{r["pos"]}\t{r["ref"]}\t{r["alt"]}\t{r["gt"]}' for r in rows]
                expected = [x for x in Path(checks['truth_tsv']).read_text().splitlines() if x and not x.startswith('#')]
                if actual != expected: raise ValueError('Known normalized allele/genotype truth mismatch')
                evidence['known_truth_variants'] = len(expected)
            if checks.get('pass_variants'):
                passed = destination / 'validation.pass.vcf'
                invoke('bcftools', ['view', '-Ov', outputs[checks['pass_variants']]], passed, destination / 'validation.decode-pass.stderr.log')
                evidence['pass_vcf'], pass_rows = normalized_vcf(passed)
                if pass_rows != [r for r in rows if r['filter'] == 'PASS']:
                    raise ValueError('PASS-only VCF does not exactly select PASS records')
        if source_hashes != {p: digest(p) for p in source_hashes}:
            raise ValueError('Selected input changed')
        evidence['inputs_unchanged'] = True
        evidence['status'] = 'passed'
    except Exception as error:
        evidence.update(status='failed', error=str(error))
    finally:
        save(destination / 'validation.json', evidence)
    return evidence


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--fixtures-only', action='store_true')
    p.add_argument('--plan', type=Path)
    p.add_argument('--cutadapt-python', type=Path, help='Run independent Cutadapt trimming checks through this Linux Python.')
    p.add_argument('--trimming-fixture', type=Path)
    args = p.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    if args.fixtures_only:
        variant_fixture(output / 'variants')
        trimming_fixture(output / 'trimming')
        print(output)
        return 0
    if args.cutadapt_python:
        if not args.trimming_fixture: p.error('--trimming-fixture is required with --cutadapt-python')
        # Preserve a virtual environment's executable path; resolving its
        # interpreter symlink would silently bypass that environment.
        report = check_cutadapt_fixture(args.cutadapt_python.absolute(), args.trimming_fixture.resolve(), output)
        print(report['status'], output / 'cutadapt-fixture-validation.json')
        return 0 if report['status'] == 'passed' else 1
    if not args.plan: p.error('--plan is required unless --fixtures-only')
    plan = json.loads(args.plan.read_text())
    report = {'schema': 1, 'status': 'running', 'host': platform.platform(),
              'scope': 'Actual pack commands run through Linux/native and portable tool prefixes; not Windows runner execution.',
              'validator_sha256': digest(Path(__file__)), 'plan_sha256': digest(args.plan),
              'started_utc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
              'tools': plan['tools'], 'executables_sha256': {}, 'runs': [], 'comparisons': {}}
    for backend, tools in plan['tools'].items():
        for tool, command in tools.items():
            for arg in command:
                if Path(arg).is_file(): report['executables_sha256'][arg] = digest(arg)
    for run in plan['runs']:
        results = {}
        for backend, tools in plan['tools'].items():
            print(run['id'], backend, flush=True)
            try:
                evidence = run_workflow(run, backend, tools, output / run['id'] / backend)
            except Exception as error:
                evidence = {'id': run['id'], 'backend': backend, 'status': 'failed', 'setup_error': str(error)}
            report['runs'].append(evidence)
            results[backend] = evidence
            save(output / 'validation-summary.json', report)
        if 'linux' in results and 'portable' in results and all(x['status'] == 'passed' for x in results.values()):
            a, b = results['linux'], results['portable']
            comparison = {}
            if 'bam' in a:
                comparison['bam_ordered_equal'] = a['bam']['ordered_sha256_without_PG_header'] == b['bam']['ordered_sha256_without_PG_header']
                comparison['bam_all_fields_equal'] = a['bam']['canonical_records_and_headers_sha256'] == b['bam']['canonical_records_and_headers_sha256']
            if 'vcf' in a: comparison['vcf_scientific_fields_equal'] = a['vcf']['sha256'] == b['vcf']['sha256']
            if 'pass_vcf' in a: comparison['pass_vcf_scientific_fields_equal'] = a['pass_vcf']['sha256'] == b['pass_vcf']['sha256']
            for artifact in run.get('checks', {}).get('equal_artifacts', []):
                comparison['artifact:' + artifact] = a['artifacts'][artifact]['sha256'] == b['artifacts'][artifact]['sha256']
            report['comparisons'][run['id']] = comparison
    report['status'] = 'passed' if (report['runs'] and all(x['status'] == 'passed' for x in report['runs'])
                                      and all(all(x.values()) for x in report['comparisons'].values())) else 'failed'
    report['finished_utc'] = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
    save(output / 'validation-summary.json', report)
    print(output / 'validation-summary.json')
    return 0 if report['status'] == 'passed' else 1


if __name__ == '__main__':
    raise SystemExit(main())
