---
description: Execute an approved ticket — preflight, review_option_order, place limit-at-mid, walk, set GTC exit
argument-hint: <path/to/ticket.json>
---

Execute the approved ticket at $ARGUMENTS. This is the money path — every step is
mandatory and ordered; any failure means STOP and report, never improvise.

1. `uv run rht preflight $ARGUMENTS` — exit 0 required. Shadow mode, halts, stale/missing
   approvals, sizing: preflight refuses and you stop. Never argue with it.
2. `review_option_order` for the exact ticket legs, limit at current mid. Compare simulated
   credit and max loss to the ticket (tolerance: `execution.review_tolerance`). Mismatch or
   any pre-trade warning you don't fully understand → STOP, show the human.
3. `place_option_order` — limit at mid. Never market.
4. Fill loop (RULES.md §4): poll `get_option_orders` ~60s; unfilled → cancel + re-place one
   tick worse; floor mid − $0.02; still unfilled → cancel,
   `uv run rht journal add --type no_fill ...`, done.
5. On fill, immediately and in this order:
   a. `review_option_order` + `place_option_order` the GTC buy-to-close at 50% of credit
      (round in the account's favor).
   b. `uv run rht journal add --type fill --symbol <sym> --ticket-hash <hash>
      --payload '{"fill_credit": ..., "mid_at_entry": ..., "slippage": ..., "gtc_order_id": ...}'`
   c. `uv run rht state open $ARGUMENTS`
6. Report: fill price vs mid (realized slippage), GTC exit resting, updated state.

If anything unexpected happens mid-flow (partial fill, rejected order, ambiguous status),
stop and surface it — an unclear position state is a human problem, not an agent guess.
