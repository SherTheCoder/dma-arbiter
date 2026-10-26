"""Cycle-stepped performance model of dma_arbiter_top and the fabric.

Steps one clock edge at a time through the handoffs written down in
docs/notes.md. It knows the fabric rules from config/fabric_default.yaml and
nothing about the testbench. Back-pressure is assumed off.

Everything is in clock edges. "since" is the edge a state was entered on, and
nothing reacts to a state on the same edge it was entered.
"""
from collections import deque

from models.config import first_beat_delay, target

# handoff delays, edges (docs/notes.md)
REQ_TO_GRANT = 1     # request up -> grant + fifo push
PUSH_TO_POP = 1      # fifo push -> pop into the issue register
IDLE_TO_POP = 1      # port master back in P_IDLE -> next pop
POP_TO_ACCEPT = 1    # pop -> cmd handshake, cmd_ready already high
ACCEPT_TO_START = 1  # cmd handshake -> fabric service start
DONE_DELAY = 1       # last write beat -> ch_done
LOAD_DELAY = 1       # driver puts a descriptor on cfg -> it loads


class Chan:
    def __init__(self, ch):
        self.ch = ch
        self.state = "IDLE"
        self.since = -1
        self.d = None
        self.left = 0
        self.write = False
        self.rise = 0


class Port:
    def __init__(self, p):
        self.p = p
        self.state = "IDLE"
        self.since = -1
        self.fifo = deque()
        self.last = None
        self.job = None


class Job:
    def __init__(self, port, chan, write, n, tgt, accept, rise):
        self.port = port
        self.chan = chan
        self.write = write
        self.len = n
        self.tgt = tgt
        self.accept = accept
        self.rise = rise
        self.start = None
        self.due = None
        self.beats = []


class Target:
    def __init__(self):
        self.free = 0
        self.owner = None
        self.waiting = []


def predict(descs, depth, fabric, n_ch=8, limit=10_000_000):
    """descs: per-channel order, each with ch, src, dst, beats, burst,
    src_port, dst_port, delay. Returns loads, dones, per-burst timings and
    total cycles (last ch_done - first load)."""
    chans = [Chan(c) for c in range(n_ch)]
    ports = [Port(0), Port(1)]
    targets = {}
    queue = {c: deque() for c in range(n_ch)}
    for d in descs:
        queue[d["ch"]].append(d)
    busy = set()
    free_at = {}
    cur = None
    left = len(descs)
    loads, dones, txns = [], [], []

    n = 0
    while left and n < limit:
        n += 1

        # data beats and the end of a burst
        for pt in ports:
            j = pt.job
            if pt.state != "DATA" or j.due != n:
                continue
            j.beats.append(n)
            j.due = n + fabric["beat_interval"][j.tgt]
            if len(j.beats) < j.len:
                continue
            targets[j.tgt].owner = None
            targets[j.tgt].free = n + 1
            pt.state, pt.since, pt.job = "IDLE", n, None
            txns.append((j.chan.ch, pt.p, int(j.write), j.len, j.rise, j.accept, j.beats[0], j.beats[-1]))
            c = j.chan
            if not j.write:
                c.state, c.since, c.write, c.rise = "REQ", n, True, n
            else:
                c.left -= j.len
                if c.left:
                    c.state, c.since, c.write, c.rise = "REQ", n, False, n
                else:
                    c.state, c.since = "DONE", n

        # command handshake, pop, grant + push
        for pt in ports:
            full = len(pt.fifo) >= depth
            if pt.state == "CMD" and n - pt.since >= POP_TO_ACCEPT:
                c, write, n_beats, rise = pt.cmd
                d = c.d
                tgt = target(d["dst"] if write else d["src"])
                j = Job(pt.p, c, write, n_beats, tgt, n, rise)
                pt.job = j
                pt.state, pt.since = "DATA", n
                targets.setdefault(tgt, Target()).waiting.append(j)
            elif (pt.state == "IDLE" and n - pt.since >= IDLE_TO_POP and pt.fifo
                  and n - pt.fifo[0][0] >= PUSH_TO_POP):
                pt.cmd = pt.fifo.popleft()[1]
                pt.state, pt.since = "CMD", n

            want = [c for c in chans if c.state == "REQ" and n - c.since >= REQ_TO_GRANT
                    and (c.d["dst_port"] if c.write else c.d["src_port"]) == pt.p]
            if want and not full:
                order = sorted(want, key=lambda c: (c.ch - (pt.last + 1 if pt.last is not None else 0)) % n_ch)
                c = order[0]
                pt.last = c.ch
                n_beats = min(c.d["burst"], c.left)
                pt.fifo.append((n, (c, c.write, n_beats, c.rise)))
                c.state, c.since = "WAIT", n

        # fabric: start the oldest waiting burst on each free target, port 0 wins a tie
        for name, t in targets.items():
            if t.owner is None:
                ready = [j for j in t.waiting if j.accept < n]
                if ready:
                    j = min(ready, key=lambda j: (j.accept, j.port))
                    t.waiting.remove(j)
                    t.owner = j
                    j.start = max(j.accept + ACCEPT_TO_START, t.free)
                    j.due = j.start + first_beat_delay(fabric, j.port, name)

        # ch_done, then the driver
        if cur is not None and chans[cur["ch"]].state == "IDLE" and n - cur["at"] >= LOAD_DELAY:
            c = chans[cur["ch"]]
            c.d, c.left, c.write = cur, cur["beats"], False
            c.state, c.since, c.rise = "REQ", n, n
            busy.add(c.ch)
            loads.append((c.ch, n))
            cur = None
        for c in chans:
            if c.state == "DONE" and n - c.since >= DONE_DELAY:
                c.state, c.since = "IDLE", n
                dones.append((c.ch, n))
                busy.discard(c.ch)
                free_at[c.ch] = n
                left -= 1
        if cur is None:
            cur = pick(queue, busy, free_at, n)
            if cur is not None:
                cur = dict(cur, at=n)

    first = min(c for _, c in loads) if loads else 0
    last = max(c for _, c in dones) if dones else first
    return {"loads": loads, "dones": dones, "txns": txns, "total": last - first}


def pick(queue, busy, free_at, n):
    """The driver's choice for this edge: lowest channel that is free and due,
    else a back-to-back reload parked on a busy channel."""
    for ch in sorted(queue):
        q = queue[ch]
        if q and ch not in busy and n >= free_at.get(ch, 0) + q[0]["delay"]:
            return q.popleft()
    for ch in sorted(queue):
        q = queue[ch]
        if q and ch in busy and q[0]["delay"] == 0:
            return q.popleft()
    return None
