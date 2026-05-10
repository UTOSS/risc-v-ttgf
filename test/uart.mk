# Makefile for UART-specific testing
# Usage: make uart-sim  (runs SystemVerilog testbench)
#        make uart-test (runs cocotb testbench for UART)

SRC_DIR = $(PWD)/../src
UART_SRC = $(SRC_DIR)/utoss-risc-v/src

# UART module source files
UART_SOURCES = \
    $(UART_SRC)/uart.sv \
    $(UART_SRC)/uart_tx.sv \
    $(UART_SRC)/uart_rx.sv

# UART module dependencies
UART_DEPS = \
    $(UART_SRC)/types.svh \
    $(UART_SRC)/params.svh

# Simulators
UART_SIMULATORS ?= iverilog xvlog modelsim verilator

.PHONY: uart-check uart-clean uart-help

# Check if UART sources exist
uart-check:
	@echo "Checking UART sources..."
	@for file in $(UART_SOURCES); do \
		if [ ! -f "$$file" ]; then \
			echo "ERROR: Missing $$file"; \
			exit 1; \
		fi; \
	done
	@echo "✓ All UART sources found"

# Help for UART testing
uart-help:
	@echo "=== UART Testbench Targets ==="
	@echo ""
	@echo "uart-check        - Verify all UART source files exist"
	@echo "uart-sim-iverilog - Run standalone test with IVerilog (default)"
	@echo "uart-sim-xsim     - Run standalone test with Xilinx XSim"
	@echo "uart-sim-modelsim - Run standalone test with ModelSim"
	@echo "uart-test         - Run cocotb UART test with Verilator"
	@echo "uart-clean        - Remove generated files"
	@echo ""
	@echo "Environment variables:"
	@echo "  SIMULATOR   - Choose simulator (iverilog, xvlog, modelsim)"
	@echo ""

# IVerilog simulation (default)
uart-sim-iverilog: uart-check
	@echo "Running UART simulation with IVerilog..."
	iverilog -g2009 -sv -I$(UART_SRC) \
		-s tb_uart \
		$(UART_SOURCES) \
		tb_uart.sv \
		-o tb_uart.o
	vvp tb_uart.o -fst
	@echo "Waveforms saved to tb_uart.fst"

# Xilinx XSim simulation
uart-sim-xsim: uart-check
	@echo "Running UART simulation with XSim..."
	xvlog -sv -L xpm \
		$(UART_SOURCES) \
		tb_uart.sv
	xelab -timescale 1ns/1ps tb_uart
	xsim -R tb_uart

# ModelSim simulation
uart-sim-modelsim: uart-check
	@echo "Running UART simulation with ModelSim..."
	vlog -sv \
		$(UART_SOURCES) \
		tb_uart.sv
	vsim -c -do "run; quit" tb_uart
	@echo "Waveforms saved to vsim.wlf"

# Generic uart-sim target (uses default or specified simulator)
UART_SIM ?= iverilog
uart-sim:
	$(MAKE) -f uart.mk uart-sim-$(UART_SIM)

# Clean generated files
uart-clean:
	rm -f tb_uart.o tb_uart.fst
	rm -f tb.fst tb.vcd
	rm -f tb_uart.wdb tb_uart.wd
	rm -f vsim.wlf transcript
	rm -rf xsim.dir
	rm -f webtalk.log webtalk.jou
	rm -rf obj_dir
	rm -f tb_uart_verilator tb_uart*.vcd
	find . -name "*.vcd" -delete
	@echo "Cleaned UART test files"

# Run cocotb UART tests
uart-test:
	@echo "Running cocotb UART testbench..."
	make -B -f Makefile SIM=verilator VERILATOR_TRACE=1 TEST=test_uart
	@echo "Verilator simulation completed"

# Run cocotb UART tests with specific test
uart-test-single:
	@if [ -z "$(TEST_NAME)" ]; then \
		echo "Usage: make uart-test-single TEST_NAME=test_name"; \
		exit 1; \
	fi
	make -B -f Makefile SIM=verilator VERILATOR_TRACE=1 TEST=test_uart::$(TEST_NAME)

# Quick verification (run all checks)
uart-verify: uart-check
	@echo "UART testbench files verified and ready"
	@echo "To run standalone tests: make uart-sim"
	@echo "To run cocotb tests:     make uart-test"

.PHONY: uart-sim uart-sim-iverilog uart-sim-xsim uart-sim-modelsim uart-test uart-test-single uart-verify

