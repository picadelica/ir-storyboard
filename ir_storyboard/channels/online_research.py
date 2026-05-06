"""Online research channel — web articles, news, sell-side notes, blog posts.

Best at filling layers 4-8 (community professional, clients, product,
social impact, PEST). Methodologically weak at layers 1-3.
"""
from __future__ import annotations

from typing import List

from .base import Channel
from ..models import CHANNEL_ONLINE_RESEARCH


class OnlineResearchChannel(Channel):
    code = CHANNEL_ONLINE_RESEARCH

    @property
    def primary_layer_ids(self) -> List[int]:
        return [4, 5, 6, 7, 8]
