"""Spread screener — a research pre-filter, never a ticket source.

Given one expiry's option chain (from any data source, e.g. delayed free data in the
dashboard), enumerate the $-width put/call credit spreads whose short leg sits in the delta
band, build a TradeTicket for each, and run the *real* entry gates and POP/EV math on it. This
shows which strikes would be worth a `/propose` before the agent spends MCP calls.

It is deliberately read-only and pure: no network, no files written. Real tickets must still
be built from live Robinhood MCP quotes by the agent and go through `rht validate` ->
`rht opinion` -> `rht preflight`; delayed data will (correctly) fail the quote-freshness gate.
"""

from __future__ import annotations

import math
from datetime import UTC, date, datetime
from typing import Literal

from pydantic import BaseModel

from . import gates, pop_ev
from .events import EventCheck
from .models import GateResult, Leg, Limits, Structure, TradeTicket

OptionType = Literal["put", "call"]


class ChainRow(BaseModel):
    option_type: OptionType
    strike: float
    bid: float
    ask: float
    iv: float  # annualized implied vol of this contract, e.g. 0.31
    open_interest: int
    delta: float | None = None  # if the source supplies greeks; otherwise computed from iv


class Candidate(BaseModel):
    structure: Structure
    short_strike: float
    long_strike: float
    short_delta: float
    short_iv: float
    credit_mid: float
    max_loss: float
    return_on_risk: float
    pop_short_strike: float | None
    pop_breakeven: float | None
    ev_hold_net: float | None
    ev_managed_net: float | None
    gates_passed: int
    gates_total: int
    failed_gates: list[GateResult]
    ticket: TradeTicket

    @property
    def all_pass(self) -> bool:
        return self.gates_passed == self.gates_total


def bs_delta(
    *, spot: float, strike: float, iv: float, dte_years: float, rate: float, option_type: OptionType
) -> float:
    """Black-Scholes delta (no dividends). Puts are negative."""
    if spot <= 0 or strike <= 0 or iv <= 0 or dte_years <= 0:
        raise ValueError("spot, strike, iv, dte must all be positive")
    d1 = (math.log(spot / strike) + (rate + iv**2 / 2) * dte_years) / (iv * math.sqrt(dte_years))
    call = pop_ev.norm_cdf(d1)
    return call if option_type == "call" else call - 1.0


def sma(closes: list[float], n: int) -> float | None:
    return sum(closes[-n:]) / n if len(closes) >= n else None


def _delta(row: ChainRow, spot: float, dte_years: float, rate: float) -> float | None:
    if row.delta is not None:
        return row.delta
    if row.iv <= 0:
        return None
    return bs_delta(
        spot=spot, strike=row.strike, iv=row.iv, dte_years=dte_years, rate=rate,
        option_type=row.option_type,
    )


def screen(
    *,
    symbol: str,
    expiry: date,
    spot: float,
    dma_200: float,
    chain: list[ChainRow],
    limits: Limits,
    events: EventCheck,
    vix: float | None = None,
    iv_rank: float | None = None,
    iv_rank_source: Literal["true", "proxy"] | None = None,
    quoted_at: datetime | None = None,
    now: datetime | None = None,
    rate: float = 0.04,
    structures: tuple[Structure, ...] = (
        Structure.PUT_CREDIT_SPREAD,
        Structure.CALL_CREDIT_SPREAD,
    ),
    delta_slack: float = 0.05,
) -> list[Candidate]:
    """Every vertical with the short leg within the delta band (+/- slack, so near-misses show
    up with their failing gate), sorted all-pass first, then by managed EV."""
    now = now or datetime.now(UTC)
    quoted_at = quoted_at or now
    dte_days = (expiry - now.date()).days
    if dte_days <= 0:
        return []
    dte_years = dte_days / 365.0
    width = limits.entry.spread_width
    lo = limits.entry.short_delta_min - delta_slack
    hi = limits.entry.short_delta_max + delta_slack

    out: list[Candidate] = []
    for structure in structures:
        otype: OptionType = "put" if structure is Structure.PUT_CREDIT_SPREAD else "call"
        side = {round(r.strike, 4): r for r in chain if r.option_type == otype}
        for short in side.values():
            d = _delta(short, spot, dte_years, rate)
            if d is None or not lo <= abs(d) <= hi:
                continue
            long_strike = short.strike - width if otype == "put" else short.strike + width
            long = side.get(round(long_strike, 4))
            if long is None:
                continue
            long_d = _delta(long, spot, dte_years, rate) or 0.0
            legs = [
                Leg(action="sell", option_type=otype, strike=short.strike, expiry=expiry,
                    bid=short.bid, ask=short.ask, delta=round(d, 4),
                    open_interest=short.open_interest, quoted_at=quoted_at),
                Leg(action="buy", option_type=otype, strike=long.strike, expiry=expiry,
                    bid=long.bid, ask=long.ask, delta=round(long_d, 4),
                    open_interest=long.open_interest, quoted_at=quoted_at),
            ]
            ticket = TradeTicket(
                symbol=symbol,
                structure=structure,
                legs=legs,
                underlying_price=spot,
                dma_200=dma_200,
                vix=vix,
                iv_rank=iv_rank,
                iv_rank_source=iv_rank_source,
                earnings_confirmed_none=False,
                earnings_source="screener (unverified)",
                created_at=now,
                note="screener pre-filter — not an executable ticket",
            )
            results = gates.run_all(ticket, limits, events, now)
            failed = [r for r in results if not r.passed]
            credit = ticket.credit_mid
            pop: pop_ev.PopEvReport | None = None
            if credit > 0 and short.iv > 0 and ticket.max_loss > 0:
                try:
                    pop = pop_ev.analyze(ticket, iv=short.iv, today=now.date(), rate=rate)
                except ValueError:
                    pop = None
            out.append(
                Candidate(
                    structure=structure,
                    short_strike=short.strike,
                    long_strike=long.strike,
                    short_delta=round(d, 3),
                    short_iv=round(short.iv, 4),
                    credit_mid=round(credit, 3),
                    max_loss=round(ticket.max_loss, 2),
                    return_on_risk=round(credit * 100 / ticket.max_loss, 4)
                    if ticket.max_loss > 0
                    else 0.0,
                    pop_short_strike=pop.pop_short_strike if pop else None,
                    pop_breakeven=pop.pop_breakeven if pop else None,
                    ev_hold_net=pop.ev_hold_net if pop else None,
                    ev_managed_net=pop.ev_managed_net if pop else None,
                    gates_passed=len(results) - len(failed),
                    gates_total=len(results),
                    failed_gates=failed,
                    ticket=ticket,
                )
            )
    out.sort(
        key=lambda c: (
            -c.gates_passed,
            -(c.ev_managed_net if c.ev_managed_net is not None else -1e9),
        )
    )
    return out
