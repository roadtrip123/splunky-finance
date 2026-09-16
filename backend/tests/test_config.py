import pytest
from pydantic import ValidationError

from app.config import Settings


def configure(settings, **changes):
    return Settings(_env_file=None, **{**settings.model_dump(), **changes})


def test_private_lan_http_requires_explicit_opt_in(settings):
    with pytest.raises(ValidationError):
        configure(settings, app_origin="http://10.0.0.170:3000")
    configured = configure(settings, app_origin="http://10.0.0.170:3000", allow_private_lan_http=True)
    assert configured.app_origin == "http://10.0.0.170:3000"


@pytest.mark.parametrize(
    "origin", ["http://8.8.8.8:3000", "http://bank.example:3000", "http://169.254.1.1:3000"]
)
def test_lan_opt_in_does_not_allow_other_remote_hosts(settings, origin):
    with pytest.raises(ValidationError):
        configure(settings, app_origin=origin, allow_private_lan_http=True)


def test_scheme_and_cookies_must_match(settings):
    with pytest.raises(ValidationError):
        configure(settings, app_origin="https://10.0.0.170:3000")
    with pytest.raises(ValidationError):
        configure(
            settings,
            app_origin="http://10.0.0.170:3000",
            allow_private_lan_http=True,
            session_cookie_secure=True,
        )
    assert configure(settings, app_origin="https://bank.example", session_cookie_secure=True)


def test_customer_login_at_configured_lan_origin(settings):
    from fastapi.testclient import TestClient

    from app.main import create_app

    configured = configure(settings, app_origin="http://10.0.0.170:3000", allow_private_lan_http=True)
    with TestClient(create_app(configured)) as client:
        payload = {
            "account_number": configured.demo_account_number,
            "password": configured.demo_password.get_secret_value(),
        }
        assert (
            client.post(
                "/api/auth/login", json=payload, headers={"Origin": "http://localhost:3000"}
            ).status_code
            == 403
        )
        response = client.post("/api/auth/login", json=payload, headers={"Origin": configured.app_origin})
        assert response.status_code == 200
        assert "Secure" not in response.headers["set-cookie"]
        assert client.get("/api/accounts").status_code == 200
