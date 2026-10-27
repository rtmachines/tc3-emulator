"""Run with pytest; even long PLC delays require no real waiting."""

from pathlib import Path

from tc_emulator import Runtime

EXAMPLES = Path(__file__).resolve().parent


def test_delayed_fb_from_tcpou():
    runtime = Runtime.from_files([EXAMPLES / "FB_Delayed.TcPOU"])
    block = runtime.instantiate("FB_Delayed")
    block.call(enable=True)
    runtime.advance_time(milliseconds=999)
    block.call()
    assert block.output("ready") is False
    assert block.output("elapsed") == 999
    runtime.advance_time(milliseconds=1)
    block.call()
    assert block.output("ready") is True
    assert block.output("elapsed") == 1000


def test_all_three_timers_with_one_virtual_clock():
    runtime = Runtime.from_files([EXAMPLES / "timers.st"])
    block = runtime.instantiate("FB_Timers")
    block.call(signal=True)
    assert block.output("delayedOn") is False
    assert block.output("delayedOff") is True
    assert block.output("pulse") is True
    runtime.advance_time(50)
    block.call()
    assert block.output("pulse") is False
    assert block.output("delayedOn") is False
    runtime.advance_time(50)
    block.call()
    assert block.output("delayedOn") is True
    block.call(signal=False)
    assert block.output("delayedOn") is False
    assert block.output("delayedOff") is True
    runtime.advance_time(199)
    block.call()
    assert block.output("delayedOff") is True
    runtime.advance_time(1)
    block.call()
    assert block.output("delayedOff") is False
    assert block.output("offElapsed") == 200


def test_time_function_uses_milliseconds_at_python_boundary():
    runtime = Runtime.from_files([EXAMPLES / "timers.st"])
    assert runtime.call("F_AddDelay", base=1000).value == 1250


def test_builtin_timer_can_be_used_directly_without_st_wrapper():
    runtime = Runtime.from_source("")
    pulse = runtime.instantiate("TP")
    pulse.call(IN=True, PT=60000)
    assert pulse.output("Q") is True
    runtime.advance_time(milliseconds=60000)
    pulse.call()
    assert pulse.output("Q") is False
    assert pulse.output("ET") == 60000
