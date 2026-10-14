#!/usr/bin/env python3
"""Build pinned Prodigal and a native validating launcher; no analysis-time runtime."""
import argparse, concurrent.futures, difflib, hashlib, json, os, re, shutil, struct, subprocess, tarfile, urllib.request
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
UPSTREAM_VERSION = '2.6.3'
VERSION = '2.6.3-workbench1'
SOURCE_COMMIT = '004218fbeb2cf54fe12d88ec2eede6a27d70ebf7'
SOURCE_NAME = 'prodigal-2.6.3.tar.gz'
SOURCE_URL = 'https://codeload.github.com/hyattpd/Prodigal/tar.gz/' + SOURCE_COMMIT
SOURCE_SHA256 = '9caafa079a29ff8f02b5ea84729fec4ecf03975c9ccf4acade4909368b69f317'
TC_NAME = 'llvm-mingw-20260922-ucrt-ubuntu-22.04-x86_64'
WINDOWS_STACK_RESERVE = 8 * 1024 * 1024
WINDOWS_STACK_COMMIT = 64 * 1024
def sha(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def pe_stack(path):
    data=Path(path).read_bytes()
    if len(data)<64 or data[:2]!=b'MZ':raise ValueError('Expected PE executable')
    pe=struct.unpack_from('<I',data,60)[0];optional=pe+24
    if len(data)<optional+88 or data[pe:pe+4]!=b'PE\0\0' or struct.unpack_from('<H',data,optional)[0]!=0x20b:raise ValueError('Expected PE32+ executable')
    return struct.unpack_from('<QQ',data,optional+72)

def prepare(cache, fetch=False, upstream=False):
    cache.mkdir(parents=True, exist_ok=True); archive = cache / SOURCE_NAME
    if not archive.exists() and fetch:
        with urllib.request.urlopen(SOURCE_URL, timeout=120) as stream: archive.write_bytes(stream.read())
    if not archive.is_file() or sha(archive) != SOURCE_SHA256: raise ValueError('Missing/changed Prodigal source; use --fetch with an empty cache')
    source = cache / ('source-pristine' if upstream else 'source-workbench')
    source.mkdir(exist_ok=True)
    pristine = {}
    with tarfile.open(archive) as stream:
        for member in stream.getmembers():
            parts = Path(member.name).parts
            if not parts or parts[0] != 'Prodigal-' + SOURCE_COMMIT or '..' in parts or not (member.isfile() or member.isdir()): raise ValueError('Unsafe source archive')
            if member.isfile():
                relative = Path(*parts[1:]); data = stream.extractfile(member).read()
                destination = source / relative; destination.parent.mkdir(parents=True, exist_ok=True); destination.write_bytes(data); pristine[str(relative)] = data
    if not upstream:
        # The source appends strings with overlapping sprintf(src, "%s...", src),
        # undefined by C and observably different between CRT implementations.
        # Append to the existing terminator instead; scientific calculations stay untouched.
        total = 0
        pattern = re.compile(r'sprintf\((genes\[i\]\.(?:gene_data|score_data)|run_data),\s*"%s([^"\n]*(?:\\"[^"\n]*)*)",\s*\1(?=\s*[,\)])')
        for name in ('gene.c', 'node.c'):
            path = source / name
            text, count = pattern.subn(lambda m: 'sprintf(' + m[1] + ' + strlen(' + m[1] + '), "' + m[2] + '"', path.read_text())
            path.write_text(text); total += count
        if total != 14: raise ValueError('Unexpected upstream append patch context: ' + str(total))
        path = source / 'main.c'; text = path.read_text()
        if text.count('#define VERSION "2.6.3"') != 1: raise ValueError('Version patch context changed')
        path.write_text(text.replace('#define VERSION "2.6.3"', '#define VERSION "' + VERSION + '"'))
        changes = []
        for relative, old in sorted(pristine.items()):
            new = (source / relative).read_bytes()
            if old != new: changes.extend(difflib.unified_diff(old.decode().splitlines(True), new.decode().splitlines(True), fromfile='a/' + relative, tofile='b/' + relative))
        (cache / 'workbench1.patch').write_text(''.join(changes))
    return source

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--cache', type=Path, default=ROOT/'build/prodigal'); p.add_argument('--toolchain', type=Path, default=ROOT/'build/toolchains'/TC_NAME)
    p.add_argument('--fetch', action='store_true'); p.add_argument('--linux', action='store_true'); p.add_argument('--upstream', action='store_true'); p.add_argument('--jobs', type=int, default=2)
    p.add_argument('--cc'); p.add_argument('--cxx'); p.add_argument('--objdump'); a = p.parse_args()
    if a.upstream and not a.linux: p.error('--upstream is the separate pristine Linux reference only')
    cache = a.cache.resolve(); tc = a.toolchain.resolve(); source = prepare(cache, a.fetch, a.upstream)
    target = 'reference-linux' if a.upstream else ('build-linux' if a.linux else 'build-windows')
    out = cache/target; out.mkdir(exist_ok=True); env = dict(os.environ)
    if not a.linux and os.name != 'nt': env['LD_LIBRARY_PATH'] = str(tc/'lib'); env['PATH'] = str(tc/'bin')+os.pathsep+env.get('PATH','')
    cc = a.cc or ('gcc' if a.linux else str(tc/'bin/x86_64-w64-mingw32-clang'))
    cxx = a.cxx or ('g++' if a.linux else str(tc/'bin/x86_64-w64-mingw32-clang++'))
    flags = ['-O2', '-march=x86-64', '-mtune=generic', '-mno-avx', '-mno-avx2']
    if a.upstream: flags += ['-U_FORTIFY_SOURCE', '-D_FORTIFY_SOURCE=0']  # Pristine overlapping sprintf needs the traditional libc path for reference-only comparison.
    (out/'tmp').mkdir(exist_ok=True); env['TMPDIR'] = str(out/'tmp')
    sources = sorted(source.glob('*.c')); commands = []
    def compile_one(path):
        obj = out/(path.name+'.o'); cmd = [cc, *flags, '-c', str(path), '-o', str(obj)]
        subprocess.run(cmd, env=env, cwd=out, check=True, capture_output=True); return obj, cmd
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1,a.jobs)) as pool:
        built = list(pool.map(compile_one, sources))
    objects = [x[0] for x in built]; commands.extend(x[1] for x in built)
    suffix = '' if a.linux else '.exe'; binary = out/('prodigal'+suffix)
    link = [] if a.linux else ['-static', '-Wl,--no-insert-timestamp']
    # Upstream train_starts_nonsd has about 1.25 MiB of fixed local arrays.
    # The PE default 1 MiB stack overflows in both forced and auto non-SD training.
    # Match the ordinary Linux 8 MiB reservation without changing the algorithm.
    prodigal_link = link + ([] if a.linux else ['-Xlinker','--stack','-Xlinker',str(WINDOWS_STACK_RESERVE)+','+str(WINDOWS_STACK_COMMIT)])
    cmd = [cc, *map(str,objects), '-lm', *prodigal_link, '-o', str(binary)]; subprocess.run(cmd,env=env,cwd=out,check=True); commands.append(cmd)
    files = [binary]
    if not a.upstream:
        guard = out/('prodigal-guard'+suffix)
        cmd = [cxx, *flags, '-std=c++17', '-Wall', '-Wextra', '-Werror', str(ROOT/'tools/prodigal/guard.cpp'), *link, '-o', str(guard)]
        subprocess.run(cmd,env=env,cwd=out,check=True); commands.append(cmd); files.append(guard)
    record = {'schema':1,'builderSha256':sha(Path(__file__)),'tool':'prodigal','version':UPSTREAM_VERSION if a.upstream else VERSION,'upstreamVersion':UPSTREAM_VERSION,'sourceCommit':SOURCE_COMMIT,'sources':{SOURCE_NAME:{'url':SOURCE_URL,'sha256':SOURCE_SHA256}},'platform':'linux-x86_64' if a.linux else 'windows-x86_64','executionTestsPerformedByBuild':False,'cpu':'baseline x86-64; no AVX/AVX2 required','compiler':subprocess.check_output([cc,'--version'],env=env,text=True).splitlines()[0],'guardCompiler':subprocess.check_output([cxx,'--version'],env=env,text=True).splitlines()[0],'compilerSha256':sha(shutil.which(cc) or cc),'guardCompilerSha256':sha(shutil.which(cxx) or cxx),'commands':commands,'files':{}}
    if not a.linux:
        record['toolchainFiles'] = {str(p.relative_to(tc)):sha(p) for p in (tc/'bin/clang',tc/'bin/lld',tc/'LICENSE.TXT') if p.is_file()}
    if not a.upstream: record.update(patchSha256=sha(cache/'workbench1.patch'),guardSourceSha256=sha(ROOT/'tools/prodigal/guard.cpp'))
    for file in files:
        info = {'bytes':file.stat().st_size,'sha256':sha(file)}
        if not a.linux:
            reserve,commit=pe_stack(file);info.update(stackReserveBytes=reserve,stackCommitBytes=commit)
            if file==binary and (reserve,commit)!=(WINDOWS_STACK_RESERVE,WINDOWS_STACK_COMMIT):raise ValueError('Prodigal PE stack configuration differs')
            cmd = [a.objdump,'-p',str(file)] if a.objdump else [str(tc/'bin/llvm-readobj'),'--coff-imports',str(file)]
            imports = subprocess.check_output(cmd,env=env,text=True); (out/(file.stem+'.imports.txt')).write_text(imports)
            info['imports'] = re.findall(r'(?:^  Name: |DLL Name: )([^\r\n]+)',imports,re.M)
            if not info['imports'] or any(x.lower() not in {'kernel32.dll','msvcrt.dll'} and not x.lower().startswith('api-ms-win-crt-') for x in info['imports']): raise ValueError('Unexpected Windows DLL dependency: '+repr(info['imports']))
        record['files'][file.name] = info
    (out/'build.json').write_text(json.dumps(record,indent=2)+'\n'); print(json.dumps({'build':str(out),'files':record['files']},indent=2))
if __name__ == '__main__': main()
