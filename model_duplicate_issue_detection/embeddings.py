"""
ml/embeddings.py
Multilingual semantic embedding + similarity utilities.

Model: sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2
  – 384-dimensional vectors
  – Supports English, Hindi, Hinglish out of the box
  – ~120 MB, CPU-friendly
"""

from __future__ import annotations

import re
import unicodedata
from functools import lru_cache
from typing import List, Optional

import numpy as np

# ── Lazy-load the heavy model once ────────────────────────────────────────────
_model = None

def get_model():
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer
        _model = SentenceTransformer(
            "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
        )
        print("[ML] Multilingual embedding model loaded.")
    return _model


# ─── Text normalisation ───────────────────────────────────────────────────────

# Common Hinglish / SMS abbreviations → expanded form
_HINGLISH_MAP = {
    r"\bkaam\b": "work",
    r"\bsadak\b": "road",
    r"\bnaali\b": "drain",
    r"\bpaani\b": "water",
    r"\bbijli\b": "electricity",
    r"\bkachra\b": "garbage",
    r"\bsafai\b": "cleaning",
    r"\bnahi\b": "not",
    r"\bhai\b": "is",
    r"\bho\b": "is",
    r"\bkaro\b": "do",
    r"\bkab\b": "when",
    r"\byahan\b": "here",
    r"\bwahan\b": "there",
    r"\bbahut\b": "very",
    r"\bpura\b": "entire",
    r"\bpuri\b": "entire",
    r"\bganda\b": "dirty",
    r"\btoot\b": "broken",
    r"\btoota\b": "broken",
    r"\bkhula\b": "open",
    r"\bjam\b": "blocked",
    r"\bjaam\b": "blocked",
}


def normalize_text(text: str) -> str:
    """
    Lowercase, strip accents, expand common Hinglish words, collapse whitespace.
    Keeps Unicode so Devanagari script is preserved for the multilingual model.
    """
    if not text:
        return ""

    # Lowercase
    text = text.lower().strip()

    # Expand Hinglish abbreviations (romanised Hindi)
    for pattern, replacement in _HINGLISH_MAP.items():
        text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)

    # Collapse multiple spaces / newlines
    text = re.sub(r"\s+", " ", text)

    return text


# ─── Embedding generation ──────────────────────────────────────────────────────

def get_text_embedding(text: str) -> List[float]:
    """Return a 384-d unit-normalised embedding for a single text string."""
    model = get_model()
    norm  = normalize_text(text)
    vec   = model.encode(norm, normalize_embeddings=True)
    return vec.tolist()


def get_batch_embeddings(texts: List[str]) -> List[List[float]]:
    """Batch encode for efficiency."""
    model = get_model()
    norms = [normalize_text(t) for t in texts]
    vecs  = model.encode(norms, normalize_embeddings=True, batch_size=32)
    return vecs.tolist()


# ─── Similarity helpers ────────────────────────────────────────────────────────

def cosine_similarity(a: List[float], b: List[float]) -> float:
    """
    Cosine similarity between two pre-normalised vectors.
    Since embeddings are unit-norm, dot product == cosine similarity.
    """
    va = np.array(a, dtype=np.float32)
    vb = np.array(b, dtype=np.float32)
    return float(np.dot(va, vb))


def geo_similarity(
    lon1: float, lat1: float,
    lon2: float, lat2: float,
    radius_km: float = 2.0,
) -> float:
    """
    Returns 1.0 when the two points are at the same location,
    decaying to 0.0 at `radius_km` distance using a Gaussian kernel.

    Uses the Haversine formula for accurate short-distance computation.
    """
    import math

    R = 6371.0  # Earth radius in km
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(math.radians(lat1))
        * math.cos(math.radians(lat2))
        * math.sin(dlon / 2) ** 2
    )
    dist_km = 2 * R * math.asin(math.sqrt(a))

    # Gaussian decay: sim = exp(-(d/r)^2)
    return float(np.exp(-((dist_km / radius_km) ** 2)))


def time_similarity(dt1, dt2, decay_hours: float = 72.0) -> float:
    """
    Returns 1.0 for same timestamp, decaying to ~0.05 after `decay_hours`.
    Uses exponential decay: sim = exp(-|Δt| / decay_hours).
    """
    delta_hours = abs((dt2 - dt1).total_seconds()) / 3600.0
    return float(np.exp(-delta_hours / decay_hours))


def image_similarity(emb1: Optional[List[float]], emb2: Optional[List[float]]) -> Optional[float]:
    """Cosine similarity between two CLIP image embeddings (512-d). Returns None if either missing."""
    if emb1 is None or emb2 is None:
        return None
    return cosine_similarity(emb1, emb2)


def update_centroid(
    old_centroid: List[float],
    new_embedding: List[float],
    old_count: int,
) -> List[float]:
    """
    Incremental mean update:
        new_mean = (old_mean * n + new_vec) / (n + 1)
    Re-normalises to unit length afterwards.
    """
    oc = np.array(old_centroid, dtype=np.float32)
    nv = np.array(new_embedding, dtype=np.float32)
    updated = (oc * old_count + nv) / (old_count + 1)
    norm = np.linalg.norm(updated)
    if norm > 0:
        updated /= norm
    return updated.tolist()