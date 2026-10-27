# User types implementation plan

Spec: docs/superpowers/specs/2026-10-27-user-types-design.md
Interfaces: .work/user-types/interfaces.md (exact shared signatures).
Constraints: stdlib-only Python3.11+, preserve570 tests, checked profile, no Git repository.

## Task1 — descriptors/storage helpers (root)
- [x] RED tests for composite defaults, mapping validation, enum membership and transparent aliases.
- [x] types.py implements shared immutable types, generalized check/default/array helpers,
  identifier array elements, canonical_type/resolve_type/same_type/is_value_type/leaf count.
- [x] Verify current REAL/TIME behavior and bounded composite defaults.

## Task2 — parser and imports (parser agent)
- [x] RED tests for TYPE aliases/STRUCT/enum grammar, nested initializers, alternating
  fields/indices, enum CASE, forward declarations and malformed/unsupported syntax.
- [x] Extend syntax.py/parser.py/loader.py per interfaces; strict declaration-only TcDUT.
- [x] Tests: original parser/loader cases preserved, no hidden TYPE in TcPOU implementation.

## Task3 — resolution and validation (validator agent)
- [x] RED tests for named resolution/defaults/cycles/aggregate limits and enum/struct typing.
- [x] Resolve all declarations and prepared initializers; Registry mapping with .types;
  reference traversal and constant-vs-writable checks per interfaces.
- [x] Tests for all parameter directions, aliases, unknown/duplicate names, numeric rejection,
  enum CASE labels/default zero member and complete validation of uncalled code.

## Task4 — memory and interpreter (root)
- [x] RED real ST integration tests for nested structures/arrays, deep copies/IN_OUT and
  stable field/element aliases, enum expression/CASE, prepared defaults and API validation.
- [x] Extend memory.py/execution.py/runtime.py/__init__.py per interfaces.
- [x] Preserve function/FB lifetimes, timers, atomic bad-input behavior and fault policy.

## Task5 — examples/review/delivery (root + reviewer)
- [x] Add real .st/.TcDUT example types, FB configuration/state machine and runnable pytest.
- [x] README documents Python values, strict profile and v0.4.0; update packaging manifests.
- [x] Independent graph-first source review; regressions for findings; full pytest,
  Ruff/format/reviewdog; wheel/sdist and installed-wheel smoke.

Review focus: losing alias identity during whole nested replacement; shared mutable defaults;
enum-vs-int confusion; metadata injection in imports; default evaluation across forward types;
aggregate allocation growth; shadowing enum type names with storage; aliased composite arrays.
