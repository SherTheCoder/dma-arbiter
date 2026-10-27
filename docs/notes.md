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

## perf model

models/perf_model.py steps edge by edge through the same handoffs as the table above, with
the fabric rules from the yaml. It assumes no back-pressure.

2026-10-27  calibration on the directed tests (all but fifo_full, which is heavy
back-pressure on purpose): with the delays straight from the table it matched every one
to the cycle, totals and per-burst latency, so nothing needed tuning. Frozen at tag
`perf-model-v1` before looking at any held-out scenario.

2026-10-27  held-out run, seeds 10000-10199 with back-pressure off plus E1/E2 balanced and
inverted: 204 scenarios, total-cycle error 0 on every one, burst latency MAE 0. That looked
too good so I checked it isn't comparing something with itself: the model only gets the
descriptors, fifo depth and fabric yaml out of each dump. Bumping any one pipeline handoff
by a cycle (req->grant, push->pop, pop->accept, accept->start) puts the mean error at 6-8%
and the max at 16.7%, ch_done +1 gives 0.1% mean. So it's exact because nothing is
random once back-pressure is off and the model walks the same pipeline, not because
the check is blind. With back-pressure on it would drift, it doesn't model stalls at all.

## mapping experiment

Metrics as set before running anything: throughput = beats written / (last ch_done - first
load), burst latency = last write beat - the cycle that burst's read request went up
(the load edge for a descriptor's first burst, else the channel's previous last write
beat). 10 seeds per point, which only move start offsets 0-64, and they're paired: seed k
has the same offsets balanced and inverted.

2026-10-27  E1/E2 at the default fabric (cross-path penalty 3):

- E1, 2 RX + 1 TX: inverting TX loses 23.3% throughput (0.363 -> 0.279 beats/cycle), TX
  worst burst latency x1.34, worst RX x1.43.
- E2, plus 5 background channels: 11.6% (0.397 -> 0.352), TX x1.10, RX x1.04.

I expected it to get worse once the other channels got busy. It halves. The peripheral
bridge is the bottleneck: busy 82% of the window in balanced E1 and 86% in E2 (counting
first-beat latency as busy). Inverted, TX bursts hold it 3 cycles longer each, and the
bridge also sits idle more (70% busy in inverted E1) because the two ports now wait on
each other. In E2 TX is only 13% of the bridge's work, so the same per-burst cost is a
smaller slice of the total.

E3 sweep, loss in %, rows are background channels, columns cross-path penalty:

```
        0     1     2     3     4     6     8
bg0  10.8  15.4  19.5  23.3  26.7  32.6  37.7
bg2   7.6  10.8  13.6  16.4  19.0  23.8  28.0
bg5   5.3   7.5   9.6  11.6  13.5  17.0  20.3
```

Inverted never beat balanced, at any point or seed.

Sanity check at penalty 0 and no background: still 10.8%. With no penalty the only
change is which port talks to which target. Balanced, port 0 only ever talks to PERIPH and
port 1 only to MEM, so a burst never waits for a target (0.00 cycles on average).
Inverted, both ports touch both targets, a burst waits 2.5 cycles on average for the
target the other port has, and its port can't do anything else meanwhile since it's
one transaction per port. So close to half of the 23.3% at the default penalty is just
from the ports sharing targets, not from the slower path.

## on the board

board/ is a bare-metal bench for the STM32N6570-DK (STM32N657, idcode 0x10006486). In dev
boot mode the boot ROM sits in an idle loop waiting for a debugger, so run.py resets the
board, checks the core really is in the ROM, loads the bench into AXISRAM2 at the FSBL
address and starts it with interrupts masked. The external flash is never touched. Clocks
are the ones in ST's DK templates: CPU 600 MHz, AXI 400, AHB/APB 200, no overdrive.
I-cache on, D-cache off so the host and the CPU see the same memory. The DMA buffers get
AXISRAM1 to themselves, code and job tables are in AXISRAM2.

A job is up to 8 GPDMA1 channels, 0-7, secure and privileged like the BSP's, all on
software request so they run flat out like the RTL fabric. Roles and seeds are the ones in
seqs.sai(): TX is memory -> SAI1_A DR, RX reads SAI1_B and SAI2_A, the background channels
hit SAI2_B and CCR1 of TIM15/16/17/9, all on APB2. The SAI blocks stay disabled, so this
is the bus only, no audio ever runs. Balanced is the peripheral side on port 0 and memory
on port 1, inverted flips TX only.

Timing is the DWT cycle counter. The bench enables the channels at their seed offsets
(x3, CPU cycles) and stamps each enable, then polls GPDMA1 SMISR (TCIE set, NVIC lines off)
and stamps the first poll that shows each channel done. Throughput and per-channel times
use the same definitions as the RTL. Everything in the results is bus cycles, CPU / 3.

Before anything is timed a self-test copies memory to memory on every port pair (AXISRAM
and AHB SRAM), uses a timer register as sink and as source on every port pair, and checks
the SAI TX fifo really fills. run.py stops if any of it fails.

