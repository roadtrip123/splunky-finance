# Presenter walkthrough

1. Start the application, confirm `/ready`, and configure a genuine model provider. Log in at `/login` with the seeded account and customer password.
2. Browse the three accounts and transaction filters. Open My Bank Agent and ask “How much did I spend on restaurants last month?” Show the live tool-backed response.
3. In another tab open `/demo-admin`, log in with the presenter password, start a run, and link the customer session. Run the explicitly paid preflight. Confirm real tool calls and Galileo export status.
4. Select `incomplete_answer`, copy its exact prompt, start a new customer conversation, and send it. Explain that the candidate is deliberately injected after the model call. Fetch actual Galileo scores after evaluation; do not present unavailable scores as successful evaluation.
5. Repeat with `policy_hallucination` and `incorrect_total`. Inspect expected results to show authoritative policy and exact arithmetic.
6. Select `guardrail_before_after` with protection disabled. Send the exact prompt and inspect its candidate hash and source event. Enable protection and send that identical prompt again. Show replay, identical candidate hash, the genuine control result, and the safe customer answer. If protection says unavailable, demonstrate fail-closed behavior and state that live control verification has not passed.
7. Reset the run before changing prompts or data. Confirm dataset reset only when intentionally replacing the synthetic dataset; comparisons and conversations are invalidated.

Expected external transfer policy is AUD 5000 daily with verification required. The injected unlimited/no-verification answer contradicts it. The synchronous seeded regex control and asynchronous custom grounding judge demonstrate different parts of observe → evaluate → detect → protect.
