"""Pack distribution trust, archive boundaries, offline use and cancellation."""
import base64
import copy
import errno
import hashlib
import http.client
import io
import json
from pathlib import Path
import stat
import socket
import ssl
import sys
import tempfile
import threading
import traceback
import unittest
from unittest.mock import patch
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'workspace'))
import pack_manager as pm
import pack_security as ps

# Deliberately public TEST ONLY private exponent; never a distribution trust key.
N = 'b8c32d907a3744be5fdd307a47a4a953ad421ca7c1a4ea8c2944881a685ffd3952978ee2c1925bb39e549b7d4219ed9939fba829764c4a59ab6554c34af4c4dbe275a460e094d6b6fb21adc77de795ae55eade0a2a00bbf5914ba1b8a22221d2496da60653d0d94956bfec1d39c16d92c062e7383c4ba655ab9be28b4b4d4d243d1f796db8f89376f36ee1a5f69bfce6e9e338fbd73fac0952e1adfaa42a1f16f2ff1c47e1d4435fccc0006a1d9d79717b0a6ca521c97add8370a122e16da560d82f034f571d36ce9f13118e5a36ebc830db18ce655883171518930dc407daed130bc2c11fc58a6c901dd051ca4793272f214be97111ca822d7806105e3a680f'
D = 'be626d25f7e36b9ab9973461b2ae21fa09099bad7b04a671ea677237b72c255df0c884e8a724c13cc365084daba108d8c68b962ae34696768c9832b7b71a0b0682c280178053ab33253d63d2e4dec28626ebef3726cdbe13eeb5b210f3da67fc46c40dd5074c4280f4a178e0c4a797a5f2152b29ef6ad7b665fd5d1528a4a08f113815dabaeb0fd09d231c6216af89fb9be6cc2074dd7c24737c0c6652948e08053c5bf4030ac6126bc973005db9a11c7480ed6fc1a170f687eff12e268ddc30850d399040bf5129c2d97dfb8d071a4da14e063c3d26199bc91f176a835230d9403cc832cf519f7665acbce4c76c9176f91baf6f91f761bda7038934e11c9cd'
KEY = {'n':N,'e':65537}
SOURCE = {'schema':1,'id':'test-feed','name':'Test publisher','catalogUrl':'https://example.invalid/catalog.json','publicKey':KEY,'allowedHosts':['example.invalid','assets.example.invalid']}


def sha(data):
    return hashlib.sha256(data).hexdigest()


def sign(document):
    payload = json.dumps(document,separators=(',',':')).encode()
    info = bytes.fromhex('3031300d060960864801650304020105000420')+hashlib.sha256(payload).digest()
    encoded = b'\x00\x01'+b'\xff'*(256-len(info)-3)+b'\x00'+info
    signature = pow(int.from_bytes(encoded,'big'),int(D,16),int(N,16)).to_bytes(256,'big')
    return json.dumps({'schema':1,'payload':base64.b64encode(payload).decode(),'signature':base64.b64encode(signature).decode()}).encode()


def payload(entry=None, date='2026-10-03T12:00:00Z'):
    return {'schema':1,'publishedAt':date,'packs':[entry] if entry else []}


def fixture():
    binary = b'MZ\x00this is a test fixture, never executed'
    manifest = f'''[pack]
format=2
id=demo
version=1.0.0
name=Example tool
platform=windows-x86_64
[tool:demo]
path=bin/demo.exe
version=2.1
sha256={sha(binary)}
[workflow:run]
name=Run demo
inputs=
outputs=result
steps=run
[output:run:result]
label=Result
path=result.txt
[step:run:run]
label=Run demo
kind=exec
tool=demo
stdout=result
'''.encode()
    files = {'pack.ini':manifest,'bin/demo.exe':binary,'licenses/LICENSE.txt':b'example licence'}
    envelope = {'schema':1,'id':'demo','version':'1.0.0','packApi':1,'minAppVersion':'0.6.0','platform':'windows-x86_64','manifestSha256':sha(manifest),'files':[{'path':name,'size':len(data),'sha256':sha(data)} for name,data in files.items()]}
    return files,envelope


def archive_bytes(files,envelope,extra=()):
    buffer=io.BytesIO()
    with zipfile.ZipFile(buffer,'w',zipfile.ZIP_DEFLATED) as zipped:
        zipped.writestr('workbench-pack.json',json.dumps(envelope))
        for name,data in files.items(): zipped.writestr('pack/'+name,data)
        for name,data in extra: zipped.writestr(name,data)
    return buffer.getvalue()


