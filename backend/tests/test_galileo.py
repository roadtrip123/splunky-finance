from types import SimpleNamespace

from conftest import login

from app.observability.galileo import Telemetry


def test_toggle_is_admin_only_csrf_checked_and_persistent(client, settings):
    route = "/api/demo-admin/galileo"
    payload = {"enabled": True, "expected_revision": 0}
    assert client.put(route, json=payload).status_code == 401
    customer = login(client)
    assert client.put(route, headers=customer, json=payload).status_code == 401
    admin = login(client, True)
    assert client.put(route, json=payload).status_code == 403
    response = client.put(route, headers=admin, json=payload)
    assert response.status_code == 200
    status = response.json()["galileo"]
    assert status["enabled"] and status["connection"] == "unconfigured"
    assert status["last_error"] == "Galileo API key missing"
    assert client.put(route, headers=admin, json=payload).status_code == 409
    restored = Telemetry(settings)
    assert restored.enabled
    response = client.put(route, headers=admin, json={"enabled": False, "expected_revision": 1})
    assert response.json()["galileo"]["connection"] == "disabled"
    assert not Telemetry(settings).enabled


async def test_connection_requires_successful_sdk_resolution(settings, monkeypatch):
    import galileo

    settings.galileo_enabled = True
    settings.galileo_api_key = settings.openai_api_key
    calls = []

    def connect(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(project_id="test-project", log_stream_id="test-stream")

    monkeypatch.setattr(galileo, "GalileoLogger", connect)
    monkeypatch.setattr(
        "galileo.log_streams.get_log_stream", lambda **kwargs: SimpleNamespace(id="test-stream")
    )
    telemetry = Telemetry(settings)
    status = await telemetry.check_connection()
    assert status["connection"] == "connected" and status["last_connected_at"]
    assert status["export"] == "not_attempted"
    await telemetry.check_connection()
    assert len(calls) == 1


async def test_connection_errors_do_not_expose_sdk_secrets(settings, monkeypatch):
    import galileo

    settings.galileo_enabled = True
    settings.galileo_api_key = settings.openai_api_key

    def fail(**kwargs):
        raise RuntimeError("credential-bearing SDK error fake-offline-key")

    monkeypatch.setattr(galileo, "GalileoLogger", fail)
    status = await Telemetry(settings).check_connection()
    assert status["connection"] == "failed"
    assert "fake-offline-key" not in str(status)
    assert status["last_connected_at"] is None
