# make TEST=smoke_m2p SEED=3
# make TEST=rand SEEDS=0:20 DEPTH=4
SIM ?= verilator
TOPLEVEL_LANG = verilog
ROOT = $(abspath ..)

RTL_DIR ?= $(ROOT)/rtl
VERILOG_SOURCES = $(addprefix $(RTL_DIR)/, dma_pkg.sv rr_arbiter.sv sync_fifo.sv dma_channel.sv port_master.sv dma_arbiter_top.sv) \
                  $(ROOT)/sva/dma_sva.sv $(ROOT)/sva/dma_sva_bind.sv

TEST ?= smoke
DEPTH ?= 4
SEED ?= 1
export SEED SEEDS DEPTH MAP BG PEN RESULTS DUMP COV
export PYTHONPATH := $(ROOT):$(ROOT)/tb:$(PYTHONPATH)

COCOTB_TOPLEVEL = dma_arbiter_top
COCOTB_TEST_MODULES = test_dma
COCOTB_TEST_FILTER = '$(TEST)'
SIM_BUILD ?= sim_build_d$(DEPTH)
EXTRA_ARGS += -GCMD_FIFO_DEPTH=$(DEPTH) --assert --coverage-user
ifdef VCOV
COCOTB_PLUSARGS += +verilator+coverage+file+$(VCOV)
endif
ifeq ($(WAVES),1)
SIM_BUILD := $(SIM_BUILD)_waves
EXTRA_ARGS += --trace-fst --trace-structs
SIM_ARGS += --trace --trace-file $(or $(WAVE_FILE),dump.fst)
endif

include $(shell cocotb-config --makefiles)/Makefile.sim
