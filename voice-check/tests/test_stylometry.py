"""
Tests for voice-check stylometry module.

Covers: text preparation, vocabulary richness metrics, punctuation ratios,
sentence distribution, compute_stylometry, calibrate_stylometry,
compare_stylometry, update_profile_stylometry, and generate_style_notes.
"""

import os
import sys
import math
import json
import tempfile
import statistics

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from stylometry import (
    _strip_markdown,
    _extract_words,
    _get_sentences,
    _compute_ttr,
    _compute_mattr,
    _compute_yules_k,
    _compute_vocabulary_richness,
    _compute_punctuation_ratios,
    _compute_sentence_distribution,
    _compute_burrows_delta,
    compute_stylometry,
    calibrate_stylometry,
    compare_stylometry,
    update_profile_stylometry,
    generate_style_notes,
    NUMPY_AVAILABLE,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

PROSE_SAMPLE = (
    "The conditions demanded it. I didn't plan to build software. "
    "The institution failed; the students needed something. I made it. "
    "Four classes — forty-nine students each. No teaching assistant. "
    "The automation wasn't a choice: it was survival."
)

AGENT_PROSE = (
    "This innovative solution leverages best practices to transform the learning "
    "environment. The paradigm shift enables stakeholders to synergize effectively. "
    "Furthermore, the impactful approach additionally demonstrates thought leadership. "
    "Perhaps this groundbreaking methodology might potentially yield actionable insights."
)

LONGER_PROSE = (
    "I built this thing. It works well. The design was intentional. "
    "Every piece serves a purpose. The architecture reflects the critique. "
    "I carried this into the next project. "
    "This second paragraph has some longer sentences that test the thresholds "
    "for what counts as a long sentence in this particular writer's style, "
    "which tends toward complexity but not obscurity. "
    "The conditions demanded it. I didn't plan to build software. "
    "The institution failed. The students needed something. I made it. "
    "Perhaps that sounds dramatic. It isn't. The numbers tell the story. "
    "Four classes. Forty-nine students each. No teaching assistant. "
    "The automation wasn't a choice — it was survival. "
    "I built curriculum from scratch, then rebuilt it when it failed. "
    "The feedback loops were immediate: you know within a week whether something works. "
    "I kept what worked and cut what didn't. That's the whole method. "
    "It isn't glamorous. It's empirical. I trust data over theory when they conflict. "
    "The data said students weren't reading the assigned texts. "
    "So I changed the texts, not the students."
)


@pytest.fixture
def two_sample_files(tmp_path):
    """Two writing sample files for calibration tests."""
    s1 = tmp_path / "sample1.md"
    s1.write_text(
        "# Sample One\n\n"
        + LONGER_PROSE
        + "\n\nI trust what I can measure. "
        "The rest is philosophy, which I also respect but keep separate. "
        "When I run the analysis again next semester, I expect the numbers to shift. "
        "They always do. The students are different. The context has changed. "
        "I update the model. That's the practice.",
        encoding="utf-8"
    )
    s2 = tmp_path / "sample2.md"
    s2.write_text(
        "# Sample Two\n\n"
        "The semester ended with a question I couldn't answer. "
        "Not because I lacked data — I had plenty. "
        "But because the question was the wrong one. "
        "I had been optimizing for completion rates; "
        "what I should have been measuring was engagement quality. "
        "The distinction matters. A student who completes every assignment "
        "but learns nothing has succeeded by my metric and failed by theirs. "
        "I changed the metric. The completion rates dropped. "
        "The learning improved. I'm comfortable with that trade. "
        "The numbers that matter are harder to collect. "
        "I collect them anyway.",
        encoding="utf-8"
    )
    return [str(s1), str(s2)]


@pytest.fixture
def single_sample_file(tmp_path):
    """Single writing sample (tests single-sample calibration path)."""
    s = tmp_path / "single.md"
    s.write_text(LONGER_PROSE * 3, encoding="utf-8")
    return [str(s)]


@pytest.fixture
def small_corpus_file(tmp_path):
    """Very short sample — triggers small corpus warning."""
    s = tmp_path / "short.md"
    s.write_text("I built this. It works. The design was intentional.", encoding="utf-8")
    return [str(s)]


@pytest.fixture
def calibrated_baseline(two_sample_files):
    """A calibrated stylometry baseline for comparison tests."""
    return calibrate_stylometry(two_sample_files, verbose=False)


# ---------------------------------------------------------------------------
# Text preparation
# ---------------------------------------------------------------------------

class TestStripMarkdown:

    def test_removes_headers(self):
        text = "# Title\n## Subtitle\nProse here."
        result = _strip_markdown(text)
        assert "Title" in result  # heading text preserved
        assert "#" not in result

    def test_removes_bold_preserves_content(self):
        result = _strip_markdown("This is **important** text.")
        assert "important" in result
        assert "**" not in result

    def test_removes_fenced_code_blocks(self):
        text = "Prose.\n```python\ncode here\n```\nMore prose."
        result = _strip_markdown(text)
        assert "code here" not in result
        assert "Prose." in result
        assert "More prose." in result

    def test_removes_links_keeps_text(self):
        result = _strip_markdown("See [this article](https://example.com) for details.")
        assert "this article" in result
        assert "example.com" not in result

    def test_preserves_prose_unchanged(self):
        prose = "I built this. It works. The design was intentional."
        assert _strip_markdown(prose) == prose


class TestExtractWords:

    def test_returns_lowercase(self):
        words = _extract_words("Hello WORLD Test")
        assert all(w == w.lower() for w in words)

    def test_excludes_numbers(self):
        words = _extract_words("I have 42 items")
        assert "42" not in words
        assert "i" in words
        assert "have" in words
        assert "items" in words

    def test_excludes_punctuation(self):
        words = _extract_words("Hello, world! How are you?")
        assert all(w.isalpha() for w in words)

    def test_empty_text(self):
        assert _extract_words("") == []


# ---------------------------------------------------------------------------
# Vocabulary richness
# ---------------------------------------------------------------------------

class TestTTR:

    def test_all_unique(self):
        words = ["a", "b", "c", "d"]
        assert _compute_ttr(words) == 1.0

    def test_all_same(self):
        words = ["the", "the", "the", "the"]
        assert _compute_ttr(words) == 0.25

    def test_empty(self):
        assert _compute_ttr([]) == 0.0

    def test_known_value(self):
        words = ["a", "b", "a", "c"]  # 3 unique / 4 total = 0.75
        assert abs(_compute_ttr(words) - 0.75) < 1e-9


class TestMATTR:

    def test_shorter_than_window_equals_ttr(self):
        words = ["a", "b", "c"]
        assert _compute_mattr(words, window=50) == _compute_ttr(words)

    def test_all_unique_mattr_is_one(self):
        words = [f"word{i}" for i in range(100)]
        assert abs(_compute_mattr(words, window=50) - 1.0) < 1e-9

    def test_all_same_mattr_is_one_over_window(self):
        words = ["the"] * 100
        assert abs(_compute_mattr(words, window=50) - 1.0 / 50) < 1e-9

    def test_empty(self):
        assert _compute_mattr([]) == 0.0


class TestYulesK:

    def test_empty(self):
        assert _compute_yules_k([]) == 0.0

    def test_all_unique_returns_zero(self):
        # All words appear once: sum(V_r * r^2) = N * 1 = N, so K = 0
        words = list("abcde")
        assert abs(_compute_yules_k(words)) < 1e-9

    def test_repetitive_higher_than_diverse(self):
        diverse = list("abcdefghijklmnopqrstuvwxyz")
        repetitive = (["the"] * 20) + (["a"] * 5) + ["cat"]
        k_diverse = _compute_yules_k(diverse)
        k_repetitive = _compute_yules_k(repetitive)
        # Higher K = less rich vocabulary
        assert k_repetitive > k_diverse


# ---------------------------------------------------------------------------
# Punctuation ratios
# ---------------------------------------------------------------------------

class TestPunctuationRatios:

    def test_counts_semicolons(self):
        text = "First sentence; second clause. Third sentence."
        ratios = _compute_punctuation_ratios(text)
        assert ratios["semicolon"] > 0

    def test_counts_emdash_unicode(self):
        text = "This — and that — are both here. One sentence."
        ratios = _compute_punctuation_ratios(text)
        assert ratios["emdash"] > 0

    def test_counts_emdash_double_hyphen(self):
        text = "This -- and that -- are both here. One sentence."
        ratios = _compute_punctuation_ratios(text)
        assert ratios["emdash"] > 0

    def test_zero_for_clean_text(self):
        text = "Simple sentence. Another sentence. Third sentence."
        ratios = _compute_punctuation_ratios(text)
        assert ratios["semicolon"] == 0.0
        assert ratios["emdash"] == 0.0
        assert ratios["question"] == 0.0

    def test_empty_text(self):
        ratios = _compute_punctuation_ratios("")
        assert all(v == 0.0 for v in ratios.values())

    def test_per_sentence_normalization(self):
        # 4 semicolons, 2 sentences → 2.0 per sentence
        text = "A; B; C. D; E; F."
        ratios = _compute_punctuation_ratios(text)
        # We have 2 sentences and 4 semicolons
        sentences = _get_sentences(text)
        n = len(sentences)
        assert abs(ratios["semicolon"] - 4 / n) < 0.01


# ---------------------------------------------------------------------------
# Sentence distribution
# ---------------------------------------------------------------------------

class TestSentenceDistribution:

    def test_single_sentence(self):
        dist = _compute_sentence_distribution("This is a single sentence.")
        assert dist["stdev"] == 0.0
        assert dist["mean"] > 0

    def test_known_mean(self):
        # Two sentences: 3 words and 5 words → mean 4
        text = "One two three. One two three four five."
        dist = _compute_sentence_distribution(text)
        assert abs(dist["mean"] - 4.0) < 0.5

    def test_empty_text(self):
        dist = _compute_sentence_distribution("")
        assert dist["mean"] == 0.0
        assert dist["stdev"] == 0.0
        assert dist["skew"] == 0.0


# ---------------------------------------------------------------------------
# compute_stylometry
# ---------------------------------------------------------------------------

class TestComputeStylometry:

    def test_returns_required_keys(self):
        result = compute_stylometry(PROSE_SAMPLE)
        assert "word_freqs" in result
        assert "punctuation_ratios" in result
        assert "vocabulary_richness" in result
        assert "sentence_distribution" in result
        assert "word_count" in result
        assert "sentence_count" in result

    def test_word_freqs_are_relative(self):
        result = compute_stylometry(PROSE_SAMPLE)
        freqs = result["word_freqs"]
        assert all(0 <= v <= 1 for v in freqs.values())

    def test_word_count_is_positive(self):
        result = compute_stylometry(PROSE_SAMPLE)
        assert result["word_count"] > 0

    def test_empty_text_handled(self):
        result = compute_stylometry("")
        assert result["word_count"] == 0
        assert result["word_freqs"] == {}

    def test_markdown_stripped_before_analysis(self):
        md_text = "# Title\n\n**Bold** and _italic_ prose here. Another sentence."
        plain_text = "Bold and italic prose here. Another sentence."
        md_result = compute_stylometry(md_text)
        plain_result = compute_stylometry(plain_text)
        # Word counts should be close (may differ slightly due to sentence tokenization)
        assert abs(md_result["word_count"] - plain_result["word_count"]) <= 2

    def test_vocabulary_richness_keys(self):
        result = compute_stylometry(PROSE_SAMPLE)
        vr = result["vocabulary_richness"]
        assert "ttr" in vr
        assert "mattr" in vr
        assert "yules_k" in vr


# ---------------------------------------------------------------------------
# calibrate_stylometry
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not NUMPY_AVAILABLE, reason="numpy required")
class TestCalibrateStylometry:

    def test_produces_all_required_keys(self, two_sample_files):
        result = calibrate_stylometry(two_sample_files, verbose=False)
        assert "function_words" in result
        assert "corpus_mean" in result
        assert "corpus_stdev" in result
        assert "centroid_z" in result
        assert "punctuation_ratios" in result
        assert "vocabulary_richness" in result
        assert "sentence_distribution" in result
        assert "distance_threshold" in result
        assert "calibration_word_count" in result
        assert "style_notes" in result
        assert "revision_count" in result

    def test_function_word_count_at_most_50(self, two_sample_files):
        result = calibrate_stylometry(two_sample_files, verbose=False)
        assert len(result["function_words"]) <= 50

    def test_corpus_mean_keys_match_function_words(self, two_sample_files):
        result = calibrate_stylometry(two_sample_files, verbose=False)
        assert set(result["corpus_mean"].keys()) == set(result["function_words"])

    def test_corpus_stdev_keys_match_function_words(self, two_sample_files):
        result = calibrate_stylometry(two_sample_files, verbose=False)
        assert set(result["corpus_stdev"].keys()) == set(result["function_words"])

    def test_centroid_z_keys_match_function_words(self, two_sample_files):
        result = calibrate_stylometry(two_sample_files, verbose=False)
        assert set(result["centroid_z"].keys()) == set(result["function_words"])

    def test_revision_count_zero_after_calibration(self, two_sample_files):
        result = calibrate_stylometry(two_sample_files, verbose=False)
        assert result["revision_count"] == 0

    def test_style_notes_nonempty(self, two_sample_files):
        result = calibrate_stylometry(two_sample_files, verbose=False)
        assert isinstance(result["style_notes"], str)
        assert len(result["style_notes"]) > 0

    def test_distance_threshold_positive(self, two_sample_files):
        result = calibrate_stylometry(two_sample_files, verbose=False)
        assert result["distance_threshold"] > 0

    def test_single_sample_no_intra_delta(self, single_sample_file):
        result = calibrate_stylometry(single_sample_file, verbose=False)
        assert result["intra_author_max_delta"] is None
        assert result["distance_threshold"] > 0  # uses default 1.5

    def test_small_corpus_warns(self, small_corpus_file, capsys):
        calibrate_stylometry(small_corpus_file, verbose=True)
        captured = capsys.readouterr()
        assert "WARNING" in captured.err
        assert "limited data" in captured.err.lower() or "unreliable" in captured.err.lower()

    def test_calibration_word_count_recorded(self, two_sample_files):
        result = calibrate_stylometry(two_sample_files, verbose=False)
        assert result["calibration_word_count"] > 0

    def test_empty_sample_list_returns_empty(self):
        result = calibrate_stylometry([], verbose=False)
        assert result == {}

    def test_two_samples_produce_intra_delta(self, two_sample_files):
        result = calibrate_stylometry(two_sample_files, verbose=False)
        assert result["intra_author_max_delta"] is not None
        assert result["intra_author_max_delta"] >= 0


