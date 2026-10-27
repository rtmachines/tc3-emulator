"""Checked, non-owning references to ordinary PLC storage."""

import pytest

from tc_emulator import ArgumentError, ExecutionError, Runtime, RuntimeFaultedError


def test_binding_copy_rebind_and_value_assignment_are_distinct():
    rt = Runtime.from_source("""
    PROGRAM Main
    VAR a : INT := 1; b : INT := 2; r, s : REFERENCE TO INT; ok : BOOL; END_VAR
    r REF= a; s REF= r; r REF= b; s := r; r := 9;
    ok := __ISVALIDREF(s); r REF= 0;
    END_PROGRAM
    """)
    rt.scan("Main")
    assert [rt.program_cell("Main", x).value for x in ("a", "b", "ok")] == [2, 9, True]
    with pytest.raises(ArgumentError):
        rt.program_cell("Main", "r")


def test_null_copy_validity_and_dereference_fault():
    rt = Runtime.from_source("""
    FUNCTION_BLOCK Holder
    VAR r, s : REFERENCE TO INT; END_VAR
    METHOD Check : BOOL s REF= r; Check := __ISVALIDREF(s); END_METHOD
    METHOD Read : INT Read := r; END_METHOD
    END_FUNCTION_BLOCK
    """)
    fb = rt.instantiate("Holder")
    assert fb.call_method("Check").value is False
    assert fb.inspect()["R"] == {"reference": "INT", "target": None, "valid": False}
    with pytest.raises(ExecutionError, match="[Nn]ull"):
        fb.call_method("Read")
    with pytest.raises(RuntimeFaultedError):
        fb.call_method("Check")


def test_python_reference_inputs_bind_cells_and_retain_fb_binding():
    rt = Runtime.from_source("""
    FUNCTION_BLOCK Update
    VAR_INPUT ref : REFERENCE TO INT; amount : INT; END_VAR
    IF __ISVALIDREF(ref) THEN ref := ref + amount; END_IF;
    METHOD Add VAR_INPUT other : REFERENCE TO INT; END_VAR other := other + 1; END_METHOD
    END_FUNCTION_BLOCK
    FUNCTION Read : INT VAR_INPUT ref : REFERENCE TO INT; END_VAR Read := ref; END_FUNCTION
    """)
    fb = rt.instantiate("Update")
    cell = rt.cell("INT", 3)
    fb.call(ref=cell, amount=2)
    fb.call()
    assert cell.value == 7
    fb.call_method("Add", other=cell)
    assert rt.call("Read", ref=cell).value == 8
    fb.set_input("ref", 0)
    fb.call()
    assert cell.value == 8
    fb.set_input("ref", cell)
    fb.call()
    assert cell.value == 10


def test_reference_initializer_targets_forward_storage_and_runs_once():
    rt = Runtime.from_source("""
    FUNCTION_BLOCK B
    VAR r : REFERENCE TO INT REF= x; x : INT := 4; y : INT := 20; END_VAR
    r := r + 1;
    METHOD Rebind r REF= y; END_METHOD
    END_FUNCTION_BLOCK
    """)
    fb = rt.instantiate("B")
    fb.call()
    fb.call_method("Rebind")
    fb.call()
    assert (fb.inspect()["X"], fb.inspect()["Y"]) == (5, 21)


def test_composite_references_keep_descendant_aliases_on_whole_value_assignment():
    rt = Runtime.from_source("""
    TYPE Config : STRUCT value : INT; data : ARRAY[-1..1] OF INT; END_STRUCT END_TYPE
    PROGRAM Main
    VAR a, b : Config; r : REFERENCE TO Config; item : REFERENCE TO INT;
        arrayRef : REFERENCE TO ARRAY[-1..1] OF INT; result : INT; END_VAR
    r REF= a; item REF= r.data[0]; arrayRef REF= r.data;
    b.value := 4; b.data[0] := 6; r := b; item := item + 3;
    result := Read(r.value) + Sum(arrayRef) + LOWER_BOUND(arrayRef, 1) + UPPER_BOUND(arrayRef, 1);
    END_PROGRAM
    FUNCTION Read : INT VAR_INPUT n : INT; END_VAR Read := n; END_FUNCTION
    FUNCTION Sum : INT VAR_IN_OUT values : ARRAY[*] OF INT; END_VAR
    VAR i : INT; END_VAR
    FOR i := LOWER_BOUND(values, 1) TO UPPER_BOUND(values, 1) DO Sum := Sum + values[i]; END_FOR;
    END_FUNCTION
    """)
    rt.scan("Main")
    assert rt.program_cell("Main", "result").value == 13
    assert rt.program_cell("Main", "a").value["DATA"] == (0, 9, 0)
    assert rt.program_cell("Main", "b").value["DATA"] == (0, 6, 0)


