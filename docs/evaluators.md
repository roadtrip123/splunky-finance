# Evaluators and guardrails

Which metrics to enable in the Galileo tenant, why each one is here, how they are defined in this
repository, and what the application does so they can score anything at all.

## Where they are defined

Everything published to a tenant comes from one file, `backend/app/observability/setup_definitions.py`:

| Object | What it holds |
| --- | --- |
| `JUDGES` | The description of each custom judge: one sentence of rubric per metric |
| `judge_prompt(name)` | Builds the full published prompt for one judge from its description plus the scoping rules that suit it |
| `BUILTIN_METRICS` | The Galileo-native evaluators to enable by slug |
| `CONTROLS` | The Agent Control guardrails, one entry per gated tool |
| `_foreign_account_pattern()` | The guardrail's deny-list, generated from the dataset so it cannot drift |
| `JUDGE_MODEL`, `JUDGE_COUNT` | `gpt-4.1-mini`, three voters |

It lives in `backend/app/` rather than `scripts/` because the container image copies only
`backend/app` and `data/`: a workshop participant running setup from the portal has no `scripts/`.

## Applying them

From `backend/`:

```bash
PYTHONPATH=. .venv/bin/python ../scripts/configure_galileo.py                    # validate schemas only
PYTHONPATH=. .venv/bin/python ../scripts/configure_galileo.py --apply            # create, enable, bind
PYTHONPATH=. .venv/bin/python ../scripts/configure_galileo.py --apply --refresh-judges
```

`--apply` creates any missing judge, enables the whole metric set on the log stream, and creates and
binds the controls. It also pushes the current control definition over whatever is already there, on
the original **and on every bound clone** — the clone is what the log stream evaluates, so refreshing
only the original leaves the old rule in force.

`--refresh-judges` publishes a new **version** of each judge and makes it the default. Editing a
prompt without this changes nothing in the tenant. Versioning rather than delete-and-recreate,
because deletion is refused for anyone but a metric's original creator and versioning keeps the
scoring history.

The same definitions back the portal's **Set up my project** button, which is hidden in workshop
mode so participants build their own.

Then confirm in the tenant console that every metric is enabled on the log stream at **100% sampling**, and that both controls are bound. The script requests remote setup; it does not prove the tenant accepted it. Tenant permissions and model entitlements differ between accounts.

## What the application does so evaluation works

[docs/instrumentation.md](instrumentation.md) has the short version with runnable code; this
section is why each choice exists.

Four deliberate choices in the logging, each one the result of a metric scoring wrongly without it:

- **A retriever span.** Policy lookup was a plain tool, so the RAG evaluators had no input and
  Completeness scored nothing. `PolicyRetriever` emits the retrieved chunks as a retriever span.
- **Evidence on the answer span.** `customer-visible-answer` logged with the question alone reported
  every claim unsupported, correct answers included. It now carries the turn's calculations, policies,
  customer and accounts as context.
- **The question in the trace output.** The record carries a `question` field. The trace input has it
  too, but a trace-level custom judge is not reliably given the input, and the one judge that needs
  the question rather than the evidence was inferring an "implied question" from the answer.
- **One answer in the trace.** After a fault is injected, `Telemetry.mask_genuine_answer` rewrites the
  agent's own answer out of every span — outputs *and* inputs, since the middleware spans carry the
  whole message list — and `raw_model_output` is stripped from the record before it becomes the trace
  output. A judge is handed the whole normalised trace, so a fuller draft left anywhere in it gets
  read as part of the answer. The presenter evidence still keeps both answers and the fault method.

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
| **SplunkyAnswerWholeQuestion** | Whether the answer covered every part the question asked. Derives the required parts from the `question` field rather than assuming a fixed list. |

All three are boolean, trace-level, on `gpt-4.1-mini`, with **three voters**. On a single judge a
borderline call flips the verdict between runs.

Each published prompt is its description plus scoping rules, assembled by `judge_prompt()`. The
rules are **not** the same for every judge, and that matters more than it looks:

| Rule | AnswerWholeQuestion | The other two |
| --- | --- | --- |
| An absent claim | **is** the failure | is not a failure |
| "an omitted part" in the list of other metrics' concerns | excluded | included |
| Other spans in the trace | ignore them; only `candidate_output` counts | — |
| Evidence and retrieved context | shows what was available, not what was said | — |

A single shared suffix carrying *"the absence of a claim is not a failure"* and an exclusion list
containing *"an omitted part"* is right for the other two and precisely wrong for the completeness
judge, whose whole job is to fail an omission. With the shared wording it stayed green on a
genuinely incomplete answer on every model tested. A regression asserts it is never told to ignore
omissions and that the other two keep the rule.

### Renamed

