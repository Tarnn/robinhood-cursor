# ADR-0001: Hybrid IV-rank source (VIX gate for SPY, snapshot accumulation + labeled RV proxy for single names)

- **Status:** accepted
- **Date:** 2026-07-16
- **Deciders:** human (scaffold review), agent (drafting)

## Context

Entry gate #2 requires IV rank ≥ 50, but the Robinhood MCP exposes no historical-IV endpoint,
so a true 252-day IV rank cannot be computed on day 0. Options considered had a cold-start /
correctness trade-off.

## Decision

Hybrid:

1. **SPY gates on VIX ≥ 18** (via `get_index_quotes`) from day 0 — VIX is a direct, always
   available implied-vol reading for the index.
2. **Single names accumulate their own history**: every `/scan` appends the ATM IV to
   `data/iv_history/<SYM>.jsonl` (journal-on-run). Once a symbol has **≥ 60 snapshots**,
   `rht iv rank` computes a true rank over the trailing year.
3. Below 60 snapshots it falls back to a **realized-vol proxy** — `ATM_IV ≥ 1.25 × 20-day
   realized vol` (from `get_equity_historicals`) — and labels the verdict `proxy`.
   **Proxy-mode entries are valid in shadow mode only**; live trades require a true rank
   (or SPY/VIX).

The mandated 2-week shadow period doubles as IV-history seeding.

## Alternatives considered

- **Pure snapshot accumulation** — correct long-term, but blinds the gate for ~60 trading days.
- **Pure realized-vol proxy** — always available, but RV ≠ IV; a proxy-only gate would
  systematically mis-time entries (IV can be rich while RV is quiet, and vice versa).
- **Third-party IV data feed** — real cost and an extra credentialed dependency for a $250
  account; rejected on proportionality.

## Consequences

- Live single-name entries are impossible until a symbol has 60 snapshots — acceptable, since
  shadow mode covers the same window and SPY remains fully gated via VIX.
- The `/scan` habit becomes load-bearing (no scan, no history); journal-discipline skill
  documents this.
- Watch: proxy-vs-true-rank disagreement rate once both exist; if the proxy repeatedly
  disagrees, tighten the 1.25 factor via ADR.
