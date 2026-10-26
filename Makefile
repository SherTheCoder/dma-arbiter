RTL = rtl/dma_pkg.sv rtl/rr_arbiter.sv rtl/sync_fifo.sv rtl/dma_channel.sv rtl/port_master.sv rtl/dma_arbiter_top.sv

lint:
	verilator --lint-only -Wall --top-module dma_arbiter_top $(RTL)
	verilator --lint-only -Wall --top-module dma_arbiter_top -GNUM_CH=4 -GCMD_FIFO_DEPTH=2 $(RTL)

# yosys' own frontend can't take package imports, so read through yosys-slang
synth:
	mkdir -p build/synth
	for n in 8 4; do \
	  yosys -m slang -q -l build/synth/n$$n.log -p "read_slang --top dma_arbiter_top -G NUM_CH=$$n $(RTL); \
	    synth -flatten -top dma_arbiter_top; tee -q -o build/synth/stat_n$$n.json stat -json" || exit 1; \
	done

unit:
	$(MAKE) -C tb/unit TOP=flop
	$(MAKE) -C tb/unit TOP=rr_arbiter N=4
	$(MAKE) -C tb/unit TOP=rr_arbiter N=8
	$(MAKE) -C tb/unit TOP=sync_fifo DEPTH=2
	$(MAKE) -C tb/unit TOP=sync_fifo DEPTH=3
	$(MAKE) -C tb/unit TOP=sync_fifo DEPTH=4

TEST ?= smoke_m2p
SEED ?= 1
SEEDS ?= 0:1000
JOBS ?= 4

test:
	python scripts/run_regression.py --one $(TEST) $(SEED)

regress:
	python scripts/run_regression.py --directed --seeds $(SEEDS) --jobs $(JOBS)

cov:
	python scripts/merge_coverage.py build/regress results

perf:
	python experiments/correlate.py

.PHONY: lint synth unit test regress cov perf
