#!/usr/bin/env python3
"""Exhaustively classify every 150-base fixture-genome window for a real model.

This is a fixture generator, not an exposed database-build operation. It uses
the actual Kraken2 classifier followed by unchanged upstream Bracken distribution
serialization. No sampled probabilities or substitute read classifier is used.
"""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import subprocess
import sys


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--fixture', type=Path, required=True)
    p.add_argument('--classifier', type=Path, required=True)
    p.add_argument('--bracken-source', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args()
    a.output.mkdir(parents=True, exist_ok=True)
    records = {}
    name = None
    for line in (a.fixture / 'reference.fa').read_text().splitlines():
        if line.startswith('>'):
            name = line[1:].split()[0]
            records[name] = ''
        else:
            records[name] += line
    mapping = dict(line.split() for line in (a.fixture / 'seqid2taxid.map').read_text().splitlines())
    windows = a.output / 'all-150-base-windows.fa'
    with windows.open('w', encoding='ascii', newline='\n') as stream:
        for name, sequence in records.items():
            for start in range(len(sequence) - 149):
                stream.write('>' + mapping[name] + '_' + str(start) + '\n' + sequence[start:start+150] + '\n')
    assignments = a.output / 'all-window-classifications.tsv'
    command = [str(a.classifier.resolve()), '-H', str((a.fixture/'hash.k2d').resolve()), '-t', str((a.fixture/'taxo.k2d').resolve()),
               '-o', str((a.fixture/'opts.k2d').resolve()), '-p', '2', '-T', '0', '-g', '2', '-Q', '0', '-O', str(assignments.resolve()), str(windows.resolve())]
    subprocess.run(command, check=True)
    counts = {}
    for line in assignments.read_text().splitlines():
        status, name, taxid, length, hits = line.split('\t')
        genome = name.split('_')[0]
        counts.setdefault(genome, Counter())[taxid] += 1
    counts_file = a.output / 'exhaustive-window-counts.tsv'
    with counts_file.open('w', encoding='ascii', newline='\n') as stream:
        for genome, count in sorted(counts.items()):
            stream.write('genome' + genome + '\t' + genome + '\t' + str(sum(count.values())) + '\t' + ' '.join(key+':'+str(value) for key,value in sorted(count.items())) + '\n')
    generator = a.bracken_source / 'src/generate_kmer_distribution.py'
    distribution = a.output / 'database150mers.kmer_distrib'
    second_command = [sys.executable, '-I', '-B', str(generator.resolve()), '-i', str(counts_file.resolve()), '-o', str(distribution.resolve())]
    subprocess.run(second_command, check=True)
    record = {'schema':1, 'description':'Every contiguous 150-base forward window in each synthetic fixture genome was classified with real Kraken2 2.17.2, standard settings. The unchanged Bracken 3.1 generator serialized the exhaustive counts. Canonical nucleotide classification is strand independent. This fixture calculation is not an exposed general database-building operation.',
              'commands':[command, second_command], 'classifierSha256':sha(a.classifier),'generatorSha256':sha(generator),
              'distributionSha256':sha(distribution),'referenceSha256':sha(a.fixture/'reference.fa'), 'counts':{key:dict(value) for key,value in counts.items()},
              'windowCount':sum(sum(value.values()) for value in counts.values())}
    (a.output/'fixture-model-provenance.json').write_text(json.dumps(record,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(record,indent=2))


if __name__ == '__main__':
    main()
