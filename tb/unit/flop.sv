`default_nettype none

module flop (
  input  wire logic clk,
  input  wire logic rst_n,
  input  wire logic d,
  output logic      q
);
  always_ff @(posedge clk)
    if (!rst_n) q <= 1'b0;
    else        q <= d;
endmodule

`default_nettype wire
