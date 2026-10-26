from cocotb.utils import get_sim_time

PERIOD_NS = 10


def cycle():
    return int(get_sim_time("ns")) // PERIOD_NS
