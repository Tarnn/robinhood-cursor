"""Free, keyless market data for the dashboard (Yahoo Finance via yfinance).

Research only: quotes are delayed and unofficial. Nothing here feeds the money path — real
tickets are built by the agent from live Robinhood MCP data. Every function degrades to
None/empty on network or parsing errors so the dashboard keeps rendering.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any

import pandas as pd
import yfinance as yf

from rh_options.screener import ChainRow, bs_delta, sma

VIX_SYMBOL = "^VIX"


@dataclass
class Quote:
    symbol: str
    price: float
    prev_close: float | None
    change_pct: float | None
    sma50: float | None
    sma200: float | None
    rv20: float | None
    closes: list[float]


def history(symbol: str, period: str = "1y") -> pd.DataFrame:
    try:
        df = yf.Ticker(symbol).history(period=period, auto_adjust=False)
    except Exception:
        return pd.DataFrame()
    return df if isinstance(df, pd.DataFrame) else pd.DataFrame()


def realized_vol(closes: list[float], n: int = 20) -> float | None:
    if len(closes) < n + 1:
        return None
    tail = closes[-(n + 1) :]
    rets = [math.log(tail[i + 1] / tail[i]) for i in range(n)]
    mean = sum(rets) / n
    var = sum((r - mean) ** 2 for r in rets) / (n - 1)
    return math.sqrt(var) * math.sqrt(252)


def quote(symbol: str) -> Quote | None:
    df = history(symbol, "1y")
    if df.empty or "Close" not in df:
        return None
    closes = [float(x) for x in df["Close"].dropna().tolist()]
    if not closes:
        return None
    prev = closes[-2] if len(closes) > 1 else None
    return Quote(
        symbol=symbol,
        price=closes[-1],
        prev_close=prev,
        change_pct=(closes[-1] / prev - 1) * 100 if prev else None,
        sma50=sma(closes, 50),
        sma200=sma(closes, 200),
        rv20=realized_vol(closes),
        closes=closes,
    )


def expiries(symbol: str) -> list[date]:
    try:
        raw = yf.Ticker(symbol).options
    except Exception:
        return []
    out = []
    for s in raw or ():
        try:
            out.append(date.fromisoformat(s))
        except ValueError:
            continue
    return out


def _num(x: Any, default: float = 0.0) -> float:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return default
    return default if math.isnan(v) else v


def chain(symbol: str, expiry: date) -> tuple[list[ChainRow], datetime]:
    """One expiry's chain as ChainRows (deltas left None; the screener computes them)."""
    fetched = datetime.now(UTC)
    try:
        oc = yf.Ticker(symbol).option_chain(expiry.isoformat())
    except Exception:
        return [], fetched
    rows: list[ChainRow] = []
    for otype, df in (("put", oc.puts), ("call", oc.calls)):
        for r in df.to_dict("records"):
            bid, ask = _num(r.get("bid")), _num(r.get("ask"))
            if bid <= 0 or ask <= 0:
                continue
            rows.append(
                ChainRow(
                    option_type=otype,  # type: ignore[arg-type]
                    strike=_num(r.get("strike")),
                    bid=bid,
                    ask=ask,
                    iv=_num(r.get("impliedVolatility")),
                    open_interest=int(_num(r.get("openInterest"))),
                )
            )
    return rows, fetched


def atm_iv(rows: list[ChainRow], spot: float) -> float | None:
    """Average IV of the put and call nearest the money."""
    ivs = []
    for otype in ("put", "call"):
        side = [r for r in rows if r.option_type == otype and r.iv > 0.01]
        if side:
            ivs.append(min(side, key=lambda r: abs(r.strike - spot)).iv)
    return sum(ivs) / len(ivs) if ivs else None


def pick_expiry(exps: list[date], today: date, dte_min: int, dte_max: int) -> date | None:
    """Expiry inside the tenor band, else the one nearest its midpoint."""
    if not exps:
        return None
    inside = [e for e in exps if dte_min <= (e - today).days <= dte_max]
    if inside:
        return inside[0]
    mid = (dte_min + dte_max) / 2
    return min(exps, key=lambda e: abs((e - today).days - mid))


def next_earnings(symbol: str) -> date | None:
    try:
        cal = yf.Ticker(symbol).calendar
    except Exception:
        return None
    raw = cal.get("Earnings Date") if isinstance(cal, dict) else None
    if not raw:
        return None
    first = raw[0] if isinstance(raw, list | tuple) else raw
    if isinstance(first, datetime):
        return first.date()
    return first if isinstance(first, date) else None


def news(symbol: str, limit: int = 8) -> list[dict[str, str]]:
    """Headlines as {title, publisher, url, published}; handles old and new yfinance shapes."""
    try:
        items = yf.Ticker(symbol).news or []
    except Exception:
        return []
    out = []
    for it in items[:limit]:
        c = it.get("content", it) if isinstance(it, dict) else {}
        canon = c.get("canonicalUrl")
        url = canon.get("url") if isinstance(canon, dict) else c.get("link", "")
        provider = c.get("provider")
        publisher = (
            provider.get("displayName", "") if isinstance(provider, dict)
            else c.get("publisher", "")
        )
        out.append(
            {
                "title": str(c.get("title", "")),
                "publisher": str(publisher),
                "url": str(url or ""),
                "published": str(c.get("pubDate", c.get("providerPublishTime", ""))),
            }
        )
    return [n for n in out if n["title"]]


__all__ = [
    "Quote", "VIX_SYMBOL", "atm_iv", "bs_delta", "chain", "expiries", "history",
    "news", "next_earnings", "pick_expiry", "quote", "realized_vol",
]
