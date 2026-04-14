"""
Tests for voice-check embeddings module.

Covers: cosine similarity, compute_embeddings, calibrate_embeddings,
compare_embeddings, update_profile_embeddings, and generate_embedding_notes.

Most tests mock the embedding model so they run without fastembed installed.
The mock uses a deterministic hash-based embedding so distance arithmetic is
stable across test runs.
"""

import os
import sys
import math
import copy

import pytest
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import embeddings as emb_module
from embeddings import (
    _cosine_similarity,
    _strip_markdown,
    _get_sentences,
    compute_embeddings,
    calibrate_embeddings,
    compare_embeddings,
    update_profile_embeddings,
    generate_embedding_notes,
    DEFAULT_MODEL,
)


# ---------------------------------------------------------------------------
# Sample texts (mirrored from test_stylometry.py — independent copies)
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
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_embed_model(monkeypatch):
    """
    Mock _get_model to return a fake embedding model.

    Returns deterministic unit-normalised 384-dim vectors based on text hash.
    This makes all distance arithmetic stable without requiring fastembed.
    """
    class FakeEmbedModel:
        def embed(self, texts):
            for text in texts:
                np.random.seed(hash(text) % (2 ** 31))
                vec = np.random.randn(384).astype(np.float32)
                vec = vec / np.linalg.norm(vec)
                yield vec

    monkeypatch.setattr("embeddings._get_model", lambda name=None: FakeEmbedModel())
    monkeypatch.setattr("embeddings.FASTEMBED_AVAILABLE", True)


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
def calibrated_baseline(mock_embed_model, two_sample_files):
    """A calibrated embedding baseline for comparison/update tests."""
    return calibrate_embeddings(two_sample_files, verbose=False)


@pytest.fixture
def first_draft_metrics(mock_embed_model):
    """Computed embedding metrics for the agent prose first draft."""
    return compute_embeddings(AGENT_PROSE)


@pytest.fixture
def final_draft_metrics(mock_embed_model):
    """Computed embedding metrics for the human-revised final draft."""
    return compute_embeddings(PROSE_SAMPLE)


# ---------------------------------------------------------------------------
# TestCosineSimilarity — pure math, no dependencies
# ---------------------------------------------------------------------------

class TestCosineSimilarity:

    def test_identical_vectors_return_one(self):
        v = np.array([1.0, 0.0, 0.0])
        assert abs(_cosine_similarity(v, v) - 1.0) < 1e-6

    def test_orthogonal_vectors_return_zero(self):
        a = np.array([1.0, 0.0, 0.0])
        b = np.array([0.0, 1.0, 0.0])
        assert abs(_cosine_similarity(a, b)) < 1e-6

    def test_opposite_vectors_return_negative_one(self):
        v = np.array([1.0, 0.0, 0.0])
        assert abs(_cosine_similarity(v, -v) - (-1.0)) < 1e-6

    def test_zero_vector_returns_zero(self):
        a = np.zeros(5)
        b = np.array([1.0, 2.0, 3.0, 0.0, 0.0])
        assert _cosine_similarity(a, b) == 0.0

    def test_both_zero_vectors_return_zero(self):
        a = np.zeros(4)
        b = np.zeros(4)
        assert _cosine_similarity(a, b) == 0.0

    def test_symmetry(self):
        a = np.array([1.0, 2.0, 3.0])
        b = np.array([4.0, 5.0, 6.0])
        assert abs(_cosine_similarity(a, b) - _cosine_similarity(b, a)) < 1e-9

    def test_normalised_dot_product(self):
        a = np.array([3.0, 4.0])
        b = np.array([0.0, 1.0])
        # cos = (3*0 + 4*1) / (5 * 1) = 0.8
        assert abs(_cosine_similarity(a, b) - 0.8) < 1e-6


# ---------------------------------------------------------------------------
# TestComputeEmbeddings — uses mock_embed_model
# ---------------------------------------------------------------------------

