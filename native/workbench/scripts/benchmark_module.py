#!/usr/bin/env python3
"""Interleaved startup-inclusive prepared/direct Linux comparison, not a Windows benchmark."""
import hashlib,json,pathlib,statistics,subprocess,time,platform,os
R=pathlib.Path(__file__).resolve().parents[1];data=R/'build'/'benchmark.fastq'
record=b'@synthetic\n'+b'ACGTN'*30+b'\n+\n'+b'I'*150+b'\n'
with data.open('wb') as f:
    for i in range(200):f.write(record*1000)
expected={'records':200000,'bases':30000000,'gc_bases':12000000,'n_bases':6000000,'min_length':150,'max_length':150,'phred33_sum':1200000000}
series={'prepared':[],'direct':[]};binaries={'prepared':R/'build'/'bwfastq-linux','direct':R/'build'/'bwfastq-linux-direct'}
for warm in [True,False,False,False,False,False]:
    for k in (['prepared','direct'] if warm or len(series['prepared'])%2==0 else ['direct','prepared']):
        t=time.perf_counter();p=subprocess.run([str(binaries[k]),'stats','--input',str(data),'--output','-'],capture_output=True,check=True);elapsed=time.perf_counter()-t
        if json.loads(p.stdout)!=expected:raise RuntimeError('Independent expected statistics mismatch')
        if not warm:series[k].append(elapsed)
report={'environment':platform.platform(),'platform_tested':'Linux x86-64 only','logical_cpus':os.cpu_count(),'input_bytes':data.stat().st_size,'input_sha256':hashlib.sha256(data.read_bytes()).hexdigest(),'reads':200000,'read_length':150,'threads':1,'repetitions':5,'method':'one warmup each, interleaved timed runs, startup-inclusive, host callbacks identical, same compiler flags for computation','seconds':series,'median_seconds':{k:statistics.median(v) for k,v in series.items()},'expected_stats':expected,'all_results_match':True,'warning':'This measures embedding/dispatch cost for a deliberately prepared module. It does not measure arbitrary Linux binary compatibility or Windows performance.'}
report['median_ratio_prepared_over_direct']=report['median_seconds']['prepared']/report['median_seconds']['direct']
(R/'results'/'module-benchmark.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report,indent=2))
