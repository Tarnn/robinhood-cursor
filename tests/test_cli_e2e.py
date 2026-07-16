"""End-to-end shadow rehearsal through the real CLI: ticket -> validate -> preflight refuses
(shadow) -> journal -> stats. Runs in a temp repo root so real data/ and config/ stay clean."""

from __future__ import annotations

import json
import shutil
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from conftest import REPO_ROOT, make_ticket

from rh_options import cli


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    (tmp_path / "config").mkdir()
    (tmp_path / "rules").mkdir()
    for name in ("limits.json", "state.json"):
        shutil.copy(REPO_ROOT / "config" / name, tmp_path / "config" / name)
    shutil.copy(REPO_ROOT / "rules" / "RULES.md", tmp_path / "rules" / "RULES.md")
    # empty macro calendar so the golden ticket's dynamic expiry can't collide with real events
    (tmp_path / "config" / "calendar_2026.json").write_text(
        json.dumps({"valid_through": "2027-12-31", "fomc": [], "cpi": []})
    )
    monkeypatch.chdir(tmp_path)
    return tmp_path


def fresh_ticket(repo: Path) -> Path:
    """Golden ticket re-timestamped to real now (the CLI validates freshness against wall clock)."""
    now = datetime.now(UTC)
    ticket = make_ticket()
    payload: dict[str, Any] = ticket.model_dump(mode="json")
    payload["created_at"] = now.isoformat()
    expiry = (now + timedelta(days=35)).date().isoformat()
    for leg in payload["legs"]:
        leg["quoted_at"] = now.isoformat()
        leg["expiry"] = expiry
    path = repo / "ticket.json"
    path.write_text(json.dumps(payload))
    return path


def run(argv: list[str]) -> int:
    with pytest.raises(SystemExit) as excinfo:
        cli.main(argv)
    return int(excinfo.value.code)


def test_shadow_lifecycle(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    ticket_path = fresh_ticket(repo)

    # 1. validate: all gates pass, report written and hash-bound
    assert run(["validate", str(ticket_path)]) == 0
    report = json.loads(capsys.readouterr().out)
    assert all(r["passed"] for r in report["results"])
    assert (repo / "data" / "validations" / f"{report['ticket_hash']}.json").exists()

    # 2. preflight: structurally refused in shadow mode
    assert run(["preflight", str(ticket_path)]) == 1
    pf = json.loads(capsys.readouterr().out)
    assert pf["passed"] is False
    assert any('mode is "shadow"' in b for b in pf["blocks"])

    # 3. journal the shadow proposal, then stats reflect it
    assert (
        run(
            [
                "journal", "add", "--type", "shadow_proposal", "--symbol", "SOFI",
                "--ticket-hash", report["ticket_hash"],
                "--payload", json.dumps({"credit": 0.27}),
            ]
        )
        == 0
    )
    capsys.readouterr()
    assert run(["journal", "stats"]) == 0
    stats = json.loads(capsys.readouterr().out)
    assert stats["shadow_proposals"] == 1

    # 4. halts are clear on a fresh account
    assert run(["state", "check-halts"]) == 0


def test_validate_rejects_bad_ticket(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    ticket_path = fresh_ticket(repo)
    doc = json.loads(ticket_path.read_text())
    doc["iv_rank"] = 12.0  # low-vol regime: the correct output is no trade
    ticket_path.write_text(json.dumps(doc))
    assert run(["validate", str(ticket_path)]) == 1
    report = json.loads(capsys.readouterr().out)
    failed = [r["gate"] for r in report["results"] if not r["passed"]]
    assert failed == ["volatility_regime"]


def test_probe_record_validates_schema(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    bad = repo / "probe.json"
    bad.write_text(json.dumps({"multi_leg_supported": "yes"}))  # wrong type + missing fields
    assert run(["probe", "record", str(bad)]) == 2

    capsys.readouterr()
    good = repo / "probe2.json"
    good.write_text(
        json.dumps(
            {
                "multi_leg_supported": True,
                "account_type": "margin",
                "options_level": 3,
                "notes": "review_option_order simulated a 2-leg SPY spread successfully",
            }
        )
    )
    assert run(["probe", "record", str(good)]) == 0
    assert (repo / "data" / "probe" / "day0.json").exists()


def test_missing_ticket_file_is_config_error(repo: Path) -> None:
    assert run(["validate", "nope.json"]) == 2
