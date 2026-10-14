#!/usr/bin/env python3
"""Build the optional IQ-TREE pack using unchanged pinned upstream binaries."""
import argparse
import hashlib
import json
from pathlib import Path
import random
import shutil
import subprocess
import sys
import tarfile
import tomllib
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'desktop'))
from prepare_modular_packs import field, number, artifact, execute, workflow
from fetch_iqtree_build_inputs import recover, sha, LOCK
VERSION = '3.1.4'
PACK_VERSION = '1.0.0'
CITATIONS = [
 {'text': 'Wong TKF et al. (2026). IQ-TREE 3: phylogenomic inference software using complex evolutionary models. Molecular Biology and Evolution 43:msag117.', 'url': 'https://doi.org/10.1093/molbev/msag117'},
 {'text': 'Kalyaanamoorthy S et al. (2017). ModelFinder: fast model selection for accurate phylogenetic estimates. Nature Methods 14:587-589.', 'url': 'https://doi.org/10.1038/nmeth.4285'},
 {'text': 'Hoang DT et al. (2018). UFBoot2: improving the ultrafast bootstrap approximation. Molecular Biology and Evolution 35:518-522.', 'url': 'https://doi.org/10.1093/molbev/msx281'},
 {'text': 'Guindon S et al. (2010). New algorithms and methods to estimate maximum-likelihood phylogenies: assessing the performance of PhyML 3.0. Systematic Biology 59:307-321.', 'url': 'https://doi.org/10.1093/sysbio/syq010'}]


def dump(path, value):
    path.write_text(json.dumps(value, indent=2, ensure_ascii=True) + '\n', encoding='utf-8')


def copy_checked(source, destination):
    destination.parent.mkdir(parents=True, exist_ok=True)
    with Path(source).open('rb') as inp, destination.open('xb') as output:
        shutil.copyfileobj(inp, output, 1024 * 1024)
    if Path(source).stat().st_size != destination.stat().st_size or sha(source) != sha(destination):
        raise ValueError('Pack copy differs: ' + str(destination))


def fixtures(path):
    path.mkdir()
    for datatype, alphabet in [('nucleotide', 'ACGT'), ('protein', 'ACDEFGHIKLMNPQRSTVWY')]:
        generator = random.Random(447)
        ancestor = [generator.choice(alphabet) for _ in range(800)]
        records = {}
        for pair, group in enumerate(('alpha', 'beta', 'gamma')):
            shared = ancestor.copy()
            for position in range(pair * 70, (pair + 1) * 70):
                shared[position] = generator.choice(alphabet.replace(shared[position], ''))
            for terminal in range(2):
                sequence = shared.copy()
                offset = 230 + (pair * 2 + terminal) * 15
                for position in range(offset, offset + 15):
                    sequence[position] = generator.choice(alphabet.replace(sequence[position], ''))
                records[group + str(terminal + 1)] = ''.join(sequence)
        (path / (datatype + '.afa')).write_text(''.join('>' + k + '\n' + v + '\n' for k, v in records.items()), encoding='ascii')
    truth = {'source': 'Deterministic independent construction: shared ancestral sequence, three disjoint 70-site pair mutations, six disjoint 15-site terminal mutations; PRNG seed 447. No user data.',
        'taxa': 6, 'columns': 800, 'variableColumns': 300, 'parsimonyInformativeColumns': 210,
        'expectedUnrootedPairs': [['alpha1', 'alpha2'], ['beta1', 'beta2'], ['gamma1', 'gamma2']]}
    dump(path / 'truth.json', truth)


