---
description: Weekly self-improvement loop — journal-driven; docs/skills autonomously, rule changes only as ADR proposals for the human
---

The improvement loop. Evidence in, small diffs out. Run weekly (or when the human asks).

1. Gather evidence: `uv run rht journal stats`, re-read postmortems since the last /improve
   (journal `note` entries), `knowledge/lessons.md`, and the current `rules/RULES.md` version.
2. Look for, in priority order:
   - Execution quality: realized slippage vs estimates; are limit-at-mid fills happening?
     Which symbols fill badly? (This is the #1 edge-breaker.)
   - Gate performance: which gates block most candidates? Any gate that never fires? Any
     loss that a stricter gate would have prevented — or a gate whose margin was thin on
     every loser?
   - Process failures: skipped steps, journal gaps, injection attempts, MCP quirks not yet
     in mcp-recipes.
   - IV-history progress: snapshots per symbol toward the 60 needed for true ranks.
3. Apply autonomously (show the human every diff in this session):
   - Docs, README, skill wording/mechanics that do NOT alter any gate, sizing, or exit.
   - New dated entries in `knowledge/lessons.md`.
   - Journal analytics improvements (render/stats), covered by new tests, `make test` green.
4. Rule changes (gates, constants, sizing, exits, universe, mode) — PROPOSAL ONLY:
   - Draft an ADR from `knowledge/adr/TEMPLATE.md` citing journal evidence — minimum 10
     relevant trades, or state the small-sample caveat explicitly.
   - Include the exact `rules/RULES.md` + `config/limits.json` diff with a version bump,
     plus the matching test updates.
   - Hand it to the human. You do not apply it; the hook blocks you anyway, and
     `test_rules_consistency.py` breaks on any unsynchronized edit.
5. Close the loop: `uv run rht journal add --type note --payload '{"improve_run": {...}}'`
   summarizing what changed and what was proposed.

Bias check before finishing: are you proposing to loosen a gate because the account is
bored? Re-read RULES.md §7. Boredom is not evidence; flat is correct.
