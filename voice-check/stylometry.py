#!/usr/bin/env python3
"""
stylometry.py — Voice fingerprinting for voice-check.

Computes statistical voice metrics (function word frequencies, punctuation ratios,
vocabulary richness, sentence length distribution) and Burrows' Delta distance
between texts.

Two operating modes:
  calibrate_stylometry(sample_paths) → dict   — build fingerprint from writing samples
  compare_stylometry(first, final, baseline) → dict — measure distance, report shifts

Called by writing_check.py in two workflows:
  --calibrate: extends the profile with a "stylometry" section
  --learn first.md final.md --profile p.json: update profile from revision pair

Does NOT use the apply_profile() globals-mutation pattern.
All functions take the profile's stylometry section as an argument and return results.

Dependencies: numpy (required for Delta); scipy (optional, improves skewness);
              nltk (tokenization, already in voice-check env).
"""

import re
import sys
import math
import statistics
from collections import Counter

try:
    import numpy as np
    NUMPY_AVAILABLE = True
except ImportError:
    NUMPY_AVAILABLE = False
    print("WARNING: numpy not installed. Burrows' Delta requires numpy.", file=sys.stderr)

try:
    from scipy.stats import skew as scipy_skew
    SCIPY_AVAILABLE = True
except ImportError:
    SCIPY_AVAILABLE = False

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
    sent_tokenize = None  # fallback defined below


# Minimum words for reliable function word frequencies.
MIN_WORDS_RELIABLE = 3000


# ---------------------------------------------------------------------------
# Text preparation
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


def _extract_words(text: str) -> list:
    """Extract lowercase alphabetic tokens (no numbers, no punctuation)."""
    return [w.lower() for w in re.findall(r"\b[a-zA-Z]+\b", text)]


def _get_sentences(text: str) -> list:
    """Split text into sentences. Uses NLTK if available, regex fallback otherwise."""
    if _NLTK_AVAILABLE and sent_tokenize is not None:
        return [s for s in sent_tokenize(text) if s.strip()]
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()]


# ---------------------------------------------------------------------------
# Punctuation ratios
# ---------------------------------------------------------------------------

def _compute_punctuation_ratios(text: str) -> dict:
    """
    Count punctuation marks per sentence.

    Returns per-sentence rates for: semicolons, colons, open-parens,
    question marks, and em-dashes (— or --).
    """
    sentences = _get_sentences(text)
    n = len(sentences)
    if n == 0:
        return {"semicolon": 0.0, "colon": 0.0, "paren": 0.0,
                "question": 0.0, "emdash": 0.0}
    return {
        "semicolon": text.count(";") / n,
        "colon": text.count(":") / n,
        "paren": text.count("(") / n,
        "question": text.count("?") / n,
        "emdash": len(re.findall(r"—|--", text)) / n,
    }


# ---------------------------------------------------------------------------
# Vocabulary richness
# ---------------------------------------------------------------------------

def _compute_ttr(words: list) -> float:
    """Type-token ratio: unique tokens / total tokens."""
    if not words:
        return 0.0
    return len(set(words)) / len(words)


def _compute_mattr(words: list, window: int = 50) -> float:
    """
    Moving Average Type-Token Ratio.
    Average TTR across all sliding windows of `window` tokens.
    Length-insensitive: corrects for the TTR artifact of longer texts.
    """
    if not words:
        return 0.0
    if len(words) < window:
        return _compute_ttr(words)
    ttrs = [
        len(set(words[i:i + window])) / window
        for i in range(len(words) - window + 1)
    ]
    return statistics.mean(ttrs)


def _compute_yules_k(words: list) -> float:
    """
    Yule's K characteristic.

    K = 10^4 × (Σ V_r·r² − N) / N²

    where V_r is the count of word types appearing exactly r times and
    N is total token count. Lower K = richer vocabulary.
    Returns 0.0 for empty or all-unique input.
    """
    if not words:
        return 0.0
    n = len(words)
    counts = Counter(words)
    freq_of_freq = Counter(counts.values())
    sum_vr_r2 = sum(v * r * r for r, v in freq_of_freq.items())
    denom = n * n
    if denom == 0:
        return 0.0
    return 10000.0 * (sum_vr_r2 - n) / denom


def _compute_vocabulary_richness(words: list) -> dict:
    return {
        "ttr": round(_compute_ttr(words), 4),
        "mattr": round(_compute_mattr(words, window=50), 4),
        "yules_k": round(_compute_yules_k(words), 2),
    }


