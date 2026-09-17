# Splunky Finance presenter walkthrough

This walkthrough demonstrates four distinct layers:

1. **Observe** — a real model selects read-only banking tools and Galileo records the model, tool, and workflow spans.
2. **Evaluate** — Galileo custom metrics assess a deliberately controlled candidate for completeness, policy grounding, or numerical accuracy.
3. **Detect** — the presenter workspace shows the raw model output, controlled candidate, evidence, trace ID, candidate hash, and any actual metric results.
4. **Protect** — Agent Control evaluates a candidate before delivery. A verified deny or an unavailable control produces a safe customer response when protection is enabled.

All accounts, transactions, policies, and faults are synthetic. No transfer, payment, repayment, or account-change tool exists.

## Before the audience arrives

The presenter portal controls a connected banking chat. Both browsers communicate through the server; no direct browser-to-browser connection is used.

1. Sign into `/demo-admin`, then customer banking in another tab in the same browser profile. Open **My Bank Agent**. Automatic linking works regardless of which tab was opened first.
2. For a different computer/profile, select **Connect using pairing code**. In the banking chat expand **Demo connection**, enter the code, and click **Connect demo**. Codes expire in five minutes and are single-use. Confirm the portal shows **Applied to connected banking session**. Each presenter controls one session; disconnect before selecting another.
3. Check the status cards:
   - **Model provider** should become `connected` after a successful model request.
   - **Galileo** should show `connected`; `Export: exported` appears only after a trace flush succeeds.
   - **Dataset** should show the intended seed, reference date, version, and transaction count.
4. Select **Check Galileo connection** if the connection state is unclear. This verifies the configured Galileo target but does not make a model call or prove a trace was exported.
5. Optionally select **Run paid preflight**. This explicitly calls the selected model and asks it to invoke `get_accounts`. A successful result must list an observed tool call; it tests provider access, the agent loop, the banking tool, and trace export. It does not test every scenario, metric, or Agent Control.
6. If metrics and Agent Control are part of the presentation, verify them in the Galileo tenant before the session. [docs/evaluators.md](docs/evaluators.md) lists every metric, why it is enabled, and which are deliberately left off. Run `scripts/configure_galileo.py` without `--apply` only to validate the local control schema. Remote creation requires an explicit reviewed `--apply` operation.

Do not describe `connected` as `exported`, an exported trace as `scored`, or an enabled protection switch as a verified control decision.

## Authoritative reference values

With the default seed `42` and reference date `2026-09-15`, “last month” is `2026-08-01` inclusive through `2026-09-01` exclusive.

| Result | Expected value |
| --- | ---: |
| Restaurant spending | **AUD $754.19** |
| Posted restaurant purchases | **8** |
| Previous-month restaurant spending | **AUD $541.67** |
| Difference | **AUD $212.52 more** |
| Percentage change | **39.23% increase** |
| Largest restaurant purchase | Jacaranda Cafe (fictional), **$119.68**, 10 Aug 2026 |
| Second largest | Riverbend Bistro (fictional), **$113.43**, 6 Aug 2026 |
| Third largest | Guzman y Gomez, **$113.12**, 30 Aug 2026 |
| Everyday external transfer limit | **AUD $5,000 per day; verification required** |

Use **Inspect expected results** in the presenter workspace to retrieve the active dataset values. If the dataset seed or reference date was changed, that live output is authoritative rather than this table.

## Part 1 — ordinary customer banking

In the customer tab:

1. Show the Everyday, Savings, and credit-card accounts.
2. Open an account and demonstrate date, category, search, sort, pending-state, and pagination controls.
3. Explain that amounts are integer AUD cents in the dataset, posted entries reconcile to balances, pending entries do not affect posted spending, and transfers/repayments do not count as purchases.

**What this shows:** the model is not the source of truth. The deterministic banking ledger and calculation functions are.

## Part 2 — genuine tool-backed assistant turn

