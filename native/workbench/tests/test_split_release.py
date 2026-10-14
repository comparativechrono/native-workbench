"""Portable-release boundaries and pack archive contract; no scientific execution."""
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock
import zipfile

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import package_split as package


def put(root,name,data):
    path=root/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(data);return path


def fake_pack(root,identity='example',version='1.0.0'):
    executable=b'synthetic bytes, not executable';identity_sha=hashlib.sha256(executable).hexdigest()
    text=f'''[pack]
format=2
id={identity}
version={version}
name=Example
platform=windows-x86_64
[tool:example]
path=bin/example.exe
version=1.0
sha256={identity_sha}
[workflow:run]
name=Run example
inputs=
outputs=result
steps=run
[output:run:result]
label=Result
path=result.txt
[step:run:run]
label=Run
kind=exec
tool=example
stdout=result
'''
    put(root,'pack.ini',text.encode());put(root,'bin/example.exe',executable)
    put(root,'licenses/LICENSE.txt',b'complete license notice')
    put(root,'licenses/source.tar.gz',b'exact corresponding source fixture')
    return text.encode()


class SplitRelease(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.pack=self.root/'example-1.0.0';self.raw=fake_pack(self.pack)
    def tearDown(self):self.temp.cleanup()

    def test_pack_archive_envelope_matches_all_bytes_and_preserves_manifest(self):
        output=self.root/'pack.zip';result=package.build_pack(self.pack,output)
        self.assertEqual((self.pack/'pack.ini').read_bytes(),self.raw)
        self.assertEqual(result['sha256'],hashlib.sha256(output.read_bytes()).hexdigest())
        with zipfile.ZipFile(output) as zipped:
            self.assertEqual(zipped.read('pack/pack.ini'),self.raw)
            envelope=json.loads(zipped.read('workbench-pack.json'))
            self.assertEqual(set(envelope),{'schema','id','version','packApi','minAppVersion','platform','manifestSha256','files'})
            self.assertEqual(envelope['manifestSha256'],hashlib.sha256(self.raw).hexdigest())
            self.assertEqual(envelope['minAppVersion'],'0.6.0')
            expected={'workbench-pack.json'}
            for entry in envelope['files']:
                path='pack/'+entry['path'];data=zipped.read(path);expected.add(path)
                self.assertEqual(entry['size'],len(data));self.assertEqual(entry['sha256'],hashlib.sha256(data).hexdigest())
            self.assertEqual(set(zipped.namelist()),expected)
            self.assertIn('pack/licenses/source.tar.gz',expected)

    def test_new_pack_floor_does_not_raise_legacy_packs_and_rejects_older_apps(self):
        from pack_manager import compatibility
        import pack_manager
        output=self.root/'new-contract.zip'
        record=package.build_pack(self.pack,output,min_app_version='0.13.0')
        with zipfile.ZipFile(output) as zipped:
            envelope=json.loads(zipped.read('workbench-pack.json'))
        self.assertEqual(record['minAppVersion'],'0.13.0')
        with mock.patch.object(pack_manager,'APP_VERSION','0.12.0'):
            self.assertFalse(compatibility(envelope)[0])
        with mock.patch.object(pack_manager,'APP_VERSION','0.13.0'):
            self.assertTrue(compatibility(envelope)[0])
        with self.assertRaises(ValueError):
            package.build_pack(self.pack,self.root/'bad-floor.zip',min_app_version='latest')
        self.assertFalse((self.root/'bad-floor.zip').exists())

    def test_pack_publisher_rejects_undeclared_runtime_and_links(self):
        put(self.pack,'bin/extra.dll',b'undeclared')
        with self.assertRaises(ValueError):package.build_pack(self.pack,self.root/'bad.zip')
        (self.pack/'bin/extra.dll').unlink();(self.pack/'licenses/link').symlink_to(self.pack/'pack.ini')
        with self.assertRaises(ValueError):package.build_pack(self.pack,self.root/'bad.zip')
        self.assertFalse((self.root/'bad.zip').exists())

    def test_pack_publisher_rejects_modified_executable_and_never_overwrites(self):
        put(self.pack,'bin/example.exe',b'changed')
        with self.assertRaises(ValueError):package.build_pack(self.pack,self.root/'bad.zip')
        fake_pack(self.pack);existing=put(self.root,'exists.zip',b'keep')
        with self.assertRaises(ValueError):package.build_pack(self.pack,existing)
        self.assertEqual(existing.read_bytes(),b'keep')

    def test_source_companions_verify_exact_legacy_source_bytes(self):
        base=self.root/'base';folder=base/'packs/example-1.0.0';fake_pack(folder)
        source=folder/'licenses/source.tar.gz'
        value={'restore_from_runtime':[{'source_path':'vendor/example.tar.gz','runtime_path':'packs/example-1.0.0/licenses/source.tar.gz',
                 'bytes':source.stat().st_size,'sha256':hashlib.sha256(source.read_bytes()).hexdigest()}]}
        put(base,'docs/SOURCE-CONTENTS-0.5.4.json',json.dumps(value).encode())
        contents,companions=package.source_companions(base)
        self.assertEqual(contents,value);self.assertEqual(companions[0]['file'],'native-workbench-pack-example-1.0.0.zip')
        source.write_bytes(b'changed source')
        with self.assertRaises(ValueError):package.source_companions(base)

    def test_split_source_recovery_is_pinned_and_includes_handover_and_nested_docs(self):
        source=self.root/'source';base=self.root/'base';previous=self.root/'previous-source.zip'
        for folder in ('desktop','workspace','scripts','tests','tools','src','include','platform_windows',
                       'pack-examples','knowledge','docs'):(source/folder).mkdir(parents=True)
        put(source,'AGENTS.md',b'agent entry point')
        put(source,'knowledge/current-state.md',b'current handover')
        put(source,'knowledge/project.json',b'{"schema":1}')
        put(source,'publishing/setup-assets.json',b'{"schema":1,"packs":[]}')
        put(source,'publishing/setup-catalogue.UNSIGNED.json',b'{"schema":1,"fixture":true}')
        put(source,'publishing/private-key.pem',b'never include local signing material')
        put(source,'docs/source-recovery/README.md',b'nested recovery instructions')
        put(source,'.github/workflows/native-core-check.yml',b'name: Core checks\n')
        put(source,'examples/starter/reference.fa',b'>reference\nACGT\n')
        legacy=b'exact historical source archive';contents={'restore_from_runtime':[]}
        recovery={'release':'0.6.0','legacy_source':{'path':'source/native-workbench-source.zip',
                  'bytes':len(legacy),'sha256':hashlib.sha256(legacy).hexdigest()},
                  'pack_companions':[],'source_aliases':[]}
        with zipfile.ZipFile(previous,'x') as zipped:
            zipped.writestr('SOURCE-RECOVERY.json',json.dumps(recovery))
            zipped.writestr('legacy/SOURCE-CONTENTS-0.5.4.json',json.dumps(contents))
            zipped.writestr('legacy/native-workbench-0.5.4-source.zip',legacy)
        availability={'sourceArtifact':{'file':previous.name,'bytes':previous.stat().st_size,
                      'sha256':hashlib.sha256(previous.read_bytes()).hexdigest()}}
        for name in ('NativeWorkbench.exe','WorkbenchBridge.exe','workspace/desktop_host.py'):put(base,name,b'old')
        put(base,'SOURCE-AVAILABILITY.json',json.dumps(availability).encode())
        manifest={'schema_version':2,'version':'0.6.0','ownership':'core','pack_management':'independent',
                  'interface':'native-win32','requires_browser':False,'transport':'anonymous-pipes',
                  'manifest_includes_itself':False,'files':[package.item(p,p.relative_to(base).as_posix()) for p in package.files(base)]}
        put(base,'manifest.json',json.dumps(manifest).encode())
        output=self.root/'new-source.zip'
        with mock.patch.object(package,'SOURCE',source):package.build_sources(base,output,previous)
        with zipfile.ZipFile(output) as zipped:
            expected={'current/AGENTS.md','current/knowledge/current-state.md','current/knowledge/project.json',
                      'current/docs/source-recovery/README.md','current/.github/workflows/native-core-check.yml',
                      'current/publishing/setup-assets.json','current/publishing/setup-catalogue.UNSIGNED.json'}
            self.assertTrue(expected<=set(zipped.namelist()))
            self.assertNotIn('current/publishing/private-key.pem',zipped.namelist())
            self.assertEqual(zipped.read('legacy/native-workbench-0.5.4-source.zip'),legacy)
            record=json.loads(zipped.read('SOURCE-RECOVERY.json'))
            self.assertEqual(record['release'],package.VERSION)
            self.assertEqual(record['build_baseline']['version'],'0.6.0')
            self.assertTrue(expected<={entry['path'] for entry in record['current_source_files']})
        previous.write_bytes(b'changed source ZIP')
        with self.assertRaises(ValueError):package.build_sources(base,self.root/'rejected-source.zip',previous)
        self.assertFalse((self.root/'rejected-source.zip').exists())

    def test_runtime_inventory_contains_new_independent_manager_and_checks(self):
        self.assertTrue({'pack_manager.py','pack_security.py','core_checks.py'}<=set(package.RUNTIME_MODULES))
        self.assertTrue({'reference_provider.py','reference_manager.py','reference_provenance.py'}<=set(package.RUNTIME_MODULES))
        self.assertTrue({'cwl_export.py','dag_routing.py'}<=set(package.RUNTIME_MODULES))
        self.assertIn('setup_manager.py',package.RUNTIME_MODULES)
        self.assertTrue({'performance.py','readiness.py','diagnostics.py'}<=set(package.RUNTIME_MODULES))
        self.assertTrue({'sample_table.py','sample_table_editor.py','run_queue.py','reference_indexes.py'}<=set(package.RUNTIME_MODULES))
        self.assertIn('setup-profile.json',package.RUNTIME_METADATA)
        self.assertNotIn('server.py',package.RUNTIME_MODULES)
        self.assertEqual(package.STARTER,('align-0.4.0','bam-0.4.0','variants-0.4.0'))

    def test_core_inventory_rejects_nested_packs_and_case_collisions(self):
        value={'schema_version':2,'version':'0.6.0','ownership':'core','pack_management':'independent',
               'interface':'native-win32','requires_browser':False,'transport':'anonymous-pipes','manifest_includes_itself':False,
               'files':[{'path':name,'bytes':0,'sha256':hashlib.sha256(b'').hexdigest()} for name in
                        ('NativeWorkbench.exe','WorkbenchBridge.exe','workspace/desktop_host.py')]}
        package.core_inventory(value)
        value['files'].append({**value['files'][0],'path':'workspace/Desktop_Host.py'})
        with self.assertRaises(ValueError):package.core_inventory(value)

    def test_starter_stage_preserves_packs_and_archive_rejects_accidental_user_data(self):
        source=self.root/'source';base=self.root/'base';app=self.root/'starter'
        put(source,'build/desktop/DesktopWorkbench.exe',b'new-ui')
        put(source,'build/desktop/WorkbenchBridge.exe',b'new-bridge')
        put(source,'LICENSE',b'core-license')
        for name in package.NATIVE_NOTICE_FILES:put(source,'desktop/licenses/'+name,('native-notice-'+name).encode())
        for name in (*package.RUNTIME_MODULES,*package.RUNTIME_METADATA):put(source,'workspace/'+name,b'fixture module')
        put(source,'workspace/release-split/README.txt',b'starter instructions')
        put(source,'examples/starter/reference.fa',b'>starter\nACGT\n')
        put(base,'runtime/python/python.exe',b'private-runtime')
        for folder in package.STARTER:
            identity,version=folder.rsplit('-',1);fake_pack(base/'packs'/folder,identity,version)
        old={'version':'0.5.4','files':[package.item(p,p.relative_to(base).as_posix()) for p in package.files(base)]}
        put(base,'manifest.json',json.dumps(old).encode())
        artifact={'file':'source.zip','bytes':1,'sha256':hashlib.sha256(b'x').hexdigest(),'packCompanions':[]}
        with mock.patch.object(package,'SOURCE',source):package.stage(base,app,artifact)
        result=json.loads((app/'manifest.json').read_text())
        self.assertTrue(all(not i['path'].startswith('packs/') for i in result['files']))
        indexed={i['path']:i for i in result['files']}
        for name in ('setup_manager.py','setup-profile.json'):
            relative='workspace/'+name
            self.assertEqual((app/relative).read_bytes(),(source/relative).read_bytes())
            self.assertEqual(indexed[relative]['sha256'],hashlib.sha256((source/relative).read_bytes()).hexdigest())
        for name in package.NATIVE_NOTICE_FILES:
            path='runtime/licenses/native/'+name
            self.assertEqual((app/path).read_bytes(),(source/'desktop/licenses'/name).read_bytes())
            self.assertEqual(indexed[path]['sha256'],hashlib.sha256((app/path).read_bytes()).hexdigest())
        for folder in package.STARTER:
            self.assertEqual((base/'packs'/folder/'pack.ini').read_bytes(),(app/'packs'/folder/'pack.ini').read_bytes())
        output=self.root/'starter.zip';package.starter_archive(app,output)
        with zipfile.ZipFile(output) as zipped:
            self.assertIn('native-workbench/SOURCE-AVAILABILITY.json',zipped.namelist())
            for name in package.NATIVE_NOTICE_FILES:self.assertIn('native-workbench/runtime/licenses/native/'+name,zipped.namelist())
            self.assertEqual(len([n for n in zipped.namelist() if n.endswith('/pack.ini')]),3)
        # Additional candidate packs are explicit, separate from immutable
        # Starter pins, and bound to their complete inventory before archiving.
        extra=self.root/'additional-example';fake_pack(extra,'example','2.0.0')
        extra_app=self.root/'with-extra'
        with mock.patch.object(package,'SOURCE',source):
            package.stage(base,extra_app,artifact,extra_pack_dirs=[extra])
        extra_manifest=json.loads((extra_app/'manifest.json').read_text())
        self.assertEqual(extra_manifest['starter_packs'],result['starter_packs'])
        self.assertEqual(extra_manifest['additional_packs'][0]['version'],'2.0.0')
        extra_zip=self.root/'extra-starter.zip';package.starter_archive(extra_app,extra_zip)
        with zipfile.ZipFile(extra_zip) as zipped:
            self.assertEqual(len([n for n in zipped.namelist() if n.endswith('/pack.ini')]),4)
        put(extra_app,'packs/example-2.0.0/licenses/LICENSE.txt',b'changed unnoticed license')
        with self.assertRaises(ValueError):package.starter_archive(extra_app,self.root/'changed-extra.zip')
        for number,extras in enumerate(([extra,extra],[base/'packs'/package.STARTER[0]])):
            destination=self.root/('bad-extra-'+str(number))
            with mock.patch.object(package,'SOURCE',source),self.assertRaises(ValueError):
                package.stage(base,destination,artifact,extra_pack_dirs=extras)
            self.assertFalse(destination.exists())
        put(app,'results/private-patient-data.txt',b'never release this')
        with self.assertRaises(ValueError):package.starter_archive(app,self.root/'rejected.zip')
        self.assertFalse((self.root/'rejected.zip').exists())

        # The next application release stages from this exact split core. Optional
        # packs and mutable data in a user's installation are not redistributed.
        put(app,'packs/optional-9.0.0/private-file',b'not in the starter')
        next_app=self.root/'next-starter'
        with mock.patch.object(package,'SOURCE',source):package.stage(app,next_app,artifact)
        self.assertEqual({p.name for p in (next_app/'packs').iterdir()},set(package.STARTER))
        self.assertFalse((next_app/'results').exists())
        for folder in package.STARTER:
            before={p.relative_to(app/'packs'/folder):p.read_bytes() for p in package.files(app/'packs'/folder)}
            after={p.relative_to(next_app/'packs'/folder):p.read_bytes() for p in package.files(next_app/'packs'/folder)}
            self.assertEqual(before,after)
        put(app,'runtime/python/python.exe',b'changed frozen runtime')
        with mock.patch.object(package,'SOURCE',source),self.assertRaises(ValueError):
            package.stage(app,self.root/'bad-runtime-starter',artifact)
        self.assertFalse((self.root/'bad-runtime-starter').exists())


if __name__=='__main__':unittest.main()
