"""Tests for discourse_profile.py — quantitative layer of the /da skill.

Tests are organized by function group:
  1. Text helpers (pure, no NLP)
  2. Markdown stripping
  3. Sentence/paragraph splitting
  4. Profile computations (agency, pronoun, modality, theme, cohesion, speech, lexical)
  5. Flagged lines
  6. Integration (analyze, main, edge cases)
"""

import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

# Import the module under test (conftest adds project root to sys.path)
import discourse_profile as dp


# =========================================================================
# 1. TEXT HELPERS
# =========================================================================

class TestContextSnippet:
    def test_short_text_unchanged(self):
        assert dp.context_snippet("hello world") == "hello world"

    def test_exact_boundary(self):
        text = "a" * 40
        assert dp.context_snippet(text) == text

    def test_long_text_truncated(self):
        text = "a" * 60
        result = dp.context_snippet(text, max_len=40)
        assert len(result) == 41  # 40 chars + ellipsis
        assert result.endswith("…")

    def test_strips_whitespace(self):
        assert dp.context_snippet("  hello  ") == "hello"

    def test_custom_max_len(self):
        result = dp.context_snippet("abcdefghij", max_len=5)
        assert result == "abcde…"

    def test_empty_string(self):
        assert dp.context_snippet("") == ""


class TestWordsIn:
    def test_basic_sentence(self):
        assert dp.words_in("The cat sat on the mat") == ["The", "cat", "sat", "on", "the", "mat"]

    def test_punctuation_stripped(self):
        words = dp.words_in("Hello, world! How are you?")
        assert "Hello" in words
        assert "world" in words
        assert "," not in words
        assert "!" not in words

    def test_empty_string(self):
        assert dp.words_in("") == []

    def test_hyphenated_words(self):
        words = dp.words_in("well-known fact")
        # \b\w+\b splits on hyphens
        assert "well" in words
        assert "known" in words

    def test_numbers_included(self):
        words = dp.words_in("There are 42 reasons")
        assert "42" in words


# =========================================================================
# 2. MARKDOWN STRIPPING
# =========================================================================

class TestStripMarkdown:
    def test_headers_stripped(self):
        lines = ["# Title", "## Subtitle", "Plain text"]
        clean, skip = dp.strip_markdown(lines)
        assert clean[0] == "Title"
        assert clean[1] == "Subtitle"
        assert clean[2] == "Plain text"

    def test_code_blocks_excluded(self):
        lines = [
            "Before code.",
            "```python",
            "x = 1",
            "y = 2",
            "```",
            "After code.",
        ]
        clean, skip = dp.strip_markdown(lines)
        # Lines 1-4 (0-indexed) should be in skip_set
        assert 1 in skip
        assert 2 in skip
        assert 3 in skip
        assert 4 in skip
        # Code lines become empty
        assert clean[2] == ""
        assert clean[3] == ""
        # Prose lines preserved
        assert clean[0] == "Before code."
        assert clean[5] == "After code."

    def test_bold_italic_stripped(self):
        lines = ["This is **bold** and *italic* text"]
        clean, _ = dp.strip_markdown(lines)
        assert clean[0] == "This is bold and italic text"

    def test_links_text_preserved(self):
        lines = ["See [the docs](https://example.com) for details"]
        clean, _ = dp.strip_markdown(lines)
        assert "the docs" in clean[0]
        assert "https" not in clean[0]

    def test_image_links_removed(self):
        lines = ["![alt text](image.png)"]
        clean, _ = dp.strip_markdown(lines)
        # The image URL is removed; residual alt-text markup may remain
        assert "image.png" not in clean[0]
        assert "https" not in clean[0]

    def test_inline_code_removed(self):
        lines = ["Use `some_function()` to do it"]
        clean, _ = dp.strip_markdown(lines)
        assert "some_function" not in clean[0]
        assert "Use" in clean[0]

    def test_bare_urls_removed(self):
        lines = ["Visit https://example.com/page for more"]
        clean, _ = dp.strip_markdown(lines)
        assert "https" not in clean[0]

    def test_preserves_line_count(self):
        lines = ["# H1", "text", "```", "code", "```", "more"]
        clean, _ = dp.strip_markdown(lines)
        assert len(clean) == len(lines)

    def test_empty_input(self):
        clean, skip = dp.strip_markdown([])
        assert clean == []
        assert skip == set()

    def test_unclosed_code_fence(self):
        lines = ["text", "```", "code that never closes"]
        clean, skip = dp.strip_markdown(lines)
        # The fence opens but never closes — lines inside are skipped
        assert 1 in skip
        assert 2 in skip

    def test_markdown_fixture(self, markdown_lines):
        """The markdown fixture should have code blocks correctly excluded."""
        clean, skip = dp.strip_markdown(markdown_lines)
        # Code block lines should be in skip set
        assert len(skip) > 0
        # "def analyze" should not appear in cleaned prose
        prose = " ".join(clean)
        assert "def analyze" not in prose


