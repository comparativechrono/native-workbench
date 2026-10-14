#!/usr/bin/env python3
"""Build an optional SnpEff/SnpSift 5.4c pack, with private Temurin Java21."""
import argparse,gzip,hashlib,io,json,os,shutil,subprocess,sys,tarfile,uuid,zipfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'desktop'))
from prepare_modular_packs import field,number,artifact,execute,workflow
from fetch_snpeff_build_inputs import recover,sha,PINS
VERSION='1.0.0';JRE='OpenJDK21U-jre_x64_windows_hotspot_21.0.9_10.zip';JDK='OpenJDK21U-jdk_x64_linux_hotspot_21.0.9_10.tar.gz'
CITATIONS=[dict(text='Cingolani P et al. (2012). A program for annotating and predicting the effects of single nucleotide polymorphisms, SnpEff. Fly 6(2):80–92.',url='https://doi.org/10.4161/fly.19695'),dict(text='Cingolani P et al. (2012). Using Drosophila melanogaster as a model for genotoxic chemical mutational studies with a new program, SnpSift. Frontiers in Genetics 3:35.',url='https://doi.org/10.3389/fgene.2012.00035')]
def dump(p,obj):Path(p).write_text(json.dumps(obj,indent=2)+'\n',encoding='utf-8')
def copy(src,dst):
    dst=Path(dst);dst.parent.mkdir(parents=True,exist_ok=True);before=sha(src)
    with Path(src).open('rb') as inp,dst.open('xb') as out:
        while block:=inp.read(1048576):out.write(block)
    if sha(dst)!=before or sha(src)!=before:raise ValueError('Changed copy: '+str(src))
def zipfiles(p,items):
    with zipfile.ZipFile(p,'x',compression=zipfile.ZIP_DEFLATED,compresslevel=9) as z:
        for name,data in sorted(items):
            info=zipfile.ZipInfo(name,(2026,10,4,0,0,0));info.compress_type=zipfile.ZIP_DEFLATED;info.external_attr=0o100644<<16;z.writestr(info,data)
