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
    with TestClient(create_app(settings, model_builder=lambda s, endpoint=None: FakeModel())) as client:
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
    # Logged with the question alone, this span reported every claim unsupported on every turn.
    context = " ".join(str(m.content) for m in answer.input)
    assert "75419" in context, "answer span carried no calculation evidence to be judged against"
    assert event["evidence"]["customer"]["name"] in context
    # Tool definitions stay off: Tool Selection Quality would fail a span that selects none.
    assert not answer.tools


def test_injected_answer_reads_as_an_ordinary_model_call(settings, monkeypatch):
    """The demonstration depends on the failure looking like something a model produced, so the
    injected answer is named after the chat model class like the agent's own calls. The honest
    record is the presenter evidence, which keeps both answers and names the fault method."""
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
    with TestClient(create_app(settings, model_builder=lambda s, endpoint=None: FakeModel())) as client:
        headers = login(client, True)
        run = client.post("/api/demo-admin/workspace", headers=headers).json()
        run = client.put(
            "/api/demo-admin/workspace",
            headers=headers,
            json={
                "run_id": run["id"],
                "expected_revision": run["revision"],
                "scenario": "incorrect_total",
                "protection": False,
            },
        ).json()
        response = client.post(
            "/api/demo-admin/chat",
            headers=headers,
            json={
                "run_id": run["id"],
                "expected_revision": run["revision"],
                "message": "How much did I spend on restaurants last month?",
            },
        )
        assert response.status_code == 200, response.text
        event = client.app.state.chat.events[-1]

    def descendants(node):
        for child in node.spans:
            yield child
            if hasattr(child, "spans"):
                yield from descendants(child)

    children = list(descendants(exported[0]))
    writers = [
        c
        for c in children
        if c.type == "llm"
        and c.name != "customer-visible-answer"
        and c.output.content == event["candidate_output"]
    ]
    # The agent's own answer span is masked to the delivered candidate, so it matches this too.
    # The injected call is logged after it.
    writer = writers[-1]
    # Named like the agent's own model calls: nothing in the trace flags it as injected.
    assert writer.name == "ChatOpenAI", writer.name
    assert "simulat" not in str(getattr(writer, "user_metadata", "") or "").lower()
    # It carries the same evidence as the answer span, so the fabrication is judged against
    # what the tools actually returned rather than reported unsupported.
    assert "75419" in " ".join(str(m.content) for m in writer.input)
    # Nothing else in the trace names the injection either. A workflow span used to pair the
    # genuine answer with the injected one, which gave it away more plainly than any span name.
    names = " ".join(str(c.name) for c in children).lower()
    assert "fault" not in names and "injection" not in names, names
    # The genuine answer appears nowhere in the exported trace: not in a span, and not in the
    # trace output, which is the record. A custom judge is handed the whole normalised trace, so
    # a fuller draft left anywhere in it is read as part of the answer -- which is how a
    # completeness judge came to pass a genuinely incomplete answer.
    import json

    blob = json.dumps(exported[0].model_dump(), default=str)
    assert event["raw_model_output"] not in blob
    assert event["candidate_output"] in blob
    # The honest record is the presenter evidence: both answers, and the method that produced them.
    assert event["raw_model_output"] != event["candidate_output"]
    assert event["fault_method"] == "model_rewrite"


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
    with TestClient(create_app(settings, model_builder=lambda s, endpoint=None: FakeModel())) as client:
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