# =========================================================================
# 3. SENTENCE / PARAGRAPH SPLITTING
# =========================================================================

class TestCountParagraphs:
    def test_single_paragraph(self):
        lines = ["Line one.", "Line two.", "Line three."]
        assert dp.count_paragraphs(lines, set()) == 1

    def test_multiple_paragraphs(self):
        lines = ["Para one.", "", "Para two.", "", "Para three."]
        assert dp.count_paragraphs(lines, set()) == 3

    def test_skip_set_breaks_paragraph(self):
        lines = ["Before.", "```", "code", "```", "After."]
        skip = {1, 2, 3}
        assert dp.count_paragraphs(lines, skip) == 2

    def test_all_blank(self):
        lines = ["", "", ""]
        assert dp.count_paragraphs(lines, set()) == 0

    def test_empty_lines(self):
        assert dp.count_paragraphs([], set()) == 0

    def test_academic_fixture_has_paragraphs(self, academic_lines):
        clean, skip = dp.strip_markdown(academic_lines)
        count = dp.count_paragraphs(clean, skip)
        assert count == 4  # 4 paragraphs separated by blank lines


class TestSplitSentences:
    def test_basic_splitting(self):
        lines = ["This is one. This is two."]
        clean, skip = dp.strip_markdown(lines)
        sents = dp.split_sentences_with_lines(clean, skip)
        assert len(sents) >= 2
        texts = [s for s, _ in sents]
        assert any("one" in t for t in texts)
        assert any("two" in t for t in texts)

    def test_returns_line_numbers(self):
        lines = ["First sentence.", "", "Second sentence."]
        clean, skip = dp.strip_markdown(lines)
        sents = dp.split_sentences_with_lines(clean, skip)
        # Each entry is (text, line_number)
        for text, ln in sents:
            assert isinstance(text, str)
            assert isinstance(ln, int)
            assert ln >= 1

    def test_skip_set_excluded(self):
        lines = ["Prose.", "```", "code = 1", "```", "More prose."]
        clean, skip = dp.strip_markdown(lines)
        sents = dp.split_sentences_with_lines(clean, skip)
        texts = " ".join(s for s, _ in sents)
        assert "code = 1" not in texts

    def test_empty_input(self):
        sents = dp.split_sentences_with_lines([], set())
        assert sents == []


# =========================================================================
# 4. PROFILE COMPUTATIONS
# =========================================================================

