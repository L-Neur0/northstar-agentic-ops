# 16 · Access: visitor key, workspace code, limits

> **Status:** built · **Implements:** F-21 (product), architecture §3.5 · **Depends on:** specs 10, 11, 15
> **Code:** `backend/app/core/access.py`, `backend/app/core/rate_limit.py` · **Tests:** `backend/tests/unit/core/test_access.py`, `test_rate_limit.py`, `backend/tests/api/test_access_routes.py`

## 1. Purpose

Let anyone with the link start a discovery session without an account, keep each expert's sessions private to them, keep the admin side behind an access code, and protect the open link (and the model budget) from abuse. Company sign-in is a production item (production readiness).

## 2. Where it sits

- **Layer:** `app/core` (shell), used by the routes as FastAPI dependencies. The engine never sees keys or tokens, only `owner_id`.
- **Exists:** settings `WORKSPACE_CODE_SPECIALIST`, `WORKSPACE_CODE_ENGINEER`, `WORKSPACE_TOKEN_SECRET`, `RATE_LIMIT_PER_VISITOR`, `RATE_LIMIT_PER_IP`, `DAILY_TOKEN_BUDGET` (spec 10, with the demo-stage checks); the LLM client's `budget_guard` and `usage_hook` (spec 11); slowapi installed.

## 3. Behaviour

### 3.1 Visitor key (experts)

1. The frontend creates a random 128-bit key on the first visit (URL-safe base64, 22 characters), keeps it in `localStorage`, and sends it on every expert call as `X-Visitor-Key`.
2. The server accepts a key of 22–64 characters from `[A-Za-z0-9_-]`; anything else → 401 `visitor_key_required`.
3. `owner_id = sha256(key)` in hex. The key itself is never stored or logged; logs carry the first 8 characters of `owner_id`.
4. **Resume link:** the frontend shows `https://<host>/#k=<key>`; opening it stores that key (the fragment never reaches the server). Whoever has the link sees those sessions; the screen says so.

### 3.2 Workspace token (specialists, engineers)

1. `POST /api/workspace/login {code, name}` (`name` 1–40 characters, shown on edits and in the audit log). The code is compared in constant time with the specialist and engineer codes; no match → 401 `workspace_code_invalid` (same message for both, no hint which part was wrong).
2. Success returns `{token, role, name, expiresAt}`. The token is `base64url(payload).base64url(hmac_sha256(secret, payload))`, payload `{role, name, exp}`; lifetime 8 hours.
3. Workspace routes require `Authorization: Bearer <token>`; missing, malformed, wrong signature or expired → 401 `workspace_code_required`; a valid token with the wrong role → 403 `forbidden`. Engineers reach only brief routes (spec 21).
4. Login attempts are rate-limited per IP (5 per minute).

### 3.3 Rate limits

