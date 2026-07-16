"""Entry gates — one pure function per rule in rules/RULES.md §2.

Every gate returns a GateResult and never raises on bad tickets: malformed input is a failed
gate with a reason, because the money path fails closed. The agent may not edit this file
(hook-enforced); constants live in config/limits.json.
"""

from __future__ import annotations

from datetime import UTC, datetime

from .events import EventCheck
from .models import GateResult, Limits, Structure, TradeTicket


def _fail(gate: str, detail: str) -> GateResult:
    return GateResult(gate=gate, passed=False, detail=detail)


def _ok(gate: str, detail: str) -> GateResult:
    return GateResult(gate=gate, passed=True, detail=detail)


def universe_and_structure(ticket: TradeTicket, limits: Limits) -> GateResult:
    """Gate 1 — whitelisted symbol, allowed + coherent structure, $1 wings."""
    gate = "universe_and_structure"
    if ticket.symbol not in limits.universe.whitelist:
        return _fail(gate, f"{ticket.symbol} not in whitelist {limits.universe.whitelist}")
    if (
        ticket.structure is Structure.IRON_CONDOR
        and ticket.symbol not in limits.universe.iron_condor_only
    ):
        return _fail(gate, f"iron condors allowed only on {limits.universe.iron_condor_only}")

    expected_legs = 4 if ticket.structure is Structure.IRON_CONDOR else 2
    if len(ticket.legs) != expected_legs:
        return _fail(gate, f"{ticket.structure} needs {expected_legs} legs, got {len(ticket.legs)}")
    if len({leg.expiry for leg in ticket.legs}) != 1:
        return _fail(gate, "all legs must share one expiry")

    sells = [leg for leg in ticket.legs if leg.action == "sell"]
    buys = [leg for leg in ticket.legs if leg.action == "buy"]
    if ticket.structure is Structure.PUT_CREDIT_SPREAD:
        coherent = (
            len(sells) == 1
            and len(buys) == 1
            and all(leg.option_type == "put" for leg in ticket.legs)
            and sells[0].strike > buys[0].strike
        )
    elif ticket.structure is Structure.CALL_CREDIT_SPREAD:
        coherent = (
            len(sells) == 1
            and len(buys) == 1
            and all(leg.option_type == "call" for leg in ticket.legs)
            and sells[0].strike < buys[0].strike
        )
    else:  # iron condor: put credit spread + call credit spread
        put_sells = [leg for leg in sells if leg.option_type == "put"]
        put_buys = [leg for leg in buys if leg.option_type == "put"]
        call_sells = [leg for leg in sells if leg.option_type == "call"]
        call_buys = [leg for leg in buys if leg.option_type == "call"]
        coherent = (
            len(put_sells) == len(put_buys) == len(call_sells) == len(call_buys) == 1
            and put_sells[0].strike > put_buys[0].strike
            and call_sells[0].strike < call_buys[0].strike
            and put_sells[0].strike < call_sells[0].strike
        )
    if not coherent:
        return _fail(gate, f"legs do not form a coherent {ticket.structure}")

    width = limits.entry.spread_width
    puts = sorted(leg.strike for leg in ticket.legs if leg.option_type == "put")
    calls = sorted(leg.strike for leg in ticket.legs if leg.option_type == "call")
    for side in (puts, calls):
        if len(side) == 2 and abs((side[1] - side[0]) - width) > 1e-9:
            return _fail(gate, f"wing width {side[1] - side[0]:.2f} != required {width:.2f}")
    return _ok(gate, f"{ticket.symbol} {ticket.structure}, ${width:.0f} wings")


