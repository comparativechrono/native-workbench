#!/usr/bin/env python3
"""Record/verify official pinned Linux FastTree outputs; these are not biological truth."""
import argparse,hashlib,json,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'scripts'))
from build_fasttree_native import SOURCES,COMMIT,sha

def record(binary,fixture_dir):
    binary=Path(binary).resolve();fixture_dir=Path(fixture_dir).resolve()
    if sha(binary)!=SOURCES['FastTree'][1]:raise ValueError('Wrong official Linux FastTree executable')
    cases={}
    for datatype,model,flag in [('nucleotide','JC',None),('nucleotide','GTR','-gtr'),('protein','JTT',None),('protein','LG','-lg'),('protein','WAG','-wag')]:
        for rates in ['cat','gamma']:
            for support in ['none','sh']:
                args=['-nopr','-cat','20','-seed','42','-boot','1000' if support=='sh' else '0']+(['-nt'] if datatype=='nucleotide' else [])+([flag] if flag else [])+(['-gamma'] if rates=='gamma' else [])
                result=subprocess.run([str(binary),*args,str(fixture_dir/(datatype+'.afa'))],capture_output=True,text=True,check=True,timeout=120)
                cases['-'.join([datatype,model,rates,support])]={'argv':['<pinned-official-Linux-FastTree>',*args,'<fixtures>/'+datatype+'.afa'],'tree':result.stdout.strip(),'log':result.stderr.replace(str(fixture_dir),'<fixtures>')}
    return {'upstreamVersion':'2.2.0','referenceExecutableSha256':sha(binary),'sourceCommit':COMMIT,'role':'Recorded official upstream Linux results. Topology has separate independent construction truth; branch lengths compared within tolerance, not used as biological truth.','fixtureSha256':{d:sha(fixture_dir/(d+'.afa')) for d in ['nucleotide','protein']},'cases':cases}

def verify(actual,expected):
    for key in ['upstreamVersion','referenceExecutableSha256','sourceCommit','fixtureSha256']:
        if actual[key]!=expected[key]:raise ValueError('Reference identity mismatch: '+key)
    if actual['cases'].keys()!=expected['cases'].keys():raise ValueError('Reference case mismatch')
    for key,case in actual['cases'].items():
        if case['tree']!=expected['cases'][key]['tree']:raise ValueError('Pinned Linux reference tree changed: '+key)
    return len(actual['cases'])

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--binary',type=Path,required=True);p.add_argument('--fixtures',type=Path,default=Path(__file__).parent/'fixtures');p.add_argument('--output',type=Path);p.add_argument('--verify',type=Path);a=p.parse_args()
    if bool(a.output)==bool(a.verify):p.error('Choose exactly one --output or --verify')
    result=record(a.binary,a.fixtures)
    if a.verify:print(json.dumps({'livePinnedLinuxReferenceCasesPassed':verify(result,json.loads(a.verify.read_text()))}))
    else:a.output.write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