# ---------------------------------------------------------------------------
# Burrows' Delta (internal)
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not NUMPY_AVAILABLE, reason="numpy required")
class TestBurrowsDelta:

    def test_returns_nan_for_empty_baseline(self):
        metrics = compute_stylometry(PROSE_SAMPLE)
        delta = _compute_burrows_delta(metrics, {})
        assert math.isnan(delta)

    def test_returns_nan_for_missing_corpus_mean(self):
        metrics = compute_stylometry(PROSE_SAMPLE)
        delta = _compute_burrows_delta(metrics, {"function_words": ["the", "a"]})
        assert math.isnan(delta)

    def test_nonnegative(self, calibrated_baseline):
        metrics = compute_stylometry(PROSE_SAMPLE)
        delta = _compute_burrows_delta(metrics, calibrated_baseline)
        if not math.isnan(delta):
            assert delta >= 0

    def test_very_similar_text_smaller_delta(self, two_sample_files, tmp_path):
        """Text from the same author should have smaller delta than very different text."""
        with open(two_sample_files[0], "r") as f:
            author_text = f.read()

        baseline = calibrate_stylometry(two_sample_files, verbose=False)
        author_metrics = compute_stylometry(author_text)
        agent_metrics = compute_stylometry(AGENT_PROSE)

        author_delta = _compute_burrows_delta(author_metrics, baseline)
        agent_delta = _compute_burrows_delta(agent_metrics, baseline)

        if not (math.isnan(author_delta) or math.isnan(agent_delta)):
            # Author text should be closer to their own baseline
            assert author_delta <= agent_delta