def test_global_initializer_and_transient_input_alias_initialization():
    rt = Runtime.from_source("""
    VAR_GLOBAL r : REFERENCE TO INT := data[2]; data : ARRAY[1..2] OF INT := [1, 7]; END_VAR
    FUNCTION Change : INT
    VAR_INPUT initial : INT; END_VAR
    VAR_IN_OUT target : INT; END_VAR
    VAR localRef : REFERENCE TO INT := initial; alias : REFERENCE TO INT := target; END_VAR
    localRef := localRef + 1; alias := localRef; r := r + 1; Change := r;
    END_FUNCTION
    """)
    cell = rt.cell("INT", 0)
    assert rt.call("Change", initial=4, target=cell).value == 8
    assert cell.value == 5


@pytest.mark.parametrize(
    "declaration,invocation",
    [
        ("FUNCTION Escape : INT VAR x : INT; END_VAR held REF= x; END_FUNCTION", "function"),
        (
            "FUNCTION_BLOCK B METHOD Escape VAR x : INT; END_VAR held REF= x; END_METHOD END_FUNCTION_BLOCK",
            "method",
        ),
        (
            "FUNCTION_BLOCK B PROPERTY Escape : INT GET VAR x : INT; END_VAR held REF= x; END_GET END_PROPERTY END_FUNCTION_BLOCK",
            "get",
        ),
        (
            "FUNCTION_BLOCK B PROPERTY Escape : INT SET VAR x : INT; END_VAR held REF= x; END_SET END_PROPERTY END_FUNCTION_BLOCK",
            "set",
        ),
        ("FUNCTION_BLOCK B VAR_TEMP x : INT; END_VAR held REF= x; END_FUNCTION_BLOCK", "fb"),
        ("PROGRAM Escape VAR_TEMP x : INT; END_VAR held REF= x; END_PROGRAM", "program"),
    ],
)
@pytest.mark.parametrize("use", ["Read", "Write", "Copy", "Clear"])
def test_transient_targets_expire_without_extending_lifetime(declaration, invocation, use):
    rt = Runtime.from_source(
        """
    VAR_GLOBAL held : REFERENCE TO INT; END_VAR
    FUNCTION Valid : BOOL Valid := __ISVALIDREF(held); END_FUNCTION
    FUNCTION Read : INT Read := held; END_FUNCTION
    FUNCTION Write : INT held := 3; END_FUNCTION
    FUNCTION Copy : INT VAR r : REFERENCE TO INT; END_VAR r REF= held; END_FUNCTION
    FUNCTION Clear : BOOL held REF= 0; Clear := __ISVALIDREF(held); END_FUNCTION
    """
        + declaration
    )
    if invocation == "function":
        rt.call("Escape")
    elif invocation == "program":
        rt.scan("Escape")
    else:
        fb = rt.instantiate("B")
        if invocation == "method":
            fb.call_method("Escape")
        elif invocation == "get":
            fb.get_property("Escape")
        elif invocation == "set":
            fb.set_property("Escape", 1)
        else:
            fb.call()
    assert rt.call("Valid").value is False
    if use == "Clear":
        assert rt.call(use).value is False
    else:
        with pytest.raises(ExecutionError, match="Expired"):
            rt.call(use)


