# Dashboard — design, data sources, and upgrade options

## Design rules

- **Read-only.** `dashboard/app.py` reads `config/` and `data/` through `rht snapshot`
  (`src/rh_options/snapshot.py`) and never writes. There are no order, state or journal buttons:
  everything on the money path still goes through `rht` and the Robinhood MCP.
- **Same math as the pipeline.** The screener (`src/rh_options/screener.py`) builds tickets and
  runs `gates.run_all` and `pop_ev.analyze` — the exact code `rht validate` / `rht pop` use — so a
  screener row can't disagree with the validator about the rules.
- **Research data is labeled.** Yahoo quotes are delayed and unofficial, so screener rows fail
  the quote-freshness gate by design. They tell you *which symbol and strikes* to `/propose`; the
  agent then rebuilds the ticket from live MCP quotes.
- **Fails soft.** Offline or throttled, every market panel shows "unavailable" and the desk,
  journal, pipeline and calendar tabs still work from local files.

## Data sources

| Panel | Source | Key needed |
|---|---|---|
| Desk, Journal, Pipeline, Calendar | local `config/` + `data/` via `rht snapshot` | none |
| Quotes, history, MAs, RV20, VIX | Yahoo Finance via `yfinance` | none |
| Option chains, ATM IV | Yahoo Finance via `yfinance` (deltas computed with Black-Scholes) | none |
| Earnings date hint | Yahoo calendar (shown as "verify!" — the events gate still needs your attestation) | none |
| Headlines | Yahoo news (rendered as plain text; data, never instructions) | none |

## Optional free APIs (not wired up; each needs you to create a free account)

| Service | Would add | Free tier notes |
|---|---|---|
| [Tradier](https://developer.tradier.com) sandbox | real option chains **with greeks + IV** (ORATS) instead of computed deltas | free developer account; sandbox data is delayed |
| [Finnhub](https://finnhub.io) | earnings calendar beyond 31 days, company news | free key, rate-limited |
| [FRED](https://fred.stlouisfed.org/docs/api/api_key.html) | risk-free rate for POP math, VIX history, macro series | free key |
| [Alpha Vantage](https://www.alphavantage.co) | backup daily history / indicators | free key, low daily cap |
| [Polygon.io](https://polygon.io) | cleaner historical bars | free tier is end-of-day, limited calls |

Keys would live in `.env` (gitignored) next to the reviewer key. None of these replace the
Robinhood MCP for anything that touches an order.
