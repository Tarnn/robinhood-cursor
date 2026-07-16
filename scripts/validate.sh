#!/usr/bin/env bash
# validate.sh — structural self-checks (fast, no network). `make validate` runs this;
# rules_version consistency and gate behavior are covered in depth by `make test`.
set -euo pipefail
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO"
fail=0

# 1. JSON files parse
for f in config/limits.json config/state.json config/calendar_2026.json .cursor/mcp.json \
         .cursor/hooks.json .claude/settings.json; do
  if ! python3 -m json.tool "$f" >/dev/null 2>&1; then
    echo "✗ invalid JSON: $f"; fail=1
  fi
done

# 2. rules_version in limits.json matches RULES.md frontmatter
rv_rules="$(awk '/^version:/{print $2; exit}' rules/RULES.md)"
rv_limits="$(python3 -c 'import json; print(json.load(open("config/limits.json"))["rules_version"])')"
if [ "$rv_rules" != "$rv_limits" ]; then
  echo "✗ version mismatch: RULES.md=$rv_rules limits.json=$rv_limits"; fail=1
fi

# 3. mode is a legal value (and warn loudly when live)
mode="$(python3 -c 'import json; print(json.load(open("config/limits.json"))["mode"])')"
case "$mode" in
  shadow) ;;
  live) echo "⚠ mode is LIVE — preflight will allow execution when all gates pass" ;;
  *) echo "✗ illegal mode: $mode"; fail=1 ;;
esac

# 4. skill/command frontmatter present
while IFS= read -r f; do
  if [ "$(grep -c '^---[[:space:]]*$' "$f")" -lt 2 ]; then
    echo "✗ missing frontmatter: $f"; fail=1
  fi
done < <(find .claude/skills -name SKILL.md; find .claude/commands -name '*.md')

# 5. protect-paths hook is executable and actually blocks
if [ ! -x .claude/hooks/protect-paths.sh ]; then
  echo "✗ protect-paths.sh not executable"; fail=1
elif ! echo '{"tool_name": "Edit", "tool_input": {"file_path": "rules/RULES.md"}}' \
    | ./.claude/hooks/protect-paths.sh >/dev/null 2>&1; then
  : # exit 2 expected — the hook blocks
else
  echo "✗ protect-paths.sh failed to block an edit to rules/RULES.md"; fail=1
fi

# 6. .cursor bundle is in sync with sources
if ! ./scripts/gen-cursor.sh --check; then fail=1; fi

# 7. no .env committed
if git ls-files --error-unmatch .env >/dev/null 2>&1; then
  echo "✗ .env is tracked by git — remove it immediately"; fail=1
fi

if [ "$fail" = 0 ]; then echo "✓ validate: all structural checks passed"; fi
exit "$fail"
