import json
import os
from collections import Counter

from cocotb.triggers import Event
from pyuvm import ConfigDB, uvm_scoreboard, uvm_subscriber

from models.config import target
from models.ref_model import predict


class Scoreboard(uvm_scoreboard):
    def build_phase(self):
        self.txn_imp = uvm_subscriber.uvm_AnalysisImp("txn_imp", self, self.on_txn)
        self.done_imp = uvm_subscriber.uvm_AnalysisImp("done_imp", self, self.on_done)
        self.load_imp = uvm_subscriber.uvm_AnalysisImp("load_imp", self, self.on_load)
        self.scn = ConfigDB().get(self, "", "scn")
        self.fabric = ConfigDB().get(self, "", "fabric")
        self.mons = []

        descs = self.scn.descs
        self.exp, self.exp_mem, self.exp_sinks = predict(descs, self.scn.mem, self.scn.seed)
        self.pos = Counter()
        # index into exp[ch] where each of the channel's descriptors ends
        self.ends = {}
        for d in descs:
            e = self.ends.setdefault(d.ch, [])
            e.append((e[-1] if e else 0) + 2 * -(-d.beats // d.burst))
        self.n_desc = Counter(d.ch for d in descs)
        self.dones = Counter()
        self.left = len(descs)
        self.all_done = Event()
        self.failed = Event()
        if not descs:
            self.all_done.set()

        self.last_read = {}
        self.last_wbeat = {}
        self.req_rise = {}
        self.loads = []
        self.done_log = []
        self.log = []
        self.errors = []

    def error(self, check, msg):
        self.errors.append(f"check {check}: {msg}")
        self.failed.set()
        if len(self.errors) <= 5:
            self.logger.error(f"check {check}: {msg}")

    def on_load(self, x):
        d, now = x
        self.loads.append((d.ch, now))
        self.req_rise[d.ch] = now

    def on_txn(self, t):
        ch = t.id
        if not 0 <= ch < 8:
            self.error(1, f"bad id {ch} on {t}")
            return
        last_addr = t.addr + 4 * (t.len - 1) * t.inc
        if target(t.addr) is None or target(last_addr) != target(t.addr):
            self.error(5, f"unmapped access {t}")
        if any(r != ch for r in t.rids):
            self.error(5, f"rid {t.rids} on a read issued as id {ch}")

        exp = self.exp.get(ch, [])
        i = self.pos[ch]
        if i >= len(exp):
            self.error(1, f"unexpected extra burst {t}")
            return
        e = exp[i]
        self.pos[ch] += 1
        if t.key() != e.key():
            self.error(1, f"ch{ch} burst {i}: got {t}, want {e}")
        if len(t.data) != t.len:
            self.error(1, f"ch{ch} burst {i}: {len(t.data)} beats for len {t.len}")
        if t.write and t.data != self.last_read.get(ch):
            self.error(2, f"ch{ch} burst {i}: write data isn't what the channel just read")
        elif t.data != e.data:
            self.error(2, f"ch{ch} burst {i}: data mismatch on {t}")

        self.log.append((ch, t.port, t.write, t.len, self.req_rise.get(ch, t.accept), t.accept,
                         t.beats[0] if t.beats else t.accept, t.beats[-1] if t.beats else t.accept))
        if t.beats:
            self.req_rise[ch] = t.beats[-1]
        if t.write:
            self.last_wbeat[ch] = t.beats[-1] if t.beats else t.accept
        else:
            self.last_read[ch] = t.data

    def on_done(self, x):
        ch, now = x
        self.done_log.append((ch, now))
        k = self.dones[ch]
        self.dones[ch] += 1
        if k >= self.n_desc[ch]:
            self.error(4, f"extra ch_done on ch{ch} @{now}")
            return
        if self.pos[ch] != self.ends[ch][k] or self.last_wbeat.get(ch, now) >= now:
            self.error(4, f"ch{ch} ch_done @{now} before its last write beat")
        self.left -= 1
        if self.left == 0:
            self.all_done.set()

    def check_phase(self):
        for ch, exp in self.exp.items():
            if self.pos[ch] < len(exp):
                self.error(1, f"ch{ch} only did {self.pos[ch]} of {len(exp)} bursts")
        for ch, n in self.n_desc.items():
            if self.dones[ch] != n:
                self.error(4, f"ch{ch} raised ch_done {self.dones[ch]} times for {n} descriptors")
        if self.fabric.mem != self.exp_mem:
            bad = sorted(a for a in set(self.fabric.mem) | set(self.exp_mem)
                         if self.fabric.mem.get(a) != self.exp_mem.get(a))
            self.error(3, f"{len(bad)} memory words differ, first at {bad[0]:#010x}")
        if self.fabric.sinks != self.exp_sinks:
            bad = [a for a in set(self.fabric.sinks) | set(self.exp_sinks)
                   if self.fabric.sinks.get(a) != self.exp_sinks.get(a)]
            self.error(3, f"peripheral sinks differ at {', '.join(f'{a:#010x}' for a in bad)}")
        for e in self.fabric.errors:
            self.error(5, e)
        for m in self.mons:
            for e in m.errors:
                self.error(5, e)

    def report_phase(self):
        scn = self.scn
        n = sum(self.pos.values())
        first = min((c for _, c in self.loads), default=0)
        last = max((c for _, c in self.done_log), default=first)
        self.logger.info(f"{scn.name} seed {scn.seed}: {n} bursts, {last - first} cycles, "
                         f"{len(self.errors)} errors")
        out = os.environ.get("RESULTS")
        if out:
            with open(out, "a") as f:
                f.write(json.dumps({"test": scn.name, "seed": scn.seed, "depth": scn.depth, "bp": scn.bp,
                                    "ok": not self.errors, "txns": n, "cycles": last - first,
                                    "errors": self.errors[:5]}) + "\n")
        dump = os.environ.get("DUMP")
        if dump:
            with open(dump, "a") as f:
                f.write(json.dumps({"name": scn.name, "seed": scn.seed, "depth": scn.depth, "bp": scn.bp,
                                    "params": scn.params, "fabric": scn.fabric, "ok": not self.errors,
                                    "descs": [d.to_dict() for d in scn.descs],
                                    "loads": self.loads, "dones": self.done_log,
                                    "txns": self.log}) + "\n")
        if self.errors:
            raise AssertionError(f"{len(self.errors)} scoreboard errors, first: {self.errors[0]}")
