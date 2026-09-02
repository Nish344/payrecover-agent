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
escalate if cause is `ambiguous` **or** confidence < 0.6 **or** amount > ₹5,000
(500000 paise), `KILL_SWITCH` stops all execution.

First-match precedence (top wins):

1. `KILL_SWITCH` → `stop` (reason: kill_switch). Checked here so a dry-run still
   records the verdict; executor also refuses writes if the flag is on.
2. `opted_out` → `stop` (reason: opt_out). Irreversible.
3. Status already `recovered` / `stopped` / `escalated` / `exhausted` → `stop`
   (reason: already_terminal). Makes re-runs a no-op.
4. Amount > ₹5,000 → `escalate` (high_amount). Wins over high confidence: a sure
   diagnosis on a large one-time charge still needs a human.
5. Cause is `ambiguous` → `escalate` (ambiguous). Unclassified stays with a human;
   a model's self-reported confidence cannot raise this ceiling. (Added Day 5 freeze;
   Day 1 only had the 0.6 gate, which Gemini bypassed by returning 0.9 on `ambiguous`.)
6. Confidence < 0.6 → `escalate` (low_confidence).
7. Cause is transient rail failure (`bank_downtime`, `issuer_unavailable`) and no
   completed wait yet → `wait`.
8. No active unpaid link and `link_count` < 2 → `issue_link` at original amount.
   Second link only if the first is cancelled/expired/paid-failed — never two live links.
9. Active unpaid link and `reminder_count` < 3 → `remind`.
10. Else → `stop` (reason: exhausted).

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
| `pays_after_wait` | 8 | 10% | pays if `wait_completed` | ignores | ignores (wait is not a payment) |
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

### Day 3 review findings — fix plan (done Day 4)

Full-repo review after the v1 loop landed. Ordered: honesty gaps first, then demo
gaps, then polish. Status as of 2026-09-01:

**1. "Recovered" is not yet what the docs claim it is.** — done, option (b).
`metrics.py` counts recovered only when `customer_response.kind=paid` **and** a
`payment_link_id` exists. README invariant 5 and `report.json` `note` say payment is
simulated, not settled on the Razorpay rail. Day 0 wording stays as history.

**2. `pays_after_wait` can be "recovered" with no link in existence.** — done.
Profile ignores WAIT and pays on the first ISSUE_LINK after `wait_completed`.

**3. The non-dry-run path has never been demoed.** — done in code.
`payrecover run --inject-timeout --limit 1` uses `InjectedTimeoutClient` (no
network): one `action_attempted` + failed `action_result` under the same
`correlation_id`, `link_count` stays 0. Kill switch: executor refuses the write.
Live `payrecover run --limit 1` (real test-mode links) is still a video step when
keys are present.

**4. `customer_response` is missing its correlation_id.** — done.
Runner threads the step's `correlation_id` through diagnosis, verdict, execute,
customer_response, and terminal.

**5. No re-run idempotency test.** — done in `tests/test_e2e.py`.

**6. Report should list escalations, not just exceptions.** — done.
`report.md` / `report.json` have "Escalations (needs human)".

**7. Prompt-injection fence is untested.** — done.
LLM `cause` is allowlisted; `bank_downtime` / other wait causes cannot be minted
unless `error_reason` already matches.

**8. Surface the differentiators or they don't exist.** — done.
`reports/sample/` is committed; README includes a report excerpt and an audit replay.

Out of scope for v1 (parking, do not start): checkout drop-off, mandate retries,
Hinglish voice, multi-merchant config. The bar is a finished, honest, auditable
slice — not more surface.

---

## 2026-09-01 (Day 4)

- Decided: recovered = simulated `paid` on a payment link, not on-rail settlement.
  Rejected (a) (mark the Razorpay link paid) because test mode has no customer-complete
  API we control; lying that a link is settled would be worse than disclosing the
  simulator.
- Decided: timeout demo is injected (`--inject-timeout`), not a real network stall —
  deterministic for the video, same typed `RazorpayTimeoutError` path as a live timeout.
- Built: wait-profile fix, correlated audit, escalation list, cause sanitizer,
  `--limit` / `--inject-timeout`, sample report committed.
- Broke: first timeout-client splice dropped `_is_transient`; restored. Metrics
  splice briefly dropped `_case_row`; restored.
- Learned: a `paid` event without `payment_link_id` is how a wait-profile bug becomes
  a fake recovery; the metrics predicate has to require the link id, not just `kind`.
- Tomorrow: live `--limit 1` on test keys if not already filmed; freeze README for
  the video; code freeze still Sep 3.

---

## 2026-09-02 (Day 5 — freeze)

