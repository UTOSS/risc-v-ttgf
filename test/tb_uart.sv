`default_nettype none
`timescale 1ns / 1ps

/*
 * Minimal testbench wrapper for the raw `uart` module.
 * This file provides the DUT instantiation and helper tasks while leaving all
 * stimulus to cocotb. Do not include any internal initial test sequences.
 */

module tb_uart ();

  // Clock and reset
  reg clk;
  reg rst;

  // TX interface (parallel -> serial)
  reg [7:0] i_data_s;
  reg i_valid_s;
  wire o_ready_s;

  // RX interface (serial -> parallel)
  wire [7:0] o_data_m;
  wire o_valid_m;
  reg i_ready_m;

  // UART lines
  reg i_rxd;
  wire o_txd;

  // Status signals
  wire o_tx_busy;
  wire o_rx_busy;
  wire o_rx_overrun_error;
  wire o_rx_frame_error;

  // Parameters for 50MHz clock, 115200 baud
  localparam int CLK_PERIOD = 20;  // 20ns for 50MHz
  localparam int BAUD = 115200;
  localparam int CLK_HZ = 50_000_000;
  localparam int CLKS_PER_BIT = CLK_HZ / BAUD;  // 434 clocks per bit

  // Dump signals for waveform viewers (cocotb may override)
  initial begin
    $dumpfile("tb_uart.fst");
    $dumpvars(0, tb_uart);
  end

  // Clock generation
  initial begin
    clk = 0;
    forever #(CLK_PERIOD/2) clk = ~clk;
  end

  // Instantiate UART module
  uart #(
    .DATA_WIDTH(8),
    .CLK_HZ(CLK_HZ),
    .BAUD(BAUD)
  ) dut (
    .clk(clk),
    .rst(rst),
    .i_data_s(i_data_s),
    .i_valid_s(i_valid_s),
    .o_ready_s(o_ready_s),
    .o_data_m(o_data_m),
    .o_valid_m(o_valid_m),
    .i_ready_m(i_ready_m),
    .i_rxd(i_rxd),
    .o_txd(o_txd),
    .o_tx_busy(o_tx_busy),
    .o_rx_busy(o_rx_busy),
    .o_rx_overrun_error(o_rx_overrun_error),
    .o_rx_frame_error(o_rx_frame_error)
  );

  // Helper task to send a byte on RX line
  task send_byte_on_rxd(input [7:0] byte_val);
    integer i;
    begin
      // Start bit (0)
      i_rxd = 0;
      #(CLKS_PER_BIT * CLK_PERIOD);

      // Data bits (LSB first)
      for (i = 0; i < 8; i = i + 1) begin
        i_rxd = byte_val[i];
        #(CLKS_PER_BIT * CLK_PERIOD);
      end

      // Stop bit (1)
      i_rxd = 1;
      #(CLKS_PER_BIT * CLK_PERIOD);
    end
  endtask

  // Helper task to send a byte with frame error
  task send_byte_with_frame_error(input [7:0] byte_val);
    integer i;
    begin
      // Start bit (0)
      i_rxd = 0;
      #(CLKS_PER_BIT * CLK_PERIOD);

      // Data bits (LSB first)
      for (i = 0; i < 8; i = i + 1) begin
        i_rxd = byte_val[i];
        #(CLKS_PER_BIT * CLK_PERIOD);
      end

      // Bad stop bit (0 instead of 1)
      i_rxd = 0;
      #(CLKS_PER_BIT * CLK_PERIOD);

      // Return to idle
      i_rxd = 1;
    end
  endtask

  // Helper task to send byte on TX (parallel interface)
  task send_byte_via_tx(input [7:0] byte_val);
    begin
      // Wait for TX ready
      wait(o_ready_s == 1);

      i_data_s = byte_val;
      i_valid_s = 1;
      @(posedge clk);
      i_valid_s = 0;

      // Wait for transmission to complete
      wait(o_tx_busy == 0);
    end
  endtask

  // Helper task to receive transmitted byte from txd line
  task automatic receive_byte_from_txd(output [7:0] byte_val);
    integer i;
    begin
      // Wait for start bit (falling edge on txd)
      wait(o_txd == 0);

      // Wait half bit time to center, then start sampling
      #((CLKS_PER_BIT/2 + 1) * CLK_PERIOD);

      // Sample data bits (LSB first)
      byte_val = 0;
      for (i = 0; i < 8; i = i + 1) begin
        #(CLKS_PER_BIT * CLK_PERIOD);
        byte_val[i] = o_txd;
      end

      // Skip stop bit
      #(CLKS_PER_BIT * CLK_PERIOD);
    end
  endtask

  // No internal initial test sequences here — cocotb controls stimulus.

endmodule
