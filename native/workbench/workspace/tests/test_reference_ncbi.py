"""Deterministic NCBI API/FTP lookup and transport-boundary tests; no network.

Fixtures use the observed Datasets v2 snake_case schema and FTP MD5 layout
from GCF_000146045.2 on 2026-10-08. Data bytes are synthetic test references.
"""
import gzip
import hashlib
import io
import json
from pathlib import Path
import sys
import threading
import unittest
from unittest.mock import patch
import urllib.request

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import reference_ncbi as rn
from reference_provider import ReferenceCancelled, ReferenceHTTPError, ReferenceProviderError

ACCESSION = 'GCF_000146045.2'
API = rn.API_BASE + ACCESSION + '/dataset_report'
PARENT = rn.FTP_BASE + '000/146/045/'
FOLDER = ACCESSION + '_R64'
ROOT = PARENT + FOLDER + '/'
REPORT = {'reports': [{'accession': ACCESSION, 'current_accession': ACCESSION,
          'source_database': 'SOURCE_DATABASE_REFSEQ',
          'organism': {'tax_id': 559292, 'organism_name': 'Saccharomyces cerevisiae S288C'},
          'assembly_info': {'assembly_status': 'current', 'assembly_name': 'R64'},
          'annotation_info': {'name': 'SGD R64-5-1', 'provider': 'SGD', 'release_date': '2026-07-10'}}],
          'total_count': 1}


class Response(io.BytesIO):
    def __init__(self, data=b'', url='', headers=None, code=200):
        super().__init__(data)
        self.url, self.code = url, code
        self.headers = {'Content-Length': str(len(data))} if headers is None else headers

    def geturl(self):
        return self.url

    def getcode(self):
        return self.code


class FakeTransport:
    def __init__(self):
        self.records, self.calls = {}, []

    def add(self, url, body, method='GET', headers=None):
        self.records[method, url] = (body.encode() if isinstance(body, str) else body, headers)

    def open_url(self, url, method='GET', cancel=None, headers=None):
        rn.cancelled(cancel)
        self.calls.append((method, url, headers))
        entry = self.records.get((method, url))
        if entry is None:
            raise rn.NCBIHTTPError(404, url)
        if isinstance(entry, Exception):
            raise entry
        return Response(entry[0], url, entry[1])


def fixture():
    fake = FakeTransport()
    fake.add(API, json.dumps(REPORT))
    fake.add(PARENT, f'<a href="{FOLDER}/">selected</a><a href="GCF_000146045.1_SacCer_May2010/">old</a>')
    checks = ['d' * 32 + f'  ./{FOLDER}_assembly_structure/Primary_Assembly/FASTA/chrI.fna.gz\n']
    for kind, suffix in rn._SUFFIXES.items():
        filename = FOLDER + suffix
        body = gzip.compress(((b'#gtf-version 2.2\n#!genome-build R64\n'
                              b'#!genome-build-accession NCBI_Assembly:GCF_000146045.2\n'
                              b'#!annotation-source SGD R64-5-1\n'
                              b'chrI\tSGD\tgene\t1\t20\t.\t+\t.\tgene_id "x";\n') if kind == 'annotation'
                              else b'>chrI\nACGTACGTACGTACGTACGT\n'), mtime=0)
        checks.append(hashlib.md5(body).hexdigest() + '  ./' + filename + '\n')
        fake.add(ROOT + filename, body)
        fake.add(ROOT + filename, b'', method='HEAD', headers={'Content-Length': str(len(body))})
    checks.append('a' * 32 + f'  ./{FOLDER}_rna.fna.gz\n')
    fake.add(ROOT + 'md5checksums.txt', ''.join(checks))
    return fake, rn.NCBIRefSeqProvider(fake)


