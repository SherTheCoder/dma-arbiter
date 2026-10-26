`default_nettype none

module port_master
  import dma_pkg::*;
#(
  parameter int DATA_W = 32,
  parameter int ADDR_W = 32,
  parameter int LEN_W  = 5,
  parameter int ID_W   = 3,
  parameter int DEPTH  = 4,
  localparam int CW    = 1 + ADDR_W + LEN_W + 1 + ID_W
) (
  input  wire logic              clk,
  input  wire logic              rst_n,

  // granted command, {write, addr, len, inc, id}
  input  wire logic              push,
  input  wire logic [CW-1:0]     push_cmd,
  output logic                   full,

  output logic                   cmd_valid,
  input  wire logic              cmd_ready,
  output logic                   cmd_write,
  output logic      [ADDR_W-1:0] cmd_addr,
  output logic      [LEN_W-1:0]  cmd_len,
  output logic                   cmd_inc,
  output logic      [ID_W-1:0]   cmd_id,
  output logic                   wvalid,
  input  wire logic              wready,
  output logic      [DATA_W-1:0] wdata,
  output logic                   wlast,
  input  wire logic              rvalid,
  output logic                   rready,
  input  wire logic [DATA_W-1:0] rdata,
  input  wire logic              rlast,
  // read data goes by the stored id, rid is only checked by the testbench
  /* verilator lint_off UNUSEDSIGNAL */
  input  wire logic [ID_W-1:0]   rid,
  /* verilator lint_on UNUSEDSIGNAL */

  // the channel being served and its buffer
  output logic      [ID_W-1:0]   id,
  input  wire logic [DATA_W-1:0] buf_rdata,
  output logic                   buf_re,
  output logic                   buf_we,
  output logic      [DATA_W-1:0] buf_wdata,
  output logic                   rd_done,
  output logic                   wr_done
);
  pm_state_t        state;
  logic [CW-1:0]    fifo_dout;
  logic             pop, empty;
  logic [LEN_W-1:0] beats_left;

  assign pop = state == P_IDLE && !empty;

  // count is only looked at by coverage
  /* verilator lint_off PINCONNECTEMPTY */
  sync_fifo #(.W(CW), .DEPTH(DEPTH)) u_fifo (
    .clk,
    .rst_n,
    .push,
    .din  (push_cmd),
    .pop,
    .dout (fifo_dout),
    .full,
    .empty,
    .count()
  );
  /* verilator lint_on PINCONNECTEMPTY */

  always_ff @(posedge clk) begin
    if (!rst_n) begin
      state      <= P_IDLE;
      cmd_write  <= 1'b0;
      cmd_addr   <= '0;
      cmd_len    <= '0;
      cmd_inc    <= 1'b0;
      cmd_id     <= '0;
      beats_left <= '0;
    end else begin
      case (state)
        P_IDLE: if (!empty) begin
          {cmd_write, cmd_addr, cmd_len, cmd_inc, cmd_id} <= fifo_dout;
          state <= P_CMD;
        end
        P_CMD: if (cmd_ready) begin
          beats_left <= cmd_len;
          state      <= cmd_write ? P_WDATA : P_RDATA;
        end
        P_WDATA: if (wready) begin
          beats_left <= beats_left - LEN_W'(1);
          if (wlast) state <= P_IDLE;
        end
        P_RDATA: if (rvalid && rlast) state <= P_IDLE;
        default: state <= P_IDLE;
      endcase
    end
  end

  assign cmd_valid = state == P_CMD;
  assign wvalid    = state == P_WDATA;
  assign wlast     = wvalid && beats_left == LEN_W'(1);
  assign wdata     = buf_rdata;
  assign rready    = state == P_RDATA;

  assign id        = cmd_id;
  assign buf_re    = wvalid && wready;
  assign buf_we    = rvalid && rready;
  assign buf_wdata = rdata;
  assign wr_done   = buf_re && wlast;
  assign rd_done   = buf_we && rlast;

endmodule

`default_nettype wire
