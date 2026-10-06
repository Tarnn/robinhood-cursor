"""Read-only desk snapshot — one JSON document a UI (or a human) can read without parsing the
internal files. Never writes anything and never touches the network: it only reads config/,
data/ and the journal, then derives status (halts, open-position exit levels, go-live
progress, pipeline artifact freshness, upcoming macro events).
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from pydantic import BaseModel

from . import ivrank, journal
from . import state as state_mod
from .journal import JournalEntry, JournalStats
from .models import BreakerState, Limits, Opinion, TradeTicket, ValidationReport

# Go-live thresholds from the README "Shadow -> live" checklist.
GO_LIVE_MIN_PROPOSALS = 10
GO_LIVE_MIN_DAYS = 14
# Warn when the macro calendar stops covering a max-DTE ticket opened within this many days.
CALENDAR_WARN_DAYS = 30


class PositionView(BaseModel):
    ticket_hash: str
    symbol: str
    structure: str
    contracts: int
    credit: float
    max_loss: float
    expiry: date
    dte: int
    hard_close_on: date
    days_to_hard_close: int
    take_profit_debit: float  # buy back at or below this to hit the profit target
    stop_debit: float  # buy back at or above this = stop-out
    opened_at: datetime


class ChecklistItem(BaseModel):
    item: str
    done: bool
    detail: str


class PipelineItem(BaseModel):
    file: str
    symbol: str
    structure: str
    ticket_hash: str
    created_at: datetime
    credit_mid: float
    max_loss: float
    validation: str  # "missing" | "passed" | "failed"
    failed_gates: list[str]
    validation_age_min: float | None
    opinion: str  # "missing" | "APPROVE" | "VETO"
    opinion_age_min: float | None
    fresh: bool  # validation + opinion both present, passing and within the freshness window


class EquityPoint(BaseModel):
    ts: datetime
    equity: float
    pnl: float


class MacroEvent(BaseModel):
    kind: str
    on: date
    days_away: int


class EntryWindow(BaseModel):
    entry_on: date
    clear_dtes: list[int]  # DTEs inside the tenor band with no FOMC/CPI before expiry


class DeskSnapshot(BaseModel):
    generated_at: datetime
    rules_version: str
    mode: str
    whitelist: list[str]
    active_halts: list[str]
    last_equity: float
    equity_high_water: float
    drawdown_pct: float
    consecutive_stop_outs: int
    positions: list[PositionView]
    open_risk: float
    journal: JournalStats
    equity_curve: list[EquityPoint]
    recent_journal: list[JournalEntry]
    go_live: list[ChecklistItem]
    iv_snapshots: dict[str, int]
    pipeline: list[PipelineItem]
    upcoming_events: list[MacroEvent]
    calendar_valid_through: date
    entry_windows: list[EntryWindow]
    entry_window_days_scanned: int
    warnings: list[str]


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def _position_views(
    limits: Limits, state_path: Path, today: date
) -> tuple[list[PositionView], float, BreakerState]:
    st = state_mod.load(state_path)
    views = []
    for p in st.open_positions:
        hard_close = p.expiry - timedelta(days=limits.exits.hard_close_dte)
        views.append(
            PositionView(
                ticket_hash=p.ticket_hash,
                symbol=p.symbol,
                structure=str(p.structure),
                contracts=p.contracts,
                credit=round(p.credit, 2),
                max_loss=round(p.max_loss, 2),
                expiry=p.expiry,
                dte=(p.expiry - today).days,
                hard_close_on=hard_close,
                days_to_hard_close=(hard_close - today).days,
                take_profit_debit=round(
                    p.credit * (1 - limits.exits.profit_target_pct_of_credit), 2
                ),
                stop_debit=round(p.credit * limits.exits.stop_multiple_of_credit, 2),
                opened_at=p.opened_at,
            )
        )
    return views, round(sum(p.max_loss for p in st.open_positions), 2), st


def _equity_curve(entries: list[journal.JournalEntry], start_equity: float) -> list[EquityPoint]:
    """Cumulative equity from journaled exits, starting at the account's initial equity."""
    out: list[EquityPoint] = []
    equity = start_equity
    for e in entries:
        if e.entry_type == "exit" and e.pnl is not None:
            equity += e.pnl
            out.append(EquityPoint(ts=e.ts, equity=round(equity, 2), pnl=e.pnl))
    return out


