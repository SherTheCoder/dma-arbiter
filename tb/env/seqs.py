import random

from pyuvm import uvm_sequence

from env.items import DescItem
from models.config import load_fabric

MIN_TXNS = 100


def mem_src(ch, off=0):
    return 0x2000_0000 + ch * 0x10_0000 + 4 * off


def mem_dst(ch, off=0):
    return 0x2800_0000 + ch * 0x10_0000 + 4 * off


def periph(ch, off=0):
    return 0x4000_0000 + ch * 0x1000 + 4 * off


class Scenario:
    def __init__(self, name, seed, descs, bp="none", depth=4, fabric=None):
        self.name = name
        self.seed = seed
        self.descs = descs
        self.bp = bp
        self.depth = depth
        self.fabric = fabric or load_fabric()
        # random words behind every memory address a descriptor reads
        rng = random.Random(seed ^ 0x5EED)
        self.mem = {}
        for d in descs:
            if d.src_inc:
                for k in range(d.beats):
                    self.mem.setdefault(d.src + 4 * k, rng.getrandbits(32))


def desc(ch, kind, beats, burst, ports=None, delay=0):
    """Descriptor with the AN5593 mapping unless ports=(src_port, dst_port) says otherwise."""
    src = periph(ch) if kind == "P2M" else mem_src(ch)
    dst = periph(ch) if kind == "M2P" else mem_dst(ch)
    if ports is None:
        ports = {"M2P": (1, 0), "P2M": (0, 1), "M2M": (1, 1)}[kind]
    return DescItem(ch=ch, kind=kind, src=src, dst=dst, beats=beats, burst=burst,
                    src_port=ports[0], dst_port=ports[1], delay=delay)


def smoke_m2p(seed):
    return Scenario("smoke_m2p", seed, [desc(0, "M2P", 16, 4)])


def smoke_p2m(seed):
    return Scenario("smoke_p2m", seed, [desc(0, "P2M", 16, 4)])


def single_beat(seed):
    return Scenario("single_beat", seed, [desc(2, "M2M", 33, 1, ports=(1, 0))])


def max_burst_tail(seed):
    return Scenario("max_burst_tail", seed, [desc(5, "M2P", 37, 16)])


def all_on_one_port(seed):
    kinds = ["M2P", "P2M", "M2M"]
    return Scenario("all_on_one_port", seed,
                    [desc(c, kinds[c % 3], 64, [4, 8, 16, 2][c % 4], ports=(0, 0)) for c in range(8)])


def fifo_full(seed):
    rng = random.Random(seed)
    descs = [desc(c, rng.choice(["M2P", "P2M", "M2M"]), 48, 4,
                  ports=(rng.randint(0, 1), rng.randint(0, 1))) for c in range(8)]
    return Scenario("fifo_full", seed, descs, bp="heavy", depth=2)


def reload(seed):
    return Scenario("reload", seed, [desc(3, k, 20, 8) for k in ("M2P", "P2M", "M2M", "M2P")])


def sai(seed, inverted, bg=0, beats=2048, fabric=None, name=None):
    """2 RX (P2M) and 1 TX (M2P), burst 4, plus up to 5 balanced background channels, burst 8.

    The seed only moves descriptor start offsets, 0 to 64 cycles.
    """
    rng = random.Random(seed)
    descs = [desc(0, "M2P", beats, 4, ports=(0, 1) if inverted else (1, 0)),
             desc(1, "P2M", beats, 4),
             desc(2, "P2M", beats, 4)]
    for i in range(bg):
        descs.append(desc(3 + i, "P2M" if i % 2 == 0 else "M2P", beats, 8))
    for d in descs:
        d.delay = rng.randint(0, 64)
    name = name or f"sai_{'inv' if inverted else 'bal'}_bg{bg}"
    return Scenario(name, seed, descs, fabric=fabric)


DIRECTED = {
    "smoke_m2p": smoke_m2p,
    "smoke_p2m": smoke_p2m,
    "single_beat": single_beat,
    "max_burst_tail": max_burst_tail,
    "all_on_one_port": all_on_one_port,
    "fifo_full": fifo_full,
    "reload": reload,
    "sai_balanced": lambda seed: sai(seed, inverted=False, name="sai_balanced"),
    "sai_inverted": lambda seed: sai(seed, inverted=True, name="sai_inverted"),
}


def pick(rng, weighted):
    vals, weights = zip(*weighted)
    return rng.choices(vals, weights=weights)[0]


def rand_scenario(seed, depth):
    rng = random.Random(seed)
    n_ch = pick(rng, [(1, 1), (2, 1), (3, 1), (4, 3), (5, 3), (6, 3), (7, 3), (8, 3)])
    chans = sorted(rng.sample(range(8), n_ch))
    bp = pick(rng, [("none", 40), ("light", 40), ("heavy", 20)])
    reloads = rng.random() < 0.3
    poff = {c: rng.randrange(256) for c in chans}

    descs = []
    txns = 0
    while txns < MIN_TXNS:
        ch = rng.choice(chans)
        kind = pick(rng, [("M2P", 40), ("P2M", 40), ("M2M", 20)])
        tail = rng.random() < 0.2
        burst = rng.choice([1, 4, 8, 16]) if rng.random() < 0.8 else rng.randint(2, 15)
        if tail and burst == 1:
            burst = rng.randint(2, 16)
        r = rng.random()
        beats = rng.randint(1, 16) if r < 0.3 else rng.randint(17, 128) if r < 0.8 else rng.randint(129, 256)
        if tail and beats % burst == 0:
            beats -= rng.randint(1, burst - 1)
        elif not tail:
            beats = max(burst, beats - beats % burst)

        src = periph(ch, poff[ch]) if kind == "P2M" else mem_src(ch, rng.randrange(0x1000))
        dst = periph(ch, poff[ch]) if kind == "M2P" else mem_dst(ch, rng.randrange(0x1000))
        first = all(d.ch != ch for d in descs)
        delay = rng.randint(0, 200) if first or not reloads else 0
        descs.append(DescItem(ch=ch, kind=kind, src=src, dst=dst, beats=beats, burst=burst,
                              src_port=rng.randint(0, 1), dst_port=rng.randint(0, 1), delay=delay))
        txns += 2 * -(-beats // burst)
    return Scenario("rand", seed, descs, bp=bp, depth=depth)


class ScenarioSeq(uvm_sequence):
    def __init__(self, name, descs):
        super().__init__(name)
        self.descs = descs

    async def body(self):
        for d in self.descs:
            await self.start_item(d)
            await self.finish_item(d)
