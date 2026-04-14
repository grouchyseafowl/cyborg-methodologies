#!/usr/bin/env python3
"""
writing_check.py — Quantitative voicing analysis for draft documents.

Measures sentence structure, em-dash usage, hedge words, self-aggrandizing frames,
topic sentence patterns, passive voice, cohesion markers, readability, narrative
padding, and product-description appositives against configurable thresholds.

Supports voice profiles: load patterns and thresholds from a JSON file so
different writers can use the tool with their own calibration.

Usage:
    python3 writing_check.py path/to/draft.md [--target 1200] [--json]
    python3 writing_check.py path/to/draft.md --profile path/to/profile.json
    python3 writing_check.py --calibrate path/to/samples/ [-o profile.json]

Dependencies (all pre-installed): textstat, nltk, re, json, sys
"""

import re
import sys
import json
import argparse
import os

import textstat
import nltk

# Ensure punkt tokenizer is available
try:
    nltk.data.find("tokenizers/punkt_tab")
except LookupError:
    nltk.download("punkt_tab", quiet=True)
try:
    nltk.data.find("taggers/averaged_perceptron_tagger_eng")
except LookupError:
    nltk.download("averaged_perceptron_tagger_eng", quiet=True)

from nltk.tokenize import sent_tokenize, word_tokenize
from nltk import pos_tag


# ---------------------------------------------------------------------------
# Configuration: patterns and thresholds
# ---------------------------------------------------------------------------

HEDGE_WORDS = [
    r"\bsuggests?\b",
    r"\bsuggesting\b",
    r"\bperhaps\b",
    r"\bpotentially\b",
    r"(?<![A-Z])\bmay\b(?!\s+\d)",  # exclude "May" (month) — capitalized or before a number
    r"\bmight\b",
    r"\bcould be\b",
    r"\bappears to\b",
    r"\bseems to\b",
]

SELF_AGGRANDIZING = [
    r"\bmost striking\b",
    r"\bmost interesting\b",
    r"\bmost important\b",
    r"\bgroundbreaking\b",
    r"\bparadigm\b",
    r"\btransformative\b",
    r"\bunprecedented\b",
    r"\bmost significant\b",
    r"\bmost compelling\b",
]

TOPIC_SENTENCE_STARTERS = [
    r"(?:^|\.\s+)This is\b",
    r"(?:^|\.\s+)These are\b",
    r"(?:^|\.\s+)That is\b",
]

LOGICAL_CONNECTORS = [
    r"\bhowever\b",
    r"\bmoreover\b",
    r"\bfurthermore\b",
    r"\badditionally\b",
    r"\bconsequently\b",
]

NARRATIVE_PADDING = [
    r"\bwhat happened next\b",
    r"\bwhat happened was\b",
    r"\bthis insight came from\b",
    r"\bit is worth noting\b",
    r"\bit should be noted\b",
    r"\bwhat draws me\b",
]

CORPORATE_JARGON = [
    r"\bactionable insights?\b",
    r"\bsurfacing needs\b",
    r"\btranslating findings\b",
    r"\bleveraging\b",
    r"\bstakeholder engagement\b",
    r"\bI(?:'d| would) welcome the chance\b",
    r"\bI am excited to\b",
    r"\bI am passionate about\b",
    r"\bthought leader(?:ship)?\b",
    r"\bsynerg(?:y|ies|istic)\b",
    r"\bparadigm shift\b",
    r"\bbest practices\b",
    r"\bkey takeaway\b",
    r"\bimpactful\b",
    r"\binnovative solutions?\b",
    r"\bscalable\b",
]

# Thresholds (from VOICING_PARAMETERS.md)
THRESH_LONG_SENT = 40
THRESH_REWRITE_SENT = 50
THRESH_LONG_SENT_MAX = 4
THRESH_REWRITE_SENT_MAX = 2
THRESH_EMDASH_PER_1000 = 15
THRESH_EMDASH_INSERT_WORDS = 10
THRESH_HEDGE_MAX = 0
THRESH_AGGRANDIZE_MAX = 0
THRESH_TOPIC_THIS_MAX = 2
THRESH_CONNECTOR_MAX = 3
THRESH_PADDING_MAX = 0
THRESH_PRODUCT_MAX = 0
THRESH_JARGON_MAX = 0
THRESH_WORDCOUNT_OVER = 1.10  # 110% of target


# ---------------------------------------------------------------------------
# Profile loading
# ---------------------------------------------------------------------------

def load_profile(profile_path: str) -> dict:
    """Load a voice profile from JSON. Validates structure and regex patterns."""
    try:
        with open(profile_path, "r", encoding="utf-8") as f:
            profile = json.load(f)
    except json.JSONDecodeError as e:
        print(f"Error: Profile at {profile_path} is not valid JSON: {e}", file=sys.stderr)
        sys.exit(1)

    # Validate regex patterns compile correctly
    for category in ("hedge_words", "self_aggrandizing", "topic_sentence_starters",
                      "logical_connectors", "narrative_padding", "corporate_jargon"):
        for pattern_str in profile.get("patterns", {}).get(category, []):
            try:
                re.compile(pattern_str, re.IGNORECASE)
            except re.error as e:
                print(f"Error: Invalid regex in profile patterns.{category}: "
                      f"\"{pattern_str}\" — {e}", file=sys.stderr)
                sys.exit(1)

    return profile