def definitions():
    workflows = []
    schema = {'schema': 1, 'category': 'Phylogenetics', 'citations': CITATIONS, 'workflows': {}}
    for datatype, flag in [('nucleotide', 'DNA'), ('protein', 'AA')]:
        identity = 'infer-' + datatype
        fixed = 'GTR+G4:GTR with gamma rates|HKY+G4:HKY with gamma rates|JC:Jukes-Cantor' if flag == 'DNA' else 'LG+G4:LG with gamma rates|WAG+G4:WAG with gamma rates|JTT+G4:JTT with gamma rates'
        inputs = [field('alignment', 'Aligned ' + datatype + ' FASTA', filter='Aligned FASTA|*.afa;*.fa;*.fasta;*.fna;*.faa|All files|*.*',
            help='Use aligned homologous sequences, for example matching MUSCLE output. Uncompressed FASTA, 4-10,000 taxa, 20-1,000,000 equal-length columns, unique first-word identifiers, at least four distinct sequences and one informative column; maximum 256 MiB. DNA U becomes T; dot gaps become hyphens. Protein stop/U/O/J are rejected. ASCII installation/results paths; spaces supported.'),
            field('model', 'Substitution model', 'choice', default='MFP', choices='MFP:ModelFinder selection by BIC|' + fixed, help='MFP tests upstream DNA or protein models and selects by BIC. Fixed models skip model selection. Input datatype is explicit.'),
            field('support', 'Branch support method', 'choice', default='none', choices='none:No branch support|ufboot:Ultrafast bootstrap with BNNI|sh-alrt:SH-aLRT|both:SH-aLRT and ultrafast bootstrap with BNNI', help='Support is optional and adds computation. Support measures are not posterior probabilities; review model adequacy. Both-method labels are SH-aLRT/UFBoot.'),
            number('replicates', 'Branch support replicates', 1000, 1000, 10000, help='Applied to each selected support method; ignored when support is none.'),
            number('threads', 'CPU threads', 2, 1, 64, help='This is not a memory limit. More threads can change numerical ordering.'),
            number('seed', 'Random seed', 42, 1, 2147483647, help='Recorded reproducibility setting; exact numeric equality across platforms is not promised.')]
        outputs = [artifact('tree', 'Unrooted phylogenetic tree (Newick)', 'inferred-tree.nwk'), artifact('report', 'IQ-TREE scientific report', 'iqtree-report.txt'),
            artifact('model', 'Model, alignment and topology summary', 'model-selection.json'), artifact('provenance', 'Analysis settings and taxon mapping', 'analysis-provenance.json'), artifact('log', 'IQ-TREE execution log', 'iqtree.log')]
        steps = [execute('version', 'Record the bundled IQ-TREE version', 'iqtree', ['--version']),
            execute('infer', 'Infer ' + datatype + ' phylogeny', 'python', ['-I', '-B', '-X', 'utf8', '{asset:adapter}', '--alignment', '{input:alignment}', '--run', '{run}', '--datatype', flag,
            '--model', '{input:model}', '--support', '{input:support}', '--replicates', '{input:replicates}', '--threads', '{input:threads}', '--seed', '{input:seed}'], produces=[o['id'] for o in outputs])]
        workflows.append(workflow(identity, 'IQ-TREE: ' + datatype + ' phylogeny', 'Infer an unrooted maximum-likelihood tree from an existing alignment, with model selection and optional branch support. Local IQ-TREE 3.1.4.', inputs, outputs, steps))
        schema['workflows'][identity] = {'ports': [{'id': 'alignment', 'label': 'Aligned ' + datatype + ' sequences', 'type': 'msa-' + datatype, 'accepts': ['msa-' + datatype], 'manifestInputs': ['alignment'], 'min': 1, 'max': 1, 'requiredState': {'compression': 'none'}, 'validation': {'minRecords': 4, 'maxRecords': 10000, 'minLength': 20, 'maxLength': 1000000, 'uniqueIds': True}}],
            'outputs': [{'id': o['id'], 'label': o['label'], 'type': 'file' if o['id'] == 'tree' else 'text' if o['id'] in ('report', 'log') else 'metrics', 'manifestOutputs': [o['id']]} for o in outputs],
            'methods': 'An unrooted maximum-likelihood phylogeny was inferred from aligned ' + datatype + ' sequences using IQ-TREE 3.1.4 with explicit ' + flag + ' datatype. The recorded substitution-model setting specifies either ModelFinder Plus selection by BIC or a fixed model. Recorded support settings specify no support, SH-aLRT, ultrafast bootstrap with BNNI correction, or both; replicate counts apply only to enabled methods. The selected model, actual command, thread count, random seed, taxon mapping and input hash were retained. Identical sequences were retained; dot gaps were normalized to hyphens and letters to upper case.' + (' RNA U was normalized to DNA T.' if flag == 'DNA' else '') + ' The display root is arbitrary; no biological rooting or species-tree inference was performed.'}
    return workflows, schema


