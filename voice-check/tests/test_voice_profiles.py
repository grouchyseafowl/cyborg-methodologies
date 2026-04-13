"""
Tests for the voice profile system in writing_check.py.

Covers: profile loading, profile application, calibration output,
error handling, backward compatibility, and threshold-aware reporting.
"""

import json
import os
import sys
import tempfile
import shutil

import pytest

# Add parent directory to path so we can import writing_check
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import writing_check


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def sample_profile():
    """A minimal valid profile for testing."""
    return {
        "profile": {
            "name": "Test User",
            "version": "1.0",
        },
        "patterns": {
            "hedge_words": ["\\bmaybe\\b", "\\bpossibly\\b"],
            "self_aggrandizing": ["\\bbrilliant\\b"],
            "topic_sentence_starters": [],
            "logical_connectors": ["\\bhowever\\b"],
            "narrative_padding": [],
            "corporate_jargon": ["\\bsynergy\\b"],
        },
        "thresholds": {
            "long_sentence_words": 50,
            "rewrite_sentence_words": 70,
            "long_sentence_max": 8,
            "rewrite_sentence_max": 4,
            "emdash_per_1000w": 25,
            "emdash_insertion_words": 15,
            "hedge_max": 1,
            "self_aggrandizing_max": 0,
            "topic_opener_max": 4,
            "logical_connector_max": 6,
            "narrative_padding_max": 0,
            "product_description_max": 0,
            "corporate_jargon_max": 0,
            "wordcount_over_pct": 120,
        },
        "qualitative": [
            {
                "id": "test_check",
                "category": "ideational",
                "name": "Test check",
                "instruction": "This is a test qualitative check.",
            }
        ],
    }


@pytest.fixture
def profile_file(sample_profile, tmp_path):
    """Write the sample profile to a temp file and return the path."""
    path = tmp_path / "test_profile.json"
    path.write_text(json.dumps(sample_profile), encoding="utf-8")
    return str(path)


@pytest.fixture
def sample_draft(tmp_path):
    """Create a simple markdown draft for analysis."""
    content = """# Test Draft

This is the first sentence of the draft. Perhaps this sentence has a hedge word.
Maybe this one does too. However, the argument continues.

I built something that works. I developed a tool that does things.
The synergy between teams was remarkable. This is a brilliant approach.

This sentence is deliberately made to be very long so that it exceeds the
forty word threshold that the default configuration uses for flagging
sentences as too long for comfortable reading in application materials.
"""
    path = tmp_path / "test_draft.md"
    path.write_text(content, encoding="utf-8")
    return str(path)


@pytest.fixture
def sample_dir_for_calibration(tmp_path):
    """Create a directory with sample writing for calibration."""
    samples = tmp_path / "samples"
    samples.mkdir()

    (samples / "sample1.md").write_text(
        "# Sample One\n\n"
        "I built this thing. It works well. The design was intentional. "
        "Every piece serves a purpose. The architecture reflects the critique. "
        "I carried this into the next project.\n\n"
        "This second paragraph has some longer sentences that test the thresholds "
        "for what counts as a long sentence in this particular writer's style, "
        "which tends toward complexity but not obscurity.\n",
        encoding="utf-8",
    )

    (samples / "sample2.md").write_text(
        "# Sample Two\n\n"
        "The conditions demanded it. I didn't plan to build software. "
        "The institution failed. The students needed something. I made it.\n\n"
        "Perhaps that sounds dramatic. It isn't. The numbers tell the story. "
        "Four classes. Forty-nine students each. No teaching assistant. "
        "The automation wasn't a choice -- it was survival.\n",
        encoding="utf-8",
    )

    return str(samples)


@pytest.fixture(autouse=True)
def reset_globals():
    """Reset writing_check globals to defaults before each test."""
    # Store originals
    originals = {
        "HEDGE_WORDS": writing_check.HEDGE_WORDS[:],
        "SELF_AGGRANDIZING": writing_check.SELF_AGGRANDIZING[:],
        "TOPIC_SENTENCE_STARTERS": writing_check.TOPIC_SENTENCE_STARTERS[:],
        "LOGICAL_CONNECTORS": writing_check.LOGICAL_CONNECTORS[:],
        "NARRATIVE_PADDING": writing_check.NARRATIVE_PADDING[:],
        "CORPORATE_JARGON": writing_check.CORPORATE_JARGON[:],
        "THRESH_LONG_SENT": writing_check.THRESH_LONG_SENT,
        "THRESH_REWRITE_SENT": writing_check.THRESH_REWRITE_SENT,
        "THRESH_LONG_SENT_MAX": writing_check.THRESH_LONG_SENT_MAX,
        "THRESH_REWRITE_SENT_MAX": writing_check.THRESH_REWRITE_SENT_MAX,
        "THRESH_EMDASH_PER_1000": writing_check.THRESH_EMDASH_PER_1000,
        "THRESH_EMDASH_INSERT_WORDS": writing_check.THRESH_EMDASH_INSERT_WORDS,
        "THRESH_HEDGE_MAX": writing_check.THRESH_HEDGE_MAX,
        "THRESH_AGGRANDIZE_MAX": writing_check.THRESH_AGGRANDIZE_MAX,
        "THRESH_TOPIC_THIS_MAX": writing_check.THRESH_TOPIC_THIS_MAX,
        "THRESH_CONNECTOR_MAX": writing_check.THRESH_CONNECTOR_MAX,
        "THRESH_PADDING_MAX": writing_check.THRESH_PADDING_MAX,
        "THRESH_PRODUCT_MAX": writing_check.THRESH_PRODUCT_MAX,
        "THRESH_JARGON_MAX": writing_check.THRESH_JARGON_MAX,
        "THRESH_WORDCOUNT_OVER": writing_check.THRESH_WORDCOUNT_OVER,
    }
    yield
    # Restore originals
    for key, val in originals.items():
        setattr(writing_check, key, val)


