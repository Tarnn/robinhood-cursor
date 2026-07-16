"""RULES.md and config/limits.json must move together: same version, same constants.
An unsigned rule change (either file edited alone) fails this suite and therefore CI."""

from __future__ import annotations

import re

from conftest import REPO_ROOT

from rh_options.models import Limits

RULES = (REPO_ROOT / "rules" / "RULES.md").read_text()
LIMITS = Limits.load(REPO_ROOT / "config" / "limits.json")


def rules_frontmatter_version() -> str:
    match = re.search(r"^version:\s*(\S+)$", RULES, flags=re.MULTILINE)
    assert match, "rules/RULES.md must carry a version: frontmatter field"
    return match.group(1)


def test_versions_match() -> None:
    assert rules_frontmatter_version() == LIMITS.rules_version


def test_ships_in_shadow_mode() -> None:
    # flipping to live is a deliberate human commit; the repo must never ship live by default
    assert LIMITS.mode == "shadow"


def test_every_constant_is_cited_in_rules() -> None:
    """Each load-bearing limit value must appear in RULES.md — changing a number in
    limits.json without updating the canonical document breaks the pact."""
    citations = [
        (f"{LIMITS.entry.iv_rank_min:.0f}", "IV rank floor"),
        (f"{LIMITS.entry.vix_min_spy:.0f}", "SPY VIX floor"),
        (f"{LIMITS.entry.short_delta_min:.2f}", "short delta min"),
        (f"{LIMITS.entry.short_delta_max:.2f}", "short delta max"),
        (f"{LIMITS.entry.dte_min}", "DTE min"),
        (f"{LIMITS.entry.dte_max}", "DTE max"),
        (f"${LIMITS.entry.min_credit:.2f}", "credit floor"),
        (f"${LIMITS.entry.min_credit_spy:.2f}", "SPY credit floor"),
        (f"{LIMITS.entry.min_open_interest}", "OI floor"),
        (f"${LIMITS.entry.max_leg_spread_abs:.2f}", "leg spread abs cap"),
        (f"{LIMITS.entry.max_leg_spread_pct_of_mid:.0%}", "leg spread pct cap"),
        (f"{LIMITS.entry.quote_max_age_minutes} minutes", "quote freshness"),
        (f"${LIMITS.sizing.max_loss_per_position:.0f}", "per-position max loss"),
        (f"${LIMITS.sizing.max_total_open_risk:.0f}", "total open risk cap"),
        (f"${LIMITS.sizing.min_cash_reserve:.0f}", "cash reserve"),
        (f"{LIMITS.exits.profit_target_pct_of_credit:.0%}", "profit target"),
        (f"{LIMITS.exits.stop_multiple_of_credit:.0f}× credit", "stop multiple"),
        (f"{LIMITS.exits.hard_close_dte} DTE", "hard close"),
        (f"${LIMITS.breakers.equity_halt_threshold:.0f}", "equity halt threshold"),
        (f"{LIMITS.breakers.equity_halt_days} days", "equity halt duration"),
        (f"{LIMITS.breakers.rolling_window_trades}-trade", "rolling window"),
        (f"{LIMITS.breakers.min_rolling_win_rate:.0%}", "win rate floor"),
        (f"{LIMITS.approvals.max_freshness_minutes} min", "approval freshness"),
    ]
    missing = [note for text, note in citations if text not in RULES]
    assert not missing, f"limits values not cited in RULES.md: {missing}"


def test_whitelist_cited_in_rules() -> None:
    for symbol in LIMITS.universe.whitelist:
        assert symbol in RULES, f"{symbol} in limits whitelist but not in RULES.md"
