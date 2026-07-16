"""Journal: JSONL round-trip, stats, markdown render. History is only ever appended."""

from __future__ import annotations

from pathlib import Path

from rh_options import journal


def test_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "journal.jsonl"
    e1 = journal.add(path, journal.JournalEntry(entry_type="shadow_proposal", symbol="SOFI"))
    journal.add(path, journal.JournalEntry(entry_type="fill", symbol="SOFI", ticket_hash="abc"))
    entries = journal.load(path)
    assert [e.entry_type for e in entries] == ["shadow_proposal", "fill"]
    assert entries[0].id == e1.id
    assert entries[0].ts.tzinfo is not None


def test_add_appends_never_rewrites(tmp_path: Path) -> None:
    path = tmp_path / "journal.jsonl"
    journal.add(path, journal.JournalEntry(entry_type="note", payload={"n": 1}))
    before = path.read_text()
    journal.add(path, journal.JournalEntry(entry_type="note", payload={"n": 2}))
    after = path.read_text()
    assert after.startswith(before)  # existing bytes untouched


def test_stats_win_rate_and_pnl(tmp_path: Path) -> None:
    path = tmp_path / "journal.jsonl"
    for pnl in [12.5, 13.0, -50.0, 11.0]:
        journal.add(path, journal.JournalEntry(entry_type="exit", symbol="SOFI", pnl=pnl))
    journal.add(path, journal.JournalEntry(entry_type="shadow_proposal", symbol="T"))
    s = journal.stats(path)
    assert s.exits == 4 and s.wins == 3 and s.losses == 1
    assert s.rolling_win_rate == 0.75
    assert s.total_pnl == -13.5
    assert s.avg_pnl_per_exit == -3.38


def test_stats_empty_journal(tmp_path: Path) -> None:
    s = journal.stats(tmp_path / "journal.jsonl")
    assert s.total_entries == 0
    assert s.rolling_win_rate is None
    assert s.avg_pnl_per_exit is None


def test_render_markdown(tmp_path: Path) -> None:
    path = tmp_path / "journal.jsonl"
    journal.add(
        path,
        journal.JournalEntry(
            entry_type="exit", symbol="SOFI", pnl=12.5, payload={"reason": "profit|target"}
        ),
    )
    md = journal.render_markdown(path)
    assert "| exit | SOFI " in md
    assert "+12.50" in md
    assert "profit\\|target" in md  # pipes escaped so the table renders
