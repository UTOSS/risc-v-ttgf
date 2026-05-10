module MA #( parameter SIZE = 1024 )
  ( input  wire         clk
  , input  wire         rst_n
  , input  addr_t       address
  , input  data_t       write_data
  , input  wire   [3:0] write_enable
  , output data_t       read_data
  );
`ifdef USE_GF180_SRAM
    wire        addr_valid;
    wire [5:0]  sram_addr;
    wire        wr_en;

    wire [7:0]  q0;
    wire [7:0]  q1;
    wire [7:0]  q2;
    wire [7:0]  q3;

    wire        cen;
    wire        gwen;

    wire [7:0]  wen0;
    wire [7:0]  wen1;
    wire [7:0]  wen2;
    wire [7:0]  wen3;

    assign addr_valid  = (address[31:8] == 24'b0);
    assign sram_addr = address[7:2];

    assign wr_en = rst_n && addr_valid && (|write_enable);

    assign cen  = rst_n ? ~addr_valid : 1'b1;
    assign gwen = wr_en ? 1'b0 : 1'b1;

    assign wen0 = (wr_en && write_enable[0]) ? 8'h00 : 8'hff;
    assign wen1 = (wr_en && write_enable[1]) ? 8'h00 : 8'hff;
    assign wen2 = (wr_en && write_enable[2]) ? 8'h00 : 8'hff;
    assign wen3 = (wr_en && write_enable[3]) ? 8'h00 : 8'hff;

    assign read_data = addr_valid ? {q3, q2, q1, q0} : 32'h0000_0000;

`ifdef UTOSS_RISCV_HARDENING
    wire VPWR;
    wire VGND;
`else
    supply1 VPWR;
    supply0 VGND;
`endif

    gf180mcu_fd_ip_sram__sram64x8m8wm1 ram_b0 (
        .CLK  (clk),
        .CEN  (cen),
        .GWEN (gwen),
        .WEN  (wen0),
        .A    (sram_addr),
        .D    (write_data[7:0]),
        .Q    (q0),
        .VDD  (VPWR),
        .VSS  (VGND)
    );

    gf180mcu_fd_ip_sram__sram64x8m8wm1 ram_b1 (
        .CLK  (clk),
        .CEN  (cen),
        .GWEN (gwen),
        .WEN  (wen1),
        .A    (sram_addr),
        .D    (write_data[15:8]),
        .Q    (q1),
        .VDD  (VPWR),
        .VSS  (VGND)
    );

    gf180mcu_fd_ip_sram__sram64x8m8wm1 ram_b2 (
        .CLK  (clk),
        .CEN  (cen),
        .GWEN (gwen),
        .WEN  (wen2),
        .A    (sram_addr),
        .D    (write_data[23:16]),
        .Q    (q2),
        .VDD  (VPWR),
        .VSS  (VGND)
    );

    gf180mcu_fd_ip_sram__sram64x8m8wm1 ram_b3 (
        .CLK  (clk),
        .CEN  (cen),
        .GWEN (gwen),
        .WEN  (wen3),
        .A    (sram_addr),
        .D    (write_data[31:24]),
        .Q    (q3),
        .VDD  (VPWR),
        .VSS  (VGND)
    );

`else

  reg [31:0] M[0:SIZE -1];

`ifndef UTOSS_RISCV_HARDENING
  initial begin
    string mem_file;

    if ($value$plusargs("MEM=%s", mem_file)) begin
      $display("loading memory from <%s>", mem_file);
      $readmemh(mem_file, M);
      $display("memory loaded");
    end
  end
`endif

  always @(posedge clk) begin
    read_data <= M[address[31:2]]; // 2 LSBs used for byte addressing

    if (write_enable[0]) M[address[31:2]][7:0]   <= write_data[7:0];
    if (write_enable[1]) M[address[31:2]][15:8]  <= write_data[15:8];
    if (write_enable[2]) M[address[31:2]][23:16] <= write_data[23:16];
    if (write_enable[3]) M[address[31:2]][31:24] <= write_data[31:24];
  end

`endif
endmodule
