#!/usr/bin/env python3
"""
perplexity.py — Per-sentence perplexity scoring for voice-check.

Measures how "surprising" a writer's text is to a language model.
Human writing tends toward higher and more variable perplexity than
AI-generated text; this characterizes the writer's "surprise profile."

Two operating modes:
  calibrate_perplexity(sample_paths) → dict   — build baseline from writing samples
  compare_perplexity(first, final, baseline) → dict — compare revision pair against baseline

Called by writing_check.py in two workflows:
  --calibrate: extends the profile with a "perplexity" section
  --learn first.md final.md --profile p.json: update profile from revision pair

Does NOT use the apply_profile() globals-mutation pattern.
All functions take data as arguments and return results.

Dependencies: numpy (required for aggregation); mlx + mlx_lm (optional — graceful
              degradation if not available; all scoring functions no-op and warn).

Default model: mlx-community/Qwen2.5-1.5B-4bit (base, not instruct).
"""

import re
import sys
import math
import statistics

try:
    import numpy as np
    NUMPY_AVAILABLE = True
except ImportError:
    NUMPY_AVAILABLE = False
    print("WARNING: numpy not installed. Perplexity aggregation requires numpy.", file=sys.stderr)

try:
    import mlx.core as mx
    import mlx.nn as nn
    from mlx_lm import load as mlx_load
    MLX_AVAILABLE = True
except ImportError:
    MLX_AVAILABLE = False

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

# Default base model for perplexity scoring.
DEFAULT_MODEL = "mlx-community/Qwen2.5-1.5B-4bit"

# Minimum sentence count for a reliable perplexity baseline.
MIN_SENTENCES_RELIABLE = 20

# ---------------------------------------------------------------------------
# Model caching
# ---------------------------------------------------------------------------

_MODEL_CACHE: dict = {}


def _get_model(model_name: str = None):
    """Load model + tokenizer, caching within session to avoid redundant loads."""
    name = model_name or DEFAULT_MODEL
    if name not in _MODEL_CACHE:
        model, tokenizer = mlx_load(name)
        _MODEL_CACHE[name] = (model, tokenizer)
    return _MODEL_CACHE[name]


# ---------------------------------------------------------------------------
# Text preparation
# ---------------------------------------------------------------------------

def _get_sentences(text: str) -> list:
    """
    Split text into sentences. Uses NLTK if available, regex fallback otherwise.
    Defined independently (not imported from stylometry) to keep modules standalone.
    """
    if _NLTK_AVAILABLE and sent_tokenize is not None:
        return [s for s in sent_tokenize(text) if s.strip()]
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()]


def _strip_markdown(text: str) -> str:
    """Remove markdown formatting, preserve prose content."""
    text = re.sub(r"```[\s\S]*?```", " ", text)
    text = re.sub(r"^#{1,6}\s+", "", text, flags=re.MULTILINE)
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
    text = re.sub(r"\*(.+?)\*", r"\1", text)
    text = re.sub(r"__(.+?)__", r"\1", text)
    text = re.sub(r"_(.+?)_", r"\1", text)
    text = re.sub(r"`[^`]+`", " ", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"!\[[^\]]*\]\([^)]+\)", " ", text)
    text = re.sub(r"https?://\S+", " ", text)
    return text


# ---------------------------------------------------------------------------
# Core MLX computation — mock boundary
# ---------------------------------------------------------------------------

