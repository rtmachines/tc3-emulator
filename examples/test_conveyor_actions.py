"""Handwritten native-format actions control three independent conveyor lifecycles."""

from pathlib import Path

import pytest

from tc_emulator import Runtime

SOURCES = Path(__file__).parent / "conveyor_actions"
DELAYS = (100, 250, 500)


def conveyor_line():
    return Runtime.from_files(sorted(SOURCES.glob("*.Tc*"), reverse=True))


def set_input(rt, name, index, value):
    rt.global_cell("GVL_Line", name).element(index).value = value


def states(rt):
    return tuple(value.name for value in rt.global_cell("GVL_Line", "state").value)


def assert_initialized(rt):
    for index, delay in enumerate(DELAYS, 1):
        conveyor = rt.program_fb("MAIN_Line", "conveyors", index)
        assert conveyor.output("id") == index
        assert conveyor.inspect()["STARTDELAY"] == delay
        assert conveyor.get_property("SpeedFactor") == 1.0
        assert conveyor.output("ready") is True
        assert conveyor.output("initTrace") == 12345
        for count in ("baseInitCount", "derivedInitCount", "afterInitCount"):
            assert conveyor.output(count) == 1


def start_all(rt):
    for index in range(1, 4):
        set_input(rt, "start", index, True)
    rt.scan("MAIN_Line")


def test_initialization_and_exact_staged_start_deadlines():
    rt = conveyor_line()
    assert_initialized(rt)
    assert states(rt) == ("STOPPED",) * 3
    start_all(rt)
    assert states(rt) == ("STARTING",) * 3
    for elapsed, expected in (
        (99, (False, False, False)),
        (1, (True, False, False)),
        (149, (True, False, False)),
        (1, (True, True, False)),
        (249, (True, True, False)),
        (1, (True, True, True)),
    ):
        before = states(rt)
        rt.advance_time(elapsed)
        assert states(rt) == before  # advancing the clock does not execute ST
        rt.scan("MAIN_Line")
        assert states(rt) == tuple("RUNNING" if active else "STARTING" for active in expected)
        assert rt.global_cell("GVL_Line", "running").value == expected
        assert rt.global_cell("GVL_Line", "actualSpeed").value == tuple(
            0.75 if active else 0.0 for active in expected
        )
        assert rt.global_cell("GVL_Line", "alarm").value == (False,) * 3
    assert_initialized(rt)


@pytest.mark.parametrize("index,delay", tuple(enumerate(DELAYS, 1)))
def test_each_conveyor_faults_latches_clears_resets_and_restarts_independently(index, delay):
    rt = conveyor_line()
    start_all(rt)
    rt.advance_time(500)
    rt.scan("MAIN_Line")
    set_input(rt, "blocked", index, True)
    rt.scan("MAIN_Line")  # blockage begins at 500, separately from start timing
    rt.advance_time(299)
    rt.scan("MAIN_Line")
    assert states(rt) == ("RUNNING",) * 3
    rt.advance_time(1)
    rt.scan("MAIN_Line")
    expected = tuple("FAULT" if i == index else "RUNNING" for i in range(1, 4))
    assert states(rt) == expected
    assert rt.global_cell("GVL_Line", "alarm").value == tuple(i == index for i in range(1, 4))
    assert rt.global_cell("GVL_Line", "running").value == tuple(i != index for i in range(1, 4))
    assert rt.global_cell("GVL_Line", "actualSpeed").value == tuple(
        0.0 if i == index else 0.75 for i in range(1, 4)
    )
    set_input(rt, "reset", index, True)
    rt.scan("MAIN_Line")
    assert states(rt) == expected  # reset cannot bypass a blocked sensor
    set_input(rt, "reset", index, False)
    set_input(rt, "blocked", index, False)
    rt.scan("MAIN_Line")
    assert states(rt) == expected  # clearing the sensor alone cannot clear the alarm
    set_input(rt, "start", index, False)
    set_input(rt, "reset", index, True)
    rt.scan("MAIN_Line")
    assert states(rt)[index - 1] == "STOPPED"
    assert rt.global_cell("GVL_Line", "alarm").value == (False,) * 3
    conveyor = rt.program_fb("MAIN_Line", "conveyors", index)
    for timer_name in ("startTimer", "blockTimer"):
        timer = conveyor.fb(timer_name)
        assert (timer.output("Q"), timer.output("ET")) == (False, 0)
    set_input(rt, "reset", index, False)
    set_input(rt, "start", index, True)
    rt.scan("MAIN_Line")
    assert states(rt)[index - 1] == "STARTING"
    rt.advance_time(delay - 1)
    rt.scan("MAIN_Line")
    assert states(rt) == tuple("STARTING" if i == index else "RUNNING" for i in range(1, 4))
    rt.advance_time(1)
    rt.scan("MAIN_Line")
    assert rt.now_ms == 800 + delay
    assert states(rt) == ("RUNNING",) * 3
    assert rt.global_cell("GVL_Line", "actualSpeed").value == (0.75,) * 3
    assert_initialized(rt)


