"""Mutect2 DAG integration using pinned Linux reference execution, not Windows.

Scientific allele/filter truth is asserted separately by test_mutect2_pack.py.
These checks exercise shared inputs, named results, report joins and the ordinary
frozen engine so a standalone caller pack also behaves correctly in pipelines.
"""
import gzip
import os
from pathlib import Path
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'workspace'))
from catalog import load_catalog
from engine import Engine, pin_for
from test_mutect2_pack import LinuxReferenceBackend

APP=Path(os.environ.get('NW_APP_ROOT',ROOT.parents[1]/'integration-0.5.4/native-workbench')).resolve()
PACK=APP/'packs/mutect2-0.5.4'


def read_text(path):
    path=Path(path)
    with path.open('rb') as stream:
        compressed=stream.read(2)==b'\x1f\x8b'
    with (gzip.open(path,'rt') if compressed else path.open()) as stream:
        return stream.read()


class Mutect2PipelineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog=load_catalog(APP)

    def setUp(self):
        self.temporary=tempfile.TemporaryDirectory(prefix='mutect2 graph ')
        self.folder=Path(self.temporary.name)
        self.backend=LinuxReferenceBackend()
        self.engine=Engine(APP,self.catalog,self.backend)

    def tearDown(self):
        self.temporary.cleanup()

    def graph(self):
        return {'schema':1,'name':'Matched somatic calling and distinct filtered reports',
                'nodes':[{'id':'step-1','tool':'bam/sort','label':'Sort tumor alignments',
                          'inputs':{'alignment':['input-1']},'params':{}},
                         {'id':'step-2','tool':'bam/sort','label':'Sort matched normal alignments',
                          'inputs':{'alignment':['input-2']},'params':{}},
                         {'id':'step-3','tool':'mutect2/tumor-normal','label':'Matched tumor and normal',
                          'inputs':{'tumor':['step-1::sorted'],'normal':['step-2::sorted'],'reference':['input-3'],'targets':['input-4']},
                          'params':{'tumor-sample':'TUMOR','normal-sample':'NORMAL','memory':1024}},
                         {'id':'step-4','tool':'variants/statistics','label':'All filtered calls',
                          'inputs':{'variants':['step-3::variants']},'params':{}},
                         {'id':'step-5','tool':'variants/statistics','label':'PASS calls only',
                          'inputs':{'variants':['step-3::pass-variants']},'params':{}},
                         {'id':'step-6','tool':'builtin/report','label':'Somatic calling comparison',
                          'inputs':{'metrics':['step-4::statistics','step-5::statistics']},'params':{'title':'All filtered and PASS calls'}}],
                'sources':[{'id':'input-1','type':'bam','label':'Tumor specimen','files':{'alignment':str(PACK/'fixtures/tumor.bam')}},
                           {'id':'input-2','type':'bam','label':'Matched normal specimen','files':{'alignment':str(PACK/'fixtures/normal.bam')}},
                           {'id':'input-3','type':'reference','label':'Shared sequence reference','files':{'reference':str(PACK/'fixtures/reference.fa')}},
                           {'id':'input-4','type':'bed','label':'Assayed targets','files':{'targets':str(PACK/'fixtures/targets.bed')}}],
                'nextNode':7,'nextSource':5}

    def test_real_alignment_branches_converge_then_pass_vcf_fans_out_to_report(self):
        graph=self.graph()
        self.assertEqual(self.engine.rank_groups(graph),[{'rank':1,'nodes':['step-1','step-2']},{'rank':2,'nodes':['step-3']},
                                                       {'rank':3,'nodes':['step-4','step-5']},{'rank':4,'nodes':['step-6']}])
        review=self.engine.validate(graph)
        self.assertTrue(review['valid'],review)
        plan=self.engine.prepare(graph,self.folder)
        planned=(Path(plan['folder'])/'methods-planned.txt').read_text()
        self.assertIn('will be performed',planned)
        self.assertIn('Matched normal specimen',planned)
        self.assertIn('Sort matched normal alignments',planned)
        self.assertTrue((Path(plan['folder'])/'pipeline.svg').is_file())
        # A graph change after preparation cannot replace named method/report
        # attribution from the frozen plan.
        graph['nodes'][3]['label']='Changed after preparation'
        result=self.engine.execute(plan)
        self.assertTrue(result['success'],[(node['id'],node['status'],node.get('message')) for node in result['nodes']])
        self.assertEqual([node['status'] for node in result['nodes']],['success']*6)
        report=read_text(next(iter(result['outputs']['step-6::report']['files'].values())))
        self.assertEqual(report.count('<section>'),2)
        self.assertIn('All filtered calls',report)
        self.assertIn('PASS calls only',report)
        self.assertNotIn('Changed after preparation',report)
        self.assertIn('was performed',result['methods'])
        self.assertIn('FilterMutectCalls',result['methods'])
        tool=self.catalog['tools']['mutect2/tumor-normal']
        self.assertEqual(tool['output']['id'],'variants')
        variants=result['outputs']['step-3::variants']
        self.assertEqual(variants['type'],'vcf')
        self.assertIn('FilterMutectCalls',read_text(next(iter(variants['files'].values()))))
        passing=result['outputs']['step-3::pass-variants']
        self.assertEqual(passing['type'],'vcf-pass')
        rows=[line.split('\t') for line in read_text(next(iter(passing['files'].values()))).splitlines() if not line.startswith('#')]
        self.assertTrue(rows)
        self.assertTrue(all(row[6]=='PASS' for row in rows))
        preflight=result['nodes'][2]['preflight']
        self.assertEqual(preflight['alignmentHeaders'],2)
        self.assertEqual(len(preflight['referenceChecks']),2)
        self.assertEqual({check['reference'] for check in preflight['referenceChecks']},{str(PACK/'fixtures/reference.fa')})
        self.assertEqual({check['check'] for check in preflight['referenceChecks']},{'sequence-MD5'})
        for original,frozen in zip(plan['graph']['nodes'],plan['nodes']):
            self.assertEqual(original['pin'],pin_for(frozen['tool']))

    def test_reusable_workflow_strips_specimen_bindings_preserves_typed_connections(self):
        graph=self.graph()
        saved=self.engine.save_pipeline(graph)
        self.assertEqual(saved['nodes'][2]['inputs'],graph['nodes'][2]['inputs'])
        self.assertNotIn('tumor-sample',saved['nodes'][2]['params'])
        self.assertNotIn('normal-sample',saved['nodes'][2]['params'])
        self.assertTrue(all('files' not in source for source in saved['sources']))
        self.assertEqual(saved['nodes'][2]['pin'],pin_for(self.catalog['tools']['mutect2/tumor-normal']))
        preset=self.engine.save_preset(graph['nodes'][2])
        self.assertNotIn('tumor-sample',preset['params'])
        self.assertNotIn('normal-sample',preset['params'])
        self.assertNotIn('inputs',preset)

    def test_rna_alignment_inputs_and_equal_sample_names_fail_before_calling(self):
        graph=self.graph();graph['sources'][0]['type']='bam-rna'
        graph['nodes'][2]['inputs']['tumor']=['input-1']
        result=self.engine.validate(graph)
        self.assertFalse(result['valid'])
        self.assertIn('bam-rna cannot feed bam',str(result['errors']))
        graph=self.graph();graph['nodes'][2]['params']['normal-sample']='TUMOR'
        result=self.engine.validate(graph)
        self.assertFalse(result['valid'])
        self.assertIn('must differ',str(result['errors']))
        self.assertEqual(self.backend.calls,[])


if __name__=='__main__':
    unittest.main()
