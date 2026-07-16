"""Sizing edges: concurrency, correlation, total-risk cap, cash floor."""

from __future__ import annotations

from datetime import timedelta

from conftest import NOW, make_ticket

from rh_options import sizing
from rh_options.models import BreakerState, Limits, OpenPosition, Structure


def fresh_state(equity: float = 250.0) -> BreakerState:
    return BreakerState(equity_high_water=max(equity, 250.0), last_equity=equity)


def open_pos(symbol: str = "T", max_loss: float = 75.0) -> OpenPosition:
    return OpenPosition(
        ticket_hash="a" * 64,
        symbol=symbol,
        structure=Structure.PUT_CREDIT_SPREAD,
        contracts=1,
        credit=0.25,
        max_loss=max_loss,
        expiry=(NOW + timedelta(days=35)).date(),
        opened_at=NOW,
    )


def test_clean_account_passes(limits: Limits) -> None:
    assert sizing.check(make_ticket(), limits, fresh_state()).passed


def test_second_position_blocked_at_max_one(limits: Limits) -> None:
    state = fresh_state()
    state.open_positions.append(open_pos())
    report = sizing.check(make_ticket(), limits, state)
    assert not report.passed
    assert any("concurrent" in f for f in report.failures)


def test_same_symbol_correlation_blocked(limits: Limits) -> None:
    two_position_limits = limits.model_copy(deep=True)
    two_position_limits.sizing.max_concurrent_positions = 2
    state = fresh_state()
    state.open_positions.append(open_pos(symbol="SOFI"))
    report = sizing.check(make_ticket(), limits=two_position_limits, state=state)
    assert not report.passed
    assert any("correlated" in f for f in report.failures)


def test_total_risk_cap(limits: Limits) -> None:
    two_position_limits = limits.model_copy(deep=True)
    two_position_limits.sizing.max_concurrent_positions = 2
    state = fresh_state(equity=400.0)  # plenty of cash, so only the risk cap binds
    state.open_positions.append(open_pos(symbol="T", max_loss=80.0))
    report = sizing.check(make_ticket(), limits=two_position_limits, state=state)  # 80+73 > 150
    assert not report.passed
    assert any("total open risk" in f for f in report.failures)


def test_cash_floor_boundary(limits: Limits) -> None:
    # golden ticket risks $73; worst-case equity = equity - 73 must stay >= $100
    assert sizing.check(make_ticket(), limits, fresh_state(equity=173.0)).passed
    assert not sizing.check(make_ticket(), limits, fresh_state(equity=172.99)).passed
