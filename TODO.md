# Splunky Finance — outstanding work

Ordered by what would hurt most if left undone. Items marked **before the workshop** are the ones
with a date attached to them.

## Gate on resolved intent, not on the model's wording

**A demonstrated bypass.** The control matches literal digit runs against the raw tool input
(`\b1234\b`), while `Banking.resolve()` strips every non-digit before looking the account up. The
two disagree about what "1234" means, so a separator walks straight through:

| `to_account` | Control | Actually reaches |
| --- | --- | --- |
| `"1234"` | DENY | Tom Whitfield |
| `"#1234"` | DENY | Tom Whitfield |
| `"1 2 3 4"` | allow | **Tom Whitfield** |
| `"12-34"` | allow | **Tom Whitfield** |
| `"4-1-2-7"` | allow | **Dan Whitfield** |

A canonicalisation differential, which is the standard failure of any guardrail matching surface
content while the system acts on a normalised form. The control did what it was told; the control
and the resolver were told different things.

**Tightening the regex is the wrong fix** — it moves the goalposts to `"one two three four"`. Send
the gate what the tool is about to do instead. The app already computes it one line before it would
execute.

- [ ] `ActionGuard` takes the `banking` instance. It is constructed in the same scope as
      `build_tools(banking, evidence)`, so this is plumbing, not restructuring.
- [ ] `check_action` sends a canonical `step_input` rather than the raw arguments:
      ```json
      {"tool": "transfer_funds", "amount_cents": 10000,
       "target_account": "•••• 1234", "target_owner": "Tom Whitfield",
       "target_is_authenticated_customer": false,
       "raw_arguments": {"to_account": "12-34", "amount_cents": 10000}}
      ```
      Keep `raw_arguments` so the audit trail still shows what the model actually wrote.
- [ ] Control condition becomes a selector on `input.target_is_authenticated_customer` for `false`,
      replacing the generated name/number deny-list. `Step.input` accepts any JSON value and
      `ControlSelector.path` selects a slice of the step payload, so this is supported by the
      models. **Unverified against the live server:** dotted-path selection into a nested field
      needs one tenant test. If it is not supported, fall back to a regex on the whole input for
      `"target_is_authenticated_customer":\s*false`, which is equally paraphrase-proof because the
      app computed the value.
- [ ] `_foreign_account_pattern()` and its generated deny-list become unnecessary. Delete, along
      with the test that asserts the pattern only matches foreign accounts.
- [ ] Update the paste-ready JSON in [docs/workshop-lab.md](docs/workshop-lab.md) and the Agent
      Control section of [docs/evaluators.md](docs/evaluators.md), including the reason — "match
      the resolved action, not the wording" is the transferable lesson and a better lab exercise
      than copying a regex.
- [ ] Regression: the probe table above, asserting every row denies.

This also improves the demo. "The guardrail evaluates the resolved action, so rephrasing the
request does not help" is a stronger claim than showing a list of blocked account numbers — and it
survives the question a partner will ask, which is whether they can just word it differently.

**Not blocking the workshop.** The demo questions use the plain account number and work correctly.
Worth doing before anyone adversarial sees it.

### Two related weaknesses, same area

- [ ] **The gate is opt-in per run.** `check_action` returns `{"decision": "disabled"}` when the
      scenario is not armed. Deliberate — the demo shows the transfer executing, then blocks it —
      but it means the guardrail is a toggle, not an always-on control. Say so out loud rather than
      letting the room assume otherwise.
- [ ] **`GATED_TOOLS` is a hardcoded allowlist of two.** Add a money-moving tool and forget the
      tuple and it is ungated, silently. Deny-by-default, gating everything not on a read-only
      list, is the safer shape and is a small change.

Not a weakness, and worth stating when asked: there is **no code execution tool** — no `eval`,
`exec`, `subprocess` or REPL anywhere in the app — so the model cannot write and run a script to
reach the banking functions. It can only emit calls against the seven bound schemas, and every one
of those is logged as a span by the LangChain callback whether or not a control evaluated it. A
tool that ran would leave a `transfer_funds` span; the proof the block worked is that there is not
one.

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
