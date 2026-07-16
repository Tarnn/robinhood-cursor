"""IV-rank tracking (ADR-0001): snapshot accumulation with a labeled realized-vol fallback.

Every /scan appends one ATM-IV snapshot per symbol. A true rank needs >= MIN_SNAPSHOTS points;
until then the proxy (ATM IV vs 20-day realized vol) applies and is valid in shadow mode only —
the volatility_regime gate enforces that.
"""

from __future__ import annotations

import json
import math
from datetime import date
from pathlib import Path
from typing import Any

from pydantic import BaseModel

MIN_SNAPSHOTS = 60
TRAILING_WINDOW = 252
PROXY_RV_MULTIPLE = 1.25
TRADING_DAYS = 252


class IvRankResult(BaseModel):
    symbol: str
    iv: float
    source: str  # "true" | "proxy"
    rank: float | None = None  # 0-100 when source == "true"
    rv_20d: float | None = None  # annualized, when source == "proxy"
    passes_proxy: bool | None = None
    snapshots: int
    detail: str


def snapshot_path(data_dir: Path, symbol: str) -> Path:
    return data_dir / "iv_history" / f"{symbol.upper()}.jsonl"


def append_snapshot(data_dir: Path, symbol: str, iv: float, on: date) -> int:
    """Record today's ATM IV (idempotent per calendar day). Returns total snapshot count."""
    path = snapshot_path(data_dir, symbol)
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = _load(path)
    if not any(r["date"] == on.isoformat() for r in rows):
        with path.open("a") as f:
            f.write(json.dumps({"date": on.isoformat(), "iv": iv}) + "\n")
        rows.append({"date": on.isoformat(), "iv": iv})
    return len(rows)


def realized_vol_20d(closes: list[float]) -> float:
    """Annualized close-to-close volatility over the last 20 returns."""
    if len(closes) < 21:
        raise ValueError(f"need >= 21 closes, got {len(closes)}")
    tail = closes[-21:]
    rets = [math.log(tail[i + 1] / tail[i]) for i in range(20)]
    mean = sum(rets) / len(rets)
    var = sum((r - mean) ** 2 for r in rets) / (len(rets) - 1)
    return math.sqrt(var) * math.sqrt(TRADING_DAYS)


def rank(
    data_dir: Path, symbol: str, current_iv: float, closes: list[float] | None
) -> IvRankResult:
    rows = _load(snapshot_path(data_dir, symbol))
    n = len(rows)
    if n >= MIN_SNAPSHOTS:
        ivs = [float(r["iv"]) for r in rows[-TRAILING_WINDOW:]]
        lo, hi = min(ivs), max(ivs)
        pct = 50.0 if hi == lo else 100.0 * (current_iv - lo) / (hi - lo)
        pct = max(0.0, min(100.0, pct))
        return IvRankResult(
            symbol=symbol,
            iv=current_iv,
            source="true",
            rank=round(pct, 1),
            snapshots=n,
            detail=f"true rank over {len(ivs)} snapshots (range {lo:.3f}-{hi:.3f})",
        )
    if closes is None:
        return IvRankResult(
            symbol=symbol,
            iv=current_iv,
            source="proxy",
            passes_proxy=False,
            snapshots=n,
            detail=f"only {n}/{MIN_SNAPSHOTS} snapshots and no closes supplied — cannot even proxy",
        )
    rv = realized_vol_20d(closes)
    passes = current_iv >= PROXY_RV_MULTIPLE * rv
    return IvRankResult(
        symbol=symbol,
        iv=current_iv,
        source="proxy",
        rv_20d=round(rv, 4),
        passes_proxy=passes,
        snapshots=n,
        detail=(
            f"proxy ({n}/{MIN_SNAPSHOTS} snapshots): IV {current_iv:.3f} "
            f"{'>=' if passes else '<'} {PROXY_RV_MULTIPLE} x RV20 {rv:.3f} — shadow-only"
        ),
    )


def _load(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
