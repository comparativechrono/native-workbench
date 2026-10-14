#!/usr/bin/env python3
"""Assemble the local LoFreq pack from pinned, validated build products; no network."""
import argparse, difflib, gzip, hashlib, io, json, random, shutil, subprocess, sys, tarfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];VENDOR=ROOT/'vendor-expanded/lofreq'
sys.path.insert(0,str(ROOT/'desktop'))
from prepare_modular_packs import field, number, artifact, execute, workflow, reference_steps, reference_outputs, reference_field
VERSION='0.5.3';TOOL_VERSION='2.1.5-workbench-port2'
LOFREQ_SHA='e4337e5ff5974d37d3a6299afa55074a8652719796a8af9638d64242151db9d0'
SOURCE_SHA='da85ec4baca21e20a55b5f9ee491cdda2986d0dc672177007a2c70ca1d804fe7'
SUBSET_SHA='5578d1ac7afd6d6ed8180b5d893322aef2389d58bd82258fabe3821186b8aa9e'
SAMTOOLS_SHA='49c2f16425d464e4ad1c1439d7a9e32a3b1c1bf8e5d54403778de610d2f440b3'

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def port(identity,kind,members,**extra):return dict(id=identity,type=kind,accepts=[kind],manifestInputs=members,min=1,max=1,**extra)
def output(identity,kind,members,**extra):return dict(id=identity,type=kind,manifestOutputs=members,**extra)
def definitions():
    workflows=[];schemas={}
    def add(identity,title,description,calling=False,indels=False):
        inputs=[field('alignment','Coordinate-sorted DNA alignments',filter='BAM alignments|*.bam|All files|*.*',help='DNA BAM aligned to the supplied reference. Duplicate-marked reads are recommended. RNA/spliced alignments are not supported by Dindel preparation.'),reference_field()]
        outputs=reference_outputs()
        steps=[execute('check-bam','Check BAM integrity','samtools',['quickcheck','-v','{input:alignment}'])]+reference_steps()
        descriptors=[output('reference','reference',['reference'],state={'compression':'none'}),output('reference-index','index',['reference-index'])]
        if indels:
            outputs += [artifact('prepared','BAM with Dindel indel qualities','indel-qualities.bam'),artifact('prepared-index','BAM index','indel-qualities.bam.csi'),artifact('alignment-statistics','Prepared alignment summary','alignment-statistics.txt')]
            steps += [execute('indelqual','Add Illumina Dindel qualities','lofreq',['indelqual','--dindel','-f','{output:reference}','-o','{output:prepared}','{input:alignment}'],produces=['prepared']),execute('index-bam','Index prepared BAM','samtools',['index','-c','{output:prepared}'],produces=['prepared-index']),execute('summarize','Summarize prepared alignments','samtools',['flagstat','{output:prepared}'],stdout='alignment-statistics')]
            descriptors += [output('prepared','bam',['prepared'],state={'sort':'coordinate'},propagateStateFrom='alignment'),output('prepared-index','index',['prepared-index']),output('alignment-statistics','metrics',['alignment-statistics'])]
        if calling:
            inputs += [number('min-mapq','Minimum mapping quality',20,0,60),number('min-baseq','Minimum reference and alternate base quality',20,0,93),number('min-coverage','Minimum tested coverage',10,10,1000000,help='LoFreq also applies its default minimum coverage filter of 10.'),number('max-depth','Maximum pileup depth',1000000,100,1000000,help='Depth above this cap is limited by LoFreq; raising it increases memory and runtime.'),field('significance','Significance level','choice',default='0.01',choices='0.05:0.05|0.01:0.01|0.001:0.001',help='Nominal significance before dynamic Bonferroni correction. Default strand-bias filtering is also applied.')]
            outputs += [artifact('variants','PASS site-only variants (no genotypes)','variants.vcf')]
            args=['call','-f','{output:reference}','-o','{output:variants}','-m','{input:min-mapq}','-q','{input:min-baseq}','-Q','{input:min-baseq}','-C','{input:min-coverage}','-d','{input:max-depth}','-a','{input:significance}']+(['--call-indels'] if indels else [])+['{output:prepared}' if indels else '{input:alignment}']
            steps += [execute('call','Call quality-aware low-frequency variants','lofreq',args,produces=['variants'])]
            descriptors.insert(0,output('variants','vcf-pass',['variants'],state={'compression':'none','selection':'PASS-only'}))
        methods=('Indel insertion/deletion qualities were generated with LoFreq indelqual --dindel using the reference homopolymer context and its Illumina-specific error model, replacing existing BI/BD tags in a new BAM; alignments and base qualities were otherwise preserved. This is not base-quality recalibration or local realignment. ' if indels else '')
        if calling:methods += 'LoFreq called '+('SNVs and indels' if indels else 'SNVs only')+' with the configured mapping/base-quality, coverage, depth and significance thresholds, extended BAQ, dynamic Bonferroni correction and default post-call filters (minimum coverage 10 and strand-bias FDR). Only PASS sites were retained. The VCF contains observed read allele frequencies and site error-model significance, not sample genotypes or a ploidy model; low-frequency calls require assay-specific validation.'
        else:methods += 'The new coordinate-sorted BAM was indexed and summarized with SAMtools. Do not realign after adding indel qualities; this preparation is specific to Illumina DNA data.'
        if indels and not calling:
            descriptors.sort(key=lambda item: item['id']!='prepared')
        workflows.append(workflow(identity,title,description,inputs,outputs,steps))
        schemas[identity]={'ports':[port('alignment','bam',['alignment'],requiredState={'sort':'coordinate'}),port('reference','reference',['reference'],requiredState={'compression':'none'})],'outputs':descriptors,'methods':methods}
        if calling:schemas[identity]['parameterConstraints']=[{'left':'min-coverage','operator':'<=','right':'max-depth'}]
    add('call-snps','LoFreq: low-frequency SNVs','Quality-aware SNV detection with allele frequencies, dynamic multiple-testing correction and default filters. Site-only VCF; no genotypes.',True)
    add('indelqual-dindel','LoFreq: prepare Illumina indel qualities','Add reference-context Dindel BI/BD qualities to a new DNA BAM and index it. Illumina assumptions; existing tags are replaced.',False,True)
    add('call-variants','LoFreq: Illumina SNVs and indels','Generate Dindel indel qualities in a new BAM, then call SNVs and indels with LoFreq. Site-only VCF; no genotypes.',True,True)
    return workflows,{'schema':1,'category':'Variant calling','citations':[{'text':'Wilm et al. (2012). LoFreq: a sequence-quality aware, ultra-sensitive variant caller for uncovering cell-population heterogeneity from high-throughput sequencing datasets. Nucleic Acids Research 40:11189–11201.','url':'https://doi.org/10.1093/nar/gks918'},{'text':'Albers et al. (2011). Dindel: accurate indel calls from short-read data. Genome Research 21:961–973.','url':'https://doi.org/10.1101/gr.112326.110'}],'workflows':schemas}

