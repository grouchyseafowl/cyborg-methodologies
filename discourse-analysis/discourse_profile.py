#!/usr/bin/env python3
"""Discourse profile generator for /da skill.

Usage: python3 discourse_profile.py <text-file>
Output: JSON to stdout. Errors/warnings to stderr.
"""

import sys
import json
import re
import statistics
from collections import defaultdict

# ---------------------------------------------------------------------------
# Dependency imports with graceful degradation
# ---------------------------------------------------------------------------

try:
    import spacy
    NLP_AVAILABLE = True
except ImportError:
    NLP_AVAILABLE = False
    print("WARNING: spacy not installed. NLP-dependent features will be empty.", file=sys.stderr)

try:
    import textstat
    TEXTSTAT_AVAILABLE = True
except ImportError:
    TEXTSTAT_AVAILABLE = False
    print("WARNING: textstat not installed. Readability scores will be 0.", file=sys.stderr)

try:
    from lexicalrichness import LexicalRichness
    LEXRICH_AVAILABLE = True
except ImportError:
    LEXRICH_AVAILABLE = False
    print("WARNING: lexicalrichness not installed. MATTR will be 0.", file=sys.stderr)

try:
    import nltk
    # Ensure required corpora are present; download quietly if missing
    for _corpus in ("punkt", "averaged_perceptron_tagger", "punkt_tab"):
        try:
            nltk.data.find(f"tokenizers/{_corpus}")
        except LookupError:
            try:
                nltk.download(_corpus, quiet=True)
            except Exception:
                pass
    NLTK_AVAILABLE = True
except ImportError:
    NLTK_AVAILABLE = False
    print("WARNING: nltk not installed. Some features will be degraded.", file=sys.stderr)

# ---------------------------------------------------------------------------
# spaCy model loading
# ---------------------------------------------------------------------------

_nlp = None

def get_nlp():
    global _nlp
    if _nlp is not None:
        return _nlp
    if not NLP_AVAILABLE:
        return None
    try:
        _nlp = spacy.load("en_core_web_sm")
    except OSError:
        print("WARNING: spaCy model 'en_core_web_sm' not found. "
              "Run: python -m spacy download en_core_web_sm", file=sys.stderr)
        _nlp = None
    return _nlp


# ---------------------------------------------------------------------------
# Markdown stripping — preserve line structure (line count unchanged)
# ---------------------------------------------------------------------------

_CODE_FENCE_RE = re.compile(r"^```", re.MULTILINE)

def strip_markdown(lines):
    """Return (clean_lines, skip_set) where skip_set contains 0-indexed line
    numbers that are inside fenced code blocks and should be excluded from
    prose analysis entirely.  clean_lines[i] is the stripped prose for line i,
    or '' if line i is inside a code block."""
    skip_set = set()
    in_fence = False
    fence_start = -1

    for i, line in enumerate(lines):
        if _CODE_FENCE_RE.match(line.strip()):
            if not in_fence:
                in_fence = True
                fence_start = i
                skip_set.add(i)
            else:
                in_fence = False
                skip_set.add(i)
        elif in_fence:
            skip_set.add(i)

    clean_lines = []
    for i, line in enumerate(lines):
        if i in skip_set:
            clean_lines.append("")
            continue
        # Strip headers
        stripped = re.sub(r"^#{1,6}\s*", "", line)
        # Strip bold/italic (**, *, __, _)
        stripped = re.sub(r"\*\*(.+?)\*\*", r"\1", stripped)
        stripped = re.sub(r"\*(.+?)\*", r"\1", stripped)
        stripped = re.sub(r"__(.+?)__", r"\1", stripped)
        stripped = re.sub(r"_(.+?)_", r"\1", stripped)
        # Strip inline code
        stripped = re.sub(r"`[^`]+`", "", stripped)
        # Strip links: [text](url) → text
        stripped = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", stripped)
        # Strip image links
        stripped = re.sub(r"!\[[^\]]*\]\([^)]+\)", "", stripped)
        # Strip bare URLs
        stripped = re.sub(r"https?://\S+", "", stripped)
        clean_lines.append(stripped)

    return clean_lines, skip_set


# ---------------------------------------------------------------------------
# Text helpers
# ---------------------------------------------------------------------------

def context_snippet(text, max_len=40):
    """Return up to max_len chars of text, stripped."""
    t = text.strip()
    if len(t) <= max_len:
        return t
    return t[:max_len] + "…"


