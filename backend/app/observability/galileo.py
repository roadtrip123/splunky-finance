import asyncio
import json
import os
import time
from pathlib import Path


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
        self.pending = set()

    def set_enabled(self, enabled):
        self.toggle_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.toggle_path.with_suffix(".tmp")
        with temporary.open("w") as stream:
            json.dump({"enabled": enabled}, stream)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, self.toggle_path)
        self.enabled = enabled
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
                from galileo import GalileoLogger

                def connect():
                    from galileo.log_streams import get_log_stream

                    logger = GalileoLogger(
                        project=self.settings.galileo_project, log_stream=self.settings.galileo_log_stream
                    )
                    # A fresh authenticated API read avoids claiming connection from cached IDs.
                    stream = get_log_stream(
                        name=self.settings.galileo_log_stream, project_id=str(logger.project_id)
                    )
                    if stream is None:
                        raise ValueError("Configured log stream unavailable")
                    return logger

                logger = await asyncio.wait_for(asyncio.to_thread(connect), 15)
                if not logger.project_id or not logger.log_stream_id:
                    raise ValueError("Unresolved Galileo target")
                self.status.update(
                    state="connected",
                    connection="connected",
                    last_connected_at=time.time(),
                    project_id=str(logger.project_id),
                    log_stream_id=str(logger.log_stream_id),
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
            from galileo import GalileoLogger
            from galileo.handlers.langchain import GalileoAsyncCallback

            def initialize():
                logger = GalileoLogger(
                    project=self.settings.galileo_project, log_stream=self.settings.galileo_log_stream
                )
                logger.start_session(name="My Bank Agent", external_id=metadata["conversation_id"])
                trace = logger.start_trace(
                    input=prompt, name="bank-chat-turn", metadata=metadata, external_id=metadata["run_id"]
                )
                return logger, trace

            logger, trace = await asyncio.wait_for(asyncio.to_thread(initialize), timeout=15)
            self.status.update(
                state="connected",
                connection="connected",
                last_error=None,
                last_checked_at=time.time(),
                last_connected_at=time.time(),
                project_id=str(logger.project_id),
                log_stream_id=str(logger.log_stream_id),
            )
            self.pending.add(logger)
            return {
                "logger": logger,
                "trace_id": str(trace.id),
                "started": time.perf_counter_ns(),
                "callback": GalileoAsyncCallback(
                    galileo_logger=logger, start_new_trace=False, flush_on_chain_end=False
                ),
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

    async def finish(self, turn, record):
        if not turn:
            return
        logger = turn["logger"]
        try:
            logger.conclude(
                output=json.dumps(record, default=str),
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
            self.pending.discard(logger)

    async def shutdown(self):
        for logger in list(self.pending):
            try:
                await asyncio.wait_for(asyncio.to_thread(logger.flush), 10)
            except Exception:  # noqa: BLE001 - isolate SDK failures without exposing credential-bearing errors
                self.status["export"] = "failed"
