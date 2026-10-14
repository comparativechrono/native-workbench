"""Public-only catalogue deployment: pins, append-only history and safe races."""
import base64
import copy
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'scripts'), str(ROOT / 'workspace'), str(ROOT / 'tests')]
import deploy_setup_catalogue as deploy
from test_pack_manager import KEY, sign  # Deliberately public test key; never production trust.

SOURCE_COMMIT = '1' * 40


def documents(stamp='2026-10-07T07:00:00Z'):
    payload = json.loads((ROOT / 'publishing/setup-catalogue.UNSIGNED.json').read_text())
    payload['publishedAt'] = stamp
    source = {'schema': 1, 'id': deploy.SOURCE_ID, 'name': deploy.SOURCE_NAME,
              'catalogUrl': deploy.CATALOG_URL, 'publicKey': KEY, 'allowedHosts': deploy.HOSTS}
    report = {'schema': 1, 'packs': len(payload['packs']),
              'sourceKeyFingerprint': deploy.key_fingerprint(KEY), 'publishedAt': stamp, 'uploaded': False}
    return {'catalogue.json': sign(payload), 'source.json': deploy.encoded(source),
            'publication-report.json': deploy.encoded(report)}


class FakeGitHub:
    def __init__(self):
        self.calls, self.blobs, self.trees = [], {}, {}
        self.commits = {SOURCE_COMMIT: {'sha': SOURCE_COMMIT, 'tree': {'sha': '2' * 40}}}
        self.head = None
        self.race_on_second_read = False
        self.race_on_write = False
        self.head_reads = 0

    def object_sha(self, kind, value):
        return deploy.hashlib.sha1(kind.encode() + deploy.encoded(value)).hexdigest()

    def store_blob(self, raw):
        sha = deploy.blob_sha(raw)
        self.blobs[sha] = raw
        return {'mode': '100644', 'type': 'blob', 'sha': sha, 'size': len(raw)}

    def replace_head_tree(self, tree):
        sha = self.object_sha('tree', tree)
        self.trees[sha] = copy.deepcopy(tree)
        commit = {'tree': {'sha': sha}, 'parents': [self.head] if self.head else []}
        head = self.object_sha('commit', commit)
        self.commits[head] = {'sha': head, **commit}
        self.head = head

    def current_tree(self):
        return copy.deepcopy(self.trees[self.commits[self.head]['tree']['sha']])

    def ref(self):
        return {'ref': 'refs/heads/catalogue', 'object': {'type': 'commit', 'sha': self.head}}

    def request(self, method, path, document=None):
        self.calls.append((method, path, copy.deepcopy(document)))
        if method == 'GET' and path == '/git/ref/heads/catalogue':
            self.head_reads += 1
            if self.race_on_second_read and self.head_reads % 2 == 0:
                self.head = 'f' * 40
            if self.head is None:
                raise deploy.APIError(404)
            return self.ref()
        if method == 'GET' and path.startswith('/git/commits/'):
            return self.commits[path.rsplit('/', 1)[1]]
        if method == 'GET' and path.startswith('/git/trees/'):
            sha = path.rsplit('/', 1)[1].split('?')[0]
            return {'sha': sha, 'truncated': False,
                    'tree': [{'path': name, **entry} for name, entry in self.trees[sha].items()]}
        if method == 'GET' and path.startswith('/git/blobs/'):
            sha = path.rsplit('/', 1)[1]
            return {'sha': sha, 'encoding': 'base64',
                    'content': base64.b64encode(self.blobs[sha]).decode('ascii')}
        if method == 'POST' and path == '/git/blobs':
            return self.store_blob(base64.b64decode(document['content']))
        if method == 'POST' and path == '/git/trees':
            tree = copy.deepcopy(self.trees.get(document.get('base_tree'), {}))
            for entry in document['tree']:
                tree[entry['path']] = {key: value for key, value in entry.items() if key != 'path'}
                tree[entry['path']]['size'] = len(self.blobs[entry['sha']])
            sha = self.object_sha('tree', tree)
            self.trees[sha] = tree
            return {'sha': sha}
        if method == 'POST' and path == '/git/commits':
            sha = self.object_sha('commit', document)
            self.commits[sha] = {'sha': sha, 'tree': {'sha': document['tree']}, 'parents': document['parents']}
            return {'sha': sha}
        if path in ('/git/refs', '/git/refs/heads/catalogue'):
            if self.race_on_write:
                raise deploy.APIError(422)
            if method == 'POST':
                if self.head is not None:
                    raise deploy.APIError(422)
                if document['ref'] != 'refs/heads/catalogue':
                    raise AssertionError('Unexpected ref')
            elif method == 'PATCH':
                if document['force'] is not False or self.commits[document['sha']]['parents'] != [self.head]:
                    raise AssertionError('Ref update is not a safe fast-forward')
            else:
                raise AssertionError('Unexpected ref method')
            self.head = document['sha']
            return self.ref()
        raise AssertionError((method, path))

    def anonymous(self, url):
        if not url.startswith(deploy.RAW):
            raise AssertionError('Unexpected public host')
        ref, path = url[len(deploy.RAW):].split('/', 1)
        head = self.head if ref == 'catalogue' else ref
        tree = self.trees[self.commits[head]['tree']['sha']]
        return self.blobs[tree[path]['sha']]


