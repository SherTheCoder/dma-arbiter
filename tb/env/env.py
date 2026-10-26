from pyuvm import ConfigDB, uvm_env, uvm_sequencer

from env.coverage import Coverage
from env.driver import CfgDriver
from env.fabric import Fabric, PortResponder
from env.monitors import DoneMonitor, PortMonitor
from env.scoreboard import Scoreboard


class DmaEnv(uvm_env):
    def build_phase(self):
        scn = ConfigDB().get(self, "", "scn")
        ConfigDB().set(self, "*", "fabric", Fabric(scn.fabric, scn.seed, scn.mem))
        self.seqr = uvm_sequencer("seqr", self)
        self.driver = CfgDriver("driver", self)
        self.resp = [PortResponder(f"resp{p}", self, p) for p in (0, 1)]
        self.mon = [PortMonitor(f"mon{p}", self, p) for p in (0, 1)]
        self.done_mon = DoneMonitor("done_mon", self)
        self.sb = Scoreboard("sb", self)
        self.cov = Coverage("cov", self)

    def connect_phase(self):
        self.driver.seq_item_port.connect(self.seqr.seq_item_export)
        self.driver.ap.connect(self.sb.load_imp)
        self.driver.ap.connect(self.cov.desc_imp)
        for m in self.mon:
            m.ap.connect(self.sb.txn_imp)
            m.ap.connect(self.cov.analysis_export)
        self.done_mon.ap.connect(self.sb.done_imp)
        self.sb.mons = self.mon
