"""One concrete receiver preserves lexical scope across inherited implementations."""

import pytest

from tc_emulator import ArgumentError, ExecutionError, Runtime, RuntimeFaultedError


def test_forward_multilevel_storage_defaults_and_python_contracts():
    rt = Runtime.from_source("""
    FUNCTION_BLOCK C EXTENDS B END_FUNCTION_BLOCK
    FUNCTION_BLOCK B EXTENDS A VAR extra : INT := 9; END_VAR END_FUNCTION_BLOCK
    FUNCTION_BLOCK A
    VAR_INPUT step : INT := 2; END_VAR VAR_OUTPUT n : INT := 3; END_VAR
    VAR child : CTU; END_VAR
    METHOD Add : INT n := n + step; Add := n; END_METHOD
    PROPERTY Value : INT GET Value := n; END_GET SET n := Value; END_SET END_PROPERTY
    END_FUNCTION_BLOCK
    """)
    first, second = rt.instantiate("C"), rt.instantiate("C")
    assert first.output("n") == 3
    first.set_input("step", 4)
    assert first.call_method("Add").value == 7
    assert second.call_method("Add").value == 5
    first.set_property("Value", 11)
    assert first.get_property("Value") == 11
    assert first.fb("child").output("cv") == 0
    assert first.inspect()["EXTRA"] == 9


def test_base_defaults_and_global_fallback_do_not_capture_descendant_names():
    rt = Runtime.from_source("""
    VAR_GLOBAL CONSTANT N : INT := 3; END_VAR
    VAR_GLOBAL score : INT := 7; END_VAR
    FUNCTION_BLOCK A
    VAR_OUTPUT data : ARRAY[1..N] OF INT := [N, N, N]; END_VAR
    METHOD Read : INT
    VAR CONSTANT N : INT := 20; END_VAR
    Read := score + data[3]; END_METHOD
    END_FUNCTION_BLOCK
    FUNCTION_BLOCK B EXTENDS A
    VAR CONSTANT N : INT := 8; END_VAR VAR score : INT := 99; END_VAR
    END_FUNCTION_BLOCK
    """)
    fb = rt.instantiate("B")
    assert fb.output("data") == (3, 3, 3)
    assert fb.call_method("Read").value == 10


def test_derived_body_runs_base_only_when_super_is_explicit():
    rt = Runtime.from_source("""
    FUNCTION_BLOCK A VAR_OUTPUT n : INT; END_VAR n := n + 1; END_FUNCTION_BLOCK
    FUNCTION_BLOCK B EXTENDS A n := n + 10; END_FUNCTION_BLOCK
    FUNCTION_BLOCK C EXTENDS B SUPER^(); n := n + 100; END_FUNCTION_BLOCK
    """)
    fb = rt.instantiate("C")
    fb.call()
    assert fb.output("n") == 110


def test_base_private_helper_and_virtual_protected_hook_on_grandchild():
    rt = Runtime.from_source("""
    FUNCTION_BLOCK A
    METHOD PRIVATE Secret : INT Secret := 3; END_METHOD
    METHOD PROTECTED Hook : INT Hook := 1; END_METHOD
    METHOD Run : INT Run := Secret() + THIS^.Hook(); END_METHOD
    END_FUNCTION_BLOCK
    FUNCTION_BLOCK B EXTENDS A
    METHOD PROTECTED Hook : INT Hook := SUPER^.Hook() + 10; END_METHOD
    END_FUNCTION_BLOCK
    FUNCTION_BLOCK C EXTENDS B END_FUNCTION_BLOCK
    """)
    fb = rt.instantiate("C")
    assert fb.call_method("Run").value == 14
    for name in ("Hook", "Secret"):
        with pytest.raises(ArgumentError):
            fb.call_method(name)


def test_override_and_base_var_inst_banks_are_distinct_and_shared_across_paths():
    rt = Runtime.from_source("""
    FUNCTION_BLOCK A
    METHOD M : INT VAR_INST n : INT; END_VAR n := n + 1; M := n; END_METHOD
    END_FUNCTION_BLOCK
    FUNCTION_BLOCK B EXTENDS A
    METHOD M : INT VAR_INST n : INT; END_VAR n := n + 10; M := n; END_METHOD
    METHOD Base : INT Base := SUPER^.M(); END_METHOD
    METHOD Both : INT Both := SUPER^.M() + THIS^.M(); END_METHOD
    END_FUNCTION_BLOCK
    """)
    fb = rt.instantiate("B")
    assert fb.call_method("Base").value == 1
    assert fb.call_method("M").value == 10
    assert fb.call_method("Both").value == 22
    assert fb.call_method("Base").value == 3
    assert fb.inspect()["$VAR_INST"] == {"A.M": {"N": 3}, "B.M": {"N": 20}}


