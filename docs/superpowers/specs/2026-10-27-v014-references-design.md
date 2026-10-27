# v0.14: data references and short-circuit conditions

## Intent and authorization

The user accepted the proposed data-reference scope and explicitly requested implementation,
Python Cell integration, tests and a three-conveyor example with shared configuration.
The implementation remains a standalone Python ST interpreter on Linux without TwinCAT.

## Approaches

1. Add typed, non-owning reference slots over the existing stable Cell storage (selected).
   This preserves alias identity, checked writes and the existing Python API.
2. Introduce a byte-addressed pointer heap. It could eventually support ADR/POINTER, but
   adds layout and platform semantics unrelated to this release's data-reference goal.
3. Add FB_init first. Useful for OOP libraries, but does not unlock shared mutable data.

The implementation uses the first approach. It is the bounded form of the proposal
accepted by the user; internal contracts below are implementation decisions.

## Global constraints

- Python >=3.11, standard-library-only runtime, Linux, no installed TwinCAT.
- Preserve v0.13 behavior, checked arithmetic, Latin-1 strings, resource limits and virtual time.
- Keep failures source-aware; execution failures fault the Runtime as before, argument errors do not.
- Preserve stable Cell identity when replacing structure/array values.
- No general pointers, FB references, reference-valued returns/properties, nested references,
  reference-containing arrays/structures or aliases whose target is a reference in v0.14.
- No native TwinCAT parity claim without differential tests; document checked-profile differences.

## Language and type contracts

`REFERENCE TO T` supports existing value types: scalar/STRING/ENUM, STRUCT and fixed arrays
(including aliases to those types). Fields and elements can be reference targets. The target
type must match with existing alias normalization and nominal UDT rules; no numeric widening,
string-capacity adaptation or array rebasing occurs during binding.

Reference declarations are allowed in VAR, VAR_TEMP, VAR_INST, VAR_GLOBAL and VAR_INPUT,
including function/method/accessor locals. Reference VAR_OUTPUT, VAR_IN_OUT and CONSTANT,
interface/FB/open-array targets, reference returns and reference properties are rejected.
Interface METHOD prototypes may have reference VAR_INPUT parameters, with exact contracts
checked on implementations and overrides.

Every reference initially has no target. `r REF= x` binds to writable addressable storage;
`r REF= otherRef` copies its current target, not an indirection through the other slot.
`r REF= 0` clears it. Copying a null reference produces null. Binding rejects bit views,
constants, temporary values, property results, FBs and incompatible types.

Ordinary reads and `:=` automatically dereference: `r := value` writes the target;
`dest := r` reads it; `r1 := r2` copies values. Field/index access through a reference
dereferences its base. References can supply values to ordinary inputs and their live
targets to ordinary VAR_IN_OUT, including open arrays. In a call to reference VAR_INPUT,
`arg := storage` binds rather than copies; accept compatible reference arguments and literal
integer 0 as well. A missing function/method input is required unless declared with a null
default; nonzero reference-input defaults in functions/methods/interface prototypes are rejected
in this profile. FB reference inputs may have direct storage binding initializers and omission
preserves their binding. Explicit THIS^/SUPER^ access and inherited
reference slots retain v0.13 visibility and live receiver semantics.

## Initializers and lifetimes

Both `r : REFERENCE TO T := target` and `r : REFERENCE TO T REF= target` are binding
initializers. Null is allowed. A nonzero declaration initializer must directly address
ordinary writable storage, without passing through another reference; indices must be
constant expressions. The bounded profile rejects reference-chain initializers.

Allocate ordinary storage and initialize its values before binding declaration references;
forward ordinary-storage targets are therefore independent of declaration order. Persistent
reference initializers cannot target VAR_TEMP, VAR_IN_OUT or invocation-local storage.
VAR_INST initializers may target the method's own VAR_INST or the owner's persistent fields.
Nonlocal GVL targets are available after persistent storage allocation. Transient initializers
run after call inputs and temporary/local cells are available and may target live ordinary
locals, value inputs and VAR_IN_OUT aliases. Binding initializers do not run again on each
scan for persistent slots.

