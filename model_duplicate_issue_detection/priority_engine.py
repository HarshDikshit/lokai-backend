"""
ml/priority_engine.py
Multi-factor priority scoring for issue clusters.

Priority replaces raw complaint_count with a richer formula:

  priority = (
      w_sev  * severity_score           # how bad the issue is
    + w_urg  * urgency_score            # how time-sensitive
    + w_rep  * reporter_score           # unique reporters (log-scaled)
    + w_spk  * spike_score              # recent complaint spike
    + w_evi  * evidence_score           # images/audio attached
    + w_cat  * category_criticality     # inherent danger of category
  )

All component scores are in [0, 1].  Final priority is in [0, 1].
"""

from __future__ import annotations

import math
from typing import Optional


# ─── Category criticality weights ────────────────────────────────────────────
# Higher = more dangerous / urgent by nature.

CATEGORY_CRITICALITY: dict[str, float] = {
    "Public Safety":           1.00,
    "Healthcare":              0.95,
    "Water Supply":            0.85,
    "Electricity":             0.80,
    "Sanitation & Waste":      0.70,
    "Infrastructure & Roads":  0.65,
    "Transportation":          0.55,
    "Environment":             0.50,
    "Government Services":     0.40,
    "Education":               0.35,
    "General":                 0.30,
}

DEFAULT_CRITICALITY = 0.30


# ─── Priority formula weights ─────────────────────────────────────────────────

PRIORITY_WEIGHTS = {
    "severity":    0.25,
    "urgency":     0.20,
    "reporters":   0.20,
    "spike":       0.15,
    "evidence":    0.10,
    "criticality": 0.10,
}


# ─── Component scorers ─────────────────────────────────────────────────────────

def _reporter_score(unique_reporters: int, scale: int = 50) -> float:
    """
    Log-scaled unique reporter contribution.
    1 reporter  → ~0.0
    5 reporters → ~0.32
    20          → ~0.60
    50+         → ~1.0 (saturates)
    """
    if unique_reporters <= 0:
        return 0.0
    return min(math.log1p(unique_reporters) / math.log1p(scale), 1.0)


def _spike_score(spike_count: int, scale: int = 20) -> float:
    """
    Recent-spike contribution (complaints in last 24 h).
    0 → 0.0,  5 → 0.35,  20+ → 1.0
    """
    if spike_count <= 0:
        return 0.0
    return min(math.log1p(spike_count) / math.log1p(scale), 1.0)


def _evidence_score(evidence_count: int, scale: int = 10) -> float:
    """Each image/audio piece adds confidence. Saturates at `scale`."""
    return min(evidence_count / scale, 1.0)


# ─── Main entry ───────────────────────────────────────────────────────────────

def calculate_cluster_priority(
    severity_score:    float,
    urgency_score:     float,
    unique_reporters:  int,
    spike_count:       int,
    evidence_count:    int,
    category:          str,
) -> dict:
    """
    Compute priority_score for a cluster and return a full breakdown.

    Returns
    -------
    {
        "priority_score":  float,   # final [0, 1]
        "severity_score":  float,
        "urgency_score":   float,
        "reporter_score":  float,
        "spike_score":     float,
        "evidence_score":  float,
        "criticality":     float,
    }
    """
    criticality   = CATEGORY_CRITICALITY.get(category, DEFAULT_CRITICALITY)
    reporter_sc   = _reporter_score(unique_reporters)
    spike_sc      = _spike_score(spike_count)
    evidence_sc   = _evidence_score(evidence_count)

    w = PRIORITY_WEIGHTS
    priority = (
        w["severity"]    * severity_score  +
        w["urgency"]     * urgency_score   +
        w["reporters"]   * reporter_sc     +
        w["spike"]       * spike_sc        +
        w["evidence"]    * evidence_sc     +
        w["criticality"] * criticality
    )
    priority = min(max(priority, 0.0), 1.0)

    return {
        "priority_score":  round(priority,      4),
        "severity_score":  round(severity_score, 4),
        "urgency_score":   round(urgency_score,  4),
        "reporter_score":  round(reporter_sc,    4),
        "spike_score":     round(spike_sc,       4),
        "evidence_score":  round(evidence_sc,    4),
        "criticality":     round(criticality,    4),
    }


# ─── Severity / urgency from sentiment + ML ───────────────────────────────────

def derive_severity_from_ml(ml_urgency_score: float, sentiment_score: float) -> float:
    """
    Blend the ML urgency score (from your existing pipeline) with
    the sentiment polarity to derive a severity estimate.

    sentiment_score is in [-1, 1]:  -1 = very negative, +1 = positive
    """
    # Map sentiment to [0, 1] — more negative → more severe
    sentiment_severity = (1.0 - sentiment_score) / 2.0
    # Blend 70% ML urgency + 30% sentiment
    return round(0.70 * ml_urgency_score + 0.30 * sentiment_severity, 4)