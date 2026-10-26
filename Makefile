RTL = rtl/dma_pkg.sv rtl/rr_arbiter.sv rtl/sync_fifo.sv

lint:
	verilator --lint-only -Wall $(RTL)

unit:
	$(MAKE) -C tb/unit TOP=flop
	$(MAKE) -C tb/unit TOP=rr_arbiter N=4
	$(MAKE) -C tb/unit TOP=rr_arbiter N=8
	$(MAKE) -C tb/unit TOP=sync_fifo DEPTH=2
	$(MAKE) -C tb/unit TOP=sync_fifo DEPTH=3
	$(MAKE) -C tb/unit TOP=sync_fifo DEPTH=4

.PHONY: lint unit
