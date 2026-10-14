#!/usr/bin/env python3
"""Prepare the independent mosdepth 0.3.14 pack for released Workbench 0.6.0."""
import argparse,json,sys,zipfile
from pathlib import Path
from fetch_mosdepth_build_inputs import ROOT,CACHE,SOURCES,sha,copy
sys.path.insert(0,str(ROOT/'desktop'));from prepare_modular_packs import field,number,artifact,execute,workflow
sys.path.insert(0,str(ROOT/'tools/mosdepth'));from fixtures import fixtures
VERSION='1.0.0';SAMTOOLS_SHA='49c2f16425d464e4ad1c1439d7a9e32a3b1c1bf8e5d54403778de610d2f440b3'
def dump(p,x):p.write_text(json.dumps(x,indent=2)+'\n',encoding='utf-8')
def definitions():
 workflows=[];schemas={}
 for target in (False,True):
  identity='targets' if target else 'coverage'
  inputs=[field('alignment','Coordinate-sorted DNA or RNA BAM',filter='BAM alignments|*.bam',help='Binary BAM with SO:coordinate and coordinate-sorted records. Multiple samples are aggregated. BAM reference dictionary defines denominators; no FASTA verification or CRAM support. A private full-size BAM copy and CSI index are made in this run.')]
  ports=[dict(id='alignment',label='Coordinate-sorted BAM',type='bam',accepts=['bam','bam-rna'],manifestInputs=['alignment'],min=1,max=1,requiredState={'sort':'coordinate'})]
  if target:
   inputs.append(field('regions','Target intervals (BED3 or BED4)',filter='Uncompressed BED|*.bed',help='Zero-based half-open BED, sorted in BAM dictionary order, nonoverlapping, in-bounds, with matching contig names. BED4 names retained; choose the correct assembly. No inferred reference download.'))
   ports.append(dict(id='regions',label='Target BED',type='bed',manifestInputs=['regions'],min=1,max=1))
  inputs += [number('mapq','Minimum mapping quality',0,0,255,help='Reads below this value are excluded; MAPQ 255 remains eligible. No base-quality filter: Q0 bases still count. RNA splice/deletion gaps do not contribute depth.'),field('exclude-flags','Exclude read flags','choice',default='1796',choices='1796:Unmapped secondary QC-failed duplicates|3844:Also exclude supplementary|772:Retain duplicate-marked reads',help='Default upstream mask 1796 retains supplementary alignments. Mask 3844 also removes them; 772 retains duplicates. Proper paired-read overlap is counted once in accurate mode.'),number('threads','Decompression threads',2,1,16,help='Threads accelerate BAM decompression. Coverage computation uses the upstream chromosome-sized array (about 4 bytes per longest contig base).')]
  inputs += [number('threshold-'+x,'Breadth threshold '+x,n,1,1000000,help='Three strictly increasing depth thresholds. Breadth is bases at or above the threshold divided by all bases in the stated reference/target.') for x,n in [('low',1),('middle',10),('high',20)]]
  outputs=[artifact('summary','Full BAM-reference and target depth/breadth','coverage.full-summary.tsv'),artifact('raw-summary','Raw mosdepth observed-contig summary','coverage.mosdepth.summary.txt'),artifact('distribution','Raw observed-contig cumulative distribution','coverage.mosdepth.global.dist.txt'),artifact('perbase','Upstream per-base coverage intervals (BGZF BED)','coverage.per-base.bed.gz'),artifact('perbase-index','Per-base CSI index','coverage.per-base.bed.gz.csi'),artifact('validation','Input and reference-boundary checks','input-validation.json')]
  if target:outputs += [artifact('regions','Mean depth per target (BGZF BED)','coverage.regions.bed.gz'),artifact('regions-index','Target depth CSI index','coverage.regions.bed.gz.csi'),artifact('thresholds','Bases at selected depths per target (BGZF BED)','coverage.thresholds.bed.gz'),artifact('thresholds-index','Threshold CSI index','coverage.thresholds.bed.gz.csi'),artifact('region-distribution','Raw observed-contig target distribution','coverage.mosdepth.region.dist.txt')]
  thresholds=['{input:threshold-'+x+'}' for x in ['low','middle','high']];by='{input:regions}' if target else 'none';stagedbed='{run}/targets.bed' if target else 'none'
  steps=[execute('quickcheck','Check BAM file integrity','samtools',['quickcheck','-v','{input:alignment}']),execute('validate','Validate and stage local BAM and target intervals','mosdepth-guard',['{input:alignment}','{run}/staged.bam',by,'{run}/targets.bed',*thresholds],stdout='validation'),execute('depth','Calculate accurate CIGAR and mate-overlap coverage','mosdepth',['--threads','{input:threads}','--mapq','{input:mapq}','--flag','{input:exclude-flags}',*(['--by',stagedbed,'--thresholds',','.join(thresholds)] if target else []),'{run}/coverage','{run}/staged.bam'],produces=[x['id'] for x in outputs if x['id'] not in ('validation','summary')]),execute('summarize','Summarize all BAM-reference bases including empty contigs','mosdepth-guard',['summary','{run}/staged.bam',stagedbed,'{output:perbase}','{output:summary}',*thresholds],produces=['summary'])]
  description=('Target-region mean depth and breadth with complete interval denominators.' if target else 'Coverage and breadth over every base in the BAM reference dictionary, including empty contigs.')+' Upstream coverage engine; aligned-base mode counts proper paired-read overlap once and excludes CIGAR deletion/splice gaps.'
  workflows.append(workflow(identity,'Target-region depth and breadth' if target else 'BAM-reference depth and breadth',description,inputs,outputs,steps))
  schemas[identity]={'ports':ports,'outputs':[dict(id=x['id'],label=x['label'],type='index' if x['id'].endswith('-index') else 'file' if x['id'] in ('perbase','regions','thresholds') else 'metrics',manifestOutputs=[x['id']]) for x in outputs],'pathPolicy':{'asciiOnly':True},'methods':'Coverage was calculated locally with mosdepth 0.3.14-workbench1 (unchanged coverage algorithm; HTSlib 1.23.1), using accurate CIGAR processing and proper-pair overlap correction. Mapping-quality cutoff, excluded SAM flag mask, decompression threads and three breadth thresholds were recorded. No base-quality, fragment-length or read-group filter was applied; all selected BAM samples were aggregated. CIGAR deletion/splice gaps were excluded; insert sequence did not contribute reference depth. BAM records and BED intervals were checked for coordinate order and reference bounds; a private CSI index was created. The primary Workbench summary was derived by length-weighted aggregation of upstream per-base coverage intervals across every BAM dictionary base (and every selected nonoverlapping BED base), including empty contigs. Breadth is bases with depth at least the recorded threshold divided by the full stated length. The original mosdepth summary/distributions were retained and exclude contigs without alignment records from their denominators. Reference identity was not verified against FASTA. RNA BAM coverage is genomic coverage, not gene-expression quantification.'}
 return workflows,{'schema':1,'category':'Quality control','citations':[{'text':'Pedersen BS and Quinlan AR (2018). Mosdepth: quick coverage calculation for genomes and exomes. Bioinformatics 34:867–868.','url':'https://doi.org/10.1093/bioinformatics/btx699'}],'workflows':schemas}
