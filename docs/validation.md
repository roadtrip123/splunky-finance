# Validation — 2026-09-16

- Python lint: passed (`ruff check app tests`).
- Backend tests: 12 passed; one upstream Starlette/AnyIO deprecation warning.
- Next.js production build: passed, including TypeScript.
- Playwright browser journeys: 6 passed across desktop Chromium and mobile Chromium.
- Agent Control schema: validated locally against installed SDK 8.7.0.
- Docker Compose configuration: checked without daemon access.

The protection tests use explicit SDK response doubles for allow/deny; browser journeys use an explicit offline model with real tool invocation. These are application tests, not live service acceptance.

Unverified: Docker image build/start, paid provider calls, local Ollama performance, genuine Galileo exports and custom judge results, and genuine tenant-bound Agent Control decisions. Docker socket access is denied for the current user. Provider and Galileo secrets must be configured locally in ignored .env.

## Private LAN configuration update

Private IPv4 HTTP requires explicit ALLOW_PRIVATE_LAN_HTTP opt-in. Public IPs, DNS names, and link-local addresses remain rejected for remote HTTP. Cookie security must match HTTP/HTTPS. LAN login, session cookies, and exact Origin rejection are tested.

A private-LAN deployment was validated using an address assigned to the test host. Docker access remained denied. Local private `.env` is excluded from Git; no host address is committed.

## Galileo admin controls update

- Backend tests: 21 passed; lint passed.
- Production build: passed.
- Browser journeys: 8 passed on desktop/mobile, including persistent enable/disable and missing-key status.
- Galileo default enabled, live .env updated, and production backend/frontend restarted.
- Connection uses a fresh authenticated SDK API read. SDK response doubles test success/failure and secret-safe errors; genuine live connection and trace export status are reported separately in the presenter portal.

## Action-span fix and live verification

Fixed two SDK integration defects: GalileoLogger is unhashable, so pending loggers must be tracked by object identity; the root trace must start in the async request context so callback tasks inherit the SDK ContextVar parent. A real-SDK offline ingestion-hook regression asserts one exported trace with LLM, calculate_spending tool, and protection workflow descendants.

Backend suite: 22 passed; lint passed. Backend restarted. One live OpenAI account-balance turn returned HTTP 200 and exported successfully. A live Galileo trace was read back through the authenticated API and contained Agent, two ChatOpenAI LLM spans, a tools workflow with a get_accounts tool span, and output-protection-decision. This verifies OpenAI tool execution and genuine Galileo span ingestion; custom judge scores and bound Agent Control decisions remain unverified. Earlier empty sessions cannot be reconstructed automatically.

## Retriever span and answer span

Policy retrieval is registered as a LangChain retriever and the delivered candidate is logged as a `customer-visible-answer` LLM span. Real-SDK offline ingestion-hook regressions assert that an exported trace contains a retriever span carrying chunks, the named answer span with the candidate as its output, and the previously covered model, tool, and protection descendants. `config` injection keeps the retriever span inside the turn's trace and stays hidden from the model's tool schema.

Backend suite: 43 passed; lint passed. Still unverified against a live tenant: whether built-in RAG evaluators return actual values for these spans, and genuine Agent Control decisions. Enable the evaluators in the tenant and confirm a real score before presenting them.

## Wrong-customer scenario and evaluator set

Added a `wrong_customer` scenario whose candidate is a fixed template rather than a model rewrite, so the injected identity is constant and the bound regex control can be pinned to it before a session. Customer identity and accounts are now seeded into evidence server-side, so entity evaluation has authoritative material to compare against even when the turn calls no profile tool. `fault_method` reports `fixed_template` for this scenario instead of claiming a model rewrite.

Retired `SplunkyGroundedness` in favour of built-in Context Adherence, and renamed `SplunkyCompleteness` to `SplunkyRequestCoverage`. The setup script now registers five built-in evaluators alongside the three custom judges and binds a second regex control.

Backend suite: 44 passed; lint passed; production build passed. Both control schemas validate against the installed SDK. Remote metric creation, built-in evaluator values, and control binding remain unverified against a live tenant.

## Presenter logout relink fix

Presenter logout deletes the run but cannot clear the customer session's copy of its id. The stale id then failed the `not customer.run_id` guard in auto-relink and tripped the 409 in `attach`, so a banking session could neither relink on the next presenter login nor recover by pairing, and every subsequent chat was attributed to a run the portal could no longer display. Bindings to a run that no longer exists are now dropped before relinking and before pairing. Two regression tests cover relink and pairing recovery; both fail with the fix disabled.

Backend suite: 46 passed; lint passed.

## Judge prompt correction

Live scores showed all three custom judges returning false on the incomplete-answer scenario: an answer with its total removed was reported as having a wrong total and a wrong customer. The judges were instructed to return false when required evidence was absent, so each failed whenever its subject was missing rather than contradicted, and the one-metric-per-scenario story did not hold. Each judge now fails only on a contradiction it can point to and returns true when its subject is absent. Added `--refresh-judges`, which deletes and recreates judges so an edited prompt reaches the tenant; without it existing judges are skipped. Applied to the tenant and all eight metrics confirmed still enabled.

## Context adherence verified against live traces

Per-span rationales from live traces corrected two earlier claims. Context Adherence does catch an invented fee stated during a calculation question: the agent's model calls carry their tool results as context, and the rationale named the fabricated 2.5% fee and scored it 0.0. No additional judge is needed for that case.

The `customer-visible-answer` span, however, is logged with the question and the candidate and no context, so Context Adherence reports its claims as unsupported even for a correct answer. Adherence on that span is not meaningful; the span remains the node the Agent Control output control scopes, which is why it exists. The span worth reading is the agent's answer-composing call, verified at 1.0 for a correct total and 0.0 for a correct total with an invented fee appended. Documentation now says so; attaching evidence to the logged span as context remains open.

## Scenario evaluation results

All four fault scenarios were run against the live tenant and each was rejected by the metric intended to catch it, with the other judges staying green where their subject was untouched. Incomplete Answer failed only SplunkyRequestCoverage; Incorrect Total failed only SplunkyNumericalCorrectness; Hallucinated Policy was rejected by Context Adherence, whose rationale named the invented fee; Wrong Customer failed SplunkyEntityIntegrity and SplunkyNumericalCorrectness together, because its candidate misstates both identity and figures. Documentation previously claimed exactly one judge fails per scenario, which does not hold for Wrong Customer and has been corrected.