`SplunkyRequestCoverage` became `SplunkyAnswerWholeQuestion` and `SplunkyEntityIntegrity` became `SplunkyRightCustomer`, so each name says what it checks without needing the description. The originals still exist in the tenant but are no longer enabled: a metric can only be deleted by its creator, and that call is refused here. Scores recorded under the old names stay with the old metrics and do not carry across.

### Retired

- **SplunkyGroundedness** — built-in Context Adherence scores the same thing against the retriever span, and Galileo maintains it.
- **SplunkyCompleteness** — renamed to `SplunkyAnswerWholeQuestion`. It measured question-part coverage, not recall over retrieved context, and sharing a name with the built-in Completeness evaluator made both hard to explain. Its instructions also hardcoded the restaurant question, so it returned false for the wrong reason on anything else.

## Reading the scores

**The numerical judge reads every evidence key, not just one.** It was written against
`evidence.calculations`, which is where the spending tool writes. Balances land in
`evidence.lookups` and money movements in `evidence.transfers`, so any figure stated about a
balance or a transfer went unchecked — a wrong balance after a transfer passed all three judges.
It now checks all three, and because the failure was a real number attributed to the wrong
account, it is told to identify which account a figure is attributed to before comparing, and
that `from_account_balance_cents` belongs to `from_account` and not to `to_account`.

**A judge fails only on a contradiction it can point to.** An answer with its total removed is not a wrong total and not a wrong customer; it is an incomplete answer. Each judge returns true when its subject is simply absent, so every scenario lights exactly one judge. Wrong Customer is the sharpest case: its candidate quotes Dan Whitfield's real account and real balance, so the figures are correct and the question is answered. Only `SplunkyRightCustomer` rejects it. A metric that went red there would be grading outside its remit. If you edit a judge prompt or settings, the change only reaches the tenant with `--apply --refresh-judges`, which publishes a new version of each judge and makes it the default. Versioning rather than delete-and-recreate: deletion is refused for anyone but a metric's original creator, and versioning keeps the scoring history.

**The question travels in the trace output JSON, not only the trace input.** `SplunkyAnswerWholeQuestion` is the only judge that needs the question rather than the evidence, and it was the only one scoring a genuinely incomplete answer as complete — on every model, with the candidate verified incomplete beforehand. Reproducing the judge on `gpt-4.1-mini` settled it: given the question it returned false 6/6; given only the output payload it returned true 6/6, reasoning about an "implied question" it had reconstructed from the answer. The trace input is set correctly and read back correctly from the tenant, so a trace-level custom judge is simply not reliably given it. The record now carries a `question` field and the judge is told to read that field and never an implied question.

**The scoping wording differs per judge, and must.** A single shared suffix carrying *"the absence of a claim is not a failure"* and an exclusion list containing *"an omitted part"* is correct for `SplunkyNumericalCorrectness` and `SplunkyRightCustomer` and precisely wrong for `SplunkyAnswerWholeQuestion`, whose whole job is to fail an omission. With the shared wording that judge stayed green on a genuinely incomplete answer on every model tested, while the other two scored correctly. `judge_prompt()` in `setup_definitions.py` now builds each prompt with the absence rule and exclusion list that suit it, and a regression asserts the completeness judge is never told to ignore omissions.

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

`raw_model_output` has since been dropped from the trace output, which trims the payload as a side effect of keeping the genuine answer out of the trace. A further lever, not yet taken: the record still carries every account and top-purchase row, and trimming that to what the judges actually read would cut tokens again without dropping a metric.

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

## Agent Control: how the guardrails are built

Evaluators are detective controls — they tell you afterwards, which is fine for a wrong number and
useless for money that has left or a balance that has been read. The guardrails are preventive, and
there are two, one per action that cannot be undone by refusing the answer afterwards:

| Control | Gated tool | Prevents |
| --- | --- | --- |
| `splunky-transfer-deny` | `transfer_funds` | Moving money to another customer |
| `splunky-account-lookup-deny` | `get_account_balance` | Reading another customer's balance |

### The definition

Both are built by `_tool_deny_control(tool_name)` and differ only in the tool they name:

```json
{
  "condition": {
    "selector": { "path": "input" },
    "evaluator": { "name": "regex", "config": { "pattern": "\\b([Dd][Aa][Nn]\\s+[Ww][Hh][Ii][Tt][Ff][Ii][Ee][Ll][Dd]|[Tt][Oo][Mm]\\s+[Ww][Hh][Ii][Tt][Ff][Ii][Ee][Ll][Dd]|4127|1234|[Dd][Aa][Nn]|[Tt][Oo][Mm])\\b" } }
  },
  "execution": "server",
  "scope": { "step_types": ["tool"], "step_names": ["transfer_funds"], "stages": ["pre"] },
  "action": { "decision": "deny" },
  "enabled": true
}
```

Three parts matter.

