"""Tiny synthetic BAM/BED truth independent of coverage executables (0-based coordinates)."""
import json,struct,zlib
from pathlib import Path
REFS=[('chr1',200),('chr2',50)]
ROWS=[('single',0,0,[(20,'M')],-1,0,60,40),('overlap',99,10,[(20,'M')],20,30,60,40),('overlap',147,20,[(20,'M')],10,-30,60,40),('deletion',0,50,[(5,'M'),(5,'D'),(5,'M')],-1,0,60,40),('splice',0,70,[(5,'M'),(10,'N'),(5,'M')],-1,0,60,40),('lowmapq',0,100,[(10,'M')],-1,0,10,40),('secondary',256,110,[(10,'M')],-1,0,60,40),('duplicate',1024,120,[(10,'M')],-1,0,60,40),('qcfail',512,130,[(10,'M')],-1,0,60,40),('supplementary',2048,140,[(10,'M')],-1,0,60,40),('lowbasequality',0,150,[(10,'M')],-1,0,60,0)]
REGIONS=[('chr1',0,40,'paired'),('chr1',50,65,'deletion'),('chr1',70,90,'splice'),('chr1',100,110,'lowmapq'),('chr1',120,130,'duplicate'),('chr1',140,150,'supplementary'),('chr1',150,160,'lowbasequality'),('chr1',180,200,'empty')]
def bam_bytes(rows=ROWS,refs=REFS,sort='coordinate'):
 header=('@HD\tVN:1.6\tSO:'+sort+'\n'+''.join(f'@SQ\tSN:{n}\tLN:{l}\n' for n,l in refs)).encode();body=b'BAM\1'+struct.pack('<i',len(header))+header+struct.pack('<i',len(refs))
 for n,l in refs:b=n.encode()+b'\0';body+=struct.pack('<i',len(b))+b+struct.pack('<i',l)
 for n,flag,pos,cigar,mpos,tlen,mapq,quality in rows:
  name=n.encode()+b'\0';seq=sum(l for l,o in cigar if o in 'MIS=X');ops=b''.join(struct.pack('<I',l<<4|'MIDNSHP=XB'.index(o)) for l,o in cigar);core=struct.pack('<iiIIiiii',0,pos,4681<<16|mapq<<8|len(name),flag<<16|len(cigar),seq,0 if flag&1 else -1,mpos,tlen);record=core+name+ops+b'\x11'*((seq+1)//2)+bytes([quality])*seq;body+=struct.pack('<i',len(record))+record
 def bgzf(data):
  c=zlib.compressobj(6,zlib.DEFLATED,-15);payload=c.compress(data)+c.flush();return b'\x1f\x8b\x08\x04'+bytes(4)+b'\x00\xff\x06\x00BC\x02\x00'+struct.pack('<H',len(payload)+25)+payload+struct.pack('<II',zlib.crc32(data),len(data))
 return b''.join(bgzf(body[i:i+60000]) for i in range(0,len(body),60000))+bgzf(b'')
def depths(mapq=0,flags=1796):
 # Independent interval union: the proper pair contributes one molecule over its
 # aligned union, all other retained records contribute their aligned M/= /X bases.
 result=[0]*200;groups={}
 for name,flag,pos,cigar,mpos,tlen,mq,bq in ROWS:
  if flag&flags or mq<mapq:continue
  key=name if flag&2 else (name,flag);positions=groups.setdefault(key,set())
  for length,op in cigar:
   if op in 'M=X':positions.update(range(pos,pos+length))
   if op in 'MDN=X':pos+=length
 for positions in groups.values():
  for pos in positions:result[pos]+=1
 return result
def fixtures(dest):
 dest=Path(dest);dest.mkdir(parents=True,exist_ok=True);(dest/'coverage.bam').write_bytes(bam_bytes());(dest/'targets.bed').write_text(''.join('\t'.join(map(str,r))+'\n' for r in REGIONS),encoding='ascii');(dest/'empty-contig.bed').write_text('chr2\t0\t50\tempty_contig\n');(dest/'empty.bam').write_bytes(bam_bytes([]));(dest/'truth.json').write_text(json.dumps({'description':'Explicit coordinate and flag truth; Q0 bases retained; deletions/spliced gaps excluded; overlap counted once. Empty chr2 is a deliberate upstream denominator diagnostic.','references':REFS,'regions':REGIONS,'depths':depths(),'records':len(ROWS)},indent=2)+'\n')