def apply_profile(profile: dict):
    """Override global patterns and thresholds from a loaded profile.

    Note: the profile's 'qualitative' section is not used by this script.
    It contains CDA checklist instructions consumed by the LLM running the
    /voice-check skill. This script handles quantitative analysis only.
    """
    global HEDGE_WORDS, SELF_AGGRANDIZING, TOPIC_SENTENCE_STARTERS
    global LOGICAL_CONNECTORS, NARRATIVE_PADDING, CORPORATE_JARGON
    global THRESH_LONG_SENT, THRESH_REWRITE_SENT, THRESH_LONG_SENT_MAX
    global THRESH_REWRITE_SENT_MAX, THRESH_EMDASH_PER_1000, THRESH_EMDASH_INSERT_WORDS
    global THRESH_HEDGE_MAX, THRESH_AGGRANDIZE_MAX, THRESH_TOPIC_THIS_MAX
    global THRESH_CONNECTOR_MAX, THRESH_PADDING_MAX, THRESH_PRODUCT_MAX
    global THRESH_JARGON_MAX, THRESH_WORDCOUNT_OVER

    patterns = profile.get("patterns", {})
    if "hedge_words" in patterns:
        HEDGE_WORDS = patterns["hedge_words"]
    if "self_aggrandizing" in patterns:
        SELF_AGGRANDIZING = patterns["self_aggrandizing"]
    if "topic_sentence_starters" in patterns:
        TOPIC_SENTENCE_STARTERS = patterns["topic_sentence_starters"]
    if "logical_connectors" in patterns:
        LOGICAL_CONNECTORS = patterns["logical_connectors"]
    if "narrative_padding" in patterns:
        NARRATIVE_PADDING = patterns["narrative_padding"]
    if "corporate_jargon" in patterns:
        CORPORATE_JARGON = patterns["corporate_jargon"]

    thresholds = profile.get("thresholds", {})
    if "long_sentence_words" in thresholds:
        THRESH_LONG_SENT = thresholds["long_sentence_words"]
    if "rewrite_sentence_words" in thresholds:
        THRESH_REWRITE_SENT = thresholds["rewrite_sentence_words"]
    if "long_sentence_max" in thresholds:
        THRESH_LONG_SENT_MAX = thresholds["long_sentence_max"]
    if "rewrite_sentence_max" in thresholds:
        THRESH_REWRITE_SENT_MAX = thresholds["rewrite_sentence_max"]
    if "emdash_per_1000w" in thresholds:
        THRESH_EMDASH_PER_1000 = thresholds["emdash_per_1000w"]
    if "emdash_insertion_words" in thresholds:
        THRESH_EMDASH_INSERT_WORDS = thresholds["emdash_insertion_words"]
    if "hedge_max" in thresholds:
        THRESH_HEDGE_MAX = thresholds["hedge_max"]
    if "self_aggrandizing_max" in thresholds:
        THRESH_AGGRANDIZE_MAX = thresholds["self_aggrandizing_max"]
    if "topic_opener_max" in thresholds:
        THRESH_TOPIC_THIS_MAX = thresholds["topic_opener_max"]
    if "logical_connector_max" in thresholds:
        THRESH_CONNECTOR_MAX = thresholds["logical_connector_max"]
    if "narrative_padding_max" in thresholds:
        THRESH_PADDING_MAX = thresholds["narrative_padding_max"]
    if "product_description_max" in thresholds:
        THRESH_PRODUCT_MAX = thresholds["product_description_max"]
    if "corporate_jargon_max" in thresholds:
        THRESH_JARGON_MAX = thresholds["corporate_jargon_max"]
    if "wordcount_over_pct" in thresholds:
        THRESH_WORDCOUNT_OVER = thresholds["wordcount_over_pct"] / 100.0


# ---------------------------------------------------------------------------
# Calibration: analyze a corpus and generate a starter profile
# ---------------------------------------------------------------------------

