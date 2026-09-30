import asyncio
import re
from datetime import date

import pytest
from conftest import login
from langchain_core.messages import AIMessage

from app.demo.generator import OTHER_CUSTOMERS, generate
from app.demo.scenarios import WRONG_CUSTOMER_ANSWER, inject
from app.observability.setup_definitions import _foreign_account_pattern
from app.schemas import Dataset
from app.tools import Banking, build_tools


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
    tom = banking.resolve("1234")
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
    before = banking.resolve("1234").posted_balance_cents
    tools = {t.name: t for t in build_tools(banking, {})}
    result = tools["transfer_funds"].invoke(
        {"to_account": "1234", "amount_cents": 10000, "description": "test"}
    )
    assert result["credited_account"] == "•••• 1234"
    assert banking.resolve("1234").posted_balance_cents == before + 10000


def test_other_customers_resolve_by_number_and_by_name(client):
    """Tom and Dan are real accounts, reachable the way a customer would name them."""
    dataset = client.app.state.storage.dataset
    banking = Banking(
        dataset, client.app.state.telemetry.settings.policy_dir, client.app.state.storage
    )
    for text, owner in (
        ("1234", "Tom Whitfield"),
        ("4127", "Dan Whitfield"),
        ("Tom", "Tom Whitfield"),
        ("Dan Whitfield", "Dan Whitfield"),
        ("How much is in Dan's everyday account?", "Dan Whitfield"),
    ):
        assert banking.resolve(text).owner_name == owner, text
    # A number the customer does supply wins over a name that happens to appear in the sentence.
    assert banking.resolve("Tom's account number 4127").owner_name == "Dan Whitfield"


def test_internal_transfer_keeps_the_ledger_reconciled(client):
    """A move between the customer's own accounts writes both rows.

    A credit with no matching transaction would make the whole dataset fail to load on the next
    read, which is exactly how the `other_accounts` change bricked the app.
    """
    dataset = client.app.state.storage.dataset
    banking = Banking(
        dataset, client.app.state.telemetry.settings.policy_dir, client.app.state.storage
    )
    tools = {t.name: t for t in build_tools(banking, {})}
    savings_before = banking.account("savings").posted_balance_cents
    everyday_before = banking.account("everyday").posted_balance_cents
    result = tools["transfer_funds"].invoke(
        {"to_account": "my savings account", "amount_cents": 10000, "description": "test"}
    )
    assert result["belongs_to_authenticated_customer"] is True
    assert banking.account("savings").posted_balance_cents == savings_before + 10000
    assert banking.account("everyday").posted_balance_cents == everyday_before - 10000
    Dataset.model_validate(dataset.model_dump())


def test_guardrail_pattern_denies_only_other_customers():
    """The control is a deny-list, not a feature switch.

    Matching everything would refuse the customer's own balance checks and own transfers too, and
    the demo would show the guardrail breaking the product rather than preventing a harm.
    """
    pattern = _foreign_account_pattern()
    for denied in ('{"account_number": "1234"}', '{"account_number": "4127"}',
                   '{"to_account": "Dan"}', '{"to_account": "Tom Whitfield"}'):
        assert re.search(pattern, denied), denied
    for allowed in ('{"account_number": "2058"}', '{"account_number": "1042"}',
                    '{"to_account": "my savings account"}'):
        assert not re.search(pattern, allowed), allowed


def test_wrong_customer_answer_quotes_dans_real_account():
    """The leak is real data, not invented text: Dan's account and balance come from the dataset."""
    dan = next(o for o in OTHER_CUSTOMERS if o["owner_name"] == "Dan Whitfield")
    assert dan["masked_number"] in WRONG_CUSTOMER_ANSWER
    assert f"${dan['balance_cents'] / 100:,.2f}" in WRONG_CUSTOMER_ANSWER
    generated = generate(42, date(2026, 9, 15))
    account = next(a for a in generated.other_accounts if a.owner_name == "Dan Whitfield")
    assert account.posted_balance_cents == dan["balance_cents"]
