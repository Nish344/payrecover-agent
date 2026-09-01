# PayRecover

Detects failed Razorpay one-time payments, diagnoses the cause, and recovers
revenue through bounded actions — payment links, reminders, escalation — with an
audit trail and measured batch recovery.

Built for **Razorpay AI Buildathon 2026**, Track 03 (AI Revenue Recovery).

## Status

Day 4: honest recovered definition, wait-profile fix, correlated audit, sample report.
See [`docs/decisions.md`](docs/decisions.md).

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
| `payrecover seed --seed 42` | Create 80 synthetic failed cases (local DB) |
| `payrecover run [--dry-run] [--limit N] [--inject-timeout]` | Process the batch |
| `payrecover report` | Recovery metrics (markdown + JSON) |
| `payrecover audit <case-id>` | Audit trail for one case |

`--dry-run` is the default path for local measurement. `--inject-timeout --limit 1`
fails the first write with a typed `RazorpayTimeoutError` (no network): one
`action_attempted` + failed `action_result` share a `correlation_id`, and
`link_count` stays 0. `KILL_SWITCH=true` records the policy verdict and refuses the
write. A live test-mode write is `payrecover run --limit 1` with keys in `.env`.

## Sample report (seed 42, dry-run)

Full files: [`reports/sample/report.md`](reports/sample/report.md),
[`reports/sample/report.json`](reports/sample/report.json),
[`reports/sample/audit.txt`](reports/sample/audit.txt) (`c42_02`).

```
# PayRecover report

- Cases: 80
- ₹ at risk: ₹141352.94
- ₹ recovered: ₹44205.18 (35 cases)
- Recovery rate: 31.27%
- Note: recovered = customer_response.kind=paid AND a payment_link_id exists;
  link sent is not recovered. v1 payment is simulated, not settled on Razorpay.

## Outcomes

- escalated: 19
- exhausted: 18
- recovered: 35
- stopped_by_policy: 8

## Exception list (unresolved)

(none)

## Escalations (needs human)

- c42_05  ₹1777.72  cause=ambiguous  rationale=low_confidence
- c42_18  ₹7500.00  cause=international_transaction_not_allowed  rationale=high_amount
```

### Audit replay (`payrecover audit c42_02`)

Wait for bank downtime, then issue a link, then a reminder; customer pays the link.
The paid `customer_response` shares `corr=` with that reminder's attempt/result.

```
diagnosis_completed  case=c42_02  corr=83c29b6e…  cause=bank_downtime  path=rules
policy_verdict       action_type=wait
customer_response    kind=ignored
policy_verdict       action_type=issue_link  amount_paise=74175
action_result        payment_link_id=plink_dry_c42_02_1
customer_response    kind=ignored  (same corr as the link)
policy_verdict       action_type=remind
customer_response    kind=paid  payment_link_id=plink_dry_c42_02_1
case_terminal        outcome=recovered
```

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
5. Recovered = simulated customer paid a recovery **payment link** (`kind=paid` and a
   `payment_link_id`). "Link sent" is not recovered. v1 does not settle the Razorpay
   link on-rail; the report states this explicitly.
6. If the LLM is unavailable, diagnosis falls back to rules and the audit records which path ran.

## Tech stack

Python 3.11+, official `razorpay` SDK (test mode), Anthropic API with a rule fallback,
Pydantic v2, SQLite, Typer, pytest, ruff.

## Decision log

See [`docs/decisions.md`](docs/decisions.md).
