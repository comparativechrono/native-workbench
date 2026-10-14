#!/usr/bin/env python3
"""Assemble the MUSCLE 5.3-workbench1 format-2 pack from pinned public source.

Use --fetch to download the GPLv3 release source if absent; --build compiles the
Windows executable with the pinned LLVM-MinGW toolchain. Scientific validation
uses scripts/build_muscle_windows.py --linux and tests/test_muscle_pack.py.
"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT/'vendor-expanded/muscle-5.3'
PACK = ROOT/'packs/muscle-0.5.2'
TC = ROOT.parents[1]/'toolchains/llvm-mingw-20260922-ucrt-ubuntu-22.04-x86_64'
SOURCE_URL = 'https://codeload.github.com/rcedgar/muscle/tar.gz/refs/tags/v5.3'
SOURCE_SHA = '74b22a94e630b16015c2bd9ae83aa2be2c2048d3e41f560b2d4a954725c81968'
SOURCE_COMMIT = '2cf9d33078c9a85697e38a6f3ad827e6862420df'
GALAXY_URL = 'https://github.com/galaxyproject/tools-iuc/blob/147197a0b7e225c92b6cb18f392a8512fda080e0/deprecated/packages/package_muscle_3_8_31/tool_dependencies.xml'
CITATION = {'text':'Edgar RC (2022). High-accuracy alignment ensembles enable unbiased assessments of sequence homology and phylogeny. Nature Communications 13, 6968.', 'url':'https://doi.org/10.1038/s41467-022-34630-w'}
FIXTURES = {
 'nucleotide': {'dna_a':'ACGTTGCAACGTTGCAACGTTGCA','dna_b':'ACGTTGCAACGCTGCAACGTTGCA','dna_c':'ACGTTGCAACGTTGCAACGCA'},
 'protein': {'protein_a':'MKTAYIAKQRQISFVKSHFSRQDILDLWQ','protein_b':'MKTAYIAKQRQISFVKSHFNRQDILDLWQ','protein_c':'MKTAYIAKQRQISFVKSHFSRQDILWQ'},
}

def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def write_json(path,value):
    path.write_text(json.dumps(value,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--fetch',action='store_true')
    parser.add_argument('--build',action='store_true')
    args=parser.parse_args()
    CACHE.mkdir(parents=True,exist_ok=True)
    archive=CACHE/'muscle-v5.3.tar.gz'
    if not archive.exists() and args.fetch:
        archive.write_bytes(urllib.request.urlopen(SOURCE_URL,timeout=120).read())
    if not archive.is_file() or sha(archive)!=SOURCE_SHA:
        raise ValueError('Missing or changed MUSCLE v5.3 source archive; use --fetch')
    original=CACHE/'source/muscle-5.3'
    if not original.exists():
        with tarfile.open(archive) as t:
            for member in t.getmembers():
                if Path(member.name).is_absolute() or '..' in Path(member.name).parts or not (member.isfile() or member.isdir()):
                    raise ValueError('Unsafe source archive member')
            t.extractall(CACHE/'source',filter='data')
    if args.build:
        subprocess.run([sys.executable,str(ROOT/'scripts/build_muscle_windows.py')],check=True)
    for child in ('bin','fixtures','licenses'):
        (PACK/child).mkdir(parents=True,exist_ok=True)
    for name in ('muscle.exe','libomp.dll'):
        shutil.copy2(CACHE/'build-windows'/name,PACK/'bin'/name)
    for name,records in FIXTURES.items():
        (PACK/'fixtures'/f'{name}.fa').write_text(''.join('>'+identity+'\n'+sequence+'\n' for identity,sequence in records.items()))
    schema={'schema':1,'category':'Multiple sequence alignment','citations':[CITATION],'workflows':{}}
    checks={'schema':1,'checks':[]}
    sections=[('pack',{'format':'2','id':'muscle','version':'0.5.2','name':'MUSCLE multiple sequence alignment','platform':'windows-x86_64','description':'Align homologous nucleotide or protein sequences with MUSCLE 5.3-workbench1. Standard alignment and Super5; local execution.','color':'#687BB5'}),('tool:muscle',{'path':'bin/muscle.exe','version':'5.3-workbench1','sha256':sha(PACK/'bin/muscle.exe')})]
    for mode in ('align','super5'):
        for alphabet,flag in (('nucleotide','-nt'),('protein','-amino')):
            identity=mode+'-'+alphabet
            label=('Align' if mode=='align' else 'Align with Super5')+' '+alphabet+' sequences'
            description=('Standard high-accuracy alignment for modest sets of homologous sequences.' if mode=='align' else 'Super5 alignment for larger sets of homologous sequences; a single alignment, not an ensemble.')
            description+=' This pack allows 2 or more sequences, each at most 15,000 residues. Memory use is not capped; use Super5 if standard alignment becomes too expensive.'
            sections.append(('workflow:'+identity,{'name':label,'description':description,'inputs':'sequences,threads,perturb,permutation','outputs':'aligned','steps':'align'}))
            sections.append(('input:'+identity+':sequences',{'label':('Unaligned nucleotide FASTA' if alphabet=='nucleotide' else 'Unaligned protein FASTA'),'type':'file','required':'true','filter':'Uncompressed FASTA|*.fa;*.fasta;*.fna;*.faa|All files|*.*','help':'Choose homologous sequences, not whole genomes or reads. Uncompressed FASTA; at least 2 unique first-word IDs; no empty sequences or alignment gaps. Each sequence is limited to 15,000 residues by this pack. '+('DNA/RNA IUPAC letters are allowed; U is retained.' if alphabet=='nucleotide' else 'Standard/ambiguous amino-acid letters and stop (*) are allowed; stop symbols are retained.')+' Use ASCII-only installation, input and results paths on Windows; spaces are supported.'}))
            sections.append(('input:'+identity+':threads',{'label':'CPU threads','type':'integer','required':'true','default':'2','min':'1','max':'64','help':'Upper limit on parallel CPU workers. Choose 1 for reproducibility checks; more threads may change floating-point ordering. This is not a memory limit.'}))
            sections.append(('input:'+identity+':perturb',{'label':'Perturbation seed','type':'integer','required':'true','default':'0','min':'0','max':'2147483647','help':'0 disables HMM perturbation. Positive values choose one reproducible perturbation replicate. The selected value is recorded in methods and provenance.'}))
            sections.append(('input:'+identity+':permutation',{'label':'Guide-tree permutation','type':'choice','required':'true','default':'none','choices':'none:None|abc:ABC|acb:ACB|bca:BCA','help':'Choose one guide-tree permutation. Multiple-replicate ensembles are not produced by this operation.'}))
            sections.append(('output:'+identity+':aligned',{'label':'Aligned '+alphabet+' FASTA','path':'alignment.afa','final':'true','nonempty':'true'}))
            step={'label':label,'kind':'exec','tool':'muscle','produces':'aligned'}
            for index,arg in enumerate(['-'+mode,'{input:sequences}','-output','{output:aligned}',flag,'-threads','{input:threads}','-perturb','{input:perturb}','-perm','{input:permutation}']):
                step['arg.'+str(index)]=arg
            sections.append(('step:'+identity+':align',step))
            schema['workflows'][identity]={'ports':[{'id':'sequences','label':'Unaligned '+alphabet+' sequences','type':'fasta-'+alphabet,'accepts':['fasta-'+alphabet],'manifestInputs':['sequences'],'min':1,'max':1,'requiredState':{'compression':'none'},'validation':{'minRecords':2,'maxLength':15000,'uniqueIds':True}}], 'outputs':[{'id':'aligned','label':'Aligned '+alphabet+' FASTA','type':'msa-'+alphabet,'manifestOutputs':['aligned'],'state':{'compression':'none'}}], 'methods':'Homologous '+alphabet+' sequences were aligned with MUSCLE 5.3-workbench1 using '+('the standard -align algorithm' if mode=='align' else 'the Super5 algorithm')+' and an explicitly selected '+alphabet+' alphabet. One alignment replicate was produced; the recorded thread count, perturbation seed and guide-tree permutation define its settings.'}
            checks['checks'].append({'id':identity,'workflow':identity,'params':{'threads':'1','perturb':'0','permutation':'none'},'inputs':{'sequences':[{'sequences':'fixture-'+alphabet}]},'expect':[{'output':'aligned','kind':'fasta','records':3,'aligned':True,'ungapped':FIXTURES[alphabet]}]})
    write_json(PACK/'workbench-schema.json',schema)
    write_json(PACK/'workbench-checks.json',checks)
    for identity,relative in [('openmp','bin/libomp.dll'),('workbench-schema','workbench-schema.json'),('workbench-checks','workbench-checks.json'),('fixture-nucleotide','fixtures/nucleotide.fa'),('fixture-protein','fixtures/protein.fa')]:
        sections.insert(2,('asset:'+identity,{'path':relative,'sha256':sha(PACK/relative)}))
    (PACK/'pack.ini').write_text('\n\n'.join('['+name+']\n'+'\n'.join(key+'='+value for key,value in fields.items()) for name,fields in sections)+'\n',encoding='utf-8')
    notices=PACK/'licenses'
    for source,name in [(original/'LICENSE','MUSCLE-GPL-3.0.txt'),(archive,'muscle-v5.3.tar.gz'),(CACHE/'workbench1.patch','workbench1.patch'),(ROOT/'scripts/build_muscle_windows.py','build_muscle_windows.py'),(TC/'LICENSE.TXT','LLVM-LICENSE.txt'),(CACHE/'build-windows/build.json','windows-build.json'),(CACHE/'build-windows/imports.json','windows-imports.json')]:
        shutil.copy2(source,notices/name)
    for name in ('galaxy-legacy-dependency.xml','galaxy-LICENSE'):
        if (CACHE/name).exists(): shutil.copy2(CACHE/name,notices/name)
    for source in (TC/'x86_64-w64-mingw32/share/mingw32').glob('COPYING*'):
        if source.is_file(): shutil.copy2(source,notices/source.name)
    (notices/'MODIFICATIONS.txt').write_text('MUSCLE 5.3-workbench1, modified 2026-10-03 for Native Workbench.\nMUSCLE changes remain under GNU GPL version 3; the original GPL license and release source are retained.\nChanges: MinGW platform and 64-bit integer portability; explicit alphabet flags in -align; selected-alphabet logging and local build identifier. No scoring model or alignment algorithm replacement.\nThis is a local source build, not an official upstream binary. The exact applied patch is workbench1.patch.\n')
    provenance={'schema':1,'modifiedDate':'2026-10-03','tool':'MUSCLE','upstreamVersion':'5.3','distributedBuild':'5.3-workbench1','source':{'tag':'v5.3','commit':SOURCE_COMMIT,'url':SOURCE_URL,'sha256':SOURCE_SHA,'retained':'muscle-v5.3.tar.gz'},'patch':{'file':'workbench1.patch','sha256':sha(CACHE/'workbench1.patch'),'changes':['Use fixed-width 64-bit integer typedefs on LLP64 Windows.','Use Windows platform branches for MinGW in process, memory and file helpers while retaining MSVC-only debug/compiler guards.','Make -align honour existing -nt/-amino flags, consistent with -super5; report selected alphabet.','Record the actual source commit and workbench1 build identity.']},'windows':{'executableSha256':sha(PACK/'bin/muscle.exe'),'openmpSha256':sha(PACK/'bin/libomp.dll'),'toolchain':'llvm-mingw-20260922-ucrt-ubuntu-22.04-x86_64','toolchainUrl':'https://github.com/mstorsjo/llvm-mingw/releases/tag/20260922','imports':json.loads((CACHE/'build-windows/imports.json').read_text()),'executed':False,'pathLimitations':'The upstream narrow Windows filename APIs remain. Only ASCII installation/input/output paths are supported by this pack; spaces are covered by Linux argument tests. Native Windows and Unicode-path acceptance testing remains required.'},'galaxyGuidance':{'url':GALAXY_URL,'version':'MUSCLE 3.8.31 legacy dependency recipe','scope':'Tool-family selection and pinned binary/source provenance only. No current IUC tools/muscle wrapper exists at the recorded tree. MUSCLE5 options, behavior and tests come from MUSCLE5 upstream source/manual; this is not a port of MUSCLE3 CLI syntax.'},'upstreamManual':'https://drive5.com/muscle5/manual','citation':CITATION,'upstreamOfficialWindowsNotDistributed':{'sha256':'a86637db99deb3efa1cb6762c4e3160ca33644608270eb167e4214f1f9409711','reason':'Imports VCOMP140.DLL; replaced by the documented source build plus app-local LLVM OpenMP runtime.'},'license':'GPL-3.0; unmodified upstream license retained. LLVM/OpenMP/compiler runtime notices are separate.'}
    write_json(notices/'provenance.json',provenance)
    (PACK/'PACK-README.md').write_text('''# MUSCLE 5.3-workbench1\n\nFour local operations align homologous nucleotide or protein sequences, using either standard MUSCLE5 alignment or Super5. Each produces one aligned FASTA. Threads, perturbation seed and guide-tree permutation are explicit. Inputs are not references, reads, or already aligned FASTA.\n\nThis pack requires at least two nonempty sequences with unique first-word IDs, no gaps, and at most 15,000 residues per sequence. The 15,000-residue ceiling is a Workbench safeguard, not an upstream guarantee of suitability. MUSCLE has no enforced memory ceiling in these operations. Start with modest homologous sets; Super5 is preferable when standard alignment is too expensive. Thread count does not cap RAM. Protein stop symbols are retained. DNA and RNA IUPAC alphabets are accepted; this is sequence alignment, not RNA secondary-structure alignment.\n\nThe local build fixes an upstream issue where -align ignored -nt/-amino and guessed the alphabet. Both standard alignment and Super5 now honour explicit nucleotide/protein choice, including proteins containing only nucleotide-like letters. Scoring models and alignment algorithms remain upstream. The GPL source, applied patch and build script are in licenses/. Build from the complete Workbench source with `python3 scripts/prepare_muscle_pack.py --fetch --build`; the pinned LLVM-MinGW toolchain is required. For a Linux scientific reference build use `python3 scripts/build_muscle_windows.py --linux`.\n\nWindows portability: the executable has an app-local SHA-pinned libomp.dll and uses Windows/UCRT system DLLs. No separate Visual C++ redistributable is required. Use ASCII-only installation, input and results paths; upstream narrow filename APIs remain. Windows execution and Unicode paths were not tested in the Linux build environment. A Check installation action runs four real alignment fixtures and verifies sequence identities, residues and equal row lengths. Linux tests cover spaces in paths.\n\nGPLv3 licensing and exact upstream source are retained. This distribution makes no claim to be the upstream official Windows binary. The Galaxy IUC legacy MUSCLE3 recipe informed family selection and provenance practice; MUSCLE5 syntax and behavior were taken from upstream v5.3. Cite Edgar (2022), DOI 10.1038/s41467-022-34630-w.\n''')
    sys.path.insert(0,str(ROOT/'workspace'))
    from catalog import load_pack
    pack=load_pack(PACK/'pack.ini')
    print(json.dumps({'pack':str(PACK),'manifestSha256':sha(PACK/'pack.ini'),'workflows':list(pack['workflows']),'executableSha256':sha(PACK/'bin/muscle.exe')}))

if __name__=='__main__': main()
