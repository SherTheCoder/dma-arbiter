# make TOP=rr_arbiter, TOP=sync_fifo or TOP=flop
TOP ?= flop
SIM ?= verilator
TOPLEVEL_LANG = verilog
RTL = $(abspath ../../rtl)

ifeq ($(TOP),flop)
VERILOG_SOURCES = $(abspath flop.sv)
else
VERILOG_SOURCES = $(RTL)/dma_pkg.sv $(RTL)/$(TOP).sv
endif

COCOTB_TOPLEVEL = $(TOP)
COCOTB_TEST_MODULES = test_$(TOP)
SIM_BUILD = sim_build_$(TOP)
COCOTB_RESULTS_FILE = results_$(TOP).xml
EXTRA_ARGS += $(PARAMS)

include $(shell cocotb-config --makefiles)/Makefile.sim
