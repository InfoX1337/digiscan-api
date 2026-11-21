"""Walidator reguł COI + auto-naprawa (kontrakt: types/stages.py ValidateFn).

`validate(form, repair=True)` nie mutuje wejścia: pracuje na głębokiej kopii, naprawia, po czym przelicza
wszystkie reguły, aby wynik pokazywał stan końcowy (`RuleResult.repaired` = reguła miała naprawy).
"""

from __future__ import annotations

from ..types.form import FormDefinition
from ..types.stages import ValidateResult
from .repair import repair_all
from .rules import RULES, check_all

MAX_PASSES = 3


def validate(form: FormDefinition, repair: bool = True) -> ValidateResult:
    work = form.model_copy(deep=True)
    repairs = []
    if repair:
        for _ in range(MAX_PASSES):
            done = repair_all(work)
            repairs += done
            if not done:
                break
    rules = check_all(work, {r.rule_id for r in repairs})
    return ValidateResult(form=work, rules=rules, repairs=repairs)


__all__ = ["RULES", "validate"]
