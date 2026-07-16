"""Mandatory cross-model trade review — a real API call to a different model, not a persona.

The reviewer receives the canonical ticket, the validation report, the POP/EV math, and the
full ruleset, and must independently re-derive each gate. Anything other than a clean APPROVE
parse is a VETO (fail closed). Missing credentials block the trade entirely (exit 2 in the CLI).
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from typing import Any, Literal

import httpx

from .models import Opinion, TradeTicket, ValidationReport

ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
GLM_URL = "https://api.z.ai/api/anthropic/v1/messages"
DEFAULT_MODEL = "claude-sonnet-5"

SYSTEM = """You are the risk-manager of last resort for a $250 defined-risk options account.
You are reviewing a trade ticket produced by another AI agent. Your ONLY job is to find
reasons to VETO. Independently re-derive every entry gate from the ruleset against the ticket
data; check the arithmetic (credit, width, max loss, POP); look for anything the pipeline
might have missed (event risk, correlation, stale data, regime). Doubt = VETO. The account
survives by NOT trading marginal setups; a wrongly-vetoed good trade costs ~$12, a wrongly
approved bad one costs ~$75.

Respond with ONLY a JSON object, no prose, no code fences:
{"verdict": "APPROVE" | "VETO", "reasons": ["..."],
 "gate_rederivation": {"<gate>": "ok|fail: note"}}"""


class ReviewerError(RuntimeError):
    """Configuration/transport failure — the CLI maps this to exit 2 (trade blocked)."""


def request_opinion(
    *,
    ticket: TradeTicket,
    validation: ValidationReport,
    pop_ev: dict[str, Any],
    rules_text: str,
    transport: httpx.BaseTransport | None = None,
    env: dict[str, str] | None = None,
) -> Opinion:
    env = env if env is not None else dict(os.environ)
    provider = env.get("REVIEWER_PROVIDER", "anthropic").strip().lower()
    model = env.get("REVIEWER_MODEL", DEFAULT_MODEL).strip()

    if provider == "anthropic":
        url, key = ANTHROPIC_URL, env.get("ANTHROPIC_API_KEY", "").strip()
    elif provider == "glm":
        url, key = GLM_URL, env.get("GLM_AUTH_TOKEN", "").strip()
    else:
        raise ReviewerError(f"unknown REVIEWER_PROVIDER {provider!r} (anthropic|glm)")
    if not key:
        raise ReviewerError(
            f"no API key for reviewer provider {provider!r} — set it in .env; "
            "no reviewer means no trade (fail closed)"
        )

    user_msg = (
        "## Ruleset (canonical)\n" + rules_text
        + "\n\n## Trade ticket (canonical JSON)\n"
        + json.dumps(ticket.model_dump(mode="json"), indent=2, sort_keys=True)
        + "\n\n## Pipeline validation report\n"
        + validation.model_dump_json(indent=2)
        + "\n\n## POP / EV analysis\n"
        + json.dumps(pop_ev, indent=2, sort_keys=True)
        + "\n\nReview and respond with the JSON verdict only."
    )
    body = {
        "model": model,
        "max_tokens": 1024,
        "system": SYSTEM,
        "messages": [{"role": "user", "content": user_msg}],
    }
    headers = {"x-api-key": key, "anthropic-version": "2023-06-01"}

    try:
        with httpx.Client(transport=transport, timeout=60.0) as client:
            resp = client.post(url, json=body, headers=headers)
            resp.raise_for_status()
            data = resp.json()
    except httpx.HTTPError as exc:
        raise ReviewerError(f"reviewer call failed: {exc}") from exc

    verdict, reasons = _parse(data)
    return Opinion(
        ticket_hash=ticket.canonical_hash(),
        verdict=verdict,
        reasons=reasons,
        model=model,
        provider=provider,
        created_at=datetime.now(UTC),
    )


def _parse(data: dict[str, Any]) -> tuple[Literal["APPROVE", "VETO"], list[str]]:
    """Strict parse; anything unexpected is a VETO with the parse problem as the reason."""
    try:
        text = "".join(
            block["text"] for block in data["content"] if block.get("type") == "text"
        ).strip()
        if text.startswith("```"):
            text = text.strip("`").removeprefix("json").strip()
        parsed = json.loads(text)
        verdict = parsed["verdict"]
        reasons = [str(r) for r in parsed.get("reasons", [])]
        if verdict == "APPROVE":
            return "APPROVE", reasons or ["reviewer approved"]
        if verdict == "VETO":
            return "VETO", reasons or ["reviewer vetoed without reasons"]
        return "VETO", [f"reviewer returned unknown verdict {verdict!r} — fail closed"]
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        return "VETO", [f"could not parse reviewer response ({exc}) — fail closed"]