def volatility_regime(ticket: TradeTicket, limits: Limits) -> GateResult:
    """Gate 2 — IV rank >= min (SPY: VIX >= min). Proxy rank valid in shadow mode only."""
    gate = "volatility_regime"
    if ticket.symbol == limits.universe.spy_symbol:
        if ticket.vix is None:
            return _fail(gate, "SPY ticket missing vix")
        if ticket.vix < limits.entry.vix_min_spy:
            return _fail(
                gate, f"VIX {ticket.vix:.2f} < {limits.entry.vix_min_spy} — flat is correct"
            )
        return _ok(gate, f"VIX {ticket.vix:.2f} >= {limits.entry.vix_min_spy}")

    if ticket.iv_rank is None or ticket.iv_rank_source is None:
        return _fail(gate, "missing iv_rank / iv_rank_source (run `rht iv rank`)")
    if ticket.iv_rank < limits.entry.iv_rank_min:
        return _fail(
            gate, f"IV rank {ticket.iv_rank:.1f} < {limits.entry.iv_rank_min} — flat is correct"
        )
    if ticket.iv_rank_source == "proxy" and limits.mode != "shadow":
        return _fail(gate, "proxy IV rank is shadow-only; live requires a true rank (ADR-0001)")
    return _ok(gate, f"IV rank {ticket.iv_rank:.1f} ({ticket.iv_rank_source})")


def event_risk(ticket: TradeTicket, limits: Limits, events: EventCheck) -> GateResult:
    """Gate 3 — no earnings / FOMC / CPI strictly before expiry. Fails closed on unknowns."""
    gate = "event_risk"
    if not events.checked_through_expiry:
        return _fail(gate, events.detail)
    if events.blocking_events:
        return _fail(gate, f"events before expiry: {', '.join(events.blocking_events)}")
    return _ok(gate, events.detail)


def short_delta_band(ticket: TradeTicket, limits: Limits) -> GateResult:
    """Gate 4 — every short leg's |delta| within [min, max]."""
    gate = "short_delta_band"
    lo, hi = limits.entry.short_delta_min, limits.entry.short_delta_max
    for leg in ticket.short_legs:
        d = abs(leg.delta)
        if not lo <= d <= hi:
            return _fail(
                gate, f"short {leg.option_type} {leg.strike} |delta|={d:.2f} outside [{lo}, {hi}]"
            )
    if not ticket.short_legs:
        return _fail(gate, "no short legs")
    return _ok(gate, f"short deltas {[round(abs(x.delta), 2) for x in ticket.short_legs]}")


def tenor_band(ticket: TradeTicket, limits: Limits, today_dte: int) -> GateResult:
    """Gate 5 — DTE within [min, max]."""
    gate = "tenor_band"
    if not limits.entry.dte_min <= today_dte <= limits.entry.dte_max:
        return _fail(
            gate, f"DTE {today_dte} outside [{limits.entry.dte_min}, {limits.entry.dte_max}]"
        )
    return _ok(gate, f"DTE {today_dte}")


def min_credit(ticket: TradeTicket, limits: Limits) -> GateResult:
    """Gate 6 — mid credit clears the floor (lower floor for SPY's tighter markets)."""
    gate = "min_credit"
    floor = (
        limits.entry.min_credit_spy
        if ticket.symbol == limits.universe.spy_symbol
        else limits.entry.min_credit
    )
    if ticket.credit_mid < floor:
        return _fail(gate, f"credit ${ticket.credit_mid:.2f} < floor ${floor:.2f}")
    return _ok(gate, f"credit ${ticket.credit_mid:.2f} >= ${floor:.2f}")


def open_interest(ticket: TradeTicket, limits: Limits) -> GateResult:
    """Gate 7 — OI floor on every leg."""
    gate = "open_interest"
    for leg in ticket.legs:
        if leg.open_interest < limits.entry.min_open_interest:
            return _fail(
                gate,
                f"{leg.option_type} {leg.strike} OI {leg.open_interest} < "
                f"{limits.entry.min_open_interest}",
            )
    return _ok(gate, f"all legs OI >= {limits.entry.min_open_interest}")


