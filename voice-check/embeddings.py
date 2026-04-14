#!/usr/bin/env python3
"""
embeddings.py — Semantic embedding similarity for voice-check.

Measures semantic drift: when an agent writes about the same topic but in a
different conceptual register than the writer would. Stylometry measures *how*
you write; embeddings measure *what semantic space* you write in. The writer's
calibrated samples define a semantic centroid. Drafts that drift far from that
centroid are writing in the wrong conceptual register, even if stylometry is close.

Two operating modes:
  calibrate_embeddings(sample_paths) → dict   — build centroid from writing samples
  compare_embeddings(first, final, baseline) → dict — measure semantic drift, report shifts

Called by writing_check.py in two workflows:
  --calibrate: extends the profile with an "embeddings" section
  --learn first.md final.md --profile p.json: update profile from revision pair

Does NOT use the apply_profile() globals-mutation pattern.
All functions take the profile's embeddings section as an argument and return results.

Dependencies: fastembed (required for embedding); numpy (required).
"""

import re
import sys
import copy

try:
    import numpy as np
    NUMPY_AVAILABLE = True
except ImportError:
    NUMPY_AVAILABLE = False
    print("WARNING: numpy not installed. Embeddings module requires numpy.", file=sys.stderr)

try:
    from fastembed import TextEmbedding
    FASTEMBED_AVAILABLE = True
except ImportError:
    FASTEMBED_AVAILABLE = False

try:
    import nltk
    from nltk.tokenize import sent_tokenize
    _NLTK_AVAILABLE = True
    for _corpus in ("punkt_tab",):
        try:
            nltk.data.find(f"tokenizers/{_corpus}")
        except LookupError:
            nltk.download(_corpus, quiet=True)
except ImportError:
    _NLTK_AVAILABLE = False
    sent_tokenize = None


# Default embedding model: 384-dim, fast, well-validated.
DEFAULT_MODEL = "BAAI/bge-small-en-v1.5"

# Minimum sentences for a reliable semantic centroid.
MIN_SENTENCES_RELIABLE = 20

# Model cache: avoid reloading within a session.
_MODEL_CACHE = {}


# ---------------------------------------------------------------------------
# Model loading
# ---------------------------------------------------------------------------

def _get_model(model_name: str = None):
    """Load embedding model, cache for reuse within session."""
    name = model_name or DEFAULT_MODEL
    if name not in _MODEL_CACHE:
        _MODEL_CACHE[name] = TextEmbedding(name)
    return _MODEL_CACHE[name]


# ---------------------------------------------------------------------------
# Text preparation (standalone — do NOT import from stylometry.py)
# ---------------------------------------------------------------------------

def _strip_markdown(text: str) -> str:
    """Remove markdown formatting, preserve prose content."""
    # Fenced code blocks
    text = re.sub(r"```[\s\S]*?```", " ", text)
    # Headers
    text = re.sub(r"^#{1,6}\s+", "", text, flags=re.MULTILINE)
    # Bold / italic
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
    text = re.sub(r"\*(.+?)\*", r"\1", text)
    text = re.sub(r"__(.+?)__", r"\1", text)
    text = re.sub(r"_(.+?)_", r"\1", text)
    # Inline code
    text = re.sub(r"`[^`]+`", " ", text)
    # Links
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"!\[[^\]]*\]\([^)]+\)", " ", text)
    # Bare URLs
    text = re.sub(r"https?://\S+", " ", text)
    return text


def _get_sentences(text: str) -> list:
    """Split text into sentences. Uses NLTK if available, regex fallback otherwise."""
    if _NLTK_AVAILABLE and sent_tokenize is not None:
        return [s for s in sent_tokenize(text) if s.strip()]
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()]


# ---------------------------------------------------------------------------
# Math helpers
# ---------------------------------------------------------------------------

def _cosine_similarity(a, b) -> float:
    """Cosine similarity between two numpy vectors. Returns 0.0 for zero-norm input."""
    norm_a = np.linalg.norm(a)
    norm_b = np.linalg.norm(b)
    if norm_a < 1e-10 or norm_b < 1e-10:
        return 0.0
    return float(np.dot(a, b) / (norm_a * norm_b))