def test_interface_dispatch_inherits_contract_and_uses_overrides_and_properties():
    rt = Runtime.from_source("""
    INTERFACE I METHOD Read : INT END_METHOD
    PROPERTY P : INT GET END_GET SET END_SET END_PROPERTY END_INTERFACE
    FUNCTION_BLOCK A IMPLEMENTS I VAR n : INT; END_VAR
    METHOD Read : INT Read := P; END_METHOD
    PROPERTY P : INT GET P := n; END_GET SET n := P; END_SET END_PROPERTY
    END_FUNCTION_BLOCK
    FUNCTION_BLOCK B EXTENDS A
    PROPERTY P : INT GET P := SUPER^.P + 10; END_GET
    SET SUPER^.P := P; END_SET END_PROPERTY END_FUNCTION_BLOCK
    FUNCTION Use : INT VAR_INPUT ref : I; END_VAR ref.P := 5; Use := ref.Read(); END_FUNCTION
    """)
    fb = rt.instantiate("B")
    assert rt.call("Use", ref=fb).value == 15
    assert fb.get_property("P") == 15
    with pytest.raises(ArgumentError):
        rt.call(
            "Use",
            ref=Runtime.from_source("FUNCTION_BLOCK Other END_FUNCTION_BLOCK").instantiate("Other"),
        )


def test_base_temporary_nested_interface_expires_but_persistent_state_survives():
    rt = Runtime.from_source("""
    INTERFACE I METHOD Ping : INT END_METHOD END_INTERFACE
    FUNCTION_BLOCK Leaf IMPLEMENTS I METHOD Ping : INT Ping := 1; END_METHOD END_FUNCTION_BLOCK
    VAR_GLOBAL saved : I; END_VAR
    FUNCTION_BLOCK A VAR_OUTPUT n : INT; END_VAR VAR_TEMP leaf : Leaf; END_VAR
    n := n + 1; saved := leaf; END_FUNCTION_BLOCK
    FUNCTION_BLOCK B EXTENDS A SUPER^(); END_FUNCTION_BLOCK
    FUNCTION Read : INT Read := saved.Ping(); END_FUNCTION
    """)
    fb = rt.instantiate("B")
    fb.call()
    fb.call()
    assert fb.output("n") == 2
    with pytest.raises(ExecutionError, match="Expired"):
        rt.call("Read")
    with pytest.raises(RuntimeFaultedError):
        fb.call()


def test_super_constants_resolve_bounds_and_defaults_in_the_lexical_base():
    rt = Runtime.from_source("""
    FUNCTION_BLOCK B EXTENDS A
    VAR_OUTPUT data : ARRAY[1..SUPER^.N] OF INT := [SUPER^.N, SUPER^.N]; END_VAR
    METHOD Read : INT VAR_INST initial : INT := SUPER^.N; END_VAR
    VAR CONSTANT N : INT := 20; END_VAR Read := initial + THIS^.N; END_METHOD
    END_FUNCTION_BLOCK
    FUNCTION_BLOCK A VAR CONSTANT N : INT := 2; END_VAR END_FUNCTION_BLOCK
    """)
    fb = rt.instantiate("B")
    assert fb.output("data") == (2, 2)
    assert fb.call_method("Read").value == 4


def test_inherited_owner_constant_wins_over_method_local_for_var_inst_defaults():
    rt = Runtime.from_source("""
    FUNCTION_BLOCK A VAR CONSTANT N : INT := 4; END_VAR
    METHOD Read : INT VAR_INST initial : INT := N; END_VAR
    VAR CONSTANT N : INT := 20; END_VAR Read := initial; END_METHOD END_FUNCTION_BLOCK
    FUNCTION_BLOCK B EXTENDS A END_FUNCTION_BLOCK
    """)
    assert rt.instantiate("B").call_method("Read").value == 4


def test_inherited_timers_nested_arrays_and_instances_are_independent():
    rt = Runtime.from_source("""
    FUNCTION_BLOCK A VAR timer : TON; children : ARRAY[2..3] OF CTU; END_VAR
    METHOD Wait : TIME timer(IN := TRUE, PT := T#20ms); Wait := timer.ET; END_METHOD
    END_FUNCTION_BLOCK
    FUNCTION_BLOCK B EXTENDS A END_FUNCTION_BLOCK
    PROGRAM Main VAR items : ARRAY[1..2] OF B; END_VAR END_PROGRAM
    """)
    first, second = rt.program_fb("Main", "items", 1), rt.program_fb("Main", "items", 2)
    assert first.call_method("Wait").value == 0
    rt.advance_time(7)
    assert first.call_method("Wait").value == 7
    assert second.call_method("Wait").value == 0
    first.fb("children", 3).call(CU=True, RESET=False, PV=5)
    assert first.fb("children", 3).output("CV") == 1
    assert first.fb("children", 2).output("CV") == 0
    assert second.fb("children", 3).output("CV") == 0


