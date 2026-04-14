"""
Tests for voice-check perplexity module.

Covers: compute_perplexity, calibrate_perplexity, compare_perplexity,
update_profile_perplexity, and generate_perplexity_notes.

MLX-dependent tests are gated behind skipif decorators or use monkeypatching
so the suite runs cleanly in environments without MLX.
"""

import os
import sys
import math
import tempfile

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from perplexity import (
    compute_perplexity,
    calibrate_perplexity,
    compare_perplexity,
    update_profile_perplexity,
    generate_perplexity_notes,
    _get_sentences,
    MLX_AVAILABLE,
    DEFAULT_MODEL,
    MIN_SENTENCES_RELIABLE,
)


# ---------------------------------------------------------------------------
# Sample texts (copied from test_stylometry to keep modules independent)
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


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_model(monkeypatch):
    """Mock _get_model to return (None, None) — prevents any real model load."""
    monkeypatch.setattr("perplexity._get_model", lambda name=None: (None, None))


@pytest.fixture
def mock_perplexity(monkeypatch):
    """
    Mock _compute_single_perplexity to return deterministic values.
    Returns 20.0 + 1.5 * word_count — varies with sentence length,
    giving a stable, predictable distribution for testing.
    """
    def fake_perplexity(text, model, tokenizer):
        words = len(text.split())
        return 20.0 + words * 1.5

    monkeypatch.setattr("perplexity._compute_single_perplexity", fake_perplexity)


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
        encoding="utf-8",
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
        encoding="utf-8",
    )
    return [str(s1), str(s2)]


@pytest.fixture
def small_corpus_file(tmp_path):
    """Very short sample — triggers small corpus warning."""
    s = tmp_path / "short.md"
    s.write_text(
        "I built this. It works. The design was intentional. "
        "Short corpus for testing the warning path.",
        encoding="utf-8",
    )
    return [str(s)]


@pytest.fixture
def calibrated_baseline():
    """
    A pre-built perplexity baseline dict for use in comparison/update tests.
    Built directly (no model needed) so pure-logic tests don't require MLX.
    """
    return {
        "model": DEFAULT_MODEL,
        "baseline_mean": 45.2,
        "baseline_stdev": 23.1,
        "baseline_variance": 533.61,
        "baseline_cv": 0.511,
        "calibration_sentence_count": 30,
        "distance_threshold": 91.4,
        "style_notes": "Moderate unpredictability.",
        "revision_count": 0,
        "enabled": True,
    }


@pytest.fixture
def profile_with_perplexity(calibrated_baseline):
    """Full profile dict containing a perplexity section."""
    return {"perplexity": calibrated_baseline, "profile": {"name": "Test"}}


# ---------------------------------------------------------------------------
# TestComputePerplexity
# ---------------------------------------------------------------------------