class LookupTests(unittest.TestCase):
    def test_descriptor_and_selector_are_offline_and_honest(self):
        fake, provider = fixture()
        descriptor = provider.descriptor()
        self.assertEqual(descriptor['id'], 'ncbi-refseq')
        self.assertEqual(provider.releases(), ['assembly'])
        self.assertIn('accession', descriptor['search_label'])
        self.assertIn('update annotations', descriptor['notice'])
        self.assertEqual(fake.calls, [])

    def test_exact_accession_search_preserves_real_annotation_provider(self):
        fake, provider = fixture()
        row = provider.species('assembly', ' GCF_000146045.2 ')[0]
        self.assertEqual(row['id'], ACCESSION)
        self.assertEqual(row['release'], ACCESSION)
        self.assertEqual(row['annotation'], REPORT['reports'][0]['annotation_info'])
        self.assertEqual(row['annotation']['provider'], 'SGD')
        self.assertEqual(fake.calls[0][1], API)

    def test_invalid_lookup_never_contacts_network(self):
        for query in ('', 'human', 'GCF_000146045', 'GCA_000146045.2', 'GCF_000146045.0',
                      ACCESSION + '/x', ACCESSION + '?x=1', ['GCF_000146045.2']):
            fake, provider = fixture()
            with self.subTest(query=query), self.assertRaises(ReferenceProviderError):
                provider.species('assembly', query)
            self.assertEqual(fake.calls, [])
        fake, provider = fixture()
        with self.assertRaises(ReferenceProviderError):
            provider.species(116, ACCESSION)
        self.assertEqual(fake.calls, [])

    def test_discovery_three_roles_md5_snapshot_and_no_rna_mislabel(self):
        fake, provider = fixture()
        value = provider.discover('assembly', ACCESSION)
        self.assertEqual(value['release'], ACCESSION)
        self.assertEqual([item['kind'] for item in value['files']], ['genome', 'annotation', 'protein'])
        self.assertEqual(value['annotation']['name'], 'SGD R64-5-1')
        manifest = fake.records['GET', ROOT + 'md5checksums.txt'][0]
        for item in value['files']:
            self.assertEqual(item['checksum']['algorithm'], 'md5')
            self.assertEqual(item['checksum']['value'], hashlib.md5(fake.records['GET', item['url']][0]).hexdigest())
            self.assertEqual(item['checksum_manifest']['sha256'], hashlib.sha256(manifest).hexdigest())
        self.assertEqual(value['source_catalog']['sha256'], hashlib.sha256(fake.records['GET', API][0]).hexdigest())
        self.assertEqual(value['warnings'], [])
        self.assertNotIn('unmasked', value['files'][0]['detail'])

    def test_missing_optional_and_all_missing(self):
        fake, provider = fixture()
        manifest_url = ROOT + 'md5checksums.txt'
        text = fake.records['GET', manifest_url][0].decode()
        fake.add(manifest_url, '\n'.join(line for line in text.splitlines() if '_genomic.gtf.gz' not in line))
        result = provider.discover('assembly', ACCESSION)
        self.assertEqual([f['kind'] for f in result['files']], ['genome', 'protein'])
        self.assertIn('not available', result['warnings'][0])
        fake.add(manifest_url, 'a' * 32 + '  ./other.txt\n')
        with self.assertRaisesRegex(ReferenceProviderError, 'No supported'):
            provider.discover('assembly', ACCESSION)

    def test_no_current_accession_substitution_or_ambiguous_report(self):
        for change in ({'accession': 'GCF_000146045.1'}, {'source_database': 'SOURCE_DATABASE_GENBANK'},
                       {'organism': {'tax_id': True, 'organism_name': 'Yeast'}},
                       {'assembly_info': {'assembly_name': 'R64', 'assembly_status': 'suppressed'}}):
            fake, provider = fixture()
            document = json.loads(json.dumps(REPORT))
            document['reports'][0].update(change)
            fake.add(API, json.dumps(document))
            with self.subTest(change=change), self.assertRaises(ReferenceProviderError):
                provider.discover('assembly', ACCESSION)
            self.assertEqual(len(fake.calls), 1)
        fake, provider = fixture()
        document = json.loads(json.dumps(REPORT))
        document['reports'][0]['current_accession'] = 'GCF_000146045.3'
        fake.add(API, json.dumps(document))
        self.assertEqual(provider.species('assembly', ACCESSION)[0]['id'], ACCESSION)
        document['reports'].append(document['reports'][0])
        fake.add(API, json.dumps(document))
        with self.assertRaises(ReferenceProviderError):
            provider.species('assembly', ACCESSION)

    def test_json_duplicate_keys_and_nonfinite_rejected(self):
        for data in ('{"reports":[],"reports":[]}', '{"total_count":NaN}', '[]', '{', 'null'):
            fake, provider = fixture()
            fake.add(API, data)
            with self.subTest(data=data), self.assertRaises(ReferenceProviderError):
                provider.species('assembly', ACCESSION)

    def test_ambiguous_exact_version_directory_fails_closed(self):
        fake, provider = fixture()
        fake.add(PARENT, f'<a href="{FOLDER}/">one</a><a href="{ACCESSION}_other/">two</a>')
        with self.assertRaisesRegex(ReferenceProviderError, 'unique FTP directory'):
            provider.discover('assembly', ACCESSION)
        fake.add(PARENT, '<a href="GCF_000146045.1_SacCer_May2010/">old</a>')
        with self.assertRaises(ReferenceProviderError):
            provider.discover('assembly', ACCESSION)

    def test_checksums_nested_safe_entries_and_unsafe_duplicate_rejected(self):
        entries, _ = rn._checksums(b'a' * 32 + b'  ./nested/entry.gz\n')
        self.assertIn('nested/entry.gz', entries)
        for name in ('../x', '/abs', 'sub//x', 'sub/./x', 'sub\\x', 'x%20', 'x:', 'x.'):
            with self.subTest(name=name), self.assertRaises(ReferenceProviderError):
                rn._checksums(('a' * 32 + '  ./' + name + '\n').encode())
        with self.assertRaisesRegex(ReferenceProviderError, 'repeats'):
            rn._checksums((('a' * 32 + '  ./x\n') * 2).encode())

    def test_head_unsupported_unknown_size_but_server_failure_propagates(self):
        fake, provider = fixture()
        url = ROOT + FOLDER + '_genomic.fna.gz'
        fake.records['HEAD', url] = rn.NCBIHTTPError(405, url)
        self.assertIsNone(provider.discover('assembly', ACCESSION)['files'][0]['bytes'])
        fake.records['HEAD', url] = rn.NCBIHTTPError(503, url)
        with self.assertRaises(rn.NCBIHTTPError):
            provider.discover('assembly', ACCESSION)

    def test_bounded_and_truncated_metadata(self):
        fake, provider = fixture()
        fake.add(API, b'x', headers={'Content-Length': '2'})
        with self.assertRaisesRegex(ReferenceProviderError, 'incomplete'):
            provider.species('assembly', ACCESSION)
        fake.add(API, b'x' * 20, headers={})
        with self.assertRaisesRegex(ReferenceProviderError, 'size limit'):
            provider.read_metadata(API, max_bytes=10)
        for value in (True, 0, rn.MAX_METADATA_BYTES + 1):
            with self.assertRaises(ReferenceProviderError):
                provider.read_metadata(API, max_bytes=value)

    def test_gtf_headers_check_exact_assembly_and_present_annotation_identity(self):
        _, provider = fixture()
        selection = provider.discover('assembly', ACCESSION)
        item = next(f for f in selection['files'] if f['kind'] == 'annotation')
        prefix = (f'#gtf-version 2.2\n#!genome-build R64\n'
                  f'#!genome-build-accession NCBI_Assembly:{ACCESSION}\n'
                  '#!annotation-source SGD R64-5-1\n').encode()
        provider.validate_download_prefix(item, prefix, selection)
        for changed in (prefix.replace(b'R64-5-1', b'R64-4-1'),
                        prefix.replace(ACCESSION.encode(), b'GCF_000146045.1'),
                        prefix.replace(b'genome-build R64', b'genome-build R63'),
                        prefix + b'#!genome-build R64\n', b'#gtf-version 2.2\n'):
            with self.subTest(prefix=changed), self.assertRaises(ReferenceProviderError):
                provider.validate_download_prefix(item, changed, selection)
        # Actual bacterial GTF files have assembly headers but can omit an
        # annotation-source header. This does not establish an annotation name.
        provider.validate_download_prefix(item, prefix.split(b'#!annotation-source')[0], selection)
        provider.validate_download_prefix({'kind': 'genome'}, b'>NC_000913.3\nACGT\n', selection)

    def test_ncbi_generated_gtf_provider_prefix_and_annotation_date(self):
        _, provider = fixture()
        selection = {'assembly': 'GRCh38.p14', 'assembly_accession': 'GCF_000001405.40',
                     'annotation': {'name': 'GCF_000001405.40-RS_2025_08', 'provider': 'NCBI RefSeq',
                                    'release_date': '2025-08-01'}}
        prefix = (b'#!genome-build GRCh38.p14\n#!genome-build-accession NCBI_Assembly:GCF_000001405.40\n'
                  b'#!annotation-date 08/01/2025\n#!annotation-source NCBI RefSeq GCF_000001405.40-RS_2025_08\n')
        provider.validate_download_prefix({'kind': 'annotation'}, prefix, selection)
        for wrong in (b'08/02/2025', b'13/01/2025', b'invalid'):
            with self.subTest(date=wrong), self.assertRaises(ReferenceProviderError):
                provider.validate_download_prefix({'kind': 'annotation'}, prefix.replace(b'08/01/2025', wrong), selection)

    def test_cancel_prevents_network(self):
        fake, provider = fixture()
        cancel = threading.Event()
        cancel.set()
        with self.assertRaises(ReferenceCancelled):
            provider.discover('assembly', ACCESSION, cancel=cancel)
        self.assertEqual(fake.calls, [])


