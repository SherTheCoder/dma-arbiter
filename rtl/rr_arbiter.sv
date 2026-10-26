`default_nettype none

module rr_arbiter #(
  parameter int N = 8
) (
  input  wire logic         clk,
  input  wire logic         rst_n,
  input  wire logic [N-1:0] req,
  input  wire logic         accept,
  output logic      [N-1:0] gnt
);
  // channels above the last winner, they get first pick next time
  logic [N-1:0] mask;
  logic [N-1:0] mreq;

  assign mreq = req & mask;

  always_comb begin
    gnt = '0;
    if (accept) begin
      if (|mreq) gnt = mreq & -mreq;
      else       gnt = req & -req;
    end
  end

  always_ff @(posedge clk)
    if (!rst_n)    mask <= '0;
    else if (|gnt) mask <= ~(gnt | (gnt - N'(1)));

endmodule

`default_nettype wire
