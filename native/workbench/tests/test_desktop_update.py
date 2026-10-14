"""Transactional native update tests with small, explicitly synthetic payloads."""
from pathlib import Path
import hashlib
import importlib.util
import json
import shutil
import tempfile
import unittest
from unittest import mock

SCRIPT=Path(__file__).resolve().parents[1]/'scripts/apply_desktop_update.py'
spec=importlib.util.spec_from_file_location('desktop_updater',SCRIPT)
u=importlib.util.module_from_spec(spec);spec.loader.exec_module(u)


def digest(data): return hashlib.sha256(data).hexdigest()
def put(root,name,data):
 p=root/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(data)
def inventory(files): return [{'path':name,'bytes':len(data),'sha256':digest(data)} for name,data in sorted(files.items())]


class DesktopUpdate(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.parent=Path(self.temp.name)
  self.root=self.parent/'app';self.update=self.parent/'update'
  self.root.mkdir();(self.update/'blobs').mkdir(parents=True)
  self.old={'NativeWorkbench.exe':b'old-ui','workspace/server.py':b'old-host',
            'workspace/web/index.html':b'old-ui-document','packs/tool.exe':b'unchanged-science',
            'source/native-workbench-source.zip':b'synthetic-source-old'}
  self.new={'NativeWorkbench.exe':b'new-native-ui','workspace/desktop_host.py':b'new-stdio-host',
            'packs/tool.exe':b'unchanged-science','source/native-workbench-source.zip':b'synthetic-source-new'}
  for name,data in self.old.items():put(self.root,name,data)
  put(self.root,'user-data/keep.txt',b'user settings')
  put(self.root,'results/keep.txt',b'user analysis')
  old_manifest={'version':'0.5.0','manifest_includes_itself':False,'files':inventory(self.old)}
  target={'version':'0.5.1','interface':'native-win32','requires_browser':False,'manifest_includes_itself':False,'files':inventory(self.new)}
  old_raw=(json.dumps(old_manifest,indent=2)+'\n').encode();new_raw=(json.dumps(target,indent=2)+'\n').encode()
  put(self.root,'manifest.json',old_raw)
  operations=[]
  def blob(data):
   name=digest(data);put(self.update,'blobs/'+name,data);return name
  for name,data in self.new.items():
   if name.startswith('source/') or self.old.get(name)==data:continue
   operations.append({'path':name,'bytes':len(data),'sha256':digest(data),'source':{'kind':'blob','blob':blob(data)}})
  old_source=self.old['source/native-workbench-source.zip'];new_source=self.new['source/native-workbench-source.zip']
  prefix=b'synthetic-source-';tail=b'new'
  recipe={'target':'source/native-workbench-source.zip','bytes':len(new_source),'sha256':digest(new_source),
          'base':{'path':'source/native-workbench-source.zip','bytes':len(old_source),'sha256':digest(old_source)},
          'pieces':[{'kind':'base','offset':0,'length':len(prefix),'sha256':digest(prefix)},
                    {'kind':'blob','blob':blob(tail),'length':len(tail),'sha256':digest(tail)}]}
  self.recipe={'schema_version':1,'kind':'native-desktop-update','base_version':'0.5.0','target_version':'0.5.1',
               'base_manifest_sha256':digest(old_raw),'target_manifest':target,'target_manifest_sha256':digest(new_raw),
               'target_manifest_blob':blob(new_raw),'operations':operations,
               'obsolete':sorted(set(self.old)-set(self.new)),'source_zip':recipe}
  self.write_recipe()
 def tearDown(self): self.temp.cleanup()
 def write_recipe(self):put(self.update,'update-manifest.json',(json.dumps(self.recipe)+'\n').encode())
 def assert_original(self):
  for name,data in self.old.items():self.assertEqual((self.root/name).read_bytes(),data,name)
  self.assertEqual(u.sha(self.root/'manifest.json'),self.recipe['base_manifest_sha256'])
  self.assertEqual((self.root/'user-data/keep.txt').read_bytes(),b'user settings')
  self.assertEqual((self.root/'results/keep.txt').read_bytes(),b'user analysis')
 def test_success_exact_files_browser_removed_userdata_retained(self):
  result=u.apply(self.root,self.update)
  self.assertEqual(result['status'],'installed')
  for name,data in self.new.items():self.assertEqual((self.root/name).read_bytes(),data)
  self.assertFalse((self.root/'workspace/web').exists());self.assertFalse((self.root/'workspace/server.py').exists())
  self.assertEqual((self.root/'user-data/keep.txt').read_bytes(),b'user settings')
  self.assertEqual((self.root/'results/keep.txt').read_bytes(),b'user analysis')
  backup=Path(result['backup']);self.assertEqual((backup/'workspace/server.py').read_bytes(),b'old-host')
 def test_idempotent(self):
  u.apply(self.root,self.update)
  self.assertEqual(u.apply(self.root,self.update)['status'],'already-installed')
 def test_changed_baseline_rejected_before_release_mutation(self):
  put(self.root,'packs/tool.exe',b'modified science')
  with self.assertRaises(ValueError):u.apply(self.root,self.update)
  self.assertEqual((self.root/'NativeWorkbench.exe').read_bytes(),b'old-ui')
  self.assertFalse((self.root/'updates').exists())
 def test_corrupt_blob_rejected_and_original_hashes_retained(self):
  blob=self.recipe['operations'][0]['source']['blob'];put(self.update,'blobs/'+blob,b'corrupt')
  with self.assertRaises(RuntimeError):u.apply(self.root,self.update)
  self.assert_original()
 def test_midcommit_exception_restores_complete_baseline(self):
  real=u.os.replace;calls=0
  def replace(src,dest):
   nonlocal calls
   calls+=1
   if calls==5:raise OSError('Injected mid-commit failure')
   return real(src,dest)
  with mock.patch.object(u.os,'replace',side_effect=replace):
   with self.assertRaises(RuntimeError):u.apply(self.root,self.update)
  self.assert_original()
  reports=list((self.root/'updates').glob('*/update-result.json'))
  self.assertTrue(json.loads(reports[0].read_text())['baseline_restored'])
 def test_obsolete_unrecognized_file_rejected(self):
  self.recipe['obsolete'].append('user-data/keep.txt');self.write_recipe()
  with self.assertRaises(ValueError):u.apply(self.root,self.update)
  self.assert_original()
 def test_extra_web_file_not_deleted(self):
  put(self.root,'workspace/web/my-notes.txt',b'private notes')
  with self.assertRaises(ValueError):u.apply(self.root,self.update)
  self.assert_original();self.assertEqual((self.root/'workspace/web/my-notes.txt').read_bytes(),b'private notes')
 def test_unknown_file_at_new_destination_not_overwritten(self):
  put(self.root,'workspace/desktop_host.py',b'personal file')
  with self.assertRaises(ValueError):u.apply(self.root,self.update)
  self.assert_original();self.assertEqual((self.root/'workspace/desktop_host.py').read_bytes(),b'personal file')
 def test_running_old_host_lock_blocks_update(self):
  with u.update_lock(self.root):
   with self.assertRaises(ValueError):u.apply(self.root,self.update)
  self.assert_original()
 def test_source_range_tampering_rolls_back(self):
  self.recipe['source_zip']['pieces'][0]['offset']=999;self.write_recipe()
  with self.assertRaises(RuntimeError):u.apply(self.root,self.update)
  self.assert_original()


if __name__=='__main__':unittest.main()
