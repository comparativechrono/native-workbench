#!/usr/bin/env python3
"""Validate local contracts, then execute the unchanged upstream Bracken estimator.

The wrapper does not implement an abundance estimator. Upstream integer truncation
and estimated-read denominator are retained and explained in the result record.
"""
import argparse
import csv
import hashlib
import json
import math
import os
from pathlib import Path
import re
import subprocess
import sys

# The module is a pinned pack asset beside this adapter, never a user module.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from resources import validate_resource, validate_classification, choose_distribution, ordinary_file, file_record

UPSTREAM_SHA = 'c311cb56921b92c807ea28710c98349c725f27b7cee2b20e2e343c50e2981cca'
HEADER = 'name\ttaxonomy_id\ttaxonomy_lvl\tkraken_assigned_reads\tadded_reads\tnew_est_reads\tfraction_total_reads'
LEVELS = {'D', 'P', 'C', 'O', 'F', 'G', 'S'}


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def dump(path, value):
    with Path(path).open('w', encoding='utf-8', newline='\n') as stream:
        stream.write(json.dumps(value, indent=2, ensure_ascii=True, allow_nan=False) + '\n')


def report_summary(path):
    """Reject MPA/minimizer/partial trees before upstream's permissive parser."""
    rows, seen, stack, unclassified, root = [], set(), [], None, None
    with Path(path).open(encoding='utf-8-sig', newline=None) as stream:
        for index, line in enumerate(stream, 1):
            values = line.rstrip('\r\n').split('\t')
            if len(values) != 6:
                raise ValueError('Expected an unmodified six-column Kraken report; invalid line ' + str(index))
            percent, clade, direct, rank, taxid, name = values
            if not clade.isdecimal() or not direct.isdecimal() or not taxid.isdecimal():
                raise ValueError('Kraken report counts and taxon IDs must be nonnegative integers')
            clade, direct, taxid = int(clade), int(direct), int(taxid)
            try:
                percent = float(percent)
            except ValueError as error:
                raise ValueError('Invalid Kraken report percentage') from error
            if not math.isfinite(percent) or not 0 <= percent <= 100 or not 0 <= direct <= clade:
                raise ValueError('Invalid Kraken report count/percentage range')
            if taxid in seen:
                raise ValueError('Duplicate taxonomy ID in Kraken report')
            seen.add(taxid)
            spaces = len(name) - len(name.lstrip(' '))
            if not name.strip() or len(name) > 16384 or any(ord(c) < 32 or ord(c) == 127 for c in name) or spaces % 2 or not re.fullmatch(r'[URKDPCOFGS](?:[0-9]+)?', rank):
                raise ValueError('Invalid rank or two-space taxonomy indentation in Kraken report')
            row = {'taxid': taxid, 'rank': rank, 'name': name.lstrip(' '), 'depth': spaces // 2,
                   'clade': clade, 'direct': direct, 'percent': percent, 'childrenTotal': 0}
            if taxid == 0:
                if rank != 'U' or spaces or clade != direct or rows:
                    raise ValueError('Unclassified Kraken row must be first, unindented, and internally consistent')
                unclassified = row
            elif taxid == 1:
                if root is not None or rank != 'R' or spaces or stack:
                    raise ValueError('Kraken root must have taxon ID 1, rank R, and no indentation')
                root = row
                stack = [row]
            else:
                if rank.startswith(('U', 'R')) and rank == 'U':
                    raise ValueError('Unexpected unclassified rank in taxonomy tree')
                if root is None or not spaces:
                    raise ValueError('Kraken report requires a root and an indented taxonomy tree')
                while stack and stack[-1]['depth'] >= row['depth']:
                    stack.pop()
                if not stack or stack[-1]['depth'] + 1 != row['depth']:
                    raise ValueError('Kraken report taxonomy indentation skips a level')
                stack[-1]['childrenTotal'] += clade
                stack.append(row)
            rows.append(row)
    if not rows:
        raise ValueError('Kraken report is empty')
    for row in rows:
        if row['clade'] != row['direct'] + row['childrenTotal']:
            raise ValueError('Kraken report clade counts disagree with the taxonomy tree')
    classified = root['clade'] if root else 0
    unknown = unclassified['clade'] if unclassified else 0
    total = classified + unknown
    if total <= 0:
        raise ValueError('Kraken report contains no observations')
    for row in rows:
        if abs(row['percent'] - 100 * row['clade'] / total) > 0.011:
            raise ValueError('Kraken report percentages disagree with total observations')
    return {'rows': rows, 'classified': classified, 'unclassified': unknown, 'total': total}


