"""`rht` — the deterministic pipeline the agent must drive.

Every subcommand prints a JSON report to stdout and signals with exit codes:
0 = pass · 1 = fail/blocked · 2 = configuration or reviewer error (always blocks trades).

Artifacts are hash-bound: validate/opinion write to data/validations|opinions/<ticket-hash>.json
and preflight cross-checks those hashes, so approvals cannot be reused across edited tickets.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from . import events as events_mod
from . import gates, ivrank, journal, pop_ev, preflight, second_opinion, sizing
from . import state as state_mod
from .models import (
    Limits,
    OpenPosition,
    Opinion,
    TradeTicket,
    ValidationReport,
)

EXIT_PASS, EXIT_FAIL, EXIT_ERROR = 0, 1, 2


def find_root(start: Path | None = None) -> Path:
    cur = (start or Path.cwd()).resolve()
    for candidate in (cur, *cur.parents):
        if (candidate / "config" / "limits.json").exists():
            return candidate
    print(json.dumps({"error": "not inside the repo (config/limits.json not found)"}))
    raise SystemExit(EXIT_ERROR)


def _emit(payload: Any) -> None:
    if hasattr(payload, "model_dump"):
        payload = payload.model_dump(mode="json")
    print(json.dumps(payload, indent=2, sort_keys=True))


def _load_ticket(path: str) -> TradeTicket:
    return TradeTicket.model_validate_json(Path(path).read_text())


def _events_for_ticket(root: Path, ticket: TradeTicket, today: date) -> events_mod.EventCheck:
    return events_mod.check_events(
        symbol=ticket.symbol,
        expiry=ticket.expiry,
        today=today,
        calendar_path=root / "config" / "calendar_2026.json",
        next_earnings_date=ticket.next_earnings_date,
        earnings_confirmed_none=ticket.earnings_confirmed_none,
    )


def cmd_validate(args: argparse.Namespace) -> int:
    root = find_root()
    limits = Limits.load(root / "config" / "limits.json")
    ticket = _load_ticket(args.ticket)
    now = datetime.now(UTC)
    results = gates.run_all(ticket, limits, _events_for_ticket(root, ticket, now.date()), now)
    report = ValidationReport(
        ticket_hash=ticket.canonical_hash(),
        rules_version=limits.rules_version,
        mode=limits.mode,
        created_at=now,
        results=results,
    )
    out = root / "data" / "validations" / f"{report.ticket_hash}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(report.model_dump_json(indent=2))
    _emit(report)
    return EXIT_PASS if report.passed else EXIT_FAIL


def cmd_preflight(args: argparse.Namespace) -> int:
    root = find_root()
    limits = Limits.load(root / "config" / "limits.json")
    ticket = _load_ticket(args.ticket)
    ticket_hash = ticket.canonical_hash()
    state = state_mod.load(root / "config" / "state.json")

    validation: ValidationReport | None = None
    vpath = root / "data" / "validations" / f"{ticket_hash}.json"
    if vpath.exists():
        validation = ValidationReport.model_validate_json(vpath.read_text())
    opinion: Opinion | None = None
    opath = root / "data" / "opinions" / f"{ticket_hash}.json"
    if opath.exists():
        opinion = Opinion.model_validate_json(opath.read_text())

    report = preflight.run(
        ticket=ticket,
        limits=limits,
        state=state,
        validation=validation,
        opinion=opinion,
        probe_path=root / "data" / "probe" / "day0.json",
        now=datetime.now(UTC),
    )
    _emit(report)
    return EXIT_PASS if report.passed else EXIT_FAIL


def cmd_pop(args: argparse.Namespace) -> int:
    ticket = _load_ticket(args.ticket)
    report = pop_ev.analyze(ticket, iv=args.iv, today=datetime.now(UTC).date())
    _emit(report)
    return EXIT_PASS


def cmd_size(args: argparse.Namespace) -> int:
    root = find_root()
    limits = Limits.load(root / "config" / "limits.json")
    state = state_mod.load(root / "config" / "state.json")
    report = sizing.check(_load_ticket(args.ticket), limits, state)
    _emit(report)
    return EXIT_PASS if report.passed else EXIT_FAIL


def cmd_iv(args: argparse.Namespace) -> int:
    root = find_root()
    data_dir = root / "data"
    if args.iv_cmd == "snapshot":
        n = ivrank.append_snapshot(data_dir, args.symbol, args.iv, datetime.now(UTC).date())
        _emit({"symbol": args.symbol.upper(), "snapshots": n})
        return EXIT_PASS
    closes: list[float] | None = None
    if args.closes_file:
        closes = [float(x) for x in json.loads(Path(args.closes_file).read_text())]
    result = ivrank.rank(data_dir, args.symbol, args.iv, closes)
    _emit(result)
    ok = (result.source == "true" and result.rank is not None) or bool(result.passes_proxy)
    return EXIT_PASS if ok else EXIT_FAIL


def cmd_events(args: argparse.Namespace) -> int:
    root = find_root()
    check = events_mod.check_events(
        symbol=args.symbol,
        expiry=date.fromisoformat(args.expiry),
        today=datetime.now(UTC).date(),
        calendar_path=root / "config" / "calendar_2026.json",
        next_earnings_date=date.fromisoformat(args.earnings_date) if args.earnings_date else None,
        earnings_confirmed_none=args.confirmed_none,
    )
    _emit(check)
    return EXIT_PASS if check.checked_through_expiry and not check.blocking_events else EXIT_FAIL


def cmd_journal(args: argparse.Namespace) -> int:
    root = find_root()
    jpath = root / "data" / "journal.jsonl"
    if args.journal_cmd == "add":
        payload = json.loads(args.payload) if args.payload else {}
        entry = journal.add(
            jpath,
            journal.JournalEntry(
                entry_type=args.type,
                symbol=args.symbol or "",
                ticket_hash=args.ticket_hash or "",
                pnl=args.pnl,
                payload=payload,
            ),
        )
        _emit(entry)
        return EXIT_PASS
    if args.journal_cmd == "render":
        md = journal.render_markdown(jpath)
        (root / "data" / "journal.md").write_text(md)
        _emit({"rendered": str(root / "data" / "journal.md")})
        return EXIT_PASS
    _emit(journal.stats(jpath))
    return EXIT_PASS


def cmd_state(args: argparse.Namespace) -> int:
    root = find_root()
    spath = root / "config" / "state.json"
    limits = Limits.load(root / "config" / "limits.json")
    state = state_mod.load(spath)
    now = datetime.now(UTC)

    if args.state_cmd == "status":
        _emit(state)
        return EXIT_PASS
    if args.state_cmd == "check-halts":
        halts = state_mod.active_halts(state, now)
        _emit({"active_halts": halts, "clear": not halts})
        return EXIT_PASS if not halts else EXIT_FAIL
    if args.state_cmd == "open":
        ticket = _load_ticket(args.ticket)
        pos = OpenPosition(
            ticket_hash=ticket.canonical_hash(),
            symbol=ticket.symbol,
            structure=ticket.structure,
            contracts=ticket.contracts,
            credit=ticket.credit_mid,
            max_loss=ticket.max_loss,
            expiry=ticket.expiry,
            opened_at=now,
        )
        state_mod.save(spath, state_mod.open_position(state, pos, now))
        _emit(pos)
        return EXIT_PASS
    # close
    try:
        state = state_mod.close_position(
            state,
            limits,
            ticket_hash=args.ticket_hash,
            pnl=args.pnl,
            was_stop_out=args.stop_out,
            now=now,
            equity=args.equity,
        )
    except ValueError as exc:
        _emit({"error": str(exc)})
        return EXIT_ERROR
    state_mod.save(spath, state)
    _emit(state)
    return EXIT_PASS if not state_mod.active_halts(state, now) else EXIT_FAIL


def cmd_opinion(args: argparse.Namespace) -> int:
    root = find_root()
    load_dotenv(root / ".env")
    ticket = _load_ticket(args.ticket)
    ticket_hash = ticket.canonical_hash()
    vpath = root / "data" / "validations" / f"{ticket_hash}.json"
    if not vpath.exists():
        _emit({"error": "validate first — no validation report for this ticket"})
        return EXIT_ERROR
    validation = ValidationReport.model_validate_json(vpath.read_text())
    pop = pop_ev.analyze(ticket, iv=args.iv, today=datetime.now(UTC).date())
    try:
        opinion = second_opinion.request_opinion(
            ticket=ticket,
            validation=validation,
            pop_ev=pop.model_dump(mode="json"),
            rules_text=(root / "rules" / "RULES.md").read_text(),
        )
    except second_opinion.ReviewerError as exc:
        _emit({"error": str(exc), "verdict": "BLOCKED"})
        return EXIT_ERROR
    out = root / "data" / "opinions" / f"{ticket_hash}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(opinion.model_dump_json(indent=2))
    _emit(opinion)
    return EXIT_PASS if opinion.verdict == "APPROVE" else EXIT_FAIL


def cmd_probe(args: argparse.Namespace) -> int:
    root = find_root()
    raw = json.loads(Path(args.results).read_text())
    required = {"multi_leg_supported", "account_type", "options_level", "notes"}
    missing = required - raw.keys()
    if missing:
        _emit({"error": f"probe results missing fields: {sorted(missing)}"})
        return EXIT_ERROR
    if not isinstance(raw["multi_leg_supported"], bool):
        _emit(
            {
                "error": "multi_leg_supported must be a boolean "
                "(from a real review_option_order simulation)"
            }
        )
        return EXIT_ERROR
    raw["recorded_at"] = datetime.now(UTC).isoformat()
    out = root / "data" / "probe" / "day0.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(raw, indent=2, sort_keys=True) + "\n")
    _emit(raw)
    return EXIT_PASS


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="rht", description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("validate", help="run all entry gates on a ticket")
    sp.add_argument("ticket")
    sp.set_defaults(fn=cmd_validate)

    sp = sub.add_parser("preflight", help="the only gate to live execution")
    sp.add_argument("ticket")
    sp.set_defaults(fn=cmd_preflight)

    sp = sub.add_parser("pop", help="Black-Scholes POP + EV after costs")
    sp.add_argument("ticket")
    sp.add_argument("--iv", type=float, required=True, help="annualized IV, e.g. 0.24")
    sp.set_defaults(fn=cmd_pop)

    sp = sub.add_parser("size", help="sizing checks against account state")
    sp.add_argument("ticket")
    sp.set_defaults(fn=cmd_size)

    sp = sub.add_parser("iv", help="IV snapshots and rank")
    ivsub = sp.add_subparsers(dest="iv_cmd", required=True)
    s1 = ivsub.add_parser("snapshot")
    s1.add_argument("symbol")
    s1.add_argument("--iv", type=float, required=True)
    s2 = ivsub.add_parser("rank")
    s2.add_argument("symbol")
    s2.add_argument("--iv", type=float, required=True)
    s2.add_argument("--closes-file", help="JSON array of >=21 daily closes (for the proxy)")
    sp.set_defaults(fn=cmd_iv)

    sp = sub.add_parser("events", help="earnings/FOMC/CPI-before-expiry check")
    evsub = sp.add_subparsers(dest="events_cmd", required=True)
    s3 = evsub.add_parser("check")
    s3.add_argument("--symbol", required=True)
    s3.add_argument("--expiry", required=True)
    s3.add_argument("--earnings-date")
    s3.add_argument("--confirmed-none", action="store_true")
    sp.set_defaults(fn=cmd_events)

    sp = sub.add_parser("journal", help="append-only journal")
    jsub = sp.add_subparsers(dest="journal_cmd", required=True)
    s4 = jsub.add_parser("add")
    s4.add_argument("--type", required=True)
    s4.add_argument("--symbol")
    s4.add_argument("--ticket-hash")
    s4.add_argument("--pnl", type=float)
    s4.add_argument("--payload", help="JSON object")
    jsub.add_parser("render")
    jsub.add_parser("stats")
    sp.set_defaults(fn=cmd_journal)

    sp = sub.add_parser("state", help="circuit-breaker state (halts auto-set, human-cleared)")
    ssub = sp.add_subparsers(dest="state_cmd", required=True)
    ssub.add_parser("status")
    ssub.add_parser("check-halts")
    s5 = ssub.add_parser("open")
    s5.add_argument("ticket")
    s6 = ssub.add_parser("close")
    s6.add_argument("--ticket-hash", required=True)
    s6.add_argument("--pnl", type=float, required=True)
    s6.add_argument("--stop-out", action="store_true")
    s6.add_argument("--equity", type=float, help="actual account equity from get_portfolio")
    sp.set_defaults(fn=cmd_state)

    sp = sub.add_parser("opinion", help="mandatory cross-model second opinion")
    osub = sp.add_subparsers(dest="opinion_cmd", required=True)
    s7 = osub.add_parser("request")
    s7.add_argument("ticket")
    s7.add_argument("--iv", type=float, required=True)
    sp.set_defaults(fn=cmd_opinion)

    sp = sub.add_parser("probe", help="record day-0 capability probe results")
    psub = sp.add_subparsers(dest="probe_cmd", required=True)
    s8 = psub.add_parser("record")
    s8.add_argument("results")
    sp.set_defaults(fn=cmd_probe)

    return p


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    try:
        code = int(args.fn(args))
    except FileNotFoundError as exc:
        _emit({"error": f"missing file: {exc.filename}"})
        code = EXIT_ERROR
    except (json.JSONDecodeError, ValueError) as exc:
        _emit({"error": str(exc)})
        code = EXIT_ERROR
    sys.exit(code)
