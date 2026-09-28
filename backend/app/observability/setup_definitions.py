"""Judges, metrics and controls shared by the setup script and the in-app setup endpoint.

These live in the package rather than in scripts/ because the container image copies only
backend/app and data/; a workshop participant runs setup from the portal, where scripts/ is
not present.
"""

def _tool_deny_control(tool_name):
    """Server-side deny on a tool call, evaluated before the tool runs.

    The `pre` stage is what makes this a guardrail rather than an audit trail: at `post` the tool
    has already executed and the money has already moved. The step carries no output at this stage,
    so the condition matches the call itself.
    """
    return {
        "condition": {
            "selector": {"path": "input"},
            "evaluator": {"name": "regex", "config": {"pattern": "(?i).+"}},
        },
        "execution": "server",
        "scope": {"step_types": ["tool"], "step_names": [tool_name], "stages": ["pre"]},
        "action": {"decision": "deny"},
        "enabled": True,
    }


# One control. The two earlier regex controls matched answer text at the `post` stage, which can
# only suppress a sentence describing an action that has already happened.
CONTROLS = {
    "splunky-transfer-deny": _tool_deny_control("transfer_funds"),
}
# Custom judges earn their place only where no built-in can know the rule. SplunkyGroundedness was
# retired because built-in Context Adherence scores the same thing against the retriever span.
# Each judge fails only on a contradiction it can point to. A judge that also failed when its
# subject was simply absent went red on every fault, whichever fault it was, and the
# one-metric-per-scenario story collapsed: an answer with its total removed was reported as having
# a wrong total and a wrong customer.
JUDGES = {
    "SplunkyAnswerWholeQuestion": (
        "Decide whether candidate_output answers every part the input asked for. Derive the "
        "required parts from the input itself; do not assume a fixed list. Return false only when "
        "a part of the question is left unanswered. An answer that addresses every part is covered "
        "even when its content is incorrect: whether a stated figure is right, and whether it "
        "describes the right customer, are not this metric's concern. Evaluate candidate_output, "
        "not final_output."
    ),
    "SplunkyNumericalCorrectness": (
        "Decide whether the money amounts and counts stated in candidate_output agree with "
        "evidence.calculations, which holds integer AUD cents; a dollar is 100 cents. Return false "
        "only when a stated figure disagrees with that evidence. If candidate_output states no "
        "money amount and no count, return true: there is nothing to contradict, and an answer "
        "that omits a figure is a different fault measured by another metric. Evaluate "
        "candidate_output, not final_output."
    ),
    "SplunkyRightCustomer": (
        "Decide whether every customer name, first name, and masked account number in "
        "candidate_output matches evidence.customer and evidence.accounts. Return false only when "
        "the candidate names a different person, or cites an account the authenticated customer "
        "does not own. If candidate_output names no person and cites no account number, return "
        "true: identity was not misstated. A wrong amount, count or date is not an identity error "
        "and must not make this metric fail. Evaluate candidate_output, not final_output."
    ),
}
JUDGE_PROMPT_SUFFIX = (
    " The trace output is JSON containing candidate_output and evidence. Judge only what"
    " candidate_output actually claims: the absence of a claim is not a failure."
    " Judge only the single property described above. An answer can be wrong in ways this metric"
    " does not measure: a wrong amount, an omitted part, an invented rule, a misnamed customer."
    " Each of those is measured by a different metric. When the property you are judging is"
    " correct, return true even if the answer is obviously wrong for some other reason, and say so"
    " in your reasoning rather than failing it."
)
JUDGE_MODEL = "gpt-4.1-mini"
# Three judges vote. On one judge a borderline call flips the whole verdict between runs:
# SplunkyAnswerWholeQuestion returned true and then false on the same scenario and question, with
# nothing left unanswered either time.
JUDGE_COUNT = 3

# Galileo's own evaluators. Context Adherence and Completeness read the retriever span the policy
# retriever emits; the tool metrics score the agent's tool use. These names are resolved against the
# tenant, not a fixed list, and the available set differs between tenants.
# Action Completion is deliberately absent: it produced no value on any trace or session, this
# tenant offers it only as the Luna small-model variant, and the SDK exposes no way to close a
# session for a session-scoped metric to score.
# Measured per turn against live traces: completeness cost $0.13-0.18, roughly 78% of the whole
# evaluation bill, while its roll-up ranked a deliberately incomplete answer above a correct one.
# Tool Selection Quality and Tool Error Rate were correct on every run but never caught anything.
# Context Adherence is kept as the Galileo-native evaluator that does work here, at about $0.02.
BUILTIN_METRICS = [
    "context_adherence",
]
