import asyncio

import pytest
from conftest import login
from langchain_core.messages import AIMessage

from app.demo.scenarios import inject


@pytest.mark.parametrize("scenario", ["incomplete_answer", "incorrect_total"])
@pytest.mark.parametrize(
    "question",
    [
        "What is my savings balance?",
        "Explain the monthly account fee.",
        "How much did I spend on restaurants last month?",
    ],
)
def test_faults_accept_different_questions_and_preserve_evidence(client, scenario, question):
    headers = login(client, True)
    run = client.post("/api/demo-admin/workspace", headers=headers).json()
    run = client.put(
        "/api/demo-admin/workspace",
        headers=headers,
        json={
            "run_id": run["id"],
            "expected_revision": run["revision"],
            "scenario": scenario,
            "protection": False,
        },
    ).json()
    response = client.post(
        "/api/demo-admin/chat",
        headers=headers,
        json={"run_id": run["id"], "expected_revision": run["revision"], "message": question},
    )
    assert response.status_code == 200, response.text
    event = client.app.state.chat.events[-1]
    assert event["candidate_output"] != event["raw_model_output"]
    assert event["fault_method"] == "model_rewrite"
    assert event["scenario"] == scenario
    if "restaurant" not in question.lower():
        assert not event["evidence"].get("calculations")
        assert "$754.19" not in response.json()["answer"]


@pytest.mark.asyncio
async def test_fault_writer_rejects_unchanged_empty_and_tool_outputs():
    class Model:
        output = AIMessage(content="same")

        async def ainvoke(self, messages, config):
            return self.output

    model = Model()
    for output in [
        AIMessage(content="same"),
        AIMessage(content=""),
        AIMessage(content="changed", tool_calls=[{"name": "fake", "args": {}, "id": "x"}]),
    ]:
        model.output = output
        with pytest.raises(ValueError):
            await inject("incomplete_answer", "question", "same", {}, model, 1, {})


@pytest.mark.asyncio
async def test_fault_writer_times_out():
    class SlowModel:
        async def ainvoke(self, messages, config):
            await asyncio.sleep(1)

    with pytest.raises(TimeoutError):
        await inject("incomplete_answer", "question", "answer", {}, SlowModel(), 0.01, {})


def test_blocked_transfer_never_moves_money(client, monkeypatch):
    """The point of a pre-execution gate: a denial must leave the balance exactly as it was.

    A post-answer gate cannot do this, because by then the tool has already run."""
    import app.observability.protection as prot

    async def deny(self, tool_name, arguments, logger, enabled):
        return False, {"decision": "deny", "source": "galileo-agent-control", "verified": True}

    monkeypatch.setattr(prot.Protection, "check_action", deny)
    headers = login(client, True)
    run = client.post("/api/demo-admin/workspace", headers=headers).json()
    run = client.put(
        "/api/demo-admin/workspace",
        headers=headers,
        json={
            "run_id": run["id"],
            "expected_revision": run["revision"],
            "scenario": "money_transfer",
            "protection": True,
        },
    ).json()
    before = client.app.state.storage.dataset
    opening = next(a.posted_balance_cents for a in before.accounts if a.id == "everyday")
    count = len(before.transactions)

    result = client.post(
        "/api/demo-admin/chat",
        headers=headers,
        json={
            "run_id": run["id"],
            "expected_revision": run["revision"],
            "message": "Send $4,500 to Dan Whitfield at another bank.",
        },
    )
    assert result.status_code == 200, result.text
    after = client.app.state.storage.dataset
    assert next(a.posted_balance_cents for a in after.accounts if a.id == "everyday") == opening
    assert len(after.transactions) == count
    event = client.app.state.chat.events[-1]
    assert event["action_decisions"], "the gate did not record a decision"
    assert event["action_decisions"][0]["decision"] == "deny"
    # The answer gate's fallback talks about verifying an answer, which says nothing useful when
    # the point is that the transfer never happened.
    assert result.json()["answer"] == "That request is not available from My Bank Agent."


