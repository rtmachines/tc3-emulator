"""Pure checked operators and explicit PLC scalar conversions."""

from __future__ import annotations

from . import string_functions
from .bitwise import bitwise_result_type, shift_value
from .syntax import Argument
from .types import (
    INTEGER_TYPES,
    NUMERIC_TYPES,
    ArrayType,
    EnumType,
    EnumValue,
    StringType,
    StructType,
    TypeSpec,
    Value,
    canonical_type,
    check_value,
    checked_integer,
    numeric_type,
    same_type,
)

_SHIFTS = frozenset({"SHL", "SHR", "ROL", "ROR"})
_OPERATORS = frozenset({"ABS", "MIN", "MAX", "LIMIT", "SEL", "MUX"}) | _SHIFTS
_CONVERSION_TYPES = frozenset(
    {
        "BOOL",
        "INT",
        "UINT",
        "DINT",
        "UDINT",
        "BYTE",
        "WORD",
        "DWORD",
        "REAL",
        "LREAL",
        "TIME",
        "STRING",
    }
)


def _conversion(name: str) -> tuple[str | None, str] | None:
    if name.startswith("TO_") and name[3:] in _CONVERSION_TYPES:
        return None, name[3:]
    source, separator, target = name.partition("_TO_")
    if separator and source in _CONVERSION_TYPES and target in _CONVERSION_TYPES:
        if "STRING" in {source, target}:
            other = target if source == "STRING" else source
            if other not in INTEGER_TYPES | {"BOOL", "STRING"}:
                return None
        return source, target
    return None


def is_standard_function(name: str) -> bool:
    """Recognize exact uppercase standard names, including supported converters."""
    return (
        name in _OPERATORS or name in string_functions.PARAMETERS or _conversion(name) is not None
    )


def _parameter_names(name: str, count: int) -> tuple[str, ...]:
    if not is_standard_function(name):
        raise ValueError(f"Unknown standard function {name}")
    if name in string_functions.PARAMETERS:
        names = string_functions.PARAMETERS[name]
    elif name == "ABS" or _conversion(name):
        names = ("IN",)
    elif name in _SHIFTS:
        names = ("IN", "N")
    elif name == "LIMIT":
        names = ("MIN", "IN", "MAX")
    elif name == "SEL":
        names = ("G", "IN0", "IN1")
    elif name in {"MIN", "MAX"}:
        if count < 2:
            raise ValueError(f"{name} requires at least two inputs")
        names = tuple(f"IN{index}" for index in range(count))
    else:
        if count < 2:
            raise ValueError("MUX requires a selector and at least one alternative")
        names = ("K", *(f"IN{index}" for index in range(count - 1)))
    if len(names) != count:
        raise ValueError(f"{name} requires {len(names)} inputs")
    return names


def bind_arguments(name: str, arguments: tuple[Argument, ...]) -> tuple[Argument, ...]:
    """Validate inputs and return arguments in the standard parameter order."""
    names = _parameter_names(name, len(arguments))
    if any(argument.mode not in {"", ":="} for argument in arguments):
        raise ValueError("Standard functions accept input arguments only")
    named = [argument.name is not None for argument in arguments]
    if any(named) and not all(named):
        raise ValueError("Cannot mix positional and named standard arguments")
    if not any(named):
        return arguments
    supplied = {}
    for argument in arguments:
        parameter = argument.name.upper()
        if name == "LIMIT":
            parameter = {"MN": "MIN", "MX": "MAX"}.get(parameter, parameter)
        if parameter not in names:
            raise ValueError(f"Unknown {name} input {parameter}")
        if parameter in supplied:
            raise ValueError(f"Duplicate {name} input {parameter}")
        supplied[parameter] = argument
    if supplied.keys() != set(names):
        raise ValueError(f"Missing {name} inputs")
    return tuple(supplied[parameter] for parameter in names)


def _is_numeric(type_name: TypeSpec) -> bool:
    return isinstance(type_name, str) and type_name in NUMERIC_TYPES | {"INTEGER"}


def _common_type(types: tuple[TypeSpec, ...], *, aggregate: bool) -> TypeSpec:
    first = types[0]
    if aggregate and all(isinstance(item, StringType) for item in types):
        return StringType(max(item.length for item in types))
    if all(_is_numeric(item) for item in types):
        if all(same_type(first, item) for item in types):
            return first
        common = first
        for item in types[1:]:
            common = numeric_type(common, item)
        return common
    if all(same_type(first, item) for item in types):
        if first in {"TIME", "BOOL"} or isinstance(first, EnumType):
            return first
        if aggregate and isinstance(first, (ArrayType, StructType)):
            return first
    raise TypeError("Standard function inputs require compatible types")


