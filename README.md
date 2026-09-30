# Splunky Finance

Fictional Australian banking demonstration: a responsive Next.js website, deterministic JSON accounts and transactions, a tool-backed LangChain assistant, and a separate presenter workspace for Galileo evaluation and Agent Control protection. All accounts, policies, and transactions are synthetic. No banking actions execute.

## Current validation

Production frontend build and desktop/mobile browser journeys passed. Backend tests cover ledger integrity, date arithmetic, session isolation, CSRF, controlled faults, and the pre-execution transfer gate including that a blocked transfer leaves balances untouched. Browser tests use an explicit offline model that invokes real banking tools; they do not validate paid model APIs or fabricate Galileo scores.

One live OpenAI tool-backed turn and its Galileo model/tool span export have been verified, as have the custom judges and Context Adherence against the live tenant. Ollama has been verified end to end for chat and fault injection. Anthropic is unverified. Tenant-bound Agent Control blocks the action, but a `verified: true` deny from a bound control has not yet been observed — the app fails closed, which looks identical from the chat and is distinguishable only in `action_decisions`. Docker image builds require access to the server's Docker daemon; the current user does not yet have that access.

## Install on Ubuntu

From a clean machine:

```bash
sudo apt-get update && sudo apt-get install -y docker.io docker-compose-v2 git
sudo usermod -aG docker $USER && newgrp docker

git clone https://github.com/roadtrip123/splunky-finance.git
cd splunky-finance
python3 scripts/setup_env.py
```

`setup_env.py` writes a private `.env` with random passwords. Edit it to select a model provider and add its key, or leave those blank and set them later from the presenter portal. Then:

```bash
docker compose up --build -d
docker compose logs --tail=100 backend frontend
```

Open http://localhost:3000, sign in with account `12345678`, and the customer password configured in `.env`.

Running more than one stack on the same machine needs a distinct `FRONTEND_PORT` and matching `APP_ORIGIN` per stack. For a workshop, `scripts/workshop.py` generates those and provisions any number of isolated stacks in one command — see [docs/workshop.md](docs/workshop.md).

The setup script generates random initial demo passwords; read them from the private `.env` and replace them before sharing access. Presenter login is at `/demo-admin` and uses its independent password. `.env` is private, ignored by Git, and created with permissions 0600. Setup never overwrites an existing file.

For a remote server, configure `APP_ORIGIN` to its exact HTTPS URL and `SESSION_COOKIE_SECURE=true`. Put a TLS reverse proxy in front of frontend port 3000. Compose binds that port to loopback by default and keeps backend internal. Use one backend process because session/run state is in memory. Dataset JSON persists in the `runtime-data` volume. Do not scale backend workers without a shared session store.

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

## Live presenter controls and banking chat

Open `/demo-admin` and sign in with the presenter password. Sign into customer banking in another tab in the **same browser profile** and open **My Bank Agent**. The server links the two sessions automatically. No logout, page refresh, or manual linking is needed.

For another computer or incognito session, click **Connect using pairing code** in the portal. In My Bank Agent, expand **Demo connection**, enter the code, and click **Connect demo**. Codes expire after five minutes and can be used only once. A presenter controls one banking session; an existing connection is never silently replaced. Use **Disconnect banking session** or **Disconnect demo** before changing targets. Explicit disconnect disables automatic relinking; use a new pairing code to reconnect.

Click **Enable Incomplete Answer**, **Enable Incorrect Total**, **Enable Wrong Customer**, or **Enable Guardrail Cross-Customer Access**. The connected banking chat receives changes automatically (approximately once per second while open). The portal confirms **Applied to connected banking session** only after that browser acknowledges the current setting.

The chat footer keeps the exact words **Fictional banking data only**, with no icons or layout change:

- Original muted colour: normal answers.
- Muted red: a controlled fault is active.
- Muted amber: synchronization, connection failure, or expired demo. Sending is paused until settings are confirmed. A tooltip/accessibility label describes the state.

Ask the scenario's example question in the existing banking conversation. Switching **Normal Answers** restores normal tool-backed responses. The transcript remains visible, but model context starts fresh when settings change. An answer already underway finishes using its original scenario. Stale sends are rejected rather than silently using the wrong setting.

**Enable Guardrail Cross-Customer Access** selects the scenario and arms the guardrail together. Transfers and balance lookups are evaluated before the tool runs, and a denial stops the call, leaving balances untouched. The bound control is a deny-list on the other customers' accounts, so the customer's own balance checks and own transfers still succeed while the guardrail is armed. Selecting it does not by itself prove a control evaluated. The optional integrated presenter chat remains available for rehearsal. Detailed scenario, protection, and evaluation evidence stays in the portal, not the customer transcript.

Sessions are isolated from other presenters. Refreshing preserves valid server-side links; restart, logout, or expiry may require pairing again. Closed banking chats do not acknowledge settings until reopened. Follow [the presenter walkthrough](DEMO-SCRIPT.md) for the live demo sequence.

After pulling changes, deploy from the project root with `sudo docker compose up --build -d`.

## Model endpoints and conversation memory

Several model endpoints are configured under **Setup** in the presenter portal and switched with one click on the **Demo** tab, which makes it possible to ask the same question of two models and compare the traces in Galileo. Traces are named `bank-chat-turn · <endpoint>` so they are distinguishable in the trace list.

Within one model the agent keeps the last 8 messages as conversation history, and every turn shares one Galileo session. Switching model clears that history and starts a new session, so each model answers the same clean question rather than inheriting the other's answer. Changing scenario, toggling the guardrail, an hour of inactivity, and a backend restart clear it too.

## Providers

