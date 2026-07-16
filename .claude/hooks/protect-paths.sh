#!/usr/bin/env bash
# protect-paths.sh — blocks agent edits to human-only / CLI-only files (exit 2 = block in
# both Claude Code and Cursor). Reads the hook payload JSON on stdin and pattern-matches the
# target path; deliberately dumb so it can't be argued with.
#
# Protected:
#   rules/RULES.md            human-only (versioned ruleset; changes need ADR + human)
#   config/limits.json        human-only (gate constants + the shadow->live flag)
#   config/state.json         CLI-only  (rht state; halts cleared only by a human)
#   src/rh_options/gates.py   human-only (the gates themselves)
#   data/journal.jsonl        CLI-only  (rht journal add; append-only)
set -euo pipefail

PAYLOAD="$(cat)"

PROTECTED='rules/RULES\.md|config/limits\.json|config/state\.json|src/rh_options/gates\.py|data/journal\.jsonl'

if echo "$PAYLOAD" | grep -Eq "$PROTECTED"; then
  # Editing tools carry the target path in the payload; shell commands carry it in the
  # command string. Either way: block writes, allow reads for shell (heuristic: common
  # write verbs / redirects near a protected path).
  if echo "$PAYLOAD" | grep -Eq '"tool_name"\s*:\s*"(Write|Edit|NotebookEdit)"'; then
    echo "BLOCKED: protected file — rules/limits/state/gates/journal are human- or CLI-only." \
         "Rule changes go through an ADR + the human; state via 'rht state'; journal via" \
         "'rht journal add'. See CLAUDE.md non-negotiable #7." >&2
    exit 2
  fi
  if echo "$PAYLOAD" | grep -Eq '(>>?|\btee\b|\bsed\b -i|\brm\b|\bmv\b|\btruncate\b|\bcp\b )[^"]*('"$PROTECTED"')'; then
    echo "BLOCKED: shell write to a protected file (rules/limits/state/gates/journal)." \
         "Use 'rht state' / 'rht journal add'; rule changes need an ADR + the human." >&2
    exit 2
  fi
fi

exit 0
