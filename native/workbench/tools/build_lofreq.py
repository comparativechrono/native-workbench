#!/usr/bin/env python3
"""Build hash-pinned LoFreq2.1.5 with HTSlib1.24 for Linux and Cosmopolitan.

No downloads. Port changes replace internal shell filtering with the same built-in
filter entry point and argv, reserve temporary VCFs in the private working directory,
and omit unused uniq/cdflib code. No calling/filter algorithm is changed.
HTSlib is built without remote access or optional compression plugins. Workflows
use one thread; no HTSlib worker threads are requested.
"""
import argparse, concurrent.futures, hashlib, json, os
from pathlib import Path
import re, shutil, subprocess, sys, tarfile
ROOT=Path(__file__).resolve().parents[1]
VENDOR=ROOT/'vendor-expanded/lofreq'
SOURCE_SHA='da85ec4baca21e20a55b5f9ee491cdda2986d0dc672177007a2c70ca1d804fe7'
SUBSET_SHA='5578d1ac7afd6d6ed8180b5d893322aef2389d58bd82258fabe3821186b8aa9e'
HTS_SHA='89b2a440123eeaa400392ce1736e7d60ce9041843027d76819753c5a8246bfdd'

def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def run(args,cwd,log,env):
    with log.open('wb') as out:
        out.write((json.dumps(list(map(str,args)))+'\n').encode());out.flush()
        subprocess.run(list(map(str,args)),cwd=cwd,stdout=out,stderr=out,env=env,check=True)
