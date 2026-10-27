"""Public source-aware error hierarchy."""

from __future__ import annotations

from .syntax import Location


class STError(Exception):
    def __init__(self, message: str, loc: Location | None = None, stack: tuple[str, ...] = ()):
        self.message = message
        self.loc = loc
        self.stack = stack
        super().__init__(message)

    def __str__(self) -> str:
        prefix = f"{self.loc.source}:{self.loc.line}:{self.loc.column}: " if self.loc else ""
        suffix = f" [ST: {' -> '.join(self.stack)}]" if self.stack else ""
        return f"{prefix}{self.message}{suffix}"


class ParseError(STError):
    pass


class ValidationError(STError):
    pass


class ExecutionError(STError):
    pass


class ArgumentError(STError):
    pass


class RuntimeFaultedError(ExecutionError):
    pass
