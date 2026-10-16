import pytest
from pydantic import ValidationError

from app.config import Settings


def configure(settings, **changes):
    return Settings(_env_file=None, **{**settings.model_dump(), **changes})


def test_private_lan_http_requires_explicit_opt_in(settings):
    with pytest.raises(ValidationError):
        configure(settings, app_origin="http://192.168.56.10:3000")
    configured = configure(settings, app_origin="http://192.168.56.10:3000", allow_private_lan_http=True)
    assert configured.app_origin == "http://192.168.56.10:3000"


@pytest.mark.parametrize(
    "origin", ["http://8.8.8.8:3000", "http://bank.example:3000", "http://169.254.1.1:3000"]
)
def test_lan_opt_in_does_not_allow_other_remote_hosts(settings, origin):
    with pytest.raises(ValidationError):
        configure(settings, app_origin=origin, allow_private_lan_http=True)


def test_scheme_and_cookies_must_match(settings):
    with pytest.raises(ValidationError):
        configure(settings, app_origin="https://192.168.56.10:3000")
    with pytest.raises(ValidationError):
        configure(
            settings,
            app_origin="http://192.168.56.10:3000",
            allow_private_lan_http=True,
            session_cookie_secure=True,
        )
    assert configure(settings, app_origin="https://bank.example", session_cookie_secure=True)


def test_customer_login_at_configured_lan_origin(settings):
    from fastapi.testclient import TestClient

    from app.main import create_app

    configured = configure(settings, app_origin="http://192.168.56.10:3000", allow_private_lan_http=True)
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


# A lab platform names each instance when it boots (i-0abc123.splunk.show), so the image cannot
# carry one address. A wildcard origin is what lets every clone be identical. The widening is
# deliberately narrow, because this check is a CSRF defence.
WILDCARD = "https://*.splunk.show"


@pytest.mark.parametrize(
    "origin",
    [
        "https://i-09c3ad076563d756c.splunk.show",
        "https://i-0d6a36626a11c4307.splunk.show",
        "https://i-0d6a36626a11c4307.splunk.show/",
    ],
)
def test_a_wildcard_origin_accepts_one_label_under_the_domain(settings, origin):
    configured = configure(settings, app_origin=WILDCARD, session_cookie_secure=True)
    assert configured.origin_allows(origin)


@pytest.mark.parametrize(
    "origin",
    [
        # The bare domain is not an instance.
        "https://splunk.show",
        # Deeper names are not what the certificate or the platform hands out.
        "https://a.b.splunk.show",
        # A suffix that merely ends with the domain, which is the attack this must refuse.
        "https://i-09c3ad076563d756c.splunk.show.evil.example",
        "https://evil.example",
        # Scheme and port are not part of the wildcard.
        "http://i-09c3ad076563d756c.splunk.show",
        "https://i-09c3ad076563d756c.splunk.show:8443",
        # What a browser sends for a sandboxed or opaque origin, and what it sends for none.
        "null",
        "",
    ],
)
def test_a_wildcard_origin_refuses_everything_else(settings, origin):
    configured = configure(settings, app_origin=WILDCARD, session_cookie_secure=True)
    assert not configured.origin_allows(origin)


def test_a_named_origin_stays_an_exact_match(settings):
    """The wildcard is opt-in. A deployment that names its address keeps string equality."""
    configured = configure(
        settings, app_origin="https://a.splunk.show", session_cookie_secure=True
    )
    assert configured.origin_allows("https://a.splunk.show")
    assert not configured.origin_allows("https://b.splunk.show")


@pytest.mark.parametrize(
    "origin",
    [
        # A wildcard over a public suffix would accept most of the internet.
        "https://*.show",
        "https://*",
        # Only the leftmost label may be a wildcard.
        "https://a.*.splunk.show",
        "https://*.*.splunk.show",
    ],
)
def test_an_over_broad_wildcard_is_refused_at_startup(settings, origin):
    with pytest.raises(ValidationError):
        configure(settings, app_origin=origin, session_cookie_secure=True)


def test_a_wildcard_origin_requires_https(settings):
    with pytest.raises(ValidationError):
        configure(settings, app_origin="http://*.splunk.show", allow_private_lan_http=True)


def test_login_accepts_any_instance_name_under_a_wildcard_origin(settings):
    """End to end, because the Origin check runs before authentication: a rejected origin is 403
    with the expected address named, an accepted one reaches the credential check."""
    from fastapi.testclient import TestClient

    from app.main import create_app

    configured = configure(settings, app_origin=WILDCARD, session_cookie_secure=True)
    payload = {
        "account_number": configured.demo_account_number,
        "password": configured.demo_password.get_secret_value(),
    }
    with TestClient(create_app(configured)) as client:
        for host in ("i-09c3ad076563d756c.splunk.show", "i-0d6a36626a11c4307.splunk.show"):
            response = client.post(
                "/api/auth/login", json=payload, headers={"Origin": f"https://{host}"}
            )
            assert response.status_code == 200, host
            client.cookies.clear()
        refused = client.post(
            "/api/auth/login", json=payload, headers={"Origin": "https://evil.example"}
        )
        assert refused.status_code == 403
        assert "*.splunk.show" in refused.json()["error"]["message"]


def test_the_origin_probe_payload_still_matches_the_login_schema():
    """scripts/serve_any_host.py proves the Origin check by POSTing to the login endpoint and
    reading 401 against 403. FastAPI validates the body before the endpoint runs, so a payload the
    schema rejects answers 422 either way and the check reports success while proving nothing. That
    happened once, with a field named customer_number. This pins the two together."""
    import json
    import re
    from pathlib import Path

    from app.schemas import Login

    source = (Path(__file__).resolve().parents[2] / "scripts" / "serve_any_host.py").read_text()
    bodies = re.findall(r"\"-d\", '(\{.*?\})'", source)
    assert bodies, "the probe no longer posts a body"
    for body in bodies:
        Login(**json.loads(body))
    assert '"401": "origin accepted"' in source
    assert '"403": "ORIGIN REJECTED"' in source


def test_a_rejected_origin_outranks_bad_credentials(settings):
    """Which is what makes 401 a pass and 403 a failure in that probe: the origin is checked
    before the password, so a wrong password reaching 401 means the origin was accepted."""
    from fastapi.testclient import TestClient

    from app.main import create_app

    configured = configure(settings, app_origin=WILDCARD, session_cookie_secure=True)
    wrong = {"account_number": "00000000", "password": "not-the-password"}
    with TestClient(create_app(configured)) as client:
        accepted = client.post(
            "/api/auth/login", json=wrong, headers={"Origin": "https://i-probe1.splunk.show"}
        )
        refused = client.post(
            "/api/auth/login", json=wrong, headers={"Origin": "https://evil.example"}
        )
    assert accepted.status_code == 401
    assert refused.status_code == 403