def definitions():
    workflows=[];schemas={}
    vcf=lambda key,label:field(key,label,filter='VCF variants|*.vcf;*.vcf.gz|All files|*.*',help='Ordinary small-variant VCF, plain/gzip; symbolic alleles, gVCF and BCF are rejected. Match assembly and normalize alleles before database annotation.')
    memory=number('memory','Maximum Java heap (MiB)',4096,512,65536,help='Heap cap for one process, plus JVM overhead. Human annotations often require at least 4 GiB; reference staging also needs local disk space.')
    entries=[('build-database','SnpEff: build local annotation database','Build a reusable checked database from matching local FASTA, gene annotation and CDS sequences.',
        [field('reference','Reference genome FASTA',filter='Uncompressed FASTA|*.fa;*.fasta;*.fna|All files|*.*'),field('annotation','Gene annotation GFF3 or GTF',filter='Gene annotation|*.gff;*.gff3;*.gtf;*.gz|All files|*.*'),field('cds','Matching CDS FASTA',filter='CDS FASTA|*.fa;*.fasta;*.fna;*.gz|All files|*.*',help='Transcript IDs must match the annotation. Upstream CDS checks use zero tolerated mismatches; supply the matching annotated transcript release.'),field('format','Gene annotation format','choice',default='gff3',choices='gff3:GFF3|gtf22:GTF 2.2'),field('assembly','Assembly/database ID','text',help='Stable assembly version, letters/digits/dot/underscore/dash, starting with a letter. Do not reuse a name for different sequence bytes.'),field('release','Annotation release','text',help='Record the actual source release/version, not merely the species name.'),field('genetic-code','Genetic code','choice',default='Standard',choices='Standard:Standard nuclear|Bacterial_and_Plant_Plastid:Bacterial and plant plastid|Vertebrate_Mitochondrial:Vertebrate mitochondrial',help='Default code for the resource; the explicit mitochondrial-contig selector can override individual contigs.'),field('mitochondrial','Vertebrate mitochondrial contigs (or none)','text',default='none',help='Comma-separated exact reference names, e.g. chrM or MT. These contigs use Vertebrate_Mitochondrial; all other contigs use the default code. Confirm organism/code, do not guess from a contig name.'),memory],
        [('reference','reference'),('annotation','file'),('cds','file')],['reference','annotation','cds','format','assembly','release','genetic-code','mitochondrial'],True,
        'A local SnpEff 5.4c annotation database was built from the selected reference FASTA, gene annotation and matching CDS release using the recorded default genetic code and explicit per-contig mitochondrial overrides. Supplied CDS sequences were compared at zero tolerated mismatch; separate protein comparison was disabled. This checks the supplied CDS set, not annotation completeness. Reference and annotation hashes, source release and database inventory were retained in the reusable resource.'),
      ('annotate','SnpEff: annotate variant consequences','Predict variant consequences using an explicitly selected local versioned database ZIP.',
        [vcf('variants','Variants VCF'),field('database','Workbench SnpEff database ZIP',filter='SnpEff resource ZIP|*.zip|All files|*.*',help='Use Build local annotation database or the documented offline converter for a trusted upstream database. This is a versioned resource, not a tool pack ZIP.'),number('upstream','Upstream/downstream distance (bases)',5000,0,100000),number('splice','Splice-site size (bases)',2,1,20),memory],
        [('variants','vcf'),('database','file')],['variants','database','upstream','splice'],False,
        'Small variants were annotated using unmodified SnpEff 5.4c and the selected versioned local annotation database. VCF REF alleles were checked against the bundled reference and inputs already carrying ANN were rejected. All database transcripts were considered, with the recorded upstream/downstream and splice-site distances and upstream HGVS behavior. Loci, alleles, filters and genotypes were retained; numeric QUAL formatting may change. ANN consequences are predictions, not pathogenicity classifications. LOF/NMD tags and remote statistics reports were disabled.'),
      ('annotate-local','SnpSift: annotate from a local VCF','Copy selected INFO annotations by allele matching from a local VCF database.',
        [vcf('variants','Variants VCF'),vcf('annotations','Local annotation VCF'),field('info','INFO fields to copy','text',default='AF',help='Comma-separated declared INFO IDs, up to 32; copied with DB_ prefix. Existing DB_ output fields are rejected.'),field('assembly','Shared reference assembly','text',help='Confirm that both VCFs use this exact assembly and contig naming; no liftover is performed. Normalize/split multiallelic records before this operation.'),memory],
        [('variants','vcf'),('annotations','vcf')],['variants','annotations','info','assembly'],False,
        'Selected INFO fields were transferred from the chosen local VCF with SnpSift 5.4c, matching chromosome, position and alleles. The matching assembly was declared by the user; no liftover or external sequence-reference verification was performed. Copied INFO fields received a DB_ prefix, original IDs and genotypes were retained, and inputs were privately staged before upstream indexing. Both datasets require matching assembly/contig names and normalized biallelic records; absence of an annotation is not evidence of absence in a population.'),
      ('filter-impact','SnpSift: select a consequence impact','Select complete VCF records with any ANN entry in one chosen impact class.',
        [vcf('variants','SnpEff-annotated variants VCF'),field('impact','Exact predicted impact','choice',default='HIGH',choices='HIGH:HIGH|MODERATE:MODERATE|LOW:LOW|MODIFIER:MODIFIER'),memory],
        [('variants','vcf')],['variants','impact'],False,
        'SnpSift 5.4c selected complete VCF records where any SnpEff ANN allele/transcript entry matched the recorded exact impact class. All alleles and genotypes of retained records remained, including alleles with other impacts; existing FILTER labels were not converted to PASS. Consequence impact alone does not establish pathogenicity or experimental validity. Empty selections were retained as valid header-only VCFs.')]
    for identity,title,description,fields,ports,args,build,methods in entries:
        outputs=[artifact('database' if build else 'variants','Versioned database ZIP' if build else 'Variants VCF','result/database.zip' if build else 'result/variants.vcf'),artifact('provenance','Resource and command provenance','result/provenance.json'),artifact('log','Upstream diagnostic log','result/upstream.log',nonempty=False)]
        command=['-Xms32m','-Xmx512m','-XX:+ExitOnOutOfMemoryError','-XX:+DisableAttachMechanism','-XX:-UsePerfData','-Djava.awt.headless=true','-Dfile.encoding=UTF-8','-cp','{asset:adapter};{asset:snpeff}','WorkbenchSnpEff',identity,'{asset:snpeff}','{asset:snpsift}','{asset:config}','{run}/result','{input:memory}']+['{input:'+key+'}' for key in args]
        workflows.append(workflow(identity,title,description,fields,outputs,[execute('run','Run offline annotation operation','java',command,produces=[x['id'] for x in outputs])]))
        products=[dict(id='database' if build else 'variants',type='file' if build else 'vcf',manifestOutputs=['database' if build else 'variants'])]+[dict(id=x,type='metrics',manifestOutputs=[x]) for x in ('provenance','log')]
        if not build:products[0]['propagateStateFrom']='variants'
        schemas[identity]=dict(ports=[dict(id=k,type=t,manifestInputs=[k],min=1,max=1) for k,t in ports],outputs=products,methods=methods,pathPolicy=dict(asciiOnly=True,forbiddenCharacters=[';']))
    return workflows,dict(schema=1,category='Variant annotation',citations=CITATIONS,workflows=schemas)
