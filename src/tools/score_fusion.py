"""
Rank-based multi-channel score fusion for GraphSearchTool (Retrieval Score Redesign R1).

Each retrieval channel (product title embeddings, attribute embeddings, review embeddings)
yields one list in which every product appears once, scored by its best match in that
channel (MaxP). The lists are ranked with competition ranking and fused with Reciprocal
Rank Fusion (Cormack et al., 2009) by default, or with a convex combination of min-max
normalised similarities for ablation (Bruch, Gai & Ingber, 2023).

The module is pure Python and performs no I/O, so the fusion logic is testable without Neo4j.
See production_artifacts/Technical_Specification.md (R1) and Vision decision 2026-10-17-013.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Sequence, Tuple

logger = logging.getLogger(__name__)

CHANNELS: Tuple[str, ...] = ("product", "attribute", "review")
DEFAULT_ARM = "rrf3"
FUSION_ARM_ENV = "RETRIEVAL_FUSION_ARM"
LEGACY_SOFT_BONUS_UNIT = 0.2


@dataclass(frozen=True)
class ChannelHit:
    """One product's best match inside one channel."""
    asin: str
    similarity: float
    reason: str


@dataclass(frozen=True)
class ChannelEvidence:
    """Rank and similarity of a fused candidate in one channel."""
    rank: int
    similarity: float
    reason: str


@dataclass(frozen=True)
class FusedCandidate:
    """A product after cross-channel fusion."""
    asin: str
    score: float
    channels: Dict[str, ChannelEvidence]


@dataclass(frozen=True)
class FusionConfig:
    """Fusion method, enabled channels and their parameters."""
    name: str = DEFAULT_ARM
    method: str = "rrf"
    channels: Tuple[str, ...] = CHANNELS
    weights: Dict[str, float] = field(default_factory=lambda: {c: 1.0 for c in CHANNELS})
    rrf_k: int = 60
    channel_depth: int = 100
    ann_k_per_limit: int = 30
    soft_bonus_beta: float = 0.25

    def channel_weight(self, channel: str) -> float:
        """Weight of one channel; channels without an explicit weight count 1.0."""
        return float(self.weights.get(channel, 1.0))

    def max_fused_score(self) -> float:
        """Highest fused score attainable: rank 1 in every enabled channel (NaN for the unbounded sum)."""
        if self.method == "rrf":
            return sum(self.channel_weight(c) for c in self.channels) / (self.rrf_k + 1)
        if self.method == "cc":
            return 1.0
        return float("nan")

    def soft_bonus_unit(self) -> float:
        """Bonus added per matched soft preference at polarity 1.0."""
        if self.method == "sum":
            return LEGACY_SOFT_BONUS_UNIT
        return self.soft_bonus_beta * self.max_fused_score()

    def to_dict(self) -> Dict[str, Any]:
        """Serialisable form for search metadata and evaluation manifests."""
        return {
            "name": self.name,
            "method": self.method,
            "channels": list(self.channels),
            "weights": {c: self.channel_weight(c) for c in self.channels},
            "rrf_k": self.rrf_k,
            "channel_depth": self.channel_depth,
            "ann_k_per_limit": self.ann_k_per_limit,
            "soft_bonus_beta": self.soft_bonus_beta,
            "soft_bonus_unit": self.soft_bonus_unit(),
        }

    @classmethod
    def from_env(cls) -> "FusionConfig":
        """Preset named by RETRIEVAL_FUSION_ARM; unknown names log a warning and fall back to rrf3."""
        name = (os.getenv(FUSION_ARM_ENV) or DEFAULT_ARM).strip().lower()
        if name in FUSION_ARMS:
            return FUSION_ARMS[name]
        logger.warning(
            f"[Fusion] Unknown {FUSION_ARM_ENV}='{name}'. Valid arms: {sorted(FUSION_ARMS)}. Falling back to '{DEFAULT_ARM}'."
        )
        return FUSION_ARMS[DEFAULT_ARM]


FUSION_ARMS: Dict[str, FusionConfig] = {
    "rrf3": FusionConfig(),
    "rrf2": FusionConfig(name="rrf2", channels=("product", "attribute")),
    "wrrf3": FusionConfig(name="wrrf3", weights={"product": 0.60, "attribute": 0.25, "review": 0.15}),
    "cc3": FusionConfig(name="cc3", method="cc"),
    "sum_legacy": FusionConfig(name="sum_legacy", method="sum"),
}


def competition_ranks(hits: Sequence[ChannelHit]) -> Dict[str, ChannelEvidence]:
    """
    Ranks one channel's hits with competition ranking (1, 2, 2, 4).

    Duplicated ASINs keep their highest similarity. Hits are ordered by
    (similarity DESC, asin ASC), so the result does not depend on input order.
    """
    best: Dict[str, ChannelHit] = {}
    for hit in hits:
        current = best.get(hit.asin)
        if (
            current is None
            or hit.similarity > current.similarity
            or (hit.similarity == current.similarity and hit.reason < current.reason)
        ):
            best[hit.asin] = hit

    ordered = sorted(best.values(), key=lambda h: (-h.similarity, h.asin))
    ranks: Dict[str, ChannelEvidence] = {}
    rank = 0
    previous_similarity = None
    for position, hit in enumerate(ordered, start=1):
        if previous_similarity is None or hit.similarity != previous_similarity:
            rank = position
            previous_similarity = hit.similarity
        ranks[hit.asin] = ChannelEvidence(rank=rank, similarity=hit.similarity, reason=hit.reason)
    return ranks


def fuse(channel_hits: Mapping[str, Sequence[ChannelHit]], config: FusionConfig) -> List[FusedCandidate]:
    """
    Fuses per-channel hit lists into one ranked candidate list.

    RRF: score = sum_c w_c / (rrf_k + rank_c). CC: score = sum_c alpha_c * minmax_c(similarity),
    alpha = weights renormalised over enabled channels. Channels outside config.channels are
    ignored; a product absent from a channel gets nothing from it. Output is sorted by
    score DESC, channels matched DESC, best similarity DESC, asin ASC.

    Raises:
        ValueError: if config.method is not "rrf" or "cc".
    """
    if config.method not in ("rrf", "cc"):
        raise ValueError(f"fuse() supports 'rrf' and 'cc', got '{config.method}' (arm '{config.name}')")

    total_weight = sum(config.channel_weight(c) for c in config.channels)
    scores: Dict[str, float] = {}
    evidence: Dict[str, Dict[str, ChannelEvidence]] = {}

    for channel in config.channels:
        ranked = competition_ranks(channel_hits.get(channel, []))
        if not ranked:
            continue
        weight = config.channel_weight(channel)
        if config.method == "cc":
            sims = [ev.similarity for ev in ranked.values()]
            low, high = min(sims), max(sims)
            alpha = weight / total_weight if total_weight > 0 else 0.0
        for asin, ev in ranked.items():
            if config.method == "rrf":
                contribution = weight / (config.rrf_k + ev.rank)
            else:
                normalised = (ev.similarity - low) / (high - low) if high > low else 1.0
                contribution = alpha * normalised
            scores[asin] = scores.get(asin, 0.0) + contribution
            evidence.setdefault(asin, {})[channel] = ev

    fused = [FusedCandidate(asin=asin, score=score, channels=evidence[asin]) for asin, score in scores.items()]
    fused.sort(key=lambda fc: (
        -fc.score,
        -len(fc.channels),
        -max(ev.similarity for ev in fc.channels.values()),
        fc.asin,
    ))
    return fused
