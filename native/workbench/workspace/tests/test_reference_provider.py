"""Deterministic reference discovery and network-boundary contracts; no network."""
import io
from pathlib import Path
import sys
import threading
import unittest
from unittest.mock import patch
import urllib.request

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import reference_provider as rp


HEADER = '#name\tspecies\tdivision\ttaxonomy_id\tassembly\tassembly_accession\tgenebuild\n'
YEAST = 'Saccharomyces cerevisiae\tsaccharomyces_cerevisiae\tEnsemblVertebrates\t559292\tR64-1-1\tGCA_000146045.2\t2018-08-SGD\n'
HUMAN = 'Human\thomo_sapiens\tEnsemblVertebrates\t9606\tGRCh38.p14\tGCA_000001405.29\t2025-11\n'
CATALOG_URL = rp.BASE_URL + 'release-116/species_EnsemblVertebrates.txt'


class Response(io.BytesIO):
    def __init__(self, data=b'', url='', headers=None, code=200):
        super().__init__(data)
        self.url = url
        self.headers = {'Content-Length': str(len(data))} if headers is None else headers
        self.code = code

    def geturl(self):
        return self.url

    def getcode(self):
        return self.code


class FakeTransport:
    def __init__(self):
        self.records = {}
        self.calls = []

    def add(self, url, body, method='GET', headers=None):
        if isinstance(body, str):
            body = body.encode()
        self.records[method, url] = (body, headers)

    def open_url(self, url, method='GET', cancel=None):
        rp.cancelled(cancel)
        self.calls.append((method, url))
        entry = self.records.get((method, url))
        if entry is None:
            raise rp.ReferenceHTTPError(404, url)
        if isinstance(entry, Exception):
            raise entry
        return Response(entry[0], url, entry[1])


def fixture(human=False):
    transport = FakeTransport()
    transport.add(CATALOG_URL, HEADER + (HUMAN if human else YEAST))
    species = 'homo_sapiens' if human else 'saccharomyces_cerevisiae'
    prefix = 'Homo_sapiens.GRCh38' if human else 'Saccharomyces_cerevisiae.R64-1-1'
    base = rp.BASE_URL + 'release-116/'
    filenames = {
        'dna': prefix + '.dna.toplevel.fa.gz',
        'gtf': prefix + ('.116.gtf.gz' if human else '.63.gtf.gz'),
        'cdna': prefix + '.cdna.all.fa.gz',
        'ncrna': prefix + '.ncrna.fa.gz',
        'pep': prefix + '.pep.all.fa.gz',
    }
    folders = {}
    for directory, filename in filenames.items():
        folder = base + (f'gtf/{species}/' if directory == 'gtf' else f'fasta/{species}/{directory}/')
        folders[directory] = folder
        transport.add(folder + 'CHECKSUMS', f'12345 2 {filename}\n')
        transport.add(folder + filename, b'', method='HEAD', headers={'Content-Length': '1234'})
    return transport, folders, filenames, species