def words_in(text):
    """Simple whitespace tokenization for basic counting."""
    return [w for w in re.findall(r"\b\w+\b", text) if w]


# ---------------------------------------------------------------------------
# Sentence splitting (respects line-number mapping)
# ---------------------------------------------------------------------------

def split_sentences_with_lines(clean_lines, skip_set):
    """Return list of (sentence_text, line_number_1indexed).

    We try spaCy sentencizer first; fall back to a regex splitter.
    Line number = the line the sentence *starts* on.
    """
    nlp = get_nlp()
    # Build a joined text but track which char offset → line number
    char_to_line = {}  # char_offset → 1-indexed line number
    parts = []
    offset = 0
    for i, line in enumerate(clean_lines):
        if i in skip_set:
            continue
        for j, ch in enumerate(line):
            char_to_line[offset + j] = i + 1
        char_to_line[offset + len(line)] = i + 1  # newline char
        parts.append(line)
        offset += len(line) + 1  # +1 for \n

    joined = "\n".join(parts)

    sentences = []

    if nlp is not None:
        # Use spaCy for sentence segmentation
        doc = nlp(joined)
        for sent in doc.sents:
            start = sent.start_char
            line_num = char_to_line.get(start, 1)
            sentences.append((sent.text.strip(), line_num))
    else:
        # Regex fallback: split on . ! ? followed by whitespace + capital
        for m in re.split(r'(?<=[.!?])\s+', joined):
            m = m.strip()
            if m:
                sentences.append((m, 1))  # can't recover line numbers without nlp

    return [(s, ln) for s, ln in sentences if s.strip()]


# ---------------------------------------------------------------------------
# Paragraph counting
# ---------------------------------------------------------------------------

def count_paragraphs(lines, skip_set):
    """Count non-empty paragraphs (separated by blank lines)."""
    in_para = False
    count = 0
    for i, line in enumerate(lines):
        if i in skip_set:
            in_para = False
            continue
        if line.strip():
            if not in_para:
                count += 1
                in_para = True
        else:
            in_para = False
    return count


# ---------------------------------------------------------------------------
# Basic stats
# ---------------------------------------------------------------------------

def compute_basic_stats(sentences, clean_lines, skip_set, full_text):
    sent_lengths = [len(words_in(s)) for s, _ in sentences]
    word_count = sum(sent_lengths)
    sentence_count = len(sentences)
    paragraph_count = count_paragraphs(clean_lines, skip_set)

    mean_sent_len = statistics.mean(sent_lengths) if sent_lengths else 0.0
    sd_sent_len = statistics.stdev(sent_lengths) if len(sent_lengths) > 1 else 0.0
    max_sent_len = max(sent_lengths) if sent_lengths else 0

    readability = {"flesch_kincaid": 0.0, "gunning_fog": 0.0, "flesch_reading_ease": 0.0}
    if TEXTSTAT_AVAILABLE and full_text.strip():
        try:
            readability["flesch_kincaid"] = round(textstat.flesch_kincaid_grade(full_text), 2)
            readability["gunning_fog"] = round(textstat.gunning_fog(full_text), 2)
            readability["flesch_reading_ease"] = round(textstat.flesch_reading_ease(full_text), 2)
        except Exception as e:
            print(f"WARNING: textstat error: {e}", file=sys.stderr)

    return {
        "word_count": word_count,
        "sentence_count": sentence_count,
        "paragraph_count": paragraph_count,
        "mean_sentence_length": round(mean_sent_len, 2),
        "sd_sentence_length": round(sd_sent_len, 2),
        "max_sentence_length": max_sent_len,
        "sentence_length_distribution": sent_lengths,
        "readability": readability,
    }


# ---------------------------------------------------------------------------
# Lexical profile
# ---------------------------------------------------------------------------

_NOMINALIZATION_SUFFIXES = re.compile(
    r"(tion|ment|ness|ity|ence|ance|ism|ist)s?$", re.IGNORECASE
)

_CONTENT_POS = {"NOUN", "VERB", "ADJ", "ADV"}