def entry_for(raw,envelope):
    return {'id':envelope['id'],'name':'Example tool','version':envelope['version'],'toolVersions':{'demo':'2.1'},'description':'Example','category':'Testing','platform':envelope['platform'],'packApi':envelope['packApi'],'minAppVersion':envelope['minAppVersion'],'downloadURL':'https://example.invalid/demo.zip','size':len(raw),'sha256':sha(raw),'manifestSha256':envelope['manifestSha256']}


class Verification(unittest.TestCase):
    def test_valid_signature_and_tampered_payload(self):
        raw=sign(payload())
        self.assertEqual(pm.validate_catalog(raw,SOURCE)['packs'],[])
        wrapper=json.loads(raw)
        wrapper['payload']=base64.b64encode(json.dumps(payload(date='2026-10-04T12:00:00Z')).encode()).decode()
        with self.assertRaisesRegex(ps.PackError,'signature'): pm.validate_catalog(json.dumps(wrapper).encode(),SOURCE)

    def test_bad_signature_padding_and_duplicate_json(self):
        raw=json.loads(sign(payload()))
        raw['signature']=base64.b64encode(b'\0'*256).decode()
        with self.assertRaises(ps.PackError): pm.validate_catalog(json.dumps(raw).encode(),SOURCE)
        with self.assertRaisesRegex(ps.PackError,'Duplicate'): ps.strict_json('{"x":1,"x":2}')

    def test_bad_source_keys_and_hosts(self):
        for url in ('http://example.invalid/a','https://example.invalid.evil/a','https://x:secret@example.invalid/a','https://example.invalid/a?token=secret','https://example.invalid:444/a','https://example.invalid/a#fragment'):
            source=copy.deepcopy(SOURCE);source['catalogUrl']=url
            with self.subTest(url=url), self.assertRaises(ps.PackError):pm.validate_source(source)
        source=copy.deepcopy(SOURCE);source['publicKey']['e']=3
        with self.assertRaises(ps.PackError):pm.validate_source(source)

    def test_redirect_host_guard_and_transient_query(self):
        request=pm.urllib.request.Request('https://example.invalid/demo.zip')
        redirect=pm._Redirects(SOURCE['allowedHosts'])
        accepted=redirect.redirect_request(request,None,302,'',{},'https://assets.example.invalid/demo.zip?ephemeral=1')
        self.assertIn('?ephemeral=',accepted.full_url)
        for url in ('http://assets.example.invalid/demo.zip','https://evil.invalid/demo.zip','https://secret@assets.example.invalid/demo.zip'):
            with self.assertRaises(ps.PackError): redirect.redirect_request(request,None,302,'',{},url)

    def test_signature_integer_outside_modulus_and_key_limit(self):
        with self.assertRaises(ps.PackError): ps.verify_signature(b'x',int(N,16).to_bytes(256,'big'),KEY)
        for key in ({'n':'f'*510,'e':65537},{'n':'f'*1025,'e':65537},{'n':N,'e':True}):
            with self.assertRaises(ps.PackError):ps.public_key(key)

    def test_duplicate_versions_rejected(self):
        files,envelope=fixture();raw=archive_bytes(files,envelope);entry=entry_for(raw,envelope)
        doc=payload(entry);doc['packs'].append(entry)
        with self.assertRaisesRegex(ps.PackError,'Duplicate'):pm.validate_catalog(sign(doc),SOURCE)