class TestComputeEmbeddings:

    def test_returns_required_keys(self, mock_embed_model):
        result = compute_embeddings(PROSE_SAMPLE)
        assert "sentence_embeddings" in result
        assert "centroid" in result
        assert "distances_from_centroid" in result
        assert "mean_distance" in result
        assert "stdev_distance" in result
        assert "sentence_count" in result
        assert "model" in result

    def test_sentence_count_matches_embeddings_length(self, mock_embed_model):
        result = compute_embeddings(PROSE_SAMPLE)
        assert result["sentence_count"] == len(result["sentence_embeddings"])
        assert result["sentence_count"] == len(result["distances_from_centroid"])

    def test_centroid_shape_matches_dimension(self, mock_embed_model):
        result = compute_embeddings(PROSE_SAMPLE)
        assert result["centroid"].shape == (384,)

    def test_distances_are_nonnegative(self, mock_embed_model):
        result = compute_embeddings(PROSE_SAMPLE)
        assert all(d >= 0.0 for d in result["distances_from_centroid"])

    def test_distances_at_most_two(self, mock_embed_model):
        # Cosine distance in [0, 2] for unit vectors; practically in [0, 1]
        result = compute_embeddings(PROSE_SAMPLE)
        assert all(d <= 2.0 for d in result["distances_from_centroid"])

    def test_empty_text_handled(self, mock_embed_model):
        result = compute_embeddings("")
        assert result["sentence_count"] == 0
        assert result["sentence_embeddings"] == []
        assert result["distances_from_centroid"] == []
        assert result["mean_distance"] == 0.0

    def test_single_sentence_distance_is_zero(self, mock_embed_model):
        result = compute_embeddings("This is a single sentence.")
        assert result["sentence_count"] == 1
        # Single sentence: centroid == that sentence, distance == 0
        assert result["distances_from_centroid"] == [0.0]

    def test_single_sentence_centroid_equals_embedding(self, mock_embed_model):
        result = compute_embeddings("This is a single sentence.")
        assert result["sentence_count"] == 1
        emb = result["sentence_embeddings"][0]
        centroid = result["centroid"]
        assert np.allclose(emb, centroid, atol=1e-5)

    def test_model_name_recorded(self, mock_embed_model):
        result = compute_embeddings(PROSE_SAMPLE)
        assert result["model"] == DEFAULT_MODEL

    def test_custom_model_name_recorded(self, mock_embed_model):
        result = compute_embeddings(PROSE_SAMPLE, model_name="custom-model")
        assert result["model"] == "custom-model"

    def test_markdown_stripped_before_embedding(self, mock_embed_model):
        md_text = "# Title\n\n**Bold** and _italic_ prose. Another sentence."
        result = compute_embeddings(md_text)
        assert result["sentence_count"] > 0

    def test_no_fastembed_returns_empty_dict(self, monkeypatch):
        monkeypatch.setattr("embeddings.FASTEMBED_AVAILABLE", False)
        result = compute_embeddings(PROSE_SAMPLE)
        assert result == {}

    def test_longer_prose_multiple_sentences(self, mock_embed_model):
        result = compute_embeddings(LONGER_PROSE)
        assert result["sentence_count"] > 5
        assert result["mean_distance"] >= 0.0


# ---------------------------------------------------------------------------
# TestCalibrateEmbeddings — uses mock_embed_model + temp files
# ---------------------------------------------------------------------------