Still unexercised: the policy retriever, since every scenario was run against the spending question, so no live trace yet contains a retriever span. Agent Control remains untested; every run so far recorded protection disabled.

## Answer span context

The `customer-visible-answer` span was logged with the question and the candidate only, so Context Adherence reported every claim unsupported on every turn. A correct answer was confirmed scoring `[0,0,0]` with the rationale "the provided context contains no transaction data or other evidence supporting any of these claims", while the agent's own answer-composing span scored `[1,1,1]` and 100% completeness on the same turn. The span now carries the turn's calculations, policies, customer and accounts as context; a regression asserts the calculation evidence and customer name reach it and that no tool definitions are attached. Whether the evaluator then scores it correctly needs one live turn to confirm.

## Answer span verified, fault writer named

A live turn confirmed the answer span fix: `customer-visible-answer` moved from `[0,0,0]` adherence and 0% completeness to `[1,1,1]` and 100%, with a rationale citing the 75,419 cent total instead of reporting no evidence. The trace completeness roll-up rose from 33% to 78%. The tool-choosing span remains borderline, having scored `[1,1,1]`, `[0,0,1]` and `[1,1,0]` across three traces, because judges disagree whether a span containing only a tool call can be adherent.

The fault writer is now logged explicitly as `controlled-fault-writer` rather than through the callback, which names chat-model spans from the model class and made the fabrication indistinguishable from the agent's genuine calls. It carries the same evidence as the answer span. A regression asserts the span exists by name, holds the candidate and the evidence, and that the agent's own model spans are not renamed.

Backend suite: 47 passed; lint passed.

## Judge voting and span verification

A faulty turn confirmed the answer span fix in both directions: `customer-visible-answer` scored `[1,1,1]` on a correct answer and `[0,0,0]` on an altered total, the rationale naming $854.19 against the authoritative $754.19. Its completeness stayed at 100% on the faulty turn, since the answer covered everything asked and only the figure was wrong. The fault writer now appears as `controlled-fault-writer` rather than a third model call named after the model class.

`SplunkyRequestCoverage` returned true and then false across two runs of the same scenario and question with nothing left unanswered, tracing to `num_judges=1` on the custom judges while the built-in evaluators use three. All three judges are now published at version 2 with three voters; version 2 is the default and all eight metrics remain enabled. Deletion proved unavailable — a metric can only be deleted by its creator — so `--refresh-judges` publishes a new version instead, which also keeps scoring history.

Still absent from every trace: `action_completion_luna`.

## Judge scoping

With three voters most verdicts became unanimous, which exposed that the judges were grading outside their own remit rather than flapping at random. On the incorrect-total scenario `SplunkyEntityIntegrity` returned false although its own reasoning stated that no person was misnamed and no foreign account cited; it failed the answer for the wrong total instead. `SplunkyRequestCoverage` showed the same pattern, noting the answer addressed the whole question before pivoting to the figure. Each judge is now told to judge one property and to return true when that property holds even if the answer is wrong for a reason another metric owns, published as version 3.

Unanimous and correct before this change: normal spending, all three judges true; incomplete answer, only SplunkyRequestCoverage false. The answer span discriminated correctly on every run, scoring `[1,1,1]` on the correct answer and `[0,0,0]` on all three faults, and `controlled-fault-writer` appeared by name on each faulty turn.

Completeness roll-ups do not rank answers: the incomplete answer rolled up to 92% against 78% for the correct one. `action_completion_luna` remains absent from every trace.

## Action Completion removed

Action Completion produced no value on any trace or session across every run, showing only "Queued". Session-level metrics were checked directly: sessions carry completeness and tool-error roll-ups only. This tenant offers the metric solely as the Luna small-model variant, and reassigning the judge model changed nothing, which is consistent with that setting governing LLM judges rather than Luna scorers. The SDK also exposes start_session, set_session and clear_session but no way to close a session, so a session-scoped metric may never see a completed session. Removed from the enabled set and from both documents rather than left advertising behaviour never observed. Seven metrics remain.

## Judge scoping verified

Version 3 was re-tested against three scenarios and every verdict was correct and unanimous. Normal spending: all three judges true. Incorrect total: SplunkyNumericalCorrectness false, the other two true, correcting the earlier `[1,0,0]` where SplunkyEntityIntegrity failed an answer that misnamed nobody. Wrong customer: SplunkyEntityIntegrity and SplunkyNumericalCorrectness false and SplunkyRequestCoverage true, correcting the earlier unanimous false on a question that was answered, for the wrong person. No split votes in any run. The answer span scored `[1,1,1]` on the correct answer and `[0,0,0]` on both faults.

The custom judges and the answer span are complete. Outstanding: the policy retriever has still never run, since every scenario has been exercised against the spending question, so no live trace contains a retriever span; Completeness roll-ups still do not rank answers and should be read per span; Agent Control has never produced a verified decision.

## Hallucinated Policy scenario removed

The scenario was dropped from `SCENARIOS`, the presenter portal, the flexible-fault tests, the README and the walkthrough, where Part 5 was removed and the remaining parts renumbered. Its `FAULT_INSTRUCTIONS` entry is deliberately retained: `inject()` maps `guardrail_before_after` onto those instructions, so removing them would have broken the protection demonstration. The flexible-fault test now parametrises `guardrail_before_after` in its place, keeping coverage of that instruction path.

The policy retriever is still reachable, since `guardrail_before_after` uses `POLICY_PROMPT`. It remains unexercised on any live trace.

Backend suite: 47 passed; lint passed; production build passed.

## Judges renamed

`SplunkyRequestCoverage` is now `SplunkyAnswerWholeQuestion` and `SplunkyEntityIntegrity` is now `SplunkyRightCustomer`. Both were created fresh with three voters and the scoped prompts, and the log stream now enables the new names alongside `SplunkyNumericalCorrectness` and the four built-ins. The originals remain in the tenant unenabled, because deletion is refused for anyone but a metric's creator. The verified-results table in the walkthrough carries the new names, though the verdicts in it were observed under the old ones; the judge logic is unchanged, only the labels.

Backend suite: 47 passed; lint passed.

## Evaluator set reduced on cost

Per-turn evaluation cost was measured against live traces: about $0.22 a turn across seven metrics, of which `completeness` alone was $0.13-0.18, roughly 78%. That metric had already been found unusable, its roll-up ranking a deliberately incomplete answer at 92% against 78% for a correct one. `tool_selection_quality` and `tool_error_rate` were correct on every run but never caught a problem.