class TestComputePerplexity:
    """
    Tests for compute_perplexity(). MLX-dependent path tested via mocks so the
    suite runs without a GPU. Real-MLX path gated behind skipif.
    """

    def test_returns_required_keys(self, mock_model, mock_perplexity):
        result = compute_perplexity(PROSE_SAMPLE)
        assert "sentence_perplexities" in result
        assert "mean" in result
        assert "stdev" in result
        assert "variance" in result
        assert "cv" in result
        assert "sentence_count" in result
        assert "model" in result

    def test_sentence_count_matches_split(self, mock_model, mock_perplexity):
        sentences = _get_sentences(PROSE_SAMPLE)
        result = compute_perplexity(PROSE_SAMPLE)
        assert result["sentence_count"] == len(sentences)

    def test_sentence_perplexities_length_matches_count(self, mock_model, mock_perplexity):
        result = compute_perplexity(PROSE_SAMPLE)
        assert len(result["sentence_perplexities"]) == result["sentence_count"]

    def test_mean_is_positive(self, mock_model, mock_perplexity):
        result = compute_perplexity(PROSE_SAMPLE)
        assert result["mean"] > 0

    def test_cv_equals_stdev_over_mean(self, mock_model, mock_perplexity):
        result = compute_perplexity(LONGER_PROSE)
        if result["mean"] > 0:
            expected_cv = result["stdev"] / result["mean"]
            assert abs(result["cv"] - expected_cv) < 1e-3

    def test_variance_equals_stdev_squared(self, mock_model, mock_perplexity):
        result = compute_perplexity(LONGER_PROSE)
        if not math.isnan(result["stdev"]):
            expected_var = result["stdev"] ** 2
            assert abs(result["variance"] - expected_var) < 1e-2

    def test_model_field_is_string(self, mock_model, mock_perplexity):
        result = compute_perplexity(PROSE_SAMPLE)
        assert isinstance(result["model"], str)
        assert len(result["model"]) > 0

    def test_model_override_recorded(self, monkeypatch):
        """Custom model_name should appear in the result."""
        monkeypatch.setattr("perplexity._get_model", lambda name=None: (None, None))
        monkeypatch.setattr(
            "perplexity._compute_single_perplexity",
            lambda text, m, t: 30.0,
        )
        result = compute_perplexity(PROSE_SAMPLE, model_name="custom/model-name")
        assert result["model"] == "custom/model-name"

    def test_empty_text_returns_nan_mean(self, mock_model, monkeypatch):
        """Empty text produces no sentences; mean should be nan or result is minimal."""
        monkeypatch.setattr(
            "perplexity._compute_single_perplexity",
            lambda text, m, t: float("nan"),
        )
        result = compute_perplexity("")
        # Empty text → 0 sentences or all-nan → mean is nan
        assert result["sentence_count"] == 0 or math.isnan(result["mean"])

    def test_all_nan_perplexities_returns_nan_mean(self, mock_model, monkeypatch):
        """When every sentence fails scoring, mean should be nan."""
        monkeypatch.setattr(
            "perplexity._compute_single_perplexity",
            lambda text, m, t: float("nan"),
        )
        result = compute_perplexity(PROSE_SAMPLE)
        assert math.isnan(result["mean"])

    def test_returns_empty_dict_when_mlx_unavailable(self, monkeypatch):
        """Without MLX the function should return {} and print a warning."""
        monkeypatch.setattr("perplexity.MLX_AVAILABLE", False)
        result = compute_perplexity(PROSE_SAMPLE)
        assert result == {}

    @pytest.mark.skipif(not MLX_AVAILABLE, reason="MLX not installed")
    def test_real_mlx_returns_required_keys(self):
        """Integration smoke-test: real model, real forward pass."""
        result = compute_perplexity(PROSE_SAMPLE)
        assert "mean" in result
        assert result["mean"] > 0


# ---------------------------------------------------------------------------
# TestCalibratePerplexity
# ---------------------------------------------------------------------------