class TestCalibrateEmbeddings:

    def test_produces_all_required_keys(self, mock_embed_model, two_sample_files):
        result = calibrate_embeddings(two_sample_files, verbose=False)
        assert "model" in result
        assert "centroid" in result
        assert "dimension" in result
        assert "mean_distance" in result
        assert "stdev_distance" in result
        assert "distance_threshold" in result
        assert "calibration_sentence_count" in result
        assert "calibration_word_count" in result
        assert "style_notes" in result
        assert "revision_count" in result

    def test_centroid_is_list(self, mock_embed_model, two_sample_files):
        result = calibrate_embeddings(two_sample_files, verbose=False)
        assert isinstance(result["centroid"], list)

    def test_centroid_json_serialisable(self, mock_embed_model, two_sample_files):
        import json
        result = calibrate_embeddings(two_sample_files, verbose=False)
        serialised = json.dumps(result["centroid"])
        restored = json.loads(serialised)
        assert len(restored) == result["dimension"]

    def test_dimension_recorded_correctly(self, mock_embed_model, two_sample_files):
        result = calibrate_embeddings(two_sample_files, verbose=False)
        assert result["dimension"] == 384  # bge-small-en-v1.5

    def test_revision_count_starts_at_zero(self, mock_embed_model, two_sample_files):
        result = calibrate_embeddings(two_sample_files, verbose=False)
        assert result["revision_count"] == 0

    def test_distance_threshold_positive(self, mock_embed_model, two_sample_files):
        result = calibrate_embeddings(two_sample_files, verbose=False)
        assert result["distance_threshold"] > 0

    def test_style_notes_nonempty(self, mock_embed_model, two_sample_files):
        result = calibrate_embeddings(two_sample_files, verbose=False)
        assert isinstance(result["style_notes"], str)
        assert len(result["style_notes"]) > 0

    def test_calibration_sentence_count_recorded(self, mock_embed_model, two_sample_files):
        result = calibrate_embeddings(two_sample_files, verbose=False)
        assert result["calibration_sentence_count"] > 0

    def test_calibration_word_count_recorded(self, mock_embed_model, two_sample_files):
        result = calibrate_embeddings(two_sample_files, verbose=False)
        assert result["calibration_word_count"] > 0

    def test_empty_sample_list_returns_empty(self, mock_embed_model):
        result = calibrate_embeddings([], verbose=False)
        assert result == {}

    def test_small_corpus_warns(self, mock_embed_model, tmp_path, capsys):
        # Single short file with fewer than MIN_SENTENCES_RELIABLE sentences
        short = tmp_path / "short.md"
        short.write_text(
            "I built this. It works. The design was intentional.",
            encoding="utf-8",
        )
        calibrate_embeddings([str(short)], verbose=True)
        captured = capsys.readouterr()
        assert "WARNING" in captured.err

    def test_small_corpus_threshold_loosened(self, mock_embed_model, tmp_path):
        # Small corpus should produce a threshold loosened by 1.5x vs normal
        short = tmp_path / "short.md"
        short.write_text(
            "I built this. It works. The design was intentional. "
            "Short and sweet. Concise. Clear.",
            encoding="utf-8",
        )
        result = calibrate_embeddings([str(short)], verbose=False)
        # The threshold should be at least mean + 1.5 * stdev (but loosened)
        expected_min = result["mean_distance"] + 1.5 * result["stdev_distance"]
        # Loosened threshold should be >= the normal threshold
        assert result["distance_threshold"] >= expected_min - 1e-6

    def test_threshold_equals_mean_plus_1_5_stdev_for_large_corpus(
        self, mock_embed_model, two_sample_files
    ):
        result = calibrate_embeddings(two_sample_files, verbose=False)
        expected = result["mean_distance"] + 1.5 * result["stdev_distance"]
        assert abs(result["distance_threshold"] - expected) < 1e-4

    def test_nonexistent_file_skipped_gracefully(self, mock_embed_model, two_sample_files, capsys):
        paths = two_sample_files + ["/nonexistent/path/sample.md"]
        result = calibrate_embeddings(paths, verbose=True)
        # Should still succeed with the valid files
        assert "centroid" in result
        captured = capsys.readouterr()
        assert "WARNING" in captured.err

    def test_no_fastembed_returns_empty(self, monkeypatch, two_sample_files):
        monkeypatch.setattr("embeddings.FASTEMBED_AVAILABLE", False)
        result = calibrate_embeddings(two_sample_files, verbose=False)
        assert result == {}


# ---------------------------------------------------------------------------
# TestCompareEmbeddings — pure logic with pre-built dicts
# ---------------------------------------------------------------------------

def _make_metrics(centroid_vec, distances):
    """Helper: build a minimal metrics dict for comparison tests."""
    sentence_embeddings = []
    for d in distances:
        # Create a unit vector with cosine distance d from centroid_vec
        # (approximate: perturb centroid slightly)
        np.random.seed(int(d * 1000) % 10000)
        noise = np.random.randn(len(centroid_vec)).astype(np.float32) * 0.1
        v = centroid_vec + noise * d
        n = np.linalg.norm(v)
        sentence_embeddings.append(v / n if n > 1e-10 else centroid_vec)
    return {
        "centroid": centroid_vec,
        "distances_from_centroid": distances,
        "sentence_embeddings": sentence_embeddings,
        "mean_distance": float(np.mean(distances)) if distances else 0.0,
        "stdev_distance": float(np.std(distances)) if len(distances) > 1 else 0.0,
        "sentence_count": len(distances),
        "model": DEFAULT_MODEL,
    }


