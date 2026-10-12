import time

from conftest import login


def test_auth_scope_csrf_and_logout(client):
    assert client.get("/api/accounts").status_code == 401
    assert client.post("/api/auth/login", json={"password": "irrelevant"}).status_code == 403
    headers = login(client)
    assert len(client.get("/api/accounts").json()["items"]) == 3
    assert client.get("/api/accounts/not-owned").status_code == 404
    assert client.get("/api/demo-admin/status").status_code == 401
    assert client.post("/api/chat", json={"message": "Hello"}).status_code == 403
    assert client.get("/api/accounts/everyday/transactions?page_size=101").status_code == 422
    assert (
        client.get("/api/accounts/everyday/transactions?start=2026-09-01&end=2026-08-01").status_code == 422
    )
    assert client.post("/api/auth/logout", headers=headers).status_code == 200
    assert client.get("/api/accounts").status_code == 401


def test_repeated_failed_logins_do_not_lock_out_valid_login(client):
    for _ in range(7):
        assert (
            client.post(
                "/api/auth/login",
                headers={"Origin": "http://localhost:3000"},
                json={"password": "wrong", "account_number": "12345678"},
            ).status_code
            == 401
        )
    login(client)


def test_session_expiry(client):
    login(client, True)
    for session in client.app.state.auth.sessions.values():
        session.expires = time.time() - 1
    assert client.get("/api/demo-admin/status").status_code == 401


def test_offline_agent_tools_conversation_isolation(client):
    headers = login(client)
    response = client.post(
        "/api/chat", headers=headers, json={"message": "How much did I spend on restaurants last month?"}
    )
    assert response.status_code == 200, response.text
    event = client.app.state.chat.events[-1]
    assert event["evidence"]["calculations"]
    assert event["trace_id"] is None and event["evaluation"]["scores"] is None
    old_id = response.json()["conversation_id"]
    client.post("/api/auth/logout", headers=headers)
    headers = login(client)
    assert (
        client.post(
            "/api/chat", headers=headers, json={"message": "Hi", "conversation_id": old_id}
        ).status_code
        == 404
    )


def test_transfer_gate_fails_closed_and_leaves_data_untouched(client):
    """Protection on with Agent Control unconfigured must block the action, not permit it.

    An unverified gate that lets money through would be worse than no gate."""
    customer = login(client)
    admin = login(client, True)
    run = client.post("/api/demo-admin/run", headers=admin).json()
    assert (
        client.post("/api/demo-admin/bind", headers=customer, json={"token": run["binding"]}).status_code
        == 200
    )
    before = client.app.state.storage.path.read_bytes()
    run = client.put(
        "/api/demo-admin/scenario",
        headers=admin,
        json={"run_id": run["id"], "expected_revision": 0, "scenario_id": "money_transfer"},
    ).json()
    run = client.put(
        "/api/demo-admin/protection",
        headers=admin,
        json={"run_id": run["id"], "expected_revision": run["revision"], "enabled": True},
    ).json()
    prompt = "Send $4,500 to Dan Whitfield at another bank."
    response = client.post("/api/chat", headers=customer, json={"message": prompt})
    assert response.status_code == 200, response.text
    decisions = client.app.state.chat.events[-1]["action_decisions"]
    assert decisions and decisions[0]["decision"] == "unavailable"
    assert decisions[0]["verified"] is False
    # The dataset file must be byte-identical: no transfer, no ledger change.
    assert client.app.state.storage.path.read_bytes() == before
    assert (
        client.post(
            "/api/demo-admin/dataset/reset", headers=admin, json={"confirmed": True, "expected_version": 1}
        ).status_code
        == 200
    )
    assert not client.app.state.chat.conversations


def test_health_and_filters(client):
    assert client.get("/health").json() == {"status": "alive"}
    assert client.get("/ready").status_code == 200
    login(client)
    result = client.get("/api/accounts/credit-card/transactions?category=restaurants&page_size=100").json()
    assert result["items"] and all(t["category"] == "restaurants" for t in result["items"])


