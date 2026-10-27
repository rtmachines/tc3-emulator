# v0.12 interfaces and injectable FB dependencies

User authorized the proposed bounded INTERFACE/IMPLEMENTS release. Runtime remains standalone, Python >=3.11, standard library only, Linux usable and deterministic. Preserve v0.11 behavior, including property declaration lexical scope and passive inspection. No Git repository exists; retain baseline/review artifacts under .work/v012-interfaces.

## Language and contracts

- Add INTERFACE Name ... END_INTERFACE as a declaration-only object, containing METHOD ... END_METHOD and PROPERTY ... GET END_GET / SET END_SET ... END_PROPERTY prototypes. This combined ST serialization belongs to the emulator, like existing method/property serialization. Interfaces may be empty. No EXTENDS or general pointers/references/queryinterface/lifecycle hooks.
- FUNCTION_BLOCK Name IMPLEMENTS I_First, I_Second permits one or more distinct declared interfaces, resolved regardless of file order. Other POU kinds cannot IMPLEMENTS. Interface names share the existing global type/POU namespace and cannot collide with reserved names/builtins/DUTs/GVLs.
- Reuse existing Pou/Property syntax nodes for prototypes, but require PUBLIC visibility, empty bodies, no local/instance/constant variables and no nested executable members. Method prototype sections VAR_INPUT/VAR_OUTPUT/VAR_IN_OUT use existing value types; interface-typed VAR_INPUT is also allowed. Only VAR_INPUT may carry existing constant default initializers. Property prototypes use existing scalar/enum/TIME/STRING property types and empty GET/SET declarations with no locals.
- Validate each implementing FB against every contract: public method, same ordered formal names/directions/resolved types, same return type, same required/optional input status and normalized default values. Alias equivalence follows existing canonical same_type, enum/struct nominal identity and STRING capacity remain significant. Additional implementation locals/members are allowed. Each declared property accessor must exist and be PUBLIC with exactly the contract type. Extra implementation accessors are inaccessible through a narrower contract.
- Interface prototypes are not executable and must resolve their types/defaults in interface declaration scope (global constants, no implementation locals or owner FB constants). Preserve strict diagnostics for unsupported forms even when unused.

## Interface storage and use

- Direct variables of nominal interface type in VAR, VAR_INPUT, FB/PROGRAM VAR_TEMP, METHOD VAR_INST, PROGRAM/GVL are supported; accessor VAR locals are allowed. They default to null. Interface declarations allow no initializer or literal integer 0 only. Interface VAR_INPUT default 0 makes that input optional under existing method rules. No CONSTANT, VAR_OUTPUT/VAR_IN_OUT, return values, property values, ARRAY/STRUCT elements, aliases to interfaces, or value-cell interface construction in this release.
- `target := fbInstance` stores the identity of a compatible existing FB. `target := otherInterface` copies the target identity (same nominal interface type), not a reference to its slot; `target := 0` clears it. Direct FB assignments can expose any implemented interface; cross-interface conversions are unsupported. Ordinary integer values, BOOL, arbitrary expressions, selection/arithmetic and by-value FB copying remain invalid.
- `reference = 0`, `reference <> 0` and reversed literal-zero comparisons are supported. No implicit BOOL conversion or interface-to-interface equality in this profile. __ISVALIDREF is not the interface check.
- Method/property calls dispatch to the live target implementation but expose only declared interface members. Capture receiver target once BEFORE argument evaluation or setter RHS, so reassigning the interface during evaluation does not change that invocation's receiver. Reuse current call context, virtual time, argument rules, source locations, steps/depth budget and runtime fault latch. Null dispatch raises ExecutionError, preserving earlier effects and faulting runtime.
- Interface references are non-owning edges; do not add them to FB containment. Count each owned interface slot as one scalar leaf for existing expanded budget (10,000 nested FBs, 1,000,000 scalar leaves). Expand static call graph edges conservatively to every loaded compatible implementer for interface methods/accessors, retaining recursion rejection; document possible conservative rejection of unreachable implementations.

## Lifetimes and Python

