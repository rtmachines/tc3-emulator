# v0.11: FB properties, explicit self access and method instance variables

User authorized implementation after the proposed bounded v0.11 scope. No additional approval gate is needed. Runtime stays standalone, Python >=3.11, standard library only, Linux usable and deterministic.

## Contract

- FB-only PROPERTY declarations, PUBLIC by default or PRIVATE, one GET and/or SET. Accessors may use PUBLIC/PRIVATE but may not broaden a PRIVATE property. Read-only/write-only properties reject the missing operation during validation/API argument checking. Supported property types: existing scalar types, TIME, STRING(n), ENUM and aliases thereof; no aggregate/reference/FB property values.
- Plain ST serialization inside FUNCTION_BLOCK, after its body, interleaved with METHOD: `PROPERTY PUBLIC Speed : LREAL`, optional property-local VAR/VAR CONSTANT, `GET` with optional access modifier and local VAR/VAR CONSTANT, statements, `END_GET`, similarly SET/END_SET, `END_PROPERTY`. This serialization is this interpreter's textual format for TwinCAT objects, not a claimed native TwinCAT combined syntax.
- Properties contain no VAR_INPUT/OUTPUT/IN_OUT/TEMP/INST. Property header locals are fresh for each accessor invocation, shared declarations but not shared storage; accessor-local name collisions with them are rejected. The property type and its header variable types, bounds, initializers and constant dependencies resolve in the property declaration scope (header constants plus owner-visible constants), excluding accessor-local declarations. GET and SET share the same resolved property type; accessor-local declarations and bodies retain their own shadowing scope. Property name inside its own accessor is the fresh result/value slot, including SET reads and GET assignment. An explicit THIS^.Property performs real access and thus participates in recursion checking.
- Every getter read and setter write executes its accessor with shared caller time, budgets and fault semantics. No caching or automatic access during inspect(). Resolve an indexed FB receiver once before RHS/arguments. Property assignment writes only the property and executes no getter. Properties are values/computations, never Cell storage: reject VAR_IN_OUT binding, FOR counters, partial/bit writes and output `=>` destinations. Whole-property reads may appear in normal value expressions and VAR_INPUT arguments.
- THIS^ supports fields, methods, properties of the current FB from the body, methods and accessors, including shadowed/private owner fields. Direct THIS value/pointer, THIS() and general dereferencing are unsupported. Existing owner VAR_TEMP/VAR_IN_OUT method restrictions also apply to accessors; explicit THIS^ cannot bypass them. THIS^ does not expose private fields of other nested FBs.
- VAR_INST is allowed only in FB METHOD declarations, without CONSTANT/RETAIN/PERSISTENT modifiers. Values, value arrays/structures, scalar FBs/timers and fixed FB arrays use existing declaration rules. Initializers remain constant expressions evaluated in owner-visible constant scope; no method-local constant, method-input/instance-variable or mutable owner dependencies. Type bounds use the same owner-visible constant scope for VAR_INST. Storage is allocated once with its owner FB, unique per owner instance and method, and survives method calls/scans. Ordinary VAR remains fresh. Function/method-local owners still have their normal fresh lifetimes.
- Include VAR_INST in expanded owner containment and allocation preflight: 10,000 nested FB instances and 1,000,000 scalar leaves. Recursion involving persistent method-owned FBs must fail before allocation; budgets include multiplication through FB arrays. Invocation-local method budgets also remain enforced.
- Python FBHandle.get_property(name, /) -> Value and set_property(name, value, /) -> None call only PUBLIC available accessors on existing instances. Names are case-insensitive. Bad name/type/access fails before accessor execution or any mutation. Both calls execute ST, so both are blocked after runtime fault; inspect/output remain read-only diagnostics. Runtime errors preserve partial writes and fault the runtime.
- .TcPOU accepts Property Name/Id, Declaration and Get/Set children containing Declaration and Implementation/ST, with optional accessor Name/Id metadata handled strictly. Property header and accessor declaration/body locations must remain meaningful. Reject duplicate accessors, malformed metadata, unsupported XML/attributes, executable code in declarations and nested object injection. Existing Method import remains compatible.
- No inheritance/interfaces/FB_init/general pointers/REFERENCE TO, PROPERTY in PROGRAM, or aggregate properties in this release. Existing 0.10 profiles remain intact.

## Internal interfaces

- syntax.This(loc) is an LValue node, used as base of Member/Index; it is never a value by itself.
- syntax.Property(name, type_name, variables, getter, setter, loc, access='PUBLIC'), getter/setter Pou or None.
- Pou appends properties: tuple[Property,...]=(), property_name: str|None=None; result_name uses property_name when present.
- Accessor Pou kinds PROPERTY_GET/PROPERTY_SET, names OWNER.PROPERTY.GET/SET, owner=OWNER, property_name=PROPERTY, return_type=property type for both. Their variables include property-header locals followed by accessor locals.
- Registry flattens accessors like methods, holds resolved properties keyed by (owner type name, property name); property access metadata maps source LValue identities to receiver and selected accessor, with separate read/write intent. Internal design may improve this contract if recorded before dependent edits.
- Frame retains per-method VAR_INST slots separately from ordinary FB slots; inspect includes only detached stored state and never executes code. When method instance storage is nonempty, include it under reserved key `$VAR_INST`, mapping uppercase short method names to detached slot dictionaries; `$` is not legal in ST identifiers, so fields cannot collide.

## Example and evidence

Preserve existing examples. Add an enhanced line of three conveyor FBs importing real .TcPOU property objects. Include SpeedSetpoint validated/clamped through SET, Running read-only, and method-local persistent timer/counter via VAR_INST with THIS^ accesses. Tests drive separate instances through virtual-time cycles and Python properties.

Tests cover malformed declarations/imports, access control, shadowing/result slot, getter effects exactly once, setter no getter, indexed receiver selection before RHS, type/range errors before execution, recursive accessor graphs, VAR_INST lifetimes and isolation, expanded ownership limits and inspect/fault behavior. Run full regression, Ruff+reviewdog, format, and wheel examples from a clean Python3.11 environment.

## References

- https://infosys.beckhoff.com/content/1033/tc3_plc_intro/2530335371.html
- https://infosys.beckhoff.com/content/1033/tc3_plc_intro/2528843147.html
- https://infosys.beckhoff.com/content/1033/tc3_plc_intro/2528798091.html
