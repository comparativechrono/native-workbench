#!/usr/bin/env python3
"""Assemble the unchanged GATK Mutect2 local JAR and private Windows Java 17."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sys
import tarfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'desktop'))
from prepare_modular_packs import field, number, artifact, execute, workflow
from generate_mutect2_fixtures import generate, self_checks
from fetch_mutect2_thirdparty_sources import INVENTORY_NAME, INVENTORY_SHA256

VERSION = '0.5.4'
GATK = '4.7.0.0'
JAVA = '17.0.20.1+1'
VENDOR = ROOT/'vendor-expanded/gatk'
THIRDPARTY = ROOT/'vendor-expanded/gatk-thirdparty'
COMPAT = ROOT/'build/mutect2/path-compat'
COMPAT_SHA256 = 'd3a35b8cf2790f12b5d57574b7d46de3598a8836201f3f9b899798521db9e78a'
COMPAT_SOURCE_PINS = {
    'gatk-local-path.patch':'0526a28160abc63da09e7fd683a160cdee49767d388f4755a557498b387f336e',
    'src/main/java/org/broadinstitute/hellbender/utils/io/IOUtils.java':'5b9f0c83e8d90c49ac8efbf2433e62fe741771c52658823a9a3a80e3678e0486',
}
PINS = {
    'gatk-4.7.0.0.zip': 'd093d2693b1626361a413ca59d6d4a0bf968717f280a8fd9ce060b25eb2ed1db',
    'gatk-4.7.0.0-source.tar.gz': '35ffd523a378374aabdb29321bdad90fe48eba31f7c251592cd6305e950016d3',
    'OpenJDK17U-jre_x64_windows_hotspot_17.0.20.1_1.zip': 'bc21a93923103cdaac93ee337b0ae4365e739fde36df823dd456bc67c8a9d352',
    'OpenJDK17U-jdk-sources_17.0.20.1_1.tar.gz': '21e2a065d244ab048e737f21af5d1fc74daaeb6707de36477ead8db1dca71214',
    'Microsoft-VC-Runtime-2015-2022-License.docx': 'f1e3d56ceb2ad68aae0711b910375009e651ac5530fa0760f0dea6e81e54fae1',
}
NATIVE_PINS = {'samtools':'49c2f16425d464e4ad1c1439d7a9e32a3b1c1bf8e5d54403778de610d2f440b3', 'bcftools':'e2f53c05048fa1de94149e87203ba9c4c73be548196097fbe2f1426c3d1d556f'}


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def java_args(tool, args):
    return ['-Xms64m', '-Xmx{input:memory}m', '-XX:+DisableAttachMechanism', '-XX:-UsePerfData',
            '-Djava.awt.headless=true', '-Duser.language=en', '-Duser.country=US', '-Duser.timezone=UTC',
            '-Dfile.encoding=UTF-8', '-Djava.io.tmpdir={run}',
            '-Dsamjdk.use_jdk_inflater=true', '-Dsamjdk.use_jdk_deflater=true',
            '-Dsamjdk.use_libdeflate=false', '-Dsamjdk.snappy.disable=true',
            '-jar', '{asset:gatk-compat}', tool, '--tmp-dir', '{run}',
            '--use-jdk-inflater', 'true', '--use-jdk-deflater', 'true', *args]


def definitions():
    workflows = []
    schema = dict(schema=1, category='Variant calling', citations=[
        dict(text='Benjamin et al. (2019). Calling somatic SNVs and indels with Mutect2.', url='https://doi.org/10.1101/861054'),
        dict(text='Van der Auwera and O\'Connor (2020). Genomics in the Cloud. GATK somatic short variant discovery.', url='https://gatk.broadinstitute.org/hc/en-us/articles/360035531132')], workflows={})
    for paired, resources in ((False,False), (True,False), (False,True), (True,True)):
        identity = ('tumor-normal' if paired else 'tumor-only') + ('-resources' if resources else '')
        label = 'Mutect2: '+('tumor + matched normal' if paired else 'tumor only') + (' + population/PoN' if resources else '')
        inputs = [field('tumor','Prepared tumor BAM',filter='Coordinate-sorted BAM|*.bam',help='One tumor sample per BAM. Prepare DNA alignments and mark duplicates before calling; assay-specific BQSR remains a separate preparation decision.'),
                  field('reference','Matching reference genome',filter='Uncompressed FASTA|*.fa;*.fasta;*.fna'),
                  field('targets','Calling intervals (BED3)',filter='BED intervals|*.bed',help='Zero-based, end-exclusive intervals. To call an entire reference, provide one full-length interval per contig. This also bounds local computation.'),
                  field('tumor-sample','Tumor sample name (BAM SM)',type='text',default='TUMOR',constraint='identifier',help='Must match the tumor BAM SM; use an ASCII identifier containing letters, digits, dot, underscore or hyphen.')]
        ports = [dict(id='tumor',type='bam',accepts=['bam'],manifestInputs=['tumor'],min=1,max=1,requiredState={'sort':'coordinate'},validation={'singleSample':True,'sampleParameter':'tumor-sample'}),
                 dict(id='reference',type='reference',accepts=['reference'],manifestInputs=['reference'],min=1,max=1,requiredState={'compression':'none'}),
                 dict(id='targets',type='bed',accepts=['bed'],manifestInputs=['targets'],min=1,max=1,validation={'minColumns':3,'referenceBounds':True})]
        if paired:
            inputs.insert(1,field('normal','Prepared matched-normal BAM',filter='Coordinate-sorted BAM|*.bam',**{'different-from':'tumor'},help='A separate BAM from the matched normal of the same individual. Workbench checks sample labels and file identity; it cannot establish donor matching.'))
            inputs.append(field('normal-sample','Normal sample name (BAM SM)',type='text',default='NORMAL',constraint='identifier',help='Must match the normal BAM SM and differ from the tumor sample name; use an ASCII identifier containing letters, digits, dot, underscore or hyphen.'))
            ports.insert(1,dict(id='normal',type='bam',accepts=['bam'],manifestInputs=['normal'],min=1,max=1,requiredState={'sort':'coordinate'},validation={'singleSample':True,'sampleParameter':'normal-sample'}))
        if resources:
            inputs += [field('germline-resource','Population germline AF resource',filter='VCF or compressed VCF|*.vcf;*.vcf.gz',help='GATK-compatible population VCF with INFO/AF for the identical reference assembly. It is staged and indexed locally.'),
                       field('panel-of-normals','Panel of normals (PoN)',filter='VCF or compressed VCF|*.vcf;*.vcf.gz',help='A compatible precomputed Mutect2 panel of normals for the assay/reference. No resources are downloaded during analysis.')]
            for name in ('germline-resource','panel-of-normals'):
                port=dict(id=name,type='vcf',accepts=['vcf','vcf-pass'],manifestInputs=[name],min=1,max=1)
                if name=='germline-resource':port['validation']={'requiredInfoFields':[{'id':'AF','number':'A','type':'Float'}]}
                ports.append(port)
        inputs += [number('memory','Maximum Java heap (MiB)',2048,512,65536,help='Additional memory is needed outside the Java heap. Pure-Java alignment likelihoods favor portability over native SIMD speed.'),
                   number('minimum-base-quality','Minimum base quality',10,6,93),
                   number('minimum-mapping-quality','Minimum read mapping quality',20,0,60),
                   number('max-reads-per-start','Maximum reads per alignment start',50,0,100000,help='GATK default is 50; zero disables this downsampling limit.'),
                   field('contamination','Previously estimated contamination fraction',type='text',default='0',help='A fraction from 0 to 1, for example 0.027 for 2.7%, used only by FilterMutectCalls. The exact entered number is retained. This pack does not estimate contamination; default zero is not a measurement.')]
        outputs = [artifact('variants','Filtered calls with all FILTER labels','variants.vcf.gz'),
                   artifact('variants-index','Filtered-call CSI index','variants.vcf.gz.csi'),
                   artifact('pass-variants','PASS calls','variants.pass.vcf.gz'),artifact('pass-index','PASS-call CSI index','variants.pass.vcf.gz.csi'),
                   artifact('unfiltered','Unfiltered Mutect2 candidates','unfiltered.vcf'),artifact('call-stats','Mutect2 calling statistics','unfiltered.vcf.stats'),
                   artifact('f1r2','Read orientation counts','f1r2.tar.gz'),artifact('orientation-priors','Learned orientation artifact priors','orientation-priors.tar.gz'),
                   artifact('filtering-stats','FilterMutectCalls statistics','filtering-stats.tsv'),
                   artifact('variant-stats','All-call summary','variant-stats.txt'),artifact('pass-stats','PASS-call summary','pass-stats.txt'),
                   artifact('filtered','Original FilterMutectCalls VCF','filtered.vcf',False),
                   artifact('reference','Private reference','reference.fa',False),artifact('reference-index','Reference FAI','reference.fa.fai',False),artifact('reference-dict','Reference dictionary','reference.dict',False),
                   artifact('tumor-copy','Private tumor BAM','tumor.bam',False),artifact('tumor-index','Private tumor BAI','tumor.bam.bai',False)]
        steps = [dict(id='copy-reference',label='Stage a private reference',kind='copy',source='{input:reference}',destination='reference'),
                 execute('index-reference','Index the private reference','samtools',['faidx','{output:reference}'],produces=['reference-index']),
                 execute('reference-dictionary','Create the reference sequence dictionary','samtools',['dict','{output:reference}'],stdout='reference-dict'),
                 dict(id='copy-tumor',label='Stage a private tumor BAM',kind='copy',source='{input:tumor}',destination='tumor-copy'),
                 execute('index-tumor','Index the private tumor BAM','samtools',['index','-b','{output:tumor-copy}','{output:tumor-index}'],produces=['tumor-index'])]
        call = ['-R','{output:reference}','-I','{output:tumor-copy}','-L','{input:targets}',
                '-O','{output:unfiltered}','--f1r2-tar-gz','{output:f1r2}',
                '--pair-hmm-implementation','LOGLESS_CACHING','--smith-waterman','JAVA',
                '--minimum-mapping-quality','{input:minimum-mapping-quality}','--min-base-quality-score','{input:minimum-base-quality}',
                '--max-reads-per-alignment-start','{input:max-reads-per-start}','--create-output-variant-index','false',
                '--add-output-vcf-command-line','false']
        if paired:
            outputs += [artifact('normal-copy','Private normal BAM','normal.bam',False),artifact('normal-index','Private normal BAI','normal.bam.bai',False)]
            steps += [dict(id='copy-normal',label='Stage a private normal BAM',kind='copy',source='{input:normal}',destination='normal-copy'),
                      execute('index-normal','Index the private normal BAM','samtools',['index','-b','{output:normal-copy}','{output:normal-index}'],produces=['normal-index'])]
            call += ['-I','{output:normal-copy}','--normal-sample','{input:normal-sample}']
        if resources:
            for name,leaf in [('germline-resource','germline.vcf.gz'),('panel-of-normals','pon.vcf.gz')]:
                outputs += [artifact(name,'Private '+name,leaf,False),artifact(name+'-index','Private '+name+' index',leaf+'.tbi',False)]
                steps += [execute('stage-'+name,'Stage and compress '+name,'bcftools',['view','-Oz','-o','{output:'+name+'}','{input:'+name+'}'],produces=[name]),
                          execute('index-'+name,'Index '+name,'bcftools',['index','--tbi','{output:'+name+'}'],produces=[name+'-index'])]
                call += ['--'+name,'{output:'+name+'}']
        steps += [execute('call','Call candidates with GATK Mutect2','java',java_args('Mutect2',call),produces=['unfiltered','call-stats','f1r2']),
                  execute('orientation','Learn the read orientation artifact model','java',java_args('LearnReadOrientationModel',['-I','{output:f1r2}','-O','{output:orientation-priors}']),produces=['orientation-priors']),
                  execute('filter','Filter Mutect2 candidates','java',java_args('FilterMutectCalls',['-R','{output:reference}','-V','{output:unfiltered}','--stats','{output:call-stats}','--orientation-bias-artifact-priors','{output:orientation-priors}',
                    '--contamination-estimate','{input:contamination}','--filtering-stats','{output:filtering-stats}','-O','{output:filtered}','--create-output-variant-index','false','--add-output-vcf-command-line','false']),produces=['filtered','filtering-stats']),
                  execute('compress','Compress filtered calls preserving records and annotations','bcftools',['view','-Oz','-o','{output:variants}','{output:filtered}'],produces=['variants']),
                  execute('index','Index filtered calls','bcftools',['index','--csi','{output:variants}'],produces=['variants-index']),
                  execute('pass','Export PASS records separately','bcftools',['view','-f','PASS','-Oz','-o','{output:pass-variants}','{output:variants}'],produces=['pass-variants']),
                  execute('pass-index','Index PASS calls','bcftools',['index','--csi','{output:pass-variants}'],produces=['pass-index']),
                  execute('statistics','Summarize all calls','bcftools',['stats','{output:variants}'],stdout='variant-stats'),
                  execute('pass-statistics','Summarize PASS calls','bcftools',['stats','{output:pass-variants}'],stdout='pass-stats')]
        workflows.append(workflow(identity,label,'Somatic SNV/indel candidates with GATK 4.7.0.0, read-orientation modeling and FilterMutectCalls; '+('matched tumor/normal.' if paired else 'tumor-only; germline variants may remain.'),inputs,outputs,steps))
        descriptors=[]
        for record in outputs:
            name=record['id'];state={}
            if name=='reference':kind='reference';state={'compression':'none'}
            elif name.endswith('-copy'):kind='bam';state={'sort':'coordinate'}
            elif name in ('variants','pass-variants','unfiltered','filtered','germline-resource','panel-of-normals'):
                kind='vcf-pass' if name=='pass-variants' else 'vcf'
                state={'compression':'none' if name in ('unfiltered','filtered') else 'bgzf'}
                if name in ('variants','pass-variants'):state['selection']='PASS-only' if name=='pass-variants' else 'all-calls-with-filter-labels'
            elif name.endswith('-index') or name=='reference-dict':kind='index'
            elif name in ('f1r2','orientation-priors'):kind='file'
            else:kind='metrics'
            descriptors.append(dict(id=name,type=kind,manifestOutputs=[name],state=state))
        methods = ('Somatic SNV and indel candidates were called with GATK Mutect2 4.7.0.0 (Workbench local-path compatibility adaptation 1) from prepared coordinate-sorted DNA '+('tumor and matched-normal BAMs' if paired else 'tumor-only BAM')+' over the recorded BED intervals. '+
                   ('A population germline AF resource and panel of normals were supplied from local files.' if resources else 'No population germline resource or panel of normals was supplied.')+
                   ' Pure-Java LOGLESS_CACHING PairHMM, JAVA Smith-Waterman and JDK compression were used. Read-orientation counts were modeled with LearnReadOrientationModel and supplied to FilterMutectCalls. The recorded contamination fraction was supplied by the user (default zero); contamination was not estimated by this workflow. Duplicate marking and base-quality recalibration were not performed within this pack. Filtered records and annotations were preserved without normalization or multiallelic splitting, and all FILTER labels plus a separate record-level PASS subset were retained. Tumor-only results can include germline variants and do not alone establish somatic origin.')
        item=dict(ports=ports,outputs=descriptors,methods=methods,parameterRanges=[{'parameter':'contamination','min':0,'max':1}])
        if paired:item['parameterConstraints']=[{'left':'tumor-sample','operator':'!=','right':'normal-sample'}]
        schema['workflows'][identity]=item
    return workflows,schema


def build(folder):
    for name,pin in PINS.items():
        if digest(VENDOR/name)!=pin:raise ValueError('Pinned source differs: '+name)
    if digest(COMPAT/'gatk-path-compat.jar')!=COMPAT_SHA256:raise ValueError('Missing or changed compatibility JAR; run scripts/build_mutect2_compat.py')
    for name,pin in COMPAT_SOURCE_PINS.items():
        if digest(COMPAT/name)!=pin:raise ValueError('Compatibility source differs: '+name)
    inventory_path=THIRDPARTY/INVENTORY_NAME
    if digest(inventory_path)!=INVENTORY_SHA256:raise ValueError('Third-party source inventory differs')
    thirdparty=json.loads(inventory_path.read_text(encoding='utf-8'))
    seen=set()
    for item in thirdparty['files']:
        name=item['name'];source=THIRDPARTY/name
        if name in seen or Path(name).name!=name or '/' in name or '\\' in name:raise ValueError('Unsafe dependency filename')
        seen.add(name)
        if source.is_symlink() or source.stat().st_size!=item['bytes'] or digest(source)!=item['sha256']:raise ValueError('Dependency source differs: '+name)
    if folder.exists():raise ValueError('Output already exists: '+str(folder))
    for leaf in ('bin','runtime/java','assets','fixtures','licenses'):(folder/leaf).mkdir(parents=True,exist_ok=True)
    with zipfile.ZipFile(VENDOR/'OpenJDK17U-jre_x64_windows_hotspot_17.0.20.1_1.zip') as archive:
        for item in archive.infolist():
            if item.is_dir():continue
            relative=Path(*Path(item.filename).parts[1:])
            if relative.is_absolute() or '..' in relative.parts:raise ValueError('Unsafe runtime archive path')
            target=folder/'runtime/java'/relative;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(archive.read(item))
    with zipfile.ZipFile(VENDOR/'gatk-4.7.0.0.zip') as archive:
        (folder/'assets/gatk.jar').write_bytes(archive.read('gatk-4.7.0.0/gatk-package-4.7.0.0-local.jar'))
    shutil.copy2(COMPAT/'gatk-path-compat.jar',folder/'assets/gatk-path-compat.jar')
    for source,target in [('gatk-local-path.patch','gatk-local-path.patch'),('src/main/java/org/broadinstitute/hellbender/utils/io/IOUtils.java','IOUtils-workbench.java'),('compatibility-provenance.json','compatibility-provenance.json')]:
        shutil.copy2(COMPAT/source,folder/'licenses'/target)
    for name in ('gatk-4.7.0.0-source.tar.gz','OpenJDK17U-jdk-sources_17.0.20.1_1.tar.gz','Microsoft-VC-Runtime-2015-2022-License.docx'):
        shutil.copy2(VENDOR/name,folder/'licenses'/name)
    shutil.copy2(inventory_path,folder/'licenses'/INVENTORY_NAME)
    for item in thirdparty['files']:
        target=folder/'licenses'/item['name']
        if target.exists():raise ValueError('Dependency notice collision: '+item['name'])
        shutil.copy2(THIRDPARTY/item['name'],target)
    with tarfile.open(VENDOR/'gatk-4.7.0.0-source.tar.gz') as archive:
        for leaf in ('LICENSE.TXT','README.md','build.gradle'):
            member=next(m for m in archive.getmembers() if m.name.count('/')==1 and Path(m.name).name==leaf)
            (folder/'licenses'/('GATK-'+leaf)).write_bytes(archive.extractfile(member).read())
    notice_index={}
    with zipfile.ZipFile(folder/'assets/gatk.jar') as archive:
        for name in archive.namelist():
            leaf=Path(name).name.lower()
            if name.endswith('/') or leaf.endswith(('.java','.class')):continue
            if any(word in leaf for word in ('license','notice','copying')):
                dest='gatk-notice-'+hashlib.sha256(name.encode()).hexdigest()[:16]+'.txt'
                (folder/'licenses'/dest).write_bytes(archive.read(name));notice_index[dest]=name
    (folder/'licenses/gatk-notice-index.json').write_text(json.dumps(notice_index,indent=2)+'\n')
    microsoft=[]
    for p in sorted((folder/'runtime/java/bin').glob('*.dll')):
        if p.name.lower().startswith(('api-ms-win-','msvcp','vcruntime','ucrtbase')):microsoft.append(dict(path=p.relative_to(folder).as_posix(),sha256=digest(p)))
    (folder/'licenses/Microsoft-runtime-components.json').write_text(json.dumps({'source':'Unmodified components in the official Temurin '+JAVA+' Windows JRE.','license':'Microsoft proprietary runtime components, not OpenJDK GPLv2/ClassPath-Exception code.','officialLicense':'https://visualstudio.microsoft.com/license-terms/vs2022-cruntime/','originalDocument':'Microsoft-VC-Runtime-2015-2022-License.docx','components':microsoft},indent=2)+'\n')
    native_notices={}
    for base in (ROOT/'baselines/licenses/cosmopolitan-3.3.10',ROOT/'vendor-variant/licenses'):
        for p in sorted(base.rglob('*')):
            if p.is_file():
                name='native-'+hashlib.sha256(str(p.relative_to(ROOT)).encode()).hexdigest()[:16]+'.txt'
                shutil.copy2(p,folder/'licenses'/name);native_notices[name]=str(p.relative_to(ROOT))
    (folder/'licenses/native-notice-index.json').write_text(json.dumps(native_notices,indent=2)+'\n')
    for name,pin in NATIVE_PINS.items():
        source=ROOT/'baselines/bin'/(name+'-cosmo.exe')
        if digest(source)!=pin:raise ValueError('Native tool differs: '+name)
        shutil.copy2(source,folder/'bin'/(name+'.exe'))
    generate(folder/'fixtures')
    workflows,schema=definitions()
    (folder/'workbench-schema.json').write_text(json.dumps(schema,indent=2)+'\n',encoding='utf-8')
    (folder/'workbench-checks.json').write_text(json.dumps(self_checks(),indent=2)+'\n',encoding='utf-8')
    sections=['[pack]\nformat=2\nid=mutect2\nversion='+VERSION+'\nname=GATK Mutect2 somatic variants\nplatform=windows-x86_64\ndescription=GATK 4.7.0.0-workbench1 tumor-only or matched-normal calling, orientation modeling and FilterMutectCalls with a private Java 17 runtime.\ncolor=#7660A8\n']
    def section(name,values):sections.append('['+name+']\n'+'\n'.join(k+'='+str(v) for k,v in values.items() if k!='id')+'\n')
    tools={'java':('runtime/java/bin/java.exe',JAVA),'samtools':('bin/samtools.exe','1.24'),'bcftools':('bin/bcftools.exe','1.24')}
    for identity,(path,version) in tools.items():section('tool:'+identity,dict(path=path,version=version,sha256=digest(folder/path)))
    assets={'gatk':'assets/gatk.jar','gatk-compat':'assets/gatk-path-compat.jar','workbench-schema':'workbench-schema.json','workbench-checks':'workbench-checks.json'}
    for p in sorted((folder/'fixtures').iterdir()):assets['fixture-'+p.stem]='fixtures/'+p.name
    declared=set(assets.values())|{x[0] for x in tools.values()}
    for p in sorted((folder/'runtime').rglob('*')):
        path=p.relative_to(folder).as_posix()
        if p.is_file() and path not in declared:assets['runtime-'+hashlib.sha256(path.encode()).hexdigest()[:16]]=path
    for identity,path in assets.items():section('asset:'+identity,dict(path=path,sha256=digest(folder/path)))
    for wf in workflows:
        identity=wf['id'];section('workflow:'+identity,dict(name=wf['name'],description=wf['description'],inputs=','.join(x['id'] for x in wf['inputs']),outputs=','.join(x['id'] for x in wf['outputs']),steps=','.join(x['id'] for x in wf['steps'])))
        for kind,plural in [('input','inputs'),('output','outputs'),('step','steps')]:
            for record in wf[plural]:section(kind+':'+identity+':'+record['id'],record)
    (folder/'pack.ini').write_text('\n'.join(sections),encoding='utf-8')
    provenance=dict(packVersion=VERSION,sourcePins=PINS,gatkVersion=GATK,gatkWorkbenchAdaptation='4.7.0.0-workbench1',gatkJarSha256=digest(folder/'assets/gatk.jar'),compatibilityJarSha256=COMPAT_SHA256,thirdpartyInventorySha256=INVENTORY_SHA256,javaRuntime='Temurin '+JAVA,javaMode='LOGLESS_CACHING PairHMM; JAVA SmithWaterman; JDK compression; libdeflate and snappy disabled',nativeWindowsExecutedDuringBuild=False)
    (folder/'licenses/BUILD-PROVENANCE.json').write_text(json.dumps(provenance,indent=2)+'\n')
    (folder/'PACK-README.md').write_text(README,encoding='utf-8')
    files=list(folder.rglob('*'));size=sum(p.stat().st_size for p in files if p.is_file())
    if len(files)>2000 or size>1024*1024*1024 or any(p.is_file() and p.stat().st_size>512*1024*1024 for p in files):raise ValueError('Pack exceeds 0.5.4 inventory budget')
    print(str(folder)+' — '+str(size)+' bytes, '+str(len(files))+' files/directories')
    return folder


README='''# GATK Mutect2 somatic variants

Pack 0.5.4 requires Native Workbench 0.5.4 or newer. GATK 4.7.0.0-workbench1 runs with the complete private Temurin 17.0.20.1+1 Windows x64 JRE. The upstream local JAR is unchanged; a small compatibility JAR overrides one IOUtils local-path conversion method so temporary paths retain spaces, Unicode and native Windows drive/UNC syntax. Variant-calling algorithms and model parameters are unchanged by this adaptation. The exact source patch, complete modified Java source, compiler pin and reproduction recipe accompany the pack. No system Java installation, Docker, WSL, browser or network transfer is required for analysis.

Four operations support tumor-only and tumor plus matched normal, each with or without local population germline AF and panel-of-normals resources. Provide prepared coordinate-sorted, single-sample DNA BAMs with matching read-group SM labels, the exact uncompressed reference FASTA, and nonempty BED3 calling intervals. Sample SM names must be ASCII identifiers (letters, digits, dot, underscore or hyphen) because upstream VCF sample-header serialization does not reliably preserve arbitrary Unicode. Normal and tumor sample names and input files must differ. The software checks labels and file identity; it cannot establish that donors are matched. Full-contig BED intervals can cover an entire reference; pure-Java execution can be considerably slower than native SIMD Linux GATK and requires adequate RAM and disk space. The heap setting is not a total process RAM limit.

The pack stages private reference/BAM/resource copies and makes fresh indexes without changing inputs. BAM and resource indexes use BAI/TBI and their coordinate limits apply. Header contig/length/MD5 checks are used where available; a header lacking reference MD5 cannot establish reference sequence identity. Resource VCFs must use the identical assembly/contigs. The population resource requires INFO/AF. Resource operations require both the population resource and a precomputed Mutect2 panel of normals; creating a PoN is not included.

Every operation runs Mutect2 with LOGLESS_CACHING PairHMM and JAVA Smith-Waterman, collects F1R2 counts, learns an orientation artifact model with LearnReadOrientationModel, and applies FilterMutectCalls. JDK compression is explicit, HTSJDK libdeflate and Snappy are disabled, and the pack does not depend on GATK platform-specific native acceleration. The sample labels validated against BAM headers are authoritative; the deprecated Mutect2 --tumor-sample argument is not needed for a single tumor.

The primary result is the complete filtered VCF with original FILTER/allele annotations. A separate record-level PASS VCF and CSI indexes are supplied. Records are compressed without normalization or splitting multiallelic alleles, preserving GATK allele-specific annotations. Inspect AS_FilterStatus when interpreting multiallelic records. Unfiltered candidates, Mutect2 stats, F1R2 counts, learned priors, filtering statistics, command logs, methods and BCFtools summaries are retained. The optional GATKCommandLine VCF header is disabled because upstream serializes non-ASCII paths inconsistently; complete exact command provenance remains in the Workbench run report. An unfiltered candidate is not an accepted somatic call.

Duplicate marking and base-quality score recalibration are preparation steps outside this pack. The contamination field accepts a previously estimated fraction for FilterMutectCalls; default zero is not a measurement. GetPileupSummaries/CalculateContamination, segmentation, PoN generation, structural variants and clinical validation are not provided. Tumor-only calling can retain germline variants, especially without a population resource; it does not establish somatic status by itself.

All subprocesses receive explicit argument arrays. Java startup injection variables are removed by Workbench, attach/performance-data facilities are disabled, and Java temporary files remain in the run folder. No shell launcher or GATK Python wrapper is used. Pinned synthetic scientific checks cover somatic SNVs/indels, matched-normal germline rejection, resources and no-call intervals. Linux scientific execution of the pinned JAR and Windows PE/import validation are separate from execution on a real Windows machine. Run File > Check installation on Windows before analysis.

GATK is distributed under Apache License 2.0 and its bundled dependencies retain their individual licenses/notices inside the unchanged JAR and copied under licenses. Complete GATK and OpenJDK corresponding sources accompany the pack. OpenJDK is GPLv2 with the Classpath Exception; Microsoft VC runtime files within the official Windows JRE are separate proprietary Microsoft components with their original terms and inventory supplied. SAMtools, BCFtools, HTSlib and Cosmopolitan notices are included. Build/download pins are in licenses/BUILD-PROVENANCE.json and source scripts/prepare_mutect2_pack.py and fetch_mutect2_vendor.py.

Project: https://github.com/broadinstitute/gatk
Mutect2 methods: https://doi.org/10.1101/861054
'''


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,default=ROOT/'packs/mutect2-0.5.4')
    build(parser.parse_args().output.resolve())
