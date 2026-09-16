# Splunky Finance

Fictional Australian banking demonstration: a responsive Next.js website, deterministic JSON accounts and transactions, a tool-backed LangChain assistant, and a separate presenter workspace for Galileo evaluation and Agent Control protection. All accounts, policies, and transactions are synthetic. No banking actions execute.

## Current validation

Production frontend build and desktop/mobile browser journeys passed. Backend tests cover ledger integrity, date arithmetic, session isolation, CSRF, controlled faults, replay, and fail-closed protection. Browser tests use an explicit offline model that invokes real banking tools; they do not validate paid model APIs or fabricate Galileo scores.

Live OpenAI/Anthropic/Ollama calls, Galileo exports/judges and tenant-bound Agent Control require configuration and remain unverified. Docker image builds require access to the server's Docker daemon; the current user does not yet have that access.

## Run on Ubuntu with Docker Compose

Install Docker Engine with Compose. From the repository root:

```bash
python3 scripts/setup_env.py
# Edit .env locally: select provider, add API key, and replace demo passwords.
docker compose up --build -d
docker compose logs --tail=100 backend frontend
```

Open http://localhost:3000, sign in with account `12345678`, and the customer password configured in `.env`. The setup script supplies initial fictional demo passwords; replace them before sharing access. Presenter login is at `/demo-admin` and uses its independent password. `.env` is private, ignored by Git, and created with permissions 0600. Setup never overwrites an existing file.

For a remote server, configure `APP_ORIGIN` to its exact HTTPS URL and `COOKIE_SECURE=true`. Put a TLS reverse proxy in front of frontend port 3000. Compose binds that port to loopback and keeps backend internal. Use one backend process because session/run state is in memory. Dataset JSON persists in the `runtime-data` volume. Do not scale backend workers without a shared session store.

## Local development

```bash
python3 scripts/setup_env.py
cd backend
uv sync --frozen
DATA_DIR=../runtime POLICY_DIR=../data/policies .venv/bin/uvicorn app.main:create_app --factory --host 127.0.0.1 --port 8001
```

In a second terminal:

```bash
cd frontend
npm ci
npm run dev
```

The frontend proxies to backend port 8001. Local path overrides are necessary because `.env.example` uses container paths. Missing model credentials allow banking pages to run; chat reports that its provider is unconfigured. It never silently substitutes an offline model.

## Providers

Configure `LLM_PROVIDER=openai|anthropic|ollama` and the corresponding model/key in `.env`; restart backend after changes. Defaults: OpenAI `gpt-4o-mini-2024-07-18`, Anthropic `claude-haiku-4-5-20251001`, and local Ollama `gemma4:e2b`. Calls have bounded time, output, model iterations, and tool iterations. Provider errors are reported safely without exposing keys. No fallback provider is selected automatically.

For Ollama:

```bash
docker compose --profile ollama up --build -d
docker compose exec ollama ollama pull gemma4:e2b
```

Set `LLM_PROVIDER=ollama` and keep `OLLAMA_BASE_URL=http://ollama:11434`. The optional service uses Ollama 0.20.0, a Gemma 4 supporting release. This model is approximately 7.2 GB; this server has 16 GB RAM. Context is capped at 4096 and one application turn per conversation runs at a time. Actual performance remains to be measured. Cloud Ollama models are rejected.

## Galileo and protection

Set `GALILEO_ENABLED=true`, API key, tenant console/API URLs where required, project and log stream, and `AGENT_CONTROL_URL`. Runtime evaluation uses the dedicated runtime-token header and a resolved log-stream target. Obtain these values from your Galileo tenant; do not guess its gateway URL.

Explicit remote setup is available from backend:

```bash
PYTHONPATH=. .venv/bin/python ../scripts/configure_galileo.py
# After reviewing tenant configuration, explicitly apply remote setup:
PYTHONPATH=. .venv/bin/python ../scripts/configure_galileo.py --apply
```

The default invocation validates the control schema without remote changes. Apply creates/enables trace-level custom boolean judges and requests a bound server regex control for the seeded unlimited-transfer claim. Verify binding and 100% metric sampling in the tenant console. The regex demonstrates rejection of a controlled contradiction; it is not a general semantic policy validator. Custom judges inspect the candidate and deterministic evidence. Tenant permissions and model entitlements may differ, so remote setup is not claimed as tested.

Presenter evidence shows real IDs, raw model output, injected candidate, delivered answer, candidate hash, control decisions, usage when supplied, and export status. Scores remain unavailable until retrieved from Galileo. Use “Fetch actual Galileo scores” after asynchronous evaluation completes. No fabricated scores, costs, trace links, or successful controls are displayed.

## Verification

```bash
cd backend
.venv/bin/ruff check app tests
.venv/bin/pytest -q
cd ../frontend
npm run build
npx playwright install chromium
npm test
```

Browser testing starts dedicated offline backend and production frontend processes; ensure ports 8001 and 3000 are free. Test data is stored under ignored `runtime/browser-tests`.

See [DEMO-SCRIPT.md](DEMO-SCRIPT.md) for presentation steps and [docs/architecture.md](docs/architecture.md) for data and security contracts. This private repository has no license grant pending the owner's license choice.
