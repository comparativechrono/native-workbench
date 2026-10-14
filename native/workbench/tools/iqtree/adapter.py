#!/usr/bin/env python3
"""Local bounded IQ-TREE frontend; no likelihood or tree-search substitution."""
from __future__ import annotations
import argparse
from collections import Counter
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

VERSION = '3.1.4'
MODELS = {'DNA': ('MFP', 'GTR+G4', 'HKY+G4', 'JC'), 'AA': ('MFP', 'LG+G4', 'WAG+G4', 'JTT+G4')}
CANONICAL = {'DNA': set('ACGT'), 'AA': set('ACDEFGHIKLMNPQRSTVWY')}
ALPHABETS = {'DNA': set('ACGTRYSWKMBDHVNU-.'), 'AA': set('ACDEFGHIKLMNPQRSTVWYBZX-.')}


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def dump(path, value):
    # Released installation checks compare decoded bytes, without newline conversion.
    # Keep JSON deterministic across Windows and Linux, including multiline splits.
    path.write_text(json.dumps(value, indent=2, ensure_ascii=True) + '\n', encoding='utf-8', newline='\n')


def bounded_integer(value, low, high, label):
    if not re.fullmatch(r'[0-9]+', value) or not low <= int(value) <= high:
        raise ValueError(f'{label} must be an integer from {low} to {high}.')
    return int(value)


def alignment(path, datatype):
    if path.is_symlink() or not path.is_file():
        raise ValueError('Choose a regular, uncompressed aligned FASTA file.')
    if path.stat().st_size > 256 * 1024 * 1024:
        raise ValueError('This local pack accepts aligned FASTA files up to 256 MiB; use managed compute for larger data.')
    records = []
    seen = set()
    with path.open(encoding='utf-8-sig') as stream:
        for line in stream:
            line = line.strip()
            if not line:
                continue
            if line.startswith('>'):
                header = line[1:].strip()
                if not header or len(header) > 4096 or any(ord(c) < 32 for c in header):
                    raise ValueError('FASTA headers must be nonempty, bounded text without control characters.')
                identity = header.split()[0]
                if identity in seen:
                    raise ValueError('FASTA first-word taxon identifiers must be unique: ' + identity)
                seen.add(identity)
                records.append({'id': identity, 'header': header, 'sequence': []})
                if len(records) > 10000:
                    raise ValueError('This local pack accepts at most 10,000 taxa; thread count does not cap memory.')
            else:
                if not records:
                    raise ValueError('Expected aligned FASTA beginning with a >taxon header.')
                sequence = line.upper()
                if set(sequence) - ALPHABETS[datatype]:
                    raise ValueError('Invalid ' + datatype + ' alignment symbols. DNA accepts IUPAC DNA/RNA; protein accepts standard amino acids and B/X/Z. Gaps are - or .; protein stop, U, O and J require review before analysis.')
                records[-1]['sequence'].append(sequence.replace('.', '-').replace('U', 'T') if datatype == 'DNA' else sequence.replace('.', '-'))
    if len(records) < 4:
        raise ValueError('IQ-TREE inference in this pack requires at least four taxa.')
    for item in records:
        item['sequence'] = ''.join(item['sequence'])
        if not set(item['sequence']) & CANONICAL[datatype]:
            raise ValueError('Each taxon must contain observed, nonambiguous residues: ' + item['id'])
    widths = {len(item['sequence']) for item in records}
    if len(widths) != 1:
        raise ValueError('Aligned FASTA rows must have the same number of columns. Run MUSCLE first.')
    width = widths.pop()
    if not 20 <= width <= 1000000:
        raise ValueError('This pack requires between 20 and 1,000,000 alignment columns.')
    if len({item['sequence'] for item in records}) < 4:
        raise ValueError('At least four distinct aligned sequences are required; identical taxa alone cannot resolve a phylogeny.')
    informative = 0
    variable = 0
    for column in zip(*(item['sequence'] for item in records)):
        counts = Counter(c for c in column if c in CANONICAL[datatype])
        variable += len(counts) > 1
        informative += sum(n >= 2 for n in counts.values()) >= 2
    if not informative:
        raise ValueError('No parsimony-informative alignment columns were found. This pack declines to present an unsupported resolved phylogeny; review sequence diversity and alignment.')
    return records, {'taxa': len(records), 'columns': width, 'variableColumnsIgnoringAmbiguity': variable, 'parsimonyInformativeColumnsIgnoringAmbiguity': informative}


