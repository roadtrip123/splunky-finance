# Changelog

Versions mark states worth returning to. Tags are annotated, so `git tag -n` and
`git describe` both say something useful.

Open defects are tracked as [GitHub issues](https://github.com/roadtrip123/splunky-finance/issues);
planned work is in [TODO.md](TODO.md).

## v0.5.0 — The guardrail actually decides

**The guardrail returns a verified deny.** Until now every armed run blocked by failing closed —
correct, and not the same as a Galileo control voting. It now reports
`decision: "deny", source: "galileo-agent-control", verified: true`, naming the control that
matched and why. Three causes, none of them a tenant permission:

- The runtime token rode the wrong header. The SDK defaults to a Bearer token on `Authorization`,
  resolved param → env → default, and `.env` carried the Splunk header copied from
  `~/healthcare-assistant`, where a gateway injects its own `Authorization`. On the Galileo
  gateway that moves the token off the only header the route reads. Now per backend.
- The agent named in `AGENT_CONTROL_AGENT_NAME` did not exist. Agents cannot be created from the
  SDK, so the name must already exist in the Agent Control console.
- Binding a control to a log stream does not attach it to an agent, and the runtime route looks
  the agent up by name — which is why the console looked correctly configured while every call
  failed. `configure_galileo.py` now attaches each control to the agent.

**The numerical judge reads every evidence key.** It was written against `evidence.calculations`,
where the spending tool writes, so every figure stated about a balance (`evidence.lookups`) or a
money movement (`evidence.transfers`) went unchecked. A transfer answer reported the customer's
balance as Dan's — wrong by $15,883.55 — and all three judges passed it.

Widening the keys was not enough on its own: the mis-stated number *was* in the evidence under the
other account, and the judge rationalised that, catching it 1 run in 3. It now has to work out
which account a figure is attributed to before comparing. Verified three runs each: mis-attributed
balance false 3/3, correct balance true 3/3, correct spending answer true 3/3, wrong total
false 3/3.

**Splunk AO is labelled Beta** beside the switch that selects it and in the status card, with one
line saying what is missing and why. Traces and sessions arrive correctly; the custom judges, the
guardrail's control target and fault masking do not work there yet.

Also fixed: deriving the Splunk AO Agent Control URL overwrote `agent_control_url` and nothing
restored it, so after one visit to Splunk AO every Galileo guardrail call went to the Splunk
gateway. The failure diagnosis now carries the HTTP status and a hint, which is what turned that
investigation from guesswork into two specific findings.

Corrected on the record: Splunk AO standalone was said to flush through an ingest request like
Galileo. It does not — both AO deployments are OTLP, so every OTLP consequence applies to both.

## v0.4.0 — Money moves both ways

- A transfer may name another customer as its **source**, not only its destination.
  `transfer_funds` takes `from_account`, defaulting to the customer's Everyday account, so the
  agent will take $1,000 out of Tom's account as readily as it will send money to him. Sending to
  the wrong person is a mistake; taking from someone who never authorised it is theft, and it is
  the same tool call.
- The guardrail needed no change for it. The control matches the whole tool input, so a source is
  as visible as a destination — confirmed for both account numbers and both names, while
  own-account transfers still pass.
- **Normal Answer / Disabled Guardrails** now offers every guardrail action with nothing gating
  it, as a second labelled group of questions. That is the "before" half of the guardrail demo,
  runnable without switching scenario. The eight prompts are one shared list, so the ungated and
  gated sets cannot drift apart.
- [docs/instrumentation.md](docs/instrumentation.md) explains how a turn reaches Galileo in the
  twenty lines that matter, with code that runs as written. Written for the workshop.

Fixed: a transfer returned a bare `new_balance_cents`, unambiguous only while the source was
always the customer's own account. After a pull the agent reported the customer's new balance as
Dan's — wrong by $15,883.55, with the ledger correct throughout. Every figure is now named.

That one is worth reading [issue #8](https://github.com/roadtrip123/splunky-finance/issues/8)
about: no evaluator caught it, because the numerical judge compares against
`evidence.calculations` and a transfer writes to `evidence.transfers`. All three judges passed the
answer. It was found by a human asking the obvious follow-up question.

## v0.3.0 — Splunk Agent Observability

Galileo remains the default and is unchanged in behaviour.

- Observability backend is switchable between Galileo and Splunk Agent Observability, from the
  Demo and Setup tabs. One active at a time: two would leave Agent Control without an
  adjudicator, and two tenants disagreeing on one tool call has no good answer.
- Every SDK reference lives behind one seam, `app/observability/sdk.py`. `splunk_ao` is the same
  core rebranded, so the gap is renames: logger, callback, `enable_evaluators`, `get_agent_stream`,
  `agent_stream_id`, and the `Traces` constructor.
- Both Splunk AO deployments are supported — Observability Cloud, needing a realm and an access
  token, and standalone, needing an API key and a console URL. The portal shows one set at a time
  with every field marked required or optional and a note on where to find it.
- `configure_environment` deletes the inactive backend's variables. `splunk_ao` bridges
  `SPLUNK_AO_*` into the `GALILEO_*` names, so a stale value points a backend at the wrong
  credential, silently.
- Agent Control's gateway header and URL follow the active backend and deployment.

Fixed along the way: the connection check assumed a logger that resolves ids through the API, which
OTLP does not; `begin()` read `log_stream_id` directly and so created a session but never a trace;
and the session was bound in a worker thread's context, leaving the named session empty while the
backend invented a second one to hold the spans.

## v0.2.0 — Evaluation that holds up

- Five scenarios with span-by-span flows in [docs/scenario-flows.md](docs/scenario-flows.md),
  drawn from real exported traces.
- Tom Whitfield and Dan Whitfield are real customers, reachable by account number or name, so the
  guardrail prevents a genuine cross-customer exposure and Wrong Customer leaks a real balance.
- The guardrail is a deny-list on those accounts rather than a match-everything rule, so the
  customer's own banking keeps working while it is armed.
- Each judge is scoped to one property, reads the question from the record, and is told to ignore
  the agent's own spans and the evidence. Four separate defects, each found by a judge scoring a
  correct answer wrongly or a faulty one as fine.
- The genuine answer is masked out of every span before export, so a judge cannot read the
  pre-injection draft.
- The injected fault is verified and imposed in code when the model will not produce it, so the
  scenario behaves the same on every model.

## v0.1.0 — The demo

Fictional Australian bank, deterministic dataset, tool-backed LangChain agent, presenter portal,
Galileo evaluation and Agent Control guardrails, and a workshop provisioner for one isolated stack
per participant.
