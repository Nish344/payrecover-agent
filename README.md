# PayRecover

Detects failed Razorpay one-time payments, diagnoses the cause, and recovers
revenue through bounded actions — payment links, reminders, escalation — with an
audit trail and measured batch recovery.

Built for **Razorpay AI Buildathon 2026**, Track 03 (AI Revenue Recovery).

## Status

Day 1 complete: test-mode ping, one real failed payment, paper audit/policy/behavior
spec in [`docs/decisions.md`](docs/decisions.md). Policy, diagnosis, audit writer, and
metrics code are next.

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env   # then fill RAZORPAY_KEY_ID / RAZORPAY_KEY_SECRET (test keys only)
payrecover ping
```

## Commands

| Command | What it does |
|---|---|
| `payrecover ping` | Authenticated test-mode read; verifies keys |
| `payrecover seed` | Synthetic batch (not wired yet) |
| `payrecover run` | End-to-end recovery loop (not wired yet) |
| `payrecover report` | Recovery metrics report (not wired yet) |
| `payrecover audit <case-id>` | Audit trail for one case (not wired yet) |

## Architecture

```
                 ┌────────────────────────────────────────────────┐
                 │                  runner (orchestrator)          │
                 └────────────────────────────────────────────────┘
   batchgen ──▶ detector ──▶ diagnosis ──▶ policy ──▶ actions ──▶ Razorpay test API
 (synthetic       (failed      (LLM +      (gates,     (link /
  cases +          payments)    rule        caps,       remind /
  ground-truth                  fallback)   stops)      wait /
  profiles)                                             escalate /
                                                        stop)
        │                          │            │          │
        └──────────────────────────┴─────┬──────┴──────────┘
                                         ▼
                              audit trail (append-only)
                                         ▼
                              metrics ──▶ reports/ (md + json)
```

One-time card/UPI failures cannot be silently re-charged. Recovery means getting the
customer to act again: issue a payment link, remind (capped), wait, escalate, or stop.

### Layout

```
src/payrecover/
  config.py            # env + settings
  models.py            # Case, Diagnosis, Action, AuditEvent, Outcome
  razorpay_client.py   # Orders, Payments, Payment Links (test mode)
  detector.py          # failed payments → Case
  diagnosis.py         # LLM + rule fallback → cause, confidence, rationale
  policy.py            # allowed actions, caps, stopping rules, escalation
  actions.py           # executes only what policy returns
  audit.py             # append-only audit log
  metrics.py           # recovery rate, outcomes, exception list
  runner.py            # batch loop
  cli.py               # payrecover seed | run | report | audit
  simulator/
    batchgen.py
    customer.py
tests/
docs/decisions.md
reports/
```

### Invariants

1. Every action passes through `policy.py`. Only `actions.py` calls Razorpay write APIs.
2. Every decision is audited, including waits and stops.
3. Caps: max 2 payment links and max 3 reminders per case; link amount equals the
   original order; opt-out is a permanent stop; escalate when confidence &lt; 0.6 or
   amount &gt; ₹5,000; `KILL_SWITCH=true` stops all execution.
4. Re-running a batch must not duplicate links or reminders.
5. Recovered = the customer actually paid the link in test mode. "Link sent" is not recovered.
6. If the LLM is unavailable, diagnosis falls back to rules and the audit records which path ran.

## Tech stack

Python 3.11+, official `razorpay` SDK (test mode), Anthropic API with a rule fallback,
Pydantic v2, SQLite, Typer, pytest, ruff.

## Decision log

See [`docs/decisions.md`](docs/decisions.md).
