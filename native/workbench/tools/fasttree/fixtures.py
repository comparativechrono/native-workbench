"""Synthetic truth is constructed before running either phylogenetic estimator."""
import json, random
from pathlib import Path

def fixtures(path):
    path=Path(path);path.mkdir(parents=True,exist_ok=True)
    for datatype,alphabet in [('nucleotide','ACGT'),('protein','ACDEFGHIKLMNPQRSTVWY')]:
        rng=random.Random(447);ancestor=[rng.choice(alphabet) for _ in range(800)];rows=[]
        for pair,group in enumerate(('alpha','beta','gamma')):
            shared=ancestor.copy()
            for position in range(pair*70,(pair+1)*70): shared[position]=rng.choice(alphabet.replace(shared[position],''))
            for terminal in range(2):
                sequence=shared.copy();offset=230+(pair*2+terminal)*15
                for position in range(offset,offset+15): sequence[position]=rng.choice(alphabet.replace(sequence[position],''))
                rows.append((group+str(terminal+1),''.join(sequence)))
        (path/(datatype+'.afa')).write_text(''.join('>'+name+'\n'+seq+'\n' for name,seq in rows),encoding='ascii',newline='\n')
    truth={'source':'Independent deterministic construction, random seed447: ancestor800 residues, 3 disjoint 70-site pair substitutions, 6 disjoint 15-site terminal substitutions. Reuses independently constructed IQ-TREE fixture design, not tool outputs.','taxa':['alpha1','alpha2','beta1','beta2','gamma1','gamma2'],'columns':800,'variableColumns':300,'informativeColumns':210,'unrootedPairs':[['alpha1','alpha2'],['beta1','beta2'],['gamma1','gamma2']]}
    (path/'truth.json').write_text(json.dumps(truth,indent=2)+'\n',encoding='utf-8')
if __name__=='__main__': fixtures(Path(__file__).parent/'fixtures')
