import asyncio

FALLBACK = "I couldn't verify that answer against the bank's policies. Please check the account terms or contact the bank for confirmation."
BLOCKED = "I can't complete that request. A transfer of this kind has to be confirmed with the bank directly."


class Protection:
    """Explicit candidate and action evaluation. No SDK-global toggles or model-selected protection tool."""

    def __init__(self, settings):
        self.settings = settings
        self.status = "unverified"

    def _unavailable(self, reason):
        return {
            "decision": "unavailable",
            "source": "application",
            "verified": False,
            "action": "safe_fallback",
            "reason": reason,
        }

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

        target_id = str(logger.log_stream_id)
        if not logger.log_stream_id:
            raise ValueError("No resolved log stream")
        request = EvaluationRequest(
            agent_name=s.agent_control_agent_name,
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
            runtime_auth_mode="jwt",
            runtime_token_header=s.agent_control_runtime_token_header,
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
        evaluated = (result.matches or []) + (result.non_matches or [])
        if result.errors or not evaluated:
            raise ValueError("No verified control evaluation")
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
            from galileo_core.schemas.logging.control import ControlResult

            for control in evaluated:
                logger.add_control_span(
                    input=span_input,
                    name=control.control_name,
                    output=ControlResult(
                        action=control.action,
                        matched=control in (result.matches or []),
                        confidence=result.confidence,
                    ),
                    control_id=str(control.control_id),
                    agent_name=self.settings.agent_control_agent_name,
                    check_stage=stage,
                    applies_to=applies_to,
                )
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
            return False, self._unavailable("Protection is not fully configured")
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
            self.status = "verified"
            return result.is_safe, details
        except Exception:  # noqa: BLE001 - isolate SDK failures without exposing credential-bearing errors
            self.status = "failed"
            return False, self._unavailable("Protection request failed or no control was evaluated")

    async def check(self, candidate, prompt, evidence, logger, enabled):
        if not enabled:
            return candidate, {"decision": "disabled", "source": "application", "verified": False}
        if not self._configured(logger):
            return FALLBACK, self._unavailable("Protection is not fully configured")
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
            self.status = "verified"
            return candidate if result.is_safe else FALLBACK, details
        except Exception:  # noqa: BLE001 - isolate SDK failures without exposing credential-bearing errors
            self.status = "failed"
            return FALLBACK, self._unavailable("Protection request failed or no control was evaluated")