def checks():
    checks = []
    cases = [('nucleotide-default', 'nucleotide', {}, 'JC'), ('protein-default', 'protein', {}, None),
        ('nucleotide-both-supports', 'nucleotide', {'model': 'GTR+G4', 'support': 'both'}, 'GTR+F+G4'),
        ('protein-bootstrap', 'protein', {'model': 'LG+G4', 'support': 'ufboot'}, 'LG+G4')]
    for identity, datatype, params, model in cases:
        fragments = ['"taxa": 6', '"columns": 800', '"variableColumnsIgnoringAmbiguity": 300', '"parsimonyInformativeColumnsIgnoringAmbiguity": 210',
            '"alpha1",\n          "alpha2"', '"beta1",\n          "beta2"', '"gamma1",\n          "gamma2"']
        if model:
            fragments.append('"selectedModel": "' + model + '"')
        checks.append({'id': identity, 'workflow': 'infer-' + datatype, 'params': params, 'inputs': {'alignment': [{'alignment': 'fixture-' + datatype}]},
            'expect': [{'output': 'tree', 'kind': 'text', 'contains': ["'" + x + "':" for x in ('alpha1', 'alpha2', 'beta1', 'beta2', 'gamma1', 'gamma2')]},
                {'output': 'model', 'kind': 'text', 'contains': fragments},
                {'output': 'report', 'kind': 'text', 'contains': ['IQ-TREE 3.1.4', '6 sequences with 800', 'Number of parsimony informative sites: 210']},
                {'output': 'provenance', 'kind': 'text', 'contains': ['"inputUnchanged": true', '"threads": 2', '"supportMethod": "' + params.get('support', 'none') + '"', '"status": "completed"']}]})
    return {'schema': 1, 'checks': checks}


