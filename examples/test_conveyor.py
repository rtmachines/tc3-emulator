"""Conveyor PLC scans with simulated I/O and no elapsed wall-clock waiting."""

from pathlib import Path

from tc_emulator import Runtime

SOURCES = Path(__file__).with_name("conveyor")


def conveyor():
    # Deliberately load the consumer before its GVL definitions.
    return Runtime.from_files(
        [SOURCES / "MAIN.TcPOU", SOURCES / "GVL_IO.TcGVL", SOURCES / "GVL_Config.TcGVL"]
    )


def test_conveyor_latches_start_and_waits_for_virtual_delay():
    runtime = conveyor()
    start = runtime.global_cell("GVL_IO", "start")
    running = runtime.global_cell("GVL_IO", "motorRunning")
    start.value = True
    runtime.scan("MAIN")
    assert running.value is False
    assert runtime.global_cell("GVL_IO", "alarm").value == "Starting"
    start.value = False
    runtime.advance_time(milliseconds=999)
    runtime.scan("MAIN")
    assert running.value is False
    runtime.advance_time(milliseconds=1)
    runtime.scan("MAIN")
    assert running.value is True
    assert runtime.global_cell("GVL_IO", "alarm").value == ""


def test_conveyor_cycles_execute_before_advancing_time():
    runtime = conveyor()
    runtime.global_cell("GVL_IO", "start").value = True
    runtime.run_cycles("MAIN", cycles=100, period_ms=10)
    assert runtime.now_ms == 1000
    assert runtime.global_cell("GVL_IO", "motorRunning").value is False
    runtime.scan("MAIN")
    assert runtime.now_ms == 1000
    assert runtime.global_cell("GVL_IO", "motorRunning").value is True


def test_open_guard_stops_motor_and_requires_a_new_start_command():
    runtime = conveyor()
    start = runtime.global_cell("GVL_IO", "start")
    guard = runtime.global_cell("GVL_IO", "guardClosed")
    running = runtime.global_cell("GVL_IO", "motorRunning")
    start.value = True
    runtime.run_cycles("MAIN", cycles=101, period_ms=10)
    assert running.value is True
    start.value = False
    guard.value = False
    runtime.scan("MAIN")
    assert running.value is False
    assert runtime.global_cell("GVL_IO", "alarm").value == "Guard open"
    guard.value = True
    runtime.run_cycles("MAIN", cycles=200, period_ms=10)
    assert running.value is False
    start.value = True
    runtime.scan("MAIN")
    assert running.value is False
    runtime.advance_time(milliseconds=1000)
    runtime.scan("MAIN")
    assert running.value is True


def test_stop_has_priority_over_start_and_counting_uses_sensor_edges():
    runtime = conveyor()
    start = runtime.global_cell("GVL_IO", "start")
    stop = runtime.global_cell("GVL_IO", "stop")
    sensor = runtime.global_cell("GVL_IO", "productSensor")
    count = runtime.global_cell("GVL_IO", "productCount")
    start.value = True
    stop.value = True
    runtime.run_cycles("MAIN", cycles=101, period_ms=10)
    assert runtime.global_cell("GVL_IO", "motorRunning").value is False
    assert runtime.global_cell("GVL_IO", "alarm").value == "Stopped"
    stop.value = False
    runtime.run_cycles("MAIN", cycles=101, period_ms=10)
    sensor.value = True
    runtime.scan("MAIN")
    runtime.run_cycles("MAIN", cycles=10, period_ms=10)
    assert count.value == 1
    sensor.value = False
    runtime.scan("MAIN")
    sensor.value = True
    runtime.scan("MAIN")
    assert count.value == 2
    runtime.global_cell("GVL_IO", "resetCount").value = True
    runtime.scan("MAIN")
    assert count.value == 0


def test_separate_conveyor_runtimes_have_independent_io_state_and_clock():
    first, second = conveyor(), conveyor()
    first.global_cell("GVL_IO", "start").value = True
    first.run_cycles("MAIN", cycles=101, period_ms=10)
    assert first.global_cell("GVL_IO", "motorRunning").value is True
    assert second.global_cell("GVL_IO", "motorRunning").value is False
    assert second.now_ms == 0
