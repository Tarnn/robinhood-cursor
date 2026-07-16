"""The only gate to live execution. /execute may call MCP place_option_order ONLY after this
passes. Everything here fails closed: shadow mode, missing probe, stale or mismatched
artifacts, active halts, and sizing all block."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel

from . import sizing
from . import state as state_mod
from .models import BreakerState, Limits, Opinion, TradeTicket, ValidationReport


class PreflightReport(BaseModel):
    passed: bool
    mode: str
    ticket_hash: str
    blocks: list[str]
    checks: list[str]


def run(
    *,
    ticket: TradeTicket,
    limits: Limits,
    state: BreakerState,
    validation: ValidationReport | None,
    opinion: Opinion | None,
    probe_path: Path,
    now: datetime,
) -> PreflightReport:
    blocks: list[str] = []
    checks: list[str] = []
    ticket_hash = ticket.canonical_hash()
    max_age = limits.approvals.max_freshness_minutes * 60

    if limits.mode != "live":
        blocks.append(f'mode is "{limits.mode}" — execution is disabled until a human flips '
                      "config/limits.json to live (see README shadow->live checklist)")
    else:
        checks.append("mode: live")

    if not probe_path.exists():
        blocks.append(f"day-0 capability probe not recorded ({probe_path}) — run /probe first")
    else:
        probe = json.loads(probe_path.read_text())
        if probe.get("multi_leg_supported") is True:
            checks.append("probe: multi-leg supported")
        else:
            blocks.append("probe says multi_leg_supported != true — the ruleset has no "
                          "single-leg strategy; human decision + ADR required")

    halts = state_mod.active_halts(state, now)
    if halts:
        blocks.append(f"active halt(s): {'; '.join(halts)}")
    else:
        checks.append("no active halts")

    if validation is None:
        blocks.append("no validation report — run `rht validate`")
    else:
        if validation.ticket_hash != ticket_hash:
            blocks.append("validation report hash does not match this ticket")
        if not validation.passed:
            failed = [r.gate for r in validation.results if not r.passed]
            blocks.append(f"validation failed gates: {failed}")
        if validation.rules_version != limits.rules_version:
            blocks.append(
                f"validation ran under rules {validation.rules_version}, "
                f"limits are {limits.rules_version}"
            )
        age = (now - _aware(validation.created_at)).total_seconds()
        if age > max_age:
            blocks.append(
                f"validation is {age / 60:.0f}m old (max {max_age / 60:.0f}m) — revalidate"
            )
        if validation.ticket_hash == ticket_hash and validation.passed and age <= max_age:
            checks.append("validation: all gates passed, fresh, hash-bound")

    if opinion is None:
        blocks.append("no second opinion — run `rht opinion request`")
    else:
        if opinion.ticket_hash != ticket_hash:
            blocks.append("second opinion hash does not match this ticket")
        if opinion.verdict != "APPROVE":
            blocks.append(f"second opinion is {opinion.verdict}: {'; '.join(opinion.reasons)}")
        age = (now - _aware(opinion.created_at)).total_seconds()
        if age > max_age:
            blocks.append(f"second opinion is {age / 60:.0f}m old (max {max_age / 60:.0f}m)")
        if opinion.ticket_hash == ticket_hash and opinion.verdict == "APPROVE" and age <= max_age:
            checks.append(f"second opinion: APPROVE ({opinion.provider}/{opinion.model})")

    size = sizing.check(ticket, limits, state)
    if size.passed:
        checks.append("sizing: " + "; ".join(size.checks))
    else:
        blocks.append("sizing: " + "; ".join(size.failures))

    return PreflightReport(
        passed=not blocks,
        mode=limits.mode,
        ticket_hash=ticket_hash,
        blocks=blocks,
        checks=checks,
    )


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)