def _pipeline(root: Path, limits: Limits, now: datetime) -> list[PipelineItem]:
    tickets_dir = root / "data" / "tickets"
    max_age = limits.approvals.max_freshness_minutes
    items: list[PipelineItem] = []
    for path in sorted(tickets_dir.glob("*.json")):
        try:
            ticket = TradeTicket.model_validate_json(path.read_text())
        except ValueError:
            continue  # malformed tickets are the validator's problem, not the dashboard's
        h = ticket.canonical_hash()
        validation, failed, v_age = "missing", [], None
        vpath = root / "data" / "validations" / f"{h}.json"
        if vpath.exists():
            rep = ValidationReport.model_validate_json(vpath.read_text())
            validation = "passed" if rep.passed else "failed"
            failed = [r.gate for r in rep.results if not r.passed]
            v_age = round((now - _aware(rep.created_at)).total_seconds() / 60, 1)
        opinion, o_age = "missing", None
        opath = root / "data" / "opinions" / f"{h}.json"
        if opath.exists():
            op = Opinion.model_validate_json(opath.read_text())
            opinion = op.verdict
            o_age = round((now - _aware(op.created_at)).total_seconds() / 60, 1)
        fresh = (
            validation == "passed"
            and opinion == "APPROVE"
            and v_age is not None
            and o_age is not None
            and v_age <= max_age
            and o_age <= max_age
        )
        items.append(
            PipelineItem(
                file=path.name,
                symbol=ticket.symbol,
                structure=str(ticket.structure),
                ticket_hash=h,
                created_at=ticket.created_at,
                credit_mid=round(ticket.credit_mid, 2),
                max_loss=round(ticket.max_loss, 2),
                validation=validation,
                failed_gates=failed,
                validation_age_min=v_age,
                opinion=opinion,
                opinion_age_min=o_age,
                fresh=fresh,
            )
        )
    items.sort(key=lambda i: _aware(i.created_at), reverse=True)
    return items


def _go_live(
    root: Path,
    limits: Limits,
    entries: list[journal.JournalEntry],
    iv_counts: dict[str, int],
    now: datetime,
) -> list[ChecklistItem]:
    proposals = [e for e in entries if e.entry_type == "shadow_proposal"]
    first = min((_aware(e.ts) for e in proposals), default=None)
    days = (now - first).days if first else 0

    probe_path = root / "data" / "probe" / "day0.json"
    probe_ok, probe_detail = False, "not recorded — run /probe"
    if probe_path.exists():
        probe = json.loads(probe_path.read_text())
        probe_ok = probe.get("multi_leg_supported") is True
        probe_detail = f"multi_leg_supported={probe.get('multi_leg_supported')}"

    ready = [s for s, n in iv_counts.items() if n >= ivrank.MIN_SNAPSHOTS]
    non_spy = [s for s in limits.universe.whitelist if s != limits.universe.spy_symbol]
    return [
        ChecklistItem(
            item=f">= {GO_LIVE_MIN_PROPOSALS} shadow proposals journaled",
            done=len(proposals) >= GO_LIVE_MIN_PROPOSALS,
            detail=f"{len(proposals)}/{GO_LIVE_MIN_PROPOSALS}",
        ),
        ChecklistItem(
            item=f">= {GO_LIVE_MIN_DAYS} days of shadow trading",
            done=days >= GO_LIVE_MIN_DAYS,
            detail=f"{days}/{GO_LIVE_MIN_DAYS} days since first proposal"
            if first
            else "no proposals yet",
        ),
        ChecklistItem(item="day-0 probe: multi-leg supported", done=probe_ok, detail=probe_detail),
        ChecklistItem(
            item=f"true IV rank ({ivrank.MIN_SNAPSHOTS} snapshots) for non-SPY symbols",
            done=bool(non_spy) and all(s in ready for s in non_spy),
            detail=", ".join(
                f"{s} {iv_counts.get(s, 0)}/{ivrank.MIN_SNAPSHOTS}" for s in non_spy
            ),
        ),
        ChecklistItem(
            item='human flipped config/limits.json to "live"',
            done=limits.mode == "live",
            detail=f'mode is "{limits.mode}"',
        ),
    ]


