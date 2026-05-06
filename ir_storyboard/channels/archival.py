"""Archival channel — books, long-form articles, SEC filings, historical research.

Useful for the professional layers (2, 4) and PEST history (8).
Cheap to populate once and update rarely.
"""
from __future__ import annotations

from typing import List

from .base import Channel
from ..models import CHANNEL_ARCHIVAL


class ArchivalChannel(Channel):
    code = CHANNEL_ARCHIVAL

    @property
    def primary_layer_ids(self) -> List[int]:
        return [2, 3, 4, 5, 6, 7, 8]
