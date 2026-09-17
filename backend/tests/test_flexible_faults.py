import asyncio

import pytest
from conftest import login
from langchain_core.messages import AIMessage

from app.demo.scenarios import inject


@pytest.mark.parametrize("scenario", ["incomplete_answer", "incorrect_total", "hallucinated_policy"])
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