# ---------------------------------------------------------------------------
# compare_stylometry
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not NUMPY_AVAILABLE, reason="numpy required")
class TestCompareStylometry:

    def test_returns_required_keys(self, calibrated_baseline):
        first = compute_stylometry(AGENT_PROSE)
        final = compute_stylometry(PROSE_SAMPLE)
        result = compare_stylometry(first, final, calibrated_baseline)
        assert "first_delta" in result
        assert "final_delta" in result
        assert "improved" in result
        assert "top_features" in result
        assert "summary" in result

    def test_top_features_at_most_5(self, calibrated_baseline):
        first = compute_stylometry(AGENT_PROSE)
        final = compute_stylometry(PROSE_SAMPLE)
        result = compare_stylometry(first, final, calibrated_baseline)
        assert len(result["top_features"]) <= 5

    def test_top_features_have_required_keys(self, calibrated_baseline):
        first = compute_stylometry(AGENT_PROSE)
        final = compute_stylometry(PROSE_SAMPLE)
        result = compare_stylometry(first, final, calibrated_baseline)
        for feat in result["top_features"]:
            assert "feature" in feat
            assert "first_value" in feat
            assert "final_value" in feat
            assert "baseline_value" in feat
            assert "direction" in feat

    def test_summary_is_string(self, calibrated_baseline):
        first = compute_stylometry(AGENT_PROSE)
        final = compute_stylometry(PROSE_SAMPLE)
        result = compare_stylometry(first, final, calibrated_baseline)
        assert isinstance(result["summary"], str)

    def test_identical_first_and_final(self, calibrated_baseline):
        """When first == final, top_features should be empty."""
        metrics = compute_stylometry(PROSE_SAMPLE)
        result = compare_stylometry(metrics, metrics, calibrated_baseline)
        assert result["top_features"] == []
        # Delta should be the same for both
        if result["first_delta"] is not None and result["final_delta"] is not None:
            assert abs(result["first_delta"] - result["final_delta"]) < 1e-9

    def test_empty_baseline_returns_none_deltas(self):
        first = compute_stylometry(PROSE_SAMPLE)
        final = compute_stylometry(PROSE_SAMPLE)
        result = compare_stylometry(first, final, {})
        assert result["first_delta"] is None
        assert result["final_delta"] is None


