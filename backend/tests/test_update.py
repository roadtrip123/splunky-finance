"""The update check, and the boundary that keeps the container from doing the update itself."""

import asyncio
import json
import re
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from app.config import Settings
from app.main import create_app
from app.update import Updates, version_key
from tests.conftest import ADMIN_PASSWORD, CUSTOMER_PASSWORD, FakeModel, login


def tags_transport(names, status=200):
    def handler(request):
        if status != 200:
            return httpx.Response(status)
        return httpx.Response(200, json=[{"name": name} for name in names])

    return httpx.MockTransport(handler)


def installed(directory, ref="v0.6.3"):
    """Mimic what scripts/selfupdate.py leaves behind after a run."""
    (directory / "state.json").write_text(json.dumps({"ref": ref, "result": "ok"}))
    return directory


def test_version_key_parses_only_releases():
    assert version_key("v1.2.3") == (1, 2, 3)
    assert version_key("v0.6.10") > version_key("v0.6.9")
    assert version_key("0.6.3") is None
    assert version_key("v0.6.3-rc1") is None


async def test_newest_tag_wins_regardless_of_api_order(tmp_path):
    # The GitHub tags endpoint is not ordered by version, so the order here is deliberately wrong.
    updates = Updates(tmp_path, "o/r", transport=tags_transport(["v0.6.9", "v0.6.10", "v0.5.0"]))
    assert await updates.check() == "v0.6.10"


async def test_update_available_only_when_newer(tmp_path):
    installed(tmp_path, "v0.6.3")
    updates = Updates(tmp_path, "o/r", transport=tags_transport(["v0.6.4"]))
    view = await updates.view()
    assert (view["current"], view["latest"], view["update_available"]) == ("v0.6.3", "v0.6.4", True)

    installed(tmp_path, "v0.6.4")
    updates = Updates(tmp_path, "o/r", transport=tags_transport(["v0.6.4"]))
    assert (await updates.view())["update_available"] is False

    # Ahead of the newest tag, which is where a box following the branch sits. Not an update.
    installed(tmp_path, "v0.7.0")
    updates = Updates(tmp_path, "o/r", transport=tags_transport(["v0.6.4"]))
    assert (await updates.view())["update_available"] is False


async def test_unknown_version_does_not_read_as_up_to_date(tmp_path):
    (tmp_path / "state.json").write_text(json.dumps({"ref": "9f3a1c2", "result": "ok"}))
    updates = Updates(tmp_path, "o/r", transport=tags_transport(["v0.6.4"]))
    view = await updates.view()
    assert view["update_available"] is False
    assert view["comparable"] is False, "a commit sha must not be compared against a tag"


async def test_check_failure_is_reported_not_raised(tmp_path):
    installed(tmp_path)
    updates = Updates(tmp_path, "o/r", transport=tags_transport([], status=503))
    view = await updates.view()
    assert view["latest"] is None
    assert view["check_error"]
    assert view["update_available"] is False


async def test_check_is_cached_until_forced(tmp_path):
    calls = []

    def handler(request):
        calls.append(request.url)
        return httpx.Response(200, json=[{"name": "v0.6.4"}])

    updates = Updates(tmp_path, "o/r", transport=httpx.MockTransport(handler))
    await updates.check()
    await updates.check()
    assert len(calls) == 1, "the status panel polls; the second call must come from cache"
    await updates.check(force=True)
    assert len(calls) == 2


async def test_control_unavailable_without_the_host_side(tmp_path):
    missing = Updates(tmp_path / "absent", "o/r", transport=tags_transport(["v0.6.4"]))
    view = await missing.view()
    assert view["control"] == "unavailable"
    assert "not mounted" in view["control_reason"]

    mounted = Updates(tmp_path, "o/r", transport=tags_transport(["v0.6.4"]))
    view = await mounted.view()
    assert view["control"] == "unavailable"
    assert "not installed" in view["control_reason"]
    with pytest.raises(RuntimeError):
        mounted.request()


async def test_request_writes_one_file_and_is_idempotent(tmp_path):
    installed(tmp_path)
    updates = Updates(tmp_path, "o/r", transport=tags_transport(["v0.6.4"]))
    assert (await updates.view())["control"] == "available"

    updates.request()
    first = updates.pending()
    assert first and first["by"] == "presenter"

    await asyncio.sleep(0.01)
    updates.request()
    assert sorted(p.name for p in tmp_path.iterdir()) == ["request.json", "state.json"]
    assert updates.pending()["requested_at"] > first["requested_at"]


