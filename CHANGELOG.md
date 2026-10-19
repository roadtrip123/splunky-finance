# Changelog

Versions mark states worth returning to. Tags are annotated, so `git tag -n` and
`git describe` both say something useful.

Open defects are tracked as [GitHub issues](https://github.com/roadtrip123/splunky-finance/issues);
planned work is in [TODO.md](TODO.md).

## v1.1.15: The pull prompts name their destination, and the judge names its model

Two unrelated corrections that both came out of running the lab.

**Both cross-customer pull prompts name the destination account.** `to my account` left the agent
to choose between two accounts and left a presenter unable to say which one it should have used.
Both now name the Everyday account and its last four digits, which `generator.py` hardcodes, so the
wording holds under any seed. The guardrail decision is unchanged: the deny pattern matches on Tom,
Dan, 1234 and 4127, and 1042 is the customer's own account and deliberately absent from that list.
Verified both prompts still match and both own-account control prompts still pass clean.

**The completeness judge works on `gpt-4.1-mini` and was never measured on anything else.** On
GPT-5.1 it caught one incomplete answer in three with the fault confirmed present. Every figure on
record for it, the 8 of 10 included, was measured on `gpt-4.1-mini`, so there was no regression
against a measured baseline; the comparison that read as judge flakiness was against numbers that
never applied to the model in use.

- **The lab names the judge model** before the first evaluator is built, and the troubleshooting row
  no longer promises 90%+ accuracy without naming the model that figure was measured on.
- **The published prompt requires enumerate-then-quote**: number the parts the question asks for,
  quote verbatim the text in `candidate_output` answering each, write NONE where none answers it,
  return false on any NONE. `setup_definitions.py` now carries the same text as the lab's paste
  block, which had diverged.
- Model and prompt changed together on the retest, so the prompt's own contribution is unmeasured
  and nothing here claims it was the fix.
- Still unverified, and recorded as such: whether the stricter prompt holds on a correct answer.
  Its failure mode would be a red on a complete answer, which is the contrast the lab is built on.

## v1.1.14: No named third-party service in the endpoint picker

Sharon AI had a preset in the Setup tab. A preset saves one paste and then has to be maintained,
and it implies the service is known to work here. For that one it was not: it answers chat requests
and emits no tool call when one is offered, so every scenario in the demo fails on an endpoint the
portal appeared to endorse.

- **The picker is OpenAI, Anthropic, Ollama (local) and Custom.** Any OpenAI-compatible service,
  LiteLLM included, is Custom, which is already what lab step 13 tells participants to pick.
- **A saved endpoint with a base URL still edits as Custom**, including one saved while a preset
  for its host existed, so nothing already configured breaks.
- The README's endpoint list follows, and says why there is no preset.

## v1.1.13: A fresh install persists the egress bypass instead of warning about it

`install.sh` inserted the bridge bypasses when its own probe found container egress hijacked, then
warned that they would not survive a reboot. On a box destined to become an image that means they
do not survive at all, and every clone starts with its containers unable to reach an observability
tenant, reporting a certificate error that reads as a rejected credential. Which is the whole of
the afternoon this cost.

- It now calls `allow_container_egress.py` to write them into the saved ruleset, and says plainly
  which of the two happened rather than leaving a warning to be read.

## v1.1.12: The redirect was hijacking the containers' own outbound HTTPS

With v1.1.11 logging the real cause, the rehearsal's unexplained Galileo failure named itself in one
line: `Hostname mismatch, certificate is not valid for 'api.multitenant.galileocloud.io'`.
`PREROUTING` catches traffic arriving on any interface, the Docker bridges included, so the same
rule that hides the box from a browser was redirecting the backend's own outbound HTTPS into the
proxy on 8443, which answered with this deployment's certificate. The credentials were never wrong.

- **`scripts/allow_container_egress.py`** inserts a `RETURN` for `docker0` and `br+` ahead of the
  redirect and writes them into `/etc/iptables/rules.v4` above the redirect line, because
  `iptables-restore` applies the file top to bottom and a bypass below the redirect is never
  reached. `install.sh` already added these rules when its own egress probe failed, and warned that
  they do not survive a reboot, which on an image means they do not survive at all.
- **Persisted into the saved ruleset rather than a boot unit**, deliberately. `netfilter-persistent`
  is demonstrably running on these images, since it is what restores the redirect every boot. Riding
  a mechanism that works beats adding one that has not been shown to fire on this platform.
- **It probes from inside the backend container.** Traffic the host originates goes through `OUTPUT`
  and never meets `PREROUTING`, so a probe run on the host passes whether or not containers are
  affected. That is precisely why this looked like a credential fault for an hour.
- Six guards, on the ordering, the idempotency, both bridge shapes, a ruleset with no nat table, and
  that the probe runs in the container.

## v1.1.11: A connection failure nobody recognised left nothing to diagnose

A rehearsal hit "Galileo connection failed; check credentials, endpoint, and project permissions"
with a key that was correct. That sentence is the fallback `_connection_error` returns when the
error matches none of its patterns, so it was reporting the one thing that was fine, and the
exception was caught, mapped and thrown away. Nothing anywhere recorded what the SDK had said.

- **The exception is now logged**, with its class name and its text, key-shaped content masked by
  the same `redact` the provider path uses, truncated to 800 characters. `docker compose logs
  backend` has it. The masking helper moved to `app/redaction.py`, since both paths log what they
  decline to put on screen.
- **The fallback sentence names the fault family** and says plainly that it is not a rejected
  credential. A certificate error, a connection reset and a malformed response are three different
  problems that all used to read as "check credentials". The class name carries no secret, which
  is the reasoning `provider_error` already relies on, and it points at the log for the rest.
- Two guards, both proved failing against the previous code, one of them asserting that a bearer
  token in the SDK's own text does not reach the log.

## v1.1.10: The clean script clears the log stream as well

v1.1.8 reset `GALILEO_LOG_STREAM` to `my-bank-agent` rather than clearing it, on the reasoning that
the field arriving correct saves a participant a step. That was the wrong call for the job the
script actually does: a box reset to walk the lab from the beginning has to arrive at the form the
lab describes, and step 10 is where the participant types that name.

- **It is blanked with the project and the credentials now.** Blanked rather than deleted, and the
  difference is not cosmetic: present and empty in `.env` overrides the application default, while
  deleting the line restores `my-bank-agent` and puts a value back in the field. A guard pins that
  distinction, since anyone tidying the script into a line delete would undo it silently.

## v1.1.9: A pasted credential is stripped, and its length is visible

"The settings are exactly the same as this box" and one of them answers 401. The portal could not
have shown the difference: nothing stripped whitespace from a pasted field, and the mask is eight
dots and the last four characters, so a key carrying a trailing space or a newline looks identical
to a clean one. This is the third time this class of fault has cost a session, after a base URL
that became `/v1%20/chat/completions` and answered 404 like a wrong model name.

- **Every field on both pasted-configuration payloads is stripped on save.** `GalileoConnection`
  and `ModelEndpoint` carry `str_strip_whitespace`, so a key, a project, a stream, a URL or a model
  name copied out of a document or a chat window cannot reach a provider with whitespace attached.
  The URL guards see the clean value, since validation runs first.
- **The stored length of a credential is reported and shown**, beside the mask, for the field that
  is set. The remaining invisible failure is a key pasted short: rejected as a bad credential,
  identical in the form to a whole one. A length is not itself a secret, and it is the only thing
  that makes two boxes comparable. The key itself is still never echoed, on either backend.
- Three guards, each proved failing against the previous code, plus the em dash removed from the
  one placeholder this touched.

## v1.1.8: The portal says why the connection failed, and the clean script clears the project

Two findings from the first real workshop rehearsal. A Galileo connection was failing with no
visible reason, and a snapshot-ready box was pre-filling the project field with `splunky-finance`,
which is nobody's project in a room where the lab has each participant create their own.

**The portal reports what the connection attempt did.**

- **Save and connect reports the outcome, not the request.** The PUT already ran a forced check and
  returned a state and a sentence written by `_connection_error`; the portal ignored it and
  announced "connection saved" either way, leaving the reason in muted fine print on a card
  elsewhere on the page. One `report()` decides now, and both buttons use it.
- **A new Test connection button.** The `/galileo/check` endpoint existed with nothing wired to it.
  Re-checking without re-entering a key is what you want when the fault is at the other end: a
  project created a moment ago, or a token just granted a permission. It forces the check, because
  the thirty-second cache would otherwise answer with the stale failure being cleared.
- **Saving now always returns a state.** With observability switched off, no check ran and the
  response carried a stale `unconfigured` with no reason, so a failure was indistinguishable from a
  success. It answers `disabled`, and the portal says the switch is off.
- **A failure reason on a status card reads as a failure**, in red rather than as muted fine print
  under a badge that already said "failed".
- Error text is still the curated sentence and never SDK output. The presenter password is
  published in this repository, so that portal stays a low-trust surface.

**The snapshot reset clears `.env`, rather than warning about it.**

- Destroying the runtime volume never touched `.env`, which is kept on purpose for the address and
  the demo passwords. Every provider and observability key there is now blanked, and the script
  re-reads the file afterwards and **fails** rather than warning, because a warning only works if
  somebody reads it.
- **`GALILEO_PROJECT` is cleared too.** Not a credential, but a pre-filled project name is a trap:
  Save and Connect answers "project not found", or it succeeds and a participant's traces land in
  somebody else's project.
- `GALILEO_LOG_STREAM` is blanked with them, so a box reset to test the lab arrives at the form
  the lab describes, step 10 being where the participant types the name. Blanked rather than
  deleted: present and empty overrides the application default, while deleting the line restores
  `my-bank-agent`. Tenant URLs are kept and reported, with `--blank-urls` for anyone who disagrees.
- The stack is restarted afterwards, so what is running matches what `.env` now says.
- **Eleven guards**, all proved failing against the previous code.

## v1.1.7: The origin check's own check was proving nothing

On the first real run, `serve_any_host.py` reported `origin check -> 422 (unexpected)`. The
deployment was correct; the probe was not. It posted `customer_number`, the schema wants
`account_number`, and FastAPI validates the body before the endpoint runs, so the origin was never
looked at. The same 422 came back for an accepted origin and a refused one, which is the worst kind
of check: one that reads as a result.

- **The probe now posts a body the `Login` schema accepts**, with credentials that cannot work, so
  401 means the origin was accepted and 403 means it was refused. Anything else now says plainly
  that the check proved nothing, rather than printing "unexpected" and moving on.
- **A guard parses the payload out of the script and validates it against the schema**, so the two
  cannot drift apart again, and a second guard pins the order they depend on: the origin is checked
  before the password, which is what makes 401 the pass.

## v1.1.6: serve_any_host refuses to run where it would break logins

Setting a wildcard `APP_ORIGIN` against a backend that compares origins as strings is accepted at
startup and then refuses every request: a 403 on every login, with nothing in the message pointing
at the cause. That is the box most likely to run this script, since the whole point of it is fixing
an instance built from an older image.

- **The script now checks this checkout for wildcard support before touching anything**, and stops
  with the command to update first. Cheaper to refuse than to debug.

## v1.1.5: One image, any instance name, nothing configured per box

The lab platform names each instance when it boots, `i-09c3ad076563d756c.splunk.show`, and the
image cannot carry that. A new instance came up on a name the proxy had never heard of and served a
blank page, because Caddy had one site block for the name the image was built with and nothing
matched. The obvious fix is a boot-time unit that writes the address, and the obvious fix is wrong
here: the unit that already exists for the port redirect did not run on that box, and a hundred
instances is the wrong place to discover that.

So nothing is configured per instance at all.

- **The proxy serves by port rather than by name.** A site block of `:443, :8443` answers whatever
  `Host` arrives, which a wildcard certificate covers. `install.sh --host '*.example.com'` writes
  it, refuses `--acme` because a wildcard needs a DNS challenge, and warns that a self-signed
  certificate cannot work for names it will never be told. Verified with real Caddy against two
  instance names and a third unrelated one.
- **`APP_ORIGIN` accepts a wildcard leftmost label**, `https://*.example.com`. That address was
  used in exactly one place, the Origin check on mutating requests, and it now matches exactly one
  label under the domain. `https://*.show`, a bare `*` and `https://a.*.example.com` are refused at
  startup; at runtime the bare domain, a deeper name, another scheme, another port and a name that
  merely ends with the domain are all refused, that last one being the attack this has to resist.
  Session cookies remain host-scoped, `HttpOnly`, `Secure` and `SameSite=Strict`, and every mutating
  request still carries the session's own CSRF token, so the Origin comparison is the third layer
  and the wildcard widens it to one lab domain rather than to the internet.
- **`scripts/serve_any_host.py`** applies both to a box whose Caddyfile is already written. It
  drops the hostname, sets the wildcard origin, restarts the stack, which is what applies it, then
  proves the result against two names it was never told and reads the Origin check through the login
  endpoint, where a 401 means accepted and a 403 means still refusing. It leaves alone a workshop
  config serving a port per participant and a plain-HTTP site, neither of which can use a wildcard.
- **Fifteen guards** across `test_config.py` and `test_ports.py`, including a real login accepted
  from two different instance names under one wildcard origin. The ones covering the origin check
  and the installer were proved failing against the previous code, twenty-one parametrised cases of
  them; the ones covering the new script could not be, since the script did not exist before.

What is given up is the per-clone `SESSION_SECRET` rotation, since nothing now runs at boot: a
cookie minted on one box is accepted by another. Behind a password published in this repository, on
synthetic data, that is a fair trade, and `setup_env.py --rotate-secret` remains for anyone who
would rather not take it.

## v1.1.4: One script applies the port arrangement to a box already built

v1.1.3 put it in `install.sh`, which runs once when an image is made. The box in front of you has
its Caddyfile already written, and nothing in the update path touches that file, so the release on
its own changed nothing for it. Editing four lines by hand is also where a copied heredoc arrives
mangled in a terminal.

- **`scripts/serve_redirect_port.py`** reads the redirect's destination out of the live nat table
  and the saved rules, defaults to 8443 when there is no rule to read, and adds that address to
  every site serving the public port. It keeps a `.bak`, validates before restarting Caddy, and
  restores the previous file if Caddy rejects the result or will not start. Then it checks the
  direct and the redirected path with the `Host` header a browser sends.
- **It knows what not to touch**: a workshop config serving a port per participant, a plain-HTTP LAN
  site, an address shape it does not recognise, and a file that already serves the destination.
  Running it twice changes nothing the second time.
- **Eight guards** in `backend/tests/test_ports.py` covering each of those shapes, including the exact
  Caddyfile the first box was found with.

## v1.1.3: The portal answers whether the port redirect is there or not

A fresh instance came up unreachable again, with `--dport 443 -j REDIRECT --to-ports 8443` live in
the nat table and saved in `/etc/iptables/rules.v4`. Deleting it is a fix that has to win a race on
every boot, against something outside the box that keeps putting it back. Serving the destination
port instead means the rule stops deciding whether the box is reachable.

- **The proxy serves the redirect's destination as well as the public port**, as two addresses in
  one site block. Caddy binds the port in each address and selects the site by the `Host` header's
  hostname with the port stripped, so a browser asking for 443 is answered by the listener the
  redirect lands on. Nothing in any URL changes, and `APP_ORIGIN` keeps no port, so the backend
  still sees the origin it was told about. Proved against the real rule in a namespace: the same
  URL returns 200 served from 8443 with the rule present and from 443 with it absent.
- **`install.sh` reads the destination out of the rule rather than refusing to install.** It used
  to stop with "this proxy would never receive traffic", which left a lab image with no route in at
  all. It now reads both the live nat table and the saved file, because a box whose boot-time unit
  has already deleted the live copy is still one reboot from carrying it again, and defaults to
  8443 behind a public port of 443 whether or not a rule is there to find. `--also-port <n>` names
  a different one and `--also-port off` restores the single-address behaviour.
- **A second port something else already holds is skipped with a warning, not fatal.** The public
  port still works without it, and taking an install down over a secondary address is the worse
  trade.
- **The install's own verification now tests the redirected path**, with the `Host` header a
  browser sends, into the port the redirect lands on. Binding a port proved nothing about whether
  the site is matched on it, which is the gap this closes.
- **`splunky-finance-ports.service` is now insurance rather than the mechanism**, and says so.
  Keep it: a box serving 443 directly depends on one less rule nobody here controls. But it failing
  to run no longer takes the portal down, which is what happened on the instance that prompted this.
- **The docs stop telling you to remove the rule before installing**, and the snapshot checklist
  checks that the proxy holds both ports rather than that the rule is gone. The local checks name
  the port they mean, because `PREROUTING` is not traversed by anything the box originates: a
  loopback curl to 443 passes on a box no browser can reach, which is what made this look
  intermittent.
- **Eight guards** in `backend/tests/test_ports.py`, including the destination expression pulled out
  of `install.sh` and run for real against every spelling of the rule, rather than a copy that would
  keep passing after the original changed.

## v1.1.2: The connection is readable at a glance on both portals

Yesterday's fix made a dead link visible in the chat footer. This makes the same reading obvious
from either side, so a presenter checking before a demo does not have to hover anything.

- **The banking page's Demo connection disclosure is now coloured**: green when the portal can
  reach that tab, red when it cannot, amber while the first poll is still in flight. The visible
  word stays "Demo connection", because the room should not be reading demo state off the banking
  page, and the accessible name carries the same reading for anyone who cannot use colour.
- **A Banking connection card sits in the admin status grid**, between agent observability and the
  dataset. It reads connected, not responding, or disconnected, names the session's first eight
  characters, and says what to do about it. The data was already in the status payload and nothing
  outside the Demo tab showed it.
- **The session line, Disconnect and the pairing code moved into that card** from the Demo tab, so
  reading the link and fixing it are one job in one place. The pairing button is gated on the
  presenter's run existing, which the demo workspace creates on mount: inside that component the
  button could not be clicked before then, and in the card it could.
- **Four tiles across, not three plus an orphan.** The grid pairs them up below 1280px and stacks
  them below 1000px rather than squeezing four columns onto a laptop.
- **"waiting" gets its own face rather than being folded into either outcome.** The binding exists
  but the tab has not polled for ten seconds, so nothing armed will reach it. Calling that
  connected or disconnected would send a presenter to the wrong fix.
- Two guards: every state `Connections.status` can return has a face in the card, and the
  disclosure carries its state in something other than colour.
- **Three browser tests repaired.** All three had been failing against the product rather than
  finding anything, which is worse than having no test: `Run example question` became one Run
  button per offered question, the blocked answer is the gate's own fallback text, the missing-key
  status reads "credentials missing", `Hallucinated Policy` was replaced by `Wrong Customer`, the
  opening suggestion is the multi-part question rather than the longer typed one, and two
  assertions were made precise: the Galileo toggle waits for a settled card before reading which
  way it points, because `isVisible` does not retry and the saved switch survives between runs,
  and "no error banner" now looks for the banner instead of `role=alert`, which Next's route
  announcer always satisfies. The full suite passes twice in a row on desktop and mobile.

## v1.1.1: A preset arms the run the chat is listening to

The first real use of the chip found this: the presets armed a scenario and the chat answered
normally, with nothing reporting a problem. The footer, which is the only thing a presenter watches,
stayed its usual colour.

- **Arming now claims the banking session** rather than giving up on it. `arm` attached only when
  both sides were unbound, so a leftover binding meant it armed a run nothing was listening to.
  In-memory runs expire after an hour and a restart clears them while cookies survive, so a leftover
  binding is the ordinary state of a box that has been in use, not an edge case. `Connections.claim`
  releases whatever holds either side first, because a presenter clicking a preset is stating intent
  about their own browser. `attach` keeps its refusal, which is right for pairing two people.
- **A failure to bind now reaches the presenter.** `arm` returns whether anything is listening, and
  the 409 that `attach` already raised can surface instead of being guarded away.
- **The footer distinguishes "normal answers" from "nothing reaches this tab".** Both reported
  scenario `normal_spending`, so they looked identical, which is why this cost a round of testing.
  It now reads "Not connected to presenter controls: scenarios will not apply", and covers any
  future cause of the same silence rather than only this one.
- **Driven by a test rather than asserted on code shape**: bind the banking session to one run, arm
  from the presenter, drive a turn, and check the fault actually applied. Against the old code it
  fails with `assert 'normal_spending' == 'incomplete_answer'`, which is the symptom exactly.

## v1.1.0: The demo chip

A presenter with one screen cannot switch to the portal to arm a scenario and back to the banking app
to ask the question. The chip does both in one click, from the chat itself.

- **Off by default, and off on every clone.** The preference lives on the runtime volume rather than
  in the source, so an image stamped a hundred times starts with it off. While it is off the banking
  page is told nothing at all: `demo-sync` returns no presets, so a box never ships the fault
  catalogue to a customer.
- **Enabled from Troubleshooting**, under Software updates, as "Demo Chip Enabled". It appears in the
  chat within a second, because the connection hook already polls.
- **In the chat heading, with the menu floating down over the transcript.** In the footer and in flow
  it shortened the conversation every time it opened, which is movement an audience notices.
- **Each item is the question itself**, with what it breaks underneath in smaller type. Grouped, since
  the guardrail pair is the same question twice and only the group heading tells them apart.
- **The chip never shows what is armed.** An audience should not be able to read "wrong customer
  enabled" off the screen; the live row is marked inside the menu, and the full description is on
  hover. A test guards it, because it is a presentation requirement that any later edit could undo.
- **`POST /api/demo-admin/arm`** does in one call what the portal does in three: it creates the
  presenter run if none exists, sets the scenario and the guardrail, and attaches the banking
  session. It reads both cookies, which is the condition `/api/demo-admin/bind` already requires
  before fault mode can activate, so this is the same authority with fewer steps. The presets work
  with the portal closed or never opened.
- **The guardrail presets are a read and a pull**, each shown with the guardrail off and then on.
  A transfer *to* another customer is a payment, which a bank is for, so blocking it is a weaker
  story; exposing a balance and draining an account are not. The own-account entry stays as the
  control.

### Also

- **A preset that had just changed the settings could send the version from before it.** The
  connection hook polls every second and `sync()` reused an in-flight request, so the answer could
  predate the change and the turn came back 409. Worse, the handler blamed every failure on a missing
  presenter session and told the presenter to sign in again, which was the one thing that could not
  help, while the portal was connected throughout.
- **The delivered-answer span had no latency and double-counted tokens.** `duration_ns` is optional
  and Galileo infers nothing in its absence, so the one span this demo points at was the only one in
  the trace without a number beside it. It also repeated the turn's total usage that the LangChain
  callback had already reported per call, so adding up a turn's LLM spans gave roughly twice what it
  spent. The injection pass keeps its counts: it runs with callbacks deliberately off, so its span is
  the only record of it.
- **The guardrail scenario said its own-account questions were gated.** `money_transfer` had no
  prompt groups, so the portal fell back to "Questions for this scenario" and every question read as
  blocked. It now lists only the seven requests that name another customer, and Normal Answers labels
  its three groups by what happens to each. Transfers *to* Tom or Dan are in the blocked group,
  because the control tests the whole argument set and a payment carries the account number just as a
  raid does.
- **A transfer cannot be dated with the real date.** `Dataset.ledger` rejects any transaction after
  the manifest's reference date, so stamping one with today's date on a dataset seeded earlier makes
  the write fail validation: the transfer is lost, the tool returns an error, and the agent says
  there was a problem with the request, which reads exactly like a model declining. The tool now
  documents why it uses the reference date, and a test covers the write-and-reload path that nothing
  covered before. A presenter who wants today's date on new rows wants the dataset reseeded with
  today as its reference date.

## v1.0.7: A 400 says what to change

`v1.0.6` surfaced a real failure on the first box it met and then named the exception rather than
the mistake: "OpenAIInvalidRequestError while calling the provider". The mapper covered 401, 403,
404 and 429 and not 400, which is the code `langchain_openai` wraps as `OpenAIInvalidRequestError`.

- **400 is now mapped**, by class name as well as by code, because the wrapper does not always put
  the number in the text. The generic case names the likeliest cause: a Model field holding the
  display name, `GPT-4.1 mini`, rather than the provider's identifier, `gpt-4.1-mini`.
- **Two 400s this app provokes itself** get their own sentences. It always sends `max_tokens`, which
  newer models reject in favour of `max_completion_tokens`, and it sends `temperature` outside the
  reasoning families, which those models also reject.
- **The provider's own words now go to the log.** The card's sentence is deliberately lossy, and
  until now the real message existed nowhere at all, so even an operator with SSH could not see it.
  Key-shaped text is masked out first: a 401 body quotes the key that was sent, and a log outlives
  the turn.

## v1.0.6: Why the model provider failed

A colleague walking the lab set up OpenAI wrongly and the portal said `Failed`, in the same muted
grey as `connected`, with no reason. A participant has the portal and nothing else: no shell, no
log. So the card said something had gone wrong, quietly, and gave them nowhere to go.

- **The cause was already in hand and thrown away.** The turn's exception handler recorded
  `type(exc).__name__` into telemetry and then set `provider_status` to a bare `failed`. It now
  carries `last_error`, mapped to a sentence: a rejected key (401), a model name the provider does
  not have (404), a refused request on quota or rate limit (429), permissions (403), or an
  unreachable host, which reads differently for Ollama because the model is on the box.
- **Provider text is never passed through.** A 401 body quotes a fragment of the key that was sent,
  and the presenter password is published in this repository, so anyone who can read that card is
  not trusted with part of a key. Only the status code and the exception's class name are read out,
  the same rule the Galileo connection errors already follow. A test asserts a leaking 401 body
  reaches the card with no key fragment, no account identifier and no URL in it.
- **`failed` is now red and bold**, and `connected` green, through `.badge.failed` and
  `.badge.connected`. The state is mapped to a class rather than interpolated into `className`.
- **The card no longer tells participants to edit `.env` and restart**, which they cannot do: they
  have no SSH. It names the Setup tab, and when the provider has failed it says to ask a question on
  the Demo tab afterwards, because the status only re-checks when a turn runs.

## v1.0.5 — The port 443 redirect no longer survives a reboot

The redirect lives in the image's `/etc/iptables/rules.v4`, and `netfilter-persistent` restores it on
every boot, so deleting it by hand never lasted. A box in that state is healthy by every internal
measure — Caddy bound to 443, containers passing their healthchecks, a certificate that validates —
and completely unreachable from a browser, because arriving packets are redirected to a port nothing
listens on. v0.6.8 made `install.sh` warn about exactly this; a warning on a box that was already an
image was not enough.

- **`scripts/fix_ports.py`** removes the rule from the running nat table and, with `--persist`, from
  the saved file that restores it. It matches on what a rule does rather than how it is spelled: the
  saved copy carries `-m tcp`, a rule added by hand may not, the destination port has varied, and one
  box carried two identical copies — `iptables -D` removes one match, so a single delete looked like
  it had worked.
- **`splunky-finance-ports.service`** runs it `After=netfilter-persistent.service`, which is the
  entire point: anything earlier is undone a moment later. `Before=splunky-finance.service` as well,
  so the stack is never reported healthy on a box no browser can reach. It is the only unit here that
  runs as root, because it edits the nat table.
- The script reports rather than fails when a rule cannot be parsed, so a box that is already
  reachable never fails to boot over this.
- **A test of the workshop provisioner hardcoded `/srv/splunk-finance`** and so could only ever pass
  on one checkout. It now derives the path, which means the suite runs on a deployed box.

## v1.0.4 — The policy corpus denied the transfer tool existed

- **The agent refused its own `transfer_funds` tool**, answering "I cannot execute transfers or
  payments" to a transfer between the customer's own accounts. Not the block message and not the
  fallback — the model's own refusal, because the retrieved policy told it so:
  `assistant-boundaries.md` said "It cannot move money" and `external-transfers.md` said "My Bank
  Agent cannot initiate transfers or change limits". The corpus described an application that cannot
  do what it does, and a retrieved policy outranks the system prompt.
- Both now say it can move money and keep the limits that are real: it cannot change limits, change
  account details, execute investments or give advice. `security.md` is unchanged — it says the agent
  cannot authenticate third parties or bypass ownership checks, which remains true and is the
  guardrail's own subject.
- The system prompt already carried a comment about exactly this failure mode, from a previous fix:
  "a prompt claiming transfers are impossible made the model refuse its own tool". The same mistake
  was sitting in the corpus, where nobody had looked.
- It was invisible until `v1.0.3`, because the answer gate was replacing every armed-mode answer with
  the fallback, so the model's refusal never reached the customer.

## v1.0.3 — Armed protection no longer replaces every legitimate answer

- **With the guardrail on, no own-account question could succeed.** Asking for your own savings
  balance returned *"I couldn't verify that answer against the bank's policies"* — the safe fallback,
  not the block message. The cause: controls are scoped to tools, so nothing is scoped to the answer
  step, and the answer gate treated "no control applies" as fail-closed. Every legitimate answer was
  replaced the moment protection was armed, which is the opposite of what a guardrail is for. Found
  by running the half of the lab's Step 8 that had never been tested.
- The two causes behind a missing verdict are now separated. `no_control_selected` — the gateway
  answered and nothing was scoped to this step — delivers the answer with `decision: not_covered`
  and `verified: false`, because nothing objected and nothing enforced. `control_errored` still fails
  closed: asked and unable to answer is different from never asked.
- **The action gate deliberately still fails closed**, including when no control covers the tool. A
  transfer is irreversible, so "no policy covers this" is not grounds to let it through; replacing an
  answer costs nothing and refusing one costs the customer their own banking. The asymmetry is
  commented where both branches are.

## v1.0.2 — No project pre-filled into every clone

- **`GALILEO_PROJECT` defaults to blank**, in `config.py` and `.env.example`. It shipped as
  `splunky-finance`, which meant every instance made from an image arrived pre-filled with one
  person's project. A participant who leaves it points at a project they probably cannot read, and
  the failure reads as a broken box rather than a wrong field. Two projects one letter apart already
  cost a day on exactly this confusion; shipping one pre-filled a hundred times is worse.
- The log stream keeps its default, because the lab has everyone create a stream by that name.

## v1.0.1 — Resetting a box without the units

- `reset_for_snapshot.sh` falls back to `docker compose up` when no `splunky-finance` unit is
  installed. It restarted through the unit unconditionally, so on a box where only the manual path
  was ever set up — a workstation — it destroyed the runtime volume and then failed, leaving the
  stack down. Wiping and not restarting is the one outcome that script must never produce.

## v1.0.0 — The working version

The first release verified end to end against a live Galileo tenant on two independent deployments:
a workstation and a public EC2 instance behind a publicly-trusted certificate.

**What is proven, by observation rather than by test double:**

- A preventive guardrail reaching a real verdict. `pre: verified` on both boxes, with the control
  named in the log stream — not the application failing closed, which is the failure that reads as
  success and which this release can finally distinguish.
- The agent registering itself. `agent_control.init()` is called when the connection check resolves
  the stream, with the name derived from project and stream, so a participant creates nothing and
  types nothing. Observed registering under two different derived names against two tenants.
- Traces and evaluator scores exporting to a live tenant, with the three custom judges scoring.
- One-command install, including on a host that redirects container egress; TLS on a bare IP, on a
  high port, and with an organisation wildcard; self-update from the host and from the portal;
  survival of a reboot with the firewall fix intact.

**What is not proven, and should be read before relying on it:**

- The own-account half of the guardrail demonstration — that a customer's own transfers and balance
  checks still work while cross-customer ones are blocked. The blocking half is verified; this half
  is not, and it is what distinguishes a guardrail from a feature switch.
- `scripts/check_endpoint.py` against the shared workshop endpoint. An endpoint can answer chat
  correctly and still fail at tool calls, which every scenario depends on.
- A human following [docs/workshop-lab.md](docs/workshop-lab.md) from end to end.
- Anthropic as a model provider, and a self-update rollback against a genuinely broken release.
- Splunk Agent Observability's Agent Control, which remains open as issue #2.

**The deployment traps this release knows about**, each of which cost a day and each of which is now
recorded where it will be met rather than in a changelog: a blanket `PREROUTING` redirect of port 443
that leaves the host working and every container broken; `default_sni`, without which TLS on a bare
IP binds the port and serves nobody; `api_key` runtime auth returning 401 where `jwt` is required; a
restart silently disarming the guardrail scenario; and two Galileo projects one letter apart.

## v0.6.24 — Two things that cost a day

Both recorded where the next person will meet them, rather than left in a transcript.

- **`AGENT_CONTROL_RUNTIME_AUTH_MODE=api_key` returns 401** from `/api/v1/evaluation` on Galileo's
  multitenant gateway, while registration with the same key succeeds. `jwt` is required. The symptom
  is the application failing closed, which reads as a working guardrail, so it survived three rounds
  of comparing two otherwise identical boxes. `.env.example` now says so at the setting.
- **Restarting or updating disarms the guardrail scenario.** It lives in memory, so after a restart
  nothing is gated and the Demo tab looks identical to never having enabled it. Three test rounds
  were spent on stale readings because of this. Step 8 of the lab sheet now warns about it where it
  will be read.

## v0.6.23 — The gateway's own words

- **A client error now carries the gateway's message**, truncated to 400 characters. It was left out
  originally on the grounds that a response body can echo credential headers — but a 4xx from this
  gateway is a server-authored explanation, and without it a 401 is just a number. Three rounds of
  comparing two boxes field by field, with every measurable input identical, could have been one.
  Captured only for 4xx, where the body explains itself; a 5xx body is noise and can be large.

## v0.6.22 — The derived agent name followed the project again

- **`declare_agent` wrote the derived name into the override field**, which made the derivation
  sticky: the first registration pinned it, and a participant who renamed their project went on
  registering and evaluating under the old project's agent name. That is precisely what deriving the
  name was meant to prevent. Every reader calls `resolved_agent_name`, which is deterministic, so
  the write-back shared nothing and only did harm. Observed on a box whose project had been changed
  from `splunky-finance-lab` to `splunky-finance` while the agent still read
  `splunky-finance-lab-my-bank-agent`.

## v0.6.21 — A working guardrail no longer reports "failed"

- **Protection status is tracked per stage.** There are two gates answering different questions: the
  pre gate decides whether a tool runs, the post gate inspects the answer. A control scoped to
  `transfer_funds` is invisible to the post gate, which correctly reports that nothing applied — and
  because only the last call was kept, a box that had *just blocked a transfer* reported `failed`.
  That nearly sent a real diagnosis the wrong way.
- **"No control applied" is no longer a failure.** It is an outcome: the gateway answered and nothing
  was scoped to that step. `failed` is now reserved for the gate not reaching a verdict at all, which
  is the case that matters — the application fails closed and the refusal looks like success.
- `protection_stages` in the admin status carries each gate's own status and detail, so `pre:
  verified, post: no_control` is legible instead of one misleading word. A genuine fault still wins:
  a 401 on either stage reports `failed`.
- The Demo tab's readiness check read the conflated status, so a working preventive guardrail showed
  as not ready.

## v0.6.20 — Which request was refused

- The failure diagnosis now carries the **path** of the refused request. A 401 on the runtime token
  exchange and a 401 on the evaluation call need different things from a tenant — a permission on the
  key, or a feature enabled — and the status code alone does not say which. The path is recorded and
  the query string is not, because a path cannot carry a token.

## v0.6.19 — Why the gate failed, without driving a turn to find out

Reaching a real gateway for the first time produced a 401 on the runtime evaluation call while
registration with the same key succeeded. Establishing that took driving a presenter turn and reading
its `action_decisions`, which is the wrong amount of work for the question "is this guardrail real".

- **The last reason the gate could not decide is kept and reported.** `protection_detail` in the
  admin status carries the diagnosis — `http_status`, `hint`, `cause` — so a guardrail failing closed
  is distinguishable from one working without reproducing a turn. The not-configured path reports its
  reason too, rather than leaving the field empty.
- **`AGENT_CONTROL_RUNTIME_AUTH_MODE` is configurable**, defaulting to `jwt`. A tenant that has not
  enabled the token exchange rejects `jwt` with 401 while accepting the same key for the management
  API, which is exactly the shape observed. Trying `api_key` no longer needs a code change.

## v0.6.18 — The Agent Control URL could never be saved

- **Setting the Galileo Agent Control URL from the portal silently did nothing.** The save returned
  200 and the field read back empty, which looked like a portal that would not save. In fact the
  value was applied and then overwritten: `agent_control_url` is Galileo's input *and* the live field
  the gate reads, and the live one is rewritten per backend from a value captured once at
  construction — so the next connection check restored whatever `.env` held at startup, usually
  nothing.
- Which means the guardrail has never been configurable from the portal at all, only from `.env`
  before the process started. A good deal of this week's confusion about agents and agent names
  traces to this one line.
- `apply_connection` now updates the remembered Galileo gateway when one is applied, and clearing the
  field clears it too, so a cleared value is not restored by the next check. Three tests cover it:
  set then check, switch to Splunk AO and back, and clear then check.

## v0.6.17 — The agent name leaves the portal again

- **The Agent Control agent name is no longer a portal field.** It was added one release earlier so a
  participant could point at an agent they had created; now the application registers its own and
  derives the name, there is nothing to point at. A field a participant can fill is a field they can
  get wrong, and getting *this* one wrong produces the 404 the app answers by failing closed — the
  transfer is refused and from the chat that is indistinguishable from a guardrail that worked. The
  same reasoning already kept the two Agent Control header settings out.
- It stays as `AGENT_CONTROL_AGENT_NAME` for whoever deploys a box.
- Removed from `CONNECTION_FIELDS` and the request schema too, not just the form, which has a useful
  side effect: **a value saved on a box configured before this release becomes inert** rather than
  overriding the derivation with a name nobody registers. A test covers that case specifically.

## v0.6.16 — The application registers its own agent

The guardrail's 404 was never a wrong agent name. **This application never registered an agent at
all.** `agent_control.init()` does that, via `/initAgent`, and nothing here called it — so every
guarded call asked the gateway about a name it had never been told about. `my-agent-liam` worked only
because something else had already registered it, and the conclusion drawn from that — that agents
must be pre-created in a console — sent hours after a screen that does not exist.

Galileo's own documentation is unambiguous: a control is created in the console and attached to a
**log stream**, and nothing attaches it to an agent. The agent is declared by the application with
the stream as target context, and the server returns the controls bound to that stream.

- **`declare_agent()` registers on each connection check**, as soon as the stream id resolves —
  which is the first moment the target is knowable. Re-registers when the name, gateway or stream
  changes, because the SDK fixes target context for the session, and skips when nothing changed.
  A failure is recorded and reported rather than raised, and the SDK's error text is not echoed
  because it can carry credential headers.
- **The agent name is derived from the project and stream** unless set explicitly. That is what
  distinguishes one participant from another: the lab has everyone name their stream the same and
  their project after themselves. So there is nothing to pre-create, nothing to type, and no
  hundred-agent spreadsheet. `AGENT_CONTROL_AGENT_NAME` and the portal field become overrides.
- **The derivation lives on `Settings`**, because two unrelated callers need it: `Telemetry`, which
  registers, and `Protection`, which names the agent on every evaluation request and has no
  telemetry. It normalises to what the gateway accepts — lowercase, `[a-z0-9:_-]`, at least ten
  characters — since a name the gateway rejects produces the same silent 404.
- **`docs/validation.md` carries a correction** rather than quietly losing the wrong conclusion, and
  `docs/workshop.md` no longer tells presenters each participant must create an agent.
- **`docs/flows/agent-control.svg`** draws the whole thing: what is set up once, what happens on
  every tool call, and the trap where an unregistered agent reads as a working guardrail.

## v0.6.15 — Each participant points at their own agent

- **The Agent Control agent name is settable from the portal.** It was read from `.env` alone, so one
  deployment could serve exactly one agent — and participants have browser access only, by design.
  Controls attach to an agent, so a workshop sharing one agent shares its controls: one person
  toggling a guardrail toggles everyone's, and Step 4 stops being an exercise. The field appears in
  all three backend forms, beside that backend's Agent Control URL. The two header settings stay out:
  the app derives them from the active backend, and they are two more fields a participant can only
  get wrong.
- **A 404 from the evaluation route now names the agent it could not find.** This is the failure that
  disguises itself as success — the app fails closed, the transfer is blocked, the customer sees the
  refusal, and only `action_decisions` shows the deny was never real. The hint says the name must
  match the console exactly and that agents cannot be created from the app.
- **`connection()` is derived from `CONNECTION_FIELDS`** rather than written out by hand. A connection
  field lives in three places — the tuple, the request schema and the view the portal's form seeds
  from — and this one was missing from the hand-written view, so it saved correctly and showed as
  empty. A test now asserts all three agree.

## v0.6.14 — The customer password loses its leading dash

- `DEMO_PASSWORD` is now `AlexDemo1234!`, without the leading hyphen. A password read aloud to a room
  should not begin with a character people hear as punctuation or as part of the sentence. Still 13
  characters, so it clears the twelve-character minimum.
- **An existing box keeps its old password**, because `.env` is not in the repository. Change it in
  place and restart: `sed -i 's|^DEMO_PASSWORD=.*|DEMO_PASSWORD=AlexDemo1234!|' .env`. Do this before
  taking an image, or every clone carries the old one.

## v0.6.13 — Workspace Setup and Control

- The presenter portal's heading reads **Workspace Setup and Control** rather than "Demo workspace",
  which says what the page is for rather than what it is.

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
