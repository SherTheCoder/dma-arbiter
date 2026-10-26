from collections import deque

import cocotb
from cocotb.triggers import Event, RisingEdge
from pyuvm import uvm_analysis_port, uvm_driver

from env.clk import cycle


class CfgDriver(uvm_driver):
    """Loads descriptors through cfg_*. Each channel works through its own queue:
    the first descriptor waits `delay` cycles from the start, later ones wait
    `delay` cycles after the channel's previous ch_done."""

    def build_phase(self):
        self.ap = uvm_analysis_port("ap", self)
        self.queue = {}
        self.busy = set()
        self.free_at = {}
        self.more = Event()

    async def run_phase(self):
        self.t0 = cycle()
        cocotb.start_soon(self.drive())
        while True:
            item = await self.seq_item_port.get_next_item()
            self.queue.setdefault(item.ch, deque()).append(item)
            self.more.set()
            self.seq_item_port.item_done()

    def pick(self, now):
        for ch in sorted(self.queue):
            q = self.queue[ch]
            if q and ch not in self.busy and now >= self.free_at.get(ch, self.t0) + q[0].delay:
                return q.popleft()
        return None

    async def drive(self):
        dut = cocotb.top
        dut.cfg_valid.value = 0
        cur = None
        while True:
            await RisingEdge(dut.clk)
            now = cycle()
            if cur is not None and dut.cfg_ready.value:
                self.ap.write((cur, now))
                self.busy.add(cur.ch)
                cur = None
            done = int(dut.ch_done.value)
            for ch in list(self.busy):
                if done >> ch & 1:
                    self.busy.discard(ch)
                    self.free_at[ch] = now
            if cur is None:
                cur = self.pick(now)
                if cur is None:
                    dut.cfg_valid.value = 0
                    if not any(self.queue.values()) and not self.busy:
                        self.more.clear()
                        await self.more.wait()
                    continue
                dut.cfg_valid.value = 1
                dut.cfg_ch.value = cur.ch
                dut.cfg_src_addr.value = cur.src
                dut.cfg_dst_addr.value = cur.dst
                dut.cfg_beats.value = cur.beats
                dut.cfg_burst.value = cur.burst
                dut.cfg_src_port.value = cur.src_port
                dut.cfg_dst_port.value = cur.dst_port
                dut.cfg_src_inc.value = cur.src_inc
                dut.cfg_dst_inc.value = cur.dst_inc
