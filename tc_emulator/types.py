"""Checked PLC scalar storage and immutable composite value types."""

from __future__ import annotations

import math
import re
import struct
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from itertools import islice
from types import MappingProxyType

BIT_STRING_TYPES = frozenset({"BYTE", "WORD", "DWORD"})
INTEGER_TYPES = frozenset({"INT", "UINT", "DINT", "UDINT"}) | BIT_STRING_TYPES
FLOAT_TYPES = frozenset({"REAL", "LREAL"})
NUMERIC_TYPES = INTEGER_TYPES | FLOAT_TYPES
SCALAR_TYPES = NUMERIC_TYPES | {"BOOL", "TIME"}
_RANGES = {
    "INT": (-32768, 32767),
    "UINT": (0, 65535),
    "DINT": (-2147483648, 2147483647),
    "UDINT": (0, 4294967295),
    "WORD": (0, 65535),
    "BYTE": (0, 255),
    "DWORD": (0, 4294967295),
    "TIME": (0, 4294967295),
}
_TIME_COMPONENT = re.compile(r"([0-9]+)(?:\.([0-9]+))?(ms|d|h|m|s)")
_TIME_UNITS = {"d": (0, 86400000), "h": (1, 3600000), "m": (2, 60000), "s": (3, 1000), "ms": (4, 1)}
_TIME_COMPONENT_LIMITS = {"h": 24, "m": 60, "s": 60, "ms": 1000}


@dataclass(frozen=True)
class StringType:
    """Latin-1 STRING storage capacity, excluding the terminating NUL."""

    length: int = 80

    def __post_init__(self) -> None:
        if type(self.length) is not int:
            raise TypeError("STRING capacity requires an integer, not BOOL")
        if not 1 <= self.length <= 1_000_000:
            raise ValueError("STRING capacity must be between 1 and 1000000")

    def __str__(self) -> str:
        return f"STRING({self.length})"


@dataclass(frozen=True)
class InterfaceType:
    """Nominal interface reference descriptor; never a PLC value type."""

    name: str

    def __post_init__(self) -> None:
        if not isinstance(self.name, str):
            raise TypeError("Interface name requires an identifier")
        if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", self.name) is None:
            raise ValueError("Interface name requires an identifier")
        object.__setattr__(self, "name", self.name.upper())

    def __str__(self) -> str:
        return self.name


@dataclass(frozen=True)
class ReferenceType:
    """Resolved non-owning data reference descriptor; never a PLC value type."""

    target: TypeSpec

    def __str__(self) -> str:
        return f"REFERENCE TO {self.target}"


@dataclass(frozen=True)
class ArrayType:
    """Fixed inclusive ST bounds; the last index varies fastest."""

    bounds: tuple[tuple[int, int], ...]
    element_type: TypeSpec

    def __post_init__(self) -> None:
        if not isinstance(self.bounds, (tuple, list)) or not 1 <= len(self.bounds) <= 8:
            raise ValueError("Arrays require between 1 and 8 dimensions")
        if isinstance(self.element_type, str):
            if not re.fullmatch(r"[A-Za-z_][A-Za-z_0-9]*", self.element_type):
                raise ValueError("Array element type must be a type name")
            object.__setattr__(self, "element_type", self.element_type.upper())
        elif not isinstance(
            self.element_type, (ArrayType, StructType, EnumType, AliasType, StringType)
        ):
            raise ValueError("Array element type must be a supported value type")
        normalized = []
        size = 1
        for bound in self.bounds:
            if not isinstance(bound, (list, tuple)) or len(bound) != 2:
                raise ValueError("Each array dimension requires lower and upper bounds")
            low, high = bound
            if type(low) is not int or type(high) is not int:
                raise TypeError("Array bounds must be integers, not BOOL")
            if not -(2**31) <= low <= high <= 2**31 - 1:
                raise ValueError("Array bounds must be ascending and in DINT range")
            size *= high - low + 1
            if size > 1_000_000:
                raise ValueError("Array exceeds the 1000000 element limit")
            normalized.append((low, high))
        object.__setattr__(self, "bounds", tuple(normalized))

    @property
    def shape(self) -> tuple[int, ...]:
        return tuple(high - low + 1 for low, high in self.bounds)

    @property
    def size(self) -> int:
        return math.prod(self.shape)

    def __str__(self) -> str:
        bounds = ", ".join(f"{low}..{high}" for low, high in self.bounds)
        return f"ARRAY[{bounds}] OF {self.element_type}"