def fixture_sam(indels=False):
    rng=random.Random(531);ref=''.join(rng.choice('ACGT') for _ in range(500));alt=next(x for x in 'ACGT' if x!=ref[149]);noise=next(x for x in 'ACGT' if x!=ref[179])
    rows=['@HD\tVN:1.6\tSO:coordinate','@SQ\tSN:chrTest\tLN:500','@RG\tID:fixture\tSM:truth']
    for i in range(400):
        seq=list(ref[49:299]);quality=['I']*250;cigar='250M'
        if indels and i<80:seq=seq[:150]+['T']+seq[150:];quality+=['I'];cigar='150M1I100M'
        if not indels and i<40:seq[100]=alt
        if not indels and i==399:seq[130]=noise;quality[130]='+'
        rows.append('\t'.join(map(str,[f'r{i}',16 if i%2 else 0,'chrTest',50,60,cigar,'*',0,0,''.join(seq),''.join(quality),'RG:Z:fixture'])))
    return '>chrTest\n'+ref+'\n','\n'.join(rows)+'\n'

def filtered_source(destination):
    canonical=VENDOR/'lofreq-2.1.5-source-subset.tar.gz'
    if canonical.exists() and canonical.resolve()!=destination.resolve():
        if sha(canonical)!=SUBSET_SHA:raise ValueError('Source subset checksum mismatch')
        shutil.copy2(canonical,destination)
        return json.loads((VENDOR/'excluded-source-members.json').read_text())
    original=VENDOR/'lofreq-2.1.5.tar.gz'
    if sha(original)!=SOURCE_SHA:raise ValueError('LoFreq upstream source hash mismatch')
    excluded=[]
    # Preserve exact selected upstream bytes, omit restricted unused CDF and old releases.
    with tarfile.open(original) as src, destination.open('wb') as raw, gzip.GzipFile(fileobj=raw,mode='wb',filename='',mtime=0) as compressed, tarfile.open(fileobj=compressed,mode='w') as dst:
        for member in src.getmembers():
            relative=member.name.partition('/')[2]
            if relative=='dist' or relative.startswith('dist/') or relative=='src/cdflib90' or relative.startswith('src/cdflib90/'):
                excluded.append(member.name);continue
            dst.addfile(member,src.extractfile(member) if member.isfile() else None)
    return excluded

