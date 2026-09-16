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
