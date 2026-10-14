#!/usr/bin/env python3
"""Assemble a self-contained VarDictJava targeted-calling pack from pinned assets."""
import argparse
import hashlib
import json
from pathlib import Path
import random
import shutil
import subprocess
import sys
import tarfile
import zipfile

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'desktop'))
from prepare_modular_packs import field, number, artifact, execute, workflow
VENDOR=ROOT/'vendor-expanded/vardict'
VERSION='0.5.3'
PINS={
 'VarDict-1.8.3.zip':'c1940c1b0308a431879010b52036c02c39ca0f97af04fd56c2f1b6febe75734b',
 'OpenJDK8U-jre_x64_windows_hotspot_8u504b01.zip':'82e2cdc6693737c5998445b31f69668fa0da77c7705121053f6508ac84961123',
 'OpenJDK8U-jdk-sources_8u504b01.tar.gz':'86cd14f299616dddca13268cc2fa794eb4d28fc732dedaad8c5b8a3078e5d3c9',
 'strawberry-perl-5.42.3.1-64bit-portable.zip':'6a081a811781c30aca51dbc036afd93092af91e3297901f02c17043795a10690',
 'perl-5.42.3.tar.xz':'c9387e1473a1866935cb047ece7c2e0a80767a3acdecb79d4a375f8a95970ddc',
 'strawberry-5.42.3.1-source.tar.gz':'c5d2edf05f4a3471a085a0bc21023cd9e73530b55a2d4043e9d79d480e4d273c',
 'gcc-13.2.0.tar.xz':'e275e76442a6067341a27f04c5c6b83d8613144004c0413528863dc6b5c743da',
 'VarDictJava-1.8.3-source.tar.gz':'b45a3f7301c468d514c3916179f9f3c25f31e12f663ce6c674109caf3d60701e',
 'VarDict-009e017-source.tar.gz':'1d70dd8eacb59a9e8fa909f6b322fbef6474d11eb27b6b21273761df0dfdd422',
 'build-extlibs-source.tar.gz':'c204ef125854ad2b33cff775818e7c9c4b7fa81e8f12c09b8de7bc80fa4c63b0',
 'mingw-w64-11.0.1-source.tar.gz':'493cb0bde1e470a281c7a633fcc1158de3b8919f687020c60a936e7b2512398d',
 'jregex-1.2_01-sources.jar':'c69ea8dc84a8c2aad0494c78bfd1e4380cc17baa7ed8e77adbfc7002470c28e2',
 'htsjdk-source.jar':'6e4ee652e89ab3515a71e5314f6d4874720febc4e4233de28a6df09fc8158298',
 'Microsoft-VC-Runtime-2015-2022-License.docx':'f1e3d56ceb2ad68aae0711b910375009e651ac5530fa0760f0dea6e81e54fae1',
}
NATIVE_PINS={'samtools':'49c2f16425d464e4ad1c1439d7a9e32a3b1c1bf8e5d54403778de610d2f440b3','bcftools':'e2f53c05048fa1de94149e87203ba9c4c73be548196097fbe2f1426c3d1d556f'}
PERL_MODULES=['strict.pm','warnings.pm','warnings/register.pm','Getopt/Std.pm','Exporter.pm','Exporter/Heavy.pm','Carp.pm']
BRIDGE=r'''# Fixed local adapter: run the original upstream converter on an already
# produced file through STDIN, with private modules and no shell or subprocess.
our $workbench_dir;
BEGIN {
    my $path = __FILE__;
    ($workbench_dir) = $path =~ /\A(.*)[\\\/]convert\.pl\z/;
    die "Cannot determine private Perl module directory\n" unless defined $workbench_dir;
    @INC = ("$workbench_dir/lib");
}
use strict;
use warnings;
die "Expected input, sample, frequency, depth, alternate depth, quality, mapping quality and read position\n" unless @ARGV == 8;
my ($input,$sample,$frequency,$depth,$alternate,$quality,$mapping,$position)=@ARGV;
open(STDIN, '<', $input) or die "Cannot read VarDict result: $!\n";
@ARGV=('-N',$sample,'-E','-A','-f',$frequency,'-d',$depth,'-v',$alternate,
       '-q',$quality,'-Q',$mapping,'-p',$position,'-F','0.2');
my $result=do "$workbench_dir/var2vcf_valid.pl";
die $@ if $@;
die "Cannot load the private upstream VCF converter: $!\n" if !defined($result) && $!;
'''