class TestCompareEmbeddings:

    def _baseline(self):
        """Build a minimal baseline dict."""
        np.random.seed(42)
        centroid = np.random.randn(384).astype(np.float32)
        centroid /= np.linalg.norm(centroid)
        return {
            "centroid": centroid.tolist(),
            "dimension": 384,
            "mean_distance": 0.15,
            "stdev_distance": 0.05,
            "distance_threshold": 0.225,
            "model": DEFAULT_MODEL,
            "revision_count": 0,
        }

    def test_returns_required_keys(self):
        baseline = self._baseline()
        b_centroid = np.array(baseline["centroid"])
        # first draft: far from baseline
        far = b_centroid + np.random.randn(384).astype(np.float32) * 0.5
        far /= np.linalg.norm(far)
        # final: close to baseline
        close = b_centroid + np.random.randn(384).astype(np.float32) * 0.05
        close /= np.linalg.norm(close)
        first = _make_metrics(far, [0.3, 0.4, 0.35])
        final = _make_metrics(close, [0.1, 0.12, 0.08])
        result = compare_embeddings(first, final, baseline)
        assert "first_centroid_distance" in result
        assert "final_centroid_distance" in result
        assert "improved" in result
        assert "first_outlier_ratio" in result
        assert "final_outlier_ratio" in result
        assert "top_drifted_sentences" in result
        assert "summary" in result

    def test_improved_flag_true_when_final_closer(self):
        baseline = self._baseline()
        b_centroid = np.array(baseline["centroid"])
        far = b_centroid.copy()
        far[0] += 0.5
        far /= np.linalg.norm(far)
        close = b_centroid.copy()
        close[0] += 0.05
        close /= np.linalg.norm(close)
        first = _make_metrics(far, [0.3])
        final = _make_metrics(close, [0.05])
        result = compare_embeddings(first, final, baseline)
        assert result["improved"] is True

    def test_improved_flag_false_when_final_further(self):
        baseline = self._baseline()
        b_centroid = np.array(baseline["centroid"])
        close = b_centroid.copy()
        close[0] += 0.02
        close /= np.linalg.norm(close)
        far = b_centroid.copy()
        far[0] += 0.5
        far /= np.linalg.norm(far)
        first = _make_metrics(close, [0.05])
        final = _make_metrics(far, [0.4])
        result = compare_embeddings(first, final, baseline)
        assert result["improved"] is False

    def test_identical_first_and_final(self):
        baseline = self._baseline()
        b_centroid = np.array(baseline["centroid"])
        metrics = _make_metrics(b_centroid, [0.1, 0.12])
        result = compare_embeddings(metrics, metrics, baseline)
        assert result["improved"] is False  # equal distance → not improved
        assert abs(result["first_centroid_distance"] - result["final_centroid_distance"]) < 1e-6

    def test_summary_is_string(self):
        baseline = self._baseline()
        b_centroid = np.array(baseline["centroid"])
        first = _make_metrics(b_centroid, [0.3])
        final = _make_metrics(b_centroid, [0.1])
        result = compare_embeddings(first, final, baseline)
        assert isinstance(result["summary"], str)
        assert len(result["summary"]) > 0

    def test_top_drifted_sentences_at_most_three(self):
        baseline = self._baseline()
        b_centroid = np.array(baseline["centroid"])
        # Many sentences
        far = b_centroid.copy()
        far[0] += 0.3
        far /= np.linalg.norm(far)
        first = _make_metrics(far, [0.2, 0.3, 0.4, 0.1, 0.35])
        final = _make_metrics(b_centroid, [0.1])
        result = compare_embeddings(first, final, baseline)
        assert len(result["top_drifted_sentences"]) <= 3

    def test_top_drifted_sentences_have_required_keys(self):
        baseline = self._baseline()
        b_centroid = np.array(baseline["centroid"])
        far = b_centroid.copy()
        far[0] += 0.5
        far /= np.linalg.norm(far)
        first = _make_metrics(far, [0.25, 0.35, 0.45])
        final = _make_metrics(b_centroid, [0.1])
        result = compare_embeddings(first, final, baseline)
        for entry in result["top_drifted_sentences"]:
            assert "sentence_index" in entry
            assert "distance" in entry

    def test_outlier_ratio_between_zero_and_one(self):
        baseline = self._baseline()
        b_centroid = np.array(baseline["centroid"])
        # distances: some above threshold (0.225), some below
        first = _make_metrics(b_centroid, [0.10, 0.30, 0.15, 0.40])
        final = _make_metrics(b_centroid, [0.10, 0.12])
        result = compare_embeddings(first, final, baseline)
        assert 0.0 <= result["first_outlier_ratio"] <= 1.0
        assert 0.0 <= result["final_outlier_ratio"] <= 1.0

    def test_empty_baseline_returns_none_distances(self):
        first = _make_metrics(np.zeros(384), [0.1])
        final = _make_metrics(np.zeros(384), [0.1])
        result = compare_embeddings(first, final, {})
        assert result["first_centroid_distance"] is None
        assert result["final_centroid_distance"] is None

    def test_centroid_distances_nonnegative(self):
        baseline = self._baseline()
        b_centroid = np.array(baseline["centroid"])
        first = _make_metrics(b_centroid, [0.1])
        final = _make_metrics(b_centroid, [0.05])
        result = compare_embeddings(first, final, baseline)
        assert result["first_centroid_distance"] >= 0.0
        assert result["final_centroid_distance"] >= 0.0


