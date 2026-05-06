"""Four ingestion channels, one per source type.

Each channel knows which layers it can primarily fill and how to convert
its input payload into Facts written to the matrix.
"""
from .base import Channel, IngestPayload, IngestResult
from .online_research import OnlineResearchChannel
from .online_interview import OnlineInterviewChannel
from .archival import ArchivalChannel
from .offline_interview import OfflineInterviewChannel

__all__ = [
    "Channel",
    "IngestPayload",
    "IngestResult",
    "OnlineResearchChannel",
    "OnlineInterviewChannel",
    "ArchivalChannel",
    "OfflineInterviewChannel",
]
