"""Cocotb integration tests for the UART-to-RISC-V core bridge.

The top-level tt_um_utoss_riscv module exposes a UART command interface that
can halt and run the core, write and read memory, and read architectural
registers. These tests exercise that protocol end-to-end.
"""

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles, ReadOnly, RisingEdge


CLK_HZ = 50_000_000
BAUD = 115_200
CLOCKS_PER_BIT = CLK_HZ // BAUD

UART_SOF = 0xA5
UART_RESP_SOF = 0x5A

CMD_WR32 = 0x10
CMD_RD32 = 0x11
CMD_RUN = 0x12
CMD_HALT = 0x13
CMD_RDREG = 0x14

R_ACK = 0x90
R_RD = 0x91
R_RDREG = 0x92

STATUS_OK = 0x00


def encode_i_type(imm, rs1, funct3, rd, opcode=0x13):
    imm = imm & 0xFFF
    return ((imm & 0xFFF) << 20) | ((rs1 & 0x1F) << 15) | ((funct3 & 0x7) << 12) | ((rd & 0x1F) << 7) | (opcode & 0x7F)


def encode_r_type(funct7, rs2, rs1, funct3, rd, opcode=0x33):
    return ((funct7 & 0x7F) << 25) | ((rs2 & 0x1F) << 20) | ((rs1 & 0x1F) << 15) | ((funct3 & 0x7) << 12) | ((rd & 0x1F) << 7) | (opcode & 0x7F)


def encode_s_type(imm, rs2, rs1, funct3, opcode=0x23):
    imm = imm & 0xFFF
    imm_hi = (imm >> 5) & 0x7F
    imm_lo = imm & 0x1F
    return ((imm_hi & 0x7F) << 25) | ((rs2 & 0x1F) << 20) | ((rs1 & 0x1F) << 15) | ((funct3 & 0x7) << 12) | ((imm_lo & 0x1F) << 7) | (opcode & 0x7F)


def encode_j_type(imm, rd, opcode=0x6F):
    imm = imm & 0x1FFFFF
    bit20 = (imm >> 20) & 0x1
    bit10_1 = (imm >> 1) & 0x3FF
    bit11 = (imm >> 11) & 0x1
    bit19_12 = (imm >> 12) & 0xFF
    return (
        (bit20 << 31)
        | (bit19_12 << 12)
        | (bit11 << 20)
        | (bit10_1 << 21)
        | ((rd & 0x1F) << 7)
        | (opcode & 0x7F)
    )


def word_to_bytes(value):
    return [
        value & 0xFF,
        (value >> 8) & 0xFF,
        (value >> 16) & 0xFF,
        (value >> 24) & 0xFF,
    ]


def checksum(bytes_):
    value = 0
    for byte in bytes_:
        value ^= byte & 0xFF
    return value & 0xFF