def test_controlled_scenario_accepts_pasted_whitespace(client):
    customer = login(client)
    admin = login(client, True)
    run = client.post("/api/demo-admin/run", headers=admin).json()
    assert (
        client.post("/api/demo-admin/bind", headers=customer, json={"token": run["binding"]}).status_code
        == 200
    )
    run = client.put(
        "/api/demo-admin/scenario",
        headers=admin,
        json={"run_id": run["id"], "expected_revision": run["revision"], "scenario_id": "incomplete_answer"},
    ).json()
    prompt = "How much did I spend on restaurants last month, what were my three biggest transactions, and how does that compare with the previous month?"
    pasted = "  \n" + prompt.replace("three biggest", "three   biggest") + "\n  "
    response = client.post("/api/chat", headers=customer, json={"message": pasted})
    assert response.status_code == 200, response.text
    assert response.json()["answer"] == "Your spending is recorded."
    assert client.app.state.chat.events[-1]["scenario"] == "incomplete_answer"
    rejected = client.post("/api/chat", headers=customer, json={"message": prompt.replace("three", "two")})
    assert rejected.status_code == 200


def test_presenter_workspace_without_customer_login(client):
    from app.demo.scenarios import SCENARIOS

    assert client.post("/api/demo-admin/workspace").status_code == 401
    headers = login(client, True)
    run = client.post("/api/demo-admin/workspace", headers=headers).json()
    assert client.post("/api/demo-admin/workspace", headers=headers).json()["id"] == run["id"]
    assert client.get("/api/auth/session").json()["authenticated"] is False
    payload = {
        "run_id": run["id"], "expected_revision": run["revision"], "scenario": "incomplete_answer", "protection": False
    }
    assert client.put("/api/demo-admin/workspace", json=payload).status_code == 403
    run = client.put("/api/demo-admin/workspace", headers=headers, json=payload).json()
    assert client.put("/api/demo-admin/workspace", headers=headers, json=payload).status_code == 409
    answer = client.post(
        "/api/demo-admin/chat",
        headers=headers,
        json={
            "run_id": run["id"],
            "expected_revision": run["revision"],
            "message": SCENARIOS["incomplete_answer"]["prompt"],
        },
    ).json()
    assert answer["answer"] == "Your spending is recorded."
    assert answer["scenario"] == "incomplete_answer"
    assert answer["protection_enabled"] is False
    assert answer["protection_decision"]["decision"] == "disabled"
    events = client.get("/api/demo-admin/status").json()["events"]
    assert events[-1]["presenter_run_id"] == run["id"]
    # A second presenter cannot modify or use the first presenter's demo.
    second = login(client, True)
    assert (
        client.post(
            "/api/demo-admin/chat",
            headers=second,
            json={"run_id": run["id"], "expected_revision": run["revision"], "message": "Hello"},
        ).status_code
        == 404
    )
    fresh = client.post("/api/demo-admin/workspace", headers=second).json()
    assert fresh["scenario"] == "normal_spending"
    assert fresh["id"] != run["id"]


def test_demo_setting_change_clears_conversation_and_rejects_stale_send(client):
    headers = login(client, True)
    run = client.post("/api/demo-admin/workspace", headers=headers).json()
    first = client.post(
        "/api/demo-admin/chat",
        headers=headers,
        json={"run_id": run["id"], "expected_revision": 0, "message": "Hello"},
    ).json()
    changed = client.put(
        "/api/demo-admin/workspace",
        headers=headers,
        json={"run_id": run["id"], "expected_revision": 0, "scenario": "incorrect_total", "protection": False},
    ).json()
    assert first["conversation_id"] not in client.app.state.chat.conversations
    assert changed["revision"] == 1
    assert (
        client.post(
            "/api/demo-admin/chat",
            headers=headers,
            json={"run_id": run["id"], "expected_revision": 0, "message": "Hello"},
        ).status_code
        == 409
    )
    assert (
        client.put(
            "/api/demo-admin/workspace",
            headers=headers,
            json={"run_id": run["id"], "expected_revision": 1, "scenario": "incorrect_total", "protection": True},
        ).status_code
        == 422
    )


def test_a_blocked_action_says_why_it_could_not_be_verified(settings):
    """Three causes used to collapse into one message, so a blocked transfer could not be told
    apart from a broken request. Each needs a different fix, so each is named."""
    import asyncio
    from types import SimpleNamespace

    from app.observability.protection import ControlNotEvaluated, Protection

    protection = Protection(settings)
    logger = SimpleNamespace(log_stream_id="stream-1")

    async def no_control(*args, **kwargs):
        raise ControlNotEvaluated(
            {"cause": "no_control_selected", "matches": 0, "non_matches": 0, "errors": []}
        )

    protection._evaluate = no_control
    settings.agent_control_url = "https://agent-control.example.com"
    settings.galileo_enabled = True
    settings.galileo_api_key = settings.openai_api_key
    allowed, decision = asyncio.run(
        protection.check_action("transfer_funds", {"amount_cents": 450000}, logger, True)
    )
    # Blocked either way; what changes is being able to say why.
    assert allowed is False
    assert decision["verified"] is False
    assert decision["diagnosis"]["cause"] == "no_control_selected"

    async def request_failed(*args, **kwargs):
        raise TimeoutError

    protection._evaluate = request_failed
    allowed, decision = asyncio.run(
        protection.check_action("transfer_funds", {"amount_cents": 450000}, logger, True)
    )
    assert allowed is False
    assert decision["diagnosis"]["cause"] == "request_failed"
    assert decision["diagnosis"]["error"] == "TimeoutError"