class TestCalibratePerplexity:

    def test_produces_all_required_keys(
        self, two_sample_files, mock_model, mock_perplexity
    ):
        result = calibrate_perplexity(two_sample_files, verbose=False)
        for key in (
            "model",
            "baseline_mean",
            "baseline_stdev",
            "baseline_variance",
            "baseline_cv",
            "calibration_sentence_count",
            "distance_threshold",
            "style_notes",
            "revision_count",
            "enabled",
        ):
            assert key in result, f"Missing key: {key}"

    def test_revision_count_starts_at_zero(
        self, two_sample_files, mock_model, mock_perplexity
    ):
        result = calibrate_perplexity(two_sample_files, verbose=False)
        assert result["revision_count"] == 0

    def test_enabled_true_after_calibration(
        self, two_sample_files, mock_model, mock_perplexity
    ):
        result = calibrate_perplexity(two_sample_files, verbose=False)
        assert result["enabled"] is True

    def test_style_notes_nonempty(
        self, two_sample_files, mock_model, mock_perplexity
    ):
        result = calibrate_perplexity(two_sample_files, verbose=False)
        assert isinstance(result["style_notes"], str)
        assert len(result["style_notes"]) > 0

    def test_distance_threshold_positive(
        self, two_sample_files, mock_model, mock_perplexity
    ):
        result = calibrate_perplexity(two_sample_files, verbose=False)
        assert result["distance_threshold"] > 0

    def test_calibration_sentence_count_recorded(
        self, two_sample_files, mock_model, mock_perplexity
    ):
        result = calibrate_perplexity(two_sample_files, verbose=False)
        assert result["calibration_sentence_count"] > 0

    def test_empty_sample_list_returns_empty_dict(self, mock_model, mock_perplexity):
        result = calibrate_perplexity([], verbose=False)
        assert result == {}

    def test_returns_empty_dict_when_mlx_unavailable(
        self, two_sample_files, monkeypatch
    ):
        monkeypatch.setattr("perplexity.MLX_AVAILABLE", False)
        result = calibrate_perplexity(two_sample_files, verbose=False)
        assert result == {}

    def test_small_corpus_warns(
        self, small_corpus_file, mock_model, mock_perplexity, capsys
    ):
        """
        Small corpus file has fewer than MIN_SENTENCES_RELIABLE sentences;
        calibrate_perplexity should emit a WARNING to stderr.
        """
        calibrate_perplexity(small_corpus_file, verbose=True)
        captured = capsys.readouterr()
        assert "WARNING" in captured.err

    def test_small_corpus_threshold_loosened(
        self, small_corpus_file, mock_model, monkeypatch
    ):
        """
        When sentence count < MIN_SENTENCES_RELIABLE the threshold is
        multiplied by 1.5. Verify by comparing against what the threshold
        would be without the correction.
        """
        call_count = {"n": 0}

        def fake_perplexity(text, model, tokenizer):
            call_count["n"] += 1
            words = len(text.split())
            return 20.0 + words * 1.5

        monkeypatch.setattr("perplexity._compute_single_perplexity", fake_perplexity)

        result = calibrate_perplexity(small_corpus_file, verbose=False)
        n = result["calibration_sentence_count"]
        assert n < MIN_SENTENCES_RELIABLE

        mean = result["baseline_mean"]
        stdev = result["baseline_stdev"]
        tight_threshold = mean + 2.0 * stdev
        assert result["distance_threshold"] == pytest.approx(tight_threshold * 1.5, rel=1e-3)

    def test_unreadable_file_skipped(
        self, two_sample_files, mock_model, mock_perplexity
    ):
        """A nonexistent path should be skipped; remaining files still processed."""
        paths = two_sample_files + ["/nonexistent/missing_file.md"]
        result = calibrate_perplexity(paths, verbose=False)
        assert result != {}
        assert result["calibration_sentence_count"] > 0

    def test_distance_threshold_equals_mean_plus_two_stdev_for_large_corpus(
        self, two_sample_files, mock_model, mock_perplexity
    ):
        """
        For a corpus >= MIN_SENTENCES_RELIABLE, threshold should be
        mean + 2 * stdev (no 1.5× correction).
        """
        # Build a big-enough corpus by tripling each file's content
        import pathlib
        for path in two_sample_files:
            content = pathlib.Path(path).read_text(encoding="utf-8")
            pathlib.Path(path).write_text(content * 5, encoding="utf-8")

        result = calibrate_perplexity(two_sample_files, verbose=False)
        n = result["calibration_sentence_count"]
        if n >= MIN_SENTENCES_RELIABLE:
            mean = result["baseline_mean"]
            stdev = result["baseline_stdev"]
            expected = mean + 2.0 * stdev
            assert result["distance_threshold"] == pytest.approx(expected, rel=1e-3)


# ---------------------------------------------------------------------------
# TestComparePerplexity
# ---------------------------------------------------------------------------