# ---------------------------------------------------------------------------
# Sentence length distribution
# ---------------------------------------------------------------------------

def _compute_sentence_distribution(text: str) -> dict:
    """Mean, stdev, and skewness of sentence lengths (in words)."""
    sentences = _get_sentences(text)
    lengths = [len(_extract_words(s)) for s in sentences if _extract_words(s)]
    if not lengths:
        return {"mean": 0.0, "stdev": 0.0, "skew": 0.0}

    mean = statistics.mean(lengths)
    stdev = statistics.stdev(lengths) if len(lengths) > 1 else 0.0

    if SCIPY_AVAILABLE and len(lengths) >= 3:
        sk = float(scipy_skew(lengths))
    elif len(lengths) >= 3 and stdev > 0:
        # Pearson's second skewness coefficient
        median = statistics.median(lengths)
        sk = 3.0 * (mean - median) / stdev
    else:
        sk = 0.0

    return {
        "mean": round(mean, 2),
        "stdev": round(stdev, 2),
        "skew": round(sk, 3),
    }


# ---------------------------------------------------------------------------
# Core single-text computation
# ---------------------------------------------------------------------------

def compute_stylometry(text: str) -> dict:
    """
    Compute raw stylometry metrics for a single text.

    Returns all measured dimensions without requiring a baseline. Use
    compare_stylometry() to measure distance against a calibrated profile.

    Returns:
        word_freqs: relative frequency of top 200 words (used for function word lookup)
        punctuation_ratios: per-sentence rates for key punctuation marks
        vocabulary_richness: TTR, MATTR, Yule's K
        sentence_distribution: mean, stdev, skewness of sentence lengths
        word_count: total word tokens
        sentence_count: number of sentences
    """
    clean = _strip_markdown(text)
    words = _extract_words(clean)
    total = len(words)

    if total > 0:
        word_freqs = {w: c / total for w, c in Counter(words).most_common(200)}
    else:
        word_freqs = {}

    return {
        "word_freqs": word_freqs,
        "punctuation_ratios": _compute_punctuation_ratios(clean),
        "vocabulary_richness": _compute_vocabulary_richness(words),
        "sentence_distribution": _compute_sentence_distribution(clean),
        "word_count": total,
        "sentence_count": len(_get_sentences(clean)),
    }


# ---------------------------------------------------------------------------
# Calibration: build fingerprint from writing samples
# ---------------------------------------------------------------------------

