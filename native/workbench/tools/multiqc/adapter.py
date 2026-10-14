#!/usr/bin/env python3
"""Run pinned, real MultiQC on explicitly selected local reports.

This is an input/runtime adapter, not a replacement for MultiQC's parsers.
"""
import argparse
import hashlib
import html
from html.parser import HTMLParser
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import sys
import tempfile
import zipfile

MAX_INPUT = 64 * 1024 * 1024
MODULES = ['fastqc', 'fastp', 'star', 'kallisto', 'featurecounts']
CSP = "default-src 'none'; script-src 'unsafe-inline' 'unsafe-eval' blob:; style-src 'unsafe-inline'; img-src data: blob:; font-src data:; connect-src 'none'; worker-src blob:; object-src 'none'; frame-src 'none'; base-uri 'none'; form-action 'none'"


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def extract_wheels(pack, destination):
    """Install verified wheel contents privately, without pip or executable hooks."""
    destination.mkdir()
    seen = set()
    expanded = 0
    for wheel in sorted((pack / 'wheels').glob('*.whl')):
        with zipfile.ZipFile(wheel) as archive:
            for entry in archive.infolist():
                name = entry.filename
                parts = PurePosixPath(name).parts
                if entry.is_dir():
                    continue
                if not parts or name.startswith('/') or '\\' in name or ':' in name or '..' in parts or (entry.external_attr >> 16) & 0o170000 == 0o120000:
                    raise ValueError('Unsafe pinned wheel member: ' + name)
                # Wheel scripts/headers are not installed or executed. The runtime
                # imports actual library files; there is no analysis-time pip.
                if any(part.endswith('.data') for part in parts):
                    continue
                key = name.casefold()
                if key in seen:
                    raise ValueError('Colliding pinned wheel member: ' + name)
                seen.add(key)
                expanded += entry.file_size
                if expanded > 1024 * 1024 * 1024 or len(seen) > 50000:
                    raise ValueError('Private Python dependencies exceed the documented budget')
                target = destination.joinpath(*parts)
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(entry) as source, target.open('wb') as output:
                    shutil.copyfileobj(source, output)
    return destination


def classify(path):
    if not path.is_file() or path.stat().st_size > MAX_INPUT:
        raise ValueError('Each report must be a local file no larger than 64 MiB: ' + str(path))
    if zipfile.is_zipfile(path):
        with zipfile.ZipFile(path) as archive:
            records = [entry for entry in archive.infolist() if entry.filename.endswith('/fastqc_data.txt') or entry.filename == 'fastqc_data.txt']
            if len(records) != 1 or records[0].file_size > MAX_INPUT:
                raise ValueError('Select one original FastQC ZIP, containing exactly one bounded fastqc_data.txt')
            raw = archive.read(records[0])
        if not raw.startswith(b'##FastQC'):
            raise ValueError('The selected ZIP does not contain a FastQC data report')
        return 'fastqc', '_fastqc_data.txt', raw
    raw = path.read_bytes()
    text = raw.decode('utf-8-sig')
    if text.startswith('##FastQC'):
        return 'fastqc', '_fastqc_data.txt', raw
    if 'Number of input reads |' in text and 'Uniquely mapped reads number |' in text:
        return 'star', 'Log.final.out', raw
    if '[quant] finding pseudoalignments for the reads' in text and 'quantifying the abundances' in text:
        return 'kallisto', '.kallisto.log', raw
    if text.startswith('Status\t') and '\nAssigned\t' in text:
        lines = text.splitlines()
        labels = lines[0].split('\t')[1:]
        if not 1 <= len(labels) <= 64 or len(set(labels)) != len(labels):
            raise ValueError('featureCounts summary needs 1 to 64 distinct sample columns')
        for line in lines[1:]:
            cells = line.split('\t')
            if len(cells) != len(labels) + 1 or not all(re.fullmatch(r'\d+', n) for n in cells[1:]):
                raise ValueError('featureCounts summary rows must contain one nonnegative integer per sample column')
        return 'featurecounts', '.summary', raw
    if text.lstrip().startswith('{'):
        data = json.loads(text)
        if isinstance(data, dict) and isinstance(data.get('summary'), dict) and {'before_filtering', 'after_filtering'} <= set(data['summary']):
            # Pretty-print only to put the upstream search marker within its
            # 50-line limit, including for otherwise valid minified JSON.
            return 'fastp', '.fastp.json', (json.dumps(data, indent=2, ensure_ascii=True) + '\n').encode()
    raise ValueError('Unsupported report. Select FastQC ZIP/data, fastp JSON, STAR Log.final.out, featureCounts .summary, or a captured kallisto quantification log. kallisto run_info.json and abundance.tsv are not parsed by MultiQC.')


