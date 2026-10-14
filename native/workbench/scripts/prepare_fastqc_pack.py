#!/usr/bin/env python3
"""Prepare FastQC 0.13.0 and a private Windows JRE for Native Workbench 0.6.0."""
import argparse
import gzip
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'desktop'))
from prepare_modular_packs import field, number, artifact, execute, workflow
PACK_VERSION = '1.0.0'
VERSION = '0.13.0'
JRE = 'OpenJDK8U-jre_x64_windows_hotspot_8u504b01.zip'
JAVA_SOURCE = 'OpenJDK8U-jdk-sources_8u504b01.tar.gz'
JDK = 'OpenJDK8U-jdk_x64_linux_hotspot_8u504b01.tar.gz'
JAVA_BASE = 'https://github.com/adoptium/temurin8-binaries/releases/download/jdk8u504-b01/'
SOURCES = {
    'fastqc_v0.13.0.zip': ('https://github.com/s-andrews/FastQC/releases/download/v0.13.0/fastqc_v0.13.0.zip', 'c9504d47752e79ecfe61691e09bf367fc3f15167ac3fe83d9e33534fffbcc301'),
    'FastQC-v0.13.0-source.tar.gz': ('https://codeload.github.com/s-andrews/FastQC/tar.gz/refs/tags/v0.13.0', '68c1c84775ee9e7ec41cf45ba770f217d17d5d377c3fcad13b5b4389c483e69f'),
    'commons-io-2.22.0-sources.jar': ('https://repo.maven.apache.org/maven2/commons-io/commons-io/2.22.0/commons-io-2.22.0-sources.jar', 'de5acfae5fa2735276df7facf46cdb0347374208ea47db246b554fae59277fb5'),
    'commons-compress-1.28.0-sources.jar': ('https://repo.maven.apache.org/maven2/org/apache/commons/commons-compress/1.28.0/commons-compress-1.28.0-sources.jar', '6de9de4559f12bba6d41789c72f6a2a424514f2d2a3f7f49e2a3c52414db9632'),
}
JAVA_SOURCES = {
    JRE: (JAVA_BASE + JRE, '82e2cdc6693737c5998445b31f69668fa0da77c7705121053f6508ac84961123'),
    JAVA_SOURCE: (JAVA_BASE + JAVA_SOURCE, '86cd14f299616dddca13268cc2fa794eb4d28fc732dedaad8c5b8a3078e5d3c9'),
    'Microsoft-VC-Runtime-2015-2022-License.docx': ('https://visualstudio.microsoft.com/wp-content/uploads/2021/09/Visual-C-Runtime-2015-2022-License-1.docx', 'f1e3d56ceb2ad68aae0711b910375009e651ac5530fa0760f0dea6e81e54fae1'),
}
JDK_PIN = '9c70e102f527ac674ac2fe9c7d47b9a04e2d19842ba5ab8e9b33f368bbadfaea'
CITATION = {'text': 'Andrews S (2010). FastQC: a quality control tool for high throughput sequence data. Babraham Bioinformatics.', 'url': 'https://www.bioinformatics.babraham.ac.uk/projects/fastqc/'}


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''): h.update(block)
    return h.hexdigest()


def dump(path, value):
    Path(path).write_text(json.dumps(value, indent=2) + '\n', encoding='utf-8')


def fetch_pins(folder, pins, fetch):
    folder.mkdir(parents=True, exist_ok=True)
    for name, (url, pin) in pins.items():
        target = folder / name
        if not target.exists() and fetch:
            temporary = target.with_name(name + '.partial')
            urllib.request.urlretrieve(url, temporary)
            if sha(temporary) != pin: raise ValueError('Downloaded checksum differs: ' + name)
            temporary.replace(target)
        if not target.is_file() or sha(target) != pin: raise ValueError('Missing or changed pinned input: ' + str(target))


