import os
import random
from collections import deque

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge


@cocotb.test()
async def random_push_pop(dut):
    depth = int(os.environ.get("DEPTH", 4))
    width = len(dut.din)
    rng = random.Random(depth)
    Clock(dut.clk, 10, unit="ns").start()
    dut.rst_n.value = 0
    dut.push.value = 0
    dut.pop.value = 0
    dut.din.value = 0
    await RisingEdge(dut.clk)
    dut.rst_n.value = 1

    q = deque()
    push = pop = False
    d = 0
    hit_full = 0
    # alternate fast and slow push phases so it spends time both full and empty
    for phase in range(40):
        p_push = 0.8 if phase % 2 == 0 else 0.3
        for _ in range(250):
            await RisingEdge(dut.clk)
            # values here are from just before the edge
            assert int(dut.count.value) == len(q)
            assert int(dut.full.value) == (len(q) == depth)
            assert int(dut.empty.value) == (len(q) == 0)
            if q:
                assert int(dut.dout.value) == q[0]
            if pop:
                q.popleft()
            if push:
                q.append(d)
            hit_full += len(q) == depth

            push = len(q) < depth and rng.random() < p_push
            pop = len(q) > 0 and rng.random() < 0.5
            d = rng.getrandbits(width)
            dut.push.value = push
            dut.pop.value = pop
            dut.din.value = d
    assert hit_full > 0
