"""Standard timer interfaces and deterministic state driven only by virtual time."""

from dataclasses import dataclass

from tc_emulator.syntax import Location, Pou, VarDecl

TIMER_NAMES = frozenset({"TON", "TOF", "TP"})


def timer_definitions() -> tuple[Pou, ...]:
    """Use normal FB declarations so builtins share all existing type/call checks."""
    location = Location("<builtin timers>", 1, 1)
    variables = tuple(
        VarDecl(name, kind, section, None, location)
        for name, kind, section in (
            ("IN", "BOOL", "VAR_INPUT"),
            ("PT", "TIME", "VAR_INPUT"),
            ("Q", "BOOL", "VAR_OUTPUT"),
            ("ET", "TIME", "VAR_OUTPUT"),
        )
    )
    return tuple(
        Pou("FUNCTION_BLOCK", name, None, variables, (), location) for name in ("TON", "TOF", "TP")
    )


@dataclass
class TimerState:
    """Per-instance timing state; preset is latched for each triggered interval."""

    kind: str
    started_ms: int | None = None
    preset_ms: int = 0
    previous_in: bool = False

    def update(self, input_value: bool, preset_ms: int, now_ms: int) -> tuple[bool, int]:
        if self.kind == "TON":
            if not input_value:
                self.started_ms = None
                return False, 0
            if self.started_ms is None:
                self.started_ms, self.preset_ms = now_ms, preset_ms
            elapsed = now_ms - self.started_ms
            return elapsed >= self.preset_ms, min(elapsed, self.preset_ms)

        if self.kind == "TOF":
            falling = self.previous_in and not input_value
            self.previous_in = input_value
            if input_value:
                self.started_ms = None
                return True, 0
            if falling:
                self.started_ms, self.preset_ms = now_ms, preset_ms
            if self.started_ms is None:
                return False, 0
            elapsed = now_ms - self.started_ms
            return elapsed < self.preset_ms, min(elapsed, self.preset_ms)

        if self.kind == "TP":
            if self.started_ms is None:
                if not input_value:
                    return False, 0
                self.started_ms, self.preset_ms = now_ms, preset_ms
            elapsed = now_ms - self.started_ms
            if elapsed >= self.preset_ms:
                if not input_value:
                    self.started_ms = None
                    return False, 0
                return False, self.preset_ms
            return True, elapsed

        raise ValueError(f"Unknown timer kind {self.kind}")
