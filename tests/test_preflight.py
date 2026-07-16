"""Preflight is the only gate to live execution — every block path must actually block."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from conftest import NOW, make_ticket

from rh_options import gates, preflight
from rh_options.events import EventCheck
from rh_options.models import BreakerState, Limits, Opinion, TradeTicket, ValidationReport

CLEAR = EventCheck(checked_through_expiry=True, blocking_events=[], detail="clear")


def fresh_state() -> BreakerState:
    return BreakerState(equity_high_water=250.0, last_equity=250.0)


def passing_validation(ticket: TradeTicket, limits: Limits, at: datetime = NOW) -> ValidationReport:
    return ValidationReport(
        ticket_hash=ticket.canonical_hash(),
        rules_version=limits.rules_version,
        mode=limits.mode,
        created_at=at,
        results=gates.run_all(ticket, limits, CLEAR, NOW),
    )


def approve(ticket: TradeTicket, at: datetime = NOW) -> Opinion:
    return Opinion(
        ticket_hash=ticket.canonical_hash(),
        verdict="APPROVE",
        reasons=["ok"],
        model="test",
        provider="anthropic",
        created_at=at,
    )


@pytest.fixture
def probe_ok(tmp_path: Path) -> Path:
    p = tmp_path / "day0.json"
    p.write_text(json.dumps({"multi_leg_supported": True, "account_type": "margin"}))
    return p


def run(
    ticket: TradeTicket,
    limits: Limits,
    *,
    state: BreakerState | None = None,
    validation: ValidationReport | None = None,
    opinion: Opinion | None = None,
    probe: Path,
    now: datetime = NOW,
) -> preflight.PreflightReport:
    return preflight.run(
        ticket=ticket,
        limits=limits,
        state=state or fresh_state(),
        validation=validation,
        opinion=opinion,
        probe_path=probe,
        now=now,
    )


def test_full_pass_in_live_mode(live_limits: Limits, probe_ok: Path) -> None:
    t = make_ticket()
    report = run(
        t,
        live_limits,
        validation=passing_validation(t, live_limits),
        opinion=approve(t),
        probe=probe_ok,
    )
    assert report.passed, report.blocks


def test_shadow_mode_always_blocks(limits: Limits, probe_ok: Path) -> None:
    t = make_ticket()
    report = run(
        t, limits, validation=passing_validation(t, limits), opinion=approve(t), probe=probe_ok
    )
    assert not report.passed
    assert any('mode is "shadow"' in b for b in report.blocks)


def test_missing_probe_blocks(live_limits: Limits, tmp_path: Path) -> None:
    t = make_ticket()
    report = run(
        t,
        live_limits,
        validation=passing_validation(t, live_limits),
        opinion=approve(t),
        probe=tmp_path / "missing.json",
    )
    assert not report.passed
    assert any("probe" in b for b in report.blocks)


def test_probe_without_multileg_blocks(live_limits: Limits, tmp_path: Path) -> None:
    p = tmp_path / "day0.json"
    p.write_text(json.dumps({"multi_leg_supported": False}))
    t = make_ticket()
    report = run(
        t, live_limits, validation=passing_validation(t, live_limits), opinion=approve(t), probe=p
    )
    assert not report.passed
    assert any("single-leg" in b for b in report.blocks)


def test_missing_artifacts_block(live_limits: Limits, probe_ok: Path) -> None:
    report = run(make_ticket(), live_limits, probe=probe_ok)
    assert not report.passed
    assert any("no validation report" in b for b in report.blocks)
    assert any("no second opinion" in b for b in report.blocks)


def test_hash_mismatch_blocks(live_limits: Limits, probe_ok: Path) -> None:
    t = make_ticket()
    other = make_ticket(underlying_price=18.5)  # the agent edited the ticket after approval
    report = run(
        t,
        live_limits,
        validation=passing_validation(other, live_limits),
        opinion=approve(other),
        probe=probe_ok,
    )
    assert not report.passed
    assert sum("hash" in b for b in report.blocks) == 2


def test_stale_artifacts_block(live_limits: Limits, probe_ok: Path) -> None:
    t = make_ticket()
    stale = NOW - timedelta(minutes=16)
    report = run(
        t,
        live_limits,
        validation=passing_validation(t, live_limits, at=stale),
        opinion=approve(t, at=stale),
        probe=probe_ok,
    )
    assert not report.passed
    assert sum("old" in b for b in report.blocks) == 2


def test_veto_blocks(live_limits: Limits, probe_ok: Path) -> None:
    t = make_ticket()
    veto = approve(t).model_copy(update={"verdict": "VETO", "reasons": ["regime"]})
    report = run(
        t, live_limits, validation=passing_validation(t, live_limits), opinion=veto, probe=probe_ok
    )
    assert not report.passed
    assert any("VETO" in b for b in report.blocks)


def test_active_halt_blocks(live_limits: Limits, probe_ok: Path) -> None:
    from rh_options.models import Halt

    state = fresh_state()
    state.halts.append(Halt(reason="consecutive_stop_outs", set_at=NOW, until=None))
    t = make_ticket()
    report = run(
        t,
        live_limits,
        state=state,
        validation=passing_validation(t, live_limits),
        opinion=approve(t),
        probe=probe_ok,
    )
    assert not report.passed
    assert any("halt" in b for b in report.blocks)


def test_failed_validation_blocks(live_limits: Limits, probe_ok: Path) -> None:
    t = make_ticket(iv_rank=30.0)  # fails the volatility gate
    report = run(
        t, live_limits, validation=passing_validation(t, live_limits), opinion=approve(t),
        probe=probe_ok,
    )
    assert not report.passed
    assert any("volatility_regime" in b for b in report.blocks)


def test_rules_version_mismatch_blocks(live_limits: Limits, probe_ok: Path) -> None:
    t = make_ticket()
    old = passing_validation(t, live_limits).model_copy(update={"rules_version": "0.9.0"})
    report = run(t, live_limits, validation=old, opinion=approve(t), probe=probe_ok)
    assert not report.passed
    assert any("rules 0.9.0" in b for b in report.blocks)


def test_naive_datetime_treated_as_utc(live_limits: Limits, probe_ok: Path) -> None:
    t = make_ticket()
    naive = NOW.replace(tzinfo=None)
    report = run(
        t,
        live_limits,
        validation=passing_validation(t, live_limits, at=naive),  # type: ignore[arg-type]
        opinion=approve(t),
        probe=probe_ok,
        now=datetime.now(UTC).replace(year=2026, month=7, day=16, hour=15, minute=5),
    )
    # freshness math must not crash on naive timestamps; 5 minutes old passes
    assert not any("old" in b for b in report.blocks)
