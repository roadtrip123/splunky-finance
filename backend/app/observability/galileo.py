import asyncio
import json
import os
import time
from contextlib import suppress
from pathlib import Path
from typing import ClassVar
from uuid import uuid4

from pydantic import SecretStr


class Telemetry:
    """One logger per turn: no shared current trace across concurrent customer requests."""

    def __init__(self, settings):
        self.settings = settings
        self.enabled = settings.galileo_enabled
        # Resolved by the connection check. Agent Control targets a stream by id, and on
        # Observability Cloud the logger exports over OTLP and never resolves one.
        self.target: dict = {}
        self.toggle_path = Path(settings.data_dir) / "galileo-settings.json"
        try:
            saved = json.loads(self.toggle_path.read_text())
            if type(saved.get("enabled")) is bool:
                self.enabled = saved["enabled"]
            # Saved connection details outrank the environment, so a workshop participant can
            # point their own instance at their own project without editing a file or restarting.
            self.apply_connection(saved.get("connection") or {})
            endpoints = self._load_endpoints(saved)
            chosen = next(
                (e for e in endpoints if e["id"] == saved.get("active_endpoint")),
                endpoints[0] if endpoints else None,
            )
            self.apply_endpoint(chosen)
        except (OSError, ValueError, TypeError, AttributeError):
            pass
        settings.galileo_enabled = self.enabled
        self.revision = 0
        self.connection_lock = asyncio.Lock()
        self.status = {
            "state": "unconfigured" if settings.galileo_enabled else "disabled",
            "enabled": self.enabled,
            "revision": self.revision,
            "connection": "not_checked" if self.enabled else "disabled",
            "last_checked_at": None,
            "last_connected_at": None,
            "project_id": None,
            "log_stream_id": None,
            "export": "not_attempted",
            "last_error": None,
        }
        self.pending = {}
        self.scorers = {}
        self.scorers_at = 0.0

    # Project and stream are shared: both backends call the same two things by different names,
    # and a participant who renames their project should not have to do it twice.
    CONNECTION_FIELDS = (
        "galileo_api_key",
        "galileo_project",
        "galileo_log_stream",
        "galileo_console_url",
        "galileo_api_url",
        "agent_control_url",
        "splunk_ao_api_key",
        "splunk_ao_console_url",
        "splunk_ao_api_url",
        "splunk_ao_realm",
        "splunk_ao_o11y_token",
        "splunk_ao_o11y_api_token",
        "splunk_ao_agent_control_url",
    )
    SECRET_FIELDS = (
        "galileo_api_key",
        "splunk_ao_api_key",
        "splunk_ao_o11y_token",
        "splunk_ao_o11y_api_token",
    )

    @property
    def backend(self):
        """The active observability SDK, resolved lazily and re-resolved when switched."""
        from app.observability.sdk import backend as resolve

        name = self.backend_name()
        if getattr(self, "_backend", None) is None or self._backend.name != name:
            self._backend = resolve(name)
        return self._backend

    def backend_label(self):
        from app.observability.sdk import DISPLAY_NAME

        return DISPLAY_NAME.get(self.backend_name(), self.backend_name())

    def backend_name(self):
        from app.observability.sdk import BACKENDS, GALILEO

        saved = self._saved().get("active_backend")
        if saved in BACKENDS:
            return saved
        configured = getattr(self.settings, "observability_backend", GALILEO)
        return configured if configured in BACKENDS else GALILEO

    def apply_connection(self, values):
        """Copy saved connection details onto settings, treating credentials as secrets."""
        for field in self.CONNECTION_FIELDS:
            value = values.get(field)
            if not isinstance(value, str) or not value:
                continue
            secret = field in self.SECRET_FIELDS
            setattr(self.settings, field, SecretStr(value) if secret else value)

    @staticmethod
    def mask(secret):
        """Enough of the key to recognise which one is loaded, never enough to use it."""
        if not secret:
            return ""
        return "\u2022" * 8 + secret[-4:] if len(secret) > 8 else "\u2022" * 8

    def connection(self):
        """Current connection details. The API key is only ever returned masked."""
        s = self.settings
        view = {
            "galileo_project": s.galileo_project,
            "galileo_log_stream": s.galileo_log_stream,
            "galileo_console_url": s.galileo_console_url,
            "galileo_api_url": s.galileo_api_url,
            "agent_control_url": s.agent_control_url,
            "splunk_ao_console_url": s.splunk_ao_console_url,
            "splunk_ao_api_url": s.splunk_ao_api_url,
            "splunk_ao_realm": s.splunk_ao_realm,
            "splunk_ao_agent_control_url": s.splunk_ao_agent_control_url,
        }
        # Every secret is reported the same way: whether it is set, and the last four characters.
        # No endpoint returns a key, on either backend.
        for field in self.SECRET_FIELDS:
            secret = getattr(s, field).get_secret_value()
            view[f"{field}_set"] = bool(secret)
            view[f"{field}_masked"] = self.mask(secret)
        return view

    def _saved(self):
        try:
            return json.loads(self.toggle_path.read_text()) or {}
        except (OSError, ValueError, TypeError, AttributeError):
            return {}

    def _persist(self, connection=None, endpoints=None, active_endpoint=None, active_backend=None):
        previous = self._saved()
        saved = {"enabled": self.enabled}
        connection = previous.get("connection") if connection is None else connection
        if endpoints is None:
            endpoints = self._load_endpoints(previous)
            active_endpoint = previous.get("active_endpoint")
        active_backend = previous.get("active_backend") if active_backend is None else active_backend
        if active_backend:
            saved["active_backend"] = active_backend
        if connection:
            saved["connection"] = connection
        if endpoints:
            saved["endpoints"] = endpoints
            saved["active_endpoint"] = active_endpoint or endpoints[0]["id"]
        self.toggle_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.toggle_path.with_suffix(".tmp")
        with temporary.open("w") as stream:
            json.dump(saved, stream)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, self.toggle_path)
        os.chmod(self.toggle_path, 0o600)

    def set_connection(self, values, clear=()):
        """Save connection details and apply them without a restart.

        A blank field is left unchanged, so a key survives an edit to the project name. That left
        no way to remove one: pasting the wrong token meant living with it. `clear` names fields
        to drop outright, which is the only way back from a bad credential.
        """
        current = dict(self._saved().get("connection") or {})
        for field in clear:
            if field in self.CONNECTION_FIELDS:
                current.pop(field, None)
                setattr(self.settings, field, SecretStr("") if field in self.SECRET_FIELDS else "")
        for field in self.CONNECTION_FIELDS:
            value = values.get(field)
            if isinstance(value, str) and value:
                current[field] = value
        self.apply_connection(current)
        self._persist(current)
        self.target = {}
        self.scorers, self.scorers_at = {}, 0.0
        self.revision += 1
        self.status.update(
            revision=self.revision,
            state="unconfigured",
            connection="not_checked",
            project_id=None,
            log_stream_id=None,
            last_checked_at=None,
            last_error=None,
        )

    # Endpoints persist in the same runtime file as the Galileo connection. Not telemetry, but
    # both are "settings a participant changes from the portal without a restart".
    MODEL_FIELDS: ClassVar[dict] = {
        "openai": ("openai_api_key", "openai_model", "openai_base_url"),
        "anthropic": ("anthropic_api_key", "anthropic_model", None),
        "ollama": (None, "ollama_model", "ollama_base_url"),
    }

    def _load_endpoints(self, saved):
        """Endpoint list, migrating the single-endpoint shape this replaced."""
        endpoints = saved.get("endpoints")
        if endpoints is None and saved.get("model"):
            legacy = saved["model"]
            provider = legacy.get("llm_provider", "openai")
            key_field, model_field, url_field = self.MODEL_FIELDS[provider]
            endpoints = [
                {
                    "id": uuid4().hex[:8],
                    "name": f"{provider} · {legacy.get(model_field, '')}".strip(" ·"),
                    "provider": provider,
                    "model": legacy.get(model_field, ""),
                    "base_url": legacy.get(url_field, "") if url_field else "",
                    "api_key": legacy.get(key_field, "") if key_field else "",
                }
            ]
        return list(endpoints or [])

    def apply_endpoint(self, endpoint):
        """Point settings at this endpoint so model_name and provider_configured follow it."""
        from pydantic import SecretStr

        if not endpoint:
            return
        provider = endpoint.get("provider")
        if provider not in self.MODEL_FIELDS:
            return
        key_field, model_field, url_field = self.MODEL_FIELDS[provider]
        self.settings.llm_provider = provider
        if endpoint.get("model"):
            setattr(self.settings, model_field, endpoint["model"])
        if url_field and endpoint.get("base_url"):
            setattr(self.settings, url_field, endpoint["base_url"])
        if key_field and endpoint.get("api_key"):
            setattr(self.settings, key_field, SecretStr(endpoint["api_key"]))

    def active_endpoint(self):
        """The endpoint a turn should call. Resolved once per turn and passed explicitly, so a
        switch part-way through cannot change the model under a running request."""
        saved = self._saved()
        endpoints = self._load_endpoints(saved)
        chosen = next((e for e in endpoints if e["id"] == saved.get("active_endpoint")), None)
        if chosen:
            return {
                "provider": chosen["provider"],
                "model": chosen["model"],
                "base_url": chosen.get("base_url", ""),
                "api_key": chosen.get("api_key", ""),
                "name": chosen.get("name", ""),
                "id": chosen["id"],
            }
        from app.llm import endpoint_from_settings

        spec = endpoint_from_settings(self.settings)
        return {**spec, "name": f"{spec['provider']} · {spec['model']}", "id": ""}

    def endpoints_view(self):
        """Saved endpoints for the portal. Keys are only ever returned masked."""
        saved = self._saved()
        endpoints = self._load_endpoints(saved)
        active = saved.get("active_endpoint") or (endpoints[0]["id"] if endpoints else "")
        return {
            "endpoints": [
                {
                    "id": e["id"],
                    "name": e.get("name", ""),
                    "provider": e.get("provider", ""),
                    "model": e.get("model", ""),
                    "base_url": e.get("base_url", ""),
                    "api_key_set": bool(e.get("api_key")),
                    "api_key_masked": self.mask(e.get("api_key", "")),
                    "active": e["id"] == active,
                }
                for e in endpoints
            ],
            "active_endpoint": active,
        }

    def save_endpoint(self, data):
        """Add an endpoint, or update one by id. A blank key keeps the stored one."""
        saved = self._saved()
        endpoints = self._load_endpoints(saved)
        identifier = data.get("id") or uuid4().hex[:8]
        existing = next((e for e in endpoints if e["id"] == identifier), None)
        entry = {
            "id": identifier,
            "name": data.get("name") or f"{data['provider']} · {data.get('model', '')}".strip(" ·"),
            "provider": data["provider"],
            "model": data.get("model", ""),
            "base_url": data.get("base_url", ""),
            "api_key": data.get("api_key") or (existing or {}).get("api_key", ""),
        }
        endpoints = [entry if e["id"] == identifier else e for e in endpoints]
        if not existing:
            endpoints.append(entry)
        active = saved.get("active_endpoint") or identifier
        self._persist(endpoints=endpoints, active_endpoint=active)
        self.apply_endpoint(next(e for e in endpoints if e["id"] == active))
        return identifier

    def delete_endpoint(self, identifier):
        saved = self._saved()
        endpoints = [e for e in self._load_endpoints(saved) if e["id"] != identifier]
        active = saved.get("active_endpoint")
        if active == identifier:
            active = endpoints[0]["id"] if endpoints else ""
        self._persist(endpoints=endpoints, active_endpoint=active)
        if active:
            self.apply_endpoint(next(e for e in endpoints if e["id"] == active))

    def set_active_endpoint(self, identifier):
        endpoints = self._load_endpoints(self._saved())
        chosen = next((e for e in endpoints if e["id"] == identifier), None)
        if not chosen:
            raise KeyError("Unknown endpoint")
        self._persist(endpoints=endpoints, active_endpoint=identifier)
        self.apply_endpoint(chosen)

    def set_active_backend(self, name):
        """Switch observability backend. One is active at a time.

        Cached scorer names belong to the previous tenant, so they go with it; without that the
        portal reports the old tenant's metrics against the new one. The revision bump is what
        the connected banking session watches, same as a connection change.
        """
        from app.observability.sdk import BACKENDS

        if name not in BACKENDS:
            raise ValueError(f"Unknown observability backend {name!r}")
        self._persist(active_backend=name)
        self._backend = None
        self.target = {}
        self.scorers, self.scorers_at = {}, 0.0
        self.revision += 1
        self.status.update(
            revision=self.revision,
            backend=name,
            state="unconfigured",
            connection="not_checked",
            project_id=None,
            log_stream_id=None,
            last_checked_at=None,
            last_error=None,
        )
        return self.backends_view()

    def backends_view(self):
        """What the portal shows: every backend, which is active, and whether it can authenticate."""
        from app.observability.sdk import BACKENDS, DISPLAY_NAME, STREAM_LABEL

        active = self.backend_name()
        return {
            "active": active,
            "backends": [
                {
                    "id": name,
                    "name": DISPLAY_NAME[name],
                    "stream_label": STREAM_LABEL[name],
                    "active": name == active,
                    "configured": self._credentials_for(name),
                    "mode": self.splunk_ao_mode() if name == "splunk_ao" else "",
                }
                for name in BACKENDS
            ],
        }

    def set_enabled(self, enabled):
        self.enabled = enabled
        self._persist()
        self.settings.galileo_enabled = enabled
        self.revision += 1
        self.status.update(
            enabled=enabled,
            revision=self.revision,
            state="unconfigured" if enabled else "disabled",
            connection="not_checked" if enabled else "disabled",
            last_error=None,
        )

    async def check_connection(self, force=False):
        async with self.connection_lock:
            if not self.enabled:
                self.status.update(state="disabled", connection="disabled")
                return dict(self.status)
            if (
                not force
                and self.status["last_checked_at"]
                and time.time() - self.status["last_checked_at"] < 30
            ):
                return dict(self.status)
            self.status["last_checked_at"] = time.time()
            if not self.settings.galileo_api_key.get_secret_value():
                self.status.update(
                    state="unconfigured",
                    connection="unconfigured",
                    last_error=f"{self.backend_label()} credentials missing",
                )
                return dict(self.status)
            self.status.update(state="checking", connection="checking", last_error=None)
            self.configure_environment()
            try:
                sdk = self.backend

                def connect():
                    # Resolve through the API rather than from the logger. On Observability Cloud
                    # the logger exports over OTLP and never resolves ids at all -- project and
                    # stream travel as resource attributes -- so `project_id is None` is normal
                    # there, not a failure. Reading it as one reported a correctly configured
                    # tenant as "project not found".
                    stream = sdk.get_stream(
                        name=self.settings.galileo_log_stream,
                        project_name=self.settings.galileo_project,
                    )
                    if stream is None:
                        raise ValueError("Configured stream unavailable")
                    return str(getattr(stream, "project_id", "") or ""), str(
                        getattr(stream, "id", "") or ""
                    )

                project_id, stream_id = await asyncio.wait_for(asyncio.to_thread(connect), 15)
                if not stream_id:
                    raise ValueError("Configured stream unavailable")
                # Agent Control targets a stream by id, and on OTLP the logger cannot supply one.
                self.target = {"project_id": project_id, "stream_id": stream_id}
                self.status.update(
                    state="connected",
                    connection="connected",
                    last_connected_at=time.time(),
                    project_id=project_id,
                    log_stream_id=stream_id,
                )
            except Exception as exc:  # noqa: BLE001 - sanitize credential-bearing SDK errors
                self.status.update(
                    state="failed", connection="failed", last_error=self._connection_error(exc)
                )
            return dict(self.status)

    # Every variable either SDK inspects. The inactive backend's are deleted rather than left
    # alone, because splunk_ao does not have its own namespace: SplunkAOConfig subclasses
    # GalileoConfig and bridges SPLUNK_AO_* into the GALILEO_* names, since galileo-core still
    # reads those. It only fills a gap, so an explicit GALILEO_* wins -- but configure Splunk AO
    # with Galileo unset and the Galileo SDK silently inherits Splunk AO's credentials. A
    # "Galileo" logger writing to Splunk AO is only noticeable by wondering why a tenant is empty.
    BACKEND_ENV_VARS: ClassVar[dict] = {
        "galileo": (
            "GALILEO_API_KEY", "GALILEO_CONSOLE_URL", "GALILEO_API_URL",
            "GALILEO_PROJECT", "GALILEO_LOG_STREAM",
        ),
        "splunk_ao": (
            "SPLUNK_AO_API_KEY", "SPLUNK_AO_CONSOLE_URL", "SPLUNK_AO_API_URL",
            "SPLUNK_AO_REALM", "SPLUNK_AO_O11Y_TOKEN", "SPLUNK_AO_O11Y_API_TOKEN",
            "SPLUNK_AO_PROJECT", "SPLUNK_AO_AGENT_STREAM",
        ),
    }

    def _backend_environment(self, name):
        """The variables one backend needs, with empty values dropped."""
        s = self.settings
        if name == "splunk_ao":
            values = {
                "SPLUNK_AO_API_KEY": s.splunk_ao_api_key.get_secret_value(),
                "SPLUNK_AO_CONSOLE_URL": s.splunk_ao_console_url,
                "SPLUNK_AO_API_URL": s.splunk_ao_api_url,
                "SPLUNK_AO_REALM": s.splunk_ao_realm,
                "SPLUNK_AO_O11Y_TOKEN": s.splunk_ao_o11y_token.get_secret_value(),
                "SPLUNK_AO_O11Y_API_TOKEN": s.splunk_ao_o11y_api_token.get_secret_value(),
                "SPLUNK_AO_PROJECT": s.galileo_project,
                "SPLUNK_AO_AGENT_STREAM": s.galileo_log_stream,
            }
        else:
            values = {
                "GALILEO_API_KEY": s.galileo_api_key.get_secret_value(),
                "GALILEO_CONSOLE_URL": s.galileo_console_url,
                "GALILEO_API_URL": s.galileo_api_url,
            }
        return {k: v for k, v in values.items() if v}

    def configure_environment(self):
        active = self.backend_name()
        for name, variables in self.BACKEND_ENV_VARS.items():
            if name == active:
                continue
            for variable in variables:
                os.environ.pop(variable, None)
        os.environ.update(self._backend_environment(active))
        self.apply_agent_control_defaults()

    def backend_credentials_present(self):
        """True when the active backend has enough to authenticate."""
        return self._credentials_for(self.backend_name())

    def _stream_word(self):
        from app.observability.sdk import STREAM_LABEL

        return STREAM_LABEL.get(self.backend_name(), "log stream")

    def _connection_error(self, exc):
        """A cause a presenter can act on, without echoing SDK error text.

        The generic message used to be the only signal, which made a rejected token and an
        unreachable host look identical. SDK text can carry URLs and credential headers, so only
        the status code is read out of it, never the message.
        """
        text = str(exc)
        label = self.backend_label()
        if "401" in text or "Authentication" in type(exc).__name__ or "Unauthorized" in text:
            if self.backend_name() == "splunk_ao" and self.splunk_ao_mode() == "o11y":
                return (
                    f"{label} rejected the credentials (401). API routes need an API token: an "
                    "ingest-only token is rejected here. Check the API token field, or give the "
                    "access token both INGEST and agent_observability_admin."
                )
            return f"{label} rejected the credentials (401). Check the API key has not expired."
        if "403" in text:
            return f"{label} accepted the credentials but refused the request (403). Check permissions."
        if "404" in text:
            return f"{label} could not find the project or stream (404). Create them in the console first."
        # A rejected token and a missing project are indistinguishable from here: with no
        # permission to list projects the SDK reports the named one as not found. Say both.
        if "not found" in text.lower():
            return (
                f"{label} could not find the project or {self._stream_word()}. Either it does not "
                "exist yet — create it in the console first — or the token cannot list it. On "
                "Observability Cloud an ingest-only token is rejected on API routes."
            )
        if "Project unavailable" in text or "stream unavailable" in text:
            return (
                f"{label} authenticated but the project or {self._stream_word()} was not found. "
                "Create them in the console first; the app cannot connect to a project that does "
                "not exist."
            )
        for marker in ("timed out", "Timeout", "Connection", "resolve"):
            if marker in text:
                return f"{label} could not be reached. Check the realm or console URL and the network."
        return f"{label} connection failed; check credentials, endpoint, and project permissions"

    def splunk_ao_mode(self):
        """Which Splunk AO deployment the saved credentials describe.

        The two are mutually exclusive and need different fields, a different Agent Control host
        and a different gateway header, so the mode is derived from what is set rather than asked
        for twice. O11y wins when both are present, matching the SDK's own precedence.
        """
        s = self.settings
        if s.splunk_ao_realm and (
            s.splunk_ao_o11y_token.get_secret_value() or s.splunk_ao_o11y_api_token.get_secret_value()
        ):
            return "o11y"
        if s.splunk_ao_api_key.get_secret_value() and s.splunk_ao_console_url:
            return "standalone"
        return ""

    # Agent Control sits behind the same gateway as each backend's API, so it authenticates with
    # that deployment's own credential on the header the gateway expects.
    AGENT_CONTROL_HEADERS: ClassVar[dict] = {
        "galileo": "Galileo-API-Key",
        "o11y": "X-SF-Token",
        "standalone": "Splunk-AO-API-Key",
    }

    def apply_agent_control_defaults(self):
        """Point Agent Control at the active backend's gateway.

        Left alone, a Splunk AO turn would send a Galileo header to a Splunk gateway and be
        rejected, with nothing in the message saying why.
        """
        s = self.settings
        if self.backend_name() != "splunk_ao":
            s.agent_control_api_key_header = self.AGENT_CONTROL_HEADERS["galileo"]
            return
        mode = self.splunk_ao_mode()
        s.agent_control_api_key_header = self.AGENT_CONTROL_HEADERS.get(mode or "standalone")
        # Each backend has its own gateway. Sharing one field meant a Splunk AO turn kept the
        # Galileo Agent Control URL and sent an X-SF-Token to the Galileo gateway.
        if s.splunk_ao_agent_control_url:
            s.agent_control_url = s.splunk_ao_agent_control_url
        elif mode == "o11y" and s.splunk_ao_realm:
            # Derive from the realm so the host always matches the credential's realm. A
            # mismatched host returns 401 from the runtime token exchange.
            s.agent_control_url = f"https://app.{s.splunk_ao_realm}.signalfx.com/ao/agent-control"

    def _credentials_for(self, name):
        if name != "splunk_ao":
            return bool(self.settings.galileo_api_key.get_secret_value())
        s = self.settings
        standalone = s.splunk_ao_api_key.get_secret_value() and s.splunk_ao_console_url
        o11y = s.splunk_ao_realm and (
            s.splunk_ao_o11y_token.get_secret_value() or s.splunk_ao_o11y_api_token.get_secret_value()
        )
        return bool(standalone or o11y)

    async def begin(self, prompt, metadata):
        if not self.enabled:
            return None
        if not self.backend_credentials_present():
            self.status.update(
                state="unconfigured", last_error=f"{self.backend_label()} credentials missing"
            )
            return None
        self.configure_environment()
        try:
            sdk = self.backend

            def initialize():
                logger = sdk.new_logger(
                    project=self.settings.galileo_project, stream=self.settings.galileo_log_stream
                )
                logger.start_session(name="My Bank Agent", external_id=metadata["conversation_id"])
                return logger

            logger = await asyncio.wait_for(asyncio.to_thread(initialize), timeout=15)
            # The SDK parent is a ContextVar: a worker thread's value does not flow
            # back to this request. Start the root here so agent callback tasks inherit it.
            label = metadata.get("endpoint") or metadata.get("model") or ""
            trace = logger.start_trace(
                input=prompt,
                name=f"bank-chat-turn · {label}" if label else "bank-chat-turn",
                metadata=metadata,
                external_id=metadata["run_id"],
            )
            self.status.update(
                state="connected",
                connection="connected",
                last_error=None,
                last_checked_at=time.time(),
                last_connected_at=time.time(),
                project_id=str(logger.project_id),
                log_stream_id=str(logger.log_stream_id),
            )
            self.pending[id(logger)] = logger
            return {
                "logger": logger,
                "trace_id": str(trace.id),
                "started": time.perf_counter_ns(),
                "callback": sdk.callback(logger),
                "backend": sdk.name,
            }
        except Exception:  # noqa: BLE001 - isolate SDK failures without exposing credential-bearing errors
            # SDK exception text can include URLs or credential headers; never expose it.
            self.status.update(
                state="failed",
                connection="failed",
                last_error="Galileo initialization failed; check server configuration",
            )
            return None

    def event(self, turn, name, input_value, output_value, **metadata):
        if not turn:
            return
        try:
            logger = turn["logger"]
            logger.add_workflow_span(
                name=name,
                input=json.dumps(input_value, default=str),
                output=json.dumps(output_value, default=str),
                metadata=metadata,
            )
            logger.conclude()
        except Exception:  # noqa: BLE001 - isolate SDK failures without exposing credential-bearing errors
            self.status["last_error"] = "A telemetry event could not be recorded"

    async def setup_project(self):
        """Enable the metrics on this log stream and bind the transfer control.

        The judges and the control definition are tenant-wide and already exist, but metric
        enablement and control binding are both per log stream, so every participant runs this
        against their own project.
        """
        self.configure_environment()

        def apply():
            from app.observability.setup_definitions import BUILTIN_METRICS, JUDGES

            s, sdk = self.settings, self.backend
            available = {str(getattr(row, "name", "")) for row in sdk.Scorers().list()}
            wanted = [m for m in list(JUDGES) + BUILTIN_METRICS if m in available]
            missing = [m for m in list(JUDGES) + BUILTIN_METRICS if m not in available]
            sdk.enable_metrics(
                project_name=s.galileo_project, stream_name=s.galileo_log_stream, metrics=wanted
            )
            logger = sdk.new_logger(project=s.galileo_project, stream=s.galileo_log_stream)
            return wanted, missing, str(sdk.stream_id(logger))

        metrics, missing, log_stream_id = await asyncio.wait_for(asyncio.to_thread(apply), 60)
        controls = await self._bind_controls(log_stream_id)
        return {
            "metrics_enabled": metrics,
            "metrics_unavailable": missing,
            "controls": controls,
            "log_stream_id": log_stream_id,
        }

    async def _bind_controls(self, log_stream_id):
        """Bind the transfer control to this log stream, reusing the tenant-wide definition."""
        s = self.settings
        if not s.agent_control_url:
            return {"state": "skipped", "reason": "No Agent Control URL configured"}
        try:
            from agent_control import AgentControlClient
            from agent_control.controls import clone_and_bind_control, create_control, list_controls

            from app.observability.setup_definitions import CONTROLS

            bound = []
            async with AgentControlClient(
                base_url=s.agent_control_url,
                timeout=30,
                api_key=s.galileo_api_key.get_secret_value(),
                api_key_header=s.agent_control_api_key_header,
                runtime_auth_mode="jwt",
                runtime_token_header=s.agent_control_runtime_token_header,
            ) as client:
                for name, definition in CONTROLS.items():
                    existing = (await list_controls(client, name=name, limit=25)).get("controls") or []
                    # clone_and_bind_control clones as well as binds, so pressing this twice
                    # would leave another copy behind. Bind the original once.
                    original = next((c for c in existing if not c.get("cloned_from_control_id")), None)
                    if any(c.get("cloned_from_control_id") for c in existing):
                        bound.append(f"{name} (already bound)")
                        continue
                    identifier = (
                        (original.get("control_id") or original.get("id"))
                        if original
                        else (await create_control(client, name=name, data=definition))["control_id"]
                    )
                    await clone_and_bind_control(
                        client,
                        control_id=identifier,
                        target_type="log_stream",
                        target_id=log_stream_id,
                        enabled=True,
                    )
                    bound.append(name)
            return {"state": "bound", "controls": bound}
        except Exception:  # noqa: BLE001 - sanitize credential-bearing SDK errors
            return {"state": "failed", "reason": "Control binding failed; check the Agent Control URL"}

    async def scorer_names(self):
        """Map scorer id to name.

        Trace metrics are keyed by scorer id, so an unresolved fetch shows the presenter a wall of
        identifiers. Cached briefly: the set changes only when metrics are reconfigured.
        """
        if self.scorers and time.time() - self.scorers_at < 300:
            return self.scorers
        if not self.enabled or not self.settings.galileo_api_key.get_secret_value():
            return self.scorers
        self.configure_environment()

        sdk = self.backend

        def load():
            return {
                str(row.id): str(row.name)
                for row in sdk.Scorers().list()
                if getattr(row, "id", None) and getattr(row, "name", None)
            }

        try:
            self.scorers = await asyncio.wait_for(asyncio.to_thread(load), 15)
            self.scorers_at = time.time()
        except Exception:  # noqa: BLE001 - isolate SDK failures without exposing credential-bearing errors
            self.status["last_error"] = "Metric names could not be resolved"
        return self.scorers

    @staticmethod
    def answer_context(evidence):
        """Render this turn's evidence as the context the delivered answer was drawn from.

        Span-level evaluators judge an answer against the context on its own span. Logged with the
        question alone, this span reported every claim as unsupported on every turn, correct answers
        included, because there was nothing on it to support them.
        """
        parts = []
        for result in (evidence or {}).get("calculations", []):
            parts.append("Spending calculation (authoritative, integer AUD cents):\n" + json.dumps(result, default=str))
        for document in (evidence or {}).get("policies", []):
            parts.append(f"Policy {document.get('citation')}: {document.get('excerpt')}")
        customer = (evidence or {}).get("customer")
        if customer:
            parts.append("Authenticated customer: " + json.dumps(customer, default=str))
        accounts = (evidence or {}).get("accounts")
        if accounts:
            parts.append("Accounts owned by that customer: " + json.dumps(accounts, default=str))
        return "\n\n".join(parts)[:12000]

    def model_span_name(self):
        """The name the LangChain callback gives the agent's own model calls."""
        return {
            "openai": "ChatOpenAI",
            "anthropic": "ChatAnthropic",
            "ollama": "ChatOllama",
        }.get(self.settings.llm_provider, "ChatOpenAI")

    @staticmethod
    def _rewrite_value(value, genuine, candidate):
        """Replace `genuine` with `candidate` anywhere inside a span field. Returns (value, hit).

        Span payloads arrive in several shapes -- a plain string, a message object, a list of
        messages, a serialised dict -- so this walks whatever it is given rather than assuming.
        """
        if isinstance(value, str):
            return (value.replace(genuine, candidate), True) if genuine in value else (value, False)
        content = getattr(value, "content", None)
        if isinstance(content, str) and genuine in content:
            value.content = content.replace(genuine, candidate)
            return value, True
        hit = False
        if isinstance(value, list):
            for index, item in enumerate(value):
                value[index], found = Telemetry._rewrite_value(item, genuine, candidate)
                hit = hit or found
        elif isinstance(value, dict):
            for key, item in value.items():
                value[key], found = Telemetry._rewrite_value(item, genuine, candidate)
                hit = hit or found
        return value, hit

    @staticmethod
    def _rewrite_spans(spans, genuine, candidate):
        """Replace `genuine` in every span input and output, depth first. Returns a count.

        Inputs matter as much as outputs: the middleware spans carry the whole message list, so
        the agent's complete answer reappears there as chat history even once its own output has
        been rewritten.
        """
        replaced = 0
        for span in spans or []:
            for field in ("input", "output"):
                value = getattr(span, field, None)
                if value is None:
                    continue
                new, hit = Telemetry._rewrite_value(value, genuine, candidate)
                if not hit:
                    continue
                if new is not value:
                    # A string is replaced wholesale; a message or list was edited in place, and
                    # a field that refuses assignment keeps that in-place edit either way.
                    with suppress(Exception):
                        setattr(span, field, new)
                replaced += 1
            replaced += Telemetry._rewrite_spans(getattr(span, "spans", None), genuine, candidate)
        return replaced

    def mask_genuine_answer(self, turn, genuine, candidate):
        """Rewrite the agent's own answer in the trace to the one the customer received.

        Without this the trace tells two stories: the agent's llm span holds the complete answer
        and `customer-visible-answer` holds the faulty one. That is a tell for anyone reading the
        trace, and it silently contaminates evaluation -- a custom judge is handed the whole
        normalised trace, spans included, so a completeness judge reads the agent's fuller draft
        and concludes the question was answered. Three rounds of prompt instructions telling it
        to ignore the spans did not hold.

        Spans are held in memory until `flush`, so this edits them in place before export. The
        honest record is unaffected: the presenter evidence still keeps the genuine answer beside
        the injected one and names the method that produced it.
        """
        if not turn or not genuine.strip() or genuine.strip() == candidate.strip():
            return 0
        try:
            traces = getattr(turn["logger"], "traces", None) or []
            if not traces:
                return 0
            return self._rewrite_spans(
                getattr(traces[-1], "spans", None), genuine.strip(), candidate
            )
        except Exception:  # noqa: BLE001 - isolate SDK failures without exposing credential-bearing errors
            self.status["last_error"] = "A telemetry event could not be recorded"
            return 0

    def fault_span(self, turn, scenario, prompt, candidate, evidence=None, usage=None):
        """Log the controlled fault writer as its own named span.

        Named after the chat model class so it reads as an ordinary model call in the trace: the
        demonstration depends on the failure looking like something a model produced. The honest
        record lives in the presenter evidence, which keeps the genuine answer beside the injected
        one and reports which method produced it.

        Carries the same evidence as the answer span, so the evaluator judges the fabricated claim
        against what the tools actually returned.
        """
        if not turn:
            return
        try:
            context = self.answer_context(evidence)
            messages = [{"role": "user", "content": prompt}]
            if context:
                messages.insert(0, {"role": "system", "content": "Context for this answer:\n" + context})
            turn["logger"].add_llm_span(
                input=messages,
                output=candidate,
                model=self.settings.model_name,
                name=self.model_span_name(),
                num_input_tokens=(usage or {}).get("input_tokens"),
                num_output_tokens=(usage or {}).get("output_tokens"),
                total_tokens=(usage or {}).get("total_tokens"),
            )
        except Exception:  # noqa: BLE001 - isolate SDK failures without exposing credential-bearing errors
            self.status["last_error"] = "A telemetry event could not be recorded"

    def answer_span(self, turn, prompt, candidate, evidence=None, usage=None):
        """Log the delivered candidate as a named LLM span.

        Carries the same evidence the agent answered from, so span-level evaluators can judge the
        answer instead of reporting it unsupported. Tool definitions are deliberately not attached:
        Tool Selection Quality scores LLM spans, and would fail a span that advertises tools and
        selects none. The trace output stays the JSON record the trace-level custom judges read, and
        the name and output are what the bound Agent Control output control scopes.
        """
        if not turn:
            return
        try:
            context = self.answer_context(evidence)
            messages = [{"role": "user", "content": prompt}]
            if context:
                messages.insert(0, {"role": "system", "content": "Context for this answer:\n" + context})
            turn["logger"].add_llm_span(
                input=messages,
                output=candidate,
                model=self.settings.model_name,
                name="customer-visible-answer",
                num_input_tokens=(usage or {}).get("input_tokens"),
                num_output_tokens=(usage or {}).get("output_tokens"),
                total_tokens=(usage or {}).get("total_tokens"),
            )
        except Exception:  # noqa: BLE001 - isolate SDK failures without exposing credential-bearing errors
            self.status["last_error"] = "A telemetry event could not be recorded"

    async def finish(self, turn, record):
        if not turn:
            return
        logger = turn["logger"]
        # The genuine answer stays out of the trace entirely. Masking the spans is only half of
        # it: the trace output is this record, and `raw_model_output` carries the complete answer
        # straight back into what every judge reads. The presenter evidence keeps it -- that has
        # always been the honest record -- but the trace shows one answer, the delivered one.
        exported = {k: v for k, v in record.items() if k != "raw_model_output"}
        try:
            logger.conclude(
                output=json.dumps(exported, default=str),
                duration_ns=time.perf_counter_ns() - turn["started"],
                conclude_all=True,
            )
            errors = []
            await asyncio.wait_for(
                asyncio.to_thread(logger.flush, on_error=lambda e: errors.append(True)), 15
            )
            self.status["export"] = "failed" if errors else "exported"
            if not errors:
                self.status.update(
                    connection="connected", state="connected", last_connected_at=time.time(), last_error=None
                )
            else:
                self.status.update(connection="failed", state="failed")
            if errors:
                self.status["last_error"] = "Galileo exporter reported an error"
        except Exception:  # noqa: BLE001 - isolate SDK failures without exposing credential-bearing errors
            self.status.update(
                export="failed", connection="failed", state="failed", last_error="Galileo export failed"
            )
        finally:
            self.pending.pop(id(logger), None)

    async def shutdown(self):
        for logger in list(self.pending.values()):
            try:
                await asyncio.wait_for(asyncio.to_thread(logger.flush), 10)
            except Exception:  # noqa: BLE001 - isolate SDK failures without exposing credential-bearing errors
                self.status["export"] = "failed"
