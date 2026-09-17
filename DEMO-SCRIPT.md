# Splunky Finance presenter walkthrough

This walkthrough demonstrates four distinct layers:

1. **Observe** — a real model selects read-only banking tools and Galileo records the model, tool, and workflow spans.
2. **Evaluate** — Galileo custom metrics assess a deliberately controlled candidate for completeness, policy grounding, or numerical accuracy.
3. **Detect** — the presenter workspace shows the raw model output, controlled candidate, evidence, trace ID, candidate hash, and any actual metric results.
4. **Protect** — Agent Control evaluates a candidate before delivery. A verified deny or an unavailable control produces a safe customer response when protection is enabled.

All accounts, transactions, policies, and faults are synthetic. No transfer, payment, repayment, or account-change tool exists.

## Before the audience arrives

The presenter workspace includes its own automatically connected demo chat. No customer login, manual run creation, session linking, or logout is required. Settings are isolated to your presenter session; another browser or colleague has an independent demo. Refreshing preserves the active settings while the session and run remain valid.

1. Open `/demo-admin` and sign in with the presenter password. The demo chat connects automatically.
2. Optionally open customer banking at `/login` to demonstrate account pages. The scenario buttons control only the integrated demo chat.
3. Check the status cards:
   - **Model provider** should become `connected` after a successful model request.
   - **Galileo** should show `connected`; `Export: exported` appears only after a trace flush succeeds.
   - **Dataset** should show the intended seed, reference date, version, and transaction count.
4. Select **Check Galileo connection** if the connection state is unclear. This verifies the configured Galileo target but does not make a model call or prove a trace was exported.
5. Optionally select **Run paid preflight**. This explicitly calls the selected model and asks it to invoke `get_accounts`. A successful result must list an observed tool call; it tests provider access, the agent loop, the banking tool, and trace export. It does not test every scenario, metric, or Agent Control.
6. If custom metrics and Agent Control are part of the presentation, verify them in the Galileo tenant before the session. Run `scripts/configure_galileo.py` without `--apply` only to validate the local control schema. Remote creation requires an explicit reviewed `--apply` operation.

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

## Part 3 — choose a scenario directly

1. In `/demo-admin`, click a scenario button such as **Enable Incomplete Answer**.
2. Wait for the confirmation that it applies to the next demo message. The active button and **Scenario** indicator reflect the saved server setting.
3. Read the expected behavior below the buttons, then click **Run example question**.
4. Read **Scenario used** and the protection outcome above the response. These labels come from the backend result, not from the currently selected button.

Changing scenarios automatically starts a fresh conversation and switches protection off. Earlier responses retain their original labels. There is no need to sign out, open incognito, or link a customer session. Settings remain scoped to this presenter session. A new login or expired run starts a normal demo again.

**Check and block unsafe answers** is available for policy scenarios. It checks the candidate before delivery; a rejected answer or unavailable check produces a fallback. Protection readiness is separate from the actual response decision. Incomplete answers and incorrect totals demonstrate evaluation, not the configured policy protection control.

## Part 4 — completeness evaluation

1. Click **Enable Incomplete Answer**.
2. Check that **Scenario: Incomplete Answer** is active.
3. Click **Run example question**. The prompt is sent automatically in the integrated chat.
4. The live model still runs first. The controlled workflow then replaces the candidate with only the restaurant total, deliberately omitting the transaction count, three largest purchases, and previous-month comparison.
5. In **Latest chat evidence**, expand the event and compare:
   - **Raw model output** — what the live model produced.
   - **Candidate output** — the deliberately incomplete sentence.
   - **Customer-visible answer** — the candidate delivered while protection is off.
   - **Evidence** and trace identifiers — the reference material available to evaluation.
6. After asynchronous evaluation completes, select **Fetch actual Galileo scores**. A configured `SplunkyCompleteness` metric should reject the incomplete candidate. `pending_or_unconfigured` is not a failed score and must not be presented as one.

**What this shows:** evaluation can measure whether an answer covers every requested component. The fault is explicitly injected and is never misrepresented as an organic model failure.

## Part 5 — policy grounding evaluation

1. Click **Enable Hallucinated Policy**.
2. Click **Run example question** to send:

   > What is the daily external transfer limit on my Everyday account?

3. The controlled candidate says the limit is unlimited and requires no verification.
4. Compare that candidate with the retrieved policy evidence: the seeded policy says AUD $5,000 daily and verification is required.
5. Fetch actual Galileo scores when available. A configured `SplunkyGroundedness` metric should reject the unsupported claim.

**What this shows:** fluent policy language is insufficient; customer-facing policy claims must agree with retrieved authoritative material.

## Part 6 — numerical correctness evaluation

1. Click **Enable Incorrect Total**.
2. Click **Run example question**; the conversation was reset automatically.
3. The controlled candidate adds exactly AUD $100.00 to the authoritative total. With the default dataset it reports **$854.19** rather than **$754.19**.
4. Compare candidate output with **Inspect expected results** and the calculation evidence.
5. Fetch actual Galileo scores. A configured `SplunkyNumericalCorrectness` metric should reject the altered amount.

**What this shows:** a numerically plausible answer still fails when it disagrees with deterministic integer-cent calculations.

## Part 7 — protection before and after

This is the key protection demonstration.

### Before protection

1. Click **Enable Protection Before / After**.
2. Leave **Check and block unsafe answers** unchecked.
3. Click **Run example question**.
4. Show that the customer receives the controlled unlimited/no-verification candidate.
5. In evidence, note its candidate hash and event/run ID.

### After protection

1. Check **Check and block unsafe answers**.
2. Click **Run example question** again without reselecting the scenario or changing the dataset.
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

## Troubleshooting during the demo

| Symptom | Action |
| --- | --- |
| Provider unconfigured | Add the selected provider key to private `.env`, then restart backend |
| Agent temporarily unavailable | Check provider credit/quota, model access, and backend status |
| Galileo connected but export not attempted | Send a chat turn; connection checks do not create traces |
| Session visible but no child spans | Use a new turn on the current build; historical empty sessions cannot be reconstructed |
| Scores pending/unconfigured | Confirm custom metrics are created/enabled, wait for asynchronous evaluation, then fetch actual scores |
| Protection unverified | Configure/bind Agent Control and run a protected turn; the switch alone is not verification |
| Exact prompt rejected | Use **Run example question** for the active scenario |
| Replay rejected | Do not change prompt, scenario, or dataset between before/after turns |
| Customer chat not affected | Use the integrated **Demo chat** in the presenter workspace; scenario controls are scoped there |
| Settings changed in another tab | Review the refreshed selection and retry; stale requests are rejected |
| HTTP 429 from model provider | Check provider quota/credit; distinguish it from Cloudflare rate limiting |

## Suggested closing statement

> Splunky Finance separates observation, evaluation, detection, and protection. The model uses read-only tools over deterministic synthetic data. Controlled faults make quality failures repeatable. Galileo records and evaluates the candidate, while the awaited Agent Control gate determines whether that exact candidate reaches the customer. Every status shown here represents observed evidence; unavailable results are never presented as successful checks.