def leg_spread_quality(ticket: TradeTicket, limits: Limits) -> GateResult:
    """Gate 8 — per-leg bid-ask <= abs cap or <= pct of mid. Slippage is the killer."""
    gate = "leg_spread_quality"
    for leg in ticket.legs:
        if leg.bid <= 0 or leg.ask <= 0 or leg.ask < leg.bid:
            return _fail(
                gate, f"{leg.option_type} {leg.strike} has a broken market ({leg.bid}/{leg.ask})"
            )
        ok = leg.spread <= limits.entry.max_leg_spread_abs or (
            leg.mid > 0 and leg.spread / leg.mid <= limits.entry.max_leg_spread_pct_of_mid
        )
        if not ok:
            return _fail(
                gate,
                f"{leg.option_type} {leg.strike} spread ${leg.spread:.2f} "
                f"(> ${limits.entry.max_leg_spread_abs:.2f} and > "
                f"{limits.entry.max_leg_spread_pct_of_mid:.0%} of mid ${leg.mid:.2f})",
            )
    return _ok(gate, "all leg markets tight enough")


def trend_alignment(ticket: TradeTicket, limits: Limits) -> GateResult:
    """Gate 9 — put side above / call side below the 200-day MA. Iron condors exempt."""
    gate = "trend_alignment"
    if ticket.structure is Structure.IRON_CONDOR:
        return _ok(gate, "iron condor: no directional filter")
    if ticket.dma_200 <= 0:
        return _fail(gate, "missing 200-day MA")
    if (
        ticket.structure is Structure.PUT_CREDIT_SPREAD
        and ticket.underlying_price <= ticket.dma_200
    ):
        return _fail(
            gate,
            f"put credit spread needs price {ticket.underlying_price} > 200dma {ticket.dma_200}",
        )
    if (
        ticket.structure is Structure.CALL_CREDIT_SPREAD
        and ticket.underlying_price >= ticket.dma_200
    ):
        return _fail(
            gate,
            f"call credit spread needs price {ticket.underlying_price} < 200dma {ticket.dma_200}",
        )
    return _ok(gate, f"price {ticket.underlying_price} vs 200dma {ticket.dma_200}")


def quote_freshness(ticket: TradeTicket, limits: Limits, now: datetime) -> GateResult:
    """Gate 10 — every quote in the ticket is recent; stale data is not data."""
    gate = "quote_freshness"
    max_age = limits.entry.quote_max_age_minutes * 60
    for leg in ticket.legs:
        quoted = leg.quoted_at if leg.quoted_at.tzinfo else leg.quoted_at.replace(tzinfo=UTC)
        age = (now - quoted).total_seconds()
        if age < 0:
            return _fail(gate, f"{leg.option_type} {leg.strike} quoted in the future")
        if age > max_age:
            return _fail(
                gate,
                f"{leg.option_type} {leg.strike} quote is {age / 60:.0f}m old "
                f"(max {limits.entry.quote_max_age_minutes}m)",
            )
    return _ok(gate, f"all quotes < {limits.entry.quote_max_age_minutes}m old")


def max_loss_cap(ticket: TradeTicket, limits: Limits) -> GateResult:
    """Gate 11 — worst case within the per-position dollar cap."""
    gate = "max_loss_cap"
    if ticket.contracts > limits.sizing.max_contracts:
        return _fail(gate, f"{ticket.contracts} contracts > max {limits.sizing.max_contracts}")
    if ticket.max_loss > limits.sizing.max_loss_per_position:
        return _fail(
            gate,
            f"max loss ${ticket.max_loss:.0f} > cap ${limits.sizing.max_loss_per_position:.0f}",
        )
    if ticket.max_loss <= 0:
        return _fail(gate, "non-positive max loss — ticket math is broken")
    return _ok(
        gate, f"max loss ${ticket.max_loss:.0f} <= ${limits.sizing.max_loss_per_position:.0f}"
    )


def run_all(
    ticket: TradeTicket,
    limits: Limits,
    events: EventCheck,
    now: datetime,
) -> list[GateResult]:
    """Run every gate in RULES.md §2 order; all gates always run (full picture > fast fail)."""
    today = now.date()
    return [
        universe_and_structure(ticket, limits),
        volatility_regime(ticket, limits),
        event_risk(ticket, limits, events),
        short_delta_band(ticket, limits),
        tenor_band(ticket, limits, ticket.dte(today)),
        min_credit(ticket, limits),
        open_interest(ticket, limits),
        leg_spread_quality(ticket, limits),
        trend_alignment(ticket, limits),
        quote_freshness(ticket, limits, now),
        max_loss_cap(ticket, limits),
    ]
