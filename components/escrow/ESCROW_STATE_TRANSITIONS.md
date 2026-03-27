# Escrow Status Transition Flow (ASCII)

This flow is generated from the current `VALID_TRANSITIONS` in `components/escrow/app/service.py`.

## ASCII flow diagram

```text
[initiator initializes escrow]
            |
            v
        [invited]
          |  |  |  |  |  |  \
          |  |  |  |  |  |   \--> [cancelled] (terminal)
          |  |  |  |  |   \-----> [expired]   (terminal)
          |  |  |  |   \--------> [rejected]  (terminal)
          |  |  |   \-----------> [counter_pending_counterparty]
          |  |   \--------------> [counter_pending_initiator]
          |   \-----------------> [accepted_by_counterparty]
           \--------------------> [accepted_by_initiator]


[accepted_by_initiator]
   |  |  |  |  |
   |  |  |  |   \---------> [cancelled] (terminal)
   |  |  |   \------------> [expired]   (terminal)
   |  |   \---------------> [rejected]  (terminal)
   |   \------------------> [counter_pending_counterparty]
    \---------------------> [counter_pending_initiator]
                             (and can move to [accepted_by_counterparty])


[accepted_by_counterparty]
   |  |  |  |  |
   |  |  |  |   \---------> [cancelled] (terminal)
   |  |  |   \------------> [expired]   (terminal)
   |  |   \---------------> [rejected]  (terminal)
   |   \------------------> [counter_pending_counterparty]
    \---------------------> [counter_pending_initiator]
                             (and can move to [accepted_by_initiator])


[counter_pending_initiator]
   |  |  |  |  |  |
   |  |  |  |  |   \-------> [cancelled] (terminal)
   |  |  |  |   \----------> [expired]   (terminal)
   |  |  |   \-------------> [rejected]  (terminal)
   |  |   \----------------> [counter_pending_counterparty]
   |   \-------------------> [counter_pending_initiator] (counter again)
   |                        [accepted_by_counterparty]
    \----------------------> [accepted_by_initiator]


[counter_pending_counterparty]
   |  |  |  |  |  |
   |  |  |  |  |   \-------> [cancelled] (terminal)
   |  |  |  |   \----------> [expired]   (terminal)
   |  |  |   \-------------> [rejected]  (terminal)
   |  |   \----------------> [counter_pending_initiator]
   |   \-------------------> [counter_pending_counterparty] (counter again)
   |                        [accepted_by_counterparty]
    \----------------------> [accepted_by_initiator]


[both accepted] --> [pending] --> [active] --> [completed] (terminal)
                                \-> [disputed] --> [completed] (terminal)
                                \-> [cancelled] (terminal)

[pending] can also go directly to [cancelled] (terminal)
[active]  can go to [cancelled] (terminal)
[disputed] can go to [cancelled] (terminal)

[rejected], [expired], [completed], [cancelled], [refunded] are terminal states.
```

## Human explanation (plain words)

1. **Initiator creates the escrow**, so it starts in **`invited`**.
2. From **`invited`**, the invited party can:
   - accept (leading to `accepted_by_counterparty`),
   - counter (leading to one of the `counter_pending_*` states),
   - reject (`rejected`),
   - do nothing until expiry (`expired`),
   - or the flow can be cancelled (`cancelled`).
3. If one side has accepted (`accepted_by_initiator` or `accepted_by_counterparty`), the other side can:
   - accept as well,
   - counter again,
   - reject,
   - let it expire,
   - or cancel.
4. During negotiation (`counter_pending_initiator` / `counter_pending_counterparty`), parties can keep countering back and forth, accept, reject, expire, or cancel.
5. Once both sides have accepted the same offer, escrow proceeds to **`pending`** (payment/funding stage).
6. From **`pending`**, it becomes **`active`** when funded, or it can still be **`cancelled`**.
7. From **`active`**, it can be **`completed`**, **`disputed`**, or **`cancelled`**.
8. From **`disputed`**, it resolves to **`completed`** or **`cancelled`**.
9. **Terminal states** (no further transitions):
   - `rejected`
   - `expired`
   - `completed`
   - `cancelled`
   - `refunded`

## Transition list (exact mapping)

- `invited` → `accepted_by_initiator`, `accepted_by_counterparty`, `counter_pending_initiator`, `counter_pending_counterparty`, `rejected`, `expired`, `cancelled`
- `counter_pending_initiator` → `accepted_by_initiator`, `accepted_by_counterparty`, `counter_pending_initiator`, `counter_pending_counterparty`, `rejected`, `expired`, `cancelled`
- `counter_pending_counterparty` → `accepted_by_initiator`, `accepted_by_counterparty`, `counter_pending_initiator`, `counter_pending_counterparty`, `rejected`, `expired`, `cancelled`
- `accepted_by_initiator` → `accepted_by_counterparty`, `counter_pending_initiator`, `counter_pending_counterparty`, `rejected`, `expired`, `cancelled`
- `accepted_by_counterparty` → `accepted_by_initiator`, `counter_pending_initiator`, `counter_pending_counterparty`, `rejected`, `expired`, `cancelled`
- `rejected` → _(none)_
- `expired` → _(none)_
- `pending` → `active`, `cancelled`
- `active` → `completed`, `disputed`, `cancelled`
- `disputed` → `completed`, `cancelled`
- `completed` → _(none)_
- `cancelled` → _(none)_
- `refunded` → _(none)_

## Proposed changes (Flow v3)

Below is a recommended rule set based on the current issues identified.

## Proposed decision (refined): Option B with implicit initial acceptance

Recommended product behavior:

