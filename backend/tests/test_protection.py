import asyncio
from types import SimpleNamespace

import httpx
import pytest
from pydantic import SecretStr

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
        protection.settings = type("S", (), {"resolved_agent_name": "my-bank-agent"})()
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
    protection.settings = type("S", (), {"resolved_agent_name": "my-bank-agent-lp"})()

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


async def test_the_last_failure_is_kept_so_a_401_is_visible_without_a_turn(settings, monkeypatch):
    """A guardrail failing closed looks identical to one working, from the chat.

    Before this, the only record of why was inside a turn's action_decisions, so establishing
    whether a refusal was real meant driving a turn and reading it back. The reason is now kept on
    the adapter and reported by the status endpoint.
    """
    import agent_control
    import httpx

    from app.observability.protection import Protection

    class Client:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def post_runtime_evaluation(self, **kwargs):
            request = httpx.Request("POST", "https://gateway.test/evaluation")
            raise httpx.HTTPStatusError(
                "unauthorized", request=request, response=httpx.Response(401, request=request)
            )

    monkeypatch.setattr(agent_control, "AgentControlClient", Client)
    # The gate only runs when it is configured; otherwise it short-circuits before any request.
    settings.galileo_enabled = True
    settings.galileo_api_key = SecretStr("test-key")
    settings.agent_control_url = "https://gateway.test/agent-control"
    protection = Protection(settings)
    assert protection.detail == {}

    _, decision = await protection.check(
        "answer", "question", {}, SimpleNamespace(log_stream_id="test-stream"), True
    )
    assert decision["decision"] == "unavailable"
    assert protection.status == "failed"
    assert protection.detail["http_status"] == 401
    assert "credentials rejected" in protection.detail["hint"]
    # Which call was refused is the difference between a missing permission and an unenabled
    # feature, and the path says which without carrying anything secret.
    assert protection.detail["path"] == "/evaluation"


def test_the_runtime_auth_mode_is_configurable(settings):
    """A tenant without the token exchange rejects jwt with 401 while accepting the same key for
    the management API, so trying the alternative must not need a code change."""
    assert settings.agent_control_runtime_auth_mode == "jwt"
    settings.agent_control_runtime_auth_mode = "api_key"
    assert settings.agent_control_runtime_auth_mode == "api_key"


async def test_a_tool_scoped_control_does_not_make_a_working_guardrail_read_as_failed(settings):
    """The two gates answer different questions, and conflating them was actively misleading.

    The pre gate decides whether a tool runs. The post gate inspects the answer. A control scoped
    to `transfer_funds` is invisible to the post gate, which correctly reports that nothing applied
    -- and because only the last call was kept, a box whose guardrail had just blocked a transfer
    reported `failed`. It also drove the Demo tab to show protection as not ready.
    """
    from app.observability.protection import ControlNotEvaluated, Protection

    protection = Protection(settings)
    assert protection.status == "unverified"

    protection._record("pre", "verified")
    assert protection.status == "verified"

    protection._record("post", "no_control", ControlNotEvaluated({"cause": "no_control_selected"}).diagnosis)
    assert protection.status == "verified", "the post gate finding nothing must not mask a real deny"
    assert protection.stages["pre"]["status"] == "verified"
    assert protection.stages["post"]["status"] == "no_control"


async def test_a_real_failure_still_wins_over_no_control(settings):
    """A 401 is a fault and must not be hidden by another stage reporting no control."""
    from app.observability.protection import Protection

    protection = Protection(settings)
    protection._record("post", "no_control", {"cause": "no_control_selected"})
    assert protection.status == "no_control"

    protection._record("pre", "failed", {"http_status": 401, "hint": "credentials rejected"})
    assert protection.status == "failed"
    assert protection.detail["http_status"] == 401


async def test_no_control_is_not_reported_as_a_failure(settings, monkeypatch):
    """Reaching the gateway and learning nothing applies is an outcome, not a fault."""
    import agent_control

    from app.observability.protection import Protection

    class Client:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def post_runtime_evaluation(self, **kwargs):
            return httpx.Response(
                200,
                request=httpx.Request("POST", "https://gateway.test/evaluation"),
                json={"is_safe": True, "confidence": 1.0, "reason": "nothing applied",
                      "matches": [], "non_matches": []},
            )

    monkeypatch.setattr(agent_control, "AgentControlClient", Client)
    settings.galileo_enabled = True
    settings.galileo_api_key = SecretStr("test-key")
    settings.agent_control_url = "https://gateway.test/agent-control"
    protection = Protection(settings)
    await protection.check("answer", "question", {}, SimpleNamespace(log_stream_id="s"), True)
    assert protection.status in {"no_control", "verified"}, protection.status
    assert protection.status != "failed", "no control applying is not a failure"