def definitions():
    workflows, schemas = [], {}
    for paired in (False, True):
        identity = 'paired' if paired else 'single'
        keys = ('reads1', 'reads2') if paired else ('reads',)
        fields = [field(key, 'Read 2 FASTQ' if key == 'reads2' else 'Read 1 FASTQ' if paired else 'Reads FASTQ',
                        filter='FASTQ reads|*.fastq;*.fq;*.fastq.gz;*.fq.gz|All files|*.*',
                        help='Plain or gzip FASTQ with four lines per record. All records and selected quality encoding are validated before QC.',
                        **({'different-from': 'reads1'} if key == 'reads2' else {})) for key in keys]
        fields += [field('quality-offset', 'FASTQ quality encoding', 'choice', default='33', choices='33:Phred+33 (modern sequencing)|64:Phred+64 (legacy Illumina)',
                         help='Choose the documented encoding of the input data. It is not inferred from high-quality reads.'),
                   number('threads', 'CPU threads per file', 2, 1, 4, help='FastQC 0.13 can use up to four workers per file. The two mate files run sequentially.'),
                   number('memory', 'FastQC Java heap (MiB)', 512, 512, 16384, help='Maximum heap for one FastQC process; allow additional memory for Java and the Workbench. Increase for very long reads.')]
        outputs, products = [], []
        for mate in range(1, 3 if paired else 2):
            for name, label, kind, filename in [('report', 'HTML report', 'report', 'fastqc.html'), ('archive', 'Original FastQC ZIP', 'metrics', 'fastqc.zip'),
                                                 ('data', 'FastQC machine-readable data', 'metrics', 'fastqc_data.txt'), ('summary', 'FastQC module flags', 'metrics', 'summary.txt')]:
                key = name + str(mate)
                outputs.append(artifact(key, ('Read ' + str(mate) + ': ' if paired else '') + label, 'qc/read' + str(mate) + '/' + filename))
                products.append(dict(id=key, type=kind, manifestOutputs=[key]))
        outputs.append(artifact('input-check', 'Input validation', 'qc/input-validation.json'))
        products.append(dict(id='input-check', type='metrics', manifestOutputs=['input-check']))
        args = ['-Xms32m', '-Xmx128m', '-XX:+ExitOnOutOfMemoryError', '-XX:+DisableAttachMechanism', '-XX:-UsePerfData', '-Djava.awt.headless=true',
                '-Dfile.encoding=UTF-8', '-cp', ';'.join('{asset:' + key + '}' for key in ('adapter', 'fastqc', 'commons-io', 'commons-compress')),
                'WorkbenchFastQC', identity, '{input:reads1}' if paired else '{input:reads}', '{input:reads2}' if paired else '-', '{run}/qc',
                '{input:threads}', '{input:memory}', '{input:quality-offset}']
        workflows.append(workflow(identity, 'FastQC: ' + ('paired reads' if paired else 'one FASTQ file'),
                                  'Read quality profiles, adapter and duplication checks using unmodified FastQC 0.13.0, with offline HTML and machine-readable outputs.',
                                  fields, outputs, [execute('quality-control', 'Validate reads and run FastQC', 'java', args, produces=[x['id'] for x in outputs])]))
        schemas[identity] = dict(ports=[dict(id='reads', type='pair' if paired else 'reads', manifestInputs=list(keys), min=1, max=1)], outputs=products,
                                methods='FASTQ structure and the selected quality encoding were validated' + (' together with mate identity, order and count' if paired else '') + '. Read quality was assessed with unmodified FastQC 0.13.0 using the recorded encoding, worker and Java heap settings. The default upstream modules, adapter/contaminant lists, grouping and thresholds were retained; no read filtering or trimming was performed. ' + ('Each mate file was assessed independently. ' if paired else '') + 'Self-contained HTML, original FastQC ZIP, machine-readable data and module flags were retained. Module warnings/failures require interpretation in the experimental context and do not by themselves establish sample suitability.',
                                pathPolicy={'asciiOnly': True, 'forbiddenCharacters': [';']})
    return workflows, dict(schema=1, category='Read quality', citations=[CITATION], workflows=schemas)


def fixtures(folder):
    folder.mkdir(parents=True, exist_ok=True)
    # Exact independent truth: 20 x 40 bases, GC 50%, Q40. Deliberate duplicates.
    for mate in (1, 2):
        data = ''.join('@synthetic%d/%d\n%s\n+\n%s\n' % (n, mate, ('ACGT' if mate == 1 else 'TGCA') * 10, 'I' * 40) for n in range(20)).encode('ascii')
        (folder / ('reads%d.fastq' % mate)).write_bytes(data)
        with (folder / ('reads%d.fastq.gz' % mate)).open('wb') as raw:
            with gzip.GzipFile(filename='', mode='wb', fileobj=raw, mtime=0) as stream: stream.write(data)
    dump(folder / 'truth.json', {'recordsPerFile': 20, 'basesPerFile': 800, 'length': 40, 'gcPercent': 50, 'meanQuality': 40,
                                'purpose': 'Synthetic software regression; not a biological acceptance threshold or clinical validation.'})


