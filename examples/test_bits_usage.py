"""Status words and payload operations, executed without TwinCAT or hardware."""

from pathlib import Path

from tc_emulator import Runtime

SOURCE = Path(__file__).with_name("bits.st")


def test_decode_status_and_write_control_bits_without_changing_neighbors():
    runtime = Runtime.from_files([SOURCE])
    device = runtime.instantiate("FB_DeviceWords")
    command = runtime.cell("WORD", 0x1201)
    enable_bit = command.bit(7)
    device.call(status=0x3401, enable=True, acknowledge=True, command=command)
    assert device.output("ready") is True
    assert device.output("fault") is False
    assert device.output("errorCode") == 0x34
    assert command.value == 0x9281
    assert enable_bit.value is True
    device.call(status=0x3409, acknowledge=False, command=command)
    assert device.output("fault") is True
    assert command.value == 0x1201
    assert enable_bit.value is False


def test_pack_two_words_and_unpack_high_byte_of_dword():
    runtime = Runtime.from_files([SOURCE])
    packed = runtime.call("F_PackWords", low=0x1234, high=0xABCD).value
    assert packed == 0xABCD1234
    assert runtime.call("F_HighByte", value=packed).value == 0xAB
    assert runtime.call("F_PackWords", low=0xFFFF, high=0xFFFF).value == 0xFFFFFFFF


def test_rotate_byte_wraps_the_top_bit_and_retains_width():
    runtime = Runtime.from_files([SOURCE])
    assert runtime.call("F_RotateMask", mask=0b10000001).value == 0b00000011
    assert runtime.call("F_RotateMask", mask=0xFF).value == 0xFF
