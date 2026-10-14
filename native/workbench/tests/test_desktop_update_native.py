"""Exact native-release update and Windows singleton protocol regression tests.

Payloads and Win32 calls are explicit fixtures, never substitutes for a native
Windows execution test. No scientific executable is invoked by this suite.
"""
from contextlib import ExitStack
import ctypes
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock
import zipfile

SCRIPTS=Path(__file__).resolve().parents[1]/'scripts'
spec=importlib.util.spec_from_file_location('desktop_native_updater',SCRIPTS/'apply_desktop_update.py')
u=importlib.util.module_from_spec(spec);spec.loader.exec_module(u)
sys.path.insert(0,str(SCRIPTS))
try:
 spec=importlib.util.spec_from_file_location('desktop_update_generator',SCRIPTS/'make_desktop_update.py')
 generator=importlib.util.module_from_spec(spec);spec.loader.exec_module(generator)
finally:sys.path.pop(0)


def digest(data):return hashlib.sha256(data).hexdigest()
def put(root,name,data):
 path=root/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(data)
def inventory(files):return [{'path':name,'bytes':len(data),'sha256':digest(data)} for name,data in sorted(files.items())]
def source_archive(version):
 output=io.BytesIO()
 with zipfile.ZipFile(output,'w',compression=zipfile.ZIP_DEFLATED) as archive:
  for name,data in [('source/shared.txt',b'unchanged scientific source\n'*100),('source/version.txt',version.encode())]:
   member=zipfile.ZipInfo(name,(2026,10,3,0,0,0));member.compress_type=zipfile.ZIP_DEFLATED
   archive.writestr(member,data)
 return output.getvalue()


class FakeKernel32:
 """Stateful mutex API fixture plus observed-path canonicalization responses."""
 def __init__(self,full=r'C:\INSTALL\Native-Workbench',final=r'\\?\C:\INSTALL\Native-Workbench'):
  self.full=full;self.final=final;self.active=False;self.error=0
  self.closed=[];self.released=[];self.created=[];self.next_handle=200
  self.lowercase_overrides={};self.map_calls=[];self.opened=[]
 def GetFullPathNameW(self,path,size,output,part):
  if not size:return len(self.full.encode('utf-16-le'))//2+1
  output.value=self.full;return len(self.full.encode('utf-16-le'))//2
 def CreateFileW(self,path,access,sharing,security,creation,flags,template):
  assert (access,sharing,creation,flags)==(0,7,3,0x02000000)
  self.opened.append(path);return 100
 def GetFinalPathNameByHandleW(self,handle,output,size,flags):
  assert handle==100 and flags==0
  if self.final is None:return 0
  if not size:return len(self.final.encode('utf-16-le'))//2+1
  output.value=self.final;return len(self.final.encode('utf-16-le'))//2
 def LCMapStringEx(self,locale,flags,path,units,output,count,version,reserved,parameter):
  assert locale=='' and flags==0x100
  assert units==len(path.encode('utf-16-le'))//2
  self.map_calls.append((path,units))
  lowered=self.lowercase_overrides.get(path,path.lower())
  if output is not None:output.value=lowered
  return len(lowered.encode('utf-16-le'))//2
 def CreateMutexW(self,security,initial,name):
  assert security is None and initial is True
  self.error=183 if self.active else 0
  self.active=True;self.next_handle+=1
  self.created.append((name,self.next_handle))
  return self.next_handle
 def ReleaseMutex(self,handle):
  self.released.append(handle);self.active=False;return True
 def CloseHandle(self,handle):self.closed.append(handle);return True


def fake_win32(kernel):
 stack=ExitStack()
 stack.enter_context(mock.patch.object(u.ctypes,'set_last_error',side_effect=lambda value:setattr(kernel,'error',value),create=True))
 stack.enter_context(mock.patch.object(u.ctypes,'get_last_error',side_effect=lambda:kernel.error,create=True))
 return stack