async def test_a_client_error_carries_the_gateway_message(settings, monkeypatch):
    """A 401 on its own is a number. The gateway's own words are what name the cause."""
    import agent_control

    from app.observability.protection import Protection

    class Client:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def post_runtime_evaluation(self, **kwargs):
            request = httpx.Request("POST", "https://gateway.test/api/v1/evaluation")
            raise httpx.HTTPStatusError(
                "unauthorized",
                request=request,
                response=httpx.Response(401, request=request,
                                        json={"detail": "agent not authorized for this log stream"}),
            )

    monkeypatch.setattr(agent_control, "AgentControlClient", Client)
    settings.galileo_enabled = True
    settings.galileo_api_key = SecretStr("test-key")
    settings.agent_control_url = "https://gateway.test/agent-control"
    protection = Protection(settings)
    await protection.check("answer", "question", {}, SimpleNamespace(log_stream_id="s"), True)
    assert "agent not authorized" in protection.detail["response"]


async def test_a_server_error_body_is_not_captured(settings, monkeypatch):
    """Only client errors explain themselves; a 5xx body is noise and may be large."""
    import agent_control

    from app.observability.protection import Protection

    class Client:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def post_runtime_evaluation(self, **kwargs):
            request = httpx.Request("POST", "https://gateway.test/api/v1/evaluation")
            raise httpx.HTTPStatusError(
                "boom", request=request,
                response=httpx.Response(503, request=request, text="x" * 5000))

    monkeypatch.setattr(agent_control, "AgentControlClient", Client)
    settings.galileo_enabled = True
    settings.galileo_api_key = SecretStr("test-key")
    settings.agent_control_url = "https://gateway.test/agent-control"
    protection = Protection(settings)
    await protection.check("answer", "question", {}, SimpleNamespace(log_stream_id="s"), True)
    assert protection.detail["http_status"] == 503
    assert "response" not in protection.detail


async def test_an_answer_no_control_covers_is_delivered(settings):
    """Armed protection must not replace every legitimate answer.

    Controls are scoped to tools, so nothing is scoped to the answer step. Treating "nothing
    applies" as fail-closed meant that with the guardrail on, a customer asking for their own
    savings balance got "I couldn't verify that answer against the bank's policies" -- the opposite
    of what a guardrail is for. Observed on a live deployment, with both own-account questions in
    the lab's own Step 8 failing.
    """
    from app.observability.protection import ControlNotEvaluated, Protection

    protection = Protection(settings)
    settings.galileo_enabled = True
    settings.galileo_api_key = SecretStr("test-key")
    settings.agent_control_url = "https://gateway.test/agent-control"

    async def nothing_applies(*args, **kwargs):
        raise ControlNotEvaluated(
            {"cause": "no_control_selected", "matches": 0, "non_matches": 0, "errors": []}
        )

    protection._evaluate = nothing_applies
    answer, decision = await protection.check(
        "Your Savings balance is $4,210.00", "balance?", {},
        SimpleNamespace(log_stream_id="s"), True,
    )
    assert answer == "Your Savings balance is $4,210.00", "the real answer must be delivered"
    assert decision["decision"] == "not_covered"
    assert decision["action"] == "deliver"
    # Never verified: Agent Control enforced nothing, and "no policy" must not read as "satisfied".
    assert decision["verified"] is False
    assert protection.stages["post"]["status"] == "no_control"


async def test_a_control_that_errored_still_fails_closed(settings):
    """Asked and unable to answer is different from never asked."""
    from app.observability.protection import ControlNotEvaluated, Protection

    protection = Protection(settings)
    settings.galileo_enabled = True
    settings.galileo_api_key = SecretStr("test-key")
    settings.agent_control_url = "https://gateway.test/agent-control"

    async def errored(*args, **kwargs):
        raise ControlNotEvaluated(
            {"cause": "control_errored", "matches": 0, "non_matches": 0, "errors": ["boom"]}
        )

    protection._evaluate = errored
    answer, decision = await protection.check(
        "Your Savings balance is $4,210.00", "balance?", {},
        SimpleNamespace(log_stream_id="s"), True,
    )
    assert answer != "Your Savings balance is $4,210.00", "a control that errored must fail closed"
    assert decision["decision"] == "unavailable"
    assert protection.stages["post"]["status"] == "failed"
