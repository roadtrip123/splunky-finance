import asyncio
import secrets
import time
from contextlib import asynccontextmanager
from datetime import date
from typing import Annotated, Literal
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import Field

from app.agent import ChatService
from app.auth import Authentication, Session
from app.config import Settings
from app.demo.connections import Connections
from app.demo.scenarios import SCENARIOS
from app.observability.galileo import Telemetry
from app.observability.protection import Protection
from app.schemas import ChatInput, DatasetReset, Login, ProtectionSetting, ScenarioSetting, StrictModel
from app.storage import Storage
from app.tools import Banking


class GalileoSetting(StrictModel):
    enabled: bool
    expected_revision: int = Field(ge=0)


class ModelEndpoint(StrictModel):
    """One saved model endpoint.

    Sharon AI and other OpenAI-compatible services use the openai provider with a base URL, so
    several endpoints can share a provider and differ only by host and model.
    """

    id: str = Field(default="", max_length=64)
    name: str = Field(default="", max_length=120)
    provider: Literal["openai", "anthropic", "ollama"]
    api_key: str = Field(default="", max_length=400)
    model: str = Field(default="", max_length=200)
    base_url: str = Field(default="", max_length=400)


class ActiveEndpoint(StrictModel):
    id: str = Field(min_length=1, max_length=64)


class GalileoConnection(StrictModel):
    """Connection details a workshop participant supplies from the portal.

    Blank fields are left unchanged, so the API key can stay as it is while a project or log
    stream is corrected.
    """

    galileo_api_key: str = Field(default="", max_length=400)
    galileo_project: str = Field(default="", max_length=200)
    galileo_log_stream: str = Field(default="", max_length=200)
    galileo_console_url: str = Field(default="", max_length=400)
    galileo_api_url: str = Field(default="", max_length=400)
    agent_control_url: str = Field(default="", max_length=400)
    splunk_ao_api_key: str = Field(default="", max_length=400)
    splunk_ao_console_url: str = Field(default="", max_length=400)
    splunk_ao_api_url: str = Field(default="", max_length=400)
    splunk_ao_realm: str = Field(default="", max_length=64)
    splunk_ao_o11y_token: str = Field(default="", max_length=400)
    splunk_ao_o11y_api_token: str = Field(default="", max_length=400)
    splunk_ao_agent_control_url: str = Field(default="", max_length=400)
    # Named explicitly, because a blank field means "leave unchanged" and always will.
    clear: list[str] = Field(default_factory=list, max_length=20)


class ActiveBackend(StrictModel):
    id: str = Field(min_length=1, max_length=32)


class DemoSettings(StrictModel):
    scenario: str
    protection: bool
    expected_revision: int = Field(ge=0)
    run_id: str


class DemoChatInput(ChatInput):
    expected_revision: int = Field(ge=0)
    run_id: str


class DemoVersion(StrictModel):
    version: str = Field(max_length=100)


class PairingCode(StrictModel):
    code: str = Field(min_length=1, max_length=32)


class Binding(StrictModel):
    token: str = Field(min_length=1, max_length=80)


