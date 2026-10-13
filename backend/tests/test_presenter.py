"""The demo chip: a presenter aid that must be invisible and inert until switched on.

The risk here is not that the chip fails. It is that it appears, or ships the fault catalogue, on a
box nobody enabled it on -- a hundred cloned instances in front of a hundred participants.
"""

from app.demo.scenarios import (
    GUARDRAIL_PROMPTS,
    PRESENTER_PRESETS,
    SCENARIOS,
)
from app.preferences import Preferences
from tests.conftest import login


def test_the_chip_is_off_until_somebody_turns_it_on(tmp_path):
    """Off by default has to mean off on every box that boots from the image, not off in source."""
    assert Preferences(tmp_path).all() == {"demo_chip": False}


def test_a_preference_survives_a_restart(tmp_path):
    preferences = Preferences(tmp_path)
    preferences.set("demo_chip", True)
    assert Preferences(tmp_path).all()["demo_chip"] is True


def test_a_file_of_the_wrong_shape_falls_back_to_off(tmp_path):
    """A string "false" is truthy in a template, so a hand-edited file must not reach one."""
    (tmp_path / "presenter-settings.json").write_text('{"demo_chip": "false"}')
    assert Preferences(tmp_path).all()["demo_chip"] is False
    (tmp_path / "presenter-settings.json").write_text("not json at all")
    assert Preferences(tmp_path).all()["demo_chip"] is False


def test_an_unknown_preference_cannot_be_written(tmp_path):
    import pytest

    with pytest.raises(KeyError):
        Preferences(tmp_path).set("install_backdoor", True)


def test_the_banking_page_is_told_nothing_while_the_chip_is_off(client):
    """Not just hidden: a box with the chip off never sends the fault catalogue to a customer."""
    customer = login(client)
    state = client.post("/api/chat/demo-sync", headers=customer).json()
    assert state["demo_chip"] is False
    assert state["presets"] == []


def test_enabling_the_chip_delivers_the_presets_to_the_banking_page(client):
    admin = login(client, admin=True)
    enabled = client.put(
        "/api/demo-admin/preferences",
        headers=admin,
        json={"name": "demo_chip", "enabled": True},
    )
    assert enabled.status_code == 200, enabled.text
    assert enabled.json()["preferences"]["demo_chip"] is True

    customer = login(client)
    state = client.post("/api/chat/demo-sync", headers=customer).json()
    assert state["demo_chip"] is True
    assert [p["id"] for p in state["presets"]] == [p["id"] for p in PRESENTER_PRESETS]


def test_an_unknown_preference_name_is_refused(client):
    admin = login(client, admin=True)
    response = client.put(
        "/api/demo-admin/preferences", headers=admin, json={"name": "nonsense", "enabled": True}
    )
    assert response.status_code == 422


def test_arming_needs_a_presenter_session(client):
    """The chip is a convenience; the authority is unchanged. A customer alone cannot arm a fault."""
    customer = login(client)
    response = client.post(
        "/api/demo-admin/arm", headers=customer, json={"preset_id": "wrong_customer"}
    )
    assert response.status_code in (401, 403)


