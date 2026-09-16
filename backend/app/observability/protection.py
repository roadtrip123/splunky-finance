import asyncio

FALLBACK = "I couldn't verify that answer against the bank's policies. Please check the account terms or contact the bank for confirmation."


class Protection:
    """Explicit post-candidate evaluation. No SDK-global toggles or model-selected protection tool."""

    def __init__(self, settings):
        self.settings = settings
        self.status = "unverified"

    async def check(self, candidate, prompt, evidence, logger, enabled):
        if not enabled:
            return candidate, {"decision": "disabled", "source": "application", "verified": False}
        s = self.settings
        if (
            not s.galileo_enabled
            or not logger
            or not s.agent_control_url
            or not s.galileo_api_key.get_secret_value()
        ):
            return FALLBACK, {
                "decision": "unavailable",
                "source": "application",
                "verified": False,
                "action": "safe_fallback",
                "reason": "Protection is not fully configured",
            }
        try:
            from agent_control import AgentControlClient
            from agent_control_models import EvaluationRequest, EvaluationResponse, Step

            target_id = str(logger.log_stream_id)
            if not logger.log_stream_id:
                raise ValueError("No resolved log stream")
            request = EvaluationRequest(
                agent_name=s.agent_control_agent_name,
                target_type="log_stream",
                target_id=target_id,
                stage="post",
                step=Step(
                    type="llm",
                    name="customer-visible-answer",
                    input=prompt,
                    output=candidate,
                    context={"evidence": evidence, "execution": "candidate_output_gate"},
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
            # Empty results do not prove a bound output control ran. Errors always fail closed.
            evaluated = (result.matches or []) + (result.non_matches or [])
            if result.errors or not evaluated:
                raise ValueError("No verified control evaluation")
            details = {
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
                "action": "deliver" if result.is_safe else "safe_fallback",
            }
            try:
                from galileo_core.schemas.logging.control import ControlResult

                for control in evaluated:
                    logger.add_control_span(
                        input=candidate,
                        name=control.control_name,
                        output=ControlResult(
                            action=control.action,
                            matched=control in (result.matches or []),
                            confidence=result.confidence,
                        ),
                        control_id=str(control.control_id),
                        agent_name=s.agent_control_agent_name,
                        check_stage="post",
                        applies_to="llm_call",
                    )
                    logger.conclude()
            except Exception:  # noqa: BLE001 - isolate SDK failures without exposing credential-bearing errors
                # Logging failure cannot change the already verified gate decision.
                details["control_telemetry"] = "failed"
            self.status = "verified"
            return candidate if result.is_safe else FALLBACK, details
        except Exception:  # noqa: BLE001 - isolate SDK failures without exposing credential-bearing errors
            self.status = "failed"
            return FALLBACK, {
                "decision": "unavailable",
                "source": "application",
                "verified": False,
                "reason": "Protection request failed or no control was evaluated",
                "action": "safe_fallback",
            }
