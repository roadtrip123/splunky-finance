import time

from conftest import login
from fastapi.testclient import TestClient

from app.demo.scenarios import SCENARIOS


def workspace(client, headers):
    return client.post("/api/demo-admin/workspace", headers=headers).json()


def change(client, headers, run, scenario):
    result = client.put(
        "/api/demo-admin/workspace",
        headers=headers,
        json={
            "run_id": run["id"],
            "expected_revision": run["revision"],
            "scenario": scenario,
            "protection": False,
        },
    )
    assert result.status_code == 200, result.text
    return result.json()


def test_automatic_link_ack_stale_request_and_normal_restore(client):
    customer = login(client)
    admin = login(client, True)
    run = workspace(client, admin)
    old = client.post("/api/chat/demo-sync", headers=customer).json()
    assert old["connected"]
    run = change(client, admin, run, "incomplete_answer")
    prompt = SCENARIOS["incomplete_answer"]["prompt"]
    assert (
        client.post(
            "/api/chat", headers=customer, json={"message": prompt, "demo_version": old["version"]}
        ).status_code
        == 409
    )
    state = client.post("/api/chat/demo-sync", headers=customer).json()
    assert client.get("/api/demo-admin/status").json()["banking_connection"]["state"] != "applied"
    assert (
        client.post("/api/chat/demo-ack", headers=customer, json={"version": state["version"]}).status_code
        == 200
    )
    assert client.get("/api/demo-admin/status").json()["banking_connection"]["state"] == "applied"
    result = client.post(
        "/api/chat", headers=customer, json={"message": prompt, "demo_version": state["version"]}
    ).json()
    assert result["answer"] == "You spent $754.19 AUD on restaurants last month."
    run = change(client, admin, run, "normal_spending")
    state = client.post("/api/chat/demo-sync", headers=customer).json()
    normal = client.post(
        "/api/chat",
        headers=customer,
        json={
            "message": prompt,
            "conversation_id": result["conversation_id"],
            "demo_version": state["version"],
        },
    ).json()
    assert normal["scenario"] == "normal_spending"
    assert normal["conversation_id"] != result["conversation_id"]
    assert normal["answer"] != result["answer"]
    client.post("/api/chat/demo-disconnect", headers=customer)
    assert not client.post("/api/chat/demo-sync", headers=customer).json()["connected"]


def test_remote_pairing_single_use_stable_target_and_expiry(client):
    admin = login(client, True)
    run = workspace(client, admin)
    with TestClient(client.app) as remote, TestClient(client.app) as other:
        customer = login(remote)
        other_customer = login(other)
        code = client.post("/api/demo-admin/pairing", headers=admin).json()["code"]
        assert remote.post("/api/chat/demo-pair", json={"code": code}).status_code == 403
        assert remote.post("/api/chat/demo-pair", headers=customer, json={"code": code}).status_code == 200
        assert (
            other.post("/api/chat/demo-pair", headers=other_customer, json={"code": code}).status_code == 400
        )
        # Opening local banking must not replace the remote target.
        local = login(client)
        assert not client.post("/api/chat/demo-sync", headers=local).json()["connected"]
        run = change(client, admin, run, "incomplete_answer")
        assert remote.post("/api/chat/demo-sync", headers=customer).json()["scenario"] == "incomplete_answer"
        assert (
            other.post("/api/chat/demo-sync", headers=other_customer).json()["scenario"] == "normal_spending"
        )
        client.app.state.chat.runs[run["id"]]["expires"] = time.time() - 1
        state = remote.post("/api/chat/demo-sync", headers=customer).json()
        assert state["expired"]
        assert (
            remote.post(
                "/api/chat", headers=customer, json={"message": "Hello", "demo_version": state["version"]}
            ).status_code
            == 409
        )
        remote.post("/api/chat/demo-disconnect", headers=customer)
        assert not remote.post("/api/chat/demo-sync", headers=customer).json()["expired"]


def test_inflight_answer_keeps_original_scenario(client):
    import asyncio
    import threading
    from concurrent.futures import ThreadPoolExecutor

    customer = login(client)
    admin = login(client, True)
    run = change(client, admin, workspace(client, admin), "incomplete_answer")
    state = client.post("/api/chat/demo-sync", headers=customer).json()
    started, release = threading.Event(), threading.Event()
    original = client.app.state.telemetry.begin

    async def delayed(*args, **kwargs):
        started.set()
        await asyncio.to_thread(release.wait, 5)
        return await original(*args, **kwargs)

    client.app.state.telemetry.begin = delayed
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(
            client.post,
            "/api/chat",
            headers=customer,
            json={"message": SCENARIOS["incomplete_answer"]["prompt"], "demo_version": state["version"]},
        )
        try:
            assert started.wait(3)
            change(client, admin, run, "normal_spending")
        finally:
            release.set()
        response = future.result(timeout=10)
    assert response.status_code == 200
    assert response.json()["scenario"] == "incomplete_answer"
    assert response.json()["answer"] == "You spent $754.19 AUD on restaurants last month."
    assert client.post("/api/chat/demo-sync", headers=customer).json()["scenario"] == "normal_spending"


def test_pairing_code_expiry(client):
    from app.demo.connections import Connections

    admin = login(client, True)
    run = workspace(client, admin)
    customer_headers = login(client)
    # Exercise the expiry boundary without waiting five minutes.
    links = Connections(client.app.state.auth, client.app.state.chat)
    customer = next(s for s in client.app.state.auth.sessions.values() if s.role == "customer")
    code = links.issue(client.app.state.chat.runs[run["id"]])["code"]
    links.codes[code] = (run["id"], time.time() - 1)
    import pytest
    from fastapi import HTTPException

    with pytest.raises(HTTPException, match="expired"):
        links.pair(customer, code)
    assert client.post("/api/chat/demo-sync", headers=customer_headers).status_code == 200