def checks():
    result = []
    for paired in (False, True):
        expected = []
        for mate in range(1, 3 if paired else 2):
            expected += [dict(output='data' + str(mate), kind='text', contains=['##FastQC\t0.13.0', 'Total Sequences\t20', 'Total Bases\t800 bp',
                            'Sequence length\t40', 'Mean Length\t40', 'Median Length\t40', '%GC\t50', '1\t40.0\t']),
                         dict(output='report' + str(mate), kind='text', contains=['FastQC Report', 'Per base sequence quality', 'data:image/'])]
        expected.append(dict(output='input-check', kind='text', contains=['"valid":true', '"recordsPerFile":20', '"qualityOffset":33']))
        result.append(dict(id='known-' + ('paired-gzip' if paired else 'single-plain'), workflow='paired' if paired else 'single',
                           params={'threads': 2, 'memory': 512, 'quality-offset': '33'},
                           inputs={'reads': [{'reads1': 'fixture-read1-gz', 'reads2': 'fixture-read2-gz'}] if paired else [{'reads': 'fixture-read1'}]}, expect=expected))
    return dict(schema=1, checks=result)


def zip_bytes(path, items):
    with zipfile.ZipFile(path, 'x', compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for name, data in sorted(items):
            info = zipfile.ZipInfo(name, (2026, 10, 4, 0, 0, 0)); info.compress_type = zipfile.ZIP_DEFLATED; info.external_attr = 0o100644 << 16
            archive.writestr(info, data)


def prepare(vendor, java_cache, destination, jdk, fetch=False):
    fetch_pins(vendor, SOURCES, fetch); fetch_pins(java_cache, JAVA_SOURCES, fetch)
    if destination.exists() and any(destination.iterdir()): raise ValueError('Destination must be new or empty: ' + str(destination))
    for name in ('runtime/java', 'assets', 'fixtures', 'licenses'): (destination / name).mkdir(parents=True, exist_ok=True)
    supplied_jdk = jdk is not None
    if jdk is None:
        fetch_pins(java_cache, {JDK: (JAVA_BASE + JDK, JDK_PIN)}, fetch)
        jdk = java_cache / 'linux/jdk8u504-b01'
        if not jdk.is_dir():
            jdk.parent.mkdir(parents=True, exist_ok=True)
            with tarfile.open(java_cache / JDK) as archive: archive.extractall(jdk.parent, filter='data')
    javac = jdk / 'bin' / ('javac.exe' if os.name == 'nt' else 'javac')
    env = dict(os.environ)
    if os.name != 'nt': env['LD_LIBRARY_PATH'] = str(jdk / 'jre/lib/amd64/jli') + (':' + env['LD_LIBRARY_PATH'] if env.get('LD_LIBRARY_PATH') else '')
    compiler_version = subprocess.run([str(javac), '-version'], env=env, capture_output=True, text=True, check=True).stderr.strip()
    if 'javac 1.8.0_504' not in compiler_version: raise ValueError('Adapter requires pinned Temurin javac 1.8.0_504; got ' + compiler_version)
    classes = vendor / 'adapter-classes'
    if classes.exists(): shutil.rmtree(classes)
    classes.mkdir()
    command = [str(javac), '-encoding', 'UTF-8', '-source', '8', '-target', '8', '-d', str(classes), str(ROOT / 'tools/fastqc/WorkbenchFastQC.java')]
    subprocess.run(command, env=env, check=True)
    zip_bytes(destination / 'assets/workbench-fastqc.jar', [(p.relative_to(classes).as_posix(), p.read_bytes()) for p in classes.rglob('*.class')])
    with zipfile.ZipFile(vendor / 'fastqc_v0.13.0.zip') as archive:
        # Repackage unmodified classes/resources into one jar to stay below import limits.
        prefixes = ('uk/', 'org/', 'net/', 'Templates/', 'Configuration/')
        items = [(n[len('FastQC/'):], archive.read(n)) for n in archive.namelist() if n.startswith('FastQC/') and not n.endswith('/') and n[len('FastQC/'):].startswith(prefixes)]
        zip_bytes(destination / 'assets/fastqc-0.13.0.jar', items)
        for name in ('commons-io-2.22.0.jar', 'commons-compress-1.28.0.jar'):
            (destination / 'assets' / name).write_bytes(archive.read('FastQC/' + name))
            with zipfile.ZipFile(destination / 'assets' / name) as dependency:
                for member in dependency.namelist():
                    if member.upper().endswith(('LICENSE.TXT', 'NOTICE.TXT')):
                        (destination / 'licenses' / (name + '-' + Path(member).name)).write_bytes(dependency.read(member))
        for name in ('LICENSE', 'README.md', 'RELEASE_NOTES.txt', 'INSTALL.md'):
            (destination / 'licenses' / ('FastQC-' + name)).write_bytes(archive.read('FastQC/' + name))
    with zipfile.ZipFile(java_cache / JRE) as archive:
        for item in archive.infolist():
            if item.is_dir(): continue
            relative = Path(*Path(item.filename).parts[1:]); target = destination / 'runtime/java' / relative
            target.parent.mkdir(parents=True, exist_ok=True); target.write_bytes(archive.read(item))
        for name in ('LICENSE', 'NOTICE', 'ASSEMBLY_EXCEPTION', 'THIRD_PARTY_README', 'THIRD_PARTY_LICENSE'):
            target = destination / 'runtime/java' / name
            if target.is_file(): shutil.copy2(target, destination / 'licenses' / ('Java-' + name))
    for cache, names in ((vendor, ['FastQC-v0.13.0-source.tar.gz', 'commons-io-2.22.0-sources.jar', 'commons-compress-1.28.0-sources.jar']), (java_cache, [JAVA_SOURCE, 'Microsoft-VC-Runtime-2015-2022-License.docx'])):
        for name in names: shutil.copy2(cache / name, destination / 'licenses' / name)
    for path in ('tools/fastqc/WorkbenchFastQC.java', 'scripts/prepare_fastqc_pack.py', 'LICENSE'):
        shutil.copy2(ROOT / path, destination / 'licenses' / Path(path).name)
    components = [{'path': p.relative_to(destination).as_posix(), 'sha256': sha(p)} for p in sorted((destination / 'runtime/java/bin').glob('*.dll')) if p.name.lower().startswith(('api-ms-win-', 'msvcp', 'vcruntime', 'ucrtbase'))]
    dump(destination / 'licenses/Microsoft-runtime-components.json', {'origin': JAVA_BASE + JRE, 'license': 'Separate Microsoft proprietary runtime components, not OpenJDK GPL/ClassPath code.',
         'licenseDocument': 'Microsoft-VC-Runtime-2015-2022-License.docx', 'officialLicense': 'https://visualstudio.microsoft.com/license-terms/vs2022-cruntime/',
         'redistributionInformation': 'https://learn.microsoft.com/en-us/visualstudio/releases/2022/redistribution', 'components': components})
    workflows, schema = definitions(); dump(destination / 'workbench-schema.json', schema); dump(destination / 'workbench-checks.json', checks()); fixtures(destination / 'fixtures')
    assets = {'adapter': 'assets/workbench-fastqc.jar', 'fastqc': 'assets/fastqc-0.13.0.jar', 'commons-io': 'assets/commons-io-2.22.0.jar', 'commons-compress': 'assets/commons-compress-1.28.0.jar',
              'workbench-schema': 'workbench-schema.json', 'workbench-checks': 'workbench-checks.json', 'fixture-truth': 'fixtures/truth.json'}
    for mate in (1, 2):
        for suffix, ext in (('', ''), ('-gz', '.gz')): assets['fixture-read' + str(mate) + suffix] = 'fixtures/reads' + str(mate) + '.fastq' + ext
    for path in sorted((destination / 'runtime/java').rglob('*')):
        if path.is_file() and path.relative_to(destination).as_posix() != 'runtime/java/bin/java.exe':
            relative = path.relative_to(destination).as_posix(); assets['runtime-' + hashlib.sha256(relative.encode()).hexdigest()[:16]] = relative
    sections = []
    def section(name, values):
        sections.append('[' + name + ']\n' + '\n'.join(k + '=' + str(v) for k, v in values.items() if k != 'id' or name == 'pack') + '\n')
    section('pack', dict(format=2, id='fastqc', version=PACK_VERSION, name='FastQC read quality', platform='windows-x86_64', color='#528EB0',
                         description='Real FastQC 0.13.0 quality control of single or paired FASTQ, offline reports and MultiQC-compatible metrics. Private Java included.'))
    section('tool:java', dict(path='runtime/java/bin/java.exe', version='Temurin-8u504-b01', sha256=sha(destination / 'runtime/java/bin/java.exe')))
    for identity, path in assets.items(): section('asset:' + identity, dict(path=path, sha256=sha(destination / path)))
    for wf in workflows:
        section('workflow:' + wf['id'], dict(name=wf['name'], description=wf['description'], inputs=','.join(x['id'] for x in wf['inputs']), outputs=','.join(x['id'] for x in wf['outputs']), steps=','.join(x['id'] for x in wf['steps'])))
        for kind in ('input', 'output', 'step'):
            for item in wf[kind + 's']: section(kind + ':' + wf['id'] + ':' + item['id'], item)
    (destination / 'pack.ini').write_text('\n'.join(sections), encoding='utf-8')
    shutil.copy2(ROOT / 'docs/FASTQC-PACK.md', destination / 'PACK-README.md')
    dump(destination / 'licenses/provenance.json', {'schema': 1, 'packId': 'fastqc', 'packVersion': PACK_VERSION, 'toolVersion': VERSION,
         'minAppVersion': '0.6.0', 'sourcePins': {n: {'url': v[0], 'sha256': v[1]} for n, v in {**SOURCES, **JAVA_SOURCES}.items()},
         'adapterCompiler': compiler_version, 'adapterCompilerArchiveSha256': None if supplied_jdk else JDK_PIN,
         'adapterCompilerExecutableSha256': sha(javac), 'adapterCompilerSuppliedExplicitly': supplied_jdk,
         'adapterSourceSha256': sha(ROOT / 'tools/fastqc/WorkbenchFastQC.java'),
         'adapterCompileArguments': ['javac', '-encoding', 'UTF-8', '-source', '8', '-target', '8', '-d', '<build-classes>', 'WorkbenchFastQC.java'],
         'runtime': 'Complete unmodified official Temurin 8u504-b01 x64 Windows JRE', 'upstreamClassesModified': False,
         'packaging': 'Unmodified FastQC classes and resources repackaged into a jar. Only FASTQ interface exposed; HTSJDK/JHDF5 dependency jars not needed or distributed at runtime.',
         'adapter': 'Strict four-line FASTQ/encoding/pair validation; direct shell-free Java process; run-local output/temp directories; verify read count; retain original report bytes and extract text by fixed archive member suffix.',
         'windowsExecutedDuringBuild': False, 'citation': CITATION})
    sys.path.insert(0, str(ROOT / 'workspace'))
    from catalog import load_pack
    pack = load_pack(destination / 'pack.ini')
    return {'packRoot': str(destination), 'packId': 'fastqc', 'packVersion': PACK_VERSION, 'manifestSha256': sha(destination / 'pack.ini'), 'workflows': list(pack['workflows']),
            'files': sum(1 for p in destination.rglob('*') if p.is_file()), 'expandedBytes': sum(p.stat().st_size for p in destination.rglob('*') if p.is_file())}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--vendor', type=Path, default=ROOT / 'vendor-expanded/fastqc')
    parser.add_argument('--java-cache', type=Path, default=ROOT / 'vendor-expanded/java')
    parser.add_argument('--jdk', type=Path, help='Temurin 8u504-b01 JDK; Linux JDK is fetched/extracted when omitted')
    parser.add_argument('--destination', type=Path, default=ROOT / 'packs/fastqc-1.0.0')
    parser.add_argument('--fetch', action='store_true')
    args = parser.parse_args()
    print(json.dumps(prepare(args.vendor.resolve(), args.java_cache.resolve(), args.destination.resolve(), args.jdk.resolve() if args.jdk else None, args.fetch), indent=2))


if __name__ == '__main__': main()
