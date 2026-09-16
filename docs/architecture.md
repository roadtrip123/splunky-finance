# Architecture and contracts

Next.js App Router renders public pages and authenticated banking pages. A same-origin API proxy forwards cookies and CSRF tokens to FastAPI. Only backend reads provider credentials. Customer and presenter roles have separate signed, HttpOnly, SameSite=Strict cookies, expiring server sessions, Argon2 password verification, and bounded failed-login tracking. Authenticated mutations require exact Origin and role CSRF tokens. Customer identifiers are injected into tool closures, never accepted as model authorization.

Backend modules: config.py validates configuration; schemas.py validates persisted datasets; storage.py implements locked atomic JSON replacement; demo/generator.py generates synthetic ledgers; demo/expected_results.py supplies deterministic arithmetic; tools.py supplies account, transaction, calculation, and policy tools; agent.py manages bounded conversations and candidate replay; observability supplies Galileo export and synchronous output protection; main.py exposes routes.

## Data

Three accounts represent Everyday, Savings, and credit card. All amounts are integer AUD cents. Signed card balances are liabilities, not cash. Closing balances reconcile to opening balances and posted ledger movements. Internal transfers and card repayments are equal/opposite paired entries. Pending transactions never affect posted spending or balances. Savings interest accrues daily at the fictional 2% annual rate, divided by 365, and is credited at month end with half-up cent rounding.

Seed and frozen reference date reproduce the dataset. Last month means the previous complete calendar month, inclusive start/exclusive end. Spending counts posted purchase debits, subtracts refunds, and excludes internal transfers, card repayments, interest, fees, and pending entries. Largest transactions sort by amount then date and ID. Percentage change uses exact Decimal arithmetic; a zero baseline returns no fabricated percentage.

Dataset version and hash protect reproducibility. Corrupt files cause a visible unhealthy dataset state; startup never silently regenerates them. Explicit confirmed reset uses expected-version checks, atomically replaces JSON, and invalidates conversations and comparisons. Account ownership, unique IDs, temporal bounds, pair integrity, and ledger totals are validated.

## Routes

`/api/auth/login|session|logout`, `/api/accounts`, `/api/accounts/{id}`, `/api/accounts/{id}/transactions`, `/api/chat`, and `/api/chat/reset` serve customers. `/api/demo-admin/login|session|logout`, `/run`, `/bind`, `/scenario`, `/protection`, `/status`, `/expected-results`, `/reset`, `/dataset/reset`, `/preflight`, `/preflight/{id}`, and `/evaluations/refresh` serve presenters or explicitly bound customer sessions. `/health` reports local liveness; `/ready` reports data/policy availability plus separate model configuration status. Readiness does not claim that a remote API succeeds.

## Candidate protection and evaluation

Each turn uses real banking tools through a bounded LangChain agent. Presenter fault scenarios deliberately inject a candidate after the model response. Deterministic evidence supplementation is marked as presenter workflow rather than model retrieval. The before/after scenario reuses the same candidate, evidence, prompt, and dataset; it makes no second model call. Its source event and candidate SHA256 identify that replay.

The protection gate is awaited before constructing the customer response. Missing configuration, service errors, or empty control evaluations produce a safe fallback when protection is enabled. Disabled protection delivers the candidate and is explicitly unverified. Actual Agent Control match/non-match responses determine allow/deny. Telemetry failure does not change an already verified gate decision. Asynchronous Galileo judges are distinct from the synchronous control gate; displayed scores are actual fetched metrics or unavailable.

Sessions, conversations, presenter runs, jobs, and recent evidence are bounded in-memory state and disappear on restart. Only datasets persist in JSON. This is a single-process demonstration, not a production banking system. No transfer/payment/account mutation tools exist. Browser chat messages are held in page memory, not local storage. Telemetry exports user prompts and synthetic banking evidence to the configured Galileo tenant; do not enter secrets or real customer data.

## Acceptance still requiring external configuration

Verify one live tool-backed turn for each configured provider, genuine Galileo trace export and custom judge values for the controlled faults, real Agent Control allow/deny with a bound tenant control, and Docker build/start/restart persistence. Offline tests validate application behavior without asserting these external integrations passed.