def stage_inputs(paths, folder):
    if not 1 <= len(paths) <= 64:
        raise ValueError('Select between 1 and 64 report files')
    folder.mkdir()
    records, hashes = [], set()
    for index, path in enumerate(paths, 1):
        path = Path(path).resolve(strict=True)
        module, suffix, payload = classify(path)
        canonical_hash = hashlib.sha256(payload).hexdigest()
        if canonical_hash in hashes:
            raise ValueError('The same report was selected twice (including a FastQC ZIP and its extracted data): ' + str(path))
        hashes.add(canonical_hash)
        stem = re.sub('[^A-Za-z0-9_.-]+', '_', path.stem).strip('._-')[:48] or 'report'
        identity = f'input{index:03d}_{stem}'
        original_labels = None
        if module == 'featurecounts':
            text = payload.decode('utf-8-sig')
            header, body = text.split('\n', 1)
            original_labels = header.rstrip('\r').split('\t')[1:]
            replacement = ['Status'] + [identity + f'_column{n:03d}' for n in range(1, len(original_labels) + 1)]
            payload = ('\t'.join(replacement) + '\n' + body).encode('utf-8')
        target = folder / (identity + suffix)
        target.write_bytes(payload)
        records.append({'id': identity, 'source': str(path), 'sourceSha256': sha(path), 'module': module, 'staged': str(target), 'stagedSha256': hashlib.sha256(payload).hexdigest(), **({'originalSampleColumns': original_labels} if original_labels else {})})
    return records


def offline_audit(event, args):
    if event in {'socket.connect', 'socket.getaddrinfo', 'socket.gethostbyname', 'subprocess.Popen', 'os.system', 'os.exec', 'os.posix_spawn'}:
        raise RuntimeError('Network connections and external programs are disabled for this local reporting operation: ' + event)


def protect_html(path):
    text = path.read_text(encoding='utf-8')
    if '<head>' not in text:
        raise ValueError('MultiQC did not produce a complete HTML document')
    text = text.replace('<head>', '<head>\n<meta http-equiv="Content-Security-Policy" content="' + html.escape(CSP, quote=True) + '">', 1)
    # An active remote reference would violate the self-contained report promise.
    # Ordinary citation hyperlinks are allowed; the CSP blocks active requests.
    class Assets(HTMLParser):
        def handle_starttag(self, tag, attrs):
            if tag in {'script', 'img', 'iframe', 'link'}:
                for name, value in attrs:
                    if name in {'src', 'href'} and value and re.match(r'\s*(?:https?:)?//', value, re.I):
                        raise ValueError('Unexpected remote asset in the generated report')
    Assets().feed(text)
    path.write_text(text, encoding='utf-8')


