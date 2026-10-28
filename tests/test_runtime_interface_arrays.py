"""Interface array elements reuse scalar dispatch, capture and ownership rules."""

import pytest

from tc_emulator import ArgumentError, ExecutionError, Runtime, RuntimeFaultedError

SOURCE = """
INTERFACE I
METHOD Add : INT VAR_INPUT amount : INT := 2; END_VAR END_METHOD
PROPERTY Value : INT GET END_GET SET END_SET END_PROPERTY
END_INTERFACE
INTERFACE Derived EXTENDS I END_INTERFACE
FUNCTION_BLOCK Slow IMPLEMENTS Derived
VAR_OUTPUT n, init : INT; END_VAR
METHOD FB_init : BOOL VAR_INPUT bInitRetains, bInCopyCode : BOOL; END_VAR init := init + 1; END_METHOD
METHOD Add : INT VAR_INPUT amount : INT := 2; END_VAR n := n + amount; Add := n; END_METHOD
PROPERTY Value : INT GET Value := n; END_GET SET n := Value; END_SET END_PROPERTY
END_FUNCTION_BLOCK
FUNCTION_BLOCK Fast IMPLEMENTS I
VAR_OUTPUT n : INT; END_VAR
METHOD Add : INT VAR_INPUT amount : INT := 2; END_VAR n := n + amount * 10; Add := n; END_METHOD
PROPERTY Value : INT GET Value := n; END_GET SET n := Value; END_SET END_PROPERTY
END_FUNCTION_BLOCK
"""


def test_elements_copy_bindings_dispatch_and_preserve_inherited_contracts():
    rt = Runtime.from_source(
        SOURCE
        + """
    FUNCTION Invoke : INT VAR_INPUT item : I; END_VAR Invoke := item.Add(); END_FUNCTION
    PROGRAM Main
    VAR a : Slow; b : Fast; derived : Derived; devices : ARRAY[-1..0,2..3] OF I;
        x, y, z, low, high : INT; ok : BOOL; END_VAR
    ok := (devices[-1,2] = 0) AND (0 = devices[-1,3]) AND (devices[0,2] = 0);
    derived := a; devices[-1,2] := derived; devices[-1,3] := devices[-1,2];
    devices[-1,2] := b;
    x := devices[-1,3].Add(); y := devices[-1,2].Add(); z := Invoke(devices[-1,3]);
    devices[-1,2].Value := 9; y := y + devices[-1,2].Value;
    devices[-1,2] := 0;
    ok := ok AND (devices[-1,2] = 0) AND (0 <> devices[-1,3]) AND (devices[-1,3] <> 0);
    low := LOWER_BOUND(devices,1); high := UPPER_BOUND(devices,2);
    END_PROGRAM
    """
    )
    rt.scan("Main")
    assert [
        rt.program_cell("Main", name).value for name in ("x", "y", "z", "low", "high", "ok")
    ] == [2, 29, 4, -1, 3, True]
    assert rt.program_fb("Main", "a").output("n") == 4
    assert rt.program_fb("Main", "b").output("n") == 9


@pytest.mark.parametrize(
    "operation", ["result := devices[Pick()].Add(Switch());", "devices[Pick()].Value := Switch();"]
)
def test_receiver_is_selected_and_captured_once_before_side_effects(operation):
    rt = Runtime.from_source(
        SOURCE
        + f"""
    VAR_GLOBAL first, second : Slow; devices : ARRAY[1..2] OF I; selected : INT := 1; picks, switches : INT; END_VAR
    FUNCTION Pick : INT picks := picks + 1; Pick := selected; END_FUNCTION
    FUNCTION Switch : INT switches := switches + 1; selected := 2; devices[1] := second; Switch := 7; END_FUNCTION
    PROGRAM Main VAR result : INT; END_VAR devices[1] := first; {operation} END_PROGRAM
    """
    )
    rt.scan("Main")
    assert rt.global_cell("GVL", "picks").value == 1
    assert rt.global_cell("GVL", "switches").value == 1
    assert rt.global_fb("GVL", "first").output("n") == 7
    assert rt.global_fb("GVL", "second").output("n") == 0


