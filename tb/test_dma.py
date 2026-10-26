import os

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge
from pyuvm import uvm_root

from env import tests

SEED = int(os.environ.get("SEED", 1))


def seeds():
    """SEEDS is "a:b", "3,8,13" or a mix of both."""
    out = []
    for part in (os.environ.get("SEEDS") or str(SEED)).split(","):
        if ":" in part:
            a, b = part.split(":")
            out += range(int(a), int(b))
        else:
            out.append(int(part))
    return out


async def run(dut, test, seed, **attrs):
    Clock(dut.clk, 10, unit="ns").start()
    dut.rst_n.value = 0
    dut.cfg_valid.value = 0
    for p in ("p0_", "p1_"):
        for s in ("cmd_ready", "wready", "rvalid"):
            getattr(dut, p + s).value = 0
    for _ in range(4):
        await RisingEdge(dut.clk)
    dut.rst_n.value = 1
    await RisingEdge(dut.clk)
    test.seed = seed
    for k, v in attrs.items():
        setattr(test, k, v)
    await uvm_root().run_test(test)


async def directed(dut, name):
    await run(dut, tests.DirectedTest, SEED, name=name)


@cocotb.test()
async def smoke_m2p(dut):
    await directed(dut, "smoke_m2p")


@cocotb.test()
async def smoke_p2m(dut):
    await directed(dut, "smoke_p2m")


@cocotb.test()
async def single_beat(dut):
    await directed(dut, "single_beat")


@cocotb.test()
async def max_burst_tail(dut):
    await directed(dut, "max_burst_tail")


@cocotb.test()
async def all_on_one_port(dut):
    await directed(dut, "all_on_one_port")


@cocotb.test()
async def fifo_full(dut):
    await directed(dut, "fifo_full")


@cocotb.test()
async def reload(dut):
    await directed(dut, "reload")


@cocotb.test()
async def sai_balanced(dut):
    await directed(dut, "sai_balanced")


@cocotb.test()
async def sai_inverted(dut):
    await directed(dut, "sai_inverted")


@cocotb.test()
@cocotb.parametrize(seed=seeds())
async def rand(dut, seed):
    await run(dut, tests.RandTest, seed)


@cocotb.test()
@cocotb.parametrize(seed=seeds())
async def sai(dut, seed):
    await run(dut, tests.SaiTest, seed)