def compute_lexical_profile(clean_lines, skip_set, sentences):
    nlp = get_nlp()

    # Join prose text for MATTR
    prose = " ".join(
        line for i, line in enumerate(clean_lines) if i not in skip_set and line.strip()
    )

    # Lexical density (content words / total words) via spaCy
    lexical_density = 0.0
    if nlp is not None and prose.strip():
        try:
            doc = nlp(prose)
            total_tokens = [t for t in doc if not t.is_punct and not t.is_space]
            content_tokens = [t for t in total_tokens if t.pos_ in _CONTENT_POS]
            if total_tokens:
                lexical_density = round(len(content_tokens) / len(total_tokens), 4)
        except Exception as e:
            print(f"WARNING: lexical density error: {e}", file=sys.stderr)

    # MATTR-50
    mattr_50 = 0.0
    if LEXRICH_AVAILABLE and prose.strip():
        try:
            lex = LexicalRichness(prose)
            if lex.words >= 50:
                mattr_50 = round(lex.mattr(window_size=50), 4)
            elif lex.words > 1:
                # Window can't exceed word count; fall back to simple TTR
                mattr_50 = round(lex.ttr, 4)
        except Exception as e:
            print(f"WARNING: MATTR error: {e}", file=sys.stderr)

    # Nominalizations — per line with context
    nominalizations_by_word = defaultdict(lambda: {"count": 0, "line": -1, "context": ""})
    nominalization_list = []

    if nlp is not None:
        for i, line in enumerate(clean_lines):
            if i in skip_set or not line.strip():
                continue
            try:
                doc = nlp(line)
                for token in doc:
                    if token.pos_ == "NOUN" and _NOMINALIZATION_SUFFIXES.search(token.text):
                        w = token.lemma_.lower()
                        entry = nominalizations_by_word[w]
                        entry["count"] += 1
                        if entry["line"] == -1:
                            entry["line"] = i + 1
                            entry["context"] = context_snippet(line)
            except Exception as e:
                print(f"WARNING: nominalization parse error on line {i+1}: {e}", file=sys.stderr)
    else:
        # Fallback: regex only (no POS filter)
        for i, line in enumerate(clean_lines):
            if i in skip_set or not line.strip():
                continue
            for w in words_in(line):
                if _NOMINALIZATION_SUFFIXES.search(w):
                    key = w.lower()
                    entry = nominalizations_by_word[key]
                    entry["count"] += 1
                    if entry["line"] == -1:
                        entry["line"] = i + 1
                        entry["context"] = context_snippet(line)

    nominalization_list = [
        {"word": w, "count": v["count"], "line": v["line"], "context": v["context"]}
        for w, v in sorted(nominalizations_by_word.items(), key=lambda x: -x[1]["count"])
    ]

    total_words = sum(len(words_in(s)) for s, _ in sentences) or 1
    nom_count = sum(v["count"] for v in nominalizations_by_word.values())
    nominalization_density = round(nom_count / total_words, 4)

    return {
        "lexical_density": lexical_density,
        "mattr_50": mattr_50,
        "nominalization_density": nominalization_density,
        "nominalizations": nominalization_list,
    }


# ---------------------------------------------------------------------------
# Agency profile (passive voice)
# ---------------------------------------------------------------------------

def compute_agency_profile(clean_lines, skip_set):
    nlp = get_nlp()
    passive_instances = []

    if nlp is None:
        return {
            "passive_rate": 0.0,
            "passive_with_agent": 0,
            "passive_without_agent": 0,
            "agent_deletion_rate": 0.0,
            "passive_instances": [],
        }

    sentence_count = 0

    for i, line in enumerate(clean_lines):
        if i in skip_set or not line.strip():
            continue
        try:
            doc = nlp(line)
            for sent in doc.sents:
                sentence_count += 1
                # Detect passive: look for auxpass or nsubjpass dependencies
                has_passive = any(
                    tok.dep_ in ("auxpass", "nsubjpass") for tok in sent
                )
                if not has_passive:
                    continue

                # Check for by-phrase (agent present)
                has_agent = False
                for tok in sent:
                    if tok.dep_ == "agent" or (
                        tok.dep_ == "prep" and tok.text.lower() == "by"
                    ):
                        has_agent = True
                        break

                passive_instances.append({
                    "line": i + 1,
                    "text": sent.text.strip(),
                    "has_agent": has_agent,
                })
        except Exception as e:
            print(f"WARNING: agency parse error on line {i+1}: {e}", file=sys.stderr)

    passive_with_agent = sum(1 for p in passive_instances if p["has_agent"])
    passive_without_agent = sum(1 for p in passive_instances if not p["has_agent"])
    total_passive = len(passive_instances)

    passive_rate = round(total_passive / sentence_count, 4) if sentence_count else 0.0
    agent_deletion_rate = round(
        passive_without_agent / total_passive, 4
    ) if total_passive else 0.0

    return {
        "passive_rate": passive_rate,
        "passive_with_agent": passive_with_agent,
        "passive_without_agent": passive_without_agent,
        "agent_deletion_rate": agent_deletion_rate,
        "passive_instances": passive_instances,
    }