Attach a lifetime token to Cell storage and propagate it to all children/bit views. Reference
slots do not extend target lifetime. FUNCTION/METHOD/accessor locals and body VAR_TEMP expire
at the existing activation boundaries; persistent FB/PROGRAM/GVL/VAR_INST and Python-created
Cells stay alive with their owner. A reference through VAR_IN_OUT follows the actual Cell's
lifetime, not the aliasing invocation's lifetime.

`__ISVALIDREF(r)` accepts one reference operand and returns FALSE for null or expired targets,
TRUE for a live target, without dereferencing. This lifetime awareness is an emulator extension
over native TwinCAT's nonzero test. Reading, writing, binding or copying an expired target
raises ExecutionError; clearing it with REF=0 is allowed. Null dereference raises ExecutionError.
Passive Cell.value and inspect snapshots remain available after a runtime fault.

## Short-circuit conditions

Add BOOL-only AND_THEN and OR_ELSE at the respective AND/OR precedence and left associativity.
Evaluate the left operand once; skip the right operand when FALSE for AND_THEN or TRUE for
OR_ELSE. AND and OR retain eager evaluation. Validation still checks both operands, even if
one will be skipped; skipped calls have no side effects and skipped expressions cannot fault.
The same rules apply to supported constant expressions.

## Python and observation

Existing Runtime.call, FBHandle.call/call_method and FBHandle.set_input accept a writable,
same-runtime, live Cell or exact integer 0 for reference VAR_INPUT. Reject BitCell, foreign
runtime Cells, expired Cells, wrong types, plain values and bool. Validate an entire argument
batch before mutating bindings or data. Existing runtime.cell, global_cell, program_cell,
Cell.field and Cell.element provide storage to bind. They remain value-storage APIs and do
not create/reference raw reference slots. No new pointer-like Python object is needed.

Reference snapshots use `{reference: str(target_type), target: str(cell.type_name) or None,
valid: bool}` without dereferencing or exposing live Cell objects. Passive inspection works
for null and expired references. No raw addresses are exposed.

## Implementation boundaries

Parser: frozen syntax.ReferenceSpec(target, loc), syntax.RefAssign(target, value, loc);
always parse REFERENCE TO as ReferenceSpec. Resolved types.ReferenceType(target) is not a
value descriptor. Preserve VarDecl layout: the resolved reference type distinguishes binding
initializers, so no initializer-mode flag is needed. REF= is recognized as one case-insensitive
operator and cannot be used on ordinary declarations. __ISVALIDREF uses existing call AST.

Core: ReferenceSlot is separate from Cell, like InterfaceSlot. Separate raw slot lookup from
automatic dereference so binding/validity never accidentally read the target value. Validator
preserves reference declaration/signature types but uses target types for value operations.
Executor resolves live slots, updates lifetime ownership and handles binding initializers.

## Examples and acceptance

Add native TwinCAT source files under examples/conveyor_references, with three independent
conveyor FBs sharing one GVL configuration STRUCT through reference inputs. Configuration
contains enabled BOOL, speed LREAL and startDelay TIME. Defaults: TRUE, 0.75, T#100ms.
Python changes speed to 0.4 between scans; all three observe it. Disabling shared configuration
stops all three. Detaching the second reference stops only the second and reports missing
configuration without a null dereference. Reattach it and verify its independent start timer.

Cover parser/native-loader source positions; null/read/write/copy/rebind; whole-value replacement
and stable nested aliases; exact type checking; declaration initialization order; transient and
persistent lifetimes; inherited THIS/SUPER/VAR_INST; reference inputs through interface methods;
Python batch prevalidation and foreign/expired inputs; short-circuit effects and constant paths.
Run the full suite, Ruff through reviewdog, build wheel/sdist, run the installed wheel's tests
and the documented scenario on Python 3.11, and perform independent task/whole-branch reviews.

## Sources

- https://infosys.beckhoff.com/content/1033/tc3_plc_intro/2529458827.html (REFERENCE)
- https://infosys.beckhoff.com/content/1033/tc3_plc_intro/2529165707.html (__ISVALIDREF)
- https://infosys.beckhoff.com/content/1033/tc3_plc_intro/2528237963.html (ST expressions)
- https://infosys.beckhoff.com/content/1033/tc3_plc_intro/2528923787.html (AND_THEN)
- https://infosys.beckhoff.com/content/1033/tc3_plc_intro/2528929163.html (OR_ELSE)
