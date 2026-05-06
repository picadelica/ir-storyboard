"""Online interview channel — podcast / YouTube / conference talk transcripts.

Reaches layers 1-4 (founder personal/professional, community) much better
than online research, because the speaker reveals beliefs, fears, stories.
"""
from __future__ import annotations

from typing import List

from .base import Channel
from ..models import CHANNEL_ONLINE_INTERVIEW


class OnlineInterviewChannel(Channel):
    code = CHANNEL_ONLINE_INTERVIEW

    @property
    def primary_layer_ids(self) -> List[int]:
        return [1, 2, 3, 4, 7]