class TransportTests(unittest.TestCase):
    def test_url_authority_and_accession_path_boundaries(self):
        url = ROOT + FOLDER + '_genomic.fna.gz'
        for valid in (API, PARENT, ROOT, url, ROOT + 'md5checksums.txt'):
            self.assertEqual(rn.validate_url(valid), valid)
        for invalid in (url.replace('https:', 'http:'), url.replace('ftp.ncbi.nlm.nih.gov', 'ftp.ncbi.nih.gov'),
                        url.replace('ftp.ncbi.nlm.nih.gov', 'ftp.ncbi.nlm.nih.gov.evil.test'),
                        url.replace('https://', 'https://user@'), url.replace('.gov/', '.gov:443/'),
                        url + '?x=1', url + '#x', url.replace('/000/146/', '/001/146/'),
                        ROOT + '../x', ROOT + '%2e%2e/x', ROOT + 'arbitrary.fa.gz',
                        ROOT + FOLDER + '_rna.fna.gz', PARENT + 'latest/', API.replace('.2/', '/')):
            with self.subTest(url=invalid), self.assertRaises(ReferenceProviderError):
                rn.validate_url(invalid)

    def test_redirect_crosshost_or_changed_object_closes_response(self):
        original = ROOT + FOLDER + '_genomic.fna.gz'
        handler = rn._NCBIRedirect(original, None)
        for target in (original.replace('https:', 'http:'), original.replace('_genomic.fna.gz', '_protein.faa.gz')):
            response = Response()
            with self.assertRaises(ReferenceProviderError):
                handler.redirect_request(urllib.request.Request(original), response, 302, 'redirect', {}, target)
            self.assertTrue(response.closed)

    def test_safe_resume_headers_only_and_206_is_retained(self):
        url = ROOT + FOLDER + '_genomic.fna.gz'
        response = Response(b'abc', url, {'Content-Length': '3', 'Content-Range': 'bytes 4-6/7'}, 206)
        with patch.object(urllib.request, 'build_opener') as factory:
            factory.return_value.open.return_value = response
            received = rn.RestrictedNCBIHTTPS().open_url(url, headers={'Range': 'bytes=4-', 'If-Range': '"etag"'})
            request = factory.return_value.open.call_args[0][0]
            self.assertEqual(request.get_header('Range'), 'bytes=4-')
            self.assertEqual(request.get_header('If-range'), '"etag"')
            self.assertEqual(received.getcode(), 206)
            received.close()
        for headers in ({'Authorization': 'secret'}, {'If-Range': '"x"'}, {'Range': 'bytes=1-2'},
                        {'Range': 'bytes=-2'}, {'Range': 'bytes=1-', 'If-Range': 'W/"weak"'},
                        {'Range': 'bytes=1-', 'If-Range': 'x\r\nHost:evil'}, {'Range': 1}):
            with self.subTest(headers=headers), self.assertRaises(ReferenceProviderError):
                rn.RestrictedNCBIHTTPS().open_url(url, headers=headers)
        with self.assertRaises(ReferenceProviderError):
            rn.RestrictedNCBIHTTPS().open_url(API, headers={'Range': 'bytes=1-'})

    def test_unrequested_partial_or_encoded_response_is_closed(self):
        url = ROOT + FOLDER + '_genomic.fna.gz'
        for headers, code in (({}, 206), ({'Content-Encoding': 'gzip'}, 200), ({'Content-Length': '-1'}, 200)):
            response = Response(b'', url, headers, code)
            with patch.object(urllib.request, 'build_opener') as factory:
                factory.return_value.open.return_value = response
                with self.assertRaises(ReferenceProviderError):
                    rn.RestrictedNCBIHTTPS().open_url(url)
                self.assertTrue(response.closed)

    def test_http_error_shared_type_supports_resume_416_fallback(self):
        error = rn.NCBIHTTPError(416, ROOT)
        self.assertIsInstance(error, ReferenceHTTPError)
        self.assertEqual(error.status, 416)
        self.assertIn('NCBI', str(error))
        self.assertNotIn('Ensembl', str(error))


if __name__ == '__main__':
    unittest.main()
