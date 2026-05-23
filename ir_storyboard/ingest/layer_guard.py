"""LayerGuard: filter facts by channel × layer methodology constraints.

online_interview may only write to L1–L4 and L7.
L5, L6, L8 are blocked (client stories, product/business, PEST context
require archival or online_research, not a single interview).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .snippet_anchor import AnchoredFact


# Allowed subsection_ids for each channel
ALLOWED_LAYERS_BY_CHANNEL: dict[str, set[str]] = {
    "online_interview": {
        "1.1", "1.2", "1.3",
        "2.1", "2.2", "2.3",
        "3.1", "3.2", "3.3",
        "4.1", "4.2", "4.3",
        "7.1", "7.2", "7.3",
    },
    # online_research and archival are unrestricted here (pipeline handles separately)
}


@dataclass
class SkippedFact:
    fact: "AnchoredFact"
    reason: str
    override_allowed: bool = True


def guard_layers(
    facts: "list[AnchoredFact]",
    channel: str,
) -> "tuple[list[AnchoredFact], list[SkippedFact]]":
    """Split facts into (allowed, skipped) by channel's layer whitelist.

    Facts in skipped are NOT written to DB by default, but the caller
    may override individual facts (e.g. on the confirm screen).
    """
    allowed_sids = ALLOWED_LAYERS_BY_CHANNEL.get(channel)
    if allowed_sids is None:
        # Channel has no restrictions defined → pass all through
        return facts, []

    allowed: list[AnchoredFact] = []
    skipped: list[SkippedFact] = []

    for fact in facts:
        if fact.subsection_id in allowed_sids:
            allowed.append(fact)
        else:
            layer_id = fact.subsection_id.split(".")[0]
            reason = (
                f"L{layer_id} ({fact.subsection_id}) is not allowed for "
                f"{channel} — requires archival or online_research"
            )
            skipped.append(SkippedFact(fact=fact, reason=reason))

    return allowed, skipped
