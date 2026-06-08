`default_nettype none
`timescale 1ns / 1ps

/* This testbench provides signal wires for cocotb stimulus and inspection.
   For cocotb-free gate-level testing, use the run_gl_icarus.sh script.
*/
module tb ();

  // Waveform dump
  initial begin
    $dumpfile("tb.fst");
    $dumpvars(0, tb);
  end

  // Wire up the inputs and outputs for cocotb control:
  reg clk;
  reg rst_n;
  reg ena;
  reg [7:0] ui_in;
  reg [7:0] uio_in;
  wire [7:0] uo_out;
  wire [7:0] uio_out;
  wire [7:0] uio_oe;

  // Instantiate the design:
  tt_um_utoss_riscv dut (
      .ui_in  (ui_in),    // Dedicated inputs
      .uo_out (uo_out),   // Dedicated outputs
      .uio_in (uio_in),   // IOs: Input path
      .uio_out(uio_out),  // IOs: Output path
      .uio_oe (uio_oe),   // IOs: Enable path (active high: 0=input, 1=output)
      .ena    (ena),      // enable - goes high when design is selected
      .clk    (clk),      // clock
      .rst_n  (rst_n)     // not reset
  );

endmodule