| Limit | Key | Default | Over the limit |
|---|---|---|---|
| Expert calls | `owner_id` | `RATE_LIMIT_PER_VISITOR` = 30/minute | 429 `rate_limited` |
| All calls | client IP (the last hop added by the platform's proxy, `X-Forwarded-For` taken only from the trusted proxy) | `RATE_LIMIT_PER_IP` = 120/minute | 429 `rate_limited` |
| Workspace login | client IP | 5/minute | 429 `rate_limited` |

slowapi with in-memory storage (one replica, architecture §10). `/api/health` is not limited.

### 3.4 Daily model budget

1. `BudgetTracker` counts tokens (input + output) per UTC day in memory.
2. Its `guard(call_type)` returns `False` when the day's total is at or above `DAILY_TOKEN_BUDGET` (0 = unlimited); its `record(usage)` adds a call's tokens. Both are passed to the LLM client (spec 11), which raises `LLMBudgetExceededError` when refused; the service maps it to 429 `budget_exhausted` (spec 15).
3. The day resets at 00:00 UTC. A log line is written once when 80 % and 100 % are reached.
4. The tracker also adds the call's tokens to the session's `cost` (spec 15 service).

## 4. Interfaces

```python
# app/core/access.py
def owner_from_key(key: str) -> str                      # validates, returns sha256 hex; raises AccessError
async def require_visitor(request) -> str                 # FastAPI dependency → owner_id
class WorkspaceUser(NamedTuple): role: Literal["specialist", "engineer"]; name: str
def issue_token(role, name, *, secret, now, ttl_seconds=28800) -> tuple[str, str]   # (token, expiresAt)
def read_token(token, *, secret, now) -> WorkspaceUser    # raises AccessError(code)
def require_role(*roles) -> Callable                       # dependency factory → WorkspaceUser
class AccessError(Exception): code: str; status: int

# app/core/rate_limit.py
def build_limiter(settings) -> Limiter
class BudgetTracker:
    def __init__(self, daily_limit: int, clock): ...
    def guard(self, call_type) -> bool
    def record(self, usage) -> None
    def snapshot(self) -> dict                            # {day, used, limit}

# app/api/workspace_routes.py (login only in this spec; the rest is spec 21)
POST /api/workspace/login
```

## 5. Implications

- **Frontend (spec 23):** generates and stores the key, sends `X-Visitor-Key`, shows the resume link; the workspace gate stores the token in `sessionStorage`.
- **Security:** keys never logged or stored; codes compared in constant time; tokens signed and short-lived; demo stage refuses default codes and secret (spec 10).
- **Production:** replaced by Entra ID sign-in (production readiness §2).

## 6. Acceptance criteria

| ID | Given / when / then |
|---|---|
| AC-16.1 | An expert route without `X-Visitor-Key`, or with a key of the wrong length or characters, returns 401 `visitor_key_required` |
| AC-16.2 | The same key always gives the same `owner_id` (sha256 hex); two keys give different ids |
| AC-16.3 | The key appears in no stored document and no log line |
| AC-16.4 | Two visitors cannot see each other's sessions (404), through every expert route |
| AC-16.5 | `workspace/login` with the specialist code returns a token with role `specialist`, the given name and an expiry 8 h ahead; the engineer code gives role `engineer` |
| AC-16.6 | A wrong code returns 401 `workspace_code_invalid` with the same message for any wrong input |
| AC-16.7 | Codes are compared with `hmac.compare_digest` |
| AC-16.8 | A tampered, malformed or expired token returns 401 `workspace_code_required`; a valid engineer token on a specialist-only route returns 403 `forbidden` |
| AC-16.9 | More than 30 expert calls a minute from one visitor return 429 `rate_limited`; another visitor is not affected |
| AC-16.10 | More than 5 login attempts a minute from one IP return 429 |
| AC-16.11 | `/api/health` is never rate-limited |
| AC-16.12 | `BudgetTracker.guard` is true below the limit and false at or above it; `record` adds input + output tokens; 0 means unlimited |
| AC-16.13 | The budget resets at the next UTC day |
| AC-16.14 | With the budget used up, a message returns 429 `budget_exhausted` and no model request is made |
| AC-16.15 | One log line at 80 % and one at 100 % of the budget per day, not more |
| AC-16.16 | Only the trusted proxy's `X-Forwarded-For` hop is used for the IP; a client-supplied header cannot change the key |

## 7. Test plan

| Test file | Covers |
|---|---|
| `tests/unit/core/test_access.py` | AC-16.2, 16.3, 16.5–16.8 |
| `tests/unit/core/test_rate_limit.py` | AC-16.12, 16.13, 16.15, 16.16 |
| `tests/api/test_access_routes.py` | AC-16.1, 16.4, 16.9–16.11, 16.14 |

## 8. Out of scope

Entra ID sign-in, per-user quotas, shared rate-limit storage for several replicas (production readiness).

## 9. Open questions

| # | Question | Default |
|---|---|---|
| Q1 | Token lifetime | 8 hours |
| Q2 | Should the resume link be shown by default or behind a button? | Behind a "Continue on another device" button |
