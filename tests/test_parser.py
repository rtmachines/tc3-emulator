from dataclasses import FrozenInstanceError

import pytest

from tc_emulator.errors import ParseError, STError
from tc_emulator.parser import parse
from tc_emulator.syntax import Binary, Call, Case, For, If, Literal, Unary, While


def function(body, declarations=""):
    return parse(f"FUNCTION Mixed : DINT\n{declarations}\n{body}\nEND_FUNCTION", "sample.st").pous[
        0
    ]


def test_precedence_names_comments_and_frozen_nodes():
    pou = function("(* outer (* inner *) end *)\n mixed := 1 + 2 * -3; // tail\n")
    assert pou.name == "MIXED"
    expression = pou.body[0].value
    assert isinstance(expression, Binary) and expression.op == "+"
    assert expression.left.value == 1
    assert expression.right.op == "*"
    assert isinstance(expression.right.right, Unary)
    assert expression.right.right.operand.value == 3
    with pytest.raises(FrozenInstanceError):
        pou.name = "OTHER"


def test_declaration_groups_types_and_initializers():
    pou = function(
        "mixed := a;", "VAR_INPUT a, b : dint := -2; END_VAR\nVAR x : BOOL := NOT FALSE; END_VAR"
    )
    assert [(v.name, v.type_name, v.section) for v in pou.variables] == [
        ("A", "DINT", "VAR_INPUT"),
        ("B", "DINT", "VAR_INPUT"),
        ("X", "BOOL", "VAR"),
    ]
    assert pou.variables[0].initial.op == "-"
    assert pou.variables[2].initial.op == "NOT"


def test_all_control_flow_and_nested_case_labels():
    pou = function(
        """IF TRUE THEN
       CASE 2 OF -1, 2: mixed := 4; 3: RETURN; ELSE mixed := 0; END_CASE;
       ELSIF FALSE THEN mixed := 2; ELSE mixed := 3; END_IF;
       FOR i := 1 TO 5 BY 2 DO WHILE FALSE DO EXIT; END_WHILE; END_FOR;
       FOR i := 5 TO 1 DO RETURN; END_FOR;""",
        "VAR i : DINT; END_VAR",
    )
    assert isinstance(pou.body[0], If)
    case = pou.body[0].branches[0][1][0]
    assert isinstance(case, Case) and case.arms[0][0] == (-1, 2)
    assert len(pou.body[0].branches) == 2
    assert isinstance(pou.body[1], For) and pou.body[1].step.value == 2
    assert isinstance(pou.body[1].body[0], While)
    assert isinstance(pou.body[2].step, Literal) and pou.body[2].step.value == 1


def test_calls_references_and_boolean_operator_precedence():
    pou = function("""inst.child(enable := TRUE, count => out);
      mixed := add(1, other(x := 2));
      flag := NOT FALSE AND TRUE XOR FALSE OR 2 < 3;""")
    call = pou.body[0].call
    assert call.target.parts == ("INST", "CHILD")
    assert [(a.name, a.mode) for a in call.arguments] == [("ENABLE", ":="), ("COUNT", "=>")]
    assert isinstance(pou.body[1].value, Call)
    assert pou.body[1].value.arguments[0].name is None
    assert pou.body[2].value.op == "OR"
    assert pou.body[2].value.left.op == "XOR"


def test_multiple_pous():
    program = parse("FUNCTION f : INT f := 1; END_FUNCTION FUNCTION_BLOCK fb END_FUNCTION_BLOCK")
    assert [(p.kind, p.name) for p in program.pous] == [("FUNCTION", "F"), ("FUNCTION_BLOCK", "FB")]


@pytest.mark.parametrize(
    "text",
    [
        "PROGRAM p : INT END_PROGRAM",
        "FUNCTION f END_FUNCTION",
        "FUNCTION f : INT REPEAT UNTIL TRUE END_REPEAT; END_FUNCTION",
        "FUNCTION f : INT f := 2 ** 3; END_FUNCTION",
        "FUNCTION f : INT f := STRING#1; END_FUNCTION",
        "FUNCTION f : INT VAR RETAIN x : INT; END_VAR END_FUNCTION",
        "FUNCTION f : INT (* unclosed",
        "FUNCTION f : INT IF TRUE THEN RETURN; END_FUNCTION",
        "FUNCTION f : INT CASE 1 OF 1..2: RETURN; END_CASE; END_FUNCTION",
    ],
)
def test_unsupported_or_malformed_syntax_is_rejected(text):
    with pytest.raises(ParseError):
        parse(text)


def test_error_has_precise_position_and_stack():
    with pytest.raises(ParseError) as caught:
        parse("FUNCTION f : INT\n f := @;\nEND_FUNCTION", "broken.st")
    assert caught.value.loc.source == "broken.st"
    assert (caught.value.loc.line, caught.value.loc.column) == (2, 7)
    assert "broken.st:2:7" in str(caught.value)
    assert "F -> G" in str(STError("failure", caught.value.loc, ("F", "G")))


@pytest.mark.parametrize("body", ["F := {number};", "CASE 1 OF {number}: RETURN; END_CASE;"])
def test_oversized_decimal_literal_has_source_aware_error(body):
    source = "FUNCTION F : INT\n" + body.format(number="9" * 5000) + "\nEND_FUNCTION"
    with pytest.raises(ParseError) as caught:
        parse(source, "huge.st")
    assert caught.value.loc.source == "huge.st"
    assert caught.value.loc.line == 2


def test_excessive_expression_nesting_has_source_aware_error():
    source = "FUNCTION F : INT\nF := " + "(" * 2000 + "1" + ")" * 2000 + ";\nEND_FUNCTION"
    with pytest.raises(ParseError) as caught:
        parse(source, "nested.st")
    assert caught.value.loc.source == "nested.st"
    assert caught.value.loc.line == 2
