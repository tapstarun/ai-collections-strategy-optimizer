# AI-Based Collections Strategy Optimizer

An AI-assisted collections strategy assistant for a fintech lender. For each delinquent
borrower it **segments** them, recommends the **next best action**, suggests the **best
channel & time**, estimates **recovery probability**, drafts a **respectful customer
message**, and **explains** every decision.

> **Core design principle — "Deterministic core, LLM at the edge."**
> Transparent rules make every *financial* decision (segment, action, timing, recovery
> score) so they are explainable and auditable. The LLM is used **only** to phrase the
> customer message, grounded in those decisions. A hallucination or prompt injection can
> therefore never change who gets escalated or how a hardship case is treated — the worst
> case is bad message text, which a safety filter catches and replaces with a safe template.

---

## Quick start

Using **uv** (recommended — fast, reproducible via `uv.lock`):

```bash
uv sync --extra dev                       # create env + install deps
cp .env.example .env                      # optional: add LLM_API_TOKEN for real LLM
uv run uvicorn app.main:app --reload      # open http://127.0.0.1:8000/docs
uv run pytest                             # run the test suite (45 tests)
```

Or with plain **pip**:

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload
pytest
```

Without `LLM_API_TOKEN`, message generation falls back to safe templates, so the app runs
fully offline. The interactive Swagger UI at `/docs` is the UI deliverable.

### Authentication for trying it out

Every protected endpoint needs two (mocked) headers:

| Header | Example | Meaning |
|---|---|---|
| `X-Agent-Id` | `agent_a` | the caller's identity / portfolio |
| `X-Role` | `agent` or `supervisor` | role for RBAC |

In Swagger, click **Authorize** or add the headers per request. In the sample data,
`agent_a` owns borrowers `B001–B005` and `agent_b` owns `B006–B010`.

---

## Architecture

```
Request (borrower id + role headers)
        │
        ▼
  Auth / RBAC + rate limit        (auth.py, slowapi)  ── default-deny, per-agent isolation
        │
        ▼
  DETERMINISTIC CORE              (segmentation.py, strategy.py, engine.py)
   • segment  + reasons
   • next-best-action + reasons
   • best channel & time
   • recovery probability + reasons
        │  decision + grounded facts
        ▼
  LLM AT THE EDGE                 (message_gen.py + safety.py)
   redact PII → call wrapper → safety-filter output → fallback to safe template
        │
        ▼
  Audit log                       (audit.py)  ── who / what / which borrower / when
