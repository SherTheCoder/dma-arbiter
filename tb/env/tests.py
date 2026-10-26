import os

import cocotb
from cocotb.triggers import ClockCycles, First
from pyuvm import ConfigDB, uvm_test

from env import seqs
from env.env import DmaEnv
from models.config import load_fabric


class DmaTest(uvm_test):
    seed = 1

    def scenario(self):
        raise NotImplementedError

    def build_phase(self):
        self.scn = self.scenario()
        depth = int(os.environ.get("DEPTH", 4))
        if self.scn.depth != depth:
            raise RuntimeError(f"{self.scn.name} needs the CMD_FIFO_DEPTH={self.scn.depth} build, this is {depth}")
        ConfigDB().set(None, "*", "scn", self.scn)
        self.env = DmaEnv("env", self)

    async def run_phase(self):
        self.raise_objection()
        scn = self.scn
        self.logger.info(f"{scn.name} seed {scn.seed}: {len(scn.descs)} descriptors, back-pressure {scn.bp}")
        for d in scn.descs:
            self.logger.debug(str(d))
        cocotb.start_soon(seqs.ScenarioSeq("seq", scn.descs).start(self.env.seqr))

        clk = cocotb.top.clk
        limit = 50 * sum(d.beats for d in scn.descs) + 10_000
        timeout = ClockCycles(clk, limit)
        if await First(self.env.sb.all_done.wait(), timeout) is timeout:
            busy = int(cocotb.top.ch_busy.value)
            chans = [c for c in range(8) if busy >> c & 1]
            self.env.sb.error(6, f"watchdog: not done after {limit} cycles, busy channels {chans}")
        await ClockCycles(clk, 4)
        self.drop_objection()


class DirectedTest(DmaTest):
    name = "smoke_m2p"

    def scenario(self):
        return seqs.DIRECTED[self.name](self.seed)


class RandTest(DmaTest):
    def scenario(self):
        return seqs.rand_scenario(self.seed, int(os.environ.get("DEPTH", 4)))


class SaiTest(DmaTest):
    """The mapping experiment. MAP, BG and PEN come from the environment."""

    def scenario(self):
        pen = os.environ.get("PEN")
        fabric = load_fabric(cross_penalty=int(pen) if pen else None)
        return seqs.sai(self.seed, inverted=os.environ.get("MAP") == "inv",
                        bg=int(os.environ.get("BG", 0)), fabric=fabric)