def test_setup_button_is_hidden_unless_asked_for(client, settings):
    """It writes judges, metrics and control bindings into whatever tenant is connected."""
    headers = login(client, True)
    assert client.get("/api/demo-admin/status", headers=headers).json()["setup_button"] is False

    settings.demo_setup_button = True
    assert client.get("/api/demo-admin/status", headers=headers).json()["setup_button"] is True

    # Never in a workshop, where building it by hand is the lab.
    settings.demo_mode = "workshop"
    assert client.get("/api/demo-admin/status", headers=headers).json()["setup_button"] is False


def test_normal_answers_offers_the_guardrail_actions_ungated(client):
    """The "before" half of the guardrail demo lives under Normal Answers.

    The same eight prompts appear there with nothing gating them and under the guardrail scenario
    where they are refused, so they are one shared list rather than two that can drift.
    """
    from app.demo.scenarios import SCENARIOS

    groups = SCENARIOS["normal_spending"]["prompt_groups"]
    assert [g["label"] for g in groups] == ["Questions for this scenario", "Disabled Guardrail questions"]
    assert groups[1]["prompts"] is SCENARIOS["money_transfer"]["prompts"]
    # Every gated action and every allowed one, so the contrast is runnable from either scenario.
    questions = " ".join(groups[1]["prompts"])
    for expected in ("1234", "Dan", "my Savings account", "from Tom's account number 1234 to my account"):
        assert expected in questions, expected

    headers = login(client, True)
    served = client.get("/api/demo-admin/status", headers=headers).json()["scenarios"]
    assert served["normal_spending"]["prompt_groups"][1]["label"] == "Disabled Guardrail questions"


def test_reprovisioning_keeps_a_participants_session_secret(tmp_path):
    """Rotating it on an update logs the whole room out, for no reason.

    Deploying a new version re-runs `workshop.py up`, which rewrites each participant's env file.
    A fresh secret there invalidates every signed cookie they hold.
    """
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
    from workshop import participant_env, read_env

    base = {"DEMO_PASSWORD": "p", "DEMO_ADMIN_PASSWORD": "a"}
    first = participant_env(base, 1, "10.0.0.5", 3101, "0.0.0.0", "workshop", "http://10.0.0.5:3101")
    path = tmp_path / ".env.p01"
    path.write_text(first)
    secret = read_env(path)["SESSION_SECRET"]
    assert secret

    again = participant_env(
        base, 1, "10.0.0.5", 3101, "0.0.0.0", "workshop", "http://10.0.0.5:3101", read_env(path)
    )
    path.write_text(again)
    assert read_env(path)["SESSION_SECRET"] == secret

    # A participant with no env file yet still gets a fresh one.
    fresh = participant_env(base, 2, "10.0.0.5", 3102, "0.0.0.0", "workshop", "http://10.0.0.5:3102")
    assert "SESSION_SECRET=" in fresh and secret not in fresh


def test_provider_error_names_the_cause_a_presenter_can_act_on():
    """"Failed" alone made a mistyped key, a mistyped model and an unreachable host identical.

    A workshop participant has the portal and nothing else: no shell, no log. If the card does not
    say which of the three it is, the only way forward is to ask the instructor.
    """
    from app.agent import provider_error

    assert "401" in provider_error(Exception("Error code: 401 - Unauthorized"), "openai")
    assert "404" in provider_error(Exception("Error code: 404 - model_not_found"), "openai")
    assert "429" in provider_error(Exception("Error code: 429 - exceeded your quota"), "openai")
    assert "403" in provider_error(Exception("Error code: 403 - forbidden"), "openai")
    # The same transport failure means different things depending on where the model is.
    assert "Ollama" in provider_error(Exception("Connection refused"), "ollama")
    assert "base URL" in provider_error(Exception("Connection refused"), "openai")
    # Unrecognised: the class name carries no secret and names the family of fault.
    assert provider_error(ValueError("something odd"), "openai").startswith("ValueError")


