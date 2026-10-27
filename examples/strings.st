(* Latin-1 text handling: no TwinCAT installation or external libraries needed. *)
TYPE ST_TextRecipe : STRUCT
    label : STRING(16);
END_STRUCT END_TYPE

FUNCTION F_AlarmText : STRING(80)
VAR_INPUT
    device : STRING(24);
    code : DINT;
    active : BOOL;
END_VAR
F_AlarmText := CONCAT(device, ': alarm ');
F_AlarmText := CONCAT(F_AlarmText, DINT_TO_STRING(code));
F_AlarmText := CONCAT(F_AlarmText, CONCAT(' [', CONCAT(BOOL_TO_STRING(active), ']')));
END_FUNCTION

FUNCTION F_ParseSpeed : DINT
VAR_INPUT command : STRING(80); END_VAR
VAR_OUTPUT valid : BOOL; END_VAR
VAR CONSTANT prefix : STRING(6) := 'SPEED='; END_VAR
valid := LEFT(command, LEN(prefix)) = prefix AND LEN(command) > LEN(prefix);
IF valid THEN
    (* Malformed or overflowing numbers raise a checked execution error. *)
    F_ParseSpeed := STRING_TO_DINT(MID(command, LEN(command), LEN(prefix) + 1));
END_IF;
END_FUNCTION

FUNCTION_BLOCK FB_SpeedCommand
VAR_INPUT command : STRING(80); END_VAR
VAR_OUTPUT accepted : BOOL; speed : DINT; END_VAR
VAR_TEMP nextSpeed : DINT; END_VAR
nextSpeed := F_ParseSpeed(command := command, valid => accepted);
IF accepted THEN
    speed := nextSpeed;
END_IF;
END_FUNCTION_BLOCK

FUNCTION F_AppendLabel : BOOL
VAR_IN_OUT label : STRING(16); END_VAR
VAR_INPUT suffix : STRING(8); END_VAR
label := CONCAT(label, suffix);
F_AppendLabel := TRUE;
END_FUNCTION
