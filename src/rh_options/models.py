"""Typed contracts for the trade pipeline.

Everything that crosses a boundary (agent -> validator -> reviewer -> preflight) is one of
these models. The ticket's canonical hash binds the pipeline together: validation reports and
second opinions embed it, and preflight refuses on any mismatch.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, date, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field


class Structure(StrEnum):
    PUT_CREDIT_SPREAD = "put_credit_spread"
    CALL_CREDIT_SPREAD = "call_credit_spread"
    IRON_CONDOR = "iron_condor"


class Leg(BaseModel):
    action: Literal["sell", "buy"]
    option_type: Literal["put", "call"]
    strike: float
    expiry: date
    bid: float
    ask: float
    delta: float
    open_interest: int
    quoted_at: datetime

    @property
    def mid(self) -> float:
        return (self.bid + self.ask) / 2

    @property
    def spread(self) -> float:
        return self.ask - self.bid


class TradeTicket(BaseModel):
    """One proposed trade, written by the agent from live MCP data. Pure data, no judgment."""

    symbol: str
    structure: Structure
    legs: list[Leg]
    contracts: int = 1
    underlying_price: float
    dma_200: float
    # Volatility context: exactly one of these paths gates entry (see gates.volatility_regime).
    vix: float | None = None
    iv_rank: float | None = None
    iv_rank_source: Literal["true", "proxy"] | None = None
    # Event context: the agent must either supply the next earnings date or explicitly attest
    # that it confirmed none exists before expiry. Absence of both fails the events gate.
    next_earnings_date: date | None = None
    earnings_confirmed_none: bool = False
    earnings_source: str = ""
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    note: str = ""

    @property
    def expiry(self) -> date:
        return self.legs[0].expiry

    def dte(self, today: date) -> int:
        return (self.expiry - today).days

    @property
    def credit_mid(self) -> float:
        """Net credit at mid per contract (positive = credit received)."""
        return sum(leg.mid if leg.action == "sell" else -leg.mid for leg in self.legs)

    @property
    def width(self) -> float:
        """Wing width per vertical. For iron condors both wings must match (gated)."""
        puts = sorted(leg.strike for leg in self.legs if leg.option_type == "put")
        calls = sorted(leg.strike for leg in self.legs if leg.option_type == "call")
        widths = []
        if len(puts) == 2:
            widths.append(puts[1] - puts[0])
        if len(calls) == 2:
            widths.append(calls[1] - calls[0])
        return max(widths) if widths else 0.0

    @property
    def max_loss(self) -> float:
        """Worst-case dollars for the whole position (one side of an IC can lose at expiry)."""
        return (self.width - self.credit_mid) * 100 * self.contracts

    @property
    def short_legs(self) -> list[Leg]:
        return [leg for leg in self.legs if leg.action == "sell"]

    def canonical_hash(self) -> str:
        payload = self.model_dump(mode="json")
        blob = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(blob.encode()).hexdigest()


class GateResult(BaseModel):
    gate: str
    passed: bool
    detail: str


class ValidationReport(BaseModel):
    ticket_hash: str
    rules_version: str
    mode: Literal["shadow", "live"]
    created_at: datetime
    results: list[GateResult]

    @property
    def passed(self) -> bool:
        return all(r.passed for r in self.results)


class Opinion(BaseModel):
    ticket_hash: str
    verdict: Literal["APPROVE", "VETO"]
    reasons: list[str]
    model: str
    provider: str
    created_at: datetime


class OpenPosition(BaseModel):
    ticket_hash: str
    symbol: str
    structure: Structure
    contracts: int
    credit: float
    max_loss: float
    expiry: date
    opened_at: datetime


class Halt(BaseModel):
    reason: str
    set_at: datetime
    until: datetime | None = None  # None = requires human review to clear


class TradeResult(BaseModel):
    trade_id: str
    win: bool
    pnl: float
    was_stop_out: bool = False


class BreakerState(BaseModel):
    schema_version: int = 1
    halts: list[Halt] = Field(default_factory=list)
    consecutive_stop_outs: int = 0
    equity_high_water: float
    last_equity: float
    rolling_results: list[TradeResult] = Field(default_factory=list)
    open_positions: list[OpenPosition] = Field(default_factory=list)
    updated_at: datetime | None = None


class EntryLimits(BaseModel):
    iv_rank_min: float
    vix_min_spy: float
    short_delta_min: float
    short_delta_max: float
    dte_min: int
    dte_max: int
    min_credit: float
    min_credit_spy: float
    min_open_interest: int
    max_leg_spread_abs: float
    max_leg_spread_pct_of_mid: float
    spread_width: float
    quote_max_age_minutes: int


class SizingLimits(BaseModel):
    max_contracts: int
    max_concurrent_positions: int
    max_loss_per_position: float
    max_total_open_risk: float
    min_cash_reserve: float


class ExitLimits(BaseModel):
    profit_target_pct_of_credit: float
    stop_multiple_of_credit: float
    hard_close_dte: int


class BreakerLimits(BaseModel):
    equity_halt_threshold: float
    equity_halt_days: int
    max_consecutive_stop_outs: int
    rolling_window_trades: int
    min_rolling_win_rate: float


class ExecutionLimits(BaseModel):
    walk_after_seconds: int
    max_chase_below_mid: float
    review_tolerance: float


class ApprovalLimits(BaseModel):
    max_freshness_minutes: int
    max_retries_per_symbol_per_day: int


class UniverseLimits(BaseModel):
    whitelist: list[str]
    iron_condor_only: list[str]
    spy_symbol: str


class Limits(BaseModel):
    rules_version: str
    mode: Literal["shadow", "live"]
    universe: UniverseLimits
    entry: EntryLimits
    sizing: SizingLimits
    exits: ExitLimits
    breakers: BreakerLimits
    execution: ExecutionLimits
    approvals: ApprovalLimits

    @classmethod
    def load(cls, path: Path) -> Limits:
        raw: dict[str, Any] = json.loads(path.read_text())
        raw.pop("//", None)
        return cls.model_validate(raw)
