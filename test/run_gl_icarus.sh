#!/bin/bash
# Simple gate-level test runner using Icarus Verilog
# Usage: PDK_ROOT=/path/to/pdk ./run_gl_icarus.sh

set -e

# Check PDK_ROOT
if [ -z "$PDK_ROOT" ]; then
  echo "ERROR: PDK_ROOT not set. Please set PDK_ROOT to the gf180mcu PDK path."
  exit 1
fi

PDK_LIB="$PDK_ROOT/gf180mcuD/libs.ref/gf180mcu_fd_sc_mcu7t5v0/verilog"

if [ ! -f "$PDK_LIB/primitives.v" ]; then
  echo "ERROR: PDK primitives not found at $PDK_LIB/primitives.v"
  exit 1
fi

echo "Running GL test with Icarus Verilog..."
echo "PDK_ROOT: $PDK_ROOT"
echo ""

TESTBENCH="tb_gl.sv"
NETLIST="gate_level_netlist.v"
SIMV="simv_gl"
LOGFILE="gl_test.log"

# Compile
echo "[1/3] Compiling with iverilog..."
iverilog -g2012 -o "$SIMV" \
  -I"$PDK_LIB" \
  "$PDK_LIB/primitives.v" \
  "$PDK_LIB/gf180mcu_fd_sc_mcu7t5v0.v" \
  "$NETLIST" \
  "$TESTBENCH" \
  2>&1 | tee "$LOGFILE"

# Run
echo ""
echo "[2/3] Running simulation with vvp..."
vvp -n "$SIMV" 2>&1 | tee -a "$LOGFILE"

# Summary
echo ""
echo "[3/3] Test complete."
echo "Simulation log: $LOGFILE"
echo ""

# Simple pass/fail check (look for test signals or output assertions in waveform)
if grep -q "FAIL\|ERROR" "$LOGFILE" 2>/dev/null; then
  echo "Result: FAILED (check $LOGFILE for details)"
  exit 1
else
  echo "Result: PASSED (no errors detected)"
  exit 0
fi
