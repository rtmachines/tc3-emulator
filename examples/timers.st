FUNCTION F_AddDelay : TIME
VAR_INPUT
    base : TIME;
END_VAR
F_AddDelay := base + T#250ms;
END_FUNCTION

FUNCTION_BLOCK FB_Timers
VAR_INPUT
    signal : BOOL;
    onDelay : TIME := T#100ms;
    offDelay : TIME := T#200ms;
    pulseWidth : TIME := T#50ms;
END_VAR
VAR_OUTPUT
    delayedOn, delayedOff, pulse : BOOL;
    onElapsed, offElapsed, pulseElapsed : TIME;
END_VAR
VAR
    onTimer : TON;
    offTimer : TOF;
    pulseTimer : TP;
END_VAR
onTimer(IN := signal, PT := onDelay, Q => delayedOn, ET => onElapsed);
offTimer(IN := signal, PT := offDelay, Q => delayedOff, ET => offElapsed);
pulseTimer(IN := signal, PT := pulseWidth, Q => pulse, ET => pulseElapsed);
END_FUNCTION_BLOCK
