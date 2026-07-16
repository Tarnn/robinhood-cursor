"""Every gate: the golden ticket passes, and each rule has at least one failing mutation,
including the boundary values called out in RULES.md."""

from __future__ import annotations

from datetime import timedelta

from conftest import NOW, make_leg, make_spy_ticket, make_ticket

from rh_options import gates
from rh_options.events import EventCheck
from rh_options.models import Limits, Structure

CLEAR = EventCheck(checked_through_expiry=True, blocking_events=[], detail="clear")


def test_golden_ticket_passes_every_gate(limits: Limits) -> None:
    results = gates.run_all(make_ticket(), limits, CLEAR, NOW)
    assert len(results) == 11
    assert all(r.passed for r in results), [r.detail for r in results if not r.passed]


def test_golden_spy_ticket_passes(limits: Limits) -> None:
    results = gates.run_all(make_spy_ticket(), limits, CLEAR, NOW)
    assert all(r.passed for r in results), [r.detail for r in results if not r.passed]


# --- gate 1: universe & structure -----------------------------------------------------------


def test_non_whitelisted_symbol_fails(limits: Limits) -> None:
    assert not gates.universe_and_structure(make_ticket(symbol="MARA"), limits).passed


def test_iron_condor_on_single_name_fails(limits: Limits) -> None:
    t = make_ticket()
    result = gates.universe_and_structure(
        make_ticket(structure=Structure.IRON_CONDOR, legs=t.legs), limits
    )
    assert not result.passed


def test_wrong_wing_width_fails(limits: Limits) -> None:
    t = make_ticket(
        legs=[
            make_leg(),
            make_leg(action="buy", strike=13.5, bid=0.10, ask=0.14, delta=-0.08),
        ]
    )
    assert not gates.universe_and_structure(t, limits).passed


def test_incoherent_spread_fails(limits: Limits) -> None:
    # "put credit spread" whose short strike is below the long strike
    t = make_ticket(
        legs=[
            make_leg(strike=15.0),
            make_leg(action="buy", strike=16.0, bid=0.30, ask=0.35, delta=-0.15),
        ]
    )
    assert not gates.universe_and_structure(t, limits).passed


# --- gate 2: volatility regime ---------------------------------------------------------------


def test_low_iv_rank_fails(limits: Limits) -> None:
    assert not gates.volatility_regime(make_ticket(iv_rank=49.9), limits).passed


def test_iv_rank_exactly_at_min_passes(limits: Limits) -> None:
    assert gates.volatility_regime(make_ticket(iv_rank=50.0), limits).passed


def test_proxy_iv_rank_allowed_in_shadow_only(limits: Limits, live_limits: Limits) -> None:
    t = make_ticket(iv_rank_source="proxy")
    assert gates.volatility_regime(t, limits).passed  # shadow
    assert not gates.volatility_regime(t, live_limits).passed  # live


def test_spy_below_vix_floor_fails(limits: Limits) -> None:
    assert not gates.volatility_regime(make_spy_ticket(vix=15.7), limits).passed


def test_spy_missing_vix_fails(limits: Limits) -> None:
    assert not gates.volatility_regime(make_spy_ticket(vix=None), limits).passed


# --- gate 3: event risk ----------------------------------------------------------------------


def test_blocking_event_fails(limits: Limits) -> None:
    blocked = EventCheck(
        checked_through_expiry=True, blocking_events=["FOMC 2026-07-29"], detail="1 event"
    )
    assert not gates.event_risk(make_ticket(), limits, blocked).passed


def test_unchecked_events_fail_closed(limits: Limits) -> None:
    unknown = EventCheck(checked_through_expiry=False, blocking_events=[], detail="unknown")
    assert not gates.event_risk(make_ticket(), limits, unknown).passed


# --- gate 4: short delta ---------------------------------------------------------------------


def test_short_delta_boundaries(limits: Limits) -> None:
    for delta, ok in [(-0.20, True), (-0.30, True), (-0.19, False), (-0.31, False)]:
        t = make_ticket(legs=[make_leg(delta=delta), make_ticket().legs[1]])
        assert gates.short_delta_band(t, limits).passed is ok, delta


# --- gate 5: tenor ---------------------------------------------------------------------------