class TestComparePerplexity:
    """Pure logic — no MLX dependency."""

    def _make_metrics(self, mean, stdev, cv):
        variance = stdev ** 2
        sentences = [mean] * 5  # fake sentence list
        return {
            "sentence_perplexities": sentences,
            "mean": mean,
            "stdev": stdev,
            "variance": variance,
            "cv": cv,
            "sentence_count": 5,
            "model": DEFAULT_MODEL,
        }

    def test_returns_required_keys(self, calibrated_baseline):
        first = self._make_metrics(60.0, 30.0, 0.5)
        final = self._make_metrics(48.0, 24.5, 0.51)
        result = compare_perplexity(first, final, calibrated_baseline)
        for key in (
            "first_mean", "final_mean", "baseline_mean",
            "first_cv", "final_cv", "baseline_cv",
            "improved", "summary",
        ):
            assert key in result, f"Missing key: {key}"

    def test_summary_is_string(self, calibrated_baseline):
        first = self._make_metrics(60.0, 30.0, 0.5)
        final = self._make_metrics(48.0, 24.5, 0.51)
        result = compare_perplexity(first, final, calibrated_baseline)
        assert isinstance(result["summary"], str)

    def test_improved_true_when_final_closer(self, calibrated_baseline):
        """
        baseline_mean=45.2, baseline_cv=0.511
        first is further away; final is closer in both dimensions.
        """
        first = self._make_metrics(70.0, 35.0, 0.8)
        final = self._make_metrics(46.0, 23.5, 0.52)
        result = compare_perplexity(first, final, calibrated_baseline)
        assert result["improved"] is True

    def test_improved_false_when_final_further(self, calibrated_baseline):
        """Final draft diverges further from baseline than first."""
        first = self._make_metrics(46.0, 23.5, 0.52)
        final = self._make_metrics(15.0, 3.0, 0.2)
        result = compare_perplexity(first, final, calibrated_baseline)
        assert result["improved"] is False

    def test_identical_first_and_final(self, calibrated_baseline):
        """Identical drafts: improved depends on distance from baseline."""
        metrics = self._make_metrics(45.2, 23.1, 0.511)
        result = compare_perplexity(metrics, metrics, calibrated_baseline)
        # first_mean == final_mean → distances equal → improved True
        assert result["improved"] is True

    def test_nan_inputs_improved_is_false(self):
        """Nan in either metrics set should not raise and improved should be False."""
        baseline = {"baseline_mean": 45.0, "baseline_cv": 0.5}
        first = {"mean": float("nan"), "cv": float("nan")}
        final = {"mean": float("nan"), "cv": float("nan")}
        result = compare_perplexity(first, final, baseline)
        assert result["improved"] is False

    def test_empty_baseline_produces_none_means(self):
        first = self._make_metrics(45.0, 20.0, 0.44)
        final = self._make_metrics(45.0, 20.0, 0.44)
        result = compare_perplexity(first, final, {})
        assert result["baseline_mean"] is None
        assert result["baseline_cv"] is None

    def test_values_rounded_to_4dp(self, calibrated_baseline):
        first = self._make_metrics(45.12345678, 22.9876543, 0.50987654)
        final = self._make_metrics(45.12345678, 22.9876543, 0.50987654)
        result = compare_perplexity(first, final, calibrated_baseline)
        for key in ("first_mean", "final_mean", "first_cv", "final_cv"):
            if result[key] is not None:
                # Must be representable with 4 decimal places
                assert round(result[key], 4) == result[key]


# ---------------------------------------------------------------------------
# TestUpdateProfilePerplexity
# ---------------------------------------------------------------------------

