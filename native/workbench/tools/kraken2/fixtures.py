#!/usr/bin/env python3
"""Construct truth independently, then build its real pinned upstream index."""
import argparse,gzip,json,random,subprocess
from pathlib import Path
def build(destination,binary):
 p=Path(destination).absolute();p.mkdir(parents=True,exist_ok=False);tax=p/'taxonomy';tax.mkdir()
 nodes=[(1,1,'no rank','root'),(2,1,'superkingdom','Bacteria'),(10,2,'genus','Synthetic genus'),(101,10,'species','Synthetic alpha'),(102,10,'species','Synthetic beta'),(20,2,'genus','Second genus'),(201,20,'species','Synthetic gamma')]
 (tax/'nodes.dmp').write_text(''.join(f'{i}\t|\t{pa}\t|\t{r}\t|\n' for i,pa,r,n in nodes),encoding='ascii',newline='\n')
 (tax/'names.dmp').write_text(''.join(f'{i}\t|\t{n}\t|\t\t|\tscientific name\t|\n' for i,pa,r,n in nodes),encoding='ascii',newline='\n')
 r=random.Random(742);seq=lambda n:''.join(r.choice('ACGT') for _ in range(n));shared=seq(400);refs={101:shared+seq(2600),102:shared+seq(2600),201:seq(3000)}
 (p/'reference.fa').write_text(''.join(f'>tax{i}\n{s}\n' for i,s in refs.items()),encoding='ascii',newline='\n')
 (p/'seqid2taxid.map').write_text(''.join(f'tax{i}\t{i}\n' for i in refs),encoding='ascii',newline='\n')
 reads=[]
 for taxid,count in [(101,12),(102,8),(201,5)]:
  for i in range(count):reads.append((f'taxon{taxid}_{i}',refs[taxid][600+30*i:750+30*i],taxid))
 for i in range(4):reads.append((f'shared_{i}',shared[40*i:40*i+150],10))
 for i in range(3):reads.append((f'unknown_{i}',seq(150),0))
 for name,mate in [('reads.fastq',None),('reads_1.fastq',1),('reads_2.fastq',2)]:
  text=''.join('@'+n+('' if mate is None else '/'+str(mate))+'\n'+s+'\n+\n'+'I'*len(s)+'\n' for n,s,t in reads)
  (p/name).write_bytes(text.encode('ascii'))
  with gzip.GzipFile(str(p/(name+'.gz')),'wb',mtime=0) as f:f.write(text.encode('ascii'))
 truth={'source':'Independent deterministic DNA construction, PRNG742. Three reference genomes; alpha/beta share400bp. Reads from unique species loci12/8/5, common genus loci4, independent absent DNA3. No human or patient data.','records':32,'length':150,'classified':29,'unclassified':3,'assignments':{n:t for n,s,t in reads},'directCounts':{'101':12,'102':8,'201':5,'10':4,'0':3}}
 (p/'truth.json').write_text(json.dumps(truth,indent=2)+'\n',encoding='utf-8',newline='\n')
 command=[str(Path(binary).absolute()),'-H',str(p/'hash.k2d'),'-t',str(p/'taxo.k2d'),'-o',str(p/'opts.k2d'),'-m',str(p/'seqid2taxid.map'),'-n',str(tax),'-k','35','-l','31','-c','50000','-p','2']
 with (p/'reference.fa').open('rb') as inp,(p/'build.log').open('wb') as log:subprocess.run(command,stdin=inp,stdout=log,stderr=log,check=True)
 (p/'build-command.json').write_text(json.dumps(command,indent=2)+'\n',encoding='utf-8',newline='\n')
 classifier=Path(binary).absolute().with_name('classify.exe' if Path(binary).suffix=='.exe' else 'classify')
 command=[str(classifier),'-H',str(p/'hash.k2d'),'-t',str(p/'taxo.k2d'),'-o',str(p/'opts.k2d'),'-p','2','-g','2','-R',str(p/'expected.report.tsv'),'-O',str(p/'expected.assignments.tsv'),str(p/'reads.fastq')]
 with (p/'classification.log').open('wb') as log:subprocess.run(command,stdout=log,stderr=log,check=True)
 observed={line.split('\t')[1]:int(line.split('\t')[2]) for line in (p/'expected.assignments.tsv').read_text().splitlines()}
 if observed!=truth['assignments']:raise ValueError('Upstream fixture classifications differ from independently constructed truth.')
 (p/'classification-command.json').write_text(json.dumps(command,indent=2)+'\n',encoding='utf-8',newline='\n')
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);p.add_argument('--builder',type=Path,required=True);a=p.parse_args();build(a.output,a.builder)
