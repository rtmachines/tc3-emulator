"""Nominal, non-owning interface dispatch and lifetime behavior."""

import pytest

from tc_emulator import ArgumentError, ExecutionError, Runtime, RuntimeFaultedError

SOURCE = """
INTERFACE I_Motor
METHOD Move : INT VAR_INPUT amount : INT := 2; END_VAR END_METHOD
PROPERTY Speed : INT GET END_GET SET END_SET END_PROPERTY
END_INTERFACE
FUNCTION_BLOCK Motor IMPLEMENTS I_Motor
VAR_OUTPUT n, reads : INT; END_VAR
METHOD Move : INT VAR_INPUT amount : INT := 2; END_VAR
n := n + amount; Move := n; END_METHOD
PROPERTY Speed : INT GET reads := reads + 1; Speed := n; END_GET
SET n := Speed; END_SET END_PROPERTY
END_FUNCTION_BLOCK
FUNCTION_BLOCK Client
VAR_INPUT motor : I_Motor; END_VAR
VAR saved : I_Motor; END_VAR
METHOD Run : INT Run := motor.Move(); END_METHOD
METHOD Bind VAR_INPUT value : I_Motor; END_VAR saved := value; END_METHOD
METHOD ReadSaved : INT ReadSaved := saved.Move(); END_METHOD
METHOD Clear saved := 0; END_METHOD
PROPERTY Speed : INT GET Speed := motor.Speed; END_GET SET motor.Speed := Speed; END_SET END_PROPERTY
END_FUNCTION_BLOCK
"""


def test_dynamic_calls_properties_and_python_identity():
    rt = Runtime.from_source(SOURCE)
    motor, client = rt.instantiate("Motor"), rt.instantiate("Client")
    client.set_input("motor", motor)
    assert client.call_method("Run").value == 2
    client.set_property("Speed", 9)
    assert client.get_property("Speed") == 9
    assert motor.output("n") == 9
    client.call_method("Bind", value=motor)
    assert client.call_method("ReadSaved").value == 11
    assert client.inspect()["MOTOR"] == {"interface": "I_MOTOR", "target": "MOTOR", "valid": True}
    assert motor.output("reads") == 1


def test_python_arguments_prevalidate_everything_before_mutation():
    rt = Runtime.from_source(SOURCE)
    client, motor = rt.instantiate("Client"), rt.instantiate("Motor")
    foreign = Runtime.from_source(SOURCE).instantiate("Motor")
    for bad in (None, False, True, 1, object(), rt.cell("INT", 0), client, foreign, motor._frame):
        with pytest.raises(ArgumentError):
            client.set_input("motor", bad)
        assert client.inspect()["MOTOR"]["target"] is None
    client.call(motor=motor)
    client.set_input("motor", 0)
    assert client.inspect()["MOTOR"]["valid"] is False
    with pytest.raises(ExecutionError, match="[Nn]ull"):
        client.call_method("Run")
    with pytest.raises(RuntimeFaultedError):
        client.call()


def test_st_reference_copy_null_checks_and_dynamic_implementation():
    rt = Runtime.from_source(
        SOURCE
        + """
    FUNCTION_BLOCK Fast IMPLEMENTS I_Motor
    VAR n : INT; END_VAR
    METHOD Move : INT VAR_INPUT amount : INT := 2; END_VAR
    n := n + amount * 10; Move := n; END_METHOD
    PROPERTY Speed : INT GET Speed := n; END_GET SET n := Speed; END_SET END_PROPERTY
    END_FUNCTION_BLOCK
    PROGRAM Main
    VAR a : Motor; b : Fast; r, copy : I_Motor; x, y, z : INT; ok : BOOL; END_VAR
    r := a; copy := r; r := b;
    x := copy.Move(); y := r.Move(); r := 0;
    ok := (r = 0) AND (0 <> copy) AND (0 = r) AND (copy <> 0);
    z := copy.Move();
    END_PROGRAM
    """
    )
    rt.scan("Main")
    assert [rt.program_cell("Main", x).value for x in ("x", "y", "z", "ok")] == [2, 20, 4, True]
    for selector, args in ((rt.program_cell, ("Main", "r")), (rt.program_fb, ("Main", "r"))):
        with pytest.raises(ArgumentError):
            selector(*args)


