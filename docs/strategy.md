# Strategy rationale — and the honest math

Research basis: live July-2026 option chains (SOFI/F/SPY), Robinhood's 2026 fee schedule,
and the variance-risk-premium literature. This document explains *why* the rules are what
they are, so nobody "optimizes" them without understanding what they protect.

## Why $1-wide credit spreads

At $250, collateral dictates everything. A $1-wide defined-risk vertical needs ~$75-85; one
position is already 30% of the account. Cash-secured puts ($500-2,700), $2.5 wings (~$225),
index products (XSP min width = $500), and long options (low POP by construction) all fail
either the bankroll or the mandate. This is the only structure that fits — which is itself
a warning: **the account is too small to size correctly**, and the rules exist to keep that
structural over-sizing from becoming ruin.

## POP is not edge

A 25-delta short strike has ~72% delta-implied POP — and a $0.25 credit on a $1 spread needs
a 75% win rate to break even. The market charges fair odds for the payoff shape; selling
further OTM raises POP and the required win rate in lockstep. **POP describes the bet's
shape; it is not expectancy.** The mandate "only trade high probability of profit" is
therefore implemented as: high POP *and* every edge-adjacent filter the research supports:

- **IV rank ≥ 50 / VIX ≥ 18**: the variance risk premium (implied > subsequently realized
  vol; Carr & Wu 2009, Bakshi & Kapadia 2003; CBOE PUT index history) is real but
  time-varying and fattest after vol spikes. In a VIX-15 tape the premium is thin and the
  correct position is none. Expected cadence: 2-5 trades/month, whole months flat.
- **No earnings/FOMC/CPI before expiry**: the VRP compensates for jump risk; a scheduled
  jump inside your tenor means the "rich" IV is fairly pricing a known event, not paying
  you a premium. (Live example from scaffold week: SOFI Aug-14 spreads looked juicy at 69%
  IV — with earnings Jul 29 sitting inside the tenor.)
- **Manage at 50% / stop at 2x / close by 14 DTE**: management improves the path (fewer
  gamma disasters), not the expectancy. The 14-DTE hard close plus never-hold-expiry-week
  removes assignment/pin risk, which a $250 account cannot survive even once.

## The cost reality (why execution rules are strict)

Fees are trivial: ~$0.17-0.18 per vertical round trip. **Slippage is the whole game**: at
$0.05-0.07 wide per leg on single names, crossing half-spreads both ways costs $4-8 against
a $25 credit — 16-32%. Hence: limit-at-mid only, the one-tick walk with a floor, GTC
profit-target exits (resting orders get filled at their price), and the leg-spread gate.
SPY earns its place with penny-wide markets despite smaller credits.

Honest per-trade EV after costs: **−$3 to +$3.** Execution quality and the IVR filter decide
the sign. Realized-vs-estimated slippage in the journal is the single most important number
this system produces.

## Expectations (set before the first trade, on purpose)

- 6-month survival (equity > $100): ~75-90% with mechanical discipline; the fat left tail
  is gaps through stops and any expiry-week accident.
- Expected 6-month P&L: roughly −$25 to +$40. P(doubling in 6 months) < 5%.
- The realistic prize is a **capital-preserving live laboratory**: real execution data, a
  tested guardrail architecture, and compounding *knowledge* — not compounding dollars.

## Top 5 things that break the edge (watch these in /improve)

1. Slippage on single-name markets — the EV lives inside the bid-ask spread.
2. Forced over-sizing — 30%/trade is structural; a normal losing streak is near-ruin, which
   is what the breakers are for.
3. POP-as-edge fallacy — loosening the IVR/event gates to trade more is the classic failure.
4. Event/gap risk — "defined risk" becomes full-width losses when prices gap; stops don't
   help against gaps, only the event gate does.
5. Regime dependence — an agent that trades because it's idle turns a marginal edge into a
   systematic donation. Flat is correct.

*Nothing in this repo is financial advice; it is a quantitative guardrail system around a
strategy with, at best, a small and fragile edge.*