def build(destination):
    if destination.exists():raise ValueError('Destination already exists: '+str(destination))
    binary=VENDOR/'lofreq-cosmo.exe';samtools=ROOT/'baselines/bin/samtools-cosmo.exe'
    if sha(binary)!=LOFREQ_SHA:raise ValueError('LoFreq binary checksum mismatch')
    if sha(samtools)!=SAMTOOLS_SHA:raise ValueError('SAMtools binary checksum mismatch: '+sha(samtools))
    for sub in ('bin','licenses','fixtures'): (destination/sub).mkdir(parents=True,exist_ok=True)
    shutil.copy2(binary,destination/'bin/lofreq.exe');shutil.copy2(samtools,destination/'bin/samtools.exe')
    licenses=destination/'licenses';src=VENDOR/'build/lofreq-2.1.5'
    for source,target in [(src/'LICENSE','LoFreq-MIT.txt'),(src/'src/uthash/LICENSE','uthash-BSD.txt'),(ROOT/'tools/build_lofreq.py','build_lofreq.py'),(ROOT/'scripts/prepare_lofreq_pack.py','prepare_lofreq_pack.py'),(ROOT/'build_variant.py','build_variant.py')]:shutil.copy2(source,licenses/target)
    excluded=filtered_source(licenses/'lofreq-2.1.5-source-subset.tar.gz')
    shutil.copy2(ROOT/'vendor-variant/archives/samtools-1.24.tar.bz2',licenses/'samtools-htslib-1.24.tar.bz2')
    shutil.copy2(ROOT/'variant-build/cosmopolitan-3.3.10.tar.gz',licenses/'cosmopolitan-3.3.10.tar.gz')
    for path in (ROOT/'vendor-variant/licenses').iterdir():
        if path.is_file():shutil.copy2(path,licenses/('runtime-'+path.name))
    notices={}
    for path in (ROOT/'baselines/licenses/cosmopolitan-3.3.10').rglob('*'):
        if path.is_file():
            relative=str(path.relative_to(ROOT/'baselines/licenses/cosmopolitan-3.3.10'));name='cosmo-'+hashlib.sha256(relative.encode()).hexdigest()[:12]+'.txt'
            shutil.copy2(path,licenses/name);notices[name]=relative
    (licenses/'cosmopolitan-notice-index.json').write_text(json.dumps(notices,indent=2)+'\n')
    # Exact patch against original source (CDF omission is in the build source list).
    diffs=[]
    with tarfile.open(VENDOR/'lofreq-2.1.5-source-subset.tar.gz') as archive:
        for relative in ('src/lofreq/lofreq_call.c','src/lofreq/lofreq_main.c'):
            before=archive.extractfile('lofreq-2.1.5/'+relative).read().decode().splitlines(True)
            after=(src/relative).read_text().splitlines(True)
            diffs+=difflib.unified_diff(before,after,fromfile='a/'+relative,tofile='b/'+relative)
    (licenses/'workbench-port.patch').write_text(''.join(diffs))
    provenance={'upstream':{'version':'2.1.5','tag':'v2.1.5','commit':'8fe42b04dcd9775fb618d8004649421c0632b35c','url':'https://codeload.github.com/CSB5/lofreq/tar.gz/refs/tags/v2.1.5','sha256':SOURCE_SHA},'sourceSubset':{'file':'lofreq-2.1.5-source-subset.tar.gz','sha256':sha(licenses/'lofreq-2.1.5-source-subset.tar.gz'),'excluded':excluded,'reason':'Unused cdflib90 carries legacy ACM copy restrictions. uniq and its binom/cdflib dependencies are not linked. Historical dist archives are omitted.'},'build':{'compiler':'Cosmopolitan3.3.10 x86_64','htslib':'1.24','lofreqSha256':LOFREQ_SHA,'samtoolsSha256':SAMTOOLS_SHA,'commands':'build_lofreq.py --target all --jobs 1','workerThreads':False,'nativeWindowsExecuted':False},'galaxyInspiration':'https://github.com/galaxyproject/tools-iuc/tree/main/tools/lofreq','notes':['No Galaxy XML or shell wrapper is executed.','Internal call→filter shell command replaced by direct built-in dispatch with unchanged arguments.','Temporary VCF reserved by mkstemp in the private run working directory.','No calling/statistical algorithm is replaced; unavailable uniq was the sole cdflib consumer.','The pack does not provide somatic, call-parallel or external Python script workflows.']}
    (licenses/'provenance.json').write_text(json.dumps(provenance,indent=2)+'\n')
    fixture_dir=destination/'fixtures';loader=ROOT/'baselines/bin/ape-loader-linux';loader.chmod(loader.stat().st_mode|0o111)
    for name,indels in [('snps',False),('indels',True)]:
        reference,sam=fixture_sam(indels);(fixture_dir/'reference.fa').write_text(reference);(fixture_dir/(name+'.sam')).write_text(sam)
        subprocess.run([str(loader),str(samtools),'view','-b','-o',str(fixture_dir/(name+'.bam')),str(fixture_dir/(name+'.sam'))],check=True)
    workflows,schema=definitions();(destination/'workbench-schema.json').write_text(json.dumps(schema,indent=2)+'\n')
    checks={'schema':1,'checks':[]}
    for identity,workflow_id,bam,pos,ref,alt,af in [('low-frequency-snv','call-snps','snps',150,'A','C','0.100000'),('dindel-insertion','call-variants','indels',199,'A','AT','0.200000')]:
        checks['checks'].append({'id':identity,'workflow':workflow_id,'inputs':{'alignment':[{'alignment':'fixture-'+bam}],'reference':[{'reference':'fixture-reference'}]},'expect':[{'output':'variants','kind':'vcf','records':1,'samples':[],'variants':[{'chrom':'chrTest','pos':pos,'ref':ref,'alt':alt,'filter':'PASS','info':{'DP':'400','AF':af}}]}]})
    (destination/'workbench-checks.json').write_text(json.dumps(checks,indent=2)+'\n')
    sections=['[pack]\nformat=2\nid=lofreq\nversion='+VERSION+'\nname=LoFreq quality-aware variant calling\nplatform=windows-x86_64\ndescription=Local low-frequency DNA SNV calling and Illumina Dindel-quality preparation/calling; site-only PASS VCF.\ncolor=#557DA5\n']
    def section(name,values):sections.append('['+name+']\n'+'\n'.join(k+'='+str(v) for k,v in values.items() if k!='id')+'\n')
    for name,version in [('lofreq',TOOL_VERSION),('samtools','1.24')]:
        path='bin/'+name+'.exe';section('tool:'+name,{'path':path,'version':version,'sha256':sha(destination/path)})
    assets={'workbench-schema':'workbench-schema.json','workbench-checks':'workbench-checks.json','fixture-reference':'fixtures/reference.fa','fixture-snps':'fixtures/snps.bam','fixture-indels':'fixtures/indels.bam','fixture-snps-sam':'fixtures/snps.sam','fixture-indels-sam':'fixtures/indels.sam'}
    for identity,path in assets.items():section('asset:'+identity,{'path':path,'sha256':sha(destination/path)})
    for wf in workflows:
        section('workflow:'+wf['id'],{**{k:wf[k] for k in ('id','name','description')},**{key:','.join(item['id'] for item in wf[key]) for key in ('inputs','outputs','steps')}})
        for kind,plural in [('input','inputs'),('output','outputs'),('step','steps')]:
            for item in wf[plural]:section(kind+':'+wf['id']+':'+item['id'],item)
    (destination/'pack.ini').write_text('\n'.join(sections))
    (destination/'PACK-README.md').write_text('''# LoFreq quality-aware variant calling

Pack 0.5.3 requires Native Workbench 0.5.3. LoFreq 2.1.5 (workbench-port2) with HTSlib 1.24 and SAMtools 1.24, compiled as local Cosmopolitan x86-64 executables. No Docker, Linux installation, remote compute, shell or external Python is used by these workflows. Single-threaded operation is deliberate.

Three individual/pipeline tools: SNV calling; Illumina Dindel indel-quality preparation; preparation followed by SNV+indel calling. Coordinate-sorted DNA BAM and the exact uncompressed reference are required. Duplicate-marked alignments are recommended. Spliced RNA alignments are not supported by indel preparation. Dindel qualities assume Illumina errors and replace existing BI/BD tags only in a new output BAM. They are not BQSR or realignment; do not realign after this step.

LoFreq uses sequencing/mapping/alignment error probabilities, dynamic Bonferroni correction and default post-call coverage/strand-bias filters. Output is PASS sites only. AF is the observed alternate read fraction, not a genotype. QUAL measures evidence against the error model, not a calibrated clinical pathogenicity probability. VCF has eight columns, no sample genotypes/ploidy model. Low-frequency calls require suitable depth, controls and assay-specific validation; this pack does not claim somatic tumor-normal inference. Defaults may require adjustment for a given assay. Target BED restriction is not exposed in this initial pack, so targeted analyses retain default dynamic whole-input testing.

Reference indexes and any new BAM indexes are built beside private run copies/results. Original inputs are read-only. The calling SNP operation does not need to modify/index the input BAM. The complete original LoFreq call/filter calculations are retained. Its internal shell filter launch is replaced with a direct call to its own filter function using separate argv elements; temporary VCFs are reserved in the run folder. Paths with spaces are tested on Linux/APE; Windows filesystem behavior remains subject to native validation.

## Redistribution and source

LoFreq is MIT, uthash BSD, HTSlib/SAMtools MIT/BSD and Cosmopolitan permissive with included third-party notices. Upstream includes an unused cdflib90 directory carrying older ACM copy restrictions; `uniq` is therefore unavailable and neither its binom/CDF code nor historical prebuilt dist archives is redistributed or linked. licenses/provenance.json records the original source URL/hash and exact excluded members; the corresponding permitted source subset, patch, build scripts and linked-library sources/notices are included. No algorithm used by call, filter or indelqual was changed. Rebuild from the source subset using build_lofreq.py --source-archive; the script verifies its pinned hash, applies the included changes and uses explicit source lists; original upstream downloads are optional for provenance verification, not redistribution.

## Validation scope

Scientific fixtures test a balanced-strand 10% SNV (40/400 reads) with rejected low-quality noise and a 20% insertion (80/400) after Dindel preparation. Linux-native and actual portable APE binaries are compared. These are synthetic correctness fixtures, not sensitivity/specificity benchmarks. Windows execution has not been performed here: Check installation runs the actual packaged executables and structural VCF assertions on the user's machine. Upstream version, argv, input hashes and methods are recorded for each run.

Citation: Wilm et al. (2012), Nucleic Acids Research 40:11189–11201, doi:10.1093/nar/gks918. Dindel: Albers et al. (2011), Genome Research 21:961–973, doi:10.1101/gr.112326.110.
''')
    print(destination)
    return destination
if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,default=ROOT/'packs'/('lofreq-'+VERSION));build(p.parse_args().output.resolve())