The set is now four: the three custom judges, which detect every scenario, and `context_adherence`, kept as the Galileo-native evaluator that works here and whose rationale named the invented fee. About $0.035 a turn, an 84% reduction, with nothing lost that the walkthrough demonstrates. Both documents were updated so neither describes a metric that no longer runs.

Not yet taken: the custom judges each consume around 9,000 tokens because the trace output carries the whole record including every account and top-purchase row.

## Money-transfer guardrail

The protection demonstration now stops an action rather than a sentence. `transfer_funds` debits the Everyday account, appends a posted `external_transfer` movement and persists through the existing atomic write, making it the only tool in the application that writes. A `TransferGuard` middleware implements `awrap_tool_call`, so the gate evaluates the call at Agent Control's `pre` stage and a denial short-circuits execution: the tool is never invoked and no balance changes. An answer-stage gate could not achieve this, because by the time a candidate exists the transfer has already happened.

Replaced: the `guardrail_before_after` scenario, its candidate-replay machinery, and the two `post`-stage regex controls that matched answer text. One control remains, `splunky-transfer-deny`, scoped to `step_types: ["tool"]`, `step_names: ["transfer_funds"]`, `stages: ["pre"]`, created and bind requested. Replay is gone because the request is identical on both runs and the comparison is now whether the action executes, so there is no candidate text to hold constant.

Tests: a denied call leaves the balance and transaction count unchanged and records a `deny`; a permitted call moves money and the ledger still reconciles, which matters because a dataset that fails reconciliation will not reload after a restart; and protection enabled with Agent Control unconfigured blocks the transfer and leaves the dataset file byte-identical.

Backend suite: 45 passed; lint passed; production build passed. The gate has not yet been exercised against a live tenant decision.

## Guardrail controls simplified

A live run moved money with the guardrail unarmed. The scenario button and the arming checkbox were separate, the checkbox read "Check and block unsafe answers", and its description covered only answer checking, so nothing connected it to a transfer. Selecting a protection-applicable scenario now arms the guardrail in the same click and the checkbox is gone, along with the explanatory paragraphs around it; the button reads **Enable Guardrail Money Transfer**.

A blocked transfer now returns "Transfer option is not available from My Bank Agent." rather than the answer gate's fallback, which spoke about verifying an answer and said nothing about the transfer not happening. The override keys on the gate's decision being `deny` or `unavailable` rather than on an action label, which a test double had omitted.

Backend suite: 45 passed; lint passed; production build passed.

## Workshop provisioning

`scripts/workshop.py up --count N --host H` provisions one compose project per participant, each on port base+N with its own dataset volume, session secret and exact `APP_ORIGIN`. Shared settings are inherited from a base env file so the LLM endpoint, passwords and dataset seed stay identical across the room.

Two changes were needed for stacks to coexist. `compose.override.yaml` pinned every project to port 3100 with `!override` and was removed; the port is now `${FRONTEND_PORT:-3000}` and the repository's own stack sets 3100 in `.env`. Both services also carry fixed `image:` tags, because without them each compose project builds and tags its own copy and fifty participants would trigger fifty builds of identical source. The script builds once and starts participants with `--no-build`.

Verified on this host: two stacks provisioned on ports 3201 and 3202, both serving, with separate `sf-p01_runtime-data` and `sf-p02_runtime-data` volumes; `list` reporting both; `down --purge` removing containers, volumes and generated env files; and the repository's own stack on 3100 unaffected throughout. Generated env files are written 0600 into a gitignored `workshop/` directory.

Not yet done: the portal cannot set Galileo credentials, so connecting to Galileo still requires editing an env file. That is the remaining blocker for a zero-SSH participant experience.

## Workshop configurability

Galileo connection details are now settable from the portal and applied without a restart. `Telemetry.set_connection` writes them alongside the enable flag in `runtime/galileo-settings.json` at mode 0600, and they outrank the environment on load, so a participant points their instance at their own project without shell access. The API key is never returned: the connection payload reports only whether one is set, and a regression asserts the key does not appear in the response and that a blank field leaves the stored value unchanged.

`POST /api/demo-admin/galileo/setup` enables the metrics on the participant's log stream and binds the transfer control, reusing the tenant-wide judges and control definition. Metric enablement and control binding are both per log stream, so each participant runs it for their own project. The shared definitions moved from `scripts/configure_galileo.py` into `app/observability/setup_definitions.py`, because the container image copies only `backend/app` and `data/` and the script directory is not present at runtime.

`DEMO_MODE=workshop` hides the seed and reference-date reset card, whose editable fields would move every figure on a participant's lab sheet, and the pairing-code control, which is meaningless when one person holds both roles in one browser profile. The paid preflight is kept but renamed "Test my setup", since it is the best check a participant has that their configuration works.

Two defects that would have broken a fifty-person workshop: `configure_galileo.py` skipped `clone_and_bind_control` whenever a control of that name already existed tenant-wide, so every participant after the first would have had no guardrail while the script reported success; and `model_factory` built `ChatOpenAI` with no `base_url`, so an OpenAI-compatible endpoint could not be reached at all. Both fixed.

`workshop.py` now refuses to provision when the resulting origin would be plain HTTP on a public address, which `config.py` rejects, rather than starting stacks that cannot boot. `scripts/Caddyfile.workshop` covers TLS with a subdomain per participant.

Backend suite: 47 passed; lint passed; production build passed.

## Presenter portal reorganised into tabs

The portal was one long scroll with no grouping, which put the Galileo connection form below the demo controls and rendered its six credential fields as a wrapping horizontal row that truncated them. It is now four tabs beneath the status cards: Demo, Evidence, Setup and Troubleshooting. Status cards and Reset balance stay above the tabs so they are reachable from anywhere, which matters because the money-transfer scenario needs a reset between runs. The connection form uses a stacked single-column layout. In workshop mode, a portal with no API key opens on Setup, since that is a participant's first task; presenter mode always opens on Demo.

A browser journey still drove the removed `guardrail_before_after` scenario and its checkbox, so it had been failing since that scenario was replaced. It now drives Enable Guardrail Money Transfer and asserts the blocked-transfer message. Playwright cannot run on this host because port 8001 is occupied, so that test is corrected but unverified.

## Connection panel corrections

The panel showed saved values only as grey placeholder text, so it read as empty even when configured. It now seeds the form from the saved connection, so a participant edits what is there instead of retyping it. The API key is never seeded, because it only ever arrives masked.