def test_nested_cells_expire_and_var_inst_cells_persist():
    rt = Runtime.from_source("""
    TYPE S : STRUCT data : ARRAY[1..2] OF INT; END_STRUCT END_TYPE
    VAR_GLOBAL held : REFERENCE TO INT; END_VAR
    FUNCTION Valid : BOOL Valid := __ISVALIDREF(held); END_FUNCTION
    FUNCTION_BLOCK B
    METHOD Save VAR_INST s : S; r : REFERENCE TO INT := s.data[2]; END_VAR
    r := r + 1; held REF= r;
    END_METHOD
    END_FUNCTION_BLOCK
    FUNCTION Escape : INT VAR b : B; END_VAR b.Save(); END_FUNCTION
    """)
    fb = rt.instantiate("B")
    fb.call_method("Save")
    fb.call_method("Save")
    assert fb.inspect()["$VAR_INST"]["SAVE"]["S"]["DATA"] == (0, 2)
    assert rt.call("Valid").value is True
    rt.call("Escape")
    assert rt.call("Valid").value is False


def test_inout_reference_escape_retains_actual_cell_lifetime():
    rt = Runtime.from_source("""
    VAR_GLOBAL held : REFERENCE TO INT; END_VAR
    FUNCTION Save : INT VAR_IN_OUT x : INT; END_VAR held REF= x; END_FUNCTION
    FUNCTION Read : INT Read := held; END_FUNCTION
    """)
    cell = rt.cell("INT", 4)
    rt.call("Save", x=cell)
    cell.value = 7
    assert rt.call("Read").value == 7


def test_python_rejection_is_atomic_for_calls_and_setters():
    source = """
    VAR_GLOBAL CONSTANT fixed : INT := 1; END_VAR
    FUNCTION_BLOCK B
    VAR_INPUT ref : REFERENCE TO INT; n : INT; END_VAR
    IF __ISVALIDREF(ref) THEN ref := ref + n; END_IF;
    END_FUNCTION_BLOCK
    """
    rt, foreign = Runtime.from_source(source), Runtime.from_source(source)
    fb = rt.instantiate("B")
    first, second = rt.cell("INT", 1), rt.cell("INT", 20)
    fb.call(ref=first, n=2)
    for bad in (
        True,
        False,
        None,
        1,
        rt.cell("DINT", 0),
        foreign.cell("INT", 0),
        first.bit(0),
        rt.global_cell("GVL", "fixed"),
    ):
        with pytest.raises(ArgumentError):
            fb.call(n=9, ref=bad)
        with pytest.raises(ArgumentError):
            fb.set_input("ref", bad)
    with pytest.raises(ArgumentError):
        fb.call(ref=second, n=True)
    fb.call()
    assert (first.value, second.value, fb.inspect()["N"]) == (5, 20, 2)


def test_expired_python_cell_rejected_and_passive_snapshot_remains_readable():
    rt = Runtime.from_source("""
    FUNCTION_BLOCK B VAR_INPUT ref : REFERENCE TO INT; END_VAR END_FUNCTION_BLOCK
    VAR_GLOBAL b : B; END_VAR
    FUNCTION Save : INT VAR data : ARRAY[1..2] OF INT := [3,4]; END_VAR b(ref := data[2]); END_FUNCTION
    """)
    rt.call("Save")
    fb = rt.global_fb("GVL", "b")
    escaped = fb._frame.slots["REF"].target
    assert escaped.value == 4
    assert fb.inspect()["REF"] == {"reference": "INT", "target": "INT", "valid": False}
    with pytest.raises(ArgumentError, match="Expired"):
        fb.set_input("ref", escaped)
    fb.set_input("ref", 0)
    fb.call()


def test_null_default_inputs_and_reference_interface_method_contract():
    rt = Runtime.from_source("""
    INTERFACE I METHOD Put : INT VAR_INPUT ref : REFERENCE TO INT := 0; END_VAR END_METHOD END_INTERFACE
    FUNCTION_BLOCK B IMPLEMENTS I
    METHOD Put : INT VAR_INPUT ref : REFERENCE TO INT := 0; END_VAR
    IF __ISVALIDREF(ref) THEN ref := ref + 1; Put := ref; END_IF;
    END_METHOD END_FUNCTION_BLOCK
    FUNCTION Optional : BOOL VAR_INPUT ref : REFERENCE TO INT := 0; END_VAR Optional := __ISVALIDREF(ref); END_FUNCTION
    PROGRAM Main VAR b : B; iface : I; x : INT; result : INT; END_VAR
    iface := b; result := iface.Put(x);
    END_PROGRAM
    """)
    assert rt.call("Optional").value is False
    assert rt.instantiate("B").call_method("Put").value == 0
    rt.scan("Main")
    assert rt.program_cell("Main", "result").value == 1