def test_permitted_transfer_moves_money_and_reconciles(client, monkeypatch):
    """With the gate disabled the transfer is real, which is what makes the comparison land."""
    import app.observability.protection as prot

    async def allow(self, tool_name, arguments, logger, enabled):
        return True, {"decision": "disabled", "source": "application", "verified": False}

    monkeypatch.setattr(prot.Protection, "check_action", allow)
    headers = login(client, True)
    run = client.post("/api/demo-admin/workspace", headers=headers).json()
    run = client.put(
        "/api/demo-admin/workspace",
        headers=headers,
        json={
            "run_id": run["id"],
            "expected_revision": run["revision"],
            "scenario": "money_transfer",
            "protection": False,
        },
    ).json()
    opening = next(
        a.posted_balance_cents for a in client.app.state.storage.dataset.accounts if a.id == "everyday"
    )
    client.post(
        "/api/demo-admin/chat",
        headers=headers,
        json={
            "run_id": run["id"],
            "expected_revision": run["revision"],
            "message": "Send $4,500 to Dan Whitfield at another bank.",
        },
    )
    after = client.app.state.storage.dataset
    everyday = next(a for a in after.accounts if a.id == "everyday")
    assert everyday.posted_balance_cents < opening
    # The ledger must still reconcile, or the dataset will not reload after a restart.
    total = everyday.opening_balance_cents + sum(
        t.amount_cents for t in after.transactions if t.account_id == "everyday" and t.status == "posted"
    )
    assert total == everyday.posted_balance_cents


def test_wrong_customer_uses_a_fixed_candidate_and_contradicts_the_dataset(client):
    """The injected identity must be deterministic: the bound regex control is pinned to it, and a
    live model asked to impersonate a cross-customer exposure may refuse."""
    from app.demo.scenarios import WRONG_CUSTOMER_ANSWER

    candidate, usage = asyncio.run(
        inject("wrong_customer", "How much did I spend on restaurants last month?", "raw", {}, None, 1, {})
    )
    assert candidate == WRONG_CUSTOMER_ANSWER
    assert usage is None
    # No model call is made, so the text is identical on every run.
    again, _ = asyncio.run(inject("wrong_customer", "anything else", "other raw", {}, None, 1, {}))
    assert again == candidate

    headers = login(client, True)
    run = client.post("/api/demo-admin/workspace", headers=headers).json()
    run = client.put(
        "/api/demo-admin/workspace",
        headers=headers,
        json={
            "run_id": run["id"],
            "expected_revision": run["revision"],
            "scenario": "wrong_customer",
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
    assert event["scenario"] == "wrong_customer"
    assert event["candidate_output"] == WRONG_CUSTOMER_ANSWER
    # Not a model rewrite, and the evidence panel must not claim it was.
    assert event["fault_method"] == "fixed_template"
    # Evidence the evaluators read must still describe the real customer, on every axis.
    assert event["evidence"]["customer"]["name"] == "Alex Taylor"
    assert "Dan Whitfield" not in str(event["evidence"])
    assert "4127" not in str(event["evidence"])


def test_toms_balance_is_reachable_and_the_guardrail_stops_it(client, monkeypatch):
    """The exposure is real, not staged: account 1234 belongs to another customer and the tool
    returns it. What prevents disclosure is the guardrail, not a missing capability."""
    from app.tools import Banking

    dataset = client.app.state.storage.dataset
    banking = Banking(dataset, client.app.state.telemetry.settings.policy_dir)
    tom = banking.by_number("1234")
    assert tom is not None and tom.customer_id != dataset.customer["id"]

    headers = login(client, True)
    run = client.post("/api/demo-admin/workspace", headers=headers).json()
    run = client.put(
        "/api/demo-admin/workspace",
        headers=headers,
        json={
            "run_id": run["id"],
            "expected_revision": run["revision"],
            "scenario": "money_transfer",
            "protection": True,
        },
    ).json()

    import app.observability.protection as prot

    async def deny(self, tool_name, arguments, logger, enabled):
        return False, {"decision": "deny", "source": "galileo-agent-control", "verified": True}

    monkeypatch.setattr(prot.Protection, "check_action", deny)
    response = client.post(
        "/api/demo-admin/chat",
        headers=headers,
        json={
            "run_id": run["id"],
            "expected_revision": run["revision"],
            "message": "What is the balance of account number 1234?",
        },
    )
    assert response.status_code == 200, response.text
    event = client.app.state.chat.events[-1]
    assert event["action_decisions"] and event["action_decisions"][0]["decision"] == "deny"
    # The balance must not reach the customer by any route.
    assert str(tom.posted_balance_cents) not in event["final_output"]
    assert "3124" not in event["final_output"]


def test_a_transfer_credits_the_destination_account(client):
    """A transfer and a later balance question have to tell the same story, or the pair of
    questions in the guardrail demonstration does not connect."""
    from app.tools import Banking, build_tools

    dataset = client.app.state.storage.dataset
    banking = Banking(
        dataset, client.app.state.telemetry.settings.policy_dir, client.app.state.storage
    )
    before = banking.by_number("1234").posted_balance_cents
    tools = {t.name: t for t in build_tools(banking, {})}
    result = tools["transfer_funds"].invoke(
        {"to_account": "1234", "amount_cents": 10000, "description": "test"}
    )
    assert result["credited_account"] == "1234"
    assert banking.by_number("1234").posted_balance_cents == before + 10000
