"""Native heterogeneous conveyors bound before the first scan."""

from pathlib import Path

import pytest

from tc_emulator import ArgumentError, Runtime

SOURCES = Path(__file__).parent / "conveyor_collections"


def conveyor_line():
    return Runtime.from_files(sorted(SOURCES.glob("*.Tc*"), reverse=True))


def values(rt, name):
    return rt.global_cell("GVL_Line", name).value


def running_line():
    rt = conveyor_line()
    rt.program_fb("MAIN_Line", "line").call_method("Start")
    rt.scan("MAIN_Line")
    rt.advance_time(500)
    rt.scan("MAIN_Line")
    return rt


def test_pre_scan_bindings_and_independent_delays():
    rt = conveyor_line()
    line = rt.program_fb("MAIN_Line", "line")
    assert [s["target"] for s in line.inspect()["DEVICES"]] == [
        "FB_STANDARDCONVEYOR",
        "FB_REVERSIBLECONVEYOR",
        "FB_JAMCONVEYOR",
    ]
    for name in ("standard", "reversible", "jam"):
        device = rt.program_fb("MAIN_Line", name)
        assert device.output("initCount") == 1
        assert device.output("cycleCount") == 0
        assert device.get_property("Running") is False
        assert device.fb("startup").inspect() == {"IN": False, "PT": 0, "Q": False, "ET": 0}
    line.call_method("Start")
    rt.scan("MAIN_Line")
    assert values(rt, "running") == (False, False, False)
    for elapsed, expected in (
        (100, (True, False, False)),
        (150, (True, True, False)),
        (250, (True, True, True)),
    ):
        rt.advance_time(elapsed)
        rt.scan("MAIN_Line")
        assert values(rt, "running") == expected
    assert values(rt, "actualSpeed") == pytest.approx((0.5, -0.75, 0.6))


def test_edges_stop_and_latched_jam_recovery():
    rt = running_line()
    sensor = rt.global_cell("GVL_Line", "sensor")
    sensor.value = (True, True, True)
    rt.scan("MAIN_Line")
    rt.scan("MAIN_Line")
    sensor.element(2).value = False
    rt.scan("MAIN_Line")
    sensor.element(2).value = True
    rt.scan("MAIN_Line")
    assert values(rt, "productCount") == (1, 2, 1)
    rt.global_cell("GVL_Line", "blocked").value = (True, True, True)
    rt.scan("MAIN_Line")
    rt.advance_time(299)
    rt.scan("MAIN_Line")
    assert values(rt, "running") == (True, True, True)
    rt.advance_time(1)
    rt.scan("MAIN_Line")
    assert values(rt, "running") == (True, True, False)
    assert values(rt, "alarm") == ("", "", "Jammed")
    rt.global_cell("GVL_Line", "blocked").value = (False, False, False)
    rt.scan("MAIN_Line")
    rt.advance_time(1000)
    rt.scan("MAIN_Line")
    assert values(rt, "running") == (True, True, False)
    line = rt.program_fb("MAIN_Line", "line")
    line.call_method("Reset")
    line.call_method("Start")
    rt.scan("MAIN_Line")
    rt.advance_time(499)
    rt.scan("MAIN_Line")
    assert values(rt, "running") == (True, True, False)
    rt.advance_time(1)
    rt.scan("MAIN_Line")
    assert values(rt, "running") == (True, True, True)
    line.call_method("Stop")
    rt.scan("MAIN_Line")
    assert values(rt, "running") == (False, False, False)


def test_rebind_preserves_state_and_rejects_foreign_handles():
    rt = running_line()
    line = rt.program_fb("MAIN_Line", "line")
    old = rt.program_fb("MAIN_Line", "reversible")
    replacement = rt.instantiate("FB_StandardConveyor", init={"startDelay": 0})
    replacement.set_property("SpeedSetpoint", 0.9)
    replacement.call_method("Start")
    replacement.call_method("Cycle", enabled=True, sensor=True, blocked=False)
    assert replacement.get_property("ProductCount") == 1
    before = replacement.inspect()
    old_before = old.inspect()
    line.call_method("Bind", index=2, target=replacement)
    assert replacement.inspect() == before
    assert old.inspect() == old_before
    rt.scan("MAIN_Line")
    assert old.inspect() == old_before
    assert replacement.output("initCount") == 1
    assert replacement.output("cycleCount") == before["CYCLECOUNT"] + 1
    assert values(rt, "actualSpeed") == pytest.approx((0.5, 0.9, 0.6))
    before = line.inspect()
    state = replacement.inspect()
    foreign = conveyor_line().instantiate("FB_StandardConveyor", init={"startDelay": 0})
    with pytest.raises(ArgumentError):
        line.call_method("Bind", index=2, target=foreign)
    assert line.inspect() == before
    assert replacement.inspect() == state
    rt.scan("MAIN_Line")
    line.call_method("Bind", index=2, target=0)
    for method in ("Start", "Stop", "Reset"):
        line.call_method(method)
    rt.scan("MAIN_Line")
    assert values(rt, "running")[1] is False
    assert values(rt, "actualSpeed")[1] == 0.0
    assert values(rt, "productCount")[1] == 0
    assert values(rt, "alarm")[1] == "Not bound"
