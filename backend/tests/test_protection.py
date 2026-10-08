import asyncio
from types import SimpleNamespace

import httpx
import pytest

from app.observability.protection import FALLBACK, Protection


@pytest.mark.parametrize("safe,expected", [(True, "answer"), (False, FALLBACK)])
async def test_verified_gate_decisions(settings, monkeypatch, safe, expected):
    import agent_control

    completed = []

    class Client:
        def __init__(self, **kwargs):
            assert kwargs["runtime_auth_mode"] == "jwt"

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def post_runtime_evaluation(self, **kwargs):
            assert kwargs["json"]["stage"] == "post"
            assert kwargs["json"]["step"]["output"] == "answer"
            await asyncio.sleep(0.01)
            completed.append(True)
            return httpx.Response(
                200,
                request=httpx.Request("POST", "https://example.test"),
                json={
                    "is_safe": safe,
                    "confidence": 1.0,
                    "reason": "test decision",
                    "matches" if not safe else "non_matches": [
                        {
                            "control_id": 123,
                            "control_name": "offline-test-control",
                            "action": "deny",
                            "result": {"matched": not safe, "confidence": 1.0},
                        }
                    ],
                    "errors": [],
                },
            )

    monkeypatch.setattr(agent_control, "AgentControlClient", Client)
    s = settings.model_copy(
        update={
            "galileo_enabled": True,
            "agent_control_url": "https://example.test",
            "galileo_api_key": settings.openai_api_key,
        }
    )
    answer, decision = await Protection(s).check(
        "answer", "question", {}, SimpleNamespace(log_stream_id="test-stream"), True
    )
    assert completed and answer == expected
    assert decision["verified"] and decision["decision"] == ("allow" if safe else "deny")


async def test_unconfigured_gate_fails_closed(settings):
    answer, decision = await Protection(settings).check("unsafe", "question", {}, None, True)
    assert answer == FALLBACK and not decision["verified"]
    answer, decision = await Protection(settings).check("candidate", "question", {}, None, False)
    assert answer == "candidate" and decision["decision"] == "disabled"


@pytest.mark.asyncio
async def test_action_gate_logs_a_control_span_from_dict_arguments():
    """The span that proves a control ran must survive the action gate's arguments.

    `add_control_span` takes a string and is decorated to swallow every exception it raises,
    returning None. The action gate passes the tool call's arguments, which are a dict, so the
    span was dropped silently on exactly the path that needs it: no span, no error, and not even
    the control_telemetry marker, because nothing ever reached our own handler.
    """
    from uuid import uuid4

    from galileo import GalileoLogger

    from app.observability.protection import Protection

    captured = []
    original = GalileoLogger.__init__

    def initialize(self, **kwargs):
        original(self, project="offline", log_stream="offline",
                 ingestion_hook=lambda request: captured.extend(request.traces))
        self.project_id, self.log_stream_id = str(uuid4()), str(uuid4())

    GalileoLogger.__init__ = initialize
    try:
        logger = GalileoLogger()
        logger.start_trace(input="q", name="t")

        class Verdict:
            def model_dump(self, mode="json"):
                return {"matched": True}

        class Control:
            control_id, control_name, action, result = 887, "splunky-transfer-deny", "deny", Verdict()

        class Result:
            matches, non_matches, errors = [Control()], [], []
            is_safe, confidence, reason = False, 1.0, "matched"

        protection = Protection.__new__(Protection)
        protection.settings = type("S", (), {"agent_control_agent_name": "my-bank-agent"})()
        details = {}
        result = Result()
        # A dict, exactly as awrap_tool_call hands it over.
        protection._log_controls(
            logger, result.matches, result,
            {"to_account": "1234", "amount_cents": 10000}, "tool_call", "pre", details,
        )
        logger.conclude(output="done", conclude_all=True)
        logger.flush()
    finally:
        GalileoLogger.__init__ = original

    def every(spans):
        for span in spans or []:
            yield span
            yield from every(getattr(span, "spans", None))

    controls = [s for s in every(captured[-1].spans) if "control" in str(getattr(s, "type", "")).lower()]
    assert [s.name for s in controls] == ["splunky-transfer-deny"]
    assert details.get("control_telemetry") != "span_rejected"


def test_a_failed_request_records_the_http_status():
    """A rejected credential, a wrong gateway and a missing route are all HTTPStatusError."""
    from app.observability.protection import Protection

    class Response:
        status_code = 401

    class Failure(Exception):
        response = Response()

    # An instance rather than the class, because the 404 hint names the configured agent.
    protection = Protection.__new__(Protection)
    protection.settings = type("S", (), {"agent_control_agent_name": "my-bank-agent-lp"})()

    diagnosis = protection._failure(Failure())
    assert diagnosis["cause"] == "request_failed"
    assert diagnosis["http_status"] == 401
    assert "credentials rejected" in diagnosis["hint"]

    # A 404 here is far more often a missing agent than a missing route, and that failure disguises
    # itself as a working guardrail: the app fails closed, the transfer is blocked, and only
    # action_decisions shows the deny was never real. The hint has to name the agent.
    Response.status_code = 404
    diagnosis = protection._failure(Failure())
    assert diagnosis["http_status"] == 404
    assert "my-bank-agent-lp" in diagnosis["hint"]
    assert "cannot be created from the app" in diagnosis["hint"]

    # No response at all still names the exception, as before.
    assert protection._failure(RuntimeError("x")) == {"cause": "request_failed", "error": "RuntimeError"}
