import os
import random

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge


class Port:
    """Fixed-latency stand-in for the fabric: every target answers 2 cycles after the command."""

    def __init__(self, dut, n, mem):
        self.dut = dut
        self.p = f"p{n}_"
        self.mem = mem

    def sig(self, name):
        return getattr(self.dut, self.p + name)

    async def run(self):
        self.sig("cmd_ready").value = 1
        self.sig("wready").value = 0
        self.sig("rvalid").value = 0
        while True:
            await RisingEdge(self.dut.clk)
            if not (self.sig("cmd_valid").value and self.sig("cmd_ready").value):
                continue
            write = int(self.sig("cmd_write").value)
            addr = int(self.sig("cmd_addr").value)
            n = int(self.sig("cmd_len").value)
            inc = int(self.sig("cmd_inc").value)
            cid = int(self.sig("cmd_id").value)
            self.sig("cmd_ready").value = 0
            await RisingEdge(self.dut.clk)
            await RisingEdge(self.dut.clk)
            for k in range(n):
                a = addr + 4 * k * inc
                if write:
                    self.sig("wready").value = 1
                    await RisingEdge(self.dut.clk)
                    assert self.sig("wvalid").value
                    assert int(self.sig("wlast").value) == (k == n - 1)
                    self.mem.setdefault(a, []).append(int(self.sig("wdata").value))
                    self.sig("wready").value = 0
                else:
                    self.sig("rvalid").value = 1
                    self.sig("rdata").value = self.mem[a][-1] if a in self.mem else 0
                    self.sig("rlast").value = k == n - 1
                    self.sig("rid").value = cid
                    await RisingEdge(self.dut.clk)
                    assert self.sig("rready").value
                    self.sig("rvalid").value = 0
            self.sig("cmd_ready").value = 1


async def smoke(dut, src_port, dst_port, src_inc, dst_inc):
    rng = random.Random(int(os.environ.get("SEED", 1)))
    Clock(dut.clk, 10, unit="ns").start()
    dut.rst_n.value = 0
    dut.cfg_valid.value = 0
    await RisingEdge(dut.clk)
    await RisingEdge(dut.clk)
    dut.rst_n.value = 1

    # writes append so a fixed-address sink keeps every beat
    mem = {}
    src, dst = 0x2000_0000, 0x2000_1000
    periph = 0x4000_0000
    if not src_inc:
        src = periph
    if not dst_inc:
        dst = periph
    words = [rng.getrandbits(32) for _ in range(16)]
    for k, w in enumerate(words):
        if src_inc:
            mem[src + 4 * k] = [w]
    if not src_inc:
        # one fixed address, so the fake peripheral hands out the same word every time
        words = [0x1234_5678] * 16
        mem[src] = [words[0]]

    cocotb.start_soon(Port(dut, 0, mem).run())
    cocotb.start_soon(Port(dut, 1, mem).run())

    dut.cfg_valid.value = 1
    dut.cfg_ch.value = 0
    dut.cfg_src_addr.value = src
    dut.cfg_dst_addr.value = dst
    dut.cfg_beats.value = 16
    dut.cfg_burst.value = 4
    dut.cfg_src_port.value = src_port
    dut.cfg_dst_port.value = dst_port
    dut.cfg_src_inc.value = src_inc
    dut.cfg_dst_inc.value = dst_inc
    await RisingEdge(dut.clk)
    while not dut.cfg_ready.value:
        await RisingEdge(dut.clk)
    dut.cfg_valid.value = 0

    for cycle in range(2000):
        await RisingEdge(dut.clk)
        if dut.ch_done.value[0]:
            break
    else:
        assert False, "no ch_done"
    dut._log.info("done after %d cycles", cycle)

    if dst_inc:
        got = [mem[dst + 4 * k][-1] for k in range(16)]
    else:
        got = mem[dst]
    assert got == words


@cocotb.test()
async def smoke_m2p(dut):
    await smoke(dut, src_port=1, dst_port=0, src_inc=1, dst_inc=0)


@cocotb.test()
async def smoke_p2m(dut):
    await smoke(dut, src_port=0, dst_port=1, src_inc=0, dst_inc=1)