class TestPronounProfile:
    def test_first_person_singular(self):
        lines = ["I think this is my best work and I enjoy it"]
        result = dp.compute_pronoun_profile(lines, set())
        assert result["first_singular"] >= 2  # "I" x2 + "my"

    def test_first_person_plural(self):
        lines = ["We believe our approach serves us well"]
        result = dp.compute_pronoun_profile(lines, set())
        assert result["first_plural"] >= 2  # "we", "our", "us"

    def test_i_we_ratio(self):
        lines = ["I think we should go"]
        result = dp.compute_pronoun_profile(lines, set())
        assert result["first_singular"] == 1
        assert result["first_plural"] == 1
        assert result["I_we_ratio"] == 1.0

    def test_i_we_ratio_no_we(self):
        lines = ["I did it myself"]
        result = dp.compute_pronoun_profile(lines, set())
        assert result["first_singular"] >= 1
        assert result["first_plural"] == 0
        # Sentinel value: first_singular * 1000 when first_plural is 0
        assert result["I_we_ratio"] > 0

    def test_skip_set_respected(self):
        lines = ["I am here", "We are there"]
        result = dp.compute_pronoun_profile(lines, {1})  # skip line 1 (0-indexed)
        assert result["first_singular"] >= 1
        assert result["first_plural"] == 0

    def test_empty_text(self):
        result = dp.compute_pronoun_profile([], set())
        assert result["first_singular"] == 0
        assert result["I_we_ratio"] == 0.0

    def test_academic_fixture(self, academic_cleaned):
        clean, skip = academic_cleaned
        result = dp.compute_pronoun_profile(clean, skip)
        # Academic text should have some "we" usage
        assert result["first_plural"] > 0
        # All expected keys present
        for key in ("first_singular", "first_plural", "second",
                     "third_human", "third_nonhuman", "I_we_ratio", "we_they_ratio"):
            assert key in result


class TestModalityProfile:
    def test_detects_modals(self):
        lines = ["We should consider this and must act"]
        clean, skip = dp.strip_markdown(lines)
        sents = dp.split_sentences_with_lines(clean, skip)
        result = dp.compute_modality_profile(clean, skip, sents)
        assert result["modal_auxiliaries"]["should"] >= 1
        assert result["modal_auxiliaries"]["must"] >= 1
        assert result["modal_density"] > 0

    def test_detects_hedging(self):
        lines = ["Perhaps this is possible. It seems likely that we could proceed."]
        clean, skip = dp.strip_markdown(lines)
        sents = dp.split_sentences_with_lines(clean, skip)
        result = dp.compute_modality_profile(clean, skip, sents)
        hedging_words = {m["word"] for m in result["hedging_markers"]}
        assert "perhaps" in hedging_words

    def test_detects_boosting(self):
        lines = ["This is certainly the case. Obviously we must proceed."]
        clean, skip = dp.strip_markdown(lines)
        sents = dp.split_sentences_with_lines(clean, skip)
        result = dp.compute_modality_profile(clean, skip, sents)
        boosting_words = {m["word"] for m in result["boosting_markers"]}
        assert "certainly" in boosting_words
        assert "obviously" in boosting_words

    def test_hedging_phrases(self):
        lines = ["It seems that this approach works. It is possible that we are wrong."]
        clean, skip = dp.strip_markdown(lines)
        sents = dp.split_sentences_with_lines(clean, skip)
        result = dp.compute_modality_profile(clean, skip, sents)
        hedging_words = {m["word"] for m in result["hedging_markers"]}
        assert "it seems" in hedging_words

    def test_empty_text(self):
        result = dp.compute_modality_profile([], set(), [])
        assert result["modal_density"] == 0.0
        assert result["hedging_markers"] == []
        assert result["boosting_markers"] == []

    def test_policy_fixture(self, policy_cleaned, policy_sentences):
        clean, skip = policy_cleaned
        result = dp.compute_modality_profile(clean, skip, policy_sentences)
        # Policy text has "shall", "must", "should", "could"
        modals = result["modal_auxiliaries"]
        assert modals["shall"] >= 1 or modals["must"] >= 1 or modals["should"] >= 1


