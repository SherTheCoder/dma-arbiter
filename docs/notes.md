# notes

## design

8 channels, 2 ports. Each port has its own rr arbiter and a command fifo inside its
port_master. A channel only ever has one burst in flight: read a burst into its 16-word
buffer through `src_port`, then write it out through `dst_port`.

The issue register in port_master is just the cmd_* output flops, so cmd payload is
stable by construction (A6 still checks it).

`rid` isn't used by the RTL. Read data goes to the channel in the stored `cmd_id`, the
scoreboard checks `rid` against it.

Yosys 0.70's own `read_verilog -sv` can't parse package imports (`import dma_pkg::*`), not
in the module header and not in the body either. Rather than spell out `dma_pkg::` on
every enum I use the yosys-slang frontend that ships in the same OSS CAD Suite build
(`yosys -m slang`, `read_slang`).

## covers

`c_all_req` (all 8 channels requesting one port) can't fire. A grant needs room in the fifo,
and while the fifo is full its DEPTH entries plus the issue register are DEPTH+1 channels
that aren't requesting. So the most requesters a port ever sees is about 8 - DEPTH, 4 with
the default fifo and 6 with depth 2. Same reason the 7 and 8 bins of the requesters
coverpoint stay empty. I left the cover in anyway since it's the obvious thing to ask for, and
added `c_four_req` which does fire.

## handoff delays

All in clock edges, from what the channel and port master do, checked against the
smoke_m2p dump (16 beats, burst 4, MEM on p1, PERIPH on p0).

| handoff | edges |
| --- | --- |
| load -> request up | 0, the channel is in RD_REQ right after the load edge |
| request -> grant + fifo push | 1 if the fifo has room (grant is combinational, push lands on the next edge) |
| grant -> fifo push | 0, same edge |
| fifo push -> pop into the issue reg | 1 |
| pop -> cmd accepted | 1 with cmd_ready already high (cmd_valid is up the cycle after the pop) |
| so push -> cmd_valid | cmd_valid goes up 1 edge after the push, earliest accept is push + 2 |
| cmd accept -> fabric service start | 1 (fabric rule) |
| service start -> first beat | base_latency + path_penalty |
| last beat -> channel's next request | 0, req is up right after the last beat's edge |
| last write beat -> ch_done | 1 |
| ch_done -> next load on that channel | 1 at the earliest (driver presents on the done edge) |

Per burst with no contention that's 3 edges from request to accept, plus 1 + latency to the
first beat, plus the beats.

## timing sketch

smoke_m2p, edges counted from the load. Read of 4 from MEM over p1 (latency 2, a beat per
cycle), then a write of 4 to PERIPH over p0 (latency 2, a beat every 2 cycles).

```
edge        0  1  2  3  4  5  6  7  8  9 10 11 12 13 14 15 16 17 18 19 20 21 22
channel     RQ RW RW RW RW RW RW RW RW WQ WW WW WW WW WW WW WW WW WW WW WW RQ RW
p1 push        x
p1 pop            x
p1 cmd               A
p1 service              s
p1 rbeat                      r  r  r  r
p0 push                                   x
p0 pop                                       x
p0 cmd                                          A
p0 service                                         s
p0 wbeat                                                 w     w     w     w
                                                                           next read
RQ/RW = RD_REQ/RD_WAIT, WQ/WW = WR_REQ/WR_WAIT, state after that edge
A = cmd accepted, s = service starts, r/w = data beats
```

21 edges per burst, so 16 beats take 84 and ch_done shows at 85, which is what the
scoreboard prints for smoke_m2p.

## random stimulus

How I read a couple of the constraint lines:

- Every scenario queues descriptors per channel until it has 100 port transactions, so
  channels get reloaded in all of them. The 30% "reload after ch_done" scenarios give
  every follow-on descriptor a start delay of 0, so it goes in the cycle after ch_done.
  The rest wait a fresh 0-200 cycles after the previous ch_done.
- A delay-0 reload gets parked on the cfg bus while its channel is still busy, so the
  driver really does sit on cfg_ready (cfg.wait coverpoint). Before that change
  cfg_valid never saw cfg_ready low.
- "20% of descriptors aren't a multiple of the burst": a tail needs burst > 1, so when
  the tail coin comes up with burst 1 I redraw the burst from 2-16.
- Depth 2 is every 5th seed (seed % 5 == 4), 200 of the 1000.

## regression log

2026-10-27  first full run, 1000/1000 seeds and the 9 directed tests pass, 181,108 port
transactions from the random seeds. Main cross 128/128, thinnest bin (ch7, p1, wr, 9-16)
with 327 hits. Requesters at a grant never went above 4.

## bugs hit along the way

(none yet)
