"""The same conveyor tested through public methods and deterministic PLC scans."""

from pathlib import Path

import pytest

from tc_emulator import ArgumentError, Runtime

SOURCES = Path(__file__).with_name("conveyor")


def conveyor_methods():
    return Runtime.from_files(
        [
            SOURCES / "MAIN_Methods.TcPOU",
            SOURCES / "FB_Conveyor.TcPOU",
            SOURCES / "GVL_IO.TcGVL",
            SOURCES / "GVL_Config.TcGVL",
        ]
    )


def test_public_methods_start_only_after_virtual_delay():
    runtime = conveyor_methods()
    controller = runtime.instantiate("FB_Conveyor")
    assert controller.call_method("Start", delay=250).value is None
    controller.call_method("Update", guardClosed=True)
    assert controller.output("alarm") == "Starting"
    runtime.advance_time(249)
    controller.call_method("Update", guardClosed=True)
    assert controller.call_method("IsRunning").value is False
    runtime.advance_time(1)
    controller.call_method("Update", guardClosed=True)
    assert controller.call_method("IsRunning").value is True
    assert runtime.now_ms == 250
    controller.call_method("Stop")
    assert controller.call_method("IsRunning").value is False


def test_method_default_input_and_instance_timers_are_independent():
    runtime = conveyor_methods()
    first, second = runtime.instantiate("FB_Conveyor"), runtime.instantiate("FB_Conveyor")
    first.call_method("Start", delay=10)
    first.call_method("Update", guardClosed=True)
    second.call_method("Start")
    second.call_method("Update", guardClosed=True)
    runtime.advance_time(10)
    first.call_method("Update", guardClosed=True)
    second.call_method("Update", guardClosed=True)
    assert first.call_method("IsRunning").value is True
    assert second.call_method("IsRunning").value is False
    runtime.advance_time(990)
    second.call_method("Update", guardClosed=True)
    assert second.call_method("IsRunning").value is True


def test_private_helper_counts_edges_and_reset_preserves_running_state():
    runtime = conveyor_methods()
    controller = runtime.instantiate("FB_Conveyor")
    controller.call_method("Start", delay=0)
    controller.call_method("Update", guardClosed=True, sensor=True)
    controller.call_method("Update", guardClosed=True, sensor=True)
    assert controller.output("productCount") == 1
    with pytest.raises(ArgumentError, match="(?i)private"):
        controller.call_method("CountProduct", sensor=False)
    assert controller.call_method("IsRunning").value is True
    controller.call_method("Update", guardClosed=True, sensor=False)
    controller.call_method("Update", guardClosed=True, sensor=True)
    assert controller.output("productCount") == 2
    controller.call_method("Reset")
    assert controller.output("productCount") == 0
    assert controller.call_method("IsRunning").value is True


def test_method_program_uses_existing_gvl_and_scan_clock():
    runtime = conveyor_methods()
    start = runtime.global_cell("GVL_IO", "start")
    running = runtime.global_cell("GVL_IO", "motorRunning")
    start.value = True
    runtime.scan("MAIN_Methods")
    start.value = False
    assert running.value is False
    runtime.run_cycles("MAIN_Methods", cycles=100, period_ms=10)
    assert running.value is False
    runtime.scan("MAIN_Methods")
    assert running.value is True
    sensor = runtime.global_cell("GVL_IO", "productSensor")
    sensor.value = True
    runtime.scan("MAIN_Methods")
    runtime.scan("MAIN_Methods")
    assert runtime.global_cell("GVL_IO", "productCount").value == 1
    runtime.global_cell("GVL_IO", "resetCount").value = True
    runtime.scan("MAIN_Methods")
    assert runtime.global_cell("GVL_IO", "productCount").value == 0


@pytest.mark.parametrize("interlock", ["stop", "guardClosed"])
def test_method_program_interlock_wins_and_requires_new_start(interlock):
    runtime = conveyor_methods()
    start = runtime.global_cell("GVL_IO", "start")
    switch = runtime.global_cell("GVL_IO", interlock)
    running = runtime.global_cell("GVL_IO", "motorRunning")
    start.value = True
    runtime.run_cycles("MAIN_Methods", cycles=101, period_ms=10)
    assert running.value is True
    switch.value = interlock == "stop"
    runtime.scan("MAIN_Methods")
    assert running.value is False
    assert runtime.global_cell("GVL_IO", "alarm").value == (
        "Stopped" if interlock == "stop" else "Guard open"
    )
    start.value = False
    switch.value = interlock != "stop"
    runtime.run_cycles("MAIN_Methods", cycles=101, period_ms=10)
    assert running.value is False
    start.value = True
    runtime.scan("MAIN_Methods")
    start.value = False
    runtime.advance_time(1000)
    runtime.scan("MAIN_Methods")
    assert running.value is True