@dataclass(frozen=True)
class OpenArrayType:
    """A non-owning array parameter whose actual storage supplies its bounds."""

    rank: int
    element_type: TypeSpec

    def __post_init__(self) -> None:
        if type(self.rank) is not int:
            raise TypeError("Open array rank requires an integer, not BOOL")
        if not 1 <= self.rank <= 8:
            raise ValueError("Arrays require between 1 and 8 dimensions")
        element = ArrayType(((0, 0),), self.element_type).element_type
        object.__setattr__(self, "element_type", element)

    def __str__(self) -> str:
        return f"ARRAY[{', '.join('*' for _ in range(self.rank))}] OF {self.element_type}"


@dataclass(frozen=True)
class FBArrayType:
    """Resolved fixed bounds for distinct FB instances, never a value array."""

    bounds: tuple[tuple[int, int], ...]
    element_type: str

    def __post_init__(self) -> None:
        if not isinstance(self.element_type, str):
            raise TypeError("FB array element type requires an instance type name")
        array = ArrayType(self.bounds, self.element_type)
        object.__setattr__(self, "bounds", array.bounds)
        object.__setattr__(self, "element_type", array.element_type)

    @property
    def shape(self) -> tuple[int, ...]:
        return tuple(high - low + 1 for low, high in self.bounds)

    @property
    def size(self) -> int:
        return math.prod(self.shape)

    def __str__(self) -> str:
        bounds = ", ".join(f"{low}..{high}" for low, high in self.bounds)
        return f"ARRAY[{bounds}] OF {self.element_type}"


@dataclass(frozen=True)
class EnumType:
    name: str
    members: tuple[tuple[str, int], ...]
    base_type: str = "INT"
    default_member: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", self.name.upper())
        object.__setattr__(self, "base_type", self.base_type.upper())
        if self.base_type not in INTEGER_TYPES - BIT_STRING_TYPES:
            raise ValueError("Enum base must be a supported integer type")
        members = tuple(
            (name.upper(), check_value(self.base_type, value)) for name, value in self.members
        )
        if not members or len({name for name, _ in members}) != len(members):
            raise ValueError("Enum requires unique member names")
        if len({value for _, value in members}) != len(members):
            raise ValueError("Enum member values must be unique")
        object.__setattr__(self, "members", members)
        default = (
            self.default_member.upper()
            if self.default_member is not None
            else next((name for name, value in members if value == 0), members[0][0])
        )
        if default not in dict(members):
            raise ValueError(f"Unknown default member {default} on {self.name}")
        object.__setattr__(self, "default_member", default)

    def __str__(self) -> str:
        return self.name


@dataclass(frozen=True)
class EnumValue:
    enum_type: EnumType
    name: str
    value: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", self.name.upper())
        if type(self.value) is not int or dict(self.enum_type.members).get(self.name) != self.value:
            raise ValueError("Enum value must name a declared member")

    @property
    def type_name(self) -> str:
        return self.enum_type.name

    def __str__(self) -> str:
        return f"{self.type_name}.{self.name}"


@dataclass(frozen=True)
class StructField:
    name: str
    type_name: TypeSpec
    default: Value | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", self.name.upper())


