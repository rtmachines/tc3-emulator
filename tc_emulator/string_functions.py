"""Pure Latin-1 STRING operations and strict basic text conversions."""

from __future__ import annotations

import re

from .types import INTEGER_TYPES, StringType, TypeSpec, Value, check_value

TEXT_TYPE = StringType(255)
PARAMETERS = {
    "LEN": ("STR",),
    "LEFT": ("STR", "SIZE"),
    "RIGHT": ("STR", "SIZE"),
    "MID": ("STR", "LEN", "POS"),
    "CONCAT": ("STR1", "STR2"),
    "FIND": ("STR1", "STR2"),
    "INSERT": ("STR1", "STR2", "POS"),
    "DELETE": ("STR", "LEN", "POS"),
    "REPLACE": ("STR1", "STR2", "L", "P"),
}
_TEXT_PARAMETERS = frozenset({"STR", "STR1", "STR2"})
_DECIMAL = re.compile(r"[+-]?[0-9]+(?:_[0-9]+)*\Z")


def infer_result(name: str, types: tuple[TypeSpec, ...]) -> TypeSpec:
    """Check the text signature and return its scalar result type."""
    parameters = PARAMETERS[name]
    if len(types) != len(parameters):
        raise ValueError(f"{name} requires {len(parameters)} inputs")
    for parameter, kind in zip(parameters, types):
        if parameter in _TEXT_PARAMETERS:
            if not isinstance(kind, StringType):
                raise TypeError(f"{name} {parameter} requires STRING input")
        elif kind not in INTEGER_TYPES | {"INTEGER"}:
            raise TypeError(f"{name} {parameter} requires an integer input")
    return "INT" if name in {"LEN", "FIND"} else TEXT_TYPE


def evaluate(name: str, values: tuple[Value, ...]) -> Value:
    """Apply STRING(255) argument/result storage and checked INT positions."""
    checked = []
    for parameter, value in zip(PARAMETERS[name], values):
        if parameter in _TEXT_PARAMETERS:
            checked.append(check_value(TEXT_TYPE, value))
        else:
            value = check_value("INT", value)
            minimum = 1 if parameter in {"POS", "P"} and name != "INSERT" else 0
            if value < minimum:
                raise ValueError(f"{name} {parameter} must be at least {minimum}")
            checked.append(value)
    text = checked[0]
    if name == "LEN":
        return len(text)
    if name == "LEFT":
        result = text[: checked[1]]
    elif name == "RIGHT":
        result = text[-checked[1] :] if checked[1] else ""
    elif name == "MID":
        size, position = checked[1:]
        result = text[position - 1 : position - 1 + size]
    elif name == "CONCAT":
        result = text + checked[1]
    elif name == "FIND":
        return text.find(checked[1]) + 1
    elif name == "INSERT":
        addition, position = checked[1:]
        result = text[:position] + addition + text[position:]
    elif name == "DELETE":
        size, position = checked[1:]
        result = text[: position - 1] + text[position - 1 + size :]
    else:
        addition, size, position = checked[1:]
        result = text[: position - 1] + addition + text[position - 1 + size :]
    return check_value(TEXT_TYPE, result)


def to_string(value: Value) -> str:
    """Format supported checked BOOL/integer values, or copy text storage."""
    if type(value) is bool:
        result = "TRUE" if value else "FALSE"
    elif type(value) is int:
        result = str(value)
    elif isinstance(value, str):
        result = value
    else:
        raise TypeError("TO_STRING requires BOOL, integer or STRING input")
    return check_value(TEXT_TYPE, result)


def from_string(value: str, target: str) -> Value:
    """Parse a complete ASCII decimal without Python's large-int text limit."""
    if target == "BOOL":
        return value in {"TRUE", "true"}
    if target not in INTEGER_TYPES:
        raise TypeError("STRING conversion requires BOOL or integer destination")
    if _DECIMAL.fullmatch(value) is None:
        raise ValueError("STRING integer conversion requires complete decimal digits")
    negative = value.startswith("-")
    digits = value.lstrip("+-").replace("_", "").lstrip("0")
    # Every supported destination has at most ten significant decimal digits.
    if len(digits) > 10:
        raise ValueError(f"STRING integer value is outside {target} range")
    integer = int(digits or "0")
    return check_value(target, -integer if negative else integer)