# ---------------------------------------------------------------------------
# Profile loading
# ---------------------------------------------------------------------------

class TestLoadProfile:

    def test_loads_valid_profile(self, profile_file):
        profile = writing_check.load_profile(profile_file)
        assert profile["profile"]["name"] == "Test User"
        assert "patterns" in profile
        assert "thresholds" in profile

    def test_rejects_malformed_json(self, tmp_path):
        bad = tmp_path / "bad.json"
        bad.write_text("not json at all", encoding="utf-8")
        with pytest.raises(SystemExit):
            writing_check.load_profile(str(bad))

    def test_rejects_invalid_regex(self, sample_profile, tmp_path):
        sample_profile["patterns"]["hedge_words"] = ["[invalid regex"]
        path = tmp_path / "bad_regex.json"
        path.write_text(json.dumps(sample_profile), encoding="utf-8")
        with pytest.raises(SystemExit):
            writing_check.load_profile(str(path))

    def test_accepts_empty_pattern_lists(self, sample_profile, tmp_path):
        sample_profile["patterns"]["hedge_words"] = []
        sample_profile["patterns"]["self_aggrandizing"] = []
        path = tmp_path / "empty_patterns.json"
        path.write_text(json.dumps(sample_profile), encoding="utf-8")
        profile = writing_check.load_profile(str(path))
        assert profile["patterns"]["hedge_words"] == []


# ---------------------------------------------------------------------------
# Profile application
# ---------------------------------------------------------------------------

class TestApplyProfile:

    def test_overrides_patterns(self, sample_profile):
        writing_check.apply_profile(sample_profile)
        assert writing_check.HEDGE_WORDS == ["\\bmaybe\\b", "\\bpossibly\\b"]
        assert writing_check.CORPORATE_JARGON == ["\\bsynergy\\b"]

    def test_overrides_thresholds(self, sample_profile):
        writing_check.apply_profile(sample_profile)
        assert writing_check.THRESH_LONG_SENT == 50
        assert writing_check.THRESH_REWRITE_SENT == 70
        assert writing_check.THRESH_HEDGE_MAX == 1
        assert writing_check.THRESH_EMDASH_PER_1000 == 25

    def test_wordcount_pct_converted(self, sample_profile):
        """wordcount_over_pct is stored as 120 in profile, should become 1.2."""
        writing_check.apply_profile(sample_profile)
        assert writing_check.THRESH_WORDCOUNT_OVER == 1.2

    def test_partial_profile_preserves_defaults(self):
        """A profile with only some keys should not clobber the others."""
        original_hedges = writing_check.HEDGE_WORDS[:]
        original_long_sent = writing_check.THRESH_LONG_SENT

        partial = {
            "patterns": {"corporate_jargon": ["\\bfoo\\b"]},
            "thresholds": {"hedge_max": 5},
        }
        writing_check.apply_profile(partial)

        # Corporate jargon overridden
        assert writing_check.CORPORATE_JARGON == ["\\bfoo\\b"]
        # Hedge max overridden
        assert writing_check.THRESH_HEDGE_MAX == 5
        # Hedge WORDS preserved (not in this profile)
        assert writing_check.HEDGE_WORDS == original_hedges
        # Long sentence threshold preserved
        assert writing_check.THRESH_LONG_SENT == original_long_sent

    def test_empty_profile_is_noop(self):
        """An empty profile should not change anything."""
        original_hedges = writing_check.HEDGE_WORDS[:]
        original_thresh = writing_check.THRESH_LONG_SENT
        writing_check.apply_profile({})
        assert writing_check.HEDGE_WORDS == original_hedges
        assert writing_check.THRESH_LONG_SENT == original_thresh


# ---------------------------------------------------------------------------
# Analysis with profiles
# ---------------------------------------------------------------------------

