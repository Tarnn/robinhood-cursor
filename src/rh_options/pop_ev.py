"""Probability-of-profit and expected-value math for credit spreads.

Black-Scholes N(d2)-style probabilities under the risk-neutral measure — the same math the
market prices with, which is exactly why POP alone is not edge (see docs/strategy.md). The EV
numbers here use a conservative binary approximation (full credit or full loss) plus explicit
cost drag, so they understate the truth slightly — fail-pessimistic on the money path.
"""

from __future__ import annotations

import math
from datetime import date

from pydantic import BaseModel

from .models import Structure, TradeTicket

# Cost model (Robinhood 2026 fee page + measured half-spread crossing; see docs/strategy.md).
FEE_PER_CONTRACT_EXECUTION = 0.04  # combined ORF+OCC per contract, per execution
TAF_PER_CONTRACT_SELL = 0.00329


def norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def prob_beyond(
    *, spot: float, strike: float, iv: float, dte_years: float, rate: float, above: bool
) -> float:
    """Risk-neutral P(S_T > strike) if above else P(S_T < strike)."""
    if spot <= 0 or strike <= 0 or iv <= 0 or dte_years <= 0:
        raise ValueError("spot, strike, iv, dte must all be positive")
    d2 = (math.log(spot / strike) + (rate - iv**2 / 2) * dte_years) / (iv * math.sqrt(dte_years))
    p_above = norm_cdf(d2)
    return p_above if above else 1.0 - p_above


class PopEvReport(BaseModel):
    pop_short_strike: float  # P(short strike expires OTM)
    pop_breakeven: float  # P(position profitable at expiry)
    credit_dollars: float
    max_loss_dollars: float
    fees_round_trip: float
    slippage_round_trip: float
    ev_hold_gross: float
    ev_hold_net: float
    ev_managed_net: float
    managed_win_rate_assumed: float
    breakeven_win_rate: float
    verdict: str


def analyze(
    ticket: TradeTicket,
    *,
    iv: float,
    today: date,
    rate: float = 0.04,
    managed_win_rate: float = 0.85,
) -> PopEvReport:
    """POP/EV for a vertical credit spread ticket (iron condors: analyze each side separately)."""
    if ticket.structure is Structure.IRON_CONDOR:
        raise ValueError("analyze() covers verticals; run each IC side as its own vertical")

    dte_years = ticket.dte(today) / 365.0
    short = ticket.short_legs[0]
    credit = ticket.credit_mid
    is_put = ticket.structure is Structure.PUT_CREDIT_SPREAD
    # Short put profits fully if S_T stays above the short strike; short call if below.
    pop_short = prob_beyond(
        spot=ticket.underlying_price,
        strike=short.strike,
        iv=iv,
        dte_years=dte_years,
        rate=rate,
        above=is_put,
    )
    breakeven = short.strike - credit if is_put else short.strike + credit
    pop_be = prob_beyond(
        spot=ticket.underlying_price,
        strike=breakeven,
        iv=iv,
        dte_years=dte_years,
        rate=rate,
        above=is_put,
    )

    credit_dollars = credit * 100 * ticket.contracts
    max_loss = ticket.max_loss
    n_legs = len(ticket.legs)
    # Four executions per vertical round trip (2 legs open + 2 close), TAF on the sell side.
    fees = (
        FEE_PER_CONTRACT_EXECUTION * n_legs * 2 * ticket.contracts
        + TAF_PER_CONTRACT_SELL * n_legs * ticket.contracts
    )
    # Crossing half the quoted spread per leg, in and out.
    slippage = sum(leg.spread / 2 for leg in ticket.legs) * 2 * 100 * ticket.contracts

    ev_hold_gross = pop_be * credit_dollars - (1 - pop_be) * max_loss
    ev_hold_net = ev_hold_gross - fees - slippage
    # Managed path: win = take 50% of credit; loss = stopped at 2x credit (gap risk means some
    # losses are still full-width — managed_win_rate is an assumption, surfaced in the report).
    ev_managed_net = (
        managed_win_rate * (0.5 * credit_dollars)
        - (1 - managed_win_rate) * (2.0 * credit_dollars)
        - fees
        - slippage
    )
    breakeven_wr = max_loss / (max_loss + credit_dollars) if (max_loss + credit_dollars) else 1.0

    verdict = (
        "positive-EV under assumptions"
        if ev_managed_net > 0 and ev_hold_net > -1
        else "EV does not clear costs — flat is correct"
    )
    return PopEvReport(
        pop_short_strike=round(pop_short, 4),
        pop_breakeven=round(pop_be, 4),
        credit_dollars=round(credit_dollars, 2),
        max_loss_dollars=round(max_loss, 2),
        fees_round_trip=round(fees, 2),
        slippage_round_trip=round(slippage, 2),
        ev_hold_gross=round(ev_hold_gross, 2),
        ev_hold_net=round(ev_hold_net, 2),
        ev_managed_net=round(ev_managed_net, 2),
        managed_win_rate_assumed=managed_win_rate,
        breakeven_win_rate=round(breakeven_wr, 4),
        verdict=verdict,
    )
