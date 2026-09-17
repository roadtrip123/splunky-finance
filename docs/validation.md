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
