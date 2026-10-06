# Changelog

Versions mark states worth returning to. Tags are annotated, so `git tag -n` and
`git describe` both say something useful.

Open defects are tracked as [GitHub issues](https://github.com/roadtrip123/splunky-finance/issues);
planned work is in [TODO.md](TODO.md).

## v0.6.1 — What a hostile network does to a workshop

Deploying on a managed lab host turned up three environment failures, each of which looks like one of
the others. All three are now documented with the check that tells them apart.

- **Container egress can be hijacked by the host.** A blanket `nat PREROUTING ... --dport 443 -j
  REDIRECT` catches every packet *arriving on an interface*, so the host is unaffected while every
  container is redirected to a local server answering with an unrelated certificate. Both the
  dependency download and the running backend's model endpoint fail. The fix is a `RETURN` for
  Docker's bridges, not a trusted CA — a name mismatch is not a trust failure, and no certificate
  makes the name match. It does not survive a reboot.
- **`BUILD_NETWORK`** puts the image build on the host's network as a fallback where the firewall
  cannot be changed, since the build's packets then originate from the host and miss PREROUTING. It
  defaults to `default` and fixes the build only.
- **TLS on a bare IP requires `default_sni`.** TLS forbids sending SNI for an IP address, so browsers
  and curl send no server name and the proxy has nothing to select a certificate by. It logs
  `certificate obtained successfully`, binds the port, and aborts every handshake with an internal
  error. `scripts/Caddyfile.selfsigned` now carries it, with `skip_install_trust` to stop the local CA
  install failing noisily on every start.
- **The proxy's ports are computed arithmetically.** The old loop concatenated digits, so without
  `seq -w` the first participant got port 311 — bound successfully, reachable by nobody.
- **Reachability has to be checked from outside the network, before building fifty stacks.** Every
  test run on the instance passes regardless, and an EC2 instance cannot reach its own public IP at
  all. A dropped packet means a security group; a refusal means nothing is listening. Some lab
  environments publish one port, and a port per participant cannot work there.
- The bootstrap section now opens with the reachability check, pins `v0.6.1`, and includes installing
  Caddy — along with the warning that the package starts `caddy.service` immediately, so it owns
  `/etc/caddy/Caddyfile` and port 2019 and must be driven with `systemctl` rather than `caddy run`.
- The CA-trust section of `docs/workshop.md` is rewritten. It previously showed a name-mismatch error
  and prescribed the fix for an issuer error; the two now appear separately, and
  `backend/ca/README.md` says plainly which one it does not fix.

## v0.6.0 — Two ways to reach it

- **The private-network path is now a documented deployment, not a rehearsal footnote.**
  `ALLOW_PRIVATE_LAN_HTTP=true` plus a private address needs no DNS and no certificates, which is
  the short path when participants are on a network that routes to the instance. The trade-off is
  stated where the decision is made: step 2 of the lab has each participant paste their own Galileo
  API key, and on plain HTTP that key crosses the network in cleartext. The synthetic data and the
  read-aloud passwords are not what the rule protects.
- The public HTTPS path keeps its own section, with the `sslip.io` option for a box with no domain
  and the reason to use one hostname rather than fifty subdomains.
- The rehearsal section now lists what a human has to do rather than only how to start two stacks —
  create the Agent Control agent, attach the controls to it, and check `action_decisions` reads
  `verified: true`. Those are the two steps that only fail against a real tenant.

## v0.5.2 — Nothing to edit in .env

- The two demo passwords are fixed in the template — `-AlexDemo1234!` and `PresenterDemo1234!`.
  A workshop hands the same pair to everyone and a presenter reads them aloud, so a random pair
  per box only meant editing every box. They are shared and fixed, so anyone who can reach an
  instance and knows them can sign in: a demo on synthetic data and nothing else. The session
  secret stays random and unshared, because it signs cookies.
- The model endpoint is configured in the presenter portal, so the bootstrap no longer asks for it
  in `.env`. Nothing in the generated file needs editing for a workshop.
- The lab sheet carries both passwords directly rather than telling participants to ask.

## v0.5.1 — Workshop corrections

Two fixes a workshop needs, found while preparing one. Nothing else changes.

- **The lab sheet never told participants to create an Agent in Agent Control.** The runtime route
  looks the agent up by name and answers 404 when it does not exist, at which point the
  application fails closed: the action is blocked, the guardrail looks like it worked, and no
  control evaluated anything. Every participant would have hit it and drawn the wrong conclusion.
  The lab now creates the agent first, and says that binding a control to a stream and attaching
  it to an agent are two different things.
- **A participant's session secret is kept across a re-provision.** `workshop.py up` rewrote each
  env file with a fresh `SESSION_SECRET`, so deploying a new version logged the whole room out.

Also documents the update itself — re-run `up` with the same arguments, no `down` first — and what
survives because it lives in the `runtime-data` volume rather than the image: Galileo credentials,
model endpoints, dataset and transfers.

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
