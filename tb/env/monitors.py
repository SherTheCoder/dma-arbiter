import cocotb
from cocotb.triggers import RisingEdge
from pyuvm import uvm_analysis_port, uvm_monitor

from env.clk import cycle
from env.items import PortTxn


class PortMonitor(uvm_monitor):
    """Rebuilds each burst from the handshakes on one port."""

    def __init__(self, name, parent, port):
        super().__init__(name, parent)
        self.port = port

    def build_phase(self):
        self.ap = uvm_analysis_port("ap", self)
        self.errors = []

    def pin(self, name):
        return getattr(cocotb.top, f"p{self.port}_{name}")

    async def run_phase(self):
        clk = cocotb.top.clk
        cmd_valid, cmd_ready = self.pin("cmd_valid"), self.pin("cmd_ready")
        wvalid, wready, wdata, wlast = self.pin("wvalid"), self.pin("wready"), self.pin("wdata"), self.pin("wlast")
        rvalid, rready, rdata, rlast, rid = (self.pin("rvalid"), self.pin("rready"), self.pin("rdata"),
                                             self.pin("rlast"), self.pin("rid"))
        t = None
        since = None
        while True:
            await RisingEdge(clk)
            now = cycle()
            if t is None:
                if cmd_valid.value:
                    if since is None:
                        since = now
                    if cmd_ready.value:
                        t = PortTxn(self.port, int(self.pin("cmd_write").value), int(self.pin("cmd_addr").value),
                                    int(self.pin("cmd_len").value), int(self.pin("cmd_inc").value),
                                    int(self.pin("cmd_id").value), now, since)
                        since = None
                elif wvalid.value:
                    self.errors.append(f"p{self.port} wvalid with no command @{now}")
                continue

            if cmd_valid.value:
                self.errors.append(f"p{self.port} new command before the last beat @{now}")
            if t.write:
                if wvalid.value and wready.value:
                    t.data.append(int(wdata.value))
                    t.beats.append(now)
                    if wlast.value:
                        self.ap.write(t)
                        t = None
            elif rvalid.value:
                if not rready.value:
                    self.errors.append(f"p{self.port} rready low during a read @{now}")
                    continue
                t.data.append(int(rdata.value))
                t.rids.append(int(rid.value))
                t.beats.append(now)
                if rlast.value:
                    self.ap.write(t)
                    t = None


class DoneMonitor(uvm_monitor):
    def build_phase(self):
        self.ap = uvm_analysis_port("ap", self)

    async def run_phase(self):
        dut = cocotb.top
        while True:
            await RisingEdge(dut.clk)
            v = int(dut.ch_done.value)
            ch = 0
            while v:
                if v & 1:
                    self.ap.write((ch, cycle()))
                v >>= 1
                ch += 1
