# CLAUDE.md — cyborg-methodologies

## Project Description

Tools for human-AI collaborative research and writing, built from a critical theory position: computational and discourse-analytical work are the same intellectual move. Two tools:

- **voice-check** — Voice matching for human-AI collaborative writing. Calibrates a voice profile from writing samples, then serves three roles: (1) style guide agents read before drafting, (2) per-draft linter catching contamination patterns (jargon, hedges, padding), (3) post-revision learning loop where stylometry compares agent first-draft to human-revised final and updates the profile so future drafts are closer. Quantitative analysis + qualitative CDA checklist.
- **discourse-analysis** — General-purpose discourse analysis instrument and research partner. Quantitative profiling (clause types, process distributions, lexical density, stance markers) + framework-configurable qualitative analysis (Fairclough 3D, SFL, Appraisal, Hyland stance). Operates as both analytical engine and conversational research partner.

Both tools are built as Claude Code skills but the Python scripts work standalone.

## Current State (as of 2026-04-13)

- voice-check: functional, 90 tests passing. Stylometry module built (`voice-check/stylometry.py`) — function word frequencies, punctuation ratios, vocabulary richness (TTR, MATTR, Yule's K), sentence length distribution, Burrows' Delta distance. `--learn` mode integrated into writing_check.py.
- Next priorities: perplexity scoring (needs MLX), then embedding similarity, then RST qualitative checks
- discourse-analysis: functional; active research project in `contexts/ai-slop.md` (12-text corpus on "ai slop" discourses, 7 findings accumulated)

## Project Index

```
cyborg-methodologies/
├── CLAUDE.md                         # This file
├── README.md                         # Top-level framing, install, usage
├── HANDOFF.md                        # Current state, next build priorities, pre-push checklist
├── .gitignore                        # Excludes profiles/*, .venv, contexts/ (privacy)
├── voice-check/
│   ├── SKILL.md                      # Claude Code skill — generic paths (repo-safe)
│   ├── README.md                     # User-facing docs
│   ├── writing_check.py              # Quantitative analysis + profile loading, calibration, --learn
│   ├── stylometry.py                 # Voice fingerprinting: Burrows' Delta, function words, vocab richness
│   ├── profiles/default.json         # Generic starter profile (loose thresholds)
│   └── tests/
│       ├── test_voice_profiles.py    # 19 profile/analysis tests
│       └── test_stylometry.py        # 71 stylometry tests
├── discourse-analysis/
│   ├── SKILL.md                      # Claude Code skill for /da
│   ├── discourse_profile.py          # Quantitative NLP profiling (spacy, textstat, lexicalrichness)
│   ├── frameworks/                   # Analytical framework protocols
│   │   ├── appraisal.md              # Martin & White Appraisal Theory
│   │   ├── fairclough-3d.md          # Fairclough 3D model
│   │   ├── hyland-stance.md          # Hyland academic stance/engagement
│   │   └── sfl.md                    # Systemic Functional Linguistics
│   ├── presets/                      # Domain-specific analysis presets (academic, ai-welfare, policy, etc.)
│   └── templates/project-context.md  # Template for per-project context files
└── contexts/
    └── ai-slop.md                    # Active project context: 12-text corpus, 7 findings
```

## Key Files

| File | Why it matters |
|---|---|
| `HANDOFF.md` | Full current state, next build spec (stylometry module), pre-push checklist |
| `voice-check/writing_check.py` | Canonical quantitative analysis engine; profile loading architecture |
| `voice-check/stylometry.py` | Voice fingerprinting engine; Burrows' Delta, calibration, learning loop |
| `voice-check/profiles/default.json` | Profile JSON schema — extend with `stylometry` and `perplexity` sections |
| `voice-check/SKILL.md` | Skill invocation protocol — generic paths for public repo |
| `discourse-analysis/SKILL.md` | Full /da pipeline, anti-sycophancy protocols, research note format |
| `contexts/ai-slop.md` | Active discourse analysis project with accumulated findings |

## Agent Instructions

**Before editing writing_check.py**, read it in full — profile loading, calibration, and pattern application are tightly coupled. The profile JSON schema is the contract between Python and LLM layers.

**Two-copy design for voice-check**: The maintainer's canonical script may live outside the repo. The repo copy is the public-safe snapshot. If you maintain a canonical copy elsewhere, sync from it before pushing. The maintainer's personal SKILL.md (local Claude Code skill) may have hardcoded paths — do not overwrite it from the repo version.

**Privacy constraint**: Before any push, run a grep for personal identifiers (usernames, real names, local paths) from repo root. Must return nothing. Keep the specific grep pattern in your local HANDOFF.md, not in this public file.

**contexts/ is gitignored** — research notes and project contexts contain accumulated findings and may contain corpus excerpts. Do not commit them.

**Stylometry module** (`voice-check/stylometry.py`): Voice fingerprinting — function word frequencies, punctuation ratios, vocabulary richness, sentence length distribution, Burrows' Delta distance. Two modes: calibrate from samples (extends `--calibrate`), learn from revision pairs (`--learn first_draft.md final_draft.md`). Profile schema extension under `"stylometry"` key. Does NOT use the `apply_profile()` globals pattern — stylometry functions take the profile section as an argument.

**Discourse analysis skill**: Anti-sycophancy and confirmation bias resistance are methodological requirements, not preferences. Do not silently resolve ambiguous codings. The tension between frameworks IS the finding.

**Install**: `pip install textstat nltk` (voice-check); add `spacy lexicalrichness scipy` for discourse-analysis. Run `python3 -m spacy download en_core_web_sm`.
