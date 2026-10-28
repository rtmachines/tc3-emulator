# v0.15: function-block initialization

## Intent and authorization

The user selected FB initialization and explicitly requested implementation of FB_init,
initialization parameters, call_after_init, inheritance, tests and a three-conveyor example.
This document makes that accepted scope concrete; implementation proceeds in the isolated
codex/v015-fb-init worktree based on v0.14 commit 85f5b1f.

## Approaches

1. Extend the existing typed frame allocation with a checked initialization phase (selected).
   Reuse stable Cell storage, reference lifetimes, method execution and budgets.
2. Actions and selected attribute compatibility would improve import coverage but not instance setup.
3. General pointers would unlock other libraries but require a separate memory-layout project.

## Global constraints

- Python >=3.11; standard-library-only runtime; Linux without installed TwinCAT.
- Preserve v0.14 checked arithmetic, virtual time, stable aliases, source locations and resource limits.
- Initialize new instances only: no restart, RETAIN/PERSISTENT, online change, FB_exit or FB_reinit.
- Do not claim native TwinCAT parity without differential execution on TwinCAT.
- Unknown attributes and unsupported constructs remain errors, including in unused source.

## FB_init and parameters

FB_init is a special public METHOD returning BOOL. Its first two parameters are exactly
bInitRetains : BOOL and bInCopyCode : BOOL, both VAR_INPUT, without defaults. The runtime
supplies TRUE and FALSE respectively for its new-instance profile. The implicit return value
is ignored, including FALSE. Additional VAR_INPUT parameters use existing value, reference
and interface types. VAR_OUTPUT/VAR_IN_OUT are not supported on this lifecycle method.
Default extra inputs follow ordinary method rules. Explicit FB_init calls from ST or Python,
including SUPER^.FB_init, are rejected in this profile instead of silently reinitializing storage.

ST instance declarations accept named or positional extra parameters, for example
`motor : FB_Motor(nAxisId := 1);`. Mixed forms, duplicate/unknown/missing parameters and
attempts to supply the two system flags are errors. Fixed FB arrays accept shared arguments
after the element type or a flat per-element list `[(id := 1), (id := 2)]` in declaration order.
An explicitly supplied element list must cover every element exactly. Existing array bounds
and flattening order apply. The parser records arguments separately from post-init values.

Post-init assignments use `fb : FB(n := 1) := (input := 2, Property := 3);` and the analogous
array initializer. Targets are existing writable public inputs and public property setters;
no arbitrary private state. Reference/interface inputs bind identity rather than copying data.
Apply post-init entries in ST source order (Python mapping insertion order). Evaluate each ST
right-hand side immediately before its assignment, after FB_init; a setter may affect later values.
Parameter and input expressions are checked in the declaring lexical scope. Constant value
expressions and direct storage values/references are supported; side-effecting calls/property
reads in declaration expressions may be rejected explicitly to keep setup deterministic.
Persistent initialization must not capture transient locals or VAR_IN_OUT. Transient FB setup
is evaluated after invocation inputs are bound. Forward references to already allocated data
are allowed; cross-instance initialization ordering is not a dependency scheduler.

Python exposes `Runtime.instantiate(name, *, init=None, inputs=None)`. Both optional arguments
are mappings: init supplies extra FB_init inputs, inputs supplies post-init FB inputs/property
values. Names are case-insensitive. Validate all supplied arguments before any user ST runs;
bad arguments raise ArgumentError and leave the Runtime healthy. Existing instantiate(name)
continues to work when no required init parameters are missing.

## Ordering and inheritance

All owned storage is allocated before initialization. Global/PROGRAM storage is allocated for
the complete runtime before any startup methods execute. A separate preparation pass binds
declaration reference initializers throughout the allocated persistent tree before lifecycle
execution, so a nested/global constructor can consume an enclosing or forward reference.
For transient activations, bind call inputs and prepare declaration references before initializing
local children. Initialize nested instances before their owner, preserving declaration order
and existing reference initializer scopes. For each FB:

1. Initialize declared storage and reference bindings.
2. Execute explicitly declared FB_init implementations from oldest base to most-derived FB.
3. Apply the instance declaration's post-init input/property assignments.
4. Execute effective call_after_init hooks once.

Derived FB_init preserves the complete base parameter prefix (names, directions, resolved types,
defaults) and may append extra inputs. Each implementation receives only its own signature.
An inherited FB_init runs even if the child does not redeclare it. Normal method dispatch rules
continue inside lifecycle bodies. FB_init chaining itself is static and automatic.

`{attribute 'call_after_init'}` is allowed immediately before FUNCTION_BLOCK and METHOD.
A marked method requires a marked owner; descendants of a marked FB must also be marked.
Hooks are methods with no formal parameters (local VAR/VAR_INST are allowed), and may have
an ordinary return value which is ignored. Lifecycle method names cannot carry this attribute.
Inherited hooks use the effective implementation once per name; an override must retain the
attribute. Base hook behavior is invoked explicitly with SUPER^.Hook(), not automatically
duplicated. Distinct hook names run in base-to-derived declaration order (documented profile).

Persistent instances initialize once; repeated calls/scans do not repeat setup. Function/method
locals initialize once per activation, VAR_TEMP once per body call, VAR_INST once per owning FB.
Initializers share the enclosing Context budget/depth/time; startup uses one bounded context.
Initialization failure raises a source-aware ExecutionError and faults an existing Runtime.
Reference lifetimes stay bounded by the owning storage, including references that escape setup.

## Internal syntax contract

- `Pou.call_after_init: bool = False`.
- `VarDecl.init_arguments: tuple[Argument, ...] | None = None` for single/shared arguments.
- `VarDecl.element_init_arguments: tuple[tuple[Argument, ...], ...] | None = None` for arrays.
- `VarDecl.initial` retains post-init StructInitializer/ArrayInitializer for FB declarations.
- New fields are appended with defaults to preserve existing positional constructors.
- Native TcPOU importer preserves pragmas on FB and Method declarations and original locations.

Registry details and helper factoring are implementation decisions. Initialization metadata
must retain the declaration's lexical owner; do not evaluate inherited declarations in child scope.
Implicit lifecycle edges and temporary-instance creation participate in cycle/limit analysis.

## Acceptance

Parser/loader, validation and runtime tests cover parameters, flag/return semantics, inheritance,
post-init setters, hooks, arrays, transients, Python atomic argument checks, faults and budgets.
The native-format three-conveyor example has shared referenced configuration, distinct init IDs,
inherited setup and an after-init hook, is ready before the first scan, and keeps independent timers.
Tests verify startup order/counts, delays 100/250/500 ms, live shared configuration and no repeated
initialization. Existing suite, Ruff through reviewdog, formatting, package build and installed
wheel smoke tests must pass. A small native-compatible order fixture documents expected traces;
actual TwinCAT execution is a future external verification, not a claim of this release.

## References

- https://infosys.beckhoff.com/content/1033/tc3_plc_intro/5094414603.html
- https://infosys.beckhoff.com/content/1033/tc3_plc_intro/2529600907.html
- https://infosys.beckhoff.com/content/1033/tc3_plc_intro/5482088715.html
