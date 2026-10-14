"""Boundary checks for self-contained runtime packs; sparse files contain no data."""
import hashlib
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

SOURCE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SOURCE/'workspace'))
from verify_installation import check_packs


class PackInventoryBudgetTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='pack-budget-')
        self.root = Path(self.temp.name)
        self.folder = self.root/'packs/runtime-0.5.4'
        (self.folder/'licenses').mkdir(parents=True)
        (self.folder/'pack.ini').touch()
        self.catalog = {'packs':[{'folder':'packs/runtime-0.5.4','manifestSha256':'test'}]}
        self.pack = {'manifestSha256':'test','tools':{},'assets':{}}

    def tearDown(self):
        self.temp.cleanup()

    def sparse(self, name, size):
        path = self.folder/name
        path.parent.mkdir(parents=True,exist_ok=True)
        with path.open('wb') as out:
            out.truncate(size)

    def check(self):
        # Parsing and executable validation have separate tests; exercise the
        # real closed inventory, size accounting, and hash verification here.
        with patch('verify_installation.load_pack',return_value=self.pack):
            return check_packs(self.root,self.catalog)

    def test_corresponding_source_bundle_can_exceed_old_512_mib_limit(self):
        self.sparse('licenses/runtime-source.tar',600*1024*1024)
        tool=self.folder/'tool.exe';tool.write_bytes(b'verified fixture')
        self.pack['tools']['runtime']={'path':'tool.exe','sha256':hashlib.sha256(tool.read_bytes()).hexdigest()}
        self.assertEqual(self.check()['executablesVerified'],1)

    def test_total_budget_includes_licenses_and_has_exact_boundary(self):
        self.sparse('licenses/runtime-source.tar',1024*1024*1024)
        self.assertEqual(self.check()['packManifests'],1)
        self.sparse('licenses/runtime-source.tar',1024*1024*1024+1)
        with self.assertRaisesRegex(ValueError,'1024 MiB'):
            self.check()

    def test_individual_runtime_asset_has_new_512_mib_limit(self):
        self.sparse('runtime/modules',512*1024*1024+1)
        self.pack['assets']['modules']={'path':'runtime/modules','sha256':'0'*64}
        with patch('verify_installation.sha256',side_effect=AssertionError('Oversized file must not be hashed')):
            with self.assertRaisesRegex(ValueError,'512 MiB file limit'):
                self.check()

    def test_more_space_does_not_admit_undeclared_runtime_files(self):
        (self.folder/'unexpected.dll').write_bytes(b'not declared')
        with self.assertRaisesRegex(ValueError,'Undeclared file'):
            self.check()


if __name__ == '__main__':
    unittest.main()
