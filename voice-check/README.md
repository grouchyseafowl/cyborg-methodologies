# Voice Check — CDA-Based Voicing QC

A tool that checks whether a draft document matches a specific writer's voice. Uses quantitative analysis (sentence structure, modality, cohesion) + qualitative Critical Discourse Analysis (transitivity, referential strategy, argumentation topoi, concept scope).

Built for [Claude Code](https://claude.ai/code) but the Python script works standalone.

## How it works

1. You provide writing samples — the voice you want the tool to protect
2. The tool calibrates a **voice profile** from your samples (quantitative thresholds + qualitative CDA checklist)
3. When you draft something new, the tool checks it against your profile and flags deviations

Voice flags (hedges, self-aggrandizing frames, corporate jargon, narrative padding) are diagnostic of AI-generated text. Structural flags (long sentences, em-dashes) may be deliberate style. The tool distinguishes between the two.

## Setup

### Prerequisites

```bash
pip install textstat nltk
```

### Step 1: Gather your writing

Collect 3-10 pieces of your own **revised, final writing** — the voice you want to maintain. These should be writing you're proud of, in the genre you'll use the tool for.

**File formats**: `.md`, `.txt`, or `.html`. If your writing is in Word or Google Docs:
- Google Docs: File > Download > Plain Text (.txt)
- Word: copy-paste content into a .txt file

Put all samples in one directory.

### Step 2: Calibrate

```bash
python3 writing_check.py --calibrate path/to/your/samples/ -o my_profile.json
```

This computes your quantitative baselines — sentence lengths, em-dash density, hedge frequency — and generates a starter profile with thresholds set from your actual writing patterns.

### Step 3: Qualitative voice extraction (Claude Code users)

If you're using this with Claude Code, run `/voice-check setup` and the LLM will:
- Read your writing samples in full
- Extract what makes your voice distinctive
- Identify anti-patterns (words/phrases that would be wrong in your voice)
- Build a custom CDA checklist and write the regex patterns for you
- Add everything to your profile JSON

If you're **not** using Claude Code, you can manually edit the profile to add:
- Custom regex patterns for words/phrases you'd never use (in `patterns.corporate_jargon` or other categories)
- Qualitative checks describing what to look for in your voice (in the `qualitative` array)

See the profile schema below for the full format. The `default.json` profile provides a starting point; the `--calibrate` flag builds one tuned to your writing.

### Step 4: Verify

Run the tool on one of your own good writing samples:

```bash
python3 writing_check.py your_good_writing.md --profile my_profile.json
```

- **Few voice flags** = profile is well-calibrated
- **Many voice flags on your own writing** = patterns are too aggressive, loosen them
- **Zero flags on everything** = thresholds may be too loose to catch AI text, tighten them

## Usage

### With Claude Code

```
/voice-check              # checks the current draft
/voice-check path/to.md   # checks a specific file
```

The skill auto-detects your profile from `~/.claude/skills/voice-check/profiles/`.

### Standalone

```bash
python3 writing_check.py draft.md --profile my_profile.json [--target 1200]
python3 writing_check.py draft.md --profile my_profile.json --json   # JSON output
python3 writing_check.py draft.md                                    # no profile = built-in defaults
```

Adjust `--target` per document type: cover letter 1200, research statement 2000, blog post 1500.

## Profile schema

```json
{
  "profile": {
    "name": "Your Name",
    "version": "1.0",
    "created": "2026-04-13",
    "calibrated_from": "description of source samples",
    "description": "what this profile captures"
  },
  "patterns": {
    "hedge_words": ["\\bperhaps\\b", "..."],
    "self_aggrandizing": ["\\bgroundbreaking\\b", "..."],
    "topic_sentence_starters": ["..."],
    "logical_connectors": ["\\bhowever\\b", "..."],
    "narrative_padding": ["..."],
    "corporate_jargon": ["\\bleveraging\\b", "..."]
  },
  "thresholds": {
    "long_sentence_words": 45,
    "rewrite_sentence_words": 60,
    "long_sentence_max": 6,
    "rewrite_sentence_max": 3,
    "emdash_per_1000w": 20,
    "emdash_insertion_words": 12,
    "hedge_max": 2,
    "self_aggrandizing_max": 0,
    "topic_opener_max": 3,
    "logical_connector_max": 5,
    "narrative_padding_max": 0,
    "product_description_max": 0,
    "corporate_jargon_max": 0,
    "wordcount_over_pct": 115
  },
  "qualitative": [
    {
      "id": "check_id",
      "category": "ideational|interpersonal|textual|structural",
      "name": "Human-readable name",
      "instruction": "What to look for and what counts as a flag."
    }
  ]
}
```

### Pattern syntax

Patterns are Python regex strings (compiled with `re.IGNORECASE`). Examples:
- `"\\bperhaps\\b"` — matches the word "perhaps"
- `"\\bI am excited to\\b"` — matches the phrase
- `"\\bsynerg(?:y|ies|istic)\\b"` — matches synergy, synergies, synergistic

### Qualitative checks

These are instructions for the LLM doing the voice check. They don't run in the Python script — they tell the LLM what to look for when reading the draft. Organized by CDA category:
- **ideational**: what the text is about (processes, concepts, framing)
- **interpersonal**: relationship with reader (stance, appraisal, referential strategy)
- **textual**: how it's organized (cohesion, information structure, register)
- **structural**: genre and narrative patterns

## Files

```
voice-check/
├── README.md              # this file
├── SKILL.md               # Claude Code skill definition
├── writing_check.py       # the analysis script
├── profiles/
│   └── default.json       # generic starter profile
└── tests/
    └── test_voice_profiles.py
```
