# Security Checklist

Execute each check against the code diff. Document findings immediately.

---

## 1. IDOR (CWE-639)

**Check all endpoints that return or modify resources:**

For each endpoint in the diff:
- [ ] Does it verify the requesting user owns/can access the resource?
- [ ] Is the check performed BEFORE any data is returned?
- [ ] Can a user access another user's data by changing an ID?

**Red flags:**
```python
# BAD: No ownership check
@router.get("/items/{item_id}")
async def get_item(item_id: int):
    return await db.get_item(item_id)

# GOOD: Ownership verified
@router.get("/items/{item_id}")
async def get_item(item_id: int, user: User = Depends(get_current_user)):
    item = await db.get_item(item_id)
    if item.user_id != user.id:
        raise HTTPException(403)
    return item
```

**Test mentally:** "If I change item_id to someone else's ID, what happens?"

---

## 2. RLS Policies

**Check all new or modified tables:**

For each table:
- [ ] Does it have RLS enabled?
- [ ] Do policies match the endpoint authorization logic?
- [ ] Are there any SELECT/INSERT/UPDATE/DELETE without policy coverage?

**Red flags:**
```sql
-- BAD: No RLS
CREATE TABLE items (
    id SERIAL PRIMARY KEY,
    user_id INT,
    data TEXT
);

-- GOOD: RLS enabled
CREATE TABLE items (
    id SERIAL PRIMARY KEY,
    user_id INT,
    data TEXT
);
ALTER TABLE items ENABLE ROW LEVEL SECURITY;
CREATE POLICY items_user_policy ON items
    USING (user_id = current_setting('app.user_id')::int);
```

**Cross-check:** Does the endpoint set the correct user context before queries?

---

## 3. JWT Flow

**Check any auth-related code:**

- [ ] Token signature verified (not just decoded)?
- [ ] Expiration checked (`exp` claim)?
- [ ] Algorithm pinned (no `alg: none` attack)?
- [ ] Refresh tokens handled securely (rotated, stored safely)?
- [ ] Logout invalidates tokens (if applicable)?

**Red flags:**
```python
# BAD: No verification
payload = jwt.decode(token, options={"verify_signature": False})

# BAD: Algorithm not pinned
payload = jwt.decode(token, secret, algorithms=["HS256", "none"])

# GOOD
payload = jwt.decode(token, secret, algorithms=["ES256"])
```

---

## 4. Secrets in Code/Logs

**Scan all changed files:**

- [ ] No hardcoded API keys, passwords, tokens?
- [ ] No secrets in comments or docstrings?
- [ ] No secrets in log statements?
- [ ] No secrets in error messages returned to users?
- [ ] All secrets loaded from env vars?

**Red flags:**
```python
# BAD: Hardcoded
api_key = "sk-1234567890abcdef"

# BAD: Logged
logger.debug(f"Calling API with key: {api_key}")

# BAD: In error response
raise HTTPException(500, f"API call failed with key {api_key[:4]}...")

# GOOD
api_key = os.environ["API_KEY"]
logger.debug("Calling external API")
```

**Grep patterns:**
```bash
grep -rn "password\s*=" --include="*.py"
grep -rn "api_key\s*=" --include="*.py"
grep -rn "secret\s*=" --include="*.py"
grep -rn "token\s*=" --include="*.py"
```

---

## 5. Input Validation (CWE-20)

**Check all external inputs:**

- [ ] Pydantic models for request bodies?
- [ ] Path/query params validated?
- [ ] String length limits?
- [ ] Array size limits?
- [ ] Numeric range limits?
- [ ] Enum values validated?

**SQL Injection (CWE-89):**
- [ ] All queries parameterized?
- [ ] No string concatenation in SQL?

**XSS (CWE-79):**
- [ ] User input escaped before rendering?
- [ ] Content-Type headers correct?

**Red flags:**
```python
# BAD: No validation
@router.post("/items")
async def create_item(data: dict):
    await db.execute(f"INSERT INTO items VALUES ('{data['name']}')")

# GOOD
class ItemCreate(BaseModel):
    name: str = Field(max_length=255)

@router.post("/items")
async def create_item(data: ItemCreate):
    await db.execute("INSERT INTO items VALUES ($1)", data.name)
```

---

## 6. DSGVO / Data Protection

**For any code handling user data:**

### 6.1 Data Identification
- [ ] What personal data is processed?
- [ ] Is it documented in the plan/spec?

### 6.2 Data Minimization
- [ ] Only necessary fields collected?
- [ ] No "might need later" fields?

### 6.3 Logging
- [ ] No PII in logs?
- [ ] User IDs logged instead of emails/names?

### 6.4 Retention
- [ ] Deletion path exists or documented as out of scope?
- [ ] No indefinite storage of personal data?

### 6.5 Third Parties
- [ ] If data sent to external APIs: is there a DPA/AVV?
- [ ] Documented which data is sent where?

**Red flags:**
```python
# BAD: PII in logs
logger.info(f"User {user.email} performed action")

# GOOD
logger.info(f"User {user.id} performed action")

# BAD: Unnecessary data
class UserCreate(BaseModel):
    email: str
    name: str
    phone: str  # Not needed for this feature
    address: str  # Not needed for this feature
```

---

## Output Format

For each finding:

```markdown
### [CHECK_ID] [Brief Title]

- **Severity:** CRITICAL / HIGH / MEDIUM / LOW
- **CWE:** CWE-XXX
- **Location:** path/to/file.py:123
- **Code:**
  ```python
  # The problematic code
  ```
- **Issue:** What's wrong
- **Impact:** What could happen
- **Fix:** Specific remediation
```

If a check passes with no findings, note:
```markdown
### [CHECK_ID] ✓ No issues found
```