class TestThemeProfile:
    def test_classify_pronoun(self):
        assert dp.classify_sentence_initial("I went to the store") == "pronoun"
        assert dp.classify_sentence_initial("We decided to proceed") == "pronoun"
        assert dp.classify_sentence_initial("They argued against it") == "pronoun"

    def test_classify_existential_there(self):
        assert dp.classify_sentence_initial("There are many reasons for this") == "existential_there"
        assert dp.classify_sentence_initial("There is no evidence to suggest") == "existential_there"

    def test_classify_it_cleft(self):
        assert dp.classify_sentence_initial("It is clear that we must act") == "it_cleft"
        assert dp.classify_sentence_initial("It was the policy that caused harm") == "it_cleft"

    def test_classify_conjunction(self):
        assert dp.classify_sentence_initial("But the evidence suggests otherwise") == "conjunction"
        assert dp.classify_sentence_initial("Although the data is limited") == "conjunction"
        assert dp.classify_sentence_initial("Because we found errors") == "conjunction"

    def test_classify_adverbial(self):
        # These use spaCy if available, heuristic fallback otherwise
        result = dp.classify_sentence_initial("However, this remains debatable")
        assert result in ("adverbial", "conjunction")  # "however" could be either depending on implementation
        assert dp.classify_sentence_initial("In the beginning there was nothing") == "adverbial"

    def test_classify_noun_phrase(self):
        assert dp.classify_sentence_initial("The committee decided to act") == "noun_phrase"
        assert dp.classify_sentence_initial("Research suggests otherwise") == "noun_phrase"

    def test_classify_empty(self):
        assert dp.classify_sentence_initial("") == "noun_phrase"

    def test_theme_profile_structure(self, academic_sentences):
        result = dp.compute_theme_profile(academic_sentences)
        assert "sentence_initial" in result
        assert "marked_theme_rate" in result
        si = result["sentence_initial"]
        for key in ("pronoun", "noun_phrase", "adverbial", "conjunction",
                     "existential_there", "it_cleft"):
            assert key in si
        # Marked theme rate is between 0 and 1
        assert 0 <= result["marked_theme_rate"] <= 1

    def test_empty_sentences(self):
        result = dp.compute_theme_profile([])
        assert result["marked_theme_rate"] == 0.0


class TestCohesionProfile:
    def test_detects_connectors(self):
        lines = ["First point. Moreover, second point. However, there is a counterargument. Therefore we conclude."]
        word_count = len(dp.words_in(lines[0]))
        result = dp.compute_cohesion_profile(lines, set(), word_count)
        assert result["connector_types"]["additive"] >= 1  # "moreover"
        assert result["connector_types"]["adversative"] >= 1  # "however"
        assert result["connector_types"]["causal"] >= 1  # "therefore"
        assert result["connectors_total"] >= 3

    def test_connector_density(self):
        lines = ["But however thus moreover"]
        word_count = 4
        result = dp.compute_cohesion_profile(lines, set(), word_count)
        assert result["connector_density"] > 0

    def test_empty_text(self):
        result = dp.compute_cohesion_profile([], set(), 0)
        assert result["connectors_total"] == 0
        assert result["connector_density"] == 0.0

    def test_skip_set_respected(self):
        lines = ["However this matters.", "But so does this."]
        # Skip line 1 (0-indexed)
        result = dp.compute_cohesion_profile(lines, {1}, 4)
        # Only line 0 should be counted
        assert result["connector_types"]["adversative"] >= 1


class TestSpeechRepresentation:
    def test_direct_quotes(self):
        lines = ['She said "I disagree with this" and he said "Me too"']
        clean, skip = dp.strip_markdown(lines)
        result = dp.compute_speech_representation(clean, skip)
        assert result["direct_quotes"] == 2

    def test_indirect_speech(self):
        lines = ["The researcher argued that the evidence was insufficient",
                 "She claimed that the method was flawed"]
        clean, skip = dp.strip_markdown(lines)
        result = dp.compute_speech_representation(clean, skip)
        assert result["indirect_speech_markers"] >= 2

    def test_unicode_quotes(self):
        lines = ["\u201cHello,\u201d she said. \u2018Goodbye,\u2019 he whispered."]
        clean, skip = dp.strip_markdown(lines)
        result = dp.compute_speech_representation(clean, skip)
        assert result["direct_quotes"] >= 2

    def test_no_speech(self):
        lines = ["The cat sat on the mat. It was warm."]
        clean, skip = dp.strip_markdown(lines)
        result = dp.compute_speech_representation(clean, skip)
        assert result["direct_quotes"] == 0
        assert result["indirect_speech_markers"] == 0

    def test_empty(self):
        result = dp.compute_speech_representation([], set())
        assert result["direct_quotes"] == 0