def fixtures(folder):
    folder.mkdir(parents=True,exist_ok=True);cds='ATGGCTGAACAATTTGGTAAGCCCGACTAA';seq='A'*30+cds+'A'*32
    (folder/'reference.fa').write_text('>chrSynthetic\n'+seq+'\n');(folder/'cds.fa').write_text('>tx1\n'+cds+'\n')
    (folder/'genes.gff').write_text('##gff-version 3\n'+''.join('chrSynthetic\tfixture\t'+t+'\t31\t60\t.\t+\t'+phase+'\t'+attrs+'\n' for t,phase,attrs in [('gene','.','ID=gene1;Name=Example'),('mRNA','.','ID=tx1;Parent=gene1'),('exon','.','ID=exon1;Parent=tx1'),('CDS','0','ID=cds1;Parent=tx1')]))
    header='##fileformat=VCFv4.2\n##reference=wbSynthetic1\n##contig=<ID=chrSynthetic,length=92>\n##FORMAT=<ID=GT,Number=1,Type=String,Description="Genotype">\n#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tSample1\n'
    records='chrSynthetic\t35\tmissense\tC\tT\t60\tPASS\t.\tGT\t0/1\nchrSynthetic\t36\tsynonymous\tT\tC\t60\tPASS\t.\tGT\t1/1\nchrSynthetic\t40\tstop\tC\tT\t60\tPASS\t.\tGT\t0/1\n'
    (folder/'variants.vcf').write_text(header+records)
    with (folder/'variants.vcf.gz').open('wb') as raw:
        with gzip.GzipFile(filename='',mode='wb',fileobj=raw,mtime=0) as z:z.write((header+records).encode())
    (folder/'annotations.vcf').write_text('##fileformat=VCFv4.2\n##reference=wbSynthetic1\n##contig=<ID=chrSynthetic,length=92>\n##INFO=<ID=AF,Number=A,Type=Float,Description="Synthetic allele frequency">\n#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\nchrSynthetic\t35\trsWrongAllele\tC\tG\t.\tPASS\tAF=0.9\nchrSynthetic\t36\trsSynonymous\tT\tC\t.\tPASS\tAF=0.2\nchrSynthetic\t40\trsStop\tC\tT\t.\tPASS\tAF=0.01\n')
    dump(folder/'truth.json',dict(assembly='wbSynthetic1',annotationRelease='fixture-v1',referenceLength=92,cds=cds,translation='MAEQFGKPD*',variants=[dict(pos=35,change='GCT>GTT',effect='missense_variant',impact='MODERATE',protein='p.Ala2Val',genotype='0/1'),dict(pos=36,change='GCT>GCC',effect='synonymous_variant',impact='LOW',protein='p.Ala2Ala',genotype='1/1'),dict(pos=40,change='CAA>TAA',effect='stop_gained',impact='HIGH',protein='p.Gln4*',genotype='0/1')],purpose='Independent codon-table expectations; synthetic software regression, not clinical validation.'))