def test_persistent_reference_input_initializer_and_inherited_bindings():
    rt = Runtime.from_source("""
    FUNCTION_BLOCK Base
    VAR_INPUT ref : REFERENCE TO INT := own; END_VAR
    VAR own : INT := 3; END_VAR
    METHOD Read : INT Read := THIS^.ref; END_METHOD
    END_FUNCTION_BLOCK
    FUNCTION_BLOCK Derived EXTENDS Base
    VAR other : INT := 10; END_VAR
    METHOD Rebind SUPER^.ref REF= other; END_METHOD
    END_FUNCTION_BLOCK
    PROGRAM Main VAR b : Derived; value : INT := 8; END_VAR b.ref REF= value; b.ref := 9; END_PROGRAM
    """)
    fb = rt.instantiate("Derived")
    assert fb.call_method("Read").value == 3
    fb.call_method("Rebind")
    fb.call()
    assert fb.call_method("Read").value == 10
    rt.scan("Main")
    assert rt.program_cell("Main", "value").value == 9


def test_python_fields_elements_and_transparent_alias_targets():
    rt = Runtime.from_source("""
    TYPE Count : INT; Config : STRUCT x : Count; data : ARRAY[-1..1] OF INT; END_STRUCT END_TYPE
    FUNCTION Set : INT VAR_INPUT ref : REFERENCE TO Count; END_VAR ref := 7; Set := ref; END_FUNCTION
    FUNCTION_BLOCK B METHOD Set VAR_INPUT ref : REFERENCE TO INT; END_VAR ref := 8; END_METHOD END_FUNCTION_BLOCK
    """)
    cell = rt.cell("Config", {})
    assert rt.call("Set", ref=cell.field("x")).value == 7
    rt.instantiate("B").call_method("Set", ref=cell.field("data").element(0))
    assert cell.value["X"] == 7
    assert cell.value["DATA"] == (0, 8, 0)


def test_reference_destination_is_captured_before_rhs_rebinding():
    rt = Runtime.from_source("""
    VAR_GLOBAL first, second : INT; ref : REFERENCE TO INT; END_VAR
    FUNCTION Switch : INT ref REF= second; Switch := 7; END_FUNCTION
    PROGRAM Main ref REF= first; ref := Switch(); END_PROGRAM
    """)
    rt.scan("Main")
    assert rt.global_cell("GVL", "first").value == 7
    assert rt.global_cell("GVL", "second").value == 0


def test_reference_rhs_index_is_evaluated_once_and_copied_binding_is_independent():
    rt = Runtime.from_source("""
    VAR_GLOBAL hits : INT; END_VAR
    FUNCTION Index : INT hits := hits + 1; Index := 2; END_FUNCTION
    PROGRAM Main VAR a : ARRAY[1..2] OF INT; r, copy : REFERENCE TO INT; END_VAR
    r REF= a[Index()]; copy REF= r; r REF= a[1]; copy := 9; r := 4;
    END_PROGRAM
    """)
    rt.scan("Main")
    assert rt.program_cell("Main", "a").value == (4, 9)
    assert rt.global_cell("GVL", "hits").value == 1


def test_escaped_target_expires_on_fault_but_snapshots_remain_detached():
    rt = Runtime.from_source("""
    FUNCTION_BLOCK B VAR_INPUT ref : REFERENCE TO INT; END_VAR END_FUNCTION_BLOCK
    VAR_GLOBAL b : B; END_VAR
    FUNCTION Escape : INT VAR x : INT := 4; END_VAR b(ref := x); Escape := 1 / 0; END_FUNCTION
    """)
    fb = rt.global_fb("GVL", "b")
    with pytest.raises(ExecutionError):
        rt.call("Escape")
    snapshot = fb.inspect()
    assert snapshot["REF"]["valid"] is False
    snapshot["REF"]["valid"] = True
    assert fb.inspect()["REF"]["valid"] is False
    assert fb._frame.slots["REF"].target.value == 4


