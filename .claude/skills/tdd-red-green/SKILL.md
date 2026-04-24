---
name: tdd-red-green
description: Enforce TDD workflow. Test Designer writes failing tests (Red), Implementer makes them pass (Green). Skill validates correct phase and prevents skipping steps. Used by test_designer and implementer agents.
type: rigid
---

# TDD Red-Green

Enforce Test-Driven Development workflow across two agents.

## Phases

| Phase | Agent | Goal | Validation |
|-------|-------|------|------------|
| **RED** | Test Designer | Write tests that fail | Tests must fail (exit code != 0) |
| **GREEN** | Implementer | Make tests pass | Tests must pass (exit code == 0) |

## When to Use

- Test Designer: Always, before writing any test
- Implementer: Always, before writing any implementation code

## Workflow: RED Phase (Test Designer)

### Step 1: Read Plan

Read `.pipeline/<feature>/plan.md` to understand:
- What functionality to test
- Edge cases mentioned
- Error conditions to cover

### Step 2: Design Test Structure

Before writing tests, outline:
```markdown
## Test Plan for <feature>

### Happy Path
- [ ] Test: [description] → expects [outcome]

### Edge Cases
- [ ] Test: [description] → expects [outcome]

### Error Conditions
- [ ] Test: [description] → expects [error type]
```

Write this to `.pipeline/<feature>/test-plan.md`.

### Step 3: Write Failing Tests

Write tests that:
- Test the PUBLIC interface (not implementation details)
- Are independent (no test depends on another)
- Have descriptive names explaining WHAT is tested
- Cover one behavior per test

Location: `tests/` directory, following project conventions.

### Step 4: Verify RED

Run tests and confirm they fail:
```bash
pytest tests/test_<feature>.py -v
```

**Required outcome:** Exit code != 0 (tests fail)

If tests pass → you wrote tests for existing functionality (wrong) or tests are broken (also wrong). Fix before proceeding.

### Step 5: Output

Write status to test-plan.md:
```markdown
## RED Phase Complete

Tests written: [count]
All tests failing: YES
Failure reasons: [brief - e.g., "function not implemented", "endpoint returns 404"]

STATUS: READY_FOR_IMPLEMENTER
```

---

## Workflow: GREEN Phase (Implementer)

### Step 1: Verify Starting State

Run tests first:
```bash
pytest tests/test_<feature>.py -v
```

**Required:** Tests must fail. If they pass, something is wrong — investigate before proceeding.

### Step 2: Read Test Intentions

Read each test to understand:
- What behavior is expected
- What inputs/outputs are specified
- What errors should be raised

Do NOT read test implementation details as a "spec" — tests describe WHAT, you decide HOW.

### Step 3: Implement Minimal Code

Write the simplest code that makes tests pass:
- No extra features
- No premature optimization
- No "while I'm here" additions

### Step 4: Run Tests Incrementally

After each logical change:
```bash
pytest tests/test_<feature>.py -v
```

Track progress:
- X of Y tests passing
- Which tests still fail and why

### Step 5: Verify GREEN

All tests must pass:
```bash
pytest tests/test_<feature>.py -v
```

**Required outcome:** Exit code == 0 (all tests pass)

### Step 6: Check for Test Modifications

**CRITICAL:** Diff your changes against test files:
```bash
git diff tests/
```

If you modified tests written by Test Designer:
- Document WHY in commit message
- Flag for gate review (QA Validator will check)

Allowed modifications:
- Fixing objectively wrong assertions (e.g., typo in expected value)
- Adding imports the test needs

Forbidden modifications:
- Changing expected behavior to match your implementation
- Removing tests that are "too hard"
- Weakening assertions

### Step 7: Output

Update `.pipeline/<feature>/impl-report.md`:
```markdown
## GREEN Phase Complete

Tests passing: [count]/[total]
Implementation files: [list]
Test modifications: [none | list with justification]

STATUS: READY_FOR_SECURITY_REVIEWER
```

---

## Gate Validation

The QA Validator will check:
- [ ] Test Designer's tests were not weakened
- [ ] Implementation matches plan requirements
- [ ] No untested code paths added
- [ ] Coverage meets threshold

## Anti-Patterns to Avoid

| Anti-Pattern | Why It's Wrong |
|--------------|----------------|
| Writing tests after implementation | Tests confirm bias, don't catch bugs |
| Writing tests that pass immediately | Not testing anything meaningful |
| Implementing more than tests require | Scope creep, untested code |
| Modifying tests to pass | Defeats the purpose of TDD |
| Skipping RED verification | Can't know if tests actually test anything |
| One giant test | Hard to debug, unclear what's tested |

## Cost Estimate

No additional LLM cost — this skill is workflow enforcement, not LLM-based review.