def checks():
    return dict(schema=1,checks=[
      dict(id='build-known-cds',workflow='build-database',params={'format':'gff3','assembly':'wbSynthetic1','release':'fixture-v1','genetic-code':'Standard','mitochondrial':'none','memory':512},inputs={k:[{k:'fixture-'+k}] for k in ('reference','annotation','cds')},expect=[dict(output='provenance',kind='text',contains=['"assembly": "wbSynthetic1"','"snpEffVersion": "5.4c"','"success": true']),dict(output='log',kind='text',contains=['OK: 1','Errors: 0'])]),
      dict(id='known-codon-consequences',workflow='annotate',params={'upstream':5000,'splice':2,'memory':512},inputs={'variants':[{'variants':'fixture-variants-gz'}],'database':[{'database':'fixture-database'}]},expect=[dict(output='variants',kind='vcf',records=3,samples=['Sample1'],contains=['T|missense_variant|MODERATE|','C|synonymous_variant|LOW|','T|stop_gained|HIGH|','p.Ala2Val','p.Ala2Ala','p.Gln4*'],variants=[dict(chrom='chrSynthetic',pos=p,genotypes={'Sample1':g}) for p,g in [(35,'0/1'),(36,'1/1'),(40,'0/1')]])]),
      dict(id='local-allele-specific-info',workflow='annotate-local',params={'info':'AF','assembly':'wbSynthetic1','memory':512},inputs={'variants':[{'variants':'fixture-variants'}],'annotations':[{'annotations':'fixture-annotations'}]},expect=[dict(output='variants',kind='vcf',records=3,samples=['Sample1'],contains=['DB_AF=0.2','DB_AF=0.01'],variants=[dict(chrom='chrSynthetic',pos=35,info={}),dict(chrom='chrSynthetic',pos=36,info={'DB_AF':'0.2'}),dict(chrom='chrSynthetic',pos=40,info={'DB_AF':'0.01'})],absentVariants=[dict(chrom='chrSynthetic',pos=35,info={'DB_AF':'0.9'})])]),
      dict(id='select-high-impact',workflow='filter-impact',params={'impact':'HIGH','memory':512},inputs={'variants':[{'variants':'fixture-annotated'}]},expect=[dict(output='variants',kind='vcf',records=1,samples=['Sample1'],variants=[dict(chrom='chrSynthetic',pos=40,ref='C',alt='T',filter='PASS',genotypes={'Sample1':'0/1'})])])])
