"""The update check, and the boundary that keeps the container from doing the update itself."""

import asyncio
import json
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

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
