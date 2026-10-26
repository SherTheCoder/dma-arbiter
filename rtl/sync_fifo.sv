`default_nettype none

module sync_fifo #(
  parameter int W     = 8,
  parameter int DEPTH = 4,
  localparam int CW   = $clog2(DEPTH + 1)
) (
  input  wire logic          clk,
  input  wire logic          rst_n,
  input  wire logic          push,
  input  wire logic [W-1:0]  din,
  input  wire logic          pop,
  output logic      [W-1:0]  dout,
  output logic               full,
  output logic               empty,
  output logic      [CW-1:0] count
);
  localparam int PW = $clog2(DEPTH);

  logic [W-1:0]  mem [DEPTH];
  logic [PW-1:0] wr_ptr, rd_ptr;

  assign dout  = mem[rd_ptr];
  assign full  = count == CW'(DEPTH);
  assign empty = count == '0;

  function automatic logic [PW-1:0] next_ptr(input logic [PW-1:0] p);
    next_ptr = p == PW'(DEPTH - 1) ? '0 : p + PW'(1);
  endfunction

  always_ff @(posedge clk) begin
    if (!rst_n) begin
      wr_ptr <= '0;
      rd_ptr <= '0;
      count  <= '0;
      for (int i = 0; i < DEPTH; i++) mem[i] <= '0;
    end else begin
      if (push) begin
        mem[wr_ptr] <= din;
        wr_ptr      <= next_ptr(wr_ptr);
      end
      if (pop) rd_ptr <= next_ptr(rd_ptr);
      if (push && !pop) count <= count + CW'(1);
      if (pop && !push) count <= count - CW'(1);
    end
  end

endmodule

`default_nettype wire