def test_provider_error_never_echoes_the_provider_text():
    """The guard that matters. A 401 body quotes a fragment of the key that was sent, and the
    presenter password is published in this repository, so anyone who can read this card is not
    trusted with even part of a key."""
    from app.agent import provider_error

    leaky = Exception(
        "Error code: 401 - {'error': {'message': 'Incorrect API key provided: "
        "sk-proj-SECRETVALUE1234. You can find your API key at https://platform.openai.com/keys'}}"
    )
    message = provider_error(leaky, "openai")
    assert "sk-proj" not in message
    assert "SECRETVALUE1234" not in message
    assert "platform.openai.com" not in message


def test_a_failed_provider_reads_as_failed_in_the_portal():
    """Static guard on the card. The reason is useless if nobody looks at the badge, and a `failed`
    badge rendered in the same muted grey as `connected` is not something anyone looks at."""
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    admin = (root / "frontend/components/Admin.tsx").read_text()
    css = (root / "frontend/app/globals.css").read_text()

    # The card must not hardcode the neutral class for a state that can be a failure.
    assert 'className={providerBadge(status.provider_status.state)}' in admin
    assert 'state === "failed" ? "badge failed"' in admin
    assert "status.provider_status.last_error" in admin
    # And the variant has to exist, or the class name resolves to nothing.
    assert ".badge.failed {" in css
    assert "var(--red)" in css.split(".badge.failed {")[1].split("}")[0]


def test_the_status_endpoint_carries_the_reason_a_provider_failed(settings):
    """End to end, because the other two tests prove the halves and not the join.

    A provider that rejects the key has to reach the portal card as a sentence. This drives a real
    turn through a model that raises what OpenAI raises, then reads the card's own endpoint.
    """
    from conftest import FakeModel
    from fastapi.testclient import TestClient

    from app.main import create_app

    class Rejecting(FakeModel):
        def _generate(self, messages, stop=None, run_manager=None, **kwargs):
            raise RuntimeError(
                "Error code: 401 - {'error': {'message': 'Incorrect API key provided: sk-proj-LEAK'}}"
            )

    def builder(s, endpoint=None):
        return Rejecting()

    with TestClient(create_app(settings, model_builder=builder)) as client:
        customer = login(client)
        turn = client.post("/api/chat", headers=customer, json={"message": "What is my balance?"})
        assert turn.status_code == 503, turn.text
        admin = login(client, admin=True)
        provider = client.get("/api/demo-admin/status", headers=admin).json()["provider_status"]

    assert provider["state"] == "failed"
    assert "401" in provider["last_error"]
    assert "sk-proj" not in provider["last_error"] and "LEAK" not in provider["last_error"]


def test_a_bad_request_is_named_rather_than_falling_through():
    """The regression this test exists for.

    langchain_openai wraps an OpenAI 400 as OpenAIInvalidRequestError. The first version of the
    mapper covered 401, 403, 404 and 429 and not 400, so a real workshop failure reached the card
    as "OpenAIInvalidRequestError while calling the provider", which names the exception rather
    than the mistake.
    """
    from app.agent import provider_error

    # Recognised by class name alone, because the wrapper does not always put the code in the text.
    class OpenAIInvalidRequestError(Exception):
        pass

    generic = provider_error(OpenAIInvalidRequestError("no number here"), "openai")
    assert "400" in generic and "identifier" in generic
    assert "OpenAIInvalidRequestError" not in generic

    # The two 400s this app provokes itself: it always sends max_tokens, and sends temperature
    # outside the reasoning families.
    parameter = provider_error(
        Exception("Error code: 400 - Unsupported parameter: 'max_tokens' is not supported"), "openai"
    )
    assert "max_completion_tokens" in parameter
    temperature = provider_error(
        Exception("Error code: 400 - Unsupported value: 'temperature' does not support 0.2"), "openai"
    )
    assert "temperature" in temperature and "Reasoning models" in temperature


def test_the_provider_failure_is_logged_in_full_but_never_with_a_key():
    """The card's sentence is deliberately lossy, so the provider's own words go to the log for
    whoever has to fix the endpoint. That log must still not carry a key: a 401 body quotes the
    one that was sent, and these logs outlive the turn."""
    from app.agent import redact

    assert redact("Incorrect API key provided: sk-proj-ABCDEFGH1234") == (
        "Incorrect API key provided: <redacted>"
    )
    assert "tv-pat-" not in redact("Authorization: Bearer tv-pat-ZZZZZZZZ99")
    # Text with nothing key-shaped survives intact, or the log would be useless.
    assert redact("model gpt-4.1-mini does not exist") == "model gpt-4.1-mini does not exist"