class UartBridge:
    def __init__(self, dut):
        self.dut = dut
        self.rx_buffer = []

    def set_rxd_idle(self):
        self.dut.ui_in.value = 0x08

    def set_rxd(self, level):
        self.dut.ui_in.value = 0x08 if level else 0x00

    async def send_byte(self, value):
        self.set_rxd(1)
        await ClockCycles(self.dut.clk, CLOCKS_PER_BIT)

        self.set_rxd(0)
        await ClockCycles(self.dut.clk, CLOCKS_PER_BIT)

        for bit_index in range(8):
            self.set_rxd((value >> bit_index) & 1)
            await ClockCycles(self.dut.clk, CLOCKS_PER_BIT)

        self.set_rxd(1)
        await ClockCycles(self.dut.clk, CLOCKS_PER_BIT)

    async def monitor_tx(self):
        previous_bit = 1

        while True:
            await RisingEdge(self.dut.clk)
            await ReadOnly()

            current_bit = (int(self.dut.uo_out.value) >> 4) & 1
            if previous_bit == 1 and current_bit == 0:
                await ClockCycles(self.dut.clk, CLOCKS_PER_BIT + (CLOCKS_PER_BIT // 2))

                value = 0
                for bit_index in range(8):
                    current_bit = (int(self.dut.uo_out.value) >> 4) & 1
                    value |= current_bit << bit_index
                    await ClockCycles(self.dut.clk, CLOCKS_PER_BIT)

                # After 8 data-bit samples we are already at the center of the stop bit.
                stop_bit = (int(self.dut.uo_out.value) >> 4) & 1
                assert stop_bit == 1, "UART stop bit was not high"
                self.rx_buffer.append(value)

            previous_bit = current_bit

    async def recv_byte(self):
        while not self.rx_buffer:
            await RisingEdge(self.dut.clk)

        return self.rx_buffer.pop(0)

    async def transact(self, payload, expected_response_len):
        for byte in [UART_SOF, *payload]:
            await self.send_byte(byte)

        response = []
        for _ in range(expected_response_len):
            response.append(await self.recv_byte())
        return response

    async def halt_core(self):
        response = await self.transact([CMD_HALT, CMD_HALT], 4)
        self._check_ack(response, CMD_HALT)
        return response

    async def run_core(self):
        response = await self.transact([CMD_RUN, CMD_RUN], 4)
        self._check_ack(response, CMD_RUN)
        return response

    async def write32(self, addr, value):
        payload = [CMD_WR32]
        payload.extend(word_to_bytes(addr))
        payload.extend(word_to_bytes(value))
        payload.append(checksum(payload))
        response = await self.transact(payload, 4)
        self._check_ack(response, CMD_WR32)

    async def read32(self, addr):
        payload = [CMD_RD32]
        payload.extend(word_to_bytes(addr))
        payload.append(checksum(payload))
        response = await self.transact(payload, 7)
        self._check_read(response, R_RD)
        return self._bytes_to_word(response[2:6])

    async def read_reg(self, reg_index):
        payload = [CMD_RDREG, reg_index & 0x1F]
        payload.append(checksum(payload))
        response = await self.transact(payload, 7)
        self._check_read(response, R_RDREG)
        return self._bytes_to_word(response[2:6])

    def _check_ack(self, response, command):
        assert response[0] == UART_RESP_SOF, f"Expected response SOF 0x{UART_RESP_SOF:02x}"
        assert response[1] == R_ACK, f"Expected ACK response 0x{R_ACK:02x}"
        assert response[2] == STATUS_OK, f"Expected OK status, got 0x{response[2]:02x}"
        assert response[3] == (R_ACK ^ STATUS_OK), "ACK checksum mismatch"

    def _check_read(self, response, response_type):
        assert response[0] == UART_RESP_SOF, f"Expected response SOF 0x{UART_RESP_SOF:02x}"
        assert response[1] == response_type, f"Expected response type 0x{response_type:02x}"
        assert response[6] == checksum(response[1:6]), "Read checksum mismatch"

    @staticmethod
    def _bytes_to_word(data_bytes):
        return (
            (data_bytes[0] & 0xFF)
            | ((data_bytes[1] & 0xFF) << 8)
            | ((data_bytes[2] & 0xFF) << 16)
            | ((data_bytes[3] & 0xFF) << 24)
        )


async def reset_dut(dut):
    dut.ena.value = 1
    dut.uio_in.value = 0
    dut.ui_in.value = 0x08
    dut.rst_n.value = 0
    await ClockCycles(dut.clk, 10)
    dut.rst_n.value = 1
    await ClockCycles(dut.clk, 10)


@cocotb.test()
async def test_uart_core_bridge(dut):
    dut._log.info("Starting UART-to-core integration test")

    clock = Clock(dut.clk, 20, unit="ns")
    cocotb.start_soon(clock.start())

    await reset_dut(dut)

    bridge = UartBridge(dut)
    cocotb.start_soon(bridge.monitor_tx())
    design = dut.dut

    assert int(design.u_master.hold_core.value) == 1, "Core should start held after reset"
    assert (int(dut.uo_out.value) & 0x10) != 0, "UART TX should idle high after reset"

    dut._log.info("Halting core through UART")
    await bridge.halt_core()
    assert int(design.u_master.hold_core.value) == 1, "HALT should keep the core held"

    program = [
        encode_i_type(32, 0, 0x0, 1),          # addi x1, x0, 32
        encode_i_type(0x123, 0, 0x0, 2),       # addi x2, x0, 0x123
        encode_s_type(0, 2, 1, 0x2),           # sw x2, 0(x1)
        encode_i_type(0, 1, 0x2, 3, 0x03),     # lw x3, 0(x1)
        encode_r_type(0x00, 3, 2, 0x0, 4),     # add x4, x2, x3
        encode_j_type(0, 0),                   # jal x0, 0
    ]

    for index, instruction in enumerate(program):
        address = index * 4
        dut._log.info("Writing instruction 0x%08x to address 0x%08x", instruction, address)
        await bridge.write32(address, instruction)

    dut._log.info("Verifying instruction memory via UART readback")
    fetched = await bridge.read32(0)
    assert fetched == program[0], f"Instruction readback mismatch: 0x{fetched:08x} != 0x{program[0]:08x}"

    dut._log.info("Releasing core through UART RUN command")
    await bridge.run_core()
    assert int(design.u_master.hold_core.value) == 0, "RUN should release the core"

    await ClockCycles(dut.clk, 1200)

    dut._log.info("Re-halt the core after execution")
    await bridge.halt_core()
    assert int(design.u_master.hold_core.value) == 1, "HALT should reassert the hold signal"

    reg_x3 = await bridge.read_reg(3)
    reg_x4 = await bridge.read_reg(4)
    mem_word = await bridge.read32(32)

    assert reg_x3 == 0x123, f"x3 mismatch: expected 0x00000123, got 0x{reg_x3:08x}"
    assert reg_x4 == 0x246, f"x4 mismatch: expected 0x00000246, got 0x{reg_x4:08x}"
    assert mem_word == 0x123, f"Memory mismatch: expected 0x00000123, got 0x{mem_word:08x}"

    pc = int(design.core.dbg_pc.value)
    assert pc != 0, "Program counter did not advance after RUN"

    dut._log.info("UART/core bridge test completed successfully")
