# User types — v0.4 design

Implement the requested TYPE/STRUCT/ENUM declarations, initialization, field access,
arrays of structures, VAR_INPUT copies and VAR_IN_OUT references, with examples/tests.
Keep Python3.11+, stdlib-only runtime, standalone Linux operation and all570 v0.3 tests.
The user selected this scope directly; proceed with reversible implementation using
the explicit defaults below. No Git repository exists; baseline snapshot is in .work/user-types.

## Approach

Resolve named types before ordinary whole-program validation, then reuse typed Cell
storage and the existing interpreter. Extend cells into a tree with stable child
identities. A separate structure interpreter would duplicate argument/memory rules;
compiling to Python would abandon the existing checked interpreter. Chosen approach
is an implementation decision grounded in the current architecture.

## Language profile

- TYPE blocks can precede/follow POUs and reference later types across input files.
  Support aliases to supported value types (including defaults), named STRUCT and enums
  in IEC syntax `TYPE E_State : (Idle, Run := 10, Stop) INT := Idle; END_TYPE`.
  No literal ENUM keyword syntax; enum default base INT, optional INT/UINT/DINT/UDINT.
  Each member after an explicit value continues at+1; unique names and values required.
  Default: declared member, else zero-valued member if present, else first member.
- Struct fields may be scalars, enums, named structs or fixed arrays thereof and have
  constant defaults. Nested structures and alternating field/index chains work.
  Struct names are nominal types; aliases are transparent for type compatibility.
- Constant declarations accept named structure initializers `(speed := 10)` and
  recursively nested structure/array initializers. Unspecified fields/elements use
  declared type defaults. Reject duplicates/unknown fields and wrong types, including
  in unreachable/uncalled code. Initializers remain declaration-only; variables and
  general expressions in declaration initializers remain unsupported.
- Qualified enum constants `E_State.Run` only outside enum type-default declarations.
  Enum values remain typed; no implicit integer conversions or enum arithmetic.
  Assignment and all comparisons require the same enum type; enum CASE accepts
  qualified member labels. Existing integer CASE labels remain unchanged.
- Support arrays of structures, enum arrays, structure fields containing arrays,
  aliases of arrays, and arrays whose named element alias resolves to an array.
  Preserve existing1–8 dimensions and1m elements per array. Bound aggregate scalar
  leaves of a resolved value type to1m, reject recursive/cyclic type definitions and
  excessive nesting (64 named-type resolution levels) before allocating cells.
- FUNCTION return/VAR_INPUT/VAR_OUTPUT/VAR_IN_OUT support all value types. Whole value
  assignment copies; IN_OUT requires equivalent declared type (aliases transparent).
  Field/element Cell identities survive whole-container replacement at any depth.
- Names case-insensitive. Reject collisions between type/POU/builtin names. Local
  variables may shadow type names; a shadowed name resolves to storage first.
- .st loads TYPE blocks. Add strict declaration-only .TcDUT import with one named DUT;
  check metadata matches declaration, reject extra objects/XML semantics, keep source
  locations. This is a documented narrow wrapper, not complete TcDUT schema support.
- Out of scope: STRUCT EXTENDS, UNION, subranges, pointers/references, FB fields in
  structs/FB aliases, strings/bit types, enum attributes, namespaces and CASE ranges.

## Python API

`runtime.cell("ST_Config", {"speed":10, "state":"Run"})` accepts case-insensitive
mapping fields, fills omitted fields from defaults, rejects unknown/duplicate names.
Nested structures use nested mappings; arrays use existing lists/tuples and exact shape.
Structure outputs are detached, recursively immutable case-insensitive StructValue
mappings; enum outputs are immutable EnumValue with `.name`, `.value`, `.type_name`.
Enum inputs accept member strings (short or correctly qualified) or matching EnumValue,
reject ints/booleans/unrelated enum values. Export StructValue and EnumValue.
`cell.field("speed")` returns a live child Cell; combine with `.element()` for arrays.
Invalid API arguments are checked atomically before any FB mutation. Faulted runtime
rules and all TIME/timer behavior remain intact.

## Verification and references

Tests: parse/type resolution/negative validation; defaults and forward references;
enum CASE/comparisons/type isolation; copies vs references and stable deep aliases;
fresh function state/independent FB instances; composite API atomic failures; .TcDUT
integration and current numeric/timer regressions. Independent graph-first/source review,
full pytest/Ruff/reviewdog, wheel/sdist and isolated installed-package examples.

[Alias](https://infosys.beckhoff.com/content/1033/tc3_plc_intro/3928317323.html),
[STRUCT](https://infosys.beckhoff.com/content/1033/tc3_plc_intro/2529481355.html),
[Enums](https://infosys.beckhoff.com/content/1033/tc3_plc_intro/2529504395.html),
[Arrays](https://infosys.beckhoff.com/content/1033/tc3_plc_intro/8825253771.html).
The strict qualified-enum and bounded-memory choices define this emulator's subset.