class TestUpdateProfilePerplexity:
    """Pure logic — no MLX dependency."""

    def _make_metrics(self, mean, stdev, cv):
        variance = stdev ** 2
        return {
            "sentence_perplexities": [],
            "mean": mean,
            "stdev": stdev,
            "variance": variance,
            "cv": cv,
            "sentence_count": 10,
            "model": DEFAULT_MODEL,
        }

    def test_increments_revision_count(self, profile_with_perplexity):
        first = self._make_metrics(60.0, 28.0, 0.47)
        final = self._make_metrics(46.0, 23.5, 0.51)
        updated = update_profile_perplexity(profile_with_perplexity, first, final)
        assert updated["perplexity"]["revision_count"] == 1

    def test_increments_again_on_second_call(self, profile_with_perplexity):
        first = self._make_metrics(60.0, 28.0, 0.47)
        final = self._make_metrics(46.0, 23.5, 0.51)
        once = update_profile_perplexity(profile_with_perplexity, first, final)
        twice = update_profile_perplexity(once, first, final)
        assert twice["perplexity"]["revision_count"] == 2

    def test_does_not_mutate_input(self, profile_with_perplexity):
        original_count = profile_with_perplexity["perplexity"]["revision_count"]
        original_mean = profile_with_perplexity["perplexity"]["baseline_mean"]
        first = self._make_metrics(60.0, 28.0, 0.47)
        final = self._make_metrics(46.0, 23.5, 0.51)
        update_profile_perplexity(profile_with_perplexity, first, final)
        assert profile_with_perplexity["perplexity"]["revision_count"] == original_count
        assert profile_with_perplexity["perplexity"]["baseline_mean"] == original_mean

    def test_ema_moves_toward_final(self, profile_with_perplexity):
        """After one update (alpha=0.5), baseline_mean should move halfway toward final."""
        old_mean = profile_with_perplexity["perplexity"]["baseline_mean"]  # 45.2
        final_mean = 80.0
        first = self._make_metrics(60.0, 28.0, 0.47)
        final = self._make_metrics(final_mean, 25.0, 0.5)
        updated = update_profile_perplexity(profile_with_perplexity, first, final)
        new_mean = updated["perplexity"]["baseline_mean"]
        # Direction: should move toward final
        assert (new_mean - old_mean) * (final_mean - old_mean) > 0

    def test_returns_unchanged_when_no_perplexity_section(self):
        profile = {"profile": {"name": "No Perplexity"}}
        first = self._make_metrics(60.0, 28.0, 0.47)
        final = self._make_metrics(46.0, 23.5, 0.51)
        updated = update_profile_perplexity(profile, first, final)
        assert "perplexity" not in updated

    def test_style_notes_updated_on_first_revision(self, profile_with_perplexity):
        first = self._make_metrics(60.0, 28.0, 0.47)
        final = self._make_metrics(46.0, 23.5, 0.51)
        updated = update_profile_perplexity(profile_with_perplexity, first, final)
        # revision_count becomes 1 → style_notes should regenerate
        assert isinstance(updated["perplexity"]["style_notes"], str)
        assert len(updated["perplexity"]["style_notes"]) > 0

    def test_style_notes_updated_on_third_revision(self, profile_with_perplexity):
        """Style notes regenerate at revision counts 1, 3, 6, 9, ..."""
        first = self._make_metrics(60.0, 28.0, 0.47)
        final = self._make_metrics(46.0, 23.5, 0.51)
        p = profile_with_perplexity
        # Advance to revision 3 manually
        for _ in range(3):
            p = update_profile_perplexity(p, first, final)
        assert p["perplexity"]["revision_count"] == 3
        assert isinstance(p["perplexity"]["style_notes"], str)

    def test_nan_final_does_not_overwrite_valid_baseline(self, profile_with_perplexity):
        """If final metrics contain NaN, the EMA should preserve the old value."""
        old_mean = profile_with_perplexity["perplexity"]["baseline_mean"]
        first = self._make_metrics(60.0, 28.0, 0.47)
        final = self._make_metrics(float("nan"), float("nan"), float("nan"))
        updated = update_profile_perplexity(profile_with_perplexity, first, final)
        assert updated["perplexity"]["baseline_mean"] == old_mean

    def test_alpha_schedule_first_revision(self, profile_with_perplexity):
        """
        revision_count=0 → alpha = max(0.2, 1/(0+2)) = 0.5.
        baseline_mean should move 50% of the way toward final_mean.
        """
        old_mean = profile_with_perplexity["perplexity"]["baseline_mean"]  # 45.2
        final_mean = 100.0
        first = self._make_metrics(60.0, 28.0, 0.47)
        final = self._make_metrics(final_mean, 25.0, 0.5)
        updated = update_profile_perplexity(profile_with_perplexity, first, final)
        new_mean = updated["perplexity"]["baseline_mean"]
        expected = 0.5 * final_mean + 0.5 * old_mean
        assert abs(new_mean - expected) < 0.01


