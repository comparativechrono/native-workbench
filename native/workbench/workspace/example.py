"""An executable starter example; optional packs are never prerequisites."""
from copy import deepcopy
from pathlib import Path


def make_example(app_root, catalog):
    """Use the three-pack starter, preserving the older fixture when applicable."""
    base = Path(app_root).resolve() / 'examples' / 'starter'
    required = ('align/paired-end', 'bam/prepare', 'variants/call', 'variants/statistics')
    missing = [identity for identity in required if identity not in catalog['tools']]
    if missing:
        raise ValueError('The example needs the minimap2, SAMtools and BCFtools starter packs. '
                         'Open Manage tools to install them. Missing operations: '+', '.join(missing))
    if not base.is_dir():
        legacy = ('fastp/paired', 'bwa/paired-end', 'freebayes/call')
        if all(identity in catalog['tools'] for identity in legacy):
            return _legacy_example(app_root, catalog)
        base = Path(app_root).resolve() / 'examples' / 'variant-truth'
    missing_files = [name for name in ('reads1.fastq','reads2.fastq','reference.fa') if not (base/name).is_file()]
    if missing_files:
        raise ValueError('The starter example data are missing. Reinstall the application to restore examples: '+', '.join(missing_files))
    graph = {'schema':1, 'name':'Starter example · minimap2, SAMtools and BCFtools',
             'sources':[
                 {'id':'input-1','label':'Example paired reads','type':'pair',
                  'files':{'reads1':str(base/'reads1.fastq'),'reads2':str(base/'reads2.fastq')}},
                 {'id':'input-2','label':'Example reference','type':'reference',
                  'files':{'reference':str(base/'reference.fa')}}],
             'nodes':[], 'nextNode':6, 'nextSource':3}
    definitions = [
        ('align/paired-end','Align reads with minimap2',{'reads':['input-1'],'reference':['input-2']},{'sample':'starter'}),
        ('bam/prepare','Prepare alignments with SAMtools',{'alignment':['step-1::sam']},{}),
        ('variants/call','Call variants with BCFtools',{'alignment':['step-2::bam'],'reference':['input-2']},{'ploidy':'2'}),
        ('variants/statistics','Summarise variant calls',{'variants':['step-3::variants']},{}),
        ('builtin/report','Alignment and variant reports',{'metrics':['step-2::alignment-stats','step-4::statistics']},
         {'title':'Starter example: alignment and variant statistics'}),
    ]
    for i,(identity,label,inputs,overrides) in enumerate(definitions,1):
        tool=catalog['tools'][identity]
        params=deepcopy(tool['defaults']);params.update(overrides)
        graph['nodes'].append({'id':'step-'+str(i),'tool':identity,'label':label,'inputs':inputs,'params':params,
                               'pin':{'packId':tool['packId'],'packVersion':tool['packVersion'],'manifestSha256':tool['manifestSha256']}})
    return graph


def _legacy_example(app_root, catalog):
    base = Path(app_root).resolve() / "examples" / "variant-truth"
    graph = {"schema": 1, "name": "Example reads · two variant callers", "nodes": [],
             "sources": [
                 {"id": "input-1", "label": "Example paired reads", "type": "pair", "files": {
                     "reads1": str(base / "reads1.fastq"), "reads2": str(base / "reads2.fastq")}},
                 {"id": "input-2", "label": "Example reference", "type": "reference", "files": {
                     "reference": str(base / "reference.fa")}},
             ], "nextNode": 9, "nextSource": 3}
    definitions = [
        ("fastp/paired", "Trim reads with fastp", {"reads": ["input-1"]}, {"adapter1": "AGATCGGAAGAGCACACGTCTGAACTCCAGTCA", "adapter2": "AGATCGGAAGAGCGTCGTGTAGGGAAAGAGTGT"}),
        ("bwa/paired-end", "Align reads with BWA", {"reads": ["step-1::trimmed"], "reference": ["input-2"]},
         {"sample": "truth", "read-group": "truth-lane-1", "library": "truth-library", "platform-unit": "truth-unit"}),
        ("bam/prepare", "Prepare aligned reads", {"alignment": ["step-2::aligned"]}, {}),
        ("variants/call", "BCFtools variant calls", {"alignment": ["step-3::bam"], "reference": ["input-2"]}, {"ploidy": "2"}),
        ("freebayes/call", "FreeBayes variant calls", {"alignment": ["step-3::bam"], "reference": ["input-2"]}, {"ploidy": "2"}),
        ("variants/statistics", "BCFtools call statistics", {"variants": ["step-4::variants"]}, {}),
        ("variants/statistics", "FreeBayes call statistics", {"variants": ["step-5::variants"]}, {}),
        ("builtin/report", "Quality and caller reports", {"metrics": ["step-1::trim-json", "step-3::alignment-stats", "step-6::statistics", "step-7::statistics"]},
         {"title": "Example reads: two callers, separately reported"}),
    ]
    for i, (tool_id, label, inputs, overrides) in enumerate(definitions, 1):
        tool = catalog["tools"][tool_id]
        params = deepcopy(tool["defaults"])
        params.update(overrides)
        graph["nodes"].append({"id": "step-" + str(i), "tool": tool_id, "label": label,
                               "params": params, "inputs": inputs,
                               "pin": {"packVersion": tool["packVersion"], "manifestSha256": tool["manifestSha256"]}})
    return graph
