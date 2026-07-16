"""Shared fixtures. NO TEST TOUCHES THE NETWORK — the autouse guard below hard-fails any
attempt to open a socket, so a regression can't silently call a real API from CI."""

from __future__ import annotations

import socket
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from rh_options.models import Leg, Limits, Structure, TradeTicket

REPO_ROOT = Path(__file__).resolve().parents[1]

NOW = datetime(2026, 7, 16, 15, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def no_network(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    def blocked(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("network access attempted in a unit test")

    monkeypatch.setattr(socket.socket, "connect", blocked)
    yield


@pytest.fixture
def limits() -> Limits:
    return Limits.load(REPO_ROOT / "config" / "limits.json")


@pytest.fixture
def live_limits(limits: Limits) -> Limits:
    return limits.model_copy(update={"mode": "live"})


def make_leg(**overrides: Any) -> Leg:
    base: dict[str, Any] = {
        "action": "sell",
        "option_type": "put",
        "strike": 16.0,
        "expiry": (NOW + timedelta(days=35)).date(),
        "bid": 0.57,
        "ask": 0.62,
        "delta": -0.28,
        "open_interest": 650,
        "quoted_at": NOW,
    }
    base.update(overrides)
    return Leg(**base)


def make_ticket(**overrides: Any) -> TradeTicket:
    """Golden SOFI put credit spread that passes every gate as of NOW.

    credit = (0.57+0.62)/2 - (0.30+0.35)/2 = 0.27; max loss = (1 - 0.27) * 100 = $73.
    """
    base: dict[str, Any] = {
        "symbol": "SOFI",
        "structure": Structure.PUT_CREDIT_SPREAD,
        "legs": [
            make_leg(),
            make_leg(action="buy", strike=15.0, bid=0.30, ask=0.35, delta=-0.15,
                     open_interest=700),
        ],
        "contracts": 1,
        "underlying_price": 17.9,
        "dma_200": 16.5,
        "iv_rank": 62.0,
        "iv_rank_source": "true",
        "next_earnings_date": None,
        "earnings_confirmed_none": True,
        "earnings_source": "test fixture",
        "created_at": NOW,
    }
    base.update(overrides)
    return TradeTicket(**base)


def make_spy_ticket(**overrides: Any) -> TradeTicket:
    base: dict[str, Any] = {
        "symbol": "SPY",
        "legs": [
            make_leg(strike=700.0, bid=0.22, ask=0.26, delta=-0.25),
            make_leg(action="buy", strike=699.0, bid=0.02, ask=0.04, delta=-0.20,
                     open_interest=900),
        ],
        "underlying_price": 754.0,
        "dma_200": 700.5,
        "vix": 19.5,
        "iv_rank": None,
        "iv_rank_source": None,
    }
    merged = {**base, **overrides}
    return make_ticket(**merged)
