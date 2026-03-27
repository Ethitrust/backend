# Escrow State Transitions V3

This document contains the V3 proposal only:

- ASCII flow diagram
- Human explanation (plain words)
- `VALID_TRANSITIONS_V3` (role-based)

## Proposed decision (refined): Option B with implicit initial acceptance

Recommended product behavior:

- The initiator's **initial offer** is implicitly accepted by the initiator (they created it).
- If counterparty accepts that original offer (same `offer_version`), escrow moves directly to `pending`.
- Initiator must explicitly accept **only after a counteroffer** from counterparty.
- Any new counteroffer invalidates previous acceptance markers and increments `offer_version`.

## Proposed ASCII flow (high-level)

```text
[initialized] -> [invited vN]
                           | accept by one side -> [pending]   # implicit initiator acceptance on original offer
                           | counter -> [counter_pending_other_party vN+1]
                           | reject -> [rejected]
                           | timeout -> [expired]
                           | cancel (allowed actor only) -> [cancelled]

[counter_pending_initiator vN]
    | initiator accepts vN -> [pending]
    | initiator counters -> [counter_pending_counterparty vN+1]
    | initiator cancels -> [cancelled]
    | timeout -> [expired]

[counter_pending_counterparty vN]
    | counterparty accepts vN -> [pending]
    | counterparty counters -> [counter_pending_initiator vN+1]
    | counterparty rejects -> [rejected]
    | timeout -> [expired]

[pending] -> [active] -> [completed]
    |           |
    |           \-> [disputed] -> [completed] OR [refunded]
    \-> [cancelled] (only if payment not captured/locked)
```

## Human explanation (plain words)

1. **Initiator creates an offer**; escrow starts at `invited`.
2. The initiator is treated as already agreeing to that first offer (implicit acceptance).
3. If the counterparty accepts the same `offer_version`, escrow goes straight to `pending`.
4. If either side counters, `offer_version` increments and the state flips to whichever side must respond next:
   - `counter_pending_initiator` means initiator must respond.
   - `counter_pending_counterparty` means counterparty must respond.
5. The responder can accept (go to `pending`), counter back (flip pending side, increment version), or reject/cancel where allowed.
6. While waiting, a timeout can move the escrow to `expired`.
7. From `pending`, escrow becomes `active` when funding is finalized.
8. From `active`, escrow can be completed or disputed.
9. `disputed` resolves through admin/resolution logic to either `completed` or `refunded`.
10. `rejected`, `expired`, `completed`, `cancelled`, and `refunded` are terminal outcomes.

## Proposed `VALID_TRANSITIONS_V3` (role-based)

```python
VALID_TRANSITIONS_V3: dict[str, dict[str, list[str]]] = {
   "invited": {
      "initiator": ["cancelled"],
      "counterparty": [
         "pending",                       # accept original offer => auto-accept initiator side
         "counter_pending_counterparty",
         "rejected",
      ],
      "system": ["expired"],
   },

   # Counterparty proposed a counteroffer; waiting initiator decision.
   "counter_pending_initiator": {
      "initiator": [
         "pending",                       # initiator accepts counteroffer version
         "counter_pending_counterparty",  # initiator re-counters; now counterparty must respond
         "cancelled",
      ],
      "counterparty": [],
      "system": ["expired"],
   },

   # Initiator proposed a counteroffer; waiting counterparty decision.
   "counter_pending_counterparty": {
      "initiator": ["cancelled"], # only if payment not captured/locked (atomic check)
      "counterparty": [
         "pending",                       # counterparty accepts initiator's latest counter
         "counter_pending_initiator",     # counterparty re-counters; now initiator must respond
         "rejected",
      ],
      "system": ["expired"],
   },

   "pending": {
      "initiator": ["cancelled"],       # only if payment not captured/locked (atomic check)
      "counterparty": ["cancelled"], # only if payment not captured/locked (atomic check)
      "system": ["active"],
   },

   "active": {
      "initiator": ["disputed"], # the one who can call completed should be the payer only, but we can enforce that in the service layer
      "counterparty": ["disputed"],
      "system": ["completed"],
   },

   "disputed": {
      "initiator": [],
      "counterparty": [],
      "admin_or_resolution_engine": ["completed", "refunded"],
   },

   # terminal states
   "rejected": {},
   "expired": {},
   "completed": {},
   "cancelled": {},
   "refunded": {},

   # Optional future state for split settlement:
   # "partially_refunded": {},
}
```

## Notes

- This is actor-scoped: transition permission depends on `initiator`, `counterparty`, `system`, or `admin_or_resolution_engine`.
- All accept/counter/reject actions must target the **active `offer_version`**.
- Any new counter invalidates prior acceptance markers and increments `offer_version`.
- `pending -> cancelled` should be guarded by an atomic funding lock check.
- `cancelled` and `refunded` are separate terminal outcomes.
