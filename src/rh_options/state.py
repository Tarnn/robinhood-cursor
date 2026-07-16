"""Circuit-breaker state transitions. The CLI sets halts automatically and NEVER clears them —
clearing a halt is a deliberate human edit to config/state.json (docs/workflow.md)."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from .models import BreakerState, Limits, OpenPosition, TradeResult

HALT_EQUITY = "equity_drawdown"
HALT_STOP_OUTS = "consecutive_stop_outs"
HALT_WIN_RATE = "rolling_win_rate"


def load(path: Path) -> BreakerState:
    raw: dict[str, Any] = json.loads(path.read_text())
    raw.pop("//", None)
    return BreakerState.model_validate(raw)


def save(path: Path, state: BreakerState) -> None:
    doc: dict[str, Any] = {
        "//": "MACHINE-MUTATED ONLY via `rht state ...`. Halts are auto-set by the CLI and can "
        "only be cleared by a human editing this file (see docs/workflow.md). Committed for "
        "auditability.",
    }
    doc.update(state.model_dump(mode="json"))
    path.write_text(json.dumps(doc, indent=2) + "\n")


def active_halts(state: BreakerState, now: datetime) -> list[str]:
    """Halts still in force. Timed halts expire on their own; untimed ones need a human."""
    out = []
    for h in state.halts:
        if h.until is None or h.until > now:
            until = h.until.date().isoformat() if h.until else "human review"
            out.append(f"{h.reason} (until {until})")
    return out


def open_position(state: BreakerState, position: OpenPosition, now: datetime) -> BreakerState:
    state.open_positions.append(position)
    state.updated_at = now
    return state


def close_position(
    state: BreakerState,
    limits: Limits,
    *,
    ticket_hash: str,
    pnl: float,
    was_stop_out: bool,
    now: datetime,
    equity: float | None = None,
) -> BreakerState:
    """Close a position, record the result, and auto-set any tripped breakers."""
    remaining = [p for p in state.open_positions if p.ticket_hash != ticket_hash]
    if len(remaining) == len(state.open_positions):
        raise ValueError(f"no open position with ticket_hash {ticket_hash}")
    state.open_positions = remaining

    state.last_equity = equity if equity is not None else state.last_equity + pnl
    state.equity_high_water = max(state.equity_high_water, state.last_equity)
    state.consecutive_stop_outs = state.consecutive_stop_outs + 1 if was_stop_out else 0
    state.rolling_results.append(
        TradeResult(trade_id=ticket_hash, win=pnl > 0, pnl=pnl, was_stop_out=was_stop_out)
    )
    window = limits.breakers.rolling_window_trades
    state.rolling_results = state.rolling_results[-window:]

    _apply_breakers(state, limits, now)
    state.updated_at = now
    return state


def _apply_breakers(state: BreakerState, limits: Limits, now: datetime) -> None:
    from .models import Halt  # local import keeps module deps one-way

    reasons = {h.reason for h in state.halts}

    if state.last_equity <= limits.breakers.equity_halt_threshold and HALT_EQUITY not in reasons:
        state.halts.append(
            Halt(
                reason=HALT_EQUITY,
                set_at=now,
                until=now + timedelta(days=limits.breakers.equity_halt_days),
            )
        )

    if (
        state.consecutive_stop_outs >= limits.breakers.max_consecutive_stop_outs
        and HALT_STOP_OUTS not in reasons
    ):
        state.halts.append(Halt(reason=HALT_STOP_OUTS, set_at=now, until=None))

    window = limits.breakers.rolling_window_trades
    if len(state.rolling_results) >= window:
        win_rate = sum(1 for r in state.rolling_results if r.win) / len(state.rolling_results)
        if win_rate < limits.breakers.min_rolling_win_rate and HALT_WIN_RATE not in reasons:
            state.halts.append(Halt(reason=HALT_WIN_RATE, set_at=now, until=None))


def now_utc() -> datetime:
    return datetime.now(UTC)
