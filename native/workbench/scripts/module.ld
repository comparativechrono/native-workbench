ENTRY(bw_entry)
SECTIONS {
 . = 0;
 .module : ALIGN(16) { KEEP(*(.text.entry)) *(.text .text.*) *(.rodata .rodata.*) }
 .data : { *(.data .data.*) }
 .bss : { *(.bss .bss.*) *(COMMON) }
 /DISCARD/ : { *(.comment) *(.note*) *(.eh_frame*) }
 ASSERT(SIZEOF(.data) == 0, "mutable data forbidden")
 ASSERT(SIZEOF(.bss) == 0, "zero-fill globals forbidden")
}
