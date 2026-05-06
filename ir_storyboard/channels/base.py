"""Channel base class + payload contracts."""
from __future__ import annotations

import sqlite3
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import List, Optional

from .. import matrix
from ..llm import classify_fact, FactCandidate
from ..models import LAYERS, channel_can_fill


@dataclass
class IngestPayload:
    """Generic input to a channel."""
    client_id: str
    raw_text: str                          # full text of the source (transcript / article / chapter)
    source_title: str = ""
    source_url: str = ""
    notes: str = ""
    # Optional pre-segmented facts (analyst hand-curated). If provided,
    # we skip the auto-classifier and trust these.
    pre_facts: List["PreFact"] = field(default_factory=list)


@dataclass
class PreFact:
    text: str
    subsection_id: str
    flag: str               # green / red / grey
    confidence: float = 1.0


@dataclass
class IngestResult:
    source_id: int
    written_fact_ids: List[int]
    skipped_facts: List[str]               # facts the channel methodologically should not own
    warnings: List[str]


class Channel(ABC):
    """A source channel — knows which layers it can primarily fill."""
    code: str = ""

    @property
    @abstractmethod
    def primary_layer_ids(self) -> List[int]:
        ...

    def can_fill(self, layer_id: int) -> bool:
        return channel_can_fill(self.code, layer_id)

    def ingest(self, conn: sqlite3.Connection, payload: IngestPayload) -> IngestResult:
        """Write a source row + classified facts into the matrix."""
        source_id = matrix.add_source(
            conn, channel=self.code,
            title=payload.source_title, url=payload.source_url, notes=payload.notes,
        )

        written: List[int] = []
        skipped: List[str] = []
        warnings: List[str] = []

        # 1) Hand-curated facts win
        if payload.pre_facts:
            for pf in payload.pre_facts:
                layer_id = int(pf.subsection_id.split(".")[0])
                if not self.can_fill(layer_id):
                    warnings.append(
                        f"channel {self.code} not primary for layer {layer_id} "
                        f"(subsection {pf.subsection_id}); ingested anyway with warning"
                    )
                fid = matrix.add_fact(
                    conn, client_id=payload.client_id,
                    subsection_id=pf.subsection_id,
                    text=pf.text, flag=pf.flag,
                    source_id=source_id, confidence=pf.confidence,
                )
                written.append(fid)
            return IngestResult(source_id, written, skipped, warnings)

        # 2) Otherwise auto-classify by paragraphs
        for para in self._split_paragraphs(payload.raw_text):
            cand: FactCandidate = classify_fact(para)
            if cand.suggested_subsection_id is None:
                skipped.append(para[:120])
                continue
            layer_id = int(cand.suggested_subsection_id.split(".")[0])
            if not self.can_fill(layer_id):
                # methodologically wrong channel — skip rather than pollute the matrix
                skipped.append(para[:120])
                warnings.append(
                    f"skipped: channel {self.code} cannot fill layer {layer_id}"
                )
                continue
            fid = matrix.add_fact(
                conn, client_id=payload.client_id,
                subsection_id=cand.suggested_subsection_id,
                text=para, flag=cand.suggested_flag,
                source_id=source_id, confidence=cand.confidence,
            )
            written.append(fid)

        return IngestResult(source_id, written, skipped, warnings)

    @staticmethod
    def _split_paragraphs(text: str) -> List[str]:
        return [p.strip() for p in text.split("\n\n") if p.strip()]
