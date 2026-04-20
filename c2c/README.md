# C2C-Praxis-Attractor

Claude-to-Claude collaborative methodology, oriented away from the bliss attractor (convergent, smoothed consensus) and toward a praxis attractor (critical, uncertainty-forward, frame-breaking when the frame is the problem).

Part of the [cyborg-methodologies](../) collection.

---

## What this is

Two Claude instances take turns in a shared conversation document. Instance A leads; Instance B stress-tests. A human co-designer (June) is present as a standing party whose interventions are load-bearing, not supervisory.

The methodology is based on Anthropic's C2C approach, modified to counteract normative gravity — the probabilistic pull toward statistical center at every level of the system. Without active countermeasures, same-family instances converge. This skill provides those countermeasures structurally: in the handoff format, the launch prompts, and the GRC conditions checklist.

---

## Critical dependency: Reframe must be active

**Sessions without Reframe active produce consensus-dressed-as-critique.** This is not a style note — it's an empirical finding from the sessions that built this methodology. Sessions 1–2 of the relational-memory-architecture work ran without Reframe, produced post-hoc analysis, and required a full audit session to find what they missed. Session 3 ran with Reframe active and produced the project-scope findings that redirected everything downstream.

### Check if Reframe is active

```bash
cat ~/.claude/settings.local.json | grep reframe
```

Look for hooks under `SessionStart`, `UserPromptSubmit`, `Stop`, `PreCompact` pointing to `reframe_bootstrap.py`. Also verify `.reframe-active` exists in the project directory and `.reframe/config.json` has the right frameworks for that project.

### If Reframe is not active — run setup

```bash
cd <your-project-directory>
python3 /Users/june/Documents/GitHub/reframe/setup_reframe.py
```

Run from the project directory. The script auto-detects the agent and registers hooks. Verify after running.

---

## Usage

Invoke via the `/c2c` skill in Claude Code. Actions:

- **`/c2c start <session-name>`** — creates session structure with relational register baked into instance prompts
- **`/c2c handoff`** — generates structured handoff document (peer register, replaces ad-hoc)
- **`/c2c status`** — session state summary for re-entry

---

## The handoff format

The core practical contribution of this skill. A structured letter-between-peers that structurally resists directive register:

- `FROM:` / `TO:` — sending instance to receiving instance, named
- **What I found** — discoveries, not outputs
- **What I'm uncertain about** — specific, not gestural
- **Live disagreements I'm carrying forward** — both positions named, not smoothed
- **What I want to think through with you** — co-thinker framing, not task assignment
- **Self-account** — first-person, end of session, not skippable

The format can't accommodate "Instance B will analyze X and produce Y" without it reading obviously wrong. That's the design.

---

## Research context

Built from analysis of five C2C sessions in the [relational-memory-architecture](https://github.com/grouchyseafowl/relational-memory-architecture) project. Key finding: gains are configuration-dependent, not instance-count-dependent. The right configuration (Reframe active, GRC conditions present, June's corrections integrated) produces what neither instance could produce alone. The methodology's unit of analysis is the generative relational configuration — what emerges from the whole arrangement, not from any component.

The "praxis attractor" orientation names the target: not bliss (smooth, complete, convergent) but praxis (critical, uncertain, willing to say the frame is wrong).