Use ordinary customer chat, or select **Normal Answers** in the presenter workspace and use its integrated chat.

1. Open **My Bank Agent**.
2. Start a new conversation.
3. Send exactly:

   > How much did I spend on restaurants last month?

4. Confirm the answer is consistent with the active expected results.
5. In Galileo, open the newest `bank-chat-turn` trace and expand approximately:

   `bank-chat-turn → Agent → model / tools → calculate_spending`

6. Point out the two model calls around the tool call: one to choose the tool and one to compose the answer from its result.

**What this shows:** a genuine model request selected an authoritative read-only tool. Galileo records model and tool spans rather than only a top-level session.

## Part 3 — control the existing banking conversation

1. Keep the banking chat open. Its footer says **Fictional banking data only** in the usual muted colour.
2. In the portal, click **Enable Incomplete Answer**.
3. Without refreshing banking, watch the same footer turn muted red. The text, position, size, and weight stay unchanged. The portal confirms **Applied to connected banking session** after the browser acknowledges the change.
4. Send the displayed example question in the existing banking conversation. The response should contain only the total, omitting top purchases and the previous-month comparison.
5. Click **Normal Answers** in the portal. Wait for the footer to return to its original muted colour, then ask the same question again. This response uses normal model/tool execution without the deliberate fault.

The visible transcript is preserved. Model context resets on setting changes so deliberately faulty prior answers do not contaminate the next answer. An in-flight response finishes using its original scenario; changes affect subsequent requests. Normal mode does not guarantee model correctness.

Muted amber means synchronization or connection trouble; sending is paused until confirmation. Hover over the footer for details, or use its accessible description. The portal identifies the connected session and shows whether it has acknowledged settings. No scenario labels or traffic-light icons appear on customer responses; inspect detailed **Latest chat evidence** in the portal.

If banking is closed, reopen My Bank Agent to resume acknowledgments. Connections remain stable until disconnected or expired. After explicit disconnect, use a new pairing code to reconnect. Refreshing retains valid links; a server restart or new login may require reconnection. Another computer never silently takes over an existing connection.

The integrated presenter **Demo chat** is still available for rehearsal. **Run example question** sends there, not to the customer banking tab. For a live banking demonstration, copy the displayed prompt into My Bank Agent.

**Check and block unsafe answers** is available for policy scenarios. Rejection or a check that cannot complete produces a fallback. Read the actual decision in the portal; a checked switch does not prove remote control execution.

## Part 4 — request coverage evaluation

1. Click **Enable Incomplete Answer**.
2. Check that **Scenario: Incomplete Answer** is active.
3. Send the displayed example question in the connected banking chat. For rehearsal only, **Run example question** sends it in the portal.
4. The live model still runs first. A second bounded model pass then rewrites the answer to drop parts of it. Which parts are dropped is not fixed, so read the candidate before describing it; the reliable claim is that the answer no longer covers everything the question asked.
5. In **Latest chat evidence**, expand the event and compare:
   - **Raw model output** — what the live model produced.
   - **Candidate output** — the deliberately incomplete sentence.
   - **Customer-visible answer** — the candidate delivered while protection is off.
   - **Evidence** and trace identifiers — the reference material available to evaluation.
6. After asynchronous evaluation completes, select **Fetch actual Galileo scores**. The `SplunkyRequestCoverage` judge should reject the candidate. `pending_or_unconfigured` is not a failed score and must not be presented as one.

**What this shows:** evaluation can measure whether an answer covers every requested component. This is question-part coverage, not the built-in Completeness evaluator, which measures recall over retrieved context and is exercised in Part 5. The fault is explicitly injected and is never misrepresented as an organic model failure.

## Part 5 — policy grounding evaluation

1. Click **Enable Hallucinated Policy**.
2. Send the displayed question in the connected banking chat:

   > What is the daily external transfer limit on my Everyday account?

