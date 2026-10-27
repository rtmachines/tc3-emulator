"""Timer traces use explicit virtual time and exercise real FB instances."""

import pytest

from tc_emulator import ArgumentError, ExecutionError, Runtime, RuntimeFaultedError


def timer(kind):
    runtime = Runtime.from_source("")
    return runtime, runtime.instantiate(kind)


def outputs(block):
    return block.output("Q"), block.output("ET")


def test_clock_is_explicit_monotonic_and_separate_for_each_runtime():
    first, second = Runtime.from_source(""), Runtime.from_source("")
    assert first.now_ms == second.now_ms == 0
    assert first.advance_time(milliseconds=250) == 250
    assert first.advance_time(0) == 250
    assert first.now_ms == 250 and second.now_ms == 0
    with pytest.raises(AttributeError):
        first.now_ms = 1


@pytest.mark.parametrize("invalid", [-1, True, False, 0.5, "100", None])
def test_invalid_clock_update_is_atomic_and_does_not_fault(invalid):
    runtime = Runtime.from_source("")
    runtime.advance_time(10)
    with pytest.raises(ArgumentError):
        runtime.advance_time(invalid)
    assert runtime.now_ms == 10
    assert runtime.advance_time(2) == 12


def test_ton_exact_deadline_saturation_reset_and_no_implicit_scan():
    runtime, block = timer("ton")
    block.call(IN=False, PT=1000)
    assert outputs(block) == (False, 0)
    block.call(IN=True)
    runtime.advance_time(999)
    assert outputs(block) == (False, 0)
    block.call()
    assert outputs(block) == (False, 999)
    runtime.advance_time(1)
    assert outputs(block) == (False, 999)
    block.call()
    assert outputs(block) == (True, 1000)
    runtime.advance_time(5000)
    block.call()
    assert outputs(block) == (True, 1000)
    block.call(IN=False)
    assert outputs(block) == (False, 0)
    block.call(IN=True)
    assert outputs(block) == (False, 0)


def test_ton_falling_input_cancels_unfinished_interval():
    runtime, block = timer("TON")
    block.call(IN=True, PT=100)
    runtime.advance_time(99)
    block.call(IN=False)
    runtime.advance_time(1000)
    block.call(IN=True)
    assert outputs(block) == (False, 0)
    runtime.advance_time(1)
    block.call()
    assert outputs(block) == (False, 1)


def test_tof_initial_false_does_not_start_and_falling_edge_delays_off():
    runtime, block = timer("TOF")
    block.call(IN=False, PT=1000)
    runtime.advance_time(5000)
    block.call()
    assert outputs(block) == (False, 0)
    block.call(IN=True)
    assert outputs(block) == (True, 0)
    block.call(IN=False)
    assert outputs(block) == (True, 0)
    runtime.advance_time(999)
    block.call()
    assert outputs(block) == (True, 999)
    runtime.advance_time(1)
    block.call()
    assert outputs(block) == (False, 1000)
    runtime.advance_time(9000)
    block.call()
    assert outputs(block) == (False, 1000)


def test_tof_rising_input_cancels_delay_and_next_fall_restarts():
    runtime, block = timer("TOF")
    block.call(IN=True, PT=100)
    block.call(IN=False)
    runtime.advance_time(99)
    block.call(IN=True)
    assert outputs(block) == (True, 0)
    runtime.advance_time(1000)
    block.call(IN=False)
    assert outputs(block) == (True, 0)
    runtime.advance_time(100)
    block.call()
    assert outputs(block) == (False, 100)


def test_tp_ignores_edges_during_pulse_and_waits_for_false_after_expiry():
    runtime, block = timer("TP")
    block.call(IN=True, PT=1000)
    assert outputs(block) == (True, 0)
    runtime.advance_time(300)
    block.call(IN=False)
    assert outputs(block) == (True, 300)
    runtime.advance_time(300)
    block.call(IN=True)
    assert outputs(block) == (True, 600)
    runtime.advance_time(400)
    block.call()
    assert outputs(block) == (False, 1000)
    runtime.advance_time(100)
    block.call()
    assert outputs(block) == (False, 1000)
    block.call(IN=False)
    assert outputs(block) == (False, 0)
    block.call(IN=True)
    assert outputs(block) == (True, 0)


