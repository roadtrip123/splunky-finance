# Evaluator setup

Which metrics to enable in the Galileo tenant, why each one is here, and what the demo shows with it.

Apply them with the setup script from `backend/`:

```bash
PYTHONPATH=. .venv/bin/python ../scripts/configure_galileo.py          # validate control schemas only
PYTHONPATH=. .venv/bin/python ../scripts/configure_galileo.py --apply  # create judges, enable metrics, bind controls
```

Then confirm in the tenant console that every metric is enabled on the log stream at **100% sampling**, and that both controls are bound. The script requests remote setup; it does not prove the tenant accepted it. Tenant permissions and model entitlements differ between accounts.

## Built-in evaluators to enable

| Evaluator | Level | Why it is here |
| --- | --- | --- |
| **Context Adherence** (`context_adherence`) | LLM span | Primary metric. Fails the wrong-customer answer and the invented policy. Replaces the retired `SplunkyGroundedness` judge. |
| **Completeness** (`completeness`) | LLM span | Paired with Context Adherence on a policy question: the same answer scores high adherence and low completeness. |
| **Tool Selection Quality** (`tool_selection_quality`) | LLM span | Gives the genuine tool-backed turn an actual score instead of only showing spans. |
| **Tool Error Rate** (`tool_error_rate`) | Tool span | Detects tool execution failures; near-free once tool spans are clean. |
| **Action Completion** (`action_completion_luna`) | Session | Whether the agent accomplished the user's goal. Sessions are already keyed by conversation. |

Metric names are resolved against the tenant and the available set differs between tenants. This one exposes Action Completion only as the small-language-model `_luna` variant, and Tool Error as `tool_error_rate`. The setup script checks every name against the tenant's scorer list before enabling, and names the missing ones rather than failing with a raw traceback. The tenant also contains many hand-made metrics from other users with similar titles (`Completeness - Craig`, `Context Adherence - gaxie`); enable the `preset` ones listed above, not those copies.\n\nThese read the spans the application logs: policy lookup emits a **retriever span** carrying the retrieved chunks, and the delivered candidate is logged as an LLM span named **`customer-visible-answer`**. Without those spans the RAG evaluators have no input.

## Custom judges

Custom judges are worth their cost only where no built-in can know the rule. Each is an LLM graded against written instructions, registered by the setup script.

| Judge | Why a built-in cannot do it |
| --- | --- |
| **SplunkyNumericalCorrectness** | Built-in Correctness has no reference data. It cannot know that $854.19 is wrong and $754.19 is right; both are plausible. This judge compares against `evidence.calculations` in integer AUD cents. |
| **SplunkyEntityIntegrity** | Checks every name and masked account number in the candidate against `evidence.customer` and `evidence.accounts`. Customer identity is seeded into evidence server-side, so this holds even when no profile tool is called. |
| **SplunkyRequestCoverage** | Whether the answer covered every part the question asked. Derives the required parts from the input rather than assuming a fixed list. |

### Retired

- **SplunkyGroundedness** — built-in Context Adherence scores the same thing against the retriever span, and Galileo maintains it.
- **SplunkyCompleteness** — renamed to `SplunkyRequestCoverage`. It measured question-part coverage, not recall over retrieved context, and sharing a name with the built-in Completeness evaluator made both hard to explain. Its instructions also hardcoded the restaurant question, so it returned false for the wrong reason on anything else.

## Deliberately not enabled

| Evaluator | Reason |
| --- | --- |
| **Correctness (Factuality)** | Standalone judge with no reference answer. Cannot adjudicate the seeded totals. |
| **PII detection** | The wrong-customer identity is fabricated, not leaked. This evaluator would either miss it or fire for a reason that has to be explained away. |
| **Chunk Relevance, Context Precision, Precision @ K** | Policy search is keyword overlap and returns some irrelevant chunks. These would score honestly but poorly. Enable them only to demonstrate retrieval-quality problems deliberately. |
| **Ground Truth Adherence** | Viable once `expected_results` is wired in as ground truth. Not configured. |
| **Text-to-SQL, Multimodal** | No SQL generation and no image or audio input. |

## Scenario to metric map

| Scenario | Metric that should reject it |
| --- | --- |
| Incomplete Answer | `SplunkyRequestCoverage` |
| Hallucinated Policy | Context Adherence |
| Incorrect Total | `SplunkyNumericalCorrectness` |
| Wrong Customer | `SplunkyEntityIntegrity`, and Context Adherence |
| Protection Before / After | Context Adherence, plus the bound Agent Control decision |

## Agent Control

Two server-side regex deny controls, both scoped to the `customer-visible-answer` LLM span at the `post` stage:

- `splunky-seeded-policy-deny` — matches the seeded unlimited-transfer-limit claim.
- `splunky-wrong-customer-deny` — matches the injected wrong-customer identity, anchored on ASCII so it does not depend on the masked-number bullet characters.

A regex rejects a controlled contradiction known before the demo. It is not a general semantic validator, and it should not be described as one. Until the `customer-visible-answer` span existed, no control scoped to that step name could fire at all; verify the binding produces a real decision before relying on it live.

## Known limits

- Built-in span-level evaluators score **every** LLM span, including `controlled-fault-writer`. Read the score on `customer-visible-answer` and expect questions about the others.
- **Fetch actual Galileo scores** reads trace-level metrics. Span-level built-in values may not appear there; read them in the console until this is confirmed against a live tenant.
- `pending_or_unconfigured` means no value was retrieved yet. It is not a failed score and must not be presented as one.
- No built-in evaluator here has been confirmed to return an actual value from a live tenant. Enable them and verify one real score before presenting them.
