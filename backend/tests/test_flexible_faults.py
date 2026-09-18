import asyncio

import pytest
from conftest import login
from langchain_core.messages import AIMessage

from app.demo.scenarios import inject


@pytest.mark.parametrize("scenario", ["incomplete_answer", "incorrect_total", "guardrail_before_after"])
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


def test_before_after_new_question_starts_new_candidate(client):
    headers = login(client, True)
    run = client.post("/api/demo-admin/workspace", headers=headers).json()
    run = client.put(
        "/api/demo-admin/workspace",
        headers=headers,
        json={
            "run_id": run["id"],
            "expected_revision": run["revision"],
            "scenario": "guardrail_before_after",
            "protection": False,
        },
    ).json()
    for question in ["What is the transfer limit?", "What is the monthly fee?"]:
        result = client.post(
            "/api/demo-admin/chat",
            headers=headers,
            json={"run_id": run["id"], "expected_revision": run["revision"], "message": question},
        )
        assert result.status_code == 200
        assert not client.app.state.chat.events[-1]["replayed"]
    assert "fee" in result.json()["answer"]


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