def calibrate_from_samples(sample_dir: str, output_path: str = None):
    """
    Analyze a directory of writing samples and generate a voice profile
    with thresholds derived from the writer's actual patterns.

    Computes baseline frequencies for quantitative metrics, then sets
    thresholds at approximately 1.5 standard deviations above the mean
    (or at the observed maximum, whichever is higher).

    The qualitative section is left as a skeleton — the LLM fills it in
    by reading the samples and extracting voice characteristics.
    """
    import glob
    import statistics

    # Find samples
    samples = []
    for ext in ("*.md", "*.txt", "*.html"):
        samples.extend(glob.glob(os.path.join(sample_dir, ext)))
        samples.extend(glob.glob(os.path.join(sample_dir, "**", ext), recursive=True))
    # Deduplicate preserving order
    seen = set()
    unique_samples = []
    for s in samples:
        real = os.path.realpath(s)
        if real not in seen:
            seen.add(real)
            unique_samples.append(s)
    samples = unique_samples

    if not samples:
        print(f"Error: No .md, .txt, or .html files found in {sample_dir}", file=sys.stderr)
        sys.exit(1)

    print(f"Calibrating from {len(samples)} writing sample(s)...")

    # Collect metrics across all samples
    all_sentence_lengths = []
    all_emdash_densities = []
    all_hedge_rates = []
    all_aggrandize_rates = []
    all_topic_opener_counts = []
    all_connector_rates = []
    all_padding_rates = []
    all_jargon_rates = []
    all_product_rates = []


    for sample_path in samples:
        print(f"  Analyzing: {os.path.basename(sample_path)}")
        results = run_analysis(sample_path, target=999999)  # no word count target for calibration

        if results.get("empty"):
            continue

        wc = results["words"]["total"]
        if wc < 50:
            continue

        # Sentence lengths
        sents = results["sentences"]
        if sents["count"] > 0:
            all_sentence_lengths.append(sents["max_length"])

        # Em-dash density
        all_emdash_densities.append(results["emdashes"]["per_1000"])

        # Rates per 1000 words
        rate = lambda count: (count / wc) * 1000 if wc > 0 else 0
        all_hedge_rates.append(rate(results["hedges"]["count"]))
        all_aggrandize_rates.append(rate(results["aggrandizing"]["count"]))
        all_topic_opener_counts.append(results["topic_sentences"]["count"])
        all_connector_rates.append(rate(results["connectors"]["count"]))
        all_padding_rates.append(rate(results["padding"]["count"]))
        all_jargon_rates.append(rate(results["corporate_jargon"]["count"]))
        all_product_rates.append(rate(results["product_descriptions"]["count"]))

    if not all_sentence_lengths:
        print("Error: No samples had enough content to analyze.", file=sys.stderr)
        sys.exit(1)

    # Compute thresholds: mean + 1.5 * stdev, with floor and ceiling
    def threshold(values, floor=0, ceiling=None, round_to=0):
        if not values:
            return floor
        mean = statistics.mean(values)
        stdev = statistics.stdev(values) if len(values) > 1 else mean * 0.2
        computed = mean + 1.5 * stdev
        result = max(computed, floor)
        if ceiling is not None:
            result = min(result, ceiling)
        return round(result, round_to) if round_to else int(round(result))

    # For counts, use the max observed + a small buffer
    def count_threshold(values, buffer=1, ceiling=None):
        if not values:
            return buffer
        result = int(max(values)) + buffer
        if ceiling is not None:
            result = min(result, ceiling)
        return result

    # Build profile
    profile = {
        "profile": {
            "name": "[Your Name]",
            "version": "1.0",
            "created": __import__("datetime").date.today().isoformat(),
            "calibrated_from": f"{len(samples)} writing sample(s) in {sample_dir}",
            "description": "Auto-calibrated voice profile. Edit name, description, and qualitative checks to match your voice."
        },
        "patterns": {
            "hedge_words": [
                "\\bperhaps\\b",
                "\\bpotentially\\b",
                "(?<![A-Z])\\bmay\\b(?!\\s+\\d)",
                "\\bmight\\b",
                "\\bcould be\\b",
                "\\bappears to\\b",
                "\\bseems to\\b"
            ],
            "self_aggrandizing": [
                "\\bgroundbreaking\\b",
                "\\btransformative\\b",
                "\\bunprecedented\\b",
                "\\bmost significant\\b",
                "\\bmost compelling\\b"
            ],
            "topic_sentence_starters": [
                "(?:^|\\. +)This is\\b",
                "(?:^|\\. +)These are\\b",
                "(?:^|\\. +)That is\\b"
            ],
            "logical_connectors": [
                "\\bhowever\\b",
                "\\bmoreover\\b",
                "\\bfurthermore\\b",
                "\\badditionally\\b",
                "\\bconsequently\\b"
            ],
            "narrative_padding": [
                "\\bwhat happened next\\b",
                "\\bit is worth noting\\b",
                "\\bit should be noted\\b"
            ],
            "corporate_jargon": [
                "\\bactionable insights?\\b",
                "\\bleveraging\\b",
                "\\bstakeholder engagement\\b",
                "\\bthought leader(?:ship)?\\b",
                "\\bsynerg(?:y|ies|istic)\\b",
                "\\bimpactful\\b",
                "\\binnovative solutions?\\b"
            ]
        },
        "thresholds": {
            "long_sentence_words": threshold(all_sentence_lengths, floor=35, ceiling=55),
            "rewrite_sentence_words": threshold(all_sentence_lengths, floor=45, ceiling=65) + 10,
            "long_sentence_max": 6,
            "rewrite_sentence_max": 3,
            "emdash_per_1000w": threshold(all_emdash_densities, floor=5, ceiling=25, round_to=1),
            "emdash_insertion_words": 12,
            "hedge_max": count_threshold(all_hedge_rates, buffer=1, ceiling=3) if statistics.mean(all_hedge_rates) > 0.5 else 0,
            "self_aggrandizing_max": 0,
            "topic_opener_max": count_threshold(all_topic_opener_counts, buffer=1, ceiling=5),
            "logical_connector_max": count_threshold(all_connector_rates, buffer=1, ceiling=6) if statistics.mean(all_connector_rates) > 1 else 3,
            "narrative_padding_max": 0,
            "product_description_max": 0,
            "corporate_jargon_max": 0,
            "wordcount_over_pct": 115
        },
        "qualitative": [
            {
                "id": "transitivity",
                "category": "ideational",
                "name": "Transitivity check",
                "instruction": "Are topic sentences using material processes ('I built,' 'I developed') or relational ('This is,' 'These are')? Check the ratio."
            },
            {
                "id": "concept_scope",
                "category": "ideational",
                "name": "Concept scope",
                "instruction": "Are key concepts used as ARCHITECTURE (organizing a section) or just VOCABULARY (mentioned and abandoned)?"
            },
            {
                "id": "referential_strategy",
                "category": "interpersonal",
                "name": "Referential strategy",
                "instruction": "Is the author positioned as an ACTOR who does things, or as a CATEGORY to be identified?"
            },
            {
                "id": "argumentation_topoi",
                "category": "interpersonal",
                "name": "Argumentation topoi",
                "instruction": "Does the text lead with authority (credentials) or consequence (what happened, what it means)?"
            },
            {
                "id": "theme_rheme",
                "category": "textual",
                "name": "Theme/Rheme",
                "instruction": "Are new concepts introduced in subject position (hard to parse) or in predicate position (easier)? Subjects should be simple and familiar."
            },
            {
                "id": "genre_moves",
                "category": "structural",
                "name": "Genre moves",
                "instruction": "Are all expected moves present for this document type?"
            },
            {
                "id": "narrative_structure",
                "category": "structural",
                "name": "Narrative structure",
                "instruction": "Does each story have orientation, complication, evaluation, and result?"
            }
        ],
        "_instructions": "This profile was auto-generated from your writing samples. To customize: (1) Edit 'profile.name' and 'profile.description'. (2) Add patterns specific to YOUR anti-patterns in the 'patterns' section. (3) Run /voice-check setup to have the LLM analyze your samples and generate custom qualitative checks. (4) Adjust thresholds after running the tool on a few drafts."
    }

    if output_path is None:
        output_path = os.path.join(sample_dir, "voice_profile.json")

    # Extend profile with stylometry fingerprint (requires numpy)
    try:
        from stylometry import calibrate_stylometry
        print("\n  Computing stylometry fingerprint...")
        stylo_data = calibrate_stylometry(samples, verbose=True)
        if stylo_data:
            profile["stylometry"] = stylo_data
            print(f"  Stylometry: {stylo_data.get('style_notes', '')[:120]}")
        else:
            print("  Stylometry: skipped (calibration returned no data).")
    except ImportError:
        print("  Stylometry: skipped (stylometry.py not found).", file=sys.stderr)

    # Extend profile with perplexity baseline (requires mlx_lm)
    try:
        from perplexity import calibrate_perplexity
        print("\n  Computing perplexity baseline...")
        ppl_data = calibrate_perplexity(samples, verbose=True)
        if ppl_data:
            profile["perplexity"] = ppl_data
            print(f"  Perplexity: {ppl_data.get('style_notes', '')[:120]}")
        else:
            print("  Perplexity: skipped (MLX not available or calibration returned no data).")
    except ImportError:
        print("  Perplexity: skipped (perplexity.py not found).", file=sys.stderr)

    # Extend profile with embedding centroid (requires fastembed)
    try:
        from embeddings import calibrate_embeddings
        print("\n  Computing embedding centroid...")
        emb_data = calibrate_embeddings(samples, verbose=True)
        if emb_data:
            profile["embeddings"] = emb_data
            print(f"  Embeddings: {emb_data.get('style_notes', '')[:120]}")
        else:
            print("  Embeddings: skipped (fastembed not available or calibration returned no data).")
    except ImportError:
        print("  Embeddings: skipped (embeddings.py not found).", file=sys.stderr)

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(profile, f, indent=2, ensure_ascii=False)

    print(f"\n  Profile written to: {output_path}")
    print(f"\n  Computed thresholds from {len(samples)} sample(s):")
    t = profile["thresholds"]
    print(f"    Long sentence:    {t['long_sentence_words']} words")
    print(f"    Rewrite sentence: {t['rewrite_sentence_words']} words")
    print(f"    Em-dash density:  {t['emdash_per_1000w']}/1000 words")
    print(f"    Hedge tolerance:  {t['hedge_max']}")
    print(f"    Connector max:    {t['logical_connector_max']}")
    print(f"\n  Next steps:")
    print(f"    1. Edit the profile: set your name, description, and tweak patterns")
    print(f"    2. Run '/voice-check setup' to extract qualitative voice characteristics")
    print(f"    3. Use it: python3 writing_check.py draft.md --profile {output_path}")
    print()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def strip_markdown_formatting(text: str) -> str:
    """Remove markdown bold/italic markers for analysis, keep everything else."""
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
    text = re.sub(r"\*(.+?)\*", r"\1", text)
    text = re.sub(r"__(.+?)__", r"\1", text)
    text = re.sub(r"_(.+?)_", r"\1", text)
    return text


