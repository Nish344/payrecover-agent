# Decision & Learning Log

One entry per working day. What I decided, what broke, how I diagnosed it, what I
learned. This file feeds the pitch video ("what broke and how I fixed it") and panel
answers. Honesty over polish — failed experiments belong here too.

Template:

```
## YYYY-MM-DD (Day N)
- Decided: ...       (and the alternative I rejected, and why)
- Built: ...
- Broke: ...         (symptom -> diagnosis -> fix)
- Learned: ...
- Tomorrow: ...
```

---

## 2026-08-27 (Day 0 — setup)

- Decided: Track 03 (AI Revenue Recovery), slice = failed one-time payment recovery on
  Razorpay test mode. Rejected checkout drop-off (weaker payment-error story) and
  mandate retries (more domain risk in the time available).
- Decided: recovery for one-time payments = get the customer to act (payment link +
  bounded reminders), NOT silent retry — merchants cannot re-charge a failed one-time
  card/UPI payment without customer action. This constraint shapes the whole action
  space.
- Decided: measurement via synthetic customer behavior model with hidden ground truth;
  "recovered" counts only when the simulated customer actually pays the link in test
  mode. Disclosed openly as a simulation.
- Built: project brief, decision log, initial layout.
- Tomorrow (Day 1): Razorpay test keys, fire failing payments manually, paper design of
  audit schema + policy rules.

---

## 2026-08-28 (Day 1)

- Decided: diagnosis keys off `error_reason` + `method` + `international`, not
  `error_code`. A real test-mode failure (`pay_TVGlLnELbwZeV2`) came back as
  `error_code=BAD_REQUEST_ERROR` (generic) and
  `error_reason=international_transaction_not_allowed` (the actual handle), with
  `method=card`, `international=true`, amount ₹100. Rejected treating `error_code` as
  the cause taxonomy — it would collapse almost every failure into one bucket.
- Built: installable package, settings, proposed models, Razorpay test-mode client
  (reads retry, writes never retry, live keys refused), `payrecover ping` against
  real test credentials. Paper audit schema, policy precedence, and customer-behavior
  mix below.
- Broke: nothing in code. The useful surprise was the dashboard vs API: the API also
  exposes `international`, `error_description`, and card last4 — detector must persist
  those, not only the five error_* fields.
- Learned: test-mode mock failures still produce a full Razorpay error object. That is
  enough to design diagnosis against; we do not need live-mode declines for v1.
- Tomorrow (Day 2): implement policy / diagnosis / audit / metrics by hand; wire
  detector → policy → actions → simulator into `payrecover run`.

### Audit schema (paper)

SQLite table `audit_events`. Inserts only. Reconstruct one case with:

```sql
SELECT * FROM audit_events WHERE case_id = ? ORDER BY ts ASC, event_id ASC;
```

Physical append-only: `BEFORE UPDATE` and `BEFORE DELETE` triggers that `RAISE(ABORT, ...)`.
No `UPDATE`/`DELETE` in application code. Timestamps stored as UTC ISO-8601; human
export converts to IST.

Every row:

| field | why it exists | if deleted |
|---|---|---|
| `event_id` | stable primary key | cannot cite a specific decision |
| `case_id` | join key for one-case replay | cannot reconstruct a story |
| `ts` | order of events | replay becomes unordered |
| `event_type` | what happened | payload is an untyped blob |
| `correlation_id` | ties `action_attempted` to `action_result` (and later customer_response) | cannot prove which API call produced which result |
| `payload` | type-specific facts (JSON) | the row is a header with no evidence |

Event types (closed set for v1):

| event_type | emitter | payload must include |
|---|---|---|
| `case_detected` | detector | payment_id, order_id, amount_paise, method, error_reason, error_source, error_step, error_code |
| `diagnosis_completed` | diagnosis | cause, confidence, rationale, path (`llm` or `rules`), model (nullable) |
| `policy_verdict` | policy | action_type, rationale, caps snapshot (link_count, reminder_count), kill_switch |
| `action_attempted` | actions | action_type, amount_paise (if link), payment_link_id (if known) |
| `action_result` | actions | ok, payment_link_id, error_type (nullable), detail |
| `customer_response` | simulator | kind (`paid` / `ignored` / `opted_out`), payment_link_id |
| `case_terminal` | runner | outcome (`recovered` / `escalated` / `stopped_by_policy` / `exhausted` / `waiting`) |

Waits and stops still get `policy_verdict` + `case_terminal`. An unaudited no-op is a bug.