def prepare_output_space(run):
    """Accommodate runner-created output parents without overwriting results."""
    if (run / 'multiqc_report.html').exists():
        raise ValueError('A MultiQC report already exists in this run directory')
    parent = run / 'multiqc_data'
    if parent.exists():
        if not parent.is_dir() or parent.is_symlink() or any(parent.iterdir()):
            raise ValueError('The reserved MultiQC data directory is not empty')
        # The released native runner creates declared output parents before
        # launching tools. MultiQC treats even an empty directory as a collision
        # and otherwise silently suffixes both of its output names.
        parent.rmdir()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', required=True, type=Path)
    parser.add_argument('--private-runtime', action='store_true')
    parser.add_argument('reports', nargs='+')
    args = parser.parse_args(argv)
    run = args.run.resolve()
    if not run.is_dir():
        raise ValueError('The private Workbench run directory must already exist')
    prepare_output_space(run)
    stage = run / 'selected-reports'
    records = stage_inputs(args.reports, stage)
    os.chdir(run)
    # -I ignores PYTHON* startup injection. No auto-loaded user/site configs,
    # dotenv files, upload settings or plugins may change this operation.
    for key in list(os.environ):
        if key.startswith(('MULTIQC_', 'AWS_', 'OPENAI_', 'ANTHROPIC_')):
            del os.environ[key]
    os.environ['POLARS_MAX_THREADS'] = '2'
    os.environ['POLARS_FORCE_PKG'] = 'compat'
    os.environ['NO_COLOR'] = '1'
    os.environ['PYTHON_DOTENV_DISABLED'] = '1'
    os.environ['PYTHONDONTWRITEBYTECODE'] = '1'
    sys.dont_write_bytecode = True
    temp = run / 'report-tmp'
    temp.mkdir()
    os.environ['TMP'] = os.environ['TEMP'] = os.environ['TMPDIR'] = str(temp)
    tempfile.tempdir = str(temp)
    if args.private_runtime:
        libraries = extract_wheels(Path(__file__).resolve().parent, run / 'report-runtime')
        sys.path.insert(0, str(libraries))
    sys.addaudithook(offline_audit)
    import multiqc
    from multiqc import config, report
    from multiqc.core.update_config import ClConfig
    from multiqc.multiqc import run as run_multiqc
    if multiqc.__version__ != '1.35':
        raise ValueError('This adapter requires pinned MultiQC 1.35')
    config.find_user_files = lambda: None
    options = ClConfig(output_dir=str(run), filename='multiqc_report.html', template='default', run_modules=MODULES,
        use_filename_as_sample_name=['fastqc', 'fastp', 'star', 'kallisto'], fn_clean_sample_names=False, require_logs=False,
        make_data_dir=True, data_format='tsv', make_report=True, force=False, no_ansi=True,
        no_version_check=True, no_ai=True, ai_summary=False, ai_summary_full=False,
        no_megaqc_upload=True, export_plots=False, plots_force_interactive=True,
        plots_force_flat=False, make_pdf=False, preserve_module_raw_data=True,
        cl_config=['title: Local QC comparison', 'data_dir_name: multiqc_data', 'skip_generalstats: false', 'disable_version_detection: false'])
    result = run_multiqc(str(stage), cfg=options, interactive=False)
    if result.sys_exit_code != 0:
        raise ValueError('MultiQC failed: ' + result.message)
    data_path = run / 'multiqc_data' / 'multiqc_data.json'
    if not data_path.is_file():
        raise ValueError('MultiQC did not write its machine-readable data')
    data = json.loads(data_path.read_text(encoding='utf-8'))
    # Actual parser participation is required for every selected report; do not
    # issue a successful report after silently ignoring an incompatible input.
    sources = data.get('report_data_sources', {})
    def source_paths(value):
        if isinstance(value, dict):
            for item in value.values():
                yield from source_paths(item)
        elif isinstance(value, str):
            yield str(Path(value).resolve())
    used_sources = set(source_paths(sources))
    for record in records:
        if str(Path(record['staged']).resolve()) not in used_sources:
            raise ValueError('MultiQC did not parse the selected report: ' + record['source'])
    html_path = run / 'multiqc_report.html'
    protect_html(html_path)
    if not (run / 'multiqc_data' / 'multiqc_general_stats.txt').is_file():
        raise ValueError('No MultiQC general statistics were produced')
    provenance = {'schema': 1, 'tool': 'MultiQC', 'version': multiqc.__version__, 'inputCount': len(records),
        'inputIdentityPolicy': 'One explicit input namespace per selected report; no biological-sample merging is inferred.',
        'networkDisabled': True, 'automaticConfigurationDisabled': True, 'implicitDotenvDisabled': True, 'activeRemoteAssetsAllowed': False,
        'networkPolicy': 'Remote MultiQC features disabled; Python socket audit hook blocks connections; HTML CSP blocks active remote content. This is not OS-level isolation and does not sandbox compiled extensions.',
        'modules': sorted({r['module'] for r in records}), 'inputs': records}
    (run / 'report-inputs.json').write_text(json.dumps(provenance, ensure_ascii=True, indent=2) + '\n', encoding='utf-8')
    print('MultiQC 1.35 reported on ' + str(len(records)) + ' selected local inputs.')


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print('MultiQC input/runtime error: ' + str(exc), file=sys.stderr)
        raise SystemExit(1)
