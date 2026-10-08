import asyncio
import time

FALLBACK = "I couldn't verify that answer against the bank's policies. Please check the account terms or contact the bank for confirmation."
BLOCKED = "That request is not available from My Bank Agent."


class ControlNotEvaluated(Exception):
    """No usable verdict came back. Carries why, so the three causes stay distinguishable."""

    def __init__(self, diagnosis):
        super().__init__(diagnosis.get("cause", "unknown"))
        self.diagnosis = diagnosis


class Protection:
    """Explicit candidate and action evaluation. No SDK-global toggles or model-selected protection tool."""

    def __init__(self, settings):
        self.settings = settings
        # Per stage, because the two gates answer different questions and conflating them made a
        # working guardrail report "failed". The pre gate decides whether a tool runs; the post gate
        # inspects the answer. Controls scoped to tools are invisible to the post gate, which then
        # correctly reports that nothing applied -- and since only the last call was kept, that was
        # all anyone ever saw.
        self.stages: dict = {}
        self.status = "unverified"
        # The detail behind `status`. Without this a 401 was only visible inside a turn record, so
        # a guardrail failing closed looked identical to one working and telling them apart meant
        # driving a turn and reading its action_decisions.
        self.detail: dict = {}

    # Best first: a stage that reached a verdict is the meaningful answer, and "no control applied"
    # is an outcome rather than a fault -- it is what a tool-scoped control looks like to the gate
    # that inspects answers.
    PRECEDENCE = ("verified", "failed", "no_control", "unverified")

    def _record(self, stage, status, detail=None):
        self.stages[stage] = {"status": status, "detail": detail or {}, "at": time.time()}
        best = min(
            (s for s in self.stages.values()),
            key=lambda s: self.PRECEDENCE.index(s["status"]),
        )
        self.status = best["status"]
        self.detail = best["detail"]
        return detail or {}

    def _unavailable(self, reason, diagnosis=None):
        details = {
            "decision": "unavailable",
            "source": "application",
            "verified": False,
            "action": "safe_fallback",
            "reason": reason,
        }
        if diagnosis:
            details["diagnosis"] = diagnosis
        return details

    def _failure(self, exc):
        """Why the request did not complete, with the HTTP status when there was one.

        The exception type alone said only that something went wrong. A rejected credential, a
        wrong gateway and a missing route are all `HTTPStatusError`, and they need different
        fixes. The status code is read off the response; the body is not, because it can carry
        credential headers back.
        """
        diagnosis = {"cause": "request_failed", "error": type(exc).__name__}
        # The path, never the full URL: a query string can carry a token, a path cannot. It says
        # which call was refused -- the runtime token exchange or the evaluation itself -- which is
        # the difference between a permission to request and a tenant feature to enable.
        request = getattr(exc, "request", None)
        path = getattr(getattr(request, "url", None), "path", None)
        if path:
            diagnosis["path"] = str(path)
        response = getattr(exc, "response", None)
        status = getattr(response, "status_code", None)
        if status:
            diagnosis["http_status"] = int(status)
            # The gateway's own message, truncated. Originally left out on the grounds that a body
            # can echo credential headers -- but a 4xx from this gateway is a server-authored error,
            # and without it a 401 is just a number. Three rounds of comparing two boxes field by
            # field could have been one if this had been here. Only for client errors, where the body
            # is an explanation rather than a payload.
            if 400 <= int(status) < 500:
                try:
                    body = response.text
                except Exception:  # noqa: BLE001 - a body that cannot be read is simply absent
                    body = ""
                if body:
                    diagnosis["response"] = body.strip()[:400]
            diagnosis["hint"] = {
                401: "credentials rejected by the Agent Control gateway",
                403: "credentials accepted but the request was refused",
                404: (
                    f"no agent named {self.settings.resolved_agent_name!r} in Agent Control, "
                    "or no such route at this Agent Control URL. The name must match the console "
                    "exactly; agents cannot be created from the app"
                ),
            }.get(int(status), "the gateway returned an error")
        return diagnosis

    def _configured(self, logger):
        s = self.settings
        return bool(
            s.galileo_enabled and logger and s.agent_control_url and s.galileo_api_key.get_secret_value()
        )

    async def _evaluate(self, logger, stage, step_type, step_name, step_input, step_output, context):
        """One runtime evaluation, shared by the action gate and the answer gate.

        Raises on anything that is not a genuine decision carrying evaluated controls, so both
        callers fail closed rather than reading silence as permission.
        """
        s = self.settings
        from agent_control import AgentControlClient
        from agent_control_models import EvaluationRequest, EvaluationResponse, Step

        from app.observability.sdk import stream_id_of

        stream_id = stream_id_of(logger)
        if not stream_id:
            raise ValueError("No resolved log stream")
        target_id = str(stream_id)
        request = EvaluationRequest(
            agent_name=s.resolved_agent_name,
            target_type="log_stream",
            target_id=target_id,
            stage=stage,
            step=Step(
                type=step_type, name=step_name, input=step_input, output=step_output, context=context
            ),
        )
        async with AgentControlClient(
            base_url=s.agent_control_url,
            timeout=10,
            api_key=s.galileo_api_key.get_secret_value(),
            api_key_header=s.agent_control_api_key_header,
            runtime_auth_mode=s.agent_control_runtime_auth_mode,
            # Omitted when blank: the SDK rejects an empty header name, and its own default is a
            # Bearer token on Authorization, which is what the Galileo gateway requires.
            **(
                {"runtime_token_header": s.agent_control_runtime_token_header}
                if s.agent_control_runtime_token_header
                else {}
            ),
        ) as client:
            response = await asyncio.wait_for(
                client.post_runtime_evaluation(
                    json=request.model_dump(mode="json"), target_type="log_stream", target_id=target_id
                ),
                15,
            )
            response.raise_for_status()
            result = EvaluationResponse.model_validate(response.json())
        # Empty results do not prove a bound control ran. Errors always fail closed.
        #
        # Three very different causes used to collapse into one message: the request failing, the
        # control erroring, and nothing selecting the control at all. Each needs a different fix,
        # so the diagnosis travels with the decision rather than being guessed at afterwards.
        evaluated = (result.matches or []) + (result.non_matches or [])
        if result.errors or not evaluated:
            raise ControlNotEvaluated(
                {
                    "cause": "control_errored" if result.errors else "no_control_selected",
                    "matches": len(result.matches or []),
                    "non_matches": len(result.non_matches or []),
                    "errors": [str(e)[:200] for e in (result.errors or [])],
                    "agent_name": s.resolved_agent_name,
                    "target": f"log_stream/{target_id}",
                    "stage": stage,
                    "step_type": step_type,
                    "step_name": step_name,
                }
            )
        return result, evaluated

    def _details(self, result, evaluated, allow_action, deny_action):
        return {
            "decision": "allow" if result.is_safe else "deny",
            "source": "galileo-agent-control",
            "verified": True,
            "confidence": result.confidence,
            "controls": [
                {
                    "id": x.control_id,
                    "name": x.control_name,
                    "action": x.action,
                    "result": x.result.model_dump(mode="json"),
                }
                for x in evaluated
            ],
            "reason": result.reason,
            "action": allow_action if result.is_safe else deny_action,
        }

    def _log_controls(self, logger, evaluated, result, span_input, applies_to, stage, details):
        try:
            import json

            from galileo_core.schemas.logging.control import ControlResult

            # add_control_span takes a string and swallows every exception it raises, returning
            # None. The action gate passes the tool-call arguments, which are a dict, so the span
            # that proves a control ran was silently dropped on exactly the path that needs it --
            # no span, no error, not even the control_telemetry marker below.
            if not isinstance(span_input, str):
                span_input = json.dumps(span_input, default=str)

            for control in evaluated:
                span = logger.add_control_span(
                    input=span_input,
                    name=control.control_name,
                    output=ControlResult(
                        action=control.action,
                        matched=control in (result.matches or []),
                        confidence=result.confidence,
                    ),
                    control_id=str(control.control_id),
                    agent_name=self.settings.resolved_agent_name,
                    check_stage=stage,
                    applies_to=applies_to,
                )
                if span is None:
                    # The SDK refused it and told nobody. Record that rather than implying the
                    # control's own evidence reached the trace.
                    details["control_telemetry"] = "span_rejected"
                    continue
                logger.conclude()
        except Exception:  # noqa: BLE001 - isolate SDK failures without exposing credential-bearing errors
            # Logging failure cannot change the already verified gate decision.
            details["control_telemetry"] = "failed"

    async def check_action(self, tool_name, arguments, logger, enabled):
        """Gate a tool call before it executes.

        The answer gate cannot help for an action: by the time a candidate answer exists the tool
        has already run and the money has already moved. This evaluates at the `pre` stage, where
        the step carries no output because the action has not happened yet. The first return value
        says whether the call may proceed, so a denial means the tool is never invoked.
        """
        if not enabled:
            return True, {"decision": "disabled", "source": "application", "verified": False}
        if not self._configured(logger):
            return False, self._unavailable(
                "Protection is not fully configured", {"cause": "not_configured"}
            )
        try:
            result, evaluated = await self._evaluate(
                logger,
                stage="pre",
                step_type="tool",
                step_name=tool_name,
                step_input=arguments,
                step_output=None,
                context={"execution": "pre_tool_gate"},
            )
            details = self._details(result, evaluated, "execute", "block")
            self._log_controls(logger, evaluated, result, arguments, "tool_call", "pre", details)
            self._record("pre", "verified")
            return result.is_safe, details
        except ControlNotEvaluated as exc:
            # The gate answered; nothing was scoped to this step. Not a failure.
            self._record("pre", "no_control", exc.diagnosis)
            return False, self._unavailable("No control evaluated this action", exc.diagnosis)
        except Exception as exc:  # noqa: BLE001 - sanitize credential-bearing SDK errors
            diagnosis = self._failure(exc)
            self._record("pre", "failed", diagnosis)
            return False, self._unavailable("Protection request failed", diagnosis)

    async def check(self, candidate, prompt, evidence, logger, enabled):
        if not enabled:
            return candidate, {"decision": "disabled", "source": "application", "verified": False}
        if not self._configured(logger):
            diagnosis = {"cause": "not_configured"}
            self._record("post", "failed", diagnosis)
            return FALLBACK, self._unavailable("Protection is not fully configured", diagnosis)
        try:
            result, evaluated = await self._evaluate(
                logger,
                stage="post",
                step_type="llm",
                step_name="customer-visible-answer",
                step_input=prompt,
                step_output=candidate,
                context={"evidence": evidence, "execution": "candidate_output_gate"},
            )
            details = self._details(result, evaluated, "deliver", "safe_fallback")
            self._log_controls(logger, evaluated, result, candidate, "llm_call", "post", details)
            self._record("post", "verified")
            return candidate if result.is_safe else FALLBACK, details
        except ControlNotEvaluated as exc:
            # Expected when every control is scoped to a tool: this gate inspects the answer, so
            # nothing applies to it. Reporting that as a failure made a working guardrail look broken.
            self._record("post", "no_control", exc.diagnosis)
            return FALLBACK, self._unavailable("No control evaluated this answer", exc.diagnosis)
        except Exception as exc:  # noqa: BLE001 - sanitize credential-bearing SDK errors
            diagnosis = self._failure(exc)
            self._record("post", "failed", diagnosis)
            return FALLBACK, self._unavailable("Protection request failed", diagnosis)
