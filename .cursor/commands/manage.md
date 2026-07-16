<!-- Check open positions against the exit rules — runs first in any session with an open position -->


Deterministic exit check for every open position. Exits are rules, not opinions.

1. `uv run rht state status` — list open positions. None → report "no open positions" and done.
2. Per position, via MCP: `get_option_positions` (confirm it actually exists — reconcile any
   mismatch with the human before acting), `get_option_orders` (is the GTC 50% exit still
   resting? if missing, re-place it via review+place before anything else),
   `get_option_quotes` on both legs + underlying quote.
3. Evaluate the exit triggers in RULES.md §5 order — first trigger wins:
   - cost-to-close (at mid) >= 2x credit received → STOP-OUT, close now
   - DTE <= 14 → time exit, close now
   - short strike touched (underlying <= short put strike / >= short call strike) → close
     same or next session
   - none → position stays; report current P&L and days to the 14-DTE close
4. Closing = cancel the resting GTC, then `review_option_order` + `place_option_order`
   buy-to-close, limit at mid, walking per RULES.md §4. Stop-outs may cross the spread —
   getting out matters more than the last nickel, that asymmetry is why entries never do.
5. After the close fills:
   - `uv run rht journal add --type exit --symbol <sym> --ticket-hash <hash> --pnl <realized>
     --payload '{"trigger": "...", "exit_slippage": ..., "days_held": ...}'`
   - `uv run rht state close --ticket-hash <hash> --pnl <realized> [--stop-out]
     --equity <live equity from get_portfolio>`
   - If state now reports a halt: say so plainly and stop trading. The halt is the system
     working, not a problem to route around.
