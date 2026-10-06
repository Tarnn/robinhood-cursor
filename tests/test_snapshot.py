"""Desk snapshot: read-only aggregation of state, journal, pipeline and calendar."""

from __future__ import annotations

import json
import shutil
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest
from conftest import NOW, REPO_ROOT, make_ticket

from rh_options import cli, journal, snapshot
from rh_options.models import Limits, Opinion, ValidationReport


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    (tmp_path / "config").mkdir()
    for name in ("limits.json", "state.json"):
        shutil.copy(REPO_ROOT / "config" / name, tmp_path / "config" / name)
    (tmp_path / "config" / "calendar_2026.json").write_text(
        json.dumps({"valid_through": "2027-12-31", "fomc": ["2026-07-28"], "cpi": []})
    )
    return tmp_path


def test_empty_desk(repo: Path) -> None:
    snap = snapshot.build(repo, NOW)
    assert snap.mode == "shadow"
    assert snap.active_halts == []
    assert snap.positions == []
    assert snap.pipeline == []
    assert snap.equity_curve == []
    assert snap.journal.total_entries == 0
    assert [e.on for e in snap.upcoming_events] == [date(2026, 7, 28)]
    assert not any(item.done for item in snap.go_live)


def test_positions_journal_and_pipeline(repo: Path) -> None:
    # open position in state
    state = json.loads((repo / "config" / "state.json").read_text())
    state["open_positions"] = [
        {
            "ticket_hash": "abc",
            "symbol": "SOFI",
            "structure": "put_credit_spread",
            "contracts": 1,
            "credit": 0.30,
            "max_loss": 70.0,
            "expiry": "2026-08-21",
            "opened_at": NOW.isoformat(),
        }
    ]
    (repo / "config" / "state.json").write_text(json.dumps(state))

    # journal: 10 proposals 20 days ago, one exit
    jpath = repo / "data" / "journal.jsonl"
    for i in range(10):
        journal.add(
            jpath,
            journal.JournalEntry(
                entry_type="shadow_proposal", symbol="SOFI", ts=NOW - timedelta(days=20, hours=i)
            ),
        )
    journal.add(jpath, journal.JournalEntry(entry_type="exit", symbol="SOFI", pnl=12.5, ts=NOW))

    # one ticket with a passing validation and an APPROVE opinion, both fresh
    ticket = make_ticket()
    (repo / "data" / "tickets").mkdir(parents=True)
    (repo / "data" / "tickets" / "t1.json").write_text(ticket.model_dump_json())
    h = ticket.canonical_hash()
    limits = Limits.load(repo / "config" / "limits.json")
    (repo / "data" / "validations").mkdir()
    (repo / "data" / "validations" / f"{h}.json").write_text(
        ValidationReport(
            ticket_hash=h, rules_version=limits.rules_version, mode="shadow",
            created_at=NOW - timedelta(minutes=3), results=[],
        ).model_dump_json()
    )
    (repo / "data" / "opinions").mkdir()
    (repo / "data" / "opinions" / f"{h}.json").write_text(
        Opinion(
            ticket_hash=h, verdict="APPROVE", reasons=["ok"], model="m", provider="p",
            created_at=NOW - timedelta(minutes=2),
        ).model_dump_json()
    )

    snap = snapshot.build(repo, NOW)

    (pos,) = snap.positions
    assert pos.dte == (date(2026, 8, 21) - NOW.date()).days
    assert pos.hard_close_on == date(2026, 8, 7)
    assert pos.take_profit_debit == 0.15
    assert pos.stop_debit == 0.60
    assert snap.open_risk == 70.0

    assert snap.journal.shadow_proposals == 10
    assert snap.equity_curve[-1].equity == 250.0  # state equity already includes the pnl
    assert snap.equity_curve[-1].pnl == 12.5
    assert snap.go_live[0].done and snap.go_live[1].done

    (item,) = snap.pipeline
    assert item.validation == "passed" and item.opinion == "APPROVE" and item.fresh


def test_stale_approval_is_not_fresh(repo: Path) -> None:
    ticket = make_ticket()
    (repo / "data" / "tickets").mkdir(parents=True)
    (repo / "data" / "tickets" / "t1.json").write_text(ticket.model_dump_json())
    snap = snapshot.build(repo, NOW + timedelta(hours=1))
    (item,) = snap.pipeline
    assert item.validation == "missing" and item.opinion == "missing" and not item.fresh


def test_entry_windows_detects_blocked_calendar(repo: Path) -> None:
    limits = Limits.load(repo / "config" / "limits.json")
    start = date(2026, 7, 1)
    monthly = {
        "valid_through": "2027-12-31",
        "fomc": [],
        "cpi": [(start + timedelta(days=28 * i)).isoformat() for i in range(10)],
    }
    assert snapshot.entry_windows(monthly, limits, start, 60) == []

    empty = {"valid_through": "2027-12-31", "fomc": [], "cpi": []}
    windows = snapshot.entry_windows(empty, limits, start, 3)
    assert len(windows) == 3
    assert windows[0].clear_dtes == list(range(limits.entry.dte_min, limits.entry.dte_max + 1))


def test_snapshot_cli(
    repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.chdir(repo)
    with pytest.raises(SystemExit) as exc:
        cli.main(["snapshot"])
    assert exc.value.code == 0
    doc = json.loads(capsys.readouterr().out)
    assert doc["mode"] == "shadow"
    assert datetime.fromisoformat(doc["generated_at"]).tzinfo == UTC
