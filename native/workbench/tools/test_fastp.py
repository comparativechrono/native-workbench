#!/usr/bin/env python3
"""Validate actual upstream fastp Linux and APE builds against known trimming truth."""
import argparse
from collections import Counter
from datetime import datetime, timezone
import gzip
import hashlib
from html import unescape
from html.parser import HTMLParser
import json
from pathlib import Path
import random
import re
import shutil
import subprocess
import time

ROOT = Path(__file__).resolve().parents[1]
ADAPTER1 = 'AGATCGGAAGAGCACACGTCTGAACTCCAGTCA'
ADAPTER2 = 'AGATCGGAAGAGCGTCGTGTAGGGAAAGAGTGT'
COMMANDS = {
    'linux': [str(ROOT / 'baselines/bin/fastp-linux')],
    'cosmo': [str(ROOT / 'baselines/bin/ape-loader-linux'), str(ROOT / 'baselines/bin/fastp-cosmo.exe')],
}


def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def rc(text):
    return text.translate(str.maketrans('ACGT', 'TGCA'))[::-1]


def fasta_records(path):
    opener = gzip.open if path.suffix == '.gz' else open
    with opener(path, 'rt', encoding='ascii') as stream:
        while True:
            name = stream.readline()
            if not name:
                return
            seq, plus, qual = [stream.readline().rstrip('\r\n') for _ in range(3)]
            assert name.startswith('@') and plus == '+' and len(seq) == len(qual), path
            yield name.rstrip('\r\n'), seq, qual


def fixture(directory):
    rng = random.Random(720619)
    records = [[], []]
    expected = [{}, {}]
    bases = 0
    for number in range(120):
        name = f'fixture{number:04d}'
        fragment = ''.join(rng.choice('ACGT') for _ in range(180))
        if number < 50:
            fragment = fragment[:60]
            reads = [fragment + ADAPTER1, rc(fragment) + ADAPTER2]
            quals = ['I' * len(read) for read in reads]
            trimmed = [fragment, rc(fragment)]
        elif number < 100:
            reads = [fragment[:90], rc(fragment[-90:])]
            quals = ['I'*75 + '!'*15]*2
            trimmed = [read[:75] for read in reads]
        elif number < 110:
            reads = [fragment[:90], rc(fragment[-90:])]
            quals = ['!'*90, 'I'*90]
            trimmed = None
        else:
            reads = ['N'*20 + fragment[20:90], rc(fragment[-90:])]
            quals = ['I'*90]*2
            trimmed = None
        for mate in range(2):
            header = f'@{name}/{mate+1}'
            records[mate].append(f'{header}\n{reads[mate]}\n+\n{quals[mate]}\n')
            bases += len(reads[mate])
            if trimmed:
                expected[mate][header] = (trimmed[mate], 'I'*len(trimmed[mate]))
    paths = []
    for mate, rows in enumerate(records, 1):
        path = directory / f'reads {mate}.fastq'
        data = ''.join(rows).encode('ascii')
        path.write_bytes(data)
        path.with_suffix('.fastq.gz').write_bytes(gzip.compress(data, mtime=0))
        paths.append(path)
    return paths, expected, bases


class Scripts(HTMLParser):
    def __init__(self):
        super().__init__()
        self.sources = []
        self.injected_tags = []

    def handle_starttag(self, tag, attrs):
        if any(key == 'id' and value == 'report-escape-regression' for key, value in attrs):
            self.injected_tags.append(tag)
        if tag == 'script':
            self.sources.extend(value for key, value in attrs if key == 'src')