def test_connection_is_settable_at_runtime_and_never_returns_the_key(client):
    """A workshop participant configures their own project from the portal.

    Without this the API key, project and log stream are env-only and need a restart, so
    connecting to Galileo would require shell access to the box."""
    headers = login(client, True)
    secret = "gal-key-not-to-be-echoed-0123456789"
    response = client.put(
        "/api/demo-admin/galileo/connection",
        headers=headers,
        json={
            "galileo_api_key": secret,
            "galileo_project": "participant-07",
            "galileo_log_stream": "their-stream",
            "agent_control_url": "https://agent-control.example.com",
        },
    )
    assert response.status_code == 200, response.text
    assert secret not in response.text, "the API key must never be echoed back"
    body = response.json()["connection"]
    # Enough of the key to tell which one is loaded, never enough to use it.
    assert body["galileo_api_key_masked"] == "\u2022" * 8 + secret[-4:]
    assert secret[:-4] not in response.text
    assert body["galileo_project"] == "participant-07"
    assert body["galileo_log_stream"] == "their-stream"
    assert body["galileo_api_key_set"] is True

    settings = client.app.state.telemetry.settings
    assert settings.galileo_project == "participant-07"
    assert settings.galileo_api_key.get_secret_value() == secret

    # Survives a restart: a new Telemetry over the same data dir reloads what was saved.
    from app.observability.galileo import Telemetry

    settings.galileo_project = "wiped"
    Telemetry(settings)
    assert settings.galileo_project == "participant-07"

    # A blank field leaves the stored value alone, so the key can stay while a stream is fixed.
    client.put(
        "/api/demo-admin/galileo/connection",
        headers=headers,
        json={"galileo_log_stream": "corrected-stream"},
    )
    assert settings.galileo_api_key.get_secret_value() == secret
    assert settings.galileo_log_stream == "corrected-stream"
    assert client.get("/api/demo-admin/status", headers=headers).json()["demo_mode"] == "presenter"


def test_connection_rejects_a_non_http_url(client):
    headers = login(client, True)
    response = client.put(
        "/api/demo-admin/galileo/connection",
        headers=headers,
        json={"agent_control_url": "file:///etc/passwd"},
    )
    assert response.status_code == 422


def test_a_fresh_instance_reports_no_galileo_connection(settings, tmp_path):
    """A workshop participant must arrive at a blank form, not the operator's credentials."""
    from pydantic import SecretStr

    from app.observability.galileo import Telemetry

    settings.data_dir = tmp_path
    settings.galileo_api_key = SecretStr("")
    settings.galileo_project = ""
    settings.galileo_log_stream = ""
    settings.galileo_console_url = ""
    settings.galileo_api_url = ""
    settings.agent_control_url = ""
    connection = Telemetry(settings).connection()
    assert connection["galileo_api_key_set"] is False
    assert connection["galileo_api_key_masked"] == ""
    assert all(connection[f] == "" for f in ("galileo_project", "galileo_log_stream", "agent_control_url"))


def test_endpoints_are_saved_switched_and_keys_masked(client):
    """Several endpoints are configured once, then switched between mid-demo.

    Sharon AI and similar are OpenAI-compatible: same provider, their own base URL, so two
    endpoints can share a provider and differ only by host and model."""
    headers = login(client, True)
    secret = "sk-participant-key-abcd9876"
    first = client.put(
        "/api/demo-admin/endpoints",
        headers=headers,
        json={
            "name": "Sharon AI · llama",
            "provider": "openai",
            "api_key": secret,
            "model": "llama-3.3-70b",
            "base_url": "https://inference.sharonai.cloud/api/v1",
        },
    )
    assert first.status_code == 200, first.text
    assert secret[:-4] not in first.text
    client.put(
        "/api/demo-admin/endpoints",
        headers=headers,
        json={"name": "Ollama · gemma4", "provider": "ollama", "model": "gemma4:e2b",
              "base_url": "http://ollama:11434"},
    )
    view = client.get("/api/demo-admin/status", headers=headers).json()["endpoints"]
    assert len(view["endpoints"]) == 2
    sharon = next(e for e in view["endpoints"] if e["provider"] == "openai")
    ollama = next(e for e in view["endpoints"] if e["provider"] == "ollama")
    assert sharon["api_key_masked"].endswith(secret[-4:])
    assert sharon["active"] and not ollama["active"]

    telemetry = client.app.state.telemetry
    settings = telemetry.settings
    assert telemetry.active_endpoint()["model"] == "llama-3.3-70b"

    # Switching points the agent at the other endpoint without losing the first one's key.
    switched = client.post(
        "/api/demo-admin/endpoints/active", headers=headers, json={"id": ollama["id"]}
    )
    assert switched.status_code == 200, switched.text
    assert telemetry.active_endpoint()["model"] == "gemma4:e2b"
    assert settings.llm_provider == "ollama"
    client.post("/api/demo-admin/endpoints/active", headers=headers, json={"id": sharon["id"]})
    assert telemetry.active_endpoint()["api_key"] == secret

    # Editing without a key keeps the stored one.
    client.put(
        "/api/demo-admin/endpoints",
        headers=headers,
        json={"id": sharon["id"], "name": "Sharon AI · llama", "provider": "openai",
              "model": "llama-3.1-8b", "base_url": "https://inference.sharonai.cloud/api/v1"},
    )
    assert telemetry.active_endpoint()["api_key"] == secret
    assert telemetry.active_endpoint()["model"] == "llama-3.1-8b"

    # A switch must start a fresh conversation, or the next model is handed the previous
    # model's answer as history and both turns land in one Galileo session.
    run = client.post("/api/demo-admin/workspace", headers=headers).json()
    before = run["revision"]
    client.post("/api/demo-admin/endpoints/active", headers=headers, json={"id": ollama["id"]})
    assert client.get("/api/demo-admin/status", headers=headers).json()["run"]["revision"] > before
    assert not client.app.state.chat.conversations
    client.post("/api/demo-admin/endpoints/active", headers=headers, json={"id": sharon["id"]})

    removed = client.delete(f"/api/demo-admin/endpoints/{sharon['id']}", headers=headers)
    assert removed.status_code == 200
    remaining = removed.json()["endpoints"]
    assert len(remaining) == 1 and remaining[0]["active"]