# ---------------------------------------------------------------------------
# Pronoun profile
# ---------------------------------------------------------------------------

_PRONOUN_CLASSES = {
    "first_singular": {"i", "me", "my", "mine", "myself"},
    "first_plural": {"we", "us", "our", "ours", "ourselves"},
    "second": {"you", "your", "yours", "yourself", "yourselves"},
    "third_nonhuman": {"it", "its", "itself"},
    "third_human": {
        "he", "she", "him", "her", "his", "hers",
        "they", "them", "their", "theirs",
    },
}


def compute_pronoun_profile(clean_lines, skip_set):
    counts = {k: 0 for k in _PRONOUN_CLASSES}

    for i, line in enumerate(clean_lines):
        if i in skip_set:
            continue
        for w in words_in(line):
            wl = w.lower()
            for cls, members in _PRONOUN_CLASSES.items():
                if wl in members:
                    counts[cls] += 1

    i_we = (
        round(counts["first_singular"] / counts["first_plural"], 4)
        if counts["first_plural"] else float("inf") if counts["first_singular"] else 0.0
    )
    # treat inf as large number for JSON serialization sanity
    if i_we == float("inf"):
        i_we = counts["first_singular"] * 1000.0  # sentinel

    # we_they_ratio: first_plural vs third_human
    we_they = (
        round(counts["first_plural"] / counts["third_human"], 4)
        if counts["third_human"] else float("inf") if counts["first_plural"] else 0.0
    )
    if we_they == float("inf"):
        we_they = counts["first_plural"] * 1000.0

    return {
        **counts,
        "I_we_ratio": round(i_we, 4),
        "we_they_ratio": round(we_they, 4),
    }


# ---------------------------------------------------------------------------
# Modality profile
# ---------------------------------------------------------------------------

_MODALS = {"can", "could", "may", "might", "will", "would", "shall", "should", "must"}

_HEDGING_SINGLE = {
    "perhaps", "possibly", "probably", "seemingly", "apparently", "arguably",
    "conceivably", "presumably", "potentially", "allegedly", "reportedly",
    "ostensibly", "might", "could", "may",
}

_HEDGING_PHRASES = [
    "it seems", "it appears", "it is possible", "it is likely",
    "to some extent", "in some cases", "it could be argued",
]

_BOOSTING_SINGLE = {
    "certainly", "clearly", "obviously", "undoubtedly", "definitely",
    "undeniably", "unquestionably", "indeed", "surely", "evidently",
    "manifestly",
}

_BOOSTING_PHRASES = [
    "it is clear that", "it is evident that", "without doubt", "beyond question",
]


def compute_modality_profile(clean_lines, skip_set, sentences):
    modal_counts = {m: 0 for m in _MODALS}
    hedging_single_counts = defaultdict(int)
    boosting_single_counts = defaultdict(int)

    total_words = 0

    for i, line in enumerate(clean_lines):
        if i in skip_set:
            continue
        line_lower = line.lower()
        ws = words_in(line)
        total_words += len(ws)
        for w in ws:
            wl = w.lower()
            if wl in _MODALS:
                modal_counts[wl] += 1
            if wl in _HEDGING_SINGLE:
                hedging_single_counts[wl] += 1
            if wl in _BOOSTING_SINGLE:
                boosting_single_counts[wl] += 1

    # Phrase-level (aggregate across full prose)
    prose = " ".join(
        line.lower() for i, line in enumerate(clean_lines)
        if i not in skip_set and line.strip()
    )
    for p in _HEDGING_PHRASES:
        c = prose.count(p)
        if c:
            hedging_single_counts[p] += c
    for p in _BOOSTING_PHRASES:
        c = prose.count(p)
        if c:
            boosting_single_counts[p] += c

    modal_total = sum(modal_counts.values())
    modal_density = round(modal_total / total_words, 4) if total_words else 0.0

    hedging_markers = [
        {"word": w, "count": c}
        for w, c in sorted(hedging_single_counts.items(), key=lambda x: -x[1])
        if c > 0
    ]
    boosting_markers = [
        {"word": w, "count": c}
        for w, c in sorted(boosting_single_counts.items(), key=lambda x: -x[1])
        if c > 0
    ]

    return {
        "modal_auxiliaries": modal_counts,
        "modal_density": modal_density,
        "hedging_markers": hedging_markers,
        "boosting_markers": boosting_markers,
    }


