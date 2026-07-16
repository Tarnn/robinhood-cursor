"""IV-rank: true rank math, cold-start proxy labeling, snapshot idempotency."""

from __future__ import annotations

import math
from datetime import date, timedelta
from pathlib import Path

import pytest

from rh_options import ivrank


def seed(tmp_path: Path, symbol: str, ivs: list[float]) -> None:
    start = date(2026, 1, 5)
    for i, iv in enumerate(ivs):
        ivrank.append_snapshot(tmp_path, symbol, iv, start + timedelta(days=i))


def test_snapshot_idempotent_per_day(tmp_path: Path) -> None:
    day = date(2026, 7, 16)
    assert ivrank.append_snapshot(tmp_path, "sofi", 0.60, day) == 1
    assert ivrank.append_snapshot(tmp_path, "SOFI", 0.65, day) == 1  # same day: no dup
    assert ivrank.append_snapshot(tmp_path, "SOFI", 0.65, day + timedelta(days=1)) == 2


def test_true_rank_after_enough_snapshots(tmp_path: Path) -> None:
    seed(tmp_path, "SOFI", [0.40 + 0.005 * i for i in range(60)])  # 0.40 .. 0.695
    result = ivrank.rank(tmp_path, "SOFI", current_iv=0.695, closes=None)
    assert result.source == "true"
    assert result.rank == 100.0
    mid = ivrank.rank(tmp_path, "SOFI", current_iv=0.5475, closes=None)
    assert mid.rank == pytest.approx(50.0, abs=0.1)


def test_rank_clamped_to_bounds(tmp_path: Path) -> None:
    seed(tmp_path, "SOFI", [0.50] * 60 + [0.60])
    assert ivrank.rank(tmp_path, "SOFI", current_iv=0.90, closes=None).rank == 100.0
    assert ivrank.rank(tmp_path, "SOFI", current_iv=0.10, closes=None).rank == 0.0


def test_cold_start_without_closes_cannot_proxy(tmp_path: Path) -> None:
    result = ivrank.rank(tmp_path, "SOFI", current_iv=0.65, closes=None)
    assert result.source == "proxy"
    assert result.passes_proxy is False


def test_proxy_labeled_and_thresholded(tmp_path: Path) -> None:
    # constant 1% daily moves -> annualized RV ~ 0.159; threshold = 1.25 x RV ~ 0.199
    closes = [100.0 * math.exp(0.01 * ((-1) ** i)) ** i for i in range(25)]
    closes = [100.0]
    for i in range(24):
        closes.append(closes[-1] * math.exp(0.01 if i % 2 else -0.01))
    rv = ivrank.realized_vol_20d(closes)
    rich = ivrank.rank(tmp_path, "SOFI", current_iv=1.30 * rv, closes=closes)
    assert rich.source == "proxy" and rich.passes_proxy is True
    cheap = ivrank.rank(tmp_path, "SOFI", current_iv=1.20 * rv, closes=closes)
    assert cheap.passes_proxy is False
    assert "shadow-only" in rich.detail


def test_realized_vol_needs_21_closes() -> None:
    with pytest.raises(ValueError):
        ivrank.realized_vol_20d([100.0] * 20)