def test_endpoint_rejects_hosted_ollama(client):
    """Mirrors the startup rule: Ollama mode is for a local runtime."""
    headers = login(client, True)
    response = client.put(
        "/api/demo-admin/endpoints",
        headers=headers,
        json={"provider": "ollama", "model": "gpt-oss:120b-cloud", "base_url": ""},
    )
    assert response.status_code == 422


def test_a_turn_uses_the_endpoint_resolved_when_it_started(client):
    """A switch must not change the model under a request already running."""
    seen = []

    def builder(settings, endpoint=None):
        from conftest import FakeModel

        seen.append((endpoint or {}).get("model"))
        return FakeModel()

    headers = login(client, True)
    client.put(
        "/api/demo-admin/endpoints",
        headers=headers,
        json={"name": "A", "provider": "ollama", "model": "model-a", "base_url": "http://a:11434"},
    )
    client.app.state.chat.model_builder = builder
    client.post("/api/chat", headers=login(client), json={"message": "What is my savings balance?"})
    assert seen and all(m == "model-a" for m in seen), seen
    event = client.app.state.chat.events[-1]
    assert event["model"] == "model-a"
    assert event["endpoint"] == "A"



def test_the_completeness_judge_is_not_told_to_ignore_omissions():
    """The shared suffix once told this judge to pass the exact fault it exists to catch.

    "the absence of a claim is not a failure" and an exclusion list containing "an omitted part"
    are right for the other two judges and precisely wrong for this one. With them in place it
    stayed green on a genuinely incomplete answer on every model tested.
    """
    from app.observability.setup_definitions import JUDGES, judge_prompt

    whole = judge_prompt("SplunkyAnswerWholeQuestion")
    assert "the absence of a claim is not a failure" not in whole
    assert "An omission is a failure here" in whole
    assert "an omitted part" not in whole.partition("does not measure:")[2]
    # The other judges keep it: for them an absent claim really is out of scope.
    for name in ("SplunkyNumericalCorrectness", "SplunkyRightCustomer"):
        assert "the absence of a claim is not a failure" in judge_prompt(name)
    assert "an omitted part" in judge_prompt("SplunkyNumericalCorrectness")
    # Every judge keeps its own description and the single-property scoping.
    for name in JUDGES:
        assert JUDGES[name] in judge_prompt(name)
        assert "Judge only the single property described above" in judge_prompt(name)