@pytest.fixture
def update_client(tmp_path):
    installed(tmp_path)
    settings = Settings(
        _env_file=None,
        galileo_enabled=False,
        demo_password=CUSTOMER_PASSWORD,
        demo_admin_password=ADMIN_PASSWORD,
        session_secret="test-signing-secret-32-characters-minimum",
        openai_api_key="fake-offline-key",
        data_dir=tmp_path / "runtime",
        policy_dir=Path(__file__).resolve().parents[2] / "data/policies",
        update_state_dir=tmp_path,
    )
    with TestClient(create_app(settings, model_builder=lambda s, endpoint=None: FakeModel())) as client:
        yield client


def test_update_endpoints_require_an_admin_session(update_client):
    assert update_client.get("/api/demo-admin/update").status_code == 401
    assert update_client.post("/api/demo-admin/update/install").status_code == 401


def test_customer_session_cannot_reach_the_update_route(update_client):
    headers = login(update_client)
    assert update_client.get("/api/demo-admin/update", headers=headers).status_code == 401


def test_install_requests_through_the_api(update_client, tmp_path):
    headers = login(update_client, admin=True)
    response = update_client.get("/api/demo-admin/update", headers=headers)
    assert response.status_code == 200, response.text
    assert response.json()["update"]["current"] == "v0.6.3"

    response = update_client.post("/api/demo-admin/update/install", headers=headers)
    assert response.status_code == 200, response.text
    assert json.loads((tmp_path / "request.json").read_text())["by"] == "presenter"


def test_install_conflicts_when_the_host_side_is_absent(update_client, tmp_path):
    (tmp_path / "state.json").unlink()
    headers = login(update_client, admin=True)
    response = update_client.post("/api/demo-admin/update/install", headers=headers)
    assert response.status_code == 409, response.text
    assert "not installed" in response.json()["error"]["message"]


# --- Removing configuration -------------------------------------------------------------------
# Both of these matter before a snapshot: an image taken with credentials still live ships them to
# every clone made from it.


def endpoint_payload(name, key):
    return {"name": name, "provider": "openai", "model": "gpt-4o", "base_url": "", "api_key": key}


def test_deleting_the_last_endpoint_stops_it_being_used(client, settings):
    headers = login(client, admin=True)
    baseline = settings.openai_api_key.get_secret_value()

    created = client.put("/api/demo-admin/endpoints", headers=headers,
                         json=endpoint_payload("Sharon AI", "sk-sharon-secret"))
    assert created.status_code == 200, created.text
    identifier = created.json()["endpoints"][-1]["id"]
    assert settings.openai_api_key.get_secret_value() == "sk-sharon-secret"

    removed = client.delete(f"/api/demo-admin/endpoints/{identifier}", headers=headers)
    assert removed.status_code == 200, removed.text
    assert removed.json()["endpoints"] == []
    # The endpoint is gone from the list; its credential must be gone from the live settings too.
    assert settings.openai_api_key.get_secret_value() == baseline
    assert settings.openai_api_key.get_secret_value() != "sk-sharon-secret"


def test_switching_endpoints_does_not_inherit_the_previous_key(client, settings):
    headers = login(client, admin=True)
    first = client.put("/api/demo-admin/endpoints", headers=headers,
                       json=endpoint_payload("With key", "sk-first-secret"))
    assert first.status_code == 200, first.text
    second = client.put("/api/demo-admin/endpoints", headers=headers,
                        json=endpoint_payload("No key", ""))
    assert second.status_code == 200, second.text
    identifier = second.json()["endpoints"][-1]["id"]

    activated = client.post("/api/demo-admin/endpoints/active", headers=headers,
                            json={"id": identifier})
    assert activated.status_code == 200, activated.text
    assert settings.openai_api_key.get_secret_value() != "sk-first-secret", (
        "an endpoint saved without a key must not inherit the previous endpoint's key"
    )


def test_a_non_secret_connection_field_can_be_cleared(client, settings):
    headers = login(client, admin=True)
    saved = client.put("/api/demo-admin/galileo/connection", headers=headers,
                       json={"galileo_project": "my-project", "galileo_log_stream": "my-stream"})
    assert saved.status_code == 200, saved.text
    assert saved.json()["connection"]["galileo_project"] == "my-project"

    # A blank value is deliberately ignored, so clearing has to be explicit.
    blanked = client.put("/api/demo-admin/galileo/connection", headers=headers,
                         json={"galileo_project": ""})
    assert blanked.json()["connection"]["galileo_project"] == "my-project"

    cleared = client.put("/api/demo-admin/galileo/connection", headers=headers,
                         json={"galileo_project": "", "clear": ["galileo_project"]})
    assert cleared.status_code == 200, cleared.text
    assert cleared.json()["connection"]["galileo_project"] == ""
    assert cleared.json()["connection"]["galileo_log_stream"] == "my-stream", "clear must be surgical"