**`"stages": ["pre"]` is the whole point.** At `post` the tool has already run: the money has moved
and the balance has been read, and all a control can block is the sentence describing it. At `pre`
the step carries no output yet, so the condition matches the call itself.

**No inline flags.** `(?i)` is a Python construct; other engines reject it as an invalid group,
and the console's own validator is one of them. A pattern that will not compile cannot match,
which at runtime is indistinguishable from a control that never fired — it surfaces as
`unavailable`, not as an error. Case insensitivity comes from character classes instead, which
every engine understands.

**The pattern is a deny-list, not `.+`.** Matching everything also refuses the customer's own
balance checks and their own transfers, which makes the guardrail a feature switch rather than a
guardrail — and a guardrail that breaks the product is not one anybody ships. `_foreign_account_pattern()`
generates it from `OTHER_CUSTOMERS` in the dataset generator, so the tenant definition cannot drift
from the accounts that actually exist. Longest names first, so `Tom Whitfield` is preferred over `Tom`
in the reported match.

**`"execution": "server"`** means Galileo evaluates it, not the application. The app asks and obeys;
it does not decide.

### How they reach the tenant

`configure_galileo.py --apply` creates each control if missing, pushes the current definition with
`set_control_data`, then calls `clone_and_bind_control` to attach it to the log stream. That call
*clones* as well as binds, so it runs only when no clone exists — calling it repeatedly leaves spare
copies behind, and a duplicate clone is what previously made the runtime return `unavailable`. Every
existing clone gets the refreshed definition too, because the clone is what actually evaluates.

### How the application obeys them

`ActionGuard`, an `AgentMiddleware` in `backend/app/agent.py`, wraps tool execution:

```python
GATED_TOOLS = ("transfer_funds", "get_account_balance")

async def awrap_tool_call(self, request, handler):
    if request.tool_call["name"] not in GATED_TOOLS:
        return await handler(request)
    allowed, decision = await self.protection.check_action(...)
    if allowed:
        return await handler(request)
    return ToolMessage(..., status="error")
```

A denial short-circuits before `handler` runs, so the tool is never invoked and no `transfer_funds`
span appears in the trace. `Protection.check_action` posts a `pre`-stage `EvaluationRequest` and
**fails closed**: anything that is not a genuine decision carrying evaluated controls blocks the
action. The customer sees `"That request is not available from My Bank Agent."`

### Two things the guardrail is not

**It is opt-in per run.** `check_action` returns `{"decision": "disabled"}` when the scenario is
not armed, and the tool runs freely. That is deliberate — the demo shows the transfer executing,
then blocks it — but it means the guardrail is a demo toggle rather than an always-on control.
Worth saying out loud rather than letting a room assume otherwise.

**`GATED_TOOLS` is a hardcoded allowlist of two.** Add a money-moving tool and forget the tuple
and it is ungated, silently. Deny-by-default — gating everything not on a read-only list — is the
safer shape for anything that ships.

### Telling a real deny from a fail-closed block

They look identical in the chat. `action_decisions` in the presenter evidence tells them apart:

| | Meaning |
| --- | --- |
| `decision: "deny"`, `verified: true` | A control evaluated and denied it. This is the goal. |
| `decision: "unavailable"`, `verified: false` | No verdict came back; the app blocked by failing closed |

An `unavailable` carries a `diagnosis.cause`, because four very different problems used to collapse
into one message:

| `cause` | What to fix |
| --- | --- |
| `no_control_selected` | The request arrived but nothing matched. Check the binding and the scope. |
| `control_errored` | A control ran and failed. `errors` has the detail. |
| `request_failed` | The call never completed. Check the Agent Control URL and key. |
| `not_configured` | No Agent Control URL saved in the app. |

A regex rejects a controlled condition known before the demo. It is not a general semantic validator
and should not be described as one. **Verify the binding produces a `verified: true` decision before
relying on it live** — a block alone does not prove a control ran.

## Known limits

- Built-in span-level evaluators score **every** LLM span, the injected answer included. Read the score on `customer-visible-answer` and expect questions about the others.
- **Fetch actual scores** reads trace-level metrics. Span-level built-in values may not appear there; read them in the console until this is confirmed against a live tenant.
- `pending_or_unconfigured` means no value was retrieved yet. It is not a failed score and must not be presented as one.
- Context Adherence has been confirmed returning real values from the live tenant. The other built-ins listed under **Deliberately not enabled** have not, so verify one real score before presenting any of them.
- `SplunkyAnswerWholeQuestion` scored correctly on 8 of 10 live runs after the trace-masking fix, with the candidate verified incomplete beforehand. The remaining two are unexplained. Two candidate causes point opposite ways: an `unverified_rewrite` shipping a complete answer, or judge variance. The `fault_method` field on a `true` trace distinguishes them. The other two judges have been unanimous throughout.
