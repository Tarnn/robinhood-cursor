---
version: 1.0.0
status: active
---

# RULES.md — the mechanical ruleset (v1.0.0)

This file is canonical. `config/limits.json` mirrors every constant here (`rules_version` must
match the `version` above — `tests/test_rules_consistency.py` enforces it). Changing anything
in this file requires: journal evidence, an ADR in `knowledge/adr/`, a version bump, updated
tests, and a **human** making the edit. The agent may never edit this file.

Grounding: delta-implied probability of profit is *priced in* — a 70–85% POP spread is a
negative-skew bet that breaks even at best at fair IV. The only real (small) edge sources are
IV-rank timing, event avoidance, mechanical management, and execution quality. Honest per-trade
EV after slippage is **−$3 to +$3**: discipline decides the sign. Therefore: **flat is correct.**
A session that ends with no trade is a successful session.

## 1. Universe

- Underlyings: **SPY, SOFI, T, F, AAL, KWEB, UNG** — nothing else, ever.
- Structures: **$1-wide vertical credit spreads** (put or call). Iron condors **SPY only**.
- Directional filter: put credit spreads only while underlying **> 200-day MA**; call credit
  spreads only while **< 200-day MA**.
- Never: naked options, cash-secured puts, long single-leg options, widths ≠ $1, undefined risk.

## 2. Entry gates (ALL must pass — one failure kills the ticket)

| # | Gate | Rule |
|---|------|------|
| 1 | Universe | symbol in whitelist; structure allowed for symbol |
| 2 | Volatility regime | IV rank ≥ **50** (SPY: VIX ≥ **18**). Proxy-based IV rank (< 60 snapshots) is valid **in shadow mode only** |
| 3 | Event risk | **no earnings, FOMC, or CPI before expiry** (not before planned exit — gaps don't wait) |
| 4 | Short delta | 0.20 ≤ \|Δ\| ≤ 0.30 |
| 5 | Tenor | 30 ≤ DTE ≤ 45 |
| 6 | Credit | mid credit ≥ **$0.25** ($0.20 for SPY) |
| 7 | Liquidity | open interest ≥ **500** on both legs |
| 8 | Spread quality | each leg bid-ask ≤ **$0.05** or ≤ **10% of mid** |
| 9 | Trend alignment | put side above / call side below the 200-day MA (§1) |
| 10 | Quote freshness | all quotes in the ticket < **10 minutes** old |
| 11 | Max loss | (width − credit) × 100 ≤ **$100** per position |

## 3. Sizing

- **1 contract** per position. **1 concurrent position** (raising to 2 uncorrelated positions is
  a rules change: ADR + human edit).
- Total open max-loss ≤ **$150**. Cash reserve ≥ **$100** at all times, post-trade.

## 4. Execution

- **Limit orders at mid only. Never market orders.**
- Unfilled after **60 s** → cancel/replace one tick worse. Floor: **mid − $0.02** — below that,
  cancel and journal `no_fill`. Do not chase.
- Always `review_option_order` before `place_option_order`; simulated credit/max-loss must match
  the ticket within **$0.05** or abort.
- On fill: immediately place the GTC buy-to-close at **50% of credit**, journal the fill,
  register the position in state.

## 5. Exits (first trigger wins)

1. **Profit**: 50% of credit (resting GTC from fill time).
2. **Stop**: cost-to-close ≥ **2× credit received**.
3. **Time**: hard close at **14 DTE**, no exceptions, no "it'll come back".
4. **Breach**: short strike touched → close same or next session.
5. **Never hold into expiration week. Never take assignment.** Robinhood force-liquidates
   expiry-day positions at bad prices; a $250 account cannot survive assignment.

## 6. Circuit breakers (auto-set by `rht state`; only a human may clear)

- Equity ≤ **$200** (−20%) → halt **30 days**.
- **2 consecutive stop-outs** → halt until human review.
- Rolling 20-trade win rate < **70%** → halt until human review.

## 7. Cadence

Expected **2–5 trades/month**. Flat weeks and flat months are correct behavior in a low-IV
regime. An agent trading daily at this account size is overtrading, by definition.

## 8. Approvals (the unfakeable pipeline)

Order of operations, no exceptions:
ticket → `rht validate` (all gates pass) → `rht pop` → `rht opinion request` (cross-model
reviewer returns **APPROVE**) → `rht preflight` (mode=live + probe recorded + no halts + sizing
+ hash/freshness match < **15 min**) → MCP `review_option_order` → `place_option_order`.

A reviewer **VETO is final** for that ticket. Max **1 revised attempt per symbol per day**.