The key is reported as eight bullets plus its last four characters, enough to tell which key is loaded and not enough to use it. A regression asserts the masked form is returned and that no part of the key beyond those four characters appears anywhere in the response.

A fresh participant instance must not inherit the operator's credentials, so `workshop.py` blanks the six Galileo and Agent Control fields rather than copying them from the base env, and sets `SESSION_COOKIE_SECURE` to match the origin scheme. Verified by generating a participant env and by a test asserting a Telemetry over an empty data directory reports no key and blank fields.

Backend suite: 48 passed; lint passed; production build passed.

## Model endpoint selectable from the portal

The Setup tab now selects the model endpoint: OpenAI, Anthropic, Ollama (local), Sharon AI, or a custom OpenAI-compatible URL. Sharon AI and custom both use the openai provider with their own base URL, since the distinction is the endpoint rather than the protocol; the base URL field appears only for the options that need one, and the key field is hidden for local Ollama.

Selection persists beside the Galileo connection in the same runtime file and applies without a restart. `model_name` and `provider_configured` are derived properties, so switching provider swaps which fields the agent reads without losing the others: a test sets an OpenAI-compatible endpoint, switches to Ollama, and asserts the OpenAI base URL survives. Provider keys are returned masked on the same terms as the Galileo key, and the endpoint enforces the startup rule that Ollama mode requires a local runtime.

`workshop.py` also blanks the provider keys and OpenAI base URL for participant instances, so a fresh stack arrives with no credentials of the operator's at all.

Backend suite: 50 passed; lint passed; production build passed.

## Injected answer reads as a model call

The span carrying an injected answer was named `controlled-fault-writer` and tagged `simulation: true`, which marked the fabrication as staged everywhere it appeared in Galileo. It is now named after the chat model class, like the agent's own calls, so a trace shows the failure the way a genuine model failure would look. The demonstration depends on that: a trace that labels the fault as injected undercuts the thing it is meant to show.

The honest record moves entirely to the presenter evidence, which was always the authoritative one: it keeps `raw_model_output` beside `candidate_output` and reports `fault_method`. A regression asserts the span is named like a model call, carries no simulation marker, still holds the turn's evidence so the evaluator judges it against the tool results, and that the evidence retains both answers and the method.

## README install instructions

The install section assumed a checked-out repository and said only "Install Docker Engine with Compose" with no commands, so it did not cover standing the project up on a new machine. It now runs from a clean Ubuntu host: package install, Docker group, clone, `setup_env.py`, then compose. `FRONTEND_PORT` is documented in `.env.example`, and the note about running several stacks points at `scripts/workshop.py` and `docs/workshop.md`.

The Providers and Galileo sections still described `.env` plus a restart as the only route. Both now lead with the presenter portal, which applies changes without a restart, and keep the environment variables as the preset path.

## Multiple model endpoints

Several endpoints are saved and switched between from the portal. `model_factory(settings, endpoint)` now takes an explicit spec and `ChatService.answer` resolves the active endpoint once per turn, passing the same one to the agent and the fault writer. Previously both read process-global settings, so a switch part-way through a turn would have changed the model under a running request, and in a workshop one participant's switch would have landed on another's. A regression drives a turn and asserts every model built used the endpoint resolved at the start.

Endpoints persist beside the Galileo connection with a migration from the single-endpoint shape that preceded them. Keys are masked on read and a blank key on edit keeps the stored one, matching the connection panel. The Setup tab manages the list; the Demo tab carries a one-click switcher, since that is where a presenter stands mid-demo.

Traces are named `bank-chat-turn · <endpoint>` so two runs of the same question are distinguishable in the trace list without opening either, and the turn metadata carries the endpoint name alongside provider and model. Latest chat evidence shows endpoint and duration per turn.

Token counts and time-to-first-token were already exported per span and were confirmed populated on a live trace. Cost reads 0.0: Galileo prices recognised model names, and the LangChain callback reports the agent's own spans as `chat-ollama` rather than the model. Whether cost populates for a priced hosted model is untested.

Backend suite: 51 passed; lint passed; production build passed.

## Model switch resets the conversation

Switching endpoints kept the conversation, so both turns shared one Galileo session and, more importantly, the second model received the first model's answer as history. It saw a larger prompt than the first model did, could refer back to an answer it had not written, and the token and latency figures were not comparable — which defeats the purpose of the switch.

A switch now clears conversations and bumps the run revision, exactly as a scenario change does, so the presenter workspace resets and each model answers the same clean question in its own session. A regression asserts the revision advances and conversations are cleared.

## Conversation memory documented

The walkthrough gained a Conversation memory section and the README a short equivalent. Within one model the agent receives the last 8 messages, trimmed at 7,000 characters, and every turn in that conversation shares one Galileo session. Switching model, changing scenario, toggling the guardrail, an hour idle, a presenter logout or a backend restart all clear it and start a new session.

Two presenting consequences are called out: a follow-up question straight after a switch will confuse the new model, which has no history; and conversational memory cannot be demonstrated in the same conversation as a model comparison. The visible transcript survives either way, so both answers stay on screen.

Also repaired a duplicated "Reading the evidence panel" heading left by an earlier edit to Part 7.

## Why a block could not be attributed

A blocked transfer reported `unavailable` with the message "Protection request failed or no control was evaluated", which covered four different causes: the HTTP request failing, a control erroring, nothing selecting the control, and protection not being configured. Each needs a different fix, and the single string made them indistinguishable, so a genuine control denial could not be told apart from a broken request.

Each cause now travels with the decision as a `diagnosis`: `request_failed` with the exception type, `control_errored` with the error strings, `no_control_selected` with the match and non-match counts plus the agent name, target, stage and step it asked about, and `not_configured`. A test asserts the first two are reported distinctly and that both still block.

Observed against the live tenant before this change: the pre-execution gate works — an armed transfer produced no `transfer_funds` span, so the tool never ran and no balance moved — but the decision was `unavailable`, and no control span has ever been written, because `_log_controls` only writes one when evaluated controls come back. Two `splunky-transfer-deny` controls exist, both enabled with `stages: ["pre"]` and `step_types: ["tool"]`, and both report `used_by_agents_count: 0`.

`clone_and_bind_control` clones as well as binds, so calling it for a control that already has a clone leaves another copy behind; that is where the duplicate came from. Both the setup script and the portal's project setup now bind only when no clone exists, and report what they found rather than claiming a binding they have not confirmed.

## Workshop scope: participants build the Galileo side

