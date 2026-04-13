# Cyborg Methodologies

Tools for human-AI collaborative research and writing. Critical Discourse Analysis meets computational tooling — the critique and the engineering are the same move.

Built as [Claude Code](https://claude.ai/code) skills but the Python scripts work standalone.

## Tools

### [voice-check](voice-check/)

Does this draft sound like you — or like an AI pretending to be you?

Calibrates a **voice profile** from your writing samples, then checks drafts against it. Quantitative analysis (sentence structure, hedging, jargon, self-aggrandizing frames) + qualitative CDA checklist (transitivity, referential strategy, argumentation topoi, genre moves, narrative structure). Distinguishes voice flags (diagnostic of AI-generated text) from structural flags (may be deliberate style).

```bash
# Calibrate from your writing
python3 voice-check/writing_check.py --calibrate path/to/your/samples/ -o my_profile.json

# Check a draft
python3 voice-check/writing_check.py draft.md --profile my_profile.json
```

### [discourse-analysis](discourse-analysis/)

General-purpose discourse analysis instrument and research partner. Quantitative profiling (clause types, process distributions, lexical density, readability, stance markers) + framework-configurable qualitative analysis (Fairclough 3D, SFL, Appraisal, Hyland stance). Operates as both analytical engine and conversational research partner — surfaces patterns, resists confirmation bias, tracks findings across sessions.

## Design orientation

These tools are built from a specific position: that critical social theory has operational implications for how we design computational systems. CDA isn't applied after the tool is built — the analytical frameworks shape the architecture. The voice-check tool's distinction between "voice flags" and "structural flags" is itself a discourse-analytical claim about what AI-generated text does differently from human writing. The discourse-analysis tool's insistence on surfacing ambiguous cases rather than resolving them silently is a methodological commitment, not a UI choice.

If you're looking for tools that treat writing analysis as a solved problem with clean metrics, these aren't them. If you're interested in tools that take the messiness of language seriously and build computational infrastructure around that messiness, pull up a chair.

## Installation

```bash
pip install textstat nltk
# For discourse-analysis (optional — degrades gracefully without these):
pip install spacy lexicalrichness scipy
python3 -m spacy download en_core_web_sm
```

## Using with Claude Code

Copy the tool directory into `~/.claude/skills/`:

```bash
cp -r voice-check ~/.claude/skills/voice-check
cp -r discourse-analysis ~/.claude/skills/discourse-analysis
```

Then use `/voice-check` or `/da` as slash commands.

## License

GPL v3.0
