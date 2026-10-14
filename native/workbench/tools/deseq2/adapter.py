"""Offline process adapter; all statistical calculations run in pinned upstream R."""
import argparse
import csv
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile

MAX_UNPACKED = 1600 * 1024 * 1024
MAX_FILES = 40000


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def dump(path, value):
    Path(path).write_text(json.dumps(value, indent=2, ensure_ascii=True) + '\n', encoding='utf-8')


def extract(archive, destination):
    """Extract only regular files into a newly created private runtime tree."""
    with zipfile.ZipFile(archive) as z:
        infos = z.infolist()
        if len(infos) > MAX_FILES or sum(i.file_size for i in infos) > MAX_UNPACKED:
            raise ValueError('Private runtime archive exceeds extraction budget')
        seen = set()
        for i in infos:
            p = PurePosixPath(i.filename)
            if p.is_absolute() or any(x in ('..', '') for x in p.parts) or '\\' in i.filename or ':' in i.filename:
                raise ValueError('Unsafe private runtime archive path')
            if (i.external_attr >> 16) & 0o170000 == 0o120000:
                raise ValueError('Runtime archive contains a symbolic link')
            key = i.filename.rstrip('/').casefold()
            if key in seen:
                raise ValueError('Duplicate runtime archive member')
            seen.add(key)
            out = destination.joinpath(*p.parts)
            if i.is_dir():
                out.mkdir(parents=True, exist_ok=True)
            else:
                out.parent.mkdir(parents=True, exist_ok=True)
                if out.exists():
                    raise ValueError('Runtime archive would overwrite a file')
                with z.open(i) as source, out.open('xb') as target:
                    shutil.copyfileobj(source, target, 1024 * 1024)


def private_runtime(pack, run):
    private = run / '_runtime'
    private.mkdir(exist_ok=False)
    runtime = json.loads((pack / 'runtime-index.json').read_text(encoding='utf-8'))
    for item in runtime['archives']:
        source = pack / item['path']
        if source.stat().st_size != item['bytes'] or sha(source) != item['sha256']:
            raise ValueError('Private runtime inventory mismatch: ' + item['path'])
        extract(source, private / item['destination'])
    rhome = private / 'R'
    exe = rhome / 'bin/x64/Rscript.exe'
    if not exe.is_file():
        raise ValueError('Private Rscript executable is missing')
    return exe, rhome