def test_origin_rejection_names_both_addresses(client, settings):
    """The bare message was undiagnosable: it fires for a stale container and for the wrong URL."""
    response = client.post(
        "/api/demo-admin/login",
        headers={"Origin": "https://not-the-configured-host.example"},
        json={"account_number": "12345678", "password": "wrong"},
    )
    assert response.status_code == 403
    message = response.json()["error"]["message"]
    assert settings.app_origin in message, "must say which origin this deployment expects"
    assert "not-the-configured-host.example" in message, "must say which origin was sent"


def test_the_proxy_exports_every_method_the_portal_uses():
    """Next answers 405 for a method with no export, without reaching the handler.

    A missing DELETE made every Remove button in the portal inert while the code behind them read
    as correct, and nothing in either test suite noticed. This is a cheap static guard: it reads the
    methods the frontend actually asks for and checks the proxy forwards them.
    """
    root = Path(__file__).resolve().parents[2]
    route = (root / "frontend/app/api/[...path]/route.ts").read_text()
    exported = set(re.findall(r"proxy as ([A-Z]+)", route))

    used = {"GET", "POST"}  # api() is GET; mutate() defaults to POST
    for source in (root / "frontend").rglob("*.tsx"):
        # The fourth argument of mutate(path, body, admin, method).
        used |= {m.upper() for m in re.findall(r"mutate\((?:[^()]|\([^()]*\))*?,\s*\"([A-Z]+)\"\s*\)", source.read_text())}

    missing = used - exported
    assert not missing, f"the proxy does not forward {sorted(missing)}; Next will answer 405"


def test_the_agent_name_is_not_settable_from_the_portal(client, settings):
    """Deliberately absent, and the reasoning belongs next to the test.

    The application registers its own agent and derives the name, so a participant has nothing to
    set. A wrong value produces a 404, which the app answers by failing closed -- the transfer is
    refused, and from the chat that is indistinguishable from a guardrail that worked. It stays an
    environment override for whoever deploys the box.
    """
    from app.main import GalileoConnection
    from app.observability.galileo import Telemetry

    assert "agent_control_agent_name" not in Telemetry.CONNECTION_FIELDS
    assert "agent_control_agent_name" not in GalileoConnection.model_fields

    headers = login(client, admin=True)
    rejected = client.put(
        "/api/demo-admin/galileo/connection",
        headers=headers,
        json={"agent_control_agent_name": "my-bank-agent-lp"},
    )
    assert rejected.status_code == 422, "the portal must not be able to set it"

    view = client.get("/api/demo-admin/status", headers=headers).json()["connection"]
    assert "agent_control_agent_name" not in view, "nor report it as settable"

    # The deployment-level override still works.
    settings.agent_control_agent_name = "my-agent-liam"
    assert settings.resolved_agent_name == "my-agent-liam"


def test_a_stale_saved_agent_name_is_inert(settings, tmp_path):
    """A box configured before the field was removed must not keep overriding the derivation."""
    import json as _json

    from app.observability.galileo import Telemetry

    settings.data_dir = tmp_path
    (tmp_path / "galileo-settings.json").write_text(
        _json.dumps({
            "enabled": False,
            "connection": {
                "agent_control_agent_name": "my-bank-agent",
                "galileo_project": "splunky-lp",
            },
        })
    )
    telemetry = Telemetry(settings)
    assert telemetry.settings.agent_control_agent_name == "", "the stale value must not be applied"
    assert telemetry.settings.galileo_project == "splunky-lp", "other saved fields still apply"



def test_the_three_connection_field_lists_agree():
    """A connection field lives in three places, and all three have to know about it.

    CONNECTION_FIELDS drives persistence and apply, GalileoConnection validates the request, and
    connection() is what the portal's form seeds itself from. A field missing from the second is
    rejected with 422; missing from the third it saves correctly and shows as empty.
    """
    from app.main import GalileoConnection
    from app.observability.galileo import Telemetry

    schema = set(GalileoConnection.model_fields) - {"clear"}
    missing = set(Telemetry.CONNECTION_FIELDS) - schema
    assert not missing, f"GalileoConnection cannot accept {sorted(missing)}; requests get 422"

    extra = schema - set(Telemetry.CONNECTION_FIELDS)
    assert not extra, f"{sorted(extra)} is accepted by the schema but never persisted"


