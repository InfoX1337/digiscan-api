"""STUB – integrator (I1): SourceDoc -> DraftForm."""

from __future__ import annotations

from ..types.draft import DraftForm, DraftTab
from ..types.source import SourceDoc


def infer(doc: SourceDoc) -> DraftForm:
    title = doc.blocks[0].text if doc.blocks else doc.filename.rsplit(".", 1)[0]
    return DraftForm(title=title, title_confidence=0.3, tabs=[DraftTab(title="Dane", confidence=0.3)])
