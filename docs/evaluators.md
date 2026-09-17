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

## Reading the scores

**A judge fails only on a contradiction it can point to.** An answer with its total removed is not a wrong total and not a wrong customer; it is an incomplete answer. Each judge returns true when its subject is simply absent, so most scenarios light exactly one judge. Wrong Customer lights two by design: its candidate misstates both the identity and the figures. If you edit a judge prompt, the change only reaches the tenant with `--apply --refresh-judges`, which deletes and recreates it and loses that judge's historical scores.

**Built-in span-level metrics score every LLM span in the trace.** A turn has up to four: one model call to choose the tool, one to compose the answer, the fault writer when a scenario is active, and the logged `customer-visible-answer` span. Context Adherence therefore reports a mix such as `false 2 / true 1` even on a correct answer.

Two of those spans score low for reasons unrelated to answer quality. The tool-choosing call has no prose output. The `customer-visible-answer` span is logged with `add_llm_span(input=prompt, output=candidate)` and **no context**, so the evaluator sees unsupported claims whatever the answer says; adherence on that span is not meaningful and should not be read. It remains the node the Agent Control output control scopes, which is what it was added for.

The span worth reading is the agent's answer-composing call. The LangChain callback attaches the tool result to it, so it scores the answer against real evidence: verified at `1.0` for a correct total and `0.0` for a correct total with an invented fee appended, with a rationale naming the fee.

**Completeness returns a percentage, not a verdict.** Use the direction, not the absolute value: a correct answer and a deliberately incomplete one scored 44% and 25% on the same question. The gap is the demonstration; neither number means much alone.

## Deliberately not enabled

| Evaluator | Reason |
| --- | --- |
| **Correctness (Factuality)** | Standalone judge with no reference answer. Cannot adjudicate the seeded totals. |
| **PII detection** | The wrong-customer identity is fabricated, not leaked. This evaluator would either miss it or fire for a reason that has to be explained away. |
| **A judge for invented fees** | Not needed. Context Adherence catches an invented fee stated alongside correct figures, because the agent's model calls carry their tool results as context. Verified against a live trace. |
| **Chunk Relevance, Context Precision, Precision @ K** | Policy search is keyword overlap and returns some irrelevant chunks. These would score honestly but poorly. Enable them only to demonstrate retrieval-quality problems deliberately. |
| **Ground Truth Adherence** | Viable once `expected_results` is wired in as ground truth. Not configured. |
| **Text-to-SQL, Multimodal** | No SQL generation and no image or audio input. |

## Scenario to metric map

| Scenario | Metric that should reject it |
| --- | --- |
| Incomplete Answer | `SplunkyRequestCoverage` |
| Hallucinated Policy | Context Adherence |
| Incorrect Total | `SplunkyNumericalCorrectness` |
| Wrong Customer | `SplunkyEntityIntegrity` and `SplunkyNumericalCorrectness`, plus Context Adherence |
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