class PublicCatalogueTests(unittest.TestCase):
    def setUp(self):
        self.docs = documents()
        self.fingerprint = deploy.key_fingerprint(KEY)
        self.lock = deploy.read_lock(ROOT / 'publishing/setup-assets.json', ROOT / 'workspace/setup-profile.json')
        self.api = FakeGitHub()
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)

    def publish(self, docs=None, **kwargs):
        return deploy.deploy(docs or self.docs, self.fingerprint, SOURCE_COMMIT, self.lock,
                             'a' * 64, 'b' * 64, self.api, get=kwargs.pop('get', self.api.anonymous),
                             pause=lambda seconds: None, **kwargs)

    def test_real_test_signature_and_all_32_locked_pins_validate_offline(self):
        payload = deploy.validate_documents(self.docs, self.fingerprint, self.lock)
        self.assertEqual(len(payload['packs']), 32)

    def test_payload_tampering_fails_signature(self):
        wrapper = json.loads(self.docs['catalogue.json'])
        payload = json.loads(base64.b64decode(wrapper['payload']))
        payload['publishedAt'] = '2027-01-01T00:00:00Z'
        wrapper['payload'] = base64.b64encode(deploy.encoded(payload)).decode()
        self.docs['catalogue.json'] = deploy.encoded(wrapper)
        with self.assertRaisesRegex(ValueError, 'signature'):
            self.publish()
        self.assertEqual(self.api.calls, [])

    def test_signed_but_changed_pins_urls_or_selection_cannot_publish(self):
        for field, value in [('sha256', '0' * 64), ('manifestSha256', '0' * 64), ('size', 1),
                             ('downloadURL', self.lock['packs'][1]['downloadURL'])]:
            with self.subTest(field=field):
                bad = copy.deepcopy(self.docs)
                payload = json.loads(base64.b64decode(json.loads(bad['catalogue.json'])['payload']))
                payload['packs'][0][field] = value
                bad['catalogue.json'] = sign(payload)
                with self.assertRaisesRegex(ValueError, 'pins|URLs'):
                    self.publish(bad)
        bad = copy.deepcopy(self.docs)
        payload['packs'].pop()
        bad['catalogue.json'] = sign(payload)
        report = json.loads(bad['publication-report.json'])
        report['packs'] -= 1
        bad['publication-report.json'] = deploy.encoded(report)
        with self.assertRaisesRegex(ValueError, 'identities'):
            self.publish(bad)
        self.assertEqual(self.api.calls, [])

    def test_source_identity_hosts_key_and_public_fields_are_strict(self):
        for field, value in [('id', 'another-source'), ('name', 'Another publisher'),
                             ('allowedHosts', deploy.HOSTS + ['other.example']),
                             ('catalogUrl', 'https://github.com/other/catalogue.json'),
                             ('privateKey', 'never copy this')]:
            with self.subTest(field=field):
                bad = copy.deepcopy(self.docs)
                source = json.loads(bad['source.json'])
                source[field] = value
                bad['source.json'] = deploy.encoded(source)
                with self.assertRaises(ValueError):
                    self.publish(bad)
        with self.assertRaisesRegex(ValueError, 'fingerprint'):
            deploy.validate_documents(self.docs, '0' * 64, self.lock)
        self.assertEqual(self.api.calls, [])

    def test_report_counters_timestamp_upload_flag_and_extra_fields_are_checked(self):
        for field, value in [('packs', 0), ('packs', True), ('publishedAt', '2026-01-01T00:00:00Z'),
                             ('uploaded', True), ('sourceKeyFingerprint', '0' * 64), ('private', 'no')]:
            with self.subTest(field=field, value=value):
                bad = copy.deepcopy(self.docs)
                report = json.loads(bad['publication-report.json'])
                report[field] = value
                bad['publication-report.json'] = deploy.encoded(report)
                with self.assertRaisesRegex(ValueError, 'report'):
                    self.publish(bad)

    def test_only_three_bounded_regular_documents_can_be_loaded(self):
        for name, raw in self.docs.items():
            (self.folder / name).write_bytes(raw)
        self.assertEqual(deploy.load_documents(self.folder), self.docs)
        (self.folder / 'unexpected.pem').write_text('not a real key, never read')
        with self.assertRaisesRegex(ValueError, 'only the three'):
            deploy.load_documents(self.folder)
        (self.folder / 'unexpected.pem').unlink()
        (self.folder / 'source.json').unlink()
        (self.folder / 'source.json').symlink_to(self.folder / 'catalogue.json')
        with self.assertRaisesRegex(ValueError, 'regular'):
            deploy.load_documents(self.folder)

    def test_first_publication_has_signed_history_bound_provenance_and_anonymous_checks(self):
        checkpoints = []
        result = self.publish(checkpoint=lambda value: checkpoints.append(copy.deepcopy(value)))
        self.assertTrue(result['published'])
        self.assertTrue(result['anonymousDownloadsVerified'])
        self.assertIsNone(result['previousCatalogueCommit'])
        self.assertEqual(result['sourceCommit'], SOURCE_COMMIT)
        self.assertEqual(len(result['verifiedPublicUrls']), 7)
        self.assertFalse(checkpoints[0]['anonymousDownloadsVerified'])
        self.assertTrue(checkpoints[-1]['anonymousDownloadsVerified'])
        tree = self.api.current_tree()
        prefix = 'history/20261007T070000Z/'
        self.assertEqual(set(tree), set(deploy.DOCUMENTS) | {prefix + name for name in (*deploy.DOCUMENTS, deploy.PUBLIC_RECEIPT)})
        raw = self.api.blobs[tree[prefix + deploy.PUBLIC_RECEIPT]['sha']]
        receipt = json.loads(raw)
        self.assertEqual(receipt['documents'], {name: deploy.digest(data) for name, data in self.docs.items()})
        self.assertNotIn('catalogueCommit', receipt)  # No circular commit identity.
        self.assertEqual(self.api.commits[self.api.head]['parents'], [])

    def test_update_retains_exact_signed_history_and_unrelated_files(self):
        first = self.publish()
        tree = self.api.current_tree()
        tree['README.md'] = self.api.store_blob(b'Leave existing unrelated files untouched.\n')
        self.api.replace_head_tree(tree)
        previous = self.api.head
        result = self.publish(documents('2026-10-07T08:00:00Z'))
        updated = self.api.current_tree()
        self.assertEqual(result['previousCatalogueCommit'], previous)
        self.assertEqual(self.api.commits[self.api.head]['parents'], [previous])
        for path, entry in tree.items():
            if path not in deploy.DOCUMENTS:
                self.assertEqual(updated[path], entry)
        self.assertNotEqual(first['catalogueCommit'], result['catalogueCommit'])
        self.assertEqual(self.api.calls[-1][2]['force'], False)

    def test_stale_or_duplicate_timestamp_never_updates_ref_or_history(self):
        self.publish()
        original_head, original_tree = self.api.head, self.api.current_tree()
        for stamp in ('2026-10-07T07:00:00Z', '2026-10-07T06:59:59Z'):
            with self.subTest(stamp=stamp), self.assertRaisesRegex(ValueError, 'strictly increase'):
                self.publish(documents(stamp))
            self.assertEqual(self.api.head, original_head)
            self.assertEqual(self.api.current_tree(), original_tree)

    def test_malformed_existing_signature_history_or_source_is_rejected(self):
        self.publish()
        original_tree = self.api.current_tree()
        mutations = []
        missing_history = copy.deepcopy(original_tree)
        del missing_history['history/20261007T070000Z/source.json']
        mutations.append(missing_history)
        changed_source = copy.deepcopy(original_tree)
        source = json.loads(self.docs['source.json'])
        source['allowedHosts'].append('unexpected.example')
        changed_source['source.json'] = self.api.store_blob(deploy.encoded(source))
        mutations.append(changed_source)
        tampered = copy.deepcopy(original_tree)
        tampered['history/20261007T070000Z/catalogue.json'] = self.api.store_blob(b'{}')
        mutations.append(tampered)
        unexpected_history = copy.deepcopy(original_tree)
        unexpected_history['history/20261007T070000Z/private.pem'] = self.api.store_blob(b'not a key')
        mutations.append(unexpected_history)
        missing_current = copy.deepcopy(original_tree)
        del missing_current['source.json']
        mutations.append(missing_current)
        for index, tree in enumerate(mutations):
            with self.subTest(mutation=index):
                self.api.replace_head_tree(tree)
                unchanged = self.api.head
                with self.assertRaises(ValueError):
                    self.publish(documents('2026-10-07T08:00:00Z'))
                self.assertEqual(self.api.head, unchanged)

    def test_existing_key_rotation_is_refused(self):
        self.publish()
        tree = self.api.current_tree()
        source = json.loads(self.docs['source.json'])
        source['publicKey']['n'] = 'f' * 512
        tree['source.json'] = self.api.store_blob(deploy.encoded(source))
        self.api.replace_head_tree(tree)
        with self.assertRaisesRegex(ValueError, 'fingerprint'):
            self.publish(documents('2026-10-07T08:00:00Z'))

    def test_second_read_race_prevents_ref_write(self):
        self.api.race_on_second_read = True
        with self.assertRaisesRegex(ValueError, 'changed during publication'):
            self.publish()
        self.assertFalse(any(method in ('POST', 'PATCH') and '/git/refs' in path
                             for method, path, _ in self.api.calls))

    def test_concurrent_ref_creation_and_non_fast_forward_fail_closed(self):
        for update in (False, True):
            with self.subTest(update=update):
                self.api = FakeGitHub()
                if update:
                    self.publish()
                original = self.api.head
                self.api.race_on_write = True
                with self.assertRaises(deploy.APIError):
                    self.publish(documents('2026-10-07T08:00:00Z'))
                self.assertEqual(self.api.head, original)
                if update:
                    self.assertFalse(self.api.calls[-1][2]['force'])

    def test_uncertain_ref_write_preserves_exact_commit_for_recovery(self):
        checkpoints = []
        self.api.race_on_write = True
        with self.assertRaises(deploy.APIError):
            self.publish(checkpoint=lambda value: checkpoints.append(copy.deepcopy(value)))
        self.assertEqual(len(checkpoints), 1)
        self.assertIsNone(checkpoints[0]['published'])
        self.assertTrue(checkpoints[0]['publicationAttempted'])
        self.assertIn(checkpoints[0]['catalogueCommit'], self.api.commits)

    def test_changed_existing_pack_bytes_refused_even_if_new_lock_requests_them(self):
        self.publish()
        updated = documents('2026-10-07T08:00:00Z')
        payload = json.loads(base64.b64decode(json.loads(updated['catalogue.json'])['payload']))
        payload['packs'][0]['sha256'] = '0' * 64
        self.lock['packs'][0]['sha256'] = '0' * 64
        updated['catalogue.json'] = sign(payload)
        with self.assertRaisesRegex(ValueError, 'published pack version'):
            self.publish(updated)

    def test_removed_pack_version_cannot_be_reintroduced_with_changed_archive(self):
        self.publish()
        removed = documents('2026-10-07T08:00:00Z')
        payload = json.loads(base64.b64decode(json.loads(removed['catalogue.json'])['payload']))
        payload['packs'] = [row for row in payload['packs'] if row['id'] != 'align']
        removed['catalogue.json'] = sign(payload)
        report = json.loads(removed['publication-report.json'])
        report['packs'] = len(payload['packs'])
        removed['publication-report.json'] = deploy.encoded(report)
        original_lock = copy.deepcopy(self.lock)
        self.lock['packs'] = [row for row in self.lock['packs'] if row['id'] != 'align']
        self.publish(removed)
        original_head, original_tree = self.api.head, self.api.current_tree()
        restored = documents('2026-10-07T09:00:00Z')
        payload = json.loads(base64.b64decode(json.loads(restored['catalogue.json'])['payload']))
        next(row for row in payload['packs'] if row['id'] == 'align')['sha256'] = '0' * 64
        restored['catalogue.json'] = sign(payload)
        self.lock = original_lock
        next(row for row in self.lock['packs'] if row['id'] == 'align')['sha256'] = '0' * 64
        first_call = len(self.api.calls)
        with self.assertRaisesRegex(ValueError, 'published pack version'):
            self.publish(restored)
        self.assertEqual(self.api.head, original_head)
        self.assertEqual(self.api.current_tree(), original_tree)
        self.assertTrue(all(method == 'GET' for method, _, _ in self.api.calls[first_call:]))

    def test_conflicting_pack_identities_in_validly_signed_history_are_rejected(self):
        self.publish()
        self.publish(documents('2026-10-07T08:00:00Z'))
        tree = self.api.current_tree()
        prefix = 'history/20261007T070000Z/'
        old_documents = {name: self.api.blobs[tree[prefix + name]['sha']] for name in deploy.DOCUMENTS}
        payload = json.loads(base64.b64decode(json.loads(old_documents['catalogue.json'])['payload']))
        payload['packs'][0]['sha256'] = '0' * 64
        old_documents['catalogue.json'] = sign(payload)
        receipt = json.loads(self.api.blobs[tree[prefix + deploy.PUBLIC_RECEIPT]['sha']])
        receipt['documents'] = {name: deploy.digest(raw) for name, raw in old_documents.items()}
        for name, raw in {**old_documents, deploy.PUBLIC_RECEIPT: deploy.encoded(receipt)}.items():
            tree[prefix + name] = self.api.store_blob(raw)
        self.api.replace_head_tree(tree)
        original_head = self.api.head
        first_call = len(self.api.calls)
        with self.assertRaisesRegex(ValueError, 'inconsistent archive identities'):
            self.publish(documents('2026-10-07T09:00:00Z'))
        self.assertEqual(self.api.head, original_head)
        self.assertTrue(all(method == 'GET' for method, _, _ in self.api.calls[first_call:]))

    def test_cdn_retries_are_bounded_and_receipt_retains_committed_failure(self):
        attempts, checkpoints = [], []
        def unavailable(url):
            attempts.append(url)
            return b'stale CDN bytes'
        with self.assertRaisesRegex(ValueError, 'Publication committed'):
            self.publish(get=unavailable, checkpoint=lambda value: checkpoints.append(copy.deepcopy(value)))
        self.assertEqual(len(attempts), 7 * 7)
        self.assertTrue(checkpoints[-1]['published'])
        self.assertFalse(checkpoints[-1]['anonymousDownloadsVerified'])
        self.assertEqual(checkpoints[-1]['catalogueCommit'], self.api.head)

    def test_cdn_eventually_matching_bytes_passes_with_fresh_downloads(self):
        calls = []
        def eventual(url):
            calls.append(url)
            return b'old' if len(calls) <= 7 else self.api.anonymous(url)
        result = self.publish(get=eventual)
        self.assertEqual(result['anonymousVerificationAttempts'], 2)
        self.assertEqual(len(calls), 14)

    def test_verify_only_needs_no_token_and_makes_no_network_request(self):
        for name, raw in self.docs.items():
            (self.folder / name).write_bytes(raw)
        head = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=ROOT, check=True,
                              stdout=subprocess.PIPE).stdout.decode().strip()
        with patch.dict(deploy.os.environ, {}, clear=True), patch.object(deploy, 'GitHub') as github, \
                patch.object(deploy, 'anonymous_get') as anonymous, patch('sys.stdout', new_callable=io.StringIO) as output:
            self.assertEqual(deploy.main(['--documents', str(self.folder), '--expected-fingerprint', self.fingerprint,
                                          '--source-commit', head, '--verify-only']), 0)
        github.assert_not_called()
        anonymous.assert_not_called()
        self.assertFalse(json.loads(output.getvalue())['networkAccessed'])

    def test_source_commit_must_match_checkout(self):
        with self.assertRaisesRegex(ValueError, 'checked-out commit'):
            deploy.source_inputs('0' * 40)


