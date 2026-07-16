# robinhood-cursor — dev + guardrail targets. `make help` lists everything.
.PHONY: help sync lint test validate cursor journal

help: ## show targets
	@grep -E '^[a-z-]+:.*##' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  %-10s %s\n", $$1, $$2}'

sync: ## install deps (uv)
	uv sync

lint: ## ruff + mypy --strict
	uv run ruff check src tests
	uv run mypy

test: ## pytest (no network — enforced by conftest guard)
	uv run pytest

validate: ## structure checks: JSON, frontmatter, rules_version consistency, .cursor drift
	./scripts/validate.sh

cursor: ## regenerate the committed .cursor/ bundle from CLAUDE.md + skills + commands
	./scripts/gen-cursor.sh

journal: ## render data/journal.jsonl -> data/journal.md + stats
	uv run rht journal render
	uv run rht journal stats
