# v0.16: ST actions and enum attributes

## Intent and authorization

The user selected ST actions plus `strict` and `qualified_only` enums, inheritance,
tests and a three-conveyor example, and explicitly requested implementation.
This document records the engineering decisions for that accepted scope. Work
continues without another approval round. Use models appropriate to complexity.

## Approaches

The accepted approach removes source-import barriers with actions and enum
attributes. POINTER/ADR would require a wider memory model; RETAIN/restart would
extend lifecycle rather than source coverage. Both remain separate future work.

## Constraints

Python >=3.11, no runtime dependencies. Preserve the checked-subset policy,
source-aware errors, case-insensitive names, bounded execution, existing API and
v0.15 lifecycle. No SFC execution, arbitrary pragma ignoring, pointer model,
restart, online change, or additional scalar types. Native-format fixtures are
not evidence of execution on Beckhoff TwinCAT.

## Actions

- An action belongs to a FUNCTION_BLOCK or PROGRAM, has a name and ST statements,
  and has no declaration section, return value, parameters of its own or local
  storage. Standalone source accepts `ACTION Name: ... END_ACTION` after the
  owner's main body (alongside FB methods/properties). Unknown/malformed/nested
  action declarations and actions on FUNCTION/INTERFACE are rejected.
- Native `.TcPOU` imports `<Action Name="..." Id="..."><Implementation><ST>...
  </ST></Implementation></Action>`; preserve original action section/line errors,
  reject foreign XML semantics and declaration/implementation injection.
- Resolve local `Action()`, `THIS^.Action()`, `fb.Action()`, indexed FB actions,
  `MAIN.Action()` and `SUPER^.Action()`. Actions are statements, never values.
  Calls may bind the owner's inputs/inouts and output mappings using the existing
  FB named-call rules. Local action calls reuse currently bound IN_OUT arguments;
  external calls require IN_OUT bindings. Inputs retain values when omitted.
- Execute only the selected action, never the owner's main body or FB_init.
  Actions share the persistent owner state. Calls inside an active owner body
  share its VAR_TEMP activation; nested actions preserve this activation and
  RETURN exits only the current action. Calls from a method must not see method
  locals. A standalone external action creates one temporary owner activation;
  temporary child initialization follows existing activation rules. Lexical base
  scopes must not accidentally resolve a derived owner's or caller's temporaries.
- FB actions inherit and dispatch virtually, including calls from base code.
  SUPER selects the lexical base implementation. Distinct actions coexist;
  collisions with fields/methods/properties and duplicate action names fail.
  PROGRAM actions have no inheritance. Actions are not interface methods.
- Cycles spanning actions, methods, properties and main bodies are rejected;
  implicit initialization call edges remain accounted for. Shared step/depth/time
  limits apply and action names appear in fault stacks.
- Python exposes `FBHandle.call_action(name, /, **inputs) -> None` and
  `Runtime.call_action(program_name, action_name, /, **inputs) -> None`. Validate
  names and all arguments before any mutation. Preserve faulted-runtime behavior.
  Outputs are read with existing handle/program APIs.
- Append `Pou.actions: tuple[Pou, ...] = ()`; represent actions as `Pou` kind
  ACTION, qualified name `OWNER.ACTION`, `owner=OWNER`, no variables or return.
  Reuse appropriate call infrastructure but do not model action storage as a
  method's fresh local bank. Focused helper modules may be added where they keep
  the existing large validation/execution modules manageable.

## Enum attributes

- Parse `{attribute 'strict'}` and `{attribute 'qualified_only'}` immediately
  before an enum TYPE declaration, either order. Reject duplicates, values,
  misplaced attributes and attributes on non-enum TYPE definitions. Preserve
  existing GVL qualified_only and FB/method call_after_init behavior.
- Append flags with False defaults to enum AST/resolved type metadata. `.st`
  and `.TcDUT` obey the same rules, with original declaration locations.
- `qualified_only` requires `Enum.Member` outside that enum's own default-value
  declaration. Without it, an unqualified member may resolve if unique and not
  shadowed by a variable/constant; ambiguous labels fail. Qualified aliases work.
- `strict` keeps enum identity: arithmetic, cross-enum assignments and mutable
  integer assignments are rejected. A compile-time integer constant matching a
  declared member can be assigned (including initializers and value inputs);
  a nonmember constant is rejected. Such permitted constants become typed enum
  values before execution, including action/method/property paths and FB setup.
  IN_OUT/output bindings still require the exact enum type, not integer storage.
- Preserve the existing conservative nominal rules for unmarked enums; do not
  implement unrestricted integer/enum arithmetic. Python values continue to use
  the existing enum API, with no indiscriminate runtime integer coercion.
- Keep existing supported base types and defaults, including aliases, arrays,
  structures, constants and CASE labels. Attribute support must not lose metadata
  during resolution or rewrap enum defaults with a different identity.

## Example and acceptance

Add native-format three-conveyor files using strict qualified states Stopped,
Starting, Running, Fault; common base actions and a derived override with SUPER;
PROGRAM actions for reading inputs, controlling conveyors and updating outputs.
Retain FB_init and separate timers from v0.15. Test staged start, blocked-sensor
fault, alarm reset, restart, independent instance state and unchanged init counts.
Document exact Python/ST usage and checked-subset limits; set version 0.16.0.

Acceptance: targeted RED/GREEN feature tests; full suite; Ruff through local
reviewdog; formatting and diff checks; wheel/sdist build and installed-package
tests with Python 3.11; independent review of the full change. Do not claim native
TwinCAT execution or publish/merge a release as part of this implementation.

Sources: [Object Action](https://infosys.beckhoff.com/content/1033/tc3_plc_intro/2530340747.html),
[strict](https://infosys.beckhoff.com/content/1033/tc3_plc_intro/3363142027.html),
[enum declarations](https://infosys.beckhoff.com/content/1033/tc3_plc_intro/2529504395.html).
