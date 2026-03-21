"""
ml/duplicate_scorer.py
Weighted hybrid duplicate-score computation.

Score = w_text  * text_sim
      + w_geo   * geo_sim
      + w_time  * time_sim
      + w_img   * img_sim   (only when both complaints have images)
      + w_cat   * cat_sim

All component scores are in [0, 1].
Final score is also normalised to [0, 1].

Thresholds (configurable via env / settings):
  AUTO_MERGE_THRESHOLD    = 0.72   → attach to cluster automatically
  REVIEW_THRESHOLD        = 0.50   → send to human review queue
  below review threshold           → create new cluster
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, List
from datetime import datetime

from model_duplicate_issue_detection.embeddings import (
    cosine_similarity,
    geo_similarity,
    time_similarity,
    image_similarity,
)

# ─── Weights ──────────────────────────────────────────────────────────────────
# Must sum to 1.0 when image IS available; text+geo+time+cat sum to 1.0 otherwise.

WEIGHTS_WITH_IMAGE = {
    "text": 0.35,
    "geo":  0.25,
    "time": 0.15,
    "img":  0.15,
    "cat":  0.10,
}

WEIGHTS_NO_IMAGE = {
    "text": 0.45,
    "geo":  0.28,
    "time": 0.17,
    "cat":  0.10,
}

# ─── Category compatibility matrix ────────────────────────────────────────────
# 1.0 = same, 0.6 = related, 0.0 = unrelated
# Used when category labels differ but the underlying issue could be the same.

CATEGORY_COMPAT = {
    ("Infrastructure & Roads", "Transportation"):       0.6,
    ("Sanitation & Waste",     "Environment"):          0.6,
    ("Water Supply",           "Infrastructure & Roads"):0.4,
    ("Electricity",            "Infrastructure & Roads"):0.4,
    ("Public Safety",          "Healthcare"):           0.3,
}

def category_similarity(cat_a: str, cat_b: str) -> float:
    if cat_a == cat_b:
        return 1.0
    key1 = (cat_a, cat_b)
    key2 = (cat_b, cat_a)
    return CATEGORY_COMPAT.get(key1, CATEGORY_COMPAT.get(key2, 0.0))


# ─── Score dataclass ──────────────────────────────────────────────────────────

@dataclass
class DuplicateScore:
    total:    float
    text_sim: float
    geo_sim:  float
    time_sim: float
    img_sim:  Optional[float]
    cat_sim:  float

    def to_dict(self) -> dict:
        return {
            "total":    round(self.total,    4),
            "text_sim": round(self.text_sim, 4),
            "geo_sim":  round(self.geo_sim,  4),
            "time_sim": round(self.time_sim, 4),
            "img_sim":  round(self.img_sim, 4) if self.img_sim is not None else None,
            "cat_sim":  round(self.cat_sim,  4),
        }


# ─── Main scorer ──────────────────────────────────────────────────────────────

def compute_duplicate_score(
    # New complaint fields
    new_text_emb:   List[float],
    new_lon:        float,
    new_lat:        float,
    new_time:       datetime,
    new_category:   str,
    new_img_emb:    Optional[List[float]],

    # Cluster centroid fields
    cluster_text_emb: List[float],
    cluster_lon:      float,
    cluster_lat:      float,
    cluster_time:     datetime,       # last_reported_at
    cluster_category: str,
    cluster_img_emb:  Optional[List[float]] = None,

    # Tuning knobs
    geo_radius_km:  float = 2.0,
    time_decay_h:   float = 72.0,
) -> DuplicateScore:
    """
    Compute a weighted hybrid duplicate score between a new complaint
    and an existing cluster's representative profile.
    """

    text_sim = cosine_similarity(new_text_emb, cluster_text_emb)
    geo_sim  = geo_similarity(new_lon, new_lat, cluster_lon, cluster_lat, geo_radius_km)
    time_sim = time_similarity(new_time, cluster_time, time_decay_h)
    cat_sim  = category_similarity(new_category, cluster_category)
    img_sim  = image_similarity(new_img_emb, cluster_img_emb)

    if img_sim is not None:
        w = WEIGHTS_WITH_IMAGE
        total = (
            w["text"] * text_sim +
            w["geo"]  * geo_sim  +
            w["time"] * time_sim +
            w["img"]  * img_sim  +
            w["cat"]  * cat_sim
        )
    else:
        w = WEIGHTS_NO_IMAGE
        total = (
            w["text"] * text_sim +
            w["geo"]  * geo_sim  +
            w["time"] * time_sim +
            w["cat"]  * cat_sim
        )

    return DuplicateScore(
        total=min(max(total, 0.0), 1.0),
        text_sim=text_sim,
        geo_sim=geo_sim,
        time_sim=time_sim,
        img_sim=img_sim,
        cat_sim=cat_sim,
    )


# ─── Decision logic ───────────────────────────────────────────────────────────

AUTO_MERGE_THRESHOLD = 0.72
REVIEW_THRESHOLD     = 0.50


def classify_match(score: float) -> str:
    """
    Returns one of:
        "auto_merged"     – attach to existing cluster
        "pending_review"  – send to human review queue
        "new_cluster"     – create a new cluster
    """
    if score >= AUTO_MERGE_THRESHOLD:
        return "auto_merged"
    if score >= REVIEW_THRESHOLD:
        return "pending_review"
    return "new_cluster"