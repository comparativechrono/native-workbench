#!/usr/bin/env python3
"""Package the small, transactional 0.4.0-to-0.4.1 Windows report fix."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
VERSION = '0.4.1'
CHANGED_PACKS = ['fastp', 'research-variants']
BASE_PACKS = ['reads', 'align', 'bam', 'variants', 'variant-pipeline', 'trimming', 'bwa', 'freebayes']


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base', type=Path, default=ROOT.parent / 'native-workbench-0.4.0-windows.zip')
    parser.add_argument('--output', type=Path, default=ROOT.parent / 'native-workbench-0.4.1-fastp-fix.zip')
    args = parser.parse_args()
    with zipfile.ZipFile(args.base) as oldzip:
        base_manifest = json.loads(oldzip.read('native-workbench/manifest.json'))
        old_entries = {entry['path']: entry for entry in base_manifest['files']}
        # Pin this updater to the verified original release, not arbitrary builds.
        assert old_entries['NativeWorkbench.exe']['sha256'] == 'e9d2eec728776f6bb0a68e137b1df3c00ec9b2880b98d92600cd874f04e1bf1f'
        assert base_manifest['version'] == '0.4.0'
    destination = args.output.resolve()
    with tempfile.TemporaryDirectory(prefix='bw041-patch-', dir=destination.parent) as temp:
        stage = Path(temp)
        patch = stage / 'fastp-report-fix'
        patch.mkdir()

        def copy(source, relative):
            output = patch / relative
            output.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, output)
            return output

        copy(ROOT / 'scripts/apply_fastp_fix.py', 'apply_fastp_fix.py')
        copy(ROOT / 'LICENSE', 'LICENSE')
        copy(ROOT / 'baselines/bin/fastp-cosmo.exe', 'files/fastp.exe')
        copy(ROOT / 'build/desktop/NativeWorkbench.exe', 'files/NativeWorkbench.exe')
        copy(ROOT / 'build/pipeline-checks/WindowsPipelineChecks.exe', 'files/WindowsPipelineChecks.exe')
        copy(ROOT / 'README-0.4.1.txt', 'files/README.txt')
        specs = []
        new_entries = dict(old_entries)
        for identity in CHANGED_PACKS:
            previous = ROOT / 'packs' / f'{identity}-0.4.0'
            current = ROOT / 'packs' / f'{identity}-{VERSION}'
            replacements = {}
            old_manifest_path = f'packs/{identity}-0.4.0/pack.ini'
            assert digest(previous / 'pack.ini') == old_entries[old_manifest_path]['sha256']
            previous_files = {p.relative_to(previous).as_posix() for p in previous.rglob('*') if p.is_file()}
            current_files = {p.relative_to(current).as_posix() for p in current.rglob('*') if p.is_file()}
            assert current_files == previous_files, identity
            for relative in sorted(current_files):
                path = current / relative
                if path.read_bytes() != (previous / relative).read_bytes():
                    if relative == 'bin/fastp.exe':
                        payload = 'files/fastp.exe'
                    else:
                        payload = f'files/{identity}/{relative}'
                        copy(path, payload)
                    replacements[relative] = payload
                new_entries.pop(f'packs/{identity}-0.4.0/{relative}')
                key = f'packs/{identity}-{VERSION}/{relative}'
                new_entries[key] = {'path': key, 'bytes': path.stat().st_size, 'sha256': digest(path)}
            assert set(replacements) == {'pack.ini', 'PACK-README.md', 'bin/fastp.exe', 'licenses/fastp/BUILD-NOTES.txt'}, replacements
            specs.append({'id': identity, 'old_version': '0.4.0', 'new_version': VERSION,
                          'old_manifest_sha256': digest(previous / 'pack.ini'),
                          'new_manifest_sha256': digest(current / 'pack.ini'), 'replacements': replacements})

        applications = []
        for name in ('NativeWorkbench.exe', 'WindowsPipelineChecks.exe', 'README.txt'):
            path = patch / 'files' / name
            applications.append({'path': name, 'source': f'files/{name}',
                                 'old_sha256': old_entries[name]['sha256'], 'new_sha256': digest(path)})
            new_entries[name] = {'path': name, 'bytes': path.stat().st_size, 'sha256': digest(path)}
        updated_manifest = dict(base_manifest)
        updated_manifest.update(version=VERSION, files=[new_entries[name] for name in sorted(new_entries)],
            source_supplement='fastp-report-fix/source',
            update_note='Reporting-only fastp fix and independently versioned pack checks. Update files/backups/results are outside this installation manifest.')
        (patch / 'files/manifest.json').write_text(json.dumps(updated_manifest, indent=2) + '\n')
        with zipfile.ZipFile(args.base) as oldzip:
            old_manifest_hash = hashlib.sha256(oldzip.read('native-workbench/manifest.json')).hexdigest()
        applications.append({'path': 'manifest.json', 'source': 'files/manifest.json',
                             'old_sha256': old_manifest_hash, 'new_sha256': digest(patch / 'files/manifest.json')})

        sources = ['tools/build_fastp.py', 'tools/test_fastp.py',
                   'desktop/modular_validation.cpp', 'desktop/workbench.h', 'desktop/workbench.rc',
                   'desktop/workbench.manifest', 'desktop/prepare_research_packs.py',
                   'desktop/inspect_research.py', 'scripts/apply_fastp_fix.py',
                   'scripts/package_fastp_fix.py', 'tests/test_apply_fastp_fix.py',
                   'vendor-expanded/fastp-offline-report.patch', 'vendor-expanded/fastp-provenance.json',
                   'README-0.4.1.txt']
        for name in sources:
            copy(ROOT / name, Path('source') / name)
        for path in sorted((ROOT / 'packs/fastp-0.4.1/licenses').rglob('*')):
            if path.is_file():
                copy(path, Path('licenses') / path.relative_to(ROOT / 'packs/fastp-0.4.1/licenses'))
        reports = {
            'validation/fastp-report-escaping.json': 'fastp-report-escaping.json',
            'fastp-build/windows-json-fixed-validation-3/fastp-validation.json': 'fastp-validation.json',
            'validation/desktop-build-0.4.1.json': 'desktop-build.json',
            'validation/patch-pack-differences.json': 'pack-differences.json',
            'validation/fastp-updater-tests.json': 'updater-tests.json',
        }
        for name, target in reports.items():
            copy(ROOT / name, Path('evidence') / target)
        old_windows = json.loads((ROOT.parent / 'upload/windows-validation(1).json').read_text())
        (patch / 'evidence/windows-0.4.0-summary.json').write_text(json.dumps({
            'application_version': old_windows['application_version'], 'passed': old_windows['passed'],
            'failed': old_windows['failed'], 'elapsed_ms': old_windows['elapsed_ms'],
            'checks': old_windows['checks'], 'source_report_sha256': digest(ROOT.parent / 'upload/windows-validation(1).json'),
            'scope': 'User-supplied Windows 0.4.0 result; not a Windows 0.4.1 result.'}, indent=2) + '\n')

        model = subprocess.run([str(ROOT / 'build/model/test_pack_model'),
             *[str(ROOT / 'packs' / f'{name}-0.4.0/pack.ini') for name in BASE_PACKS],
             *[str(ROOT / 'packs' / f'{name}-0.4.1/pack.ini') for name in CHANGED_PACKS]],
             check=True, text=True, capture_output=True)
        (patch / 'evidence/pack-model.txt').write_text(model.stdout)
        metadata = {'schema_version': 1, 'patch_id': 'fastp-report-fix-0.4.1',
                    'files': {p.relative_to(patch).as_posix(): digest(p) for p in sorted(patch.rglob('*')) if p.is_file()},
                    'applications': applications, 'packs': specs}
        (patch / 'patch-metadata.json').write_text(json.dumps(metadata, indent=2) + '\n')
        command = r'''@echo off
setlocal DisableDelayedExpansion
if not exist "%~dp0NativeWorkbench.exe" (
  echo Put this command and fastp-report-fix beside NativeWorkbench.exe first.
  goto failed
)
if not exist "%~dp0packs\trimming-0.4.0\runtime\python\python.exe" (
  echo The bundled Python runtime from Native Workbench 0.4.0 is missing.
  goto failed
)
"%~dp0packs\trimming-0.4.0\runtime\python\python.exe" -I -B "%~dp0fastp-report-fix\apply_fastp_fix.py" --app-root "%~dp0." --patch-dir "%~dp0fastp-report-fix"
if errorlevel 1 goto failed
echo Restart Native Workbench and click Check installation.
pause
exit /b 0
:failed
echo Update did not complete. Read the message above; keep the existing files.
pause
exit /b 1
'''
        # Backslashes in the command are literal Windows path separators.
        command = command.replace('\r\n', '\n').replace('\n', '\r\n')
        (stage / 'apply-fastp-fix.cmd').write_bytes(command.encode('ascii'))
        (stage / 'README-fastp-fix.txt').write_text('''NATIVE WORKBENCH 0.4.1 — SMALL FASTP REPORT UPDATE

1. Close Native Workbench.
2. Extract this ZIP. Copy apply-fastp-fix.cmd and the entire fastp-report-fix
   folder into your existing native-workbench folder, beside NativeWorkbench.exe.
3. Double-click apply-fastp-fix.cmd and wait for the success message.
4. Restart start-windows.cmd, click Check installation, and return the new
   windows-validation.json. The standard ten-pack installation has 34 checks.

This update fixes invalid JSON escaping of Windows paths in fastp reports and
escapes dynamic HTML text. Read trimming and scientific metrics are unchanged.
It installs application 0.4.1 plus fastp/research packs 0.4.1. Other packs stay
at 0.4.0; checks now support independently versioned packs. The update creates
backups under updates/, verifies existing and new files, and rolls back a
failed publication. Your reads and results are not modified. Do not interrupt
the update. It requires the original 0.4.0 download; modified installations
are rejected. Running an already-installed update safely reports that status.

No administrator rights, internet connection or separate Python installation
are required. New Windows execution still needs the installation check above.
Linux/portable validation includes Windows-style paths, quotes, Unicode and
control characters; exact trimmed-read/metric comparisons include yeast lane1.

fastp-report-fix/source contains the changed source and build files to apply
over the original source ZIP, plus the reporting patch and provenance.
fastp-report-fix/licenses retains distribution notices. The original complete
source archive and unrelated application files remain in place.
''', encoding='utf-8')
        pending = destination.with_suffix('.zip.partial')
        with zipfile.ZipFile(pending, 'w', zipfile.ZIP_DEFLATED, compresslevel=9) as z:
            for path in sorted(stage.rglob('*')):
                if path.is_file():
                    z.write(path, path.relative_to(stage))
        with zipfile.ZipFile(pending) as z:
            assert z.testzip() is None
            for name, expected in metadata['files'].items():
                assert hashlib.sha256(z.read('fastp-report-fix/' + name)).hexdigest() == expected
            assert not any(byte < 32 and byte not in (10, 13) for byte in z.read('apply-fastp-fix.cmd'))
            longest = max(len('C:/Users/Tim_H/Downloads/native-workbench-0.4.0-windows/native-workbench/') + len(name) for name in z.namelist())
            assert longest < 260, longest
        pending.replace(destination)
    print(json.dumps({'path': str(destination), 'bytes': destination.stat().st_size,
                      'sha256': digest(destination), 'model_check': model.stdout.splitlines()[-1]}, indent=2))


if __name__ == '__main__':
    main()