@pytest.mark.parametrize("receiver,match", [("devices[1]", "Null"), ("devices[3]", "outside")])
@pytest.mark.parametrize(
    "operation", ["result := RECEIVER.Add(Switch());", "RECEIVER.Value := Switch();"]
)
def test_receiver_faults_before_rhs_and_latches(receiver, match, operation):
    rt = Runtime.from_source(
        SOURCE
        + f"""
    VAR_GLOBAL effects : INT; END_VAR
    FUNCTION Switch : INT effects := effects + 1; Switch := 7; END_FUNCTION
    PROGRAM Main VAR devices : ARRAY[1..2] OF I; result : INT; END_VAR {operation.replace("RECEIVER", receiver)} END_PROGRAM
    """,
        source="receivers.st",
    )
    with pytest.raises(ExecutionError, match=match) as caught:
        rt.scan("Main")
    assert caught.value.loc.source == "receivers.st"
    assert caught.value.stack == ("MAIN",)
    assert rt.global_cell("GVL", "effects").value == 0
    with pytest.raises(RuntimeFaultedError):
        rt.scan("Main")


LIFETIME = (
    SOURCE
    + """
VAR_GLOBAL devices : ARRAY[1..2] OF I; saved : I; effects : INT; END_VAR
FUNCTION Escape : INT VAR local : Slow; END_VAR devices[1] := local; saved := devices[1]; END_FUNCTION
FUNCTION Read : INT Read := devices[1].Value; END_FUNCTION
FUNCTION Copy : INT devices[2] := devices[1]; END_FUNCTION
FUNCTION Check : BOOL Check := devices[1] <> 0; END_FUNCTION
FUNCTION Dispatch : INT Dispatch := saved.Add(); END_FUNCTION
FUNCTION Clear : BOOL devices[1] := 0; saved := 0; Clear := devices[1] = 0; END_FUNCTION
FUNCTION Switch : INT effects := effects + 1; Switch := 7; END_FUNCTION
FUNCTION LateCall : INT LateCall := devices[1].Add(Switch()); END_FUNCTION
FUNCTION LateSet : INT devices[1].Value := Switch(); END_FUNCTION
"""
)


@pytest.mark.parametrize("use", ["Read", "Copy", "Check", "Dispatch", "LateCall", "LateSet"])
def test_escaped_targets_expire_through_array_and_scalar_copies(use):
    rt = Runtime.from_source(LIFETIME)
    rt.call("Escape")
    with pytest.raises(ExecutionError, match="Expired"):
        rt.call(use)
    assert rt.global_cell("GVL", "effects").value == 0
    with pytest.raises(RuntimeFaultedError):
        rt.call("Clear")


def test_expired_bindings_can_be_cleared_before_faulting():
    rt = Runtime.from_source(LIFETIME)
    rt.call("Escape")
    assert rt.call("Clear").value is True


@pytest.mark.parametrize("kind", ["FUNCTION", "METHOD", "GET", "SET", "FB_TEMP", "PROGRAM_TEMP"])
def test_local_arrays_start_unbound_on_each_activation(kind):
    body = "IF slots[1] = 0 THEN count := count + 1; END_IF; slots[1] := target;"
    declaration = "VAR slots : ARRAY[1..1] OF I; END_VAR"
    global_source = "VAR_GLOBAL target : Slow; count : INT; END_VAR"
    if kind == "FUNCTION":
        source = f"FUNCTION Run : INT {declaration} {body} END_FUNCTION"
    elif kind == "METHOD":
        source = (
            f"FUNCTION_BLOCK Owner METHOD Run {declaration} {body} END_METHOD END_FUNCTION_BLOCK"
        )
    elif kind in {"GET", "SET"}:
        source = f"FUNCTION_BLOCK Owner PROPERTY Run : INT {kind} {declaration} {body} END_{kind} END_PROPERTY END_FUNCTION_BLOCK"
    else:
        pou_kind = "FUNCTION_BLOCK" if kind == "FB_TEMP" else "PROGRAM"
        source = f"{pou_kind} Owner {declaration.replace('VAR slots', 'VAR_TEMP slots')} {body} END_{pou_kind}"
    rt = Runtime.from_source(SOURCE + global_source + "\n" + source)
    owner = rt.instantiate("Owner") if kind not in {"FUNCTION", "PROGRAM_TEMP"} else None
    for _ in range(2):
        if kind == "FUNCTION":
            rt.call("Run")
        elif kind == "METHOD":
            owner.call_method("Run")
        elif kind == "GET":
            owner.get_property("Run")
        elif kind == "SET":
            owner.set_property("Run", 1)
        elif kind == "FB_TEMP":
            owner.call()
        else:
            rt.scan("Owner")
    assert rt.global_cell("GVL", "count").value == 2


