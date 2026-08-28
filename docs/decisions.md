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
