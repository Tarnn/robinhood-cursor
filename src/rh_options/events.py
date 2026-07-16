"""Event-risk checking: earnings (agent-supplied from MCP) + FOMC/CPI (static calendar).

Named events gap prices; the gate blocks any ticket whose expiry crosses one. Fails closed:
an unknown earnings situation or a calendar that doesn't cover the expiry is a block, not a
pass. (`get_earnings_calendar` only sees 31 days out — for 30-45 DTE tickets the agent must
also confirm via the symbol's last report + typical cycle; see the mcp-recipes skill.)
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from pydantic import BaseModel


class EventCheck(BaseModel):
    checked_through_expiry: bool
    blocking_events: list[str]
    detail: str


def check_events(
    *,
    symbol: str,
    expiry: date,
    today: date,
    calendar_path: Path,
    next_earnings_date: date | None,
    earnings_confirmed_none: bool,
) -> EventCheck:
    raw = json.loads(calendar_path.read_text())
    valid_through = date.fromisoformat(raw["valid_through"])
    if expiry > valid_through:
        return EventCheck(
            checked_through_expiry=False,
            blocking_events=[],
            detail=f"macro calendar only valid through {valid_through}, expiry {expiry} — "
            "refresh config/calendar_2026.json",
        )

    blocking: list[str] = []
    for kind in ("fomc", "cpi"):
        for iso in raw[kind]:
            d = date.fromisoformat(iso)
            if today < d < expiry:
                blocking.append(f"{kind.upper()} {d}")

    if next_earnings_date is not None:
        if today < next_earnings_date < expiry:
            blocking.append(f"{symbol} earnings {next_earnings_date}")
    elif not earnings_confirmed_none:
        return EventCheck(
            checked_through_expiry=False,
            blocking_events=[],
            detail="earnings unknown: supply next_earnings_date or set earnings_confirmed_none "
            "after explicitly verifying no report lands before expiry",
        )

    detail = (
        f"clear through {expiry}" if not blocking else f"{len(blocking)} blocking event(s)"
    )
    return EventCheck(checked_through_expiry=True, blocking_events=blocking, detail=detail)