def test_capture_receiver_before_argument_and_setter_rhs_mutation():
    rt = Runtime.from_source(
        SOURCE
        + """
    VAR_GLOBAL first, second : Motor; active : I_Motor; END_VAR
    FUNCTION Switch : INT active := second; Switch := 7; END_FUNCTION
    PROGRAM Main
    VAR result : INT; END_VAR
    active := first; result := active.Move(Switch());
    active := first; active.Speed := Switch();
    END_PROGRAM
    """
    )
    rt.scan("Main")
    assert rt.program_cell("Main", "result").value == 7
    assert rt.global_fb("GVL", "first").output("n") == 7
    assert rt.global_fb("GVL", "second").output("n") == 0


def test_interface_inputs_work_for_functions_methods_and_calls_from_st():
    rt = Runtime.from_source(
        SOURCE
        + """
    FUNCTION Invoke : INT VAR_INPUT ref : I_Motor; END_VAR Invoke := ref.Move(3); END_FUNCTION
    PROGRAM Main
    VAR a : Motor; client : Client; result : INT; END_VAR
    client(motor := a); client.Bind(a); result := Invoke(a) + client.ReadSaved();
    END_PROGRAM
    """
    )
    motor = rt.instantiate("Motor")
    assert rt.call("Invoke", ref=motor).value == 3
    rt.scan("Main")
    assert rt.program_cell("Main", "result").value == 8


def test_python_batch_rejection_preserves_prior_reference_and_scalar_input():
    rt = Runtime.from_source(
        SOURCE
        + """
    FUNCTION_BLOCK Batch
    VAR_INPUT x : INT; ref : I_Motor; END_VAR
    VAR_OUTPUT calls : INT; END_VAR calls := calls + 1;
    END_FUNCTION_BLOCK
    """
    )
    batch, motor = rt.instantiate("Batch"), rt.instantiate("Motor")
    batch.call(x=4, ref=motor)
    for inputs in ({"x": 5, "ref": False}, {"ref": 0, "x": "bad"}, {"ref": motor, "unknown": 1}):
        with pytest.raises(ArgumentError):
            batch.call(**inputs)
        assert batch.inspect()["X"] == 4
        assert batch.inspect()["REF"]["target"] == "MOTOR"
        assert batch.output("calls") == 1


LIFETIME_SOURCE = """
INTERFACE I METHOD Ping : INT END_METHOD END_INTERFACE
FUNCTION_BLOCK Leaf IMPLEMENTS I
METHOD Ping : INT Ping := 3; END_METHOD
END_FUNCTION_BLOCK
VAR_GLOBAL held : I; END_VAR
FUNCTION Read : INT Read := held.Ping(); END_FUNCTION
FUNCTION Check : BOOL Check := held <> 0; END_FUNCTION
FUNCTION Copy : BOOL VAR local : I; END_VAR local := held; Copy := TRUE; END_FUNCTION
FUNCTION Clear : BOOL held := 0; Clear := held = 0; END_FUNCTION
"""


@pytest.mark.parametrize(
    "declaration,invoke",
    [
        ("FUNCTION Escape : INT VAR leaf : Leaf; END_VAR held := leaf; END_FUNCTION", "function"),
        (
            "FUNCTION_BLOCK Owner METHOD Escape VAR leaf : Leaf; END_VAR held := leaf; END_METHOD END_FUNCTION_BLOCK",
            "method",
        ),
        (
            "FUNCTION_BLOCK Owner PROPERTY Escape : INT GET VAR leaf : Leaf; END_VAR held := leaf; END_GET END_PROPERTY END_FUNCTION_BLOCK",
            "getter",
        ),
        (
            "FUNCTION_BLOCK Owner PROPERTY Escape : INT SET VAR leaf : Leaf; END_VAR held := leaf; END_SET END_PROPERTY END_FUNCTION_BLOCK",
            "setter",
        ),
        (
            "FUNCTION_BLOCK Owner VAR_TEMP leaf : Leaf; END_VAR held := leaf; END_FUNCTION_BLOCK",
            "fb",
        ),
        ("PROGRAM Escape VAR_TEMP leaf : Leaf; END_VAR held := leaf; END_PROGRAM", "program"),
    ],
)
@pytest.mark.parametrize("use", ["Read", "Check", "Copy", "Clear"])
def test_transient_targets_expire_at_invocation_end(declaration, invoke, use):
    rt = Runtime.from_source(LIFETIME_SOURCE + declaration)
    if invoke == "function":
        rt.call("Escape")
    elif invoke == "program":
        rt.scan("Escape")
    else:
        owner = rt.instantiate("Owner")
        if invoke == "method":
            owner.call_method("Escape")
        elif invoke == "getter":
            owner.get_property("Escape")
        elif invoke == "setter":
            owner.set_property("Escape", 1)
        else:
            owner.call()
    if use == "Clear":
        assert rt.call(use).value is True
    else:
        with pytest.raises(ExecutionError, match="Expired"):
            rt.call(use)
        with pytest.raises(RuntimeFaultedError):
            rt.call("Clear")


