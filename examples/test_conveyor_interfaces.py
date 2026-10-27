"""Three conveyors with interface-bound motors and a Python-controlled fake."""

from pathlib import Path

import pytest

from tc_emulator import ArgumentError, Runtime

SOURCES = Path(__file__).parent / "conveyor_interfaces"


def conveyor_line():
    return Runtime.from_files(sorted(SOURCES.glob("*.Tc*"), reverse=True))


def start_all(runtime):
    runtime.global_cell("GVL_Line", "start").value = [True, True, True]
    runtime.scan("MAIN_Line")
    runtime.global_cell("GVL_Line", "start").value = [False, False, False]


def test_three_interface_bound_motors_keep_independent_virtual_delays():
    rt = conveyor_line()
    start_all(rt)
    running = rt.global_cell("GVL_Line", "running")
    assert running.value == (False, False, False)
    rt.run_cycles("MAIN_Line", cycles=10, period_ms=10)
    assert rt.now_ms == 100
    rt.scan("MAIN_Line")
    assert running.value == (True, False, False)
    rt.advance_time(150)
    rt.scan("MAIN_Line")
    assert running.value == (True, True, False)
    rt.advance_time(250)
    rt.scan("MAIN_Line")
    assert running.value == (True, True, True)
    assert rt.global_cell("GVL_Line", "actualSpeed").value == (0.5, 0.5, 0.5)


def test_python_fake_fault_stops_only_the_second_conveyor():
    rt = conveyor_line()
    rt.scan("MAIN_Line")  # Bind the three default simulated motors once.
    fake = rt.instantiate("FB_MotorFake")
    second = rt.program_fb("MAIN_Line", "conveyors", 2)
    second.call_method("BindMotor", motor=fake)
    second.set_property("SpeedSetpoint", 0.75)
    start_all(rt)
    rt.advance_time(500)
    rt.scan("MAIN_Line")
    assert rt.global_cell("GVL_Line", "actualSpeed").value == (0.5, 0.75, 0.5)
    assert fake.get_property("Running") is True
    assert fake.output("updates") > 0
    assert rt.program_fb("MAIN_Line", "motors", 2).get_property("Running") is False
    fake.set_input("fault", True)
    rt.scan("MAIN_Line")
    assert rt.global_cell("GVL_Line", "running").value == (True, False, True)
    assert second.get_property("Alarm") == "Motor fault"
    assert fake.get_property("Faulted") is True
    assert rt.global_cell("GVL_Line", "actualSpeed").value == (0.5, 0.0, 0.5)


def test_clearing_fake_fault_requires_an_explicit_restart():
    rt = conveyor_line()
    rt.scan("MAIN_Line")
    fake = rt.instantiate("FB_MotorFake")
    second = rt.program_fb("MAIN_Line", "conveyors", 2)
    second.call_method("BindMotor", motor=fake)
    fake.set_input("fault", True)
    start_all(rt)
    assert second.get_property("Alarm") == "Motor fault"
    fake.set_input("fault", False)
    rt.run_cycles("MAIN_Line", cycles=100, period_ms=10)
    assert second.get_property("Running") is False
    second.call_method("Start", delay=250)
    rt.scan("MAIN_Line")
    rt.advance_time(249)
    rt.scan("MAIN_Line")
    assert second.get_property("Running") is False
    rt.advance_time(1)
    rt.scan("MAIN_Line")
    assert second.get_property("Running") is True


def test_rebinding_stops_old_motor_and_commands_the_new_instance():
    rt = conveyor_line()
    start_all(rt)
    rt.advance_time(500)
    rt.scan("MAIN_Line")
    second = rt.program_fb("MAIN_Line", "conveyors", 2)
    original = rt.program_fb("MAIN_Line", "motors", 2)
    assert original.get_property("Running") is True
    fake = rt.instantiate("FB_MotorFake")
    second.call_method("BindMotor", motor=fake)
    assert original.get_property("Running") is False
    second.call_method("Start", delay=0)
    rt.scan("MAIN_Line")
    assert fake.get_property("Running") is True
    assert rt.global_cell("GVL_Line", "running").value == (True, True, True)


def test_bad_python_bindings_leave_the_current_motor_running():
    rt = conveyor_line()
    start_all(rt)
    rt.advance_time(500)
    rt.scan("MAIN_Line")
    second = rt.program_fb("MAIN_Line", "conveyors", 2)
    foreign = conveyor_line().instantiate("FB_MotorFake")
    for bad in (foreign, second, True, None, 1):
        with pytest.raises(ArgumentError):
            second.call_method("BindMotor", motor=bad)
        assert second.get_property("Running") is True
    rt.scan("MAIN_Line")
    assert rt.global_cell("GVL_Line", "running").value == (True, True, True)


def test_unbound_motor_is_reported_without_dereferencing_null():
    rt = conveyor_line()
    rt.scan("MAIN_Line")
    second = rt.program_fb("MAIN_Line", "conveyors", 2)
    second.call_method("BindMotor", motor=0)
    second.call_method("Start", delay=0)
    rt.scan("MAIN_Line")
    assert second.get_property("Running") is False
    assert second.get_property("Alarm") == "Motor not bound"
    assert rt.global_cell("GVL_Line", "actualSpeed").element(2).value == 0.0


def test_interface_motor_state_preserves_independent_product_edges():
    rt = conveyor_line()
    start_all(rt)
    rt.advance_time(500)
    sensors = rt.global_cell("GVL_Line", "productSensor")
    sensors.value = [True, True, True]
    rt.scan("MAIN_Line")
    rt.scan("MAIN_Line")
    assert rt.global_cell("GVL_Line", "productCount").value == (1, 1, 1)
    sensors.element(2).value = False
    rt.scan("MAIN_Line")
    sensors.element(2).value = True
    rt.scan("MAIN_Line")
    assert rt.global_cell("GVL_Line", "productCount").value == (1, 2, 1)