Explain-one-action (this failed ₹100 international card, if the agent later issued a link):
read aloud `case_detected` → `diagnosis_completed` (path + cause) → `policy_verdict`
(`issue_link`, amount 10000 paise) → `action_attempted` / `action_result` (same
`correlation_id`) → `customer_response` → `case_terminal`. If the evaluator asks "why
this amount?", the verdict payload must show it equals the original order.

### Policy rules (paper)

Caps (one place in `policy.py` when implemented): max 2 links / case, max 3 reminders /
case, link amount == original `amount_paise` (never more), opt-out is permanent,
escalate if confidence < 0.6 **or** amount > ₹5,000 (500000 paise), `KILL_SWITCH`
stops all execution.

First-match precedence (top wins):

1. `KILL_SWITCH` → `stop` (reason: kill_switch). Checked here so a dry-run still
   records the verdict; executor also refuses writes if the flag is on.
2. `opted_out` → `stop` (reason: opt_out). Irreversible.
3. Status already `recovered` / `stopped` / `escalated` / `exhausted` → `stop`
   (reason: already_terminal). Makes re-runs a no-op.
4. Amount > ₹5,000 → `escalate` (high_amount). Wins over high confidence: a sure
   diagnosis on a large one-time charge still needs a human.
5. Confidence < 0.6 → `escalate` (low_confidence).
6. Cause is transient rail failure (`bank_downtime`, `issuer_unavailable`) and no
   completed wait yet → `wait`.
7. No active unpaid link and `link_count` < 2 → `issue_link` at original amount.
   Second link only if the first is cancelled/expired/paid-failed — never two live links.
8. Active unpaid link and `reminder_count` < 3 → `remind`.
9. Else → `stop` (reason: exhausted).

Idempotency: counts come from already-written audit rows + case state, not from
"intent". Re-running a case that already has a successful `issue_link` result must
not emit another create. Amount mismatch vs original → `stop` (never silently clip
or inflate).

Rejected: silent retry of the original payment (not allowed for one-time card/UPI).
Rejected: putting kill-switch only in the executor — then a dry-run would look like
it would have charged.

### Customer behavior mix (paper)

Batch size 80. Hidden from the agent (separate table / file, never on `Case`).
Shares chosen so easy payers are not a majority.

| profile | n | share | on `issue_link` | on `remind` | on `wait` |
|---|---|---|---|---|---|
| `pays_on_first_link` | 16 | 20% | pays | n/a | n/a |
| `pays_after_reminder` | 14 | 18% | ignores | pays on 1st or 2nd remind | n/a |
| `pays_if_fast` | 8 | 10% | pays only if contacted before a wait | else ignores | ignores |
| `pays_after_wait` | 8 | 10% | ignores | ignores | pays after wait completes |
| `never_pays` | 18 | 22% | ignores | ignores | ignores |
| `opts_out` | 10 | 12% | opt-out on first contact | if somehow reached, opt-out | n/a |
| `high_value` | 6 | 8% | amount > ₹5,000; policy should escalate before a link | n/a | n/a |

Failure-cause mix (independent of profile, assigned at seed): include
`international_transaction_not_allowed` (seen in test mode), `insufficient_funds`,
`bank_downtime`, `incorrect_pin` / `invalid_otp`, and an ambiguous bucket with a
generic description so the LLM path has work. Opt-out is honored exactly once and is
terminal. Recovered = paid the payment link in test mode, never "link sent".

---

## 2026-08-29 (Day 2)

- Decided: seed is local-only (80 synthetic failed cases in SQLite). Razorpay writes
  happen only on `payrecover run` when policy issues a link/remind, not at seed.
  Rejected creating 80 live orders at seed — rate limits and leftover dashboard noise.
- Decided: batch `wait` is compressed (wait_completed flips on the wait action) so a
  single `run` can exercise pays_after_wait without sleeping an hour.
- Built: store, detector, actions, batchgen, customer mechanics, runner, CLI seed/run.
  `policy.py` / `diagnosis.py` / `audit.py` / `metrics.py` are fill-in stubs.
- Tomorrow: fill those four modules from the Day 1 spec; then `payrecover run --dry-run`
  on the seeded batch.

---

## 2026-08-31 (Day 3)

- Built: `audit.py` (append-only SQLite + IST export), `policy.py` (first-match
  precedence), `diagnosis.py` (reason-keyed rules + LLM fallback), `metrics.py`
  (paid ≠ link sent).
- `payrecover seed` → `run --dry-run` → `report` is the v1 loop.
- Tomorrow: demo a Razorpay timeout path and freeze README for the video.