Choose the endpoint in the presenter portal under **Setup**: OpenAI, Anthropic, Ollama (local), Sharon AI, or a custom OpenAI-compatible URL. That applies immediately and needs no restart. Sharon AI and custom use the OpenAI protocol with their own base URL, set through `OPENAI_BASE_URL`.

The same settings can be preset in `.env` with `LLM_PROVIDER=openai|anthropic|ollama` and the corresponding model and key; changes made that way need a backend restart. Defaults: OpenAI `gpt-4o-mini-2024-07-18`, Anthropic `claude-haiku-4-5-20251001`, and local Ollama `gemma4:e2b`. Calls have bounded time, output, model iterations, and tool iterations. Provider errors are reported safely without exposing keys. No fallback provider is selected automatically.

For Ollama:

```bash
docker compose --profile ollama up --build -d
docker compose exec ollama ollama pull gemma4:e2b
```

Set `LLM_PROVIDER=ollama` and keep `OLLAMA_BASE_URL=http://ollama:11434`. The optional service uses Ollama 0.20.0, a Gemma 4 supporting release. This model is approximately 7.2 GB; this server has 16 GB RAM. Context is capped at 4096 and one application turn per conversation runs at a time. Actual performance remains to be measured. Cloud Ollama models are rejected.

## Galileo and protection

Connect from the presenter portal under **Setup**: API key, project, log stream, console and API URLs, and `AGENT_CONTROL_URL`. Saved to the instance and applied without a restart, so a workshop participant configures their own project without shell access. The key is only ever displayed masked. **Set up my project** then enables the metrics on that log stream and binds the transfer control, both of which are per log stream even though the judges and control definition are tenant-wide.

The same values can be preset in `.env` as `GALILEO_ENABLED`, `GALILEO_API_KEY`, `GALILEO_PROJECT`, `GALILEO_LOG_STREAM`, `GALILEO_CONSOLE_URL`, `GALILEO_API_URL` and `AGENT_CONTROL_URL`. Runtime evaluation uses the dedicated runtime-token header and a resolved log-stream target. Obtain these values from your Galileo tenant; do not guess its gateway URL.

Explicit remote setup is available from backend:

```bash
PYTHONPATH=. .venv/bin/python ../scripts/configure_galileo.py
# After reviewing tenant configuration, explicitly apply remote setup:
PYTHONPATH=. .venv/bin/python ../scripts/configure_galileo.py --apply
```

The default invocation validates the control schemas without remote changes. `--apply` creates the custom boolean judges, enables the built-in evaluators, and creates and binds two server-side regex controls, one per gated tool, at the `pre` stage. `--apply --refresh-judges` publishes a new version of each judge; editing a prompt without it changes nothing in the tenant.

Everything published comes from one file, `backend/app/observability/setup_definitions.py`: the judge rubrics, the prompt builder, the built-in metric slugs, and the control definitions. The guardrail's deny-list is generated from the dataset, so it cannot drift from the accounts that exist.

[docs/evaluators.md](docs/evaluators.md) is the reference: every metric and why it is enabled, which are deliberately left off, how the guardrails are built and how the application obeys them, and the four logging choices without which none of it scores correctly. Verify binding and 100% metric sampling in the tenant console. The regex rejects a controlled condition known before the demo; it is not a general semantic policy validator. Tenant permissions and model entitlements differ between accounts.

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

For a workshop, [docs/workshop.md](docs/workshop.md) provisions one isolated stack per participant on a single EC2 instance with `scripts/workshop.py`, and [docs/workshop-lab.md](docs/workshop-lab.md) is the participant guide: connect the app to their own Galileo project, build the evaluators, build the guardrail.

See [DEMO-SCRIPT.md](DEMO-SCRIPT.md) for presentation steps, [docs/evaluators.md](docs/evaluators.md) for which Galileo metrics to enable and why, and [docs/architecture.md](docs/architecture.md) for data and security contracts. This private repository has no license grant pending the owner's license choice.

## Private LAN deployment

For trusted-LAN testing, choose an address assigned to the deployment host and set:

```dotenv
APP_ORIGIN=http://<SERVER_LAN_IP>:3000
FRONTEND_BIND_ADDRESS=<SERVER_LAN_IP>
ALLOW_PRIVATE_LAN_HTTP=true
SESSION_COOKIE_SECURE=false
```

Run `docker compose up --build -d` and open the exact configured origin. HTTP login traffic is unencrypted, so limit it to a trusted synthetic demo network. For public deployment, use an HTTPS hostname, `SESSION_COOKIE_SECURE=true`, and `ALLOW_PRIVATE_LAN_HTTP=false`, with a TLS proxy or tunnel. The committed examples contain no deployment-specific hostname or address.

## Shared environment snapshot

`master.env` records this server's shareable settings. OpenAI, Anthropic, and Galileo API keys are blank; customer/presenter passwords and the session signing secret are placeholders. Use your private ignored `.env` for actual credentials. The backend reads `.env`, not `master.env`. After editing `.env`, restart backend to apply changes. Galileo is enabled by default. Configure its API key and endpoints in private `.env`.

## Galileo admin switch and connection status

Galileo starts enabled by default. The presenter workspace has Enable/Disable Galileo and Check Galileo connection buttons. The switch applies to all demo chats, persists in `runtime/galileo-settings.json` (or the Docker data volume), and overrides the environment startup default until changed again. Changes wait for active chat/connection work to finish. The toggle and connection check require an authenticated presenter and CSRF validation.

Connection status distinguishes disabled, unconfigured (missing key), checking, connected (SDK resolved the configured target), and failed. Last check/connection times and actual export status are separate: connected does not imply that a trace was exported or scored. The startup check and manual check do not invoke a paid model. Existing traces can finish exporting before disable, and protection remains fail-closed if Galileo is disabled. Keys and passwords are never exposed by these endpoints.