def validate_distribution(path):
    """Stream-validate the upstream text format; do not modify probabilities."""
    taxa, genomes = set(), {}
    with Path(path).open(encoding='ascii', newline=None) as stream:
        if stream.readline().rstrip('\r\n') != 'mapped_taxid\tgenome_taxids:kmers_mapped:total_genome_kmers':
            raise ValueError('Not a supported upstream Bracken kmer distribution')
        for line in stream:
            fields = line.rstrip('\r\n').split('\t')
            if len(fields) != 2 or not fields[0].isdecimal() or not fields[1].split():
                raise ValueError('Malformed Bracken distribution row')
            taxid = int(fields[0])
            if taxid in taxa:
                raise ValueError('Duplicate mapped taxon in Bracken distribution')
            taxa.add(taxid)
            row_genomes = set()
            for triple in fields[1].split():
                parts = triple.split(':')
                if len(parts) != 3 or any(not value.isdecimal() for value in parts):
                    raise ValueError('Malformed Bracken distribution count triple')
                genome, mapped, total = map(int, parts)
                # Official upstream examples retain zero mapped numerators;
                # they are valid probabilities, unlike a zero denominator.
                if genome <= 0 or total <= 0 or not 0 <= mapped <= total or genome in row_genomes:
                    raise ValueError('Invalid/duplicate Bracken distribution genome counts')
                row_genomes.add(genome)
                prior_total, summed = genomes.get(genome, (total, 0))
                if prior_total != total:
                    raise ValueError('Inconsistent Bracken distribution genome denominator')
                genomes[genome] = total, summed + mapped
    if not taxa or any(total != summed for total, summed in genomes.values()):
        raise ValueError('Bracken distribution probabilities do not cover complete genome windows')
    return {'mappedTaxa': len(taxa), 'genomes': len(genomes)}