```

Why this design: in regulated lending every decision must be explainable and defensible.
Letting an LLM decide segments/escalation would be non-deterministic and unauditable; using
only templates would fail the "AI-generated empathetic communication" requirement. The hybrid
gets both — and contains the LLM's risk to message text only.

---

## API

| Method & path | Purpose | Access |
|---|---|---|
| `GET /health` | Liveness check | open |
| `POST /borrowers/{id}/strategy` | Full recommendation + message draft | own portfolio / supervisor |
| `GET /borrowers/{id}/explain` | "Why is this borrower assigned to X?" | own portfolio / supervisor |
| `GET /queue` | Workload, ranked by expected recoverable value | scoped by role |
| `POST /borrowers/{id}/execute` | Record an action (**mock — nothing is sent**) | own portfolio; escalation = supervisor |
| `GET /audit` | Audit trail of executed actions | supervisor only |

---

## Data schema

Borrower record (see `app/data/borrowers.json`, validated by `app/models.py`):

| Field | Type | Notes |
|---|---|---|
| `borrower_id` | str | unique id |
| `name` | str | only the first name is ever sent to the LLM |
| `assigned_agent_id` | str | portfolio owner — basis for data isolation |
| `days_past_due` | int ≥ 0 | delinquency stage |
| `overdue_amount` | float ≥ 0 | outstanding balance |
| `preferred_channel` | enum | `sms` \| `email` \| `call` |
| `prior_late_payments` | int ≥ 0 | habitual-pattern signal |
| `promises_made` / `promises_kept` | int ≥ 0 | reliability signal (recovery score) |
| `hardship_indicator` | bool | takes priority over all other signals |
| `contact_history` | list | `{channel, responded, hour}` — drives channel/time learning |
| `notes` | str? | **untrusted free text** — sanitised & redacted before any LLM use |

### Segments → actions

| Segment | Rule (first match wins) | Next best action |
|---|---|---|
| Hardship Case | `hardship_indicator` true | hardship support |
| High-Risk Escalation | DPD ≥ 90, or large balance + no response | escalation |
| Unresponsive | contacted but never responded | agent call |
| Habitual Late Payer | ≥ 3 prior late payments | SMS reminder |
| Willing but Delayed | DPD ≤ 30 and has responded | SMS reminder (payment plan if balance ≥ 10k) |
| Manual Review | nothing overdue, or signals unclear | manual review |

Rule order is **borrower-protective**: hardship is checked first so a struggling customer is
never routed to escalation.

### Recovery probability

Transparent heuristic (not ML), starting at 60 and adjusted by promise-kept rate,
engagement, delinquency depth, and hardship; clamped to 0–100. Every adjustment is returned
in `reasons`. Workload priority = `recovery_probability × overdue_amount` (expected
recoverable value).

---

## Security & privacy

**Implemented in the prototype (authorization is real; identity is mocked):**
- **RBAC**, default-deny, on every protected endpoint. Missing/invalid creds → 401.
- **Optional API-key gate** — set `API_KEY` and all protected endpoints require a matching
  `X-API-Key` header (constant-time compare); `/health` stays open.
- **Per-agent data isolation** — an agent cannot read/act on another agent's borrower. To an
  agent, a not-in-portfolio borrower returns the **same 404** as a non-existent one, so the
  API is not an enumeration oracle. (Supervisors see all.)
- **Escalation is supervisor-only**; audit log is supervisor-only.
- **Rate limiting** keyed on **client IP** (not the spoofable `X-Agent-Id`) so an attacker
  cannot rotate a header to bypass it.
- **Strict input validation** (Pydantic `extra="forbid"`) rejects unexpected/oversized fields;
  a model validator rejects impossible data (e.g. `promises_kept > promises_made`).
- **Data minimisation to the LLM** — only a sanitised **first name** is sent (never the
  surname); PII is redacted before any LLM call; **no PII in logs or client error messages**.
- **Prompt-injection defence**: borrower free text has whitespace normalised (defeats
  `ignore   all   previous   instructions`-style evasion), trigger phrases stripped, and is
  passed as clearly-fenced *untrusted data*. The LLM only emits message text and cannot alter
  a decision; its output is re-scanned and unsafe replies fall back to a safe template.
- **Audit log** records actor, role, borrower, event, timestamp.

### Threat model & known limitations (honest)
- **Trusted-header identity is the main caveat.** `X-Agent-Id` / `X-Role` are client-supplied
  and therefore **spoofable** — in this prototype a caller can claim `supervisor`. This is an
  accepted property of a *mock*, not a secure auth system. The optional `API_KEY` narrows the
  surface but is not per-user identity.
- The injection scrubber and output filter are pattern-based — useful guardrails, not a
  complete content-moderation/jailbreak defence. The real protection is architectural: the LLM
  can never change a financial decision.

**How this maps to production (documented, not built):**
- Identity via OAuth2/OIDC + **signed JWT**; role claims come from the verified token, not
  headers. The authorization functions stay essentially unchanged.
- Data isolation via database **row-level security** keyed on the agent's portfolio.
- Sensitive fields **encrypted at rest** (KMS); decrypted only for authorized roles.
- Audit log as an **append-only** store/sink; PII tokenised.
- Rate limiting + WAF at the gateway (on authenticated identity); secrets from a managed
  secret store.

---

## Assumptions
- Synthetic data; no real telephony/SMS/email/payment integrations (per the brief).
- `execute` is a **mock** — it records intent in the audit log and sends nothing.
- Legal/compliance workflows are simplified; thresholds are illustrative and centralised in
  `segmentation.py` / `strategy.py` for easy tuning.
- The provided LLM wrapper accepts `{"prompt": ...}`; response text is read tolerantly across
  common field names, with a template fallback if the shape differs.

## Limitations
- Rules are hand-tuned, not learned — the decision layer is intentionally isolated so a
  calibrated risk model could replace it behind the same `(segment, reasons)` contract.
- In-memory store and audit log (reset on restart); not multi-instance safe as-is.
- The output safety filter is keyword/pattern based — a useful guardrail, not a complete
  content-moderation system.


## Testing
`uv run pytest` — covers every segment rule and the hardship tie-breaker, strategy/recovery
logic, PII redaction + injection sanitisation + output safety + LLM fallback paths, and the
API's auth/isolation/rate-limit/error behaviour.

