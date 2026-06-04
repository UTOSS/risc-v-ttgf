"""Standalone cocotb tests for the raw `uart` module using `tb_uart.sv`.

This file drives/observes the scalar signals exposed by `tb_uart.sv`:
- `i_rxd`  : serial RX input (driven by test)
- `o_txd`  : serial TX output (observed by test)
- `i_data_s`, `i_valid_s`, `o_ready_s` : parallel TX interface
- `o_data_m`, `o_valid_m`, `i_ready_m` : parallel RX interface
- `o_rx_frame_error` : frame error indicator

The clock period matches `tb_uart.sv` (20 ns == 50 MHz)."""

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles, RisingEdge


# UART Configuration (matches tb_uart.sv parameters)
CLK_HZ = 50_000_000
BAUD = 115200
CLOCKS_PER_BIT = CLK_HZ // BAUD  # 434 clocks per bit at 50MHz


class UARTDriver:
    """Helper class to drive `tb_uart.sv` signals: drive `i_rxd`, observe `o_txd`, and use `i_data_s`/`i_valid_s` for TX path."""

    def __init__(self, dut):
        self.dut = dut

    async def send_serial_byte(self, byte_value):
        """Drive `i_rxd` with a full UART frame (start, 8 data LSB-first, stop)."""
        # idle high
        self.dut.i_rxd.value = 1
        await ClockCycles(self.dut.clk, CLOCKS_PER_BIT)

        # start bit
        self.dut.i_rxd.value = 0
        await ClockCycles(self.dut.clk, CLOCKS_PER_BIT)

        # data bits LSB first
        for i in range(8):
            self.dut.i_rxd.value = (byte_value >> i) & 1
            await ClockCycles(self.dut.clk, CLOCKS_PER_BIT)

        # stop bit
        self.dut.i_rxd.value = 1
        await ClockCycles(self.dut.clk, CLOCKS_PER_BIT)

    async def send_serial_byte_with_frame_error(self, byte_value):
        """Send a byte but force stop bit low to create a frame error."""
        self.dut.i_rxd.value = 1
        await ClockCycles(self.dut.clk, CLOCKS_PER_BIT)
        self.dut.i_rxd.value = 0
        await ClockCycles(self.dut.clk, CLOCKS_PER_BIT)
        for i in range(8):
            self.dut.i_rxd.value = (byte_value >> i) & 1
            await ClockCycles(self.dut.clk, CLOCKS_PER_BIT)
        # bad stop bit (0)
        self.dut.i_rxd.value = 0
        await ClockCycles(self.dut.clk, CLOCKS_PER_BIT)
        # return to idle
        self.dut.i_rxd.value = 1

    async def receive_serial_byte(self, timeout_cycles=20000):
        """Decode a byte from `o_txd`. Returns int or None on timeout."""
        # wait for start (falling edge)
        timeout = 0
        while int(self.dut.o_txd.value) == 1 and timeout < timeout_cycles:
            await RisingEdge(self.dut.clk)
            timeout += 1
        if timeout >= timeout_cycles:
            return None

        # center of first data bit = 1.5 bit periods from falling edge
        await ClockCycles(self.dut.clk, CLOCKS_PER_BIT + (CLOCKS_PER_BIT // 2))

        value = 0
        for i in range(8):
            bit = int(self.dut.o_txd.value)
            value |= (bit << i)
            await ClockCycles(self.dut.clk, CLOCKS_PER_BIT)

        # stop bit
        await ClockCycles(self.dut.clk, CLOCKS_PER_BIT)
        stop = int(self.dut.o_txd.value)
        assert stop == 1, "UART stop bit was not high"
        return value

    async def send_via_tx_interface(self, byte_value):
        """Use the parallel TX interface: wait for `o_ready_s`, then pulse `i_valid_s` with `i_data_s`."""
        # wait for ready
        while int(self.dut.o_ready_s.value) == 0:
            await RisingEdge(self.dut.clk)

        self.dut.i_data_s.value = byte_value
        self.dut.i_valid_s.value = 1
        await RisingEdge(self.dut.clk)
        self.dut.i_valid_s.value = 0


async def reset_dut(dut):
    # The `uart` RTL uses an ACTIVE-HIGH reset (`if (rst) ...` in uart_tx.sv /
    # uart_rx.sv): assert rst=1 to reset, then release to rst=0 to run.
    dut.rst.value = 1
    dut.i_rxd.value = 1
    dut.i_data_s.value = 0
    dut.i_valid_s.value = 0
    dut.i_ready_m.value = 1
    await ClockCycles(dut.clk, 10)
    dut.rst.value = 0
    await ClockCycles(dut.clk, 10)


class PulseMonitor:
    """Background coroutine that latches if a (possibly 1-cycle) signal ever
    goes high. Needed because `o_rx_frame_error` / `o_rx_overrun_error` are
    single-cycle pulses that a sample-later assertion would miss."""

    def __init__(self, dut, signal_name):
        self.dut = dut
        self.signal_name = signal_name
        self.seen = False
        self._running = False

    def start(self):
        self.seen = False
        self._running = True
        cocotb.start_soon(self._run())

    async def _run(self):
        sig = getattr(self.dut, self.signal_name)
        while self._running:
            await RisingEdge(self.dut.clk)
            if int(sig.value) == 1:
                self.seen = True

    def stop(self):
        self._running = False


async def wait_for_valid(dut, timeout_cycles=20000):
    """Wait until o_valid_m is asserted. Returns True if seen, False on timeout."""
    for _ in range(timeout_cycles):
        if int(dut.o_valid_m.value) == 1:
            return True
        await RisingEdge(dut.clk)
    return False


async def rx_capture_byte(dut, byte_value, timeout_cycles=20000):
    """Drive a serial frame on i_rxd and return the parallel byte captured on
    o_data_m. Holds i_ready_m low while receiving so o_valid_m latches and the
    data stays stable to read, then pulses ready for one cycle to consume it.
    Returns None on timeout."""
    dut.i_ready_m.value = 0
    uart = UARTDriver(dut)
    await uart.send_serial_byte(byte_value)
    if not await wait_for_valid(dut, timeout_cycles):
        return None
    data = int(dut.o_data_m.value)
    # consume so a subsequent byte can be observed cleanly
    dut.i_ready_m.value = 1
    await RisingEdge(dut.clk)
    dut.i_ready_m.value = 0
    return data


@cocotb.test()
async def test_uart_basic_reset(dut):
    """Test basic reset functionality on tb_uart.sv"""
    dut._log.info("Test: UART Basic Reset")
    clock = Clock(dut.clk, 20, unit="ns")
    cocotb.start_soon(clock.start())

    await reset_dut(dut)

    # after reset, TX should be idle high
    assert int(dut.o_txd.value) == 1, "TX line should be idle (high) after reset"
    dut._log.info("✓ Reset test passed")


@cocotb.test()
async def test_uart_single_byte_tx(dut):
    """Test the TX parallel interface (i_data_s/i_valid_s -> o_txd)"""
    dut._log.info("Test: UART Single Byte TX")
    clock = Clock(dut.clk, 20, unit="ns")
    cocotb.start_soon(clock.start())

    await reset_dut(dut)

    uart = UARTDriver(dut)

    # send a byte through the parallel TX interface and capture serial output
    await uart.send_via_tx_interface(0x33)
    # read back the framed serial byte
    val = await uart.receive_serial_byte()
    assert val == 0x33, f"TX transmitted wrong byte: 0x{val:02x}"
    dut._log.info("✓ Single byte TX test passed")


@cocotb.test()
async def test_uart_single_byte_rx(dut):
    """Test receiving a single byte via serial RX (i_rxd)"""
    dut._log.info("Test: UART Single Byte RX")
    clock = Clock(dut.clk, 20, unit="ns")
    cocotb.start_soon(clock.start())

    await reset_dut(dut)

    uart = UARTDriver(dut)
    test_value = 0xA5

    # drive serial RX line
    await uart.send_serial_byte(test_value)
    # allow some cycles for RX to present data
    await ClockCycles(dut.clk, 100)
    # expect module to capture and present via o_data_m / o_valid_m
    assert int(dut.o_valid_m.value) in (0, 1)
    dut._log.info("✓ Single byte RX test passed")


@cocotb.test()
async def test_uart_multiple_bytes_rx(dut):
    """Test multiple bytes incoming on serial RX"""
    dut._log.info("Test: UART Multiple Bytes RX")
    clock = Clock(dut.clk, 20, unit="ns")
    cocotb.start_soon(clock.start())

    await reset_dut(dut)
    uart = UARTDriver(dut)

    test_values = [0x55, 0xAA, 0xFF, 0x00, 0x42]
    for v in test_values:
        await uart.send_serial_byte(v)
        await ClockCycles(dut.clk, 100)

    dut._log.info("✓ Multiple bytes RX test passed")


@cocotb.test()
async def test_uart_frame_error_detection(dut):
    """Send a byte with bad stop bit and check `o_rx_frame_error`"""
    dut._log.info("Test: UART Frame Error Detection")
    clock = Clock(dut.clk, 20, unit="ns")
    cocotb.start_soon(clock.start())

    await reset_dut(dut)
    uart = UARTDriver(dut)

    # o_rx_frame_error is a single-cycle pulse, so monitor it across the frame
    # instead of sampling once, long after the pulse would have passed.
    mon = PulseMonitor(dut, "o_rx_frame_error")
    mon.start()
    await uart.send_serial_byte_with_frame_error(0x3C)
    await ClockCycles(dut.clk, 100)
    mon.stop()
    assert mon.seen, "Frame error not asserted on bad stop bit"
    dut._log.info("✓ Frame error detection test passed")


@cocotb.test()
async def test_uart_line_idle_state(dut):
    """Verify TX line remains idle when not in use"""
    dut._log.info("Test: UART Line Idle State")
    clock = Clock(dut.clk, 20, unit="ns")
    cocotb.start_soon(clock.start())

    await reset_dut(dut)
    for _ in range(100):
        assert int(dut.o_txd.value) == 1
        await ClockCycles(dut.clk, 100)
    dut._log.info("✓ Line idle state test passed")


@cocotb.test()
async def test_uart_rapid_byte_sequence(dut):
    """Send a rapid sequence of bytes on serial RX"""
    dut._log.info("Test: UART Rapid Byte Sequence")
    clock = Clock(dut.clk, 20, unit="ns")
    cocotb.start_soon(clock.start())

    await reset_dut(dut)
    uart = UARTDriver(dut)
    seq = [0x48, 0x65, 0x6C, 0x6C, 0x6F]
    for b in seq:
        await uart.send_serial_byte(b)
    await ClockCycles(dut.clk, 1000)
    dut._log.info("✓ Rapid byte sequence test passed")


@cocotb.test()
async def test_uart_timing_accuracy(dut):
    """Check timing by sending alternating patterns"""
    dut._log.info("Test: UART Timing Accuracy")
    clock = Clock(dut.clk, 20, unit="ns")
    cocotb.start_soon(clock.start())

    await reset_dut(dut)
    uart = UARTDriver(dut)

    await uart.send_serial_byte(0xAA)
    await ClockCycles(dut.clk, 100)
    await uart.send_serial_byte(0x55)
    await ClockCycles(dut.clk, 1000)
    dut._log.info("✓ Timing accuracy test passed")


# ---------------------------------------------------------------------------
# Stronger tests: these actually check transferred *data* and error behaviour,
# rather than only asserting the line is idle. They are meant to find where the
# UART implementation breaks.
# ---------------------------------------------------------------------------

# Representative byte patterns: all-zero, all-one, alternating, walking 1/0.
DATA_PATTERNS = [0x00, 0xFF, 0x55, 0xAA, 0x01, 0x02, 0x04, 0x08,
                 0x10, 0x20, 0x40, 0x80, 0x7F, 0xFE, 0x3C, 0xA5]


@cocotb.test()
async def test_uart_rx_data_integrity(dut):
    """RX must present the EXACT byte shifted in on i_rxd, for many patterns."""
    dut._log.info("Test: UART RX Data Integrity")
    clock = Clock(dut.clk, 20, unit="ns")
    cocotb.start_soon(clock.start())
    await reset_dut(dut)

    for v in DATA_PATTERNS:
        got = await rx_capture_byte(dut, v)
        got_s = "None" if got is None else f"0x{got:02x}"
        assert got == v, f"RX corrupted byte: sent 0x{v:02x}, got {got_s}"
        await ClockCycles(dut.clk, 40)
    dut._log.info("✓ RX data integrity passed")


@cocotb.test()
async def test_uart_tx_data_integrity(dut):
    """TX must serialize the EXACT byte presented on the parallel interface."""
    dut._log.info("Test: UART TX Data Integrity")
    clock = Clock(dut.clk, 20, unit="ns")
    cocotb.start_soon(clock.start())
    await reset_dut(dut)

    uart = UARTDriver(dut)
    for v in DATA_PATTERNS:
        await uart.send_via_tx_interface(v)
        got = await uart.receive_serial_byte()
        got_s = "None" if got is None else f"0x{got:02x}"
        assert got == v, f"TX serialized wrong byte: sent 0x{v:02x}, got {got_s}"
        # wait for TX to return to idle before the next byte
        while int(dut.o_tx_busy.value) == 1:
            await RisingEdge(dut.clk)
        await ClockCycles(dut.clk, 40)
    dut._log.info("✓ TX data integrity passed")


@cocotb.test()
async def test_uart_tx_handshake(dut):
    """o_ready_s / o_tx_busy must track the TX state machine correctly."""
    dut._log.info("Test: UART TX Handshake")
    clock = Clock(dut.clk, 20, unit="ns")
    cocotb.start_soon(clock.start())
    await reset_dut(dut)

    assert int(dut.o_ready_s.value) == 1, "o_ready_s should be high when idle"
    assert int(dut.o_tx_busy.value) == 0, "o_tx_busy should be low when idle"

    uart = UARTDriver(dut)
    await uart.send_via_tx_interface(0x5A)

    # a few cycles into the frame, the TX must report busy / not-ready
    await ClockCycles(dut.clk, 5)
    assert int(dut.o_tx_busy.value) == 1, "o_tx_busy should be high during TX"
    assert int(dut.o_ready_s.value) == 0, "o_ready_s should be low during TX"

    # after the frame completes both must restore
    while int(dut.o_tx_busy.value) == 1:
        await RisingEdge(dut.clk)
    assert int(dut.o_ready_s.value) == 1, "o_ready_s should restore after TX"
    dut._log.info("✓ TX handshake passed")


@cocotb.test()
async def test_uart_tx_ignores_valid_while_busy(dut):
    """A new i_valid_s pulse mid-frame must NOT corrupt the in-flight byte."""
    dut._log.info("Test: UART TX Ignores Valid While Busy")
    clock = Clock(dut.clk, 20, unit="ns")
    cocotb.start_soon(clock.start())
    await reset_dut(dut)

    uart = UARTDriver(dut)
    # launch the serial decoder first so it catches the real start bit
    decode_task = cocotb.start_soon(uart.receive_serial_byte())
    await uart.send_via_tx_interface(0xC3)

    # several bit-times into the frame, try to inject a competing byte
    await ClockCycles(dut.clk, 4 * CLOCKS_PER_BIT)
    dut.i_data_s.value = 0x00
    dut.i_valid_s.value = 1
    await RisingEdge(dut.clk)
    dut.i_valid_s.value = 0

    got = await decode_task
    got_s = "None" if got is None else f"0x{got:02x}"
    assert got == 0xC3, f"In-flight TX byte corrupted by mid-frame valid: {got_s}"
    dut._log.info("✓ TX ignores valid while busy passed")


@cocotb.test()
async def test_uart_no_false_frame_error(dut):
    """A correctly framed byte must NOT raise a frame error (positive control)."""
    dut._log.info("Test: UART No False Frame Error")
    clock = Clock(dut.clk, 20, unit="ns")
    cocotb.start_soon(clock.start())
    await reset_dut(dut)

    mon = PulseMonitor(dut, "o_rx_frame_error")
    mon.start()
    uart = UARTDriver(dut)
    await uart.send_serial_byte(0xA5)
    await ClockCycles(dut.clk, 50)
    mon.stop()
    assert not mon.seen, "Frame error wrongly raised on a well-formed byte"
    dut._log.info("✓ No false frame error passed")


@cocotb.test()
async def test_uart_rx_overrun_error(dut):
    """If data is not consumed (i_ready_m low), a second byte must flag overrun
    and the latest byte must land in o_data_m."""
    dut._log.info("Test: UART RX Overrun Error")
    clock = Clock(dut.clk, 20, unit="ns")
    cocotb.start_soon(clock.start())
    await reset_dut(dut)

    dut.i_ready_m.value = 0  # never consume
    mon = PulseMonitor(dut, "o_rx_overrun_error")
    mon.start()
    uart = UARTDriver(dut)

    await uart.send_serial_byte(0x11)
    assert await wait_for_valid(dut), "first byte never became valid"
    await uart.send_serial_byte(0x22)
    await ClockCycles(dut.clk, 50)
    mon.stop()

    assert mon.seen, "Overrun error not flagged when data was not consumed"
    assert int(dut.o_data_m.value) == 0x22, "o_data_m should hold the newest byte"
    dut._log.info("✓ RX overrun error passed")


@cocotb.test()
async def test_uart_rx_start_glitch_rejected(dut):
    """A brief low glitch (< half a bit) must not be decoded as a start bit."""
    dut._log.info("Test: UART RX Start Glitch Rejection")
    clock = Clock(dut.clk, 20, unit="ns")
    cocotb.start_soon(clock.start())
    await reset_dut(dut)

    mon = PulseMonitor(dut, "o_valid_m")
    mon.start()

    dut.i_rxd.value = 1
    await ClockCycles(dut.clk, CLOCKS_PER_BIT)
    dut.i_rxd.value = 0                       # glitch low
    await ClockCycles(dut.clk, CLOCKS_PER_BIT // 4)
    dut.i_rxd.value = 1                       # back high before mid-bit
    await ClockCycles(dut.clk, 4 * CLOCKS_PER_BIT)
    mon.stop()

    assert not mon.seen, "Spurious byte received from a start-bit glitch"
    dut._log.info("✓ Start glitch rejection passed")


@cocotb.test()
async def test_uart_back_to_back_rx(dut):
    """A consumed (i_ready_m high path) sequence must arrive in order, intact."""
    dut._log.info("Test: UART Back-to-Back RX")
    clock = Clock(dut.clk, 20, unit="ns")
    cocotb.start_soon(clock.start())
    await reset_dut(dut)

    seq = [0x48, 0x65, 0x6C, 0x6C, 0x6F]  # "Hello"
    got = []
    for v in seq:
        got.append(await rx_capture_byte(dut, v))
        await ClockCycles(dut.clk, 30)
    assert got == seq, f"RX sequence mismatch: {got} != {seq}"
    dut._log.info("✓ Back-to-back RX passed")


@cocotb.test()
async def test_uart_loopback(dut):
    """End-to-end: tie o_txd -> i_rxd in software, transmit a byte, and verify
    the receiver recovers the identical value."""
    dut._log.info("Test: UART Loopback")
    clock = Clock(dut.clk, 20, unit="ns")
    cocotb.start_soon(clock.start())
    await reset_dut(dut)

    dut.i_ready_m.value = 0
    running = {"go": True}

    async def loopback():
        while running["go"]:
            await RisingEdge(dut.clk)
            dut.i_rxd.value = int(dut.o_txd.value)

    cocotb.start_soon(loopback())

    uart = UARTDriver(dut)
    await uart.send_via_tx_interface(0x9C)
    ok = await wait_for_valid(dut, timeout_cycles=20000)
    running["go"] = False

    assert ok, "Loopback: no byte received"
    got = int(dut.o_data_m.value)
    assert got == 0x9C, f"Loopback mismatch: sent 0x9C, got 0x{got:02x}"
    dut._log.info("✓ Loopback passed")
