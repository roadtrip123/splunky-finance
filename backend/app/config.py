import re
from datetime import date
from ipaddress import ip_address, ip_network
from pathlib import Path
from typing import Literal
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

from pydantic import SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# What the Agent Control gateway accepts as an agent name: lowercase letters, digits, ":", "_" or
# "-", and at least ten characters. Anything else is rejected on registration.
AGENT_NAME_DISALLOWED = re.compile(r"[^a-z0-9:_-]+")
AGENT_NAME_MIN = 10
AGENT_NAME_FALLBACK = "splunky-finance-agent"

PRIVATE_LAN_NETWORKS = tuple(ip_network(x) for x in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16"))


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file="../.env", extra="ignore", case_sensitive=False)
    llm_provider: Literal["openai", "anthropic", "ollama"] = "openai"
    openai_api_key: SecretStr = SecretStr("")
    openai_model: str = "gpt-4o-mini-2024-07-18"
    # Any OpenAI-compatible endpoint; blank uses OpenAI itself.
    openai_base_url: str = ""
    anthropic_api_key: SecretStr = SecretStr("")
    anthropic_model: str = "claude-haiku-4-5-20251001"
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "gemma4:e2b"
    llm_temperature: float = 0
    llm_timeout_seconds: int = 60
    llm_max_tool_calls: int = 8
    llm_max_model_calls: int = 6
    llm_max_output_tokens: int = 2000
    galileo_enabled: bool = True
    galileo_api_key: SecretStr = SecretStr("")
    # Blank, deliberately. A default here is pre-filled into every deployment made from an image,
    # and a participant who leaves it points at somebody else's project -- which they probably
    # cannot read, producing a failure that looks like a broken box. The stream keeps its default
    # because the lab has everyone create one by that name.
    galileo_project: str = ""
    galileo_log_stream: str = "my-bank-agent"
    galileo_console_url: str = ""
    galileo_api_url: str = ""
    agent_control_url: str = ""
    # Blank by default: the application registers its own agent, deriving the name from the
    # project and stream. Set this only to point at a specific existing agent.
    agent_control_agent_name: str = ""
    agent_control_api_key_header: str = "Galileo-API-Key"
    # Blank means the SDK default, which is a Bearer token on Authorization -- what the Galileo
    # gateway requires. Splunk AO Observability Cloud needs a dedicated header instead, because a
    # gateway there injects its own Authorization and would clobber the runtime token. Setting the
    # Splunk value for Galileo sends the JWT off Authorization entirely and the route answers
    # "Missing Authorization header" with a 401.
    agent_control_runtime_token_header: str = ""
    # How the runtime evaluation call authenticates. "jwt" exchanges the API key for a short-lived
    # token, which is what Galileo's gateway expects; a tenant that has not enabled the exchange
    # rejects it with 401 while the management API accepts the same key. Settable so that can be
    # tried without a code change.
    agent_control_runtime_auth_mode: Literal["jwt", "api_key", "auto", "none"] = "jwt"
    galileo_protection_enabled: bool = False
    # Which observability SDK is active. One at a time: two backends would leave Agent Control
    # without an adjudicator, and two tenants disagreeing on one tool call has no good answer.
    observability_backend: str = "galileo"
    # Splunk AO, standalone deployment. Mirrors the Galileo fields above.
    splunk_ao_api_key: SecretStr = SecretStr("")
    splunk_ao_console_url: str = ""
    splunk_ao_api_url: str = ""
    # Splunk AO, Observability Cloud. The SDK derives console, API and OTLP ingest from the realm.
    splunk_ao_realm: str = ""
    splunk_ao_o11y_token: SecretStr = SecretStr("")
    splunk_ao_o11y_api_token: SecretStr = SecretStr("")
    # Agent Control lives behind each backend's own gateway, so the URL cannot be shared: a
    # Galileo URL left in place sends a Splunk token to the Galileo gateway and 401s.
    splunk_ao_agent_control_url: str = ""
    demo_seed: int = 42
    demo_reference_date: date = date(2026, 9, 15)
    demo_timezone: str = "Australia/Brisbane"
    demo_account_number: str = "12345678"
    demo_password: SecretStr
    demo_admin_password: SecretStr
    session_secret: SecretStr
    session_cookie_secure: bool = False
    allow_private_lan_http: bool = False
    # "workshop" hides presenter-only controls that confuse a solo lab participant.
    demo_mode: Literal["presenter", "workshop"] = "presenter"
    # "Set up my project" creates the judges, enables the metrics and binds the controls in one
    # click. Hidden unless asked for: it writes to whatever tenant is connected, and in a lab it
    # would skip the exercise. Set DEMO_SETUP_BUTTON=true to show it.
    demo_setup_button: bool = False
    app_origin: str = "http://localhost:3000"
    # Shared with the host, which performs the update; the container only writes a request into it.
    # See backend/app/update.py for why the container is not given Docker instead.
    update_state_dir: Path = Path("/app/update")
    update_repo: str = "roadtrip123/splunky-finance"
    data_dir: Path = Path("../runtime")
    policy_dir: Path = Path("../data/policies")

    @model_validator(mode="after")
    def validate_configuration(self):
        for name in ("demo_password", "demo_admin_password", "session_secret"):
            value = getattr(self, name).get_secret_value()
            minimum = 32 if name == "session_secret" else 12
            if len(value) < minimum or any(x in value.lower() for x in ("replace_with", "change-this")):
                raise ValueError(
                    f"{name.upper()} must be a non-placeholder secret (minimum {minimum} characters)"
                )
        if self.demo_password == self.demo_admin_password:
            raise ValueError("Customer and presenter passwords must differ")
        model = self.model_name
        if not model or "REPLACE" in model.upper():
            raise ValueError("Selected provider model must be configured")
        if self.llm_provider == "ollama" and ("cloud" in model or "ollama.com" in self.ollama_base_url):
            raise ValueError("Ollama mode requires a local model and local runtime")
        if not 1 <= self.llm_timeout_seconds <= 300:
            raise ValueError("LLM timeout must be 1–300 seconds")
        if not 1 <= self.llm_max_tool_calls <= 16 or not 1 <= self.llm_max_model_calls <= 10:
            raise ValueError("Invalid agent execution limits")
        if not 128 <= self.llm_max_output_tokens <= 4000:
            raise ValueError("Output limit must be 128–4000 tokens")
        origin = urlparse(self.app_origin)
        if origin.scheme not in ("http", "https") or not origin.hostname or origin.path not in ("", "/"):
            raise ValueError("APP_ORIGIN must be an HTTP(S) origin")
        if origin.username or origin.password or origin.query or origin.fragment:
            raise ValueError("APP_ORIGIN must not include credentials, query, or fragment")
        local = origin.hostname in ("localhost", "127.0.0.1", "::1")
        private_lan = False
        try:
            address = ip_address(origin.hostname)
            private_lan = address.version == 4 and any(address in network for network in PRIVATE_LAN_NETWORKS)
        except ValueError:
            pass
        if origin.scheme == "https" and not self.session_cookie_secure:
            raise ValueError("HTTPS requires secure session cookies")
        if origin.scheme == "http" and self.session_cookie_secure:
            raise ValueError("HTTP cannot use secure session cookies; use HTTPS")
        if not local and origin.scheme == "http" and not (self.allow_private_lan_http and private_lan):
            raise ValueError("Remote exposure requires HTTPS or explicit private LAN HTTP opt-in")
        ZoneInfo(self.demo_timezone)
        if self.galileo_protection_enabled and not self.galileo_enabled:
            raise ValueError("Protection requires Galileo")
        return self

    @property
    def resolved_agent_name(self):
        """The agent name to register and to evaluate under.

        `agent_control_agent_name` is an override. Blank, the name is derived from the project and
        stream, which is what distinguishes one participant from another: the lab has everyone name
        their stream the same and their project after themselves. Deriving it is what makes the agent
        a non-step -- the application registers the name it then uses, so there is nothing to create
        in advance and nothing to type.

        Normalised to what the gateway accepts, because a name it rejects is refused at registration
        and the resulting 404 is indistinguishable from a guardrail that worked.
        """
        candidate = (self.agent_control_agent_name or "").strip()
        if not candidate:
            candidate = f"{self.galileo_project}-{self.galileo_log_stream}"
        cleaned = AGENT_NAME_DISALLOWED.sub("-", candidate.lower()).strip("-")
        return cleaned if len(cleaned) >= AGENT_NAME_MIN else AGENT_NAME_FALLBACK

    @property
    def model_name(self):
        return getattr(self, f"{self.llm_provider}_model")

    @property
    def provider_configured(self):
        return self.llm_provider == "ollama" or bool(
            getattr(self, f"{self.llm_provider}_api_key").get_secret_value()
        )
