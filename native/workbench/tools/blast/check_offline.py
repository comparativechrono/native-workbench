#!/usr/bin/env python3
"""Native BLAST malformed-input/missing-database regression after pack import.

Runs installed, hash-verified native executables on synthetic data. This checks
local failure behavior and the reviewed source boundary; it does not claim that
the operating system's network was disabled. Never uses a remote BLAST query.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def snapshot(root):
    return {p.relative_to(root).as_posix():sha(p) for p in root.rglob('*') if p.is_file()}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--app-root',type=Path,required=True)
    p.add_argument('--report',type=Path,required=True)
    p.add_argument('--pack-version',default='1.0.0')
    args=p.parse_args()
    if os.name!='nt':p.error('This installed-pack regression must run on native Windows')
    app=args.app_root.resolve();sys.path.insert(0,str(app/'workspace'))
    from catalog import load_catalog,load_pack
    report=dict(schema=1,packId='blast',packVersion=args.pack_version,nativeWindowsHost=True,nativeWindowsExecuted=False,
                scope='Installed native BLAST local error-path regressions; no OS network-blocking claim',
                osNetworkBlocked=False,success=False,passed=0,failed=1,commands=[])
    before=None;pack_root=None;started=time.monotonic()
    try:
        choices=[x for x in load_catalog(app)['packs'] if x['id']=='blast' and x['version']==args.pack_version]
        if len(choices)!=1:raise ValueError('Expected exactly one installed BLAST pack at the requested version')
        pack_root=(app/choices[0]['folder']).resolve()
        if not pack_root.is_relative_to(app):raise ValueError('Pack escapes application')
        before=snapshot(pack_root);pack=load_pack(pack_root/'pack.ini')
        for name,tool in pack['tools'].items():
            if sha(pack_root/tool['path'])!=tool['sha256']:raise ValueError('Executable checksum differs: '+name)
        guard=pack_root/pack['tools']['guard']['path']
        def asset(identity):
            item=pack['assets'][identity];path=pack_root/item['path']
            if sha(path)!=item['sha256']:raise ValueError('Fixture checksum differs')
            return path
        query=asset('fixture-nucl-query-fa');subjects=asset('fixture-nucl-db-fa')
        results=app/'results';results.mkdir(exist_ok=True)
        folder=Path(tempfile.mkdtemp(prefix='blast offline check with spaces ',dir=results))
        report.update(folder=str(folder),manifestSha256=pack['manifestSha256'],guardSha256=sha(guard))
        def run(label,arguments,success=True):
            command=[str(guard),*map(str,arguments)]
            entry=dict(label=label,argv=command);report['commands'].append(entry)
            with (folder/(label+'.stdout.txt')).open('wb') as out,(folder/(label+'.stderr.txt')).open('wb') as err:
                with subprocess.Popen(command,cwd=folder,stdout=out,stderr=err) as process:
                    report['nativeWindowsExecuted']=True
                    try:code=process.wait(timeout=30)
                    except subprocess.TimeoutExpired:
                        subprocess.run([str(Path(os.environ['SystemRoot'])/'System32/taskkill.exe'),'/PID',str(process.pid),'/T','/F'],capture_output=True,timeout=15)
                        process.wait(timeout=10);raise ValueError(label+' timed out')
            entry['exitCode']=code
            entry['stdout']=(folder/(label+'.stdout.txt')).read_text(encoding='utf-8',errors='replace')[:8192]
            entry['stderr']=(folder/(label+'.stderr.txt')).read_text(encoding='utf-8',errors='replace')[:8192]
            if (code==0)!=success:raise ValueError(label+' returned unexpected exit status '+str(code))
            return entry['stderr']
        run('index',['run','makeblastdb','-in',subjects,'-dbtype','nucl','-parse_seqids','-blastdb_version','4','-out','private-db'])
        run('search',['run','blastn','-query',query,'-db','private-db','-task','blastn','-num_threads','2','-outfmt','11','-out','search.asn'])
        run('format-present',['run','blast_formatter','-archive','search.asn','-outfmt','6 qseqid sseqid pident length qstart qend sstart send','-out','present.tsv'])
        if (folder/'present.tsv').read_text().strip()!='nq\tns\t100.000\t120\t1\t120\t81\t200':raise ValueError('Unexpected known-coordinate native alignment')
        report['passed']+=1
        for path in folder.glob('private-db.*'):path.rename(path.with_name('removed-'+path.name))
        err=run('format-missing',['run','blast_formatter','-archive','search.asn','-outfmt','6','-out','missing.tsv'],False)
        if 'No alias or index file found' not in err:raise ValueError('Formatter did not report its absent local database')
        report['passed']+=1
        err=run('search-missing',['run','blastn','-query',query,'-db','private-db','-outfmt','6','-out','missing-search.tsv'],False)
        if 'No alias or index file found' not in err:raise ValueError('Search did not report its absent local database')
        report['passed']+=1
        bad=folder/'malformed.fa';bad.write_text('>broken\nACGT!\n',encoding='ascii')
        err=run('malformed',['validate','nucl',bad,folder/'malformed-validation.json'],False)
        if 'Invalid nucl residue' not in err:raise ValueError('Malformed FASTA failure is not attributable to the validator')
        report['passed']+=1
        for option in ('-remote','-rid'):
            err=run('rejected-'+option[1:],['run','blastn',option],False)
            if 'Remote BLAST is not permitted' not in err:raise ValueError('Network operation was not rejected at the boundary')
            report['passed']+=1
        report.update(success=True,failed=0)
    except Exception as error:report['error']=str(error)
    finally:
        if before is not None:
            report['installedPackUnchanged']=snapshot(pack_root)==before
            if not report['installedPackUnchanged']:report.update(success=False,failed=1,error='Installed pack was modified')
        report['elapsedSeconds']=round(time.monotonic()-started,3)
        args.report.parent.mkdir(parents=True,exist_ok=True)
        args.report.write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({k:report[k] for k in ('success','passed','failed','nativeWindowsExecuted')}))
    return 0 if report['success'] else 1


if __name__=='__main__':raise SystemExit(main())
