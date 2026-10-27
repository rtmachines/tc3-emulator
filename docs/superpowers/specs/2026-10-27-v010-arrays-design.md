# v0.10 — FB arrays and open array parameters

User authorized implementation after the v0.10 proposal. Extend the standalone Python ST interpreter, with no TwinCAT installation or runtime dependencies. Python >=3.11, preserve v0.9 behavior.

## User-visible contract

- Fixed arrays (1–8 dimensions, inclusive DINT bounds, negative/nonzero lower bounds) of user and standard FBs, including TON/TOF/TP. Legal as local VAR, FB/PROGRAM VAR_TEMP, method-local VAR and GVL storage, with existing lifetime rules. Each element is a distinct instance. No FB-array initialization/copying/value passing/return, aliases/STRUCT embedding of FB arrays or open FB arrays.
- Indexed instance calls `blocks[i](...)`, method calls `blocks[i].Reset()`, input writes/output reads and namespace paths such as `GVL.blocks[i].Reset()`. Preserve PUBLIC/PRIVATE and existing field access rules. Select and bounds-check the receiver exactly once, before evaluating arguments; selector side effects must not cause re-selection.
- `ARRAY[*] OF T` / `ARRAY[*, *] OF T` for direct VAR_IN_OUT parameters of FUNCTION, FUNCTION_BLOCK and METHOD only; rank 1–8, all dimensions open (mixed open/fixed unsupported), no initializer. T is an existing resolved value type, including aliases, structures, enums and STRING. No open arrays as types/fields, local variables, results, VAR_INPUT/OUTPUT or PROGRAM parameters.
- Open parameter binding requires equal rank and canonical exact element type. A fixed array or another open parameter may be passed; the actual Cell and actual fixed bounds are retained. Fixed-array IN_OUT keeps exact-bound matching. A Python caller supplies an existing fixed-array Cell of the same Runtime; read-only and bit Cells remain invalid. No implicit list conversion, rebasing or copying.
- Open parameters support indexed access, bounds queries and forwarding to open parameters. Whole open-array value operations/assignment/returns and passing an open parameter to a fixed-array formal are unsupported.
- `LOWER_BOUND(array, dimension)` and `UPPER_BOUND(array, dimension)` accept exactly two positional arguments: an array storage location and an integer dimension expression numbered 1..rank. Fixed value arrays, fixed FB arrays and open parameters supported. Result DINT; invalid dimensions raise source-aware ExecutionError and fault as usual. Arrays/indices and dimension evaluated once, source order; no array value snapshot needed. Runtime expressions only; declaration constant expressions remain call-free. Fixed array support follows TwinCAT build4026 profile.
- Python `Runtime.program_fb(program_name, variable_name, *indices)`, `Runtime.global_fb(gvl_name, variable_name, *indices)`, `FBHandle.fb(variable_name, *indices)` return handles to existing scalar FB or a selected fixed-array element. Names are direct variable identifiers, case-insensitive; indices are ST indices, exact int (not bool), exact rank. Chain `.fb(...)` for nested instances. Never instantiate/copy while selecting. Reject non-FB, missing/wrong indices and VAR_TEMP with ArgumentError before mutation. Handles may be acquired/read after fault; execution/mutation still fails. `.inspect()` includes detached snapshots of FB arrays with matching tuple shape.
- Allocation preflight rejects containment cycles including FB-array edges. Enforce per-root POU expanded storage limits: at most 10,000 nested FB instances and 1,000,000 scalar value leaves, including multiplication by FB-array sizes; IN_OUT aliases allocate no owned storage. Preserve existing value-array/type limits. No actual instances created during validation.
- Tests and docs cover the new features, strict unsupported cases, source errors, lifetimes and resource bounds. Ship v0.10.0 with an example of three conveyors using v0.9 FB_Conveyor, distinct delays, I/O arrays and an open-array aggregation function.

## Shared interfaces / ownership

Task 1 owns types.py, syntax.py, parser.py and foundation tests:
- `Call.target: LValue` (old Reference shapes retained for simple calls).
- `OpenArrayType(rank: int, element_type: TypeSpec)` frozen descriptor, rank1..8; `FBArrayType(bounds: tuple[tuple[int,int],...], element_type: str)` frozen resolved instance-array descriptor with normalized bounds/name, shape and size properties. Both included in TypeSpec but excluded from is_value_type and resolve_type (Python Cell creation). canonical_type handles OpenArrayType canonical element; FBArrayType unchanged; value utilities reject them.
- `inout_compatible(expected: TypeSpec, actual: TypeSpec) -> bool`: normal uses same_type; open expected accepts ArrayType/OpenArrayType actual with exact canonical element/rank. Does not accept FBArrayType.
- Syntax `OpenArrayBounds(rank: int, element_type: TypeSpec | StringBounds, loc: Location)` holds unresolved STRING capacity when needed; ordinary open parse returns OpenArrayType. Fixed FB declarations initially parse as ArrayType/ArrayBounds; validator converts only allowed FB-array declarations to FBArrayType.

Task 2 owns validation.py and validation tests:
- Flatten/resolve declaration metadata as before, converting fixed FB arrays and resolving open value-element types, including bounds constant preflight. Check context/containment/allocation rules.
- `Registry.method_calls: dict[int, tuple[LValue | None, str]]` (widened receiver; same semantics).
- `Registry.bound_calls: dict[int, tuple[LValue, Expr, bool]]`, bool=True for UPPER_BOUND, False for LOWER_BOUND. Recognize operator names in call resolution and reserve POU/type names as other builtins; local symbols and owner methods retain existing shadowing rules.
- Reference/index validation supports ArrayType, FBArrayType, OpenArrayType. Instance arrays are not value types. Method target splitting handles both Reference and Member receivers.

Task 3 owns memory.py, execution.py, runtime.py and runtime/API tests:
- `FBArray(type_name: FBArrayType, items: tuple[Frame,...])` storage with `_element(indices: tuple[int,...]) -> Frame`, `inspect()` nested tuple of detached dictionaries. Row-major last-index-fastest. Frame.slots includes FBArray.
- Execution allocates each instance independently. resolve(Index) accepts Cell or FBArray; storage remains Cell-only. Bound calls resolve actual storage and rank without copying values. Receiver resolves once before inputs; type result lookup must support indexed methods/calls safely.
- Python handles and open Cell argument validation follow above contract and shared inout_compatible.

Root owns docs/version, example and integration tests, baseline/review packaging. Parallel validator/runtime editing is safe after foundation interfaces land; no shared-file writes.

## References

- https://infosys.beckhoff.com/content/1033/tc3_plc_intro/8825253771.html
- https://infosys.beckhoff.com/content/1033/tc3_plc_intro/8825257611.html
- https://infosys.beckhoff.com/content/1031/tc3_plc_intro/21269831691.html

Checked2026-10-27. The profile deliberately excludes open FB arrays and dynamic allocation.