# ---------------------------------------------------------------------------
# Theme profile (sentence-initial elements)
# ---------------------------------------------------------------------------

_FIRST_PERSON_PRON = {"i", "we", "you", "he", "she", "they", "it"}
_COORD_CONJ = {"and", "but", "or", "nor", "for", "yet", "so"}
_SUBORD_CONJ = {
    "although", "because", "since", "while", "whereas", "if", "unless",
    "until", "when", "whenever", "where", "wherever", "after", "before",
    "though", "even", "as", "once", "whether",
}
_EXISTENTIAL_THERE = re.compile(
    r"^there\s+(is|are|was|were|will|would|has|have|had)\b", re.IGNORECASE
)
_IT_CLEFT = re.compile(r"^it\s+(is|was|were|'s)\b.+\b(that|who|which)\b", re.IGNORECASE)


def classify_sentence_initial(sentence):
    """Return one of: pronoun, existential_there, it_cleft, conjunction, adverbial, noun_phrase."""
    s = sentence.strip()
    if not s:
        return "noun_phrase"

    first_word = s.split()[0].lower() if s.split() else ""

    # Existential there
    if _EXISTENTIAL_THERE.match(s):
        return "existential_there"

    # It-cleft (must come before pronoun check since "it" is a pronoun)
    if _IT_CLEFT.match(s):
        return "it_cleft"

    # Pronoun
    if first_word in _FIRST_PERSON_PRON:
        return "pronoun"

    # Conjunction
    if first_word in _COORD_CONJ or first_word in _SUBORD_CONJ:
        return "conjunction"

    # Adverbial — use spaCy if available, else heuristic
    nlp = get_nlp()
    if nlp is not None:
        try:
            doc = nlp(s[:200])  # limit for speed
            if doc:
                first_token = doc[0]
                # ADV, or prep phrase (ADP + NOUN)
                if first_token.pos_ == "ADV":
                    return "adverbial"
                if first_token.pos_ == "ADP":
                    return "adverbial"
        except Exception:
            pass
    else:
        # Heuristic: common adverbials
        if first_word in {
            "however", "therefore", "thus", "moreover", "furthermore",
            "consequently", "additionally", "meanwhile", "subsequently",
            "previously", "finally", "ultimately", "overall", "indeed",
            "certainly", "clearly", "notably", "importantly", "interestingly",
            "in", "on", "at", "by", "with", "from", "under", "through",
            "despite", "during", "after", "before", "between", "among",
        }:
            return "adverbial"

    return "noun_phrase"


def compute_theme_profile(sentences):
    counts = {
        "pronoun": 0,
        "noun_phrase": 0,
        "adverbial": 0,
        "conjunction": 0,
        "existential_there": 0,
        "it_cleft": 0,
    }
    for sent, _ in sentences:
        cat = classify_sentence_initial(sent)
        counts[cat] = counts.get(cat, 0) + 1

    total = len(sentences) or 1
    marked = counts["adverbial"] + counts["conjunction"] + counts["existential_there"] + counts["it_cleft"]
    marked_theme_rate = round(marked / total, 4)

    return {
        "sentence_initial": counts,
        "marked_theme_rate": marked_theme_rate,
    }


# ---------------------------------------------------------------------------
# Cohesion profile (connectors)
# ---------------------------------------------------------------------------

_CONNECTORS = {
    "additive": [
        "and", "also", "moreover", "furthermore", "in addition", "additionally",
        "besides", "likewise", "similarly",
    ],
    "adversative": [
        "but", "however", "yet", "nevertheless", "nonetheless", "although",
        "though", "despite", "in contrast", "on the other hand", "conversely",
    ],
    "causal": [
        "because", "therefore", "thus", "consequently", "hence", "accordingly",
        "as a result", "so", "since", "due to",
    ],
    "temporal": [
        "then", "next", "finally", "meanwhile", "subsequently", "previously",
        "afterwards", "before", "after", "during", "eventually", "simultaneously",
    ],
}