def test_interrupted_obstruction_restarts_the_timeout_instead_of_accumulating():
    rt = conveyor_line()
    start_all(rt)
    rt.advance_time(500)
    set_input(rt, "blocked", 1, True)
    rt.scan("MAIN_Line")
    rt.advance_time(299)
    set_input(rt, "blocked", 1, False)
    rt.scan("MAIN_Line")
    set_input(rt, "blocked", 1, True)
    rt.scan("MAIN_Line")
    rt.advance_time(299)
    rt.scan("MAIN_Line")
    assert states(rt) == ("RUNNING",) * 3
    rt.advance_time(1)
    rt.scan("MAIN_Line")
    assert rt.now_ms == 1099
    assert states(rt) == ("FAULT", "RUNNING", "RUNNING")
    assert_initialized(rt)


def test_program_action_phases_and_inherited_action_api_run_only_selected_bodies():
    rt = conveyor_line()
    for index in range(1, 4):
        set_input(rt, "start", index, True)
    rt.call_action("MAIN_Line", "ReadInputs")
    first = rt.program_fb("MAIN_Line", "conveyors", 1)
    assert first.output("state").name == "STOPPED"
    rt.call_action("MAIN_Line", "ControlConveyors")
    assert first.output("state").name == "STARTING"
    assert states(rt) == ("STOPPED",) * 3
    rt.call_action("MAIN_Line", "WriteOutputs")
    assert states(rt) == ("STARTING",) * 3
    rt.advance_time(100)
    rt.call_action("MAIN_Line", "ControlConveyors")
    rt.call_action("MAIN_Line", "WriteOutputs")
    assert states(rt) == ("RUNNING", "STARTING", "STARTING")
    assert first.output("derivedActionCount") == 2  # dispatch from base FB body
    first.call_action("UpdateOutputs")
    assert first.output("derivedActionCount") == 3
    assert first.output("running") is True  # SUPER action computes base outputs
    assert first.output("actualSpeed") == 0.75
    assert first.fb("startTimer").output("ET") == 100
    assert_initialized(rt)


def test_shared_config_disable_stops_then_restarts_delays_without_reinitialization():
    rt = conveyor_line()
    start_all(rt)
    rt.advance_time(500)
    rt.scan("MAIN_Line")
    config = rt.global_cell("GVL_Line", "config")
    config.field("speed").value = 0.4
    rt.scan("MAIN_Line")
    assert rt.global_cell("GVL_Line", "actualSpeed").value == (0.4,) * 3
    config.field("enabled").value = False
    rt.scan("MAIN_Line")
    assert states(rt) == ("STOPPED",) * 3
    assert rt.global_cell("GVL_Line", "actualSpeed").value == (0.0,) * 3
    rt.advance_time(1000)
    config.field("enabled").value = True
    rt.scan("MAIN_Line")
    assert states(rt) == ("STARTING",) * 3
    rt.advance_time(100)
    rt.scan("MAIN_Line")
    assert states(rt) == ("RUNNING", "STARTING", "STARTING")
    assert_initialized(rt)