def calibrate_stylometry(sample_paths: list, verbose: bool = True) -> dict:
    """
    Build a voice fingerprint from a list of writing sample file paths.

    Computes:
    - Top 50 function words (most frequent across the writer's corpus)
    - Corpus mean and stdev per function word (z-score coordinate system)
    - Centroid z-score vector (the "target" for future drafts)
    - Intra-author Burrows' Delta range (self-calibrating threshold)
    - Aggregated punctuation, vocabulary richness, and sentence metrics
    - Human-readable style_notes for use as a drafting style guide

    Small corpus handling: if calibration corpus < 3000 words, prints a warning
    and loosens the distance threshold by 1.5× to avoid false positives.

    Returns the dict for profile["stylometry"]. Empty dict on failure.
    """
    if not NUMPY_AVAILABLE:
        print("ERROR: numpy required for stylometry calibration.", file=sys.stderr)
        return {}

    # Read samples
    texts = []
    for path in sample_paths:
        try:
            with open(path, "r", encoding="utf-8") as f:
                texts.append(f.read())
        except OSError as e:
            print(f"WARNING: Could not read {path}: {e}", file=sys.stderr)

    if not texts:
        print("ERROR: No readable samples for stylometry calibration.", file=sys.stderr)
        return {}

    clean_texts = [_strip_markdown(t) for t in texts]
    sample_words = [_extract_words(ct) for ct in clean_texts]

    total_words = sum(len(w) for w in sample_words)
    small_corpus = total_words < MIN_WORDS_RELIABLE

    if small_corpus and verbose:
        print(
            f"WARNING: Stylometry baseline computed from limited data "
            f"({total_words} words) — results may be unreliable. "
            f"Recommend {MIN_WORDS_RELIABLE}+ words for stable function word frequencies.",
            file=sys.stderr
        )

    # Build function word list: top 50 by frequency across the entire corpus
    all_words: list = []
    for w in sample_words:
        all_words.extend(w)

    counter = Counter(all_words)
    function_words = [w for w, _ in counter.most_common(50)]

    # Relative frequency vectors: one per sample
    def freq_vector(words):
        n = len(words)
        if n == 0:
            return [0.0] * len(function_words)
        c = Counter(words)
        return [c.get(fw, 0) / n for fw in function_words]

    freq_matrix = np.array([freq_vector(w) for w in sample_words], dtype=float)

    # Corpus statistics (define the z-score coordinate system)
    corpus_mean = freq_matrix.mean(axis=0)
    corpus_stdev = freq_matrix.std(axis=0)
    corpus_stdev[corpus_stdev < 1e-10] = 1e-10  # avoid division by zero

    # Z-score matrix and centroid
    z_matrix = (freq_matrix - corpus_mean) / corpus_stdev
    centroid_z = z_matrix.mean(axis=0)  # near-zero by construction

    # Intra-author Burrows' Delta: pairwise between samples
    n_samples = len(texts)
    intra_deltas = [
        float(np.mean(np.abs(z_matrix[i] - z_matrix[j])))
        for i in range(n_samples)
        for j in range(i + 1, n_samples)
    ]

    if intra_deltas:
        intra_author_max_delta = max(intra_deltas)
        distance_threshold = intra_author_max_delta * 1.5
    else:
        intra_author_max_delta = None
        distance_threshold = 1.5  # default for single sample

    if small_corpus:
        distance_threshold *= 1.5  # loosen threshold for small corpora

    # Aggregate punctuation, vocab, and sentence metrics across samples
    punct_samples = [_compute_punctuation_ratios(ct) for ct in clean_texts]
    vocab_samples = [_compute_vocabulary_richness(w) for w in sample_words]
    sent_samples = [_compute_sentence_distribution(ct) for ct in clean_texts]

    def mean_of(dicts, key):
        vals = [d[key] for d in dicts if key in d and d[key] is not None]
        return round(statistics.mean(vals), 4) if vals else 0.0

    punctuation_ratios = {
        k: mean_of(punct_samples, k)
        for k in ("semicolon", "colon", "paren", "question", "emdash")
    }
    vocabulary_richness = {
        k: mean_of(vocab_samples, k)
        for k in ("ttr", "mattr", "yules_k")
    }
    sentence_distribution = {
        k: mean_of(sent_samples, k)
        for k in ("mean", "stdev", "skew")
    }

    stylometry_data = {
        "function_words": function_words,
        "corpus_mean": {fw: float(corpus_mean[i]) for i, fw in enumerate(function_words)},
        "corpus_stdev": {fw: float(corpus_stdev[i]) for i, fw in enumerate(function_words)},
        "centroid_z": {fw: float(centroid_z[i]) for i, fw in enumerate(function_words)},
        "punctuation_ratios": punctuation_ratios,
        "vocabulary_richness": vocabulary_richness,
        "sentence_distribution": sentence_distribution,
        "distance_threshold": round(float(distance_threshold), 4),
        "intra_author_max_delta": round(float(intra_author_max_delta), 4)
            if intra_author_max_delta is not None else None,
        "calibration_word_count": total_words,
        "style_notes": "",  # filled below
        "revision_count": 0,
    }

    stylometry_data["style_notes"] = generate_style_notes(stylometry_data)
    return stylometry_data


# ---------------------------------------------------------------------------
# Burrows' Delta (internal)
# ---------------------------------------------------------------------------

def _compute_burrows_delta(metrics: dict, baseline: dict) -> float:
    """
    Burrows' Delta between a text's function word frequencies and the baseline centroid.

    Z-score normalizes using baseline's stored corpus_mean and corpus_stdev,
    then computes mean absolute z-score difference from the centroid.

    Lower Delta = closer to the writer's voice fingerprint.
    Returns float('nan') if baseline lacks required data.
    """
    if not NUMPY_AVAILABLE:
        return float("nan")

    function_words = baseline.get("function_words", [])
    if not function_words:
        return float("nan")

    corpus_mean = baseline.get("corpus_mean", {})
    corpus_stdev = baseline.get("corpus_stdev", {})
    centroid_z = baseline.get("centroid_z", {})
    word_freqs = metrics.get("word_freqs", {})

    if not corpus_mean or not corpus_stdev:
        return float("nan")

    z_diffs = []
    for fw in function_words:
        freq = word_freqs.get(fw, 0.0)
        mean = corpus_mean.get(fw, 0.0)
        stdev = corpus_stdev.get(fw, 1e-10)
        z_text = (freq - mean) / stdev
        z_base = centroid_z.get(fw, 0.0)
        z_diffs.append(abs(z_text - z_base))

    return float(np.mean(z_diffs)) if z_diffs else float("nan")


