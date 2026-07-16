---
description: Structured postmortem for a closed trade — thesis vs outcome, slippage, closest gate, lesson routing
argument-hint: <ticket-hash or journal id>
---

Postmortem for trade $ARGUMENTS. Structure from the journal-discipline skill:

1. Pull every journal entry for this ticket_hash (proposal/fill/exit) from `data/journal.jsonl`
   plus its validation report and opinion from `data/validations/` and `data/opinions/`.
2. Write the postmortem:
   - Thesis at entry vs what actually happened (price path, IV path).
   - Slippage: estimated (ticket spreads) vs realized (fill payloads), entry and exit.
   - Closest gate: which entry gate had the least margin — marginal setups are where the
     losses concentrate; say whether this trade was marginal.
   - Exit analysis: which trigger fired; would the other triggers have done better? (evidence
     for /improve, not a rule change here.)
   - Reviewer check: did the second opinion flag anything that played out?
3. Route the lesson (journal-discipline): skill fix → edit the SKILL.md; cross-cutting →
   `knowledge/lessons.md`; rule-touching → note it as an /improve agenda item (ADR path).
4. Append the postmortem summary:
   `uv run rht journal add --type note --ticket-hash <hash> --payload '{"postmortem": ...}'`
