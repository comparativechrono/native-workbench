"""Record fresh unmodified Primer3 CLI results, separately from adapter execution."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
SOURCE_COMMIT = '7f9f17d6012f404e83bbf0f931a4d06eb4af465b'
SOURCE_SHA256 = 'c981e42765ceb525f56607c6a7cf989ac5068483731c6e083b1e9fb22816463b'

def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def result_tags(text):
    return {k:v for line in text.splitlines() if '=' in line and line != '=' for k,v in [line.split('=',1)] if k.startswith(('PRIMER_LEFT_', 'PRIMER_RIGHT_', 'PRIMER_PAIR_', 'PRIMER_ERROR', 'PRIMER_WARNING'))}

def record(binary, fixtures):
    binary,fixtures=Path(binary).resolve(),Path(fixtures).resolve()
    build=json.loads((binary.parent/'build.json').read_text())
    if build['upstreamCommit']!=SOURCE_COMMIT or not build['upstreamSourceUnmodified'] or build['files'][binary.name]['sha256']!=sha(binary) or build['sources']['primer3-2.6.1.tar.gz']['sha256']!=SOURCE_SHA256:
        raise ValueError('Reference executable is not bound to pristine pinned source')
    result={'schema':1,'toolVersion':'2.6.1','sourceCommit':SOURCE_COMMIT,'sourceArchiveSha256':SOURCE_SHA256,'referenceExecutableSha256':sha(binary),'scope':'Pristine upstream Linux CLI execution. Planted binding sites are independent construction; ordinary result equality is a port regression, not independent biological truth.','cases':{}}
    with tempfile.TemporaryDirectory(prefix='primer3-reference-') as directory:
        for name in ('planted','ordinary','no-pairs'):
            source=fixtures/(name+'.fa');sequence=''.join(source.read_text().splitlines()[1:]);request=Path(directory)/(name+'.boulder')
            text=f'SEQUENCE_ID=synthetic_{name.replace("-","_")}\nSEQUENCE_TEMPLATE={sequence}\nPRIMER_TASK=generic\nPRIMER_PICK_LEFT_PRIMER=1\nPRIMER_PICK_RIGHT_PRIMER=1\nPRIMER_PICK_INTERNAL_OLIGO=0\nPRIMER_FIRST_BASE_INDEX=0\nPRIMER_NUM_RETURN=5\nPRIMER_PRODUCT_SIZE_RANGE=100-300\nPRIMER_MIN_SIZE={20 if name=="planted" else 18}\nPRIMER_OPT_SIZE=20\nPRIMER_MAX_SIZE={20 if name=="planted" else 27}\nPRIMER_MIN_TM=57\nPRIMER_OPT_TM=60\nPRIMER_MAX_TM=63\nPRIMER_SALT_MONOVALENT=50\nPRIMER_SALT_DIVALENT=1.5\nPRIMER_DNTP_CONC=0.6\nPRIMER_DNA_CONC=50\nPRIMER_TM_FORMULA=1\nPRIMER_SALT_CORRECTIONS=1\nPRIMER_THERMODYNAMIC_OLIGO_ALIGNMENT=1\nPRIMER_THERMODYNAMIC_TEMPLATE_ALIGNMENT=0\nPRIMER_EXPLAIN_FLAG=1\nPRIMER_MAX_NS_ACCEPTED=0\nPRIMER_LIBERAL_BASE=0\nPRIMER_LOWERCASE_MASKING=0\nPRIMER_MASK_TEMPLATE=0\nPRIMER_THERMODYNAMIC_PARAMETERS_PATH={binary.parent.as_posix()}/primer3_config/\n=\n'
            request.write_text(text,encoding='ascii')
            child=subprocess.run([str(binary),'--default_version=2','--io_version=4','--strict_tags',str(request)],capture_output=True,text=True,timeout=120)
            if child.returncode:raise RuntimeError(child.stdout+child.stderr)
            tags=result_tags(child.stdout)
            if 'PRIMER_ERROR' in tags:raise ValueError(tags['PRIMER_ERROR'])
            result['cases'][name]={'fixtureSha256':sha(source),'resultTags':tags}
    planted=result['cases']['planted']['resultTags']
    if planted['PRIMER_LEFT_0']!='40,20' or planted['PRIMER_RIGHT_0']!='219,20' or planted['PRIMER_PAIR_0_PRODUCT_SIZE']!='180':raise ValueError('Independent planted binding truth failed')
    return result

def verify(actual, expected):
    for key in ('toolVersion','sourceCommit','sourceArchiveSha256','cases'):
        if actual[key]!=expected[key]:raise ValueError('Fresh pristine reference changed: '+key)
    return len(actual['cases'])

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--binary',type=Path,required=True);p.add_argument('--fixtures',type=Path,default=Path(__file__).parent/'fixtures');p.add_argument('--output',type=Path,required=True);a=p.parse_args();a.output.write_text(json.dumps(record(a.binary,a.fixtures),indent=2)+'\n',encoding='utf-8')
