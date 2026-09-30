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

Metric names are resolved against the tenant and the available set differs between tenants. This one exposes Tool Error as `tool_error_rate`. The setup script checks every name against the tenant's scorer list before enabling, and names the missing ones rather than failing with a raw traceback. The tenant also contains many hand-made metrics from other users with similar titles (`Completeness - Craig`, `Context Adherence - gaxie`); enable the `preset` ones listed above, not those copies.

These read the spans the application logs: policy lookup emits a **retriever span** carrying the retrieved chunks, and the delivered candidate is logged as an LLM span named **`customer-visible-answer`**. Without those spans the RAG evaluators have no input.

## Custom judges

Custom judges are worth their cost only where no built-in can know the rule. Each is an LLM graded against written instructions, registered by the setup script.

| Judge | Why a built-in cannot do it |
| --- | --- |
| **SplunkyNumericalCorrectness** | Built-in Correctness has no reference data. It cannot know that $854.19 is wrong and $754.19 is right; both are plausible. This judge compares against `evidence.calculations` in integer AUD cents. |
| **SplunkyRightCustomer** | Checks every name and masked account number in the candidate against `evidence.customer` and `evidence.accounts`. Customer identity is seeded into evidence server-side, so this holds even when no profile tool is called. |
| **SplunkyAnswerWholeQuestion** | Whether the answer covered every part the question asked. Derives the required parts from the input rather than assuming a fixed list. |

### Renamed

`SplunkyRequestCoverage` became `SplunkyAnswerWholeQuestion` and `SplunkyEntityIntegrity` became `SplunkyRightCustomer`, so each name says what it checks without needing the description. The originals still exist in the tenant but are no longer enabled: a metric can only be deleted by its creator, and that call is refused here. Scores recorded under the old names stay with the old metrics and do not carry across.

### Retired

- **SplunkyGroundedness** — built-in Context Adherence scores the same thing against the retriever span, and Galileo maintains it.
- **SplunkyCompleteness** — renamed to `SplunkyAnswerWholeQuestion`. It measured question-part coverage, not recall over retrieved context, and sharing a name with the built-in Completeness evaluator made both hard to explain. Its instructions also hardcoded the restaurant question, so it returned false for the wrong reason on anything else.

## Reading the scores

**A judge fails only on a contradiction it can point to.** An answer with its total removed is not a wrong total and not a wrong customer; it is an incomplete answer. Each judge returns true when its subject is simply absent, so every scenario lights exactly one judge. Wrong Customer is the sharpest case: its candidate quotes Dan Whitfield's real account and real balance, so the figures are correct and the question is answered. Only `SplunkyRightCustomer` rejects it. A metric that went red there would be grading outside its remit. If you edit a judge prompt or settings, the change only reaches the tenant with `--apply --refresh-judges`, which publishes a new version of each judge and makes it the default. Versioning rather than delete-and-recreate: deletion is refused for anyone but a metric's original creator, and versioning keeps the scoring history.

**Each judge is scoped to one property and told to ignore the others.** Without that, a judge that had correctly established its own subject was fine would fail the answer anyway on noticing a different defect. `SplunkyRightCustomer` said in its own reasoning that "misnaming a person doesn't apply here" and then returned false because the total was wrong. A judge must return true when its property holds, even when the answer is obviously wrong for a reason another metric owns.

**Completeness roll-ups do not rank answers.** A deliberately incomplete answer rolled up to 92% while the correct answer on the same question rolled up to 78%. Read per-span values, and do not put the roll-up on screen.

**All three judges use three voters.** On a single judge a borderline call flips the whole verdict between runs — `SplunkyAnswerWholeQuestion` returned true and then false on the same scenario and question, with nothing left unanswered either time. Three judges vote, matching the built-in evaluators.

**Built-in span-level metrics score every LLM span in the trace.** A turn has up to four: one model call to choose the tool, one to compose the answer, the fault writer when a scenario is active, and `customer-visible-answer`. The last two are logged explicitly rather than through the LangChain callback, which names chat-model spans after the model class and left the fault writer indistinguishable from the agent's genuine calls. Context Adherence therefore reports a mix such as `false 2 / true 1` even on a correct answer.

The `customer-visible-answer` span now carries this turn's evidence as context, so it can be judged on the answer rather than reported unsupported. Tool definitions are deliberately left off it: Tool Selection Quality scores LLM spans and would fail one that advertises tools and selects none.

The tool-choosing call is genuinely borderline and varies between runs, scoring `[1,1,1]` on one trace and `[0,0,1]` on another, because judges disagree about whether a span containing only a tool call can be adherent. Expect it to move.

