"""Event gate: earnings/FOMC/CPI before expiry block; unknowns fail closed."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from rh_options.events import check_events

TODAY = date(2026, 7, 16)


def write_calendar(tmp_path: Path, **overrides: object) -> Path:
    doc: dict[str, object] = {
        "valid_through": "2026-12-31",
        "fomc": ["2026-07-28", "2026-07-29", "2026-09-15", "2026-09-16"],
        "cpi": ["2026-08-12", "2026-09-11"],
    }
    doc.update(overrides)
    path = tmp_path / "calendar.json"
    path.write_text(json.dumps(doc))
    return path


def test_clear_window_passes(tmp_path: Path) -> None:
    cal = write_calendar(tmp_path, fomc=[], cpi=[])
    check = check_events(
        symbol="SOFI",
        expiry=date(2026, 8, 20),
        today=TODAY,
        calendar_path=cal,
        next_earnings_date=date(2026, 10, 27),  # after expiry: fine
        earnings_confirmed_none=False,
    )
    assert check.checked_through_expiry and not check.blocking_events


def test_fomc_before_expiry_blocks(tmp_path: Path) -> None:
    check = check_events(
        symbol="SPY",
        expiry=date(2026, 8, 20),
        today=TODAY,
        calendar_path=write_calendar(tmp_path),
        next_earnings_date=None,
        earnings_confirmed_none=True,
    )
    assert check.blocking_events  # FOMC 7/28-29 and CPI 8/12 all land inside
    assert any("FOMC" in e for e in check.blocking_events)
    assert any("CPI" in e for e in check.blocking_events)


def test_earnings_inside_expiry_blocks(tmp_path: Path) -> None:
    cal = write_calendar(tmp_path, fomc=[], cpi=[])
    check = check_events(
        symbol="SOFI",
        expiry=date(2026, 8, 14),
        today=TODAY,
        calendar_path=cal,
        next_earnings_date=date(2026, 7, 29),  # the live SOFI trap from the research
        earnings_confirmed_none=False,
    )
    assert check.blocking_events == ["SOFI earnings 2026-07-29"]


def test_unknown_earnings_fails_closed(tmp_path: Path) -> None:
    cal = write_calendar(tmp_path, fomc=[], cpi=[])
    check = check_events(
        symbol="SOFI",
        expiry=date(2026, 8, 20),
        today=TODAY,
        calendar_path=cal,
        next_earnings_date=None,
        earnings_confirmed_none=False,
    )
    assert not check.checked_through_expiry


def test_expiry_past_calendar_validity_fails_closed(tmp_path: Path) -> None:
    cal = write_calendar(tmp_path, valid_through="2026-08-01")
    check = check_events(
        symbol="SOFI",
        expiry=date(2026, 9, 18),
        today=TODAY,
        calendar_path=cal,
        next_earnings_date=None,
        earnings_confirmed_none=True,
    )
    assert not check.checked_through_expiry
    assert "calendar" in check.detail


def test_event_on_expiry_day_does_not_block(tmp_path: Path) -> None:
    # strictly-before-expiry semantics: expiry-day AM events are the settlement's problem,
    # but the 14-DTE hard close means we are long gone anyway
    cal = write_calendar(tmp_path, fomc=[], cpi=["2026-08-20"])
    check = check_events(
        symbol="SOFI",
        expiry=date(2026, 8, 20),
        today=TODAY,
        calendar_path=cal,
        next_earnings_date=None,
        earnings_confirmed_none=True,
    )
    assert check.checked_through_expiry and not check.blocking_events