def run_one(target, inputs, folder, flags):
    folder.mkdir(parents=True)
    output = [folder/f'trimmed{mate}.fastq.gz' for mate in (1, 2)]
    report, html = folder/'fastp.json', folder/'fastp.html'
    shutil.copy2(ROOT/'vendor-expanded/fastp-assets/plotly-1.2.0.min.js', folder/'plotly-1.2.0.min.js')
    command = [*COMMANDS[target], '-i', str(inputs[0]), '-I', str(inputs[1]),
               '-o', str(output[0]), '-O', str(output[1]), '--json', str(report), '--html', str(html),
               '--thread', '2', '--dont_eval_duplication', '--disable_trim_poly_g', *flags]
    started = time.perf_counter()
    result = subprocess.run(command, cwd=folder, capture_output=True, timeout=180)
    elapsed = time.perf_counter() - started
    (folder/'stdout.log').write_bytes(result.stdout)
    (folder/'stderr.log').write_bytes(result.stderr)
    assert result.returncode == 0, (target, result.returncode, result.stderr[-3000:])
    document = json.loads(report.read_text())
    # Upstream records argv joined by spaces, including a final space. The APE
    # loader is not part of fastp's argv. Check exact text, not merely JSON syntax:
    # unescaped Windows \t/\f/\u sequences can otherwise parse but change paths.
    fastp_argv = command[len(COMMANDS[target])-1:]
    expected_command = ''.join(argument + ' ' for argument in fastp_argv)
    assert document['command'] == expected_command, (target, document['command'], expected_command)
    text = html.read_bytes().decode('utf-8')
    scripts = Scripts()
    scripts.feed(text)
    assert scripts.sources == ['plotly-1.2.0.min.js'], scripts.sources
    assert 'cdn.plot.ly' not in text and 'window.Plotly ||' not in text
    assert "modeBarButtonsToRemove:['sendDataToCloud']" in text
    footer = re.search(r"<div id='footer'> <p>(.*?)</p>", text, re.DOTALL)
    assert footer and unescape(footer.group(1)) == expected_command
    assert not scripts.injected_tags, scripts.injected_tags
    summary = {'target': target, 'exit_code': result.returncode, 'wall_seconds': elapsed,
               'command': command, 'executable_sha256': sha(Path(COMMANDS[target][-1])),
               'summary': document['summary'], 'filtering_result': document['filtering_result'],
               'adapters': document.get('adapter_cutting'), 'output_sha256': [sha(path) for path in output],
               'json_sha256': sha(report), 'html_sha256': sha(html), 'offline_chart_script_verified': True,
               'json_command_exact_roundtrip': True, 'html_command_exact_roundtrip': True}
    return output, document, summary


def paired_output(outputs):
    left, right = list(fasta_records(outputs[0])), list(fasta_records(outputs[1]))
    assert len(left) == len(right)
    for first, second in zip(left, right):
        assert first[0][:-2] == second[0][:-2], (first[0], second[0])
    return left, right


