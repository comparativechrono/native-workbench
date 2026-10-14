#!/usr/bin/env python3
"""Native setup gate, with explicitly separate exact-GUI and fixture scopes.

The normal gate requires an untouched disposable candidate extraction. Its GUI
is executed unchanged. Signed batch fixtures use a second extraction with only
catalog-sources.json/setup-profile.json replaced by TEST-ONLY configuration;
installed application code and the native importer remain unchanged. A child
process substitutes HTTP response bytes, never signature/inventory verification.
--full-catalogue additionally installs real published packs with a test-signed
catalogue and real HTTPS asset transfers. That is NOT production trust evidence.
--production-full instead requires the packaged official trust and uses it as-is.
"""
from __future__ import annotations

import argparse
import ast
import base64
import copy
import ctypes
from ctypes import wintypes
from datetime import datetime, timezone
import hashlib
import io
import json
import os
from pathlib import Path
import platform
import queue
import shutil
import subprocess
import sys
import threading
import time
import traceback
import zipfile

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_references_windows import PrivateHost, require, sha256, write_json, stop_process_tree
from check_workspace_ui_windows import NativeUI, native_scientific_chain

TEST_URL = 'https://setup-fixture.invalid/catalogue.json'
SOURCE_ID = 'native-workbench-official'


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def check(report, text):
    report['checks'].append(text)
    print(json.dumps({'check': text, 'passed': len(report['checks'])}), flush=True)
    report['passed'] = len(report['checks'])
    write_json(report['reportPath'], report)


def core_hashes(root):
    paths = [root / 'NativeWorkbench.exe', root / 'WorkbenchBridge.exe']
    paths.extend(p for p in (root / 'workspace').rglob('*')
                 if p.is_file() and '__pycache__' not in p.parts)
    return {p.relative_to(root).as_posix(): sha256(p) for p in sorted(paths) if p.is_file()}


def wait_setup(host, expected='completed', timeout=180):
    deadline = time.monotonic() + timeout
    last_progress, last_time = None, 0
    while time.monotonic() < deadline:
        state = host.call('setup/status')
        op = state['operation']
        progress = (op.get('completed'), op.get('current'), op.get('phase'))
        if progress != last_progress or time.monotonic() - last_time > 15:
            print(json.dumps({'setupProgress': op}), flush=True)
            last_progress, last_time = progress, time.monotonic()
        if not op.get('active'):
            require(op.get('status') == expected,
                    'Setup ended unexpectedly: ' + json.dumps(op))
            return state
        time.sleep(.05)
    raise TimeoutError('Setup did not finish within the validation deadline.')


def test_signature(document):
    # Existing deliberately public unit-test key. It is never a production key
    # and is read only by this gate, not bundled into the installed application.
    source = Path(__file__).resolve().parents[1] / 'tests/test_pack_manager.py'
    literals = {}
    for node in ast.parse(source.read_text(encoding='utf-8')).body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            name = getattr(node.targets[0], 'id', '')
            if name in ('N', 'D'):
                literals[name] = ast.literal_eval(node.value)
    require(set(literals) == {'N', 'D'}, 'The explicit test-only signing fixture is unavailable.')
    payload = json.dumps(document, separators=(',', ':')).encode()
    info = bytes.fromhex('3031300d060960864801650304020105000420') + hashlib.sha256(payload).digest()
    length = len(literals['N']) // 2
    encoded = b'\x00\x01' + b'\xff' * (length-len(info)-3) + b'\x00' + info
    signature = pow(int.from_bytes(encoded, 'big'), int(literals['D'], 16),
                    int(literals['N'], 16)).to_bytes(length, 'big')
    wrapper = {'schema': 1, 'payload': base64.b64encode(payload).decode(),
               'signature': base64.b64encode(signature).decode()}
    return json.dumps(wrapper).encode(), {'n': literals['N'], 'e': 65537}


def fixture_archive(identity, executable, padding=0, licenses=None):
    """A synthetic pack around an unchanged native SAMtools executable."""
    digest = hashlib.sha256(executable).hexdigest()
    manifest = f'''[pack]
format=2
id={identity}
version=1.0.0
name=Setup test {identity}
platform=windows-x86_64
[tool:samtools]
path=bin/samtools.exe
version=setup-fixture
sha256={digest}
[workflow:version]
name=Setup fixture version
inputs=
outputs=version
steps=run
[output:version:version]
label=Version
path=version.txt
[step:version:run]
label=SAMtools version
kind=exec
tool=samtools
arg.0=--version
stdout=version
'''.encode()
    files = {'pack.ini': manifest, 'bin/samtools.exe': executable,
             'licenses/TEST-FIXTURE.txt': b'Synthetic validation wrapper, not a distributed scientific pack.\n'}
    files.update(licenses or {})
    if padding:
        files['licenses/setup-test-padding.bin'] = hashlib.shake_256(identity.encode()).digest(padding)
    envelope = {'schema': 1, 'id': identity, 'version': '1.0.0', 'packApi': 1,
                'minAppVersion': '0.10.0', 'platform': 'windows-x86_64',
                'manifestSha256': hashlib.sha256(manifest).hexdigest(),
                'files': [{'path': name, 'size': len(data), 'sha256': hashlib.sha256(data).hexdigest()}
                          for name, data in files.items()]}
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('workbench-pack.json', json.dumps(envelope))
        for name, data in files.items():
            archive.writestr('pack/' + name, data)
    raw = buffer.getvalue()
    entry = {'id': identity, 'name': 'Setup test ' + identity, 'version': '1.0.0',
             'toolVersions': {'samtools': 'setup-fixture'}, 'description': 'Synthetic setup validation pack',
             'category': 'Testing', 'platform': 'windows-x86_64', 'packApi': 1,
             'minAppVersion': '0.10.0', 'downloadURL': 'https://setup-fixture.invalid/' + identity + '.zip',
             'size': len(raw), 'sha256': hashlib.sha256(raw).hexdigest(),
             'manifestSha256': envelope['manifestSha256']}
    return raw, entry