- Use explicit lifetime tracking for transient FB ownership trees, so Python object retention cannot extend ST lifetime. Function/method/accessor locals and every FB/PROGRAM VAR_TEMP activation expire at the end of their invocation, also on errors. Expiry includes nested FBs/arrays and their VAR_INST children. Owner VAR_INST follows the FB owner's lifetime, not the caller method's invocation.
- Binding/copying or dispatching an expired target raises ExecutionError. Comparing an expired reference with zero also raises ExecutionError (do not silently treat a dangling reference as null); explicit `:= 0` is permitted. These are checked emulator rules rather than hardware pointer behavior. Passive inspection must remain possible after fault.
- Extend Runtime.call, FBHandle.call/call_method and FBHandle.set_input to accept FBHandle for an interface VAR_INPUT. Accept exact integer 0 for null; reject None, BOOL, raw objects/frames, Cell, nonimplementers and handles from another Runtime before any persistent writes or execution. Public Value/Cell semantics for ordinary arguments remain unchanged.
- Existing handles from instantiate/program_fb/global_fb/fb refer to the same instance supplied to ST. Interface slots are not Cell. global_cell/program_cell/fb selectors must reject wrong storage categories with ArgumentError, never expose internal slot objects or execute getters.
- inspect() includes interface slots as detached diagnostic dictionaries `{interface: 'I_MOTOR', target: 'FB_MOTORFAKE'|None, valid: bool}`. Do not recursively follow interface targets (cycles and shared references are legal). This is diagnostic metadata, never a live handle. Existing stored-state/$VAR_INST snapshots remain intact.

## Import

- .TcIO uses TcPlcObject / Itf(Name, optional Id), exactly one Declaration, Method children with Name/Id and Declaration only, Property children with Name/Id, Declaration and Get/Set children containing Declaration only (optional Name/Id, matching accessor kind). Verified native sample: https://github.com/Beckhoff-USA-Community/AMR_Demo/blob/06cd17c5b1f1b80851d5958461359e8d18aad5e1/AMR_Demo/PLC/AMR/Interface/I_AmrModule.TcIO . That sample includes unsupported inheritance/interface-return properties; only its XML shape informs this subset.
- Reject Implementation elements, duplicate sections/accessors, unknown attributes/tags, metadata mismatch, bodies/injected objects in declarations, DTD/entities. Preserve per-interface/member/accessor Declaration source locations. Existing .TcPOU permits IMPLEMENTS in FB header; other importers must reject leaked interface declarations. Aggregate Program.interfaces across files including .st and .TcIO, with BOM/case-insensitive extension as existing loaders.

## Internal interfaces

- syntax.InterfaceDecl(name: str, methods: tuple[Pou,...], properties: tuple[Property,...], loc: Location).
- Program appends interfaces: tuple[InterfaceDecl,...]=(); Pou appends implements: tuple[str,...]=(). Prototypes use METHOD / PROPERTY_GET / PROPERTY_SET, qualified names I_Name.Member[.GET/.SET], owner=interface name. Existing property_name/result_name contracts remain.
- types.InterfaceType(name: str), frozen nominal normalized identifier, added to TypeSpec, never Value/is_value_type/default_value/array/Cell.
- Registry has separate interface contracts and implementation sets/dispatch metadata. Engine uses InterfaceSlot separate from Cell plus lifetime tokens on owned frame trees. Core worker owns exact metadata design because validation/execution/API are one coupled task.

## Example and acceptance

Preserve past examples. Add examples/conveyor_interfaces with I_Motor.TcIO, FB_MotorSim, configurable FB_MotorFake, FB_Conveyor, MAIN_Line and GVL_Line. BindMotor accepts I_Motor and stores it; Update commands and reads motor via interface. Three conveyors use independent motor state; Python can replace one dependency with the fake and toggle its fault input. Use virtual-time startup, running/speed properties, missing motor/fault diagnostics and intentional restart after a cleared fault.

Tests must cover exact signature/default/accessor matching, nominal/alias/string types, multiple implementations/interfaces, null and expired targets, copying vs sharing slots, receiver capture before mutations, private/narrow contract access, conservative cycles, Python prevalidation and cross-runtime isolation, persistent/temporary lifetimes, getter/setter effects and passive snapshots. Import tests cover strict XML and location boundaries. Full regression, Ruff via reviewdog, format, executable README examples and built-wheel examples on isolated Python3.11 required.

References: https://infosys.beckhoff.com/content/1033/tc3_plc_intro/4256428299.html and https://infosys.beckhoff.com/content/1033/tc3_plc_intro/5680748299.html .
