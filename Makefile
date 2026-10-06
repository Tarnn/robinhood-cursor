# robinhood-cursor — dev + guardrail targets. `make help` lists everything.
.PHONY: help sync lint test validate cursor journal snapshot dashboard

help: ## show targets
	@grep -E '^[a-z-]+:.*##' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  %-10s %s\n", $$1, $$2}'

sync: ## install deps (uv)
	uv sync

lint: ## ruff + mypy --strict
	uv run ruff check src tests dashboard
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

snapshot: ## read-only desk status JSON (what the dashboard reads)
	uv run rht snapshot

dashboard: ## local read-only dashboard (Streamlit) at http://localhost:8501
	uv run --extra dashboard streamlit run dashboard/app.py