def load_and_prepare(filepath: str):
    """
    Load a markdown file. Return:
      - raw_lines: original lines with line numbers (1-indexed)
      - analysis_text: text with headers stripped and markdown formatting removed
      - header_count: number of header lines stripped
    """
    with open(filepath, "r", encoding="utf-8") as f:
        raw_lines = f.readlines()

    header_count = 0
    body_lines = []
    body_line_map = []  # maps body line index -> original 1-indexed line number

    for i, line in enumerate(raw_lines):
        if line.strip().startswith("#"):
            header_count += 1
        else:
            body_lines.append(line)
            body_line_map.append(i + 1)

    body_text = "".join(body_lines)
    analysis_text = strip_markdown_formatting(body_text)

    return raw_lines, analysis_text, body_lines, body_line_map, header_count


def find_line_number(raw_lines, pattern_match_text, start_search=0):
    """Find the 1-indexed line number containing a piece of text."""
    clean_fragment = strip_markdown_formatting(pattern_match_text.strip())[:60]
    for i in range(start_search, len(raw_lines)):
        clean_line = strip_markdown_formatting(raw_lines[i])
        if clean_fragment in clean_line:
            return i + 1
    return 0


def context_snippet(text: str, match_start: int, match_end: int, window: int = 40) -> str:
    """Extract a context window around a match position."""
    ctx_start = max(0, match_start - window)
    ctx_end = min(len(text), match_end + window)
    snippet = text[ctx_start:ctx_end].replace("\n", " ").strip()
    if ctx_start > 0:
        snippet = "..." + snippet
    if ctx_end < len(text):
        snippet = snippet + "..."
    return snippet


def get_line_for_position(body_lines, body_line_map, position: int) -> int:
    """Given a character position in the joined body text, return the original line number."""
    cumulative = 0
    for idx, line in enumerate(body_lines):
        cumulative += len(line)
        if position < cumulative:
            return body_line_map[idx]
    return body_line_map[-1] if body_line_map else 0


# ---------------------------------------------------------------------------
# Analysis functions
# ---------------------------------------------------------------------------

def analyze_words(analysis_text: str, target: int):
    words = word_tokenize(analysis_text)
    word_count = len(words)
    pct_diff = ((word_count - target) / target) * 100 if target > 0 else 0
    over_target = word_count > target * THRESH_WORDCOUNT_OVER
    return {
        "total": word_count,
        "target": target,
        "pct_diff": round(pct_diff, 1),
        "flag": over_target,
    }


def analyze_sentences(analysis_text: str):
    sentences = sent_tokenize(analysis_text)
    lengths = []
    long_sentences = []  # (sentence, word_count, approx line)

    for sent in sentences:
        wc = len(word_tokenize(sent))
        lengths.append(wc)

    count = len(sentences)
    avg = round(sum(lengths) / count, 1) if count else 0
    max_len = max(lengths) if lengths else 0
    over_long = [(s, l) for s, l in zip(sentences, lengths) if l > THRESH_LONG_SENT]
    over_rewrite = [(s, l) for s, l in zip(sentences, lengths) if l > THRESH_REWRITE_SENT]

    return {
        "count": count,
        "avg_length": avg,
        "max_length": max_len,
        "long_threshold": THRESH_LONG_SENT,
        "rewrite_threshold": THRESH_REWRITE_SENT,
        "over_long_count": len(over_long),
        "over_rewrite_count": len(over_rewrite),
        "over_long": over_long,
        "over_rewrite": over_rewrite,
        "flag_long": len(over_long) > THRESH_LONG_SENT_MAX,
        "flag_rewrite": len(over_rewrite) > THRESH_REWRITE_SENT_MAX,
    }


def analyze_emdashes(analysis_text: str, word_count: int, raw_lines, body_lines, body_line_map):
    # Count all em-dashes (both unicode and double-hyphen)
    emdash_pattern = re.compile(r"[\u2014]|--")
    all_dashes = list(emdash_pattern.finditer(analysis_text))
    total = len(all_dashes)
    per_1000 = round((total / word_count) * 1000, 1) if word_count > 0 else 0

    # Find em-dash insertions (text between PAIRED em-dashes within a sentence).
    # Constraints: no newlines, no sentence-ending punctuation (. ? !) between
    # the pair, which prevents matching two independent em-dashes in different
    # sentences on the same line.
    insertion_pattern = re.compile(r"(?:[\u2014]|--)\s*([^\n.!?]+?)\s*(?:[\u2014]|--)")
    long_insertions = []

    for m in insertion_pattern.finditer(analysis_text):
        insertion_text = m.group(1)
        insertion_wc = len(word_tokenize(insertion_text))
        if insertion_wc > THRESH_EMDASH_INSERT_WORDS:
            line_no = get_line_for_position(body_lines, body_line_map, m.start())
            long_insertions.append({
                "line": line_no,
                "text": insertion_text.strip()[:80],
                "word_count": insertion_wc,
            })

    return {
        "total": total,
        "per_1000": per_1000,
        "long_insertions": long_insertions,
        "flag_density": per_1000 > THRESH_EMDASH_PER_1000,
        "flag_insertions": len(long_insertions) > 0,
    }


def analyze_hedges(analysis_text: str, raw_lines, body_lines, body_line_map):
    findings = []
    for pattern_str in HEDGE_WORDS:
        pat = re.compile(pattern_str, re.IGNORECASE)
        for m in pat.finditer(analysis_text):
            word = m.group()
            line_no = get_line_for_position(body_lines, body_line_map, m.start())
            ctx = context_snippet(analysis_text, m.start(), m.end())
            findings.append({
                "line": line_no,
                "word": word,
                "context": ctx,
            })
    return {
        "count": len(findings),
        "items": findings,
        "flag": len(findings) > THRESH_HEDGE_MAX,
    }


def analyze_aggrandizing(analysis_text: str, raw_lines, body_lines, body_line_map):
    findings = []
    for pattern_str in SELF_AGGRANDIZING:
        pat = re.compile(pattern_str, re.IGNORECASE)
        for m in pat.finditer(analysis_text):
            phrase = m.group()
            line_no = get_line_for_position(body_lines, body_line_map, m.start())
            ctx = context_snippet(analysis_text, m.start(), m.end())
            findings.append({
                "line": line_no,
                "phrase": phrase,
                "context": ctx,
            })
    return {
        "count": len(findings),
        "items": findings,
        "flag": len(findings) > THRESH_AGGRANDIZE_MAX,
    }


