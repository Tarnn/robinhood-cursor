"""Screener: builds verticals from a chain and runs the real gates + POP/EV on them."""

from __future__ import annotations

from datetime import timedelta

import pytest
from conftest import NOW

from rh_options.events import EventCheck
from rh_options.models import Limits, Structure
from rh_options.screener import ChainRow, bs_delta, screen, sma

CLEAR = EventCheck(checked_through_expiry=True, blocking_events=[], detail="clear")
EXPIRY = (NOW + timedelta(days=35)).date()


def test_bs_delta_signs_and_atm() -> None:
    call = bs_delta(spot=100, strike=100, iv=0.3, dte_years=0.1, rate=0.0, option_type="call")
    put = bs_delta(spot=100, strike=100, iv=0.3, dte_years=0.1, rate=0.0, option_type="put")
    assert 0.5 < call < 0.53
    assert put == pytest.approx(call - 1.0)
    with pytest.raises(ValueError):
        bs_delta(spot=100, strike=100, iv=0, dte_years=0.1, rate=0.0, option_type="call")


def test_sma() -> None:
    assert sma([1, 2, 3, 4], 2) == 3.5
    assert sma([1.0], 2) is None


def chain() -> list[ChainRow]:
    # SOFI-like: spot 17.9, supplied deltas so the test doesn't depend on BS precision
    return [
        ChainRow(option_type="put", strike=17.0, bid=0.95, ask=1.00, iv=0.55,
                 open_interest=900, delta=-0.38),
        ChainRow(option_type="put", strike=16.0, bid=0.57, ask=0.62, iv=0.56,
                 open_interest=650, delta=-0.28),
        ChainRow(option_type="put", strike=15.0, bid=0.30, ask=0.35, iv=0.58,
                 open_interest=700, delta=-0.15),
        ChainRow(option_type="put", strike=14.0, bid=0.10, ask=0.14, iv=0.60,
                 open_interest=300, delta=-0.07),
        ChainRow(option_type="call", strike=19.0, bid=0.60, ask=0.66, iv=0.52,
                 open_interest=800, delta=0.27),
        ChainRow(option_type="call", strike=20.0, bid=0.31, ask=0.36, iv=0.53,
                 open_interest=600, delta=0.15),
    ]


def test_screen_finds_golden_spread(limits: Limits) -> None:
    cands = screen(
        symbol="SOFI", expiry=EXPIRY, spot=17.9, dma_200=16.5, chain=chain(), limits=limits,
        events=CLEAR, iv_rank=62.0, iv_rank_source="true", now=NOW,
    )
    best = cands[0]
    assert best.structure is Structure.PUT_CREDIT_SPREAD
    assert (best.short_strike, best.long_strike) == (16.0, 15.0)
    assert best.all_pass, best.failed_gates
    assert best.credit_mid == pytest.approx(0.27)
    assert best.max_loss == pytest.approx(73.0)
    assert best.pop_short_strike is not None and 0.5 < best.pop_short_strike < 1

    # call side: price above the 200dma, so the trend gate must fail it
    call = next(c for c in cands if c.structure is Structure.CALL_CREDIT_SPREAD)
    assert "trend_alignment" in [g.gate for g in call.failed_gates]
    # 17/16 put has |delta| 0.38: outside band + slack, never considered
    assert all(c.short_strike != 17.0 for c in cands)


def test_screen_stale_quotes_fail_freshness(limits: Limits) -> None:
    cands = screen(
        symbol="SOFI", expiry=EXPIRY, spot=17.9, dma_200=16.5, chain=chain(), limits=limits,
        events=CLEAR, iv_rank=62.0, iv_rank_source="true", now=NOW,
        quoted_at=NOW - timedelta(minutes=20),
    )
    assert all("quote_freshness" in [g.gate for g in c.failed_gates] for c in cands)


def test_screen_computes_delta_when_missing(limits: Limits) -> None:
    rows = [r.model_copy(update={"delta": None}) for r in chain()]
    cands = screen(
        symbol="SOFI", expiry=EXPIRY, spot=17.9, dma_200=16.5, chain=rows, limits=limits,
        events=CLEAR, iv_rank=62.0, iv_rank_source="true", now=NOW,
    )
    assert cands, "BS deltas should land some shorts in the band"
    assert all(c.short_delta < 0 for c in cands if c.structure is Structure.PUT_CREDIT_SPREAD)


def test_screen_expired_returns_nothing(limits: Limits) -> None:
    assert screen(
        symbol="SOFI", expiry=NOW.date(), spot=17.9, dma_200=16.5, chain=chain(),
        limits=limits, events=CLEAR, now=NOW,
    ) == []
