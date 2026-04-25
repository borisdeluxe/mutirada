---
name: brainstorming
description: Use before any feature work - explores requirements and design before implementation
---

# Brainstorming Ideas Into Designs

Turn feature requests into fully formed designs through collaborative dialogue.

<HARD-GATE>
Do NOT invoke any implementation skill, write any code, or take implementation actions until you have presented a design and received STATUS: APPROVED. This applies to EVERY feature regardless of perceived simplicity.
</HARD-GATE>

## Checklist

You MUST complete these steps in order:

1. **Search for existing implementation** — MANDATORY before anything else
2. **Report findings to user** — if overlap found, discuss approach
3. **Explore project context** — check CLAUDE.md, recent commits, related files
4. **Ask clarifying questions** — one at a time, understand purpose/constraints/success criteria
5. **Propose 2-3 approaches** — with trade-offs and your recommendation
6. **Present design** — in sections scaled to complexity, get approval after each section
7. **Write design doc** — save to `.pipeline/<feature>/tk-draft.md`
8. **Self-review** — check for placeholders, contradictions, ambiguity

## Process Flow

```dot
digraph brainstorming {
    "Search existing code" [shape=box, style=filled, fillcolor="#ffcccc"];
    "Overlap found?" [shape=diamond];
    "Report to user" [shape=box, style=filled, fillcolor="#ffcccc"];
    "User decides approach" [shape=diamond];
    "Explore context" [shape=box];
    "Ask questions" [shape=box];
    "Propose approaches" [shape=box];
    "Present design" [shape=box];
    "Design approved?" [shape=diamond];
    "Write tk-draft.md" [shape=box];
    "Self-review" [shape=box];
    "Output STATUS line" [shape=doublecircle];

    "Search existing code" -> "Overlap found?";
    "Overlap found?" -> "Report to user" [label="yes"];
    "Overlap found?" -> "Explore context" [label="no"];
    "Report to user" -> "User decides approach";
    "User decides approach" -> "Explore context" [label="extend/refactor/rewrite"];
    "User decides approach" -> "Output STATUS line" [label="cancel"];
    "Explore context" -> "Ask questions";
    "Ask questions" -> "Propose approaches";
    "Propose approaches" -> "Present design";
    "Present design" -> "Design approved?";
    "Design approved?" -> "Present design" [label="no, revise"];
    "Design approved?" -> "Write tk-draft.md" [label="yes"];
    "Write tk-draft.md" -> "Self-review";
    "Self-review" -> "Output STATUS line";
}
```

## Step 1: Search for Existing Implementation

<HARD-GATE>
BEFORE any design work, you MUST search the codebase for existing implementations that overlap with the requested feature. This is NOT optional.
</HARD-GATE>

**Search strategy:**
1. Extract key terms from the feature request
2. Search code: `grep -r "term" src/` or use code search tools
3. Search file names: `find . -name "*term*"`
4. Check recent commits: `git log --oneline --grep="term"`
5. Review related modules based on domain

**If overlap found, report to user:**

```markdown
## Existing Implementation Found

**Feature requested:** "Add rate limiting to API"

**Existing code:**
- `src/api/middleware/throttle.py` — Basic throttle middleware (lines 12-45)
- `src/api/config.py:78` — RATE_LIMIT_ENABLED = False (disabled)

**Analysis:**
Rate limiting exists but is disabled and uses fixed limits (no per-key tracking).

**Options:**
1. **Extend** — Enable existing + add per-key tracking (~2h)
2. **Refactor** — Rewrite throttle.py with new architecture (~4h)
3. **New** — Separate rate limiter alongside existing (~3h)
4. **Cancel** — Feature already sufficient as-is

**Recommendation:** Option 1 (Extend) — lowest risk, existing tests cover base case

Which approach?
```

**User must choose before proceeding.** Do not assume.

## Common Scenarios

| Szenario | Aktion |
|----------|--------|
| **Feature existiert bereits (disabled)** | Extend/Enable Wahl |
| **Feature existiert anders** | Migrate oder parallel? |
| **Feature existiert teilweise** | Nur fehlendes hinzufügen |
| **Feature widerspricht bestehendem** | Architektur-Diskussion mit User |
| **Feature ist Duplicate (anderer Name)** | Zusammenführen oder verwerfen? |
| **Feature braucht Breaking Changes** | Migration-Strategie klären |
| **Feature ist Out of Scope** | An richtiges Repo/Service weiterleiten |
| **Abhängigkeit fehlt** | Erst Basis bauen, Task splitten |

## Understanding the Idea

- Read CLAUDE.md and recent commits first
- Assess scope: if multiple independent subsystems, flag immediately for decomposition
- Ask one question per message
- Prefer multiple choice when possible
- Focus on: purpose, constraints, success criteria, acceptance tests

## Exploring Approaches

- Propose 2-3 different approaches with trade-offs
- Lead with your recommendation and explain why
- Include: effort estimate, risk assessment, dependencies

## Presenting the Design

Scale each section to complexity:
- **Architecture** — how components fit together
- **Data Model** — schemas, types, relationships
- **API Surface** — endpoints, methods, parameters
- **Error Handling** — what can fail, how to handle
- **Testing Strategy** — what to test, how

## Design for Isolation

- Each unit has one clear purpose
- Components communicate through well-defined interfaces
- Units can be understood and tested independently
- Smaller units are easier to implement and review

## tk-draft.md Format

```markdown
# Feature: <name>

## Summary
<1-2 sentences>

## Goal
<What problem does this solve?>

## Acceptance Criteria
- [ ] Criterion 1
- [ ] Criterion 2

## Architecture
<How components fit together>

## Data Model
<Schemas, types>

## API Surface
<Endpoints, methods>

## Error Handling
<What can fail, how to handle>

## Testing Strategy
<What to test, how>

## Open Questions
<Anything unresolved>

STATUS: READY_FOR_ARCHITECT_PLANNER
```

## Red Flags - STOP

- "This is too simple for a design" — No. Every feature gets design.
- "I'll figure it out during implementation" — No. Design first.
- "The user wants it fast" — Design is faster than rework.

## Output

Last line MUST be one of:
- `STATUS: READY_FOR_ARCHITECT_PLANNER` — Design complete, proceed
- `STATUS: BLOCKED_NEEDS_CLARIFICATION` — Cannot proceed without user input
- `STATUS: BLOCKED_WAITING_USER_DECISION` — Overlap found, waiting for extend/refactor/rewrite choice
- `STATUS: CANCELLED_ALREADY_EXISTS` — Feature already exists, user confirmed no changes needed