def analyze_topic_sentences(analysis_text: str, raw_lines, body_lines, body_line_map):
    findings = []
    for pattern_str in TOPIC_SENTENCE_STARTERS:
        pat = re.compile(pattern_str, re.IGNORECASE | re.MULTILINE)
        for m in pat.finditer(analysis_text):
            # grab the rest of the sentence
            end_match = re.search(r"[.!?]", analysis_text[m.end():])
            if end_match:
                sentence_end = m.end() + end_match.end()
            else:
                sentence_end = min(m.end() + 80, len(analysis_text))
            sentence_start_text = analysis_text[m.start():sentence_end].strip()
            # Clean up leading period+space if captured
            sentence_start_text = re.sub(r"^\.\s*", "", sentence_start_text)
            line_no = get_line_for_position(body_lines, body_line_map, m.start())
            findings.append({
                "line": line_no,
                "text": sentence_start_text[:100],
            })
    return {
        "count": len(findings),
        "items": findings,
        "flag": len(findings) > THRESH_TOPIC_THIS_MAX,
    }


def analyze_passive_voice(analysis_text: str):
    """
    Approximate passive voice detection: auxiliary (was/were/is/are/been/be/being)
    followed by a past participle (VBN tag).
    """
    sentences = sent_tokenize(analysis_text)
    passive_count = 0
    passive_examples = []

    aux_pattern = re.compile(
        r"\b(was|were|is|are|been|be|being)\s+(\w+)", re.IGNORECASE
    )

    for sent in sentences:
        for m in aux_pattern.finditer(sent):
            candidate = m.group(2)
            tagged = pos_tag([candidate])
            if tagged and tagged[0][1] == "VBN":
                passive_count += 1
                if len(passive_examples) < 5:
                    passive_examples.append(sent.strip()[:100])
                break  # count once per sentence

    return {
        "count": passive_count,
        "examples": passive_examples,
    }


def analyze_connectors(analysis_text: str, raw_lines, body_lines, body_line_map):
    findings = []
    for pattern_str in LOGICAL_CONNECTORS:
        pat = re.compile(pattern_str, re.IGNORECASE)
        for m in pat.finditer(analysis_text):
            word = m.group()
            line_no = get_line_for_position(body_lines, body_line_map, m.start())
            findings.append({
                "line": line_no,
                "word": word,
            })
    return {
        "count": len(findings),
        "items": findings,
        "flag": len(findings) > THRESH_CONNECTOR_MAX,
    }


def analyze_readability(analysis_text: str):
    fk = textstat.flesch_kincaid_grade(analysis_text)
    fog = textstat.gunning_fog(analysis_text)
    fre = textstat.flesch_reading_ease(analysis_text)
    return {
        "flesch_kincaid": round(fk, 1),
        "gunning_fog": round(fog, 1),
        "flesch_reading_ease": round(fre, 1),
    }


def analyze_padding(analysis_text: str, raw_lines, body_lines, body_line_map):
    findings = []
    for pattern_str in NARRATIVE_PADDING:
        pat = re.compile(pattern_str, re.IGNORECASE)
        for m in pat.finditer(analysis_text):
            phrase = m.group()
            line_no = get_line_for_position(body_lines, body_line_map, m.start())
            findings.append({
                "line": line_no,
                "phrase": phrase,
            })
    return {
        "count": len(findings),
        "items": findings,
        "flag": len(findings) > THRESH_PADDING_MAX,
    }


def analyze_product_descriptions(analysis_text: str, raw_lines, body_lines, body_line_map):
    """
    Detect product-description appositives:
    TOOL_NAME, a/an ADJECTIVE NOUN that/which ...
    e.g. "Autograder4Canvas, an equity-centered teacher automation tool that surfaces..."
    """
    # Match: capitalized word(s) or known tool names, comma, a/an, then adjective(s)+noun, then that/which
    pat = re.compile(
        r"([A-Z][A-Za-z0-9_]*(?:\s+[A-Z][A-Za-z0-9_]*)*)"  # Tool name (capitalized)
        r",\s+an?\s+"                                         # , a/an
        r"((?:\w+[\s-])*\w+)"                                # adjective(s) + noun phrase
        r"\s+(?:that|which)\b",                               # that/which
        re.MULTILINE,
    )
    findings = []
    for m in pat.finditer(analysis_text):
        tool_name = m.group(1)
        descriptor = m.group(2)
        full_match = m.group(0)
        line_no = get_line_for_position(body_lines, body_line_map, m.start())
        findings.append({
            "line": line_no,
            "tool": tool_name,
            "descriptor": descriptor,
            "text": full_match[:100],
        })
    return {
        "count": len(findings),
        "items": findings,
        "flag": len(findings) > THRESH_PRODUCT_MAX,
    }


def analyze_corporate_jargon(analysis_text: str, raw_lines, body_lines, body_line_map):
    findings = []
    for pattern_str in CORPORATE_JARGON:
        pat = re.compile(pattern_str, re.IGNORECASE)
        for m in pat.finditer(analysis_text):
            phrase = m.group()
            line_no = get_line_for_position(body_lines, body_line_map, m.start())
            ctx = context_snippet(analysis_text, m.start(), m.end())
            findings.append({
                "line": line_no,
                "phrase": phrase,
                "context": ctx,
            })
    return {
        "count": len(findings),
        "items": findings,
        "flag": len(findings) > THRESH_JARGON_MAX,
    }


# ---------------------------------------------------------------------------
# Flagged sentences collector
# ---------------------------------------------------------------------------