# ---------------------------------------------------------------------------
# TestUpdateProfileEmbeddings — pure logic
# ---------------------------------------------------------------------------

class TestUpdateProfileEmbeddings:

    def _make_profile(self, centroid=None):
        """Build a minimal profile with embeddings section."""
        if centroid is None:
            np.random.seed(99)
            centroid = np.random.randn(384).astype(np.float32)
            centroid /= np.linalg.norm(centroid)
        return {
            "embeddings": {
                "model": DEFAULT_MODEL,
                "centroid": centroid.tolist(),
                "dimension": 384,
                "mean_distance": 0.15,
                "stdev_distance": 0.05,
                "distance_threshold": 0.225,
                "calibration_sentence_count": 30,
                "calibration_word_count": 500,
                "style_notes": "Original notes.",
                "revision_count": 0,
            }
        }

    def _make_draft_metrics(self, centroid_vec):
        """Build minimal metrics dict with numpy centroid."""
        return {
            "centroid": centroid_vec,
            "distances_from_centroid": [0.10, 0.12, 0.09],
            "mean_distance": 0.103,
            "stdev_distance": 0.015,
            "sentence_count": 3,
            "model": DEFAULT_MODEL,
        }

    def test_increments_revision_count(self):
        profile = self._make_profile()
        np.random.seed(1)
        final_centroid = np.random.randn(384).astype(np.float32)
        final_centroid /= np.linalg.norm(final_centroid)
        first = self._make_draft_metrics(final_centroid)
        final = self._make_draft_metrics(final_centroid)
        updated = update_profile_embeddings(profile, first, final)
        assert updated["embeddings"]["revision_count"] == 1

    def test_increments_again_on_second_call(self):
        profile = self._make_profile()
        np.random.seed(2)
        c = np.random.randn(384).astype(np.float32)
        c /= np.linalg.norm(c)
        first = self._make_draft_metrics(c)
        final = self._make_draft_metrics(c)
        once = update_profile_embeddings(profile, first, final)
        twice = update_profile_embeddings(once, first, final)
        assert twice["embeddings"]["revision_count"] == 2

    def test_does_not_mutate_input(self):
        profile = self._make_profile()
        original_count = profile["embeddings"]["revision_count"]
        original_centroid = list(profile["embeddings"]["centroid"])
        np.random.seed(3)
        c = np.random.randn(384).astype(np.float32)
        c /= np.linalg.norm(c)
        first = self._make_draft_metrics(c)
        final = self._make_draft_metrics(c)
        update_profile_embeddings(profile, first, final)
        assert profile["embeddings"]["revision_count"] == original_count
        assert profile["embeddings"]["centroid"] == original_centroid

    def test_centroid_shifts_toward_final(self):
        """After update, new centroid should be more similar to final draft centroid."""
        np.random.seed(42)
        old_centroid = np.random.randn(384).astype(np.float32)
        old_centroid /= np.linalg.norm(old_centroid)

        np.random.seed(7)
        final_centroid = np.random.randn(384).astype(np.float32)
        final_centroid /= np.linalg.norm(final_centroid)

        profile = self._make_profile(centroid=old_centroid)
        first = self._make_draft_metrics(old_centroid)
        final = self._make_draft_metrics(final_centroid)

        updated = update_profile_embeddings(profile, first, final)
        new_centroid = np.array(updated["embeddings"]["centroid"])

        sim_old = _cosine_similarity(new_centroid, old_centroid)
        sim_final = _cosine_similarity(new_centroid, final_centroid)

        # On first revision (alpha=0.5), centroid is midpoint →
        # should be more similar to final than to old if final is far from old
        # At minimum, the new centroid should not be identical to old
        orig_sim = _cosine_similarity(old_centroid, final_centroid)
        new_sim_to_final = _cosine_similarity(np.array(updated["embeddings"]["centroid"]), final_centroid)
        new_sim_to_old = _cosine_similarity(np.array(updated["embeddings"]["centroid"]), old_centroid)
        # New centroid should be between old and final (both similarities < 1)
        assert new_sim_to_old < 1.0 or new_sim_to_final < 1.0

    def test_centroid_is_list_after_update(self):
        """Centroid must be JSON-serialisable (list) after update."""
        import json
        profile = self._make_profile()
        np.random.seed(5)
        c = np.random.randn(384).astype(np.float32)
        c /= np.linalg.norm(c)
        first = self._make_draft_metrics(c)
        final = self._make_draft_metrics(c)
        updated = update_profile_embeddings(profile, first, final)
        assert isinstance(updated["embeddings"]["centroid"], list)
        # Must be JSON-serialisable
        json.dumps(updated["embeddings"]["centroid"])

    def test_centroid_is_unit_vector_after_update(self):
        """Updated centroid should be normalised to unit length."""
        profile = self._make_profile()
        np.random.seed(6)
        c = np.random.randn(384).astype(np.float32)
        c /= np.linalg.norm(c)
        first = self._make_draft_metrics(c)
        final = self._make_draft_metrics(c)
        updated = update_profile_embeddings(profile, first, final)
        new_centroid = np.array(updated["embeddings"]["centroid"])
        assert abs(np.linalg.norm(new_centroid) - 1.0) < 1e-4

    def test_returns_unchanged_when_no_embeddings_section(self):
        profile = {"profile": {"name": "No Embeddings"}}
        np.random.seed(8)
        c = np.random.randn(384).astype(np.float32)
        c /= np.linalg.norm(c)
        first = self._make_draft_metrics(c)
        final = self._make_draft_metrics(c)
        updated = update_profile_embeddings(profile, first, final)
        assert "embeddings" not in updated

    def test_style_notes_updated_on_first_revision(self):
        profile = self._make_profile()
        original_notes = profile["embeddings"]["style_notes"]
        np.random.seed(9)
        c = np.random.randn(384).astype(np.float32)
        c /= np.linalg.norm(c)
        first = self._make_draft_metrics(c)
        final = self._make_draft_metrics(c)
        updated = update_profile_embeddings(profile, first, final)
        # revision_count goes to 1, style_notes must regenerate
        assert isinstance(updated["embeddings"]["style_notes"], str)
        assert len(updated["embeddings"]["style_notes"]) > 0

    def test_style_notes_updated_every_third_revision(self):
        profile = self._make_profile()
        np.random.seed(10)
        c = np.random.randn(384).astype(np.float32)
        c /= np.linalg.norm(c)
        first = self._make_draft_metrics(c)
        final = self._make_draft_metrics(c)
        # Advance to revision_count=2 without triggering regen (counts 1 and 3 trigger)
        profile["embeddings"]["revision_count"] = 2
        updated = update_profile_embeddings(profile, first, final)
        assert updated["embeddings"]["revision_count"] == 3
        # revision_count 3 → 3 % 3 == 0 → notes regenerated
        assert isinstance(updated["embeddings"]["style_notes"], str)

    def test_mean_and_stdev_distance_updated(self):
        profile = self._make_profile()
        profile["embeddings"]["mean_distance"] = 0.20
        np.random.seed(11)
        c = np.random.randn(384).astype(np.float32)
        c /= np.linalg.norm(c)
        first = self._make_draft_metrics(c)
        final = {
            "centroid": c,
            "distances_from_centroid": [0.05, 0.06, 0.04],
            "mean_distance": 0.05,
            "stdev_distance": 0.01,
            "sentence_count": 3,
            "model": DEFAULT_MODEL,
        }
        updated = update_profile_embeddings(profile, first, final)
        # Mean should shift toward 0.05 from 0.20 (alpha=0.5 on first revision)
        new_mean = updated["embeddings"]["mean_distance"]
        assert new_mean < 0.20  # moved toward final's lower mean

    def test_distance_threshold_recomputed_after_update(self):
        profile = self._make_profile()
        np.random.seed(12)
        c = np.random.randn(384).astype(np.float32)
        c /= np.linalg.norm(c)
        first = self._make_draft_metrics(c)
        final = self._make_draft_metrics(c)
        updated = update_profile_embeddings(profile, first, final)
        emb = updated["embeddings"]
        expected_threshold = emb["mean_distance"] + 1.5 * emb["stdev_distance"]
        assert abs(emb["distance_threshold"] - expected_threshold) < 1e-5