def checks():
 values=[]
 for op,mapq,flags,depthsum in [('coverage',0,1796,100),('targets',0,1796,100),('targets',20,3844,80),('targets',0,772,110)]:
  inputs={'alignment':[{'alignment':'fixture-bam'}]}
  if op=='targets':inputs['regions']=[{'regions':'fixture-regions'}]
  expected=[{'output':'summary','kind':'text','contains':['reference\tchr2\t50\t0\t0.000000\t0\t0.000000','reference-total\ttotal\t250\t'+str(depthsum)+'\t'+format(depthsum/250,'.6f')]},{'output':'perbase','kind':'text','contains':['chr1\t10\t20\t2\n','chr1\t55\t60\t0\n','chr1\t75\t85\t0\n','chr2\t0\t50\t0\n']},{'output':'validation','kind':'text','contains':['"valid":true','"bam_records":11','"coordinate_records_checked":true']}]
  if op=='targets':expected += [{'output':'thresholds','kind':'text','contains':['chr1\t0\t40\tpaired\t40\t10\t0\n','chr1\t180\t200\tempty\t0\t0\t0\n']},{'output':'regions','kind':'text','contains':['chr1\t0\t40\tpaired\t1.25\n','chr1\t180\t200\tempty\t0.00\n']}]
  values.append({'id':op+'-mapq-'+str(mapq)+'-flags-'+str(flags),'workflow':op,'params':{'mapq':mapq,'exclude-flags':str(flags),'threads':2,'threshold-low':1,'threshold-middle':2,'threshold-high':3},'inputs':inputs,'expect':expected})
 return {'schema':1,'checks':values}