def digest(path):
    h=hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda:stream.read(1024*1024),b''):h.update(block)
    return h.hexdigest()

def choice(identity,label,default,choices,help=''):
    return field(identity,label,'choice',default=default,choices=choices,help=help)

def definitions():
    inputs=[field('alignment','Prepared coordinate-sorted single-sample BAM',filter='BAM alignment|*.bam',help='All read groups must identify one sample. Use DNA alignments, with duplicates marked as appropriate for the assay.'),
      field('reference','Matching reference genome',filter='Uncompressed FASTA|*.fa;*.fasta;*.fna'),
      field('targets','Target intervals (BED4)',filter='Target intervals|*.bed',help='Nonoverlapping tab-separated chromosome, zero-based start, end, region name. Contigs and bounds must match the reference.'),
      field('sample','Sample name (BAM SM)',type='text',default='sample',constraint='identifier',help='Must match the single sample name in the BAM read groups.'),
      choice('minimum-frequency','Minimum candidate allele fraction','0.02','0.01:1%|0.02:2%|0.05:5%|0.1:10%|0.2:20%|0.3:30%',help='Single-sample calling cannot distinguish somatic from germline variants. Choose thresholds for the assay.'),
      number('minimum-depth','VCF minimum total depth',8,1,1000000),number('minimum-alt','Minimum alternate-supporting reads',3,1,1000000),
      number('base-quality','Good-base Phred quality',25,1,93),number('mapping-quality','Minimum read mapping quality',20,0,60),
      number('read-position','VCF minimum mean read position',8,1,1000),number('threads','Threads',1,1,64),
      number('memory','Maximum Java heap (MiB)',1024,256,32768,help='Additional RAM is needed outside the Java heap. Targeted intervals are recommended; this is not an optimized whole-genome workflow.')]
    outputs=[artifact('reference','Private reference','reference.fa',False),artifact('reference-index','Reference FAI','reference.fa.fai',False),
      artifact('alignment-copy','Private BAM','alignment.bam',False),artifact('bam-index','Private BAM index','alignment.bam.bai',False),
      artifact('calls-table','VarDict candidate table (experimental Java Fisher)','vardict.tsv',True,False),
      artifact('raw-vcf','Original upstream converter VCF','raw.vcf',False),artifact('header-vcf','Reference-header VCF','header.vcf',False),
      artifact('variants','Normalized calls with VarDict FILTER labels','variants.vcf.gz'),artifact('variants-index','All-call CSI index','variants.vcf.gz.csi'),
      artifact('pass-variants','PASS-only calls','variants.pass.vcf.gz'),artifact('pass-index','PASS-call CSI index','variants.pass.vcf.gz.csi'),
      artifact('variant-stats','All-call statistics','variant-stats.txt'),artifact('pass-stats','PASS-call statistics','pass-stats.txt')]
    jars=['vardict','commons-cli','commons-math3','jregex','htsjdk']
    java=['-Xms64m','-Xmx{input:memory}m','-XX:+DisableAttachMechanism','-XX:-UsePerfData',
      '-Djava.awt.headless=true','-Duser.language=en','-Duser.country=US','-Duser.timezone=UTC','-Dfile.encoding=UTF-8',
      '-Dsamjdk.use_jdk_inflater=true','-Dsamjdk.use_jdk_deflater=true','-cp',';'.join('{asset:'+name+'}' for name in jars),
      'com.astrazeneca.vardict.Main','-G','{output:reference}','-b','{output:alignment-copy}','-N','{input:sample}',
      '-z','-c','1','-S','2','-E','3','-g','4','-th','{input:threads}','-f','{input:minimum-frequency}',
      '-r','{input:minimum-alt}','-q','{input:base-quality}','-Q','{input:mapping-quality}',
      '-k','1','-U','--fisher','-VS','STRICT','{input:targets}']
    steps=[dict(id='copy-reference',label='Stage a private reference',kind='copy',source='{input:reference}',destination='reference'),
      execute('index-reference','Index the reference','samtools',['faidx','{output:reference}'],produces=['reference-index']),
      dict(id='copy-bam',label='Stage a private alignment',kind='copy',source='{input:alignment}',destination='alignment-copy'),
      execute('index-bam','Index the private BAM','samtools',['index','-b','{output:alignment-copy}','{output:bam-index}'],produces=['bam-index']),
      execute('call','VarDictJava 1.8.3 (experimental Java Fisher)','java',java,stdout='calls-table'),
      execute('convert','Convert with the original upstream Perl VCF script','perl',['-T','{asset:converter-adapter}','{output:calls-table}',
        '{input:sample}','{input:minimum-frequency}','{input:minimum-depth}','{input:minimum-alt}','{input:base-quality}',
        '{input:mapping-quality}','{input:read-position}'],stdout='raw-vcf'),
      execute('reference-header','Add complete reference contig headers','bcftools',['reheader','-f','{output:reference-index}','-o','{output:header-vcf}','{output:raw-vcf}'],produces=['header-vcf']),
      execute('normalize','Check REF alleles, left-align and split multiallelic records','bcftools',['norm','-c','e','-f','{output:reference}','-m','-any','-Oz','-o','{output:variants}','{output:header-vcf}'],produces=['variants']),
      execute('index','Index normalized variants','bcftools',['index','--csi','{output:variants}'],produces=['variants-index']),
      execute('pass','Select PASS calls separately','bcftools',['view','-f','PASS','-Oz','-o','{output:pass-variants}','{output:variants}'],produces=['pass-variants']),
      execute('pass-index','Index PASS calls','bcftools',['index','--csi','{output:pass-variants}'],produces=['pass-index']),
      execute('stats','Summarize all calls','bcftools',['stats','{output:variants}'],stdout='variant-stats'),
      execute('pass-stats','Summarize PASS calls','bcftools',['stats','{output:pass-variants}'],stdout='pass-stats')]
    wf=workflow('call','VarDictJava: targeted calls (experimental Fisher)',
      'Single-sample targeted SNV/indel calling with VarDictJava 1.8.3, its experimental Java Fisher mode and the original Perl VCF converter.',inputs,outputs,steps)
    ports=[dict(id='alignment',type='bam',accepts=['bam'],manifestInputs=['alignment'],min=1,max=1,requiredState={'sort':'coordinate'},validation={'singleSample':True,'sampleParameter':'sample'}),
      dict(id='reference',type='reference',accepts=['reference'],manifestInputs=['reference'],min=1,max=1,requiredState={'compression':'none'}),
      dict(id='targets',type='bed',accepts=['bed'],manifestInputs=['targets'],min=1,max=1,validation={'minColumns':4,'nonOverlapping':True,'referenceBounds':True})]
    kinds={'reference':'reference','reference-index':'index','alignment-copy':'bam','bam-index':'index','calls-table':'metrics','raw-vcf':'vcf','header-vcf':'vcf','variants':'vcf','variants-index':'index','pass-variants':'vcf-pass','pass-index':'index','variant-stats':'metrics','pass-stats':'metrics'}
    descriptors=[]
    for record in outputs:
        identity=record['id'];state={}
        if identity=='alignment-copy':state={'sort':'coordinate'}
        elif identity in ('variants','pass-variants'):state={'compression':'bgzf','selection':'PASS-only' if identity=='pass-variants' else 'all-calls-with-filter-labels'}
        elif identity in ('reference','raw-vcf','header-vcf'):state={'compression':'none'}
        descriptors.append(dict(id=identity,type=kinds[identity],manifestOutputs=[identity],state=state))
    rank={'variants':0,'pass-variants':1,'variant-stats':2,'pass-stats':3,'calls-table':4}
    descriptors.sort(key=lambda item:rank.get(item['id'],5))
    methods='Single-sample targeted variants were called with VarDictJava 1.8.3 using local realignment and the upstream EXPERIMENTAL --fisher implementation of strand-bias Fisher tests. Structural-variant calling was disabled. Coordinate-sorted DNA BAM and nonoverlapping BED4 targets were used with the recorded quality, depth and allele-fraction settings. The unmodified upstream var2vcf_valid.pl script bundled with release 1.8.3 (script version 1.8.2) converted every candidate allele (-A) to VCF, retaining FILTER labels; its allele-fraction-based diploid genotype convention was retained (homozygous ALT above 80% AF). This does not determine somatic status or support arbitrary ploidy. BCFtools checked REF alleles, left-aligned/split calls, compressed/indexed all calls and separately exported PASS calls. The Java Fisher path was compared with R on finite deterministic fixtures but remains experimental upstream.'
    schema=dict(schema=1,category='Variant calling',citations=[dict(text='Lai et al. (2016). VarDict: a novel and versatile variant caller for next-generation sequencing in cancer research.',url='https://doi.org/10.1093/nar/gkw227')],workflows={'call':dict(ports=ports,outputs=descriptors,methods=methods,pathPolicy={'asciiOnly':True,'forbiddenCharacters':[';','|']})})
    return wf,schema