# ---------------------------------------------------------------------------
# update_profile_stylometry
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not NUMPY_AVAILABLE, reason="numpy required")
class TestUpdateProfileStylometry:

    @pytest.fixture
    def profile_with_stylometry(self, calibrated_baseline):
        return {"stylometry": calibrated_baseline, "profile": {"name": "Test"}}

    def test_increments_revision_count(self, profile_with_stylometry):
        first = compute_stylometry(AGENT_PROSE)
        final = compute_stylometry(PROSE_SAMPLE)
        updated = update_profile_stylometry(profile_with_stylometry, first, final)
        assert updated["stylometry"]["revision_count"] == 1

    def test_increments_again_on_second_call(self, profile_with_stylometry):
        first = compute_stylometry(AGENT_PROSE)
        final = compute_stylometry(PROSE_SAMPLE)
        once = update_profile_stylometry(profile_with_stylometry, first, final)
        twice = update_profile_stylometry(once, first, final)
        assert twice["stylometry"]["revision_count"] == 2

    def test_does_not_mutate_input(self, profile_with_stylometry):
        original_count = profile_with_stylometry["stylometry"]["revision_count"]
        first = compute_stylometry(AGENT_PROSE)
        final = compute_stylometry(PROSE_SAMPLE)
        update_profile_stylometry(profile_with_stylometry, first, final)
        assert profile_with_stylometry["stylometry"]["revision_count"] == original_count

    def test_updates_punctuation_ratios(self, profile_with_stylometry):
        first = compute_stylometry(AGENT_PROSE)
        # Build final with guaranteed semicolons
        final_text = "A; B. C; D. E; F. G; H. I; J."
        final = compute_stylometry(final_text)
        updated = update_profile_stylometry(profile_with_stylometry, first, final)
        # Semicolon rate in final should pull baseline toward it
        old_semi = profile_with_stylometry["stylometry"]["punctuation_ratios"]["semicolon"]
        new_semi = updated["stylometry"]["punctuation_ratios"]["semicolon"]
        final_semi = final["punctuation_ratios"]["semicolon"]
        if final_semi != old_semi:
            # Should have moved toward final (EMA shift)
            assert (new_semi - old_semi) * (final_semi - old_semi) >= 0

    def test_returns_profile_unchanged_when_no_stylometry(self):
        profile = {"profile": {"name": "No Stylometry"}}
        first = compute_stylometry(PROSE_SAMPLE)
        final = compute_stylometry(PROSE_SAMPLE)
        updated = update_profile_stylometry(profile, first, final)
        assert "stylometry" not in updated

    def test_first_revision_alpha_is_large(self, profile_with_stylometry):
        """On first revision (count=0), alpha = 1/(0+2) = 0.5. Changes should be noticeable."""
        old_sent = profile_with_stylometry["stylometry"]["sentence_distribution"]["mean"]
        # Build final with very different sentence length
        final_text = "This is a very long sentence that has many many words in it. " * 10
        final = compute_stylometry(final_text)
        updated = update_profile_stylometry(profile_with_stylometry, compute_stylometry(PROSE_SAMPLE), final)
        new_sent = updated["stylometry"]["sentence_distribution"]["mean"]
        final_mean = final["sentence_distribution"]["mean"]
        if abs(final_mean - old_sent) > 1:
            # The mean should have moved toward final
            assert (new_sent - old_sent) * (final_mean - old_sent) > 0

    def test_style_notes_updated_on_first_revision(self, profile_with_stylometry):
        first = compute_stylometry(AGENT_PROSE)
        final = compute_stylometry(PROSE_SAMPLE)
        updated = update_profile_stylometry(profile_with_stylometry, first, final)
        # revision_count goes to 1, which triggers style_notes regeneration
        assert isinstance(updated["stylometry"]["style_notes"], str)
        assert len(updated["stylometry"]["style_notes"]) > 0


