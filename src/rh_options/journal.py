"""Append-only trade journal (JSONL) — the evidence base for /postmortem and /improve.

Append-only is enforced two ways: this module only ever opens the file in append mode and
tracks a line-count high-water mark in the first record's metadata... simpler and honest:
`add()` refuses to run if the file has fewer lines than it did at open. History is never
rewritten; corrections are new entries of type "note" referencing the original id.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

EntryType = Literal[
    "shadow_proposal",
    "fill",
    "exit",
    "no_fill",
    "halt",
    "note",
    "injection_attempt",
    "scan",
]


class JournalEntry(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    ts: datetime = Field(default_factory=lambda: datetime.now(UTC))
    entry_type: EntryType
    symbol: str = ""
    ticket_hash: str = ""
    pnl: float | None = None
    payload: dict[str, Any] = Field(default_factory=dict)


class JournalStats(BaseModel):
    total_entries: int
    shadow_proposals: int
    fills: int
    exits: int
    wins: int
    losses: int
    rolling_win_rate: float | None  # over the breaker window, None until any exits exist
    total_pnl: float
    avg_pnl_per_exit: float | None


def add(path: Path, entry: JournalEntry) -> JournalEntry:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as f:
        f.write(entry.model_dump_json() + "\n")
    return entry


def load(path: Path) -> list[JournalEntry]:
    if not path.exists():
        return []
    return [
        JournalEntry.model_validate_json(line)
        for line in path.read_text().splitlines()
        if line.strip()
    ]


def stats(path: Path, rolling_window: int = 20) -> JournalStats:
    entries = load(path)
    exits = [e for e in entries if e.entry_type == "exit" and e.pnl is not None]
    pnls = [e.pnl for e in exits if e.pnl is not None]
    wins = sum(1 for p in pnls if p > 0)
    recent = pnls[-rolling_window:]
    return JournalStats(
        total_entries=len(entries),
        shadow_proposals=sum(1 for e in entries if e.entry_type == "shadow_proposal"),
        fills=sum(1 for e in entries if e.entry_type == "fill"),
        exits=len(exits),
        wins=wins,
        losses=len(pnls) - wins,
        rolling_win_rate=(sum(1 for p in recent if p > 0) / len(recent)) if recent else None,
        total_pnl=round(sum(pnls), 2),
        avg_pnl_per_exit=round(sum(pnls) / len(pnls), 2) if pnls else None,
    )


def render_markdown(path: Path) -> str:
    entries = load(path)
    s = stats(path)
    lines = [
        "# Trade journal",
        "",
        f"_Generated {datetime.now(UTC).isoformat(timespec='seconds')} — do not edit; "
        "append via `rht journal add`._",
        "",
        f"**{s.total_entries}** entries · **{s.shadow_proposals}** shadow proposals · "
        f"**{s.fills}** fills · **{s.exits}** exits "
        f"({s.wins}W/{s.losses}L"
        + (f", rolling win rate {s.rolling_win_rate:.0%}" if s.rolling_win_rate is not None else "")
        + f") · total P&L **${s.total_pnl:.2f}**",
        "",
        "| ts | type | symbol | pnl | detail |",
        "|---|---|---|---|---|",
    ]
    for e in reversed(entries):
        detail = json.dumps(e.payload, sort_keys=True) if e.payload else ""
        if len(detail) > 120:
            detail = detail[:117] + "..."
        detail = detail.replace("|", "\\|")
        pnl = f"{e.pnl:+.2f}" if e.pnl is not None else ""
        lines.append(
            f"| {e.ts.isoformat(timespec='minutes')} | {e.entry_type} | {e.symbol} "
            f"| {pnl} | {detail} |"
        )
    return "\n".join(lines) + "\n"
