#!/usr/bin/env python3
"""Scientific/failure regressions against a prepared exact Bracken pack.

The actual Kraken2 chain additionally requires its frozen release ZIP. Linux
uses host Python for source execution and makes no native Windows claim.
"""
import argparse
import copy
import configparser
import csv
from fractions import Fraction
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile
import unittest
from unittest import mock
import zipfile

# Contract tests import the adapter for controlled validation-race injection.
# Keep that developer-side import as read-only as the pack's -B execution path.
sys.dont_write_bytecode = True

ROOT = Path(__file__).resolve().parents[1]
PACK = None
KRAKEN_ARCHIVE = None
KRAKEN_LINUX_BINARY = None


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def write(path, value):
    Path(path).write_bytes((json.dumps(value, indent=2) + '\n').encode('utf-8'))


def inventory(path):
    return {p.relative_to(path).as_posix():sha(p) for p in path.rglob('*') if p.is_file()}


class BrackenTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if PACK is None:
            raise unittest.SkipTest('Use --pack for exact packaged upstream scientific tests')
        cls.pack = PACK.resolve()
        cls.before = inventory(cls.pack)
        cls.python = cls.pack/'bin/python.exe' if os.name == 'nt' else Path(sys.executable)
        cls.adapter = cls.pack/'adapter.py'
        temporary_parent=Path(os.environ.get('NW_BRACKEN_TEMP_DIR',str(ROOT/'build/bracken-test-temp'))).resolve()
        temporary_parent.mkdir(parents=True,exist_ok=True)
        cls.temp = tempfile.TemporaryDirectory(prefix='Bracken scientific paths ',dir=temporary_parent)
        cls.base = Path(cls.temp.name)
        cls.kraken = None
        if KRAKEN_ARCHIVE:
            target = cls.base/'Kraken dependency with spaces'
            with zipfile.ZipFile(KRAKEN_ARCHIVE) as archive:
                for item in archive.infolist():
                    if not item.filename.startswith('pack/'):
                        continue
                    relative=Path(item.filename.removeprefix('pack/'))
                    if relative.is_absolute() or '..' in relative.parts:
                        raise ValueError('Unsafe dependency archive path')
                    if item.is_dir():
                        continue
                    destination=target/relative
                    destination.parent.mkdir(parents=True,exist_ok=True)
                    with archive.open(item) as source,destination.open('wb') as output:
                        shutil.copyfileobj(source,output)
            cls.kraken=target

    @classmethod
    def tearDownClass(cls):
        if inventory(cls.pack) != cls.before:
            raise AssertionError('Scientific checks modified the installed Bracken pack')
        cls.temp.cleanup()

    def setUp(self):
        self.root=self.base/self._testMethodName
        self.root.mkdir()
        self.fixture=self.root/'local inputs with spaces'
        shutil.copytree(self.pack/'fixtures',self.fixture)
        self.before_fixture=inventory(self.fixture)
        self.n=0

    def run_tool(self, mode='estimate-external', expected=0, **kwargs):
        self.n+=1
        run=self.root/('results with spaces '+str(self.n))
        if mode=='estimate':
            values={'database':self.fixture/'database.json','classification':self.fixture/'classification.json','read-length':150,'level':'S','threshold':0,'length-policy':'exact'}
        else:
            values={'report':self.fixture/'manual.report.tsv','distribution':self.fixture/'manual150mers.kmer_distrib','database-label':'Synthetic truth model','database-release':'manual2026-10-04','external-confirmation':'confirmed','external-unit':'reads','read-length':150,'level':'S','threshold':0}
        values.update(kwargs)
        command=[str(self.python),'-I','-B','-X','utf8',str(self.adapter),'--mode',mode,'--run',str(run)]
        for key,value in values.items():
            if value is not None:
                command += ['--'+key,str(value)]
        result=subprocess.run(command,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,encoding='utf-8')
        if expected==0:
            self.assertEqual(result.returncode,0,result.stdout)
        else:
            self.assertNotEqual(result.returncode,0,result.stdout)
            self.assertIn(expected,result.stdout)
            self.assertFalse((run/'bracken-provenance.json').exists(),'Failed run was labelled successful')
        return run,result.stdout

    def table(self,run):
        with (run/'bracken.abundance.tsv').open(encoding='utf-8',newline='') as stream:
            return {row['taxonomy_id']:row for row in csv.DictReader(stream,delimiter='\t')}

    def test_01_independent_bayesian_truth_and_denominator(self):
        run,_=self.run_tool()
        table=self.table(run)
        # Independently calculated exact rational Bayes weights, not copied
        # from Bracken output or an implementation-shaped mock estimator.
        alpha_weight=Fraction(30,1)/Fraction(80,100)*Fraction(20,100)
        beta_weight=Fraction(20,1)/Fraction(60,100)*Fraction(40,100)
        expected={'101':int(30+20*alpha_weight/(alpha_weight+beta_weight)),
                  '102':int(20+20*beta_weight/(alpha_weight+beta_weight)),'201':20}
        self.assertEqual(expected,{'101':37,'102':32,'201':20})
        self.assertEqual({k:int(v['new_est_reads']) for k,v in table.items()},expected)
        self.assertEqual(table['101']['fraction_total_reads'],'0.41111')
        self.assertEqual(table['102']['fraction_total_reads'],'0.35556')
        record=read(run/'bracken-provenance.json')
        self.assertEqual(record['sumOfTruncatedEstimatedCounts'],89)
        self.assertEqual(record['totalInputObservations'],100)
        self.assertEqual(record['unclassifiedInputObservations'],10)
        self.assertEqual(record['identityScope'],'user-declared-external-report-unverified')

    def test_02_genus_and_threshold_are_real_upstream_choices(self):
        run,_=self.run_tool(level='G')
        self.assertEqual({k:int(v['new_est_reads']) for k,v in self.table(run).items()},{'10':70,'20':20})
        run,_=self.run_tool(threshold=25)
        table=self.table(run)
        self.assertEqual(set(table),{'101'})
        self.assertEqual(int(table['101']['new_est_reads']),50)
        self.assertEqual(table['101']['fraction_total_reads'],'1.00000')

    def test_03_record_bound_real_kraken_fixture_truth(self):
        run,_=self.run_tool('estimate')
        self.assertEqual({k:int(v['new_est_reads']) for k,v in self.table(run).items()},{'101':14,'102':9,'201':5})
        record=read(run/'bracken-provenance.json')
        self.assertEqual(record['identityScope'],'hash-bound-workbench-classification')
        self.assertEqual(record['distribution']['association'],'locally-built')
        self.assertFalse(record['databaseBinaryFilesReadByBracken'])
        self.assertEqual(record['totalInputObservations'],32)
        self.assertFalse((self.fixture/'hash.k2d').exists(),'Bracken should not need unused index binaries')

    def test_04_changed_report_and_database_identity_fail(self):
        report=self.fixture/'expected.report.tsv'
        report.write_bytes(report.read_bytes()+b'\n')
        self.run_tool('estimate',expected='Resource size changed')
        shutil.copyfile(self.pack/'fixtures/expected.report.tsv',report)
        record=read(self.fixture/'classification.json');record['databaseFingerprint']='0'*64
        write(self.fixture/'classification.json',record)
        self.run_tool('estimate',expected='different Kraken2 database fingerprints')

    def test_05_changed_distribution_read_length_and_model_fail(self):
        path=self.fixture/'database150mers.kmer_distrib'
        path.write_bytes(path.read_bytes()+b'\n')
        self.run_tool('estimate',expected='Resource size changed')
        shutil.copyfile(self.pack/'fixtures/database150mers.kmer_distrib',path)
        self.run_tool('estimate',expected='No registered Bracken distribution',**{'read-length':151})
        resource=read(self.fixture/'database.json');resource['brackenDistributions'][0]['classifierSettings']['confidence']=0.1
        write(self.fixture/'database.json',resource)
        self.run_tool('estimate',expected='distribution registered for standard Kraken2')
        resource=read(self.fixture/'database.json');resource['brackenDistributions'][0]['databaseFingerprint']='0'*64
        write(self.fixture/'database.json',resource)
        self.run_tool('estimate',expected='another database fingerprint')

    def test_06_variable_lengths_need_explicit_approximation(self):
        record=read(self.fixture/'classification.json')
        record['reads']['mate1']['minLength']=140
        record['reads']['mate1']['maxLength']=160
        write(self.fixture/'classification.json',record)
        self.run_tool('estimate',expected='do not exactly match')
        run,_=self.run_tool('estimate',**{'length-policy':'representative'})
        self.assertEqual(read(run/'bracken-provenance.json')['readLengthPolicy'],'representative')
        self.assertIn('approximation',(run/'bracken-methods.txt').read_text())
        record['reads']['mate1'].update(minLength=151,maxLength=160,bases=32*155)
        record['reads']['bases']=32*155
        write(self.fixture/'classification.json',record)
        self.run_tool('estimate',expected='within the observed',**{'length-policy':'representative'})

    def test_07_nonstandard_classifier_settings_rejected(self):
        original=read(self.fixture/'classification.json')
        for key,value in [('confidence',0.2),('minimumHitGroups',1),('minimumBaseQuality',20),('quick',True)]:
            record=copy.deepcopy(original);record['classifier'][key]=value
            write(self.fixture/'classification.json',record)
            self.run_tool('estimate',expected='standard Kraken2 classification')

    def test_08_pair_counts_are_fragments_not_doubled(self):
        record=read(self.fixture/'classification.json')
        record['reads'].update(paired=True,unit='fragments',reads=64,bases=9600,mate2=copy.deepcopy(record['reads']['mate1']))
        write(self.fixture/'classification.json',record)
        run,_=self.run_tool('estimate')
        result=read(run/'bracken-provenance.json')
        self.assertEqual(result['observationUnit'],'fragments')
        self.assertEqual(result['totalInputObservations'],32)
        self.assertEqual(result['sumOfTruncatedEstimatedCounts'],28)

    def test_09_malformed_reports_fail_before_estimation(self):
        original=(self.fixture/'manual.report.tsv').read_text()
        variants=[('C\tr\t101\t150\t101:116\n','six-column'),
                  ('k__Bacteria|s__Example\t100\n','six-column'),
                  (original.replace('30\t30\tS','30\t-1\tS'),'nonnegative integers'),
                  (original.replace('      Synthetic alpha','          Synthetic alpha'),'skips a level'),
                  (original.replace('70\t20\tG','71\t20\tG'),'clade counts'),
                  (original.replace('30.00\t30','31.00\t30'),'percentages'),
                  (original.replace('\t102\t','\t101\t'),'Duplicate taxonomy'),
                  (original.replace('Synthetic alpha','Synthetic\x00alpha'),'Invalid rank')]
        for text,message in variants:
            (self.fixture/'manual.report.tsv').write_text(text)
            self.run_tool(expected=message)

    def test_10_invalid_distribution_probabilities_rejected(self):
        original=(self.fixture/'manual150mers.kmer_distrib').read_text()
        for text,message in [
            (original.replace('101:80:100','101:80:0'),'genome counts'),
            (original.replace('101:80:100','101:80:101'),'denominator'),
            (original.replace('101:80:100','101:79:100'),'complete genome windows'),
            (original.replace('101:80:100','101:80:100 101:1:100'),'genome counts')]:
            (self.fixture/'manual150mers.kmer_distrib').write_text(text)
            self.run_tool(expected=message)

    def test_11_external_confirmation_and_source_identity_required(self):
        self.run_tool(expected='explicit confirmation',**{'external-confirmation':'unconfirmed'})
        self.run_tool(expected='nonempty database label',**{'database-label':''})
        run,_=self.run_tool(**{'external-unit':'fragments'})
        record=read(run/'bracken-provenance.json')
        self.assertIsNone(record['databaseFingerprint'])
        self.assertEqual(record['observationUnit'],'fragments')
        self.assertEqual(record['distribution']['databaseRelease'],'manual2026-10-04')

    def test_12_no_estimate_outcomes_preserve_upstream_failure(self):
        self.run_tool(expected='No classified taxa',threshold=1000)
        (self.fixture/'manual.report.tsv').write_text('100.00\t100\t100\tU\t0\tunclassified\n')
        self.run_tool(expected='No classified taxa')
        (self.fixture/'manual.report.tsv').write_text('')
        self.run_tool(expected='report is empty')

    def test_13_spaces_unicode_crlf_and_input_immutability(self):
        report=self.fixture/'microbe caf\u00e9 report.tsv'
        report.write_bytes((self.fixture/'manual.report.tsv').read_bytes().replace(b'\n',b'\r\n'))
        before=inventory(self.fixture)
        run,_=self.run_tool(report=report)
        self.assertEqual(inventory(self.fixture),before)
        self.assertEqual(int(self.table(run)['101']['new_est_reads']),37)
        self.assertNotIn(b'\r\r\n',(run/'bracken-provenance.json').read_bytes())
        self.assertIn('user-declared',(run/'bracken-methods.txt').read_text())

    def test_14_byte_identical_upstream_and_direct_oracle(self):
        upstream=self.pack/'upstream/est_abundance.py'
        self.assertEqual(sha(upstream),'c311cb56921b92c807ea28710c98349c725f27b7cee2b20e2e343c50e2981cca')
        for level in ['S','G']:
            run,_=self.run_tool(level=level)
            oracle=self.root/('direct upstream '+level);oracle.mkdir()
            result=subprocess.run([str(self.python),'-I','-B','-X','utf8',str(upstream),'-i',str(self.fixture/'manual.report.tsv'),'-k',str(self.fixture/'manual150mers.kmer_distrib'),'-o',str(oracle/'abundance.tsv'),'--out-report',str(oracle/'report.tsv'),'-l',level,'-t','0'],stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True)
            self.assertEqual(result.returncode,0,result.stdout)
            self.assertEqual((run/'bracken.abundance.tsv').read_bytes(),(oracle/'abundance.tsv').read_bytes())
            self.assertEqual((run/'bracken.report.tsv').read_bytes(),(oracle/'report.tsv').read_bytes())

    def test_15_actual_kraken_to_bracken_species_genus_and_pairs(self):
        if self.kraken is None:
            self.skipTest('Actual Kraken2 chain requires --kraken2-archive; not validated by captured fixture')
        if os.name!='nt' and not KRAKEN_LINUX_BINARY:
            self.skipTest('Windows dependency requires native Windows or explicit Linux reference override')
        runtime=self.kraken/'bin/python.exe' if os.name=='nt' else Path(sys.executable)
        fixtures=self.kraken/'fixtures'
        for paired in (False,True):
            krun=self.root/('real paired Kraken result' if paired else 'real single Kraken result')
            command=[str(runtime),'-I','-B','-X','utf8',str(self.kraken/'adapter.py'),'classify','--database',str(fixtures/'database-resource.json'),'--reads',str(fixtures/('reads_1.fastq.gz' if paired else 'reads.fastq.gz')),'--run',str(krun),'--threads','2','--confidence','0','--minimum-hit-groups','2','--minimum-base-quality','0','--memory','mapped']
            if paired:command += ['--reads2',str(fixtures/'reads_2.fastq.gz')]
            if os.name!='nt':command += ['--binary',str(KRAKEN_LINUX_BINARY)]
            result=subprocess.run(command,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,encoding='utf-8')
            self.assertEqual(result.returncode,0,result.stdout)
            for level,expected in [('S',{'101':14,'102':9,'201':5}),('G',{'10':24,'20':5})]:
                run,_=self.run_tool('estimate',classification=krun/'classification-record.json',database=fixtures/'database-resource.json',level=level)
                self.assertEqual({k:int(v['new_est_reads']) for k,v in self.table(run).items()},expected)
                provenance=read(run/'bracken-provenance.json')
                self.assertEqual(provenance['observationUnit'],'fragments' if paired else 'reads')
                self.assertEqual(provenance['totalInputObservations'],32)

    def test_16_real_upstream_distribution_generator_unclassified_and_contigs(self):
        archive_path=self.pack/'licenses/Bracken-v3.1.tar.gz'
        with tarfile.open(archive_path) as archive:
            generator=self.root/'generate_kmer_distribution.py'
            generator.write_bytes(archive.extractfile('Bracken-3.1/src/generate_kmer_distribution.py').read())
            official=self.root/'official-example-distribution.txt'
            official.write_bytes(archive.extractfile('Bracken-3.1/sample_data/sample_kmer_distr_75mers.txt').read())
        counts=self.root/'two-contigs-per-genome.tsv'
        counts.write_text('contigA\t101\t50\t10:10 101:40\ncontigB\t101\t50\t10:10 101:35 0:5\ncontigC\t102\t100\t10:40 102:60\ncontigD\t201\t100\t201:100\n')
        distribution=self.root/'generated150.kmer_distrib'
        result=subprocess.run([str(self.python),'-I','-B',str(generator),'-i',str(counts),'-o',str(distribution)],stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True)
        self.assertEqual(result.returncode,0,result.stdout)
        self.assertIn('101:75:100',distribution.read_text())
        self.assertIn('0\t101:5:100',distribution.read_text())
        # Actual unchanged upstream example and generator output, including
        # unclassified windows and multiple sequences aggregated per genome,
        # both satisfy the complete-denominator contract.
        code=('import importlib.util,sys; '
              's=importlib.util.spec_from_file_location("bracken_pack_adapter",sys.argv[1]); '
              'm=importlib.util.module_from_spec(s);s.loader.exec_module(m); '
              'print(m.validate_distribution(sys.argv[2]));print(m.validate_distribution(sys.argv[3]))')
        result=subprocess.run([str(self.python),'-I','-B','-c',code,str(self.adapter),str(distribution),str(official)],stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True)
        self.assertEqual(result.returncode,0,result.stdout)
        self.assertIn("'genomes': 3",result.stdout)

    def test_17_changed_input_between_validation_and_baseline_is_rejected(self):
        spec=importlib.util.spec_from_file_location('bracken_pack_race',self.adapter)
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        for kind in ['resource','report','distribution','classification']:
            shutil.copytree(self.pack/'fixtures',self.fixture,dirs_exist_ok=True)
            args=argparse.Namespace(mode='estimate',run=self.root/('race '+kind),database=self.fixture/'database.json',classification=self.fixture/'classification.json',level='S',threshold=0,read_length=150,length_policy='exact')
            original=module.validate_classification
            def mutate_after_validation(path,resource,kind=kind):
                result=original(path,resource)
                selected={'resource':self.fixture/'database.json','report':self.fixture/'expected.report.tsv','distribution':self.fixture/'database150mers.kmer_distrib','classification':self.fixture/'classification.json'}[kind]
                selected.write_bytes(selected.read_bytes()+b'\n')
                return result
            with mock.patch.object(module,'validate_classification',mutate_after_validation):
                with self.assertRaisesRegex(ValueError,'changed during input validation'):
                    module.execute(args)
            self.assertFalse((Path(args.run)/'bracken-upstream.log').exists(),'A changed resource reached scientific execution')
        self.run_tool(expected='not an ordinary file',report=self.fixture)


