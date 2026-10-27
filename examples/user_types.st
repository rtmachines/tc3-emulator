TYPE
    E_State : (Idle := 0, Waiting := 10, Running := 20) INT := Idle;
    T_Speed : REAL := 1.5;
    T_Recipe : ARRAY[-1..1] OF ST_Config;
END_TYPE

FUNCTION F_Accelerated : ST_Config
VAR_INPUT
    config : ST_Config;
END_VAR
config.speed := config.speed + 1;
F_Accelerated := config;
END_FUNCTION

FUNCTION F_SetSpeed : BOOL
VAR_IN_OUT
    config : ST_Config;
END_VAR
VAR_INPUT
    speed : T_Speed;
END_VAR
config.speed := speed;
F_SetSpeed := TRUE;
END_FUNCTION

FUNCTION F_Recipe : T_Recipe
VAR
    configs : T_Recipe := [(speed := 2, delay := T#50ms), (speed := 4)];
END_VAR
F_Recipe := configs;
END_FUNCTION

FUNCTION_BLOCK FB_Machine
VAR_INPUT
    start : BOOL;
    config : ST_Config;
END_VAR
VAR_OUTPUT
    state : E_State;
    activeSpeed : REAL;
END_VAR
VAR
    delayTimer : TON;
END_VAR
delayTimer(IN := start AND config.enabled, PT := config.delay);
CASE state OF
    E_State.Idle:
        IF start AND config.enabled THEN state := E_State.Waiting; END_IF;
    E_State.Waiting:
        IF NOT start OR NOT config.enabled THEN
            state := E_State.Idle;
        ELSIF delayTimer.Q THEN
            state := E_State.Running;
        END_IF;
    E_State.Running:
        IF NOT start OR NOT config.enabled THEN state := E_State.Idle; END_IF;
END_CASE;
IF state = E_State.Running THEN
    activeSpeed := config.speed;
ELSE
    activeSpeed := 0;
END_IF;
END_FUNCTION_BLOCK
