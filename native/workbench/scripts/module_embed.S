.section .text.bwmodule,"ax"
.balign 16
.global bw_module_start
.global bw_module_end
bw_module_start:
.incbin "build/fastq.module"
bw_module_end:
#ifndef _WIN32
.section .note.GNU-stack,"",@progbits
#endif