def compute_cohesion_profile(clean_lines, skip_set, word_count):
    connector_types = {k: 0 for k in _CONNECTORS}

    prose = " ".join(
        " " + line.lower() + " "
        for i, line in enumerate(clean_lines)
        if i not in skip_set and line.strip()
    )

    for cat, items in _CONNECTORS.items():
        for connector in items:
            # Match as whole word/phrase (surrounded by non-alpha or sentence boundary)
            pattern = r"(?<![a-z])" + re.escape(connector) + r"(?![a-z])"
            connector_types[cat] += len(re.findall(pattern, prose))

    connectors_total = sum(connector_types.values())
    connector_density = round(connectors_total / word_count, 4) if word_count else 0.0

    return {
        "connectors_total": connectors_total,
        "connector_types": connector_types,
        "connector_density": connector_density,
    }


# ---------------------------------------------------------------------------
# Speech representation
# ---------------------------------------------------------------------------

_REPORTING_VERBS = [
    "said", "reported", "claimed", "argued", "suggested", "stated",
    "noted", "explained", "maintained", "contended", "asserted",
    "observed", "indicated",
]

# Pattern: reporting verb optionally followed by "that" near it
_INDIRECT_PATTERN = re.compile(
    r"\b(" + "|".join(_REPORTING_VERBS) + r")\b\s*(?:that\b)?",
    re.IGNORECASE,
)


def compute_speech_representation(clean_lines, skip_set):
    direct_quotes = 0
    indirect_speech_markers = 0

    for i, line in enumerate(clean_lines):
        if i in skip_set:
            continue
        # Count paired double quotes
        dq = line.count('"') // 2
        # Single smart quotes (Unicode)
        sq = line.count('\u2018') + line.count('\u201c')  # opening single/double curly
        # Guillemets
        gq = line.count('«')
        direct_quotes += dq + sq + gq

        indirect_speech_markers += len(_INDIRECT_PATTERN.findall(line))

    return {
        "direct_quotes": direct_quotes,
        "indirect_speech_markers": indirect_speech_markers,
    }


# ---------------------------------------------------------------------------
# Flagged lines
# ---------------------------------------------------------------------------

def build_flagged_lines(clean_lines, skip_set, agency_profile, nominalization_list):
    """Collect lines with notable discourse features for easy LLM reference."""
    flagged = {}

    def flag(line_num, text, feature):
        if line_num not in flagged:
            flagged[line_num] = {"line": line_num, "text": text.strip()[:120], "features": [], "context": ""}
        if feature not in flagged[line_num]["features"]:
            flagged[line_num]["features"].append(feature)

    # Passive instances
    for p in agency_profile["passive_instances"]:
        ln = p["line"]
        raw_text = clean_lines[ln - 1] if 0 < ln <= len(clean_lines) else p["text"]
        feat = "passive_with_agent" if p["has_agent"] else "passive_no_agent"
        flag(ln, raw_text, feat)

    # Nominalizations (top 10 by frequency)
    nom_lines = set()
    for nom in nominalization_list[:10]:
        ln = nom["line"]
        if ln > 0 and ln not in nom_lines:
            nom_lines.add(ln)
            raw_text = clean_lines[ln - 1] if 0 < ln <= len(clean_lines) else nom["word"]
            flag(ln, raw_text, f"nominalization:{nom['word']}")

    # Add context snippets
    result = []
    for ln, entry in sorted(flagged.items()):
        ctx_line = clean_lines[ln - 1] if 0 < ln <= len(clean_lines) else entry["text"]
        entry["context"] = context_snippet(ctx_line, 80)
        result.append(entry)

    return result


# ---------------------------------------------------------------------------
# Main analysis orchestrator
# ---------------------------------------------------------------------------

def analyze(raw_lines):
    """Run full discourse profile. raw_lines: list of str (original file lines)."""
    clean_lines, skip_set = strip_markdown(raw_lines)

    # Build full prose text for readability (code blocks excluded)
    full_text = "\n".join(
        line for i, line in enumerate(clean_lines) if i not in skip_set
    )

    sentences = split_sentences_with_lines(clean_lines, skip_set)
    word_count = sum(len(words_in(s)) for s, _ in sentences)

    warnings = []
    if word_count == 0:
        # Empty file — return all-zeros profile
        return _empty_profile()

    if word_count < 50:
        warnings.append("Text under 50 words — quantitative measures may be unreliable")

    basic = compute_basic_stats(sentences, clean_lines, skip_set, full_text)
    lexical = compute_lexical_profile(clean_lines, skip_set, sentences)
    agency = compute_agency_profile(clean_lines, skip_set)
    pronoun = compute_pronoun_profile(clean_lines, skip_set)
    modality = compute_modality_profile(clean_lines, skip_set, sentences)
    theme = compute_theme_profile(sentences)
    cohesion = compute_cohesion_profile(clean_lines, skip_set, word_count)
    speech = compute_speech_representation(clean_lines, skip_set)
    flagged = build_flagged_lines(clean_lines, skip_set, agency, lexical["nominalizations"])

    profile = {
        "basic_stats": basic,
        "lexical_profile": lexical,
        "agency_profile": agency,
        "pronoun_profile": pronoun,
        "modality_profile": modality,
        "theme_profile": theme,
        "cohesion_profile": cohesion,
        "speech_representation": speech,
        "flagged_lines": flagged,
    }

    if warnings:
        profile["warnings"] = warnings

    return profile


