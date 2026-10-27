"""Native inherited motors share implementation, never per-instance state."""

from pathlib import Path

import pytest

from tc_emulator import ArgumentError, Runtime

SOURCES = Path(__file__).parent / "conveyor_inheritance"


def conveyor_line():
    return Runtime.from_files(sorted(SOURCES.glob("*.Tc*"), reverse=True))


def start_all(runtime):
    runtime.global_cell("GVL_Line", "start").value = [True, True, True]
    runtime.scan("MAIN_Line")
    runtime.global_cell("GVL_Line", "start").value = [False, False, False]


def test_inherited_timers_keep_three_independent_startup_delays():
    rt = conveyor_line()
    start_all(rt)
    running = rt.global_cell("GVL_Line", "running")
    assert running.value == (False, False, False)
    rt.advance_time(99)
    rt.scan("MAIN_Line")
    assert running.value == (False, False, False)
    rt.advance_time(1)
    rt.scan("MAIN_Line")
    assert running.value == (True, False, False)
    rt.advance_time(150)
    rt.scan("MAIN_Line")
    assert running.value == (True, True, False)
    rt.advance_time(250)
    rt.scan("MAIN_Line")
    assert running.value == (True, True, True)
    assert rt.global_cell("GVL_Line", "actualSpeed").value == (0.5, 0.5, 0.5)


def test_inherited_interface_accepts_fake_and_fault_is_isolated():
    rt = conveyor_line()
    rt.scan("MAIN_Line")
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
    assert rt.global_cell("GVL_Line", "actualSpeed").value == (0.5, 0.0, 0.5)
    assert second.get_property("Alarm") == "Motor fault"
    assert fake.get_property("Faulted") is True


def test_clearing_fake_fault_requires_explicit_restart_and_full_delay():
    rt = conveyor_line()
    rt.scan("MAIN_Line")
    fake = rt.instantiate("FB_MotorFake")
    second = rt.program_fb("MAIN_Line", "conveyors", 2)
    second.call_method("BindMotor", motor=fake)
    fake.set_input("fault", True)
    start_all(rt)
    assert second.get_property("Alarm") == "Motor fault"
    fake.set_input("fault", False)
    rt.advance_time(1000)
    rt.scan("MAIN_Line")
    assert rt.global_cell("GVL_Line", "running").value == (True, False, True)
    second.call_method("Start", delay=250)
    rt.scan("MAIN_Line")
    rt.advance_time(249)
    rt.scan("MAIN_Line")
    assert second.get_property("Running") is False
    rt.advance_time(1)
    rt.scan("MAIN_Line")
    assert rt.global_cell("GVL_Line", "running").value == (True, True, True)


def test_base_update_calls_derived_protected_hook_on_same_receiver():
    rt = conveyor_line()
    fake = rt.instantiate("FB_MotorFake")
    fake.call_method("Update", run=True, delay=0)
    assert fake.get_property("Running") is True
    fake.set_input("fault", True)
    fake.call_method("Update", run=True, delay=0)
    assert fake.get_property("Running") is False
    assert fake.get_property("Faulted") is True
    assert fake.output("updates") == 2
    sim = rt.instantiate("FB_MotorSim")
    sim.call_method("Update", run=True, delay=0)
    assert sim.get_property("Running") is True
    assert sim.get_property("Faulted") is False


def test_super_body_and_inherited_properties_keep_instance_state_independent():
    rt = conveyor_line()
    first = rt.instantiate("FB_MotorSim")
    second = rt.instantiate("FB_MotorSim")
    first.call()
    first.call()
    assert first.output("bodyCalls") == 2
    assert second.output("bodyCalls") == 0
    first.set_property("SpeedSetpoint", 2.0)
    first.call_method("Update", run=True, delay=0)
    assert first.get_property("ActualSpeed") == 1.0
    assert second.get_property("SpeedSetpoint") == 0.5
    assert second.get_property("Running") is False
    first.set_property("SpeedSetpoint", -1.0)
    assert first.get_property("ActualSpeed") == 0.0


def test_python_cannot_call_inherited_private_or_protected_members():
    rt = conveyor_line()
    motor = rt.instantiate("FB_MotorFake")
    for method, arguments in (("CheckFault", {}), ("ClampSpeed", {"value": 0.5})):
        with pytest.raises(ArgumentError):
            motor.call_method(method, **arguments)
    with pytest.raises(ArgumentError):
        motor.get_property("MayRun")
    motor.call_method("Update", run=True, delay=0)
    assert motor.get_property("Running") is True


def test_product_edges_remain_independent_with_inherited_motors():
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
