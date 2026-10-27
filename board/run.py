#!/usr/bin/env python3
"""The mapping experiment again, on a real STM32N6570-DK.

Loads board/build/bench.elf into AXISRAM over the on-board ST-LINK with
OpenOCD, feeds it batches of jobs (see bench.c) and saves every DWT timestamp
to results/board_raw.json.gz. analyse.py turns that into numbers.

The board has to be in dev boot mode. OPENOCD and OPENOCD_SCRIPTS point at
ST's OpenOCD, the one that comes with STM32CubeIDE and has target/stm32n6x.cfg.
"""
import gzip
import json
import os
import random
import re
import socket
import struct
import subprocess
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ELF = os.path.join(ROOT, "board", "build", "bench.elf")
RAW = os.path.join(ROOT, "results", "board_raw.json.gz")
LOG = os.path.join(ROOT, "build", "board", "openocd.log")
NM = os.environ.get("NM", "arm-none-eabi-nm")

CPU_PER_BUS = 3          # 600 MHz CPU, 200 MHz AHB/APB
NCH, MAX_JOBS, MAX_PROBES = 8, 512, 32
MAGIC = 0x444D4142

# bench.c endpoints: the apb[] registers, then memory
SAI1_A, SAI1_B, SAI2_A, SAI2_B, TIM15, TIM16, TIM17, TIM9, MEM, SCRATCH, AHB = range(11)
BG_EP = [SAI2_B, TIM15, TIM16, TIM17, TIM9]
MEMS = {"axi": MEM, "ahb": AHB}

CHAN = struct.Struct("<BBBBHH")
TAIL = struct.Struct("<BBHI")
RESULT = struct.Struct(f"<{NCH}I{NCH}I3I{MAX_PROBES}H")
CTL = ["magic", "go", "done", "njobs", "err", "selftest", "cpu_hz", "sys_hz", "hclk_hz", "pclk2_hz",
       "idcode"]

SEEDS = range(10)
# beats per burst for the SAI channels and the background ones: what the RTL
# experiment used, and what the BSP actually programs
BURSTS = {"rtl": (4, 8), "bsp": (1, 1)}


def ports(src, dst):
    return src | dst << 1


def job(kind, chans, probe=0xFF, probes=0, gap=0, probe_wait=0, **meta):
    return {"chans": chans, "probe": probe, "probes": probes, "gap": gap, "probe_wait": probe_wait,
            "meta": dict(kind=kind, **meta)}


def sai_chans(seed, inverted, bg, bursts, words, mem=MEM):
    """seqs.sai() on the board: same channels, and seed k gives the same start
    offsets (0-64 bus cycles) as it does in the RTL runs."""
    rng = random.Random(seed)
    sai, other = bursts
    chans = {0: [mem, SAI1_A, sai, ports(0, 1) if inverted else ports(1, 0), words],
             1: [SAI1_B, mem, sai, ports(0, 1), words],
             2: [SAI2_A, mem, sai, ports(0, 1), words]}
    for i in range(bg):
        if i % 2 == 0:
            chans[3 + i] = [BG_EP[i], mem, other, ports(0, 1), words]
        else:
            chans[3 + i] = [mem, BG_EP[i], other, ports(1, 0), words]
    for c in sorted(chans):
        chans[c].append(rng.randint(0, 64) * CPU_PER_BUS)
    return chans


def mapping_jobs(reps=3):
    out = []
    for rep in range(reps):
        for mem, e in MEMS.items():
            for burst, b in BURSTS.items():
                for bg in (0, 2, 5):
                    for seed in SEEDS:
                        for m in ("bal", "inv"):
                            out.append(job("map", sai_chans(seed, m == "inv", bg, b, 2048, e), gap=200,
                                           map=m, bg=bg, burst=burst, mem=mem, seed=seed, rep=rep))
    # the CPU polls GPDMA1 to see the channels finish; does how often matter?
    for gap in (0, 2000):
        for bg in (0, 5):
            for seed in SEEDS:
                for m in ("bal", "inv"):
                    out.append(job("gap", sai_chans(seed, m == "inv", bg, BURSTS["rtl"], 2048), gap=gap,
                                   map=m, bg=bg, burst="rtl", mem="axi", seed=seed))
    return out


