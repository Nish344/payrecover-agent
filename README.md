# PayRecover

Detects failed Razorpay one-time payments, diagnoses the cause, and recovers
revenue through bounded actions — payment links, reminders, escalation — with an
audit trail and measured batch recovery.

Built for **Razorpay AI Buildathon 2026**, Track 03 (AI Revenue Recovery).

**v1 frozen 2026-09-02.** Code freeze is 2026-09-03. The slice is finished: no
checkout drop-off, mandate retries, or extra surface.

## Status

Frozen for the pitch video. The committed headline is a **rules-only** seed 42
dry-run (`GEMINI_API_KEY` unset): **₹44,205.18 of ₹141,352.94** (31.27%, 35 of
80 cases). Of the 46 customers who would pay given the right actions, **35 were
captured (76.09%)**. Recovered means a simulated customer paid a recovery
payment link — not "link sent", and not settled on the Razorpay rail.

[`reports/sample/llm-audit.txt`](reports/sample/llm-audit.txt) is a **separate**
one-case Gemini run of `c42_05`. It is not the source of 31.27%.

See [`docs/decisions.md`](docs/decisions.md).

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env   # Razorpay test keys; leave GEMINI_API_KEY empty for the headline run
payrecover ping
payrecover seed --seed 42
payrecover run                 # dry-run (default; no Razorpay writes)
payrecover report
payrecover audit c42_02
```

`payrecover report` scores **every case in the database**. Run `detect` only
after you have captured the 80-case report (or use a fresh `DB_PATH`). A second
seed without `--force` also mixes batches into one report.

```bash
payrecover detect                    # optional: real failed test-mode payments
payrecover run --case rzp_<payment_id>
```

Detected `rzp_*` cases have no simulator ground truth, so they never get a
`customer_response` and terminate `exhausted`. Detect is real ingest; recovered
rupees in the sample report are simulated.

## Commands

| Command | What it does |
|---|---|
| `payrecover ping` | Authenticated test-mode read; verifies keys |
| `payrecover detect` | Read-only ingest of failed Razorpay payments into cases |
| `payrecover seed --seed 42` | Create 80 synthetic failed cases (local DB) |
| `payrecover run` | Dry-run the batch (default) |
| `payrecover run --live --case c42_06` | Real test-mode payment-link create |
| `payrecover run --case c42_02` | One case |
| `payrecover run --inject-timeout --case c42_02` | Typed write timeout, `link_count` stays 0 |
| `payrecover report` | Recovery metrics (markdown + JSON) |
| `payrecover audit <case-id>` | Audit trail for one case |

`KILL_SWITCH=true payrecover run --case c42_02` records the policy verdict and
refuses the write. That stop is **permanent**: processed cases become `stopped`
and turning the switch off does not resume them. `--live` requires `--case` or
`--limit` so a full batch cannot create 80 real payment links.

v1 does not expire or cancel payment links, so a second recovery link is
unreachable. Report `action_counts` scan the full audit history and accumulate
across re-runs.

`payrecover seed --force` DROPs `audit_events` and recreates it. The UPDATE/DELETE
triggers do not cover DROP: the trail is append-only **within a run**, not
tamper-evident.

## Pitch video (5 minutes)

1. **Problem (~45s).** A failed one-time card/UPI payment cannot be silently
   re-charged. Recovery is a bounded nudge: link, remind, wait, escalate, or stop.
2. **One case (~90s).** `payrecover audit c42_02` — bank downtime → wait → link →
   remind → paid. Same `corr=` on the paying step. Full replay:
   [`reports/sample/audit.txt`](reports/sample/audit.txt).
   Generic-failure shot: `payrecover audit c42_05` from the Gemini one-case file
   — `path=llm`, cause `ambiguous`, policy escalates anyway
   ([`reports/sample/llm-audit.txt`](reports/sample/llm-audit.txt)).
3. **Batch (~60s).** `payrecover report` — 31.27% recovered, plus the evaluator
   capture-rate section (hidden ground truth; the agent is blind). Excerpts below.
   Do this **before** `detect`.
4. **Detect (~20s).** `payrecover detect` — read-only ingest of a real failed
   test-mode payment (`rzp_pay_…`), then `payrecover run --case <id>`. That case
   ends `exhausted` (no simulator customer). Do not re-run `report` if you want
   the committed 80-case numbers.
5. **Graceful failure (~45s).** `payrecover run --inject-timeout --case c42_02` —
   wait succeeds, link create fails as `RazorpayTimeoutError` under one
   correlation_id, no duplicate link.
   [`reports/sample/timeout-audit.txt`](reports/sample/timeout-audit.txt).
6. **Kill switch (~30s).** `KILL_SWITCH=true` — verdict recorded, executor refuses.
   Optional last shots: `payrecover run --live --case c42_06` (test-mode link
   create); `sqlite3 data/payrecover.db "UPDATE audit_events SET case_id='x';"`
   aborted by the append-only trigger.

## Sample report (seed 42, dry-run, rules-only)

Full files: [`reports/sample/report.md`](reports/sample/report.md),
[`reports/sample/report.json`](reports/sample/report.json),
[`reports/sample/audit.txt`](reports/sample/audit.txt) (`c42_02`, same rules-only
run), [`reports/sample/llm-audit.txt`](reports/sample/llm-audit.txt) (`c42_05`,
Gemini one-case, not this batch).

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

- c42_05  ₹1777.72  cause=ambiguous  rationale=ambiguous
- c42_18  ₹7500.00  cause=international_transaction_not_allowed  rationale=high_amount

## Evaluator (hidden ground truth; agent is blind)

- Recoverable by construction: 46
- Captured: 35 (76.09%)
- Misses by profile: pays_if_fast 4, pays_after_wait 5, pays_after_reminder 1,
  pays_on_first_link 1
```

