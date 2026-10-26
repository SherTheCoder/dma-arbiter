from pyuvm import uvm_sequence_item


class DescItem(uvm_sequence_item):
    def __init__(self, name="desc", ch=0, kind="M2M", src=0, dst=0, beats=1, burst=1,
                 src_port=0, dst_port=1, delay=0):
        super().__init__(name)
        self.ch = ch
        self.kind = kind
        self.src = src
        self.dst = dst
        self.beats = beats
        self.burst = burst
        self.src_port = src_port
        self.dst_port = dst_port
        # memory sides step, peripheral sides stay put
        self.src_inc = int(kind != "P2M")
        self.dst_inc = int(kind != "M2P")
        self.delay = delay

    def mapping(self):
        if self.kind == "M2M":
            return None
        periph, mem = (self.dst_port, self.src_port) if self.kind == "M2P" else (self.src_port, self.dst_port)
        if periph == mem:
            return "same"
        return "balanced" if periph == 0 else "inverted"

    def to_dict(self):
        return {k: getattr(self, k) for k in
                ("ch", "kind", "src", "dst", "beats", "burst", "src_port", "dst_port",
                 "src_inc", "dst_inc", "delay")}

    def __str__(self):
        return (f"ch{self.ch} {self.kind} {self.src:#010x}->{self.dst:#010x} "
                f"beats={self.beats} burst={self.burst} ports={self.src_port}->{self.dst_port} "
                f"delay={self.delay}")


class PortTxn:
    """One burst as seen on the pins."""

    def __init__(self, port, write, addr, n, inc, ch, accept, valid_since):
        self.port = port
        self.write = write
        self.addr = addr
        self.len = n
        self.inc = inc
        self.id = ch
        self.accept = accept
        self.cmd_wait = accept - valid_since
        self.data = []
        self.rids = []
        self.beats = []

    def key(self):
        return (self.port, self.write, self.addr, self.len, self.inc, self.id)

    def gaps(self):
        return [b - a - 1 for a, b in zip(self.beats, self.beats[1:])]

    def __repr__(self):
        return (f"{'WR' if self.write else 'RD'} p{self.port} ch{self.id} "
                f"addr={self.addr:#010x} len={self.len} inc={self.inc} @{self.accept}")
