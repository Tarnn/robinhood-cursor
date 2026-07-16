# robinhood-cursor — agentic options desk (Cursor + Robinhood MCP)

A workspace where an AI agent (Cursor / Grok 4.5, or Claude Code) trades **defined-risk options
spreads** in a dedicated [Robinhood Agentic account](https://robinhood.com/us/en/agentic-trading/)
— with **zero discretion on the money path**. Every judgment call is made by deterministic,
tested Python (`rht` CLI) plus a mandatory cross-model second opinion. The agent gathers data
and follows the pipeline; the rules decide.

> **Read this first.** This is a $250 live laboratory, not an income machine. Honest per-trade
> expectancy after slippage is **−$3 to +$3**; realistic 6-month P&L is **−$25 to +$40**. The
> goal is capital-preserving, instrumented, disciplined execution — maximal learning per dollar.
> Most sessions should end with no trade (**flat is correct**). Nothing here is financial advice.

## How it works

```
agent (Cursor/Grok)          deterministic Python (rht)              human
────────────────────         ─────────────────────────────           ─────────────────
MCP: quotes/chains ──► ticket.json ──► rht validate (11 gates)
                                       rht pop (BS POP/EV math)
                                       rht opinion request ──► cross-model APPROVE/VETO
                                       rht preflight ─────────► blocks unless mode=live,
MCP: review_option_order ◄── only if preflight passes             probe recorded, no halts,
MCP: place_option_order                                           hashes fresh + matching
                                       rht journal / rht state ──► you review, flip mode
```

- Validator + reviewer outputs embed a **SHA-256 of the canonical ticket** and expire after
  15 minutes — the agent cannot reuse yesterday's approval or hand-edit a verdict.
- `config/limits.json` (gates, `mode`) and `rules/RULES.md` are **human-edited only**,
  hook-protected. `config/state.json` (halts, streaks, positions) is **CLI-mutated only**.
- The strategy and its rationale: [`rules/RULES.md`](rules/RULES.md) ·
  [`docs/strategy.md`](docs/strategy.md). The lifecycle: [`docs/workflow.md`](docs/workflow.md).

## Setup

1. **Toolkit** (Python ≥ 3.11, [uv](https://docs.astral.sh/uv/)):

   ```bash
   uv sync && uv run pytest        # everything must be green before you connect anything
   cp .env.example .env            # add your reviewer API key (never committed)
   ```

2. **Robinhood side** (desktop browser required): open the Robinhood app → Agentic Trading →
   follow onboarding to create the dedicated Agentic account, then fund it ($250).

3. **Cursor side**: open this repo in Cursor. `.cursor/mcp.json` already declares the only MCP
   server this project uses:

   ```json
   { "mcpServers": { "robinhood-trading": { "type": "http", "url": "https://agent.robinhood.com/mcp/trading" } } }
   ```

   Settings → Tools & MCPs → **Connect** next to robinhood-trading → complete the OAuth flow
   (it bounces browser ↔ Robinhood mobile app; if the final `localhost` redirect page errors,
   copy the full URL from the address bar back into Cursor — that's expected).

4. **Day 0**: run `/probe`. It simulates (never places) a 1-contract SPY put credit spread via
   `review_option_order` to answer the one open platform question — whether multi-leg orders
   are accepted — and records account facts to `data/probe/day0.json`. **If multi-leg is not
   supported, stop: the ruleset has no single-leg strategy on purpose.**

## Shadow → live

The repo ships in **shadow mode**: the full pipeline runs — scans, tickets, validation, second
opinions, journal — but `rht preflight` structurally refuses execution, so `/execute` cannot
place orders. Go live only after **all** of:

- [ ] ≥ 10 shadow proposals journaled and reviewed by you
- [ ] ≥ 2 weeks elapsed (this also seeds the IV-rank history)
- [ ] `data/probe/day0.json` recorded with `multi_leg_supported: true`
- [ ] `make validate && make test && make lint` green
- [ ] You personally edit `config/limits.json` → `"mode": "live"` and commit it

One-tap disconnect in the Robinhood app is the global kill switch, and every agent trade
triggers a push notification. The agent only trades while Cursor is open — this is a
supervised desk, not a 24/7 bot.

## Daily driving

| Command | What it does |
|---|---|
| `/scan` | halt check → VIX/quotes/trend/IV snapshots → per-symbol verdict (or "flat is correct") |
| `/propose SYM` | chain → ticket → validate → POP/EV → second opinion → present (shadow: journal it) |
| `/execute <ticket>` | preflight → review order → place limit-at-mid → GTC 50% exit |
| `/manage` | run first whenever a position is open: deterministic exit-trigger check |
| `/journal` / `/postmortem` | render stats / per-trade analysis → lesson candidates |
| `/improve` | weekly self-improvement loop (docs autonomously; rule changes need ADR + you) |

## Repo map

`rules/RULES.md` ruleset (canonical, versioned) · `config/` limits + state + macro calendar ·
`src/rh_options/` the `rht` CLI · `data/` tickets, validations, opinions, journal, IV history ·
`.claude/` + `.cursor/` agent skills/commands/rules (`.cursor` is generated — `make cursor`) ·
`knowledge/` lessons + ADRs · `docs/` workflow + strategy rationale · `tests/` no-network suite.