2026-10-27  path costs, one channel alone, bus cycles per word from a fit over 16-1024
word blocks (below that the poll's own round trip, ~69 cycles, hides it):

```
                     same port   split ports
AXISRAM -> APB2        19.0        15.0
APB2 -> AXISRAM        19.0        16.5
AXISRAM -> AXISRAM     31.2        31.2
APB2 -> APB2            7.0         4.5
AHBSRAM -> APB2         5.0         4.0
APB2 -> AHBSRAM         4.0         3.5
```

Port 0 and port 1 come out within 0.005 cycles a word of each other in every row. So
there's no direct or cross path to see, what costs is having both sides of a channel on
the same port. Memory is the slow side, and memory to memory gains nothing from split
ports, so both ports seem to go through the same path to AXISRAM. The fabric model has
this the wrong way round (MEM 1 cycle a word, PERIPH 2, +3 across). Bursts of 1, 4 or 8
time the same on these channels, to within 0.0001 on every ratio, so the BSP's burst of 1
and the RTL's 4/8 give the same answer.

2026-10-27  E1/E2 on the board, 10 seeds x 3 runs, paired:

- throughput lost by inverting TX: -0.2% in E1, -0.1% in E2, inverted very slightly
  ahead. The RTL said 23.3% and 11.6%.
- TX's own transfer time x1.51 in E1, x1.34 in E2. RX doesn't move.
- balanced E1, TX is done after 64k cycles and the RX channels at 96k. Inverted, all three
  finish at 96k. In balanced E2 the memory-to-SAI channels (TX, bg ch4 and ch6) finish at
  191k and the rest at 256k. Inverted, TX drops back into the 256k group and ch4/ch6 finish
  at 126k.

The total doesn't move because AXISRAM is the bottleneck either way. 3 x 2048 words in
96k cycles is 15.7 a word, about the cost of one access. Inverting only changes which
channel gets it. With the buffers in AHB SRAM APB2 becomes the bottleneck instead (3.34-3.38
cycles a word) and the loss is still 0.0% in E1 and -1.3% in E2, TX time x1.42 and x1.27.

For latency, the probe jobs: one SAI channel does single 4-word blocks back to back while
the others stream 8192 words each, so they're still going when the probes end (checked
per job, it held in all of them). A block is timed from the CCR write to the CSR read that
shows TCF, so it includes the CPU's own register round trip, which is why it's 81 cycles
with nothing else running.

```
                  balanced        inverted
                mean   worst    mean   worst
TX alone          81     81       81     81
TX, E1 load      156    161      237    241
TX, E2 load      376    385      659    768
RX alone          88     88       88     88
RX, E1 load      250    264      224    248
RX, E2 load      621    640      650    776
```

TX latency goes up 1.5x with the RX channels running, 1.75x mean and 1.87x worst with
all eight. RX gets a little better in E1 and 1.12x worse at worst in E2. My guess at why:
inverted, TX's SAI writes go out on port 1 behind the RX channels' SRAM writes, ~16
cycles each, where balanced they share port 0 with other APB accesses of a few cycles.
I haven't shown that, it just fits the numbers.

Polling check: the CPU reads SMISR while the channels run, over the same AHB as GPDMA1's
register port. Polling flat out moves the E1 loss by about 1% in favour of inverted.
Every 200 CPU cycles, which the main runs use, moves it by 0.1-0.2%, and every 2000 by
nothing I can measure. I ran the whole set twice with a reset and reload in between:
the main losses moved by up to 0.12 points (the flat-out polling ones by 0.25) and the
latency ratios by up to 0.03.

Not covered: the SAI actually running (at audio rates the channels sit idle most of the
time and none of this saturation happens), channels 12-15 with their bigger fifos, where
bursts might matter, other clock setups, other boards. It's one board and one silicon rev.

## mutation testing

2026-10-27  while writing m04 (full flag one entry late) I noticed A4 as first written,
`push |-> !full` on the fifo's own `full` output, could never catch it. A late flag stays
low on the push that overflows, so it vouches for itself. The checker now works out full
and empty from `count` and the property is the same. It's a gap in my checker, not an RTL
bug, so it doesn't go in the list below.

Also made the test stop at the first scoreboard error instead of running to the
watchdog. m09 used to sit there for 50 cycles a beat on every seed.

First run: 10/10 killed, each by the check it was aimed at, so all six assertions have
killed something. m06 (cmd_addr moving while cmd_ready is low) gets past all the
directed tests on the depth-4 build because none of them stall cmd_ready, it took
random seed 1 (light back-pressure) to see it.

## bugs hit along the way

None. Neither the scoreboard nor an assertion ever fired on the real RTL, in the directed
tests or the 1000 seeds. What did break along the way was all testbench and scripts, which
don't count: the fifo unit test first checked a cycle late, `export SEEDS` in the tb
makefile handed the test an empty string, the regression runner wrote results relative to
tb/ and then couldn't find them, and the A4 checker gap above.
