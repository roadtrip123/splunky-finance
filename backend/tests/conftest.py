import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult

from app.config import Settings
from app.demo.expected_results import money
from app.main import create_app

CUSTOMER_PASSWORD = "test-customer-password-only"
ADMIN_PASSWORD = "test-presenter-password-only"


class FakeModel(BaseChatModel):
    @property
    def _llm_type(self):
        return "offline-test-double"

    def bind_tools(self, tools, **kwargs):
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        if str(messages[0].content).startswith("CONTROLLED_DEMO_FAULT:"):
            source = json.loads(messages[-1].content)
            scenario = str(messages[0].content).splitlines()[0].split(": ", 1)[1]
            question = source["question"].lower()
            if scenario == "incomplete_answer":
                text = (
                    "Your spending is recorded."
                    if "restaurant" in question
                    else "Your account information is available."
                )
            elif scenario == "incorrect_total":
                text = "The total is $999.00 AUD."
            elif "transfer" in question:
                text = "Your Everyday account has an unlimited daily external transfer limit, with no verification required."
            else:
                text = "Bank policy requires a $75 monthly fee for this account."
            return ChatResult(generations=[ChatGeneration(message=AIMessage(content=text))])
        if isinstance(messages[-1], ToolMessage):
            result = json.loads(messages[-1].content)
            text = (
                f"Restaurant spending was {money(result['total_cents'])}."
                if "total_cents" in result
                else json.dumps(result)
            )
            answer = AIMessage(content=text)
        else:
            question = messages[-1].content.lower()
            if "restaurant" in question:
                name, args = (
                    "calculate_spending",
                    {
                        "start": "2026-08-01",
                        "end": "2026-09-01",
                        "category": "restaurants",
                        "compare_start": "2026-07-01",
                        "compare_end": "2026-08-01",
                    },
                )
            elif "limit" in question or "fee" in question:
                name, args = "search_bank_policy", {"query": question[:300], "limit": 3}
            else:
                name, args = "get_accounts", {}
            answer = AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": "test-tool-call"}])
        return ChatResult(generations=[ChatGeneration(message=answer)])


@pytest.fixture
def settings(tmp_path):
    return Settings(
        _env_file=None,
        galileo_enabled=False,
        demo_password=CUSTOMER_PASSWORD,
        demo_admin_password=ADMIN_PASSWORD,
        session_secret="test-signing-secret-32-characters-minimum",
        openai_api_key="fake-offline-key",
        data_dir=tmp_path / "runtime",
        policy_dir=Path(__file__).resolve().parents[2] / "data/policies",
    )


@pytest.fixture
def client(settings):
    with TestClient(create_app(settings, model_builder=lambda s: FakeModel())) as client:
        yield client


def login(client, admin=False):
    prefix = "demo-admin" if admin else "auth"
    response = client.post(
        f"/api/{prefix}/login",
        headers={"Origin": "http://localhost:3000"},
        json={"account_number": "12345678", "password": ADMIN_PASSWORD if admin else CUSTOMER_PASSWORD},
    )
    assert response.status_code == 200, response.text
    return {"Origin": "http://localhost:3000", "X-CSRF-Token": response.json()["csrf_token"]}
