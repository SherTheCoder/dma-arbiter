import random

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, ReadOnly


def rr_pick(req, last, n):
    for k in range(1, n + 1):
        i = (last + k) % n
        if req >> i & 1:
            return i
    return None


async def reset(dut):
    dut.rst_n.value = 0
    dut.req.value = 0
    dut.accept.value = 0
    await RisingEdge(dut.clk)
    dut.rst_n.value = 1


async def step(dut, req, accept):
    """Drive one cycle, return the grant index (or None) seen before the edge."""
    dut.req.value = req
    dut.accept.value = accept
    await ReadOnly()
    g = int(dut.gnt.value)
    await RisingEdge(dut.clk)
    if g == 0:
        return None
    assert g & (g - 1) == 0, f"gnt {g:b} not one-hot"
    return g.bit_length() - 1


@cocotb.test()
async def exhaustive(dut):
    """Every pointer position x every request pattern x accept, checked against rr_pick,
    then a probe with all channels requesting to check where the pointer went."""
    n = len(dut.req)
    Clock(dut.clk, 10, unit="ns").start()
    for last in range(n):
        for req in range(1 << n):
            for accept in (0, 1):
                await reset(dut)
                # park the pointer on `last`
                assert await step(dut, 1 << last, 1) == last
                want = rr_pick(req, last, n) if accept else None
                got = await step(dut, req, accept)
                assert got == want, f"last={last} req={req:0{n}b} acc={accept}: got {got} want {want}"
                after = last if got is None else got
                probe = await step(dut, (1 << n) - 1, 1)
                assert probe == (after + 1) % n


@cocotb.test()
async def bounded_wait(dut):
    """Requesters hold req until granted. No one should see n or more other grants first."""
    n = len(dut.req)
    rng = random.Random(1)
    Clock(dut.clk, 10, unit="ns").start()
    await reset(dut)
    req = 0
    waited = [0] * n
    worst = 0
    last = n - 1
    for _ in range(20000):
        for i in range(n):
            if not req >> i & 1 and rng.random() < 0.3:
                req |= 1 << i
        accept = rng.random() < 0.7
        g = await step(dut, req, accept)
        assert g == (rr_pick(req, last, n) if accept else None)
        if g is None:
            continue
        last = g
        req &= ~(1 << g)
        waited[g] = 0
        for i in range(n):
            if req >> i & 1:
                waited[i] += 1
                worst = max(worst, waited[i])
        assert max(waited) < n, f"channel waited {max(waited)} grants"
    dut._log.info("worst wait %d grants (n=%d)", worst, n)
    assert worst == n - 1