@dataclass(frozen=True)
class StructType:
    name: str
    fields: tuple[StructField, ...] = field(compare=False, hash=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", self.name.upper())
        object.__setattr__(self, "fields", tuple(self.fields))
        if len({item.name for item in self.fields}) != len(self.fields):
            raise ValueError("Structure field names must be unique")

    def __str__(self) -> str:
        return self.name


@dataclass(frozen=True)
class AliasType:
    name: str
    target: TypeSpec
    default: Value | None = field(default=None, compare=False, hash=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", self.name.upper())

    def __str__(self) -> str:
        return self.name


def _mapping_fields(value: Mapping) -> dict[str, object]:
    result = {}
    for name, item in value.items():
        if not isinstance(name, str):
            raise TypeError("Structure field names must be strings")
        name = name.upper()
        if name in result:
            raise ValueError(f"Duplicate structure field {name}")
        result[name] = item
    return result


class StructValue(Mapping[str, "Value"]):
    """A detached immutable structure snapshot, with case-insensitive field lookup."""

    __slots__ = ("_type_name", "_values")

    def __init__(self, type_name: str, values: Mapping[str, Value]) -> None:
        def freeze(value):
            if isinstance(value, StructValue):
                return value
            if isinstance(value, Mapping):
                return MappingProxyType({key: freeze(item) for key, item in value.items()})
            if isinstance(value, (tuple, list)):
                return tuple(freeze(item) for item in value)
            if type(value) in (int, bool, float, str) or isinstance(value, EnumValue):
                return value
            raise TypeError("Unsupported structure field value")

        self._type_name = type_name.upper()
        self._values = MappingProxyType(
            {name: freeze(value) for name, value in _mapping_fields(values).items()}
        )

    @property
    def type_name(self) -> str:
        return self._type_name

    def __getitem__(self, name: str) -> Value:
        return self._values[name.upper()]

    def __iter__(self) -> Iterator[str]:
        return iter(self._values)

    def __len__(self) -> int:
        return len(self._values)

    def __repr__(self) -> str:
        return f"{self.type_name}({dict(self._values)!r})"


TypeSpec = (
    str
    | ArrayType
    | OpenArrayType
    | FBArrayType
    | StructType
    | EnumType
    | AliasType
    | StringType
    | InterfaceType
    | ReferenceType
)
Scalar = int | bool | float | str | EnumValue
Value = Scalar | tuple | StructValue


def canonical_type(type_name: TypeSpec) -> TypeSpec:
    """Strip transparent aliases while retaining nominal structure/enum identity."""
    if isinstance(type_name, AliasType):
        return canonical_type(type_name.target)
    if isinstance(type_name, ArrayType):
        return ArrayType(type_name.bounds, canonical_type(type_name.element_type))
    if isinstance(type_name, OpenArrayType):
        return OpenArrayType(type_name.rank, canonical_type(type_name.element_type))
    if isinstance(type_name, ReferenceType):
        return ReferenceType(canonical_type(type_name.target))
    return type_name


def same_type(left: TypeSpec, right: TypeSpec) -> bool:
    return canonical_type(left) == canonical_type(right)


def inout_compatible(expected: TypeSpec, actual: TypeSpec) -> bool:
    """Match open parameter rank/element identity, retaining fixed bound matching."""
    expected = canonical_type(expected)
    actual = canonical_type(actual)
    if isinstance(expected, OpenArrayType):
        if not isinstance(actual, (ArrayType, OpenArrayType)):
            return False
        rank = len(actual.bounds) if isinstance(actual, ArrayType) else actual.rank
        return expected.rank == rank and same_type(expected.element_type, actual.element_type)
    return same_type(expected, actual)


def is_value_type(type_name: TypeSpec) -> bool:
    return type_name in SCALAR_TYPES or isinstance(
        type_name, (ArrayType, StructType, EnumType, AliasType, StringType)
    )


def resolve_type(type_name: TypeSpec, registry: Mapping[str, TypeSpec]) -> TypeSpec:
    if isinstance(type_name, str):
        name = type_name.upper()
        if name == "STRING":
            return StringType()
        if name in SCALAR_TYPES:
            return name
        if name not in registry:
            raise ValueError(f"Unknown value type {name}")
        resolved = registry[name]
        if isinstance(resolved, (OpenArrayType, FBArrayType, InterfaceType, ReferenceType)):
            raise TypeError("Expected a supported value type")
        return resolved
    if isinstance(type_name, ArrayType):
        return ArrayType(type_name.bounds, resolve_type(type_name.element_type, registry))
    if isinstance(type_name, (StructType, EnumType, AliasType, StringType)):
        return type_name
    raise TypeError("Expected a supported value type")


def value_leaf_count(type_name: TypeSpec) -> int:
    if isinstance(type_name, (OpenArrayType, FBArrayType, InterfaceType, ReferenceType)):
        raise TypeError("Expected a supported value type")
    if isinstance(type_name, AliasType):
        return value_leaf_count(type_name.target)
    if isinstance(type_name, ArrayType):
        return type_name.size * value_leaf_count(type_name.element_type)
    if isinstance(type_name, StructType):
        return sum(value_leaf_count(item.type_name) for item in type_name.fields)
    return 1


def parse_time_literal(text: str) -> int:
    """Convert a descending-unit TIME literal to exact uint32 milliseconds."""
    prefix, separator, body = text.lower().partition("#")
    if not separator or prefix not in {"t", "time"} or not body:
        raise ValueError("Expected T# or TIME# duration")
    position, previous, total = 0, -1, 0
    while position < len(body):
        component = _TIME_COMPONENT.match(body, position)
        if component is None:
            raise ValueError("Invalid TIME duration component")
        whole, fraction, unit = component.groups()
        order, multiplier = _TIME_UNITS[unit]
        if order <= previous:
            raise ValueError("TIME units must be distinct and in descending order")
        # Bound conversion before int(): huge malformed input must remain a ValueError,
        # independent of Python's configurable decimal-integer conversion capacity.
        significant = whole.lstrip("0")
        if len(significant) > 10:
            raise ValueError("TIME literal is outside TIME range")
        integer = int(significant or "0")
        if previous >= 0 and integer >= _TIME_COMPONENT_LIMITS[unit]:
            raise ValueError(f"TIME {unit} component exceeds its unit range")
        total += integer * multiplier
        if fraction is not None:
            if component.end() != len(body):
                raise ValueError("Only the final TIME component may have a fraction")
            fractional_digits = fraction.rstrip("0")
            # Of the supported multipliers, d has the largest power of 2 or 5
            # (2**10), so more than 10 decimal places can never yield whole ms.
            if len(fractional_digits) > 10:
                raise ValueError("TIME fractions must represent whole milliseconds")
            numerator = int(fractional_digits or "0") * multiplier
            milliseconds, remainder = divmod(numerator, 10 ** len(fractional_digits))
            if remainder:
                raise ValueError("TIME fractions must represent whole milliseconds")
            total += milliseconds
        if total > _RANGES["TIME"][1]:
            raise ValueError("TIME literal is outside TIME range")
        previous, position = order, component.end()
        if position < len(body) and body[position] == "_":
            position += 1
            if position == len(body):
                raise ValueError("Expected TIME component after underscore")
    return total


def _real_from_ratio(numerator: int, denominator: int) -> float:
    """Round an exact rational to binary32 once, using nearest with ties to even."""
    sign = -1 if numerator < 0 else 1
    numerator = abs(numerator)
    if numerator == 0:
        return math.copysign(0.0, sign)
    exponent = numerator.bit_length() - denominator.bit_length()
    if exponent >= 0:
        exponent -= numerator < (denominator << exponent)
    else:
        exponent -= (numerator << -exponent) < denominator
    if exponent > 127:
        raise ValueError("Value is outside finite REAL range")
    if exponent < -150:
        return math.copysign(0.0, sign)

    # Normals have 24 significant bits; subnormals use a fixed 2**-149 grid.
    shift = max(exponent - 23, -149)
    if shift >= 0:
        denominator <<= shift
    else:
        numerator <<= -shift
    significand, remainder = divmod(numerator, denominator)
    if 2 * remainder > denominator or (2 * remainder == denominator and significand % 2):
        significand += 1
    rounded = math.ldexp(float(significand), shift)
    if rounded >= 2.0**128:
        raise ValueError("Value is outside finite REAL range")
    return math.copysign(rounded, sign)


def check_float_literal(type_name: str, value: Scalar, raw_text: str | None = None) -> float:
    """Preserve decimal REAL precision without an intermediate binary64 rounding."""
    if type_name != "REAL" or raw_text is None:
        return check_value(type_name, value)
    try:
        exact = Decimal(raw_text)
    except InvalidOperation as error:
        raise ValueError("Invalid REAL literal") from error
    if not exact.is_finite():
        raise ValueError("Value is outside finite REAL range")
    # Guard enormous decimal exponents before constructing an integer ratio.
    if exact.is_zero() or exact.adjusted() < -46:
        return math.copysign(0.0, -1 if exact.is_signed() else 1)
    if exact.adjusted() > 38:
        raise ValueError("Value is outside finite REAL range")
    numerator, denominator = exact.as_integer_ratio()
    return _real_from_ratio(numerator, denominator)


def check_value(type_name: TypeSpec, value: object) -> Value:
    """Return a checked scalar or detached immutable array value."""
    if isinstance(type_name, (OpenArrayType, FBArrayType, InterfaceType, ReferenceType)):
        raise TypeError("Expected a supported value type")
    if isinstance(type_name, StringType):
        if not isinstance(value, str):
            raise TypeError(f"{type_name} requires a Python str")
        try:
            value.encode("latin-1")
        except UnicodeEncodeError as error:
            raise ValueError("STRING requires Latin-1 text") from error
        return value.split("\0", 1)[0][: type_name.length]
    if isinstance(type_name, AliasType):
        target = canonical_type(type_name.target)
        if isinstance(target, EnumType) and isinstance(value, str):
            prefix, separator, member = value.upper().partition(".")
            if separator and prefix == type_name.name:
                value = member
        if isinstance(target, StructType) and isinstance(value, Mapping):
            if isinstance(value, StructValue) and value.type_name != target.name:
                raise TypeError(f"Expected structure {target.name}, got {value.type_name}")
            provided = _mapping_fields(value)
            defaults = dict(default_value(type_name))
            defaults.update(provided)
            value = defaults
        return check_value(type_name.target, value)
    if isinstance(type_name, EnumType):
        if isinstance(value, EnumValue):
            if value.enum_type != type_name:
                raise TypeError(f"Expected {type_name}, got {value.type_name}")
            return value
        if not isinstance(value, str):
            raise TypeError(f"{type_name} requires a member name or matching EnumValue")
        parts = value.upper().split(".")
        if len(parts) == 2 and parts[0] == type_name.name:
            parts = parts[1:]
        if len(parts) != 1 or parts[0] not in dict(type_name.members):
            raise ValueError(f"Unknown member {value} on {type_name}")
        return EnumValue(type_name, parts[0], dict(type_name.members)[parts[0]])
    if isinstance(type_name, StructType):
        if not isinstance(value, Mapping):
            raise TypeError(f"{type_name} requires a mapping of fields")
        if isinstance(value, StructValue) and value.type_name != type_name.name:
            raise TypeError(f"Expected structure {type_name.name}, got {value.type_name}")
        provided = _mapping_fields(value)
        unknown = provided.keys() - {item.name for item in type_name.fields}
        if unknown:
            raise ValueError(f"Unknown fields on {type_name}: {', '.join(sorted(unknown))}")
        return StructValue(
            type_name.name,
            {
                item.name: check_value(item.type_name, provided[item.name])
                if item.name in provided
                else check_value(item.type_name, item.default)
                if item.default is not None
                else default_value(item.type_name)
                for item in type_name.fields
            },
        )
    if isinstance(type_name, ArrayType):

        def convert(current: object, dimension: int) -> tuple:
            if not isinstance(current, (list, tuple)):
                raise TypeError(f"{type_name} requires nested lists or tuples")
            if len(current) != type_name.shape[dimension]:
                raise ValueError(f"Array dimension {dimension + 1} has wrong length")
            if dimension + 1 == len(type_name.bounds):
                return tuple(check_value(type_name.element_type, item) for item in current)
            return tuple(convert(item, dimension + 1) for item in current)

        return convert(value, 0)
    if type_name not in SCALAR_TYPES:
        raise ValueError(f"Unknown scalar type {type_name}")
    if type_name in FLOAT_TYPES:
        if type(value) not in (int, float):
            raise TypeError(f"{type_name} requires a Python int or float, not BOOL")
        if type_name == "REAL" and type(value) is int:
            return _real_from_ratio(value, 1)
        try:
            converted = float(value)
            if not math.isfinite(converted):
                raise ValueError(f"{type_name} requires a finite value")
            if type_name == "REAL":
                converted = struct.unpack("!f", struct.pack("!f", converted))[0]
            if not math.isfinite(converted):
                raise ValueError(f"{type_name} overflow")
            return converted
        except (OverflowError, struct.error) as error:
            raise ValueError(f"Value is outside finite {type_name} range") from error
    expected = bool if type_name == "BOOL" else int
    if type(value) is not expected:
        raise TypeError(f"{type_name} requires a Python {expected.__name__}")
    if type_name != "BOOL":
        low, high = _RANGES[type_name]
        if not low <= value <= high:
            raise ValueError(f"{value} is outside {type_name} range [{low}, {high}]")
    return value


def default_value(type_name: TypeSpec) -> Value:
    """Return a fresh immutable default value for a supported PLC type."""
    if isinstance(type_name, (OpenArrayType, FBArrayType, InterfaceType, ReferenceType)):
        raise TypeError("Expected a supported value type")
    if isinstance(type_name, AliasType):
        return (
            check_value(type_name.target, type_name.default)
            if type_name.default is not None
            else default_value(type_name.target)
        )
    if isinstance(type_name, EnumType):
        return check_value(type_name, type_name.default_member)
    if isinstance(type_name, StructType):
        return check_value(type_name, {})
    if isinstance(type_name, ArrayType):

        def zeros(dimension: int) -> tuple:
            value = (
                default_value(type_name.element_type)
                if dimension + 1 == len(type_name.bounds)
                else zeros(dimension + 1)
            )
            return (value,) * type_name.shape[dimension]

        return zeros(0)
    if isinstance(type_name, StringType):
        return ""
    return check_value(type_name, False if type_name == "BOOL" else 0)


def array_initial_value(type_name: ArrayType, flat_values: Iterable[Value]) -> Value:
    """Check a bounded flat declaration initializer, default-fill and reshape it."""
    if not isinstance(type_name, ArrayType):
        raise TypeError("Expected a fixed value array type")
    values = list(islice(iter(flat_values), type_name.size + 1))
    if len(values) > type_name.size:
        raise ValueError("Too many array initializer elements")
    values = [check_value(type_name.element_type, value) for value in values]
    values.extend([default_value(type_name.element_type)] * (type_name.size - len(values)))
    iterator = iter(values)

    def reshape(dimension: int) -> tuple:
        if dimension + 1 == len(type_name.bounds):
            return tuple(next(iterator) for _ in range(type_name.shape[dimension]))
        return tuple(reshape(dimension + 1) for _ in range(type_name.shape[dimension]))

    return reshape(0)


def numeric_type(left: str, right: str) -> str:
    """Choose a deterministic common type for checked numeric expressions."""
    if left not in NUMERIC_TYPES | {"INTEGER"} or right not in NUMERIC_TYPES | {"INTEGER"}:
        raise ValueError("Numeric operands required")
    return "LREAL" if "LREAL" in (left, right) else "REAL" if "REAL" in (left, right) else "INTEGER"


def checked_integer(value: int) -> int:
    """Check the signed 64-bit range used for integer intermediates."""
    if type(value) is not int:
        raise TypeError("Integer arithmetic requires a Python int")
    if not -(2**63) <= value <= 2**63 - 1:
        raise ValueError(f"{value} is outside signed 64-bit intermediate range")
    return value


def trunc_div(left: int, right: int) -> int:
    """Divide integers towards zero without a floating-point conversion."""
    quotient = abs(left) // abs(right)
    return -quotient if (left < 0) != (right < 0) else quotient
