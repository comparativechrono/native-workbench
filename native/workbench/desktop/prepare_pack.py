#!/usr/bin/env python3
"""Package the exact executables that passed the user's initial Windows checks."""
from pathlib import Path
import hashlib
import shutil

ROOT = Path(__file__).resolve().parents[1]
TOOLS = {
    'bwfastq': ('build/windows/bwfastq.exe', '0.1.0-experiment', '9ef643f49c96d9e221eae3925a7aad36f7081a16f218ee1e7346cce5f8c1fb6f'),
    'seqtk': ('baselines/bin/seqtk-cosmo.exe', '1.4-r122', 'c5df3fadda2e622a2e358de78a0d34513b392b68bd50208ee3dccb4877c72c2e'),
    'minimap2': ('baselines/bin/minimap2-cosmo.exe', '2.28-r1209', '06bf0815a79552ffcb1291046c7828f2bf8b11d9ad7fe0d9309283e966e973fa'),
}


def prepare():
    pack = ROOT / 'packs/core-bio-0.2.0'
    (pack / 'bin').mkdir(parents=True, exist_ok=True)
    text = '[pack]\nformat=1\nid=core-bio\nversion=0.2.0\nname=Bioinformatics essentials\nplatform=windows-x86_64\n'
    for name, (source, version, expected) in TOOLS.items():
        path = ROOT / source
        with path.open('rb') as f:
            actual = hashlib.file_digest(f, 'sha256').hexdigest()
        if actual != expected:
            raise SystemExit('Validated executable changed: ' + source)
        shutil.copy2(path, pack / 'bin' / (name + '.exe'))
        text += f'\n[{name}]\npath=bin\\{name}.exe\nversion={version}\nsha256={actual}\n'
    (pack / 'pack.ini').write_text(text, encoding='utf-8', newline='\n')
    shutil.copytree(ROOT / 'baselines/licenses', pack / 'licenses', dirs_exist_ok=True)
    shutil.copytree(ROOT / 'desktop/licenses', pack / 'licenses/windows-runtime', dirs_exist_ok=True)
    shutil.copy2(ROOT / 'LICENSE', pack / 'licenses/Native-Workbench-MIT.txt')
    (pack / 'PACK-README.md').write_text(
        'Bioinformatics essentials, pack 0.2.0\n\n'
        'Contains the unchanged executables from the initial native Windows validation.\n'
        'Pack format 1 is documented in docs/TOOL-PACKS.md in the application package.\n'
        'Tools execute as trusted native programs. Checksums check bytes, not publisher identity.\n'
        'All license notices are in licenses/. No network connection is needed.\n', encoding='utf-8')
    print(pack)


if __name__ == '__main__':
    prepare()
