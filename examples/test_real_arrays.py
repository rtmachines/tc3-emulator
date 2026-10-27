"""Runnable REAL/LREAL and fixed-array examples; no TwinCAT required."""

from pathlib import Path

import pytest

from tc_emulator import Runtime

EXAMPLES = Path(__file__).resolve().parent


@pytest.fixture
def runtime():
    return Runtime.from_files([EXAMPLES / "real_arrays.st", EXAMPLES / "FB_Samples.TcPOU"])


def test_mean_lreal(runtime):
    assert runtime.call("F_Mean", samples=[1.0, 2.0, 3.0, 4.0]).value == 2.5
    assert runtime.call("F_Mean", samples=[16777217] * 4).value == 16777217.0


def test_multidimensional_array(runtime):
    assert runtime.call("F_Trace", matrix=[[1.5, 2.0], [3.0, 4.5]]).value == 6.0


def test_array_inout(runtime):
    values = runtime.cell("ARRAY[-1..1] OF REAL", [1.0, 2.0, 3.0])
    assert runtime.call("F_Scale", values=values, factor=0.5).value is True
    assert values.value == (0.5, 1.0, 1.5)
    values.element(-1).value = 10.0  # Index -1 is the first declared ST element.
    assert values.value == (10.0, 1.0, 1.5)


def test_fb_stores_independent_real_arrays(runtime):
    first, second = runtime.instantiate("FB_Samples"), runtime.instantiate("FB_Samples")
    first.call(write=True, index=1, value=16777217)
    first.call(write=True, index=2, value=0.1)
    assert first.output("values") == (16777216.0, 0.10000000149011612, 0.0)
    assert second.output("values") == (0.0, 0.0, 0.0)
