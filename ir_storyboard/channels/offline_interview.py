"""Offline interview channel — analyst's own interview with the client/founder.

The only channel that can reliably fill the inner layers (1-3): personal
fears, values, co-founder dynamics, community culture stories. Without it
the matrix will permanently show grey on the most important narrative cells.
"""
from __future__ import annotations

from typing import List

from .base import Channel
from ..models import CHANNEL_OFFLINE_INTERVIEW


class OfflineInterviewChannel(Channel):
    code = CHANNEL_OFFLINE_INTERVIEW

    @property
    def primary_layer_ids(self) -> List[int]:
        return [1, 2, 3, 5]
