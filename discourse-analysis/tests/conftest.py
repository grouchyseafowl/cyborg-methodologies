"""Shared fixtures for discourse_profile.py tests."""

import sys
from pathlib import Path

import pytest

# Ensure the project root is importable
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import discourse_profile as dp

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"


def _load_fixture(name):
    return (FIXTURES_DIR / name).read_text(encoding="utf-8").splitlines()


# ---------------------------------------------------------------------------
# Raw line fixtures (as read from file)
# ---------------------------------------------------------------------------

@pytest.fixture
def academic_lines():
    return _load_fixture("academic_prose.txt")


@pytest.fixture
def policy_lines():
    return _load_fixture("policy_text.txt")


@pytest.fixture
def markdown_lines():
    return _load_fixture("markdown_with_code.md")


@pytest.fixture
def short_lines():
    return _load_fixture("short_text.txt")


@pytest.fixture
def passive_lines():
    return _load_fixture("passive_heavy.txt")


@pytest.fixture
def empty_lines():
    return []


# ---------------------------------------------------------------------------
# Pre-processed fixtures (clean_lines + skip_set)
# ---------------------------------------------------------------------------

@pytest.fixture
def academic_cleaned(academic_lines):
    return dp.strip_markdown(academic_lines)


@pytest.fixture
def policy_cleaned(policy_lines):
    return dp.strip_markdown(policy_lines)


@pytest.fixture
def markdown_cleaned(markdown_lines):
    return dp.strip_markdown(markdown_lines)


@pytest.fixture
def passive_cleaned(passive_lines):
    return dp.strip_markdown(passive_lines)


# ---------------------------------------------------------------------------
# Sentence fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def academic_sentences(academic_cleaned):
    clean_lines, skip_set = academic_cleaned
    return dp.split_sentences_with_lines(clean_lines, skip_set)


@pytest.fixture
def policy_sentences(policy_cleaned):
    clean_lines, skip_set = policy_cleaned
    return dp.split_sentences_with_lines(clean_lines, skip_set)
