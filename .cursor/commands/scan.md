<!-- Market scan — halt check, VIX + whitelist quotes, trend, IV snapshots, per-symbol verdict (flat-is-correct aware) -->


Scan the whitelist for viable setups. Follow the mcp-recipes skill for call patterns.

1. `uv run rht state check-halts` — if halted, report the halt and STOP. Do not scan around
   a halt.
2. If any position is open (`rht state status`), run /manage first.
3. Snapshot the market: VIX via `get_index_quotes`; whitelist prices via one batched
   `get_equity_quotes`; per symbol: 200-day MA + last 21 closes via `get_equity_historicals`;
   ATM IV from the nearest 30-45 DTE chain.
4. For every candidate: `uv run rht iv snapshot SYM --iv <atm_iv>` (always — this seeds the
   rank history), then `uv run rht iv rank SYM --iv <atm_iv> --closes-file <closes.json>`.
5. Verdict table, one row per symbol: price vs 200dma (direction), IV rank/VIX status,
   earnings situation, and either CANDIDATE or the first gate that pre-fails.
6. Journal it: `uv run rht journal add --type scan --payload '<summary json>'`.
7. If nothing qualifies, end with exactly this framing: "No setup passes the gates today —
   flat is correct." That is a successful scan, not a failure. Do not loosen a filter to
   manufacture a candidate.

Cadence expectation: 2-5 trades/month. If you have proposed trades on 3 consecutive scans,
say so and re-read RULES.md §7 before proposing another.
