import asyncio
import json
import os
import time
from contextlib import suppress
from pathlib import Path
from typing import ClassVar
from uuid import uuid4


class Telemetry:
    """One logger per turn: no shared current trace across concurrent customer requests."""

    def __init__(self, settings):
        self.settings = settings
        self.enabled = settings.galileo_enabled
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

    CONNECTION_FIELDS = (
        "galileo_api_key",
        "galileo_project",
        "galileo_log_stream",
        "galileo_console_url",
        "galileo_api_url",
        "agent_control_url",
    )

    @property
    def backend(self):
        """The active observability SDK, resolved lazily and re-resolved when switched."""
        from app.observability.sdk import backend as resolve

        name = self.backend_name()
        if getattr(self, "_backend", None) is None or self._backend.name != name:
            self._backend = resolve(name)
        return self._backend

    def backend_name(self):
        from app.observability.sdk import BACKENDS, GALILEO

        saved = self._saved().get("active_backend")
        if saved in BACKENDS:
            return saved
        configured = getattr(self.settings, "observability_backend", GALILEO)
        return configured if configured in BACKENDS else GALILEO

    def apply_connection(self, values):
        """Copy saved connection details onto settings, treating the API key as a secret."""
        from pydantic import SecretStr

        for field in self.CONNECTION_FIELDS:
            value = values.get(field)
            if not isinstance(value, str) or not value:
                continue
            setattr(self.settings, field, SecretStr(value) if field.endswith("_key") else value)

    @staticmethod
    def mask(secret):
        """Enough of the key to recognise which one is loaded, never enough to use it."""
        if not secret:
            return ""
        return "\u2022" * 8 + secret[-4:] if len(secret) > 8 else "\u2022" * 8

    def connection(self):
        """Current connection details. The API key is only ever returned masked."""
        s = self.settings
        key = s.galileo_api_key.get_secret_value()
        return {
            "galileo_project": s.galileo_project,
            "galileo_log_stream": s.galileo_log_stream,
            "galileo_console_url": s.galileo_console_url,
            "galileo_api_url": s.galileo_api_url,
            "agent_control_url": s.agent_control_url,
            "galileo_api_key_set": bool(key),
            "galileo_api_key_masked": self.mask(key),
        }

    def _saved(self):
        try:
            return json.loads(self.toggle_path.read_text()) or {}
        except (OSError, ValueError, TypeError, AttributeError):
            return {}

    def _persist(self, connection=None, endpoints=None, active_endpoint=None):
        previous = self._saved()
        saved = {"enabled": self.enabled}
        connection = previous.get("connection") if connection is None else connection
        if endpoints is None:
            endpoints = self._load_endpoints(previous)
            active_endpoint = previous.get("active_endpoint")
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

    def set_connection(self, values):
        """Save connection details and apply them without a restart."""
        current = dict(self._saved().get("connection") or {})
        for field in self.CONNECTION_FIELDS:
            value = values.get(field)
            if isinstance(value, str) and value:
                current[field] = value
        self.apply_connection(current)
        self._persist(current)
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
                    state="unconfigured", connection="unconfigured", last_error="Galileo API key missing"
                )
                return dict(self.status)
            self.status.update(state="checking", connection="checking", last_error=None)
            self.configure_environment()
            try:
                sdk = self.backend

                def connect():
                    logger = sdk.new_logger(
                        project=self.settings.galileo_project, stream=self.settings.galileo_log_stream
                    )
                    # A fresh authenticated API read avoids claiming connection from cached IDs.
                    stream = sdk.get_stream(
                        name=self.settings.galileo_log_stream, project_id=str(logger.project_id)
                    )
                    if stream is None:
                        raise ValueError("Configured log stream unavailable")
                    return logger

                logger = await asyncio.wait_for(asyncio.to_thread(connect), 15)
                if not logger.project_id or not sdk.stream_id(logger):
                    raise ValueError("Unresolved Galileo target")
                self.status.update(
                    state="connected",
                    connection="connected",
                    last_connected_at=time.time(),
                    project_id=str(logger.project_id),
                    log_stream_id=str(sdk.stream_id(logger)),
                )
            except Exception:  # noqa: BLE001 - sanitize credential-bearing SDK errors
                self.status.update(
                    state="failed",
                    connection="failed",
                    last_error="Galileo connection failed; check API key, endpoint, and project permissions",
                )
            return dict(self.status)

    def configure_environment(self):
        s = self.settings
        os.environ["GALILEO_API_KEY"] = s.galileo_api_key.get_secret_value()
        for name in ("galileo_console_url", "galileo_api_url"):
            if getattr(s, name):
                os.environ[name.upper()] = getattr(s, name)

    async def begin(self, prompt, metadata):
        if not self.enabled:
            return None
        if not self.settings.galileo_api_key.get_secret_value():
            self.status.update(state="unconfigured", last_error="Galileo API key missing")
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
