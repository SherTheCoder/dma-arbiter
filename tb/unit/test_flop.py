import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, ReadOnly


@cocotb.test()
async def flop_follows_d(dut):
    Clock(dut.clk, 10, unit="ns").start()
    dut.rst_n.value = 0
    dut.d.value = 1
    await RisingEdge(dut.clk)
    await ReadOnly()
    assert dut.q.value == 0

    await RisingEdge(dut.clk)
    dut.rst_n.value = 1
    for d in [1, 0, 1, 1, 0]:
        dut.d.value = d
        await RisingEdge(dut.clk)
        await ReadOnly()
        assert dut.q.value == d
        await RisingEdge(dut.clk)
