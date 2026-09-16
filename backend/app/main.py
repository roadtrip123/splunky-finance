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
from app.demo.scenarios import SCENARIOS
from app.observability.galileo import Telemetry
from app.observability.protection import Protection
from app.schemas import ChatInput, DatasetReset, Login, ProtectionSetting, ScenarioSetting, StrictModel
from app.storage import Storage
from app.tools import Banking


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
    jobs = {}

    @asynccontextmanager
    async def lifespan(app):
        yield
        for job in jobs.values():
            task = job.get("task")
            if task and not task.done():
                task.cancel()
        await telemetry.shutdown()

    app = FastAPI(title="Splunky Finance", docs_url=None, redoc_url=None, lifespan=lifespan)
    app.state.storage, app.state.auth, app.state.chat = storage, auth, chat

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
        return Banking(storage.dataset, settings.policy_dir)

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
        return envelope(request, await chat.answer(current, payload, bank()))

    @app.post("/api/chat/reset")
    async def clear_chat(request: Request):
        current = session(request, changing=True)
        if any(c.owner == current.id and c.lock.locked() for c in chat.conversations.values()):
            raise HTTPException(409, "Wait for the current answer before resetting")
        chat.clear(current)
        return envelope(request, {"status": "reset"})

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
        customer.run_id = run["id"]
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

    @app.get("/api/demo-admin/status")
    async def admin_status(request: Request):
        current = session(request, "admin")
        run = chat.run(current)
        events = [e for e in chat.events if run and e.get("presenter_run_id") == run["id"]]
        return envelope(
            request,
            {
                "provider": settings.llm_provider,
                "model": settings.model_name,
                "provider_status": chat.provider_status,
                "galileo": telemetry.status,
                "project": settings.galileo_project,
                "log_stream": settings.galileo_log_stream,
                "console_url": settings.galileo_console_url or None,
                "protection_status": protection.status,
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
        for record in chat.events:
            if run and record.get("presenter_run_id") == run["id"] and record.get("trace_id"):
                try:
                    from galileo.traces import Traces

                    traces = Traces(project_id=record["project_id"], log_stream_id=record["log_stream_id"])
                    remote = await asyncio.wait_for(traces.get_trace(record["trace_id"]), 10)
                    metrics = remote.get("metrics", {})
                    scores = {k: v for k, v in metrics.items() if k != "duration_ns" and v is not None}
                    record["evaluation"] = {
                        "state": "received" if scores else "pending_or_unconfigured",
                        "scores": scores or None,
                        "metric_info": remote.get("metric_info"),
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
