"""STUB – integrator (I2): DraftForm -> FormDefinition."""

from __future__ import annotations

import uuid

from ..types.draft import DraftForm
from ..types.form import FormDefinition, Tab
from ..types.stages import BuildResult


def build(draft: DraftForm) -> BuildResult:
    tabs = [Tab(id=str(uuid.uuid4()), title=t.title, type=t.type) for t in draft.tabs]
    return BuildResult(form=FormDefinition(title=draft.title, tabs=tabs), key_to_id={})