class TestAgencyProfile:
    def test_passive_detection(self, passive_cleaned):
        clean, skip = passive_cleaned
        result = dp.compute_agency_profile(clean, skip)
        assert result["passive_rate"] > 0
        assert len(result["passive_instances"]) > 0

    def test_passive_with_agent(self):
        lines = ["The proposal was rejected by the committee."]
        clean, skip = dp.strip_markdown(lines)
        result = dp.compute_agency_profile(clean, skip)
        if result["passive_instances"]:
            has_by_agent = any(p["has_agent"] for p in result["passive_instances"])
            assert has_by_agent, "Should detect 'by the committee' as agent"
            assert result["passive_with_agent"] >= 1

    def test_passive_without_agent(self):
        lines = ["The data was collected over six months."]
        clean, skip = dp.strip_markdown(lines)
        result = dp.compute_agency_profile(clean, skip)
        if result["passive_instances"]:
            agentless = any(not p["has_agent"] for p in result["passive_instances"])
            assert agentless

    def test_active_voice(self):
        lines = ["The committee rejected the proposal firmly."]
        clean, skip = dp.strip_markdown(lines)
        result = dp.compute_agency_profile(clean, skip)
        assert result["passive_rate"] == 0.0

    def test_agent_deletion_rate(self, passive_cleaned):
        clean, skip = passive_cleaned
        result = dp.compute_agency_profile(clean, skip)
        # Some passives have agents, some don't — rate should be between 0 and 1
        if result["passive_instances"]:
            assert 0 <= result["agent_deletion_rate"] <= 1

    def test_structure(self, passive_cleaned):
        clean, skip = passive_cleaned
        result = dp.compute_agency_profile(clean, skip)
        for key in ("passive_rate", "passive_with_agent", "passive_without_agent",
                     "agent_deletion_rate", "passive_instances"):
            assert key in result

    def test_empty_text(self):
        result = dp.compute_agency_profile([], set())
        assert result["passive_rate"] == 0.0
        assert result["passive_instances"] == []


class TestLexicalProfile:
    def test_structure(self, academic_cleaned, academic_sentences):
        clean, skip = academic_cleaned
        result = dp.compute_lexical_profile(clean, skip, academic_sentences)
        for key in ("lexical_density", "mattr_50", "nominalization_density", "nominalizations"):
            assert key in result

    def test_lexical_density_range(self, academic_cleaned, academic_sentences):
        clean, skip = academic_cleaned
        result = dp.compute_lexical_profile(clean, skip, academic_sentences)
        # Lexical density should be between 0 and 1
        assert 0 <= result["lexical_density"] <= 1

    def test_nominalizations_detected(self, academic_cleaned, academic_sentences):
        clean, skip = academic_cleaned
        result = dp.compute_lexical_profile(clean, skip, academic_sentences)
        # Academic text should have nominalizations (e.g., "nominalization", "transformation", etc.)
        assert len(result["nominalizations"]) > 0
        assert result["nominalization_density"] > 0

    def test_nominalization_structure(self, academic_cleaned, academic_sentences):
        clean, skip = academic_cleaned
        result = dp.compute_lexical_profile(clean, skip, academic_sentences)
        if result["nominalizations"]:
            nom = result["nominalizations"][0]
            assert "word" in nom
            assert "count" in nom
            assert "line" in nom
            assert "context" in nom

    def test_empty_text(self):
        result = dp.compute_lexical_profile([], set(), [])
        assert result["lexical_density"] == 0.0
        assert result["nominalizations"] == []