# ---------------------------------------------------------------------------
# Core single-text computation
# ---------------------------------------------------------------------------

def compute_embeddings(text: str, model_name: str = None) -> dict:
    """
    Compute sentence embeddings for a single text.

    Strips markdown, splits into sentences, embeds each sentence, and returns
    per-sentence embeddings plus the centroid and distance distribution.

    Returns:
        sentence_embeddings: list of numpy arrays (one per sentence)
        centroid: numpy array (mean of sentence embeddings)
        distances_from_centroid: list of floats (cosine distance per sentence)
        mean_distance: float
        stdev_distance: float
        sentence_count: int
        model: str (model name used)

    Returns empty dict with warning if fastembed is not available.
    Handles edge cases: empty text, single sentence.
    """
    if not FASTEMBED_AVAILABLE:
        print(
            "WARNING: fastembed not installed. "
            "Install with: pip install fastembed",
            file=sys.stderr,
        )
        return {}
    if not NUMPY_AVAILABLE:
        print("WARNING: numpy not installed. Embeddings require numpy.", file=sys.stderr)
        return {}

    clean = _strip_markdown(text)
    sentences = _get_sentences(clean)

    if not sentences:
        return {
            "sentence_embeddings": [],
            "centroid": np.zeros(384),
            "distances_from_centroid": [],
            "mean_distance": 0.0,
            "stdev_distance": 0.0,
            "sentence_count": 0,
            "model": model_name or DEFAULT_MODEL,
        }

    model = _get_model(model_name)
    embeddings = list(model.embed(sentences))  # list of numpy arrays

    if len(embeddings) == 1:
        centroid = embeddings[0].copy()
        distances = [0.0]
    else:
        centroid = np.mean(np.stack(embeddings), axis=0)
        distances = [
            float(1.0 - _cosine_similarity(emb, centroid))
            for emb in embeddings
        ]

    mean_dist = float(np.mean(distances))
    stdev_dist = float(np.std(distances)) if len(distances) > 1 else 0.0

    return {
        "sentence_embeddings": embeddings,
        "centroid": centroid,
        "distances_from_centroid": distances,
        "mean_distance": round(mean_dist, 6),
        "stdev_distance": round(stdev_dist, 6),
        "sentence_count": len(sentences),
        "model": model_name or DEFAULT_MODEL,
    }


# ---------------------------------------------------------------------------
# Calibration: build semantic centroid from writing samples
# ---------------------------------------------------------------------------

def calibrate_embeddings(
    sample_paths: list,
    model_name: str = None,
    verbose: bool = True,
) -> dict:
    """
    Build a semantic centroid from a list of writing sample file paths.

    Embeds all sentences from all samples, computes a single centroid across
    the full corpus, and characterises the distance distribution. Sets a
    distance threshold at mean + 1.5 * stdev — sentences beyond this in a
    draft are semantically drifting from the writer's register.

    Small corpus handling: if fewer than 20 sentences total, warns and
    loosens the threshold by 1.5x to avoid false positives.

    Returns the dict for profile["embeddings"]. Empty dict on failure.
    """
    if not FASTEMBED_AVAILABLE:
        print(
            "WARNING: fastembed not installed. "
            "Install with: pip install fastembed",
            file=sys.stderr,
        )
        return {}
    if not NUMPY_AVAILABLE:
        print("ERROR: numpy required for embedding calibration.", file=sys.stderr)
        return {}

    if not sample_paths:
        print("ERROR: No sample paths provided for embedding calibration.", file=sys.stderr)
        return {}

    # Read samples
    texts = []
    total_words = 0
    for path in sample_paths:
        try:
            with open(path, "r", encoding="utf-8") as f:
                raw = f.read()
            texts.append(raw)
            total_words += len(re.findall(r"\b[a-zA-Z]+\b", raw))
        except OSError as e:
            print(f"WARNING: Could not read {path}: {e}", file=sys.stderr)

    if not texts:
        print("ERROR: No readable samples for embedding calibration.", file=sys.stderr)
        return {}

    # Collect all sentences from all samples
    all_sentences = []
    for text in texts:
        clean = _strip_markdown(text)
        sentences = _get_sentences(clean)
        all_sentences.extend(sentences)

    if not all_sentences:
        print("ERROR: No sentences found in samples.", file=sys.stderr)
        return {}

    small_corpus = len(all_sentences) < MIN_SENTENCES_RELIABLE
    if small_corpus and verbose:
        print(
            f"WARNING: Embedding baseline computed from limited data "
            f"({len(all_sentences)} sentences) — results may be unreliable. "
            f"Recommend {MIN_SENTENCES_RELIABLE}+ sentences for stable centroid.",
            file=sys.stderr,
        )

    # Embed all sentences
    name = model_name or DEFAULT_MODEL
    model = _get_model(name)
    all_embeddings = list(model.embed(all_sentences))
    stacked = np.stack(all_embeddings)  # shape: (N, dim)

    centroid = np.mean(stacked, axis=0)
    dimension = int(centroid.shape[0])

    # Distance distribution
    distances = [
        float(1.0 - _cosine_similarity(emb, centroid))
        for emb in all_embeddings
    ]
    mean_dist = float(np.mean(distances))
    stdev_dist = float(np.std(distances))

    distance_threshold = mean_dist + 1.5 * stdev_dist
    if small_corpus:
        distance_threshold *= 1.5  # loosen for small corpora

    embedding_data = {
        "model": name,
        "centroid": centroid.tolist(),
        "dimension": dimension,
        "mean_distance": round(mean_dist, 6),
        "stdev_distance": round(stdev_dist, 6),
        "distance_threshold": round(distance_threshold, 6),
        "calibration_sentence_count": len(all_sentences),
        "calibration_word_count": total_words,
        "style_notes": "",  # filled below
        "revision_count": 0,
    }

    embedding_data["style_notes"] = generate_embedding_notes(embedding_data)
    return embedding_data