def test_method_instance_arrays_persist_and_snapshots_do_not_follow_cycles():
    rt = Runtime.from_source(
        SOURCE
        + """
    FUNCTION_BLOCK Owner IMPLEMENTS I
    VAR slots : ARRAY[1..1] OF I; count : INT; END_VAR
    METHOD Add : INT VAR_INPUT amount : INT := 2; END_VAR Add := amount; END_METHOD
    PROPERTY Value : INT GET END_GET SET END_SET END_PROPERTY
    METHOD Run VAR_INPUT self : I; END_VAR VAR_INST saved : ARRAY[1..1] OF I; END_VAR
    IF saved[1] = 0 THEN count := count + 1; END_IF; saved[1] := self; slots[1] := self;
    END_METHOD
    METHOD Fail VAR bad : ARRAY[1..1] OF I; x : INT; END_VAR x := bad[1].Add(); END_METHOD
    END_FUNCTION_BLOCK
    """
    )
    owner = rt.instantiate("Owner")
    owner.call_method("Run", self=owner)
    snapshot = owner.inspect()
    snapshot["SLOTS"][0]["target"] = "detached"
    owner.call_method("Run", self=owner)
    assert owner.inspect()["COUNT"] == 1
    assert owner.inspect()["$VAR_INST"]["RUN"]["SAVED"][0]["target"] == "OWNER"
    with pytest.raises(ExecutionError, match="Null"):
        owner.call_method("Fail")
    assert owner.inspect()["SLOTS"][0] == {"interface": "I", "target": "OWNER", "valid": True}


def test_initialization_binds_three_inputs_without_initializing_targets_again():
    rt = Runtime.from_source(
        SOURCE
        + """
    FUNCTION_BLOCK Manager
    VAR devices : ARRAY[1..3] OF I; binds : INT; END_VAR
    FOR binds := 1 TO 3 DO IF devices[binds] <> 0 THEN devices[binds].Add(); END_IF; END_FOR;
    METHOD FB_init : BOOL
    VAR_INPUT bInitRetains, bInCopyCode : BOOL; first, second, third : I; END_VAR
    devices[1] := first; devices[2] := second; devices[3] := third;
    END_METHOD
    METHOD Bind VAR_INPUT index : INT; target : I; END_VAR binds := binds + 1; devices[index] := target; END_METHOD
    END_FUNCTION_BLOCK
    PROGRAM Main
    VAR a,b,c : Slow; manager : Manager(first := a, second := b, third := c); END_VAR
    manager();
    END_PROGRAM
    """
    )
    manager = rt.program_fb("Main", "manager")
    assert all(item["target"] == "SLOW" for item in manager.inspect()["DEVICES"])
    assert [rt.program_fb("Main", name).output("init") for name in ("a", "b", "c")] == [1, 1, 1]
    rt.scan("Main")
    replacement = rt.instantiate("Slow")
    manager.call_method("Bind", index=2, target=replacement)
    before = manager.inspect()
    foreign = Runtime.from_source(SOURCE).instantiate("Slow")
    with pytest.raises(ArgumentError):
        manager.call_method("Bind", index=1, target=foreign)
    assert manager.inspect() == before
    rt.scan("Main")
    assert rt.program_fb("Main", "b").output("n") == 2
    assert replacement.output("n") == 2
    assert replacement.output("init") == 1
    assert [rt.program_fb("Main", name).output("init") for name in ("a", "b", "c")] == [1, 1, 1]


def test_python_value_and_fb_selection_apis_reject_interface_storage_without_faulting():
    rt = Runtime.from_source(
        SOURCE
        + """
    FUNCTION_BLOCK Owner VAR devices : ARRAY[1..2] OF I; END_VAR END_FUNCTION_BLOCK
    VAR_GLOBAL devices : ARRAY[1..2] OF I; END_VAR
    PROGRAM Main VAR devices : ARRAY[1..2] OF I; owner : Owner; END_VAR END_PROGRAM
    """
    )
    owner = rt.program_fb("Main", "owner")
    for operation in (
        lambda: rt.program_cell("Main", "devices"),
        lambda: rt.global_cell("GVL", "devices"),
        lambda: rt.program_fb("Main", "devices", 1),
        lambda: rt.global_fb("GVL", "devices", 1),
        lambda: owner.fb("devices", 1),
    ):
        with pytest.raises(ArgumentError):
            operation()
    rt.scan("Main")
    assert owner.inspect()["DEVICES"] == ({"interface": "I", "target": None, "valid": False},) * 2


