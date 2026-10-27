/* The bench sits where the boot ROM would load an FSBL, in AXISRAM2. Its
   DMA buffers get AXISRAM1 to themselves so the CPU's own traffic stays off
   the memory the channels are using. 0x34000000-0x3401ffff is left for
   OpenOCD's work area. */

ENTRY(Reset_Handler)

MEMORY
{
  CODE (rx) : ORIGIN = 0x34180400, LENGTH = 63K
  RAM  (rw) : ORIGIN = 0x34190000, LENGTH = 448K
  DMA  (rw) : ORIGIN = 0x34020000, LENGTH = 640K
}

_estack = ORIGIN(RAM) + LENGTH(RAM);
_sstack = _estack - 0x1000;

SECTIONS
{
  .isr_vector :
  {
    . = ALIGN(4);
    KEEP(*(.isr_vector))
    . = ALIGN(4);
  } >CODE

  .text :
  {
    *(.text*)
    *(.glue_7) *(.glue_7t) *(.eh_frame)
    KEEP(*(.init))
    KEEP(*(.fini))
    . = ALIGN(4);
    _etext = .;
  } >CODE

  /* -mcmse wants somewhere to put secure entry veneers, even if there are none */
  .gnu.sgstubs :
  {
    . = ALIGN(32);
    *(.gnu.sgstubs*)
    . = ALIGN(32);
  } >CODE

  .rodata :
  {
    . = ALIGN(4);
    *(.rodata*)
    . = ALIGN(4);
  } >CODE

  .ARM.exidx :
  {
    __exidx_start = .;
    *(.ARM.exidx*)
    __exidx_end = .;
  } >CODE

  .init_array :
  {
    PROVIDE_HIDDEN(__preinit_array_start = .);
    KEEP(*(.preinit_array*))
    PROVIDE_HIDDEN(__preinit_array_end = .);
    PROVIDE_HIDDEN(__init_array_start = .);
    KEEP(*(SORT(.init_array.*)))
    KEEP(*(.init_array*))
    PROVIDE_HIDDEN(__init_array_end = .);
    PROVIDE_HIDDEN(__fini_array_start = .);
    KEEP(*(SORT(.fini_array.*)))
    KEEP(*(.fini_array*))
    PROVIDE_HIDDEN(__fini_array_end = .);
  } >CODE

  _sidata = LOADADDR(.data);
  .data :
  {
    . = ALIGN(4);
    _sdata = .;
    *(.data*)
    . = ALIGN(4);
    _edata = .;
  } >RAM AT>CODE

  .bss (NOLOAD) :
  {
    . = ALIGN(4);
    _sbss = .;
    __bss_start__ = _sbss;
    *(.bss*)
    *(COMMON)
    . = ALIGN(4);
    _ebss = .;
    __bss_end__ = _ebss;
    PROVIDE(end = .);
  } >RAM

  .dma (NOLOAD) :
  {
    *(.dma*)
  } >DMA
}
