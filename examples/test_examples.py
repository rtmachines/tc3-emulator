"""Run with: python -m pytest examples -q."""

from pathlib import Path

import pytest

from tc_emulator import Runtime

EXAMPLES = Path(__file__).resolve().parent


@pytest.fixture
def runtime():
    return Runtime.from_files([EXAMPLES / "functions.st", EXAMPLES / "FB_Counter.TcPOU"])


def test_add(runtime):
    assert runtime.call("F_Add", a=2, b=3).value == 5


def test_counter(runtime):
    counter = runtime.instantiate("FB_Counter")
    counter.call(enable=True)
    counter.call()  # Pominięte wejście zachowuje wartość TRUE.
    assert counter.output("count") == 2
    other = runtime.instantiate("FB_Counter")
    assert other.output("count") == 0


def test_reference(runtime):
    value = runtime.cell("DINT", 10)
    runtime.call("F_Increment", value=value)
    assert value.value == 11
