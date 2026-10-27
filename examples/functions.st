FUNCTION F_Add : DINT
VAR_INPUT
    a, b : DINT;
END_VAR
F_Add := a + b;
END_FUNCTION

FUNCTION F_Increment : DINT
VAR_IN_OUT
    value : DINT;
END_VAR
value := value + 1;
F_Increment := value;
END_FUNCTION