def test_the_question_travels_in_the_payload_the_judges_read(client):
    """SplunkyAnswerWholeQuestion needs the question; the other two need only the evidence.

    The trace input carries the question, but a trace-level custom judge is not reliably given
    it: this judge scored a genuinely incomplete answer as complete on every model, reasoning
    about an "implied question" it had reconstructed from the answer. The other two judges were
    unaffected because they compare against evidence, which was always in the payload.
    """
    from conftest import login

    headers = login(client, True)
    run = client.post("/api/demo-admin/workspace", headers=headers).json()
    question = "How much did I spend on restaurants last month and what was the largest purchase?"
    client.post(
        "/api/demo-admin/chat",
        headers=headers,
        json={"run_id": run["id"], "expected_revision": run["revision"], "message": question},
    )
    assert client.app.state.chat.events[-1]["question"] == question


def test_the_completeness_judge_reads_the_question_from_the_payload():
    from app.observability.setup_definitions import judge_prompt

    whole = judge_prompt("SplunkyAnswerWholeQuestion")
    assert "`question` field of the trace output JSON" in whole
    assert "never an implied or reconstructed question" in whole
    assert "question, candidate_output and evidence" in whole


def test_the_completeness_judge_is_told_to_ignore_the_agent_spans():
    """The judge is handed the whole normalised trace, not just its output.

    Its published template is `{normalized_input_json}` over a trace object with every span, so
    the agent's own llm spans -- which carry the complete answer before the fault was injected --
    are in front of it. Without this instruction it reads one and passes the turn.
    """
    from app.observability.setup_definitions import judge_prompt

    whole = judge_prompt("SplunkyAnswerWholeQuestion")
    assert "Ignore every span" in whole
    assert "Judge only the trace-level candidate_output" in whole


def test_masking_reaches_nested_spans_and_message_history():
    """Inputs matter as much as outputs.

    The agent's own answer span is the obvious place, but the middleware spans carry the whole
    message list, so the complete answer reappears there as chat history. Leaving it anywhere in
    the trace is enough to contaminate a judge, which reads the whole normalised trace.
    """
    from app.observability.galileo import Telemetry

    genuine = "You spent $754.19. Your largest was Jacaranda Cafe at $119.68."
    candidate = "You spent $754.19."

    class Msg:
        def __init__(self, content):
            self.content = content

    class Span:
        def __init__(self, name, input=None, output=None, spans=None):
            self.name, self.input, self.output, self.spans = name, input, output, spans or []

    tree = [
        Span(
            "Agent",
            spans=[
                Span("ChatOpenAI", input=[Msg("q")], output=Msg(genuine)),
                Span("calculate_spending", input="{}", output='{"total_cents": 75419}'),
                Span("ToolCallLimitMiddleware.after_model", input=f'{{"messages": ["{genuine}"]}}'),
            ],
        ),
        Span("customer-visible-answer", input=[Msg("q")], output=Msg(genuine)),
    ]
    assert Telemetry._rewrite_spans(tree, genuine, candidate) == 3
    agent = tree[0].spans
    assert agent[0].output.content == candidate
    assert genuine not in agent[2].input and candidate in agent[2].input
    assert tree[1].output.content == candidate
    # Tool results are evidence, not the answer, and must be left alone.
    assert agent[1].output == '{"total_cents": 75419}'


def test_masking_is_a_no_op_without_a_fault():
    from app.observability.galileo import Telemetry

    telemetry = Telemetry.__new__(Telemetry)
    telemetry.status = {}
    assert telemetry.mask_genuine_answer(None, "a", "b") == 0
    assert telemetry.mask_genuine_answer({"logger": object()}, "same", "same") == 0


def test_the_completeness_judge_does_not_count_evidence_as_an_answer():
    """The evidence carries the figures the answer was meant to quote.

    It cannot be removed -- Context Adherence scores against it, and without it every claim on
    the span scored unsupported -- so the omitted part sits in context looking answered.
    """
    from app.observability.setup_definitions import judge_prompt

    whole = judge_prompt("SplunkyAnswerWholeQuestion")
    assert "not what it said" in whole
    assert "does not count as an answered part" in whole