# ---------------------------------------------------------------------------
# TestGeneratePerplexityNotes
# ---------------------------------------------------------------------------

class TestGeneratePerplexityNotes:
    """Pure logic — no MLX dependency."""

    def _base_data(self, **overrides):
        base = {
            "model": DEFAULT_MODEL,
            "baseline_mean": 45.2,
            "baseline_stdev": 23.1,
            "baseline_variance": 533.61,
            "baseline_cv": 0.511,
            "calibration_sentence_count": 30,
            "distance_threshold": 91.4,
            "revision_count": 0,
            "enabled": True,
        }
        base.update(overrides)
        return base

    def test_returns_nonempty_string(self):
        notes = generate_perplexity_notes(self._base_data())
        assert isinstance(notes, str)
        assert len(notes) > 0

    def test_mentions_predictability_or_perplexity(self):
        notes = generate_perplexity_notes(self._base_data())
        assert "perplexity" in notes.lower() or "predictab" in notes.lower()

    def test_mentions_mean_value(self):
        notes = generate_perplexity_notes(self._base_data(baseline_mean=45.2))
        assert "45.2" in notes

    def test_mentions_cv_value(self):
        notes = generate_perplexity_notes(self._base_data(baseline_cv=0.511))
        assert "0.51" in notes

    def test_high_perplexity_label(self):
        notes = generate_perplexity_notes(self._base_data(baseline_mean=120.0))
        assert "high unpredictability" in notes.lower() or "unconventional" in notes.lower()

    def test_low_perplexity_label(self):
        notes = generate_perplexity_notes(self._base_data(baseline_mean=15.0))
        assert "low unpredictability" in notes.lower() or "predictab" in notes.lower()

    def test_high_cv_guidance(self):
        notes = generate_perplexity_notes(self._base_data(baseline_cv=0.7))
        # High CV should mention variation
        assert "variation" in notes.lower() or "vary" in notes.lower()

    def test_low_cv_guidance(self):
        notes = generate_perplexity_notes(self._base_data(baseline_cv=0.1))
        assert "consistent" in notes.lower() or "variation" in notes.lower()

    def test_mentions_revision_count_when_updated(self):
        notes = generate_perplexity_notes(self._base_data(revision_count=5))
        assert "5" in notes

    def test_mentions_sentence_count(self):
        notes = generate_perplexity_notes(
            self._base_data(calibration_sentence_count=42)
        )
        assert "42" in notes

    def test_mentions_model(self):
        notes = generate_perplexity_notes(self._base_data(model="test/model-7b"))
        assert "test/model-7b" in notes

    def test_handles_empty_dict_gracefully(self):
        """Should not raise on completely empty input."""
        notes = generate_perplexity_notes({})
        assert isinstance(notes, str)

    def test_handles_missing_mean_gracefully(self):
        notes = generate_perplexity_notes({"baseline_cv": 0.4, "revision_count": 0})
        assert isinstance(notes, str)

    def test_handles_nan_mean_gracefully(self):
        notes = generate_perplexity_notes(self._base_data(baseline_mean=float("nan")))
        assert isinstance(notes, str)
        assert "not yet calibrated" in notes.lower()

    def test_threshold_mentioned(self):
        notes = generate_perplexity_notes(self._base_data(distance_threshold=91.4))
        assert "91.4" in notes or "threshold" in notes.lower()