- Decided: `payrecover run` is dry-run by default; `--live` is required for a real
  test-mode write. A clone that types `payrecover run` must not create 80 payment
  links. Rejected leaving `--dry-run` as an opt-in flag — the README already claimed
  dry-run was the local path, but the CLI did the opposite.
- Built: `--case` for the video; committed timeout audit; froze README with the
  5-minute shot list.
- Broke: first live `issue_link` (`c42_06`) returned `RazorpayAPIError`: "Recurring
  digits in customer contact are disallowed" (`+919999999999`). The runner then
  retried the same write until `max_steps`, which also hit "Too many requests".
  Diagnosis: dummy contact rejected; failed writes were not treated like timeout
  (leave the case open, do not loop). Fix: contact `+918765432109`; any failed
  non-terminal execute returns immediately. `payrecover ping` succeeded
  (payments_visible=1). Film `--live --case c42_06` for the video; do not hammer
  the API from here.
- Learned: a typed error in the audit is only half the demo — if the loop retries
  a bad request, the trail looks like the agent does not know how to stop.
- Tomorrow: record the video; submit. No more product surface. Code freeze Sep 3.

#### Freeze evening — `ambiguous` was actionable under Gemini

Gemini returns `cause: ambiguous` with `confidence: 0.9` ("I am sure I cannot
classify this"). Policy treated 0.9 as permission to issue a link, so enabling
the LLM made the agent *less* bounded than rules-only (0.45 → escalate).
Committed `llm-audit.txt` for `c42_05` showed link + three reminders +
`exhausted`; the rules-only report listed the same case as escalated. Fix:
`cause == "ambiguous"` escalates on its own precedence rung, before the
confidence check. Headline batch stays rules-only (seed 42, no Gemini).
`reports/sample/llm-audit.txt` is a separate one-case Gemini run of `c42_05`
that must now escalate.

Also disclosed, not rebuilt: `seed --force` DROPs `audit_events` (triggers do
not cover DROP); `report` scores the whole DB; detected `rzp_*` cases have no
simulator customer and terminate `exhausted`.

Diagnosis LLM provider switched from Anthropic to Gemini (free-tier key in
`.env`, never committed). `GEMINI_API_KEY` + `LLM_MODEL=gemini-3.5-flash-lite`.
Wait-cause sanitizer remains; non-wait classifications from the LLM are allowed
on generic failures. `--live` now requires `--case` or `--limit`.

### Day 5 pre-submission review — final loophole pass (done)

Full re-read of code + docs + samples with a judge's eye. Findings were in three
buckets: (A) worth building, (B) spec-vs-code mismatches, (C) disclose-only.
Implemented before publish:

**A1.** `payrecover detect` — read-only `list_payments` → `ingest_failed_payments`
→ `upsert_detected`. Demo: detect a real failed test-mode payment, then
`run --case rzp_<payment_id>`.

**A2.** Sample LLM audit: [`reports/sample/llm-audit.txt`](../reports/sample/llm-audit.txt)
(`c42_05`, `path=llm`, cause `ambiguous`, policy escalates). Separate from the
rules-only headline batch.

**A3.** Report evaluator section: capture rate vs recoverable-by-construction
profiles. Marked as reading hidden ground truth; the agent stays blind.

**A4.** `--live` requires `--case` or `--limit`.

**B1.** `policy_verdict` payload includes `amount_paise` and `payment_link_id`.

**B2.** Terminal re-runs emit `policy_verdict` `already_terminal` and do not call
decide/execute.

**B3.** Failed non-terminal writes and `max_steps` expiry emit
`case_terminal` `{outcome: waiting, reason: run_released}` without flipping
status.

**B4.** `case_detected` is emitted only when the case has no prior row.

**C1–C4.** Disclosed in README (kill switch is a permanent stop; second link
unreachable; `action_counts` accumulate; generic seed bucket uses an empty
`error_reason`, not the string `"ambiguous"`). LICENSE is MIT.

Original review notes (A build / B fix / C disclose) are superseded by the
implementation above. C1–C3 remain disclose-only; C4 was implemented in
`batchgen`.

#### Submission checklist

- LICENSE: MIT, repo root.
- Video: A1 detect shot, A2 `path=llm` + escalate on `ambiguous`, sqlite3
  `UPDATE audit_events` abort (and say `seed --force` DROPs the table),
  capture-rate framing from A3. Film `report` before `detect`.
- Re-verify before publishing: `.local/` untracked, `.env` untracked, no secrets
  in git, `payrecover ping` works on a fresh clone with `.env.example`.
- Panel prep: (1) simulated-paid vs on-rail settlement, (2) kill-switch
  permanence, (3) 31.27% is a floor — capture-rate is the better frame,
  (4) `ambiguous` escalates even when Gemini reports 0.9.
