<!-- Build a trade ticket for a symbol, run the full validation + second-opinion pipeline, present it (shadow-aware) -->


Build and pipeline a trade ticket for $ARGUMENTS. Mechanics: trade-construction skill.

1. Confirm $ARGUMENTS was a CANDIDATE in a scan from today. If not, run /scan first.
2. Chain → legs (per trade-construction): 30-45 DTE expiry, short strike nearest 0.20-0.30
   |delta|, $1 wing, live quotes with timestamps. Determine earnings honestly (mcp-recipes).
3. Write `data/tickets/<UTC-ts>-$ARGUMENTS.json`.
4. Pipeline, in order, stopping at the first failure:
   - `uv run rht validate <ticket>` — any failed gate: report which and STOP (no tweaking
     the ticket to squeak past a gate; that is the marginal setup that loses money).
   - `uv run rht pop <ticket> --iv <atm_iv>`
   - `uv run rht opinion request <ticket> --iv <atm_iv>` — VETO is final for this ticket
     (max 1 revised attempt per symbol per day, and only for data errors, not judgment).
5. Present ONE table: legs, credit, max loss, POP (short-strike + breakeven), EV (hold +
   managed, net of costs), every gate result, reviewer verdict + reasons.
6. In shadow mode (current default): journal it —
   `uv run rht journal add --type shadow_proposal --symbol $ARGUMENTS --ticket-hash <hash>
   --payload '<summary>'` — and remind the human this was NOT placed and /execute will
   refuse until they flip mode.
7. In live mode: ask the human explicitly whether to /execute. Never chain into /execute
   on your own.
