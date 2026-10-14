"""Scientific CLI checks for the exact MUSCLE5.3-workbench1 source build.

These execute Linux reference binaries. Windows acceptance is performed by the
four pack-owned installation checks, not inferred from Linux execution.
"""
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest

ROOT=Path(__file__).resolve().parents[1]
CACHE=ROOT/'vendor-expanded/muscle-5.3'
PACK=ROOT/'packs/muscle-0.5.2'
BINARY=CACHE/'build-linux/muscle'
OFFICIAL=CACHE/'muscle-linux-x86.v5.3'
sys.path.insert(0,str(ROOT/'workspace'))
from catalog import load_pack, describe_workflow
from engine import _sequence_evidence


def records(path):
    result={}
    identity=None
    for line in path.read_text().splitlines():
        if line.startswith('>'):
            identity=line[1:].split()[0]
            if identity in result: raise ValueError('Duplicate ID')
            result[identity]=''
        elif line.strip(): result[identity]+=line.strip()
    return result


class MusclePackTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pack=load_pack(PACK/'pack.ini')
        if not BINARY.exists(): raise RuntimeError('Build the patched Linux reference first')

    def run_alignment(self,mode,alphabet,input_path,output_path,binary=BINARY,seed=0):
        command=[str(binary),'-'+mode,str(input_path),'-output',str(output_path),'-nt' if alphabet=='nucleotide' else '-amino','-threads','1','-perturb',str(seed),'-perm','none']
        result=subprocess.run(command,capture_output=True,text=True,timeout=30)
        self.assertEqual(result.returncode,0,result.stderr)
        return result,records(output_path)

    def test_integrity_and_typed_workflows(self):
        self.assertEqual(len(self.pack['workflows']),4)
        for group in ('tools','assets'):
            for asset in self.pack[group].values():
                self.assertEqual(hashlib.sha256((PACK/asset['path']).read_bytes()).hexdigest(),asset['sha256'])
        for identity,workflow in self.pack['workflows'].items():
            alphabet=identity.split('-')[1]
            tool=describe_workflow(self.pack,workflow,'packs/muscle-0.5.2',self.pack['manifestSha256'])
            self.assertEqual(tool['ports'][0]['accepts'],['fasta-'+alphabet])
            self.assertEqual(tool['outputs'][0]['type'],'msa-'+alphabet)
            self.assertEqual(tool['ports'][0]['validation']['maxLength'],15000)
            self.assertEqual(tool['executables'][0]['version'],'5.3-workbench1')
        relative=[str(p.relative_to(PACK)) for p in PACK.rglob('*')]
        self.assertLess(max(map(len,relative)),140)

    def test_normal_alignments_and_official_regression(self):
        with tempfile.TemporaryDirectory(prefix='muscle scientific spaces ') as temp:
            dest=Path(temp)
            for mode in ('align','super5'):
                for alphabet in ('nucleotide','protein'):
                    with self.subTest(mode=mode,alphabet=alphabet):
                        source=PACK/'fixtures'/(alphabet+'.fa')
                        result,aligned=self.run_alignment(mode,alphabet,source,dest/f'{mode}-{alphabet}.afa')
                        self.assertIn('Workbench alphabet: '+('nucleotide' if alphabet=='nucleotide' else 'amino-acid'),result.stderr)
                        self.assertNotIn('not used',result.stderr)
                        self.assertEqual({key:value.replace('-','') for key,value in aligned.items()},records(source))
                        self.assertEqual(len({len(value) for value in aligned.values()}),1)
                        if OFFICIAL.is_file():
                            _,old=self.run_alignment(mode,alphabet,source,dest/f'official-{mode}-{alphabet}.afa',OFFICIAL)
                            self.assertEqual(aligned,old)

    def test_ambiguous_protein_alphabet_is_explicit(self):
        with tempfile.TemporaryDirectory() as temp:
            dest=Path(temp)
            source=dest/'acgt-only-protein.fa'
            source.write_text('>p1\nACGTACGTACGTTACGT\n>p2\nACGTTCGTACGACGT\n>p3\nACGTACGTTCGTTACGT\n')
            for mode in ('align','super5'):
                for alphabet,expected in (('protein','amino-acid'),('nucleotide','nucleotide')):
                    result,aligned=self.run_alignment(mode,alphabet,source,dest/(mode+alphabet+'.afa'))
                    self.assertIn('Workbench alphabet: '+expected,result.stderr)
                    self.assertNotIn('not used',result.stderr)
                    self.assertEqual({key:value.replace('-','') for key,value in aligned.items()},records(source))

    def test_repeated_seed_and_stop_symbols(self):
        with tempfile.TemporaryDirectory() as temp:
            dest=Path(temp)
            source=dest/'stops.fa'
            source.write_text('>a\nMKTAYIAKQRQISFVKSHF*RQDILDLWQ*\n>b\nMKTAYIAKQRQISFVKSHFNRQDILDLWQ*\n>c\nMKTAYIAKQRQISFVKSHFSRQDILWQ*\n')
            for mode in ('align','super5'):
                _,a=self.run_alignment(mode,'protein',source,dest/(mode+'-a.afa'),seed=7)
                _,b=self.run_alignment(mode,'protein',source,dest/(mode+'-b.afa'),seed=7)
                self.assertEqual(a,b)
                self.assertEqual({key:value.replace('-','') for key,value in a.items()},records(source))

    def test_rna_retains_uracil(self):
        with tempfile.TemporaryDirectory() as temp:
            dest=Path(temp)
            source=dest/'rna.fa'
            source.write_text('>r1\nACGUACGUACGUACGU\n>r2\nACGUACGACGUACGU\n>r3\nACGUACGUUCGUACGU\n')
            for mode in ('align','super5'):
                _,aligned=self.run_alignment(mode,'nucleotide',source,dest/(mode+'.afa'))
                self.assertEqual({key:value.replace('-','') for key,value in aligned.items()},records(source))

    def test_pack_constraints_before_execution(self):
        port=self.pack['workbenchSchema']['align-nucleotide']['ports'][0]
        invalid={'empty':'','one':'>a\nACGT\n','duplicate':'>a x\nACGT\n>a y\nACGT\n','gapped':'>a\nAC-GT\n>b\nACGT\n','protein':'>a\nMPEPTIDE\n>b\nMPEPTIDE\n','long':'>a\n'+'A'*15001+'\n>b\nACGT\n'}
        with tempfile.TemporaryDirectory() as temp:
            for name,content in invalid.items():
                path=Path(temp)/(name+'.fa');path.write_text(content)
                with self.subTest(name=name),self.assertRaises(ValueError):
                    _sequence_evidence(path,'fasta-nucleotide',['fasta-nucleotide'],{'compression':'none'},threading.Event(),rules=port['validation'])

    def test_no_unbundled_runtime_dependency(self):
        imports=json.loads((PACK/'licenses/windows-imports.json').read_text())
        self.assertIn('libomp.dll',imports['muscle.exe'])
        for binary,dependencies in imports.items():
            for dependency in dependencies:
                self.assertTrue(dependency.lower() in ('kernel32.dll','libomp.dll') or dependency.lower().startswith('api-ms-win-crt-'),(binary,dependency))
                self.assertNotEqual(dependency.upper(),'VCOMP140.DLL')

if __name__=='__main__': unittest.main()