The span that scores most reliably is the agent's answer-composing call. The LangChain callback attaches the tool result to it, and it has been verified at `1.0` adherence and `100%` completeness for a correct answer, and `0.0` for a correct total with an invented fee appended, with a rationale naming the fee.

**Completeness returns a percentage, not a verdict, and the trace roll-up averages every LLM span.** On the answer-composing span a correct answer scored `100%`; the same turn rolled up to `33%` because spans without context average in. Read the per-span value, not the roll-up.

## Cost

Evaluation cost was measured per turn against live traces. The set was cut from seven metrics to four, from roughly $0.22 a turn to $0.035, an 84% reduction, without losing anything the demonstration shows.

| Metric | Per turn | Kept |
| --- | ---: | --- |
| `completeness` | $0.13-0.18 | No. Around 78% of the entire bill, and its roll-up ranked a deliberately incomplete answer above a correct one. |
| `context_adherence` | $0.022 | Yes. The Galileo-native evaluator that works here, and the one whose rationale named the invented fee. |
| `tool_selection_quality` | $0.009 | No. Correct on every run but never caught a problem. |
| `tool_error_rate` | $0.002 | No. Same. |
| Each custom judge | $0.004 | Yes. These are what detect the scenarios. |

Dropping `context_adherence` as well would reach about $0.013 a turn, but every remaining metric would then be one written in-house, which weakens a demonstration of Galileo's own evaluation.

A further lever, not yet taken: the custom judges each consume around 9,000 tokens because the trace output carries the whole record, including every account and top-purchase row. Trimming that to what the judges actually read would cut tokens again without dropping a metric.

## Deliberately not enabled

| Evaluator | Reason |
| --- | --- |
| **Correctness (Factuality)** | Standalone judge with no reference answer. Cannot adjudicate the seeded totals. |
| **PII detection** | The wrong-customer identity is fabricated, not leaked. This evaluator would either miss it or fire for a reason that has to be explained away. |
| **A judge for invented fees** | Not needed. Context Adherence catches an invented fee stated alongside correct figures, because the agent's model calls carry their tool results as context. Verified against a live trace. |
| **Chunk Relevance, Context Precision, Precision @ K** | Policy search is keyword overlap and returns some irrelevant chunks. These would score honestly but poorly. Enable them only to demonstrate retrieval-quality problems deliberately. |
| **Ground Truth Adherence** | Viable once `expected_results` is wired in as ground truth. Not configured. |
| **Completeness** | Enabled for a time and removed on cost. See the section above. Its per-span values were sound; the trace roll-up was not, and it accounted for most of the evaluation bill. |
| **Tool Selection Quality, Tool Error Rate** | Correct on every run but never caught a problem. Removed on cost. |
| **Action Completion** | Enabled for a time and removed. It produced no value on any trace or session across every run. This tenant offers it only as the Luna small-model variant, and the SDK exposes no way to close a session for a session-scoped metric to score. Reassigning the judge model changed nothing, which fits: that setting governs LLM judges, not Luna. |
| **Text-to-SQL, Multimodal** | No SQL generation and no image or audio input. |

## Scenario to metric map

| Scenario | Metric that should reject it |
| --- | --- |
| Incomplete Answer | `SplunkyAnswerWholeQuestion` |
| Incorrect Total | `SplunkyNumericalCorrectness` |
| Wrong Customer | `SplunkyRightCustomer`, plus Context Adherence |
| Guardrail Cross-Customer Access | No evaluator. The pre-execution Agent Control decision is the result |

## Agent Control

Two server-side regex deny controls, both scoped to the `customer-visible-answer` LLM span at the `post` stage:

- `splunky-seeded-policy-deny` — matches the seeded unlimited-transfer-limit claim.
- `splunky-wrong-customer-deny` — matches the injected wrong-customer identity, anchored on ASCII so it does not depend on the masked-number bullet characters.

A regex rejects a controlled contradiction known before the demo. It is not a general semantic validator, and it should not be described as one. Until the `customer-visible-answer` span existed, no control scoped to that step name could fire at all; verify the binding produces a real decision before relying on it live.

## Known limits

- Built-in span-level evaluators score **every** LLM span, the injected answer included. Read the score on `customer-visible-answer` and expect questions about the others.
- **Fetch actual Galileo scores** reads trace-level metrics. Span-level built-in values may not appear there; read them in the console until this is confirmed against a live tenant.
- `pending_or_unconfigured` means no value was retrieved yet. It is not a failed score and must not be presented as one.
- No built-in evaluator here has been confirmed to return an actual value from a live tenant. Enable them and verify one real score before presenting them.
