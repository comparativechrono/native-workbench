"""Deterministic, artificial six-sample bulk RNA expression fixtures."""
import csv
import json
from pathlib import Path
import random


def fixtures(destination):
    p = Path(destination); p.mkdir(parents=True, exist_ok=True)
    rng = random.Random(810431)
    names = ['control1','control2','control3','treated1','treated2','treated3']
    genes = ['gene%04d' % (n+1) for n in range(300)]
    rows = []
    for g in range(300):
        mean = 400 + (g*127)%2100
        values = []
        for s in range(6):
            effect = 8 if (g<12 and s>=3) or (12<=g<24 and s<3) else 1
            batch = (1.08 if s%3==1 else .95 if s%3==2 else 1)
            value = max(1,round(mean * effect * batch * rng.uniform(.88,1.12)))
            values.append(value)
        rows.append(values)
    with (p/'counts.tsv').open('w',newline='',encoding='utf-8') as f:
        w=csv.writer(f,delimiter='\t',lineterminator='\n');w.writerow(['gene_id']+names)
        w.writerows([[g]+r for g,r in zip(genes,rows)])
    sample_rows=[[n,'control' if i<3 else 'treated','individual'+str(i+1),'batch'+str(i%3+1),i+1] for i,n in enumerate(names)]
    with (p/'samples.tsv').open('w',newline='',encoding='utf-8') as f:
        w=csv.writer(f,delimiter='\t',lineterminator='\n');w.writerow(['sample_id','condition','biological_replicate','batch','input_index']);w.writerows(sample_rows)
    with (p/'tx2gene.tsv').open('w',newline='',encoding='utf-8') as f:
        w=csv.writer(f,delimiter='\t',lineterminator='\n');w.writerow(['transcript_id','gene_id'])
        for i,g in enumerate(genes):w.writerow(['tx%04d'%(i+1),g])
    for s,name in enumerate(names):
        with (p/('featurecounts-'+str(s+1)+'.tsv')).open('w',newline='',encoding='utf-8') as f:
            f.write('# Program:featureCounts v2.1.1; synthetic independently specified count truth\n')
            w=csv.writer(f,delimiter='\t',lineterminator='\n');w.writerow(['Geneid','Chr','Start','End','Strand','Length',name+'.bam'])
            for i,g in enumerate(genes):w.writerow([g,'chr1',i*1100+1,i*1100+1000,'+',1000,rows[i][s]])
        total=sum(r[s] for r in rows)
        with (p/('abundance-'+str(s+1)+'.tsv')).open('w',newline='',encoding='utf-8') as f:
            w=csv.writer(f,delimiter='\t',lineterminator='\n');w.writerow(['target_id','length','eff_length','est_counts','tpm'])
            for i,g in enumerate(genes):w.writerow(['tx%04d'%(i+1),1000,821,rows[i][s],format(rows[i][s]/total*1e6,'.12g')])
    truth={'schema':1,'source':'Deterministic artificial counts, six asserted independent sample IDs, 300 genes; not simulated reads and not a biological performance benchmark.',
        'seed':810431,'samples':names,'positive':genes[:12],'negative':genes[12:24],'null':genes[24:],
        'expected':{'positiveLog2FoldChangeMinimum':2,'negativeLog2FoldChangeMaximum':-2,'effectAdjustedPMaximum':0.01},
        'kallistoFixtureScope':'Hand-authored format-valid abundance tables with identical transcript lengths; actual released kallisto compatibility tested separately using its abundance.tsv output.'}
    (p/'truth.json').write_text(json.dumps(truth,indent=2)+'\n')

if __name__=='__main__':
    import sys
    fixtures(sys.argv[1])