def scratch_directory(override=None):
    """R requires a temp path without spaces; own only a unique child directory."""
    root = Path(override).resolve(strict=True) if override else None
    if root is not None and not root.is_dir():
        raise ValueError('Temporary files folder must be an existing local directory')
    owned = Path(tempfile.mkdtemp(prefix='nw-deseq2-', dir=root))
    usable = str(owned)
    if ' ' in usable:
        import ctypes
        from ctypes import wintypes
        get_short = ctypes.WinDLL('kernel32', use_last_error=True).GetShortPathNameW
        get_short.argtypes = [wintypes.LPCWSTR, wintypes.LPWSTR, wintypes.DWORD]
        get_short.restype = wintypes.DWORD
        size = get_short(usable, None, 0)
        if size:
            output = ctypes.create_unicode_buffer(size)
            if get_short(usable, output, size):
                usable = output.value
    if ' ' in usable or not usable.isascii():
        shutil.rmtree(owned)
        raise ValueError('R needs a temporary folder without spaces. Select an existing user-writable local Temporary files folder whose full path has no spaces; no administrator privileges or drive mapping are needed.')
    return owned, usable


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--mode', choices=('counts', 'featurecounts', 'kallisto'), required=True)
    p.add_argument('--run', type=Path, required=True)
    p.add_argument('--samples', type=Path, required=True)
    p.add_argument('--scratch-root', default='')
    p.add_argument('--tx2gene', default='-')
    p.add_argument('--design', choices=('condition', 'batch-condition'), required=True)
    p.add_argument('--numerator', required=True)
    p.add_argument('--denominator', required=True)
    p.add_argument('--alpha', required=True)
    p.add_argument('--min-count', type=int, required=True)
    p.add_argument('--counts-origin', choices=('raw-integer', 'featurecounts', 'kallisto'), required=True)
    p.add_argument('files', nargs='+')
    a = p.parse_args(argv)
    pack = Path(__file__).resolve().parent
    run = a.run.resolve(strict=True)
    if os.name != 'nt':
        raise ValueError('This pack uses a private native Windows R runtime')
    if not re.fullmatch(r'[A-Za-z][A-Za-z0-9_.-]{0,63}', a.numerator) or not re.fullmatch(r'[A-Za-z][A-Za-z0-9_.-]{0,63}', a.denominator):
        raise ValueError('Contrast names must be identifiers beginning with a letter')
    if a.numerator == a.denominator:
        raise ValueError('Numerator and denominator must be different conditions')
    if not re.fullmatch(r'(?:0?\.\d+|1(?:\.0+)?)', a.alpha) or not 0 < float(a.alpha) < 1:
        raise ValueError('FDR alpha must be a decimal strictly between 0 and 1')
    if not 1 <= a.min_count <= 1000000:
        raise ValueError('Minimum total gene count must be between 1 and 1000000')
    if a.counts_origin != {'counts': 'raw-integer', 'featurecounts': 'featurecounts', 'kallisto': 'kallisto'}[a.mode]:
        raise ValueError('Input count origin does not match the selected operation')
    if (a.mode == 'counts' and len(a.files) != 1) or (a.mode != 'counts' and not 4 <= len(a.files) <= 64):
        raise ValueError('Select one count matrix or 4 to 64 individual sample count files')
    paths = [Path(f).resolve(strict=True) for f in a.files]
    if any(not f.is_file() for f in paths):
        raise ValueError('All inputs must be local files')
    for i, f in enumerate(paths):
        if any(os.path.samefile(f, other) for other in paths[:i]):
            raise ValueError('The same physical count file cannot represent two biological samples')
    samples = a.samples.resolve(strict=True)
    tx2gene = Path(a.tx2gene).resolve(strict=True) if a.mode == 'kallisto' else None
    selected = [samples] + paths + ([tx2gene] if tx2gene else [])
    inputs = [{'path': str(f), 'bytes': f.stat().st_size, 'sha256': sha(f)} for f in selected]
    # Copy every user-selected file before R reads it. Original user files remain unchanged.
    staged = run / '_inputs'
    staged.mkdir(exist_ok=False)
    staged_paths = []
    for n, f in enumerate(selected):
        dest = staged / ('input-%03d.tsv' % n)
        with f.open('rb') as source, dest.open('xb') as target:
            shutil.copyfileobj(source, target, 1024 * 1024)
        if sha(dest) != inputs[n]['sha256']:
            raise ValueError('Input changed during staging')
        staged_paths.append(str(dest))
    request = {'mode': a.mode, 'samples': staged_paths[0], 'files': staged_paths[1:1+len(paths)],
        'tx2gene': staged_paths[-1] if tx2gene else None, 'run': str(run), 'design': a.design,
        'numerator': a.numerator, 'denominator': a.denominator, 'alpha': float(a.alpha), 'minCount': a.min_count,
        'inputIdentities': inputs, 'countsOrigin': a.counts_origin}
    exe, rhome = private_runtime(pack, run)
    dump(run / 'request.json', request)
    env = {k: v for k, v in os.environ.items() if not k.upper().startswith(('R_', 'RSTUDIO', '_R_', 'RTOOLS', 'R_LIBS'))}
    # Environment is process-local. --vanilla prevents user/site profiles and .Renviron.
    scratch, temp = scratch_directory(a.scratch_root or None)
    env.update({'R_HOME': str(rhome), 'R_USER': str(run / '_home'), 'R_LIBS': str(rhome / 'library'),
        'R_LIBS_USER': str(rhome / 'library'), 'R_LIBS_SITE': str(rhome / 'library'),
        'TMPDIR': temp, 'TMP': temp, 'TEMP': temp, 'OMP_NUM_THREADS': '1', 'OPENBLAS_NUM_THREADS': '1',
        'MKL_NUM_THREADS': '1', 'R_DEFAULT_PACKAGES': 'datasets,utils,grDevices,graphics,stats,methods'})
    (run / '_home').mkdir(exist_ok=False)
    command = [str(exe), '--vanilla', str(pack / 'analysis.R'), str(run / 'request.json')]
    dump(run / 'commands.json', {'argv': command, 'shell': False, 'privateR': True, 'userStartupDisabled': True, 'temporaryDirectory': temp, 'scratchPolicy': 'Unique owned child of user-selected or OS temporary folder; short Windows alias used when needed; deleted after R exits'})
    try:
        proc = subprocess.run(command, cwd=run, env=env, check=False)
    finally:
        shutil.rmtree(scratch)
    if proc.returncode:
        raise RuntimeError('DESeq2 analysis failed; inspect the R error in the run log')
    for item in inputs:
        if sha(item['path']) != item['sha256']:
            raise ValueError('A selected input changed during analysis')
    dump(run / 'input-provenance.json', {'inputs': inputs, 'unchanged': True, 'mode': a.mode,
        'fileOrderMeaning': 'samples.tsv input_index selects the 1-based count-file position; matrix mode uses exact sample_id column names',
        'runtime': json.loads((pack / 'runtime-index.json').read_text()), 'networkRequestsPerformed': False, 'temporaryDirectoryRemoved': not scratch.exists()})


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print('DESeq2 pack: ' + str(exc), file=sys.stderr)
        sys.exit(1)
