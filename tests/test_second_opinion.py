"""Reviewer client: parse APPROVE/VETO, fail closed on garbage, block without credentials.
All transport is httpx.MockTransport — the conftest guard proves nothing hits the network."""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
from conftest import NOW, make_ticket

from rh_options import gates, second_opinion
from rh_options.events import EventCheck
from rh_options.models import Limits, ValidationReport

CLEAR = EventCheck(checked_through_expiry=True, blocking_events=[], detail="clear")
ENV = {"REVIEWER_PROVIDER": "anthropic", "ANTHROPIC_API_KEY": "test-key"}


def validation(limits: Limits) -> ValidationReport:
    t = make_ticket()
    return ValidationReport(
        ticket_hash=t.canonical_hash(),
        rules_version=limits.rules_version,
        mode=limits.mode,
        created_at=NOW,
        results=gates.run_all(t, limits, CLEAR, NOW),
    )


def transport_returning(payload: dict[str, Any] | str) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        text = payload if isinstance(payload, str) else json.dumps(payload)
        return httpx.Response(200, json={"content": [{"type": "text", "text": text}]})

    return httpx.MockTransport(handler)


def call(limits: Limits, transport: httpx.BaseTransport, env: dict[str, str] | None = None) -> Any:
    return second_opinion.request_opinion(
        ticket=make_ticket(),
        validation=validation(limits),
        pop_ev={"ev_managed_net": 1.0},
        rules_text="# rules",
        transport=transport,
        env=env if env is not None else dict(ENV),
    )


def test_approve_parses(limits: Limits) -> None:
    opinion = call(limits, transport_returning({"verdict": "APPROVE", "reasons": ["gates ok"]}))
    assert opinion.verdict == "APPROVE"
    assert opinion.ticket_hash == make_ticket().canonical_hash()


def test_veto_parses(limits: Limits) -> None:
    opinion = call(limits, transport_returning({"verdict": "VETO", "reasons": ["earnings risk"]}))
    assert opinion.verdict == "VETO"
    assert opinion.reasons == ["earnings risk"]


def test_code_fenced_json_still_parses(limits: Limits) -> None:
    fenced = "```json\n" + json.dumps({"verdict": "APPROVE", "reasons": ["ok"]}) + "\n```"
    assert call(limits, transport_returning(fenced)).verdict == "APPROVE"


def test_malformed_response_fails_closed_to_veto(limits: Limits) -> None:
    opinion = call(limits, transport_returning("I think this trade looks great!"))
    assert opinion.verdict == "VETO"
    assert any("parse" in r for r in opinion.reasons)


def test_unknown_verdict_fails_closed(limits: Limits) -> None:
    opinion = call(limits, transport_returning({"verdict": "MAYBE", "reasons": []}))
    assert opinion.verdict == "VETO"


def test_http_error_raises_reviewer_error(limits: Limits) -> None:
    transport = httpx.MockTransport(lambda request: httpx.Response(429, json={}))
    with pytest.raises(second_opinion.ReviewerError, match="failed"):
        call(limits, transport)


def test_missing_key_blocks(limits: Limits) -> None:
    with pytest.raises(second_opinion.ReviewerError, match="fail closed"):
        call(limits, transport_returning({}), env={"REVIEWER_PROVIDER": "anthropic"})


def test_unknown_provider_blocks(limits: Limits) -> None:
    with pytest.raises(second_opinion.ReviewerError, match="unknown REVIEWER_PROVIDER"):
        call(limits, transport_returning({}), env={"REVIEWER_PROVIDER": "chatgpt"})


def test_glm_provider_uses_glm_url(limits: Limits) -> None:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return httpx.Response(
            200,
            json={"content": [{"type": "text", "text": json.dumps({"verdict": "APPROVE"})}]},
        )

    call(
        limits,
        httpx.MockTransport(handler),
        env={"REVIEWER_PROVIDER": "glm", "GLM_AUTH_TOKEN": "tok", "REVIEWER_MODEL": "glm-4.6"},
    )
    assert seen == [second_opinion.GLM_URL]


def test_reviewer_prompt_carries_rules_and_ticket(limits: Limits) -> None:
    bodies: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        bodies.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={"content": [{"type": "text", "text": json.dumps({"verdict": "APPROVE"})}]},
        )

    call(limits, httpx.MockTransport(handler))
    msg = bodies[0]["messages"][0]["content"]
    assert "# rules" in msg and "SOFI" in msg and "Pipeline validation report" in msg
    assert "VETO" in bodies[0]["system"]