def verify_corresponding_dependencies(cache, lock):
    pins = {x['filename']: x for x in lock['inputs']}
    with tarfile.open(cache / 'source.tar.gz') as source:
        cargo = tomllib.loads(source.extractfile('iqtree3-3.1.4/mutsel_rust/Cargo.lock').read().decode())
    registry = [x for x in cargo['package'] if x.get('source', '').startswith('registry+')]
    for item in registry:
        name = 'rust-crates/' + item['name'] + '-' + item['version'] + '.crate'
        if pins.get(name, {}).get('sha256') != item['checksum']:
            raise ValueError('Missing exact Cargo.lock source for ' + name)
    if len(registry) != 252:
        raise ValueError('Unexpected upstream Cargo dependency closure')
    compared = 0
    with tarfile.open(cache / 'eigen-3.4.0.tar.gz') as source, zipfile.ZipFile(cache / 'eigen.3.4.0.20240224.nupkg') as package:
        for name in package.namelist():
            if name.startswith('include/eigen3/') and not name.endswith('/'):
                relative = name[len('include/eigen3/'):]
                if package.read(name) != source.extractfile('eigen-3.4.0/' + relative).read():
                    raise ValueError('Eigen upstream and actual build-package headers differ: ' + relative)
                compared += 1
    if compared != 530:
        raise ValueError('Unexpected Eigen header inventory')
    return {'cargoRegistryCratesMatchedToLock': len(registry), 'eigenPackageHeadersMatchedToSource': compared, 'eigenDifferences': 0,
        'boostSource': 'boost_1_84_0.tar.bz2', 'rustStandardLibrarySource': 'rust-src-1.98.1.tar.xz',
        'phyloGradSourceCommit': '939dedb07605411bd6b2dbb4d3d733f842a15ff5'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cache', type=Path, default=ROOT / 'build/iqtree-inputs')
    parser.add_argument('--destination', type=Path, default=ROOT / 'packs/iqtree-1.0.0')
    parser.add_argument('--fetch', action='store_true')
    args = parser.parse_args()
    cache, dest = args.cache.resolve(), args.destination.resolve()
    lock = recover(cache, args.fetch)
    dependency_audit = verify_corresponding_dependencies(cache, lock)
    if dest.exists():
        raise ValueError('Use a new pack destination; do not overwrite a built pack.')
    for sub in ('bin', 'licenses'):
        (dest / sub).mkdir(parents=True)
    with zipfile.ZipFile(cache / 'python.zip') as archive:
        archive.extractall(dest / 'bin')
    (dest / 'bin/pythonw.exe').unlink()
    (dest / 'bin/python313._pth').write_text('python313.zip\n.\n', encoding='ascii')
    with zipfile.ZipFile(cache / 'windows.zip') as archive:
        for name in ('iqtree3.exe', 'libiomp5md.dll'):
            with archive.open('iqtree-3.1.4-Windows/bin/' + name) as inp, (dest / 'bin' / name).open('xb') as output:
                shutil.copyfileobj(inp, output)
    for name in ('source.tar.gz', 'lsd2.tar.gz', 'cmaple.tar.gz', 'python-source.tar.xz', 'Intel-OpenMP-LICENSE.txt'):
        copy_checked(cache / name, dest / 'licenses' / name)
    for pin in lock['inputs']:
        if 'retainAs' in pin:
            copy_checked(cache / pin['filename'], dest / pin['retainAs'])
    dump(dest / 'licenses/dependency-source-audit.json', dependency_audit)
    for source, target in [(ROOT / 'tools/iqtree/upstream-dependency-evidence.txt', 'licenses/upstream-dependency-evidence.txt'), (ROOT / 'tools/iqtree/adapter.py', 'adapter.py'), (ROOT / 'tools/iqtree/adapter.py', 'licenses/adapter.py'),
        (LOCK, 'licenses/input-lock.json'), (ROOT / 'scripts/fetch_iqtree_build_inputs.py', 'licenses/fetch_iqtree_build_inputs.py'),
        (ROOT / 'scripts/prepare_iqtree_pack.py', 'licenses/prepare_iqtree_pack.py'), (ROOT / 'LICENSE', 'licenses/Workbench-MIT.txt'),
        (ROOT / 'docs/IQTREE-PACK.md', 'PACK-README.md')]:
        copy_checked(source, dest / target)
    with tarfile.open(cache / 'source.tar.gz') as archive:
        for path, name in [('LICENSE', 'IQTREE-GPL-2.0.txt'), ('.github/workflows/ci.yaml', 'upstream-build-workflow.yaml')]:
            (dest / 'licenses' / name).write_bytes(archive.extractfile('iqtree3-3.1.4/' + path).read())
    imports = {}
    for name in ('iqtree3.exe', 'libiomp5md.dll'):
        result = subprocess.run(['objdump', '-p', str(dest / 'bin' / name)], check=True, capture_output=True, text=True)
        imports[name] = [line.split('DLL Name:', 1)[1].strip() for line in result.stdout.splitlines() if 'DLL Name:' in line]
    dump(dest / 'licenses/windows-imports.json', imports)
    dump(dest / 'licenses/provenance.json', {'schema': 1, 'packId': 'iqtree', 'packVersion': PACK_VERSION, 'iqtreeVersion': VERSION,
        'sourceCommit': lock['iqtreeCommit'], 'sourceTag': 'v3.1.4', 'inputLockSha256': sha(LOCK), 'windowsExecuted': False,
        'upstreamExecutableSha256': sha(dest / 'bin/iqtree3.exe'), 'openmpSha256': sha(dest / 'bin/libiomp5md.dll'),
        'upstreamPatch': None, 'windowsImports': imports, 'privateRuntime': 'CPython 3.13.16 embeddable Windows x64; stdlib-only isolated adapter',
        'intelOpenmpVersion': '5.0.20140611, build 2014-06-13 19:04:41 UTC, Intel C++14.0',
        'intelLicensingReference': 'https://community.intel.com/t5/Software-Archive/Intel-OpenMP-licensing-and-static-linking/m-p/1082427',
        'licenseScope': 'Upstream IQ-TREE GPLv2 source and submodules retained. Bundled source retains third-party notices. Historical OpenMP Intel/LLVM license notice retained; not claimed to reproduce exact Intel DLL. CPython original notices and source retained.',
        'dependencySourceAudit': dependency_audit, 'upstreamWindowsDependencyVersions': lock['windowsDependencyEvidence'],
        'sourceReproductionScope': 'Matching official IQ-TREE/source/submodules, complete Boost1.84 and Eigen3.4 source, exact Eigen package headers, all252 Cargo.lock registry sources and pinned phylo_grad, plus Rust1.98.1 standard-library sources; build workflow and dated CI version evidence retained. Compiler runtime notices/exceptions retained separately. Not a claim of bit-for-bit compiler reconstruction.'})
    (dest / 'licenses/NOTICE.txt').write_text('IQ-TREE 3.1.4: GNU GPL version 2; exact tag source and submodule archives retained. No upstream algorithm or executable changes.\nIntel OpenMP performance library 5.0.20140611: Copyright (C) 1997-2014 Intel Corporation. Historical open-source Intel/LLVM OpenMP license retained in Intel-OpenMP-LICENSE.txt; upstream official Windows distribution supplies this exact library.\nCorresponding compiled dependency sources: Boost1.84 (BSL1.0), Eigen3.4 (MPL2 plus original component notices), all252 Rust Cargo.lock registry archives, phylo_grad pinned source, Rust1.98.1 standard-library source. Their original source archives retain license/copyright notices; input-lock.json pins each archive. GCC14.2 libstdc++/libgcc runtime uses GPLv3 plus GCC Runtime Library Exception3.1, retained separately.\nCPython: PSF license and bundled component notices in bin/LICENSE.txt and python-source.tar.xz. Workbench adapter, fixture construction and pack recipe: MIT. See input-lock.json and provenance.json for exact input sources and scope.\n', encoding='utf-8')
    fixtures(dest / 'fixtures')
    workflows, schema = definitions()
    dump(dest / 'workbench-schema.json', schema)
    dump(dest / 'workbench-checks.json', checks())
    sections = []
    def section(name, values):
        sections.append('[' + name + ']\n' + '\n'.join(k + '=' + str(v) for k, v in values.items() if k != 'id' or name == 'pack') + '\n')
    section('pack', {'format': 2, 'id': 'iqtree', 'version': PACK_VERSION, 'name': 'IQ-TREE phylogenetic inference', 'platform': 'windows-x86_64', 'description': 'Local nucleotide/protein maximum-likelihood trees, model selection and optional branch support. Workbench 0.6.0 or newer.', 'color': '#5B7F6B'})
    for identity, file, version in [('iqtree', 'iqtree3.exe', VERSION), ('python', 'python.exe', lock['pythonVersion'])]:
        section('tool:' + identity, {'path': 'bin/' + file, 'version': version, 'sha256': sha(dest / 'bin' / file)})
    explicit = {'adapter': 'adapter.py', 'workbench-schema': 'workbench-schema.json', 'workbench-checks': 'workbench-checks.json', 'fixture-nucleotide': 'fixtures/nucleotide.afa', 'fixture-protein': 'fixtures/protein.afa'}
    used = {'bin/iqtree3.exe', 'bin/python.exe'}
    for identity, relative in explicit.items():
        section('asset:' + identity, {'path': relative, 'sha256': sha(dest / relative)})
        used.add(relative)
    for n, path in enumerate(sorted(dest.rglob('*'))):
        relative = path.relative_to(dest).as_posix()
        if path.is_file() and relative not in used and not relative.startswith('licenses/') and relative != 'PACK-README.md':
            section('asset:runtime-' + str(n), {'path': relative, 'sha256': sha(path)})
    for wf in workflows:
        section('workflow:' + wf['id'], {'name': wf['name'], 'description': wf['description'], 'inputs': ','.join(x['id'] for x in wf['inputs']), 'outputs': ','.join(x['id'] for x in wf['outputs']), 'steps': ','.join(x['id'] for x in wf['steps'])})
        for kind in ('input', 'output', 'step'):
            for item in wf[kind + 's']:
                section(kind + ':' + wf['id'] + ':' + item['id'], item)
    (dest / 'pack.ini').write_text('\n'.join(sections), encoding='utf-8')
    sys.path.insert(0, str(ROOT / 'workspace'))
    from catalog import load_pack
    pack = load_pack(dest / 'pack.ini')
    print(json.dumps({'pack': str(dest), 'manifestSha256': sha(dest / 'pack.ini'), 'workflows': list(pack['workflows']), 'windowsExecuted': False, 'fileCount': sum(p.is_file() for p in dest.rglob('*'))}, indent=2))


if __name__ == '__main__':
    main()
