#!/usr/bin/env python3
"""Convert a deliberately downloaded upstream SnpEff database into a local resource.

Publisher/helper command, not an analysis-time downloader. Requires exact upstream
ZIP checksum plus matching local FASTA and explicit assembly/annotation identity.
The Workbench annotation operation rechecks its inventory and every VCF REF allele.
"""
import argparse,hashlib,json,re,zipfile
from pathlib import Path
SCHEMA='native-workbench-snpeff-database-v1'
def sha(p):
    with Path(p).open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def convert(upstream,reference,assembly,release,expected,output,source_url,code='Standard',config=None):
    if not re.fullmatch(r'[A-Za-z][A-Za-z0-9_.-]{0,99}',assembly):raise ValueError('Invalid assembly ID')
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_. -]{0,149}',release):raise ValueError('Invalid annotation release')
    if not re.fullmatch(r'[0-9a-f]{64}',expected) or sha(upstream)!=expected:raise ValueError('Upstream ZIP checksum mismatch')
    if config is None or sha(config)!='777768cee885c91c7396ca716c03abb254ef4cde129de2a10513e2844895df5a':raise ValueError('Select the pinned SnpEff5.4c snpEff.config; source/config checksum differs')
    overrides={};allowed=set();global_code='Standard'
    for line in config.read_text(encoding='utf-8').splitlines():
        line=line.strip()
        if not line or line.startswith('#'):continue
        bits=re.split(r'\s*[:=]\s*',line,maxsplit=1)
        if len(bits)!=2:continue
        key,value=bits[0].strip(),bits[1].strip()
        if key.startswith('codon.'):allowed.add(key[6:])
        elif key==assembly+'.codonTable':global_code=value
        elif key.startswith(assembly+'.') and key.endswith('.codonTable'):
            chrom=key[len(assembly)+1:-len('.codonTable')]
            if not re.fullmatch(r'[A-Za-z0-9_][A-Za-z0-9_.-]{0,149}',chrom):raise ValueError('Unsupported upstream contig mapping name')
            overrides[chrom]=value
    if global_code not in allowed or any(v not in allowed for v in overrides.values()):raise ValueError('Unknown upstream codon mapping')
    if code!='Standard' and code!=global_code:raise ValueError('Requested default code disagrees with selected upstream assembly configuration')
    code=global_code
    if not source_url.startswith(('https://','file:')):raise ValueError('Record the public source URL or local file URI')
    with reference.open('rb') as f:
        if f.read(1)!=b'>':raise ValueError('Reference must be uncompressed DNA FASTA')
    inventory=[];total=reference.stat().st_size
    with zipfile.ZipFile(upstream) as src,zipfile.ZipFile(output,'x',compression=zipfile.ZIP_DEFLATED,compresslevel=6) as dst:
        selected=[];seen=set()
        for item in src.infolist():
            name=item.filename
            if item.is_dir():continue
            # Official archives may have an enclosing snpEff/ folder.
            if name.startswith('snpEff/'):name=name[7:]
            if not name.startswith('data/'+assembly+'/'):continue
            if not re.fullmatch('data/'+re.escape(assembly)+r'/[A-Za-z0-9_.-]+\.bin',name):raise ValueError('Unexpected database member: '+name)
            if name.lower() in seen or (item.external_attr>>16)&0o170000==0o120000:raise ValueError('Duplicate or linked member')
            seen.add(name.lower());total+=item.file_size
            if item.file_size>32*1024**3 or total>64*1024**3 or len(seen)>19999:raise ValueError('Resource exceeds bounded inventory/size limit')
            selected.append((item,name))
        if ('data/'+assembly+'/snpeffectpredictor.bin').lower() not in seen:raise ValueError('No predictor for the selected exact assembly ID')
        for item,name in selected:
            h=hashlib.sha256();n=0
            with src.open(item) as i,dst.open(name,'w',force_zip64=True) as o:
                while block:=i.read(1048576):
                    n+=len(block)
                    if n>item.file_size:raise ValueError('ZIP member exceeded declared size')
                    h.update(block);o.write(block)
            if n!=item.file_size:raise ValueError('Truncated database member')
            inventory.append(dict(path=name,bytes=n,sha256=h.hexdigest()))
        h=hashlib.sha256();n=0
        with reference.open('rb') as i,dst.open('reference.fa','w',force_zip64=True) as o:
            while block:=i.read(1048576):h.update(block);n+=len(block);o.write(block)
        inventory.append(dict(path='reference.fa',bytes=n,sha256=h.hexdigest()))
        meta=dict(schema=SCHEMA,snpEffVersion='5.4c',assembly=assembly,annotationRelease=release,geneticCode=code,codonOverrides=overrides,sourceConfigSha256=sha(config),origin='explicit-upstream-conversion',sourceUrl=source_url,upstreamArchiveSha256=expected,referenceSha256=h.hexdigest(),referenceFile=reference.name,validation='Integrity checked at conversion. Publisher must verify upstream database/reference identity and run representative annotations before distribution; VCF REF mismatches reject during use.',files=sorted(inventory,key=lambda x:x['path']))
        dst.writestr('database.json',json.dumps(meta,indent=2)+'\n')
    return dict(path=str(output),sha256=sha(output),bytes=output.stat().st_size,assembly=assembly,annotationRelease=release)
def main():
    p=argparse.ArgumentParser(description=__doc__)
    for arg in ('upstream','reference','output','config'):p.add_argument('--'+arg,type=Path,required=True)
    for arg in ('assembly','release','sha256','source-url'):p.add_argument('--'+arg,required=True)
    p.add_argument('--genetic-code',default='Standard',choices=['Standard','Bacterial_and_Plant_Plastid','Vertebrate_Mitochondrial']);a=p.parse_args()
    if a.output.exists():raise FileExistsError('Output already exists: '+str(a.output))
    try:print(json.dumps(convert(a.upstream,a.reference,a.assembly,a.release,a.sha256,a.output,a.source_url,a.genetic_code,a.config),indent=2))
    except Exception:
        # Do not leave a partial resource that appears usable.
        if a.output.exists():a.output.unlink()
        raise
if __name__=='__main__':main()
