`default_nettype none

bind rr_arbiter arb_sva #(.N(N)) u_arb_sva (
  .clk  (clk),
  .rst_n(rst_n),
  .req  (req),
  .gnt  (gnt)
);

bind sync_fifo fifo_sva #(.DEPTH(DEPTH)) u_fifo_sva (
  .clk  (clk),
  .rst_n(rst_n),
  .push (push),
  .pop  (pop),
  .count(count)
);

bind port_master port_sva #(.ADDR_W(ADDR_W), .LEN_W(LEN_W), .ID_W(ID_W)) u_port_sva (
  .clk      (clk),
  .rst_n    (rst_n),
  .cmd_valid(cmd_valid),
  .cmd_ready(cmd_ready),
  .cmd_write(cmd_write),
  .cmd_addr (cmd_addr),
  .cmd_len  (cmd_len),
  .cmd_inc  (cmd_inc),
  .cmd_id   (cmd_id)
);

`default_nettype wire