def create_app(settings=None, model_builder=None, protection_adapter=None):
    settings = settings or Settings()
    storage = Storage(settings)
    auth = Authentication(settings)
    telemetry = Telemetry(settings)
    protection = protection_adapter or Protection(settings)
    chat = ChatService(
        settings, telemetry, protection, **({"model_builder": model_builder} if model_builder else {})
    )
    links = Connections(auth, chat)
    jobs = {}

    @asynccontextmanager
    async def lifespan(app):
        connection_task = asyncio.create_task(telemetry.check_connection())
        yield
        connection_task.cancel()
        await asyncio.gather(connection_task, return_exceptions=True)
        for job in jobs.values():
            task = job.get("task")
            if task and not task.done():
                task.cancel()
        await telemetry.shutdown()

    app = FastAPI(title="Splunky Finance", docs_url=None, redoc_url=None, lifespan=lifespan)
    app.state.storage, app.state.auth, app.state.chat = storage, auth, chat
    app.state.telemetry = telemetry

    @app.middleware("http")
    async def correlation(request, call_next):
        request.state.correlation_id = str(uuid4())
        response = await call_next(request)
        response.headers["X-Correlation-ID"] = request.state.correlation_id
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    def error(request, status, code, message):
        return JSONResponse(
            status_code=status,
            content={
                "error": {"code": code, "message": message},
                "correlation_id": request.state.correlation_id,
            },
        )

    @app.exception_handler(HTTPException)
    async def http_error(request, exc):
        return error(request, exc.status_code, f"http_{exc.status_code}", str(exc.detail))

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, exc):
        return error(request, 422, "invalid_request", "Invalid request fields or values")

    @app.exception_handler(Exception)
    async def internal_error(request, exc):
        return error(request, 503, "unavailable", "Service temporarily unavailable")

    def session(request, role="customer", changing=False):
        value = auth.get(request, role)
        if changing:
            auth.csrf(request, value)
        return value

    def bank():
        if not storage.dataset:
            raise HTTPException(503, "Banking data is unavailable")
        return Banking(storage.dataset, settings.policy_dir, storage)

    def envelope(request, content):
        return {**content, "correlation_id": request.state.correlation_id}

    @app.get("/health")
    async def health():
        return {"status": "alive"}

    @app.get("/ready")
    async def ready(response: Response):
        local = storage.dataset is not None and bool(list(settings.policy_dir.glob("*.md")))
        response.status_code = 200 if local else 503
        return {
            "status": "ready" if local else "not_ready",
            "data": "valid" if storage.dataset else "unavailable",
            "model": "configured" if settings.provider_configured else "unconfigured",
            "galileo": telemetry.status["state"],
        }

    @app.post("/api/auth/login")
    async def login(request: Request, credentials: Login, response: Response):
        auth.csrf(request)
        return envelope(request, auth.login(request, "customer", credentials, response))

    @app.post("/api/demo-admin/login")
    async def admin_login(request: Request, credentials: Login, response: Response):
        auth.csrf(request)
        return envelope(request, auth.login(request, "admin", credentials, response))

    @app.get("/api/auth/session")
    async def auth_session(request: Request):
        return envelope(request, auth.summary(auth.get(request, required=False)))

    @app.get("/api/demo-admin/session")
    async def admin_session(request: Request):
        return envelope(request, auth.summary(auth.get(request, "admin", required=False)))

    def logout_session(request, role, response):
        current = session(request, role, True)
        auth.sessions.pop(current.id, None)
        chat.clear(current)
        if role == "admin":
            chat.runs = {k: v for k, v in chat.runs.items() if v["owner"] != current.id}
        response.delete_cookie(
            auth.cookie(role),
            path="/",
            secure=settings.session_cookie_secure,
            httponly=True,
            samesite="strict",
        )
        return envelope(request, {"status": "logged_out"})

    @app.post("/api/auth/logout")
    async def logout(request: Request, response: Response):
        return logout_session(request, "customer", response)

    @app.post("/api/demo-admin/logout")
    async def admin_logout(request: Request, response: Response):
        return logout_session(request, "admin", response)

    @app.get("/api/customer")
    async def customer(request: Request):
        session(request)
        return envelope(request, bank().dataset.customer)

    @app.get("/api/accounts")
    async def accounts(request: Request):
        session(request)
        rows = bank().dataset.accounts
        return envelope(
            request,
            {
                "items": [a.model_dump(mode="json") for a in rows],
                "cash_total_cents": sum(a.posted_balance_cents for a in rows if a.type != "credit_card"),
                "card_amount_owed_cents": sum(
                    max(0, -a.posted_balance_cents) for a in rows if a.type == "credit_card"
                ),
            },
        )

    @app.get("/api/accounts/{identifier}")
    async def account(request: Request, identifier: str):
        session(request)
        row = bank().account(identifier)
        if not row:
            raise HTTPException(404, "Account not found")
        return envelope(request, row.model_dump(mode="json"))

    @app.get("/api/accounts/{identifier}/transactions")
    async def transactions(
        request: Request,
        identifier: str,
        start: date | None = None,
        end: date | None = None,
        category: Annotated[str | None, Field(max_length=60)] = None,
        search: Annotated[str | None, Field(max_length=100)] = None,
        sort: Literal["date_desc", "date_asc", "amount_desc", "amount_asc"] = "date_desc",
        page: Annotated[int, Field(ge=1, le=10000)] = 1,
        page_size: Annotated[int, Field(ge=1, le=100)] = 25,
    ):
        session(request)
        banking = bank()
        if not banking.account(identifier):
            raise HTTPException(404, "Account not found")
        if start and end and start >= end:
            raise HTTPException(422, "Start must precede exclusive end date")
        items = banking.transactions(identifier, start, end, category, search, sort)
        return envelope(
            request,
            {
                "items": [
                    t.model_dump(mode="json") for t in items[(page - 1) * page_size : page * page_size]
                ],
                "page": page,
                "page_size": page_size,
                "total": len(items),
            },
        )

    @app.post("/api/chat")
    async def answer(request: Request, payload: ChatInput):
        current = session(request, changing=True)
        state = links.state(current)
        if state["expired"] or (
            payload.demo_version is not None and payload.demo_version != state["version"]
        ):
            raise HTTPException(409, "Demo settings changed; wait for synchronization and send again")
        # Start fresh model context after a setting change, keeping the browser transcript.
        context_version = getattr(current, "context_version", None)
        if payload.conversation_id:
            existing = chat.conversations.get(payload.conversation_id)
            if existing and existing.owner != current.id:
                raise HTTPException(404, "Conversation not found")
        if context_version is not None and context_version != state["version"]:
            payload = payload.model_copy(update={"conversation_id": None})
        current.context_version = state["version"]
        return envelope(request, await chat.answer(current, payload, bank()))

    @app.post("/api/chat/demo-sync")
    async def demo_sync(request: Request):
        customer = session(request, changing=True)
        links.auto(customer, auth.get(request, "admin", required=False))
        return envelope(request, links.state(customer))

    @app.post("/api/chat/demo-ack")
    async def demo_ack(request: Request, payload: DemoVersion):
        customer = session(request, changing=True)
        if payload.version != links.state(customer)["version"]:
            raise HTTPException(409, "Demo settings changed")
        links.seen[customer.id] = (payload.version, time.time())
        return envelope(request, {"status": "acknowledged"})

    @app.post("/api/chat/demo-pair")
    async def demo_pair(request: Request, payload: PairingCode):
        customer = session(request, changing=True)
        links.pair(customer, payload.code)
        return envelope(request, links.state(customer))

    @app.post("/api/chat/demo-disconnect")
    async def demo_disconnect(request: Request):
        customer = session(request, changing=True)
        links.disconnect(customer)
        return envelope(request, links.state(customer))

    @app.post("/api/demo-admin/pairing")
    async def demo_pairing(request: Request):
        admin = session(request, "admin", True)
        run = chat.run(admin)
        if not run:
            raise HTTPException(409, "Open the demo workspace first")
        return envelope(request, links.issue(run))

    @app.post("/api/demo-admin/disconnect")
    async def presenter_disconnect(request: Request):
        admin = session(request, "admin", True)
        run = chat.run(admin)
        if run:
            customer = auth.sessions.get(run.get("customer_id"))
            if customer:
                links.disconnect(customer, run)
            run.pop("customer_id", None)
            run["auto_disabled"] = True
            links.codes = {k: v for k, v in links.codes.items() if v[0] != run["id"]}
        return envelope(request, {"status": "disconnected"})

    @app.post("/api/chat/reset")
    async def clear_chat(request: Request):
        current = session(request, changing=True)
        if any(c.owner == current.id and c.lock.locked() for c in chat.conversations.values()):
            raise HTTPException(409, "Wait for the current answer before resetting")
        chat.clear(current)
        return envelope(request, {"status": "reset"})

    def demo_idle(current):
        if any(c.owner == current.id and c.lock.locked() for c in chat.conversations.values()):
            raise HTTPException(409, "Wait for the current answer before changing demo settings")

    @app.post("/api/demo-admin/workspace")
    async def demo_workspace(request: Request):
        current = session(request, "admin", True)
        run = chat.run(current)
        if not run:
            chat.clear(current)
            run = chat.new_run(current)
            run["protection"] = False
        links.auto(auth.get(request, required=False), current)
        return envelope(request, run)

    @app.put("/api/demo-admin/workspace")
    async def demo_settings(request: Request, payload: DemoSettings):
        current = session(request, "admin", True)
        run = chat.owned_run(current, payload.run_id)
        demo_idle(current)
        if run["revision"] != payload.expected_revision:
            raise HTTPException(409, "Settings changed in another tab. Refresh and try again.")
        if payload.scenario not in SCENARIOS:
            raise HTTPException(422, "Unknown scenario")
        if payload.protection and not SCENARIOS[payload.scenario]["protection_applicable"]:
            raise HTTPException(422, "Protection demonstration is available for policy scenarios")
        if run["scenario"] != payload.scenario:
            run["replay"] = None
        chat.clear(current)
        run.update(scenario=payload.scenario, protection=payload.protection, revision=run["revision"] + 1)
        return envelope(request, run)

    @app.post("/api/demo-admin/chat")
    async def demo_answer(request: Request, payload: DemoChatInput):
        current = session(request, "admin", True)
        run = chat.owned_run(current, payload.run_id)
        if run["revision"] != payload.expected_revision:
            raise HTTPException(409, "Settings changed in another tab. Refresh and try again.")
        return envelope(request, await chat.answer(current, payload, bank()))

    @app.post("/api/demo-admin/run")
    async def new_run(request: Request):
        current = session(request, "admin", True)
        return envelope(request, chat.new_run(current))

    @app.post("/api/demo-admin/bind")
    async def bind_run(request: Request, payload: Binding):
        # Requires both presenter and customer sessions; token alone cannot activate fault mode.
        admin = session(request, "admin")
        customer = session(request, changing=True)
        run = chat.run(admin)
        if not run or not secrets.compare_digest(payload.token, run["binding"]):
            raise HTTPException(403, "Presenter run binding rejected")
        links.attach(customer, run)
        chat.clear(customer)
        return envelope(request, {"status": "bound"})

    @app.put("/api/demo-admin/scenario")
    async def set_scenario(request: Request, payload: ScenarioSetting):
        current = session(request, "admin", True)
        run = chat.owned_run(current, payload.run_id)
        if payload.expected_revision != run["revision"]:
            raise HTTPException(409, "Run settings changed; refresh")
        if payload.scenario_id not in SCENARIOS:
            raise HTTPException(422, "Unknown scenario")
        run.update(scenario=payload.scenario_id, revision=run["revision"] + 1, replay=None)
        for customer in auth.sessions.values():
            if customer.run_id == run["id"]:
                chat.clear(customer)
        return envelope(request, run)

    @app.put("/api/demo-admin/protection")
    async def set_protection(request: Request, payload: ProtectionSetting):
        current = session(request, "admin", True)
        run = chat.owned_run(current, payload.run_id)
        if payload.expected_revision != run["revision"]:
            raise HTTPException(409, "Run settings changed; refresh")
        run.update(protection=payload.enabled, revision=run["revision"] + 1)
        return envelope(request, run)

    @app.put("/api/demo-admin/galileo")
    async def set_galileo(request: Request, payload: GalileoSetting):
        session(request, "admin", True)
        if payload.expected_revision != telemetry.revision:
            raise HTTPException(409, "Galileo settings changed; refresh")
        if (
            telemetry.pending
            or telemetry.connection_lock.locked()
            or any(c.lock.locked() for c in chat.conversations.values())
        ):
            raise HTTPException(409, "Wait for active requests before changing Galileo")
        telemetry.set_enabled(payload.enabled)
        if payload.enabled:
            await telemetry.check_connection(force=True)
        return envelope(request, {"galileo": dict(telemetry.status)})

    def _endpoint_guard(payload):
        if payload.base_url and not payload.base_url.startswith(("http://", "https://")):
            raise HTTPException(422, "Base URL must be an http(s) URL")
        # Mirrors the startup rule: Ollama mode is for a local runtime, not a hosted one.
        if payload.provider == "ollama" and ("cloud" in payload.model or "ollama.com" in payload.base_url):
            raise HTTPException(422, "Ollama mode requires a local model and local runtime")

    def _busy():
        if any(c.lock.locked() for c in chat.conversations.values()):
            raise HTTPException(409, "Wait for active conversations before changing the model")

    @app.put("/api/demo-admin/endpoints")
    async def save_endpoint(request: Request, payload: ModelEndpoint):
        session(request, "admin", True)
        _busy()
        _endpoint_guard(payload)
        telemetry.save_endpoint(payload.model_dump())
        chat.provider_status = {"state": "unverified" if settings.provider_configured else "unconfigured"}
        return envelope(request, telemetry.endpoints_view())

    @app.post("/api/demo-admin/endpoints/active")
    async def activate_endpoint(request: Request, payload: ActiveEndpoint):
        """Switch the model mid-demo. The next turn resolves this once and passes it explicitly,
        so a switch cannot change the model under a request already running."""
        current = session(request, "admin", True)
        _busy()
        try:
            telemetry.set_active_endpoint(payload.id)
        except KeyError:
            raise HTTPException(404, "Unknown endpoint") from None
        # Start a fresh conversation, as a scenario change does. Otherwise the next model is
        # handed the previous model's answer as history: it sees a larger prompt, may refer back
        # to an answer it did not write, and both traces land in one Galileo session, so the
        # comparison the switch exists for is contaminated.
        chat.clear(current)
        run = chat.run(current)
        if run:
            run["revision"] += 1
        chat.provider_status = {"state": "unverified" if settings.provider_configured else "unconfigured"}
        return envelope(request, telemetry.endpoints_view())

    @app.post("/api/demo-admin/backends/active")
    async def activate_backend(request: Request, payload: ActiveBackend):
        """Switch observability backend. One is active at a time.

        Same shape as the model switch: a fresh conversation, because the previous backend's
        session belongs to the previous tenant and mixing the two makes the traces hard to read.
        """
        current = session(request, "admin", True)
        _busy()
        try:
            view = telemetry.set_active_backend(payload.id)
        except ValueError:
            raise HTTPException(404, "Unknown observability backend") from None
        chat.clear(current)
        run = chat.run(current)
        if run:
            run["revision"] += 1
        return envelope(request, view)

    @app.delete("/api/demo-admin/endpoints/{identifier}")
    async def remove_endpoint(request: Request, identifier: str):
        session(request, "admin", True)
        _busy()
        telemetry.delete_endpoint(identifier)
        chat.provider_status = {"state": "unverified" if settings.provider_configured else "unconfigured"}
        return envelope(request, telemetry.endpoints_view())

    @app.put("/api/demo-admin/galileo/connection")
    async def set_galileo_connection(request: Request, payload: GalileoConnection):
        session(request, "admin", True)
        if telemetry.pending or any(c.lock.locked() for c in chat.conversations.values()):
            raise HTTPException(409, "Wait for active requests before changing Galileo")
        for name in ("galileo_console_url", "galileo_api_url", "agent_control_url"):
            value = getattr(payload, name)
            if value and not value.startswith(("http://", "https://")):
                raise HTTPException(422, f"{name} must be an http(s) URL")
        values = payload.model_dump()
        telemetry.set_connection(values, clear=values.pop("clear", []))
        status = await telemetry.check_connection(force=True) if telemetry.enabled else telemetry.status
        # The API key is never echoed back; the connection payload reports only whether one is set.
        return envelope(request, {"galileo": dict(status), "connection": telemetry.connection()})

    @app.post("/api/demo-admin/galileo/setup")
    async def setup_galileo_project(request: Request):
        """Enable the metrics on this log stream and bind the transfer control.

        Metrics are enabled per log stream and control bindings are per log stream, so each
        participant has to do this against their own project even though the judges and the
        control definition already exist tenant-wide.
        """
        session(request, "admin", True)
        if not telemetry.enabled or not settings.galileo_api_key.get_secret_value():
            raise HTTPException(409, "Connect to Galileo before setting up the project")
        job = str(uuid4())
        jobs[job] = {"state": "running", "result": None}

        async def run():
            try:
                jobs[job] = {"state": "complete", "result": await telemetry.setup_project()}
            except Exception:  # noqa: BLE001 - sanitize credential-bearing SDK errors
                jobs[job] = {"state": "failed", "result": {"error": "Project setup failed"}}

        asyncio.create_task(run())
        return envelope(request, {"job_id": job})

    @app.post("/api/demo-admin/galileo/check")
    async def check_galileo(request: Request):
        session(request, "admin", True)
        return envelope(request, {"galileo": await telemetry.check_connection()})

    @app.get("/api/demo-admin/status")
    async def admin_status(request: Request):
        current = session(request, "admin")
        run = chat.run(current)
        events = [e for e in chat.events if run and e.get("presenter_run_id") == run["id"]]
        return envelope(
            request,
            {
                "banking_connection": links.status(run),
                "provider": settings.llm_provider,
                "model": settings.model_name,
                "provider_status": chat.provider_status,
                "galileo": telemetry.status,
                "project": settings.galileo_project,
                "log_stream": settings.galileo_log_stream,
                "console_url": settings.galileo_console_url or None,
                "protection_status": protection.status,
                "demo_mode": settings.demo_mode,
                # Never in workshop mode, where building it by hand is the lab.
                "setup_button": settings.demo_setup_button and settings.demo_mode != "workshop",
                "connection": telemetry.connection(),
                "endpoints": telemetry.endpoints_view(),
                "observability": telemetry.backends_view(),
                "run": run,
                "events": events[-10:],
                "scenarios": SCENARIOS,
                "dataset": {
                    **storage.dataset.manifest.model_dump(mode="json"),
                    "transaction_count": len(storage.dataset.transactions),
                }
                if storage.dataset
                else {"state": "unavailable", "dataset_version": 0},
            },
        )

    @app.post("/api/demo-admin/evaluations/refresh")
    async def refresh_evaluations(request: Request):
        current = session(request, "admin", True)
        run = chat.run(current)
        results = []
        names = await telemetry.scorer_names()
        for record in list(chat.events)[-10:]:
            if run and record.get("presenter_run_id") == run["id"] and record.get("trace_id"):
                try:
                    traces = telemetry.backend.traces(
                        project_id=record["project_id"], stream_id=record["log_stream_id"]
                    )
                    remote = await asyncio.wait_for(traces.get_trace(record["trace_id"]), 10)
                    metrics = remote.get("metrics", {}) or {}
                    info = remote.get("metric_info") or {}
                    # Metrics are keyed by scorer id, alongside per-metric "<id>_rationale" and
                    # cost keys. Keep the resolvable ones and carry each judge's reasoning, which
                    # is what makes a score defensible on screen.
                    scores = {}
                    for key, value in metrics.items():
                        name = names.get(key)
                        if not name or value is None:
                            continue
                        if isinstance(value, list) and len(value) == 1:
                            value = value[0]
                        scores[name] = {
                            "value": value,
                            "rationale": metrics.get(f"{key}_rationale")
                            or (info.get(key) or {}).get("explanation"),
                        }
                    record["evaluation"] = {
                        "state": "received" if scores else "pending_or_unconfigured",
                        "scores": scores or None,
                        "unresolved_metric_keys": (
                            None
                            if names
                            else "Metric names unavailable; scores are keyed by scorer id"
                        ),
                    }
                except Exception:  # noqa: BLE001 - isolate SDK failures without exposing credential-bearing errors
                    record["evaluation"] = {"state": "failed", "scores": None}
                results.append({"run_id": record["run_id"], "evaluation": record["evaluation"]})
        return envelope(request, {"items": results})

    @app.get("/api/demo-admin/expected-results")
    async def expected(request: Request):
        session(request, "admin")
        return envelope(request, bank().dataset.expected_results)

    @app.post("/api/demo-admin/reset")
    async def reset_run(request: Request):
        current = session(request, "admin", True)
        run = chat.run(current)
        if run:
            run.update(replay=None, scenario="normal_spending", revision=run["revision"] + 1)
            for customer in auth.sessions.values():
                if customer.run_id == run["id"]:
                    chat.clear(customer)
        return envelope(request, {"status": "reset"})

    @app.post("/api/demo-admin/dataset/reset")
    async def reset_dataset(request: Request, payload: DatasetReset):
        session(request, "admin", True)
        if not payload.confirmed:
            raise HTTPException(422, "Reset must be confirmed")
        if any(c.lock.locked() for c in chat.conversations.values()):
            raise HTTPException(409, "Wait for active conversations before resetting data")
        try:
            ds = storage.reset(payload.expected_version, payload.seed, payload.reference_date)
        except ValueError:
            raise HTTPException(409, "Dataset version changed; refresh") from None
        chat.conversations.clear()
        for run in chat.runs.values():
            run.update(replay=None, revision=run["revision"] + 1)
        return envelope(request, {"status": "reset", "dataset_version": ds.manifest.dataset_version})

    @app.post("/api/demo-admin/preflight")
    async def preflight(request: Request):
        current = session(request, "admin", True)
        # Explicit presenter action, not a health probe. This can make paid model calls.
        jobs_to_remove = [k for k, v in jobs.items() if v["state"] != "running"]
        for key in jobs_to_remove:
            del jobs[key]
        if any(v["state"] == "running" for v in jobs.values()):
            raise HTTPException(409, "Preflight already running")
        identifier = str(uuid4())
        job = {"id": identifier, "owner": current.id, "state": "running"}
        jobs[identifier] = job

        async def execute():
            try:
                fake = Session(str(uuid4()), "customer", time.time() + 300, "")
                result = await chat.answer(
                    fake, ChatInput(message="Use get_accounts to list my account names and balances."), bank()
                )
                observed = chat.events[-1].get("observed_tool_calls", [])
                job.update(
                    state="completed" if observed else "failed",
                    result={
                        "observed_tool_calls": observed,
                        "provider": chat.provider_status,
                        "answer": result["answer"],
                        "galileo": dict(telemetry.status),
                    },
                )
                chat.clear(fake)
            except Exception:  # noqa: BLE001 - isolate SDK failures without exposing credential-bearing errors
                job.update(
                    state="failed",
                    result={
                        "message": "Preflight failed; check configured provider and data",
                        "provider": chat.provider_status,
                        "galileo": dict(telemetry.status),
                    },
                )

        job["task"] = asyncio.create_task(execute())
        return envelope(request, {"job_id": identifier, "state": "running"})

    @app.get("/api/demo-admin/preflight/{identifier}")
    async def preflight_status(request: Request, identifier: str):
        current = session(request, "admin")
        job = jobs.get(identifier)
        if not job or job["owner"] != current.id:
            raise HTTPException(404, "Preflight not found")
        return envelope(request, {k: v for k, v in job.items() if k not in ("task", "owner")})

    return app
