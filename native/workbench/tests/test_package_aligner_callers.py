"""Packaging/source-inventory regression tests with synthetic local fixtures."""
from contextlib import contextmanager
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock
import zipfile

SCRIPTS=Path(__file__).resolve().parents[1]/'scripts'
sys.path.insert(0,str(SCRIPTS))
try:
 import package_aligner_callers as p
 import restore_source_archives as restore
finally:sys.path.pop(0)


def sha(data):return hashlib.sha256(data).hexdigest()
def put(root,name,data):
 path=root/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(data);return path


class SourceInventory(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
  self.source=self.root/'source';self.source.mkdir()
  self.runtime=self.root/'runtime';(self.runtime/'packs').mkdir(parents=True)
  self.context=mock.patch.object(p,'SOURCE',self.source);self.context.start()
 def tearDown(self):self.context.stop();self.temp.cleanup()
 def test_rebuilt_source_code_and_patches_retained_generated_runtime_and_restricted_archive_excluded(self):
  included=['desktop/new_child_environment.h','tools/build_lofreq.py','workspace/desktop_host.py',
            'tools/build_fastp.py','tools/build_paircheck.py','tools/paircheck.c','build_variant.py',
            'variant-protocol.txt','variant-provenance.json',
            'vendor-expanded/freebayes/compat/llrintl.c','vendor-expanded/freebayes/compat/test_llrintl.c',
            'vendor-expanded/archives/plotly-1.2.0.js','vendor-expanded/archives/plotly-1.2.0.min.js',
            'vendor-expanded/licenses/runtime/notice.c','vendor-expanded/licenses/runtime/notice.h',
            'vendor-expanded/lofreq/patches/omit-uniq.patch','vendor-expanded/vardict/provenance.json',
            'vendor-variant/archives/samtools-source.tar.bz2','variant-build/cosmopolitan-3.3.10.tar.gz',
            'packs/lofreq-0.5.3/licenses/patches.json','README-0.5.3.txt']
  excluded=['build/lofreq/source/new.c','vendor-expanded/lofreq/lofreq-2.1.5.tar.gz',
            'vendor-expanded/varscan/VarScan.v2.4.6.source.jar','vendor-expanded/varscan/galaxy-mpileup.xml',
            'vendor-expanded/vardict/strawberry-perl-5.42.3.1-64bit-portable.zip',
            'vendor-expanded/vardict/OpenJDK8U-jre_x64_linux_hotspot_8u504b01.tar.gz',
            'vendor-expanded/vardict/VarDict-1.8.3.zip','vendor-expanded/hisat2/scientific spaces/generated.bam',
            'vendor-expanded/hisat2/fixtures/generated.ht2l',
            'vendor-expanded/hisat2/build-source-upstream/snapshot.c',
            'vendor-expanded/lofreq/source/cdflib90/unused.c','vendor-expanded/muscle/source/bigfixture.txt',
            'packs/vardict-0.5.3/runtime/java/bin/java.exe','packs/vardict-0.5.3/bin/vardict.jar',
            'baselines/bin/old-linux','results/private.txt','user-data/settings.json',
            'expansion-pipeline-temp/unexpected.txt','vendor-expanded/vardict/OpenJDK-windows.zip']
  for name in included+excluded:put(self.source,name,b'fixture')
  files,_=p.collect_sources(self.runtime)
  self.assertEqual({x.relative_to(self.source).as_posix() for x in files},set(included))
 def test_only_checksum_identical_source_archives_are_referenced_and_local_restore_is_exact(self):
  content=b'complete corresponding source fixture'
  put(self.runtime,'packs/new-0.5.3/licenses/source.tar.gz',content)
  a=put(self.source,'vendor-expanded/new/source.tar.gz',content)
  b=put(self.source,'packs/new-0.5.3/licenses/source.tar.gz',content)
  different=put(self.source,'vendor-expanded/new/different.tar.gz',b'different source')
  put(self.source,'scripts/build_new.py',b'# reproducible builder')
  files,index=p.collect_sources(self.runtime)
  self.assertNotIn(a,files);self.assertNotIn(b,files);self.assertIn(different,files)
  self.assertEqual(len(index['restore_from_runtime']),2)
  put(self.source,'SOURCE-CONTENTS.json',json.dumps(index).encode())
  a.unlink();b.unlink()
  result=restore.restore(self.source,self.runtime)
  self.assertEqual(result['restored'],2)
  self.assertEqual(a.read_bytes(),content);self.assertEqual(b.read_bytes(),content)
  self.assertEqual(restore.restore(self.source,self.runtime)['already_present'],2)
 def test_different_existing_source_not_overwritten_and_corrupt_runtime_not_copied(self):
  good=b'complete source';put(self.runtime,'packs/new/licenses/src.tar.gz',good)
  index={'schema':1,'restore_from_runtime':[{'runtime_path':'packs/new/licenses/src.tar.gz',
         'source_path':'vendor-expanded/new/src.tar.gz','sha256':sha(good),'bytes':len(good)}]}
  put(self.source,'SOURCE-CONTENTS.json',json.dumps(index).encode())
  dest=put(self.source,'vendor-expanded/new/src.tar.gz',b'personal modified source')
  with self.assertRaisesRegex(ValueError,'refusing overwrite'):restore.restore(self.source,self.runtime)
  self.assertEqual(dest.read_bytes(),b'personal modified source')
  dest.unlink();put(self.runtime,'packs/new/licenses/src.tar.gz',b'bad')
  with self.assertRaisesRegex(ValueError,'differs'):restore.restore(self.source,self.runtime)
  self.assertFalse(dest.exists())
 def test_restore_rejects_path_escape_and_linked_destination(self):
  good=b'source';put(self.runtime,'packs/new/licenses/src.tar.gz',good)
  item={'runtime_path':'packs/new/licenses/src.tar.gz','source_path':'../outside.tar.gz','sha256':sha(good),'bytes':len(good)}
  put(self.source,'SOURCE-CONTENTS.json',json.dumps({'schema':1,'restore_from_runtime':[item]}).encode())
  with self.assertRaisesRegex(ValueError,'Unsafe'):restore.restore(self.source,self.runtime)
  outside=self.root/'elsewhere';outside.mkdir();(self.source/'linked').symlink_to(outside,target_is_directory=True)
  item['source_path']='linked/file.tar.gz'
  put(self.source,'SOURCE-CONTENTS.json',json.dumps({'schema':1,'restore_from_runtime':[item]}).encode())
  with self.assertRaisesRegex(ValueError,'links'):restore.restore(self.source,self.runtime)
  self.assertFalse((outside/'file.tar.gz').exists())


class ReleaseGuards(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
  self.pack=self.root/'pack';self.pack.mkdir()
  put(self.pack,'pack.ini',b'synthetic metadata fixture')
  put(self.pack,'bin/tool.exe',b'declared executable fixture')
  self.data={'id':'fixture','version':'0.5.3','tools':{'tool':{'path':'bin/tool.exe','sha256':sha(b'declared executable fixture')}},'assets':{}}
  self.context=mock.patch.object(p,'catalog_module',return_value=SimpleNamespace(load_pack=lambda path:self.data));self.context.start()
 def tearDown(self):self.context.stop();self.temp.cleanup()
 def test_closed_inventory_rejects_hidden_java_runtime_file(self):
  put(self.pack,'runtime/java/lib/jvm.dll',b'undeclared')
  with self.assertRaisesRegex(ValueError,'Undeclared runtime'):p.validate_pack(self.pack)
 def test_declared_runtime_and_license_sources_accepted_but_combined_budget_enforced(self):
  data=b'private runtime';put(self.pack,'runtime/java/lib/jvm.dll',data)
  self.data['assets']['jvm']={'path':'runtime/java/lib/jvm.dll','sha256':sha(data)}
  put(self.pack,'licenses/source.tar.gz',b'corresponding source archive')
  self.assertEqual(p.validate_pack(self.pack)['id'],'fixture')
  with mock.patch.object(p,'MAX_PACK_BYTES',20):
   with self.assertRaisesRegex(ValueError,'512 MiB'):p.validate_pack(self.pack)
 def test_individual_asset_cap_independent_of_license_archive_size(self):
  put(self.pack,'licenses/source.tar.gz',b'license source'*20)
  with mock.patch.object(p,'MAX_PACK_FILE_BYTES',30):
   self.assertEqual(p.validate_pack(self.pack)['id'],'fixture')
  with mock.patch.object(p,'MAX_PACK_FILE_BYTES',5):
   with self.assertRaisesRegex(ValueError,'Executable/asset'):p.validate_pack(self.pack)
 def test_original_thirteen_pack_files_preserved_exactly(self):
  table={}
  for i in range(13):
   name=f'packs/old-{i}/pack.ini';data=f'original {i}'.encode();put(self.root,name,data)
   table[name]={'path':name,'bytes':len(data),'sha256':sha(data)}
  self.assertEqual(len(p.verify_preserved_packs(table,self.root)),13)
  put(self.root,'packs/old-4/pack.ini',b'modified original')
  with self.assertRaisesRegex(ValueError,'differs'):p.verify_preserved_packs(table,self.root)
 def test_finish_rejects_baseline_overlap_before_any_write(self):
  with self.assertRaisesRegex(ValueError,'overlap'):p.finish(self.root,self.root)
  with self.assertRaisesRegex(ValueError,'overlap'):p.finish(self.root,self.root/'nested')


if __name__=='__main__':unittest.main()
