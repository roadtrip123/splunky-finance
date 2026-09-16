# Splunky Finance presenter walkthrough

This walkthrough demonstrates four distinct layers:

1. **Observe** — a real model selects read-only banking tools and Galileo records the model, tool, and workflow spans.
2. **Evaluate** — Galileo custom metrics assess a deliberately controlled candidate for completeness, policy grounding, or numerical accuracy.
3. **Detect** — the presenter workspace shows the raw model output, controlled candidate, evidence, trace ID, candidate hash, and any actual metric results.
4. **Protect** — Agent Control evaluates a candidate before delivery. A verified deny or an unavailable control produces a safe customer response when protection is enabled.

All accounts, transactions, policies, and faults are synthetic. No transfer, payment, repayment, or account-change tool exists.

## Before the audience arrives

Use two tabs in the same browser profile because linking a presenter run requires both the presenter and customer session cookies.

1. Open the public application and sign in to customer banking at `/login`.
2. Open `/demo-admin` in a second tab and sign in with the separate presenter password.
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

Do this before starting a controlled presenter run, or leave the run on `normal_spending`.

1. Open **My Bank Agent**.
2. Start a new conversation.
3. Send exactly:

   > How much did I spend on restaurants last month?

4. Confirm the answer is consistent with the active expected results.
5. In Galileo, open the newest `bank-chat-turn` trace and expand approximately:

   `bank-chat-turn → Agent → model / tools → calculate_spending`

6. Point out the two model calls around the tool call: one to choose the tool and one to compose the answer from its result.

**What this shows:** a genuine model request selected an authoritative read-only tool. Galileo records model and tool spans rather than only a top-level session.

## Part 3 — create and link a presenter run

In the presenter tab:

1. Select **Start a new run**.
2. Keep **Output protection** disabled initially.
3. Select **Link customer session**.
4. Use **Open banking** or return to the already logged-in customer tab.
5. Start a new customer conversation whenever the scenario changes.

A run isolates scenario selection, controlled candidates, trace evidence, and before/after replay. Linking requires presenter and customer authentication in the same browser. A run is unnecessary for ordinary chat or ordinary Galileo tracing.

The message `Protection verification: unverified` is expected until a genuine Agent Control response has been received. Enabling a switch is configuration, not proof that a remote control ran.

## Part 4 — completeness evaluation

1. Select scenario **`incomplete_answer`**.
2. Copy the displayed prompt; the backend requires the exact selected scenario prompt.
3. In a new customer conversation, send it.
4. The live model still runs first. The controlled workflow then replaces the candidate with only the restaurant total, deliberately omitting the transaction count, three largest purchases, and previous-month comparison.
5. In **Latest run evidence**, expand the event and compare:
   - **Raw model output** — what the live model produced.
   - **Candidate output** — the deliberately incomplete sentence.
   - **Customer-visible answer** — the candidate delivered while protection is off.
   - **Evidence** and trace identifiers — the reference material available to evaluation.
6. After asynchronous evaluation completes, select **Fetch actual Galileo scores**. A configured `SplunkyCompleteness` metric should reject the incomplete candidate. `pending_or_unconfigured` is not a failed score and must not be presented as one.

**What this shows:** evaluation can measure whether an answer covers every requested component. The fault is explicitly injected and is never misrepresented as an organic model failure.

## Part 5 — policy grounding evaluation

1. Select scenario **`hallucinated_policy`**.
2. Copy and send the exact displayed prompt:

   > What is the daily external transfer limit on my Everyday account?

3. The controlled candidate says the limit is unlimited and requires no verification.
4. Compare that candidate with the retrieved policy evidence: the seeded policy says AUD $5,000 daily and verification is required.
5. Fetch actual Galileo scores when available. A configured `SplunkyGroundedness` metric should reject the unsupported claim.

**What this shows:** fluent policy language is insufficient; customer-facing policy claims must agree with retrieved authoritative material.

## Part 6 — numerical correctness evaluation

1. Select scenario **`incorrect_total`**.
2. Copy and send its exact restaurant-spending prompt in a new conversation.
3. The controlled candidate adds exactly AUD $100.00 to the authoritative total. With the default dataset it reports **$854.19** rather than **$754.19**.
4. Compare candidate output with **Inspect expected results** and the calculation evidence.
5. Fetch actual Galileo scores. A configured `SplunkyNumericalCorrectness` metric should reject the altered amount.

**What this shows:** a numerically plausible answer still fails when it disagrees with deterministic integer-cent calculations.

## Part 7 — protection before and after

This is the key protection demonstration.

### Before protection

1. Select **`guardrail_before_after`**.
2. Set **Output protection** to **Disabled**.
3. Copy and send the exact transfer-limit prompt in a new customer conversation.
4. Show that the customer receives the controlled unlimited/no-verification candidate.
5. In evidence, note its candidate hash and event/run ID.

### After protection

1. Return to the presenter tab and set **Output protection** to **Enabled — fail closed**.
2. Send the identical prompt again without changing the dataset or scenario.
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

- **New conversation** clears the customer conversation while retaining the presenter run.
- **Reset run** returns the run to `normal_spending`, clears replay state, and invalidates linked conversations. Use it between rehearsal sequences.
- **Start a new run** creates a new isolated presenter run. Link it again to the customer session.
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
| Exact prompt rejected | Copy the prompt again from the currently selected scenario |
| Replay rejected | Do not change prompt, scenario, or dataset between before/after turns |
| Customer run not affected | Link the current run again in the same browser profile |
| HTTP 429 from model provider | Check provider quota/credit; distinguish it from Cloudflare rate limiting |

## Suggested closing statement

> Splunky Finance separates observation, evaluation, detection, and protection. The model uses read-only tools over deterministic synthetic data. Controlled faults make quality failures repeatable. Galileo records and evaluates the candidate, while the awaited Agent Control gate determines whether that exact candidate reaches the customer. Every status shown here represents observed evidence; unavailable results are never presented as successful checks.