def prepare(cache,destination,jdk=None):
    recover(cache,False)
    if destination.exists() and any(destination.iterdir()):raise ValueError('Destination must be empty')
    for n in ('assets','runtime/java','licenses','fixtures'):(destination/n).mkdir(parents=True,exist_ok=True)
    if jdk is None:
        root=cache/'jdk';jdk=root/'jdk-21.0.9+10'
        if not jdk.exists():
            root.mkdir(exist_ok=True)
            with tarfile.open(cache/JDK) as t:t.extractall(root,filter='data')
    javac=jdk/'bin/javac';java=jdk/'bin/java';env=dict(os.environ,LD_LIBRARY_PATH=str(jdk/'lib')+':'+str(jdk/'lib/server'))
    for k in ('JAVA_TOOL_OPTIONS','JDK_JAVA_OPTIONS','_JAVA_OPTIONS','CLASSPATH'):env.pop(k,None)
    cv=subprocess.run([str(javac),'-version'],capture_output=True,text=True,check=True,env=env).stdout.strip()
    if cv!='javac 21.0.9':raise ValueError('Requires pinned javac21.0.9: '+cv)
    with zipfile.ZipFile(cache/'snpEff_v5_4c_core.zip') as z:
        for name,dest in [('snpEff.jar','assets/snpEff.jar'),('SnpSift.jar','assets/SnpSift.jar'),('snpEff.config','assets/snpEff.config'),('LICENSE.md','licenses/SnpEff-MIT.txt')]:
            data=z.read('snpEff/'+name)
            if name.endswith('.jar'):
                with zipfile.ZipFile(io.BytesIO(data)) as original:
                    omitted=[n for n in original.namelist() if n.startswith('javax/vecmath/')]
                    retained=[(n,original.read(n)) for n in original.namelist() if not n.endswith('/') and n not in omitted]
                    zipfiles(destination/dest,retained)
                    with zipfile.ZipFile(destination/dest) as repacked:
                        if set(repacked.namelist())!={n for n,_ in retained}:raise ValueError('Repacked JAR inventory differs')
                        for n,b in retained:
                            if repacked.read(n)!=b:raise ValueError('Upstream class/resource changed: '+n)
                    dump(destination/'licenses'/(name+'-packaging.json'),dict(sourceCoreArchiveSha256=sha(cache/'snpEff_v5_4c_core.zip'),upstreamJarSha256=hashlib.sha256(data).hexdigest(),packagedJarSha256=sha(destination/dest),retainedEntries=len(retained),allRetainedEntryBytesIdentical=True,omissionReason='Unused legacy Sun Binary Code licensed javax.vecmath1.3.1; structural/PDB operations are not exposed.',omitted=[dict(path=n,sha256=hashlib.sha256(original.read(n)).hexdigest()) for n in omitted if not n.endswith('/')]))
            else:
                (destination/dest).write_bytes(data)
                if hashlib.sha256(data).hexdigest()!=sha(destination/dest):raise ValueError('Config extraction differs')
    classes=cache/'compiled-adapter'
    if classes.exists():shutil.rmtree(classes)
    classes.mkdir();subprocess.run([str(javac),'-proc:none','--release','21','-encoding','UTF-8','-cp',str(destination/'assets/snpEff.jar'),'-d',str(classes),str(ROOT/'tools/snpeff/WorkbenchSnpEff.java')],env=env,check=True)
    zipfiles(destination/'assets/workbench-snpeff.jar',[(p.relative_to(classes).as_posix(),p.read_bytes()) for p in classes.rglob('*.class')])
    with zipfile.ZipFile(cache/JRE) as z:
        for item in z.infolist():
            if item.is_dir():continue
            rel=Path(*Path(item.filename).parts[1:]);dest=destination/'runtime/java'/rel;dest.parent.mkdir(parents=True,exist_ok=True)
            with z.open(item) as src,dest.open('xb') as dst:
                h=hashlib.sha256()
                while block:=src.read(1048576):dst.write(block);h.update(block)
            if sha(dest)!=h.hexdigest():raise ValueError('Runtime extraction differs: '+str(rel))
    for row in PINS:
        if row['name'] in (JRE,JDK,'snpEff_v5_4c_core.zip'):continue
        copy(cache/row['name'],destination/'licenses'/row['name'])
    for source in ['LICENSE','tools/snpeff/WorkbenchSnpEff.java','tools/snpeff/build-inputs.json','tools/snpeff/prepare_database_resource.py','scripts/fetch_snpeff_build_inputs.py','scripts/prepare_snpeff_pack.py']:
        copy(ROOT/source,destination/'licenses'/Path(source).name)
    notices=[]
    for jar in ('snpEff.jar','SnpSift.jar'):
        with zipfile.ZipFile(destination/'assets'/jar) as z:
            for name in z.namelist():
                if not name.endswith('/') and ('license' in Path(name).name.lower() or 'notice' in Path(name).name.lower() or 'copying' in Path(name).name.lower()):notices.append((jar+'/'+name,z.read(name)))
    zipfiles(destination/'licenses/upstream-shaded-notices.zip',notices)
    fixtures(destination/'fixtures')
    # Fixture executes unchanged upstream algorithms with the matching pinned Linux Java.
    def invoke(op,output,args):
        command=[str(java),'-Xmx512m','-cp',os.pathsep.join(str(destination/'assets'/n) for n in ('workbench-snpeff.jar','snpEff.jar')),'WorkbenchSnpEff',op]+[str(destination/'assets'/n) for n in ('snpEff.jar','SnpSift.jar','snpEff.config')]+[str(output),'512']+list(map(str,args));subprocess.run(command,env=env,check=True)
    fixture_build=cache/('fixture-build-'+uuid.uuid4().hex)
    f=destination/'fixtures';invoke('build-database',fixture_build,[f/'reference.fa',f/'genes.gff',f/'cds.fa','gff3','wbSynthetic1','fixture-v1','Standard','none']);copy(fixture_build/'database.zip',f/'database.zip')
    ann=cache/('fixture-annotation-'+uuid.uuid4().hex)
    invoke('annotate',ann,[f/'variants.vcf',f/'database.zip',5000,2]);copy(ann/'variants.vcf',f/'annotated.vcf')
    dump(destination/'licenses/Microsoft-runtime-components.json',dict(origin=next(r['url'] for r in PINS if r['name']==JRE),licenseDocument='Microsoft-VC-Runtime-2015-2022-License.docx',components=[dict(path=p.relative_to(destination).as_posix(),sha256=sha(p)) for p in (destination/'runtime/java/bin').glob('*.dll') if p.name.lower().startswith(('api-ms-win-','msvcp','vcruntime','ucrtbase'))]))
    workflows,schema=definitions();dump(destination/'workbench-schema.json',schema);dump(destination/'workbench-checks.json',checks())
    assets={'adapter':'assets/workbench-snpeff.jar','snpeff':'assets/snpEff.jar','snpsift':'assets/SnpSift.jar','config':'assets/snpEff.config','workbench-schema':'workbench-schema.json','workbench-checks':'workbench-checks.json'}
    for key,name in [('reference','reference.fa'),('annotation','genes.gff'),('cds','cds.fa'),('variants','variants.vcf'),('variants-gz','variants.vcf.gz'),('annotations','annotations.vcf'),('database','database.zip'),('annotated','annotated.vcf'),('truth','truth.json')]:assets['fixture-'+key]='fixtures/'+name
    for p in sorted((destination/'runtime/java').rglob('*')):
        if p.is_file() and p.relative_to(destination).as_posix()!='runtime/java/bin/java.exe':
            rel=p.relative_to(destination).as_posix();assets['runtime-'+hashlib.sha256(rel.encode()).hexdigest()[:16]]=rel
    sections=[]
    def section(name,values):sections.append('['+name+']\n'+'\n'.join(k+'='+str(v) for k,v in values.items() if k!='id' or name=='pack')+'\n')
    section('pack',dict(format=2,id='snpeff',version=VERSION,name='SnpEff and SnpSift',platform='windows-x86_64',color='#AB729E',description='Local variant consequence annotation, reusable checked databases, local VCF INFO annotation and bounded impact selection. Private Java21 included.'))
    section('tool:java',dict(path='runtime/java/bin/java.exe',version='Temurin-21.0.9+10',sha256=sha(destination/'runtime/java/bin/java.exe')))
    for key,name in assets.items():section('asset:'+key,dict(path=name,sha256=sha(destination/name)))
    for wf in workflows:
        section('workflow:'+wf['id'],dict(name=wf['name'],description=wf['description'],inputs=','.join(x['id'] for x in wf['inputs']),outputs=','.join(x['id'] for x in wf['outputs']),steps=','.join(x['id'] for x in wf['steps'])))
        for kind in ('input','output','step'):
            for item in wf[kind+'s']:section(kind+':'+wf['id']+':'+item['id'],item)
    (destination/'pack.ini').write_text('\n'.join(sections),encoding='utf-8');copy(ROOT/'docs/SNPEFF-PACK.md',destination/'PACK-README.md')
    dump(destination/'licenses/build-provenance.json',dict(schema=1,packId='snpeff',packVersion=VERSION,minAppVersion='0.6.0',upstreamVersion='5.4c',upstreamSourceCommit='0201ed20051d43628e51dcf48e774adac5b5e025',snpSiftSourceCommit='a9122d0283cad1475ec475b1623f87bbd8fbfec5',snpSiftSourceNote='SnpSift v5.4b source commit is the latest before upstream5.4c core build; SnpSift version string derives from SnpEff.',upstreamJarsModified=True,upstreamScientificClassesModified=False,containerModification="Only unused javax/vecmath entries omitted; all remaining class/resource bytes verified identical; structural/PDB commands unsupported",sourcePins=PINS,compiler=cv,compilerExecutableSha256=sha(javac),adapterSourceSha256=sha(ROOT/'tools/snpeff/WorkbenchSnpEff.java'),windowsExecutedDuringBuild=False,fixtureExecution='Linux Java21.0.9; synthetic database/ANN production, separate Windows installation checks required.'))
    sys.path.insert(0,str(ROOT/'workspace'));from catalog import load_pack
    pack=load_pack(destination/'pack.ini')
    return dict(packRoot=str(destination),packId='snpeff',packVersion=VERSION,manifestSha256=sha(destination/'pack.ini'),workflows=list(pack['workflows']),files=sum(1 for p in destination.rglob('*') if p.is_file()),expandedBytes=sum(p.stat().st_size for p in destination.rglob('*') if p.is_file()))
if __name__=='__main__':
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--cache',type=Path,default=ROOT/'build/snpeff-inputs');ap.add_argument('--destination',type=Path,default=ROOT/'packs/snpeff-1.0.0');ap.add_argument('--jdk',type=Path);a=ap.parse_args();print(json.dumps(prepare(a.cache.resolve(),a.destination.resolve(),a.jdk.resolve() if a.jdk else None),indent=2))
