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

Configured deployment target: http://10.0.0.170:3000. The selected address is assigned to this server’s Wi-Fi interface. Docker access remained denied. Local private .env is excluded from Git.
