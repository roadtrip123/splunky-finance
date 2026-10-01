# Splunky Finance — outstanding work

Ordered by what would hurt most if left undone. Items marked **before the workshop** are the ones
with a date attached to them.

## Support Splunk AO alongside Galileo

Splunky Finance logs through the `galileo` package. Splunk Agent Observability uses `splunk_ao`,
which is the same core rebranded — it imports `galileo_core` internally and the span methods have
identical names. `~/healthcare-assistant` is already fully on `splunk_ao` and is the reference for
the parts that differ.

**Coexistence is proven.** `uv pip install --dry-run splunk-ao==0.4.0` into the backend venv
resolves with nothing removed or downgraded: both packages need `galileo-core` and the ranges
overlap (`>=4.4,<5` and `>=4.5,<5`) on the installed 4.5.0. It adds `splunk-ao` plus the OTLP
exporter stack, 11 packages.

**The seam already exists.** Every SDK reference is a lazy import inside a method — 8 in
`app/observability/galileo.py`, 1 in `protection.py`, 1 in `main.py`. No module-level coupling.

The differences are renames, each checked against the 0.4.0 wheel:

| | `galileo` | `splunk_ao` |
| --- | --- | --- |
| Logger | `GalileoLogger` | `SplunkAOLogger` |
| LangChain callback | `GalileoAsyncCallback` | `SplunkAOAsyncCallback` |
| Enable metrics | `enable_metrics(log_stream_name=…)` | `enable_evaluators(agent_stream_name=…)` |
| Resolve stream | `get_log_stream` | `get_agent_stream` |
| Scorer enum | `Scorers` | `SplunkAOEvaluators` |
| Stream id attribute | `logger.log_stream_id` | `logger.agent_stream_id` |
| `ControlResult` | `galileo_core.schemas.logging.control` | `splunk_ao.logger.control` |
| Span methods | identical | identical |

`enable_evaluators` is signature-identical to `enable_metrics` apart from that one keyword.

### Stages

- [ ] **Stage 0 — spike, ~20 min.** Install `splunk-ao` in a scratch venv, log one trace with an
      injected fault, and confirm `mask_genuine_answer` still empties the genuine answer out of
      every span when the export path is OTLP. Everything below is pointless if this fails: if the
      masking does not survive, the completeness judge goes back to reading the agent's full draft.
- [ ] **Stage 1 — extract the adapter, Galileo only.** A `sdk(provider)` returning `Logger`,
      `Callback`, `enable_metrics`, `get_stream`, `Scorers`, `Traces`, `ControlResult` and a
      `stream_id(logger)` helper. Roughly 60 lines. No behaviour change, no new provider, suite
      still green. Safe to land at any time.
- [ ] **Stage 2 — add `splunk_ao` behind the same seam**, with the standalone/o11y credential sets.
      Copy the mode handling from `~/healthcare-assistant/setup_env.py`, including the part that
      **deletes the unselected mode's environment variables** — both SDKs self-configure from the
      environment, so a stale export silently routes to the wrong backend. That is the subtle
      failure to design against, not the imports.
- [ ] **Stage 3 — rename the user-facing wording.** "Galileo" appears 68 times in the frontend and
      55 in docs, and log stream becomes agent stream. Drive it off the active provider. Last,
      because it is cosmetic and touches everything.

Expect `BUILTIN_METRICS` to need a per-provider map: tenant metric slugs differ. The existing
preflight that checks names against the tenant before enabling will catch it.

**Not before the workshop.** Stages 0 and 1 are safe now; Stage 2 changes how a working demo
reaches its tenant.

## Before the workshop

- [ ] **Prove the guardrail returns a verified deny.** It blocks, but by failing closed:
      `action_decisions` has read `decision: "unavailable"`, never `verified: true`. Both controls
      have since been refreshed and the second bound, so it may already work — nobody has checked.
      Part 7 is the close of the demo and rests on this.
- [ ] **Check for spare control clones** in the console. `clone_and_bind_control` clones as well as
      binds, and a duplicate clone is what previously made the runtime return `unavailable`.
      Current: `splunky-transfer-deny` 886 with clone 887, `splunky-account-lookup-deny` 1029 with
      clone 1030.
- [ ] **Rehearse the participant path.** `python3 scripts/workshop.py up --count 2 --host <private
      ip> --base-port 3200`, then walk one instance through [docs/workshop-lab.md](docs/workshop-lab.md)
      end to end. Participants build the metrics and controls by hand and that path has only ever
      been exercised by the script.
- [ ] **Rotate the Sharon AI key.** `tv-pat-4da4…` was pasted into a chat transcript. Re-run
      `scripts/check_endpoint.py` once their tool calling is enabled.

## Smaller

- [ ] **Settle the completeness judge.** It scores correctly on 8 of 10 runs. Two candidate causes
      point opposite ways — an `unverified_rewrite` shipping a complete answer, or judge variance —
      and `fault_method` on a trace that scored `true` distinguishes them. If it is variance, the
      lever is `JUDGE_COUNT` 3 → 5, about two thirds more cost for that metric.
- [ ] **Re-run Wrong Customer** and replace the expected row in DEMO-SCRIPT.md with an observed one.
- [ ] **Playwright journey test** is corrected but unverified; it cannot run on this host because
      port 8001 is occupied.
- [ ] **Retired metrics still visible in the tenant** (`SplunkyCompleteness`, `SplunkyEntityIntegrity`,
      `SplunkyRequestCoverage`, `Splunky Context Adherence`). Not enabled, and only their creator can
      delete them, but participants will see them in the picker. Worth a line in the briefing.

## Healthcare assistant

Separate repository, `~/healthcare-assistant`. Already on `splunk_ao`; these are gaps found while
reading it as the reference for the work above.

- [ ] **`OTEL_SERVICE_NAME` is never set** — not in `setup_env.py`, not in either manifest. The SaaS
      path exports over OTLP, so the service shows as `unknown_service` in APM.
- [ ] **`splunk-ao-config` and `splunk-agent-control-config` ConfigMaps are not in the repo**, though
      both `k8s.yaml` and `k8s-o11y.yaml` reference them. The two manifests differ by one line
      (`SPLUNK_AO_API_KEY` → `SPLUNK_AO_O11Y_TOKEN`) but need different ConfigMap *contents* — realm
      for one, console URL for the other. Same name, incompatible contents, nothing in the repo to
      show which.
- [ ] **README is stale**: documents `agent_control_api_key_header = "Splunk-AO-Key"`, which matches
      neither mode (`Splunk-AO-API-Key` standalone, `X-SF-Token` o11y), and pins `>=7.10.0` where
      `requirements.txt` needs `>=8.5.0`.
