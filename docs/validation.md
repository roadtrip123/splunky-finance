# Validation — 2026-09-16

- Python lint: passed (`ruff check app tests`).
- Backend tests: 12 passed; one upstream Starlette/AnyIO deprecation warning.
- Next.js production build: passed, including TypeScript.
- Playwright browser journeys: 6 passed across desktop Chromium and mobile Chromium.
- Agent Control schema: validated locally against installed SDK 8.7.0.
- Docker Compose configuration: checked without daemon access.

The protection tests use explicit SDK response doubles for allow/deny; browser journeys use an explicit offline model with real tool invocation. These are application tests, not live service acceptance.

Unverified: Docker image build/start, paid provider calls, local Ollama performance, genuine Galileo exports and custom judge results, and genuine tenant-bound Agent Control decisions. Docker socket access is denied for the current user. Provider and Galileo secrets must be configured locally in ignored .env.

## Private LAN configuration update

Private IPv4 HTTP requires explicit ALLOW_PRIVATE_LAN_HTTP opt-in. Public IPs, DNS names, and link-local addresses remain rejected for remote HTTP. Cookie security must match HTTP/HTTPS. LAN login, session cookies, and exact Origin rejection are tested.

A private-LAN deployment was validated using an address assigned to the test host. Docker access remained denied. Local private `.env` is excluded from Git; no host address is committed.

## Galileo admin controls update

- Backend tests: 21 passed; lint passed.
- Production build: passed.
- Browser journeys: 8 passed on desktop/mobile, including persistent enable/disable and missing-key status.
- Galileo default enabled, live .env updated, and production backend/frontend restarted.
- Connection uses a fresh authenticated SDK API read. SDK response doubles test success/failure and secret-safe errors; genuine live connection and trace export status are reported separately in the presenter portal.

## Action-span fix and live verification

Fixed two SDK integration defects: GalileoLogger is unhashable, so pending loggers must be tracked by object identity; the root trace must start in the async request context so callback tasks inherit the SDK ContextVar parent. A real-SDK offline ingestion-hook regression asserts one exported trace with LLM, calculate_spending tool, and protection workflow descendants.

Backend suite: 22 passed; lint passed. Backend restarted. One live OpenAI account-balance turn returned HTTP 200 and exported successfully. A live Galileo trace was read back through the authenticated API and contained Agent, two ChatOpenAI LLM spans, a tools workflow with a get_accounts tool span, and output-protection-decision. This verifies OpenAI tool execution and genuine Galileo span ingestion; custom judge scores and bound Agent Control decisions remain unverified. Earlier empty sessions cannot be reconstructed automatically.

## Retriever span and answer span

Policy retrieval is registered as a LangChain retriever and the delivered candidate is logged as a `customer-visible-answer` LLM span. Real-SDK offline ingestion-hook regressions assert that an exported trace contains a retriever span carrying chunks, the named answer span with the candidate as its output, and the previously covered model, tool, and protection descendants. `config` injection keeps the retriever span inside the turn's trace and stays hidden from the model's tool schema.

Backend suite: 43 passed; lint passed. Still unverified against a live tenant: whether built-in RAG evaluators return actual values for these spans, and genuine Agent Control decisions. Enable the evaluators in the tenant and confirm a real score before presenting them.