def probe_jobs():
    """One SAI channel does single 4-word blocks while everything else streams."""
    out = []
    for burst, b in BURSTS.items():
        for side, p in (("tx", 0), ("rx", 1)):
            for bg in (0, 5):
                for seed in SEEDS:
                    for m in ("bal", "inv"):
                        chans = sai_chans(seed, m == "inv", bg, b, 8192)
                        chans[p][4] = 4
                        out.append(job("probe", chans, probe=p, probes=MAX_PROBES, probe_wait=3000,
                                       map=m, bg=bg, burst=burst, mem="axi", side=side, seed=seed))
            # the same block with nothing else running
            for m in ("bal", "inv"):
                chans = {p: sai_chans(0, m == "inv", 0, b, 4)[p]}
                out.append(job("probe", chans, probe=p, probes=MAX_PROBES, map=m, bg=None,
                               burst=burst, mem="axi", side=side, seed=0))
    return out


PATHS = {"m2p": (MEM, SAI1_A), "p2m": (SAI1_B, MEM), "m2m": (MEM, SCRATCH), "p2p": (SAI1_B, TIM15),
         "m2p_ahb": (AHB, SAI1_A), "p2m_ahb": (SAI1_B, AHB)}


def path_jobs(reps=5):
    """One channel on its own, every port pair, a range of block sizes."""
    out = []
    for rep in range(reps):
        for d, (src, dst) in PATHS.items():
            for burst in (1, 4):
                for words in (1, 4, 16, 64, 256, 1024):
                    for pr in range(4):
                        out.append(job("path", {0: [src, dst, burst, pr, words, 0]}, dir=d, burst=burst,
                                       words=words, src=pr & 1, dst=pr >> 1, rep=rep))
    return out


def pack(j):
    b = b"".join(CHAN.pack(*j["chans"].get(c, [0] * 6)) for c in range(NCH))
    return b + TAIL.pack(j["probe"], j["probes"], j["gap"], j["probe_wait"])