# ---------------------------------------------------------------------------
# Comparison: what did the revision do?
# ---------------------------------------------------------------------------

def compare_stylometry(
    first_metrics: dict,
    final_metrics: dict,
    baseline: dict,
) -> dict:
    """
    Compare first draft to final draft against the baseline voice fingerprint.

    Computes Burrows' Delta for each draft, identifies the top 5 features that
    shifted most between first and final draft, and frames the output as revision
    guidance framed around the writer's baseline.

    Args:
        first_metrics: output of compute_stylometry() on the agent's first draft
        final_metrics: output of compute_stylometry() on the human's revised final
        baseline: profile["stylometry"]

    Returns:
        first_delta: Delta between first draft and baseline (lower = closer)
        final_delta: Delta between final draft and baseline
        improved: True if final draft is closer to baseline voice
        top_features: list of up to 5 dicts describing what shifted most
        summary: human-readable revision guidance string
    """
    first_delta = _compute_burrows_delta(first_metrics, baseline)
    final_delta = _compute_burrows_delta(final_metrics, baseline)

    if math.isnan(first_delta) or math.isnan(final_delta):
        improved = None
    else:
        improved = final_delta < first_delta

    top_features = _find_shifted_features(first_metrics, final_metrics, baseline)
    summary = _format_comparison_summary(first_delta, final_delta, top_features, baseline)

    return {
        "first_delta": round(first_delta, 4) if not math.isnan(first_delta) else None,
        "final_delta": round(final_delta, 4) if not math.isnan(final_delta) else None,
        "improved": improved,
        "top_features": top_features,
        "summary": summary,
    }


def _find_shifted_features(
    first_metrics: dict,
    final_metrics: dict,
    baseline: dict,
) -> list:
    """
    Identify the top 5 features that shifted most between first and final draft.

    Considers: punctuation ratios, vocabulary richness dimensions, and sentence
    distribution. Returns list of dicts sorted by shift magnitude.
    """
    shifts = []

    # Punctuation
    punct_base = baseline.get("punctuation_ratios", {})
    first_punct = first_metrics.get("punctuation_ratios", {})
    final_punct = final_metrics.get("punctuation_ratios", {})

    punct_labels = {
        "semicolon": "semicolons/sentence",
        "colon": "colons/sentence",
        "paren": "parentheses/sentence",
        "question": "question marks/sentence",
        "emdash": "em-dashes/sentence",
    }
    for key, label in punct_labels.items():
        first_val = first_punct.get(key, 0.0)
        final_val = final_punct.get(key, 0.0)
        base_val = punct_base.get(key, 0.0)
        shift = abs(final_val - first_val)
        if shift > 0.001:
            shifts.append({
                "feature": label,
                "first_value": round(first_val, 3),
                "final_value": round(final_val, 3),
                "baseline_value": round(base_val, 3),
                "shift_magnitude": round(shift, 4),
                "direction": "increased" if final_val > first_val else "decreased",
            })

    # Vocabulary richness
    vocab_base = baseline.get("vocabulary_richness", {})
    first_vocab = first_metrics.get("vocabulary_richness", {})
    final_vocab = final_metrics.get("vocabulary_richness", {})

    vocab_labels = {
        "ttr": "type-token ratio",
        "mattr": "moving avg TTR (MATTR)",
        "yules_k": "Yule's K",
    }
    for key, label in vocab_labels.items():
        first_val = first_vocab.get(key, 0.0)
        final_val = final_vocab.get(key, 0.0)
        base_val = vocab_base.get(key, 0.0)
        # Normalize shift by baseline magnitude for comparability
        denom = abs(base_val) if base_val != 0 else 1.0
        shift = abs(final_val - first_val) / denom
        if shift > 0.01:
            shifts.append({
                "feature": label,
                "first_value": round(first_val, 4),
                "final_value": round(final_val, 4),
                "baseline_value": round(base_val, 4),
                "shift_magnitude": round(shift, 4),
                "direction": "increased" if final_val > first_val else "decreased",
            })

    # Sentence distribution
    sent_base = baseline.get("sentence_distribution", {})
    first_sent = first_metrics.get("sentence_distribution", {})
    final_sent = final_metrics.get("sentence_distribution", {})

    for key, label in (("mean", "mean sentence length (words)"),
                       ("stdev", "sentence length variability")):
        first_val = first_sent.get(key, 0.0)
        final_val = final_sent.get(key, 0.0)
        base_val = sent_base.get(key, 0.0)
        shift = abs(final_val - first_val)
        if shift > 0.5:
            shifts.append({
                "feature": label,
                "first_value": round(first_val, 1),
                "final_value": round(final_val, 1),
                "baseline_value": round(base_val, 1),
                "shift_magnitude": round(shift, 2),
                "direction": "increased" if final_val > first_val else "decreased",
            })

    shifts.sort(key=lambda x: x["shift_magnitude"], reverse=True)
    return shifts[:5]