3. The controlled candidate says the limit is unlimited and requires no verification.
4. Compare that candidate with the retrieved policy evidence: the seeded policy says AUD $5,000 daily and verification is required.
5. Fetch actual Galileo scores when available. Built-in **Context Adherence** should reject the unsupported claim: it scores the answer against the chunks the policy retriever returned. The `SplunkyGroundedness` judge this scenario used previously was retired because the built-in measures the same thing.

**What this shows:** fluent policy language is insufficient; customer-facing policy claims must agree with retrieved authoritative material.

## Part 6 — numerical correctness evaluation

1. Click **Enable Incorrect Total**.
2. Send the displayed restaurant-spending question in the connected banking chat; model context resets automatically.
3. A bounded model pass alters a number in the answer. The altered figure is not fixed, so read the candidate rather than announcing an expected amount; the authoritative total is **$754.19**.
4. Compare candidate output with **Inspect expected results** and the calculation evidence.
5. Fetch actual Galileo scores. A configured `SplunkyNumericalCorrectness` metric should reject the altered amount.

**What this shows:** a numerically plausible answer still fails when it disagrees with deterministic integer-cent calculations.

## Part 7 — wrong customer

This is the scenario that makes the cost of no evaluation layer obvious.

1. Click **Enable Wrong Customer**.
2. Send the restaurant-spending question in the connected banking chat.
3. The customer receives an answer addressed to a different person, citing an account they do not own:

   > Hi Dan — your Everyday account (•••• 4127) spent $3,182.40 on restaurants last month across 14 purchases...

4. In **Latest chat evidence**, show that the seeded dataset contradicts it on four independent axes:

   | Candidate claims | Dataset holds |
   | --- | --- |
   | Dan Whitfield | Alex Taylor (`syn-alex`) |
   | •••• 4127 | •••• 1042 |
   | $3,182.40 across 14 purchases | $754.19 across 8 |
   | Bunnings, Qantas, Harvey Norman | Jacaranda Cafe, Riverbend Bistro, Guzman y Gomez |

5. Say this once, with the evidence panel open:

   > The banking tools cannot return another customer's data. Customer scope is captured server-side in the tool closure and is never accepted as a model argument. This identity was injected after the model call.

6. `SplunkyEntityIntegrity` and Context Adherence should both reject the candidate.

Unlike the other scenarios, this candidate is a **fixed template**, not a model rewrite — the evidence panel reports `fault_method: fixed_template`. Two reasons: a live model asked to impersonate a cross-customer exposure may refuse, and the bound regex control needs a string known before the demo.

**What this shows:** a fluent, confident, well-formatted answer can be wrong about *who the customer is*. No amount of output polish catches that; comparing the answer against authoritative evidence does.

## Part 8 — protection before and after

This is the key protection demonstration.

### Before protection

1. Click **Enable Protection Before / After**.
2. Leave **Check and block unsafe answers** unchecked.
3. Send the displayed question in the connected banking chat. **Wrong Customer** is the stronger close here; the transfer-limit scenario works as a warm-up.
4. Show that the customer receives the controlled unlimited/no-verification candidate.
5. In evidence, note its candidate hash and event/run ID.

### After protection

1. Check **Check and block unsafe answers**.
2. Send the same question in the same connected banking chat without reselecting the scenario or changing the dataset.
3. The application replays the exact frozen candidate and evidence. It does **not** make a second model call.
4. Verify the second event has:
   - `replayed: true`;
   - the same candidate hash as the first event;
   - the first event as its source run;
   - a genuine Agent Control decision if the tenant control is configured.
5. The customer should receive the safe fallback when the verified control denies the candidate.

If Agent Control is missing, unreachable, or returns no evaluated controls, the application also fails closed. In that case the decision remains `unavailable`/unverified. Explain this as safe fallback behavior, not as proof that Agent Control detected the policy error.

**What this shows:** the before/after comparison holds model output constant. The only intended difference is the awaited output gate before customer delivery.

## Reading the evidence panel

