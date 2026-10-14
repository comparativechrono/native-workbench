"""Catalogue coverage and rejection tests, including the shipped pack manifests."""
import copy
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import catalog

APP_ROOT=Path(os.environ.get('BW_TEST_APP_ROOT',Path(__file__).resolve().parents[4]/'integration-0.5'/'native-workbench'))


class ShippedCatalog(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog=catalog.load_catalog(APP_ROOT)

    def test_every_declared_workflow_input_and_output_is_exposed(self):
        expected=set()
        for path in (APP_ROOT/'packs').glob('*/pack.ini'):
            pack=catalog.load_pack(path)
            for workflow in pack['workflows'].values():
                key=pack['id']+'/'+workflow['id']
                expected.add(key)
                descriptor=self.catalog['tools'][key]
                input_ids=[x for p in descriptor['ports'] for x in p['manifestInputs']]+[p['id'] for p in descriptor['params']]
                output_ids=[x for o in descriptor['outputs'] for x in o['manifestOutputs']]
                self.assertCountEqual(input_ids,[x['id'] for x in workflow['inputs']],key)
                self.assertCountEqual(output_ids,[x['id'] for x in workflow['outputs']],key)
                self.assertEqual(len(input_ids),len(set(input_ids)),key)
                self.assertEqual(len(output_ids),len(set(output_ids)),key)
        self.assertEqual(len(expected),43)
        self.assertEqual(set(self.catalog['tools']),expected|{'builtin/report'})

    def test_atomic_pairs_and_unpaired_reads_not_mislabelled(self):
        fastp=self.catalog['tools']['fastp/paired']
        self.assertEqual(fastp['packVersion'],'0.4.1')
        self.assertEqual(fastp['ports'][0]['manifestInputs'],['reads1','reads2'])
        outputs={x['id']:x for x in fastp['outputs']}
        self.assertEqual(outputs['trimmed']['type'],'pair')
        self.assertEqual(outputs['trimmed']['manifestOutputs'],['trimmed1','trimmed2'])
        self.assertEqual(outputs['unpaired1']['type'],'reads')
        self.assertEqual(outputs['unpaired2']['type'],'reads')
        self.assertIn('plotly-js',outputs)

    def test_variants_and_genotype_likelihoods_differ(self):
        tools=self.catalog['tools']
        pileup=next(o for o in tools['variants/pileup']['outputs'] if o['id']=='pileup')
        call=tools['variants/call-bcf']['ports'][0]
        self.assertEqual(pileup['type'],'bcf-likelihoods')
        self.assertEqual(call['accepts'],['bcf-likelihoods'])
        freebayes={o['id']:o for o in tools['freebayes/call']['outputs']}
        self.assertEqual(freebayes['variants']['type'],'vcf')
        self.assertEqual(freebayes['pass-variants']['type'],'vcf-pass')
        self.assertNotEqual(freebayes['variants']['state']['selection'],freebayes['pass-variants']['state']['selection'])

    def test_states_are_not_inferred_as_interchangeable(self):
        tools=self.catalog['tools']
        self.assertEqual(tools['bam/merge']['ports'][0]['requiredState'],{'sort':'coordinate'})
        self.assertEqual(tools['bam/merge']['ports'][0]['min'],2)
        self.assertEqual(tools['bam/fixmate']['ports'][0]['requiredState']['sort'],'queryname')
        self.assertEqual(tools['bam/mark-duplicates']['ports'][0]['requiredState']['mateFixed'],True)
        self.assertEqual(tools['reads/statistics']['ports'][0]['requiredState'],{'compression':'none'})
        self.assertEqual(tools['trimming/cutadapt-single']['output']['state']['compression'],'gzip')

    def test_binding_metadata_excluded_from_presets(self):
        params={p['id']:p for p in self.catalog['tools']['bwa/paired-end']['params']}
        for key in ('sample','library','read-group','platform-unit'):
            self.assertFalse(params[key]['preset'])
            self.assertTrue(params[key]['binding'])
        self.assertTrue(params['threads']['preset'])

    def test_serializable_and_pinned(self):
        encoded=json.dumps(self.catalog)
        self.assertNotIn(str(APP_ROOT.resolve()),encoded)
        self.assertEqual(len(json.loads(encoded)['tools']),44)
        for tool in self.catalog['tools'].values():
            self.assertRegex(tool['manifestSha256'],r'^[0-9a-f]{64}$')
            for executable in tool['executables']:
                self.assertRegex(executable['sha256'],r'^[0-9a-f]{64}$')
                self.assertTrue(executable['path'].endswith('.exe'))

    def test_defaults_satisfy_declared_types_except_required_user_entries(self):
        for tool in self.catalog['tools'].values():
            for param in tool['params']:
                if param['default'] or not param['required']:
                    self.assertEqual(catalog.validate_parameter(param,param['default']),param['default'])
        param=next(p for p in self.catalog['tools']['bwa/paired-end']['params'] if p['id']=='threads')
        for bad in ('0','65','2;calc.exe',2.5,'2\n3'):
            with self.assertRaises(catalog.CatalogError): catalog.validate_parameter(param,bad)


class ManifestRejection(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text=(APP_ROOT/'packs'/'bwa-0.4.0'/'pack.ini').read_text()

    def reject(self,text):
        with self.assertRaises((catalog.CatalogError,KeyError)):
            catalog.parse_pack(text)

    def test_path_traversal_and_windows_device_names(self):
        for path in ('../bwa.exe','C:/bwa.exe','bin/../bwa.exe','bin/CON.exe','bin/file. /bwa.exe','/bwa.exe'):
            self.reject(self.text.replace('path=bin/bwa.exe','path='+path,1))

    def test_duplicate_sections_keys_and_control_characters(self):
        self.reject(self.text+'\n[pack]\nformat=2\n')
        self.reject(self.text.replace('format=2','format=2\nformat=2',1))
        self.reject(self.text.replace('name=BWA alignment','name=BWA\valignment'))
        self.reject(self.text.replace('name=BWA alignment','name=BWA\0alignment'))

    def test_unknown_sections_and_arguments(self):
        self.reject(self.text+'\n[surprise]\nkey=value\n')
        self.reject(self.text.replace('arg.0=index','arg.1=index',1))
        self.reject(self.text.replace('arg.0=index','arg.01=index',1))
        self.reject(self.text.replace('arg.0=index','command=cmd.exe',1))

    def test_unknown_input_and_unproduced_output(self):
        self.reject(self.text.replace('{input:reference}','{input:unknown}',1))
        self.reject(self.text.replace('arg.0=index','arg.0={output:aligned}',1))
        self.reject(self.text.replace('produces=aligned','produces=unknown',1))
        self.reject(self.text.replace('arg.3={output:aligned}','arg.3={inputs:reference}',1))

    def test_hash_and_reference_validation(self):
        self.reject(self.text.replace('55d08b399c42a671e60a8dc7d0421fb60aca8899aa54201903fcf1e2ac21fa0a','z'*64))
        self.reject(self.text.replace('different-from=reads1','different-from=sample'))
        self.reject(self.text.replace('max=64','max=0'))

    def test_misnamed_duplicate_installed_versions_are_isolated(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)
            for name in ('bwa-0.4.0','bwa-0.4.1','duplicate'):
                folder=root/'packs'/name
                folder.mkdir(parents=True)
                (folder/'pack.ini').write_text(self.text.replace('version=0.4.0','version=0.4.1',1) if name=='bwa-0.4.1' else self.text)
            discovered=catalog.load_catalog(root)
            self.assertEqual(discovered['tools']['bwa/paired-end']['packVersion'],'0.4.1')
            self.assertEqual(len(discovered['toolVersions']['bwa/paired-end']),2)
            self.assertEqual(len(discovered['errors']),1)
            self.assertEqual(discovered['errors'][0]['folder'],'packs/duplicate')


if __name__=='__main__': unittest.main()
