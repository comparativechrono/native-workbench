#!/usr/bin/env python3
"""Synthetic-only PCR design fixtures with independently planted binding sites."""
from pathlib import Path
import json
import random

def fixtures(directory):
    out = Path(directory)
    out.mkdir(parents=True, exist_ok=True)
    left = 'CTACTCAGGACTAGCCAAGC'
    right = 'CGCCGAGCCTAGACAACGAA'
    reverse = right.translate(str.maketrans('ACGT', 'TGCA'))[::-1]
    planted = 'N' * 40 + left + 'N' * 140 + reverse + 'N' * 40
    rng = random.Random(413896)
    ordinary = ''.join(rng.choice('ACGT') for _ in range(600))
    for name, sequence in [('planted', planted), ('ordinary', ordinary), ('no-pairs', 'N' * 300)]:
        (out / (name + '.fa')).write_bytes(('>synthetic_' + name.replace('-', '_') + '\n' + sequence + '\n').encode('ascii'))
    truth = {'schema': 1, 'synthetic': True,
        'construction': 'Two predetermined 20-base arms separated and surrounded by N. Primer N acceptance is zero, so with exact length 20 the only permissible binding intervals are left [40,60), right [200,220). Product length 180 is independently derived. Arms were selected for a positive example, not obtained from a biological locus. Ordinary template is seeded random DNA (Python Random 413896); no-pairs is all N.',
        'left': left, 'right': right, 'leftStart0': 40, 'leftEnd0': 60, 'rightStart0': 200, 'rightEnd0': 220, 'productBases': 180,
        'leftGcPercent': 55, 'rightGcPercent': 60, 'primerLength': 20,
        'defaultSettings': ['100','300','5','18','20','27','57','60','63','50','1.5','0.6','50'],
        'plantedSettings': ['100','300','5','20','20','20','57','60','63','50','1.5','0.6','50']}
    (out / 'truth.json').write_bytes((json.dumps(truth, indent=2) + '\n').encode('ascii'))

if __name__ == '__main__':
    fixtures(Path(__file__).parent / 'fixtures')