def _empty_profile():
    return {
        "basic_stats": {
            "word_count": 0, "sentence_count": 0, "paragraph_count": 0,
            "mean_sentence_length": 0.0, "sd_sentence_length": 0.0,
            "max_sentence_length": 0, "sentence_length_distribution": [],
            "readability": {"flesch_kincaid": 0.0, "gunning_fog": 0.0, "flesch_reading_ease": 0.0},
        },
        "lexical_profile": {
            "lexical_density": 0.0, "mattr_50": 0.0,
            "nominalization_density": 0.0, "nominalizations": [],
        },
        "agency_profile": {
            "passive_rate": 0.0, "passive_with_agent": 0, "passive_without_agent": 0,
            "agent_deletion_rate": 0.0, "passive_instances": [],
        },
        "pronoun_profile": {
            "first_singular": 0, "first_plural": 0, "second": 0,
            "third_human": 0, "third_nonhuman": 0,
            "I_we_ratio": 0.0, "we_they_ratio": 0.0,
        },
        "modality_profile": {
            "modal_auxiliaries": {m: 0 for m in _MODALS},
            "modal_density": 0.0, "hedging_markers": [], "boosting_markers": [],
        },
        "theme_profile": {
            "sentence_initial": {
                "pronoun": 0, "noun_phrase": 0, "adverbial": 0,
                "conjunction": 0, "existential_there": 0, "it_cleft": 0,
            },
            "marked_theme_rate": 0.0,
        },
        "cohesion_profile": {
            "connectors_total": 0,
            "connector_types": {"additive": 0, "adversative": 0, "causal": 0, "temporal": 0},
            "connector_density": 0.0,
        },
        "speech_representation": {"direct_quotes": 0, "indirect_speech_markers": 0},
        "flagged_lines": [],
        "warnings": ["Empty file — no analysis possible"],
    }


# ---------------------------------------------------------------------------
# Corpus mode — cross-file comparison with outlier detection
# ---------------------------------------------------------------------------

_CORPUS_METRICS = {
    "word_count":             lambda p: p["basic_stats"]["word_count"],
    "mean_sentence_length":   lambda p: p["basic_stats"]["mean_sentence_length"],
    "flesch_kincaid":         lambda p: p["basic_stats"]["readability"]["flesch_kincaid"],
    "flesch_reading_ease":    lambda p: p["basic_stats"]["readability"]["flesch_reading_ease"],
    "lexical_density":        lambda p: p["lexical_profile"]["lexical_density"],
    "mattr_50":               lambda p: p["lexical_profile"]["mattr_50"],
    "nominalization_density": lambda p: p["lexical_profile"]["nominalization_density"],
    "passive_rate":           lambda p: p["agency_profile"]["passive_rate"],
    "agent_deletion_rate":    lambda p: p["agency_profile"]["agent_deletion_rate"],
    "first_singular":         lambda p: p["pronoun_profile"]["first_singular"],
    "first_plural":           lambda p: p["pronoun_profile"]["first_plural"],
    "modal_density":          lambda p: p["modality_profile"]["modal_density"],
    "hedge_count":            lambda p: sum(h["count"] for h in p["modality_profile"]["hedging_markers"]),
    "marked_theme_rate":      lambda p: p["theme_profile"]["marked_theme_rate"],
    "connector_density":      lambda p: p["cohesion_profile"]["connector_density"],
    "adversative_count":      lambda p: p["cohesion_profile"]["connector_types"]["adversative"],
    "direct_quotes":          lambda p: p["speech_representation"]["direct_quotes"],
    "indirect_speech":        lambda p: p["speech_representation"]["indirect_speech_markers"],
}