def _format_comparison_summary(
    first_delta: float,
    final_delta: float,
    top_features: list,
    baseline: dict,
) -> str:
    """Format a human-readable summary of what the revision did."""
    parts = []

    if not math.isnan(first_delta) and not math.isnan(final_delta):
        direction = "closer to" if final_delta < first_delta else "further from"
        threshold = baseline.get("distance_threshold", "?")
        parts.append(
            f"Revision moved {direction} your voice fingerprint "
            f"(Delta: {first_delta:.3f} → {final_delta:.3f}, threshold: {threshold})."
        )

    if top_features:
        parts.append("Top shifts in your revision:")
        for feat in top_features:
            parts.append(
                f"  {feat['feature']}: "
                f"{feat['first_value']} → {feat['final_value']} "
                f"(baseline: {feat['baseline_value']})"
            )

    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Profile update: learning loop
# ---------------------------------------------------------------------------

def update_profile_stylometry(
    profile: dict,
    first_draft_metrics: dict,
    final_draft_metrics: dict,
) -> dict:
    """
    Update the profile's stylometry section from a revision pair.

    Uses exponential moving average. Alpha is large early (profile learns
    quickly from first few revisions) and shrinks as revision_count grows,
    stabilizing the profile over time.

    Alpha schedule: max(0.2, 1 / (revision_count + 2))
    - revision_count=0 → alpha=0.5
    - revision_count=4 → alpha=0.167 (clamped to 0.2)
    - revision_count=9 → alpha=0.2

    Updates centroid_z (function word targets), punctuation_ratios,
    vocabulary_richness, and sentence_distribution. Does not mutate input.

    Returns updated profile. Regenerates style_notes every 3 revisions.
    """
    import copy
    profile = copy.deepcopy(profile)
    baseline = profile.get("stylometry")

    if not baseline:
        return profile

    revision_count = baseline.get("revision_count", 0)
    alpha = max(0.2, 1.0 / (revision_count + 2))

    def ema(old_val, new_val):
        return round(alpha * new_val + (1 - alpha) * old_val, 6)

    # Punctuation ratios
    final_punct = final_draft_metrics.get("punctuation_ratios", {})
    for key in list(baseline.get("punctuation_ratios", {})):
        if key in final_punct:
            baseline["punctuation_ratios"][key] = ema(
                baseline["punctuation_ratios"][key], final_punct[key]
            )

    # Vocabulary richness
    final_vocab = final_draft_metrics.get("vocabulary_richness", {})
    for key in list(baseline.get("vocabulary_richness", {})):
        if key in final_vocab:
            baseline["vocabulary_richness"][key] = ema(
                baseline["vocabulary_richness"][key], final_vocab[key]
            )

    # Sentence distribution (mean, stdev, skew)
    final_sent = final_draft_metrics.get("sentence_distribution", {})
    for key in ("mean", "stdev", "skew"):
        if key in baseline.get("sentence_distribution", {}) and key in final_sent:
            baseline["sentence_distribution"][key] = ema(
                baseline["sentence_distribution"][key], final_sent[key]
            )

    # Centroid z-scores: shift toward final draft's z-scores
    if (NUMPY_AVAILABLE
            and baseline.get("function_words")
            and baseline.get("corpus_mean")):
        function_words = baseline["function_words"]
        corpus_mean = baseline["corpus_mean"]
        corpus_stdev = baseline["corpus_stdev"]
        final_word_freqs = final_draft_metrics.get("word_freqs", {})
        centroid_z = baseline.get("centroid_z", {})

        for fw in function_words:
            freq = final_word_freqs.get(fw, 0.0)
            mean = corpus_mean.get(fw, 0.0)
            stdev = corpus_stdev.get(fw, 1e-10)
            z_final = (freq - mean) / stdev
            old_z = centroid_z.get(fw, 0.0)
            centroid_z[fw] = round(alpha * z_final + (1 - alpha) * old_z, 6)

        baseline["centroid_z"] = centroid_z

    baseline["revision_count"] = revision_count + 1

    # Regenerate style_notes on first revision and every 3 after that
    new_count = baseline["revision_count"]
    if new_count == 1 or new_count % 3 == 0:
        baseline["style_notes"] = generate_style_notes(baseline)

    profile["stylometry"] = baseline
    return profile


