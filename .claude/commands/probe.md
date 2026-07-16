---
description: Day-0 capability probe — verify multi-leg support and account facts via simulation only; never places an order
---

Run the day-0 capability probe against the robinhood-trading MCP. This command NEVER calls
`place_option_order` — simulation only.

1. `get_accounts` → account type (cash/margin), which account is the Agentic account.
2. `get_option_level_upgrade_info` → current options approval level; report if an upgrade is
   needed for spreads (Level 3).
3. `get_portfolio` → confirm settled buying power (~$250 expected).
4. Build a syntactically complete 1-contract SPY put credit spread from the live chain
   (any 30-45 DTE expiry, ~25-delta short, $1 wing — it will NOT be traded) and call
   **`review_option_order` only**. The answer we need: does the API accept a 2-leg order at
   all? Capture the full response, including any rejection reason.
5. Write the results to a JSON file with exactly these fields and run
   `uv run rht probe record <file>`:
   `{"multi_leg_supported": <bool>, "account_type": "...", "options_level": ..., "notes": "..."}`
6. Report findings. If `multi_leg_supported` is false: STOP — the ruleset deliberately has
   no single-leg strategy; the human must decide next steps via ADR. Preflight will keep
   blocking live trades either way.