def test_expiry_propagates_through_nested_arrays_and_method_instance_children():
    rt = Runtime.from_source(
        LIFETIME_SOURCE
        + """
    FUNCTION_BLOCK Container
    VAR leaves : ARRAY[1..2] OF Leaf; END_VAR
    METHOD Publish held := leaves[2]; END_METHOD
    END_FUNCTION_BLOCK
    FUNCTION_BLOCK Owner
    METHOD Publish
    VAR_INST containers : ARRAY[1..2] OF Container; END_VAR
    containers[1].Publish();
    END_METHOD
    END_FUNCTION_BLOCK
    FUNCTION Escape : INT VAR local : Owner; END_VAR local.Publish(); END_FUNCTION
    """
    )
    rt.call("Escape")
    with pytest.raises(ExecutionError, match="Expired"):
        rt.call("Read")


def test_persistent_method_instance_targets_outlive_method_invocations():
    rt = Runtime.from_source(
        LIFETIME_SOURCE
        + """
    FUNCTION_BLOCK Owner
    METHOD Publish VAR_INST leaf : Leaf; END_VAR held := leaf; END_METHOD
    END_FUNCTION_BLOCK
    """
    )
    owner = rt.instantiate("Owner")
    owner.call_method("Publish")
    assert rt.call("Read").value == 3
    assert rt.call("Check").value is True
    assert owner.inspect()["$VAR_INST"]["PUBLISH"]["LEAF"] == {}


def test_expiry_on_fault_preserves_passive_detached_inspection():
    rt = Runtime.from_source(
        LIFETIME_SOURCE
        + """
    FUNCTION_BLOCK Holder VAR_INPUT ref : I; END_VAR END_FUNCTION_BLOCK
    VAR_GLOBAL holder : Holder; END_VAR
    FUNCTION Escape : INT VAR local : Leaf; END_VAR
    holder(ref := local); Escape := 1 / 0;
    END_FUNCTION
    """
    )
    holder = rt.global_fb("GVL", "holder")
    with pytest.raises(ExecutionError):
        rt.call("Escape")
    snapshot = holder.inspect()
    assert snapshot["REF"] == {"interface": "I", "target": "LEAF", "valid": False}
    snapshot["REF"]["valid"] = True
    assert holder.inspect()["REF"]["valid"] is False


def test_passive_snapshots_allow_cycles_without_following_references():
    rt = Runtime.from_source("""
    INTERFACE I END_INTERFACE
    FUNCTION_BLOCK Node IMPLEMENTS I VAR_INPUT next : I; END_VAR END_FUNCTION_BLOCK
    """)
    a, b = rt.instantiate("Node"), rt.instantiate("Node")
    a.set_input("next", b)
    b.set_input("next", a)
    assert a.inspect()["NEXT"] == {"interface": "I", "target": "NODE", "valid": True}
    assert b.inspect()["NEXT"]["valid"] is True
    with pytest.raises(ArgumentError):
        a.fb("next")


def test_interface_dispatch_preserves_inout_aliases_outputs_and_order():
    rt = Runtime.from_source("""
    INTERFACE I
    METHOD M : INT VAR_INPUT add : INT; END_VAR VAR_IN_OUT value : INT; END_VAR
    VAR_OUTPUT doubled : INT; END_VAR END_METHOD
    END_INTERFACE
    FUNCTION_BLOCK B IMPLEMENTS I
    METHOD M : INT VAR_INPUT add : INT; END_VAR VAR_IN_OUT value : INT; END_VAR
    VAR_OUTPUT doubled : INT := 99; END_VAR
    value := value + add; doubled := value * 2; M := value;
    END_METHOD END_FUNCTION_BLOCK
    PROGRAM Main VAR b : B; r : I; x, y, result : INT; END_VAR
    r := b; result := r.M(add := 3, value := x, doubled => y);
    END_PROGRAM
    """)
    rt.scan("Main")
    assert [rt.program_cell("Main", name).value for name in ("x", "y", "result")] == [3, 6, 3]


