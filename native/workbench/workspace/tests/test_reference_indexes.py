"""Real local store/engine contracts with a synthetic, non-scientific backend.

The separate native candidate gate must establish actual minimap2 equivalence.
These tests deliberately do not count fixture bytes as scientific execution.
"""
import copy
import hashlib
import json
import os
from pathlib import Path
import sys
import subprocess
import tempfile
import threading
import unittest

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'workspace'))
sys.path.insert(0,str(ROOT/'scripts'))
from catalog import CatalogError, _validate_workbench_schema, load_catalog, parse_pack
from engine import Engine, digest_file, pin_for
from desktop_model import DesktopModel
from cwl_export import definition_sha256
from package_reusable_index import contracts, BASE_MANIFEST_SHA256
from reference_indexes import ReferenceIndexStore, key_for, _copy_verified


class FixtureBackend:
    def __init__(self):
        self.requests=[];self.mode='success'

    def run(self,request,event,cancel):
        self.requests.append(copy.deepcopy(request));folder=Path(request['output_folder'])
        if self.mode=='failure':
            return {'success':False,'message':'Synthetic failure'}
        if self.mode=='cancel':
            cancel.set();return {'success':False,'cancelled':True}
        if request['workflow_id']=='build-sr-index':
            payload=b'MMI\x02'+b'\0'*20+Path(request['values']['reference']).read_bytes()
            (folder/'reference.mmi').write_bytes(payload)
        else:
            (folder/'alignment.sam').write_text('@HD\tVN:1.6\n')
            if request['workflow_id']=='paired-end-indexed':
                (folder/'read-pairs.json').write_text('{}\n')
        if self.mode=='cancel_after_output':
            cancel.set()
        return {'success':True,'folder':str(folder)}


def fixture_pack(root):
    original=(ROOT/'pack-examples/align.ini').read_text(encoding='utf-8')
    pack=parse_pack(original)
    for executable in pack['tools'].values():
        payload=('synthetic-'+executable['id']).encode()
        original=original.replace(executable['sha256'],hashlib.sha256(payload).hexdigest())
        for version in ('0.4.0','0.4.1'):
            path=root/'packs'/('align-'+version)/executable['path']
            path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(payload)
    (root/'packs/align-0.4.0/pack.ini').write_text(original)
    manifest,schema=contracts(original)
    (root/'packs/align-0.4.1/pack.ini').write_text(manifest)
    (root/'packs/align-0.4.1/workbench-schema.json').write_bytes(schema)


class ReferenceIndexTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='nw-index-')
        self.root=Path(self.temp.name);fixture_pack(self.root)
        self.reference=self.root/'ref.fa';self.reference.write_text('>chr1\nACGTACGTACGT\n')
        self.reads=self.root/'reads.fq';self.reads.write_text('@r\nACGT\n+\nIIII\n')
        self.catalog=load_catalog(self.root)
        self.assertEqual(self.catalog['errors'],[])
        self.backend=FixtureBackend();self.engine=Engine(self.root,self.catalog,self.backend)
        self.store=ReferenceIndexStore(self.root)

    def tearDown(self):
        self.temp.cleanup()

    def graph(self):
        return {'schema':1,'name':'Synthetic indexed fixture','sources':[
            {'id':'input-1','type':'reference','files':{'reference':str(self.reference)}},
            {'id':'input-2','type':'reads','files':{'reads1':str(self.reads)}}],
            'nodes':[
                {'id':'step-1','tool':'align/build-sr-index','params':{'threads':'2'},'inputs':{'reference':['input-1']}},
                {'id':'step-2','tool':'align/single-end-indexed','params':{'threads':'2','sample':'test'},'inputs':{'index':['step-1::index'],'reads1':['input-2']}}]}

    def run_graph(self,**kwargs):
        plan=self.engine.prepare(self.graph(),self.root,**kwargs)
        return plan,self.engine.execute(plan)

    def built(self):
        plan,run=self.run_graph();self.assertTrue(run['success'],run)
        return plan,run,run['nodes'][0]['referenceIndex']

    def test_build_hit_exact_files_methods_and_cwl_commands(self):
        plan,first,index=self.built()
        self.assertEqual(index['action'],'built')
        second_plan,second=self.run_graph()
        self.assertTrue(second['success'],second)
        self.assertEqual(second['nodes'][0]['referenceIndex']['action'],'reused')
        self.assertEqual([r['workflow_id'] for r in self.backend.requests],['build-sr-index','single-end-indexed','single-end-indexed'])
        self.assertEqual(first['outputs']['step-1::index']['sha256'],second['outputs']['step-1::index']['sha256'])
        receipt=self.store.verify(index['key'])
        self.assertEqual(receipt['identity']['reference']['sha256'],digest_file(self.reference))
        self.assertIn('indexing command was not run',second['methods'])
        exported=json.loads((Path(second_plan['folder'])/'workflow.cwl').read_text(encoding='utf-8'))
        self.assertEqual(definition_sha256(exported),second_plan['workflowExport']['definitionSha256'])
        self.assertIn('build-sr-index',json.dumps(exported))
        self.assertIn('reused',json.dumps(exported['$graph'][0]['nw:execution']))
        self.assertEqual(second['outputs']['step-1::index']['referenceIndex']['key'],index['key'])
        metrics=json.loads((Path(second_plan['folder'])/'performance.json').read_text(encoding='utf-8'))
        self.assertIn('reference_index_reused_without_native_command',json.dumps(metrics['steps'][0]))

    def test_reference_and_parameters_make_distinct_builds(self):
        _,_,first=self.built()
        self.reference.write_text('>chr1\nACGTACGTACGA\n')
        _,changed=self.run_graph();self.assertTrue(changed['success'],changed)
        self.assertNotEqual(first['key'],changed['nodes'][0]['referenceIndex']['key'])
        graph=self.graph();graph['nodes'][0]['params']['threads']='1'
        plan=self.engine.prepare(graph,self.root);third=self.engine.execute(plan)
        self.assertTrue(third['success'],third)
        self.assertNotEqual(changed['nodes'][0]['referenceIndex']['key'],third['nodes'][0]['referenceIndex']['key'])
        for path,value in [('version','2.29'),('sha256','0'*64)]:
            identity=copy.deepcopy(first['identity']);identity['executables'][0][path]=value
            self.assertNotEqual(key_for(identity),first['key'])
        identity=copy.deepcopy(first['identity']);identity['pack']['manifestSha256']='1'*64
        self.assertNotEqual(key_for(identity),first['key'])

    def test_corrupt_hit_fails_closed_and_blocks_consumer(self):
        _,_,index=self.built()
        cache=self.store.root/index['key']/'files/reference.mmi'
        cache.write_bytes(b'broken')
        _,run=self.run_graph()
        self.assertFalse(run['success']);self.assertEqual(run['nodes'][1]['status'],'blocked')
        self.assertIn('corrupted',run['nodes'][0]['message'])
        self.assertEqual(len(self.backend.requests),2)
        self.assertEqual(cache.read_bytes(),b'broken')

    def test_missing_extra_or_duplicate_receipt_fields_rejected(self):
        _,_,index=self.built();folder=self.store.root/index['key']
        extra=folder/'unexpected.txt';extra.write_text('not inventoried')
        with self.assertRaisesRegex(ValueError,'undeclared'):
            self.store.verify(index['key'])
        extra.unlink()
        saved=(folder/'files/reference.mmi').read_bytes();(folder/'files/reference.mmi').unlink()
        with self.assertRaisesRegex(ValueError,'missing'):
            self.store.verify(index['key'])
        (folder/'files/reference.mmi').write_bytes(saved)
        (folder/'index.json').write_text('{"schema":1,"schema":1}')
        with self.assertRaisesRegex(ValueError,'Duplicate'):
            self.store.verify(index['key'])

    def test_malformed_receipt_is_an_invalid_row_not_a_broken_library(self):
        _,_,index=self.built();folder=self.store.root/index['key'];path=folder/'index.json'
        original=path.read_text(encoding='utf-8')
        for raw in ('[]','{"schema":NaN}','{"schema":true}'):
            path.write_text(raw)
            self.assertEqual(self.store.list()['entries'][0]['status'],'invalid')
            with self.assertRaises(ValueError):
                self.store.verify(index['key'])
        receipt=json.loads(original);receipt['identity']['outputs']=[]
        key=key_for(receipt['identity']);receipt['key']=key;path.write_text(json.dumps(receipt))
        folder.rename(self.store.root/key)
        with self.assertRaisesRegex(ValueError,'inventory'):
            self.store.verify(key)

    def test_failure_and_cancellation_publish_nothing(self):
        for mode in ('failure','cancel','cancel_after_output'):
            self.backend.mode=mode
            _,run=self.run_graph()
            self.assertFalse(run['success'],run)
            self.assertFalse(any(p.name[0]!='.' or '.partial-' in p.name for p in self.store.root.iterdir()))

    def test_rebuild_policy_runs_command_but_preserves_matching_entry(self):
        _,_,index=self.built();before=(self.store.root/index['key']/'index.json').read_bytes()
        plan,run=self.run_graph(index_policy='rebuild')
        self.assertTrue(run['success'],run)
        self.assertEqual(plan['referenceIndexPolicy'],'rebuild')
        self.assertEqual(run['nodes'][0]['referenceIndex']['action'],'built')
        self.assertEqual(len(self.backend.requests),4)
        self.assertEqual((self.store.root/index['key']/'index.json').read_bytes(),before)

    def test_tampered_executable_rejected_on_hit(self):
        self.built()
        (self.root/'packs/align-0.4.1/bin/minimap2.exe').write_text('changed executable')
        _,run=self.run_graph();self.assertFalse(run['success'])
        self.assertIn('executable failed integrity',run['nodes'][0]['message'])
        self.assertEqual(len(self.backend.requests),2)

    def test_external_index_and_incompatible_mapping_binary_rejected(self):
        graph=self.graph();graph['sources'].append({'id':'input-3','type':'minimap2-sr-index','files':{'index':str(self.reference)}})
        graph['nodes'][1]['inputs']['index']=['input-3']
        review=self.engine.validate(graph,check_files=False)
        self.assertFalse(review['ok']);self.assertIn('arbitrary .mmi',json.dumps(review))
        self.catalog['tools']['align/single-end-indexed']=copy.deepcopy(self.catalog['tools']['align/single-end-indexed'])
        self.catalog['tools']['align/single-end-indexed']['executables'][0]['version']='different'
        review=self.engine.validate(self.graph())
        self.assertFalse(review['ok']);self.assertIn('incompatible',json.dumps(review))

    def test_external_input_list_excludes_producer_only_port_but_keeps_graph_connection(self):
        model=DesktopModel(self.root,self.catalog,auto_sources=False)
        kinds={row['id'] for row in model.input_types()}
        self.assertNotIn('minimap2-sr-index',kinds)
        self.assertTrue({'reference','pair','reads'}<=kinds)
        with self.assertRaises(ValueError):
            model.dispatch('add_input',{'inputType':'minimap2-sr-index'})
        built=model.dispatch('add_tool',{'toolId':'align/build-sr-index'})['selected']
        consumer=model.dispatch('add_tool',{'toolId':'align/single-end-indexed'})['selected']
        connected=model.dispatch('connect',{'nodeId':consumer,'portId':'index','refs':[built+'::index']})
        index_port=next(port for port in connected['inspector']['ports'] if port['id']=='index')
        self.assertEqual(index_port['refs'][0]['ref'],built+'::index')
        self.assertIn('Workflow mode',index_port['help'])
        # The exclusion follows the declared port, not a hardcoded type name.
        # A future pack may independently accept ordinary files of that type.
        modified=copy.deepcopy(self.catalog)
        other=copy.deepcopy(modified['tools']['align/single-end-indexed'])
        other.pop('requiresReferenceIndex');modified['tools']['fixture/ordinary-index']=other
        external=DesktopModel(self.root,modified,auto_sources=False)
        self.assertIn('minimap2-sr-index',{row['id'] for row in external.input_types()})
        standalone=DesktopModel(self.root,self.catalog)
        shown=standalone.dispatch('add_tool',{'toolId':'align/single-end-indexed'})
        help_text=next(port['help'] for port in shown['inspector']['ports'] if port['id']=='index')
        self.assertIn('requires that graph producer',help_text)

    def test_process_owned_lock_blocks_concurrent_build_and_recovers_after_kill(self):
        _,_,index=self.built()
        command='import sys; sys.path.insert(0,sys.argv[1]); from reference_indexes import ReferenceIndexStore; store=ReferenceIndexStore(sys.argv[2]); lease=store._locked(sys.argv[3],None); lease.__enter__(); print("locked",flush=True); sys.stdin.read()'
        child=subprocess.Popen([sys.executable,'-u','-c',command,str(ROOT/'workspace'),str(self.root),index['key']],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
        try:
            self.assertEqual(child.stdout.readline().strip(),'locked')
            _,run=self.run_graph();self.assertFalse(run['success'])
            self.assertIn('already being built',run['nodes'][0]['message'])
            self.assertEqual(len(self.backend.requests),2)
        finally:
            child.kill();child.communicate(timeout=10)
        _,run=self.run_graph();self.assertTrue(run['success'],run)
        self.assertEqual(run['nodes'][0]['referenceIndex']['action'],'reused')
        self.assertEqual(len(self.backend.requests),3)

    def test_existing_copy_destination_is_never_deleted(self):
        target=self.root/'preserved';target.write_text('must remain')
        with self.assertRaises(FileExistsError):
            _copy_verified(self.reference,target,{'bytes':1,'sha256':'0'*64},None)
        self.assertEqual(target.read_text(),'must remain')

    def test_readonly_listing_does_not_create_or_claim_verified_indexes(self):
        self.assertEqual(self.store.list(),{'schema':1,'entries':[],'truncated':False})
        self.assertFalse(self.store.root.exists())
        _,_,index=self.built();listing=self.store.list()
        self.assertEqual(listing['entries'][0]['status'],'not_verified')
        self.assertEqual(listing['entries'][0]['key'],index['key'])

    def test_symlink_store_is_rejected(self):
        if os.name=='nt':
            self.skipTest('Creating a Windows test symlink may require privileges; native gate checks ordinary paths.')
        target=self.root/'outside';target.mkdir()
        parent=self.root/'user-data';parent.mkdir()
        (parent/'reference-indexes').symlink_to(target,target_is_directory=True)
        _,run=self.run_graph();self.assertFalse(run['success'])
        self.assertIn('symbolic links',run['nodes'][0]['message'])
        self.assertEqual(list(target.iterdir()),[])

    def test_batch_provenance_is_frozen_and_bound_into_cwl(self):
        metadata={'batchId':'a'*32,'sampleId':'sample1','metadata':{'schema':1,'columns':{'condition':'test'},'fileBindings':[{'sourceId':'input-2','path':str(self.reads)}]}}
        plan=self.engine.prepare(self.graph(),self.root,run_metadata=metadata)
        metadata['metadata']['columns']['condition']='changed'
        self.assertEqual(plan['batch']['metadata']['columns']['condition'],'test')
        exported=json.loads((Path(plan['folder'])/'workflow.cwl').read_text(encoding='utf-8'))
        self.assertEqual(json.loads(exported['$graph'][0]['nw:batch']),plan['batch'])
        run=self.engine.execute(plan);self.assertTrue(run['success'],run)
        self.assertEqual(run['batch'],plan['batch'])
        self.assertIn('sample sample1',run['methods'])
        for invalid in ({},dict(metadata,batchId='not-valid'),dict(metadata,metadata={'huge':'x'*17000}),dict(metadata,metadata={'constructor':1})):
            with self.assertRaises(ValueError):
                self.engine.prepare(self.graph(),self.root,run_metadata=invalid)

    def test_reference_mutation_after_freeze_rejected(self):
        plan=self.engine.prepare(self.graph(),self.root)
        self.reference.write_text('>chr1\nTTTT\n')
        run=self.engine.execute(plan);self.assertFalse(run['success'])
        self.assertEqual(self.backend.requests,[])

    def test_reference_alphabet_and_duplicate_contigs_checked_before_build(self):
        for text in ('>a\nXYZ\n','>a\nACGT\n>a\nACGT\n'):
            self.reference.write_text(text)
            _,run=self.run_graph();self.assertFalse(run['success'],run)
        self.assertEqual(self.backend.requests,[])

    def test_indexed_alignment_keeps_reference_lineage_through_bam_to_caller(self):
        for pack in ('bam','variants'):
            folder=self.root/'packs'/(pack+'-0.4.0');folder.mkdir()
            (folder/'pack.ini').write_bytes((ROOT/'pack-examples'/(pack+'.ini')).read_bytes())
        engine=Engine(self.root,load_catalog(self.root),self.backend)
        other=self.root/'different-reference.fa';other.write_text('>chr1\nTTTTTTTTTTTT\n')
        graph=self.graph()
        graph['sources'].append({'id':'input-3','type':'reference','files':{'reference':str(other)}})
        graph['nodes'] += [
            {'id':'step-3','tool':'bam/sort','params':{},'inputs':{'alignment':['step-2::sam']}},
            {'id':'step-4','tool':'variants/call','params':{},'inputs':{'alignment':['step-3::sorted'],'reference':['input-3']}}]
        rejected=engine.validate(graph)
        self.assertFalse(rejected['ok'])
        self.assertIn('different reference input slots',json.dumps(rejected))
        graph['nodes'][-1]['inputs']['reference']=['input-1']
        accepted=engine.validate(graph)
        self.assertTrue(accepted['ok'],accepted)

    def test_legacy_pins_preserved_and_candidate_schema_is_strict(self):
        published=(ROOT/'pack-examples/align.ini').read_bytes()
        self.assertEqual(hashlib.sha256(published).hexdigest(),BASE_MANIFEST_SHA256)
        manifest,raw=contracts(published.decode());pack=parse_pack(manifest);schema=json.loads(raw)
        self.assertEqual(len(pack['workflows']),5)
        old=parse_pack(published.decode())
        for name in ('single-end','paired-end'):
            self.assertEqual(pack['workflows'][name],old['workflows'][name])
        self.assertEqual([t['packVersion'] for t in self.catalog['toolVersions']['align/single-end']],['0.4.1','0.4.0'])
        for change in ({'format':'unknown'},{'referencePort':'missing'},{'tool':'missing'},{'extra':True}):
            modified=copy.deepcopy(schema);modified['workflows']['build-sr-index']['referenceIndex'].update(change)
            with self.assertRaises(CatalogError):
                _validate_workbench_schema(modified,pack)


if __name__=='__main__':
    unittest.main()