class DownloadTransport(unittest.TestCase):
    class Response(io.BytesIO):
        def __init__(self,data,headers=None,url='https://example.invalid/demo.zip'):
            super().__init__(data);self.headers=headers or {};self.url=url
        def getcode(self):return 200
        def geturl(self):return self.url

    def test_exact_download_digest_and_size(self):
        data=b'tool archive'
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'download.zip'
            response=self.Response(data,{'Content-Length':str(len(data))})
            with patch.object(pm.urllib.request.OpenerDirector,'open',return_value=response):
                size,digest=pm._download('https://example.invalid/demo.zip',SOURCE['allowedHosts'],path,100,expected_size=len(data),expected_sha=sha(data))
            self.assertEqual((size,digest),(len(data),sha(data)));self.assertEqual(path.read_bytes(),data)

    def test_truncated_corrupt_and_oversize_downloads(self):
        for data,limit,expected_size,digest in ((b'x',100,10,None),(b'bad',100,3,sha(b'yes')),(b'overflow',3,None,None)):
            with self.subTest(data=data), tempfile.TemporaryDirectory() as folder:
                with patch.object(pm.urllib.request.OpenerDirector,'open',return_value=self.Response(data)):
                    with self.assertRaises(ps.PackError):pm._download('https://example.invalid/a',SOURCE['allowedHosts'],Path(folder)/'x',limit,expected_size=expected_size,expected_sha=digest)

    def test_cancel_between_received_chunks(self):
        cancel=threading.Event()
        class SmallChunks(self.Response):
            def read1(self,size):return super().read1(min(size,3))
        def progress(event):cancel.set()
        with tempfile.TemporaryDirectory() as folder:
            with patch.object(pm.urllib.request.OpenerDirector,'open',return_value=SmallChunks(b'abcdefghij')):
                with self.assertRaises(pm.PackCancelled):pm._download('https://example.invalid/a',SOURCE['allowedHosts'],Path(folder)/'x',100,cancel,event=progress)
            self.assertEqual((Path(folder)/'x').read_bytes(),b'abc')

    def test_unapproved_final_host_cannot_write_payload(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'x'
            with patch.object(pm.urllib.request.OpenerDirector,'open',return_value=self.Response(b'bad',url='https://evil.invalid/x')):
                with self.assertRaises(ps.PackError):pm._download('https://example.invalid/a',SOURCE['allowedHosts'],path,100)
            self.assertFalse(path.exists())

    def test_network_failure_categories_keep_private_details_out_of_errors(self):
        secret='https://user:private-password@proxy.invalid/file?token=private-token'
        failures = (
            (pm.urllib.error.HTTPError(secret,407,secret,{},None),'proxy requires authentication'),
            (pm.urllib.error.HTTPError(secret,403,secret,{},None),'HTTP 403'),
            (pm.urllib.error.HTTPError(secret,404,secret,{},None),'HTTP 404'),
            (pm.urllib.error.HTTPError(secret,429,secret,{},None),'HTTP 429'),
            (pm.urllib.error.HTTPError(secret,503,secret,{},None),'HTTP 503'),
            (pm.urllib.error.URLError(OSError('Tunnel connection failed: 407 '+secret)),'proxy requires authentication'),
            (pm.urllib.error.URLError(ssl.SSLCertVerificationError(1,secret)),'certificate could not be verified'),
            (pm.urllib.error.URLError(ssl.SSLError(1,secret)),'secure HTTPS connection failed'),
            (pm.urllib.error.URLError(socket.gaierror(-2,secret)),'could not be resolved'),
            (pm.urllib.error.URLError(TimeoutError(secret)),'timed out'),
            (pm.urllib.error.URLError(ConnectionRefusedError(secret)),'connection was refused'),
            (pm.urllib.error.URLError(PermissionError(secret)),'Network access was denied'),
            (pm.urllib.error.URLError(OSError(errno.ENETUNREACH,secret)),'network request failed'),
            (pm.urllib.error.URLError(secret),'network request failed'),
        )
        for failure, expected in failures:
            with self.subTest(expected=expected), tempfile.TemporaryDirectory() as folder:
                with patch.object(pm.urllib.request.OpenerDirector,'open',side_effect=failure):
                    try:
                        pm._download('https://example.invalid/a',SOURCE['allowedHosts'],Path(folder)/'x',100)
                    except ps.PackError as error:
                        message=str(error)
                        rendered=''.join(traceback.format_exception(error))
                    else:
                        self.fail('Expected a sanitized download error')
                self.assertIn(expected,message)
                self.assertIn('example.invalid',message)
                self.assertNotIn('private-password',rendered)
                self.assertNotIn('private-token',rendered)
                self.assertNotIn('proxy.invalid',rendered)
                self.assertLess(len(message),350)
                self.assertFalse((Path(folder)/'x').exists())

    def test_redirect_failure_identifies_only_approved_host(self):
        def failure(opener,request,timeout):
            redirects=next(h for h in opener.handlers if isinstance(h,pm._Redirects))
            redirects.redirect_request(request,None,302,'',{},
                                       'https://assets.example.invalid/private-path?token=private-token')
            raise pm.urllib.error.URLError(TimeoutError('private-token'))
        with tempfile.TemporaryDirectory() as folder:
            with patch.object(pm.urllib.request.OpenerDirector,'open',failure):
                with self.assertRaises(ps.PackError) as caught:
                    pm._download('https://example.invalid/a',SOURCE['allowedHosts'],Path(folder)/'x',100)
            self.assertIn('Download from assets.example.invalid failed',str(caught.exception))
            self.assertNotIn('private-',str(caught.exception))

    def test_read_failure_is_not_reported_as_local_storage_failure(self):
        for failure in (TimeoutError('private-token'),ConnectionResetError('private-token'),
                        http.client.IncompleteRead(b'private-response'),http.client.RemoteDisconnected('private-token')):
            with self.subTest(failure=type(failure).__name__), tempfile.TemporaryDirectory() as folder:
                response=self.Response(b'',url='https://assets.example.invalid/a?token=private-token')
                with patch.object(pm.urllib.request.OpenerDirector,'open',return_value=response),patch.object(response,'read1',side_effect=failure):
                    with self.assertRaises(ps.PackError) as caught:
                        pm._download('https://example.invalid/a',SOURCE['allowedHosts'],Path(folder)/'x',100)
                self.assertIn('Download from assets.example.invalid failed',str(caught.exception))
                self.assertNotIn('saved',str(caught.exception))
                self.assertNotIn('private-',str(caught.exception))

    def test_destination_create_failures_are_not_reported_as_network_failures(self):
        locked=OSError('private-folder');locked.winerror=32
        failures=((PermissionError(errno.EACCES,'private-folder'),'Write access was denied'),
                  (OSError(errno.ENOSPC,'private-folder'),'not enough free disk space'),
                  (FileNotFoundError(errno.ENOENT,'private-folder'),'folder is no longer available'),
                  (locked,'locked by another process'))
        for failure,expected in failures:
            with self.subTest(expected=expected),tempfile.TemporaryDirectory() as folder:
                with patch.object(pm.urllib.request.OpenerDirector,'open',return_value=self.Response(b'a')),patch.object(Path,'open',side_effect=failure):
                    with self.assertRaises(ps.PackError) as caught:
                        pm._download('https://example.invalid/a',SOURCE['allowedHosts'],Path(folder)/'x',100)
                message=str(caught.exception)
                self.assertIn('Download could not be saved',message)
                self.assertIn(expected,message)
                self.assertNotIn('private-folder',message)

    def test_destination_write_and_flush_failures_are_local(self):
        class FullDisk(io.BytesIO):
            def write(self,data):raise OSError(errno.ENOSPC,'private-folder')
        class DeniedFlush(io.BytesIO):
            def __exit__(self,*args):
                super().__exit__(*args)
                raise PermissionError(errno.EACCES,'private-folder')
        for output,expected in ((FullDisk(),'not enough free disk space'),(DeniedFlush(),'Write access was denied')):
            with self.subTest(expected=expected),tempfile.TemporaryDirectory() as folder:
                with patch.object(pm.urllib.request.OpenerDirector,'open',return_value=self.Response(b'a')),patch.object(Path,'open',return_value=output):
                    with self.assertRaises(ps.PackError) as caught:
                        pm._download('https://example.invalid/a',SOURCE['allowedHosts'],Path(folder)/'x',100)
                self.assertIn('Download could not be saved',str(caught.exception))
                self.assertIn(expected,str(caught.exception))


class WindowsPaths(unittest.TestCase):
    def test_drive_and_unc_extended_paths(self):
        slash=chr(92);prefix=slash*2+'?'+slash
        self.assertEqual(pm.extended_windows_path('C:/workbench/a/../b'),prefix+'C:'+slash+'workbench'+slash+'b')
        unc=slash*2+'server'+slash+'share'+slash+'deep'
        self.assertEqual(pm.extended_windows_path(unc),prefix+'UNC'+slash+unc[2:])
        self.assertEqual(pm.ordinary_windows_path(prefix+'C:'+slash+'long'), 'C:'+slash+'long')
        self.assertEqual(pm.extended_windows_path(prefix+'C:'+slash+'long'),prefix+'C:'+slash+'long')
    def test_device_paths_rejected(self):
        slash=chr(92)
        for path in (slash*2+'.'+slash+'PhysicalDrive0',slash*2+'?'+slash+'GLOBALROOT'+slash+'Device'):
            with self.assertRaises(ps.PackError):pm.extended_windows_path(path)

    @unittest.skipUnless(sys.platform=='win32','Native Windows long-path filesystem check')
    def test_windows_deep_local_archive_import(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=pm.filesystem_path(Path(temporary)/('a'*80)/('b'*80)/('c'*80))
            root.mkdir(parents=True)
            files,envelope=fixture();archive=root/'pack.zip';archive.write_bytes(archive_bytes(files,envelope))
            observed=[]
            def importer(source):
                self.assertTrue((pm.filesystem_path(source)/'pack.ini').is_file())
                observed.append(source)
                return {'success':True}
            manager=pm.PackManager(root,importer,lambda:{'packs':[],'tools':{}})
            self.assertTrue(manager.import_archive(archive)['success'])
            self.assertGreater(len(observed[0]),260)
            self.assertFalse(observed[0].startswith(chr(92)*2+'?'))


class Archives(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.files,self.envelope=fixture()
    def tearDown(self):self.temp.cleanup()
    def run_extract(self,raw,expected=None,cancel=None):
        path=self.root/'pack.zip';path.write_bytes(raw)
        return pm.extract_archive(path,self.root/'out',expected,cancel)

    def test_round_trip_inventory_and_manifest(self):
        raw=archive_bytes(self.files,self.envelope)
        folder,envelope,pack=self.run_extract(raw,entry_for(raw,self.envelope))
        self.assertEqual(pack['id'],'demo');self.assertEqual(envelope,self.envelope)
        self.assertEqual((folder/'bin/demo.exe').read_bytes(),self.files['bin/demo.exe'])

    def test_tamper_never_reaches_importer(self):
        self.files['bin/demo.exe']=b'corrupt'
        path=self.root/'pack.zip';path.write_bytes(archive_bytes(self.files,self.envelope))
        callback=lambda request:self.fail('Tampered executable reached importer')
        manager=pm.PackManager(self.root,callback,lambda:{'packs':[],'tools':{}})
        with self.assertRaises(ps.PackError):manager.import_archive(path)
        self.assertEqual(list((manager.data).glob('_import-*')),[])

    def test_manifest_executable_digest_must_match_inventory(self):
        self.files['pack.ini']=self.files['pack.ini'].replace(sha(self.files['bin/demo.exe']).encode(),b'0'*64)
        self.envelope['manifestSha256']=sha(self.files['pack.ini'])
        self.envelope['files'][0].update(size=len(self.files['pack.ini']),sha256=sha(self.files['pack.ini']))
        with self.assertRaisesRegex(ps.PackError,'Manifest executable'):self.run_extract(archive_bytes(self.files,self.envelope))

    def test_traversal_and_extra_file_rejected(self):
        for name in ('../escape','pack/../../escape','pack/bin/CON.exe','pack/extra.txt','elsewhere.txt','pack\\bad'):
            with self.subTest(name=name):
                path=self.root/'test.zip';path.write_bytes(archive_bytes(self.files,self.envelope,[(name,b'x')]))
                with tempfile.TemporaryDirectory(dir=self.root) as directory, self.assertRaises(ValueError):pm.extract_archive(path,Path(directory)/'out')
        self.assertFalse((self.root.parent/'escape').exists())

    def test_duplicate_case_path_and_symlink_rejected(self):
        raw=archive_bytes(self.files,self.envelope,[('pack/BIN/demo.exe',b'x')])
        with self.assertRaises(ps.PackError):self.run_extract(raw)
        symlink=zipfile.ZipInfo('pack/evil');symlink.create_system=3;symlink.external_attr=(stat.S_IFLNK|0o777)<<16
        path=self.root/'link.zip'
        with zipfile.ZipFile(path,'w') as zipped:zipped.writestr(symlink,'../../escape')
        with self.assertRaisesRegex(ps.PackError,'Links'):pm.extract_archive(path,self.root/'link-out')

    def test_incompatible_archive_rejected_before_extract(self):
        self.envelope['minAppVersion']='999.0.0'
        with self.assertRaisesRegex(ps.PackError,'Requires Workbench'):self.run_extract(archive_bytes(self.files,self.envelope))
        self.assertFalse((self.root/'out/pack').exists())

    def test_expanded_size_and_directory_case_limits(self):
        self.envelope['files'][0]['size']=pm.MAX_PACK_BYTES+1
        with self.assertRaises(ps.PackError):pm._archive_envelope(self.envelope)
        self.files,self.envelope=fixture()
        self.envelope['files'].extend([{'path':'BIN/extra','size':1,'sha256':'0'*64}])
        with self.assertRaisesRegex(ps.PackError,'Case-colliding'):pm._archive_envelope(self.envelope)

    def test_cancel_never_publishes_and_cleans_staging(self):
        path=self.root/'pack.zip';path.write_bytes(archive_bytes(self.files,self.envelope))
        cancel=threading.Event();cancel.set()
        manager=pm.PackManager(self.root,lambda request:self.fail('Cancelled import reached publication'))
        with self.assertRaises(pm.PackCancelled):manager.import_archive(path,cancel)
        self.assertEqual(list(manager.data.glob('_import-*')),[])

    def test_cancel_during_extraction_retains_cancel_type(self):
        path=self.root/'pack.zip';path.write_bytes(archive_bytes(self.files,self.envelope))
        cancel=threading.Event()
        manager=pm.PackManager(self.root,lambda request:self.fail('Cancelled extraction reached publication'))
        def progress(event):
            if event['phase']=='verifying':cancel.set()
        with self.assertRaises(pm.PackCancelled):manager.import_archive(path,cancel,progress)
        self.assertEqual(list(manager.data.glob('_import-*')),[])
        self.assertFalse((self.root/'user-data/pack-receipts/demo-1.0.0.json').exists())

    def test_offline_publisher_label_and_success_receipt(self):
        path=self.root/'pack.zip';path.write_bytes(archive_bytes(self.files,self.envelope))
        captured=[]
        def importer(request):
            self.assertTrue(Path(request,'pack.ini').is_file())
            return {'success':True}
        manager=pm.PackManager(self.root,importer)
        result=manager.import_archive(path,event=captured.append)
        self.assertTrue(result['success']);self.assertFalse(result['publisherVerified'])
        self.assertFalse(captured[-1]['cancellable'])
        receipt=json.loads((self.root/'user-data/pack-receipts/demo-1.0.0.json').read_text())
        self.assertEqual(receipt['manifestSha256'],self.envelope['manifestSha256'])
        self.assertEqual(list(manager.data.glob('_import-*')),[])

    def test_receipt_write_failure_prevents_publication(self):
        path=self.root/'pack.zip';path.write_bytes(archive_bytes(self.files,self.envelope))
        manager=pm.PackManager(self.root,lambda request:self.fail('Receipt failure reached native publication'))
        with patch.object(pm.os,'replace',side_effect=OSError('disk failure')):
            with self.assertRaises(OSError):manager.import_archive(path)
        self.assertEqual(list((self.root/'user-data/pack-receipts').glob('_write-*')),[])

    def test_receipt_visible_during_publication_and_cleanup_on_exception(self):
        path=self.root/'pack.zip';path.write_bytes(archive_bytes(self.files,self.envelope))
        receipt=self.root/'user-data/pack-receipts/demo-1.0.0.json'
        def fail_import(source):
            self.assertTrue(receipt.is_file())
            raise ValueError('Native copy failed')
        manager=pm.PackManager(self.root,fail_import)
        with self.assertRaisesRegex(ValueError,'Native copy failed'):manager.import_archive(path)
        self.assertFalse(receipt.exists())

    def test_existing_version_receipt_is_never_modified(self):
        folder=self.root/'packs/custom-folder';folder.mkdir(parents=True)
        (folder/'pack.ini').write_bytes(self.files['pack.ini'])
        receipt=self.root/'user-data/pack-receipts/demo-1.0.0.json'
        receipt.parent.mkdir(parents=True);receipt.write_bytes(b'existing metadata')
        path=self.root/'pack.zip';path.write_bytes(archive_bytes(self.files,self.envelope))
        manager=pm.PackManager(self.root,lambda request:self.fail('Duplicate reached publication'))
        with self.assertRaisesRegex(ps.PackError,'already installed'):manager.import_archive(path)
        self.assertEqual(receipt.read_bytes(),b'existing metadata')

    def test_corrupt_canonical_version_preserves_existing_receipt(self):
        folder=self.root/'packs/DEMO-1.0.0';folder.mkdir(parents=True)
        (folder/'pack.ini').write_bytes(b'corrupted manifest')
        receipt=self.root/'user-data/pack-receipts/demo-1.0.0.json'
        receipt.parent.mkdir(parents=True);receipt.write_bytes(b'original metadata')
        path=self.root/'pack.zip';path.write_bytes(archive_bytes(self.files,self.envelope))
        manager=pm.PackManager(self.root,lambda request:self.fail('Duplicate reached publication'))
        with self.assertRaisesRegex(ps.PackError,'already installed'):manager.import_archive(path)
        self.assertEqual(receipt.read_bytes(),b'original metadata')

    def test_failed_import_writes_no_receipt(self):
        path=self.root/'pack.zip';path.write_bytes(archive_bytes(self.files,self.envelope))
        manager=pm.PackManager(self.root,lambda request:{'success':False})
        self.assertFalse(manager.import_archive(path)['success'])
        self.assertFalse((self.root/'user-data/pack-receipts/demo-1.0.0.json').exists())


class Manager(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.files,self.envelope=fixture();self.raw=archive_bytes(self.files,self.envelope)
        self.entry=entry_for(self.raw,self.envelope)
        self.manager=pm.PackManager(self.root,lambda request:{'success':True},lambda:{'packs':[],'tools':{}})
    def tearDown(self):self.temp.cleanup()
    def add(self):
        path=self.root/'source.json';path.write_text(json.dumps(SOURCE));return self.manager.add_source(path)
    def cache(self,doc=None):
        path=self.manager.data/'cache/test-feed.json';path.parent.mkdir(parents=True,exist_ok=True)
        path.write_bytes(sign(doc or payload(self.entry)));return path

    def test_empty_snapshot_has_no_network_or_state_writes(self):
        with patch.object(pm,'_download',side_effect=AssertionError('Implicit network')):
            snapshot=self.manager.snapshot()
        self.assertEqual(snapshot['packs'],[]);self.assertEqual(snapshot['sources'],[])
        self.assertFalse(self.manager.data.exists())

    def bundle(self, sources=None):
        path=self.root/'workspace/catalog-sources.json';path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text(json.dumps(sources if sources is not None else [SOURCE]));return path

    def test_bundled_source_is_read_only_without_network(self):
        path=self.bundle();before=path.read_bytes()
        with patch.object(pm,'_download',side_effect=AssertionError('Implicit network')):
            snapshot=self.manager.snapshot()
        self.assertEqual(len(snapshot['sources']),1)
        self.assertEqual(snapshot['sources'][0]['id'],SOURCE['id'])
        self.assertEqual(path.read_bytes(),before);self.assertFalse(self.manager.data.exists())

    def test_imported_bundled_source_is_deduplicated_without_write(self):
        self.bundle()
        self.assertFalse(self.add()['added'])
        self.assertEqual(len(self.manager._sources()),1)
        self.assertFalse(self.manager.sources_path.exists())

    def test_source_addition_writes_only_user_sources(self):
        bundled=copy.deepcopy(SOURCE);bundled['id']='bundled-feed'
        path=self.bundle([bundled]);before=path.read_bytes()
        self.assertTrue(self.add()['added'])
        self.assertEqual(json.loads(self.manager.sources_path.read_bytes()),[SOURCE])
        self.assertEqual(path.read_bytes(),before)
        self.assertEqual({source['id'] for source in self.manager._sources()},{'bundled-feed','test-feed'})

    def test_bundled_source_cannot_be_overridden(self):
        path=self.bundle();before=path.read_bytes()
        changed=copy.deepcopy(SOURCE);changed['catalogUrl']='https://example.invalid/different.json'
        candidate=self.root/'candidate.json';candidate.write_text(json.dumps(changed))
        with self.assertRaisesRegex(ps.PackError,'preserved'):self.manager.add_source(candidate)
        self.assertEqual(path.read_bytes(),before);self.assertFalse(self.manager.sources_path.exists())
        self.manager.sources_path.parent.mkdir(parents=True)
        self.manager.sources_path.write_text(json.dumps([changed]))
        with self.assertRaisesRegex(ps.PackError,'cannot be overridden'):self.manager.snapshot()
        self.assertEqual(path.read_bytes(),before)

    def test_merged_catalogue_limit_counts_bundled_sources(self):
        sources=[]
        for index in range(16):
            source=copy.deepcopy(SOURCE);source['id']='bundled-'+str(index);sources.append(source)
        self.bundle(sources)
        with self.assertRaisesRegex(ps.PackError,'At most 16'):self.add()
        self.assertFalse(self.manager.sources_path.exists())

    def test_read_cached_catalogue_no_network_and_exact_installed_version(self):
        self.add();self.cache()
        self.manager.catalog_callback=lambda:{'packs':[{'id':'demo','version':'1.0.0','manifestSha256':self.envelope['manifestSha256'],'folder':'packs/demo-1.0.0'}],'tools':{}}
        with patch.object(pm,'_download',side_effect=AssertionError('Implicit network')):
            row=self.manager.snapshot()['packs'][0]
        self.assertTrue(row['installed']);self.assertTrue(row['publisherVerified']);self.assertFalse(row['updateAvailable'])

    def test_failed_refresh_preserves_verified_cache(self):
        self.add();path=self.cache();before=path.read_bytes()
        with patch.object(pm,'_download',side_effect=ps.PackError('Network unavailable')):
            result=self.manager.snapshot(refresh=True)
        self.assertEqual(path.read_bytes(),before)
        self.assertEqual(len(result['packs']),1);self.assertIn('Network unavailable',result['sources'][0]['error'])

    def test_cache_tampering_not_trusted(self):
        self.add();path=self.cache();data=json.loads(path.read_bytes());data['signature']=base64.b64encode(b'\0'*256).decode();path.write_text(json.dumps(data))
        result=self.manager.snapshot()
        self.assertEqual(result['packs'],[]);self.assertIn('signature',result['sources'][0]['error'])

    def test_catalogue_rollback_preserves_current_cache(self):
        self.add();path=self.cache();before=path.read_bytes()
        def download(url,hosts,destination,*args,**kwargs):Path(destination).write_bytes(sign(payload(self.entry,'2026-10-02T12:00:00Z')))
        with patch.object(pm,'_download',side_effect=download):result=self.manager.snapshot(refresh=True)
        self.assertEqual(path.read_bytes(),before);self.assertIn('rollback',result['sources'][0]['error'])

    def test_source_id_cannot_silently_change_trust(self):
        self.add();changed=copy.deepcopy(SOURCE);changed['catalogUrl']='https://example.invalid/different.json'
        path=self.root/'source.json';path.write_text(json.dumps(changed))
        with self.assertRaisesRegex(ps.PackError,'preserved'):self.manager.add_source(path)
        self.assertEqual(self.manager._sources()[0],SOURCE)

    def test_install_verifies_download_and_reaches_atomic_import(self):
        self.add();self.cache();events=[]
        def download(url,hosts,destination,*args,**kwargs):Path(destination).write_bytes(self.raw)
        with patch.object(pm,'_download',side_effect=download):result=self.manager.install('test-feed','demo','1.0.0',event=events.append)
        self.assertTrue(result['success']);self.assertTrue(result['publisherVerified'])
        self.assertEqual(events[-1]['phase'],'publishing');self.assertFalse(events[-1]['cancellable'])
        self.assertEqual(list(self.manager.data.glob('_install-*')),[])

    def test_install_refuses_archive_not_bound_by_signature(self):
        self.add();self.cache()
        def download(url,hosts,destination,*args,**kwargs):Path(destination).write_bytes(self.raw+b'evil')
        with patch.object(pm,'_download',side_effect=download),self.assertRaisesRegex(ps.PackError,'size'):
            self.manager.install('test-feed','demo','1.0.0')

    def test_numeric_updates_and_unknown_installed_pack(self):
        self.add();self.entry['version']='1.10.0';self.cache()
        self.manager.catalog_callback=lambda:{'packs':[{'id':'demo','version':'1.9.0','manifestSha256':'0'*64,'folder':'packs/demo-1.9.0'},{'id':'other','version':'0.1.0','manifestSha256':'1'*64,'folder':'packs/other'}],'tools':{}}
        rows=self.manager.snapshot()['packs']
        self.assertTrue(next(row for row in rows if row['version']=='1.10.0')['updateAvailable'])
        self.assertTrue(next(row for row in rows if row['id']=='other')['installed'])


if __name__=='__main__':unittest.main()