class ProviderTests(unittest.TestCase):
    def test_descriptor_does_not_connect(self):
        fake = FakeTransport()
        desc = rp.EnsemblArchiveProvider(fake).descriptor()
        self.assertEqual(desc['default_release'], 116)
        self.assertIn('replacement', desc['notice'])
        self.assertEqual(fake.calls, [])

    def test_releases_are_explicit_supported_unique_and_sorted(self):
        fake = FakeTransport()
        fake.add(rp.BASE_URL, '<a href="current/">current</a><a href="release-99/">old</a>'
                 '<a href="release-100/">100</a><a href="release-116/">116</a>'
                 '<a href="release-116/">duplicate</a><a href="release-117/">new</a>'
                 '<a href="https://evil.test/release-115/">other</a>')
        self.assertEqual(rp.EnsemblArchiveProvider(fake).releases(), [116, 100])

    def test_species_search_preserves_release_accession_and_patch_metadata(self):
        fake = FakeTransport()
        fake.add(CATALOG_URL, HEADER + YEAST + HUMAN)
        provider = rp.EnsemblArchiveProvider(fake)
        self.assertEqual([x['id'] for x in provider.species(116, 'GCA_000146045.2')], ['saccharomyces_cerevisiae'])
        human = provider.search(116, 'human GRCh38')[0]
        self.assertEqual((human['assembly'], human['taxon_id'], human['release']), ('GRCh38.p14', 9606, 116))
        self.assertEqual([x['name'] for x in provider.species(116)], ['Human', 'Saccharomyces cerevisiae'])

    def test_actual_yeast_annotation_number_and_all_roles(self):
        fake, folders, names, species = fixture()
        result = rp.EnsemblArchiveProvider(fake).discover(116, species)
        self.assertEqual([x['id'] for x in result['files']], ['genome', 'annotation', 'cdna', 'ncrna', 'protein'])
        annotation = result['files'][1]
        self.assertEqual(annotation['filename'], names['gtf'])
        self.assertEqual(annotation['annotation_file_release'], 63)
        self.assertEqual(result['release'], 116)
        self.assertEqual(result['assembly_accession'], 'GCA_000146045.2')
        self.assertEqual(result['files'][0]['sequence_scope'], 'toplevel')
        self.assertEqual(annotation['checksum_manifest']['url'], folders['gtf'] + 'CHECKSUMS')
        self.assertEqual(annotation['bytes'], 1234)
        self.assertEqual(annotation['size'], 1234)
        self.assertEqual(annotation['checksum']['algorithm'], 'bsd-sum')
        self.assertIn('excluding ncRNA', result['files'][2]['label'])

    def test_primary_assembly_preferred_and_masked_not_selected(self):
        fake, folders, names, species = fixture(human=True)
        primary = names['dna'].replace('toplevel', 'primary_assembly')
        fake.add(folders['dna'] + 'CHECKSUMS', f'1 2 {names["dna"]}\n2 2 {primary}\n3 2 {primary.replace(".dna.", ".dna_sm.")}\n')
        fake.add(folders['dna'] + primary, b'', method='HEAD', headers={'Content-Length': '1234'})
        result = rp.EnsemblArchiveProvider(fake).discover(116, species)
        genome = result['files'][0]
        self.assertEqual(genome['filename'], primary)
        self.assertEqual(genome['sequence_scope'], 'primary_assembly')
        self.assertEqual(result['assembly'], 'GRCh38.p14')
        self.assertEqual(genome['assembly'], 'GRCh38')

    def test_missing_optional_resource_is_explicit(self):
        fake, folders, _, species = fixture()
        del fake.records['GET', folders['ncrna'] + 'CHECKSUMS']
        result = rp.EnsemblArchiveProvider(fake).discover(116, species)
        self.assertNotIn('ncrna', [x['id'] for x in result['files']])
        self.assertEqual(len(result['warnings']), 1)

    def test_network_failure_is_not_misreported_as_missing_resource(self):
        fake, folders, _, species = fixture()
        fake.records['GET', folders['ncrna'] + 'CHECKSUMS'] = rp.ReferenceHTTPError(503, folders['ncrna'])
        with self.assertRaises(rp.ReferenceHTTPError):
            rp.EnsemblArchiveProvider(fake).discover(116, species)

    def test_head_unsupported_allows_unknown_size_but_not_contradiction(self):
        fake, folders, names, species = fixture()
        fake.records['HEAD', folders['dna'] + names['dna']] = rp.ReferenceHTTPError(405, folders['dna'])
        result = rp.EnsemblArchiveProvider(fake).discover(116, species)
        self.assertIsNone(result['files'][0]['bytes'])
        fake.add(folders['dna'] + names['dna'], b'', method='HEAD', headers={'Content-Length': '9000'})
        with self.assertRaisesRegex(rp.ReferenceProviderError, 'disagrees'):
            rp.EnsemblArchiveProvider(fake).discover(116, species)

    def test_wrong_assembly_and_ambiguous_gtf_fail(self):
        fake, folders, names, species = fixture()
        fake.add(folders['gtf'] + 'CHECKSUMS', f'1 2 {names["gtf"].replace("R64-1-1", "R64-2-1")}\n')
        with self.assertRaisesRegex(rp.ReferenceProviderError, 'assembly'):
            rp.EnsemblArchiveProvider(fake).discover(116, species)
        fake.add(folders['gtf'] + 'CHECKSUMS', f'1 2 {names["gtf"]}\n1 2 {names["gtf"].replace(".63.", ".116.")}\n')
        with self.assertRaisesRegex(rp.ReferenceProviderError, 'ambiguous'):
            rp.EnsemblArchiveProvider(fake).discover(116, species)

    def test_catalogue_rejects_duplicate_rows_and_hostile_species(self):
        fake = FakeTransport()
        fake.add(CATALOG_URL, HEADER + YEAST + YEAST)
        with self.assertRaisesRegex(rp.ReferenceProviderError, 'duplicate'):
            rp.EnsemblArchiveProvider(fake).species(116)
        for release in (True, '116', 99, 117):
            with self.subTest(release=release), self.assertRaises(rp.ReferenceProviderError):
                rp.EnsemblArchiveProvider(fake).species(release)
        with self.assertRaises(rp.ReferenceProviderError):
            rp.EnsemblArchiveProvider(fake).discover(116, '../homo_sapiens')

    def test_legacy_missing_accession_is_preserved_and_explained(self):
        fake, _, _, species = fixture()
        fake.add(CATALOG_URL, HEADER + YEAST.replace('GCA_000146045.2', ''))
        result = rp.EnsemblArchiveProvider(fake).discover(116, species)
        self.assertEqual(result['assembly_accession'], '')
        self.assertIn('does not supply an assembly accession', result['warnings'][0])

    def test_observed_legacy_assembly_filename_spellings(self):
        cases = [('C.savignyi', 'ciona_savignyi', '51511', 'CSAV 2.0', 'CSAV2.0'),
                 ('Tetraodon', 'tetraodon_nigroviridis', '99883', 'TETRAODON 8.0', 'TETRAODON8')]
        for name, species, taxon, assembly, spelling in cases:
            with self.subTest(assembly=assembly):
                fake = FakeTransport()
                fake.add(CATALOG_URL, HEADER + f'{name}\t{species}\tEnsemblVertebrates\t{taxon}\t{assembly}\t\t2006-04-Ensembl\n')
                folder = rp.BASE_URL + f'release-116/fasta/{species}/dna/'
                filename = species[0].upper() + species[1:] + f'.{spelling}.dna.toplevel.fa.gz'
                fake.add(folder + 'CHECKSUMS', f'123 2 {filename}\n')
                fake.add(folder + filename, b'', method='HEAD', headers={})
                result = rp.EnsemblArchiveProvider(fake).discover(116, species)
                self.assertEqual(result['assembly'], assembly)
                self.assertEqual(result['files'][0]['assembly'], spelling)

    def test_manifest_rejects_traversal_duplicates_and_non_bsd_records(self):
        for text in ('1 1 ../bad.gz', '1 1 good.gz\n2 1 good.gz', '65536 1 bad.gz',
                     '9e107d9d372bb6826bd81d3542a419d6 good.gz', '1 1 C:\\bad.gz', ''):
            with self.subTest(text=text), self.assertRaises(rp.ReferenceProviderError):
                rp._checksums(text.encode())

    def test_url_allowlist_rejects_current_traversal_encoded_and_other_services(self):
        suffix = 'release-116/fasta/homo_sapiens/dna/Homo_sapiens.GRCh38.dna.primary_assembly.fa.gz'
        self.assertEqual(rp.validate_url(rp.BASE_URL + suffix), suffix)
        self.assertEqual(rp.validate_url('https://ftp.ebi.ac.uk/pub/ensembl/' + suffix), suffix)
        for url in ('http://ftp.ensembl.org/pub/', 'https://evil.test/pub/',
                    'https://ftp.ensembl.org:443/pub/', 'https://user@ftp.ensembl.org/pub/',
                    rp.BASE_URL + 'current_fasta/', rp.BASE_URL + 'release-116/current_fasta/',
                    rp.BASE_URL + 'release-116/../secret', rp.BASE_URL + 'release-116/%2e%2e/secret',
                    rp.BASE_URL + 'release-116/file?x=1', rp.BASE_URL + 'release-116/file#f',
                    'https://ftp.ebi.ac.uk/pub/other/release-116/',
                    rp.BASE_URL + 'release-116/a\\b', rp.BASE_URL + 'release-117/'):
            with self.subTest(url=url), self.assertRaises(rp.ReferenceProviderError):
                rp.validate_url(url)

    def test_redirect_preserves_exact_archive_object(self):
        old = rp.BASE_URL + 'release-116/fasta/file.gz'
        request = urllib.request.Request(old)
        handler = rp._ArchiveRedirect(old, None)
        response = io.BytesIO()
        new = handler.redirect_request(request, response, 302, '', {}, 'https://ftp.ebi.ac.uk/pub/ensembl/release-116/fasta/file.gz')
        self.assertEqual(new.full_url, 'https://ftp.ebi.ac.uk/pub/ensembl/release-116/fasta/file.gz')
        for target in (rp.BASE_URL + 'release-115/fasta/file.gz', rp.BASE_URL + 'release-116/fasta/other.gz', 'http://ftp.ensembl.org/pub/'):
            response = io.BytesIO()
            with self.subTest(target=target), self.assertRaises(rp.ReferenceProviderError):
                handler.redirect_request(request, response, 302, '', {}, target)
            self.assertTrue(response.closed)

    def test_metadata_bounds_truncation_and_cancellation(self):
        fake = FakeTransport()
        fake.add(CATALOG_URL, b'abcdef', headers={})
        provider = rp.EnsemblArchiveProvider(fake)
        with self.assertRaisesRegex(rp.ReferenceProviderError, 'size limit'):
            provider.read_metadata(CATALOG_URL, max_bytes=5)
        fake.add(CATALOG_URL, b'abc', headers={'Content-Length': '4'})
        with self.assertRaisesRegex(rp.ReferenceProviderError, 'incomplete'):
            provider.read_metadata(CATALOG_URL)
        cancel = threading.Event()
        cancel.set()
        with self.assertRaises(rp.ReferenceCancelled):
            provider.species(116, cancel=cancel)
        with self.assertRaises(rp.ReferenceCancelled):
            provider.species(116, cancel=lambda: True)

    def test_transport_checks_status_encoding_size_and_final_location(self):
        url = rp.BASE_URL + 'release-116/README'
        for response in (Response(b'x', url, code=206),
                         Response(b'x', url, {'Content-Encoding': 'gzip'}),
                         Response(b'x', url, {'Content-Length': '-1'}),
                         Response(b'x', 'https://evil.test/')):
            with self.subTest(response=response), patch('urllib.request.build_opener') as factory:
                factory.return_value.open.return_value = response
                with self.assertRaises(rp.ReferenceProviderError):
                    rp.RestrictedEnsemblHTTPS().open_url(url)
                self.assertTrue(response.closed)

    def test_resume_transport_preserves_bounded_range_headers(self):
        url = rp.BASE_URL + 'release-116/fasta/file.gz'
        response = Response(b'abc', url, {'Content-Length': '3', 'Content-Range': 'bytes 10-12/13', 'ETag': '"one"'}, code=206)
        with patch('urllib.request.build_opener') as factory:
            factory.return_value.open.return_value = response
            with rp.RestrictedEnsemblHTTPS().open_url(url, headers={'Range': 'bytes=10-', 'If-Range': '"one"'}) as got:
                self.assertEqual(got.getcode(), 206)
            request = factory.return_value.open.call_args.args[0]
            self.assertEqual(request.get_header('Range'), 'bytes=10-')
            self.assertEqual(request.get_header('If-range'), '"one"')
        for headers in ({'Authorization': 'secret'}, {'Range': 'bytes=1-'},
                        {'Range': 'bytes=1-2', 'If-Range': '"one"'},
                        {'Range': 'bytes=1-', 'If-Range': 'W/"weak"'},
                        {'Range': 'bytes=1-', 'If-Range': '"bad\r\nheader"'}):
            with self.subTest(headers=headers), patch('urllib.request.build_opener') as factory:
                with self.assertRaises(rp.ReferenceProviderError):
                    rp.RestrictedEnsemblHTTPS().open_url(url, headers=headers)
                factory.assert_not_called()


if __name__ == '__main__':
    unittest.main()
