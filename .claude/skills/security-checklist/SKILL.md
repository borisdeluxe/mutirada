---
name: security-checklist
description: Structured security review for code changes. Checks IDOR, RLS, JWT, secrets, input validation, DSGVO compliance. Produces security-report.md with findings classified by CWE. Used by security_reviewer agent.
type: rigid
---

# Security Checklist

Systematic security review of code changes before QA and deployment.

## When to Use

- Security Reviewer agent reviewing Implementer's code diff
- Before any code reaches QA Validator
- Mandatory for: new endpoints, auth changes, database schema changes, external API integrations

## Inputs

- Code diff from Implementer (git diff)
- `.pipeline/<feature>/plan.md` (context)
- `.pipeline/<feature>/impl-report.md` (what was implemented)
- Existing security patterns from CLAUDE.md

## Workflow

### Step 1: Scope Assessment

Determine review depth based on changes:

| Change Type | Review Depth |
|-------------|--------------|
| New endpoint | FULL (all checks) |
| Auth/permission changes | FULL + extra JWT focus |
| Database schema changes | FULL + extra RLS focus |
| Internal refactor only | LIGHT (secrets + input validation only) |
| Config/env changes | SECRETS focus |

### Step 2: Run Checklist

Execute each check from `prompts/checklist.md`. For each finding:

```markdown
### [CHECK_ID] Finding

- **Severity:** CRITICAL / HIGH / MEDIUM / LOW / INFO
- **CWE:** CWE-XXX (if applicable)
- **Location:** file:line
- **Description:** What the issue is
- **Impact:** What could happen if exploited
- **Remediation:** Specific fix required
- **Verified:** [ ] (QA will verify fix)
```

### Step 3: Cross-Reference Plan

Check that security considerations from plan.md are addressed:
- Were auth requirements implemented?
- Were mentioned edge cases handled?
- Are error messages safe (no information leakage)?

### Step 4: DSGVO Quick Check

For any code handling user data:
- [ ] Personal data identified and documented
- [ ] Data minimization applied (only necessary fields)
- [ ] No PII in logs
- [ ] Retention/deletion path exists or is out of scope

### Step 5: Generate Report

Write `.pipeline/<feature>/security-report.md`:

```markdown
# Security Report: <feature>

## Summary
- Scope: [FULL / LIGHT]
- Findings: [X CRITICAL, Y HIGH, Z MEDIUM, W LOW]
- Gate Recommendation: [PASS / FAIL]

## Findings

### CRITICAL
[findings or "None"]

### HIGH
[findings or "None"]

### MEDIUM
[findings or "None"]

### LOW
[findings or "None"]

## DSGVO Compliance
[assessment]

## Checks Performed
- [x] IDOR on endpoints
- [x] RLS policies
- [x] JWT flow
- [x] Secrets in code/logs
- [x] Input validation
- [x] DSGVO data handling

## Gate Decision
[PASS: No CRITICAL/HIGH findings]
[FAIL: CRITICAL or HIGH findings present]

STATUS: READY_FOR_QA_VALIDATOR
```

### Step 6: Gate Decision

| Condition | Decision |
|-----------|----------|
| 0 CRITICAL + 0 HIGH | **PASS** |
| 0 CRITICAL + 1-2 HIGH (with clear fix) | **CONDITIONAL_PASS** (fix before deploy) |
| Any CRITICAL | **FAIL** |
| 3+ HIGH | **FAIL** |

For CONDITIONAL_PASS: QA Validator must verify fixes before deploy handoff.

---

## Checklist Reference

Detailed checks are in `prompts/checklist.md`. Summary:

### 1. IDOR (Insecure Direct Object Reference)
- All /v1/ endpoints check ownership before returning data
- User can only access their own resources
- No sequential ID enumeration possible

### 2. RLS (Row Level Security)
- New tables have RLS policies
- Policies match endpoint authorization logic
- No bypass via direct SQL

### 3. JWT Flow
- Tokens validated on every request
- ES256 or HS256 as documented
- Expiration enforced
- Refresh flow secure

### 4. Secrets
- No hardcoded API keys, passwords, tokens
- No secrets in logs (even debug level)
- Env vars used for all secrets
- No secrets in error messages

### 5. Input Validation
- Pydantic models for all inputs
- Type coercion explicit
- Size limits on strings/arrays
- SQL injection prevention (parameterized queries)
- XSS prevention (output encoding)

### 6. DSGVO
- Personal data fields identified
- Consent/legal basis documented
- No unnecessary data collection
- Deletion path exists

---

## CWE Reference

Common findings mapped to CWE:

| Issue | CWE |
|-------|-----|
| IDOR | CWE-639 |
| Missing auth | CWE-306 |
| Broken access control | CWE-284 |
| SQL injection | CWE-89 |
| XSS | CWE-79 |
| Hardcoded credentials | CWE-798 |
| Sensitive data in logs | CWE-532 |
| Missing input validation | CWE-20 |
| Insecure JWT | CWE-347 |

## Cost Estimate

~$0.05-0.10 per review (single Sonnet pass, focused scope)