The lab is now configuring Galileo, not having the app configure it. **Set up my project**, which enables metrics and binds the control in one press, is hidden in workshop mode because it performs exactly the exercise; the Connect panel says so in its place. Presenter mode keeps it.

[docs/workshop-lab.md](workshop-lab.md) is the participant guide: create an API key, project and log stream first, point the app at them, then build four evaluators and a guardrail control by hand, then run the scenarios and read the traces. The three judge prompts and the control definition are included ready to paste, and a check confirms the pasted prompts are byte-identical to what `setup_definitions.py` registers, so the guide cannot drift from the code silently.

Two things the guide has to say that are not obvious. Custom metrics are tenant-wide, so fifty participants each creating `SplunkyRightCustomer` collide in one namespace and every metric needs a per-participant suffix. And the two instructions in each judge prompt that look like padding are there because of observed failures: without "the absence of a claim is not a failure" an answer with its total removed was reported as having a wrong total, and without "judge only the single property described above" a judge would establish its own subject was fine and then fail the answer for a different defect.

Sizing for 100 participants: 200 containers, about 51.5 GB working set, which needs `r7i.4xlarge` at 128 GiB. On the 64 GiB box sized for 50 that is 80% committed, too close for a live session. Disk goes to 100 GB and `--stagger` should drop to 1, or starting 200 containers takes nearly seven minutes.

## Sharon AI cannot drive the agent yet

Tested directly against `https://inference.sharonai.cloud/api/v1` with `shared-gpt-oss-120b`. The endpoint answers chat requests and fills `content`, but **emits no tool call when one is offered**. Every scenario depends on the model calling a banking tool, so the endpoint cannot back the demo until tool calling is enabled; a request to enable it is with the provider.

An earlier probe with a small `max_tokens` also returned empty `content` with the text in `reasoning_content`, which is how a reasoning model spends its budget before producing output. With a realistic limit `content` was populated, so that was a budget artefact rather than a format incompatibility — worth re-checking if the model changes.

The supplied config gives `api_key_value` as `"Bearer tv-pat-..."`, a full header value. The OpenAI client adds `Bearer` itself, so pasting it verbatim produces a doubled prefix: confirmed 200 with the bare key and 401 with the doubled one. The saved endpoint on this instance holds the bare key correctly.

`scripts/check_endpoint.py` runs these three checks — reachable, fills `content`, emits a tool call — so an endpoint can be cleared before a workshop rather than during one.

## Tom's account and a real cross-customer exposure

A second fictional customer holds account `1234`, stored in `other_accounts` so the authenticated customer's ledger still reconciles exactly and the existing validator is untouched. `get_account_balance` looks up any account by number **without an ownership check**, and `transfer_funds` now credits the destination when it is a real account, so a transfer and a later balance question describe the same money.

Both tools are gated before execution by the renamed `ActionGuard`, which was `TransferGuard` and gated one tool. One scenario button arms both gates, and two controls are needed, `splunky-transfer-deny` and `splunky-account-lookup-deny`, one per tool.

This deliberately removes the guarantee that the tools cannot reach another customer's data. That guarantee is what made Wrong Customer honest — its script said the identity had to be fabricated because no tool could return it. Both scenarios are kept: Wrong Customer shows evaluators catching a fabricated identity after the fact, and this shows a control preventing a real one. The walkthrough now states the difference rather than leaving the earlier claim standing where it is no longer true.

Also fixed: `wrong_customer` carried `protection_applicable: True` from when it had a bound regex control, so selecting it armed the answer gate, which failed closed and replaced the fabricated answer with the fallback — hiding the thing the scenario demonstrates.

Tests: account 1234 is confirmed to belong to another customer and be reachable, a denied lookup discloses no balance by any route, and a transfer credits the destination.

Backend suite: 54 passed; lint passed; production build passed.

## Dataset migration, Dan, and a guardrail that is not a kill switch

Adding `other_accounts` changed every stored dataset's content hash, so `Storage.read()` raised, startup reported corruption and the backend never became healthy. The manifest already carried `generator_version`; nothing compared it. Startup now rebuilds when the stored version differs from the current one, deterministically from the same seed and reference date, so published figures do not move and only uncommitted demo state is lost. A missing or unreadable version is still corruption and still fails visibly. `docs/architecture.md` states the exception.

Separately, the agent refused to call its own lookup tool — *"I cannot access Tom's account information"* — with nothing blocking it. `get_account_balance` has no ownership check by design; the model invented the privacy rule. Same fix as the earlier `transfer_funds` refusal: the tool description and system prompt now say plainly that the tool covers every account at the bank.

**Dan Whitfield is now a real customer** on `•••• 4127` with $4,806.20, alongside Tom on `•••• 1234`. Both resolve by account number or by name: digits win over names so "Tom's account 4127" resolves to Dan, and full names are matched before first names because the two share a surname. `transfer_funds` credits either, and an internal transfer between the customer's own accounts now writes both ledger rows under a shared `transfer_pair_id` — a credit with no matching row would fail the reconciliation validator on the next read, which is exactly how `other_accounts` bricked the app.

Wrong Customer now answers *"How much is in my account?"* with Dan's **real** account and **real** balance, read from the dataset rather than invented. The leak is genuine data. It also sharpens the evaluation story: only `SplunkyRightCustomer` goes red, because the figure is internally consistent and the question was answered. One metric aimed at one property catches a breach every other metric is right to wave through.

**The control is now a deny-list rather than `(?i).+`.** Matching everything made the guardrail a feature switch: the customer's own balance checks and own transfers were refused too. The pattern is generated from `OTHER_CUSTOMERS`, so the tenant definition cannot drift from the dataset. `configure_galileo.py` now pushes the current definition with `set_control_data` on both the original and every bound clone — it previously only reused an existing control, so a definition change never reached the tenant. Verified live: controls 886, 887, 1029 and 1030 all carry the new pattern.

Tests: resolution by number and by name including the surname collision, ledger reconciliation after an internal transfer, the deny-list matching only foreign accounts, and the injected answer quoting Dan's real figures.

Backend suite: 59 passed; lint passed; production build passed. The guardrail's allowed paths are verified by unit test and by the live control definitions, not yet by a live armed run.

## Making the fault happen on every model

