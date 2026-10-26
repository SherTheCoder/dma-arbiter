`default_nettype none

// the three checkers share one file
/* verilator lint_off DECLFILENAME */

module arb_sva #(
  parameter int N = 8
) (
  input wire logic         clk,
  input wire logic         rst_n,
  input wire logic [N-1:0] req,
  input wire logic [N-1:0] gnt
);
  localparam int CW = $clog2(N + 1);

  // grants that went to someone else while channel i was waiting
  logic [N-1:0][CW-1:0] wait_cnt;

  for (genvar i = 0; i < N; i++) begin : g_wait
    always_ff @(posedge clk)
      if (!rst_n || !req[i] || gnt[i]) wait_cnt[i] <= '0;
      else if (|gnt)                   wait_cnt[i] <= wait_cnt[i] + CW'(1);

    a_rr_bounded_wait: assert property (@(posedge clk) disable iff (!rst_n) wait_cnt[i] < CW'(N))
      else $error("A3 rr_bounded_wait: ch%0d passed over %0d times", i, wait_cnt[i]);
  end

  a_gnt_onehot0: assert property (@(posedge clk) disable iff (!rst_n) $onehot0(gnt))
    else $error("A1 gnt_onehot0: gnt=%b", gnt);
  a_gnt_has_req: assert property (@(posedge clk) disable iff (!rst_n) (gnt & ~req) == '0)
    else $error("A2 gnt_has_req: gnt=%b req=%b", gnt, req);

  c_all_req:  cover property (@(posedge clk) disable iff (!rst_n) req == '1);
  c_four_req: cover property (@(posedge clk) disable iff (!rst_n) $countones(req) >= 4);
endmodule


module fifo_sva #(
  parameter int DEPTH = 4,
  localparam int CW   = $clog2(DEPTH + 1)
) (
  input wire logic          clk,
  input wire logic          rst_n,
  input wire logic          push,
  input wire logic          pop,
  input wire logic [CW-1:0] count
);
  // from the count, not the fifo's own flags, so a wrong flag can't vouch for itself
  logic full, empty;
  assign full  = count == CW'(DEPTH);
  assign empty = count == '0;

  a_fifo_no_ovf: assert property (@(posedge clk) disable iff (!rst_n) push |-> !full)
    else $error("A4 fifo_no_overflow");
  a_fifo_no_udf: assert property (@(posedge clk) disable iff (!rst_n) pop |-> !empty)
    else $error("A5 fifo_no_underflow");

  c_full: cover property (@(posedge clk) disable iff (!rst_n) full);
endmodule


module port_sva #(
  parameter int ADDR_W = 32,
  parameter int LEN_W  = 5,
  parameter int ID_W   = 3
) (
  input wire logic              clk,
  input wire logic              rst_n,
  input wire logic              cmd_valid,
  input wire logic              cmd_ready,
  input wire logic              cmd_write,
  input wire logic [ADDR_W-1:0] cmd_addr,
  input wire logic [LEN_W-1:0]  cmd_len,
  input wire logic              cmd_inc,
  input wire logic [ID_W-1:0]   cmd_id
);
  a_cmd_stable: assert property (@(posedge clk) disable iff (!rst_n)
                  cmd_valid && !cmd_ready |=> cmd_valid &&
                  $stable({cmd_write, cmd_addr, cmd_len, cmd_inc, cmd_id}))
    else $error("A6 cmd_stable");

  c_cmd_stall: cover property (@(posedge clk) disable iff (!rst_n) cmd_valid && !cmd_ready);
endmodule

/* verilator lint_on DECLFILENAME */

`default_nettype wire
