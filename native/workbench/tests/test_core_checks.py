"""Application checks with zero packs and an actual three-pack starter run."""
import copy
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import threading
import unittest

SOURCE = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(SOURCE/'workspace'))
sys.path.insert(0,str(SOURCE/'tests'))
from catalog import load_catalog
from core_checks import run_starter_checks
from engine import Engine
from example import make_example
from verify_installation import check_frontend, check_graph, check_release_manifest, check_packs, VerificationError
from test_workspace_engine import PortableBackend

APP = Path(os.environ.get('NW_APP_ROOT', SOURCE.parents[1]/'integration-0.5.4/native-workbench')).resolve()


class CoreChecksTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='core-checks-',dir=SOURCE)
        self.root = Path(self.temporary.name)
        (self.root/'workspace').mkdir()
        (self.root/'packs').mkdir()
        (self.root/'results').mkdir()
    def tearDown(self):
        self.temporary.cleanup()
    def starter(self):
        for identity in ('align','bam','variants'):
            shutil.copytree(APP/'packs'/f'{identity}-0.4.0',self.root/'packs'/f'{identity}-0.4.0')
        shutil.copytree(SOURCE/'examples/starter',self.root/'examples/starter')
        shutil.copyfile(SOURCE/'workspace/starter-check-profile.json',self.root/'workspace/starter-check-profile.json')
        return load_catalog(self.root)
    def manifest(self, extra=()):
        names = ['NativeWorkbench.exe','WorkbenchBridge.exe','workspace/catalog.py','workspace/engine.py',
                 'workspace/verify_installation.py','workspace/desktop_host.py','workspace/desktop_model.py',
                 'workspace/service.py','workspace/core_checks.py']+list(extra)
        files=[]
        for name in names:
            path=self.root/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(b'core fixture')
            files.append({'path':name,'bytes':path.stat().st_size,'sha256':hashlib.sha256(path.read_bytes()).hexdigest()})
        manifest={'schema_version':2,'ownership':'core','version':'0.6.0','interface':'native-win32',
                  'requires_browser':False,'transport':'anonymous-pipes','pack_management':'independent',
                  'manifest_includes_itself':False,'files':files}
        (self.root/'manifest.json').write_text(json.dumps(manifest))
    def test_empty_installation_can_discover_and_check_graph_without_optional_tools(self):
        catalog=load_catalog(self.root)
        self.assertEqual(set(catalog['tools']),{'builtin/report'})
        self.assertEqual(check_graph(self.root,catalog)['fanOut'],2)
        self.assertEqual(check_packs(self.root,catalog)['packManifests'],0)
        self.manifest()
        self.assertEqual(check_release_manifest(self.root)['filesVerified'],9)
    def test_core_manifest_cannot_claim_optional_packs_or_mutable_data(self):
        for name in ('packs/align-0.4.0/pack.ini','results/private.txt','user-data/settings.json'):
            with self.subTest(path=name):
                self.manifest([name])
                with self.assertRaises(VerificationError):
                    check_release_manifest(self.root)
    def test_core_inventory_detects_changed_application_file(self):
        self.manifest()
        (self.root/'workspace/core_checks.py').write_bytes(b'changed core')
        with self.assertRaisesRegex(VerificationError,'File (size|hash) differs'):
            check_release_manifest(self.root)
    def test_only_explicit_download_clients_can_import_network_and_never_listener(self):
        (self.root/'manifest.json').write_text('{"interface":"native-win32"}')
        for name in ('desktop_host.py','desktop_model.py','service.py'):
            (self.root/'workspace'/name).write_text('import json\n')
        client = self.root/'workspace/pack_manager.py'
        client.write_text('import urllib.request\nimport http.client\n')
        self.assertFalse(check_frontend(self.root)['requiresBrowser'])
        for code in ('import http.server\n','from http import server\n','socket.bind(address)\n'):
            client.write_text(code)
            with self.subTest(code=code), self.assertRaises(VerificationError):
                check_frontend(self.root)
        client.unlink()
        for name in ('reference_provider.py', 'reference_ncbi.py'):
            reference = self.root/'workspace'/name
            reference.write_text('import urllib.request\nimport http.client\n')
            self.assertFalse(check_frontend(self.root)['requiresBrowser'])
            for code in ('from http import server\n', 'import webbrowser\n', 'socket.listen(1)\n'):
                reference.write_text(code)
                with self.subTest(reference_client=name, code=code), self.assertRaises(VerificationError):
                    check_frontend(self.root)
            reference.unlink()
        helper=self.root/'workspace/pack_security.py'
        helper.write_text('from urllib.parse import urlsplit\n')
        self.assertFalse(check_frontend(self.root)['requiresBrowser'])
        helper.write_text('from urllib import request\n')
        with self.assertRaisesRegex(VerificationError,'URL parsing'):
            check_frontend(self.root)
        helper.unlink()
        (self.root/'workspace/service.py').write_text('import urllib.request\n')
        with self.assertRaisesRegex(VerificationError,'network/browser'):
            check_frontend(self.root)
    def test_starter_graph_needs_only_three_packs_and_has_valid_ports(self):
        catalog=self.starter();graph=make_example(self.root,catalog)
        self.assertEqual({p['id'] for p in catalog['packs']},{'align','bam','variants'})
        self.assertEqual([n['tool'] for n in graph['nodes']],['align/paired-end','bam/prepare','variants/call','variants/statistics','builtin/report'])
        self.assertTrue(Engine(self.root,catalog).validate(graph)['ok'])
        self.assertEqual(graph['nodes'][1]['inputs']['alignment'],['step-1::sam'])
    def test_real_catalogue_citation_parser_passes_frontend_client_boundary(self):
        (self.root/'manifest.json').write_text('{"interface":"native-win32"}')
        for name in ('catalog.py','pack_security.py','pack_manager.py','desktop_host.py','desktop_model.py','service.py'):
            shutil.copyfile(SOURCE/'workspace'/name,self.root/'workspace'/name)
        self.assertFalse(check_frontend(self.root)['requiresBrowser'])
        catalogue=self.root/'workspace/catalog.py'
        with catalogue.open('a') as stream:
            stream.write('\nimport urllib.request\n')
        with self.assertRaisesRegex(VerificationError,'URL parsing'):
            check_frontend(self.root)
    def test_all_packaged_runtime_modules_pass_static_frontend_boundary(self):
        # Exercise the packager's actual module inventory, so a new module
        # cannot evade this installation-check regression through a stale list.
        sys.path.insert(0, str(SOURCE/'scripts'))
        from package_split import RUNTIME_MODULES
        (self.root/'manifest.json').write_text('{"interface":"native-win32"}')
        for name in RUNTIME_MODULES:
            shutil.copyfile(SOURCE/'workspace'/name, self.root/'workspace'/name)
        result = check_frontend(self.root)
        self.assertEqual(set(result['modules']), set(RUNTIME_MODULES))
        self.assertFalse(result['requiresBrowser'])
    def test_project_path_encoding_does_not_allow_network_clients(self):
        (self.root/'manifest.json').write_text('{"interface":"native-win32"}')
        for name in ('desktop_host.py', 'desktop_model.py', 'service.py'):
            (self.root/'workspace'/name).write_text('import json\n')
        helper = self.root/'workspace/project_manager.py'
        for code in ('from urllib.parse import quote\n', 'import urllib.parse\n'):
            helper.write_text(code)
            self.assertFalse(check_frontend(self.root)['requiresBrowser'])
        for code in ('import urllib.request\n', 'from urllib import request\n',
                     'from urllib.request import urlopen\n', 'import urllib\n'):
            helper.write_text(code)
            with self.subTest(code=code), self.assertRaisesRegex(VerificationError, 'URL parsing'):
                check_frontend(self.root)
    def test_reference_transfer_can_only_import_http_exception_class(self):
        (self.root/'manifest.json').write_text('{"interface":"native-win32"}')
        for name in ('desktop_host.py', 'desktop_model.py', 'service.py'):
            (self.root/'workspace'/name).write_text('import json\n')
        helper = self.root/'workspace/reference_transfer.py'
        helper.write_text('from http.client import HTTPException\n')
        self.assertFalse(check_frontend(self.root)['requiresBrowser'])
        for code in ('import http.client\n', 'from http import client\n',
                     'from http.client import HTTPConnection\n', 'from http.client import HTTPException, HTTPSConnection\n',
                     'import urllib.request\n', 'import socket\n', 'from http import server\n',
                     'import webbrowser\n', 'connection.listen(1)\n'):
            helper.write_text(code)
            with self.subTest(code=code), self.assertRaises(VerificationError):
                check_frontend(self.root)
    def test_missing_optional_starter_is_skip_and_example_explains_installation(self):
        shutil.copyfile(SOURCE/'workspace/starter-check-profile.json',self.root/'workspace/starter-check-profile.json')
        catalog=load_catalog(self.root)
        result=run_starter_checks(self.root,catalog,self.root/'results')
        self.assertTrue(result['success']);self.assertEqual(result['skipped'],1)
        self.assertFalse(result['analysisExecuted'])
        with self.assertRaisesRegex(ValueError,'Manage tools'):
            make_example(self.root,catalog)
    def test_corrupt_fixture_fails_before_execution(self):
        catalog=self.starter()
        (self.root/'examples/starter/reads1.fastq').write_text('tampered')
        result=run_starter_checks(self.root,catalog,self.root/'results')
        self.assertFalse(result['success']);self.assertFalse(result['analysisExecuted'])
        self.assertIn('fixture differs',result['message'])
    def test_cancel_before_execution_is_reported(self):
        catalog=self.starter();cancel=threading.Event();cancel.set()
        result=run_starter_checks(self.root,catalog,self.root/'results',cancel=cancel)
        self.assertFalse(result['success']);self.assertTrue(result['cancelled'])
        self.assertFalse(result['analysisExecuted'])
    @unittest.skipIf(os.name=='nt','This validation adapter executes portable binaries on Linux only')
    def test_real_starter_pipeline_calls_truth_and_reports_reference_evidence(self):
        self.starter()
        # The default alignment version is deliberately newer. The externally
        # pinned scientific check must still execute its original exact pack.
        newer=self.root/'packs/align-0.4.1'
        shutil.copytree(self.root/'packs/align-0.4.0',newer)
        manifest=newer/'pack.ini'
        manifest.write_text(manifest.read_text().replace('version=0.4.0','version=0.4.1',1))
        catalog=load_catalog(self.root)
        self.assertEqual(catalog['tools']['align/paired-end']['packVersion'],'0.4.1')
        class RecordingBackend(PortableBackend):
            def __init__(self,root):
                super().__init__(root);self.calls=[]
            def run(self,request,event,cancel):
                self.calls.append(request)
                return super().run(request,event,cancel)
        backend=RecordingBackend(self.root)
        result=run_starter_checks(self.root,catalog,self.root/'results',backend=backend)
        self.assertTrue(result['success'],result)
        self.assertEqual(result['passed'],1)
        self.assertTrue(result['analysisExecuted'])
        self.assertFalse(result['nativeWindowsExecuted'])
        self.assertEqual(result['checks'][0]['evidence'],'reference-backend')
        self.assertEqual(Path(backend.calls[0]['pack_folder']).name,'align-0.4.0')


if __name__=='__main__':
    unittest.main()