`SplunkyAnswerWholeQuestion` returned true on an Incomplete Answer turn. The judge was right. `inject()` only rejected a candidate identical to the original, and distinct text is not the same as a faulty answer: on the multi-part restaurants question gpt-4o-mini reliably dropped only the trailing "so August was $212.52 higher", leaving an answer that addresses every part and whose figures all reconcile with the ledger. Gemma, on the same question, omitted the transactions and the comparison as instructed and scored false. Two models, same judge, opposite verdicts, both correct.

An earlier hypothesis — that the judge was reading `raw_model_output` out of the trace output JSON — is disproven by that gemma result: the genuine answer is in the payload for both runs, and only one came back true.

`inject()` now verifies the fault is present and imposes it in code when it is not. For Incomplete Answer the bar is a whole claim going missing rather than a single figure, because losing one trailing amount was exactly the case that slipped through; the thresholds bias towards the deterministic path, since forcing an omission the model had already made is harmless while shipping a complete answer under a label promising a fault is the failure being prevented. For Incorrect Total the candidate must state a money amount the original did not. `fault_method` now reports what actually produced the candidate: `model_rewrite`, `deterministic_fault`, or `unverified_rewrite` for a single-claim answer with no part that could be removed.

That last case delivers the model's candidate rather than raising. The previous code path would have turned an unforceable answer into a 503, and a broken turn in front of an audience is worse than a weak fault.

Verified live against gpt-4o-mini: three runs of the two-part question, three genuinely incomplete candidates, and the reproduced "kept every part" candidate is now rejected by the verifier and forced. The Incomplete Answer scenario prompt is now the two-part restaurants question.

Backend suite: 62 passed; lint passed; production build passed.

## The completeness judge was told to ignore omissions

Across both models and all three evaluation scenarios, `SplunkyRightCustomer` and `SplunkyNumericalCorrectness` scored correctly and `SplunkyAnswerWholeQuestion` stayed green on a genuinely incomplete answer. With the candidate now verifiably incomplete on every model, the remaining fault was in the judge.

`JUDGE_PROMPT_SUFFIX` was one shared string appended to all three judges, and two of its clauses contradict this judge directly: *"the absence of a claim is not a failure"*, and an exclusion list naming *"an omitted part"* as another metric's concern. Both are correct for the other two judges — an absent figure is not a wrong figure, and an absent name is not a misnamed customer — and both tell the completeness judge to pass the one fault it exists to catch. It was doing what it was told.

`judge_prompt(name)` now builds each prompt with the absence rule and exclusion list that suit it. For `SplunkyAnswerWholeQuestion` the rule is inverted — *"An omission is a failure here, whatever other metrics make of it"* — and "an omitted part" is removed from its exclusions. The other two are unchanged. A regression asserts the completeness judge is never told to ignore omissions and that the other two keep the rule.

Published to the tenant with `--apply --refresh-judges`. The paste-ready prompts in the lab guide are generated from `judge_prompt()` so they cannot drift from what the script publishes.

Backend suite: 63 passed; lint passed.

## Gemma still passed: length is not evidence of an omission

With the corrected judge, Incomplete Answer scored false on OpenAI and still true on Gemma. Two gaps, both in the verifier rather than the judge.

`_dropped_something` accepted a candidate on length alone, at 60% of the original. A model that compresses verbose output into one terse sentence keeps every claim while looking like it cut something, which is Gemma's habit. Length is no longer evidence of anything: the bar is two of the original's figures going missing, which takes a whole claim rather than a trailing derived number.

`_force_incomplete` only cut at sentence boundaries. A two-part answer written as one sentence — "you spent $754.19 last month, and your largest purchase was $119.68" — has no sentence to drop, so the forced answer was the complete one. It now falls back to a clause boundary after the first figure, and accepts the result only once a figure the original stated has actually gone. Verified against five answer shapes including markdown bullets and a semicolon clause.

Verified live: both models, two runs each of the two-part question, all four `deterministic_fault` and none mentioning the largest purchase. The scenario is now model-independent by construction rather than by luck.

Backend suite: 68 passed; lint passed; production build passed.

## The completeness judge never saw the question

After the prompt fix, Incomplete Answer still scored true on three of four runs with the candidate verified incomplete on both models. Reproducing the judge directly on `gpt-4.1-mini` with the real trace payload settled it in two experiments: given the question alongside the output it returned false 6/6, with and without `raw_model_output` present — which also disproves the contamination theory properly. Given only the output payload it returned true 6/6, and its stated reasoning named an "implied question" it had reconstructed from the answer.

The trace input is set correctly: a diagnostic trace logged the way the app logs one and fetched back through `Traces.get_trace` returned the question verbatim in its `input` field. So the input exists and the trace-level custom judge is not reliably given it.

That also explains why only this judge was affected. `SplunkyNumericalCorrectness` and `SplunkyRightCustomer` compare the candidate against `evidence`, which has always been in the output payload; they never needed the question. `SplunkyAnswerWholeQuestion` cannot do its job without it, and with nothing to compare against it inferred a question the answer happened to satisfy.

The record now carries a `question` field, and the judge is told to read it from the trace output JSON, never an implied question, and to return true rather than guess if it is absent. Verified with the judge given only the output payload: false 3/3 on the incomplete answer, true 3/3 on the complete one. Published as version 2.

Backend suite: 70 passed; lint passed; production build passed.

## What the judge actually reads: the whole trace, spans included

After the `question` field was added, 5 of 8 runs scored correctly. Reproducing the judge on the full 3,381-character record returned false 9/9, so the prompt and the payload were not the problem — which meant the reproduction itself was wrong.

Reading the published scorer version settled it. The template is `{normalized_input_json}` and the system prompt describes a **trace object with every span**, not the trace output alone. So the judge is also handed the agent's own llm spans, whose outputs carry the complete answer as the agent wrote it, before the fault was injected. A judge that reads one sees the largest purchase present and passes the turn. Every reproduction until now had handed it only the trace output JSON, which is why the fault never appeared in simulation.

This is the contamination the earlier `raw_model_output` theory was reaching for and missing: the leak is the spans, not the record. Removing `raw_model_output` would not have fixed it.

The spans have to stay, because the trace has to look like an ordinary agent run. So the judge is now told explicitly that the trace contains the agent's own spans, that their outputs may hold a fuller draft than the customer received, to ignore every span, and that a part answered in a span but not in `candidate_output` was never delivered and is an omission. Published as version 3.

Confidence is lower here than on the previous fixes: the instruction is verified present in the published version, but it cannot be checked in simulation without reconstructing a full normalised trace. The tenant run is the test.

Backend suite: 71 passed; lint passed.

## Removing the contradiction instead of asking the judge to overlook it

