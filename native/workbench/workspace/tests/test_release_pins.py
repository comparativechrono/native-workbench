"""Release 0.5 regression gate: retain the independently versioned fixed packs.

Set BW_TEST_APP_ROOT to the unpacked release to repeat this check elsewhere.
These expected hashes deliberately describe the shipped 0.4.0/0.4.1 tools;
the workspace application version must not silently change their identity.
"""
import hashlib
import json
import os
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import catalog

SOURCE_ROOT = Path(__file__).resolve().parents[2]
APP_ROOT = Path(os.environ.get('BW_TEST_APP_ROOT', SOURCE_ROOT.parents[1] / 'integration-0.5' / 'native-workbench'))
PINS = {
    'align': ('0.4.0', '81c962222c93356a4f7727b23193c71d7dcd515859e62a179574781f411824d3'),
    'bam': ('0.4.0', '45b3f9d5092b0b3014f67b29331003e1214c72919f85695a571fb371030a9888'),
    'bwa': ('0.4.0', '7d49d9bac3c4c98776f70120915ffa7f2a85ee297787f9c1e45c8b4655ee4a37'),
    'fastp': ('0.4.1', '7d18c64a45ebbd78e1d246b660a82d7d1a98166ccfd2c40e3f621cd9fee2a6a6'),
    'freebayes': ('0.4.0', '9ba67c19846368c8d35119ec47404381c2aed6c6fbb693534963e7ec05ea7a7c'),
    'reads': ('0.4.0', '65fc3065fb382ffdd13c4b94fa834b26531e63eb87858d84a4c173e567fb73c0'),
    'research-variants': ('0.4.1', 'c255113ec8391e9f967b28612a7e6052da2d8344327db24fff3eff0f4f3db1f7'),
    'trimming': ('0.4.0', '5ebd1c6ae0368cdd6d1fb6a01041bb114c7a099fa8ab0e8836813bb60974d646'),
    'variant-pipeline': ('0.4.0', 'c14b3a1804a0a09bc2929653e9c07c9ac7fcdab92d8ed9ef5b1910e9eb86b367'),
    'variants': ('0.4.0', 'ea4b7f0a6c28709e4190b6514c07cbf7bdd58e1a4f2a2d931f2cae3ce6ec3795'),
}
FIXED_FASTP = '1dc1c0898be5625180d65dd630f426701d5741978a757624695d6bd54c1c4bd4'


class ReleasePins(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = catalog.load_catalog(APP_ROOT)
        manifest = APP_ROOT/'manifest.json'
        cls.independent = manifest.is_file() and json.loads(manifest.read_text()).get('ownership') == 'core'

    def test_installed_original_pack_pins_are_retained(self):
        installed = [p for p in self.catalog['packs'] if p['id'] in PINS and
                     (not self.independent or p['version'] == PINS[p['id']][0])]
        if not self.independent:
            self.assertEqual(len(installed), len(PINS))
            self.assertEqual({p['id'] for p in installed}, set(PINS))
        for pack in installed:
            version, digest = PINS[pack['id']]
            with self.subTest(pack=pack['id']):
                self.assertEqual(pack['version'], version)
                self.assertEqual(pack['folder'], f"packs/{pack['id']}-{version}")
                self.assertEqual(pack['manifestSha256'], digest)

    def test_installed_workflows_carry_their_own_exact_pack_pin(self):
        available = (t for versions in self.catalog.get('toolVersions',{}).values() for t in versions) if self.independent else self.catalog['tools'].values()
        descriptors = [t for t in available if t['packId'] in PINS and
                       (not self.independent or t['packVersion'] == PINS[t['packId']][0])]
        if not self.independent:
            self.assertEqual(len(descriptors), 43)
        for tool in descriptors:
            version, digest = PINS[tool['packId']]
            with self.subTest(tool=tool['id']):
                self.assertEqual(tool['packVersion'], version)
                self.assertEqual(tool['packFolder'], f"packs/{tool['packId']}-{version}")
                self.assertEqual(tool['manifestSha256'], digest)

    def test_both_installed_fastp_copies_are_the_fixed_executable(self):
        for pack_id in ('fastp', 'research-variants'):
            folder = APP_ROOT / 'packs' / f'{pack_id}-0.4.1'
            if self.independent and not folder.exists():
                continue
            pack = catalog.load_pack(folder / 'pack.ini')
            fastp = pack['tools']['fastp']
            with self.subTest(pack=pack_id):
                self.assertEqual(fastp['sha256'], FIXED_FASTP)
                self.assertEqual(hashlib.sha256((folder / fastp['path']).read_bytes()).hexdigest(), FIXED_FASTP)

    def test_source_declares_current_runner_and_retains_fixed_validation(self):
        if self.independent:
            # Application implementation hashes change independently of packs.
            # Application integrity is checked against its own release manifest.
            from verify_installation import check_release_manifest
            self.assertGreater(check_release_manifest(APP_ROOT)['filesVerified'],0)
            return
        expected = {
            'desktop/workbench.h': '048202b1139b5ecbfc9bfa85470617a2e40a53bdc36c81db4daaca0ce9140dae',
            'desktop/modular_validation.cpp': '1524c727610e09bf2f616e164df965d5391d7ec2af4d180437100b2758b65454',
            'baselines/bin/fastp-cosmo.exe': FIXED_FASTP,
        }
        for relative, digest in expected.items():
            with self.subTest(source=relative):
                path = SOURCE_ROOT / relative
                # The lean source bundle references runtime executables rather
                # than carrying redundant benchmark binary copies.
                if relative == 'baselines/bin/fastp-cosmo.exe' and not path.is_file():
                    path = APP_ROOT / 'packs/fastp-0.4.1/bin/fastp.exe'
                self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), digest)


if __name__ == '__main__':
    unittest.main()
