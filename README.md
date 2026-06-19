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

**Implemented in the prototype (auth simulated, authorization real):**
- **RBAC**, default-deny, on every protected endpoint. Missing/invalid creds → 401.
- **Per-agent data isolation** — an agent cannot read/act on another agent's borrower (403);
  error messages don't reveal whether the borrower exists elsewhere.
- **Escalation is supervisor-only**; audit log is supervisor-only.
- **Rate limiting** (`slowapi`, default 30/min per caller) to resist being overwhelmed.
- **Strict input validation** (Pydantic `extra="forbid"`) rejects unexpected/oversized fields.
- **PII redaction** before any LLM call; **no PII in logs or client error messages**.
- **Prompt-injection defence**: borrower free text is sanitised and passed as clearly-fenced
  *untrusted data*; the LLM only emits message text and cannot alter a decision.
- **Output safety filter** blocks threatening/harassing language and leaked PII → safe template.
- **Audit log** records actor, role, borrower, event, timestamp.

**How this maps to production (documented, not built):**
- Identity via OAuth2/OIDC + signed JWT instead of trusted headers.
- Data isolation via database **row-level security** keyed on the agent's portfolio.
- Sensitive fields **encrypted at rest** (KMS); decrypted only for authorized roles.
- Audit log as an **append-only** store/sink; PII tokenised.
- Rate limiting + WAF at the gateway; secrets from a managed secret store.

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

## Project layout
```
app/
  main.py          FastAPI app + endpoints (auth, rate limit, audit wiring)
  models.py        Pydantic schemas (strict validation)
  segmentation.py  deterministic segment rules + reasons
  strategy.py      action mapping, channel/time, recovery score, priority
  engine.py        composes segmentation + strategy + message
  message_gen.py   LLM wrapper client + safe template fallback
  safety.py        PII redaction, injection sanitisation, output filter
  auth.py          mocked RBAC + data isolation
  audit.py         in-memory audit log
  config.py        env-based config (no secrets in code)
  store.py         loads & validates synthetic data
  data/borrowers.json
tests/             45 tests (segmentation, strategy, safety, API/RBAC, bonus)
```

## Testing
`uv run pytest` — covers every segment rule and the hardship tie-breaker, strategy/recovery
logic, PII redaction + injection sanitisation + output safety + LLM fallback paths, and the
API's auth/isolation/rate-limit/error behaviour.
```