Three rounds of prompt instructions telling the completeness judge to ignore the agent's spans did not hold, because the judge is handed the whole normalised trace and LLM judges are poor at ignoring salient text in front of them. The trace itself was the problem: the agent's span said one thing and `customer-visible-answer` said another, which contaminated evaluation and was a plain tell for anyone reading a trace.

Galileo's spans are held in memory until `flush`, so they can be edited before export. After a fault is injected, `Telemetry.mask_genuine_answer` walks the span tree and replaces the genuine answer with the delivered one. The trace now shows a single answer.

Two things were needed beyond the obvious span. **Span inputs matter as much as outputs**: `ToolCallLimitMiddleware.after_model` and `ModelCallLimitMiddleware.after_model` carry the whole message list, so the complete answer reappeared there as chat history even once the agent's own output had been rewritten. **The trace output is the record**, and `raw_model_output` carried the complete answer straight back into what every judge reads, so it is stripped from what goes to `conclude()`.

The presenter evidence is unchanged and still keeps the genuine answer beside the injected one with the method that produced it. That was always the honest record; it simply stops being in the trace.

This fixes the contamination for every judge, including Context Adherence and anything a workshop participant writes, rather than only the three prompts under our control. An end-to-end regression exports a real trace and asserts the genuine answer appears nowhere in it while the delivered one does; a unit test covers nesting, message history and leaving tool results alone.

Backend suite: 73 passed; lint passed; production build passed.

## Residual: evidence read as an answer

With the genuine answer out of the trace, 8 of 10 runs scored correctly. The two that did not were indistinguishable from the ones that did: same question, same model, same record shape, opposite verdict.

What remains available to the judge is the evidence. `answer_context` puts the turn's calculations on the answer span, and those calculations carry `top_purchases` — so Jacaranda Cafe at $119.68, the very part the answer omits, sits in the span's context looking answered. The evidence cannot be removed: Context Adherence scores against it, and logging the span without it made every claim score unsupported, correct answers included.

So the judge is now told that evidence and retrieved context show what was available to the agent, not what it said, and that a figure present only in evidence was not communicated and does not count as an answered part. Published as version 4.

If runs remain intermittent after this, the cause is judge variance rather than anything readable in the trace, and the lever is `JUDGE_COUNT`: three voters make a borderline call a 2–1. Raising it to five costs about two thirds more for this metric.

Backend suite: 74 passed; lint passed.

## Documentation pass

`docs/evaluators.md` was the stalest file in the repository: its Agent Control section still described two `post`-stage regex controls on `customer-visible-answer` (`splunky-seeded-policy-deny`, `splunky-wrong-customer-deny`) that no longer exist. It now documents the two `pre`-stage tool controls, why `pre` is the whole point, why the condition is a deny-list rather than `(?i).+`, how `--apply` reaches the tenant including the clone-refresh, how `ActionGuard` obeys a denial before the tool runs, and how to tell a real deny from a fail-closed block.

Added to the same file: where every definition lives, how to apply and re-version them, and the four logging choices the evaluators depend on — retriever span, evidence on the answer span, the `question` field, and masking the genuine answer out of every span.

`DEMO-SCRIPT.md` gained Tom's and Dan's balances in the reference table, the two-part Incomplete Answer question, the `fault_method` values a presenter will see, and a note that the genuine answer is in the presenter evidence but deliberately not in the trace. The verified-results table now carries an observation date per row and states plainly that Incomplete Answer scored 8 of 10.

`docs/workshop-lab.md` gained a table of what the app does so the participants' judges can score anything, and a warning that the completeness judge is the flakiest part of the lab. `docs/workshop.md` and `README.md` were corrected to match.

Backend suite: 74 passed.

## The control's own span was never reaching the trace

Dumping a real exported trace for an armed `money_transfer` turn showed no control span at all. Isolating `add_control_span` explained it: the method takes `input: str`, and it is decorated with `@warn_catch_exception(exceptions=(Exception,))`, so anything it raises is swallowed and it returns `None`. The action gate passes `request.tool_call["args"]` — a dict — so the span was dropped on exactly the path that needs it. The answer gate passes a string and was unaffected.

The failure was invisible from both ends: no span in Galileo, no exception for `_log_controls` to catch, and so not even the `control_telemetry: "failed"` marker that exists for this purpose. `action_decisions` in the trace output was the only evidence a control had run.

`_log_controls` now serialises a non-string input and checks the return value, recording `control_telemetry: "span_rejected"` when the SDK refuses a span rather than implying the evidence reached the trace. Verified by exporting the same turn again: `[StepType.control] splunky-transfer-deny` now appears, at the trace root.

Backend suite: 75 passed.

## Splunk AO as a switchable backend

`splunk_ao` is the Splunk Agent Observability rebrand of the same core — it imports `galileo_core` internally and the span methods have identical names — so the work was a seam plus renames, not a rewrite.

**Stage 1** moved every SDK import into `app/observability/sdk.py`, which resolves a backend to the dozen symbols the application uses. No behaviour change; the suite stayed at 75. `stream_id_of()` reads `log_stream_id` or `agent_stream_id` without needing the backend, because the action gate and the turn record hold a logger but not a `Telemetry`. `ControlResult` needed no abstraction at all: `splunk_ao.logger.control` re-exports `galileo_core`'s class, so both resolve to the same type and a regression asserts it.

**Stage 2** added the provider. Both packages install together — they resolve against `galileo-core 4.5.0` and nothing is downgraded — and only one is active at a time. Dual export was rejected deliberately: Agent Control would need an adjudicator, and two tenants disagreeing on one tool call has no good answer.

The trap is the environment. `splunk_ao` has no namespace of its own: `SplunkAOConfig` subclasses `GalileoConfig` and bridges `SPLUNK_AO_*` into the `GALILEO_*` names, because galileo-core still reads them. It only fills a gap, so an explicit value wins — but a stale variable on either side points a backend at the wrong credential, silently, and a "Galileo" logger writing to Splunk AO is only noticeable by wondering why a tenant is empty. `configure_environment()` therefore sets the active backend's variables and **deletes the inactive backend's**, with a regression covering both directions.

**Stage 3** added the switch, mirroring the model-endpoint control presenters already use: `set_active_backend` clears the cached scorer names, bumps the revision and starts a fresh conversation, so one tenant's session never contains the other's turns. The Setup tab shows a Galileo / Splunk AO selector and then the fields for whichever is active — Splunk AO's two deployment modes need different credentials, and showing all of them at once invites filling in the wrong set. All three new secrets are reported the way the Galileo key already was, set flag plus last four, and a regression asserts no endpoint returns one.