def main():
    global PACK,KRAKEN_ARCHIVE,KRAKEN_LINUX_BINARY
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pack',type=Path,required=True)
    parser.add_argument('--kraken2-archive',type=Path)
    parser.add_argument('--kraken2-linux-binary',type=Path)
    parser.add_argument('--report',type=Path,required=True)
    args=parser.parse_args()
    PACK=args.pack;KRAKEN_ARCHIVE=args.kraken2_archive;KRAKEN_LINUX_BINARY=args.kraken2_linux_binary
    suite=unittest.defaultTestLoader.loadTestsFromTestCase(BrackenTests)
    result=unittest.TextTestRunner(verbosity=2).run(suite)
    manifest=configparser.ConfigParser(interpolation=None);manifest.read(PACK/'pack.ini',encoding='utf-8')
    record={'schema':1,'pack':'bracken','packVersion':manifest['pack']['version'],'upstreamVersion':'3.1','nativeWindowsHost':os.name=='nt','nativeWindowsExecuted':os.name=='nt',
        'packDirectory':str(PACK.resolve()),'manifestSha256':sha(PACK/'pack.ini'),'upstreamEstimatorSha256':sha(PACK/'upstream/est_abundance.py'),
        'kraken2Archive':{'path':str(KRAKEN_ARCHIVE.resolve()),'sha256':sha(KRAKEN_ARCHIVE)} if KRAKEN_ARCHIVE else None,
        'actualKrakenChainExecuted':KRAKEN_ARCHIVE is not None and (os.name=='nt' or KRAKEN_LINUX_BINARY is not None),
        'testsRun':result.testsRun,'passed':result.testsRun-len(result.failures)-len(result.errors)-len(result.skipped),
        'failures':[{'test':str(test),'detail':detail} for test,detail in result.failures],
        'errors':[{'test':str(test),'detail':detail} for test,detail in result.errors],
        'skipped':[{'test':str(test),'reason':reason} for test,reason in result.skipped],
        'success':result.wasSuccessful() and not result.skipped,
        'scope':'Packaged unchanged upstream estimator with independent hand-calculated Bayesian truth, real captured Kraken fixture, explicit provenance/length/format/setting guards, input and pack immutability. Actual full Kraken chain is separately recorded. No GUI, performance, clinical or network-isolation claim.'}
    args.report.parent.mkdir(parents=True,exist_ok=True);write(args.report,record)
    print(json.dumps(record,indent=2))
    return 0 if record['success'] else 1


if __name__=='__main__':
    raise SystemExit(main())
