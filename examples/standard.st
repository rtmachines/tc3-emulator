TYPE ST_BatchConfig : STRUCT
    target : WORD := 3;
    releaseDelay : TIME := T#100ms;
    speed : REAL := 10.0;
END_STRUCT END_TYPE

FUNCTION_BLOCK FB_Batch
VAR_INPUT
    sensor : BOOL;
    reset : BOOL;
    config : ST_BatchConfig;
END_VAR
VAR_OUTPUT
    count : WORD;
    targetReached : BOOL;
    release : BOOL;
    speedCommand : INT;
END_VAR
VAR
    edge : R_TRIG;
    counter : CTU;
    reachedLatch : RS;
    releaseTimer : TON;
END_VAR
edge(CLK := sensor);
counter(CU := edge.Q, RESET := reset, PV := config.target, CV => count);
reachedLatch(SET := counter.Q, RESET1 := reset, Q1 => targetReached);
releaseTimer(IN := targetReached, PT := config.releaseDelay, Q => release);
speedCommand := REAL_TO_INT(LIMIT(REAL#0.0, config.speed, REAL#100.0));
END_FUNCTION_BLOCK

FUNCTION F_ConstantTable : DINT
VAR CONSTANT
    cCount : INT := 3;
    cScale : INT := cCount * 2;
END_VAR
VAR
    values : ARRAY[1..cCount] OF INT := [cScale, cScale + 2, cScale + 4];
    index : INT;
END_VAR
FOR index := 1 TO cCount DO
    F_ConstantTable := F_ConstantTable + values[index];
END_FOR;
END_FUNCTION

FUNCTION F_SafeRatio : LREAL
VAR_INPUT
    numerator : LREAL;
    denominator : LREAL;
END_VAR
F_SafeRatio := SEL(denominator <> 0.0, 0.0, numerator / denominator);
END_FUNCTION
