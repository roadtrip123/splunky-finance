"""Explicit remote setup; run from backend with PYTHONPATH=. .venv/bin/python."""

import argparse
import asyncio
from app.config import Settings
from app.observability.galileo import Telemetry

CONTROL = {
    "condition": {
        "selector": {"path": "output"},
        "evaluator": {
            "name": "regex",
            "config": {"pattern": "(?i)unlimited daily external transfer limit"},
        },
    },
    "execution": "server",
    "scope": {
        "step_types": ["llm"],
        "step_names": ["customer-visible-answer"],
        "stages": ["post"],
    },
    "action": {"decision": "deny"},
    "enabled": True,
}
JUDGES = {
    "SplunkyCompleteness": "Return true only if candidate_output answers every requested part of the input. For restaurant detail requests require total, transaction count, three biggest transactions, and prior-month comparison. Evaluate the candidate, not final_output.",
    "SplunkyGroundedness": "Return true only if every banking policy assertion in candidate_output is supported by evidence.policies. The seeded external transfer limit is AUD 5000 daily and verification is required; an unlimited/no-verification claim is false. Evaluate the candidate, not final_output.",
    "SplunkyNumericalCorrectness": "Return true only if all candidate_output money totals and counts agree with evidence.calculations, which uses integer AUD cents. A dollar is 100 cents. Evaluate the candidate, not final_output.",
}


async def main():
    from agent_control_models import ControlDefinition

    ControlDefinition.model_validate(CONTROL)
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Create remote custom judges and a bound control",
    )
    args = parser.parse_args()
    if not args.apply:
        print(
            "Control schema valid. Remote setup not performed; use --apply explicitly."
        )
        return
    s = Settings()
    if (
        not s.galileo_enabled
        or not s.agent_control_url
        or not s.galileo_api_key.get_secret_value()
    ):
        raise SystemExit("Configure Galileo and Agent Control in .env first")
    Telemetry(s).configure_environment()
    from galileo import GalileoLogger
    from galileo.metrics import create_custom_llm_metric
    from galileo.scorers import Scorers
    from galileo.log_streams import enable_metrics
    from galileo_core.schemas.logging.step import StepType
    from galileo.resources.models.output_type_enum import OutputTypeEnum

    logger = GalileoLogger(project=s.galileo_project, log_stream=s.galileo_log_stream)
    for name, instructions in JUDGES.items():
        if not Scorers().list(name=name):
            create_custom_llm_metric(
                name=name,
                user_prompt=instructions
                + " The trace output is JSON containing candidate_output and evidence. Return false when required evidence is absent.",
                node_level=StepType.trace,
                output_type=OutputTypeEnum.BOOLEAN,
                model_name="gpt-4.1-mini",
                num_judges=1,
            )
    enable_metrics(
        project_name=s.galileo_project,
        log_stream_name=s.galileo_log_stream,
        metrics=list(JUDGES),
    )
    from agent_control import AgentControlClient
    from agent_control.controls import (
        create_control,
        clone_and_bind_control,
        list_controls,
    )

    async with AgentControlClient(
        base_url=s.agent_control_url,
        timeout=30,
        api_key=s.galileo_api_key.get_secret_value(),
        api_key_header=s.agent_control_api_key_header,
        runtime_auth_mode="jwt",
        runtime_token_header=s.agent_control_runtime_token_header,
    ) as client:
        existing = await list_controls(
            client, name="splunky-seeded-policy-deny", limit=10
        )
        # Avoid accidental duplicate controls: inspect existing configuration in console first.
        if existing.get("controls"):
            print(
                "Control listing returned existing data; inspect binding in console. No duplicate created."
            )
        else:
            control = await create_control(
                client, name="splunky-seeded-policy-deny", data=CONTROL
            )
            identifier = control["control_id"]
            await clone_and_bind_control(
                client,
                control_id=identifier,
                target_type="log_stream",
                target_id=str(logger.log_stream_id),
                enabled=True,
            )
    print(
        "Metric setup requested. Verify sampling, metric scores, and control binding in the tenant console."
    )


if __name__ == "__main__":
    asyncio.run(main())
