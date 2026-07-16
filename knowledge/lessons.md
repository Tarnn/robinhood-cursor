# Lessons

Cross-cutting gotchas captured from live operation, newest first. Routing rule: a lesson that
refines a skill → edit that SKILL.md directly; a hard-to-reverse decision → ADR; everything
cross-cutting lands here. Format:

```
## YYYY-MM-DD — title
**Context:** what happened
**Lesson:** the durable takeaway
**Why:** the mechanism behind it
(links: path)
```

## 2026-07-16 — POP is a payoff description, not an edge
**Context:** Repo scaffolded around the "only high probability of profit" mandate.
**Lesson:** Delta-implied POP is priced in; selling 70–85% POP spreads has ~zero expectancy at
fair IV. Edge, if any, comes from IV-rank timing, event avoidance, mechanical exits, and
execution quality — which is why the gates exist and why "flat is correct" is a rule, not a mood.
**Why:** Breakeven win rate of a $0.25-credit / $1-wide spread is 75%, right at the
delta-implied win rate — the market charges you fair odds for the shape of the bet.
(links: rules/RULES.md, docs/strategy.md)