### Audit replay (`payrecover audit c42_02`)

Wait for bank downtime, then issue a link, then a reminder; customer pays the link.
The paid `customer_response` shares `corr=` with that reminder's attempt/result.

```
diagnosis_completed  case=c42_02  corr=d7417e0e…  cause=bank_downtime  path=rules
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
  cli.py               # payrecover ping | detect | seed | run | report | audit
  simulator/
    batchgen.py
    customer.py
tests/
docs/decisions.md
reports/sample/
```

### Invariants

1. Every action passes through `policy.py`. Only `actions.py` calls Razorpay write APIs.
2. Every decision is audited, including waits and stops.
3. Caps: max 2 payment links and max 3 reminders per case; link amount equals the
   original order; opt-out is a permanent stop; escalate when cause is
   `ambiguous` (regardless of confidence), confidence &lt; 0.6, or amount &gt;
   ₹5,000; `KILL_SWITCH=true` stops all execution. The kill is permanent for any
   case the runner processes while the switch is on — flipping it off does not
   resume those cases.
4. Re-running a batch must not duplicate links or reminders.
5. Recovered = simulated customer paid a recovery **payment link** (`kind=paid` and a
   `payment_link_id`). "Link sent" is not recovered. v1 does not settle the Razorpay
   link on-rail; the report states this explicitly.
6. If the LLM is unavailable, diagnosis falls back to rules and the audit records which path ran.
7. v1 does not expire or cancel payment links, so policy's second-link path is unreachable.
8. Report `action_counts` accumulate across re-runs (they scan the full audit history).

## How this was built

Six working days, paper-first. Policy precedence, audit schema, diagnosis keys
(`error_reason`, not `error_code`), metrics definition, and the hidden customer
mix were written in [`docs/decisions.md`](docs/decisions.md) before the loop was
wired. The Razorpay client, CLI, runner, and tests were drafted with AI assistance
and reviewed. The public repo is the product; local agent notes stay out of git.

## Tech stack

Python 3.11+, official `razorpay` SDK (test mode), Gemini API with a rule fallback,
Pydantic v2, SQLite, Typer, pytest, ruff.

## Decision log

See [`docs/decisions.md`](docs/decisions.md).