class Board:
    def __init__(self):
        os.makedirs(os.path.dirname(LOG), exist_ok=True)
        cmd = [os.environ.get("OPENOCD", "openocd")]
        if os.environ.get("OPENOCD_SCRIPTS"):
            cmd += ["-s", os.environ["OPENOCD_SCRIPTS"]]
        cmd += ["-f", "interface/stlink-dap.cfg", "-f", "target/stm32n6x.cfg",
                "-c", "gdb_port disabled", "-c", "telnet_port disabled", "-c", "tcl_port 6666"]
        self.log = open(LOG, "w")
        self.proc = subprocess.Popen(cmd, stdout=self.log, stderr=subprocess.STDOUT)
        deadline = time.time() + 15
        while True:
            try:
                self.sock = socket.create_connection(("127.0.0.1", 6666), timeout=120)
                break
            except OSError:
                if time.time() > deadline or self.proc.poll() is not None:
                    sys.exit(f"openocd didn't come up, see {LOG}")
                time.sleep(0.2)
        self.sym = {}
        for line in subprocess.run([NM, ELF], capture_output=True, text=True, check=True).stdout.splitlines():
            addr, _, name = line.split()
            self.sym[name] = int(addr, 16)
        with open(ELF, "rb") as f:
            self.entry = struct.unpack_from("<I", f.read(0x1C), 0x18)[0]

    def cmd(self, c):
        self.sock.sendall(c.encode() + b"\x1a")
        data = b""
        while not data.endswith(b"\x1a"):
            chunk = self.sock.recv(1 << 16)
            if not chunk:
                sys.exit(f"openocd went away during '{c}', see {LOG}")
            data += chunk
        return data[:-1].decode()

    def reg(self, name):
        return int(re.search(r":\s*(0x[0-9a-f]+)", self.cmd(f"reg {name}")).group(1), 16)

    def words(self, addr, n):
        return [int(x, 16) for x in self.cmd(f"read_memory {addr:#x} 32 {n}").split()]

    def ctl(self):
        return dict(zip(CTL, self.words(self.sym["ctl"], len(CTL))))

    def wait(self, what, until, timeout=30):
        deadline = time.time() + timeout
        while not until():
            if time.time() > deadline:
                sys.exit(f"timed out waiting for {what}")
            time.sleep(0.1)

    def boot(self):
        self.cmd("reset run")
        time.sleep(0.8)
        self.cmd("halt")
        pc = self.reg("pc")
        if pc >> 24 != 0x18:
            sys.exit(f"after reset the core isn't sitting in the boot ROM (pc {pc:#010x}), "
                     "is the board in dev boot mode?")
        out = self.cmd(f"load_image {ELF}")
        if "downloaded" not in out:
            sys.exit(f"load_image failed: {out}")
        # we're taking over from the ROM's idle loop, not from a reset
        for r, v in (("primask", 1), ("control", 0), ("msplim_s", 0), ("xpsr", 0x01000000),
                     ("pc", self.entry & ~1)):
            self.cmd(f"reg {r} {v:#x}")
        self.cmd("resume")
        self.wait("the bench to come up", lambda: self.ctl()["magic"] == MAGIC)
        c = self.ctl()
        if c["err"] or c["selftest"]:
            sys.exit(f"bench init failed: err {c['err']}, self-test {c['selftest']:#x}")
        return c

    def batch(self, jobs, go):
        with tempfile.NamedTemporaryFile(suffix=".bin", delete=False) as f:
            f.write(b"".join(pack(j) for j in jobs))
        self.cmd(f"load_image {f.name} {self.sym['jobs']:#x} bin")
        self.cmd(f"mww {self.sym['ctl'] + 4 * CTL.index('njobs'):#x} {len(jobs)}")
        self.cmd(f"mww {self.sym['ctl'] + 4 * CTL.index('go'):#x} {go}")
        self.wait("a batch", lambda: self.ctl()["done"] == go, timeout=120)
        self.cmd(f"dump_image {f.name} {self.sym['res']:#x} {RESULT.size * len(jobs)}")
        with open(f.name, "rb") as g:
            data = g.read()
        os.unlink(f.name)
        out = []
        for k in range(len(jobs)):
            v = RESULT.unpack_from(data, k * RESULT.size)
            out.append({"start": list(v[:NCH]), "done": list(v[NCH:2 * NCH]), "flags": v[16],
                        "polls": v[17], "probe_end": v[18], "lat": list(v[19:19 + jobs[k]["probes"]])})
        return out

    def close(self):
        try:
            self.cmd("shutdown")
        except (OSError, SystemExit):
            pass
        self.proc.wait(10)


def main():
    if not os.path.exists(ELF):
        sys.exit("build the bench first: make -C board")
    jobs = path_jobs() + mapping_jobs() + probe_jobs()
    board = Board()
    try:
        info = board.boot()
        print(f"bench up: cpu {info['cpu_hz'] / 1e6:.0f} MHz, axi {info['sys_hz'] / 1e6:.0f} MHz, "
              f"ahb {info['hclk_hz'] / 1e6:.0f} MHz, apb2 {info['pclk2_hz'] / 1e6:.0f} MHz, self-test ok")
        res = []
        for k in range(0, len(jobs), MAX_JOBS):
            t = time.time()
            res += board.batch(jobs[k:k + MAX_JOBS], k // MAX_JOBS + 1)
            print(f"batch {k // MAX_JOBS + 1}: {len(jobs[k:k + MAX_JOBS])} jobs, {time.time() - t:.1f} s")
    finally:
        board.close()
    bad = [j["meta"] for j, r in zip(jobs, res) if r["flags"]]
    if bad:
        sys.exit(f"{len(bad)} jobs ended with error flags, first: {bad[0]}")
    out = {"board": {"idcode": info["idcode"], "cpu_hz": info["cpu_hz"], "axi_hz": info["sys_hz"],
                     "ahb_hz": info["hclk_hz"], "apb2_hz": info["pclk2_hz"]},
           "jobs": [dict(j["meta"], chans={c: v for c, v in j["chans"].items()}, probe=j["probe"], gap=j["gap"],
                         **r) for j, r in zip(jobs, res)]}
    with gzip.open(RAW, "wt") as f:
        json.dump(out, f, separators=(",", ":"))
    print(f"{len(jobs)} jobs -> {os.path.relpath(RAW, ROOT)}")


if __name__ == "__main__":
    main()
