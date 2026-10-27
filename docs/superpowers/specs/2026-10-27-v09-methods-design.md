# v0.9 — FB methods

Authorized by the user's request to implement METHOD in FB, PUBLIC/PRIVATE, TcPOU import, Python calls, tests and a conveyor example.

## Contract

- Python >=3.11, standard-library-only runtime, standalone Linux-compatible execution. Preserve v0.8 behavior.
- Methods belong only to user FUNCTION_BLOCKs. Plain .st uses nested METHOD [PUBLIC|PRIVATE] Name [: Type] ... END_METHOD sections after the FB body, before END_FUNCTION_BLOCK. PUBLIC is the default. No executable FB statements after method sections.
- Methods support VAR, VAR CONSTANT, VAR_INPUT, VAR_OUTPUT, VAR_IN_OUT; optional value return through the method's short name. Ordinary method locals (including nested FBs), inputs, outputs and return values are fresh per call.
- Method inputs without explicit initializers are required. Explicitly initialized inputs may be omitted and receive that initializer each time (TwinCAT 4026 profile). IN_OUT is always required and uses existing exact-type mutable Cell rules. Named/positional ST argument rules match functions; Python accepts named arguments.
- Method locals/result shadow owner fields; owner fields shadow globals. Owner VAR_TEMP is inaccessible. References to owner VAR_IN_OUT from methods are rejected in v0.9 to prevent stale aliases; a method's own IN_OUT is supported. Constants remain immutable through all paths.
- Calls: owner body's bare M(), methods calling sibling M(), and external fb.M() including nested FB paths and GVL/PROGRAM-held instances. A method call does not execute the FB body. Value methods work in expressions and statements; void methods only in statements.
- PRIVATE may be called only from the declaring FB body or its methods (including another same-type instance from this scope). Python may only call PUBLIC methods. Duplicate method names, collisions with owner fields/owner name, unsupported modifiers and special FB_INIT/FB_REINIT/FB_EXIT names are errors. Methods are not global functions or value fields.
- All methods are statically validated, even unused. Existing static rejection of recursive call cycles is extended to methods; method invocations share clock, step budget and call-depth limit. Qualified method names appear in execution error stacks.
- FBHandle.call_method(name, /, **inputs) returns CallResult(value=None for void, outputs=immutable case-insensitive snapshot). Validate all arguments and access before mutation. Execution failures retain partial state and fault the runtime as in v0.8; argument errors do not fault it. Method calls never advance virtual time.
- TcPOU supports nested Method elements under FUNCTION_BLOCK POU, each with Name and optional Id plus exactly Declaration and Implementation/ST. Validate metadata against declarations, reject hidden declaration/body injection, preserve per-method section/line locations. Other semantic objects remain errors.
- Outside scope: methods on PROGRAM, THIS^, VAR_INST, inheritance, interfaces, properties, actions, lifecycle hooks, references/pointers, arrays of FB and ARRAY[*]. Unsupported constructs fail explicitly at load time.

## Shared implementation interfaces

- Extend syntax.Pou with trailing fields methods: tuple[Pou, ...] = (), owner: str | None = None, access: str = "PUBLIC"; property result_name returns final component of name. Parsed METHOD names are canonical owner-qualified (FB.M), owner is canonical FB name. Existing constructor positional arguments retain meaning.
- Validator flattens methods into Registry using qualified names, alongside owner POUs; methods are never globally callable. Registry.method_calls maps id(Call) to (Reference | None, qualified_method_name). Receiver None denotes the current FB instance / a method's owner. Methods' fields use resolved declarations in the flat registry.
- Frame.method_owner: Frame | None = None links a fresh method frame to its owning FB. Engine.new_method_frame(pou, owner) allocates fresh locals, output and optional result slots. Method result slot uses pou.result_name. Registry metadata selects dispatch before existing function/FB call handling.
- Constants, type bounds and call graphs use qualified method identity, while source result assignment uses result_name. Allocation containment edges of method locals are separate from persistent owner containment.

## Verification / example

Tests cover default/public/private, same method name across types, owner isolation, local shadowing and reset, fresh local timers, return/output/IN_OUT structures, defaults, forbidden owner transient storage, namespace precedence, nested receivers, unused invalid methods, recursion, limits, fault semantics and malformed XML with source locations.

Extend conveyor example with FB_Conveyor methods Start, Stop, Reset, Update, IsRunning and a private counting helper. Test public API independently and MAIN_Methods PLC cycles with existing GVL I/O, interlock priority, virtual startup delay and product edges. Keep v0.8 example usable.

References: https://infosys.beckhoff.com/content/1033/tc3_plc_intro/2530307467.html and https://infosys.beckhoff.com/content/1033/tc3_plc_intro/2527348875.html (checked 2026-10-27).
