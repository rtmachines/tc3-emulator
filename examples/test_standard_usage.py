"""Run standard PLC logic in pytest without a TwinCAT installation or waiting."""

from pathlib import Path

from tc_emulator import Runtime

SOURCE = Path(__file__).with_name("standard.st")


def test_batch_counter_latch_and_virtual_timer():
    runtime = Runtime.from_files([SOURCE])
    batch = runtime.instantiate("FB_Batch")
    batch.call(sensor=False, config={"target": 2, "releaseDelay": 1000, "speed": 12.5})
    for expected in (1, 2):
        batch.call(sensor=True)
        assert batch.output("count") == expected
        batch.call()  # A maintained signal does not count twice.
        assert batch.output("count") == expected
        batch.call(sensor=False)
    assert batch.output("targetReached") is True
    assert batch.output("release") is False
    assert batch.output("speedCommand") == 12
    runtime.advance_time(999)
    batch.call()
    assert batch.output("release") is False
    runtime.advance_time(1)
    batch.call()
    assert batch.output("release") is True
    batch.call(reset=True)
    assert batch.output("count") == 0
    assert batch.output("targetReached") is False
    assert batch.output("release") is False


def test_constants_define_array_bounds_and_initialize_values():
    runtime = Runtime.from_files([SOURCE])
    assert runtime.call("F_ConstantTable").value == 24


def test_selector_does_not_evaluate_a_division_by_zero():
    runtime = Runtime.from_files([SOURCE])
    assert runtime.call("F_SafeRatio", numerator=10.0, denominator=0.0).value == 0.0
    assert runtime.call("F_SafeRatio", numerator=10.0, denominator=4.0).value == 2.5


def test_standalone_latch_and_down_counter():
    runtime = Runtime.from_source("")
    latch = runtime.instantiate("SR")
    latch.call(SET1=True, RESET=True)
    assert latch.output("Q1") is True  # SET1 dominates RESET.
    counter = runtime.instantiate("CTD")
    counter.call(LOAD=True, PV=1)
    counter.call(LOAD=False, CD=True)
    assert counter.output("CV") == 0
    assert counter.output("Q") is True