def test_reference_temporary_initializer_rebinds_each_invocation():
    rt = Runtime.from_source("""
    FUNCTION_BLOCK B VAR_INPUT input : INT; END_VAR VAR_OUTPUT seen : INT; END_VAR
    VAR_TEMP r : REFERENCE TO INT := input; END_VAR
    seen := r; r REF= 0;
    END_FUNCTION_BLOCK
    """)
    fb = rt.instantiate("B")
    fb.call(input=4)
    assert fb.output("seen") == 4
    fb.call(input=9)
    assert fb.output("seen") == 9


def test_initializer_execution_failure_faults_existing_runtime():
    rt = Runtime.from_source("""
    FUNCTION_BLOCK B VAR data : ARRAY[1..2] OF INT; r : REFERENCE TO INT := data[3]; END_VAR END_FUNCTION_BLOCK
    """)
    with pytest.raises(ExecutionError):
        rt.instantiate("B")
    with pytest.raises(RuntimeFaultedError):
        rt.instantiate("B")


def test_inherited_initializer_keeps_declaration_scope_when_derived_field_shadows_global():
    rt = Runtime.from_source("""
    VAR_GLOBAL shared : INT := 3; END_VAR
    FUNCTION_BLOCK Base VAR r : REFERENCE TO INT := shared; END_VAR
    METHOD Read : INT Read := r; END_METHOD END_FUNCTION_BLOCK
    FUNCTION_BLOCK Derived EXTENDS Base VAR shared : INT := 99; END_VAR END_FUNCTION_BLOCK
    """)
    assert rt.instantiate("Derived").call_method("Read").value == 3


def test_super_input_rebinding_remains_live_after_base_body_returns():
    rt = Runtime.from_source("""
    FUNCTION_BLOCK Base VAR_INPUT ref : REFERENCE TO INT; END_VAR ref := ref + 1; END_FUNCTION_BLOCK
    FUNCTION_BLOCK Derived EXTENDS Base
    VAR other : INT := 10; END_VAR
    VAR_OUTPUT plain, explicit_this, explicit_super : INT; END_VAR
    SUPER^(ref := other);
    plain := ref; explicit_this := THIS^.ref; explicit_super := SUPER^.ref;
    ref := ref + 1;
    END_FUNCTION_BLOCK
    """)
    fb, cell = rt.instantiate("Derived"), rt.cell("INT", 2)
    fb.call(ref=cell)
    assert [fb.output(name) for name in ("plain", "explicit_this", "explicit_super")] == [
        11,
        11,
        11,
    ]
    assert fb.inspect()["OTHER"] == 12
    assert cell.value == 2


def test_property_header_reference_initializer_runs_after_setter_input():
    rt = Runtime.from_source("""
    FUNCTION_BLOCK B VAR_OUTPUT saved : INT; END_VAR
    PROPERTY Value : INT
    VAR r : REFERENCE TO INT := saved; END_VAR
    GET Value := r; END_GET
    SET r := Value; END_SET
    END_PROPERTY END_FUNCTION_BLOCK
    """)
    fb = rt.instantiate("B")
    fb.set_property("Value", 7)
    assert fb.get_property("Value") == 7


@pytest.mark.parametrize(
    "kind,initial,expression,expected",
    [
        ("BOOL", False, "NOT ref", True),
        ("STRING(5)", "ab", "'xy'", "xy"),
        ("TIME", 4, "ref + T#1ms", 5),
        ("REAL", 0.5, "ref + REAL#0.25", 0.75),
        ("LREAL", 0.5, "ref + LREAL#0.25", 0.75),
    ],
)
def test_reference_inputs_preserve_scalar_value_semantics(kind, initial, expression, expected):
    rt = Runtime.from_source(f"""
    FUNCTION Change : {kind} VAR_INPUT ref : REFERENCE TO {kind}; END_VAR
    ref := {expression}; Change := ref; END_FUNCTION
    """)
    cell = rt.cell(kind, initial)
    assert rt.call("Change", ref=cell).value == expected
    assert cell.value == expected


def test_enum_reference_binding_preserves_nominal_values():
    rt = Runtime.from_source("""
    TYPE Mode : (Idle, Run); END_TYPE
    FUNCTION Change : Mode VAR_INPUT ref : REFERENCE TO Mode; END_VAR
    ref := Mode.Run; Change := ref; END_FUNCTION
    """)
    cell = rt.cell("Mode", "Idle")
    assert rt.call("Change", ref=cell).value.name == "RUN"
    assert cell.value.type_name == "MODE"