# Only urllib's response acquisition is substituted in the isolated test child.
# Every production URL policy, size/hash, signature, inventory and import check
# remains active. Real published asset requests can be explicitly allowed.
FIXTURE_BOOTSTRAP = r'''
import io,json,sys,time,urllib.request,urllib.parse
from pathlib import Path
sys.dont_write_bytecode=True
root,fixture,live=sys.argv[1],Path(sys.argv[2]),sys.argv[3]=='1'
def deny(event,args):
 if not live and event.startswith('socket.'):
  raise RuntimeError('TEST FIXTURE forbids network: '+event)
sys.addaudithook(deny)
original=urllib.request.OpenerDirector.open
class Response(io.BytesIO):
 def __init__(self,data,url,slow):
  super().__init__(data);self.url=url;self.slow=slow
  self.headers={'Content-Length':str(len(data)),'Content-Encoding':'identity'}
 def getcode(self):return 200
 def geturl(self):return self.url
 def read1(self,size):
  if self.slow:time.sleep(.03)
  return super().read1(min(size,16384 if self.slow else size))
def open_fixture(self,request,*args,**kwargs):
 url=request.full_url if hasattr(request,'full_url') else str(request)
 mapping=json.loads((fixture/'transport.json').read_text())
 with (fixture/'requests.jsonl').open('a') as stream:
  parsed=urllib.parse.urlsplit(url)
  recorded=urllib.parse.urlunsplit((parsed.scheme,parsed.netloc,parsed.path,'',''))
  stream.write(json.dumps({'url':recorded,'utc':time.time()})+'\n')
 if url in mapping:
  spec=mapping[url]
  return Response((fixture/spec['file']).read_bytes(),url,spec.get('slow',False))
 if live:return original(self,request,*args,**kwargs)
 raise RuntimeError('Unexpected fixture transport request: '+url)
urllib.request.OpenerDirector.open=open_fixture
sys.path.insert(0,str(Path(root)/'workspace'))
from desktop_host import main
raise SystemExit(main(['--app-root',root]))
'''


class FixtureHost(PrivateHost):
    def __init__(self, root, evidence, name, fixture, live=False):
        self.sequence = 0
        self.messages = queue.Queue()
        self.stderr = (evidence / (name + '.stderr.txt')).open('wb')
        command = [str(root / 'runtime/python/python.exe'), '-I', '-u', '-c',
                   FIXTURE_BOOTSTRAP, str(root), str(fixture), '1' if live else '0']
        self.process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                        stderr=self.stderr, cwd=root)
        self.thread = threading.Thread(target=self._read, daemon=True)
        self.thread.start()


def prepare_fixture(root, fixture, entries, blobs):
    fixture.mkdir(parents=True)
    document = {'schema': 1, 'publishedAt': '2026-10-06T00:00:00Z', 'packs': entries}
    signed, key = test_signature(document)
    (fixture / 'catalogue.json').write_bytes(signed)
    hosts = {'setup-fixture.invalid', 'github.com', 'release-assets.githubusercontent.com',
             'objects.githubusercontent.com'}
    source = {'schema': 1, 'id': SOURCE_ID, 'name': 'TEST ONLY setup publisher',
              'catalogUrl': TEST_URL, 'publicKey': key, 'allowedHosts': sorted(hosts)}
    write_json(root / 'workspace/catalog-sources.json', [source])
    profile = read_json(root / 'workspace/setup-profile.json')
    profile['sourceId'] = SOURCE_ID
    old_starter = {row['id']: row for row in profile['packs'] if row['starter']}
    selected = [{key: entry[key] for key in ('id', 'name', 'version', 'size', 'sha256', 'manifestSha256')}
                | {'starter': entry['id'] in old_starter} for entry in entries]
    if not any(row['starter'] for row in selected):
        selected = list(old_starter.values()) + selected
    profile['packs'] = selected
    write_json(root / 'workspace/setup-profile.json', profile)
    mapping = {TEST_URL: {'file': 'catalogue.json'}}
    for identity, data in blobs.items():
        name = identity + '.zip'
        (fixture / name).write_bytes(data)
        mapping['https://setup-fixture.invalid/' + name] = {'file': name, 'slow': identity == 'setup-b'}
    write_json(fixture / 'transport.json', mapping)
    return {'notice': 'Public unit-test signing key and substituted response bytes; NOT production publisher trust.',
            'catalogueSha256': sha256(fixture / 'catalogue.json'),
            'configuration': {name: sha256(root / 'workspace' / name)
                              for name in ('catalog-sources.json', 'setup-profile.json')}}


def unchanged(before, root, exceptions=()):
    after = core_hashes(root)
    require({k: v for k, v in before.items() if k not in exceptions} ==
            {k: v for k, v in after.items() if k not in exceptions},
            'Setup changed application code, executables or unrelated bundled metadata.')