def corpus_mode(directory, outlier_threshold=1.5):
    """Run per-file profiles across a directory and compute corpus baseline + outlier flags.

    Output JSON structure:
        mode, directory, file_count,
        corpus_stats: {metric: {mean, sd}},
        files: [{file, metrics, z_scores, outlier_flags}],
        outlier_summary: [{file, flags}]   # only files with ≥1 flag
    """
    import os

    txt_files = sorted(
        os.path.join(directory, f)
        for f in os.listdir(directory)
        if f.endswith(".txt")
    )
    if not txt_files:
        print(f"ERROR: No .txt files found in {directory}", file=sys.stderr)
        sys.exit(1)

    profiles = []
    for path in txt_files:
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                raw_lines = f.read().splitlines()
            profile = analyze(raw_lines)
            profiles.append({"file": os.path.basename(path), "profile": profile})
        except Exception as e:
            print(f"WARNING: Skipping {path}: {e}", file=sys.stderr)

    if not profiles:
        print("ERROR: No files could be analyzed.", file=sys.stderr)
        sys.exit(1)

    # Extract scalar metrics for each file
    metric_values = {name: [] for name in _CORPUS_METRICS}
    for entry in profiles:
        p = entry["profile"]
        for name, extractor in _CORPUS_METRICS.items():
            try:
                val = extractor(p)
            except Exception:
                val = 0.0
            metric_values[name].append(float(val) if val is not None else 0.0)

    # Corpus-level stats: mean and SD per metric
    corpus_stats = {}
    for name, vals in metric_values.items():
        mean = statistics.mean(vals) if vals else 0.0
        sd = statistics.stdev(vals) if len(vals) > 1 else 0.0
        corpus_stats[name] = {"mean": round(mean, 4), "sd": round(sd, 4)}

    # Per-file z-scores and outlier flags
    file_results = []
    for i, entry in enumerate(profiles):
        metrics = {}
        z_scores = {}
        outlier_flags = []

        for name in _CORPUS_METRICS:
            val = metric_values[name][i]
            mean = corpus_stats[name]["mean"]
            sd = corpus_stats[name]["sd"]
            metrics[name] = round(val, 4)
            if sd > 0:
                z = round((val - mean) / sd, 2)
                z_scores[name] = z
                if abs(z) >= outlier_threshold:
                    direction = "above" if z > 0 else "below"
                    outlier_flags.append(f"{name} ({z:+.1f} SD {direction} mean)")
            else:
                z_scores[name] = 0.0

        file_results.append({
            "file": entry["file"],
            "metrics": metrics,
            "z_scores": z_scores,
            "outlier_flags": outlier_flags,
        })

    outlier_summary = [
        {"file": r["file"], "flags": r["outlier_flags"]}
        for r in file_results
        if r["outlier_flags"]
    ]

    return {
        "mode": "corpus",
        "directory": directory,
        "file_count": len(profiles),
        "corpus_stats": corpus_stats,
        "files": file_results,
        "outlier_summary": outlier_summary,
    }


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    args = sys.argv[1:]

    if not args:
        print("Usage: discourse_profile.py <text-file>", file=sys.stderr)
        print("       discourse_profile.py --corpus <directory>", file=sys.stderr)
        sys.exit(1)

    # Corpus mode
    if args[0] == "--corpus":
        if len(args) < 2:
            print("Usage: discourse_profile.py --corpus <directory>", file=sys.stderr)
            sys.exit(1)
        directory = args[1]
        try:
            result = corpus_mode(directory)
        except Exception as e:
            import traceback
            print(f"ERROR: Corpus analysis failed: {e}", file=sys.stderr)
            traceback.print_exc(file=sys.stderr)
            sys.exit(1)
        print(json.dumps(result, indent=2))
        return

    # Single-file mode
    filepath = args[0]

    try:
        with open(filepath, "r", encoding="utf-8", errors="replace") as f:
            raw_lines = f.read().splitlines()
    except FileNotFoundError:
        print(f"ERROR: File not found: {filepath}", file=sys.stderr)
        sys.exit(1)
    except PermissionError:
        print(f"ERROR: Permission denied: {filepath}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"ERROR: Could not read file: {e}", file=sys.stderr)
        sys.exit(1)

    try:
        profile = analyze(raw_lines)
    except Exception as e:
        import traceback
        print(f"ERROR: Analysis failed: {e}", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
        # Still output valid (empty) JSON so the skill can degrade gracefully
        print(json.dumps(_empty_profile(), indent=2))
        sys.exit(1)

    print(json.dumps(profile, indent=2))


if __name__ == "__main__":
    main()
