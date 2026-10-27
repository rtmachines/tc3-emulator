"""Pure checked bit operations shared by validation, constants and execution."""

from __future__ import annotations

from .types import BIT_STRING_TYPES, TypeSpec, Value, canonical_type, check_value

_WIDTHS = {"BYTE": 8, "WORD": 16, "DWORD": 32, "INT": 16, "UINT": 16, "DINT": 32, "UDINT": 32}
_BINARY_OPERATORS = frozenset({"AND", "OR", "XOR"})
_SHIFT_OPERATORS = frozenset({"SHL", "SHR", "ROL", "ROR"})


def bit_width(type_name: TypeSpec) -> int:
    """Return the integer storage width, resolving transparent aliases."""
    kind = canonical_type(type_name)
    if not isinstance(kind, str) or kind not in _WIDTHS:
        raise TypeError("Bit access requires an integer storage type")
    return _WIDTHS[kind]


def bitwise_result_type(op: str, left: TypeSpec, right: TypeSpec | None = None) -> TypeSpec:
    """Resolve the BOOL overload or widest checked unsigned operand width."""
    if op not in _BINARY_OPERATORS | {"NOT"}:
        raise ValueError(f"Unknown bitwise operator {op}")
    if (op == "NOT") != (right is None):
        raise TypeError("NOT requires one operand; AND/OR/XOR require two")
    kinds = (
        (canonical_type(left),) if right is None else (canonical_type(left), canonical_type(right))
    )
    if all(kind == "BOOL" for kind in kinds):
        return "BOOL"
    if any(
        not isinstance(kind, str) or kind not in BIT_STRING_TYPES | {"INTEGER"} for kind in kinds
    ):
        raise TypeError("Bitwise operands require BOOLs, bitstrings or untyped integers")
    typed = [kind for kind in kinds if kind in BIT_STRING_TYPES]
    return max(typed, key=bit_width) if typed else "DWORD"


def bitwise_value(op: str, left: Value, right: Value | None, kind: TypeSpec) -> Value:
    """Check operands in the chosen result type and evaluate within its width."""
    kind = canonical_type(kind)
    bitwise_result_type(op, kind, None if right is None else kind)
    left = check_value(kind, left)
    if op == "NOT":
        return not left if kind == "BOOL" else left ^ ((1 << bit_width(kind)) - 1)
    right = check_value(kind, right)
    if op == "AND":
        return left & right
    if op == "OR":
        return left | right
    return left ^ right


def shift_value(op: str, value: Value, count: Value, kind: TypeSpec) -> int:
    """Shift or rotate an unsigned bitstring without allocating huge integers."""
    if op not in _SHIFT_OPERATORS:
        raise ValueError(f"Unknown shift operator {op}")
    kind = canonical_type(kind)
    if not isinstance(kind, str) or kind not in BIT_STRING_TYPES:
        raise TypeError("Shifts require a bitstring result type")
    value = check_value(kind, value)
    if type(count) is not int:
        raise TypeError("Shift count must be an integer, not BOOL")
    if count < 0:
        raise ValueError("Shift count cannot be negative")
    width = bit_width(kind)
    mask = (1 << width) - 1
    if op in {"SHL", "SHR"}:
        if count >= width:
            return 0
        return (value << count) & mask if op == "SHL" else value >> count
    count %= width
    if not count:
        return value
    if op == "ROL":
        return ((value << count) | (value >> (width - count))) & mask
    return ((value >> count) | (value << (width - count))) & mask


def _checked_bit(value: Value, type_name: TypeSpec, index: int) -> tuple[int, str, int]:
    kind = canonical_type(type_name)
    width = bit_width(kind)
    if type(index) is not int:
        raise TypeError("Bit index must be an integer, not BOOL")
    if not 0 <= index < width:
        raise ValueError(f"Bit index must be in range 0..{width - 1}")
    return check_value(kind, value), kind, width


def read_bit(value: Value, type_name: TypeSpec, index: int) -> bool:
    """Read an integer storage bit, including signed two's-complement values."""
    value, _, _ = _checked_bit(value, type_name, index)
    return bool(value & (1 << index))


def write_bit(value: Value, type_name: TypeSpec, index: int, bit: bool) -> int:
    """Replace one storage bit and reconstruct signed values at their width."""
    value, kind, width = _checked_bit(value, type_name, index)
    if type(bit) is not bool:
        raise TypeError("Bit assignment requires a BOOL")
    value &= (1 << width) - 1
    mask = 1 << index
    result = value | mask if bit else value & ~mask
    if kind in {"INT", "DINT"} and result & (1 << (width - 1)):
        result -= 1 << width
    return check_value(kind, result)