def _compute_single_perplexity(text: str, model, tokenizer) -> float:
    """
    Compute perplexity for a single text passage. This is the MLX boundary.

    Process:
      1. Tokenize: tokens = tokenizer.encode(text)
      2. Create input: input_ids = mx.array(tokens)[None, :]   # [1, seq_len]
      3. Forward pass: logits = model(input_ids)               # [1, seq_len, vocab_size]
      4. Shift for next-token prediction:
             shift_logits = logits[:, :-1, :]
             shift_labels = input_ids[:, 1:]
      5. Cross-entropy loss (per token), then mean → exp → perplexity
      6. Force computation with mx.eval(logits) before reading values.
      7. Clear Metal cache if available (try/except — not on all platforms).

    Returns float perplexity.
    Returns float('nan') on error (empty text, single token, MLX exception).
    """
    if not text or not text.strip():
        return float("nan")

    try:
        tokens = tokenizer.encode(text)
        if len(tokens) < 2:
            # Need at least 2 tokens for next-token prediction
            return float("nan")

        input_ids = mx.array(tokens)[None, :]           # [1, seq_len]
        logits = model(input_ids)                        # [1, seq_len, vocab_size]
        mx.eval(logits)                                  # force computation

        shift_logits = logits[:, :-1, :]                # [1, seq_len-1, vocab_size]
        shift_labels = input_ids[:, 1:]                 # [1, seq_len-1]

        loss = nn.losses.cross_entropy(
            shift_logits.reshape(-1, shift_logits.shape[-1]),
            shift_labels.reshape(-1),
            reduction="none",
        )
        perp = math.exp(loss.mean().item())

        try:
            mx.metal.clear_cache()
        except (AttributeError, Exception):
            pass

        return perp

    except Exception as exc:
        print(f"WARNING: perplexity computation failed: {exc}", file=sys.stderr)
        return float("nan")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def compute_perplexity(text: str, model_name: str = None) -> dict:
    """
    Compute per-sentence perplexity for a text.

    Splits text into sentences, scores each with the language model, and
    returns aggregate statistics characterising the writer's "surprise profile."

    Args:
        text: Raw prose (markdown stripped internally).
        model_name: Override the default model. None → DEFAULT_MODEL.

    Returns dict with keys:
        sentence_perplexities: list of float (nan for unparseable sentences)
        mean: float — mean perplexity across valid sentences
        stdev: float
        variance: float
        cv: float — coefficient of variation (stdev / mean); 0.0 if mean is 0
        sentence_count: int — number of sentences attempted
        model: str — model name used

    Returns empty dict (with warning) if MLX is not available.
    """
    if not MLX_AVAILABLE:
        print(
            "WARNING: mlx / mlx_lm not installed. Perplexity scoring unavailable. "
            "Install with: pip install mlx mlx-lm",
            file=sys.stderr,
        )
        return {}

    model, tokenizer = _get_model(model_name)
    used_model = model_name or DEFAULT_MODEL

    clean = _strip_markdown(text)
    sentences = _get_sentences(clean)

    perplexities = [_compute_single_perplexity(s, model, tokenizer) for s in sentences]
    valid = [p for p in perplexities if not math.isnan(p)]

    if not valid:
        return {
            "sentence_perplexities": perplexities,
            "mean": float("nan"),
            "stdev": float("nan"),
            "variance": float("nan"),
            "cv": float("nan"),
            "sentence_count": len(sentences),
            "model": used_model,
        }

    mean = statistics.mean(valid)
    stdev = statistics.stdev(valid) if len(valid) > 1 else 0.0
    variance = stdev ** 2
    cv = stdev / mean if mean > 0 else 0.0

    return {
        "sentence_perplexities": perplexities,
        "mean": round(mean, 4),
        "stdev": round(stdev, 4),
        "variance": round(variance, 4),
        "cv": round(cv, 4),
        "sentence_count": len(sentences),
        "model": used_model,
    }


def calibrate_perplexity(
    sample_paths: list,
    model_name: str = None,
    verbose: bool = True,
) -> dict:
    """
    Build a perplexity baseline from a list of writing sample file paths.

    Reads each sample, scores all sentences, aggregates statistics across
    all samples into a single baseline, and derives a distance_threshold
    (mean + 2 * stdev of per-sentence perplexity).

    Small corpus handling: if fewer than MIN_SENTENCES_RELIABLE (20) sentences
    total, warns and loosens threshold by 1.5×.

    Returns the dict for profile["perplexity"]. Empty dict on failure or if
    MLX is not available.
    """
    if not MLX_AVAILABLE:
        print(
            "WARNING: mlx / mlx_lm not installed. Perplexity calibration unavailable.",
            file=sys.stderr,
        )
        return {}

    if not sample_paths:
        print("ERROR: No sample paths provided for perplexity calibration.", file=sys.stderr)
        return {}

    model, tokenizer = _get_model(model_name)
    used_model = model_name or DEFAULT_MODEL

    all_sentence_perplexities: list = []

    for path in sample_paths:
        try:
            with open(path, "r", encoding="utf-8") as f:
                text = f.read()
        except OSError as e:
            print(f"WARNING: Could not read {path}: {e}", file=sys.stderr)
            continue

        clean = _strip_markdown(text)
        sentences = _get_sentences(clean)
        for s in sentences:
            p = _compute_single_perplexity(s, model, tokenizer)
            if not math.isnan(p):
                all_sentence_perplexities.append(p)

    if not all_sentence_perplexities:
        print(
            "ERROR: No valid perplexity scores computed from samples.",
            file=sys.stderr,
        )
        return {}

    n = len(all_sentence_perplexities)
    small_corpus = n < MIN_SENTENCES_RELIABLE

    if small_corpus and verbose:
        print(
            f"WARNING: Perplexity baseline computed from only {n} sentences — "
            f"results may be unreliable. Recommend {MIN_SENTENCES_RELIABLE}+ sentences "
            f"for a stable surprise profile.",
            file=sys.stderr,
        )

    mean = statistics.mean(all_sentence_perplexities)
    stdev = statistics.stdev(all_sentence_perplexities) if n > 1 else 0.0
    variance = stdev ** 2
    cv = stdev / mean if mean > 0 else 0.0

    distance_threshold = mean + 2.0 * stdev
    if small_corpus:
        distance_threshold *= 1.5

    perplexity_data = {
        "model": used_model,
        "baseline_mean": round(mean, 4),
        "baseline_stdev": round(stdev, 4),
        "baseline_variance": round(variance, 4),
        "baseline_cv": round(cv, 4),
        "calibration_sentence_count": n,
        "distance_threshold": round(float(distance_threshold), 4),
        "style_notes": "",
        "revision_count": 0,
        "enabled": True,
    }

    perplexity_data["style_notes"] = generate_perplexity_notes(perplexity_data)
    return perplexity_data


