# PayRecover report

- Cases: 80
- ₹ at risk: ₹141352.94
- ₹ recovered: ₹44205.18 (35 cases)
- Recovery rate: 31.27%
- Note: recovered = customer_response.kind=paid AND a payment_link_id exists; link sent is not recovered. v1 payment is simulated, not settled on Razorpay.

## Outcomes

- escalated: 19
- exhausted: 18
- recovered: 35
- stopped_by_policy: 8

## Action counts

- escalate: 19
- issue_link: 58
- remind: 74
- stop: 26
- wait: 24

## Exception list (unresolved)

(none)

## Policy-stop list

- c42_20  ₹801.86  stopped
- c42_32  ₹794.36  stopped
- c42_42  ₹1435.69  stopped
- c42_46  ₹387.43  stopped
- c42_63  ₹1550.24  stopped
- c42_64  ₹2356.48  stopped
- c42_67  ₹1507.63  stopped
- c42_72  ₹1780.24  stopped

## Escalations (needs human)

- c42_05  ₹1777.72  cause=ambiguous  rationale=low_confidence
- c42_11  ₹2309.48  cause=ambiguous  rationale=low_confidence
- c42_17  ₹926.94  cause=ambiguous  rationale=low_confidence
- c42_18  ₹7500.00  cause=international_transaction_not_allowed  rationale=high_amount
- c42_23  ₹1586.82  cause=ambiguous  rationale=low_confidence
- c42_29  ₹1785.19  cause=ambiguous  rationale=low_confidence
- c42_35  ₹1512.89  cause=ambiguous  rationale=low_confidence
- c42_41  ₹462.62  cause=ambiguous  rationale=low_confidence
- c42_47  ₹500.66  cause=ambiguous  rationale=low_confidence
- c42_52  ₹7500.00  cause=invalid_otp  rationale=high_amount
- c42_53  ₹1206.66  cause=ambiguous  rationale=low_confidence
- c42_54  ₹7500.00  cause=international_transaction_not_allowed  rationale=high_amount
- c42_55  ₹7500.00  cause=insufficient_funds  rationale=high_amount
- c42_59  ₹1326.96  cause=ambiguous  rationale=low_confidence
- c42_62  ₹7500.00  cause=bank_downtime  rationale=high_amount
- c42_65  ₹130.09  cause=ambiguous  rationale=low_confidence
- c42_68  ₹7500.00  cause=bank_downtime  rationale=high_amount
- c42_71  ₹2114.83  cause=ambiguous  rationale=low_confidence
- c42_77  ₹2395.99  cause=ambiguous  rationale=low_confidence

## Evaluator (hidden ground truth; agent is blind)

- Recoverable by construction: 46
- Captured: 35 (76.09%)
- Note: Evaluator-only. Reads hidden ground truth; the agent is blind. Recoverable profiles would pay given the right actions (pays_on_first_link, pays_after_reminder, pays_if_fast, pays_after_wait). never_pays / opts_out / high_value are excluded. Misses include pays_if_fast customers whose cause correctly triggered a wait.

### Misses by profile

- pays_after_reminder: 1
- pays_after_wait: 5
- pays_if_fast: 4
- pays_on_first_link: 1
