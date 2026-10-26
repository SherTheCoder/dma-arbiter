`default_nettype none

module dma_arbiter_top #(
  parameter int NUM_CH         = 8,
  parameter int DATA_W         = 32,
  parameter int ADDR_W         = 32,
  parameter int MAX_BURST      = 16,
  parameter int CMD_FIFO_DEPTH = 4,
  parameter int BEATS_W        = 16,
  localparam int ID_W          = $clog2(NUM_CH),
  localparam int LEN_W         = $clog2(MAX_BURST + 1)
) (
  input  wire logic               clk,
  input  wire logic               rst_n,

  input  wire logic               cfg_valid,
  output logic                    cfg_ready,
  input  wire logic [ID_W-1:0]    cfg_ch,
  input  wire logic [ADDR_W-1:0]  cfg_src_addr,
  input  wire logic [ADDR_W-1:0]  cfg_dst_addr,
  input  wire logic [BEATS_W-1:0] cfg_beats,
  input  wire logic [LEN_W-1:0]   cfg_burst,
  input  wire logic               cfg_src_port,
  input  wire logic               cfg_dst_port,
  input  wire logic               cfg_src_inc,
  input  wire logic               cfg_dst_inc,
  output logic      [NUM_CH-1:0]  ch_busy,
  output logic      [NUM_CH-1:0]  ch_done,

  output logic                    p0_cmd_valid,
  input  wire logic               p0_cmd_ready,
  output logic                    p0_cmd_write,
  output logic      [ADDR_W-1:0]  p0_cmd_addr,
  output logic      [LEN_W-1:0]   p0_cmd_len,
  output logic                    p0_cmd_inc,
  output logic      [ID_W-1:0]    p0_cmd_id,
  output logic                    p0_wvalid,
  input  wire logic               p0_wready,
  output logic      [DATA_W-1:0]  p0_wdata,
  output logic                    p0_wlast,
  input  wire logic               p0_rvalid,
  output logic                    p0_rready,
  input  wire logic [DATA_W-1:0]  p0_rdata,
  input  wire logic               p0_rlast,
  input  wire logic [ID_W-1:0]    p0_rid,

  output logic                    p1_cmd_valid,
  input  wire logic               p1_cmd_ready,
  output logic                    p1_cmd_write,
  output logic      [ADDR_W-1:0]  p1_cmd_addr,
  output logic      [LEN_W-1:0]   p1_cmd_len,
  output logic                    p1_cmd_inc,
  output logic      [ID_W-1:0]    p1_cmd_id,
  output logic                    p1_wvalid,
  input  wire logic               p1_wready,
  output logic      [DATA_W-1:0]  p1_wdata,
  output logic                    p1_wlast,
  input  wire logic               p1_rvalid,
  output logic                    p1_rready,
  input  wire logic [DATA_W-1:0]  p1_rdata,
  input  wire logic               p1_rlast,
  input  wire logic [ID_W-1:0]    p1_rid
);
  localparam int CW = 1 + ADDR_W + LEN_W + 1 + ID_W;

  logic [NUM_CH-1:0]             ch_idle, ch_req, ch_port, ch_write, ch_inc;
  logic [NUM_CH-1:0][ADDR_W-1:0] ch_addr;
  logic [NUM_CH-1:0][LEN_W-1:0]  ch_len;
  logic [NUM_CH-1:0][DATA_W-1:0] ch_word;

  logic [NUM_CH-1:0] req0, req1, gnt0, gnt1;
  logic              full0, full1;
  logic [CW-1:0]     push_cmd0, push_cmd1;

  logic [ID_W-1:0]   id0, id1;
  logic              re0, re1, we0, we1, rd_done0, rd_done1, wr_done0, wr_done1;
  logic [DATA_W-1:0] wd0, wd1;

  assign cfg_ready = ch_idle[cfg_ch];
  assign ch_busy   = ~ch_idle;

  for (genvar i = 0; i < NUM_CH; i++) begin : g_ch
    logic hit0, hit1;
    assign hit0 = id0 == ID_W'(i);
    assign hit1 = id1 == ID_W'(i);

    dma_channel #(
      .DATA_W   (DATA_W),
      .ADDR_W   (ADDR_W),
      .MAX_BURST(MAX_BURST),
      .BEATS_W  (BEATS_W)
    ) u_ch (
      .clk,
      .rst_n,
      .load        (cfg_valid && cfg_ready && cfg_ch == ID_W'(i)),
      .cfg_src_addr,
      .cfg_dst_addr,
      .cfg_beats,
      .cfg_burst,
      .cfg_src_port,
      .cfg_dst_port,
      .cfg_src_inc,
      .cfg_dst_inc,
      .idle        (ch_idle[i]),
      .done        (ch_done[i]),
      .req         (ch_req[i]),
      .req_port    (ch_port[i]),
      .req_write   (ch_write[i]),
      .req_addr    (ch_addr[i]),
      .req_len     (ch_len[i]),
      .req_inc     (ch_inc[i]),
      .gnt         (gnt0[i] || gnt1[i]),
      .rd_done     ((rd_done0 && hit0) || (rd_done1 && hit1)),
      .wr_done     ((wr_done0 && hit0) || (wr_done1 && hit1)),
      .buf_we      ((we0 && hit0) || (we1 && hit1)),
      .buf_wdata   (we0 && hit0 ? wd0 : wd1),
      .buf_re      ((re0 && hit0) || (re1 && hit1)),
      .buf_rdata   (ch_word[i])
    );
  end

  assign req0 = ch_req & ~ch_port;
  assign req1 = ch_req & ch_port;

  rr_arbiter #(.N(NUM_CH)) u_arb0 (.clk, .rst_n, .req(req0), .accept(!full0), .gnt(gnt0));
  rr_arbiter #(.N(NUM_CH)) u_arb1 (.clk, .rst_n, .req(req1), .accept(!full1), .gnt(gnt1));

  always_comb begin
    push_cmd0 = '0;
    push_cmd1 = '0;
    for (int i = 0; i < NUM_CH; i++) begin
      if (gnt0[i]) push_cmd0 = {ch_write[i], ch_addr[i], ch_len[i], ch_inc[i], ID_W'(i)};
      if (gnt1[i]) push_cmd1 = {ch_write[i], ch_addr[i], ch_len[i], ch_inc[i], ID_W'(i)};
    end
  end

  port_master #(
    .DATA_W(DATA_W),
    .ADDR_W(ADDR_W),
    .LEN_W (LEN_W),
    .ID_W  (ID_W),
    .DEPTH (CMD_FIFO_DEPTH)
  ) u_pm0 (
    .clk,
    .rst_n,
    .push      (|gnt0),
    .push_cmd  (push_cmd0),
    .full      (full0),
    .cmd_valid (p0_cmd_valid),
    .cmd_ready (p0_cmd_ready),
    .cmd_write (p0_cmd_write),
    .cmd_addr  (p0_cmd_addr),
    .cmd_len   (p0_cmd_len),
    .cmd_inc   (p0_cmd_inc),
    .cmd_id    (p0_cmd_id),
    .wvalid    (p0_wvalid),
    .wready    (p0_wready),
    .wdata     (p0_wdata),
    .wlast     (p0_wlast),
    .rvalid    (p0_rvalid),
    .rready    (p0_rready),
    .rdata     (p0_rdata),
    .rlast     (p0_rlast),
    .rid       (p0_rid),
    .id        (id0),
    .buf_rdata (ch_word[id0]),
    .buf_re    (re0),
    .buf_we    (we0),
    .buf_wdata (wd0),
    .rd_done   (rd_done0),
    .wr_done   (wr_done0)
  );

  port_master #(
    .DATA_W(DATA_W),
    .ADDR_W(ADDR_W),
    .LEN_W (LEN_W),
    .ID_W  (ID_W),
    .DEPTH (CMD_FIFO_DEPTH)
  ) u_pm1 (
    .clk,
    .rst_n,
    .push      (|gnt1),
    .push_cmd  (push_cmd1),
    .full      (full1),
    .cmd_valid (p1_cmd_valid),
    .cmd_ready (p1_cmd_ready),
    .cmd_write (p1_cmd_write),
    .cmd_addr  (p1_cmd_addr),
    .cmd_len   (p1_cmd_len),
    .cmd_inc   (p1_cmd_inc),
    .cmd_id    (p1_cmd_id),
    .wvalid    (p1_wvalid),
    .wready    (p1_wready),
    .wdata     (p1_wdata),
    .wlast     (p1_wlast),
    .rvalid    (p1_rvalid),
    .rready    (p1_rready),
    .rdata     (p1_rdata),
    .rlast     (p1_rlast),
    .rid       (p1_rid),
    .id        (id1),
    .buf_rdata (ch_word[id1]),
    .buf_re    (re1),
    .buf_we    (we1),
    .buf_wdata (wd1),
    .rd_done   (rd_done1),
    .wr_done   (wr_done1)
  );

endmodule

`default_nettype wire