@pytest.mark.parametrize("dimension", [0, 2])
def test_bound_dimension_faults_keep_location_stack_and_fault_latch(dimension):
    rt = Runtime.from_source(
        SOURCE
        + f"PROGRAM Main VAR a : ARRAY[1..2] OF I; n : INT; END_VAR n := UPPER_BOUND(a,{dimension}); END_PROGRAM",
        source="bounds.st",
    )
    with pytest.raises(ExecutionError, match="dimension") as caught:
        rt.scan("Main")
    assert caught.value.loc.source == "bounds.st" and caught.value.stack == ("MAIN",)
    with pytest.raises(RuntimeFaultedError):
        rt.scan("Main")


@pytest.mark.parametrize(
    "limits,match", [({"max_steps": 1}, "budget"), ({"max_call_depth": 1}, "depth")]
)
def test_array_dispatch_shares_instruction_and_depth_limits(limits, match):
    rt = Runtime.from_source(
        SOURCE
        + """
    FUNCTION_BLOCK Client
    VAR devices : ARRAY[1..1] OF I; END_VAR
    METHOD Bind VAR_INPUT target : I; END_VAR devices[1] := target; END_METHOD
    METHOD Run : INT Run := devices[1].Add(); END_METHOD
    END_FUNCTION_BLOCK
    """,
        **limits,
    )
    client, target = rt.instantiate("Client"), rt.instantiate("Slow")
    client.call_method("Bind", target=target)
    with pytest.raises(ExecutionError, match=match) as caught:
        client.call_method("Run")
    assert caught.value.stack[0] == "CLIENT.RUN"
    assert client.inspect()["DEVICES"][0]["valid"] is True
    with pytest.raises(RuntimeFaultedError):
        client.call_method("Run")


def test_derived_array_elements_expose_inherited_properties_and_inputs():
    rt = Runtime.from_source(
        SOURCE
        + """
    FUNCTION Invoke : INT VAR_INPUT item : I; END_VAR Invoke := item.Add(); END_FUNCTION
    PROGRAM Main VAR target : Slow; devices : ARRAY[1..1] OF Derived; result : INT; END_VAR
    devices[1] := target; devices[1].Value := 5; result := devices[1].Value + Invoke(devices[1]);
    END_PROGRAM
    """
    )
    rt.scan("Main")
    assert rt.program_cell("Main", "result").value == 12


@pytest.mark.parametrize("kind", ["METHOD", "GET", "SET", "FB_TEMP", "PROGRAM_TEMP"])
def test_nonfunction_owned_targets_expire_when_escaped_via_arrays(kind):
    declaration = "VAR local : Slow; END_VAR"
    body = "devices[1] := local; saved := devices[1];"
    if kind == "METHOD":
        source = (
            f"FUNCTION_BLOCK Owner METHOD Escape {declaration} {body} END_METHOD END_FUNCTION_BLOCK"
        )
    elif kind in {"GET", "SET"}:
        source = f"FUNCTION_BLOCK Owner PROPERTY Escape : INT {kind} {declaration} {body} END_{kind} END_PROPERTY END_FUNCTION_BLOCK"
    else:
        pou_kind = "FUNCTION_BLOCK" if kind == "FB_TEMP" else "PROGRAM"
        source = f"{pou_kind} Owner {declaration.replace('VAR local', 'VAR_TEMP local')} {body} END_{pou_kind}"
    rt = Runtime.from_source(LIFETIME + source)
    if kind == "PROGRAM_TEMP":
        rt.scan("Owner")
    else:
        owner = rt.instantiate("Owner")
        if kind == "METHOD":
            owner.call_method("Escape")
        elif kind == "GET":
            owner.get_property("Escape")
        elif kind == "SET":
            owner.set_property("Escape", 1)
        else:
            owner.call()
    with pytest.raises(ExecutionError, match="Expired"):
        rt.call("Dispatch")


def test_two_object_reference_cycle_remains_inspectable_after_runtime_fault():
    rt = Runtime.from_source("""
    INTERFACE I END_INTERFACE
    FUNCTION_BLOCK Node IMPLEMENTS I
    VAR next : ARRAY[1..1] OF I; END_VAR
    METHOD Bind VAR_INPUT target : I; END_VAR next[1] := target; END_METHOD
    METHOD Fail VAR n : INT; END_VAR n := 1 / 0; END_METHOD
    END_FUNCTION_BLOCK
    """)
    first, second = rt.instantiate("Node"), rt.instantiate("Node")
    first.call_method("Bind", target=second)
    second.call_method("Bind", target=first)
    with pytest.raises(ExecutionError):
        first.call_method("Fail")
    assert first.inspect()["NEXT"][0] == {"interface": "I", "target": "NODE", "valid": True}
    assert second.inspect()["NEXT"][0]["valid"] is True
