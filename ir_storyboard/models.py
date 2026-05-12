"""Domain dataclasses + the canonical 8-layer schema."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

# ---------- canonical layers (concentric, intimacy 1=innermost ... 8=outermost) ----------

# Channel codes — keep in sync with schema.sql CHECK constraint
CHANNEL_ONLINE_RESEARCH = "online_research"
CHANNEL_ONLINE_INTERVIEW = "online_interview"
CHANNEL_ARCHIVAL = "archival"
CHANNEL_OFFLINE_INTERVIEW = "offline_interview"

ALL_CHANNELS = (
    CHANNEL_ONLINE_RESEARCH,
    CHANNEL_ONLINE_INTERVIEW,
    CHANNEL_ARCHIVAL,
    CHANNEL_OFFLINE_INTERVIEW,
)

FLAG_GREEN = "green"
FLAG_RED = "red"
FLAG_GREY = "grey"

CYCLE_WEEKLY = "weekly"
CYCLE_EVENT = "event"
CYCLE_QUARTERLY = "quarterly"


@dataclass
class LayerSpec:
    id: int
    code: str
    name: str
    intimacy: int                 # 1=innermost, 8=outermost
    primary_channels: List[str]   # which channels can feed this layer
    subsections: List["SubsectionSpec"] = field(default_factory=list)


@dataclass
class SubsectionSpec:
    id: str          # '1.1'
    code: str        # 'ORIGIN_CHILDHOOD'
    name: str        # 'Origin & Childhood'
    description: str = ""
    sort_order: int = 0


@dataclass
class Fact:
    id: Optional[int]
    cell_id: int
    text: str
    flag: str             # green / red / grey
    source_id: Optional[int]
    confidence: float = 1.0


@dataclass
class Source:
    id: Optional[int]
    channel: str
    title: str = ""
    url: str = ""
    notes: str = ""


@dataclass
class NarrativeTrack:
    id: Optional[int]
    plan_id: int
    name: str
    angle: str
    target_layer_ids: List[int]
    target_subsection_ids: List[str]
    priority: int = 1


# ---------- the canonical 8 layers (matches the framework PDF) ----------

LAYERS: List[LayerSpec] = [
    LayerSpec(
        id=1, code="FOUNDER_PERSONAL", name="Founder Personal Story",
        intimacy=1,
        # personal layer is built almost entirely from interviews
        primary_channels=[CHANNEL_OFFLINE_INTERVIEW, CHANNEL_ONLINE_INTERVIEW],
        subsections=[
            SubsectionSpec("1.1", "ORIGIN_CHILDHOOD", "Origin & Childhood", sort_order=1),
            SubsectionSpec("1.2", "VALUES_BELIEFS", "Values & Beliefs", sort_order=2),
            SubsectionSpec("1.3", "FEARS_DREAMS_IDENTITY", "Fears, Dreams & Identity",
                           description="Inner self: fears, vulnerabilities, dreams and identity of the founder",
                           sort_order=3),
        ],
    ),
    LayerSpec(
        id=2, code="FOUNDER_PROFESSIONAL", name="Founder Professional Story",
        intimacy=2,
        primary_channels=[CHANNEL_OFFLINE_INTERVIEW, CHANNEL_ONLINE_INTERVIEW, CHANNEL_ARCHIVAL],
        subsections=[
            SubsectionSpec("2.1", "PATH_TO_EXPERTISE", "Path to expertise", sort_order=1),
            SubsectionSpec("2.2", "FOUNDER_ROLE_MOTIVATION", "Founder role & motivation", sort_order=2),
            SubsectionSpec("2.3", "COFOUNDER_DYNAMICS", "Co-founder dynamics", sort_order=3),
        ],
    ),
    LayerSpec(
        id=3, code="COMMUNITY_CULTURE", name="Community Culture, Values & Stories",
        intimacy=3,
        primary_channels=[CHANNEL_OFFLINE_INTERVIEW, CHANNEL_ONLINE_INTERVIEW, CHANNEL_ARCHIVAL],
        subsections=[
            SubsectionSpec("3.1", "ATTRACTION_SELECTION", "Attraction & Selection", sort_order=1),
            SubsectionSpec("3.2", "SHARED_LIFE", "Shared life", sort_order=2),
            SubsectionSpec("3.3", "INVESTORS_PARTNERS", "Investors & Partners", sort_order=3),
        ],
    ),
    LayerSpec(
        id=4, code="COMMUNITY_PROFESSIONAL", name="Community Professional Experience",
        intimacy=4,
        primary_channels=[CHANNEL_ARCHIVAL, CHANNEL_ONLINE_RESEARCH, CHANNEL_ONLINE_INTERVIEW],
        subsections=[
            SubsectionSpec("4.1", "EXPERTISE_DIVERSITY", "Expertise & Diversity", sort_order=1),
            SubsectionSpec("4.2", "GROWTH_TRANSFORMATION", "Growth & Transformation", sort_order=2),
            SubsectionSpec("4.3", "COLLECTIVE_FAILURE_MEMORY", "Collective Failure Memory", sort_order=3),
        ],
    ),
    LayerSpec(
        id=5, code="CLIENTS_STORIES", name="Clients - Stories",
        intimacy=5,
        primary_channels=[CHANNEL_ONLINE_RESEARCH, CHANNEL_OFFLINE_INTERVIEW, CHANNEL_ARCHIVAL],
        subsections=[
            SubsectionSpec("5.1", "CLIENT_CHALLENGE_CONTEXT", "Client's challenge & context", sort_order=1),
            SubsectionSpec("5.2", "MOMENT_OF_CHOICE_TRUST", "Moment of choice & trust", sort_order=2),
            SubsectionSpec("5.3", "CONFLICT_HONESTY", "Conflict & Honesty", sort_order=3),
        ],
    ),
    LayerSpec(
        id=6, code="PRODUCT_BUSINESS", name="Product & Business",
        intimacy=6,
        primary_channels=[CHANNEL_ONLINE_RESEARCH, CHANNEL_ARCHIVAL],
        subsections=[
            SubsectionSpec("6.1", "ARCHITECTURE_OF_SOLUTION", "Architecture of the solution", sort_order=1),
            SubsectionSpec("6.2", "PHILOSOPHY_PRODUCT_DECISIONS", "Philosophy of product decisions", sort_order=2),
            SubsectionSpec("6.3", "EVOLUTION_OF_PRODUCT", "Evolution of the product", sort_order=3),
        ],
    ),
    LayerSpec(
        id=7, code="SOCIAL_IMPACT", name="Social Impact Vision",
        intimacy=7,
        primary_channels=[CHANNEL_ONLINE_RESEARCH, CHANNEL_ONLINE_INTERVIEW, CHANNEL_ARCHIVAL],
        subsections=[
            SubsectionSpec("7.1", "VISION_OF_CHANGE", "Vision of change", sort_order=1),
            SubsectionSpec("7.2", "CONTRADICTIONS_COST", "Contradictions & Cost", sort_order=2),
            SubsectionSpec("7.3", "LEGACY", "Legacy", sort_order=3),
        ],
    ),
    LayerSpec(
        id=8, code="PEST_CONTEXT", name="Political, Economical, Social & Technological Context",
        intimacy=8,
        # outermost layer is best fed by online research
        primary_channels=[CHANNEL_ONLINE_RESEARCH, CHANNEL_ARCHIVAL],
        subsections=[
            SubsectionSpec("8.1", "HISTORICAL_MOMENT", "The historical moment", sort_order=1),
            SubsectionSpec("8.2", "MARKET_TECHNOLOGY", "Market & technology", sort_order=2),
            SubsectionSpec("8.3", "POLICY_REGULATION", "Policy & regulation", sort_order=3),
        ],
    ),
]


def layer_by_id(lid: int) -> LayerSpec:
    for L in LAYERS:
        if L.id == lid:
            return L
    raise KeyError(f"layer {lid} not found")


def subsection_by_id(sid: str) -> SubsectionSpec:
    for L in LAYERS:
        for s in L.subsections:
            if s.id == sid:
                return s
    raise KeyError(f"subsection {sid} not found")


def channel_can_fill(channel: str, layer_id: int) -> bool:
    """Methodological constraint: which channels can feed which layers."""
    return channel in layer_by_id(layer_id).primary_channels
