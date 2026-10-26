import random

import cocotb
from cocotb.triggers import RisingEdge
from pyuvm import ConfigDB, uvm_component

from env.clk import cycle
from models.config import MEM, PERIPH, first_beat_delay, periph_stream, target

PROFILES = {"none": (0.0, 1), "light": (0.1, 1), "heavy": (0.4, 8)}


class Target:
    """A single-ported target. Serves one burst at a time across both ports,
    first come first served, port 0 wins a tie."""

    def __init__(self, name):
        self.name = name
        self.free = 0
        self.owner = None
        self.waiting = []

    def poll(self, now):
        if self.owner is not None:
            return
        ready = [j for j in self.waiting if j.accept < now]
        if ready:
            j = min(ready, key=lambda j: (j.accept, j.port))
            self.waiting.remove(j)
            j.start = max(j.accept + 1, self.free)
            self.owner = j

    def release(self, now):
        self.owner = None
        self.free = now + 1


class Fabric:
    """Storage and target state shared by the two responders."""

    def __init__(self, cfg, seed, mem):
        self.cfg = cfg
        self.seed = seed
        self.mem = dict(mem)
        self.sinks = {}
        self.streams = {}
        self.targets = {MEM: Target(MEM), PERIPH: Target(PERIPH)}
        self.errors = []

    def read(self, a):
        t = target(a)
        if t == PERIPH:
            if a not in self.streams:
                self.streams[a] = periph_stream(self.seed, a)
            return next(self.streams[a])
        if t == MEM:
            return self.mem.get(a, 0)
        return 0

    def write(self, a, w):
        t = target(a)
        if t == PERIPH:
            self.sinks.setdefault(a, []).append(w)
        elif t == MEM:
            self.mem[a] = w


class Job:
    def __init__(self, port, write, addr, n, inc, ch, accept):
        self.port = port
        self.write = write
        self.addr = addr
        self.len = n
        self.inc = inc
        self.id = ch
        self.accept = accept
        self.start = None
        self.due = None
        self.done = 0

    def beat_addr(self):
        return self.addr + 4 * self.done * self.inc


class Stall:
    def __init__(self, rng, p, longest):
        self.rng = rng
        self.p = p
        self.longest = longest
        self.left = 0

    def __call__(self):
        if self.left:
            self.left -= 1
            return True
        if self.p and self.rng.random() < self.p:
            self.left = self.rng.randint(1, self.longest) - 1
            return True
        return False


class PortResponder(uvm_component):
    """Fabric side of one port. Only looks at the port pins."""

    def __init__(self, name, parent, port):
        super().__init__(name, parent)
        self.port = port

    def build_phase(self):
        scn = ConfigDB().get(self, "", "scn")
        self.fabric = ConfigDB().get(self, "", "fabric")
        p, longest = PROFILES[scn.bp]
        # back-pressure only moves timing, so it gets its own rng
        rng = random.Random(scn.seed * 2 + self.port)
        self.cmd_stall = Stall(rng, p, longest)
        self.w_stall = Stall(rng, p, longest)
        self.r_stall = Stall(rng, p, longest)

    def pin(self, name):
        return getattr(cocotb.top, f"p{self.port}_{name}")

    def accept(self, now):
        a = int(self.pin("cmd_addr").value)
        job = Job(self.port, int(self.pin("cmd_write").value), a, int(self.pin("cmd_len").value),
                  int(self.pin("cmd_inc").value), int(self.pin("cmd_id").value), now)
        t = target(a)
        last = a + 4 * (job.len - 1) * job.inc
        if t is None or target(last) != t:
            self.fabric.errors.append(f"p{self.port} burst to unmapped address {a:#010x} @{now}")
            # serve it on a private target with MEM timing so the DUT doesn't hang
            job.tgt = Target(MEM)
            job.lat = first_beat_delay(self.fabric.cfg, self.port, MEM)
            job.gap = self.fabric.cfg["beat_interval"][MEM]
        else:
            job.tgt = self.fabric.targets[t]
            job.lat = first_beat_delay(self.fabric.cfg, self.port, t)
            job.gap = self.fabric.cfg["beat_interval"][t]
        job.tgt.waiting.append(job)
        return job

    async def run_phase(self):
        clk = cocotb.top.clk
        cmd_valid, cmd_ready = self.pin("cmd_valid"), self.pin("cmd_ready")
        wvalid, wready, wdata, wlast = self.pin("wvalid"), self.pin("wready"), self.pin("wdata"), self.pin("wlast")
        rvalid, rready, rdata, rlast, rid = (self.pin("rvalid"), self.pin("rready"), self.pin("rdata"),
                                             self.pin("rlast"), self.pin("rid"))
        cmd_ready.value = 0
        wready.value = 0
        rvalid.value = 0
        rlast.value = 0
        rid.value = 0
        rdata.value = 0
        job = None
        ready = w_on = r_on = r_drv = False
        while True:
            await RisingEdge(clk)
            now = cycle()
            if job is None:
                if ready and cmd_valid.value:
                    job = self.accept(now)
            elif job.write:
                if w_on and wvalid.value:
                    self.fabric.write(job.beat_addr(), int(wdata.value))
                    if bool(wlast.value) != (job.done == job.len - 1):
                        self.fabric.errors.append(f"p{self.port} wlast wrong on beat {job.done} @{now}")
                    job.done += 1
                    job.due = now + job.gap
            elif r_on and rready.value:
                job.done += 1
                job.due = now + job.gap
                r_on = False
            if job is not None and job.done == job.len:
                job.tgt.release(now)
                job = None

            # outputs for the next edge
            new_ready = new_w = False
            if job is None:
                new_ready = not self.cmd_stall()
            else:
                job.tgt.poll(now)
                if job.start is not None and job.due is None:
                    job.due = job.start + job.lat
                if job.due is not None and now + 1 >= job.due:
                    if job.write:
                        new_w = not self.w_stall()
                    elif not r_on and not self.r_stall():
                        r_on = True
                        rdata.value = self.fabric.read(job.beat_addr())
                        rlast.value = int(job.done == job.len - 1)
                        rid.value = job.id
            if r_on != r_drv:
                rvalid.value = r_on
                r_drv = r_on
            if new_ready != ready:
                cmd_ready.value = new_ready
                ready = new_ready
            if new_w != w_on:
                wready.value = new_w
                w_on = new_w
