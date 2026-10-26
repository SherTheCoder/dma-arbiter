# make TOP=rr_arbiter N=4, TOP=sync_fifo DEPTH=3, or TOP=flop
TOP ?= flop
SIM ?= verilator
TOPLEVEL_LANG = verilog
RTL = $(abspath ../../rtl)

ifeq ($(TOP),flop)
VERILOG_SOURCES = $(abspath flop.sv)
else
VERILOG_SOURCES = $(RTL)/dma_pkg.sv $(RTL)/$(TOP).sv
endif

ifeq ($(TOP),rr_arbiter)
N ?= 8
TAG = _n$(N)
EXTRA_ARGS += -GN=$(N)
endif
ifeq ($(TOP),sync_fifo)
DEPTH ?= 4
export DEPTH
TAG = _d$(DEPTH)
EXTRA_ARGS += -GDEPTH=$(DEPTH)
endif

COCOTB_TOPLEVEL = $(TOP)
COCOTB_TEST_MODULES = test_$(TOP)
SIM_BUILD = sim_build_$(TOP)$(TAG)
COCOTB_RESULTS_FILE = results_$(TOP)$(TAG).xml

include $(shell cocotb-config --makefiles)/Makefile.sim
