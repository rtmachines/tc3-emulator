"""Property-based configuration and method-owned state in three conveyors."""

from pathlib import Path

import pytest

from tc_emulator import ArgumentError, Runtime

SOURCES = Path(__file__).parent / "conveyor_properties"


def conveyor_line():
    return Runtime.from_files(sorted(SOURCES.glob("*.TcPOU")) + sorted(SOURCES.glob("*.TcGVL")))


def start_all(runtime):
    runtime.global_cell("GVL_Line", "start").value = [True, True, True]
    runtime.scan("MAIN_Line")
    runtime.global_cell("GVL_Line", "start").value = [False, False, False]


def test_python_properties_configure_one_existing_conveyor_and_clamp_speed():
    runtime = conveyor_line()
    first = runtime.program_fb("MAIN_Line", "conveyors", 1)
    second = runtime.program_fb("MAIN_Line", "conveyors", 2)
    second.set_property("speedsetpoint", 0.75)
    assert second.get_property("SpeedSetpoint") == 0.75
    assert first.get_property("SpeedSetpoint") == 0.5
    second.set_property("SpeedSetpoint", 4.0)
    assert second.get_property("SpeedSetpoint") == 1.0
    second.set_property("SpeedSetpoint", -0.5)
    assert second.get_property("SpeedSetpoint") == 0.0
    with pytest.raises(ArgumentError):
        second.set_property("SpeedSetpoint", "fast")
    with pytest.raises(ArgumentError):
        second.set_property("Running", True)
    assert second.get_property("Running") is False
    assert second.get_property("SpeedSetpoint") == 0.0


def test_indexed_st_property_writes_feed_running_conveyors():
    runtime = conveyor_line()
    runtime.global_cell("GVL_Line", "applySpeed").value = [True, True, True]
    runtime.global_cell("GVL_Line", "speedCommand").value = [0.25, 0.75, 2.0]
    start_all(runtime)
    assert runtime.global_cell("GVL_Line", "actualSpeed").value == (0.0, 0.0, 0.0)
    runtime.global_cell("GVL_Line", "applySpeed").value = [False, False, False]
    runtime.advance_time(500)
    runtime.scan("MAIN_Line")
    assert runtime.global_cell("GVL_Line", "actualSpeed").value == (0.25, 0.75, 1.0)
    runtime.program_fb("MAIN_Line", "conveyors", 2).set_property("SpeedSetpoint", 0.4)
    runtime.scan("MAIN_Line")
    assert runtime.global_cell("GVL_Line", "actualSpeed").value == (0.25, 0.4, 1.0)


def test_method_instance_timers_survive_cycles_with_independent_delays():
    runtime = conveyor_line()
    start_all(runtime)
    runtime.run_cycles("MAIN_Line", cycles=10, period_ms=10)
    assert runtime.now_ms == 100
    assert runtime.global_cell("GVL_Line", "running").value == (False, False, False)
    runtime.scan("MAIN_Line")
    assert runtime.global_cell("GVL_Line", "running").value == (True, False, False)
    runtime.advance_time(150)
    runtime.scan("MAIN_Line")
    assert runtime.global_cell("GVL_Line", "running").value == (True, True, False)
    runtime.advance_time(250)
    runtime.scan("MAIN_Line")
    assert runtime.global_cell("GVL_Line", "running").value == (True, True, True)
    assert runtime.global_cell("GVL_Line", "updateCount").value == (14, 14, 14)
    second = runtime.program_fb("MAIN_Line", "conveyors", 2)
    assert second.call_method("Update", guardClosed=True).value == 15
    runtime.scan("MAIN_Line")
    assert runtime.global_cell("GVL_Line", "updateCount").value == (15, 16, 15)


def test_stop_and_restart_reset_only_the_selected_method_timer():
    runtime = conveyor_line()
    start_all(runtime)
    runtime.advance_time(500)
    runtime.scan("MAIN_Line")
    runtime.global_cell("GVL_Line", "guardClosed").element(2).value = False
    runtime.scan("MAIN_Line")
    assert runtime.global_cell("GVL_Line", "running").value == (True, False, True)
    second = runtime.program_fb("MAIN_Line", "conveyors", 2)
    assert second.get_property("Alarm") == "Guard open"
    assert second.get_property("ActiveSpeed") == 0.0
    runtime.global_cell("GVL_Line", "guardClosed").element(2).value = True
    second.call_method("Start", delay=250)
    runtime.scan("MAIN_Line")
    runtime.advance_time(249)
    runtime.scan("MAIN_Line")
    assert second.get_property("Running") is False
    runtime.advance_time(1)
    runtime.scan("MAIN_Line")
    assert second.get_property("Running") is True


def test_method_instance_edges_and_counters_are_independent():
    runtime = conveyor_line()
    start_all(runtime)
    runtime.advance_time(500)
    sensors = runtime.global_cell("GVL_Line", "productSensor")
    sensors.value = [True, True, True]
    runtime.scan("MAIN_Line")
    runtime.scan("MAIN_Line")
    assert runtime.global_cell("GVL_Line", "productCount").value == (1, 1, 1)
    sensors.element(2).value = False
    runtime.scan("MAIN_Line")
    sensors.element(2).value = True
    runtime.scan("MAIN_Line")
    assert runtime.global_cell("GVL_Line", "productCount").value == (1, 2, 1)
    second = runtime.program_fb("MAIN_Line", "conveyors", 2)
    second.call_method("Reset")
    runtime.scan("MAIN_Line")
    assert second.get_property("ProductCount") == 0
    assert runtime.global_cell("GVL_Line", "productCount").value == (1, 0, 1)