class TestAnalysisWithProfile:

    def test_profile_changes_hedge_detection(self, sample_profile, sample_draft):
        """With custom hedge patterns, different words should be flagged."""
        # Default: "perhaps" is a hedge
        default_results = writing_check.run_analysis(sample_draft, target=1200)
        default_hedges = {item["word"].lower() for item in default_results["hedges"]["items"]}
        assert "perhaps" in default_hedges

        # Custom profile: only "maybe" and "possibly" are hedges
        writing_check.apply_profile(sample_profile)
        profile_results = writing_check.run_analysis(sample_draft, target=1200)
        profile_hedges = {item["word"].lower() for item in profile_results["hedges"]["items"]}
        assert "maybe" in profile_hedges
        assert "perhaps" not in profile_hedges

    def test_profile_changes_sentence_thresholds(self, sample_profile, sample_draft):
        """With higher sentence threshold, fewer sentences should be flagged."""
        default_results = writing_check.run_analysis(sample_draft, target=1200)

        writing_check.apply_profile(sample_profile)
        profile_results = writing_check.run_analysis(sample_draft, target=1200)

        # Profile has threshold 50 (vs default 40), so fewer/equal sentences flagged
        assert profile_results["sentences"]["over_long_count"] <= default_results["sentences"]["over_long_count"]

    def test_threshold_values_in_results(self, sample_profile, sample_draft):
        """Sentence results should include the actual thresholds used."""
        writing_check.apply_profile(sample_profile)
        results = writing_check.run_analysis(sample_draft, target=1200)
        assert results["sentences"]["long_threshold"] == 50
        assert results["sentences"]["rewrite_threshold"] == 70


# ---------------------------------------------------------------------------
# Report formatting
# ---------------------------------------------------------------------------

class TestReportFormatting:

    def test_report_shows_profile_thresholds(self, sample_profile, sample_draft):
        """Report labels should use the profile's thresholds, not hardcoded 40/50."""
        writing_check.apply_profile(sample_profile)
        results = writing_check.run_analysis(sample_draft, target=1200)
        flagged = writing_check.collect_flagged_sentences(
            "", [], [], [], results  # minimal args — flagged sentence collection
        )
        report = writing_check.format_report(sample_draft, results, flagged)
        assert "Over 50 words:" in report
        assert "Over 70 words:" in report
        assert "Over 40 words:" not in report

    def test_report_default_thresholds(self, sample_draft):
        """Without a profile, report should show default thresholds."""
        results = writing_check.run_analysis(sample_draft, target=1200)
        flagged = results["flagged_sentences"]
        report = writing_check.format_report(sample_draft, results, flagged)
        assert "Over 40 words:" in report
        assert "Over 50 words:" in report


# ---------------------------------------------------------------------------
# Calibration
# ---------------------------------------------------------------------------

class TestCalibration:

    def test_calibrate_produces_valid_profile(self, sample_dir_for_calibration, tmp_path):
        output = tmp_path / "calibrated.json"
        writing_check.calibrate_from_samples(
            sample_dir_for_calibration, str(output)
        )

        assert output.exists()
        profile = json.loads(output.read_text(encoding="utf-8"))

        # Structure check
        assert "profile" in profile
        assert "patterns" in profile
        assert "thresholds" in profile
        assert "qualitative" in profile

        # Thresholds are reasonable numbers
        t = profile["thresholds"]
        assert 35 <= t["long_sentence_words"] <= 55
        assert t["rewrite_sentence_words"] > t["long_sentence_words"]
        assert t["emdash_per_1000w"] >= 5

    def test_calibrate_empty_dir(self, tmp_path):
        empty = tmp_path / "empty"
        empty.mkdir()
        with pytest.raises(SystemExit):
            writing_check.calibrate_from_samples(str(empty))

    def test_calibrated_profile_is_loadable(self, sample_dir_for_calibration, tmp_path):
        """A profile generated by --calibrate should be loadable by load_profile."""
        output = tmp_path / "calibrated.json"
        writing_check.calibrate_from_samples(
            sample_dir_for_calibration, str(output)
        )
        profile = writing_check.load_profile(str(output))
        # Should not raise — apply it
        writing_check.apply_profile(profile)
        assert writing_check.THRESH_LONG_SENT >= 35


# ---------------------------------------------------------------------------
# Backward compatibility
# ---------------------------------------------------------------------------

class TestBackwardCompatibility:

    def test_no_profile_uses_defaults(self, sample_draft):
        """Without applying a profile, analysis uses hardcoded defaults."""
        results = writing_check.run_analysis(sample_draft, target=1200)
        # Default hedge threshold is 0, so any hedge should flag
        assert results["sentences"]["long_threshold"] == 40
        assert results["sentences"]["rewrite_threshold"] == 50

    def test_default_profile_is_loadable(self, sample_draft):
        """The default profile should load and apply without error."""
        profile_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "profiles", "default.json"
        )
        if not os.path.exists(profile_path):
            pytest.skip("Default profile not found")

        profile = writing_check.load_profile(profile_path)
        writing_check.apply_profile(profile)
        results = writing_check.run_analysis(sample_draft, target=1200)

        # Default profile has looser thresholds
        assert results["sentences"]["long_threshold"] == 45
        assert results["sentences"]["rewrite_threshold"] == 60
