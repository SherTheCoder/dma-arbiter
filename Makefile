RTL = rtl/dma_pkg.sv rtl/rr_arbiter.sv rtl/sync_fifo.sv rtl/dma_channel.sv rtl/port_master.sv rtl/dma_arbiter_top.sv

lint:
	verilator --lint-only -Wall --top-module dma_arbiter_top $(RTL)
	verilator --lint-only -Wall --top-module dma_arbiter_top -GNUM_CH=4 -GCMD_FIFO_DEPTH=2 $(RTL)

unit:
	$(MAKE) -C tb/unit TOP=flop
	$(MAKE) -C tb/unit TOP=rr_arbiter N=4
	$(MAKE) -C tb/unit TOP=rr_arbiter N=8
	$(MAKE) -C tb/unit TOP=sync_fifo DEPTH=2
	$(MAKE) -C tb/unit TOP=sync_fifo DEPTH=3
	$(MAKE) -C tb/unit TOP=sync_fifo DEPTH=4

.PHONY: lint unit