def test_tp_rising_edge_on_expiry_call_does_not_retrigger():
    runtime, block = timer("TP")
    block.call(IN=True, PT=10)
    runtime.advance_time(5)
    block.call(IN=False)
    runtime.advance_time(5)
    block.call(IN=True)
    assert outputs(block) == (False, 10)
    block.call(IN=False)
    block.call(IN=True)
    assert outputs(block) == (True, 0)


def test_tp_expires_with_false_input_and_rearms_on_that_call():
    runtime, block = timer("TP")
    block.call(IN=True, PT=10)
    runtime.advance_time(100)
    block.call(IN=False)
    assert outputs(block) == (False, 0)
    block.call(IN=True)
    assert outputs(block) == (True, 0)


@pytest.mark.parametrize("kind", ["TON", "TOF", "TP"])
def test_timer_latches_preset_until_next_interval(kind):
    runtime, block = timer(kind)
    block.call(IN=True, PT=100)
    if kind == "TOF":
        block.call(IN=False)
    runtime.advance_time(50)
    block.call(PT=200)
    assert block.output("ET") == 50
    runtime.advance_time(50)
    block.call(PT=300)
    assert outputs(block) == (kind == "TON", 100)
    if kind == "TOF":
        block.call(IN=True)
        block.call(IN=False)
    else:
        block.call(IN=False)
        block.call(IN=True)
    runtime.advance_time(299)
    block.call()
    assert outputs(block) == (kind != "TON", 299)
    runtime.advance_time(1)
    block.call()
    assert outputs(block) == (kind == "TON", 300)


@pytest.mark.parametrize("kind", ["TON", "TOF", "TP"])
def test_zero_preset_and_repeated_calls_without_advancing_time(kind):
    runtime, block = timer(kind)
    block.call(IN=True, PT=0)
    assert outputs(block) == (kind != "TP", 0)
    block.call(IN=False)
    assert outputs(block) == (False, 0)
    block.call(IN=True, PT=10)
    for _ in range(3):
        block.call()
    assert outputs(block) == (kind != "TON", 0)
    assert runtime.now_ms == 0


def test_clock_does_not_wrap_and_timers_saturate_after_large_jump():
    runtime, block = timer("TON")
    runtime.advance_time(2**32 + 100)
    block.call(IN=True, PT=2**32 - 1)
    runtime.advance_time(2**64)
    block.call()
    assert outputs(block) == (True, 4294967295)
    assert runtime.now_ms == 2**64 + 2**32 + 100


def test_timer_instances_are_independent_and_unsampled_input_does_not_trigger():
    runtime, first = timer("TON")
    second = runtime.instantiate("TON")
    first.call(IN=True, PT=100)
    second.set_input("IN", True)
    second.set_input("PT", 100)
    runtime.advance_time(100)
    first.call()
    second.call()
    assert outputs(first) == (True, 100)
    assert outputs(second) == (False, 0)


@pytest.mark.parametrize("invalid", [-1, 4294967296, True, 1.0, "T#1s"])
def test_invalid_timer_arguments_do_not_update_inputs_or_start_timer(invalid):
    runtime, block = timer("TON")
    with pytest.raises(ArgumentError):
        block.call(IN=True, PT=invalid)
    assert block.inspect() == {"IN": False, "PT": 0, "Q": False, "ET": 0}
    runtime.advance_time(500)
    block.call(PT=100)
    assert outputs(block) == (False, 0)
    block.call(IN=True)
    assert outputs(block) == (False, 0)


def test_faulted_runtime_rejects_clock_changes_but_remains_inspectable():
    runtime = Runtime.from_source("FUNCTION F:INT F:=1/0; END_FUNCTION")
    runtime.advance_time(123)
    with pytest.raises(ExecutionError):
        runtime.call("F")
    with pytest.raises(RuntimeFaultedError):
        runtime.advance_time(1)
    assert runtime.now_ms == 123
