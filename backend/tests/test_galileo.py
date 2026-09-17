from types import SimpleNamespace

from conftest import login

from app.observability.galileo import Telemetry


def test_toggle_is_admin_only_csrf_checked_and_persistent(client, settings):
    route = "/api/demo-admin/galileo"
    payload = {"enabled": True, "expected_revision": 0}
    assert client.put(route, json=payload).status_code == 401
    customer = login(client)
    assert client.put(route, headers=customer, json=payload).status_code == 401
    admin = login(client, True)
    assert client.put(route, json=payload).status_code == 403
    response = client.put(route, headers=admin, json=payload)
    assert response.status_code == 200
    status = response.json()["galileo"]
    assert status["enabled"] and status["connection"] == "unconfigured"
    assert status["last_error"] == "Galileo API key missing"
    assert client.put(route, headers=admin, json=payload).status_code == 409
    restored = Telemetry(settings)
    assert restored.enabled
    response = client.put(route, headers=admin, json={"enabled": False, "expected_revision": 1})
    assert response.json()["galileo"]["connection"] == "disabled"
    assert not Telemetry(settings).enabled


async def test_connection_requires_successful_sdk_resolution(settings, monkeypatch):
    import galileo

    settings.galileo_enabled = True
    settings.galileo_api_key = settings.openai_api_key
    calls = []

    def connect(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(project_id="test-project", log_stream_id="test-stream")

    monkeypatch.setattr(galileo, "GalileoLogger", connect)
    monkeypatch.setattr(
        "galileo.log_streams.get_log_stream", lambda **kwargs: SimpleNamespace(id="test-stream")
    )
    telemetry = Telemetry(settings)
    status = await telemetry.check_connection()
    assert status["connection"] == "connected" and status["last_connected_at"]
    assert status["export"] == "not_attempted"
    await telemetry.check_connection()
    assert len(calls) == 1


async def test_connection_errors_do_not_expose_sdk_secrets(settings, monkeypatch):
    import galileo

    settings.galileo_enabled = True
    settings.galileo_api_key = settings.openai_api_key

    def fail(**kwargs):
        raise RuntimeError("credential-bearing SDK error fake-offline-key")

    monkeypatch.setattr(galileo, "GalileoLogger", fail)
    status = await Telemetry(settings).check_connection()
    assert status["connection"] == "failed"
    assert "fake-offline-key" not in str(status)
    assert status["last_connected_at"] is None


def test_real_sdk_callback_exports_model_and_tool_under_one_trace(settings, monkeypatch):
    from uuid import uuid4

    from conftest import FakeModel
    from fastapi.testclient import TestClient
    from galileo import GalileoLogger as RealLogger

    from app.main import create_app

    exported = []
    loggers = []

    original_init = RealLogger.__init__

    def initialize(self, **kwargs):
        original_init(
            self,
            project="offline",
            log_stream="offline",
            ingestion_hook=lambda request: exported.extend(request.traces),
        )
        self.project_id = str(uuid4())
        self.log_stream_id = str(uuid4())
        loggers.append(self)

    monkeypatch.setattr(RealLogger, "__init__", initialize)
    monkeypatch.setattr(RealLogger, "start_session", lambda self, **kwargs: "offline-session")
    monkeypatch.setattr("galileo.log_streams.get_log_stream", lambda **kwargs: object())
    settings.galileo_enabled = True
    settings.galileo_api_key = settings.openai_api_key
    with TestClient(create_app(settings, model_builder=lambda s: FakeModel())) as client:
        headers = login(client)
        response = client.post(
            "/api/chat", headers=headers, json={"message": "How much did I spend on restaurants last month?"}
        )
        assert response.status_code == 200
        event = client.app.state.chat.events[-1]
        assert client.app.state.telemetry.status["export"] == "exported"
    assert len(exported) == 1
    trace = exported[0]
    assert str(trace.id) == event["trace_id"]

    def descendants(node):
        for child in node.spans:
            yield child
            if hasattr(child, "spans"):
                yield from descendants(child)

    children = list(descendants(trace))
    assert any(child.type == "llm" for child in children)
    assert any(child.type == "tool" and child.name == "calculate_spending" for child in children)
    assert any(child.name == "output-protection-decision" for child in children)
    # Span-level evaluators and the bound output control both address this node by name.
    answer = next(c for c in children if c.type == "llm" and c.name == "customer-visible-answer")
    assert answer.output.content == event["candidate_output"]


def test_policy_retrieval_exports_a_retriever_span_with_chunks(settings, monkeypatch):
    """Retrieved chunks must reach Galileo as a retriever span; RAG evaluators score against it."""
    from uuid import uuid4

    from conftest import FakeModel
    from fastapi.testclient import TestClient
    from galileo import GalileoLogger as RealLogger

    from app.main import create_app

    exported = []
    original_init = RealLogger.__init__

    def initialize(self, **kwargs):
        original_init(
            self,
            project="offline",
            log_stream="offline",
            ingestion_hook=lambda request: exported.extend(request.traces),
        )
        self.project_id = str(uuid4())
        self.log_stream_id = str(uuid4())

    monkeypatch.setattr(RealLogger, "__init__", initialize)
    monkeypatch.setattr(RealLogger, "start_session", lambda self, **kwargs: "offline-session")
    monkeypatch.setattr("galileo.log_streams.get_log_stream", lambda **kwargs: object())
    settings.galileo_enabled = True
    settings.galileo_api_key = settings.openai_api_key
    with TestClient(create_app(settings, model_builder=lambda s: FakeModel())) as client:
        headers = login(client)
        response = client.post(
            "/api/chat",
            headers=headers,
            json={"message": "What are the fees on my Everyday account and the transfer limit?"},
        )
        assert response.status_code == 200
        event = client.app.state.chat.events[-1]

    def descendants(node):
        for child in node.spans:
            yield child
            if hasattr(child, "spans"):
                yield from descendants(child)

    children = list(descendants(exported[0]))
    retriever = next(child for child in children if child.type == "retriever")
    assert retriever.output, "retriever span carried no chunks"
    citations = {document["citation"] for document in event["evidence"]["policies"]}
    assert "everyday-fees#monthly-fee" in citations
    assert any(child.type == "llm" and child.name == "customer-visible-answer" for child in children)
