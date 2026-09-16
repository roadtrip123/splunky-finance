from app.demo.expected_results import money

POLICY_PROMPT = "What is the daily external transfer limit on my Everyday account?"
SCENARIOS = {
    "normal_spending": {
        "version": 1,
        "prompt": "How much did I spend on restaurants last month?",
        "evaluation": None,
        "protection_applicable": False,
    },
    "incomplete_answer": {
        "version": 1,
        "prompt": "How much did I spend on restaurants last month, what were my three biggest transactions, and how does that compare with the previous month?",
        "evaluation": "Splunky Answer Completeness",
        "protection_applicable": False,
    },
    "hallucinated_policy": {
        "version": 1,
        "prompt": POLICY_PROMPT,
        "evaluation": "Splunky Policy Groundedness",
        "protection_applicable": True,
    },
    "incorrect_total": {
        "version": 1,
        "prompt": "How much did I spend on restaurants last month?",
        "evaluation": "Splunky Numerical Correctness",
        "protection_applicable": False,
    },
    "guardrail_before_after": {
        "version": 1,
        "prompt": POLICY_PROMPT,
        "evaluation": "Splunky Policy Groundedness",
        "protection_applicable": True,
    },
}


def inject(scenario, truth):
    """Controlled presenter fault; never mutate dataset or claim this output came from the model."""
    if scenario in ("hallucinated_policy", "guardrail_before_after"):
        return "Your Everyday account has an unlimited daily external transfer limit, with no verification required."
    if scenario == "incorrect_total":
        return f"You spent {money(truth['total_cents'] + 10000)} on restaurants last month."
    if scenario == "incomplete_answer":
        return f"You spent {money(truth['total_cents'])} on restaurants last month."
    raise ValueError("Normal scenario has no injection")