Verified in the running container: both backends resolve to their own SDK, Galileo remains active, and `backends_view` reports Splunk AO as present but not configured.

**Not yet verified:** no trace has been sent to a Splunk AO tenant, because no credentials for one exist here. And the Stage 0 spike found that `mask_genuine_answer` will not work on the SaaS path — `_sink.emit()` converts and queues each span the moment it concludes, before the gate ever runs, so mutating the in-memory tree afterwards changes nothing that has been emitted. Masking works on the standalone path. That is recorded in TODO.md as the open item.

Backend suite: 81 passed; lint passed; production build passed.

## An inline regex flag the console would not compile

Adding the control by hand in the console failed with `Invalid regular expression: Invalid group`. Two things were wrong with the documented pattern, and the second matters well beyond the paste.

The lab sheet showed `\\b`, which is correct **inside a JSON definition** and wrong in the console's plain Pattern field, where it means a literal backslash. Both forms are now given, labelled.

More seriously, the pattern opened with `(?i)`. That is a Python inline flag. JavaScript rejects it outright — confirmed against node — and the console validates with JavaScript. A pattern that will not compile cannot match, and at runtime that is indistinguishable from a control that never fired: it surfaces as `decision: "unavailable"`, not as an error. This is a candidate explanation for the guardrail never having returned a `verified: true` deny, though it is not proof, since the fail-closed path has several causes and none has been observed directly.

`_foreign_account_pattern()` now builds case insensitivity from character classes, which every engine understands. Verified accepted by both Python's `re` and node's `RegExp`, matching `tom`, `TOM WHITFIELD`, `Dan Whitfield` and `1234` while leaving the customer's own `2058` and `1042` alone. Republished to controls 886, 887, 1029 and 1030, all four confirmed carrying a pattern with no inline flag. A regression asserts `(?` never appears in a generated pattern.

Backend suite: 87 passed.

## The readiness check assumed an API-resolving logger

Splunk AO reported "authenticated but the project or agent stream was not found" against a tenant where both existed and were correctly named. The fault was the check, not the tenant.

On Observability Cloud the logger exports over OTLP: project and stream are resource attributes on the spans, there is no API resolution step, and `project_id` and `agent_stream_id` are `None` by design. The check required an id on the logger and read its absence as a missing project. It now resolves the target through the API — `get_stream(name=..., project_name=...)` — and takes the ids from that, which works on both backends and removes a UUID-validation path that previously hid a 401 behind a schema error.

The resolved ids are kept on `Telemetry.target`, cleared whenever the backend or the connection changes.

**Knock-on, not yet addressed.** `Protection._evaluate` targets Agent Control with `stream_id_of(logger)`, which is `None` on OTLP for the same reason. The guardrail therefore cannot target a stream on Splunk AO Observability Cloud and will raise "No resolved log stream" before it reaches the gateway. It needs the resolved id from `Telemetry.target` rather than the logger. Recorded in TODO.md.

## Two sessions on Splunk AO, the named one empty

Galileo showed one session, `My Bank Agent`, holding the turn's trace. Splunk AO showed two: `My Bank Agent` with zero traces, and a second named `session` holding all the spans.

`start_session` publishes the session id into a **ContextVar**, via `_set_active_session_id`. `begin()` calls it inside `asyncio.to_thread`, and a worker thread's context does not flow back to the request — the same trap the code already documents for the parent span, hitting a second variable. So the API created the named session and the spans were exported from a context with no session id, leaving the backend to invent one to hold them.

Galileo is unaffected: it keeps the id on the logger object rather than in a ContextVar, which is why one backend was right and the other was not on identical code. The re-bind is therefore conditional on `_set_active_session_id` existing — calling `set_session` on Galileo's logger disturbs an export that already works, which three existing regressions caught immediately.

Verified against the live tenant: the API session id and `get_effective_session_id()` in the request context now match, and the trace exports.

**That was necessary but not sufficient, and the duplicate persists.** Listing the tenant's sessions afterwards showed both fixed runs still produced a pair, the `session` row appearing 17 and 40 seconds after the named one — on flush:

```
05:09:21  My Bank Agent   ext=diag-session-bind
05:09:56  My Bank Agent   ext=diag-bind-v2
05:10:02  session         ext=a2da8583…     the session id from the 05:09:21 run
05:10:13  session         ext=db4a9782…     the session id from the 05:09:56 run
```

The mechanism is visible in those external ids. The API-created session is keyed on `external_id` = the **conversation id**. The OTLP side carries its session as `gen_ai.conversation.id` baggage holding the SDK's generated **session UUID**, and the backend creates a session keyed on that string, naming it `session` because no name travels with it. The two keys are different values, so they can never dedupe to one row.

**Fixed by aligning the keys.** Comparing with Galileo made the mechanism obvious: Galileo attaches the session to the ingest request itself —

```python
TracesIngestRequest(traces=..., session_id=..., session_external_id=..., experiment_id=...)
```

— one call carrying the traces and the session identity together, so the server links them and a second session is impossible. OTLP has no such request. The only channel is one opaque string in `gen_ai.conversation.id` baggage, and the SDK was putting the session UUID there while the API session had been created with the conversation id as its external id.

Setting the baggage to the conversation id makes both sides agree. Verified against the tenant: a turn with conversation id `diag-single-001` produced exactly one session row, named `My Bank Agent`, where every previous run produced a pair.

**Correction to an earlier claim here:** this was said to be specific to Observability Cloud, on the assumption that standalone flushes through an ingest request like Galileo. It does not. `build_standalone_exporter` returns an `OTLPSpanExporter` just as `build_o11y_exporter` does — the two differ only in endpoint and auth header. Both Splunk AO deployments are OTLP, so every OTLP consequence applies to both: the duplicate session, the dropped trace output, the masking, and the unresolved stream id. The real split is Galileo's ingest API against Splunk AO's OTLP, not one AO mode against the other.

Unrelated but visible in the same comparison: Splunk AO shows no `bank-chat-turn` root row, because the OTLP path does not emit the Trace object itself — only spans, which carry the trace id. And it labels spans with OpenTelemetry semantic conventions (`invoke_agent`, `invoke_workflow`, `execute_tool`, `chat`) rather than the plain names Galileo shows. Both are SDK behaviour, not configuration.

Backend suite: 90 passed.
