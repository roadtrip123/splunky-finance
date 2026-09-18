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
