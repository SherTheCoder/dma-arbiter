from models.config import PERIPH, periph_stream, target


class Txn:
    def __init__(self, port, write, addr, n, inc, ch, data):
        self.port = port
        self.write = write
        self.addr = addr
        self.len = n
        self.inc = inc
        self.id = ch
        self.data = data

    def key(self):
        return (self.port, self.write, self.addr, self.len, self.inc, self.id)

    def __repr__(self):
        return (f"{'WR' if self.write else 'RD'} p{self.port} ch{self.id} "
                f"addr={self.addr:#010x} len={self.len} inc={self.inc}")


def predict(descs, mem0, seed):
    """Expected per-channel transaction lists, final MEM and peripheral sinks.

    Channels own disjoint memory windows and their own peripheral address, so
    running each channel's descriptors in order is exact whatever the
    interleaving on the ports.
    """
    mem = dict(mem0)
    sinks = {}
    streams = {}
    txns = {}

    def read(a):
        if target(a) == PERIPH:
            if a not in streams:
                streams[a] = periph_stream(seed, a)
            return next(streams[a])
        return mem.get(a, 0)

    def write(a, w):
        if target(a) == PERIPH:
            sinks.setdefault(a, []).append(w)
        else:
            mem[a] = w

    for d in descs:
        out = txns.setdefault(d.ch, [])
        src, dst, left = d.src, d.dst, d.beats
        while left:
            n = min(d.burst, left)
            data = [read(src + 4 * k * d.src_inc) for k in range(n)]
            out.append(Txn(d.src_port, 0, src, n, d.src_inc, d.ch, data))
            for k, w in enumerate(data):
                write(dst + 4 * k * d.dst_inc, w)
            out.append(Txn(d.dst_port, 1, dst, n, d.dst_inc, d.ch, data))
            src += 4 * n * d.src_inc
            dst += 4 * n * d.dst_inc
            left -= n
    return txns, mem, sinks