def patch(src):
    main=src/'src/lofreq/lofreq_main.c';main_text=main.read_text()
    main_text=main_text.replace('          return main_uniq(argc, argv);', '          fprintf(stderr, "uniq is unavailable in this Workbench build (unused cdflib dependency omitted)\\n");\n          return 1;')
    main.write_text(main_text)
    path=src/'src/lofreq/lofreq_call.c';text=path.read_text()
    if 'filter_argv' in text:return
    text=text.replace('char vcf_tmp_template[] = "/tmp/lofreq2-call-dyn-bonf.XXXXXX";', 'char vcf_tmp_template[] = "./lofreq2-call-dyn-bonf.XXXXXX";')
    text=text.replace('         vcf_tmp_out = strdup(mktemp(vcf_tmp_template));', '''         int temp_fd = mkstemp(vcf_tmp_template);
         if (temp_fd < 0) {
              LOG_FATAL("%s\\n", "Could not reserve temporary VCF in the working directory");
              return 1;
         }
         close(temp_fd);
         vcf_tmp_out = strdup(vcf_tmp_template);''')
    text=text.replace('#include "lofreq_call.h"','#include "lofreq_call.h"\n#include "lofreq_filter.h"')
    text=text.replace('         char cmd[BUF_SIZE];\n         int len;', '''         /* Workbench portability: direct argv dispatch, no shell/PATH lookup. */
         char *filter_argv[12] = {"lofreq", "filter", "-i", vcf_tmp_out,
                                  "-o", NULL==vcf_out ? "-" : vcf_out};
         char snv_threshold[32], indel_threshold[32];
         int filter_argc = 6;''')
    old='''         snprintf(cmd, BUF_SIZE,
                  "lofreq filter -i %s -o %s",
                  vcf_tmp_out, NULL==vcf_out ? "-" : vcf_out);
         len = strlen(cmd);
'''
    if old not in text:raise RuntimeError('Upstream shell block changed')
    text=text.replace(old,'')
    text=text.replace('              len += sprintf(cmd+len, " %s", "--no-defaults");','              filter_argv[filter_argc++] = "--no-defaults";')
    start=text.index('              len += sprintf(cmd+len,/* appending')
    end=text.index('         } else {',start)
    text=text[:start]+'''              snprintf(snv_threshold, sizeof(snv_threshold), "%d", snvqual_thresh);
              snprintf(indel_threshold, sizeof(indel_threshold), "%d", indelqual_thresh);
              filter_argv[filter_argc++] = "--snvqual-thresh";
              filter_argv[filter_argc++] = snv_threshold;
              filter_argv[filter_argc++] = "--indelqual-thresh";
              filter_argv[filter_argc++] = indel_threshold;
'''+text[end:]
    text=text.replace('''         LOG_VERBOSE("Executing %s\\n", cmd);
         if (0 != (rc = system(cmd))) {
              LOG_ERROR("The following command failed: %s\\n", cmd);''','''         LOG_VERBOSE("%s\\n", "Executing built-in lofreq filter directly");
         filter_argv[filter_argc] = NULL;
         optind = 0; /* reset getopt before calling the second CLI entry point */
         if (0 != (rc = main_filter(filter_argc, filter_argv))) {
              LOG_ERROR("%s\\n", "Built-in lofreq filter failed");''')
    if 'system(cmd)' in text:raise RuntimeError('Shell dispatch remained')
    path.write_text(text)

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--target',choices=['linux','cosmo','all'],default='all');p.add_argument('--jobs',type=int,default=2);p.add_argument('--resume',action='store_true');p.add_argument('--reference-comparator',action='store_true',help='Also build a Linux-only original shell-filter comparator for regression tests; never shipped as a runtime tool');p.add_argument('--source-archive',type=Path,default=VENDOR/'lofreq-2.1.5-source-subset.tar.gz');a=p.parse_args()
    build=VENDOR/'build';build.mkdir(exist_ok=True,parents=True)
    archive=a.source_archive.resolve();hts_archive=ROOT/'vendor-variant/archives/samtools-1.24.tar.bz2'
    if sha(archive) not in (SOURCE_SHA,SUBSET_SHA) or sha(hts_archive)!=HTS_SHA:raise RuntimeError('Source archive hash mismatch')
    src=build/'lofreq-2.1.5'
    if not a.resume or not src.exists():
        if src.exists():shutil.rmtree(src)
        with tarfile.open(archive) as tf:tf.extractall(build,filter='data')
    patch(src)
    cosmo=build/'cosmocc-3.3.10'
    if a.target!='linux' and not cosmo.exists():
        sys.path.insert(0,str(ROOT));from build_variant import extract_cosmocc
        extract_cosmocc(VENDOR/'cosmocc-3.3.10.zip',cosmo)
    (build/'tmp').mkdir(exist_ok=True)
    for target in ['linux','cosmo'] if a.target=='all' else [a.target]:
        dst=build/target;dst.mkdir(exist_ok=True);hts=dst/'samtools-1.24/htslib-1.24'
        if not hts.exists():
            with tarfile.open(hts_archive) as tf:tf.extractall(dst,filter='data')
        cc=str(cosmo/'bin/x86_64-unknown-cosmo-cc') if target=='cosmo' else 'gcc'
        env={**os.environ,'TMPDIR':str(build/'tmp'),'CC':cc}
        if not a.resume or not (hts/'libhts.a').exists():
            for f in hts.rglob('*'):
                if f.is_file() and (f.name in ['configure','config.guess','config.sub','install-sh'] or f.suffix=='.sh'):f.chmod(f.stat().st_mode|0o111)
            options=['--disable-bz2','--disable-lzma','--disable-libcurl','--disable-gcs','--disable-s3','--disable-plugins','--disable-ref-cache','--without-libdeflate','CFLAGS=-O2 -g']
            if target=='cosmo':
                env['AR']=str(cosmo/'bin/x86_64-unknown-cosmo-ar');env['ac_cv_lib_z_inflate']='yes'
                subprocess.run(['ar','rcs',str(dst/'libz.a')],check=True)
                options+=['CPPFLAGS=-I'+str(cosmo/'include/third_party/zlib'),'LDFLAGS=-L'+str(dst)]
            run(['sh','./configure',*options],hts,dst/'hts-configure.log',env)
            run(['make','-j'+str(a.jobs),'libhts.a'],hts,dst/'hts-build.log',env)
        source_files=list((src/'src/lofreq').glob('*.c'))
        source_files=[s for s in source_files if s.name not in ['lofreq_bamstats.c','lofreq_uniq.c','binom.c']]
        # cdflib90 is used only by the unavailable uniq command and is omitted.
        includes=[src/'src/lofreq',src/'src/uthash',hts]
        if target=='cosmo':includes.append(cosmo/'include/third_party/zlib')
        options=['-O2','-g','-D_FILE_OFFSET_BITS=64','-D_LARGEFILE64_SOURCE','-DPACKAGE_VERSION="2.1.5"','-DGIT_VERSION="8fe42b04-workbench-port2-no-uniq"','-ffunction-sections','-fdata-sections']+[f'-I{x}' for x in includes]
        def compile_one(source):
            obj=dst/(source.name+'.o')
            if a.resume and obj.exists() and obj.stat().st_mtime>=source.stat().st_mtime:return obj
            run([cc,*options,'-c',source,'-o',obj],src,dst/(source.name+'.log'),env);return obj
        with concurrent.futures.ThreadPoolExecutor(max_workers=a.jobs) as ex:objects=list(ex.map(compile_one,source_files))
        output=VENDOR/('lofreq-cosmo.exe' if target=='cosmo' else 'lofreq-linux')
        run([cc,'-Wl,--gc-sections','-o',output,*objects,hts/'libhts.a','-lm','-lpthread',*(['-lz'] if target=='linux' else [])],src,dst/'link.log',env)
        print(target,output,sha(output),flush=True)
        if target=='linux' and a.reference_comparator:
            with tarfile.open(archive) as upstream:
                original=upstream.extractfile('lofreq-2.1.5/src/lofreq/lofreq_call.c').read().decode()
            # Test comparator keeps upstream shell filtering. Only /tmp is moved
            # into its private fixture working directory for sandboxed validation.
            original=original.replace('/tmp/lofreq2-call-dyn-bonf.XXXXXX','./lofreq2-call-dyn-bonf.XXXXXX')
            original_path=dst/'original-call.c';original_path.write_text(original)
            obj=dst/'original-call.o'
            run([cc,*options,'-c',original_path,'-o',obj],src,dst/'original-call.log',env)
            baseline=VENDOR/'lofreq-original-filter-linux'
            original_objects=[obj if p.name=='lofreq_call.c.o' else p for p in objects]
            run([cc,'-Wl,--gc-sections','-o',baseline,*original_objects,hts/'libhts.a','-lm','-lpthread','-lz'],src,dst/'original-link.log',env)
            print('original-filter comparator',baseline,sha(baseline),flush=True)
if __name__=='__main__':main()
