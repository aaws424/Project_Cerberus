# Data

All data is synthetic. No real customer, account or transaction appears anywhere in this repository.
"Nakhla Wallet" (محفظة نخلة) is a fictional Iraqi mobile wallet invented for this project.

## `seed/tickets_seed.jsonl`: 53 hand-written tickets

A smoke-test and demo set, written by hand to cover every path through the pipeline. **It is not an
evaluation set**: the offline keyword rules were written alongside it, so scores on it are optimistic.
Real results will come from the generated dev / test / held-out splits (see ROADMAP §4).

| Covers | Tickets |
|---|---|
| All 11 categories | failed transfer, wrong recipient, agent dispute, card, bill payment, login, OTP, balance/fee, KYC, how-to, unclear |
| "I want a human" (direct, indirect, alongside a real issue) | T-029, T-042, T-043 |
| Prompt injection (Arabic, English, fake `</ticket>` tag) | T-044, T-045, T-046 |
| How-to answered from the manual / not covered by it | T-035 – T-039 / T-040, T-041 |
| Fraud, account takeover, legal threat | T-010, T-015, T-016, T-026 |
| Arabizi, English, MSA, Kurdish | T-003, T-036 / T-009, T-014, T-019, T-025, T-029, T-039, T-045 / T-053 / T-049 |
| Two issues in one ticket | T-050 |
| Repeat customer (same customer as T-001) / exact duplicate of T-027 | T-051 / T-052 |
| Known hard cases | T-011 (two phone numbers), T-013 (agent vs fee), T-022 ("رصيد" = phone credit), T-033 ("البطاقة" = ID card) |

### Format

One JSON object per line:

```json
{"id": "T-001", "channel": "whatsapp", "customer_id": "C-101", "created_at": "2026-10-20T09:12:00+03:00",
 "text": "هلو، حولت مليون ونص لاخوي امس ...",
 "label": {"category": "failed_transfer",
           "fields": {"amount": 1500000, "currency": "IQD", "transaction_ref": "8823419", "incident_date": "2026-10-19"},
           "flags": {}, "expected_lane": "ready"}}
```

`label` is optional (unlabeled batches work too). Inside it, fields and flags that are absent mean null / false.
`expected_lane` is `ready`, `needs_you` or `duplicate`; `expected_reason` names the policy rule for `needs_you`.
`manual_section` is the app-manual article that should answer a how-to question.
Gold priority is not stored: the evaluator applies the priority formula to the gold facts.

## Next: generated splits

Facts-first generation (code draws the facts, an LLM writes the words), 400 tickets → QA → ≥ 300 kept →
`dev` 50% / `test` 25% / `heldout` 25%, with hashes committed before any prompt tuning. See ROADMAP §4.5.