| Field | Meaning |
| --- | --- |
| Raw model output | Genuine selected-provider output before controlled injection |
| Candidate output | Text presented to evaluation/protection; may be deliberately injected |
| Fault method | `model_rewrite` for a second model pass, `fixed_template` for constant injected text, empty when no fault is active |
| Customer-visible answer | Delivered candidate or safe fallback after the gate |
| Candidate hash | SHA-256 identity used to prove same-candidate replay |
| Trace ID | Actual Galileo trace identifier, or unavailable |
| Observed tool calls | Tools actually observed in agent messages |
| Usage | Provider token metadata when supplied |
| Evaluation | Actual fetched metrics, pending/unconfigured, or failed; never invented |
| Decision | Disabled, verified allow/deny, or unavailable fail-closed result |
| Source run ID | Original event used for before/after replay |

## Reset controls

- **New conversation** starts a fresh chat while retaining the active scenario and protection settings. Earlier response labels remain visible.
- **Normal Answers** disables deliberate faults and protection, resets the conversation, and clears before/after replay when switching scenarios.
- Selecting another scenario resets conversation context automatically. Refreshing keeps the saved scenario but clears the local chat transcript; evidence remains available for the active run.
- **Confirm and reset data** regenerates the entire synthetic dataset with the selected seed/reference date, increments the dataset version, and invalidates all conversations and comparisons. Do not use this during a normal presentation unless reseeding is the topic.

## Honest status language

Use these exact distinctions:

- **Connected** — credentials and configured target were resolved.
- **Exported** — a trace flush completed without a reported exporter error.
- **Pending/unconfigured** — no actual metric value was retrieved yet.
- **Verified allow/deny** — Agent Control returned a real evaluation containing evaluated controls.
- **Unavailable/fallback** — protection was enabled but no verified control decision was available.
- **Simulation/injection** — the presenter workflow deliberately altered a candidate after the genuine model call.
- **Fixed template** — the candidate is constant text, not a model rewrite. Only Wrong Customer uses this.

## Troubleshooting during the demo

| Symptom | Action |
| --- | --- |
| Provider unconfigured | Add the selected provider key to private `.env`, then restart backend |
| Agent temporarily unavailable | Check provider credit/quota, model access, and backend status |
| Galileo connected but export not attempted | Send a chat turn; connection checks do not create traces |
| Session visible but no child spans | Use a new turn on the current build; historical empty sessions cannot be reconstructed |
| Scores pending/unconfigured | Confirm metrics are enabled at 100% sampling, wait for asynchronous evaluation, then fetch actual scores |
| Only `Splunky*` scores appear | The three custom judges are trace-level; the five built-in evaluators are span-level. Read built-in values in the Galileo console until the portal reads span metrics |
| Protection unverified | Configure/bind Agent Control and run a protected turn; the switch alone is not verification |
| Exact prompt rejected | Use **Run example question** for the active scenario |
| Replay rejected | Do not change prompt, scenario, or dataset between before/after turns |
| Customer chat not affected | Open My Bank Agent and check the portal connection acknowledgment; use pairing for another browser or computer |
| Chats missing from Latest chat evidence | The panel shows only the current presenter run. Presenter logout abandons earlier events, which stay in memory but can no longer be displayed; read those turns in the Galileo console |
| Footer amber | Wait for reconnection; if expired, disconnect and pair again |
| Pairing code rejected | Generate a fresh code; codes expire after five minutes and are single-use |
| Settings changed in another tab | Review the refreshed selection and retry; stale requests are rejected |
| HTTP 429 from model provider | Check provider quota/credit; distinguish it from Cloudflare rate limiting |

## Suggested closing statement

> Splunky Finance separates observation, evaluation, detection, and protection. The model uses read-only tools over deterministic synthetic data. Controlled faults make quality failures repeatable. Galileo records and evaluates the candidate, while the awaited Agent Control gate determines whether that exact candidate reaches the customer. Every status shown here represents observed evidence; unavailable results are never presented as successful checks.