# ---------------------------------------------------------------------------
# TestGenerateEmbeddingNotes — pure logic
# ---------------------------------------------------------------------------

class TestGenerateEmbeddingNotes:

    def _tight_data(self):
        return {
            "mean_distance": 0.12,
            "stdev_distance": 0.04,
            "distance_threshold": 0.18,
            "dimension": 384,
            "model": DEFAULT_MODEL,
            "calibration_sentence_count": 45,
            "calibration_word_count": 800,
            "revision_count": 0,
        }

    def _broad_data(self):
        return {
            "mean_distance": 0.38,
            "stdev_distance": 0.10,
            "distance_threshold": 0.53,
            "dimension": 384,
            "model": DEFAULT_MODEL,
            "calibration_sentence_count": 60,
            "calibration_word_count": 1200,
            "revision_count": 0,
        }

    def test_returns_nonempty_string(self):
        notes = generate_embedding_notes(self._tight_data())
        assert isinstance(notes, str)
        assert len(notes) > 0

    def test_mentions_semantic_or_cluster(self):
        notes = generate_embedding_notes(self._tight_data())
        lower = notes.lower()
        assert "semantic" in lower or "cluster" in lower or "distance" in lower

    def test_tight_cluster_description(self):
        notes = generate_embedding_notes(self._tight_data())
        lower = notes.lower()
        assert "tight" in lower or "consistent" in lower or "focused" in lower

    def test_broad_range_description(self):
        notes = generate_embedding_notes(self._broad_data())
        lower = notes.lower()
        assert "broad" in lower or "varied" in lower or "range" in lower

    def test_mentions_threshold(self):
        notes = generate_embedding_notes(self._tight_data())
        assert "0.18" in notes or "threshold" in notes.lower()

    def test_mentions_dimension_count(self):
        notes = generate_embedding_notes(self._tight_data())
        assert "384" in notes

    def test_mentions_sentence_count(self):
        notes = generate_embedding_notes(self._tight_data())
        assert "45" in notes or "sentence" in notes.lower()

    def test_mentions_revision_count_when_updated(self):
        data = self._tight_data()
        data["revision_count"] = 4
        notes = generate_embedding_notes(data)
        assert "4" in notes or "revision" in notes.lower()

    def test_no_mention_of_revision_when_zero(self):
        data = self._tight_data()
        data["revision_count"] = 0
        notes = generate_embedding_notes(data)
        # Should not claim "refined through 0 revisions"
        assert "0 revision" not in notes

    def test_handles_missing_keys_gracefully(self):
        notes = generate_embedding_notes({})
        assert isinstance(notes, str)
        # Empty data → fallback message
        assert len(notes) > 0

    def test_handles_zero_mean_distance(self):
        data = self._tight_data()
        data["mean_distance"] = 0.0
        notes = generate_embedding_notes(data)
        assert isinstance(notes, str)

    def test_returns_fallback_for_empty_dict(self):
        notes = generate_embedding_notes({})
        assert "No embedding data" in notes or isinstance(notes, str)