class TestBasicStats:
    def test_structure(self, academic_sentences, academic_cleaned):
        clean, skip = academic_cleaned
        full_text = "\n".join(line for i, line in enumerate(clean) if i not in skip)
        result = dp.compute_basic_stats(academic_sentences, clean, skip, full_text)
        for key in ("word_count", "sentence_count", "paragraph_count",
                     "mean_sentence_length", "sd_sentence_length",
                     "max_sentence_length", "sentence_length_distribution", "readability"):
            assert key in result

    def test_word_count_positive(self, academic_sentences, academic_cleaned):
        clean, skip = academic_cleaned
        full_text = "\n".join(line for i, line in enumerate(clean) if i not in skip)
        result = dp.compute_basic_stats(academic_sentences, clean, skip, full_text)
        assert result["word_count"] > 50
        assert result["sentence_count"] > 1
        assert result["paragraph_count"] > 0

    def test_readability_scores(self, academic_sentences, academic_cleaned):
        clean, skip = academic_cleaned
        full_text = "\n".join(line for i, line in enumerate(clean) if i not in skip)
        result = dp.compute_basic_stats(academic_sentences, clean, skip, full_text)
        r = result["readability"]
        # Flesch-Kincaid grade level — academic text should be higher than, say, 8
        assert r["flesch_kincaid"] > 0
        # Gunning fog should be present
        assert r["gunning_fog"] > 0

    def test_sentence_length_distribution(self, academic_sentences, academic_cleaned):
        clean, skip = academic_cleaned
        full_text = "\n".join(line for i, line in enumerate(clean) if i not in skip)
        result = dp.compute_basic_stats(academic_sentences, clean, skip, full_text)
        dist = result["sentence_length_distribution"]
        assert len(dist) == result["sentence_count"]
        assert all(isinstance(n, int) for n in dist)

    def test_empty_text(self):
        result = dp.compute_basic_stats([], [], set(), "")
        assert result["word_count"] == 0
        assert result["sentence_count"] == 0
        assert result["mean_sentence_length"] == 0.0


# =========================================================================
# 5. FLAGGED LINES
# =========================================================================

class TestFlaggedLines:
    def test_flags_passive(self, passive_cleaned):
        clean, skip = passive_cleaned
        agency = dp.compute_agency_profile(clean, skip)
        flagged = dp.build_flagged_lines(clean, skip, agency, [])
        # Should have flagged lines for passive voice
        if agency["passive_instances"]:
            assert len(flagged) > 0
            features = []
            for f in flagged:
                features.extend(f["features"])
            assert any("passive" in feat for feat in features)

    def test_flags_nominalizations(self, academic_cleaned, academic_sentences):
        clean, skip = academic_cleaned
        agency = dp.compute_agency_profile(clean, skip)
        lexical = dp.compute_lexical_profile(clean, skip, academic_sentences)
        flagged = dp.build_flagged_lines(clean, skip, agency, lexical["nominalizations"])
        features = []
        for f in flagged:
            features.extend(f["features"])
        assert any("nominalization" in feat for feat in features)

    def test_flagged_structure(self, passive_cleaned):
        clean, skip = passive_cleaned
        agency = dp.compute_agency_profile(clean, skip)
        flagged = dp.build_flagged_lines(clean, skip, agency, [])
        for entry in flagged:
            assert "line" in entry
            assert "text" in entry
            assert "features" in entry
            assert "context" in entry
            assert isinstance(entry["features"], list)

    def test_empty_profiles(self):
        flagged = dp.build_flagged_lines([], set(), {"passive_instances": []}, [])
        assert flagged == []


# =========================================================================
# 6. INTEGRATION: analyze() and main()
# =========================================================================