def test_each_super_body_has_separate_temp_and_inherited_inout_cells():
    rt = Runtime.from_source("""
    FUNCTION_BLOCK A
    VAR_IN_OUT value : INT; END_VAR VAR_OUTPUT n : INT; END_VAR
    VAR_TEMP base_temp : INT := 2; END_VAR
    THIS^.base_temp := THIS^.base_temp + 1;
    value := value + base_temp; n := n + 1;
    END_FUNCTION_BLOCK
    FUNCTION_BLOCK B EXTENDS A VAR_TEMP child_temp : INT := 10; END_VAR
    child_temp := child_temp + 1;
    SUPER^(value := value); SUPER^(value := value); value := value + child_temp;
    END_FUNCTION_BLOCK
    """)
    fb, cell = rt.instantiate("B"), rt.cell("INT", 0)
    fb.call(value=cell)
    assert cell.value == 17
    fb.call(value=cell)
    assert cell.value == 34
    assert fb.output("n") == 4


def test_python_arguments_are_checked_before_mutating_inherited_state():
    rt = Runtime.from_source("""
    FUNCTION_BLOCK A VAR_INPUT x : INT := 2; y : INT := 3; END_VAR
    VAR_OUTPUT n : INT; END_VAR n := x + y;
    METHOD Add : INT VAR_INPUT delta : INT; END_VAR n := n + delta; Add := n; END_METHOD
    END_FUNCTION_BLOCK FUNCTION_BLOCK B EXTENDS A SUPER^(); END_FUNCTION_BLOCK
    """)
    fb = rt.instantiate("B")
    with pytest.raises(ArgumentError):
        fb.call(x=10, y=100000)
    assert fb.inspect()["X"] == 2
    with pytest.raises(ArgumentError):
        fb.call_method("Add", delta=100000)
    assert fb.output("n") == 0
    fb.call()
    assert fb.output("n") == 5


def test_base_global_function_and_enum_names_are_not_captured_by_derived_fields():
    rt = Runtime.from_source("""
    TYPE E : (Ready := 4); END_TYPE
    FUNCTION Read : INT Read := 7; END_FUNCTION
    FUNCTION_BLOCK A METHOD Run : INT VAR evalue : E; END_VAR
    evalue := E.Ready; Run := Read(); END_METHOD END_FUNCTION_BLOCK
    FUNCTION_BLOCK B EXTENDS A VAR Read, E : INT; END_VAR END_FUNCTION_BLOCK
    """)
    assert rt.instantiate("B").call_method("Run").value == 7


@pytest.mark.parametrize(
    "limits,match", [({"max_steps": 1}, "budget"), ({"max_call_depth": 1}, "depth")]
)
def test_super_reuses_execution_limits_and_fault_latch(limits, match):
    rt = Runtime.from_source(
        """
    FUNCTION_BLOCK A VAR_OUTPUT n : INT; END_VAR n := n + 1; END_FUNCTION_BLOCK
    FUNCTION_BLOCK B EXTENDS A SUPER^(); END_FUNCTION_BLOCK
    """,
        **limits,
    )
    fb = rt.instantiate("B")
    with pytest.raises(ExecutionError, match=match):
        fb.call()
    with pytest.raises(RuntimeFaultedError):
        fb.call()


def test_base_body_and_properties_dispatch_overrides_with_original_receiver():
    rt = Runtime.from_source("""
    FUNCTION_BLOCK A VAR_OUTPUT n : INT; END_VAR n := Hook() + P;
    METHOD PROTECTED Hook : INT Hook := 1; END_METHOD
    PROPERTY P : INT GET P := 2; END_GET SET n := P; END_SET END_PROPERTY
    END_FUNCTION_BLOCK
    FUNCTION_BLOCK B EXTENDS A SUPER^();
    METHOD PROTECTED Hook : INT Hook := 10; END_METHOD
    PROPERTY P : INT GET P := 20; END_GET SET SUPER^.P := P + 1; END_SET END_PROPERTY
    END_FUNCTION_BLOCK
    """)
    fb = rt.instantiate("B")
    fb.call()
    assert fb.output("n") == 30
    fb.set_property("P", 40)
    assert fb.output("n") == 41


def test_super_method_uses_base_default_and_preserves_output_inout_binding():
    rt = Runtime.from_source("""
    FUNCTION_BLOCK A
    METHOD M : INT
    VAR_INPUT amount : INT := 2; END_VAR VAR_IN_OUT value : INT; END_VAR
    VAR_OUTPUT copied : INT; END_VAR value := value + amount; copied := value; M := value;
    END_METHOD END_FUNCTION_BLOCK
    FUNCTION_BLOCK B EXTENDS A
    METHOD M : INT
    VAR_INPUT amount : INT := 2; END_VAR VAR_IN_OUT value : INT; END_VAR
    VAR_OUTPUT copied : INT; END_VAR
    M := SUPER^.M(value := value, copied => copied);
    END_METHOD END_FUNCTION_BLOCK
    """)
    fb, cell = rt.instantiate("B"), rt.cell("INT", 3)
    result = fb.call_method("M", value=cell)
    assert (result.value, result.outputs["copied"], cell.value) == (5, 5, 5)


