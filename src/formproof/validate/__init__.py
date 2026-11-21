"""STUB – strumień VALIDATE zastępuje implementacją (kontrakt: types/stages.py ValidateFn)."""

from __future__ import annotations

from ..types.form import FormDefinition
from ..types.stages import ValidateResult


def validate(form: FormDefinition, repair: bool = True) -> ValidateResult:
    return ValidateResult(form=form.model_copy(deep=True), rules=[], repairs=[])
