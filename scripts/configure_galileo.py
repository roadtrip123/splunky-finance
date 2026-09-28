"""Explicit remote setup; run from backend with PYTHONPATH=. .venv/bin/python."""

import argparse
import asyncio

from app.config import Settings
from app.observability.galileo import Telemetry
from app.observability.setup_definitions import (
    BUILTIN_METRICS,
    CONTROLS,
    JUDGE_COUNT,
    JUDGE_MODEL,
    JUDGE_PROMPT_SUFFIX,
    JUDGES,
)


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
        help="Publish a new version of each custom judge so edited prompts and settings take "
        "effect. Existing judges are otherwise left untouched.",
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
        existing = Scorers().list(name=name)
        if args.refresh_judges and existing:
            # A new version rather than delete and recreate: deletion is refused for anyone but the
            # metric's original creator, and versioning keeps the judge's scoring history.
            from galileo.metrics import (
                CreateLLMScorerVersionRequest,
                GalileoPythonConfig,
            )
            from galileo.metrics import (
                create_llm_scorer_version_scorers_scorer_id_version_llm_post as publish_version,
            )

            published = publish_version.sync(
                scorer_id=str(existing[0].id),
                client=GalileoPythonConfig.get().api_client,
                body=CreateLLMScorerVersionRequest(
                    user_prompt=instructions + JUDGE_PROMPT_SUFFIX,
                    model_name=JUDGE_MODEL,
                    num_judges=JUDGE_COUNT,
                    output_type=OutputTypeEnum.BOOLEAN,
                    cot_enabled=True,
                ),
            )
            print(f"{name}: published version {getattr(published, 'version', '?')}")
        if not existing:
            print(f"{name}: created")
            create_custom_llm_metric(
                name=name,
                user_prompt=instructions + JUDGE_PROMPT_SUFFIX,
                node_level=StepType.trace,
                output_type=OutputTypeEnum.BOOLEAN,
                model_name=JUDGE_MODEL,
                num_judges=JUDGE_COUNT,
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
            found = (existing.get("controls") or [None])[0]
            if found:
                identifier = found.get("control_id") or found.get("id")
                print(f"{name}: reusing existing control.")
            else:
                identifier = (await create_control(client, name=name, data=definition))["control_id"]
                print(f"{name}: created.")
            # Bind every time. The control is tenant-wide but the binding is per log stream, so
            # skipping this for an existing control leaves that stream with no guardrail at all.
            await clone_and_bind_control(
                client,
                control_id=identifier,
                target_type="log_stream",
                target_id=str(logger.log_stream_id),
                enabled=True,
            )
            print(f"{name}: bound to {s.galileo_log_stream}.")
    print(
        "Metric setup requested. Verify sampling, metric scores, and control binding in the tenant console."
    )


if __name__ == "__main__":
    asyncio.run(main())
