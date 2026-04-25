---
name: docs-update
description: Use after implementation is complete to update documentation
---

# Documentation Update

Update public documentation after feature implementation.

<HARD-GATE>
NEVER document internal/admin APIs in public documentation. Security review MUST approve any new endpoint documentation.
</HARD-GATE>

## Checklist

1. **Identify doc changes needed** — What was added/changed?
2. **Security classification** — Is this public or internal?
3. **Update relevant docs** — API docs, guides, changelog
4. **Verify no secrets/internal info** — Final security check
5. **Commit doc changes** — Separate commit from code

## Security Classification

| Type | Public Docs | Internal Only |
|------|-------------|---------------|
| Public API endpoints (`/v1/*`) | ✅ Document | — |
| Admin endpoints (`/admin/*`) | ❌ NEVER | ✅ Internal wiki |
| Internal endpoints (`/internal/*`) | ❌ NEVER | ✅ Internal wiki |
| API Keys, Secrets | ❌ NEVER | ❌ NEVER |
| Infrastructure details | ❌ NEVER | ✅ Internal wiki |
| Rate limits, pricing | ✅ Document | — |
| Error codes (public) | ✅ Document | — |
| Error codes (internal) | ❌ NEVER | ✅ Internal wiki |

## Before Documenting an Endpoint

Ask yourself:
1. Is this endpoint meant for external developers?
2. Does documenting it expose attack surface?
3. Would a malicious actor benefit from this info?
4. Is there sensitive business logic revealed?

**If ANY answer is "yes" or "maybe" → Do NOT document publicly.**

## Falara-Specific Rules

**Document in falara-api-docs:**
- `/v1/translate` — Public translation API
- `/v1/languages` — Supported languages
- `/v1/usage` — Usage statistics for API key owner
- Webhook formats
- Error codes and handling
- Rate limits and quotas

**NEVER document publicly:**
- `/admin/*` — All admin endpoints
- `/internal/*` — Service-to-service
- `/v1/*/debug` — Debug endpoints
- Database schemas
- Internal queue formats
- Provider API keys/configs
- Billing internals

## Doc Update Format

```markdown
## Changelog Entry

### [Version] - YYYY-MM-DD

#### Added
- `POST /v1/translate` now supports `metadata` parameter (#FAL-47)

#### Changed
- Rate limit increased to 100 req/min for Pro tier

#### Deprecated
- `format` parameter in `/v1/translate` (use `output_format` instead)
```

## Output

Last line MUST be one of:
- `STATUS: READY_FOR_QA_VALIDATOR` — Docs updated, ready for review
- `STATUS: DOCS_NOT_NEEDED` — No public-facing changes
- `STATUS: BLOCKED_SECURITY_REVIEW` — Needs security approval before documenting
