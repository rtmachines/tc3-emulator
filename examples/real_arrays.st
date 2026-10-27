FUNCTION F_Mean : LREAL
VAR_INPUT
    samples : ARRAY[1..4] OF LREAL;
END_VAR
VAR
    i : INT;
END_VAR
FOR i := 1 TO 4 DO
    F_Mean := F_Mean + samples[i];
END_FOR;
F_Mean := F_Mean / 4.0;
END_FUNCTION

FUNCTION F_Scale : BOOL
VAR_INPUT
    factor : REAL;
END_VAR
VAR_IN_OUT
    values : ARRAY[-1..1] OF REAL;
END_VAR
VAR
    i : INT;
END_VAR
FOR i := -1 TO 1 DO
    values[i] := values[i] * factor;
END_FOR;
F_Scale := TRUE;
END_FUNCTION

FUNCTION F_Trace : LREAL
VAR_INPUT
    matrix : ARRAY[-1..0, -1..0] OF LREAL;
END_VAR
F_Trace := matrix[-1, -1] + matrix[0, 0];
END_FUNCTION