# --- Agent registration -------------------------------------------------------------------------
# The evaluation route answers 404 for an agent it has never been told about, and the app then fails
# closed: the transfer is refused and it reads as a guardrail that worked. Registration is what makes
# the name real, and nothing in this application called it until now.


def test_the_agent_name_is_derived_from_project_and_stream(settings):
    settings.agent_control_agent_name = ""
    settings.galileo_project = "splunky-lp"
    settings.galileo_log_stream = "my-bank-agent"
    assert settings.resolved_agent_name == "splunky-lp-my-bank-agent"


def test_an_explicit_name_overrides_the_derivation(settings):
    settings.agent_control_agent_name = "my-agent-liam"
    settings.galileo_project = "splunky-lp"
    assert settings.resolved_agent_name == "my-agent-liam"


def test_a_derived_name_is_always_acceptable_to_the_gateway(settings):
    """Lowercase, [a-z0-9:_-], at least ten characters, or registration refuses it."""
    import re as _re

    for project, stream in [
        ("Splunky Finance", "My Bank Agent"),   # spaces and capitals
        ("a", "b"),                             # far too short
        ("", ""),                               # nothing configured yet
        ("proj.with.dots", "stream/slash"),     # punctuation the gateway rejects
        ("--leading", "trailing--"),            # separators at the edges
    ]:
        settings.agent_control_agent_name = ""
        settings.galileo_project, settings.galileo_log_stream = project, stream
        name = settings.resolved_agent_name
        assert len(name) >= 10, f"{project}/{stream} produced {name!r}"
        assert _re.fullmatch(r"[a-z0-9:_-]+", name), f"{project}/{stream} produced {name!r}"


async def test_registration_is_skipped_without_a_gateway_and_says_so(settings):
    from app.observability.galileo import Telemetry

    telemetry = Telemetry(settings)
    telemetry.target = {"stream_id": "stream-1"}
    settings.agent_control_url = ""
    state = await telemetry.declare_agent()
    assert state["state"] == "skipped"
    assert "Agent Control URL" in state["reason"]
    # The name is still settled, so the evaluation request never sends a blank one.
    assert state["name"] == settings.resolved_agent_name


async def test_registration_carries_the_stream_and_is_not_repeated(settings, monkeypatch):
    import agent_control

    from app.observability.galileo import Telemetry

    calls = []
    monkeypatch.setattr(agent_control, "init", lambda **kwargs: calls.append(kwargs))

    settings.agent_control_url = "https://gateway.test/agent-control"
    settings.galileo_api_key = SecretStr("test-key")
    settings.galileo_project, settings.galileo_log_stream = "splunky-lp", "my-bank-agent"
    telemetry = Telemetry(settings)
    telemetry.target = {"stream_id": "stream-1"}

    state = await telemetry.declare_agent()
    assert state["state"] == "registered", state
    assert len(calls) == 1
    assert calls[0]["agent_name"] == "splunky-lp-my-bank-agent"
    assert calls[0]["target_type"] == "log_stream"
    assert calls[0]["target_id"] == "stream-1", "the target is what scopes the controls"

    # Nothing changed, so no second registration.
    await telemetry.declare_agent()
    assert len(calls) == 1

    # A new stream is a new target, and the SDK fixes target context per session.
    telemetry.target = {"stream_id": "stream-2"}
    await telemetry.declare_agent()
    assert len(calls) == 2
    assert calls[1]["target_id"] == "stream-2"


async def test_a_failed_registration_is_reported_not_raised(settings, monkeypatch):
    import agent_control

    from app.observability.galileo import Telemetry

    def explode(**kwargs):
        raise RuntimeError("gateway refused")

    monkeypatch.setattr(agent_control, "init", explode)
    settings.agent_control_url = "https://gateway.test/agent-control"
    settings.galileo_api_key = SecretStr("test-key")
    telemetry = Telemetry(settings)
    telemetry.target = {"stream_id": "stream-1"}

    state = await telemetry.declare_agent()
    assert state["state"] == "failed"
    assert state["error"] == "RuntimeError"
    assert "gateway refused" not in str(state), "SDK errors can carry credential headers"