class TestEmptyProfile:
    def test_structure(self):
        profile = dp._empty_profile()
        for key in ("basic_stats", "lexical_profile", "agency_profile",
                     "pronoun_profile", "modality_profile", "theme_profile",
                     "cohesion_profile", "speech_representation", "flagged_lines",
                     "warnings"):
            assert key in profile

    def test_all_zeros(self):
        profile = dp._empty_profile()
        assert profile["basic_stats"]["word_count"] == 0
        assert profile["basic_stats"]["sentence_count"] == 0
        assert profile["agency_profile"]["passive_rate"] == 0.0
        assert profile["pronoun_profile"]["first_singular"] == 0

    def test_json_serializable(self):
        profile = dp._empty_profile()
        # Should not raise
        output = json.dumps(profile)
        assert isinstance(output, str)


class TestAnalyze:
    def test_academic_text(self, academic_lines):
        profile = dp.analyze(academic_lines)
        # Should have all top-level keys
        for key in ("basic_stats", "lexical_profile", "agency_profile",
                     "pronoun_profile", "modality_profile", "theme_profile",
                     "cohesion_profile", "speech_representation", "flagged_lines"):
            assert key in profile
        # Word count should be substantial
        assert profile["basic_stats"]["word_count"] > 100

    def test_policy_text(self, policy_lines):
        profile = dp.analyze(policy_lines)
        # Policy text should have modals
        modals = profile["modality_profile"]["modal_auxiliaries"]
        modal_total = sum(modals.values())
        assert modal_total > 0

    def test_markdown_code_blocks_excluded(self, markdown_lines):
        profile = dp.analyze(markdown_lines)
        # Flagged lines should not reference code block content
        for fl in profile["flagged_lines"]:
            assert "def analyze" not in fl.get("text", "")

    def test_short_text_warning(self, short_lines):
        profile = dp.analyze(short_lines)
        assert "warnings" in profile
        assert any("under 50" in w.lower() for w in profile["warnings"])

    def test_empty_input(self):
        profile = dp.analyze([])
        assert profile["basic_stats"]["word_count"] == 0
        assert "warnings" in profile

    def test_only_code_blocks(self):
        lines = ["```", "x = 1", "y = 2", "```"]
        profile = dp.analyze(lines)
        assert profile["basic_stats"]["word_count"] == 0

    def test_json_serializable(self, academic_lines):
        profile = dp.analyze(academic_lines)
        output = json.dumps(profile)
        parsed = json.loads(output)
        assert parsed["basic_stats"]["word_count"] == profile["basic_stats"]["word_count"]

    def test_passive_heavy_text(self, passive_lines):
        profile = dp.analyze(passive_lines)
        # This text is mostly passive — rate should be notably above 0
        assert profile["agency_profile"]["passive_rate"] > 0.1


class TestMain:
    def test_valid_file(self, tmp_path):
        f = tmp_path / "test.txt"
        f.write_text("The committee decided to act. They approved the proposal unanimously.")
        with patch.object(sys, "argv", ["discourse_profile.py", str(f)]):
            # main() returns normally on success (no sys.exit)
            dp.main()

    def test_valid_file_output(self, tmp_path, capsys):
        f = tmp_path / "test.txt"
        f.write_text("The committee decided to act. They approved the proposal unanimously.")
        with patch.object(sys, "argv", ["discourse_profile.py", str(f)]):
            # main() calls print(json.dumps(...)) then falls off the end
            try:
                dp.main()
            except SystemExit:
                pass
            captured = capsys.readouterr()
            # Should produce valid JSON
            profile = json.loads(captured.out)
            assert "basic_stats" in profile

    def test_missing_file(self):
        with patch.object(sys, "argv", ["discourse_profile.py", "/nonexistent/file.txt"]):
            with pytest.raises(SystemExit) as exc_info:
                dp.main()
            assert exc_info.value.code == 1

    def test_no_arguments(self):
        with patch.object(sys, "argv", ["discourse_profile.py"]):
            with pytest.raises(SystemExit) as exc_info:
                dp.main()
            assert exc_info.value.code == 1