def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--cache',type=Path,default=CACHE);p.add_argument('--build',type=Path,default=ROOT/'build/mosdepth-windows');p.add_argument('--destination',type=Path,default=ROOT/'packs/mosdepth-1.0.0');a=p.parse_args();dest=a.destination.resolve();cache=a.cache.resolve();build=a.build.resolve();record=json.loads((build/'build.json').read_text())
 if record['guardSha256']!=sha(ROOT/'tools/mosdepth/guard.cpp') or record['platform']!='windows-x86_64' or record['upstreamVersion']!='0.3.14':raise ValueError('Changed or wrong build')
 if dest.exists() and any(dest.iterdir()):raise ValueError('Destination must be new/empty')
 for directory in ['bin','fixtures','licenses']:(dest/directory).mkdir(parents=True,exist_ok=True)
 sections=[]
 def section(name,values):sections.append('['+name+']\n'+'\n'.join(k+'='+str(v) for k,v in values.items() if k!='id' or name=='pack')+'\n')
 section('pack',dict(format=2,id='mosdepth',version=VERSION,name='mosdepth coverage',platform='windows-x86_64',description='Accurate BAM coverage, target depth and breadth with explicit denominator and read-filter policies. Workbench 0.6.0 or newer.',color='#517A87'))
 for name in ['mosdepth.exe','mosdepth-guard.exe','libhts.dll']:
  if sha(build/name)!=record['files'][name]['sha256']:raise ValueError('Changed build executable '+name)
  copy(build/name,dest/'bin'/name)
  if name.endswith('.exe'):section('tool:'+name[:-4],dict(path='bin/'+name,version='0.3.14-workbench1' if name=='mosdepth.exe' else VERSION,sha256=sha(dest/'bin'/name)))
  else:section('asset:htslib',dict(path='bin/'+name,sha256=sha(dest/'bin'/name)))
 starter=cache/'starter.zip'
 if sha(starter)!=SOURCES['starter.zip'][1]:raise ValueError('Changed starter')
 with zipfile.ZipFile(starter) as z:
  prefix='native-workbench/packs/bam-0.4.0/'
  data=z.read(prefix+'bin/samtools.exe');(dest/'bin/samtools.exe').write_bytes(data)
  with zipfile.ZipFile(dest/'licenses/samtools-1.24-inherited-notices.zip','w',zipfile.ZIP_DEFLATED) as notices:
   for name in z.namelist():
    if name.startswith(prefix+'licenses/') and not name.endswith('/'):notices.writestr(name.removeprefix(prefix+'licenses/'),z.read(name))
 if sha(dest/'bin/samtools.exe')!=SAMTOOLS_SHA:raise ValueError('Changed SAMtools helper')
 section('tool:samtools',dict(path='bin/samtools.exe',version='1.24',sha256=SAMTOOLS_SHA))
 workflows,schema=definitions();dump(dest/'workbench-schema.json',schema);dump(dest/'workbench-checks.json',checks());fixtures(dest/'fixtures')
 for name,path in {'workbench-schema':'workbench-schema.json','workbench-checks':'workbench-checks.json','fixture-bam':'fixtures/coverage.bam','fixture-regions':'fixtures/targets.bed','fixture-empty-contig':'fixtures/empty-contig.bed','fixture-empty-bam':'fixtures/empty.bam','fixture-truth':'fixtures/truth.json'}.items():section('asset:'+name,dict(path=path,sha256=sha(dest/path)))
 for wf in workflows:
  section('workflow:'+wf['id'],dict(name=wf['name'],description=wf['description'],inputs=','.join(x['id'] for x in wf['inputs']),outputs=','.join(x['id'] for x in wf['outputs']),steps=','.join(x['id'] for x in wf['steps'])))
  for kind in ('input','output','step'):
   for item in wf[kind+'s']:section(kind+':'+wf['id']+':'+item['id'],item)
 (dest/'pack.ini').write_text('\n'.join(sections),encoding='utf-8')
 for name,(_,digest) in SOURCES.items():
  if name in ('starter.zip','llvm.tar.xz','nim.tar.xz','upstream-mosdepth'):continue
  if sha(cache/name)!=digest:raise ValueError('Changed source archive '+name)
  copy(cache/name,dest/'licenses'/name)
 for source in [ROOT/'tools/mosdepth/guard.cpp',ROOT/'tools/mosdepth/build.py',ROOT/'tools/mosdepth/fixtures.py',Path(__file__),ROOT/'scripts/fetch_mosdepth_build_inputs.py',ROOT/'LICENSE']:copy(source,dest/'licenses'/source.name)
 tc=next((cache/'llvm').iterdir());copy(tc/'LICENSE.TXT',dest/'licenses/LLVM-LICENSE.txt')
 for source in (tc/'x86_64-w64-mingw32/share/mingw32').glob('COPYING*'):copy(source,dest/'licenses'/source.name)
 copy(build/'workbench1.patch',dest/'licenses/workbench1.patch');dump(dest/'licenses/build-provenance.json',record);copy(ROOT/'docs/MOSDEPTH-PACK.md',dest/'PACK-README.md')
 sys.path.insert(0,str(ROOT/'workspace'));from catalog import load_pack;pack=load_pack(dest/'pack.ini');print(json.dumps({'pack':str(dest),'manifestSha256':sha(dest/'pack.ini'),'workflows':list(pack['workflows']),'checks':len(checks()['checks'])},indent=2))
if __name__=='__main__':main()