def collect_flagged_sentences(analysis_text, raw_lines, body_lines, body_line_map, results):
    """Collect all individually flagged sentences with reasons."""
    flagged = []

    # Long sentences
    for sent, wc in results["sentences"]["over_long"]:
        line_no = find_line_number(raw_lines, sent)
        reason = f"Sentence is {wc} words (>{THRESH_LONG_SENT})"
        if wc > THRESH_REWRITE_SENT:
            reason += " — REWRITE"
        flagged.append({"line": line_no, "sentence": sent.strip()[:120], "reason": reason})

    # Hedge words
    for item in results["hedges"]["items"]:
        flagged.append({
            "line": item["line"],
            "sentence": item["context"],
            "reason": f"Hedge word: \"{item['word']}\"",
        })

    # Self-aggrandizing
    for item in results["aggrandizing"]["items"]:
        flagged.append({
            "line": item["line"],
            "sentence": item["context"],
            "reason": f"Self-aggrandizing frame: \"{item['phrase']}\"",
        })

    # Topic sentences
    for item in results["topic_sentences"]["items"]:
        flagged.append({
            "line": item["line"],
            "sentence": item["text"],
            "reason": "\"This is\"/\"These are\"/\"That is\" topic sentence opener",
        })

    # Long em-dash insertions
    for item in results["emdashes"]["long_insertions"]:
        flagged.append({
            "line": item["line"],
            "sentence": item["text"],
            "reason": f"Em-dash insertion is {item['word_count']} words (>{THRESH_EMDASH_INSERT_WORDS})",
        })

    # Narrative padding
    for item in results["padding"]["items"]:
        flagged.append({
            "line": item["line"],
            "sentence": item["phrase"],
            "reason": "Narrative padding phrase",
        })

    # Product descriptions
    for item in results["product_descriptions"]["items"]:
        flagged.append({
            "line": item["line"],
            "sentence": item["text"],
            "reason": f"Product-description appositive for \"{item['tool']}\"",
        })

    # Corporate jargon
    for item in results.get("corporate_jargon", {}).get("items", []):
        flagged.append({
            "line": item["line"],
            "sentence": item["context"],
            "reason": f"Corporate jargon: \"{item['phrase']}\"",
        })

    # Sort by line number
    flagged.sort(key=lambda x: x["line"])
    return flagged


# ---------------------------------------------------------------------------
# Output formatting
# ---------------------------------------------------------------------------

def flag_marker(flagged: bool) -> str:
    return " [FLAG]" if flagged else ""


def format_report(filepath: str, results: dict, flagged_sentences: list) -> str:
    filename = os.path.basename(filepath)
    wc = results["words"]
    ss = results["sentences"]
    ed = results["emdashes"]
    hd = results["hedges"]
    ag = results["aggrandizing"]
    ts = results["topic_sentences"]
    cn = results["connectors"]
    pv = results["passive"]
    rd = results["readability"]
    pd = results["padding"]
    pr = results["product_descriptions"]
    cj = results.get("corporate_jargon", {"count": 0, "items": [], "flag": False})

    sign = "+" if wc["pct_diff"] >= 0 else ""

    lines = []
    lines.append("")
    lines.append("\u2550" * 51)
    lines.append("  VOICING REPORT: " + filename)
    lines.append("\u2550" * 51)
    lines.append("")

    # Word count
    lines.append("WORD COUNT")
    lines.append(f"  Total: {wc['total']} words ({sign}{wc['pct_diff']}% vs target {wc['target']})"
                 + flag_marker(wc["flag"]))
    lines.append("")

    # Sentence structure
    lines.append("SENTENCE STRUCTURE")
    lines.append(f"  Sentences: {ss['count']} | Avg: {ss['avg_length']} words | Max: {ss['max_length']} words")
    lines.append(f"  Over {ss['long_threshold']} words: {ss['over_long_count']} sentences"
                 + flag_marker(ss["flag_long"]))
    lines.append(f"  Over {ss['rewrite_threshold']} words: {ss['over_rewrite_count']} sentences"
                 + flag_marker(ss["flag_rewrite"]))
    lines.append("")

    # Em-dash usage
    lines.append("EM-DASH USAGE")
    lines.append(f"  Total: {ed['total']} ({ed['per_1000']}/1000 words)"
                 + flag_marker(ed["flag_density"]))
    lines.append(f"  Insertions >{THRESH_EMDASH_INSERT_WORDS} words: {len(ed['long_insertions'])}"
                 + flag_marker(ed["flag_insertions"]))
    for ins in ed["long_insertions"]:
        lines.append(f"    Line {ins['line']}: \"{ins['text']}\" ({ins['word_count']} words)")
    lines.append("")

    # Modality / Stance
    lines.append("MODALITY / STANCE")
    lines.append(f"  Hedge words: {hd['count']}" + flag_marker(hd["flag"]))
    for item in hd["items"]:
        lines.append(f"    Line {item['line']}: \"{item['word']}\" \u2014 \"{item['context']}\"")
    lines.append(f"  Self-aggrandizing frames: {ag['count']}" + flag_marker(ag["flag"]))
    for item in ag["items"]:
        lines.append(f"    Line {item['line']}: \"{item['phrase']}\" \u2014 \"{item['context']}\"")
    lines.append("")

    # Topic sentences
    lines.append("TOPIC SENTENCES")
    lines.append(f"  \"This is/These are/That is\" openers: {ts['count']}"
                 + flag_marker(ts["flag"]))
    for item in ts["items"]:
        lines.append(f"    Line {item['line']}: \"{item['text']}\"")
    lines.append("")

    # Cohesion
    lines.append("COHESION")
    lines.append(f"  Logical connectors: {cn['count']}" + flag_marker(cn["flag"]))
    for item in cn["items"]:
        lines.append(f"    Line {item['line']}: \"{item['word']}\"")
    lines.append(f"  Passive voice (approx): {pv['count']}")
    lines.append("")

    # Readability
    lines.append("READABILITY")
    lines.append(f"  Flesch-Kincaid: {rd['flesch_kincaid']} | Gunning Fog: {rd['gunning_fog']} | Flesch Reading: {rd['flesch_reading_ease']}")
    lines.append("")

    # Narrative patterns
    lines.append("NARRATIVE PATTERNS")
    lines.append(f"  Padding phrases: {pd['count']}" + flag_marker(pd["flag"]))
    for item in pd["items"]:
        lines.append(f"    Line {item['line']}: \"{item['phrase']}\"")
    lines.append(f"  Product descriptions: {pr['count']}" + flag_marker(pr["flag"]))
    for item in pr["items"]:
        lines.append(f"    Line {item['line']}: \"{item['text']}\"")
    lines.append(f"  Corporate jargon: {cj['count']}" + flag_marker(cj["flag"]))
    for item in cj["items"]:
        lines.append(f"    Line {item['line']}: \"{item['phrase']}\" \u2014 \"{item['context']}\"")
    lines.append("")

    # Flagged sentences
    lines.append("\u2550" * 51)
    lines.append("  FLAGGED SENTENCES (review these)")
    lines.append("\u2550" * 51)
    lines.append("")

    if flagged_sentences:
        for fs in flagged_sentences:
            lines.append(f"  Line {fs['line']}: {fs['reason']}")
            lines.append(f"    \"{fs['sentence']}\"")
            lines.append("")
    else:
        lines.append("  No flagged sentences.")
        lines.append("")

    # Summary
    lines.append("\u2550" * 51)
    lines.append("  SUMMARY")
    lines.append("\u2550" * 51)
    lines.append("")

    # Count total flags, distinguishing voice flags (diagnostic of agent writing)
    # from structural flags (may reflect deliberate style choices)
    flag_breakdown = {}
    voice_flags = 0  # hedges, aggrandizing, padding, product descs — diagnostic
    structural_flags = 0  # long sentences, em-dashes — may be deliberate

    if wc["flag"]:
        flag_breakdown["word count"] = 1
        structural_flags += 1
    if ss["flag_long"]:
        flag_breakdown[f"long sentences (>{ss['long_threshold']}w)"] = ss["over_long_count"]
        structural_flags += ss["over_long_count"]
    if ss["flag_rewrite"]:
        flag_breakdown[f"rewrite sentences (>{ss['rewrite_threshold']}w)"] = ss["over_rewrite_count"]
        structural_flags += ss["over_rewrite_count"]
    if ed["flag_density"]:
        flag_breakdown["em-dash density"] = 1
        structural_flags += 1
    if ed["flag_insertions"]:
        flag_breakdown["em-dash insertions"] = len(ed["long_insertions"])
        structural_flags += len(ed["long_insertions"])
    if hd["flag"]:
        flag_breakdown["hedge words"] = hd["count"]
        voice_flags += hd["count"]
    if ag["flag"]:
        flag_breakdown["self-aggrandizing"] = ag["count"]
        voice_flags += ag["count"]
    if ts["flag"]:
        flag_breakdown["topic sentence openers"] = ts["count"]
        voice_flags += ts["count"]
    if cn["flag"]:
        flag_breakdown["logical connectors"] = cn["count"]
        voice_flags += cn["count"]
    if pd["flag"]:
        flag_breakdown["padding phrases"] = pd["count"]
        voice_flags += pd["count"]
    if pr["flag"]:
        flag_breakdown["product descriptions"] = pr["count"]
        voice_flags += pr["count"]
    if cj["flag"]:
        flag_breakdown["corporate jargon"] = cj["count"]
        voice_flags += cj["count"]

    total_flags = sum(flag_breakdown.values())
    breakdown_str = ", ".join(f"{v} {k}" for k, v in flag_breakdown.items())

    lines.append(f"  Flags: {total_flags} total ({voice_flags} voice, {structural_flags} structural)" +
                 (f" — {breakdown_str}" if breakdown_str else " (clean)"))

    # Overall assessment: voice flags are more diagnostic than structural flags
    # A document can have several long sentences and em-dash insertions as
    # deliberate style, but hedge words and self-aggrandizing frames are always
    # agent artifacts.
    if total_flags == 0:
        lines.append("  Draft passes quantitative voicing checks. Proceed to qualitative CDA review.")
    elif voice_flags == 0 and structural_flags <= 15:
        lines.append("  Draft has structural flags only (no voice flags). Review long sentences and em-dashes, then proceed to qualitative CDA review.")
    elif voice_flags <= 2 and total_flags <= 8:
        lines.append("  Draft has minor quantitative issues. Review flagged items, then proceed to qualitative CDA review.")
    elif voice_flags <= 4 and total_flags <= 15:
        lines.append("  Draft has notable quantitative issues. Address voice flags before qualitative review.")
    else:
        lines.append("  Draft has significant quantitative issues typical of agent-generated text. Recommend revision pass before qualitative review.")

    lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Learning loop: update profile from revision pair