def tree_evidence(text, names):
    """Parse unmodified upstream safe-ID Newick and validate taxa/finite branches."""
    tokens = re.findall(r"[^\s(),:;]+|[(),:;]", text)
    at = 0
    leaves, groups, support, stack = [], [], [], []
    pending = None
    need_node = True
    while at < len(tokens):
        token = tokens[at]
        at += 1
        if token == '(':
            if not need_node:
                raise ValueError('Invalid adjacent Newick nodes.')
            stack.append([])
            continue
        if token == ',':
            if need_node or not stack:
                raise ValueError('Invalid Newick separator.')
            stack[-1].append(pending)
            pending, need_node = None, True
            continue
        if token == ';':
            if need_node or stack or at != len(tokens):
                raise ValueError('Invalid Newick terminator.')
            break
        if token == ')':
            if need_node or not stack:
                raise ValueError('Unbalanced Newick tree.')
            children = stack.pop() + [pending]
            if len(children) < 2:
                raise ValueError('Newick internal node has fewer than two children.')
            pending = set().union(*children)
            # A complete split list repeats every taxon for every branch.
            # Keep JSON bounded for large phylogenies; full Newick is retained.
            if len(names) <= 256:
                groups.append(pending.copy())
            if at < len(tokens) and tokens[at] not in (':', ',', ')', ';'):
                values = [float(v) for v in tokens[at].split('/')]
                if not all(math.isfinite(v) and 0 <= v <= 100 for v in values):
                    raise ValueError('Invalid branch support in upstream tree.')
                support.append(values)
                at += 1
        else:
            if not need_node or token not in names:
                raise ValueError('Unexpected taxon or malformed upstream tree: ' + token)
            leaves.append(token)
            pending = {token}
        need_node = False
        if at < len(tokens) and tokens[at] == ':':
            at += 1
            if at >= len(tokens):
                raise ValueError('Missing upstream branch length.')
            branch = float(tokens[at])
            if not math.isfinite(branch) or branch < 0:
                raise ValueError('Nonfinite or negative upstream branch length.')
            at += 1
    else:
        raise ValueError('Newick tree lacks its terminator.')
    if Counter(leaves) != Counter(names.keys()):
        raise ValueError('Upstream tree must contain each original taxon exactly once.')
    universe = set(names)
    splits = set()
    for group in groups:
        other = universe - group
        if min(len(group), len(other)) >= 2:
            a, b = tuple(sorted(names[x] for x in group)), tuple(sorted(names[x] for x in other))
            splits.add(min((a, b), (b, a)))
    return {'taxa': sorted(names.values()), 'nontrivialBipartitions': [[list(a), list(b)] for a, b in sorted(splits)], 'branchSupportValues': support,
        'bipartitionSummary': 'complete' if len(names) <= 256 else 'omitted-above-256-taxa-use-full-Newick'}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--alignment', type=Path, required=True)
    parser.add_argument('--run', type=Path, required=True)
    parser.add_argument('--datatype', choices=MODELS, required=True)
    parser.add_argument('--model', required=True)
    parser.add_argument('--support', choices=('none', 'ufboot', 'sh-alrt', 'both'), default='none')
    parser.add_argument('--replicates', default='1000')
    parser.add_argument('--threads', default='2')
    parser.add_argument('--seed', default='42')
    # Explicit developer reference hook; manifest never supplies an external tool.
    parser.add_argument('--reference-binary', type=Path)
    args = parser.parse_args(argv)
    if args.model not in MODELS[args.datatype]:
        raise ValueError('Choose a model listed for the selected DNA/protein workflow.')
    threads = bounded_integer(args.threads, 1, 64, 'Threads')
    seed = bounded_integer(args.seed, 1, 2147483647, 'Seed')
    replicates = bounded_integer(args.replicates, 1000, 10000, 'Support replicates')
    source = args.alignment.resolve(strict=True)
    before = digest(source)
    records, stats = alignment(source, args.datatype)
    run = args.run.resolve(strict=True)
    if not run.is_dir():
        raise ValueError('Results folder must exist.')
    outputs = ('inferred-tree.nwk', 'iqtree-report.txt', 'model-selection.json', 'analysis-provenance.json', 'iqtree.log')
    if any((run / name).exists() for name in outputs):
        raise ValueError('IQ-TREE results already exist; choose a fresh run folder.')
    binary = args.reference_binary.resolve(strict=True) if args.reference_binary else Path(__file__).resolve().parent / 'bin/iqtree3.exe'
    if os.name == 'nt' and any(not str(p).isascii() for p in (run, binary)):
        raise ValueError('IQ-TREE upstream Windows paths must use ASCII characters. Spaces are supported; choose an ASCII installation and results folder.')
    scratch = run / 'iqtree-work'
    scratch.mkdir()
    staged = scratch / 'alignment.fa'
    names = {}
    with staged.open('w', encoding='ascii', newline='\n') as stream:
        for n, item in enumerate(records, 1):
            key = 'T' + str(n).zfill(6)
            names[key] = item['id']
            stream.write('>' + key + '\n' + item['sequence'] + '\n')
    command = [str(binary), '-s', 'alignment.fa', '-st', args.datatype, '-m', args.model, '-T', str(threads), '-seed', str(seed), '--prefix', 'analysis', '-keep-ident']
    if args.support in ('ufboot', 'both'):
        command += ['-B', str(replicates), '-bnni']
    if args.support in ('sh-alrt', 'both'):
        command += ['-alrt', str(replicates)]
    provenance = {'schema': 1, 'tool': 'IQ-TREE', 'version': VERSION, 'input': {'path': str(source), 'sha256': before, **stats}, 'datatype': args.datatype,
        'requestedModel': args.model, 'modelSelectionCriterion': 'BIC' if args.model == 'MFP' else None,
        'supportMethod': args.support, 'supportReplicates': replicates if args.support != 'none' else 0,
        'ufbootBNNI': args.support in ('ufboot', 'both'), 'threads': threads, 'seed': seed,
        'alignmentNormalizations': ['Upper-case letters', 'Dot gaps become hyphens'] + (['RNA U becomes DNA T'] if args.datatype == 'DNA' else []),
        'taxonMapping': [{'internalId': k, 'originalId': names[k], 'originalHeader': records[n]['header']} for n, k in enumerate(names)],
        'stagedAlignmentSha256': digest(staged), 'executableSha256': digest(binary), 'argv': command, 'cwd': str(scratch),
        'treeRooting': 'Unrooted; display root is arbitrary', 'dataPolicy': 'Selected local alignment only; no reference download or analysis upload',
        'status': 'running'}
    dump(run / 'analysis-provenance.json', provenance)
    env = dict(os.environ)
    for key in tuple(env):
        if key.startswith(('OMP_', 'KMP_', 'GOMP_')):
            env.pop(key)
    env['OMP_NUM_THREADS'] = str(threads)
    with (scratch / 'console.log').open('w', encoding='utf-8') as log:
        result = subprocess.run(command, cwd=scratch, env=env, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT, shell=False)
    if digest(source) != before:
        raise ValueError('Selected alignment changed while analysis was running; discard these results.')
    upstream_log = scratch / 'analysis.log'
    shutil.copyfile(upstream_log if upstream_log.exists() else scratch / 'console.log', run / 'iqtree.log')
    if result.returncode:
        provenance.update(status='failed', exitCode=result.returncode)
        dump(run / 'analysis-provenance.json', provenance)
        raise ValueError('IQ-TREE failed (exit ' + str(result.returncode) + '); see iqtree.log for its scientific or resource diagnostic.')
    report = (scratch / 'analysis.iqtree').read_text(encoding='utf-8')
    model = re.search(r'^Model of substitution:\s*(\S+)', report, re.MULTILINE)
    sites = re.search(r'Input data:\s+(\d+) sequences with (\d+)\s+(?:nucleotide|amino-acid) sites', report)
    if not model or not sites or (int(sites[1]), int(sites[2])) != (stats['taxa'], stats['columns']):
        raise ValueError('Upstream report is missing the selected model or expected alignment dimensions.')
    tree = (scratch / 'analysis.treefile').read_text(encoding='ascii')
    evidence = tree_evidence(tree, names)
    if args.support != 'none' and not evidence['branchSupportValues']:
        raise ValueError('Requested branch support is absent from the upstream tree.')
    expected_values = 2 if args.support == 'both' else 1
    if args.support != 'none' and any(len(x) != expected_values for x in evidence['branchSupportValues']):
        raise ValueError('Upstream branch-support labels do not match the selected support methods.')
    labelled_tree = re.sub(r'\bT[0-9]{6}\b', lambda m: "'" + names[m[0]].replace("'", "''") + "'", tree)
    (run / 'inferred-tree.nwk').write_text(labelled_tree, encoding='utf-8')
    shutil.copyfile(scratch / 'analysis.iqtree', run / 'iqtree-report.txt')
    dump(run / 'model-selection.json', {'schema': 1, 'requestedModel': args.model, 'selectedModel': model[1], 'criterion': 'BIC' if args.model == 'MFP' else None, 'alignment': stats, 'tree': evidence})
    provenance.update(status='completed', exitCode=0, selectedModel=model[1], inputUnchanged=True)
    dump(run / 'analysis-provenance.json', provenance)
    print('IQ-TREE completed: ' + model[1] + '; ' + str(stats['taxa']) + ' taxa; ' + str(stats['columns']) + ' columns.')


if __name__ == '__main__':
    try:
        main()
    except (ValueError, OSError, UnicodeError) as error:
        print('IQ-TREE pack: ' + str(error), file=sys.stderr)
        sys.exit(2)
