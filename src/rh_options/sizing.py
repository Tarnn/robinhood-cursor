"""Position sizing checks against account state. All-or-nothing: any failure blocks the trade."""

from __future__ import annotations

from pydantic import BaseModel

from .models import BreakerState, Limits, TradeTicket

# Symbols treated as the same underlying exposure for the concurrency check.
CORRELATED_GROUPS: list[set[str]] = [{"SPY"}]  # each symbol also always correlates with itself


class SizingReport(BaseModel):
    passed: bool
    checks: list[str]
    failures: list[str]


def _correlated(a: str, b: str) -> bool:
    if a == b:
        return True
    return any(a in group and b in group for group in CORRELATED_GROUPS)


def check(ticket: TradeTicket, limits: Limits, state: BreakerState) -> SizingReport:
    checks: list[str] = []
    failures: list[str] = []

    if ticket.contracts > limits.sizing.max_contracts:
        failures.append(f"{ticket.contracts} contracts > max {limits.sizing.max_contracts}")
    else:
        checks.append(f"contracts {ticket.contracts} <= {limits.sizing.max_contracts}")

    if len(state.open_positions) >= limits.sizing.max_concurrent_positions:
        failures.append(
            f"{len(state.open_positions)} open position(s) — max "
            f"{limits.sizing.max_concurrent_positions} concurrent"
        )
    else:
        checks.append(
            f"open positions {len(state.open_positions)} < {limits.sizing.max_concurrent_positions}"
        )

    for pos in state.open_positions:
        if _correlated(pos.symbol, ticket.symbol):
            failures.append(f"already exposed to {pos.symbol}; {ticket.symbol} is correlated")

    open_risk = sum(p.max_loss for p in state.open_positions)
    total = open_risk + ticket.max_loss
    if total > limits.sizing.max_total_open_risk:
        failures.append(
            f"total open risk ${total:.0f} > cap ${limits.sizing.max_total_open_risk:.0f}"
        )
    else:
        checks.append(f"total open risk ${total:.0f} <= ${limits.sizing.max_total_open_risk:.0f}")

    # Cash floor: worst-case equity after this trade must keep the reserve intact.
    worst_case_equity = state.last_equity - total
    if worst_case_equity < limits.sizing.min_cash_reserve:
        failures.append(
            f"worst-case equity ${worst_case_equity:.0f} < reserve "
            f"${limits.sizing.min_cash_reserve:.0f}"
        )
    else:
        checks.append(
            f"worst-case equity ${worst_case_equity:.0f} >= ${limits.sizing.min_cash_reserve:.0f}"
        )

    return SizingReport(passed=not failures, checks=checks, failures=failures)
