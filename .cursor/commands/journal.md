<!-- Render the trade journal to markdown and show performance stats -->


1. `uv run rht journal render` → regenerates `data/journal.md`.
2. `uv run rht journal stats` → wins/losses, rolling win rate, total P&L, shadow count.
3. Summarize for the human: rolling win rate vs the 70% breaker floor, realized slippage vs
   the estimates (the number that decides whether the edge is real), and how many shadow
   proposals have accumulated toward the 10 needed before going live.
