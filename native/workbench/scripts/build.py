#!/usr/bin/env python3
"""Build and structurally validate a prepared module using the local GNU toolchain."""
import hashlib,json,os,pathlib,re,subprocess,sys
ROOT=pathlib.Path(__file__).resolve().parents[1]
os.chdir(ROOT)
B=ROOT/'build';B.mkdir(exist_ok=True)
def run(*args):
    subprocess.run(args,check=True)
flags=['-std=c11','-O2','-Wall','-Wextra','-Werror','-Wno-misleading-indentation','-ffreestanding','-fPIC','-fno-builtin','-fno-stack-protector','-fno-asynchronous-unwind-tables','-fno-unwind-tables','-mno-red-zone','-fcf-protection=none','-fno-tree-loop-distribute-patterns','-fstack-usage','-Wframe-larger-than=3072','-Iinclude']
run('gcc',*flags,'-c','src/fastq_module.c','-o','build/fastq.o')
stack_usage=(B/'fastq.su').read_text()
for line in stack_usage.splitlines():
    columns=line.split('\t')
    if columns[-1]!='static' or int(columns[-2])>3072:raise SystemExit(f'Unsupported stack use: {line}')
rel=subprocess.check_output(['readelf','-rW','build/fastq.o'],text=True)
rel_types=set(re.findall(r'R_X86_64_\w+',rel))
if not rel_types <= {'R_X86_64_PC32','R_X86_64_PLT32'}:raise SystemExit(f'Unsupported module relocations: {rel_types}')
run('ld','-nostdlib','--no-undefined','-T','scripts/module.ld','build/fastq.o','-o','build/fastq.elf')
if subprocess.check_output(['nm','-u','build/fastq.elf']).strip():raise SystemExit('Unresolved symbols')
finalrel=subprocess.check_output(['readelf','-rW','build/fastq.elf'],text=True)
if 'There are no relocations' not in finalrel:raise SystemExit('Unresolved relocations')
header=subprocess.check_output(['readelf','-h','build/fastq.elf'],text=True)
if not re.search(r'Entry point address:\s+0x0\s',header):raise SystemExit('Entry must be offset zero')
run('objcopy','-O','binary','-j','.module','build/fastq.elf','build/fastq.module')
data=(B/'fastq.module').read_bytes();digest=hashlib.sha256(data).hexdigest()
run('gcc','-std=c11','-O2','-Wall','-Wextra','-Werror','-Wno-misleading-indentation','-Iinclude',f'-DBW_MODULE_SHA256="{digest}"','src/host_posix.c','scripts/module_embed.S','-pthread','-o','build/bwfastq-linux')
# Same source, compiler and host. Direct object linking is the overhead control.
run('gcc','-std=c11','-O2','-Iinclude','-DBW_DIRECT',f'-DBW_MODULE_SHA256="{digest}"','src/host_posix.c','build/fastq.o','-pthread','-o','build/bwfastq-linux-direct')
objdump=subprocess.check_output(['objdump','-d','build/fastq.elf'],text=True)
if re.search(r'\t(?:syscall|sysenter|int\s+\$0x80)\b',objdump):raise SystemExit('Raw OS entry instruction found')
if (B/'bwfastq-linux').read_bytes().count(data)!=1:raise SystemExit('Module bytes not embedded exactly once')
report={'abi_version':1,'architecture':'x86_64','entry_offset':0,'module_bytes':len(data),'module_sha256':digest,'elf_relocations':0,'undefined_symbols':0,'object_relocation_types':sorted(rel_types),'raw_syscalls_in_disassembly':False,'compiler':subprocess.check_output(['gcc','-dumpfullversion'],text=True).strip(),'linker':subprocess.check_output(['ld','--version'],text=True).splitlines()[0],'flags':flags,'linux_executable_bytes':(B/'bwfastq-linux').stat().st_size,'stack_usage':stack_usage.splitlines(),'windows_execution_tested':False}
(B/'module.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps(report,indent=2))