# ---------------------------------------------------------------------------
# Comparison: what did the revision do semantically?
# ---------------------------------------------------------------------------

def compare_embeddings(
    first_metrics: dict,
    final_metrics: dict,
    baseline: dict,
) -> dict:
    """
    Compare semantic drift of first draft and final draft against the baseline centroid.

    For each draft, measures how far the draft's semantic centroid sits from the
    writer's baseline centroid, and how many sentences exceed the drift threshold.

    Args:
        first_metrics: output of compute_embeddings() on the agent's first draft
        final_metrics: output of compute_embeddings() on the human's revised final
        baseline: profile["embeddings"]

    Returns:
        first_centroid_distance: cosine distance of first draft centroid from baseline
        final_centroid_distance: cosine distance of final draft centroid from baseline
        improved: True if final is closer to baseline
        first_outlier_ratio: fraction of first draft sentences beyond distance_threshold
        final_outlier_ratio: fraction of final draft sentences beyond distance_threshold
        top_drifted_sentences: up to 3 sentences from first draft that drifted most
        summary: human-readable description of what the revision did semantically
    """
    if not NUMPY_AVAILABLE:
        return {
            "first_centroid_distance": None,
            "final_centroid_distance": None,
            "improved": None,
            "first_outlier_ratio": None,
            "final_outlier_ratio": None,
            "top_drifted_sentences": [],
            "summary": "numpy not available",
        }

    baseline_centroid_list = baseline.get("centroid", [])
    distance_threshold = baseline.get("distance_threshold", 0.0)

    if not baseline_centroid_list:
        return {
            "first_centroid_distance": None,
            "final_centroid_distance": None,
            "improved": None,
            "first_outlier_ratio": None,
            "final_outlier_ratio": None,
            "top_drifted_sentences": [],
            "summary": "No baseline centroid available.",
        }

    baseline_centroid = np.array(baseline_centroid_list)

    # Draft centroids
    first_centroid_raw = first_metrics.get("centroid")
    final_centroid_raw = final_metrics.get("centroid")

    if first_centroid_raw is None or final_centroid_raw is None:
        return {
            "first_centroid_distance": None,
            "final_centroid_distance": None,
            "improved": None,
            "first_outlier_ratio": None,
            "final_outlier_ratio": None,
            "top_drifted_sentences": [],
            "summary": "Draft embeddings missing centroid data.",
        }

    # Handle both list (from profile JSON) and numpy array
    first_centroid = np.array(first_centroid_raw) if not isinstance(first_centroid_raw, np.ndarray) else first_centroid_raw
    final_centroid = np.array(final_centroid_raw) if not isinstance(final_centroid_raw, np.ndarray) else final_centroid_raw

    first_dist = round(float(1.0 - _cosine_similarity(first_centroid, baseline_centroid)), 6)
    final_dist = round(float(1.0 - _cosine_similarity(final_centroid, baseline_centroid)), 6)

    improved = final_dist < first_dist

    # Outlier ratios: sentences beyond distance_threshold
    first_dists = first_metrics.get("distances_from_centroid", [])
    final_dists = final_metrics.get("distances_from_centroid", [])

    if first_dists and distance_threshold > 0:
        first_outlier_ratio = round(
            sum(1 for d in first_dists if d > distance_threshold) / len(first_dists), 4
        )
    else:
        first_outlier_ratio = 0.0

    if final_dists and distance_threshold > 0:
        final_outlier_ratio = round(
            sum(1 for d in final_dists if d > distance_threshold) / len(final_dists), 4
        )
    else:
        final_outlier_ratio = 0.0

    # Top drifted sentences from first draft
    first_sentence_embeddings = first_metrics.get("sentence_embeddings", [])
    top_drifted = []
    if first_sentence_embeddings and baseline_centroid_list:
        indexed_dists = [
            (i, float(1.0 - _cosine_similarity(
                np.array(emb) if not isinstance(emb, np.ndarray) else emb,
                baseline_centroid
            )))
            for i, emb in enumerate(first_sentence_embeddings)
        ]
        indexed_dists.sort(key=lambda x: x[1], reverse=True)
        for idx, dist in indexed_dists[:3]:
            top_drifted.append({"sentence_index": idx, "distance": round(dist, 6)})

    summary = _format_embedding_summary(
        first_dist, final_dist, first_outlier_ratio, final_outlier_ratio,
        distance_threshold, improved
    )

    return {
        "first_centroid_distance": first_dist,
        "final_centroid_distance": final_dist,
        "improved": improved,
        "first_outlier_ratio": first_outlier_ratio,
        "final_outlier_ratio": final_outlier_ratio,
        "top_drifted_sentences": top_drifted,
        "summary": summary,
    }


