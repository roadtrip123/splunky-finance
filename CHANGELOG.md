# Changelog

Versions mark states worth returning to. Tags are annotated, so `git tag -n` and
`git describe` both say something useful.

Open defects are tracked as [GitHub issues](https://github.com/roadtrip123/splunky-finance/issues);
planned work is in [TODO.md](TODO.md).

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