def fixtures(folder):
    rng=random.Random(5303);reference=''.join(rng.choice('ACGT') for _ in range(1200));position=300
    alt={'A':'C','C':'G','G':'T','T':'A'}[reference[position-1]]
    (folder/'reference.fa').write_text('>chr1\n'+reference+'\n',encoding='ascii')
    (folder/'targets.bed').write_text('chr1\t0\t1200\ttarget\n',encoding='ascii')
    sam=['@HD\tVN:1.6\tSO:coordinate','@SQ\tSN:chr1\tLN:1200\tM5:'+hashlib.md5(reference.encode()).hexdigest(),'@RG\tID:validation-rg\tSM:validation\tLB:validation\tPL:ILLUMINA']
    for n in range(48):
        start=220+n//2;sequence=list(reference[start-1:start-1+180]);is_alt=n%2==1
        if is_alt:sequence[position-start]=alt
        sam.append('\t'.join([f'read{n:03d}',str(16 if (n//2)%2 else 0),'chr1',str(start),'60','180M','*','0','0',''.join(sequence),'I'*180,'RG:Z:validation-rg','NM:i:'+str(int(is_alt))]))
    (folder/'input.sam').write_text('\n'.join(sam)+'\n',encoding='ascii')
    samtools=ROOT/'baselines/bin/samtools-linux';samtools.chmod(samtools.stat().st_mode|0o100)
    subprocess.run([str(samtools),'view','--no-PG','-b','-o',str(folder/'input.bam'),str(folder/'input.sam')],check=True,capture_output=True)
    checks=dict(schema=1,checks=[dict(id='targeted-snv',workflow='call',params={'sample':'validation'},inputs={'alignment':[{'alignment':'fixture-bam'}],'reference':[{'reference':'fixture-reference'}],'targets':[{'targets':'fixture-targets'}]},expect=[dict(output='variants',kind='vcf',records=1,samples=['validation'],variants=[dict(chrom='chr1',pos=position,ref=reference[position-1],alt=alt,filter='PASS',genotypes={'validation':'1/0'})]),dict(output='pass-variants',kind='vcf',records=1,samples=['validation'],variants=[dict(chrom='chr1',pos=position,ref=reference[position-1],alt=alt,filter='PASS')])])])
    # Separate reads support one insertion and deletion as well as the SNP.
    insertion='AGC' if reference[599]!='C' else 'AGT'
    deletion_position=900
    while reference[deletion_position-1]==reference[deletion_position+2]:deletion_position+=1
    combined=sam[:]
    for locus,kind in ((600,'insertion'),(deletion_position,'deletion')):
        for n in range(48):
            start=locus-80+n//2;is_alt=n%2==1;left=locus-start+1;right=180-left
            cigar='180M';sequence=reference[start-1:start-1+180]
            if is_alt and kind=='insertion':
                cigar=f'{left}M3I{right}M';sequence=reference[start-1:locus]+insertion+reference[locus:start-1+180]
            elif is_alt:
                cigar=f'{left}M3D{right}M';sequence=reference[start-1:locus]+reference[locus+3:start-1+183]
            combined.append('\t'.join([f'{kind}{n:03d}',str(16 if (n//2)%2 else 0),'chr1',str(start),'60',cigar,'*','0','0',sequence,'I'*len(sequence),'RG:Z:validation-rg','NM:i:'+str(3 if is_alt else 0)]))
    (folder/'indels.sam').write_text('\n'.join(combined)+'\n',encoding='ascii')
    subprocess.run([str(samtools),'view','--no-PG','-b','-o',str(folder/'indels.bam'),str(folder/'indels.sam')],check=True,capture_output=True)
    variants=[dict(chrom='chr1',pos=position,ref=reference[position-1],alt=alt,filter='PASS'),
        dict(chrom='chr1',pos=600,ref=reference[599],alt=reference[599]+insertion,filter='PASS'),
        dict(chrom='chr1',pos=deletion_position,ref=reference[deletion_position-1:deletion_position+3],alt=reference[deletion_position-1],filter='PASS')]
    checks['checks'].append(dict(id='targeted-snv-insertion-deletion',workflow='call',params={'sample':'validation'},inputs={'alignment':[{'alignment':'fixture-indels-bam'}],'reference':[{'reference':'fixture-reference'}],'targets':[{'targets':'fixture-targets'}]},expect=[dict(output='variants',kind='vcf',records=3,samples=['validation'],variants=variants)]))
    (folder/'truth.json').write_text(json.dumps(variants,indent=2)+'\n')
    return checks

def build(folder):
    for name,pin in PINS.items():
        if digest(VENDOR/name)!=pin:raise ValueError('Upstream checksum mismatch: '+name)
    if folder.exists():raise ValueError('Output already exists: '+str(folder))
    for sub in ('bin','runtime/java','runtime/perl/lib','assets','licenses','fixtures'):(folder/sub).mkdir(parents=True,exist_ok=True)
    with zipfile.ZipFile(VENDOR/'OpenJDK8U-jre_x64_windows_hotspot_8u504b01.zip') as z:
        for item in z.infolist():
            if item.is_dir():continue
            relative=Path(*Path(item.filename).parts[1:]);dest=folder/'runtime/java'/relative
            dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(z.read(item))
            if relative.as_posix() in ('LICENSE','NOTICE','ASSEMBLY_EXCEPTION'):(folder/'licenses'/('java-'+relative.name)).write_bytes(z.read(item))
    with zipfile.ZipFile(VENDOR/'strawberry-perl-5.42.3.1-64bit-portable.zip') as z:
        for name in ('perl.exe','perl542.dll','libgcc_s_seh-1.dll','libstdc++-6.dll','libwinpthread-1.dll'):
            (folder/'runtime/perl'/name).write_bytes(z.read('perl/bin/'+name))
        for name in PERL_MODULES:
            dest=folder/'runtime/perl/lib'/name;dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(z.read('perl/lib/'+name))
        for name in ('Artistic','Copying','Readme'):(folder/'licenses'/('perl-'+name+'.txt')).write_bytes(z.read('licenses/perl/'+name))
        (folder/'licenses/strawberry-README.txt').write_bytes(z.read('README.txt'))
    jars={}
    with zipfile.ZipFile(VENDOR/'VarDict-1.8.3.zip') as z:
        for name in z.namelist():
            leaf=Path(name).name
            if name.endswith('.jar'):
                (folder/'assets'/leaf).write_bytes(z.read(name))
                jars[{'VarDict-1.8.3.jar':'vardict','commons-cli-1.2.jar':'commons-cli','commons-math3-3.6.1.jar':'commons-math3','jregex-1.2_01.jar':'jregex','htsjdk-2.21.1.jar':'htsjdk'}[leaf]]='assets/'+leaf
            elif leaf=='var2vcf_valid.pl':(folder/'runtime/perl'/leaf).write_bytes(z.read(name))
            elif leaf in ('teststrandbias.R','testsomatic.R'):(folder/'licenses'/leaf).write_bytes(z.read(name))
    (folder/'runtime/perl/convert.pl').write_text(BRIDGE,encoding='utf-8')
    with tarfile.open(VENDOR/'VarDictJava-1.8.3-source.tar.gz') as t:
        for source,target in [('LICENSE','VarDictJava-MIT.txt'),('Readme.md','VarDictJava-Readme.md')]:
            member=next(m for m in t.getmembers() if m.name.count('/')==1 and Path(m.name).name==source)
            (folder/'licenses'/target).write_bytes(t.extractfile(member).read())
    for name in PINS:
        if name.endswith(('.tar.gz','.tar.xz')):shutil.copy2(VENDOR/name,folder/'licenses'/name)
    for name in ('jregex-1.2_01-sources.jar','htsjdk-source.jar','Microsoft-VC-Runtime-2015-2022-License.docx'):
        shutil.copy2(VENDOR/name,folder/'licenses'/name)
    for name in ('jregex-1.2_01-sources.jar','htsjdk-source.jar'):
        with zipfile.ZipFile(VENDOR/name) as z:
            headers=[];seen=set()
            for item in z.namelist():
                if item.endswith('.java'):
                    text=z.read(item).decode('utf-8',errors='replace');header=text.split('package ',1)[0].strip()
                    if any(word in header.lower() for word in ('copyright','license','permission')) and header not in seen:
                        seen.add(header);headers.append('Source: '+item+'\n'+header)
            (folder/'licenses'/(name.replace('.jar','')+'-NOTICES.txt')).write_text('\n\n'.join(headers)+'\n',encoding='utf-8')
    microsoft=[]
    for p in sorted((folder/'runtime/java/bin').glob('*.dll')):
        if p.name.lower().startswith(('api-ms-win-','msvcp','vcruntime','ucrtbase')):
            microsoft.append(dict(path=p.relative_to(folder).as_posix(),sha256=digest(p)))
    (folder/'licenses/Microsoft-runtime-components.json').write_text(json.dumps({'source':'Unmodified files included in the official Eclipse Temurin8u504-b01 Windows JRE archive.','license':'Microsoft proprietary runtime components; these DLLs are not licensed as OpenJDK GPLv2/ClassPath-Exception code.','officialLicense':'https://visualstudio.microsoft.com/license-terms/vs2022-cruntime/','originalDocument':'Microsoft-VC-Runtime-2015-2022-License.docx','officialRedistributionInformation':'https://learn.microsoft.com/en-us/visualstudio/releases/2022/redistribution','components':microsoft},indent=2)+'\n')
    # Sources and notices for the MinGW threading runtime, retained flat.
    mingw=VENDOR/'mingw-w64-11.0.1-source.tar.gz'
    if not mingw.is_file():raise ValueError('Missing MinGW runtime corresponding source')
    shutil.copy2(mingw,folder/'licenses'/mingw.name)
    for archive,targets,prefix in [('gcc-13.2.0.tar.xz',('COPYING3','COPYING.RUNTIME'),'gcc'),('VarDict-009e017-source.tar.gz',('LICENSE',),'VarDict-Perl')]:
        with tarfile.open(VENDOR/archive) as t:
            for leaf in targets:
                matches=[m for m in t.getmembers() if m.isfile() and m.name.count('/')==1 and Path(m.name).name==leaf]
                if matches:(folder/'licenses'/(prefix+'-'+leaf+'.txt')).write_bytes(t.extractfile(matches[0]).read())
    # JAR libraries carry their own notices; retain them outside the JAR as well.
    for p in sorted((folder/'assets').glob('*.jar')):
        with zipfile.ZipFile(p) as z:
            for name in z.namelist():
                if not name.endswith('/') and any(word in Path(name).name.lower() for word in ('license','notice','copying')):
                    (folder/'licenses'/(p.stem+'-'+hashlib.sha256(name.encode()).hexdigest()[:8]+'.txt')).write_bytes(z.read(name))
    license_index={}
    for base in [ROOT/'baselines/licenses/cosmopolitan-3.3.10',ROOT/'vendor-variant/licenses']:
        for p in sorted(base.rglob('*')):
            if p.is_file():
                name='native-'+hashlib.sha256(str(p.relative_to(ROOT)).encode()).hexdigest()[:16]+'.txt'
                shutil.copy2(p,folder/'licenses'/name);license_index[name]=str(p.relative_to(ROOT))
    (folder/'licenses/native-notice-index.json').write_text(json.dumps(license_index,indent=2)+'\n')
    for name in ('samtools','bcftools'):
        source=ROOT/'baselines/bin'/(name+'-cosmo.exe')
        if digest(source)!=NATIVE_PINS[name]:raise ValueError('Pinned native tool differs: '+name)
        shutil.copy2(source,folder/'bin'/(name+'.exe'))
    wf,schema=definitions();checks=fixtures(folder/'fixtures')
    for name,document in [('workbench-schema.json',schema),('workbench-checks.json',checks)]:
        (folder/name).write_text(json.dumps(document,indent=2)+'\n',encoding='utf-8')
    sections=['[pack]\nformat=2\nid=vardict\nversion='+VERSION+'\nname=VarDictJava targeted variants\nplatform=windows-x86_64\ndescription=Single-sample targeted SNV/indel calling; upstream experimental Java Fisher mode, original Perl VCF conversion, private runtimes.\ncolor=#8C68A8\n']
    def section(name,values):sections.append('['+name+']\n'+'\n'.join(k+'='+str(v) for k,v in values.items() if k!='id')+'\n')
    tools={'java':('runtime/java/bin/java.exe','8u504-b01'),'perl':('runtime/perl/perl.exe','5.42.3.1'),'samtools':('bin/samtools.exe','1.24'),'bcftools':('bin/bcftools.exe','1.24')}
    for identity,(path,version) in tools.items():section('tool:'+identity,dict(path=path,version=version,sha256=digest(folder/path)))
    assets=dict(jars,**{'converter-adapter':'runtime/perl/convert.pl','fixture-bam':'fixtures/input.bam','fixture-reference':'fixtures/reference.fa','fixture-targets':'fixtures/targets.bed','fixture-sam':'fixtures/input.sam','fixture-indels-bam':'fixtures/indels.bam','fixture-indels-sam':'fixtures/indels.sam','fixture-truth':'fixtures/truth.json','workbench-schema':'workbench-schema.json','workbench-checks':'workbench-checks.json'})
    declared=set(assets.values())|{x[0] for x in tools.values()}
    for p in sorted((folder/'runtime').rglob('*')):
        path=p.relative_to(folder).as_posix()
        if p.is_file() and path not in declared:assets['runtime-'+hashlib.sha256(path.encode()).hexdigest()[:16]]=path
    for identity,path in assets.items():section('asset:'+identity,dict(path=path,sha256=digest(folder/path)))
    section('workflow:call',dict(name=wf['name'],description=wf['description'],inputs=','.join(x['id'] for x in wf['inputs']),outputs=','.join(x['id'] for x in wf['outputs']),steps=','.join(x['id'] for x in wf['steps'])))
    for kind,plural in [('input','inputs'),('output','outputs'),('step','steps')]:
        for record in wf[plural]:section(kind+':call:'+record['id'],record)
    (folder/'pack.ini').write_text('\n'.join(sections),encoding='utf-8')
    provenance={'packVersion':VERSION,'sourcePins':PINS,'mingwSourceSha256':digest(mingw),'javaRuntime':'Temurin8u504-b01','perlRuntime':'StrawberryPerl5.42.3.1; only unmodified interpreter, five required PE files and seven core modules for the fixed upstream converter','javaMode':'Experimental upstream --fisher; no R required at runtime','nativeWindowsExecutedDuringBuild':False}
    (folder/'licenses/BUILD-PROVENANCE.json').write_text(json.dumps(provenance,indent=2)+'\n')
    shutil.copy2(ROOT/'validation/vardict-0.5.3-fisher.json',folder/'licenses/fisher-validation.json')
    (folder/'PACK-README.md').write_text('''# VarDictJava targeted calling — experimental Java Fisher mode

Pack 0.5.3 requires Native Workbench 0.5.3 or newer. VarDictJava 1.8.3 calls single-sample targeted SNVs and small indels from a prepared DNA BAM, matching uncompressed reference FASTA and nonoverlapping BED4 targets. Structural-variant calling is disabled. This workflow does not determine somatic status, infer arbitrary ploidy, or provide clinical validation.

The upstream --fisher Java implementation is explicitly EXPERIMENTAL. It replaces the upstream R statistical stage. Its rounded p-values and conditional odds ratios matched R 4.3.3 on 40 deterministic balanced, asymmetric, extreme, zero and high-depth tables; see licenses/fisher-validation.json. This finite comparison does not prove equivalence for all inputs. The original upstream var2vcf_valid.pl (version 1.8.2, bundled with the official 1.8.3 release) remains unmodified; its allele-fraction genotype convention is retained, including heterozygous 1/0 and homozygous ALT above 80% AF. All alleles at a position are requested (-A).

Private copies of BAM and reference are indexed inside the run folder. All BAM read groups must have one sample name matching the supplied sample field. BED coordinates are zero-based, end-exclusive, in bounds, and nonoverlapping; the fourth column is a region name. Header dictionary/MD5 checks are recorded; headers without MD5 cannot establish reference sequence identity. The BAM index uses BAI: contigs over the BAI coordinate range are not supported by this workflow.

All normalized calls retain VarDict FILTER labels. PASS calls and their statistics are exported separately. BCFtools supplies the complete reference contig dictionary, rejects mismatching REF alleles, left-aligns and splits multiallelic records, and writes BGZF/CSI files. Original candidate tables and command logs are retained. No candidate output is a valid empty result if the target contains no supported variant; an empty or malformed input reference/BED/BAM is an error.

Java, Perl, SAMtools and BCFtools run locally from this pack; no system Java, Perl, R, Docker or WSL is required. The Windows runtime is the complete official Temurin 8u504-b01 JRE. The Perl runtime contains unmodified Strawberry Perl 5.42.3.1 interpreter/DLLs and the core-module closure needed by the fixed upstream converter, not a general-purpose Perl development installation. A small included adapter binds a local generated TSV to STDIN using a three-argument open, fixes private module lookup and invokes the original converter. No shell is used. Runtime startup injection environment variables are removed by Workbench 0.5.3, Perl taint mode is enabled, and Java attach/performance-data facilities are disabled.

Official Windows PE/import checks and Linux scientific tests are separate evidence. The installation check runs the actual bundled Windows toolchain on a known SNV fixture. Native Windows execution, very long paths and non-ASCII Windows paths require validation on the user's machine. Upstream Strawberry recommends short ASCII installation paths without spaces; argv quoting is tested independently but does not remove that upstream runtime limitation.

VarDictJava and the upstream VarDict Perl scripts are MIT licensed; Commons libraries use Apache 2.0; JRegex is BSD; HTSJDK is MIT. OpenJDK code uses GPLv2 with the Classpath Exception; the Perl interpreter is dual Artistic/GPL. Microsoft VC++/Universal CRT DLLs bundled by the official Temurin Windows image are separate Microsoft proprietary components, not GPL/ClassPath code; their inventory, Microsoft's original 2015-2022 Runtime license document and official redistribution-information link accompany the unchanged JRE notices. Compiler runtime exceptions and component notices are retained. Corresponding Java, Perl, compiler/runtime and VarDict sources are archived under licenses. Build pins and extracted component identities are recorded in licenses/BUILD-PROVENANCE.json. The source distribution includes scripts/prepare_vardict_pack.py and its pinned fetch manifest.

Project: https://github.com/AstraZeneca-NGS/VarDictJava
Galaxy guidance: https://github.com/galaxyproject/tools-iuc/tree/main/tools/vardict
Citation: Lai et al. (2016), https://doi.org/10.1093/nar/gkw227
''',encoding='utf-8')
    files=list(folder.rglob('*'));size=sum(p.stat().st_size for p in files if p.is_file())
    if len(files)>2000 or size>512*1024*1024:raise ValueError('Pack exceeds reviewed 0.5.3 inventory budget')
    print(str(folder)+' — '+str(size)+' bytes, '+str(len(files))+' files/directories')
    return folder

if __name__=='__main__':
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--output',type=Path,default=ROOT/'packs/vardict-0.5.3');build(ap.parse_args().output.resolve())
