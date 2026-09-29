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
