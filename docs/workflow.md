# Workflow — lifecycle, file flow, and the human's levers

## The pipeline (one trade, start to finish)

```
/scan ──► candidate ──► /propose SYM
                          │  data/tickets/<ts>-SYM.json          (agent writes, from MCP data)
                          │  rht validate ─► data/validations/<hash>.json   11 gates
                          │  rht pop      ─► POP + EV after costs
                          │  rht opinion  ─► data/opinions/<hash>.json      cross-model APPROVE/VETO
                          ▼
              shadow mode: rht journal add --type shadow_proposal  ✅ done (nothing placed)
              live mode:   human says go ──► /execute
                          │  rht preflight        mode+probe+halts+sizing+hash+freshness
                          │  review_option_order  simulation must match ticket
                          │  place_option_order   limit at mid, walk per RULES §4
                          ▼
                     on fill: GTC 50%-profit exit placed immediately
                              rht journal add --type fill · rht state open
                          ▼
        every session: /manage ──► exit triggers (50% / 2x stop / 14 DTE / strike touch)
                          ▼
                     rht journal add --type exit · rht state close --pnl
                          ▼
                /postmortem ──► weekly /improve ──► lessons / ADR proposals
```

The SHA-256 ticket hash binds ticket → validation → opinion → preflight. Any edit to the
ticket after validation orphans its approvals (by design — build a new ticket).

## File ownership

| Path | Written by | Notes |
|---|---|---|
| `rules/RULES.md`, `config/limits.json` | **human only** | hook-blocked for the agent; version-locked together by tests |
| `config/state.json` | `rht state` only | halts auto-set; **only a human clears them** (edit the file, commit) |
| `data/journal.jsonl` | `rht journal add` only | append-only |
| `data/tickets|validations|opinions/`, `data/iv_history/`, `data/probe/` | agent via `rht` | committed for audit |
| `.cursor/`, `AGENTS.md`, `data/journal.md` | generated | `make cursor` / `make journal` |

## Human levers

- **Go live**: complete the README checklist, then edit `config/limits.json` →
  `"mode": "live"`, commit. (Going back to shadow is the same edit in reverse, any time.)
- **Clear a halt**: investigate first — the halt fired because a breaker tripped. Then remove
  the entry from `config/state.json` `halts[]` and commit with a message saying why.
- **Change a rule**: only via the ADR the agent drafts in /improve (or your own): apply the
  RULES.md + limits.json diff together, bump the version in both, run `make test`.
- **Kill switch**: disconnect the agent in the Robinhood app (Settings → Agentic). Works
  regardless of anything in this repo.

## Session etiquette (for the human)

Open Cursor → if a position is open, the agent must run /manage before anything else →
/scan when you want to look → expect "flat is correct" most days. Every agent trade pushes a
notification from Robinhood; if you see one you didn't expect, disconnect first, investigate
second.
