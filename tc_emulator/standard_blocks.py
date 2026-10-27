"""Standard PLC block interfaces and state advanced only by explicit calls."""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import cast

from tc_emulator.syntax import Location, Pou, VarDecl
from tc_emulator.types import Value

STANDARD_BLOCK_NAMES = frozenset({"R_TRIG", "F_TRIG", "SR", "RS", "CTU", "CTD", "CTUD"})


def standard_block_definitions() -> tuple[Pou, ...]:
    """Declare normal FB ports so builtins use the existing type and call checks."""
    location = Location("<builtin standard blocks>", 1, 1)
    interfaces = {
        "R_TRIG": (("CLK",), ("Q",)),
        "F_TRIG": (("CLK",), ("Q",)),
        "SR": (("SET1", "RESET"), ("Q1",)),
        "RS": (("SET", "RESET1"), ("Q1",)),
        "CTU": (("CU", "RESET", "PV"), ("Q", "CV")),
        "CTD": (("CD", "LOAD", "PV"), ("Q", "CV")),
        "CTUD": (("CU", "CD", "RESET", "LOAD", "PV"), ("QU", "QD", "CV")),
    }
    definitions = []
    for kind, (inputs, outputs) in interfaces.items():
        variables = tuple(
            VarDecl(name, "WORD" if name in {"PV", "CV"} else "BOOL", section, None, location)
            for section, names in (("VAR_INPUT", inputs), ("VAR_OUTPUT", outputs))
            for name in names
        )
        definitions.append(Pou("FUNCTION_BLOCK", kind, None, variables, (), location))
    return tuple(definitions)


@dataclass
class StandardBlockState:
    """Remember sampled edges; latches and counts live in normal output cells."""

    kind: str
    previous_clk: bool = False
    previous_cu: bool = False
    previous_cd: bool = False

    def update(self, values: Mapping[str, Value]) -> dict[str, Value]:
        """Compute outputs from a snapshot of checked input/output values."""
        if self.kind in {"R_TRIG", "F_TRIG"}:
            clk = cast(bool, values["CLK"])
            q = (
                clk and not self.previous_clk
                if self.kind == "R_TRIG"
                else self.previous_clk and not clk
            )
            self.previous_clk = clk
            return {"Q": q}

        if self.kind == "SR":
            return {"Q1": (not values["RESET"] and values["Q1"]) or values["SET1"]}
        if self.kind == "RS":
            return {"Q1": not values["RESET1"] and (values["Q1"] or values["SET"])}

        if self.kind in {"CTU", "CTD", "CTUD"}:
            cu = cast(bool, values.get("CU", False))
            cd = cast(bool, values.get("CD", False))
            rising_cu = cu and not self.previous_cu
            rising_cd = cd and not self.previous_cd
            # Sample even when RESET or LOAD suppresses counting on this call.
            self.previous_cu, self.previous_cd = cu, cd
            cv, pv = cast(int, values["CV"]), cast(int, values["PV"])

            if self.kind == "CTU":
                if values["RESET"]:
                    cv = 0
                elif rising_cu:
                    cv = min(cv + 1, 65535)
                return {"Q": cv >= pv, "CV": cv}

            if self.kind == "CTD":
                if values["LOAD"]:
                    cv = pv
                elif rising_cd:
                    cv = max(cv - 1, 0)
                return {"Q": cv == 0, "CV": cv}

            if values["RESET"]:
                cv = 0
            elif values["LOAD"]:
                cv = pv
            elif rising_cu and not rising_cd:
                cv = min(cv + 1, 65535)
            elif rising_cd and not rising_cu:
                cv = max(cv - 1, 0)
            return {"QU": cv >= pv, "QD": cv == 0, "CV": cv}

        raise ValueError(f"Unknown standard block kind {self.kind}")
