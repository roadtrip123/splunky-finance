# Changelog

Versions mark states worth returning to. Tags are annotated, so `git tag -n` and
`git describe` both say something useful.

Open defects are tracked as [GitHub issues](https://github.com/roadtrip123/splunky-finance/issues);
planned work is in [TODO.md](TODO.md).

## v0.6.8 — What the first real install found

Three defects, all in the install path, all found by running it on a fresh instance rather than by
reading it.

- **The shared update directory locked out the host.** It was given to the container's uid outright,
  so the account running the updater could no longer write the state file beside the container's
  request file. It is now `<owner>:10001` with mode `0770` — user for the host, group for the
  container. The symptom was `selfupdate.py` reporting it could not record what it did, after a
  successful build.
- **The proxy was verified the instant after `systemctl restart`.** Caddy provisions its internal
  certificate authority and binds after systemd reports the restart complete, so the check failed on
  a proxy that was already about to serve — and the installer reported a working deployment as
  broken. It now retries for twenty seconds, and if the local check still fails it says that the
  check goes through loopback and names the command to confirm from another machine, rather than
  asserting the proxy is down.
- **`[ ... ] && break` inside the retry loop** would have taken the script down under `set -e` on the
  first retry, which is the same trap already fixed once in the egress check.
- **`install.sh` now warns when a redirect for the chosen port is still in `/etc/iptables/rules.v4`
  or `/etc/rc.local`.** A rule deleted by hand comes back on the next boot, and on a box destined to
  become an AMI that means every clone starts with the port broken.

## v0.6.12 — Radios are not text fields

- **Radios and checkboxes no longer inherit text-field sizing.** The base stylesheet gives every
  `input` full width, a 44px minimum height and 13px of padding, which is right for something you
  type into and produces an enormous circle on a control the browser draws itself. The endpoint
  selector has looked that way since it was added: the sizing dates from the first commit and the
  radio arrived later with nothing exempting it. Selected by type rather than by the one place it was
  noticed, so any added later inherits sane sizing; the clickable label remains the touch target.

## v0.6.11 — The Remove buttons were never wired up

- **The API proxy did not forward `DELETE`.** Next answers 405 for any method with no export, before
  the handler runs, so every Remove button in the portal has been inert since it was added — the
  request never reached the backend at all. Found by reproducing it against a live deployment rather
  than by reading the code, which read as entirely correct on both sides of the gap.
- This is the actual reason an endpoint could not be removed. The stale-credentials defect fixed in
  v0.6.9 was real and would have bitten next, but nothing was reaching the delete route to expose it.
- A static guard now reads the methods the frontend asks for and asserts the proxy forwards each one.
  It fails on the old code. Neither test suite noticed this: the backend tests call the API directly
  and the browser tests never exercised a delete, so the proxy sat in the one gap between them.
- An empty `DELETE` body is dropped rather than forwarded as `""`, which not every HTTP stack treats
  as equivalent to no body.

## v0.6.10 — "Request origin rejected" now says what it expected

- **Every "update now" instruction says `restart`, not `start`.** The unit is `Type=oneshot` with
  `RemainAfterExit=yes`, so once it has run it sits in `active (exited)`, and `systemctl start` on an
  active unit does nothing and says nothing. It is the quietest possible way to believe a change was
  applied when it was not: an `APP_ORIGIN` edit stayed unapplied and the application then rejected
  every request for an origin it had never been told about. Corrected in `install.sh`, the unit's own
  comments, `reset_for_snapshot.sh` and the documentation.
- **The origin rejection names both addresses.** It fires for two causes that need opposite fixes — a
  container still holding a previous `APP_ORIGIN`, or a browser on a different address than the one
  configured — and the bare message distinguished neither. It now states what the deployment answers
  to, what arrived, and the two ways to resolve it. The origin is the URL the deployment is reached
  at rather than a secret, and every participant configuring their own box will meet this once.

## v0.6.9 — A certificate nobody has to accept

- **`install.sh --cert/--key` serves an existing certificate**, which is the mode to use wherever an
  organisation wildcard exists. It is the only one with no issuance step: nothing is fetched at boot,
  no rate limit applies, and a clone serves immediately. Everything that existed to cope with a bare
  IP disappears with it — no `tls internal`, no `default_sni`, no accepted warning, and `http://`
  redirects to `https://` for free. Verified live against a DigiCert wildcard: `ssl_verify=0` from
  outside with no `-k`.
- **`--acme`** fetches a Let's Encrypt certificate, and is **never attempted unless asked**. A
  hostname that does not resolve publicly would otherwise hang trying to reach Let's Encrypt, which
  is exactly the home-lab case. It also refuses an IP, since no public authority will issue for one.
- **`--lan-http`** serves plain HTTP for a home lab on a trusted network, and only for an RFC1918
  address, because the application refuses it anywhere else. It says what that costs.
- `--host` is now required wherever EC2 metadata is unavailable, and says so with examples rather
  than failing obscurely. All four TLS modes were generated from the script's own code and validated
  through Caddy, and the no-SNI handshake — what a browser sends to a bare IP — was exercised.

### Removing configuration actually removes it

Both found while preparing an image for cloning, where the stakes are a hundred people holding
someone else's API key.

- **Deleting a model endpoint left its credentials live.** `apply_endpoint` returned early on an
  empty endpoint and never undid what it had applied, so the endpoint vanished from the portal while
  the next turn still called it with the same key. Deleting now restores what `.env` configured —
  restoring rather than blanking, so a key deliberately placed in `.env` is not discarded.
- **Switching endpoints inherited the previous key.** Fields were applied only when present, so an
  endpoint saved without a key kept the last one's. Both are covered by tests that fail on the old
  code.
- **Only secrets offered "Clear saved value".** A blank field is deliberately left unchanged so a key
  survives editing a project name, which meant a URL, project or stream name could be overwritten but
  never removed. Every saved field now offers it.
- **`scripts/reset_for_snapshot.sh` wipes a box before it becomes an image.** It destroys the runtime
  volume rather than editing it, then proves `galileo-settings.json` is gone and lists what the image
  will still carry, warning about a provider key in `.env` that the volume wipe would not touch.
  Clearing fields in the portal is not equivalent: a field forgotten is a field every clone inherits.

## v0.6.7 — One command

- **`scripts/install.sh` installs a public single-stack instance in one command.** Docker, Caddy, the
  configuration, the image build, the self-update units, TLS on 443, and a verification pass. Safe to
  re-run: every step checks before acting, so a failed run is fixed and the script run again rather
  than unpicked.
- It stops with a reason rather than continuing on a wrong assumption — when the public IP cannot be
  read, when something already holds the port, when a `PREROUTING` redirect means a proxy on that port
  would bind and never receive a packet, or when containers cannot reach the internet. The last it
  first tries to fix, by exempting Docker's bridges, since that is the usual cause.
- It ends by naming the two things it cannot do: open the security group, and test from a machine that
  is not this one. An EC2 instance cannot reach its own public IP, so a check from the box proves
  nothing.
- `docs/single-instance.md` is restructured around the script, with the by-hand sequence kept below it
  for a box where some step has to differ.

## v0.6.6 — IMDSv2

- The AMI clone snippet in `docs/single-instance.md` now does the IMDSv2 token handshake. New
  instances commonly have IMDSv1 disabled, where the plain request returns nothing and
  `setup_env.py --origin` is handed an empty string — which fails validation rather than silently
  misconfiguring, but only after the clone has booted.

## v0.6.5 — The release an image was built from

- **The image now knows its own version.** `APP_VERSION` is a build argument that
  `scripts/selfupdate.py` fills in from the ref it checked out, so the portal reports the running
  release on any box — not only one where the host-side updater has run. `.git` is excluded from the
  build context, so this could not be derived inside the build.
- **`scripts/install_service.py` installs the three systemd units**, substituting the repository's
  real path and the account that invoked `sudo`. The units ship with defaults for a stock Ubuntu AMI,
  and a box whose user or path differs would install them, report success and never work: a path unit
  watching a directory that does not exist stays silent, and `systemctl status` shows only a unit that
  has never triggered. It also creates `runtime/update/` owned by the container's uid, which is what
  the portal's install button depends on.

## v0.6.4 — Boxes that update themselves

- **`scripts/selfupdate.py` and `scripts/splunky-finance.service`: an instance updates to the newest
  release on boot.** An instance spun up for a workshop should not run whatever was baked into the AMI
  weeks earlier, and rebuilding the AMI for every fix is what this avoids. Publishing a change becomes
  a tag plus `systemctl restart splunky-finance`.
- Two properties were designed for ahead of being current, because this runs unattended on the morning
  of a workshop. **It never leaves the box worse than it started**: the build runs before anything is
  recreated, so a failed build leaves the running stack untouched, and a stack that does not report
  healthy within `UPDATE_TIMEOUT` is rolled back to the commit checked out on entry, rebuilt and
  restarted. **It never blocks on the network**: a failed fetch is logged and skipped. It also refuses
  to update a tree with modified tracked files, because somebody edited that box by hand.
- `UPDATE_CHANNEL` defaults to `tags`, not branch HEAD. A tag is a decision someone made; a branch tip
  is whatever was pushed last, and fifty boxes pulling it at nine in the morning is fifty boxes
  inheriting an unfinished commit. `branch` and `off` are the other two.
- **The presenter portal can check for and install updates.** A *Software updates* card in the
  Troubleshooting tab reports the running release, the newest published one, and offers an install
  button when they differ. It is presenter-only, because that tab is hidden in workshop mode and
  participants should not be restarting their own box mid-exercise.
- The container does not perform the update, and is not given Docker to do it with. It writes one
  request file; a systemd path unit on the host notices and runs the update. The presenter password is
  published in this repository and identical on every box, so a container holding the Docker socket
  would mean anyone with that password owns the instance. The worst case here is a pull of a tag from
  this repository.
- **The validation section of the README is rewritten**, because it had gone stale in two ways that
  mattered: it still said a `verified: true` deny from a bound Agent Control had not been observed,
  and that the current user lacked Docker daemon access. It now also states what is *not* verified —
  Anthropic as a provider, a self-update rollback against a genuinely broken release, and that no
  human has followed the lab sheet end to end.

## v0.6.3 — One instance per demo

- **[docs/single-instance.md](docs/single-instance.md): one stack on its own instance, reached on port
  443 alone.** No port range to have opened, no port arithmetic, no per-participant origin template —
  which makes it the path to pick when the network publishes a single port, as managed lab
  environments often do. Carries measured sizing (`t3.medium`, 30 GB gp3; the build peaks near 2 GiB
  and sets the floor, while the running stack is about 1 GiB with the host), the checks that have to
  run before building, and a comparison with the fifty-stack path so the choice is made on what the
  network allows rather than by accident.
- **`setup_env.py --origin <address>`** accepts a bare address or a full origin and writes
  `APP_ORIGIN` with the matching `SESSION_COOKIE_SECURE`. The backend validates the two together and
  refuses to start when they disagree, so deriving the flag from the scheme removes a foot-gun that
  presents as a container which will not boot.
- **`setup_env.py` now updates an existing `.env` in place** when given `--origin` or
  `--rotate-secret`, rather than refusing. An instance cloned from an AMI carries the address of the
  box it was baked from, and this is what rewrites it: the whole of a `cloud-init` block that makes
  clones self-configuring is now five lines, documented. Written through a temporary file so an
  interrupted run cannot leave a half-written `.env` that takes the backend down on its next restart.
  Without either flag the behaviour is unchanged — it still preserves what is there.

## v0.6.2 — Say what this is not

- **A disclaimer, in the two places someone browsing the repository will see it.** A banner at the top
  of the README and a standalone [DISCLAIMER.md](DISCLAIMER.md): not a Cisco, Splunk or Galileo
  product, not affiliated with or supported by any of them, and not to be run in a production
  environment. It names the specific trade-offs that make it unsuitable — published shared passwords,
  plain HTTP as a supported path, pasted API keys stored for convenience, no authorisation model,
  audit trail or backups — so "demo only" is a statement with reasons rather than a slogan.
- Version pins in the deployment instructions move to v0.6.2, since the documented path deploys a tag
  and anything meant to reach a box has to be in one.

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
