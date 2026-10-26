import copy
import os

import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

MEM = "MEM"
PERIPH = "PERIPH"


def target(addr):
    if 0x2000_0000 <= addr <= 0x2FFF_FFFF:
        return MEM
    if 0x4000_0000 <= addr <= 0x4FFF_FFFF:
        return PERIPH
    return None


def load_fabric(path=None, cross_penalty=None):
    with open(path or os.path.join(ROOT, "config", "fabric_default.yaml")) as f:
        cfg = yaml.safe_load(f)
    if cross_penalty is not None:
        cfg = copy.deepcopy(cfg)
        cfg["path_penalty"]["P0"]["MEM"] = cross_penalty
        cfg["path_penalty"]["P1"]["PERIPH"] = cross_penalty
    return cfg


def first_beat_delay(cfg, port, tgt):
    return cfg["base_latency"][tgt] + cfg["path_penalty"][f"P{port}"][tgt]


def periph_stream(seed, addr):
    """xorshift32, one stream per peripheral address."""
    x = ((seed * 0x9E3779B1) ^ addr) & 0xFFFFFFFF or 1
    while True:
        x ^= (x << 13) & 0xFFFFFFFF
        x ^= x >> 17
        x ^= (x << 5) & 0xFFFFFFFF
        yield x
