# make TOP=rr_arbiter N=4, TOP=sync_fifo DEPTH=3, or TOP=flop
TOP ?= flop
SIM ?= verilator
TOPLEVEL_LANG = verilog
ROOT = $(abspath ../..)

ifeq ($(TOP),flop)
VERILOG_SOURCES = $(abspath flop.sv)
else
# everything, so the bind file finds the modules it binds to
VERILOG_SOURCES = $(addprefix $(ROOT)/rtl/, dma_pkg.sv rr_arbiter.sv sync_fifo.sv dma_channel.sv port_master.sv dma_arbiter_top.sv) \
                  $(ROOT)/sva/dma_sva.sv $(ROOT)/sva/dma_sva_bind.sv
EXTRA_ARGS += --assert
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