def entry_windows(
    cal: dict[str, list[str] | str], limits: Limits, start: date, days: int
) -> list[EntryWindow]:
    """Entry dates in [start, start+days) where at least one DTE in the tenor band clears the
    macro calendar (earnings are per-symbol and not included). With monthly CPI and a 30-45
    DTE band this list is often empty — the dashboard surfaces that rather than hiding it."""
    valid_through = date.fromisoformat(str(cal["valid_through"]))
    macro = sorted(
        date.fromisoformat(x) for kind in ("fomc", "cpi") for x in cal[kind] if isinstance(x, str)
    )
    out: list[EntryWindow] = []
    for offset in range(days):
        day = start + timedelta(days=offset)
        clear = [
            dte
            for dte in range(limits.entry.dte_min, limits.entry.dte_max + 1)
            if day + timedelta(days=dte) <= valid_through
            and not any(day < m < day + timedelta(days=dte) for m in macro)
        ]
        if clear:
            out.append(EntryWindow(entry_on=day, clear_dtes=clear))
    return out


def build(root: Path, now: datetime | None = None) -> DeskSnapshot:
    now = now or datetime.now(UTC)
    today = now.date()
    limits = Limits.load(root / "config" / "limits.json")
    positions, open_risk, st = _position_views(limits, root / "config" / "state.json", today)
    jpath = root / "data" / "journal.jsonl"
    entries = journal.load(jpath)
    stats = journal.stats(jpath, rolling_window=limits.breakers.rolling_window_trades)
    start_equity = st.last_equity - stats.total_pnl

    iv_counts = {
        s: len(ivrank._load(ivrank.snapshot_path(root / "data", s)))
        for s in limits.universe.whitelist
    }

    cal = json.loads((root / "config" / "calendar_2026.json").read_text())
    valid_through = date.fromisoformat(cal["valid_through"])
    events = sorted(
        (
            MacroEvent(kind=kind.upper(), on=d, days_away=(d - today).days)
            for kind in ("fomc", "cpi")
            for d in (date.fromisoformat(x) for x in cal[kind])
            if d >= today
        ),
        key=lambda e: e.on,
    )

    warnings: list[str] = []
    window_days = 90
    windows = entry_windows(cal, limits, today, window_days)
    if not windows:
        warnings.append(
            f"no entry date in the next {window_days} days has a {limits.entry.dte_min}-"
            f"{limits.entry.dte_max} DTE expiry clear of FOMC/CPI — the event gate will block "
            "every ticket (see RULES.md gate 3)"
        )
    horizon = today + timedelta(days=limits.entry.dte_max + CALENDAR_WARN_DAYS)
    if valid_through < horizon:
        warnings.append(
            f"macro calendar ends {valid_through}: tickets expiring after it fail the event "
            "gate — add next year's FOMC/CPI dates to config/calendar_2026.json"
        )
    for p in positions:
        if p.days_to_hard_close <= 0:
            warnings.append(f"{p.symbol}: past the {limits.exits.hard_close_dte}-DTE hard close")

    hw = st.equity_high_water
    return DeskSnapshot(
        generated_at=now,
        rules_version=limits.rules_version,
        mode=limits.mode,
        whitelist=limits.universe.whitelist,
        active_halts=state_mod.active_halts(st, now),
        last_equity=st.last_equity,
        equity_high_water=hw,
        drawdown_pct=round(100 * (hw - st.last_equity) / hw, 2) if hw else 0.0,
        consecutive_stop_outs=st.consecutive_stop_outs,
        positions=positions,
        open_risk=open_risk,
        journal=stats,
        equity_curve=_equity_curve(entries, start_equity),
        recent_journal=list(reversed(entries[-50:])),
        go_live=_go_live(root, limits, entries, iv_counts, now),
        iv_snapshots=iv_counts,
        pipeline=_pipeline(root, limits, now),
        upcoming_events=events,
        calendar_valid_through=valid_through,
        entry_windows=windows,
        entry_window_days_scanned=window_days,
        warnings=warnings,
    )
