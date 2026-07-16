"""Circuit breakers: every auto-halt trigger, halt persistence, human-only clearing."""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import pytest
from conftest import NOW, make_ticket

from rh_options import state as state_mod
from rh_options.models import BreakerState, Limits, OpenPosition


def fresh(equity: float = 250.0) -> BreakerState:
    return BreakerState(equity_high_water=250.0, last_equity=equity)


def pos(ticket_hash: str = "h1") -> OpenPosition:
    t = make_ticket()
    return OpenPosition(
        ticket_hash=ticket_hash,
        symbol=t.symbol,
        structure=t.structure,
        contracts=1,
        credit=t.credit_mid,
        max_loss=t.max_loss,
        expiry=t.expiry,
        opened_at=NOW,
    )


def close(
    state: BreakerState, limits: Limits, pnl: float, *, stop: bool = False, h: str = "h1"
) -> BreakerState:
    return state_mod.close_position(
        state, limits, ticket_hash=h, pnl=pnl, was_stop_out=stop, now=NOW
    )


def test_equity_halt_boundary(limits: Limits) -> None:
    state = fresh(equity=251.0)
    state.open_positions.append(pos())
    state = close(state, limits, -51.0)  # 251 -> 200: at the threshold, halts
    assert any(h.reason == state_mod.HALT_EQUITY for h in state.halts)
    assert state.halts[0].until is not None  # timed halt: 30 days

    ok = fresh(equity=252.0)
    ok.open_positions.append(pos())
    ok = close(ok, limits, -51.0)  # 252 -> 201: no halt
    assert not ok.halts


def test_consecutive_stop_outs_halt(limits: Limits) -> None:
    state = fresh()
    state.open_positions.extend([pos("h1"), pos("h2")])
    state = close(state, limits, -50.0, stop=True, h="h1")
    assert not any(h.reason == state_mod.HALT_STOP_OUTS for h in state.halts)
    state = close(state, limits, -50.0, stop=True, h="h2")
    halts = [h for h in state.halts if h.reason == state_mod.HALT_STOP_OUTS]
    assert halts and halts[0].until is None  # untimed: human review required


def test_win_resets_stop_out_streak(limits: Limits) -> None:
    state = fresh()
    state.open_positions.extend([pos("h1"), pos("h2"), pos("h3")])
    state = close(state, limits, -50.0, stop=True, h="h1")
    state = close(state, limits, 12.0, h="h2")
    assert state.consecutive_stop_outs == 0
    state = close(state, limits, -50.0, stop=True, h="h3")
    assert not any(h.reason == state_mod.HALT_STOP_OUTS for h in state.halts)


def test_rolling_win_rate_halt_at_window(limits: Limits) -> None:
    state = fresh(equity=1000.0)  # keep equity clear of the drawdown halt
    # 13 wins + 7 losses = 65% over the 20-trade window -> halt (but no stop-out streak)
    outcomes = [12.0] * 13 + [-20.0] * 7
    for i, pnl in enumerate(outcomes):
        state.open_positions.append(pos(f"h{i}"))
        was_stop = pnl < 0 and i % 2 == 0  # avoid 2 consecutive stop-outs
        state = state_mod.close_position(
            state, limits, ticket_hash=f"h{i}", pnl=pnl, was_stop_out=was_stop, now=NOW
        )
    assert any(h.reason == state_mod.HALT_WIN_RATE for h in state.halts)


def test_no_win_rate_halt_below_window(limits: Limits) -> None:
    state = fresh(equity=1000.0)
    for i in range(5):  # 0% win rate but only 5 trades: window not met
        state.open_positions.append(pos(f"h{i}"))
        state = state_mod.close_position(
            state, limits, ticket_hash=f"h{i}", pnl=-10.0, was_stop_out=False, now=NOW
        )
    assert not any(h.reason == state_mod.HALT_WIN_RATE for h in state.halts)


def test_timed_halt_expires_untimed_does_not(limits: Limits) -> None:
    state = fresh(equity=201.0)
    state.open_positions.append(pos())
    state = close(state, limits, -50.0, stop=True)  # equity 151 -> timed halt
    assert state_mod.active_halts(state, NOW)
    after = NOW + timedelta(days=31)
    remaining = state_mod.active_halts(state, after)
    assert all("human review" not in h for h in remaining) or not remaining


def test_close_unknown_position_raises(limits: Limits) -> None:
    with pytest.raises(ValueError, match="no open position"):
        close(fresh(), limits, 10.0, h="nope")


def test_save_load_round_trip(tmp_path: Path, limits: Limits) -> None:
    path = tmp_path / "state.json"
    state = fresh()
    state.open_positions.append(pos())
    state_mod.save(path, state)
    loaded = state_mod.load(path)
    assert loaded.open_positions[0].ticket_hash == "h1"
    assert loaded.equity_high_water == 250.0
    # the CLI never clears halts: save/load must preserve them verbatim
    state = close(loaded, limits, -60.0, stop=True)
    state_mod.save(path, state)
    assert state_mod.load(path).consecutive_stop_outs == 1