def compare_perplexity(
    first_metrics: dict,
    final_metrics: dict,
    baseline: dict,
) -> dict:
    """
    Compare perplexity distributions of first draft vs final draft against baseline.

    "Improved" means the final draft's distribution is closer to the writer's
    baseline — both mean and variance converging toward the baseline values.

    Args:
        first_metrics: output of compute_perplexity() on the agent's first draft
        final_metrics: output of compute_perplexity() on the human's revised final
        baseline: profile["perplexity"]

    Returns dict with keys:
        first_mean, final_mean, baseline_mean: float
        first_cv, final_cv, baseline_cv: float
        improved: bool — True if final draft closer to baseline in mean + CV
        summary: human-readable string describing the revision's effect
    """
    first_mean = first_metrics.get("mean", float("nan"))
    final_mean = final_metrics.get("mean", float("nan"))
    first_cv = first_metrics.get("cv", float("nan"))
    final_cv = final_metrics.get("cv", float("nan"))

    base_mean = baseline.get("baseline_mean", float("nan"))
    base_cv = baseline.get("baseline_cv", float("nan"))

    # Determine whether revision improved alignment with baseline
    if (math.isnan(first_mean) or math.isnan(final_mean)
            or math.isnan(base_mean) or math.isnan(first_cv)
            or math.isnan(final_cv) or math.isnan(base_cv)):
        improved = False
    else:
        first_mean_dist = abs(first_mean - base_mean)
        final_mean_dist = abs(final_mean - base_mean)
        first_cv_dist = abs(first_cv - base_cv)
        final_cv_dist = abs(final_cv - base_cv)
        improved = (final_mean_dist <= first_mean_dist) and (final_cv_dist <= first_cv_dist)

    summary = _format_perplexity_summary(
        first_mean, final_mean, base_mean,
        first_cv, final_cv, base_cv,
        improved,
    )

    def _fmt(v):
        return round(v, 4) if not math.isnan(v) else None

    return {
        "first_mean": _fmt(first_mean),
        "final_mean": _fmt(final_mean),
        "baseline_mean": _fmt(base_mean),
        "first_cv": _fmt(first_cv),
        "final_cv": _fmt(final_cv),
        "baseline_cv": _fmt(base_cv),
        "improved": improved,
        "summary": summary,
    }


def _format_perplexity_summary(
    first_mean: float,
    final_mean: float,
    base_mean: float,
    first_cv: float,
    final_cv: float,
    base_cv: float,
    improved: bool,
) -> str:
    """Format a human-readable summary of what the perplexity comparison found."""
    parts = []

    has_data = not any(math.isnan(v) for v in
                       [first_mean, final_mean, base_mean, first_cv, final_cv, base_cv])

    if has_data:
        direction = "closer to" if improved else "further from"
        parts.append(
            f"Revision moved {direction} your natural surprise profile."
        )

        # Mean perplexity shift
        mean_direction = "increased" if final_mean > first_mean else "decreased"
        parts.append(
            f"Mean perplexity {mean_direction} "
            f"({first_mean:.1f} → {final_mean:.1f}, baseline {base_mean:.1f})."
        )

        # CV shift (variation / texture)
        cv_direction = "increased" if final_cv > first_cv else "decreased"
        parts.append(
            f"Revision {cv_direction} perplexity variance "
            f"(CV {first_cv:.2f} → {final_cv:.2f}, baseline {base_cv:.2f}), "
            f"{'moving closer to' if improved else 'diverging from'} "
            f"your natural surprise profile."
        )
    else:
        parts.append("Insufficient data for perplexity comparison.")

    return " ".join(parts)


