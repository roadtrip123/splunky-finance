"""Explicit remote setup; run from backend with PYTHONPATH=. .venv/bin/python."""

import argparse
import asyncio

from app.config import Settings
from app.observability.galileo import Telemetry


def _deny_control(pattern):
    """Server-side regex deny on the delivered candidate.

    Scoped to the `customer-visible-answer` LLM span, which the application logs for exactly this
    purpose. A regex rejects a controlled contradiction known before the demo; it is not a general
    semantic validator.
    """
    return {
        "condition": {
            "selector": {"path": "output"},
            "evaluator": {"name": "regex", "config": {"pattern": pattern}},
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


CONTROLS = {
    "splunky-seeded-policy-deny": _deny_control("(?i)unlimited daily external transfer limit"),
    # Anchored on ASCII so the pattern does not depend on the masked-number bullet characters.
    "splunky-wrong-customer-deny": _deny_control("(?i)(dan whitfield|4127)"),
}
# Custom judges earn their place only where no built-in can know the rule. SplunkyGroundedness was
# retired because built-in Context Adherence scores the same thing against the retriever span.
# Each judge fails only on a contradiction it can point to. A judge that also failed when its
# subject was simply absent went red on every fault, whichever fault it was, and the
# one-metric-per-scenario story collapsed: an answer with its total removed was reported as having
# a wrong total and a wrong customer.
JUDGES = {
    "SplunkyRequestCoverage": (
        "Decide whether candidate_output answers every part the input asked for. Derive the "
        "required parts from the input itself; do not assume a fixed list. Return false only when "
        "a part of the question is left unanswered. Evaluate candidate_output, not final_output."
    ),
    "SplunkyNumericalCorrectness": (
        "Decide whether the money amounts and counts stated in candidate_output agree with "
        "evidence.calculations, which holds integer AUD cents; a dollar is 100 cents. Return false "
        "only when a stated figure disagrees with that evidence. If candidate_output states no "
        "money amount and no count, return true: there is nothing to contradict, and an answer "
        "that omits a figure is a different fault measured by another metric. Evaluate "
        "candidate_output, not final_output."
    ),
    "SplunkyEntityIntegrity": (
        "Decide whether every customer name, first name, and masked account number in "
        "candidate_output matches evidence.customer and evidence.accounts. Return false only when "
        "the candidate names a different person, or cites an account the authenticated customer "
        "does not own. If candidate_output names no person and cites no account number, return "
        "true: identity was not misstated. Evaluate candidate_output, not final_output."
    ),
}
# Galileo's own evaluators. Context Adherence and Completeness read the retriever span the policy
# retriever emits; the tool metrics score the agent's tool use. These names are resolved against the
# tenant, not a fixed list, and the available set differs between tenants: this one exposes Action
# Completion only as the small-language-model `_luna` variant.
BUILTIN_METRICS = [
    "context_adherence",
    "completeness",
    "tool_selection_quality",
    "tool_error_rate",
    "action_completion_luna",
]


async def main():
    from agent_control_models import ControlDefinition

    for definition in CONTROLS.values():
        ControlDefinition.model_validate(definition)
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Create remote custom judges and a bound control",
    )
    parser.add_argument(
        "--refresh-judges",
        action="store_true",
        help="Delete and recreate the custom judges so edited prompts take effect. "
        "Existing judges are otherwise left alone, and their historical scores are lost.",
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
    from galileo.log_streams import enable_metrics
    from galileo.metrics import create_custom_llm_metric
    from galileo.resources.models.output_type_enum import OutputTypeEnum
    from galileo.scorers import Scorers
    from galileo_core.schemas.logging.step import StepType

    logger = GalileoLogger(project=s.galileo_project, log_stream=s.galileo_log_stream)
    for name, instructions in JUDGES.items():
        if args.refresh_judges and Scorers().list(name=name):
            from galileo.metrics import delete_metric

            delete_metric(name=name)
            print(f"{name}: deleted for refresh")
        if not Scorers().list(name=name):
            print(f"{name}: created")
            create_custom_llm_metric(
                name=name,
                user_prompt=instructions
                + " The trace output is JSON containing candidate_output and evidence. Judge only"
                " what candidate_output actually claims: the absence of a claim is not a failure.",
                node_level=StepType.trace,
                output_type=OutputTypeEnum.BOOLEAN,
                model_name="gpt-4.1-mini",
                num_judges=1,
            )
    # Resolve names first: enable_metrics raises a bare ValueError naming only the unknown entries,
    # which is hard to act on when the valid set is tenant-specific.
    available = {str(getattr(row, "name", "")) for row in Scorers().list()}
    missing = [name for name in BUILTIN_METRICS if name not in available]
    if missing:
        raise SystemExit(
            "These metrics do not exist in this tenant: "
            + ", ".join(missing)
            + ". List the tenant's scorers and update BUILTIN_METRICS; names vary between tenants."
        )
    enable_metrics(
        project_name=s.galileo_project,
        log_stream_name=s.galileo_log_stream,
        metrics=list(JUDGES) + BUILTIN_METRICS,
    )
    from agent_control import AgentControlClient
    from agent_control.controls import (
        clone_and_bind_control,
        create_control,
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
        for name, definition in CONTROLS.items():
            existing = await list_controls(client, name=name, limit=10)
            # Avoid accidental duplicate controls: inspect existing configuration in console first.
            if existing.get("controls"):
                print(
                    f"{name}: listing returned existing data; inspect binding in console. No duplicate created."
                )
                continue
            control = await create_control(client, name=name, data=definition)
            await clone_and_bind_control(
                client,
                control_id=control["control_id"],
                target_type="log_stream",
                target_id=str(logger.log_stream_id),
                enabled=True,
            )
            print(f"{name}: created and bind requested.")
    print(
        "Metric setup requested. Verify sampling, metric scores, and control binding in the tenant console."
    )


if __name__ == "__main__":
    asyncio.run(main())