def _format_embedding_summary(
    first_dist: float,
    final_dist: float,
    first_outlier_ratio: float,
    final_outlier_ratio: float,
    distance_threshold: float,
    improved: bool,
) -> str:
    """Format a human-readable summary of the semantic revision."""
    direction = "closer to" if improved else "further from"
    parts = [
        f"Revision moved semantic centroid {direction} your voice "
        f"(distance {first_dist:.2f}→{final_dist:.2f}, threshold {distance_threshold:.2f})."
    ]
    first_pct = round(first_outlier_ratio * 100)
    final_pct = round(final_outlier_ratio * 100)
    if first_outlier_ratio != final_outlier_ratio:
        direction_out = "decreased" if final_outlier_ratio < first_outlier_ratio else "increased"
        parts.append(
            f"Outlier sentences {direction_out} from {first_pct}% to {final_pct}%."
        )
    else:
        parts.append(f"Outlier sentences unchanged at {first_pct}%.")
    return " ".join(parts)


# ---------------------------------------------------------------------------
# Profile update: learning loop
# ---------------------------------------------------------------------------

def update_profile_embeddings(
    profile: dict,
    first_draft_metrics: dict,
    final_draft_metrics: dict,
) -> dict:
    """
    Update the profile's embeddings section from a revision pair.

    Uses exponential moving average. Alpha is large early (profile learns
    quickly from first few revisions) and shrinks as revision_count grows,
    stabilising the profile over time.

    Alpha schedule: max(0.2, 1 / (revision_count + 2))
    - revision_count=0 → alpha=0.5
    - revision_count=4 → alpha=0.167 (clamped to 0.2)
    - revision_count=9 → alpha=0.2

    Updates centroid (EMA toward final draft centroid, then re-normalises),
    mean_distance, and stdev_distance. Does not mutate input.

    Returns updated profile. Regenerates style_notes on first revision and
    every 3 revisions after that.
    """
    profile = copy.deepcopy(profile)
    baseline = profile.get("embeddings")

    if not baseline:
        return profile

    if not NUMPY_AVAILABLE:
        return profile

    # Final draft centroid
    final_centroid_raw = final_draft_metrics.get("centroid")
    if final_centroid_raw is None:
        return profile

    final_centroid = (
        np.array(final_centroid_raw)
        if not isinstance(final_centroid_raw, np.ndarray)
        else final_centroid_raw
    )

    revision_count = baseline.get("revision_count", 0)
    alpha = max(0.2, 1.0 / (revision_count + 2))

    # Update centroid via EMA, then normalise to unit vector
    old_centroid = np.array(baseline["centroid"])
    new_centroid = alpha * final_centroid + (1 - alpha) * old_centroid
    norm = np.linalg.norm(new_centroid)
    if norm > 1e-10:
        new_centroid = new_centroid / norm
    baseline["centroid"] = new_centroid.tolist()

    # Update distance distribution from final draft
    final_mean = final_draft_metrics.get("mean_distance", baseline.get("mean_distance", 0.0))
    final_stdev = final_draft_metrics.get("stdev_distance", baseline.get("stdev_distance", 0.0))

    old_mean = baseline.get("mean_distance", 0.0)
    old_stdev = baseline.get("stdev_distance", 0.0)

    baseline["mean_distance"] = round(alpha * final_mean + (1 - alpha) * old_mean, 6)
    baseline["stdev_distance"] = round(alpha * final_stdev + (1 - alpha) * old_stdev, 6)

    # Recompute threshold from updated distribution
    baseline["distance_threshold"] = round(
        baseline["mean_distance"] + 1.5 * baseline["stdev_distance"], 6
    )

    baseline["revision_count"] = revision_count + 1

    # Regenerate style_notes on first revision and every 3 after that
    new_count = baseline["revision_count"]
    if new_count == 1 or new_count % 3 == 0:
        baseline["style_notes"] = generate_embedding_notes(baseline)

    profile["embeddings"] = baseline
    return profile


