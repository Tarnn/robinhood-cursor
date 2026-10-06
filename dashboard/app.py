"""Desk dashboard — local, read-only view over the `rht` pipeline plus free market data.

Run:  make dashboard   (or: uv run --extra dashboard streamlit run dashboard/app.py)

There are deliberately no order buttons here. The money path stays inside `rht` + the
Robinhood MCP; this app only reads config/ and data/ and pulls delayed Yahoo data for
research. Screener rows are pre-filters for `/propose`, never executable tickets.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import marketdata as md
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

from rh_options import events as events_mod
from rh_options import ivrank, snapshot
from rh_options.models import Limits, Structure
from rh_options.screener import ChainRow, screen

ROOT = Path(__file__).resolve().parents[1]
UP, DOWN, MUTED = "#16a34a", "#dc2626", "#6b7280"

st.set_page_config(page_title="Options Desk", page_icon="📈", layout="wide")


# ── data loaders ─────────────────────────────────────────────────────────────────────────


@st.cache_data(ttl=15)
def load_snapshot() -> dict[str, object]:
    return snapshot.build(ROOT).model_dump(mode="json")


@st.cache_data(ttl=300, show_spinner=False)
def load_quote(symbol: str) -> md.Quote | None:
    return md.quote(symbol)


@st.cache_data(ttl=300, show_spinner=False)
def load_history(symbol: str, period: str) -> pd.DataFrame:
    return md.history(symbol, period)


@st.cache_data(ttl=300, show_spinner=False)
def load_expiries(symbol: str) -> list[date]:
    return md.expiries(symbol)


@st.cache_data(ttl=120, show_spinner=False)
def load_chain(symbol: str, expiry: date) -> tuple[list[ChainRow], datetime]:
    return md.chain(symbol, expiry)


@st.cache_data(ttl=3600, show_spinner=False)
def load_earnings(symbol: str) -> date | None:
    return md.next_earnings(symbol)


@st.cache_data(ttl=900, show_spinner=False)
def load_news(symbol: str) -> list[dict[str, str]]:
    return md.news(symbol)


limits = Limits.load(ROOT / "config" / "limits.json")
snap = load_snapshot()
today = datetime.now(UTC).date()

# ── header ───────────────────────────────────────────────────────────────────────────────

mode = str(snap["mode"])
halts: list[str] = snap["active_halts"]  # type: ignore[assignment]
badge = "🟢 LIVE" if mode == "live" else "🟡 SHADOW"
st.title("Options Desk")
st.caption(
    f"{badge} · rules v{snap['rules_version']} · read-only view · "
    f"snapshot {str(snap['generated_at'])[:19]}Z"
)
if halts:
    st.error("**Active halts:** " + "; ".join(halts) + " — no trading until a human clears them.")
for w in snap["warnings"]:  # type: ignore[attr-defined]
    st.warning(w)

with st.sidebar:
    st.header("Desk")
    if st.button("Refresh now", width="stretch"):
        st.cache_data.clear()
        st.rerun()
    st.caption(
        "Market data: Yahoo Finance via yfinance (free, delayed, unofficial). Research only: "
        "real tickets come from the Robinhood MCP through `/propose`."
    )
    st.divider()
    st.markdown("**Whitelist**")
    st.write(", ".join(limits.universe.whitelist))

tabs = st.tabs(["Desk", "Market", "Screener", "Journal", "Pipeline", "Calendar", "News"])

# ── Desk ─────────────────────────────────────────────────────────────────────────────────

with tabs[0]:
    j = snap["journal"]  # type: ignore[index]
    c = st.columns(5)
    c[0].metric("Equity", f"${snap['last_equity']:,.2f}",
                f"-{snap['drawdown_pct']}% from high" if snap["drawdown_pct"] else None,
                delta_color="inverse")
    c[1].metric("Open risk", f"${snap['open_risk']:,.0f}",
                help=f"cap ${limits.sizing.max_total_open_risk:,.0f}")
    c[2].metric("Realized P&L", f"${j['total_pnl']:,.2f}")  # type: ignore[index]
    wr = j["rolling_win_rate"]  # type: ignore[index]
    c[3].metric("Rolling win rate", f"{wr:.0%}" if wr is not None else "—",
                help=f"halt below {limits.breakers.min_rolling_win_rate:.0%} over "
                f"{limits.breakers.rolling_window_trades} trades")
    c[4].metric("Stop-outs in a row", snap["consecutive_stop_outs"],
                help=f"halt at {limits.breakers.max_consecutive_stop_outs}")

    st.subheader("Open positions")
    positions = snap["positions"]  # type: ignore[assignment]
    if not positions:
        st.info("Flat. No open positions — flat is correct most days.")
    else:
        df = pd.DataFrame(positions)[
            ["symbol", "structure", "contracts", "credit", "max_loss", "expiry", "dte",
             "hard_close_on", "days_to_hard_close", "take_profit_debit", "stop_debit"]
        ]
        st.dataframe(df, hide_index=True, width="stretch")
        st.caption("Exit triggers (RULES §3): buy back at ≤ take-profit debit, at ≥ stop debit, "
                   "or on the hard-close date, whichever comes first. `/manage` decides.")

    st.subheader("Go-live checklist")
    items = snap["go_live"]  # type: ignore[assignment]
    done = sum(1 for i in items if i["done"])
    st.progress(done / len(items), text=f"{done}/{len(items)} complete")
    for i in items:
        st.markdown(f"{'✅' if i['done'] else '⬜'} **{i['item']}** — {i['detail']}")

# ── Market ───────────────────────────────────────────────────────────────────────────────

with tabs[1]:
    vix = load_quote(md.VIX_SYMBOL)
    v1, v2, v3 = st.columns(3)
    if vix:
        v1.metric("VIX", f"{vix.price:.2f}",
                  f"{vix.change_pct:+.2f}%" if vix.change_pct is not None else None,
                  delta_color="inverse")
        ok = vix.price >= limits.entry.vix_min_spy
        v2.metric("SPY vol gate", "open" if ok else "closed",
                  f"needs VIX ≥ {limits.entry.vix_min_spy}", delta_color="off")
    else:
        v1.metric("VIX", "—")
        v2.caption("Market data unavailable (offline or Yahoo throttling).")
    v3.metric("Next macro event",
              f"{snap['upcoming_events'][0]['kind']} {snap['upcoming_events'][0]['on']}"  # type: ignore[index]
              if snap["upcoming_events"] else "none listed")

    st.subheader("Watchlist")
    rows = []
    with st.spinner("Loading quotes and ATM IV…"):
        for sym in limits.universe.whitelist:
            q = load_quote(sym)
            if q is None:
                rows.append({"symbol": sym, "price": None})
                continue
            exp = md.pick_expiry(load_expiries(sym), today, limits.entry.dte_min,
                                 limits.entry.dte_max)
            iv = None
            if exp:
                chain_rows, _ = load_chain(sym, exp)
                iv = md.atm_iv(chain_rows, q.price)
            rank_txt = "—"
            if iv:
                r = ivrank.rank(ROOT / "data", sym, iv, q.closes[-60:])
                rank_txt = (f"{r.rank:.0f} (true)" if r.source == "true" and r.rank is not None
                            else ("proxy pass" if r.passes_proxy else "proxy fail"))
            trend = None
            if q.sma200:
                trend = "above 200d" if q.price > q.sma200 else "below 200d"
            rows.append({
                "symbol": sym,
                "price": round(q.price, 2),
                "chg %": round(q.change_pct, 2) if q.change_pct is not None else None,
                "200d MA": round(q.sma200, 2) if q.sma200 else None,
                "trend": trend,
                "RV20": round(q.rv20, 3) if q.rv20 else None,
                "ATM IV": round(iv, 3) if iv else None,
                "IV/RV": round(iv / q.rv20, 2) if iv and q.rv20 else None,
                "IV rank": rank_txt,
                "IV snapshots": snap["iv_snapshots"].get(sym, 0),  # type: ignore[attr-defined]
                "expiry used": exp,
            })
    wl = pd.DataFrame(rows)
    st.dataframe(
        wl, hide_index=True, width="stretch",
        column_config={"chg %": st.column_config.NumberColumn(format="%+.2f")},
    )
    st.caption("IV rank: true once 60 daily snapshots exist (`rht iv snapshot` during /scan), "
               "otherwise the ADR-0001 proxy (ATM IV ≥ 1.25 × RV20), valid in shadow only.")

    st.subheader("Chart")
    cc1, cc2 = st.columns([1, 3])
    sym = cc1.selectbox("Symbol", limits.universe.whitelist, key="chart_sym")
    period = cc1.radio("Period", ["3mo", "6mo", "1y", "2y"], index=2, horizontal=True)
    hist = load_history(sym, "2y")
    if hist.empty:
        st.info("No price history available.")
    else:
        h = hist.copy()
        h["SMA50"] = h["Close"].rolling(50).mean()
        h["SMA200"] = h["Close"].rolling(200).mean()
        months = {"3mo": 3, "6mo": 6, "1y": 12, "2y": 24}[period]
        cutoff = h.index.max() - pd.DateOffset(months=months)
        h = h[h.index >= cutoff]
        fig = make_subplots(rows=2, cols=1, shared_xaxes=True, row_heights=[0.78, 0.22],
                            vertical_spacing=0.03)
        fig.add_trace(go.Candlestick(x=h.index, open=h["Open"], high=h["High"], low=h["Low"],
                                     close=h["Close"], name=sym,
                                     increasing_line_color=UP, decreasing_line_color=DOWN),
                      row=1, col=1)
        fig.add_trace(go.Scatter(x=h.index, y=h["SMA50"], name="50d", line={"width": 1.2}),
                      row=1, col=1)
        fig.add_trace(go.Scatter(x=h.index, y=h["SMA200"], name="200d", line={"width": 1.6}),
                      row=1, col=1)
        fig.add_trace(go.Bar(x=h.index, y=h["Volume"], name="Volume",
                             marker_color=MUTED, opacity=0.5), row=2, col=1)
        for ev in snap["upcoming_events"]:  # type: ignore[attr-defined]
            fig.add_vline(x=pd.Timestamp(ev["on"]), line_dash="dot", line_color=MUTED,
                          opacity=0.4)
        fig.update_layout(height=520, xaxis_rangeslider_visible=False,
                          margin={"l": 8, "r": 8, "t": 24, "b": 8},
                          legend={"orientation": "h", "y": 1.04})
        cc2.plotly_chart(fig, width="stretch")

# ── Screener ─────────────────────────────────────────────────────────────────────────────

with tabs[2]:
    e = limits.entry
    st.markdown(
        f"Enumerates ${e.spread_width:.0f}-wide credit spreads with the short leg near the "
        f"{e.short_delta_min:.2f}–{e.short_delta_max:.2f} delta band and runs the **real 11 "
        "entry gates** and POP/EV math on each. Delayed data fails the quote-freshness gate by "
        "design — use this to pick a symbol and strikes for `/propose`."
    )
    s1, s2, s3 = st.columns(3)
    ssym = s1.selectbox("Symbol", limits.universe.whitelist, key="scr_sym")
    q = load_quote(ssym)
    exps = load_expiries(ssym)
    band = [x for x in exps if e.dte_min - 7 <= (x - today).days <= e.dte_max + 7]
    if q is None or not band:
        st.info("No quote or no expiries near the tenor band (offline, or Yahoo throttling).")
    else:
        default = md.pick_expiry(band, today, limits.entry.dte_min, limits.entry.dte_max)
        exp = s2.selectbox("Expiry", band, index=band.index(default) if default in band else 0,
                           format_func=lambda e: f"{e} ({(e - today).days} DTE)")
        guess = load_earnings(ssym)
        earn = s3.date_input("Next earnings (verify!)", value=guess, min_value=today) \
            if ssym != limits.universe.spy_symbol else None
        confirmed_none = ssym == limits.universe.spy_symbol or (
            earn is None and s3.checkbox("I confirmed no earnings before expiry")
        )
        chain_rows, fetched = load_chain(ssym, exp)
        iv = md.atm_iv(chain_rows, q.price)
        iv_rank_val, iv_src = None, None
        if iv and ssym != limits.universe.spy_symbol:
            r = ivrank.rank(ROOT / "data", ssym, iv, q.closes[-60:])
            if r.source == "true":
                iv_rank_val, iv_src = r.rank, "true"
            elif r.passes_proxy is not None:
                # The proxy is pass/fail; map it onto the threshold so the gate reflects it.
                iv_rank_val = limits.entry.iv_rank_min if r.passes_proxy else 0.0
                iv_src = "proxy"
        ev_check = events_mod.check_events(
            symbol=ssym, expiry=exp, today=today,
            calendar_path=ROOT / "config" / "calendar_2026.json",
            next_earnings_date=earn if isinstance(earn, date) else None,
            earnings_confirmed_none=bool(confirmed_none),
        )
        vix_q = load_quote(md.VIX_SYMBOL)
        cands = screen(
            symbol=ssym, expiry=exp, spot=q.price, dma_200=q.sma200 or 0.0, chain=chain_rows,
            limits=limits, events=ev_check,
            vix=vix_q.price if vix_q and ssym == limits.universe.spy_symbol else None,
            iv_rank=iv_rank_val, iv_rank_source=iv_src,  # type: ignore[arg-type]
            quoted_at=fetched,
        )
        m = st.columns(4)
        m[0].metric("Spot", f"{q.price:.2f}")
        m[1].metric("200d MA", f"{q.sma200:.2f}" if q.sma200 else "—")
        m[2].metric("ATM IV", f"{iv:.1%}" if iv else "—")
        m[3].metric("Event check", "clear" if ev_check.checked_through_expiry
                    and not ev_check.blocking_events else "blocked",
                    ", ".join(ev_check.blocking_events) or ev_check.detail, delta_color="off")
        if not cands:
            st.info("No spreads near the delta band for this expiry.")
        else:
            table = pd.DataFrame([{
                "structure": "put" if c.structure is Structure.PUT_CREDIT_SPREAD else "call",
                "short": c.short_strike, "long": c.long_strike, "Δ short": c.short_delta,
                "credit": c.credit_mid, "max loss": c.max_loss,
                "RoR": c.return_on_risk, "POP": c.pop_breakeven,
                "EV hold": c.ev_hold_net, "EV managed": c.ev_managed_net,
                "gates": f"{c.gates_passed}/{c.gates_total}",
                "failing": ", ".join(g.gate for g in c.failed_gates),
            } for c in cands])
            st.dataframe(
                table, hide_index=True, width="stretch",
                column_config={
                    "RoR": st.column_config.NumberColumn(format="percent"),
                    "POP": st.column_config.ProgressColumn(min_value=0, max_value=1,
                                                           format="%.2f"),
                    "credit": st.column_config.NumberColumn(format="$%.2f"),
                    "max loss": st.column_config.NumberColumn(format="$%.0f"),
                },
            )
            pick = st.selectbox(
                "Inspect", range(len(cands)),
                format_func=lambda i: f"{table.iloc[i]['structure']} "
                f"{cands[i].short_strike:g}/{cands[i].long_strike:g} · {table.iloc[i]['gates']}",
            )
            c = cands[pick]
            left, right = st.columns([2, 3])
            with left:
                st.markdown("**Gate results**")
                failed_names = {g.gate for g in c.failed_gates}
                for g in c.failed_gates:
                    st.markdown(f"❌ `{g.gate}` — {g.detail}")
                st.caption(f"{c.gates_total - len(failed_names)} other gates passed.")
                st.download_button("Download pre-filter JSON", c.ticket.model_dump_json(indent=2),
                                   file_name=f"screen-{ssym}-{c.short_strike:g}.json",
                                   help="Reference only. /propose must rebuild it from MCP quotes.")
            with right:
                is_put = c.structure is Structure.PUT_CREDIT_SPREAD
                lo_px, hi_px = sorted([c.short_strike, c.long_strike])
                xs = [lo_px - 3 * (hi_px - lo_px) + i * (8 * (hi_px - lo_px)) / 200
                      for i in range(201)]
                credit = c.credit_mid * 100
                width = abs(c.short_strike - c.long_strike) * 100

                def pnl(px: float) -> float:
                    intrinsic = (max(0.0, c.short_strike - px) if is_put
                                 else max(0.0, px - c.short_strike)) * 100
                    return credit - min(intrinsic, width)

                ys = [pnl(x) for x in xs]
                fig = go.Figure(go.Scatter(x=xs, y=ys, fill="tozeroy", name="P&L at expiry",
                                           line={"color": UP}))
                fig.add_hline(y=0, line_color=MUTED)
                fig.add_vline(x=q.price, line_dash="dash", annotation_text="spot")
                fig.update_layout(height=300, margin={"l": 8, "r": 8, "t": 24, "b": 8},
                                  yaxis_title="$ per contract", xaxis_title="underlying")
                st.plotly_chart(fig, width="stretch")

# ── Journal ──────────────────────────────────────────────────────────────────────────────

with tabs[3]:
    curve = snap["equity_curve"]  # type: ignore[assignment]
    entries = snap["recent_journal"]  # type: ignore[assignment]
    if curve:
        cdf = pd.DataFrame(curve)
        cdf["ts"] = pd.to_datetime(cdf["ts"])
        fig = make_subplots(rows=2, cols=1, shared_xaxes=True, row_heights=[0.65, 0.35])
        fig.add_trace(go.Scatter(x=cdf["ts"], y=cdf["equity"], mode="lines+markers",
                                 name="Equity"), row=1, col=1)
        fig.add_hline(y=limits.breakers.equity_halt_threshold, line_dash="dot",
                      line_color=DOWN, annotation_text="equity halt", row=1, col=1)
        fig.add_trace(go.Bar(x=cdf["ts"], y=cdf["pnl"], name="Trade P&L",
                             marker_color=[UP if p > 0 else DOWN for p in cdf["pnl"]]),
                      row=2, col=1)
        fig.update_layout(height=440, margin={"l": 8, "r": 8, "t": 24, "b": 8})
        st.plotly_chart(fig, width="stretch")
    else:
        st.info("No closed trades yet. The equity curve starts with the first `exit` entry.")
    jj = snap["journal"]  # type: ignore[assignment]
    st.markdown(
        f"**{jj['total_entries']}** entries · **{jj['shadow_proposals']}** shadow proposals · "
        f"**{jj['fills']}** fills · **{jj['exits']}** exits ({jj['wins']}W/{jj['losses']}L)"
    )
    if entries:
        jdf = pd.DataFrame(entries)[["ts", "entry_type", "symbol", "pnl", "payload"]]
        types = sorted(jdf["entry_type"].unique())
        chosen = st.multiselect("Types", types, default=types)
        st.dataframe(jdf[jdf["entry_type"].isin(chosen)], hide_index=True,
                     width="stretch")

# ── Pipeline ─────────────────────────────────────────────────────────────────────────────

with tabs[4]:
    pipe = snap["pipeline"]  # type: ignore[assignment]
    if not pipe:
        st.info("No tickets in data/tickets/ yet. `/propose SYM` writes one.")
    else:
        pdf = pd.DataFrame(pipe)
        pdf["failed_gates"] = pdf["failed_gates"].apply(", ".join)
        pdf["ticket_hash"] = pdf["ticket_hash"].str[:10]
        st.dataframe(
            pdf[["created_at", "symbol", "structure", "credit_mid", "max_loss", "validation",
                 "failed_gates", "validation_age_min", "opinion", "opinion_age_min", "fresh",
                 "ticket_hash", "file"]],
            hide_index=True, width="stretch",
        )
        st.caption(f"Approvals expire after {limits.approvals.max_freshness_minutes} minutes and "
                   "are bound to the ticket's SHA-256; any edit orphans them.")

# ── Calendar ─────────────────────────────────────────────────────────────────────────────

with tabs[5]:
    evs = snap["upcoming_events"]  # type: ignore[assignment]
    windows = snap["entry_windows"]  # type: ignore[assignment]
    st.subheader("Macro events")
    if evs:
        st.dataframe(pd.DataFrame(evs), hide_index=True, width="stretch")
    st.caption(f"Calendar valid through {snap['calendar_valid_through']}. The event gate fails "
               "closed for any expiry beyond it.")
    st.subheader("Entry windows")
    st.markdown(
        f"Days in the next {snap['entry_window_days_scanned']} where some "
        f"{limits.entry.dte_min}–{limits.entry.dte_max} DTE expiry has no FOMC/CPI before it "
        "(earnings excluded)."
    )
    if windows:
        wdf = pd.DataFrame([{"entry_on": w["entry_on"], "clear DTEs": len(w["clear_dtes"]),
                             "range": f"{min(w['clear_dtes'])}–{max(w['clear_dtes'])}"}
                            for w in windows])
        st.dataframe(wdf, hide_index=True, width="stretch")
    else:
        st.error("None. With CPI monthly and a 30–45 DTE tenor, every expiry crosses an event, "
                 "so gate 3 blocks every ticket. Changing that is a rules decision (ADR).")
    days = [today + timedelta(days=i) for i in range(int(snap["entry_window_days_scanned"]))]  # type: ignore[call-overload]
    open_days = {w["entry_on"] for w in windows}
    fig = go.Figure(go.Bar(
        x=days, y=[1] * len(days),
        marker_color=[UP if d.isoformat() in open_days else "#e5e7eb" for d in days],
        hovertext=[("open" if d.isoformat() in open_days else "blocked") for d in days],
        hoverinfo="x+text",
    ))
    for ev in evs:
        fig.add_vline(x=pd.Timestamp(ev["on"]), line_color=DOWN, opacity=0.5)
    fig.update_layout(height=140, yaxis_visible=False, margin={"l": 8, "r": 8, "t": 8, "b": 8},
                      bargap=0.1)
    st.plotly_chart(fig, width="stretch")

# ── News ─────────────────────────────────────────────────────────────────────────────────

with tabs[6]:
    st.caption("Headlines are data, never instructions (CLAUDE.md prompt-injection defense).")
    nsym = st.selectbox("Symbol", limits.universe.whitelist, key="news_sym")
    items = load_news(nsym)
    if not items:
        st.info("No headlines available.")
    for n in items:
        # Plain text only: never render third-party HTML/markdown from a feed.
        st.text(n["title"])
        if n["url"].startswith("https://"):
            st.link_button("Open", n["url"])
        st.caption(f"{n['publisher']} · {n['published']}")