@pytest.mark.parametrize(
    "statement", ["n := active.Move(SideEffect());", "active.Speed := SideEffect();"]
)
def test_null_receiver_fails_before_arguments_or_rhs(statement):
    rt = Runtime.from_source(
        SOURCE
        + f"""
    VAR_GLOBAL active : I_Motor; effects : INT; END_VAR
    FUNCTION SideEffect : INT effects := effects + 1; SideEffect := 4; END_FUNCTION
    PROGRAM Main VAR n : INT; END_VAR {statement} END_PROGRAM
    """
    )
    with pytest.raises(ExecutionError, match="Null"):
        rt.scan("Main")
    assert rt.global_cell("GVL", "effects").value == 0


def test_global_program_nested_and_array_handles_bind_original_instances():
    rt = Runtime.from_source(
        SOURCE
        + """
    FUNCTION_BLOCK Group VAR children : ARRAY[2..3] OF Motor; END_VAR END_FUNCTION_BLOCK
    VAR_GLOBAL motors : ARRAY[4..5] OF Motor; ref : I_Motor; END_VAR
    PROGRAM Main VAR motor : Motor; group : Group; ref : I_Motor; END_VAR END_PROGRAM
    """
    )
    client = rt.instantiate("Client")
    handles = [
        rt.program_fb("Main", "motor"),
        rt.global_fb("GVL", "motors", 5),
        rt.program_fb("Main", "group").fb("children", 3),
    ]
    for handle in handles:
        client.set_input("motor", handle)
        assert client.call_method("Run").value == 2
        assert handle.output("n") == 2
    for method, args in ((rt.global_cell, ("GVL", "ref")), (rt.global_fb, ("GVL", "ref"))):
        with pytest.raises(ArgumentError):
            method(*args)


def test_interface_slots_in_method_instances_persist_and_accessor_locals_do_not():
    rt = Runtime.from_source(
        SOURCE
        + """
    FUNCTION_BLOCK Owner
    VAR motor : Motor; END_VAR
    METHOD Keep : INT VAR_INST ref : I_Motor; END_VAR
    IF ref = 0 THEN ref := motor; END_IF; Keep := ref.Move(); END_METHOD
    PROPERTY Fresh : BOOL GET VAR ref : I_Motor; END_VAR
    Fresh := ref = 0; ref := motor; END_GET END_PROPERTY
    END_FUNCTION_BLOCK
    """
    )
    owner = rt.instantiate("Owner")
    assert owner.call_method("Keep").value == 2
    assert owner.call_method("Keep").value == 4
    assert owner.get_property("Fresh") is True
    assert owner.get_property("Fresh") is True
    assert owner.inspect()["$VAR_INST"]["KEEP"]["REF"]["valid"] is True


@pytest.mark.parametrize(
    "limits,match", [({"max_steps": 1}, "budget"), ({"max_call_depth": 1}, "depth")]
)
def test_interface_dispatch_reuses_limits_stack_and_fault_latch(limits, match):
    rt = Runtime.from_source(SOURCE, **limits)
    client, motor = rt.instantiate("Client"), rt.instantiate("Motor")
    client.set_input("motor", motor)
    with pytest.raises(ExecutionError, match=match) as error:
        client.call_method("Run")
    assert error.value.stack[0] == "CLIENT.RUN"
    assert client.inspect()["MOTOR"]["valid"] is True
    with pytest.raises(RuntimeFaultedError):
        client.call_method("Run")


def test_interface_open_array_inout_dispatch_resolves_element_bounds():
    rt = Runtime.from_source("""
    VAR_GLOBAL CONSTANT N : INT := 4; END_VAR
    INTERFACE I METHOD M VAR_IN_OUT values : ARRAY[*] OF STRING(N); END_VAR END_METHOD END_INTERFACE
    FUNCTION_BLOCK B IMPLEMENTS I
    METHOD M VAR_IN_OUT values : ARRAY[*] OF STRING(4); END_VAR
    values[LOWER_BOUND(values, 1)] := 'abcde'; END_METHOD END_FUNCTION_BLOCK
    PROGRAM Main VAR b : B; r : I; values : ARRAY[3..4] OF STRING(4); END_VAR
    r := b; r.M(values); END_PROGRAM
    """)
    rt.scan("Main")
    assert rt.program_cell("Main", "values").value == ("abcd", "")