def update_profile_perplexity(
    profile: dict,
    first_draft_metrics: dict,
    final_draft_metrics: dict,
) -> dict:
    """
    Update the profile's perplexity section from a revision pair.

    Uses exponential moving average (EMA). Alpha is large early (rapid learning)
    and shrinks as revision_count grows (stabilizing the profile over time).

    Alpha schedule: max(0.2, 1 / (revision_count + 2))
      - revision_count=0 → alpha=0.5
      - revision_count=4 → alpha=0.167 (clamped to 0.2)
      - revision_count=9 → alpha=0.2

    Updates baseline_mean, baseline_stdev, baseline_variance, baseline_cv
    from the final draft's metrics. Does not mutate input dict.

    Regenerates style_notes on first revision and every 3 revisions after that.
    """
    import copy
    profile = copy.deepcopy(profile)
    baseline = profile.get("perplexity")

    if not baseline:
        return profile

    revision_count = baseline.get("revision_count", 0)
    alpha = max(0.2, 1.0 / (revision_count + 2))

    def ema(old_val, new_val):
        if math.isnan(old_val) or math.isnan(new_val):
            return old_val
        return round(alpha * new_val + (1 - alpha) * old_val, 6)

    final_mean = final_draft_metrics.get("mean", float("nan"))
    final_stdev = final_draft_metrics.get("stdev", float("nan"))
    final_variance = final_draft_metrics.get("variance", float("nan"))
    final_cv = final_draft_metrics.get("cv", float("nan"))

    baseline["baseline_mean"] = ema(baseline.get("baseline_mean", float("nan")), final_mean)
    baseline["baseline_stdev"] = ema(baseline.get("baseline_stdev", float("nan")), final_stdev)
    baseline["baseline_variance"] = ema(
        baseline.get("baseline_variance", float("nan")), final_variance
    )
    baseline["baseline_cv"] = ema(baseline.get("baseline_cv", float("nan")), final_cv)

    baseline["revision_count"] = revision_count + 1

    new_count = baseline["revision_count"]
    if new_count == 1 or new_count % 3 == 0:
        baseline["style_notes"] = generate_perplexity_notes(baseline)

    profile["perplexity"] = baseline
    return profile


def generate_perplexity_notes(perplexity_data: dict) -> str:
    """
    Generate a plain-language summary of the writer's perplexity profile.

    This is the guide that agents read before drafting. It describes:
      - predictability level (low / medium / high perplexity)
      - sentence-to-sentence consistency (low / high CV)
      - what this means concretely for drafting
      - data provenance (revision count, model)
    """
    parts = []

    mean = perplexity_data.get("baseline_mean")
    cv = perplexity_data.get("baseline_cv")
    model = perplexity_data.get("model", DEFAULT_MODEL)
    revision_count = perplexity_data.get("revision_count", 0)
    sentence_count = perplexity_data.get("calibration_sentence_count", 0)
    threshold = perplexity_data.get("distance_threshold")

    # Predictability level
    if mean is not None and not math.isnan(mean):
        if mean >= 100:
            pred_level = "high unpredictability"
            pred_guidance = (
                "Use unconventional phrasing, syntactic variety, and unexpected transitions. "
                "Smooth, predictable prose will feel foreign to this voice."
            )
        elif mean >= 40:
            pred_level = "moderate unpredictability"
            pred_guidance = (
                "Mix predictable and surprising constructions. "
                "Avoid uniformly smooth or formulaic prose."
            )
        else:
            pred_level = "low unpredictability (high predictability)"
            pred_guidance = (
                "Prefer clear, direct, economical phrasing. "
                "Elaborate variation will feel out of register."
            )

        parts.append(
            f"Writing has {pred_level} (mean perplexity {mean:.1f}). {pred_guidance}"
        )
    else:
        parts.append("Mean perplexity not yet calibrated.")

    # Sentence-to-sentence variation (CV)
    if cv is not None and not math.isnan(cv):
        if cv >= 0.5:
            var_desc = "high sentence-to-sentence variation (CV {:.2f})".format(cv)
            var_guidance = (
                "Deliberately vary sentence complexity — some sentences should be jarring "
                "or unusual, others routine. Uniform smoothness is a contamination signal."
            )
        elif cv >= 0.25:
            var_desc = "moderate sentence-to-sentence variation (CV {:.2f})".format(cv)
            var_guidance = (
                "Maintain a mix of predictable and surprising sentences without "
                "going to extremes."
            )
        else:
            var_desc = "low sentence-to-sentence variation (CV {:.2f})".format(cv)
            var_guidance = (
                "This voice is unusually consistent in predictability. "
                "Avoid injecting dramatic variation."
            )

        parts.append(f"Sentences show {var_desc}. {var_guidance}")
    else:
        parts.append("Perplexity variance not yet calibrated.")

    # Threshold note
    if threshold is not None and not math.isnan(threshold):
        parts.append(
            f"Distance threshold: {threshold:.1f} — individual sentences exceeding "
            f"this perplexity are 'surprising even for this writer' and should be "
            f"used deliberately, not avoided."
        )

    # Data provenance
    if revision_count > 0:
        parts.append(f"Profile updated from {revision_count} revision pair(s).")
    if sentence_count > 0:
        parts.append(
            f"Calibrated from {sentence_count} sentences using {model}."
        )
    elif model:
        parts.append(f"Model: {model}.")

    return " ".join(parts)
