"""Three independent conveyors, indexed ST methods and open-array aggregation."""

from pathlib import Path

import pytest

from tc_emulator import ArgumentError, Runtime

EXAMPLES = Path(__file__).parent
SOURCES = EXAMPLES / "conveyor_line"


def conveyor_line():
    return Runtime.from_files(
        [
            SOURCES / "MAIN_Line.TcPOU",
            SOURCES / "GVL_Line.TcGVL",
            SOURCES / "F_Total.TcPOU",
            EXAMPLES / "conveyor" / "FB_Conveyor.TcPOU",
        ]
    )


def start_all(runtime):
    start = runtime.global_cell("GVL_Line", "start")
    start.value = [True, True, True]
    runtime.scan("MAIN_Line")
    start.value = [False, False, False]


def test_three_conveyors_have_independent_delays_on_one_virtual_clock():
    runtime = conveyor_line()
    running = runtime.global_cell("GVL_Line", "motorRunning")
    start_all(runtime)
    assert running.value == (False, False, False)
    runtime.run_cycles("MAIN_Line", cycles=10, period_ms=10)
    assert runtime.now_ms == 100
    assert running.value == (False, False, False)
    runtime.scan("MAIN_Line")
    assert running.value == (True, False, False)
    runtime.advance_time(149)
    runtime.scan("MAIN_Line")
    assert running.value == (True, False, False)
    runtime.advance_time(1)
    runtime.scan("MAIN_Line")
    assert running.value == (True, True, False)
    runtime.advance_time(250)
    runtime.scan("MAIN_Line")
    assert running.value == (True, True, True)


def test_python_handle_controls_the_existing_second_instance_used_by_program():
    runtime = conveyor_line()
    second = runtime.program_fb("MAIN_Line", "conveyors", 2)
    same_second = runtime.program_fb("main_line", "CONVEYORS", 2)
    second.call_method("Start", delay=50)
    runtime.scan("MAIN_Line")
    runtime.advance_time(50)
    runtime.scan("MAIN_Line")
    assert same_second.call_method("IsRunning").value is True
    assert runtime.global_cell("GVL_Line", "motorRunning").value == (False, True, False)
    same_second.call_method("Stop")
    assert second.call_method("IsRunning").value is False
    with pytest.raises(ArgumentError):
        runtime.program_fb("MAIN_Line", "conveyors", 0)
    runtime.scan("MAIN_Line")
    assert runtime.global_cell("GVL_Line", "motorRunning").value == (False, False, False)


@pytest.mark.parametrize("interlock", ["stop", "guardClosed"])
def test_one_conveyor_interlock_does_not_stop_others(interlock):
    runtime = conveyor_line()
    start_all(runtime)
    runtime.advance_time(500)
    runtime.scan("MAIN_Line")
    switch = runtime.global_cell("GVL_Line", interlock).element(2)
    runtime.global_cell("GVL_Line", "start").element(2).value = True
    switch.value = interlock == "stop"
    runtime.scan("MAIN_Line")
    assert runtime.global_cell("GVL_Line", "motorRunning").value == (True, False, True)
    assert runtime.global_cell("GVL_Line", "alarm").element(2).value == (
        "Stopped" if interlock == "stop" else "Guard open"
    )
    runtime.global_cell("GVL_Line", "start").element(2).value = False
    switch.value = interlock != "stop"
    runtime.run_cycles("MAIN_Line", cycles=100, period_ms=10)
    assert runtime.global_cell("GVL_Line", "motorRunning").value == (True, False, True)


def test_sensor_edges_and_reset_keep_independent_counts_and_update_total():
    runtime = conveyor_line()
    start_all(runtime)
    runtime.advance_time(500)
    sensors = runtime.global_cell("GVL_Line", "productSensor")
    counts = runtime.global_cell("GVL_Line", "productCount")
    total = runtime.global_cell("GVL_Line", "totalCount")
    sensors.value = [True, True, True]
    runtime.scan("MAIN_Line")
    runtime.scan("MAIN_Line")
    assert counts.value == (1, 1, 1)
    assert total.value == 3
    sensors.element(2).value = False
    runtime.scan("MAIN_Line")
    sensors.element(2).value = True
    runtime.scan("MAIN_Line")
    assert counts.value == (1, 2, 1)
    assert total.value == 4
    runtime.global_cell("GVL_Line", "resetCount").element(2).value = True
    runtime.scan("MAIN_Line")
    assert counts.value == (1, 0, 1)
    assert total.value == 2


def test_open_aggregation_uses_actual_bounds_of_python_cells():
    runtime = conveyor_line()
    counts = runtime.cell("ARRAY[-2..0] OF UDINT", [5, 8, 13])
    assert runtime.call("F_Total", counts=counts).value == 26
    counts.element(-1).value = 0
    assert runtime.call("F_Total", counts=counts).value == 18
    short = runtime.cell("ARRAY[7..7] OF UDINT", [9])
    assert runtime.call("F_Total", counts=short).value == 9