def ui_polling_checks(root, evidence, report, expect_regression=False):
    """Observe real desktop frames and real setup polling, with no host substitution.

    The control may install completed packs before cancellation. Call this with
    its own disposable exact extraction. A failure to reach the live operation
    is a failed prerequisite, never an expected UI regression.
    """
    evidence.mkdir(parents=True, exist_ok=True)
    before = core_hashes(root)
    ui = NativeUI(root, evidence)
    observations = {'expectedRegression': expect_regression, 'defects': [], 'navigationDefects': [],
                    'scope': 'Exact native GUI and production trust; real HTTPS refresh/install briefly followed by cancellation.',
                    'physicalDisplayCoverage': False, 'productionFullCompleted': False}
    def record(condition, message, category='navigation'):
        if not condition:
            observations['defects'].append(message)
            if category == 'navigation':
                observations['navigationDefects'].append(message)
    def setup_window():
        return next((h for h in ui.windows() if ui.label(h, True) == 'WorkbenchToolSetup0100'), None)
    def enabled(identity):
        return bool(ui.user.IsWindowEnabled(ui.child(identity, owner)))
    def click(identity):
        control = ui.child(identity, owner)
        require(control and enabled(identity), 'Polling gate control is unavailable: ' + str(identity))
        left, top, right, bottom = ui.bounds(control)
        ui.click_at((left+right)//2, (top+bottom)//2)
        if identity in (702, 703, 704):
            # SendInput queues mouse events; a previous row-focus state cannot
            # acknowledge that the newly clicked profile has been processed.
            ui.wait('polling gate profile acknowledged ' + str(identity), lambda:
                    ui.send(control, 0x00F0) == 1)
    def position():
        return {'top': ui.send(listing, 0x1027),
                'selected': ui.send(listing, 0x100C, -1, 2),
                'focused': ui.send(listing, 0x100C, -1, 1),
                'horizontal': ui.scroll_info(listing, 0)['nPos']}
    class GuiThreadInfo(ctypes.Structure):
        _fields_ = [('cbSize', wintypes.DWORD), ('flags', wintypes.DWORD),
                    ('hwndActive', wintypes.HWND), ('hwndFocus', wintypes.HWND),
                    ('hwndCapture', wintypes.HWND), ('hwndMenuOwner', wintypes.HWND),
                    ('hwndMoveSize', wintypes.HWND), ('hwndCaret', wintypes.HWND),
                    ('rcCaret', wintypes.RECT)]
    ui.user.GetGUIThreadInfo.argtypes = [wintypes.DWORD, ctypes.POINTER(GuiThreadInfo)]
    ui.user.GetGUIThreadInfo.restype = wintypes.BOOL
    def focus_listing():
        # SendInput is asynchronous, and LVIS_FOCUSED remembers a row even
        # while a radio/default button owns actual keyboard focus. Space must
        # only be posted after the application thread confirms focus is here.
        ui.click_at(left + 75, header_bottom + 10)
        if not enabled(705):
            return  # Preserve the disabled-list negative control observation.
        def focused():
            info = GuiThreadInfo()
            info.cbSize = ctypes.sizeof(info)
            thread = ui.user.GetWindowThreadProcessId(owner, None)
            require(ui.user.GetGUIThreadInfo(thread, ctypes.byref(info)),
                    'Could not observe the actual native GUI keyboard focus.')
            return info.hwndFocus == listing
        ui.wait('polling gate actual keyboard focus in package list', focused)
    def frames(name, seconds, expected_position=None, busy=False):
        # BitBlt reads presented pixels; unlike PrintWindow this does not ask
        # the application to repaint and hide an intermediate blank header.
        sample = {'seconds': seconds, 'frames': 0, 'headerHashes': {},
                  'positionChanges': [], 'busySamples': 0, 'disabledSamples': 0,
                  'notices': [], 'progressStates': [],
                  'pixelComparison': 'BGR bytes only; undefined BitBlt alpha ignored'}
        busy_first = busy_last = None
        boundary = ui.bounds(header)
        ui.mouse(*ui.bounds(ui.child(706, owner))[:2])
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            require(ui.process.poll() is None, 'Native GUI exited during sustained observation.')
            _, pixels = ui.screen_capture(name + '-last.bmp', boundary)
            bgr = bytearray(len(pixels) // 4 * 3)
            for channel in range(3):
                bgr[channel::3] = pixels[channel::4]
            digest = hashlib.sha256(bgr).hexdigest()
            sample['headerHashes'][digest] = sample['headerHashes'].get(digest, 0) + 1
            sample['frames'] += 1
            if expected_position is not None:
                observed = position()
                if observed != expected_position and observed not in sample['positionChanges']:
                    sample['positionChanges'].append(observed)
            if not enabled(713):
                sample['busySamples'] += 1
                sample['disabledSamples'] += not enabled(705)
                busy_last = time.monotonic()
                if busy_first is None:
                    busy_first = busy_last
            notice = ui.label(ui.child(707, owner))
            if not sample['notices'] or sample['notices'][-1] != notice:
                sample['notices'].append(notice)
            progress = {'notice': notice, 'position': ui.send(ui.child(708, owner), 0x0408)}
            if not sample['progressStates'] or sample['progressStates'][-1] != progress:
                sample['progressStates'].append(progress)
            time.sleep(.04)
        sample['observedBusySeconds'] = 0 if busy_first is None else busy_last - busy_first
        if busy:
            require(sample['busySamples'] >= 20 and sample['observedBusySeconds'] >= 3,
                    'Live setup did not remain active long enough to test multiple status polls: ' + json.dumps(sample))
            require(len(sample['progressStates']) >= 2,
                    'No changing host status/progress was observed during the active interval; repeated polling was not established.')
        return sample
    try:
        ui.wait('polling gate first-run setup', setup_window)
        owner = setup_window()
        ui.wait('polling gate populated list', lambda: ui.child(705, owner) and
                ui.send(ui.child(705, owner), 0x1004) == 32)
        listing = ui.child(705, owner)
        header = ui.send(listing, 0x101F)
        click(704)
        ui.wait('polling gate Custom selection', lambda: ui.send(ui.child(704, owner), 0x00F0) == 1)
        scale = ui.user.GetDpiForWindow(owner) / 96
        ui.user.MoveWindow(owner, 0, 0, round(830*scale), round(650*scale), True)
        left, _, right, bottom = ui.bounds(listing)
        header_bottom = ui.bounds(header)[3]
        focus_listing()
        ui.key(listing, 0x24)
        ui.wait('polling gate first pack selected', lambda: ui.send(listing, 0x100C, -1, 1) == 0)
        # Select all 32 through normal Custom keyboard interaction. This makes
        # the later locked-checkbox assertion meaningful: this same checkbox
        # was editable before the download operation started.
        for row in range(32):
            if ui.send(listing, 0x102C, row, 0xF000) != 0x2000:
                ui.key(listing, 0x20)
                ui.wait('Custom pack selected ' + str(row), lambda row=row:
                        ui.send(listing, 0x102C, row, 0xF000) == 0x2000)
            if row < 31:
                ui.key(listing, 0x28)
                ui.wait('Custom focus ' + str(row+1), lambda row=row:
                        ui.send(listing, 0x100C, -1, 1) == row+1)
        # No operation is active, so no backend poll can repair stale local
        # checkbox state. Prime an all-checked rendering, edit Custom, then
        # immediately return to Full and inspect the actual native checkmarks.
        click(702)
        click(704)
        # A radio click moves keyboard focus away from the list. Restore it
        # through normal pointer interaction before posting navigation/Space.
        focus_listing()
        ui.key(listing, 0x23)
        ui.wait('Custom final pack focused before immediate profile switch', lambda:
                ui.send(listing, 0x100C, -1, 1) == 31)
        ui.key(listing, 0x20)
        ui.wait('Custom final pack unchecked', lambda: ui.send(listing, 0x102C, 31, 0xF000) == 0x1000)
        click(702)
        ui.wait('Full restores every visible check without a status poll', lambda:
                all(ui.send(listing, 0x102C, row, 0xF000) == 0x2000 for row in range(32)))
        click(704)
        ui.wait('Custom retains the previous unchecked choice', lambda:
                ui.send(listing, 0x102C, 31, 0xF000) == 0x1000)
        focus_listing()
        ui.key(listing, 0x23)
        ui.wait('Custom final pack focused again', lambda: ui.send(listing, 0x100C, -1, 1) == 31)
        ui.key(listing, 0x20)
        ui.wait('Custom final pack reselected for the polling probe', lambda:
                ui.send(listing, 0x102C, 31, 0xF000) == 0x2000)
        observations['immediateCustomFullChecks'] = True
        ui.key(listing, 0x23)
        ui.wait('polling gate can initially reach final row', lambda: ui.send(listing, 0x1027) > 0)
        time.sleep(.3)
        idle_position = position()
        observations['idle'] = frames('setup-idle-header', 3, idle_position)
        record(len(observations['idle']['headerHashes']) == 1,
               'Unchanged column header pixels changed during idle sampling.', 'pixels')
        record(not observations['idle']['positionChanges'], 'Idle setup moved the viewport or selection.')
        # A genuine wheel input must move the viewport without changing the
        # highlighted pack. Hold the new viewport through another idle interval.
        ui.wheel(left + 100, header_bottom + 30, 360)
        ui.wait('idle setup real wheel scroll', lambda: ui.send(listing, 0x1027) < idle_position['top'])
        wheel_position = position()
        observations['idleWheel'] = frames('setup-idle-wheel', 2, wheel_position)
        record(not observations['idleWheel']['positionChanges'], 'Wheel position was reset while idle.')
        if not expect_regression:
            record(set(observations['idleWheel']['headerHashes']) == set(observations['idle']['headerHashes']),
                   'The settled idle header changed after wheel navigation.', 'pixels')
        click(709)
        ui.wait('live catalogue refresh completed', lambda: enabled(713) and
                'Official catalogue verified.' in ui.label(ui.child(707, owner)), 120)
        observations['refreshPosition'] = position()
        record(observations['refreshPosition'] == wheel_position,
               'Catalogue row updates lost the exact viewport, highlighted pack or focus.')
        click(710)
        ui.wait('live installation starts', lambda: not enabled(713))
        record(enabled(705), 'Package list is disabled during installation, preventing native scrolling.')
        # End followed by real wheel navigation exercises the control while the
        # application is polling. The old build is intentionally still observed
        # after finding it disabled, so the negative control retains evidence.
        focus_listing()
        ui.key(listing, 0x23)
        time.sleep(.2)
        busy_end = position()
        if not expect_regression:
            require(busy_end['focused'] == 31 and busy_end['selected'] == 31,
                    'The editable-before-installation final pack was not focused for the locked-checkbox check.')
        ui.wheel(left + 100, header_bottom + 30, 360)
        time.sleep(.2)
        busy_position = position()
        observations['busyWheel'] = {'before': busy_end, 'after': busy_position}
        record(busy_position['top'] < busy_end['top'], 'Real mouse wheel cannot scroll the active installation list.')
        check_state = [ui.send(listing, 0x102C, row, 0xF000) for row in range(32)]
        observations['lockedCheckboxInteractionExecuted'] = enabled(705)
        if observations['lockedCheckboxInteractionExecuted']:
            ui.key(listing, 0x20)
            time.sleep(.1)
            record([ui.send(listing, 0x102C, row, 0xF000) for row in range(32)] == check_state,
                   'A locked installation checkbox changed while setup was active.', 'selection')
        observations['polling'] = frames('setup-busy-header', 5, busy_position, busy=True)
        record(not observations['polling']['disabledSamples'], 'Status polling disabled the inspectable package list.')
        record(not observations['polling']['positionChanges'], 'Status polling changed the viewport, highlighted pack or focus.')
        record(len(observations['polling']['headerHashes']) == 1,
               'Unchanged column header pixels changed during active status polling.', 'pixels')
        if not expect_regression:
            record(set(observations['polling']['headerHashes']) == set(observations['idle']['headerHashes']),
                   'The active-installation header differs from the settled idle header.', 'pixels')
        # Exercise the native scroll bar as well as wheel and keyboard input.
        if enabled(705):
            ui.key(listing, 0x24)
            ui.wait('busy list Home', lambda: ui.send(listing, 0x1027) == 0)
            has_horizontal = ui.scroll_info(listing, 0)['nMax'] >= ui.scroll_info(listing, 0)['nPage']
            ui.click_at(right - round(9*scale), bottom - round((27 if has_horizontal else 9)*scale))
            time.sleep(.2)
            record(ui.send(listing, 0x1027) > 0, 'Native vertical scroll-bar arrow did not scroll during setup.')
        if not enabled(713):
            ui.wait('active installation is cancellable', lambda: enabled(712), 120)
            click(712)
        ui.wait('polling gate cancellation settles', lambda: enabled(713), 120)
        observations['finalNotice'] = ui.label(ui.child(707, owner))
        observations['capture'] = ui.capture('setup-polling-final.bmp', owner)
        unchanged(before, root)
        observations['headerFlashObserved'] = any(len(observations[key]['headerHashes']) > 1
                                                   for key in ('idle', 'polling'))
        write_json(evidence/'setup-polling-observations.json', observations)
        require(bool(observations['navigationDefects']) if expect_regression else not observations['defects'],
                ('Published baseline did not reproduce a UI regression.' if expect_regression else
                 'Native setup polling regressions: ' + '; '.join(observations['defects'])))
        check(report, 'Published 0.10.0 negative control reproduces setup navigation defects.' if expect_regression else
              'Native setup keeps header pixels and viewport stable during sustained idle and live polling, supports wheel/scroll-bar navigation while busy, and blocks checkbox edits.')
        return observations
    finally:
        # This disposable probe may fail while work is still cancellable; stop
        # only its process group without a modal close-confirmation race.
        write_json(evidence/'setup-polling-observations.json', observations)
        stop_process_tree(ui.process)
        ui.user.SetThreadDpiAwarenessContext(ui.previous_dpi)
        saved = root/'user-data/tool-setup.json'
        if saved.is_file():
            shutil.copy2(saved, evidence/'tool-setup-state.json')


def gui_checks(root, evidence, report):
    ui = NativeUI(root, evidence)
    captures = []
    succeeded = False
    def setup_window():
        return next((h for h in ui.windows() if ui.label(h, True) == 'WorkbenchToolSetup0100'), None)
    def click(identity, owner):
        control = ui.child(identity, owner)
        require(control and ui.user.IsWindowVisible(control) and ui.user.IsWindowEnabled(control),
                'Setup control is not available: ' + str(identity))
        left, top, right, bottom = ui.bounds(control)
        ui.click_at((left+right)//2, (top+bottom)//2)
    try:
        ui.wait('first-run setup opens', setup_window)
        owner = setup_window()
        ui.wait('setup profiles populated', lambda: ui.child(702, owner) and ui.child(705, owner))
        require(ui.send(ui.child(702, owner), 0x00F0) == 1, 'Fresh setup did not recommend Full.')
        captures.append(ui.capture('setup-full-first-run.bmp', owner))
        check(report, 'Exact packaged native first-run setup opens with Full recommended.')
        click(704, owner)
        ui.wait('Custom radio selected', lambda: ui.send(ui.child(704, owner), 0x00F0) == 1)
        require(ui.send(ui.child(705, owner), 0x1004) >= 3, 'Custom choices omit preinstalled Starter packs.')
        rows = read_json(root/'workspace/setup-profile.json')['packs']
        optional = next(index for index, row in enumerate(rows) if not row['starter'])
        listing = ui.child(705, owner)
        header = ui.send(listing, 0x101F)  # LVM_GETHEADER returns a handle, no cross-process pointer.
        left, _, _, _ = ui.bounds(listing)
        _, _, _, header_bottom = ui.bounds(header)
        ui.click_at(left + 70, header_bottom + 10)
        ui.key(listing, 0x24)  # Home, then keyboard navigation to the first optional pack.
        for _ in range(optional):
            ui.key(listing, 0x28)
        old_state = ui.send(listing, 0x102C, optional, 0xF000)  # LVM_GETITEMSTATE.
        old_total = ui.label(ui.child(706, owner))
        ui.key(listing, 0x20)
        ui.wait('Custom checkbox changes selected download total', lambda:
                ui.send(listing, 0x102C, optional, 0xF000) != old_state and
                ui.label(ui.child(706, owner)) != old_total)
        captures.append(ui.capture('setup-custom.bmp', owner))
        check(report, 'Native Custom checkbox navigation changes the selection and recalculates its download total.')
        scale = ui.user.GetDpiForWindow(owner) / 96
        ui.user.MoveWindow(owner, 0, 0, round(830*scale), round(650*scale), True)
        ui.key(listing, 0x23)  # End scrolls to the final pack in the real native list.
        ui.wait('minimum-size setup list scrolls to final pack', lambda: ui.send(listing, 0x1027) > 0)
        geometry = ui.controls(owner)
        bounds = ui.bounds(owner)
        for identity in (702, 703, 704, 705, 706, 707, 709, 710, 711, 712, 713):
            row = next(control for control in geometry if control['id'] == identity)
            l, t, r, b = row['bounds']
            require(bounds[0] <= l < r <= bounds[2] and bounds[1] <= t < b <= bounds[3],
                    'A setup control escaped its observed minimum window bounds.')
        captures.append(ui.capture('setup-minimum-scrolled.bmp', owner))
        write_json(evidence/'setup-minimum-controls.json', geometry)
        check(report, 'At the supported minimum window size, setup controls remain within the window and the pack list scrolls.')
        click(703, owner)
        ui.wait('Starter radio selected', lambda: ui.send(ui.child(703, owner), 0x00F0) == 1)
        captures.append(ui.capture('setup-starter.bmp', owner))
        click(710, owner)
        ui.wait('offline Starter completes', lambda:
                'Your selected tools are ready.' in ui.label(ui.child(707, owner)) and
                ui.user.IsWindowEnabled(ui.child(713, owner)), 60)
        click(713, owner)
        ui.wait('Starter continues into the native workspace', lambda: not setup_window())
        ui.wait('initial setup dismissal completes', lambda: ui.user.IsWindowEnabled(ui.child(410)))
        check(report, 'Native Starter selection completes and enters the workspace without downloading packs.')
        ui.click_button(402)
        def manager():
            return next((h for h in ui.windows() if ui.label(h, True) == 'WorkbenchPackManager060'), None)
        ui.wait('Manage tools after setup', manager)
        click(714, manager())
        ui.wait('setup reopened through Manage tools', setup_window)
        captures.append(ui.capture('setup-reopened.bmp', setup_window()))
        click(713, setup_window())
        ui.wait('reopened setup closes', lambda: not setup_window())
        if manager():
            click(513, manager())
        ui.wait('workspace idle after setup dismissal', lambda:
                ui.user.IsWindowEnabled(ui.child(410)) and ui.user.IsWindowEnabled(ui.child(402)))
        check(report, 'Manage tools remains available and reopens Tool setup after first-run completion.')
        succeeded = True
        return {'captures': captures, 'nativeGUIValidated': True,
                'scope': 'Exact unmodified native GUI; first-run, profiles, offline Starter, reopening. Batch transfers validated separately.'}
    except Exception:
        owner = setup_window()
        if owner:
            ui.capture('setup-failure.bmp', owner)
            write_json(evidence/'setup-failure-controls.json', ui.controls(owner))
        raise
    finally:
        if succeeded:
            ui.close()
        else:
            # Do not race a queued setup/dismiss with main WM_CLOSE: that
            # opens the app's deliberate close-confirmation dialog. Preserve
            # the original failure, then stop only this gate-owned process.
            stop_process_tree(ui.process)
            ui.user.SetThreadDpiAwarenessContext(ui.previous_dpi)
            log = root/'user-data/desktop-host.stderr.txt'
            if log.is_file():
                shutil.copyfile(log, evidence/'ui-desktop-host.stderr.txt')


def fixture_checks(root, evidence, report):
    fixture_root = root.parent / (root.name + '-setup-fixture')
    require(not fixture_root.exists(), 'Fixture extraction must be fresh.')
    shutil.copytree(root, fixture_root)
    # Keep the explicitly installed user sentinel; clear only setup state in our
    # disposable copy so the exact-GUI completion does not mask fresh behavior.
    data = fixture_root / 'user-data'
    (data/'tool-setup.json').unlink(missing_ok=True)
    fixture = evidence / 'transport-fixture'
    origin = root/'packs/bam-0.4.0'
    executable = (origin/'bin/samtools.exe').read_bytes()
    licenses = {path.relative_to(origin).as_posix(): path.read_bytes()
                for path in (origin/'licenses').rglob('*') if path.is_file()}
    require(bool(licenses), 'The original SAMtools fixture licensing material is missing.')
    a, entry_a = fixture_archive('setup-a', executable, licenses=licenses)
    b, entry_b = fixture_archive('setup-b', executable, padding=2*1024*1024, licenses=licenses)
    c, entry_c = fixture_archive('setup-c', executable, licenses=licenses)
    config = prepare_fixture(fixture_root, fixture, [entry_a, entry_b, entry_c],
                             {'setup-a': a, 'setup-b': b, 'setup-c': c})
    config['fixtureOrigin'] = {'pack': 'bam-0.4.0',
        'executableSha256': hashlib.sha256(executable).hexdigest(),
        'preservedLicenseFiles': {name: hashlib.sha256(data).hexdigest() for name, data in licenses.items()}}
    original = core_hashes(root)
    marker = data / 'saved-settings' / 'preserve-setup-gate.json'
    marker.parent.mkdir(exist_ok=True)
    marker.write_text('{"syntheticExistingUserSetting":true}\n', encoding='utf-8')
    marker_sha = sha256(marker)
    installed_before = {p.relative_to(fixture_root).as_posix(): sha256(p)
                        for p in (fixture_root/'packs').rglob('*') if p.is_file()}
    host = FixtureHost(fixture_root, evidence, 'signed-fixture', fixture)
    try:
        host.call('init')
        initial = host.call('setup/status')
        require(initial['configured'], 'Explicit test-only source was not recognised.')
        require(not (fixture/'requests.jsonl').exists(), 'Setup status silently performed network transport.')
        host.call('setup/refresh')
        state = wait_setup(host)
        require({row['id'] for row in state['rows']}.issuperset({'setup-a', 'setup-b', 'setup-c'}),
                'Verified catalogue was not presented by setup.')
        check(report, 'Packaged backend refresh verifies a test-signed catalogue; startup/status perform no transport.')
        host.call('setup/start', {'profile': 'custom', 'pack_ids': ['setup-a', 'setup-b']})
        deadline = time.monotonic() + 120
        while time.monotonic() < deadline:
            state = host.call('setup/status')
            if ((fixture_root/'packs/setup-a-1.0.0/pack.ini').exists()
                    and state['operation'].get('current') == entry_b['name']
                    and state['operation'].get('currentBytes', 0) > 0
                    and state['operation'].get('cancellable')):
                host.call('setup/cancel')
                break
            require(state['operation'].get('active'), 'Batch ended before controlled second-pack cancellation.')
            time.sleep(.02)
        else:
            raise TimeoutError('Did not reach second-pack download for cancellation.')
        wait_setup(host, 'cancelled')
        completed = fixture_root/'packs/setup-a-1.0.0/pack.ini'
        require(completed.is_file() and not (fixture_root/'packs/setup-b-1.0.0').exists(),
                'Cancellation lost a completed pack or exposed an incomplete pack.')
        completed_sha = sha256(completed)
        require(not list((data/'pack-manager').glob('_install-*')), 'Cancelled batch left partial installation staging.')
        require(not (fixture_root/'packs/setup-c-1.0.0').exists(), 'Custom installed an unselected pack.')
        check(report, 'Custom batch cancellation retains the first installed pack, removes partial second-pack files and leaves unselected packs absent.')
    finally:
        host.close()
    host = FixtureHost(fixture_root, evidence, 'retry-fixture', fixture)
    try:
        host.call('init')
        host.call('setup/retry')
        state = wait_setup(host)
        require((fixture_root/'packs/setup-b-1.0.0/pack.ini').is_file() and sha256(completed) == completed_sha,
                'Retry failed to finish the exact saved selection or changed a completed pack.')
        requests = [json.loads(line)['url'] for line in (fixture/'requests.jsonl').read_text().splitlines()]
        require(requests.count(entry_a['downloadURL']) == 1, 'Retry redownloaded the already completed pack.')
        check(report, 'Restart and Retry restore the saved selection and download only the incomplete pack.')
        # Corrupt same-size payload must fail the signed archive hash.
        damaged = bytearray(c)
        damaged[len(damaged)//2] ^= 1
        (fixture/'setup-c.zip').write_bytes(damaged)
        host.call('setup/start', {'profile': 'custom', 'pack_ids': ['setup-c']})
        failed = wait_setup(host, 'failed')
        require('checksum' in json.dumps(failed).lower() and not (fixture_root/'packs/setup-c-1.0.0').exists(),
                'Signed digest mismatch was not rejected before publication.')
        (fixture/'setup-c.zip').write_bytes(c)
        host.call('setup/retry')
        wait_setup(host)
        require((fixture_root/'packs/setup-c-1.0.0/pack.ini').is_file(), 'Retry did not recover after a corrected transfer.')
        check(report, 'Corrupt archive bytes are rejected before installation; retry succeeds only with the signed exact bytes.')
        before_cache = sha256(data/'pack-manager/cache'/ (SOURCE_ID+'.json'))
        wrapper = read_json(fixture/'catalogue.json')
        wrapper['signature'] = base64.b64encode(bytes(256)).decode()
        write_json(fixture/'catalogue.json', wrapper)
        host.call('setup/refresh')
        state = wait_setup(host, 'failed')
        require(sha256(data/'pack-manager/cache'/(SOURCE_ID+'.json')) == before_cache,
                'An invalid signature replaced the previously verified catalogue.')
        check(report, 'Invalid catalogue signature fails closed and preserves the previously verified cache.')
    finally:
        host.close()
    require(sha256(marker) == marker_sha and all(sha256(fixture_root/name) == digest
            for name, digest in installed_before.items()), 'Setup changed existing settings or installed pack bytes.')
    unchanged(original, fixture_root, ('workspace/catalog-sources.json', 'workspace/setup-profile.json'))
    check(report, 'Batch installation preserves existing settings, every preinstalled pack file and all application code.')
    science = native_scientific_chain(fixture_root, evidence)
    check(report, 'After batch installation, an offline native minimap2-to-SAMtools workflow preserves all 202 expected alignment records.')
    return {'configuration': config, 'initial': initial, 'science': science,
            'fixtureRoot': str(fixture_root), 'productionTrustValidated': False}


def full_checks(root, evidence, report, catalogue=None):
    production = catalogue is None
    original = core_hashes(root)
    fixture = evidence/'full-transport-fixture'
    if production:
        host = PrivateHost(root, evidence, 'production-full')
        config = None
    else:
        document = read_json(catalogue)
        require(set(document) == {'schema', 'publishedAt', 'packs'} and len(document['packs']) == 32,
                'Full fixture must supply exactly the reviewed 32 current packs.')
        fields = ('id', 'version', 'size', 'sha256', 'manifestSha256')
        packaged = read_json(root/'workspace/setup-profile.json')['packs']
        require({tuple(row[key] for key in fields) for row in document['packs']} ==
                {tuple(row[key] for key in fields) for row in packaged},
                'Full catalogue fixture differs from the exact packaged selection pins.')
        config = prepare_fixture(root, fixture, document['packs'], {})
        host = FixtureHost(root, evidence, 'test-signed-full', fixture, live=True)
    try:
        host.call('init')
        initial = host.call('setup/status')
        require(initial['configured'], 'Packaged production catalogue trust is unavailable; production Full gate was not run.')
        host.call('setup/refresh')
        state = wait_setup(host, timeout=300)
        require(len(state['rows']) == 32, 'Full setup catalogue does not contain the complete reviewed selection.')
        host.call('setup/start', {'profile': 'full'})
        state = wait_setup(host, timeout=5400)
        require(all(row['installed'] for row in state['rows']), 'Full setup left a selected pack uninstalled.')
        check(report, 'All 32 current packs coexist after Full setup through signed catalogue verification and the native importer.')
        write_json(evidence/'full-final-state.json', state)
    finally:
        host.close()
    unchanged(original, root, () if production else ('workspace/catalog-sources.json', 'workspace/setup-profile.json'))
    science = native_scientific_chain(root, evidence)
    check(report, 'With all 32 packs installed, offline native alignment and SAM-to-BAM analysis preserves all 202 expected records.')
    host = PrivateHost(root, evidence, 'full-offline', offline=True)
    try:
        state = host.call('init')
        listed = host.call('packs/list')
        require(not listed.get('errors'), 'All-pack installation contains catalogue load errors.')
        require(len({row['id'] for row in listed['packs'] if row['installed']}) == 32,
                'Offline pack discovery does not see all 32 installed packs.')
        require('bed' in {item['id'] for item in state['inputTypes']},
                'Installed BEDTools did not contribute BED to Add workflow input.')
        host.call('workspace/mode', {'mode': 'workflow'})
        bed = host.call('model', {'action': 'add_input', 'payload': {'inputType': 'bed'}})
        require(bed['selected'] and bed['sources'], 'Installed BED workflow input could not be added.')
        host.call('workspace/tool', {'toolId': 'bam/reference-index'})
        host.call('setup/status')
        check(report, 'Installed BEDTools contributes a usable BED workflow input through the normal pack-driven input list.')
        check(report, 'All 32 installed packs and setup state reopen with socket operations denied; individual-tool selection remains usable.')
    finally:
        host.close()
    return {'productionTrustValidated': production, 'configuration': config,
            'science': science, 'scope': 'All current real release packs; catalogue/import/coexistence and starter scientific checks, not every pack scientific fixture.'}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--app-root', required=True, type=Path)
    parser.add_argument('--report', required=True, type=Path)
    parser.add_argument('--source-commit', required=True)
    parser.add_argument('--asset-sha256', required=True)
    parser.add_argument('--full-catalogue', type=Path)
    parser.add_argument('--production-full', action='store_true')
    parser.add_argument('--ui-regression-only', action='store_true')
    parser.add_argument('--expect-ui-regression', action='store_true')
    args = parser.parse_args(argv)
    root, path = args.app_root.resolve(), args.report.resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    report = {'schema': 1, 'success': False, 'startedUtc': datetime.now(timezone.utc).isoformat(),
              'platform': platform.platform(), 'python': sys.version, 'sourceCommit': args.source_commit,
              'assetSha256': args.asset_sha256, 'gateSha256': sha256(__file__), 'appRoot': str(root),
              'reportPath': str(path),
              'nativeWindowsExecuted': False, 'productionTrustValidated': False,
              'checks': [], 'skips': [], 'unrun': []}
    write_json(path, report)
    try:
        require(os.name == 'nt', 'Actual native Windows is mandatory; this gate has no passing skip mode.')
        require(Path(sys.executable).resolve() == (root/'runtime/python/python.exe').resolve(),
                'Run with the exact packaged application private Python.')
        require(sum((bool(args.full_catalogue), args.production_full, args.ui_regression_only)) <= 1,
                'Select one setup gate scope.')
        require(not args.expect_ui_regression or args.ui_regression_only,
                'The published negative control is a separate UI-only scope.')
        version = read_json(root/'manifest.json')['version']
        require(version == ('0.10.0' if args.expect_ui_regression else '0.10.1'), 'Wrong candidate application version.')
        report['appVersion'] = version
        before = core_hashes(root)
        report['appFiles'] = before
        if args.ui_regression_only:
            report['uiPolling'] = ui_polling_checks(root, path.parent/'polling', report, args.expect_ui_regression)
        elif args.full_catalogue or args.production_full:
            report['full'] = full_checks(root, path.parent, report, args.full_catalogue)
            report['productionTrustValidated'] = report['full']['productionTrustValidated']
        else:
            # Completed packs can be large even in a short live probe. Keep
            # its disposable installation outside the uploaded evidence tree.
            polling_root = path.parent.parent/(path.parent.name + '-polling-app')
            shutil.copytree(root, polling_root)
            report['uiPolling'] = ui_polling_checks(polling_root, path.parent/'polling', report)
            report['gui'] = gui_checks(root, path.parent, report)
            host = PrivateHost(root, path.parent, 'persisted-starter', offline=True)
            try:
                host.call('init')
                saved = host.call('setup/status')
                require(saved['selection']['profile'] == 'starter' and
                        saved['operation']['status'] == 'completed' and not saved['offered'],
                        'The native Starter action did not persist its completed selection and welcome dismissal.')
                require(all(row['installed'] for row in saved['rows'] if row['starter']),
                        'Completed Starter setup is missing a required installed pack.')
                report['gui']['persistedStarter'] = saved
                check(report, 'The native Starter action persists completed selection and dismissed welcome across an offline private-host restart.')
            finally:
                host.close()
            unchanged(before, root)
            report['fixture'] = fixture_checks(root, path.parent, report)
        if not report['productionTrustValidated']:
            report['unrun'].append('Production signed catalogue refresh and clean-client Full installation are not exercised by test-only trust fixtures.')
        report['nativeWindowsExecuted'] = True
        report['success'] = True
    except Exception as exc:
        report.update(error=str(exc), traceback=traceback.format_exc())
    finally:
        report['passed'] = len(report['checks'])
        report['completedUtc'] = datetime.now(timezone.utc).isoformat()
        write_json(path, report)
    print(json.dumps({'success': report['success'], 'passed': report['passed'], 'report': str(path)}), flush=True)
    return 0 if report['success'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