# ---------------------------------------------------------------------------
# Embedding notes: human-readable semantic space summary
# ---------------------------------------------------------------------------

def generate_embedding_notes(embedding_data: dict) -> str:
    """
    Generate a plain-language summary of the writer's semantic space.

    This is the semantic style guide that agents read before drafting. It
    describes the writer's measurable semantic characteristics: how tightly
    clustered their writing is, how far sentences typically drift from the
    centre, and how much the profile has been refined through revision.
    """
    parts = []

    mean_dist = embedding_data.get("mean_distance", 0.0)
    stdev_dist = embedding_data.get("stdev_distance", 0.0)
    threshold = embedding_data.get("distance_threshold", 0.0)
    dimension = embedding_data.get("dimension", 0)
    sentence_count = embedding_data.get("calibration_sentence_count", 0)
    revision_count = embedding_data.get("revision_count", 0)

    # Semantic tightness
    if mean_dist > 0:
        if mean_dist <= 0.20:
            cluster_desc = "tight semantic cluster"
            focus_desc = "suggesting consistent topical focus and register"
        elif mean_dist <= 0.35:
            cluster_desc = "moderate semantic range"
            focus_desc = "suggesting varied but coherent topics"
        else:
            cluster_desc = "broad semantic range"
            focus_desc = "varied topics and registers"

        parts.append(
            f"Writing occupies a {cluster_desc} "
            f"(mean distance {mean_dist:.2f}, stdev {stdev_dist:.2f}) — "
            f"{focus_desc}."
        )

        if threshold > 0:
            if mean_dist <= 0.20:
                parts.append(
                    f"Sentences rarely drift beyond the baseline range "
                    f"(threshold {threshold:.2f})."
                )
            else:
                parts.append(
                    f"Expect some semantic drift in individual sentences "
                    f"(threshold {threshold:.2f})."
                )

    # Dimension note (informational)
    if dimension > 0:
        parts.append(
            f"Embeddings use {dimension}-dimensional vectors "
            f"(model: {embedding_data.get('model', DEFAULT_MODEL)})."
        )

    # Calibration provenance
    if sentence_count > 0:
        parts.append(f"Calibrated from {sentence_count} sentences.")

    if revision_count > 0:
        parts.append(f"Profile refined through {revision_count} revision pair(s).")

    return " ".join(parts) if parts else "No embedding data available."
