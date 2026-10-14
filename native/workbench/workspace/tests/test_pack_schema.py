"""Versioned, SHA-pinned scientific pack metadata and sequence boundaries."""
import copy
import gzip
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import unittest

WORKSPACE=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(WORKSPACE))
from catalog import CatalogError, load_catalog, load_pack, _output_type
from engine import Engine, _sequence_evidence, _check_path_policy, _check_file_kind, _bed_evidence, _vcf_header_evidence

MANIFEST='''[pack]
format=2
id=example
version=0.5.2
name=Example sequence pack
platform=windows-x86_64
description=Exercise explicitly typed scientific metadata.
color=#43847C
[tool:example]
path=bin/example.exe
version=1.0
sha256={binary_sha}
[asset:workbench-schema]
path=workbench-schema.json
sha256={schema_sha}
[workflow:filter]
name=Filter nucleotide sequences
description=Filter sequences using the recorded threshold.
inputs=sequences,minimum
outputs=filtered,statistics
steps=filter,statistics
[input:filter:sequences]
label=Nucleotide sequences
type=file
required=true
filter=FASTA sequences|*.fa;*.fasta
[input:filter:minimum]
label=Minimum length
type=integer
min=0
max=1000000
default=10
[output:filter:filtered]
label=Filtered sequences
path=filtered.fa
nonempty=false
[output:filter:statistics]
label=Sequence statistics
path=statistics.tsv
nonempty=true
[step:filter:filter]
label=Filter sequences
kind=exec
tool=example
stdout=filtered
arg.0=filter
arg.1={{input:sequences}}
arg.2={{input:minimum}}
[step:filter:statistics]
label=Summarize filtered sequences
kind=exec
tool=example
stdout=statistics
arg.0=stats
arg.1={{output:filtered}}
'''


def metadata():
    return {'schema':1,'category':'Sequence utilities','citations':[{'text':'Example authors. Example software. 2026.','url':'https://example.org/paper'}],
            'workflows':{'filter':{'methods':'Sequences are filtered by the configured minimum length.',
                'ports':[{'id':'sequences','type':'fasta-nucleotide','accepts':['fasta-nucleotide'],'manifestInputs':['sequences'],'min':1,'max':1,'requiredState':{'compression':'none'}}],
                'outputs':[{'id':'filtered','type':'fasta-nucleotide','manifestOutputs':['filtered'],'state':{'compression':'none','alphabet':'nucleotide'},'propagateStateFrom':'sequences'},
                           {'id':'statistics','type':'metrics','manifestOutputs':['statistics'],'state':{}}]}}}


class PackSchemaTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(prefix='workbench-schema-')
        self.root=Path(self.tmp.name)
        self.pack=self.root/'packs/example-0.5.2'
        (self.pack/'bin').mkdir(parents=True)
        self.binary=b'fixture executable contents'
        (self.pack/'bin/example.exe').write_bytes(self.binary)
        self.write(metadata())
        self.cancel=threading.Event()

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, document=None, raw=None):
        raw=raw if raw is not None else json.dumps(document).encode()
        (self.pack/'workbench-schema.json').write_bytes(raw)
        (self.pack/'pack.ini').write_text(MANIFEST.format(binary_sha=hashlib.sha256(self.binary).hexdigest(),schema_sha=hashlib.sha256(raw).hexdigest()))

    def fasta(self,text,name='sequences.fa'):
        path=self.root/name;path.write_text(text)
        return path

    def evidence(self,text,kind='fasta-nucleotide',rules=None,state=None,allow_empty=False):
        return _sequence_evidence(self.fasta(text),kind,[kind],state or {},self.cancel,allow_empty=allow_empty,rules=rules)

    def test_discovery_uses_pinned_category_ports_outputs_methods_and_citations(self):
        tool=load_catalog(self.root)['tools']['example/filter']
        self.assertEqual(tool['category'],'Sequence utilities')
        self.assertEqual(tool['ports'][0]['type'],'fasta-nucleotide')
        self.assertEqual(tool['outputs'][0]['type'],'fasta-nucleotide')
        self.assertFalse(tool['outputs'][0]['fields'][0]['nonempty'])
        self.assertEqual(tool['schemaAsset']['path'],'workbench-schema.json')
        self.assertIn('minimum length',tool['methodsDescription'])
        self.assertEqual(tool['citations'][0]['url'],'https://example.org/paper')

    def test_native_path_policy_is_pinned_and_checks_windows_paths_on_linux(self):
        document=metadata()
        document['workflows']['filter']['pathPolicy']={'asciiOnly':True,'forbiddenCharacters':[',']}
        self.write(document)
        tool=load_catalog(self.root)['tools']['example/filter']
        self.assertEqual(tool['pathPolicy'],{'asciiOnly':True,'forbiddenCharacters':[',']})
        _check_path_policy(tool,[r'C:\Users\Tim H\reads.fastq',r'D:\Work Results'])
        for path in (r'C:\Users\Last, First\reads.fastq','C:\\Users\\Jos\u00e9\\reads.fastq'):
            with self.subTest(path=path),self.assertRaises(ValueError):
                _check_path_policy(tool,[path])
        engine=Engine(self.root,load_catalog(self.root))
        source=self.fasta('>one\nACGT\n')
        graph={'sources':[{'id':'input-1','type':'fasta-nucleotide','files':{'sequences':str(source)}}],
               'nodes':[{'id':'step-1','tool':'example/filter','inputs':{'sequences':['input-1']},'params':{}}]}
        for name in ('comma,results','r\u00e9sults'):
            output=self.root/name;output.mkdir()
            with self.assertRaisesRegex(ValueError,'paths'):
                engine.prepare(graph,output)
            self.assertFalse(list(output.iterdir()),'Invalid paths must be rejected before allocating a run')
        old=WORKSPACE.parents[2]/'integration-0.5.2/native-workbench/workspace/catalog.py'
        if old.is_file():
            spec=importlib.util.spec_from_file_location('catalog_052_boundary',old)
            module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
            with self.assertRaisesRegex(ValueError,'unknown field'):
                module.load_pack(self.pack/'pack.ini')

    def test_path_policy_rejects_unknown_or_unsafe_schema_shapes(self):
        for policy in ({'runCode':'anything'},{'asciiOnly':'true'},{'forbiddenCharacters':[',',',']},
                       {'forbiddenCharacters':['/']},{'forbiddenCharacters':[['comma']]},{'forbiddenCharacters':['xx']}):
            document=metadata();document['workflows']['filter']['pathPolicy']=policy
            self.write(document)
            with self.subTest(policy=policy),self.assertRaises(ValueError):
                load_pack(self.pack/'pack.ini')

    def test_rna_alignment_semantic_type_survives_file_signature_normalization(self):
        document=metadata();workflow=document['workflows']['filter']
        workflow['ports'][0].update(type='sam-rna',accepts=['sam-rna','bam-rna'],requiredState={})
        workflow['outputs'][0].update(type='bam-rna',state={'sort':'coordinate','pairing':'paired'})
        self.write(document)
        catalog=load_catalog(self.root);engine=Engine(self.root,catalog)
        path=self.fasta('@HD\tVN:1.6\tSO:unsorted\n@SQ\tSN:chr1\tLN:100\n','rna.sam')
        _check_file_kind(path,'sam-rna',allowed_types=['sam-rna'])
        graph={'sources':[{'id':'input-1','type':'sam-rna','files':{'sequences':str(path)}}],
               'nodes':[{'id':'step-1','tool':'example/filter','inputs':{'sequences':['input-1']},'params':{}}]}
        plan=engine.prepare(graph,self.root)
        self.assertEqual(plan['graph']['sources'][0]['type'],'sam-rna')
        changed=copy.deepcopy(catalog)
        changed['tools']['example/filter']['ports'][0].update(type='sam',accepts=['sam','bam'])
        self.assertFalse(Engine(self.root,changed).validate(graph)['valid'])

    def test_target_bed_is_zero_based_bounded_named_and_nonoverlapping(self):
        rules={'minColumns':4,'referenceBounds':True,'nonOverlapping':True}
        reference=[('chr1',100,'unused')]
        path=self.root/'targets.bed'
        path.write_text('track name=targets\nchr1\t0\t20\tfirst\nchr1\t20\t100\tsecond\n')
        evidence=_bed_evidence(path,rules,reference,self.cancel)
        self.assertEqual(evidence['records'],2)
        for text in ('chr1\t-1\t20\tx\n','chr1\t2\t2\tx\n','chr1\t0\t101\tx\n',
                     'chr2\t0\t20\tx\n','chr1\t0\t20\n','chr1\t0\t20\t\n',
                     'chr1\t10\t30\tx\nchr1\t0\t20\ty\n'):
            path.write_text(text)
            with self.subTest(text=text),self.assertRaises(ValueError):
                _bed_evidence(path,rules,reference,self.cancel)
        self.cancel.set()
        with self.assertRaises(InterruptedError):
            _bed_evidence(path,rules,reference,self.cancel)

    def test_related_integer_bounds_are_checked_before_execution(self):
        document=metadata()
        document['workflows']['filter']['parameterConstraints']=[{'left':'minimum','operator':'<=','right':'maximum'}]
        self.write(document)
        manifest=self.pack/'pack.ini'
        text=manifest.read_text().replace('inputs=sequences,minimum\n','inputs=sequences,minimum,maximum\n')
        manifest.write_text(text+'\n[input:filter:maximum]\nlabel=Maximum length\ntype=integer\nmin=0\nmax=1000000\ndefault=100\n')
        catalog=load_catalog(self.root);engine=Engine(self.root,catalog)
        path=self.fasta('>one\nACGT\n')
        graph={'sources':[{'id':'input-1','type':'fasta-nucleotide','files':{'sequences':str(path)}}],
               'nodes':[{'id':'step-1','tool':'example/filter','inputs':{'sequences':['input-1']},'params':{}}]}
        self.assertTrue(engine.validate(graph)['valid'])
        graph['nodes'][0]['params']={'minimum':'100','maximum':'10'}
        result=engine.validate(graph)
        self.assertFalse(result['valid'])
        self.assertIn('Minimum length must be less than or equal to Maximum length',str(result['errors']))
        optional=copy.deepcopy(catalog)
        maximum=next(p for p in optional['tools']['example/filter']['params'] if p['id']=='maximum')
        maximum.update(required=False,default='')
        graph['nodes'][0]['params']={}
        self.assertTrue(Engine(self.root,optional).validate(graph)['valid'],'An omitted optional bound has no numeric comparison')
        for constraint in ({'left':'minimum','operator':'>','right':'maximum'},
                           {'left':'minimum','operator':'<=','right':'minimum'},
                           {'left':'minimum','operator':'<=','right':'sequences'}):
            document['workflows']['filter']['parameterConstraints']=[constraint]
            self.write(document)
            with self.subTest(constraint=constraint),self.assertRaises(ValueError):
                load_pack(self.pack/'pack.ini')

    def test_single_sample_header_requires_matching_parameter(self):
        path=self.fasta('@HD\tVN:1.6\tSO:coordinate\n@SQ\tSN:chr1\tLN:4\n','alignment.sam')
        reference=self.fasta('>chr1\nACGT\n','reference.fa')
        port={'id':'alignment','type':'bam','accepts':['sam','bam'],'manifestInputs':['alignment'],
              'requiredState':{'sort':'coordinate'},'validation':{'singleSample':True,'sampleParameter':'sample'}}
        tool={'id':'fixture/call','name':'Caller','schemaAsset':{},'ports':[port,{'id':'reference','type':'reference','manifestInputs':['reference']}],
              'executables':[]}
        node={'tool':tool};values={'alignment':str(path),'reference':str(reference),'sample':'one'}
        class Backend:
            def inspect_alignment(inner,*args):
                return path.read_text()+inner.groups
        backend=Backend();engine=Engine(self.root,load_catalog(self.root),backend)
        engine._samtools=lambda node: self.pack/'bin/example.exe'
        backend.groups='@RG\tID:lane1\tSM:one\n@RG\tID:lane2\tSM:one\n'
        result=engine._preflight(node,values,self.cancel)
        self.assertEqual(result['alignmentHeaders'],1)
        for groups in ('','@RG\tID:lane1\n','@RG\tID:lane1\tSM:two\n',
                       '@RG\tID:lane1\tSM:one\n@RG\tID:lane2\tSM:two\n',
                       '@RG\tID:lane1\tSM:one\n@RG\tID:lane1\tSM:one\n'):
            backend.groups=groups
            with self.subTest(groups=groups),self.assertRaises(ValueError):
                engine._preflight(node,values,self.cancel)

    def test_distinct_text_parameters_match_sample_identifier_semantics(self):
        document=metadata()
        document['workflows']['filter']['parameterConstraints']=[{'left':'tumor-sample','operator':'!=','right':'normal-sample'}]
        def install():
            self.write(document)
            manifest=self.pack/'pack.ini'
            text=manifest.read_text().replace('inputs=sequences,minimum\n','inputs=sequences,minimum,tumor-sample,normal-sample\n')
            manifest.write_text(text+'\n[input:filter:tumor-sample]\nlabel=Tumor sample\ntype=text\nconstraint=identifier\ndefault=TUMOR\n'
                                '\n[input:filter:normal-sample]\nlabel=Normal sample\ntype=text\nconstraint=identifier\ndefault=NORMAL\n')
        install()
        engine=Engine(self.root,load_catalog(self.root))
        graph={'sources':[{'id':'input-1','type':'fasta-nucleotide','files':{'sequences':str(self.fasta('>one\nACGT\n'))}}],
               'nodes':[{'id':'step-1','tool':'example/filter','inputs':{'sequences':['input-1']},'params':{}}]}
        self.assertTrue(engine.validate(graph)['valid'])
        graph['nodes'][0]['params']={'tumor-sample':'patient','normal-sample':'patient'}
        self.assertIn('Tumor sample must differ from Normal sample',str(engine.validate(graph)['errors']))
        with self.assertRaisesRegex(ValueError,'must differ'):
            engine.prepare(graph,self.root)
        graph['nodes'][0]['params']['normal-sample']='PATIENT'
        self.assertTrue(engine.validate(graph)['valid'],'SAM sample names are case-sensitive')
        self.assertEqual(engine.save_preset(graph['nodes'][0])['params'],{'minimum':'10'},'Sample names are analysis bindings, never preset settings')
        for constraint in ({'left':'tumor-sample','operator':'==','right':'normal-sample'},
                           {'left':'tumor-sample','operator':'<=','right':'normal-sample'},
                           {'left':'tumor-sample','operator':'!=','right':'minimum'},
                           {'left':'tumor-sample','operator':'!=','right':'tumor-sample'},
                           {'left':['tumor-sample'],'operator':'!=','right':'normal-sample'}):
            document['workflows']['filter']['parameterConstraints']=[constraint]
            install()
            with self.subTest(constraint=constraint),self.assertRaises(ValueError):
                load_pack(self.pack/'pack.ini')

    def test_manifest_distinct_files_catches_hard_links_before_execution(self):
        document=metadata()
        document['workflows']['filter']['ports'].append({'id':'normal','type':'fasta-nucleotide','manifestInputs':['normal']})
        self.write(document)
        manifest=self.pack/'pack.ini'
        text=manifest.read_text().replace('inputs=sequences,minimum\n','inputs=sequences,minimum,normal\n')
        manifest.write_text(text+'\n[input:filter:normal]\nlabel=Normal input\ntype=file\ndifferent-from=sequences\n')
        catalog=load_catalog(self.root);engine=Engine(self.root,catalog)
        first=self.fasta('>one\nACGT\n');second=self.fasta('>two\nACGT\n','normal.fa')
        alias=self.root/'same-content-hardlink.fa';os.link(first,alias)
        graph={'sources':[{'id':'input-1','type':'fasta-nucleotide','files':{'sequences':str(first)}},
                          {'id':'input-2','type':'fasta-nucleotide','files':{'normal':str(second)}}],
               'nodes':[{'id':'step-1','tool':'example/filter','inputs':{'sequences':['input-1'],'normal':['input-2']},'params':{}}]}
        self.assertTrue(engine.validate(graph)['valid'])
        node={'tool':catalog['tools']['example/filter']}
        for duplicate in (first,alias):
            graph['sources'][1]['files']['normal']=str(duplicate)
            self.assertIn('must be a different file',str(engine.validate(graph)['errors']))
            with self.assertRaisesRegex(ValueError,'hard links'):
                engine._preflight(node,{'sequences':str(first),'normal':str(duplicate)},self.cancel)
        # Optional unbound files are left to ordinary cardinality validation.
        result=engine._preflight(node,{'sequences':str(first),'normal':''},self.cancel)
        self.assertEqual(len(result['sequenceChecks']),1)

    def test_vcf_resource_info_header_rule_is_strict_and_pinned(self):
        document=metadata();port=document['workflows']['filter']['ports'][0]
        port.update(type='vcf',accepts=['vcf'],requiredState={},
                    validation={'requiredInfoFields':[{'id':'AF','number':'A','type':'Float'}]})
        self.write(document)
        catalog=load_catalog(self.root);tool=catalog['tools']['example/filter']
        self.assertEqual(tool['ports'][0]['validation'],port['validation'])
        path=self.fasta('##fileformat=VCFv4.2\n##INFO=<ID=AF,Number=A,Type=Float,Description="Population allele frequency">\n'
                        '#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\n','resource.vcf')
        evidence=Engine(self.root,catalog)._preflight({'tool':tool},{'sequences':str(path)},self.cancel)
        self.assertEqual(evidence['sequenceChecks'][0]['check'],'VCF-INFO-header')
        invalid=[[],[{'id':'AF','number':'A','type':'float'}],[{'id':'AF','number':1,'type':'Float'}],
                 [{'id':'AF','number':'A','type':'Float','command':'ignored'}],
                 [{'id':'AF','number':'A','type':'Float'}]*2,[{'id':'AF','number':'A','type':'Flag'}]]
        for fields in invalid:
            port['validation']['requiredInfoFields']=fields;self.write(document)
            with self.subTest(fields=fields),self.assertRaises(ValueError):
                load_pack(self.pack/'pack.ini')
        port['validation']['requiredInfoFields']=[{'id':'AF','number':'A','type':'Float'}]
        port['accepts']=['vcf','bcf'];self.write(document)
        with self.assertRaises(ValueError):
            load_pack(self.pack/'pack.ini')

    def test_decimal_text_bounds_preserve_precise_settings_and_reject_invalid_values(self):
        document=metadata()
        document['workflows']['filter']['parameterRanges']=[{'parameter':'contamination','min':0,'max':1}]
        def install():
            self.write(document)
            manifest=self.pack/'pack.ini'
            text=manifest.read_text().replace('inputs=sequences,minimum\n','inputs=sequences,minimum,contamination\n')
            manifest.write_text(text+'\n[input:filter:contamination]\nlabel=Contamination fraction\ntype=text\ndefault=0\n')
        install();engine=Engine(self.root,load_catalog(self.root))
        graph={'sources':[{'id':'input-1','type':'fasta-nucleotide','files':{'sequences':str(self.fasta('>one\nACGT\n'))}}],
               'nodes':[{'id':'step-1','tool':'example/filter','inputs':{'sequences':['input-1']},'params':{}}]}
        for value in ('0','1','0.01367251','1.367251e-2','.5','+0.10'):
            graph['nodes'][0]['params']['contamination']=value
            with self.subTest(value=value):
                self.assertTrue(engine.validate(graph)['valid'])
                self.assertEqual(engine.save_preset(graph['nodes'][0])['params']['contamination'],value)
        graph['nodes'][0]['params']['contamination']='0.01367251'
        plan=engine.prepare(graph,self.root)
        self.assertEqual(plan['nodes'][0]['params']['contamination'],'0.01367251')
        self.assertIn('Contamination fraction=0.01367251',plan['methods'])
        for value in ('NaN','Infinity','-Infinity','1e9999','-0.01','1.01','1.000000000000000000000000001',' 0.1 ','0.1;anything',''):
            graph['nodes'][0]['params']['contamination']=value
            with self.subTest(value=value):
                self.assertFalse(engine.validate(graph)['valid'])
                with self.assertRaises(ValueError):
                    engine.save_preset(graph['nodes'][0])
        for bounds in ({'parameter':'minimum','min':0,'max':1},{'parameter':'contamination','min':True,'max':1},
                       {'parameter':'contamination','min':0,'max':'1'},{'parameter':'contamination','min':2,'max':1},
                       {'parameter':'contamination','min':0,'max':1,'code':'anything'}):
            document['workflows']['filter']['parameterRanges']=[bounds];install()
            with self.subTest(bounds=bounds),self.assertRaises(ValueError):
                load_pack(self.pack/'pack.ini')

    def test_vcf_header_checks_plain_gzip_quoted_descriptions_and_reject_bad_resources(self):
        rules={'requiredInfoFields':[{'id':'AF','number':'A','type':'Float'}]}
        prefix='##fileformat=VCFv4.2\n'
        declaration='##INFO=<Description="Comma, and escaped \\\"quote\\\"",Type=Float,ID=AF,Number=A>\n'
        columns='#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\n'
        # This validator establishes the header contract only. A deliberately
        # invalid record remains the variant reader's responsibility.
        text=prefix+declaration+columns+'chr1\t1\t.\tA\tC\t.\t.\tAF=not-a-number\n'
        path=self.fasta(text,'population.vcf')
        zipped=self.root/'population.vcf.gz';zipped.write_bytes(gzip.compress(text.encode()))
        for selected in (path,zipped):
            evidence=_vcf_header_evidence(selected,rules,self.cancel)
            self.assertEqual(evidence['requiredInfoFields'],rules['requiredInfoFields'])
            self.assertIn('do not verify every record',evidence['note'])
        for invalid in (prefix+columns,prefix+declaration.replace('Number=A','Number=1')+columns,
                        prefix+declaration.replace('Type=Float','Type=Integer')+columns,
                        prefix+declaration*2+columns,prefix+declaration,
                        prefix+'##INFO=<ID=AF,ID=DP,Number=A,Type=Float>\n'+columns,
                        prefix+'##INFO=<ID=AF,Number=A,Type=Float,Description="unfinished>\n'+columns,
                        prefix+'##large='+'x'*(1024*1024)+'\n'+declaration+columns):
            path.write_text(invalid)
            with self.subTest(prefix=invalid[:80]),self.assertRaises(ValueError):
                _vcf_header_evidence(path,rules,self.cancel)
        self.cancel.set()
        with self.assertRaises(InterruptedError):
            _vcf_header_evidence(zipped,rules,self.cancel)

    def test_content_hash_checked_at_discovery_and_again_before_execution(self):
        catalog=load_catalog(self.root);engine=Engine(self.root,catalog)
        (self.pack/'workbench-schema.json').write_text('{}')
        isolated=load_catalog(self.root)
        self.assertNotIn('example/filter',isolated['tools'])
        self.assertIn('hash mismatch',isolated['errors'][0]['message'])
        with self.assertRaisesRegex(CatalogError,'hash mismatch'):
            load_pack(self.pack/'pack.ini')
        with self.assertRaisesRegex(ValueError,'schema changed'):
            engine._verify_manifest(catalog['tools']['example/filter'])

    def test_duplicate_nonfinite_unknown_json_fields_and_versions_rejected(self):
        for raw in (b'{"schema":1,"schema":1}',b'{"schema":NaN}',b'{"schema":Infinity}'):
            with self.subTest(raw=raw):
                self.write(raw=raw)
                with self.assertRaises(CatalogError): load_pack(self.pack/'pack.ini')
        for key,value in (('schema',2),('commands',['arbitrary']),('types',{'reference':'Protein'})):
            document=metadata();document[key]=value;self.write(document)
            with self.assertRaises(CatalogError): load_pack(self.pack/'pack.ini')

    def test_workflow_file_coverage_cardinality_and_ids_are_strict(self):
        changes=[lambda d:d['workflows'].clear(),
                 lambda d:d['workflows']['filter']['ports'].clear(),
                 lambda d:d['workflows']['filter']['outputs'].pop(),
                 lambda d:d['workflows']['filter']['ports'][0].update(max=2),
                 lambda d:d['workflows']['filter']['ports'][0].update(manifestInputs=['minimum']),
                 lambda d:d['workflows']['filter']['ports'][0].update(accepts=['unknown']),
                 lambda d:d['workflows']['filter']['ports'][0].update(requiredState={'unchecked':'anything'}),
                 lambda d:d['workflows']['filter']['outputs'][0].update(manifestOutputs=['filtered','filtered'])]
        for change in changes:
            document=metadata();change(document);self.write(document)
            with self.assertRaises(CatalogError): load_pack(self.pack/'pack.ini')

    def test_sequence_compression_and_abundance_declarations_are_consistent(self):
        document=metadata();document['workflows']['filter']['outputs'][0]['state']['compression']='gzip';self.write(document)
        with self.assertRaises(CatalogError): load_pack(self.pack/'pack.ini')
        document=metadata();document['workflows']['filter']['outputs'][0]['type']='fasta-nucleotide-abundance';self.write(document)
        with self.assertRaises(CatalogError): load_pack(self.pack/'pack.ini')
        document['workflows']['filter']['outputs'][0]['state']['abundance']=True;self.write(document)
        self.assertEqual(load_catalog(self.root)['tools']['example/filter']['outputs'][0]['type'],'fasta-nucleotide-abundance')

    def test_plain_fasta_extension_does_not_become_genomic_reference(self):
        self.assertEqual(_output_type({'id':'sequences','path':'sequences.fa'}),'file')
        self.assertEqual(_output_type({'id':'reference','path':'reference.fa'}),'reference')

    def test_full_alphabet_validation_reads_beyond_signature_window(self):
        with self.assertRaisesRegex(ValueError,'Unexpected characters'):
            self.evidence('>one\n'+'ACGT\n'*1100+'MPEPTIDE\n')
        self.assertEqual(self.evidence('>one\nMPEPTIDE\n','fasta-protein')['records'],1)
        with self.assertRaises(ValueError): self.evidence('>one\nAC-GT\n')

    def test_msa_columns_and_alphabets_are_separate_from_unaligned_fasta(self):
        result=self.evidence('>a\nAC-GT\n>b\nA-CGT\n','msa-nucleotide')
        self.assertEqual(result['columns'],5)
        with self.assertRaisesRegex(ValueError,'column counts'):
            self.evidence('>a\nAC-GT\n>b\nACGT\n','msa-nucleotide')
        with self.assertRaisesRegex(ValueError,'Unexpected characters'):
            self.evidence('>a\nMPEPTIDE\n>b\nMP-PTIDE\n','msa-nucleotide')

    def test_abundance_headers_required_counted_and_not_duplicated(self):
        result=self.evidence('>a;size=4;\nACGT\n>b;size=2;\nAAAA\n','fasta-nucleotide-abundance')
        self.assertEqual(result['abundanceTotal'],6)
        for header in ('a','a;size=0;','a;size=3;size=5;'):
            with self.assertRaises(ValueError): self.evidence('>'+header+'\nACGT\n','fasta-nucleotide-abundance')

    def test_cumulative_abundance_cannot_overflow_downstream_counts(self):
        maximum=9223372036854775807
        self.assertEqual(self.evidence(f'>a;size={maximum};\nACGT\n','fasta-nucleotide-abundance')['abundanceTotal'],maximum)
        with self.assertRaisesRegex(ValueError,'Total FASTA abundance'):
            self.evidence(f'>a;size={maximum};\nACGT\n>b;size=1;\nAAAA\n','fasta-nucleotide-abundance')

    def test_empty_output_allowed_but_empty_sequence_input_rejected(self):
        self.assertEqual(self.evidence('',allow_empty=True)['records'],0)
        with self.assertRaisesRegex(ValueError,'No sequence records'): self.evidence('')

    def test_muscle_style_explicit_input_limits_unique_ids_and_cancel(self):
        rules={'minRecords':2,'maxLength':5,'uniqueIds':True}
        document=metadata();document['workflows']['filter']['ports'][0]['validation']=rules;self.write(document)
        self.assertEqual(load_catalog(self.root)['tools']['example/filter']['ports'][0]['validation'],rules)
        for text in ('>a\nACGT\n','>a\nACGT\n>a\nAAAA\n','>a\nACGTAC\n>b\nAAAA\n'):
            with self.assertRaises(ValueError): self.evidence(text,rules=rules)
        self.assertEqual(self.evidence('>a\nACGT\n>b\nAAAA\n',rules=rules)['records'],2)
        self.cancel.set()
        with self.assertRaises(InterruptedError): self.evidence('>a\nACGT\n')

    def test_methods_are_future_then_completed_and_only_include_relevant_citations(self):
        engine=Engine(self.root,load_catalog(self.root))
        graph={'name':'Example','nodes':[{'id':'step-1','tool':'example/filter','params':{'minimum':'20'},'inputs':{'sequences':['input-1']}}],
               'sources':[{'id':'input-1','type':'fasta-nucleotide','label':'Nucleotide sequences','files':{'sequences':str(self.fasta('>one\nACGT\n'))}}]}
        planned=engine.methods(graph)
        self.assertIn('will be performed',planned)
        self.assertIn('Minimum length=20',planned)
        self.assertIn('Example authors.',planned)
        failed=engine.methods(graph,completed=True,statuses={'step-1':'failed'})
        self.assertNotIn('Example authors.',failed)
        completed=engine.methods(graph,completed=True,statuses={'step-1':'success'})
        self.assertIn('was performed',completed)

    def test_fasta_abundance_sort_state_does_not_invoke_samtools(self):
        catalog=load_catalog(self.root);engine=Engine(self.root,catalog)
        node={'tool':copy.deepcopy(catalog['tools']['example/filter'])}
        node['tool']['ports'][0]['requiredState']={'sort':'abundance'}
        path=self.fasta('>a;size=4;\nACGT\n')
        result=engine._preflight(node,{'sequences':str(path),'minimum':'10'},self.cancel)
        self.assertIn('sequenceChecks',result)

    def test_actual_producer_alignment_type_is_retained_for_multi_type_consumer(self):
        catalog=load_catalog(self.root);engine=Engine(self.root,catalog)
        node={'tool':copy.deepcopy(catalog['tools']['example/filter'])}
        node['tool']['ports'][0].update(type='reads',accepts=['reads','fasta-nucleotide','msa-nucleotide'])
        path=self.fasta('>a\nAC-GT\n>b\nA-CGT\n')
        result=engine._preflight(node,{'sequences':str(path),'minimum':'10'},self.cancel,{str(path.resolve()):'msa-nucleotide'})
        self.assertEqual(result['sequenceChecks'][0]['type'],'msa-nucleotide')
        self.assertEqual(result['sequenceChecks'][0]['columns'],5)

    def test_reject_abundance_is_per_workflow_and_abundance_sort_is_verified(self):
        text='>a;size=4;\nACGT\n'
        self.assertEqual(self.evidence(text)['records'],1)
        with self.assertRaisesRegex(ValueError,'abundance-aware'):
            self.evidence(text,rules={'rejectAbundance':True})
        with self.assertRaisesRegex(ValueError,'highest to lowest'):
            self.evidence('>a;size=2;\nACGT\n>b;size=4;\nAAAA\n','fasta-nucleotide-abundance',state={'sort':'abundance'})

    def test_plain_gzip_cannot_claim_bgzf(self):
        path=self.root/'seq.fa.gz'
        with gzip.open(path,'wb') as stream: stream.write(b'>a\nACGT\n')
        with self.assertRaisesRegex(ValueError,'BGZF'):
            _sequence_evidence(path,'fasta-nucleotide',['fasta-nucleotide'],{'compression':'bgzf'},self.cancel)


if __name__=='__main__':
    unittest.main(verbosity=2)