def infer_result(name: str, argument_types: tuple[TypeSpec, ...]) -> TypeSpec:
    """Infer a canonical overload result while checking every argument type."""
    _parameter_names(name, len(argument_types))
    types = tuple(canonical_type(item) for item in argument_types)
    if name in string_functions.PARAMETERS:
        return string_functions.infer_result(name, types)
    if name in _SHIFTS:
        if types[1] not in INTEGER_TYPES | {"INTEGER"}:
            raise TypeError("Shift count requires an integer type")
        kind = bitwise_result_type("NOT", types[0])
        if kind == "BOOL":
            raise TypeError("Shifts require bitstrings or untyped integers")
        return kind
    conversion = _conversion(name)
    if conversion:
        source, target = conversion
        actual = types[0]
        if isinstance(actual, StringType) or source == "STRING" or target == "STRING":
            if source == "STRING" and not isinstance(actual, StringType):
                raise TypeError("STRING source requires STRING input")
            if isinstance(actual, StringType):
                if source not in {None, "STRING"}:
                    raise TypeError("Numeric conversion source cannot accept STRING")
                if target not in INTEGER_TYPES | {"BOOL", "STRING"}:
                    raise TypeError("STRING converts only to BOOL, integer or STRING")
            elif target == "STRING":
                if actual not in INTEGER_TYPES | {"BOOL", "INTEGER"} and not (
                    source in INTEGER_TYPES and _is_numeric(actual)
                ):
                    raise TypeError("TO_STRING requires BOOL, integer or STRING input")
                if source == "BOOL" and actual != "BOOL":
                    raise TypeError("BOOL source requires BOOL input")
                if source in INTEGER_TYPES and not _is_numeric(actual):
                    raise TypeError("Numeric conversion sources require numeric input")
            return string_functions.TEXT_TYPE if target == "STRING" else target
        if not isinstance(actual, str) or actual not in _CONVERSION_TYPES | {"INTEGER"}:
            raise TypeError("Conversions require scalar inputs, excluding enums")
        if source == "BOOL" and actual != "BOOL":
            raise TypeError("BOOL source requires BOOL input")
        if source == "TIME" and actual not in {"TIME", "INTEGER"}:
            raise TypeError("TIME source requires TIME or an untyped integer")
        if source in NUMERIC_TYPES and not _is_numeric(actual):
            raise TypeError("Numeric conversion sources require numeric input")
        return target
    if name == "ABS":
        if not _is_numeric(types[0]):
            raise TypeError("ABS requires numeric input")
        return types[0]
    if name == "SEL":
        if types[0] != "BOOL":
            raise TypeError("SEL requires a BOOL selector")
        return _common_type(types[1:], aggregate=True)
    if name == "MUX":
        if types[0] not in INTEGER_TYPES | {"INTEGER"}:
            raise TypeError("MUX requires an integer selector")
        return _common_type(types[1:], aggregate=True)
    return _common_type(types, aggregate=False)


def selection_index(name: str, selector: Value, alternative_count: int) -> int:
    """Return the chosen expression's position, including the selector at zero."""
    if type(alternative_count) is not int or alternative_count < 1:
        raise ValueError("Selection requires at least one alternative")
    if name == "SEL":
        if type(selector) is not bool or alternative_count != 2:
            raise TypeError("SEL requires a BOOL selector and two alternatives")
        return 2 if selector else 1
    if name == "MUX":
        checked_integer(selector)
        if selector < 0:
            raise ValueError("MUX selector cannot be negative")
        return min(selector + 1, alternative_count)
    raise ValueError(f"{name} is not a selection function")


def _checked(type_name: TypeSpec, value: Value) -> Value:
    return checked_integer(value) if type_name == "INTEGER" else check_value(type_name, value)


def _convert_scalar(value: Value, target: str) -> Value:
    if target == "BOOL":
        return bool(value)
    if type(value) is bool:
        value = int(value)
    if target in INTEGER_TYPES | {"TIME"} and type(value) is float:
        value = round(value)
    return check_value(target, value)


def evaluate(name: str, arguments: tuple[tuple[Value, TypeSpec], ...]) -> tuple[Value, TypeSpec]:
    """Evaluate an eager pure call; interpreter selection is independently lazy."""
    result_type = infer_result(name, tuple(type_name for _, type_name in arguments))
    values = tuple(_checked(canonical_type(type_name), value) for value, type_name in arguments)
    if name in string_functions.PARAMETERS:
        return string_functions.evaluate(name, values), result_type
    if name in _SHIFTS:
        return shift_value(name, values[0], values[1], result_type), result_type
    conversion = _conversion(name)
    if conversion:
        source, target = conversion
        value = values[0]
        if source is not None and source != "STRING":
            value = _convert_scalar(value, source)
        if target == "STRING":
            return string_functions.to_string(value), result_type
        if isinstance(value, str):
            return string_functions.from_string(value, target), result_type
        return _convert_scalar(value, target), result_type
    if name in {"SEL", "MUX"}:
        index = selection_index(name, values[0], len(values) - 1)
        return _checked(result_type, values[index]), result_type
    if name == "ABS":
        result = abs(values[0])
    else:

        def ordering(value: Value) -> Value:
            return value.value if isinstance(value, EnumValue) else value

        if name == "MIN":
            result = min(values, key=ordering)
        elif name == "MAX":
            result = max(values, key=ordering)
        else:
            lower, value, upper = values
            result = min(max(value, lower, key=ordering), upper, key=ordering)
    return _checked(result_type, result), result_type
