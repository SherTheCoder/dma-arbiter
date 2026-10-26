import os

import cocotb
from cocotb.triggers import RisingEdge
from cocotb_coverage.coverage import CoverCross, CoverPoint, coverage_db
from pyuvm import ConfigDB, uvm_subscriber

LENS = ["1", "2-4", "5-8", "9-16"]
STALLS = ["0", "1", "2-4", "5+"]


def len_bin(n):
    return "1" if n == 1 else "2-4" if n <= 4 else "5-8" if n <= 8 else "9-16"


def stall_bin(n):
    return "0" if n == 0 else "1" if n == 1 else "2-4" if n <= 4 else "5+"


@CoverPoint("txn.ch", xf=lambda t: t.id, bins=list(range(8)))
@CoverPoint("txn.port", xf=lambda t: t.port, bins=[0, 1])
@CoverPoint("txn.dir", xf=lambda t: "wr" if t.write else "rd", bins=["rd", "wr"])
@CoverPoint("txn.len", xf=lambda t: len_bin(t.len), bins=LENS)
@CoverCross("txn.cross", items=["txn.ch", "txn.port", "txn.dir", "txn.len"])
def sample_txn(t):
    pass


@CoverPoint("stall.cmd_ready", xf=lambda n: stall_bin(n), bins=STALLS)
def sample_cmd_stall(n):
    pass


@CoverPoint("stall.wready", xf=lambda n: stall_bin(n), bins=STALLS)
def sample_w_stall(n):
    pass


@CoverPoint("stall.rgap", xf=lambda n: stall_bin(n), bins=STALLS)
def sample_r_gap(n):
    pass


@CoverPoint("arb.port", xf=lambda p, n: p, bins=[0, 1])
@CoverPoint("arb.requesters", xf=lambda p, n: n, bins=list(range(1, 9)))
@CoverCross("arb.requesters_x_port", items=["arb.port", "arb.requesters"])
def sample_grant(p, n):
    pass


@CoverPoint("arb.wrap", xf=lambda p: p, bins=[0, 1])
def sample_wrap(p):
    pass


@CoverPoint("fifo.occupancy_at_push", xf=lambda occ, full: occ, bins=[1, 2, 3, 4])
@CoverPoint("fifo.full_at_push", xf=lambda occ, full: full, bins=[False, True])
def sample_push(occ, full):
    pass


@CoverPoint("desc.mapping", xf=lambda m: m, bins=["balanced", "inverted", "same"])
def sample_mapping(m):
    pass


@CoverPoint("desc.tail", xf=lambda tail: tail, bins=[False, True])
def sample_tail(tail):
    pass


@CoverPoint("cfg.wait", xf=lambda n: "0" if n == 0 else "1-10" if n <= 10 else "11+", bins=["0", "1-10", "11+"])
def sample_cfg_wait(n):
    pass


class Coverage(uvm_subscriber):
    def build_phase(self):
        self.desc_imp = uvm_subscriber.uvm_AnalysisImp("desc_imp", self, self.on_load)
        self.depth = ConfigDB().get(self, "", "scn").depth

    def write(self, t):
        sample_txn(t)
        sample_cmd_stall(t.cmd_wait)
        for g in t.gaps():
            if t.write:
                sample_w_stall(g)
            else:
                sample_r_gap(g)

    def on_load(self, x):
        d, now = x
        # cycles cfg_valid sat there with cfg_ready low
        sample_cfg_wait(now - d.presented - 1)
        if d.mapping():
            sample_mapping(d.mapping())
        sample_tail(d.beats % d.burst != 0)

    async def run_phase(self):
        # grants only exist inside the DUT, so this peeks. The responders never do.
        dut = cocotb.top
        arbs = [dut.u_arb0, dut.u_arb1]
        fifos = [dut.u_pm0.u_fifo, dut.u_pm1.u_fifo]
        last = [None, None]
        while True:
            await RisingEdge(dut.clk)
            for p in (0, 1):
                g = int(arbs[p].gnt.value)
                if not g:
                    continue
                w = g.bit_length() - 1
                sample_grant(p, bin(int(arbs[p].req.value)).count("1"))
                occ = int(fifos[p].count.value) + 1
                sample_push(occ, occ == self.depth)
                if last[p] is not None and w <= last[p]:
                    sample_wrap(p)
                last[p] = w

    def report_phase(self):
        out = os.environ.get("COV")
        if out:
            coverage_db.export_to_yaml(out)
