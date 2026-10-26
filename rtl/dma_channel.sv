`default_nettype none

module dma_channel
  import dma_pkg::*;
#(
  parameter int DATA_W    = 32,
  parameter int ADDR_W    = 32,
  parameter int MAX_BURST = 16,
  parameter int BEATS_W   = 16,
  localparam int LEN_W    = $clog2(MAX_BURST + 1),
  localparam int BW       = $clog2(MAX_BURST)
) (
  input  wire logic               clk,
  input  wire logic               rst_n,

  input  wire logic               load,
  input  wire logic [ADDR_W-1:0]  cfg_src_addr,
  input  wire logic [ADDR_W-1:0]  cfg_dst_addr,
  input  wire logic [BEATS_W-1:0] cfg_beats,
  input  wire logic [LEN_W-1:0]   cfg_burst,
  input  wire logic               cfg_src_port,
  input  wire logic               cfg_dst_port,
  input  wire logic               cfg_src_inc,
  input  wire logic               cfg_dst_inc,
  output logic                    idle,
  output logic                    done,

  output logic                    req,
  output logic                    req_port,
  output logic                    req_write,
  output logic      [ADDR_W-1:0]  req_addr,
  output logic      [LEN_W-1:0]   req_len,
  output logic                    req_inc,
  input  wire logic               gnt,

  input  wire logic               rd_done,
  input  wire logic               wr_done,
  input  wire logic               buf_we,
  input  wire logic [DATA_W-1:0]  buf_wdata,
  input  wire logic               buf_re,
  output logic      [DATA_W-1:0]  buf_rdata
);
  localparam int ASH = $clog2(DATA_W / 8);

  ch_state_t          state;
  logic [ADDR_W-1:0]  src_addr, dst_addr;
  logic [BEATS_W-1:0] beats_left;
  logic [LEN_W-1:0]   burst, len;
  logic               src_port, dst_port, src_inc, dst_inc;

  logic [DATA_W-1:0]  data [MAX_BURST];
  logic [BW-1:0]      fill_ptr, drain_ptr;

  // the last burst carries whatever is left
  assign len = beats_left < BEATS_W'(burst) ? LEN_W'(beats_left) : burst;

  assign idle      = state == IDLE;
  assign done      = state == DONE;
  assign req       = state == RD_REQ || state == WR_REQ;
  assign req_write = state == WR_REQ;
  assign req_port  = req_write ? dst_port : src_port;
  assign req_addr  = req_write ? dst_addr : src_addr;
  assign req_inc   = req_write ? dst_inc : src_inc;
  assign req_len   = len;
  assign buf_rdata = data[drain_ptr];

  always_ff @(posedge clk) begin
    if (!rst_n) begin
      state      <= IDLE;
      src_addr   <= '0;
      dst_addr   <= '0;
      beats_left <= '0;
      burst      <= '0;
      src_port   <= 1'b0;
      dst_port   <= 1'b0;
      src_inc    <= 1'b0;
      dst_inc    <= 1'b0;
    end else begin
      case (state)
        IDLE: if (load) begin
          src_addr   <= cfg_src_addr;
          dst_addr   <= cfg_dst_addr;
          beats_left <= cfg_beats;
          burst      <= cfg_burst;
          src_port   <= cfg_src_port;
          dst_port   <= cfg_dst_port;
          src_inc    <= cfg_src_inc;
          dst_inc    <= cfg_dst_inc;
          state      <= RD_REQ;
        end
        RD_REQ: if (gnt) state <= RD_WAIT;
        RD_WAIT: if (rd_done) begin
          if (src_inc) src_addr <= src_addr + (ADDR_W'(len) << ASH);
          state <= WR_REQ;
        end
        WR_REQ: if (gnt) state <= WR_WAIT;
        WR_WAIT: if (wr_done) begin
          if (dst_inc) dst_addr <= dst_addr + (ADDR_W'(len) << ASH);
          beats_left <= beats_left - BEATS_W'(len);
          state      <= beats_left == BEATS_W'(len) ? DONE : RD_REQ;
        end
        DONE:    state <= IDLE;
        default: state <= IDLE;
      endcase
    end
  end

  always_ff @(posedge clk) begin
    if (!rst_n) begin
      fill_ptr  <= '0;
      drain_ptr <= '0;
      for (int i = 0; i < MAX_BURST; i++) data[i] <= '0;
    end else begin
      if (buf_we) begin
        data[fill_ptr] <= buf_wdata;
        fill_ptr       <= fill_ptr + BW'(1);
      end
      if (rd_done) fill_ptr <= '0;
      if (buf_re)  drain_ptr <= drain_ptr + BW'(1);
      if (wr_done) drain_ptr <= '0;
    end
  end

endmodule

`default_nettype wire