# ---------------------------------------------------------------------------
# generate_style_notes
# ---------------------------------------------------------------------------

class TestGenerateStyleNotes:

    def test_returns_nonempty_string(self):
        data = {
            "sentence_distribution": {"mean": 18.5, "stdev": 9.2, "skew": 0.8},
            "punctuation_ratios": {"semicolon": 0.06, "colon": 0.02,
                                   "paren": 0.05, "question": 0.04, "emdash": 0.03},
            "vocabulary_richness": {"ttr": 0.52, "mattr": 0.72, "yules_k": 125},
            "function_words": ["the", "is", "of", "and", "in"],
            "corpus_mean": {},
            "revision_count": 0,
            "calibration_word_count": 5000,
        }
        notes = generate_style_notes(data)
        assert isinstance(notes, str)
        assert len(notes) > 0

    def test_mentions_sentence_length(self):
        data = {
            "sentence_distribution": {"mean": 18.5, "stdev": 9.2, "skew": 0.8},
            "punctuation_ratios": {"semicolon": 0.0, "colon": 0.0,
                                   "paren": 0.0, "question": 0.0, "emdash": 0.0},
            "vocabulary_richness": {"ttr": 0.52, "mattr": 0.72, "yules_k": 125},
            "function_words": [],
            "revision_count": 0,
            "calibration_word_count": 5000,
        }
        notes = generate_style_notes(data)
        assert "18.5" in notes or "sentence" in notes.lower()

    def test_mentions_semicolons_when_frequent(self):
        data = {
            "sentence_distribution": {"mean": 15.0, "stdev": 5.0, "skew": 0.0},
            "punctuation_ratios": {"semicolon": 0.1, "colon": 0.0,
                                   "paren": 0.0, "question": 0.0, "emdash": 0.0},
            "vocabulary_richness": {"ttr": 0.5, "mattr": 0.7, "yules_k": 100},
            "function_words": [],
            "revision_count": 0,
            "calibration_word_count": 5000,
        }
        notes = generate_style_notes(data)
        assert "semicolon" in notes.lower()

    def test_notes_limited_corpus_when_small(self):
        data = {
            "sentence_distribution": {"mean": 10.0, "stdev": 3.0, "skew": 0.0},
            "punctuation_ratios": {"semicolon": 0.0, "colon": 0.0,
                                   "paren": 0.0, "question": 0.0, "emdash": 0.0},
            "vocabulary_richness": {"ttr": 0.8, "mattr": 0.9, "yules_k": 50},
            "function_words": [],
            "revision_count": 0,
            "calibration_word_count": 500,  # below MIN_WORDS_RELIABLE
        }
        notes = generate_style_notes(data)
        assert "limited" in notes.lower() or "unreliable" in notes.lower()

    def test_handles_missing_keys_gracefully(self):
        # Should not raise on minimal or empty data
        notes = generate_style_notes({})
        assert isinstance(notes, str)

    def test_mentions_revision_count_when_updated(self):
        data = {
            "sentence_distribution": {"mean": 18.0, "stdev": 8.0, "skew": 0.0},
            "punctuation_ratios": {"semicolon": 0.03, "colon": 0.01,
                                   "paren": 0.02, "question": 0.01, "emdash": 0.02},
            "vocabulary_richness": {"ttr": 0.5, "mattr": 0.7, "yules_k": 100},
            "function_words": ["the", "a"],
            "revision_count": 5,
            "calibration_word_count": 8000,
        }
        notes = generate_style_notes(data)
        assert "5" in notes
