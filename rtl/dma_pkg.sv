`default_nettype none

package dma_pkg;

  typedef enum logic [2:0] {
    IDLE,
    RD_REQ,
    RD_WAIT,
    WR_REQ,
    WR_WAIT,
    DONE
  } ch_state_t;

  typedef enum logic [1:0] {
    P_IDLE,
    P_CMD,
    P_WDATA,
    P_RDATA
  } pm_state_t;

endpackage

`default_nettype wire
