"""Fault-inject only executables to verify a successful downstream cannot hide producer failure."""
import importlib.util,json,pathlib,sys,tempfile
ROOT=pathlib.Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('workflow',ROOT/'scripts/run_workflow.py');mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
with tempfile.TemporaryDirectory(dir=ROOT/'build') as d:
    d=pathlib.Path(d);producer=d/'producer';consumer=d/'consumer'
    producer.write_text('#!/usr/bin/env python3\nimport sys\nsys.stdout.buffer.write(b"partial data")\nsys.exit(7)\n')
    consumer.write_text('#!/usr/bin/env python3\nimport sys\nsys.stdout.buffer.write(sys.stdin.buffer.read())\n')
    producer.chmod(0o755);consumer.chmod(0o755)
    mod.commands=lambda _:([str(producer)],[str(consumer)])
    old=sys.argv;sys.argv=['workflow','--input',str(ROOT/'examples/reads.fastq'),'--reference',str(ROOT/'examples/reference.fa'),'--output-dir',str(d/'output')]
    try:code=mod.main()
    finally:sys.argv=old
    record=json.loads((d/'output/run.json').read_text())
    assert code==1 and record['exit_codes']==[7,0] and record['status']=='failed'
    assert not (d/'output/alignment.sam').exists() and not (d/'output/alignment.sam.partial').exists()
    f=ROOT/'results/workflow.json';r=json.loads(f.read_text());r['failure_case']={'producer_failure_not_hidden_by_successful_consumer':True,'both_exit_statuses_recorded':[7,0],'no_partial_or_final_output':True};f.write_text(json.dumps(r,indent=2)+'\n')
    print('Producer failure correctly preserved; no completed output published.')