def normalized_json(document):
    return {key: value for key, value in document.items() if key != 'command'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--practical-data', type=Path)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    folder = (args.output or ROOT/'fastp-build'/('validation-'+datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S'))).resolve()
    if args.practical_data:
        args.practical_data = args.practical_data.resolve()
    folder.mkdir(parents=True, exist_ok=False)
    paths, expected, before_bases = fixture(folder)
    truth_flags = ['--adapter_sequence', ADAPTER1, '--adapter_sequence_r2', ADAPTER2,
                   '--cut_tail', '--cut_tail_window_size', '1', '--cut_tail_mean_quality', '20',
                   '--length_required', '30', '--qualified_quality_phred', '15',
                   '--unqualified_percent_limit', '40', '--n_base_limit', '5']
    records = []
    comparisons = []
    windows_paths = []
    for mate, path in enumerate(paths, 1):
        # These backslashes are literal filename bytes on Linux. They exercise
        # the same report serialization as Windows paths without claiming that
        # the Windows loader or filesystem was executed by this test.
        name = (r'C:\Users\Tim_H\reads ' if mate == 1 else r'C:\temp\foo\u0061\reads ')
        renamed = folder / (name + str(mate) + ' μ.fastq')
        shutil.copy2(path, renamed)
        windows_paths.append(renamed)
    report_title = ('Report "quoted" & <script id="report-escape-regression">text</script> '
                    "apostrophe ' Unicode μ 🧬 " + r'backslash \ UNC \\server\share \u0061 ' +
                    ''.join(chr(value) for value in range(1, 32)))
    for mode in ('plain', 'gzip', 'windows-paths', 'report-special-characters'):
        inputs = windows_paths if mode == 'windows-paths' else paths
        if mode == 'gzip':
            inputs = [path.with_suffix('.fastq.gz') for path in paths]
        flags = truth_flags + (['--report_title', report_title] if mode == 'report-special-characters' else [])
        outputs_by_target = []
        docs = []
        for target in COMMANDS:
            outputs, document, summary = run_one(target, inputs, folder/f'fixture-{mode}-{target}', flags)
            paired = paired_output(outputs)
            for mate, rows in enumerate(paired):
                actual = {name: (seq, qual) for name, seq, qual in rows}
                assert len(actual) == len(rows) == 100
                assert actual == expected[mate], (target, mode, mate,
                    next(((key, expected[mate].get(key), value) for key, value in actual.items()
                          if expected[mate].get(key) != value), None))
            assert document['summary']['before_filtering']['total_reads'] == 240
            assert document['summary']['before_filtering']['total_bases'] == before_bases
            assert document['summary']['after_filtering']['total_reads'] == 200
            assert document['summary']['after_filtering']['total_bases'] == 13500
            summary['known_truth_exact'] = True
            summary['case'] = f'fixture-{mode}'
            records.append(summary)
            outputs_by_target.append(paired)
            docs.append(normalized_json(document))
        assert outputs_by_target[0] == outputs_by_target[1]
        assert docs[0] == docs[1]
        comparisons.append({'case': f'fixture-{mode}', 'paired_output_exact': True,
                            'json_equal_excluding_command': True, 'known_truth_exact': True})
    unit_results = []
    upstream_source = ROOT/'fastp-build/sources/fastp-1.3.7'
    if not upstream_source.is_dir():
        upstream_source = ROOT/'vendor-expanded/fastp-1.3.7'
    if not upstream_source.is_dir():
        raise FileNotFoundError('Build fastp first with tools/build_fastp.py; upstream test data are not prepared')
    for target, command in COMMANDS.items():
        result = subprocess.run([*command, 'test'], cwd=upstream_source,
                                capture_output=True, timeout=30, check=True)
        (folder/f'upstream-tests-{target}.stdout.log').write_bytes(result.stdout)
        (folder/f'upstream-tests-{target}.stderr.log').write_bytes(result.stderr)
        assert b'ALL PASSED' in result.stdout and b' FAILED' not in result.stdout
        unit_results.append({'target': target, 'checks': result.stdout.count(b': PASSED'), 'passed': True})
    if args.practical_data:
        inputs = [args.practical_data/'lane1'/f's-7-{mate}.fastq' for mate in (1, 2)]
        flags = ['--adapter_fasta', str(args.practical_data/'primers_adapters.fa'),
                 '--cut_tail', '--cut_tail_window_size', '4', '--cut_tail_mean_quality', '20',
                 '--length_required', '30']
        paired, docs = [], []
        for target in COMMANDS:
            outputs, document, summary = run_one(target, inputs, folder/f'yeast-lane1-{target}', flags)
            summary['case'] = 'yeast-lane1'
            summary['input_sha256'] = [sha(path) for path in inputs]
            records.append(summary)
            paired.append(paired_output(outputs))
            docs.append(normalized_json(document))
        assert all(Counter(paired[0][mate]) == Counter(paired[1][mate]) for mate in (0, 1))
        assert docs[0] == docs[1]
        comparisons.append({'case': 'yeast-lane1', 'paired_output_exact': paired[0] == paired[1],
                            'output_record_multisets_equal': True, 'json_equal_excluding_command': True})
    report = {'tool': 'fastp', 'version': '1.3.7', 'platform': 'Linux x86-64 reference versus same-host Cosmopolitan APE',
              'windows_execution_tested': False, 'fixture_seed': 720619, 'fixture_before_pairs': 120,
              'fixture_expected_after_pairs': 100, 'fixture_description':
              '50 adapter-contaminated pairs trim exactly to 60 bases; 50 low-quality-tail pairs trim to 75 bases; '
              '10 all-low-quality mate pairs and 10 excessive-N mate pairs are discarded.',
              'upstream_tests': unit_results, 'comparisons': comparisons, 'runs': records}
    path = folder/'fastp-validation.json'
    path.write_text(json.dumps(report, indent=2)+'\n')
    print(path)
    print(json.dumps({'upstream_tests': unit_results, 'comparisons': comparisons,
                      'summaries': [{key: record[key] for key in ['case', 'target', 'wall_seconds', 'summary']}
                                    for record in records]}, indent=2))


if __name__ == '__main__':
    main()