# ---------------------------------------------------------------------------

def learn_from_revision(first_draft_path: str, final_draft_path: str, profile_path: str):
    """
    Compare an agent first draft to a human-revised final draft.
    Updates the profile's stylometry, perplexity, and embedding fingerprints
    via exponential moving average. Prints a revision guidance report showing
    what shifted and in which direction.
    """
    try:
        from stylometry import compute_stylometry, compare_stylometry, update_profile_stylometry
    except ImportError:
        print("Error: stylometry.py not found. Cannot run --learn mode.", file=sys.stderr)
        sys.exit(1)

    profile = load_profile(profile_path)

    if "stylometry" not in profile:
        print(
            "Error: Profile has no stylometry section. "
            "Run --calibrate first to build the voice fingerprint.",
            file=sys.stderr
        )
        sys.exit(1)

    with open(first_draft_path, "r", encoding="utf-8") as f:
        first_text = f.read()
    with open(final_draft_path, "r", encoding="utf-8") as f:
        final_text = f.read()

    # --- Stylometry ---
    first_stylo = compute_stylometry(first_text)
    final_stylo = compute_stylometry(final_text)

    stylo_comparison = compare_stylometry(first_stylo, final_stylo, profile["stylometry"])

    # Print report
    sep = "\u2550" * 51
    print(f"\n{sep}")
    print("  REVISION LEARNING REPORT")
    print(sep)
    print(f"\n  First draft:  {os.path.basename(first_draft_path)}")
    print(f"  Final draft:  {os.path.basename(final_draft_path)}")
    print(f"  Profile:      {os.path.basename(profile_path)}")
    print(f"\n  STYLOMETRY")
    print(f"  {stylo_comparison['summary']}")

    updated = update_profile_stylometry(profile, first_stylo, final_stylo)

    # --- Perplexity (optional) ---
    if "perplexity" in updated:
        try:
            from perplexity import compute_perplexity, compare_perplexity, update_profile_perplexity
            first_ppl = compute_perplexity(first_text)
            final_ppl = compute_perplexity(final_text)
            if first_ppl and final_ppl:
                ppl_comparison = compare_perplexity(first_ppl, final_ppl, updated["perplexity"])
                print(f"\n  PERPLEXITY")
                print(f"  {ppl_comparison['summary']}")
                updated = update_profile_perplexity(updated, first_ppl, final_ppl)
        except ImportError:
            pass

    # --- Embeddings (optional) ---
    if "embeddings" in updated:
        try:
            from embeddings import compute_embeddings, compare_embeddings, update_profile_embeddings
            first_emb = compute_embeddings(first_text)
            final_emb = compute_embeddings(final_text)
            if first_emb and final_emb:
                emb_comparison = compare_embeddings(first_emb, final_emb, updated["embeddings"])
                print(f"\n  EMBEDDINGS")
                print(f"  {emb_comparison['summary']}")
                updated = update_profile_embeddings(updated, first_emb, final_emb)
        except ImportError:
            pass

    # Save updated profile
    with open(profile_path, "w", encoding="utf-8") as f:
        json.dump(updated, f, indent=2, ensure_ascii=False)

    revision_count = updated["stylometry"]["revision_count"]
    print(f"\n  Profile updated. Revision count: {revision_count}")
    notes_preview = updated["stylometry"].get("style_notes", "")[:160]
    if notes_preview:
        print(f"  Style notes: {notes_preview}...")
    print()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run_analysis(filepath: str, target: int = 1200) -> dict:
    raw_lines, analysis_text, body_lines, body_line_map, header_count = load_and_prepare(filepath)

    # Edge case: empty or headers-only files
    stripped = analysis_text.strip()
    if not stripped:
        return {
            "file": os.path.basename(filepath),
            "file_path": filepath,
            "headers_stripped": header_count,
            "words": {"total": 0, "target": target, "pct_diff": -100.0, "flag": False},
            "sentences": {"count": 0, "avg_length": 0, "max_length": 0,
                          "long_threshold": THRESH_LONG_SENT,
                          "rewrite_threshold": THRESH_REWRITE_SENT,
                          "over_long_count": 0, "over_rewrite_count": 0,
                          "over_long": [], "over_rewrite": [],
                          "flag_long": False, "flag_rewrite": False},
            "emdashes": {"total": 0, "per_1000": 0, "long_insertions": [],
                         "flag_density": False, "flag_insertions": False},
            "hedges": {"count": 0, "items": [], "flag": False},
            "aggrandizing": {"count": 0, "items": [], "flag": False},
            "topic_sentences": {"count": 0, "items": [], "flag": False},
            "passive": {"count": 0, "examples": []},
            "connectors": {"count": 0, "items": [], "flag": False},
            "readability": {"flesch_kincaid": 0, "gunning_fog": 0, "flesch_reading_ease": 0},
            "padding": {"count": 0, "items": [], "flag": False},
            "product_descriptions": {"count": 0, "items": [], "flag": False},
            "flagged_sentences": [],
            "empty": True,
        }

    word_data = analyze_words(analysis_text, target)

    results = {
        "file": os.path.basename(filepath),
        "file_path": filepath,
        "headers_stripped": header_count,
        "words": word_data,
        "sentences": analyze_sentences(analysis_text),
        "emdashes": analyze_emdashes(analysis_text, word_data["total"], raw_lines, body_lines, body_line_map),
        "hedges": analyze_hedges(analysis_text, raw_lines, body_lines, body_line_map),
        "aggrandizing": analyze_aggrandizing(analysis_text, raw_lines, body_lines, body_line_map),
        "topic_sentences": analyze_topic_sentences(analysis_text, raw_lines, body_lines, body_line_map),
        "passive": analyze_passive_voice(analysis_text),
        "connectors": analyze_connectors(analysis_text, raw_lines, body_lines, body_line_map),
        "readability": analyze_readability(analysis_text),
        "padding": analyze_padding(analysis_text, raw_lines, body_lines, body_line_map),
        "product_descriptions": analyze_product_descriptions(analysis_text, raw_lines, body_lines, body_line_map),
        "corporate_jargon": analyze_corporate_jargon(analysis_text, raw_lines, body_lines, body_line_map),
    }

    flagged = collect_flagged_sentences(analysis_text, raw_lines, body_lines, body_line_map, results)
    results["flagged_sentences"] = flagged

    return results