def test_inherited_interface_null_checks_precede_argument_and_property_rhs_effects():
    source = """
    INTERFACE I METHOD M : INT VAR_INPUT n : INT; END_VAR END_METHOD
    PROPERTY P : INT SET END_SET END_PROPERTY END_INTERFACE
    FUNCTION_BLOCK A VAR ref : I; END_VAR
    METHOD Run : INT Run := ref.M(Side()); END_METHOD
    METHOD Set ref.P := Side(); END_METHOD END_FUNCTION_BLOCK
    FUNCTION_BLOCK B EXTENDS A END_FUNCTION_BLOCK
    VAR_GLOBAL count : INT; END_VAR
    FUNCTION Side : INT count := count + 1; Side := 1; END_FUNCTION
    """
    for name in ("Run", "Set"):
        rt = Runtime.from_source(source)
        with pytest.raises(ExecutionError, match="Null"):
            rt.instantiate("B").call_method(name)
        assert rt.global_cell("GVL", "count").value == 0


def test_inherited_public_property_with_protected_setter_remains_read_only_to_python():
    rt = Runtime.from_source("""
    FUNCTION_BLOCK A VAR n : INT; END_VAR
    PROPERTY P : INT GET P := n; END_GET SET PROTECTED n := P; END_SET END_PROPERTY
    END_FUNCTION_BLOCK
    FUNCTION_BLOCK B EXTENDS A METHOD Set P := 5; END_METHOD END_FUNCTION_BLOCK
    """)
    fb = rt.instantiate("B")
    fb.call_method("Set")
    assert fb.get_property("P") == 5
    with pytest.raises(ArgumentError, match="PROTECTED"):
        fb.set_property("P", 9)


def test_super_rebinding_inout_is_live_for_all_body_reads_and_writes():
    rt = Runtime.from_source("""
    FUNCTION_BLOCK A VAR_IN_OUT value : INT; END_VAR value := value + 1; END_FUNCTION_BLOCK
    FUNCTION_BLOCK B EXTENDS A
    VAR other : INT := 10; END_VAR
    VAR_OUTPUT plain, explicit_this, explicit_super, after_plain, after_this : INT; END_VAR
    SUPER^(value := other);
    plain := value; explicit_this := THIS^.value; explicit_super := SUPER^.value;
    value := value + 1; after_plain := SUPER^.value;
    THIS^.value := THIS^.value + 1; after_this := value;
    SUPER^.value := SUPER^.value + 1;
    END_FUNCTION_BLOCK
    """)
    fb, original = rt.instantiate("B"), rt.cell("INT", 2)
    fb.call(value=original)
    assert (fb.output("plain"), fb.output("explicit_this"), fb.output("explicit_super")) == (
        11,
        11,
        11,
    )
    assert (fb.output("after_plain"), fb.output("after_this")) == (12, 13)
    assert fb.inspect()["VALUE"] == fb.inspect()["OTHER"] == 14
    assert original.value == 2


def test_nested_super_rebinding_updates_suspended_descendant_activations():
    rt = Runtime.from_source("""
    FUNCTION_BLOCK A VAR_IN_OUT value : INT; END_VAR value := value + 1; END_FUNCTION_BLOCK
    FUNCTION_BLOCK B EXTENDS A VAR other : INT := 10; END_VAR
    VAR_TEMP base_temp : INT := 20; END_VAR
    VAR_OUTPUT middle : INT; END_VAR
    SUPER^(value := other); value := value + 1; middle := value + THIS^.base_temp;
    END_FUNCTION_BLOCK
    FUNCTION_BLOCK C EXTENDS B VAR_TEMP child_temp : INT := 30; END_VAR
    VAR_OUTPUT plain, explicit_this, explicit_super : INT; END_VAR
    SUPER^(value := value);
    plain := value; explicit_this := THIS^.value; explicit_super := SUPER^.value;
    value := value + child_temp;
    END_FUNCTION_BLOCK
    """)
    fb, original = rt.instantiate("C"), rt.cell("INT", 2)
    fb.call(value=original)
    assert (fb.output("plain"), fb.output("explicit_this"), fb.output("explicit_super")) == (
        12,
        12,
        12,
    )
    assert fb.output("middle") == 32
    assert fb.inspect()["VALUE"] == fb.inspect()["OTHER"] == 42
    assert original.value == 2