def test_dte_boundaries(limits: Limits) -> None:
    for days, ok in [(30, True), (45, True), (29, False), (46, False)]:
        expiry = (NOW + timedelta(days=days)).date()
        t = make_ticket(
            legs=[
                make_leg(expiry=expiry),
                make_leg(action="buy", strike=15.0, bid=0.30, ask=0.35, delta=-0.15,
                         expiry=expiry),
            ]
        )
        assert gates.tenor_band(t, limits, t.dte(NOW.date())).passed is ok, days


# --- gate 6: credit --------------------------------------------------------------------------


def test_credit_below_floor_fails(limits: Limits) -> None:
    t = make_ticket(legs=[make_leg(bid=0.50, ask=0.54), make_ticket().legs[1]])
    assert t.credit_mid < 0.25
    assert not gates.min_credit(t, limits).passed


def test_credit_exactly_at_floor_passes(limits: Limits) -> None:
    # sell mid 0.575, buy mid 0.325 -> credit 0.25
    t = make_ticket(legs=[make_leg(bid=0.55, ask=0.60), make_ticket().legs[1]])
    assert abs(t.credit_mid - 0.25) < 1e-9
    assert gates.min_credit(t, limits).passed


def test_spy_uses_lower_floor(limits: Limits) -> None:
    t = make_spy_ticket()
    assert 0.20 <= t.credit_mid < 0.25
    assert gates.min_credit(t, limits).passed


# --- gate 7: open interest -------------------------------------------------------------------


def test_thin_open_interest_fails(limits: Limits) -> None:
    t = make_ticket(legs=[make_leg(open_interest=499), make_ticket().legs[1]])
    assert not gates.open_interest(t, limits).passed


# --- gate 8: leg spread quality --------------------------------------------------------------


def test_wide_leg_market_fails(limits: Limits) -> None:
    t = make_ticket(legs=[make_leg(bid=0.50, ask=0.70), make_ticket().legs[1]])
    assert not gates.leg_spread_quality(t, limits).passed


def test_wide_but_cheap_relative_spread_passes(limits: Limits) -> None:
    # $0.06 spread fails the abs cap but is 8.6% of a $0.70 mid — pct branch passes
    t = make_ticket(legs=[make_leg(bid=0.67, ask=0.73), make_ticket().legs[1]])
    assert gates.leg_spread_quality(t, limits).passed


def test_crossed_market_fails(limits: Limits) -> None:
    t = make_ticket(legs=[make_leg(bid=0.62, ask=0.57), make_ticket().legs[1]])
    assert not gates.leg_spread_quality(t, limits).passed


# --- gate 9: trend alignment -----------------------------------------------------------------


def test_put_spread_below_200dma_fails(limits: Limits) -> None:
    assert not gates.trend_alignment(make_ticket(underlying_price=16.0), limits).passed


def test_call_spread_needs_downtrend(limits: Limits) -> None:
    t = make_ticket(
        structure=Structure.CALL_CREDIT_SPREAD,
        legs=[
            make_leg(option_type="call", strike=19.0, delta=0.25),
            make_leg(action="buy", option_type="call", strike=20.0, bid=0.30, ask=0.35,
                     delta=0.15),
        ],
        underlying_price=17.9,
        dma_200=16.5,
    )
    assert not gates.trend_alignment(t, limits).passed  # price above MA: no call spreads
    t2 = t.model_copy(update={"dma_200": 19.0})
    assert gates.trend_alignment(t2, limits).passed


# --- gate 10: quote freshness ----------------------------------------------------------------


def test_stale_quote_fails(limits: Limits) -> None:
    stale = NOW - timedelta(minutes=11)
    t = make_ticket(legs=[make_leg(quoted_at=stale), make_ticket().legs[1]])
    assert not gates.quote_freshness(t, limits, NOW).passed


def test_future_quote_fails(limits: Limits) -> None:
    t = make_ticket(legs=[make_leg(quoted_at=NOW + timedelta(minutes=5)), make_ticket().legs[1]])
    assert not gates.quote_freshness(t, limits, NOW).passed


# --- gate 11: max loss -----------------------------------------------------------------------


def test_two_contracts_fail_max_contracts(limits: Limits) -> None:
    assert not gates.max_loss_cap(make_ticket(contracts=2), limits).passed


def test_max_loss_within_cap_passes(limits: Limits) -> None:
    t = make_ticket()
    assert t.max_loss == 73.0
    assert gates.max_loss_cap(t, limits).passed
