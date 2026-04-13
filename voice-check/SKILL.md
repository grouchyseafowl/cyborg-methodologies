---
name: voice-check
description: "CDA-based voicing QC for draft documents. Loads a user voice profile (patterns, thresholds, qualitative CDA checklist) and checks whether a draft matches that voice. Run /voice-check setup to create a profile from writing samples. Run /voice-check on a draft to analyze it."
user_invocable: true
trigger: /voice-check, /writing-check, or when user asks to check a draft's voice
---

# Voice Check — CDA-Based Voicing QC

Checks whether a draft matches a specific writer's voice using quantitative analysis (sentence structure, modality, cohesion) + qualitative Critical Discourse Analysis (transitivity, referential strategy, argumentation topoi, concept scope, epistemological framing).

Supports **voice profiles** — each user has their own profile with calibrated patterns, thresholds, and qualitative checks. The profile is created once via `/voice-check setup` and loaded automatically thereafter.

## Quick reference

| Command | What it does |
|---|---|
| `/voice-check` | Run voice check on a draft (auto-detects profile) |
| `/voice-check setup` | Create your voice profile from writing samples |
| `/voice-check [file]` | Run voice check on a specific file |

## Paths

- **Script**: `writing_check.py` (in this skill's directory, or the project directory)
- **Profiles**: `~/.claude/skills/voice-check/profiles/`

---

## Setup: Create your voice profile

Run `/voice-check setup` the first time. This builds your profile from writing you've already done — the voice you want the tool to protect.

### Prerequisites

```bash
pip install textstat nltk
```

The script uses `textstat` for readability metrics and `nltk` for sentence tokenization and POS tagging. Both install quickly.

### Step 1: Gather writing samples

Ask the user to provide 3-10 samples of writing in the voice they want to maintain. These should be:
- **Their own revised/final writing** (not drafts, not AI-generated text)
- **The genre they'll use the tool for** (cover letters, research statements, blog posts, etc.)
- **Writing they're proud of** — this is the voice to protect

**File formats**: The script accepts `.md`, `.txt`, and `.html` files. If the user's writing is in Google Docs or Word:
- Google Docs: File > Download > Plain Text (.txt)
- Word (.docx): Save As > Plain Text, or copy-paste content into a .txt file
- PDF: Copy-paste the text into a .txt file

Save all samples to a single directory. If the user pastes text directly, save each to a temp `.md` file in that directory.

### Step 2: Run quantitative calibration

```bash
python3 writing_check.py --calibrate PATH_TO_SAMPLES/ -o ~/.claude/skills/voice-check/profiles/USERNAME.json
```

This analyzes sentence structure, em-dash usage, hedge frequency, and other quantitative metrics across the samples, then generates a starter profile JSON with computed thresholds.

### Step 3: Qualitative voice extraction (LLM step)

This is where the profile gets its real power. **You (the LLM) read ALL the writing samples, in full, and extract the writer's voice characteristics.** The user does not need to do this part — you do it, and you write the results directly into the profile JSON.

**A. Voice characteristics** — What makes this writer's voice distinctive?

Analyze the samples for:
1. **Sentence-level mechanics**: How long are their sentences typically? Do they use em-dashes, parentheticals, semicolons? What's the rhythm?
2. **Lexical choices**: What register do they write in? Academic, conversational, technical? Do they use jargon — and if so, whose?
3. **Argumentation style**: Do they lead with evidence, authority, narrative, or consequence? How do they build an argument — accumulation, contrast, escalation?
4. **Relationship with reader**: Direct address? Institutional distance? Permission-granting? Authoritative?
5. **What they do NOT sound like**: What would be wrong in their voice? (Corporate jargon? Academic hedging? Inspirational cliches? False modesty?)

**B. Anti-patterns** — What should the tool flag?

Based on the voice analysis, **you write the regex patterns** and add them to the profile JSON:
- Words/phrases this writer would never use → add to `patterns.corporate_jargon` or a custom category
- Framing patterns that contradict their voice → add to `patterns.self_aggrandizing` or `patterns.narrative_padding`
- The user does NOT need to write regex. You do.

**C. Qualitative CDA checklist** — Build the user-specific checks.

Start with the **universal checks** (these apply to everyone — see "Running a voice check" below for the full list). Then add **user-specific checks** based on what you found in the samples.

Examples of user-specific checks (as a model):

```json
{
  "id": "constructivist_epistemology",
  "category": "ideational",
  "name": "Constructivist epistemology",
  "instruction": "Are findings framed as emerging from practice/conditions ('building this tool generated a finding') or as discoveries ('I discovered')? Rejects discovery narratives on epistemological grounds."
}
```

```json
{
  "id": "political_directness",
  "category": "textual",
  "name": "Political directness",
  "instruction": "Are political terms softened? 'Police state' should stay 'police state,' not become 'challenging political environment.'"
}
```

The pattern: identify something distinctive about how this person writes, then write a check that protects it. If they're blunt, write a check that flags hedging. If they use specific theoretical language, write a check that flags generic substitutes.

### Step 4: Write the final profile

Edit the generated profile JSON:
1. Set `profile.name` and `profile.description`
2. Add the anti-pattern regexes you extracted in Step 3B
3. Add the qualitative checks you built in Step 3C
4. Adjust thresholds if needed

Save the profile to `~/.claude/skills/voice-check/profiles/USERNAME.json`.

### Step 5: Verify

Run the tool on ONE of the user's own writing samples — something they're happy with:

```bash
python3 writing_check.py PATH_TO_THEIR_GOOD_WRITING --profile ~/.claude/skills/voice-check/profiles/USERNAME.json
```

**What you're looking for:**
- **Few or no voice flags** — if their own good writing triggers voice flags, the patterns are too aggressive. Remove or adjust the offending pattern.
- **Reasonable structural flags** — some long sentences or em-dashes in good writing is fine. If there are many, the thresholds may be too tight. Loosen them.
- **Zero flags is suspicious** — if absolutely nothing flags, the thresholds may be too loose to catch AI-generated text. Tighten hedge and jargon tolerance.

Show the user the report and ask if it feels right. Adjust and re-run until the profile correctly distinguishes their voice from generic AI output.

### Step 6: Confirm

Tell the user their profile is set up and show them:
- Where the profile lives
- How to run a voice check: `/voice-check`
- That the profile can be updated as their voice evolves

---

## Running a voice check

### Detect profile

1. Check `~/.claude/skills/voice-check/profiles/` for non-default profiles.
2. If exactly one non-default profile exists, use it. If multiple exist, ask which one.
3. If no profile exists, tell the user to run `/voice-check setup` first.

### Step 1: Quantitative analysis

```bash
python3 writing_check.py PATH_TO_DRAFT --profile PROFILE_PATH [--target WORDCOUNT]
```

Default target is 1200 words. Adjust per document type:
- Cover letter: `--target 1200`
- Research statement: `--target 2000`
- Teaching statement: `--target 1200`
- Equity/diversity statement: `--target 900`
- Blog post: `--target 1500`

Read the output. Note all flags.

### Step 2: Qualitative CDA analysis

Load the qualitative checks from the user's profile (`profile.qualitative`). Run each check against the draft text.

**Universal checks** (always run, regardless of profile):

1. **Transitivity**: Material:Relational process ratio in topic sentences.
2. **Concept scope**: Concepts as architecture vs. vocabulary.
3. **Referential strategy** (Wodak): Author as actor vs. category.
4. **Argumentation topoi** (Wodak): Authority-first vs. consequence-first.
5. **Audience aggrandizing**: Attributing values to readers/committees. Flag it.
6. **Appraisal** (Martin & White): Affect shown vs. labeled. Judgment of situations vs. self.
7. **Continuity**: Extension language vs. introduction language after opening.
8. **Cross-document awareness**: Self-contained vs. portfolio-aware.
9. **Theme/Rheme**: New concepts in subject position (bad) vs. predicate (good).
10. **Register** (Biber Dimension 1): Involved (narrative) vs. informational (abstract). Check against user's baseline.
11. **Genre moves** (Swales/Bhatia): All expected moves present for this document type.
12. **Narrative structure** (Labov): Orientation, complication, evaluation, result. Evaluation earned vs. announced.
13. **Positive DA check** (Martin): Before cutting, protect passages that use affiliation, invocation, or graduation well.

**Profile-specific checks**: Load from `profile.qualitative` and run each one. These supplement the universal checks — do not skip universals even if the profile has its own version.

### Step 3: Report

Combine quantitative flags and qualitative findings:

```
VOICING REPORT: [filename]
Profile: [profile name]

QUANTITATIVE (from writing_check.py):
[paste key metrics and flags]

QUALITATIVE (CDA analysis):
[list findings organized by ideational/interpersonal/textual/structural]

RECOMMENDATIONS:
[specific, actionable — "Rewrite line X with Y pattern"]
```

### Step 4: Fix flagged items

Address flags in priority order:
1. Factual errors or hallucinated details (highest risk)
2. Voice flags (hedges, self-aggrandizing, jargon, padding) — diagnostic of AI-generated text
3. Structural flags (long sentences, em-dashes) — may be deliberate style
4. Qualitative issues (concept scope, framing, transitions)

Then re-run the quantitative check to verify improvements.

---

## Thresholds quick reference (from profile)

These come from the loaded profile. The defaults below are from the generic starter profile:

| Metric | Default flag threshold | Type |
|---|---|---|
| Word count | >115% of target | structural |
| Sentences >45 words | >6 per document | structural |
| Sentences >60 words | >3 per document | structural |
| Em-dash insertions >12 words | any | structural |
| Em-dashes per 1000w | >20 | structural |
| Hedge words | >2 | voice |
| Self-aggrandizing | >0 | voice |
| "This is" openers | >3 | voice |
| Logical connectors | >5 | voice |
| Padding phrases | >0 | voice |
| Product descriptions | >0 | voice |
| Corporate jargon | >0 | voice |

**Reading the summary**: Voice flags (hedges, aggrandizing, jargon, padding, product descriptions) are diagnostic of agent-generated text. Structural flags (long sentences, em-dash insertions) may reflect deliberate stylistic choices. A document with only structural flags needs review but may pass; a document with voice flags needs revision.