class WindowsInstanceProtocol(unittest.TestCase):
 def test_disk_canonical_path_case_and_trailing_separator_match_utf16_digest(self):
  kernel=FakeKernel32(full='C:\\alias\\',final='\\\\?\\C:\\REAL\\Workbench\\')
  actual=u.windows_instance_name('ignored alias',kernel)
  expected='Local\\WorkbenchNativeWorkspace_'+digest('c:\\real\\workbench'.encode('utf-16-le'))
  self.assertEqual(actual,expected)
  self.assertEqual(kernel.opened,['\\\\?\\C:\\alias'])
  self.assertEqual(kernel.closed,[100])
 def test_unc_identity_and_supplementary_unicode_use_windows_mapping_and_utf16_units(self):
  kernel=FakeKernel32(full='\\\\SERVER\\SHARE\\İ😀',final='\\\\?\\UNC\\SERVER\\SHARE\\İ😀\\')
  normalized='\\\\server\\share\\i😀'
  kernel.lowercase_overrides['\\\\SERVER\\SHARE\\İ😀']=normalized
  actual=u.windows_instance_name('UNC fixture',kernel)
  self.assertEqual(actual,'Local\\WorkbenchNativeWorkspace_'+digest(normalized.encode('utf-16-le')))
  self.assertEqual(kernel.opened,['\\\\?\\UNC\\SERVER\\SHARE\\İ😀'])
  self.assertTrue(all(n==len(path.encode('utf-16-le'))//2 for path,n in kernel.map_calls))
 def test_failed_final_path_query_matches_desktop_lexical_fallback(self):
  kernel=FakeKernel32(full='C:\\Fallback\\',final=None)
  self.assertEqual(u.windows_instance_name('fixture',kernel),'Local\\WorkbenchNativeWorkspace_'+digest('c:\\fallback'.encode('utf-16-le')))
 def test_active_desktop_mutex_is_closed_without_releasing_its_ownership(self):
  kernel=FakeKernel32();kernel.active=True
  with fake_win32(kernel):
   with self.assertRaisesRegex(ValueError,'Native Workbench is still running'):
    with u.windows_instance_lock('fixture',kernel):self.fail('Entered active installation')
  self.assertTrue(kernel.active)
  self.assertEqual(kernel.released,[])
  self.assertIn(kernel.created[0][1],kernel.closed)
 def test_owned_mutex_blocks_competing_update_and_releases_after_exception(self):
  kernel=FakeKernel32()
  with fake_win32(kernel):
   with self.assertRaisesRegex(RuntimeError,'injected failure'):
    with u.windows_instance_lock('fixture',kernel):
     self.assertTrue(kernel.active)
     with self.assertRaisesRegex(ValueError,'still running'):
      with u.windows_instance_lock('fixture',kernel):self.fail('Concurrent entry')
     self.assertTrue(kernel.active)
     raise RuntimeError('injected failure')
  self.assertFalse(kernel.active)
  self.assertEqual(kernel.released,[kernel.created[0][1]])
  self.assertTrue(all(handle in kernel.closed for _,handle in kernel.created))
 def test_create_mutex_failure_is_fail_closed(self):
  kernel=FakeKernel32()
  def deny(*args):kernel.error=5;return None
  kernel.CreateMutexW=deny
  with fake_win32(kernel):
   with self.assertRaisesRegex(ValueError,'Windows error 5'):
    with u.windows_instance_lock('fixture',kernel):self.fail('Entered without lock')
  self.assertEqual(kernel.released,[])
 def test_path_mapping_error_never_creates_mutex(self):
  kernel=FakeKernel32();kernel.LCMapStringEx=lambda *args:0
  with fake_win32(kernel):
   with self.assertRaisesRegex(ValueError,'Cannot normalize'):
    with u.windows_instance_lock('fixture',kernel):self.fail('Entered without identity')
  self.assertEqual(kernel.created,[])


class NativeReleaseUpdate(unittest.TestCase):
 BASE_VERSION='0.5.1'
 TARGET_VERSION='0.5.2'
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.parent=Path(self.temp.name)
  self.root=self.parent/'base';self.target=self.parent/'target';self.payload=self.parent/'payload'
  self.root.mkdir();self.target.mkdir()
  self.old={'NativeWorkbench.exe':b'native-051','workspace/desktop_host.py':b'stdio-051',
            'packs/core-bio/pack.json':b'core-pack','packs/core-bio/bin/seqtk.exe':b'unchanged-science',
            'source/native-workbench-source.zip':source_archive(self.BASE_VERSION)}
  self.new={**self.old,'NativeWorkbench.exe':b'native-052','workspace/desktop_host.py':b'stdio-052',
            'packs/expansion/pack.json':b'new-pack-descriptor','packs/expansion/bin/new-tool.exe':b'new-science',
            'packs/expansion/licenses/LICENSE.txt':b'new-science-license',
            'source/native-workbench-source.zip':source_archive(self.TARGET_VERSION)}
  for root,version,files in ((self.root,self.BASE_VERSION,self.old),(self.target,self.TARGET_VERSION,self.new)):
   for name,data in files.items():put(root,name,data)
   manifest={'version':version,'interface':'native-win32','requires_browser':False,'files':inventory(files)}
   put(root,'manifest.json',(json.dumps(manifest,indent=2)+'\n').encode())
  self.old_manifest=(self.root/'manifest.json').read_bytes()
  self.generator_source=self.parent/'generator'
  for name in ('apply_desktop_update.py','make_desktop_update.py','make_workspace_update.py','reuse_source_zip.py'):
   put(self.generator_source,'scripts/'+name,('synthetic source '+name).encode())
  put(self.generator_source,'build/desktop/UpdateWorkbench.exe',b'synthetic-picker')
  with mock.patch.object(generator,'SOURCE',self.generator_source):
   self.stats=generator.make(self.root,self.target,self.payload,self.parent/'work')
  self.update=self.payload/'update'
  put(self.root,'user-data/keep.txt',b'user settings')
  put(self.root,'results/keep.txt',b'user analysis')
  put(self.root,'packs/personal/keep.txt',b'personal pack')
 def tearDown(self):self.temp.cleanup()
 def assert_original(self):
  self.assertEqual((self.root/'manifest.json').read_bytes(),self.old_manifest)
  for name,data in self.old.items():self.assertEqual((self.root/name).read_bytes(),data,name)
  self.assertEqual((self.root/'user-data/keep.txt').read_bytes(),b'user settings')
  self.assertEqual((self.root/'results/keep.txt').read_bytes(),b'user analysis')
  self.assertEqual((self.root/'packs/personal/keep.txt').read_bytes(),b'personal pack')
 def test_generated_native_delta_adds_pack_preserves_extras_and_reconstructs_exact_source(self):
  result=u.apply(self.root,self.update)
  self.assertEqual(result['version'],self.TARGET_VERSION);self.assertEqual(result['status'],'installed')
  for name,data in self.new.items():self.assertEqual((self.root/name).read_bytes(),data,name)
  self.assertEqual((self.root/'manifest.json').read_bytes(),(self.target/'manifest.json').read_bytes())
  self.assertEqual((self.root/'packs/personal/keep.txt').read_bytes(),b'personal pack')
  self.assertEqual((self.root/'results/keep.txt').read_bytes(),b'user analysis')
  self.assertGreater(self.stats['source_zip_reuse_bytes'],0)
  self.assertTrue(self.stats['source_zip_exact_reconstruction_verified'])
  self.assertEqual(u.apply(self.root,self.update)['status'],'already-installed')
 def test_modern_readme_uses_window_close_and_exact_baseline(self):
  text=(self.payload/'README.txt').read_text()
  self.assertIn('exact '+self.BASE_VERSION+' installation',text)
  self.assertIn('Close every NativeWorkbench window',text)
  self.assertNotIn('Close the old workbench service',text)
  self.assertNotIn('Historical browser runtime files are backed up and removed',text)
 def test_new_pack_conflict_is_rejected_without_mutation(self):
  put(self.root,'packs/expansion/bin/new-tool.exe',b'user supplied executable')
  with self.assertRaises(ValueError):u.apply(self.root,self.update)
  self.assert_original()
  self.assertEqual((self.root/'packs/expansion/bin/new-tool.exe').read_bytes(),b'user supplied executable')
  self.assertFalse((self.root/'updates').exists())
 def test_failed_manifest_commit_removes_added_pack_files_and_restores_native_release(self):
  real=u.os.replace;injected=False
  def replace(source,target):
   nonlocal injected
   if not injected and Path(source).name=='manifest.json' and Path(source).parent.name=='stage':
    injected=True;raise OSError('Injected final-manifest commit failure')
   return real(source,target)
  with mock.patch.object(u.os,'replace',side_effect=replace):
   with self.assertRaisesRegex(RuntimeError,'Injected final-manifest'):u.apply(self.root,self.update)
  self.assertTrue(injected);self.assert_original()
  for name in set(self.new)-set(self.old):self.assertFalse((self.root/name).exists(),name)
  report=json.loads(next((self.root/'updates').glob('*/update-result.json')).read_text())
  self.assertTrue(report['baseline_restored']);self.assertEqual(report['rollback_errors'],[])
 def test_active_native_guard_prevents_staging_or_release_mutation(self):
  kernel=FakeKernel32();kernel.active=True
  with fake_win32(kernel),mock.patch.object(u,'native_instance_lock',side_effect=lambda root:u.windows_instance_lock(root,kernel)):
   with self.assertRaisesRegex(ValueError,'Native Workbench is still running'):u.apply(self.root,self.update)
  self.assert_original();self.assertFalse((self.root/'updates').exists())
  self.assertTrue(kernel.active);self.assertEqual(kernel.released,[])
 def test_native_guard_remains_owned_during_commit_and_rollback(self):
  kernel=FakeKernel32();real=u.os.replace;calls=0
  def replace(source,target):
   nonlocal calls
   self.assertTrue(kernel.active,'Singleton guard released before transaction ended')
   calls+=1
   if calls==4:raise OSError('Injected guarded transaction failure')
   return real(source,target)
  with fake_win32(kernel),mock.patch.object(u,'native_instance_lock',side_effect=lambda root:u.windows_instance_lock(root,kernel)),mock.patch.object(u.os,'replace',side_effect=replace):
   with self.assertRaisesRegex(RuntimeError,'guarded transaction'):u.apply(self.root,self.update)
  self.assertGreater(calls,4);self.assert_original();self.assertFalse(kernel.active)
  self.assertEqual(len(kernel.released),1)
 def test_tampered_new_pack_blob_is_rejected_with_original_intact(self):
  recipe=json.loads((self.update/'update-manifest.json').read_text())
  operation=next(x for x in recipe['operations'] if x['path']=='packs/expansion/bin/new-tool.exe')
  put(self.update,'blobs/'+operation['source']['blob'],b'tampered')
  with self.assertRaises(RuntimeError):u.apply(self.root,self.update)
  self.assert_original()
 def test_unsupported_version_pair_rejected_before_staging(self):
  recipe=json.loads((self.update/'update-manifest.json').read_text());recipe['base_version']='0.4.1'
  put(self.update,'update-manifest.json',json.dumps(recipe).encode())
  with self.assertRaisesRegex(ValueError,'Unsupported update versions'):u.apply(self.root,self.update)
  self.assert_original();self.assertFalse((self.root/'updates').exists())


class AlignerCallerReleaseUpdate(NativeReleaseUpdate):
 BASE_VERSION='0.5.2'
 TARGET_VERSION='0.5.3'


class Mutect2ReleaseUpdate(NativeReleaseUpdate):
 BASE_VERSION='0.5.3'
 TARGET_VERSION='0.5.4'


if __name__=='__main__':unittest.main()