def execute(args):
    if args.level not in LEVELS or args.threshold < 0 or args.read_length < 1:
        raise ValueError('Choose a supported rank, nonnegative threshold, and positive read length')
    run = Path(args.run).resolve()
    run.mkdir(parents=True, exist_ok=True)
    outputs = {name: run / filename for name, filename in {
        'abundance': 'bracken.abundance.tsv', 'report': 'bracken.report.tsv',
        'provenance': 'bracken-provenance.json', 'methods': 'bracken-methods.txt',
        'log': 'bracken-upstream.log'}.items()}
    if any(path.exists() for path in outputs.values()):
        raise ValueError('Refusing to overwrite existing Bracken results')
    resource = None
    classification = None
    if args.mode == 'estimate':
        resource = validate_resource(Path(args.database), verify_database=False)
        selected = choose_distribution(resource, args.read_length, verify=True)
        if selected['document']['classifierSettings'] != {'confidence': 0, 'minimumHitGroups': 2, 'minimumBaseQuality': 0, 'quick': False}:
            raise ValueError('This Bracken pack requires a distribution registered for standard Kraken2 classification: confidence 0, minimum hit groups 2, minimum base quality 0, and no quick mode')
        classification = validate_classification(Path(args.classification), resource)
        report = classification['report']
        record = classification['document']
        reads, classifier = record['reads'], record['classifier']
        if classifier['confidence'] != 0 or classifier['minimumHitGroups'] != 2 or classifier['minimumBaseQuality'] != 0 or classifier['quick']:
            raise ValueError('This Bracken pack requires standard Kraken2 classification: confidence 0, minimum hit groups 2, minimum base quality 0, and no quick mode')
        mates = [reads['mate1']] + ([reads['mate2']] if reads['paired'] else [])
        if args.length_policy == 'exact':
            if any(m['minLength'] != args.read_length or m['maxLength'] != args.read_length for m in mates):
                raise ValueError('Observed read lengths do not exactly match this Bracken distribution. Choose a matching distribution, or explicitly select representative-length approximation for variable reads.')
        elif not min(m['minLength'] for m in mates) <= args.read_length <= max(m['maxLength'] for m in mates):
            raise ValueError('Representative length must be within the observed read-length range')
        unit = reads['unit']
        identity_scope = 'hash-bound-workbench-classification'
    else:
        if args.external_confirmation != 'confirmed':
            raise ValueError('External reports require explicit confirmation of matching database, standard classifier settings, read length and observation units')
        # Inspect selected paths before resolving; resolving first could hide
        # a symbolic link or Windows junction/reparse point from the guard.
        report = ordinary_file(Path(args.report)).absolute()
        distribution = ordinary_file(Path(args.distribution)).absolute()
        if (not args.database_label or not args.database_release or len(args.database_label) > 256 or len(args.database_release) > 256
                or any(ord(c) < 32 or ord(c) == 127 for c in args.database_label + args.database_release)):
            raise ValueError('External reports require a nonempty database label and release/source identifier')
        selected = {'path': distribution, 'document': {'path': str(distribution), **file_record(distribution),
            'readLength': args.read_length, 'association': 'user-attested-external',
            'databaseLabel': args.database_label, 'databaseRelease': args.database_release,
            'model': 'user-declared standard Kraken2 classification and matching read-length distribution'}}
        unit = args.external_unit
        reads = None
        identity_scope = 'user-declared-external-report-unverified'
    before = {'report': sha(report), 'distribution': sha(selected['path']), 'databaseDescriptor': sha(resource['path']) if resource else None}
    if (before['distribution'] != selected['document']['sha256']
            or (resource and before['databaseDescriptor'] != resource['sha256'])
            or (classification and (before['report'] != classification['document']['report']['sha256']
                                    or sha(classification['path']) != classification['sha256']))):
        raise ValueError('A selected report or distribution changed during input validation')
    summary = report_summary(report)
    if classification:
        if (summary['total'], summary['classified'], summary['unclassified']) != (reads['fragments'], reads['classifiedFragments'], reads['unclassifiedFragments']):
            raise ValueError('Kraken report counts disagree with classification provenance')
    eligible = [row for row in summary['rows'] if row['rank'] == args.level and row['clade'] >= args.threshold and row['clade'] > 0]
    if not eligible:
        raise ValueError('No classified taxa at the selected rank meet the threshold; Bracken cannot estimate abundance for this input')
    distribution_summary = validate_distribution(selected['path'])
    upstream = Path(__file__).resolve().parent / 'upstream/est_abundance.py'
    if sha(upstream) != UPSTREAM_SHA:
        raise ValueError('Pack upstream Bracken estimator changed')
    command = [sys.executable, '-I', '-B', '-X', 'utf8', str(upstream), '-i', str(report), '-k', str(selected['path']),
               '-o', str(outputs['abundance']), '--out-report', str(outputs['report']), '-l', args.level, '-t', str(args.threshold)]
    environment = os.environ.copy()
    for key in list(environment):
        if key.upper().startswith('PYTHON'):
            environment.pop(key)
    with outputs['log'].open('wb') as log:
        status = subprocess.run(command, cwd=run, env=environment, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT).returncode
    if status:
        raise ValueError('Upstream Bracken failed (exit ' + str(status) + '); see bracken-upstream.log')
    after = {'report': sha(report), 'distribution': sha(selected['path']), 'databaseDescriptor': sha(resource['path']) if resource else None}
    if before != after or (classification and sha(classification['path']) != classification['sha256']):
        raise ValueError('A Bracken input changed during execution; results are not valid')
    with outputs['abundance'].open(encoding='utf-8', newline='') as stream:
        reader = csv.DictReader(stream, delimiter='\t')
        if reader.fieldnames != HEADER.split('\t'):
            raise ValueError('Unexpected upstream Bracken output columns')
        result = list(reader)
    if not result or any(row['taxonomy_lvl'] != args.level for row in result):
        raise ValueError('Unexpected empty or wrong-rank upstream Bracken result')
    estimated = sum(int(row['new_est_reads']) for row in result)
    association = selected['document']['association']
    length_scope = args.length_policy if classification else 'user-declared-external'
    methods = ('Taxonomic abundance was estimated locally using the unchanged Bracken 3.1 upstream est_abundance.py, '
        'at rank ' + args.level + ' with minimum Kraken clade count ' + str(args.threshold) + ' and the database-specific '
        + str(args.read_length) + '-base distribution. The input report counted ' + unit + '. Database/report identity scope was '
        + identity_scope + '; distribution-to-database association was ' + association + '. Read-length policy was ' + length_scope + '. '
        'Bracken fractions use its retained estimated-abundance denominator, not all input observations; unclassified and '
        'unallocated observations are not added to that denominator. Integer truncation and upstream report contents were retained. '
        'A representative-length policy is an explicit approximation for variable reads, not a mixture-of-read-length model. '
        'Read/fragment abundance is not organism cell abundance, and these results do not establish clinical detection.\n')
    with outputs['methods'].open('w', encoding='utf-8', newline='\n') as stream:
        stream.write(methods)
    dump(outputs['provenance'], {'schema': 1, 'kind': 'native-workbench-bracken-abundance', 'success': True,
        'upstreamVersion': '3.1', 'upstreamEstimatorSha256': UPSTREAM_SHA, 'identityScope': identity_scope,
        'databaseFingerprint': resource['document']['databaseFingerprint'] if resource else None, 'databaseDescriptor': str(resource['path']) if resource else None,
        'databaseDescriptorSha256': before['databaseDescriptor'], 'distribution': selected['document'],
        'distributionPath': str(selected['path']), 'distributionValidation': distribution_summary,
        'classificationRecord': str(classification['path']) if classification else None,
        'classificationRecordSha256': classification['sha256'] if classification else None,
        'inputReport': {'path': str(report), 'sha256': before['report'], 'bytes': report.stat().st_size},
        'reads': reads, 'observationUnit': unit, 'readLength': args.read_length, 'readLengthPolicy': length_scope,
        'rank': args.level, 'threshold': args.threshold, 'totalInputObservations': summary['total'],
        'classifiedInputObservations': summary['classified'], 'unclassifiedInputObservations': summary['unclassified'],
        'estimatedTaxa': len(result), 'sumOfTruncatedEstimatedCounts': estimated,
        'fractionDenominator': 'int(sum of unrounded retained per-taxon estimates); each numerator is int(its estimate), formatted to five decimal places',
        'inputsUnchanged': True, 'databaseBinaryFilesReadByBracken': False,
        'command': command, 'outputs': {name: {'path': path.name, 'bytes': path.stat().st_size, 'sha256': sha(path)} for name, path in outputs.items() if name != 'provenance'},
        'methods': methods})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mode', choices=['estimate', 'estimate-external'], required=True)
    parser.add_argument('--run', required=True)
    parser.add_argument('--database')
    parser.add_argument('--classification')
    parser.add_argument('--report')
    parser.add_argument('--distribution')
    parser.add_argument('--database-label')
    parser.add_argument('--database-release')
    parser.add_argument('--read-length', type=int, required=True)
    parser.add_argument('--level', choices=sorted(LEVELS), default='S')
    parser.add_argument('--threshold', type=int, default=10)
    parser.add_argument('--length-policy', choices=['exact', 'representative'], default='exact')
    parser.add_argument('--external-confirmation', default='unconfirmed')
    parser.add_argument('--external-unit', choices=['reads', 'fragments'], default='reads')
    args = parser.parse_args()
    try:
        execute(args)
    except (ValueError, OSError, KeyError, TypeError) as error:
        parser.exit(1, 'Bracken: ' + str(error) + '\n')


if __name__ == '__main__':
    main()