# ---------------------------------------------------------------------------
# Style notes: human-readable fingerprint summary
# ---------------------------------------------------------------------------

def generate_style_notes(stylometry_data: dict) -> str:
    """
    Generate a plain-language summary of the voice fingerprint.

    This is the style guide that agents read before drafting. It describes
    the writer's measurable characteristics: sentence rhythm, punctuation
    habits, vocabulary density, and characteristic function words.
    """
    parts = []

    # Sentence rhythm
    sent = stylometry_data.get("sentence_distribution", {})
    mean_len = sent.get("mean", 0)
    stdev_len = sent.get("stdev", 0)
    skew = sent.get("skew", 0)

    if mean_len > 0:
        if mean_len >= 25:
            complexity = "long, complex"
        elif mean_len >= 18:
            complexity = "moderately long"
        elif mean_len >= 12:
            complexity = "medium-length"
        else:
            complexity = "short, direct"

        rhythm = (
            "uneven rhythm" if stdev_len > mean_len * 0.5
            else "relatively consistent rhythm"
        )
        if skew > 0.5:
            skew_note = "occasional very long sentences"
        elif skew < -0.5:
            skew_note = "few outlier-length sentences"
        else:
            skew_note = "roughly symmetric length distribution"

        parts.append(
            f"Writes {complexity} sentences (mean {mean_len} words, "
            f"stdev {stdev_len}). {rhythm.capitalize()} — {skew_note}."
        )

    # Punctuation habits
    punct = stylometry_data.get("punctuation_ratios", {})
    punct_notes = []

    if punct.get("semicolon", 0) >= 0.05:
        punct_notes.append("frequent semicolons")
    elif punct.get("semicolon", 0) <= 0.01:
        punct_notes.append("rare semicolons")

    if punct.get("emdash", 0) >= 0.1:
        punct_notes.append("heavy em-dash use")
    elif punct.get("emdash", 0) <= 0.02:
        punct_notes.append("minimal em-dashes")

    if punct.get("paren", 0) >= 0.15:
        punct_notes.append("frequent parentheticals")

    if punct.get("question", 0) >= 0.05:
        punct_notes.append("rhetorical questions")

    if punct_notes:
        parts.append(f"Punctuation habits: {', '.join(punct_notes)}.")

    # Vocabulary richness
    vocab = stylometry_data.get("vocabulary_richness", {})
    mattr = vocab.get("mattr", 0)
    ttr = vocab.get("ttr", 0)

    if mattr > 0.8:
        parts.append(f"Rich, varied vocabulary (MATTR {mattr}, TTR {ttr}).")
    elif mattr > 0.65:
        parts.append(f"Moderately varied vocabulary (MATTR {mattr}, TTR {ttr}).")
    elif mattr > 0:
        parts.append(
            f"Economical vocabulary with recurring terms (MATTR {mattr}, TTR {ttr})."
        )

    # Top function words
    function_words = stylometry_data.get("function_words", [])
    if function_words:
        top5 = function_words[:5]
        parts.append(
            f"Most characteristic function words: {', '.join(repr(w) for w in top5)}."
        )

    # Data provenance notes
    revision_count = stylometry_data.get("revision_count", 0)
    calibration_words = stylometry_data.get("calibration_word_count", 0)

    if revision_count > 0:
        parts.append(f"Profile updated from {revision_count} revision pair(s).")
    if 0 < calibration_words < MIN_WORDS_RELIABLE:
        parts.append(
            f"Note: calibrated from limited corpus ({calibration_words} words). "
            f"Stylometry baseline may be unreliable."
        )

    return " ".join(parts)