def test_arming_creates_the_run_rather_than_requiring_the_portal(client):
    """The whole point: it works on a box where the portal was never opened or paired."""
    admin = login(client, admin=True)
    response = client.post(
        "/api/demo-admin/arm", headers=admin, json={"preset_id": "pull_blocked"}
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["run"]["scenario"] == "money_transfer"
    assert body["run"]["protection"] is True
    assert body["prompt"]


def test_arming_an_unknown_preset_is_refused(client):
    admin = login(client, admin=True)
    response = client.post("/api/demo-admin/arm", headers=admin, json={"preset_id": "nope"})
    assert response.status_code == 422


def test_clearing_is_a_preset_with_nothing_to_ask(client):
    admin = login(client, admin=True)
    body = client.post("/api/demo-admin/arm", headers=admin, json={"preset_id": "clear"}).json()
    assert body["run"]["scenario"] == "normal_spending"
    assert body["run"]["protection"] is False
    # No prompt, so the chip arms without sending anything.
    assert body["prompt"] is None


def test_no_preset_can_drift_from_its_scenario():
    """A preset whose question no longer matches its scenario demonstrates nothing, and says
    nothing about why. The prompts are taken from the scenario constants for that reason."""
    for preset in PRESENTER_PRESETS:
        assert preset["scenario"] in SCENARIOS, preset["id"]
        if preset["prompt"] is None:
            continue
        scenario = SCENARIOS[preset["scenario"]]
        allowed = {scenario["prompt"], *scenario.get("prompts", []), *GUARDRAIL_PROMPTS}
        assert preset["prompt"] in allowed, preset["id"]


def test_the_guardrail_demo_is_the_same_two_questions_twice():
    """The demonstration is the contrast, so each question appears once with the guardrail off and
    once with it on, worded identically. A read that exposes another customer and a pull that takes
    their money: both unambiguous harm, unlike a transfer *to* someone, which a bank is for."""
    by_id = {p["id"]: p for p in PRESENTER_PRESETS}
    for off, on in (("read_open", "read_blocked"), ("pull_open", "pull_blocked")):
        assert by_id[off]["prompt"] == by_id[on]["prompt"], off
        assert by_id[off]["protection"] is False
        assert by_id[on]["protection"] is True
        # Identical questions, so only the note can tell a presenter which row is which.
        assert by_id[off]["note"] != by_id[on]["note"], off
    # Another customer is named, because "account number 1234" does not say whose it is.
    assert "Tom" in by_id["read_open"]["prompt"]
    assert "from Tom" in by_id["pull_open"]["prompt"]


def test_the_control_is_present():
    """A guardrail that refuses everything passes both blocked tests and is useless. This is the
    entry that catches it, and it is how the defects in v1.0.3 and v1.0.4 were found."""
    by_id = {p["id"]: p for p in PRESENTER_PRESETS}
    assert by_id["own_account"]["protection"] is True
    assert "my Savings" in by_id["own_account"]["prompt"]


def test_every_preset_says_what_it_breaks():
    """The menu shows the question as its label, so the question alone has to be unambiguous about
    what will happen. Two presets share a prompt and differ only in the guardrail, which is exactly
    the pair a note has to tell apart."""
    for preset in PRESENTER_PRESETS:
        assert preset["note"].strip(), preset["id"]
    by_id = {p["id"]: p for p in PRESENTER_PRESETS}
    assert by_id["read_open"]["note"] != by_id["read_blocked"]["note"]


def test_the_chip_never_shows_the_armed_scenario_on_its_face():
    """A presentation requirement, so it needs a guard: an audience should not be able to read
    "wrong customer enabled" off the screen. The armed row is marked inside the menu instead, which
    is only open when the presenter opens it, and the full description stays on hover for the
    presenter."""
    from pathlib import Path as FilePath

    chat = (FilePath(__file__).resolve().parents[2] / "frontend/components/Chat.tsx").read_text()
    # The chip's visible text: everything between the end of its opening tag and its close.
    opening = chat.index("onClick={() => setChipOpen")
    face = chat[chat.index(">", opening) + 1 : chat.index("</button>", opening)]
    assert "demo.description" not in face, f"the chip face renders the scenario: {face.strip()!r}"
    assert "Demo" in face
    # Still available to the presenter, invisible to the room.
    assert "title={demo.description}" in chat[:opening]
    # And the live row is marked where only the presenter sees it.
    assert "demo-chip-live" in chat


def test_the_menu_is_grouped_because_the_pairs_read_identically():
    """read_open and read_blocked show the same question text. Without a heading saying which half
    of the menu you are in, the only difference is a 9px note."""
    groups = [(p["id"], p.get("group")) for p in PRESENTER_PRESETS]
    assert dict(groups)["incomplete"] == "Evaluator faults"
    assert dict(groups)["read_open"] == "No guardrail"
    assert dict(groups)["read_blocked"] == "Guardrail on"
    # One heading per group, on its first entry, or the menu repeats it on every row.
    assert [g for _, g in groups if g] == [
        "Evaluator faults",
        "No guardrail",
        "Guardrail on",
        "Reset",
    ]


def test_a_transfer_is_still_a_valid_dataset_afterwards():
    """The regression this exists for: a transfer that fails validation is lost silently.

    Dataset.ledger rejects any transaction dated after the manifest's reference date. Stamping a
    transfer with the real date, on a dataset seeded earlier, made storage.write raise, the tool
    return an error, and the agent answer "there was an issue with the transfer request" -- which
    reads exactly like a model declining, so the guardrail demo appeared to break for the wrong
    reason. Nothing covered the write-and-reload path.
    """
    from datetime import date
    from pathlib import Path as FilePath

    from app.demo.generator import generate
    from app.schemas import Dataset
    from app.tools import Banking, build_tools

    policies = FilePath(__file__).resolve().parents[2] / "data/policies"
    reference = date(2026, 9, 15)
    dataset = generate(42, reference)
    tools = {t.name: t for t in build_tools(Banking(dataset, policies), {})}

    before = next(a.posted_balance_cents for a in dataset.other_accounts if a.owner_name.startswith("Tom"))
    result = tools["transfer_funds"].invoke(
        {"to_account": "my account", "amount_cents": 100_000, "from_account": "1234"}
    )
    assert result["transferred_cents"] == 100_000, result
    assert result["debited_another_customer"] is True
    after = next(a.posted_balance_cents for a in dataset.other_accounts if a.owner_name.startswith("Tom"))
    assert after == before - 100_000

    # The whole point: the dataset the transfer produced has to survive the validator, or the row
    # never reaches disk and the agent reports a tool error instead of a completed transfer.
    Dataset.model_validate(dataset.model_dump())
    assert all(row.posted_date <= reference for row in dataset.transactions)


def test_a_preset_forces_a_fresh_sync_and_does_not_blame_sign_in():
    """Two faults from one race, both reported by a presenter mid-test.

    useDemoConnection polls every second and sync() reused an in-flight request, so a preset that
    had just changed the settings could be handed the answer to a request made *before* the change,
    send the stale version, and get 409 "Demo settings changed" back. The catch then told the
    presenter to sign in to /demo-admin, which was the one thing that could not fix it, while the
    portal was connected the whole time.
    """
    from pathlib import Path as FilePath

    root = FilePath(__file__).resolve().parents[2]
    hook = (root / "frontend/lib/demo-connection.ts").read_text()
    chat = (root / "frontend/components/Chat.tsx").read_text()

    # The dedupe has to be skippable, or a caller can never get state newer than the poll's.
    assert "sync(force = false)" in hook
    assert "if (pending.current && !force) return pending.current;" in hook
    # Sending forces it, because a preset arms and sends in one click.
    assert "demo.sync(true)" in chat
    # The acknowledgement is advisory: a 409 there means a newer version exists, not a failure.
    assert "/* superseded */" in hook
    # And sign-in is only suggested when the failure was actually about authorization.
    assert "unauthorized" in chat


def test_a_turn_does_not_report_its_tokens_twice():
    """The delivered-answer span used to repeat the whole turn's usage.

    The LangChain callback logs every model call the agent makes, with its own tokens and duration.
    Our explicit span then reported the summed total again, so adding up a turn's LLM spans gave
    roughly double what the turn actually spent, which is the figure a partner would be quoted.

    The injection pass is the exception and keeps its counts: it runs with callbacks deliberately
    off, so its own span is the only record of it.
    """
    from pathlib import Path as FilePath

    source = (FilePath(__file__).resolve().parents[2] / "backend/app/observability/galileo.py").read_text()
    answer = source[source.index("def answer_span") : source.index("async def finish")]
    assert "num_input_tokens" not in answer, "the delivered-answer span must not repeat the turn's usage"
    assert "duration_ns=duration_ns" in answer, "and it must carry a latency, which Galileo never infers"

    fault = source[source.index("def fault_span") : source.index("def answer_span")]
    assert "num_input_tokens" in fault, "the uninstrumented injection pass is the only exception"
    assert "duration_ns=duration_ns" in fault


def test_both_explicit_spans_are_timed_from_the_calls_they_describe():
    """Measured around the real work, not reused from the trace, or the number means nothing."""
    from pathlib import Path as FilePath

    agent = (FilePath(__file__).resolve().parents[2] / "backend/app/agent.py").read_text()
    assert "agent_started = time.perf_counter_ns()" in agent
    assert "agent_ns = time.perf_counter_ns() - agent_started" in agent
    assert "fault_ns = time.perf_counter_ns() - fault_started" in agent
    assert "answer_span(turn, message, candidate, evidence, agent_ns)" in agent