def main():
    parser = argparse.ArgumentParser(
        description="Voicing analysis for draft documents. Supports configurable voice profiles."
    )
    parser.add_argument("file", nargs="?", help="Path to the draft file to analyze")
    parser.add_argument(
        "--target", type=int, default=1200,
        help="Target word count (default: 1200)"
    )
    parser.add_argument(
        "--json", action="store_true", dest="output_json",
        help="Output JSON instead of formatted report"
    )
    parser.add_argument(
        "--profile", type=str, default=None,
        help="Path to a voice profile JSON file"
    )
    parser.add_argument(
        "--calibrate", type=str, default=None, metavar="SAMPLE_DIR",
        help="Analyze writing samples in SAMPLE_DIR and generate a voice profile"
    )
    parser.add_argument(
        "-o", "--output", type=str, default=None,
        help="Output path for generated profile (used with --calibrate)"
    )
    parser.add_argument(
        "--learn", nargs=2, metavar=("FIRST_DRAFT", "FINAL_DRAFT"),
        help="Compare agent first draft to human-revised final; update profile stylometry"
    )
    args = parser.parse_args()

    # Learning mode (post-revision profile update)
    if args.learn:
        if not args.profile:
            parser.error("--learn requires --profile to specify which profile to update")
        first_path, final_path = args.learn
        for p in (first_path, final_path):
            if not os.path.isfile(p):
                print(f"Error: File not found: {p}", file=sys.stderr)
                sys.exit(1)
        if not os.path.isfile(args.profile):
            print(f"Error: Profile not found: {args.profile}", file=sys.stderr)
            sys.exit(1)
        learn_from_revision(first_path, final_path, args.profile)
        return

    # Calibration mode
    if args.calibrate:
        if not os.path.isdir(args.calibrate):
            print(f"Error: Directory not found: {args.calibrate}", file=sys.stderr)
            sys.exit(1)
        calibrate_from_samples(args.calibrate, args.output)
        return

    # Analysis mode — file is required
    if not args.file:
        parser.error("the following arguments are required: file (or use --calibrate)")

    if not os.path.isfile(args.file):
        print(f"Error: File not found: {args.file}", file=sys.stderr)
        sys.exit(1)

    # Load and apply voice profile if specified
    if args.profile:
        if not os.path.isfile(args.profile):
            print(f"Error: Profile not found: {args.profile}", file=sys.stderr)
            sys.exit(1)
        profile = load_profile(args.profile)
        apply_profile(profile)
        profile_name = profile.get("profile", {}).get("name", os.path.basename(args.profile))
    else:
        profile_name = None

    results = run_analysis(args.file, args.target)

    if results.get("empty"):
        print(f"\nFile has no body text (only headers or empty). Nothing to analyze.\n")
        sys.exit(0)

    if args.output_json:
        # Clean up non-serializable data for JSON output
        output = dict(results)
        if profile_name:
            output["profile"] = profile_name
        # Convert sentence tuples to dicts
        output["sentences"] = dict(results["sentences"])
        output["sentences"]["over_long"] = [
            {"sentence": s[:120], "words": w} for s, w in results["sentences"]["over_long"]
        ]
        output["sentences"]["over_rewrite"] = [
            {"sentence": s[:120], "words": w} for s, w in results["sentences"]["over_rewrite"]
        ]
        print(json.dumps(output, indent=2, ensure_ascii=False))
    else:
        flagged = results["flagged_sentences"]
        report = format_report(args.file, results, flagged)
        if profile_name:
            # Insert profile name into report header
            report = report.replace(
                "  VOICING REPORT:",
                f"  VOICING REPORT ({profile_name}):"
            )
        print(report)


if __name__ == "__main__":
    main()