class TransportTests(unittest.TestCase):
    def test_authenticated_redirects_fail_without_new_request(self):
        handler = deploy.NoRedirects()
        with self.assertRaises(deploy.APIError):
            handler.redirect_request(None, None, 302, 'redirect', {}, 'https://attacker.example/')

    def test_api_errors_never_disclose_response_body_or_token(self):
        token = 'sensitive-token-do-not-print'
        api = deploy.GitHub(token)
        error = deploy.urllib.error.HTTPError(deploy.API + '/git/refs', 403, 'sensitive-response', {}, io.BytesIO(b'private response'))
        with patch.object(api._opener, 'open', side_effect=error):
            with self.assertRaises(deploy.APIError) as caught:
                api.request('POST', '/git/refs', {})
        self.assertEqual(str(caught.exception), 'GitHub API request failed (HTTP 403)')
        with self.assertRaisesRegex(ValueError, 'Unexpected GitHub API'):
            api.request('GET', '/actions/secrets')
        with self.assertRaisesRegex(ValueError, 'Unexpected GitHub API'):
            api.request('GET', '/git/../actions/secrets')

    def test_malformed_api_json_diagnostics_never_quote_response_body(self):
        class Response:
            def __enter__(self):
                return self
            def __exit__(self, *args):
                pass
            def geturl(self):
                return deploy.API + '/git/ref/heads/catalogue'
            def read(self, limit):
                return b'{"sensitive response field":1,"sensitive response field":2}'
        api = deploy.GitHub('test-token-never-log')
        with patch.object(api._opener, 'open', return_value=Response()):
            with self.assertRaises(deploy.APIError) as caught:
                api.request('GET', '/git/ref/heads/catalogue')
        self.assertEqual(str(caught.exception), 'GitHub API request failed')

    def test_anonymous_verification_only_accepts_fixed_public_document_urls(self):
        with self.assertRaisesRegex(ValueError, 'Unexpected anonymous'):
            deploy.anonymous_get('https://attacker.example/catalogue.json')
        with self.assertRaisesRegex(ValueError, 'Unexpected anonymous'):
            deploy.anonymous_get(deploy.RAW + 'catalogue/secrets.json')


if __name__ == '__main__':
    unittest.main()
