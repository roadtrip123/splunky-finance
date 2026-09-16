import asyncio
import json
import os
import time


class Telemetry:
    """One logger per turn: no shared current trace across concurrent customer requests."""

    def __init__(self, settings):
        self.settings = settings
        self.status = {
            "state": "unconfigured" if settings.galileo_enabled else "disabled",
            "export": "not_attempted",
            "last_error": None,
        }
        self.pending = set()

    def configure_environment(self):
        s = self.settings
        os.environ["GALILEO_API_KEY"] = s.galileo_api_key.get_secret_value()
        for name in ("galileo_console_url", "galileo_api_url"):
            if getattr(s, name):
                os.environ[name.upper()] = getattr(s, name)

    async def begin(self, prompt, metadata):
        if not self.settings.galileo_enabled:
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
            self.status.update(state="configured", last_error=None)
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
                state="failed", last_error="Galileo initialization failed; check server configuration"
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
            if errors:
                self.status["last_error"] = "Galileo exporter reported an error"
        except Exception:  # noqa: BLE001 - isolate SDK failures without exposing credential-bearing errors
            self.status.update(export="failed", last_error="Galileo export failed")
        finally:
            self.pending.discard(logger)

    async def shutdown(self):
        for logger in list(self.pending):
            try:
                await asyncio.wait_for(asyncio.to_thread(logger.flush), 10)
            except Exception:  # noqa: BLE001 - isolate SDK failures without exposing credential-bearing errors
                self.status["export"] = "failed"
