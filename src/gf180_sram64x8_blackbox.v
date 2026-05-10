`default_nettype none

(* blackbox *)
module gf180mcu_fd_ip_sram__sram64x8m8wm1 (
    input  wire       CLK,
    input  wire       CEN,
    input  wire       GWEN,
    input  wire [7:0] WEN,
    input  wire [5:0] A,
    input  wire [7:0] D,
    output wire [7:0] Q,
    inout  wire       VDD,
    inout  wire       VSS
);

endmodule

`default_nettype wire