- The initiator's **initial offer** is implicitly accepted by the initiator (they created it).
- If counterparty accepts that original offer (same `offer_version`), escrow moves directly to `pending`.
- Initiator must explicitly accept **only after a counteroffer** from counterparty.
- Any new counteroffer invalidates previous acceptance markers and increments `offer_version`.

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
      "initiator": [],
      "counterparty": [
         "pending",                       # counterparty accepts initiator's latest counter
         "counter_pending_initiator",     # counterparty re-counters; now initiator must respond
         "rejected",
      ],
      "system": ["expired"],
   },

   "pending": {
      "initiator": ["cancelled"],       # only if payment not captured/locked (atomic check)
      "counterparty": [],
      "system": ["active"],
   },

   "active": {
      "initiator": ["disputed", "completed"],
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

### Notes for this proposed mapping

- This is actor-scoped: every transition is authorized by **who** performs it (`initiator`, `counterparty`, `system`, `admin_or_resolution_engine`).
- Initial-offer acceptance is implicit for initiator; explicit dual-accept is required only for counteroffers.
- All acceptance/counter/reject operations must target the **current active `offer_version`**.
- Any new counter (`offer_version += 1`) must invalidate both parties' prior acceptance markers.
- `counter_pending_*` loops are intentionally constrained by policy (`MAX_COUNTER_ROUNDS` + `counter_expires_at`).
- Expiry checks must target the **active offer version only**.
- `pending -> cancelled` must use atomic funding lock checks to prevent race conditions.
- `cancelled` and `refunded` remain semantically separate terminal outcomes.

### Compatibility note

If the codebase currently stores `accepted_by_initiator` / `accepted_by_counterparty` states, keep them as legacy-compatible aliases during migration, but prefer the V3 role-based transitions above for new logic.

### 1) Acceptance ambiguity: require **same offer version** acceptance

Define acceptance as: both parties must accept the **same `offer_version`**.

- If either party submits a new counter (`offer_version += 1`), previous acceptance by the other side is invalid for matching.
- Keep two fields for matching, for example:
  - `initiator_accepted_version`
  - `counterparty_accepted_version`
- Move to `pending` only when:
  - `initiator_accepted_version == counterparty_accepted_version == escrow.offer_version`

### 2) Prevent infinite counter loops

Add negotiation guardrails:

- `MAX_COUNTER_ROUNDS` (example: 5 or 10)
- Per-counter expiration (example: `counter_expires_at` = now + 24h)
- If max rounds reached or counter expires without response:
  - either force terminal `expired`,
  - or require fresh re-invite flow (`resend` + new offer version).

### 3) Restrict cancellation by stage + actor

`cancelled` should not be universally reachable by any actor.

Recommended policy:

- `invited`, `counter_pending_*`: initiator can cancel; counterparty may reject instead.
- `pending`: initiator cancel only if payment not captured/locked.
- `active`: no unilateral cancellation; raise dispute or complete according to role.
- `disputed`: only resolution engine/admin transitions to `completed` or `refunded`.

Also define fund effects explicitly per transition:

- `pending -> cancelled`: unlock/void payment authorization.
- `active/disputed -> refunded`: use refund settlement pipeline for funded reversals.

### 4) Clarify `refunded` vs `cancelled`

Use both states with distinct meaning:

- `cancelled` = business workflow terminated.
- `refunded` = financial settlement result where funds returned.

Recommended relation:

- `cancelled` should represent **pre-funding/business cancellation**.
- For funded escrows, route directly to `refunded` from funded/dispute resolution paths.
- Avoid `cancelled -> refunded` as a default flow to reduce semantic overlap.

### 5) Standardize expiration rules

Use two expiry concepts:

- `invite_expires_at` for initial invitation.
- `counter_expires_at` for each pending counter offer.

Rules:

- If current actionable item (invite/counter) expires before required response, move to terminal `expired`.
- Expiration should always evaluate against the **current active offer version**.
- Accept/counter/reject must verify that active offer has not expired.

### 6) Improve dispute outcomes for partial scenarios

Current `disputed -> completed|refunded` is cleaner than `cancelled`, but still coarse for divisible deliveries.

Recommended outcomes:

- `disputed -> completed` (full release)
- `disputed -> refunded` (full return)
- `disputed -> partially_refunded` (optional new state if partial settlement is required)

If avoiding new states, keep `disputed -> completed|refunded` and record split details in settlement fields/events.

## Proposed ASCII flow (high-level)

```text
[initialized] -> [invited vN]
                           | accept by one side -> [accepted_by_* vN]
                           | counter -> [counter_pending_other_party vN+1]
                           | reject -> [rejected]
                           | timeout -> [expired]
                           | cancel (allowed actor only) -> [cancelled]

[accepted_by_* vN]
    | other side accepts same vN -> [pending]
    | either side counters -> [counter_pending_* vN+1]
    | timeout -> [expired]
    | cancel (policy-based) -> [cancelled]

[counter_pending_* vN]
    | target accepts vN -> [accepted_by_target vN]
    | target counters -> [counter_pending_other_party vN+1]
    | target rejects -> [rejected]
    | counter timeout -> [expired]
    | max rounds reached -> [expired] or [cancelled_by_policy]

[pending] -> [active] -> [completed]
                \-> [cancelled] (only if payment not finalized)

[active] -> [disputed] -> [completed] OR [refunded] (or partial resolution)
```

## Suggested next implementation steps

1. Add version-specific acceptance fields and enforce same-version matching.
2. Add counter round limit + per-counter expiry checks.
3. Introduce role-based cancellation guards per state.
4. Add explicit funded-cancel refund path and transition(s) to `refunded`.
5. Update tests for all edge cases (version mismatch, max counters, expiry race, funded cancel behavior).
