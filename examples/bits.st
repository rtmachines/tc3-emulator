FUNCTION_BLOCK FB_DeviceWords
VAR_INPUT
    status : WORD;
    enable : BOOL;
    acknowledge : BOOL;
END_VAR
VAR_IN_OUT
    command : WORD;
END_VAR
VAR_OUTPUT
    ready : BOOL;
    fault : BOOL;
    errorCode : BYTE;
END_VAR
VAR CONSTANT
    cReadyBit : INT := 0;
    cFaultBit : INT := 3;
    cEnableBit : INT := 7;
    cAcknowledgeMask : WORD := WORD#8#100000;
END_VAR
ready := status.cReadyBit;
fault := status.cFaultBit;
errorCode := WORD_TO_BYTE(SHR(status, 8));
command.cEnableBit := enable AND NOT fault;
command := (command AND NOT cAcknowledgeMask)
    OR SEL(acknowledge, WORD#0, cAcknowledgeMask);
END_FUNCTION_BLOCK

FUNCTION F_PackWords : DWORD
VAR_INPUT
    low : WORD;
    high : WORD;
END_VAR
F_PackWords := SHL(WORD_TO_DWORD(high), 16) OR WORD_TO_DWORD(low);
END_FUNCTION

FUNCTION F_HighByte : BYTE
VAR_INPUT
    value : DWORD;
END_VAR
F_HighByte := DWORD_TO_BYTE(SHR(value, 24));
END_FUNCTION

FUNCTION F_RotateMask : BYTE
VAR_INPUT
    mask : BYTE;
END_VAR
F_RotateMask := ROL(mask, 1);
END_FUNCTION
