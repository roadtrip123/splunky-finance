# Workshop deployment

One isolated Splunky Finance stack per participant, provisioned by a single script on one EC2 instance. Participants need a browser and nothing else: no SSH, no shell, no file editing.

Each participant gets their own compose project, so their dataset, sessions and Galileo configuration are separate. That separation is not cosmetic — the money-transfer scenario writes to the ledger, so on a shared instance one participant's transfer would move everyone's balance.

## Instance

| | |
| --- | --- |
| Type | `r7i.2xlarge` (8 vCPU, 64 GiB) for 50, `r7i.4xlarge` (16 vCPU, 128 GiB) for 100 |
| Disk | 50 GB gp3 for 50 participants, 100 GB for 100 — not the 8 GB default |
| OS | Ubuntu 24.04 |
| Security group | SSH from your address; 443 from wherever participants sit |
| DNS | Wildcard `*.demo.example.com` pointing at the instance |

Sizing: each stack measured 229 MiB idle (frontend 48, backend 181), and roughly 500 MiB after an hour of use. Fifty stacks plus the host is about 26.5 GB on a 64 GiB box, leaving 2.4× headroom. A hundred stacks is 200 containers and about 51.5 GB, which needs 128 GiB: on 64 GiB that is 80% committed, too close for a live session. At a hundred, drop `--stagger` to 1 or the start takes nearly seven minutes. The app is almost entirely IO-wait because the model runs elsewhere, so memory rather than CPU is the binding constraint. Avoid burstable instance types: a workshop is exactly when CPU credits run out.

Ports are `base + N`, so participant 7 is `3107` with the default base of 3100.

## Bootstrap on a fresh box

```bash
sudo apt-get update && sudo apt-get install -y docker.io docker-compose-v2 git
sudo usermod -aG docker $USER && newgrp docker

# Pin to a released version. The default branch moves; a workshop should not.
git clone --branch v0.5.0 https://github.com/roadtrip123/splunky-finance.git
cd splunky-finance
git describe --tags          # expect v0.5.0
python3 scripts/setup_env.py
```

`setup_env.py` writes a private `.env`. Nothing in it needs editing for a workshop:

- the two demo passwords are the fixed shared pair, `-AlexDemo1234!` and `PresenterDemo1234!`
- the model endpoint is configured in the presenter portal, not here
- the Galileo values stay blank; participants supply their own

The session secret is generated per box and never shared, because it signs cookies.

## When the image build cannot reach PyPI or npm

Two different network problems produce a failed dependency download, and they need opposite fixes.
Read the certificate name in the error before doing anything.

### The name in the certificate is unrelated to the host being fetched

```
× Failed to download `langgraph==1.2.11`
  ╰─▶ invalid peer certificate: certificate not valid for name "files.pythonhosted.org";
      certificate is only valid for DnsName("*.lab.example")
```

Nothing is wrong with trust here. The connection is being *redirected* to a different server, which
answers with its own default certificate. Adding certificates cannot help, because the name will
never match. The usual cause is a network that redirects container IPv4 egress while leaving the
host alone -- often because the host reaches the internet over IPv6 and Docker's bridge network has
no IPv6 route.

Confirm it by running the same request on each network. The bridge one fails, the host one does not:

```bash
PROBE="import urllib.request;print(urllib.request.urlopen('https://pypi.org/simple/',timeout=15).status)"
docker run --rm                python:3.12-slim python -c "$PROBE"   # fails
docker run --rm --network host python:3.12-slim python -c "$PROBE"   # succeeds
```

If that is what you see, build on the host's network:

```bash
echo 'BUILD_NETWORK=host' >> .env
python3 scripts/workshop.py up --count 2 --host <host> --base-port 3200
```

`BUILD_NETWORK` only affects the build. Containers still run on their own network, so stacks stay
isolated from each other and ports still map per participant.

Host networking during a build needs the `network.host` entitlement, which BuildKit normally grants
for the default builder. If it refuses, use the classic builder for the build only:

```bash
DOCKER_BUILDKIT=0 docker compose -p sf-build --env-file .env build
python3 scripts/workshop.py up --count 2 --host <host> --base-port 3200 --skip-build
```

Containers that run with the default bridge still have to reach the model endpoint and the
observability backend at runtime. Check that before the day:

```bash
docker run --rm python:3.12-slim python -c \
  "import urllib.request;print(urllib.request.urlopen('https://api.openai.com/v1/models',timeout=10).status)"
```

A 401 is a pass -- the request arrived and was rejected for having no key. A certificate error means
runtime egress is redirected too, and the stacks need `network_mode: host` or a working IPv6 route
on the Docker bridge.

### The certificate is for the right host but issued by a CA the build does not trust

```
× Failed to download `langgraph==1.2.11`
  ╰─▶ invalid peer certificate: UnknownIssuer
```

This one is a real TLS-intercepting proxy, and trusting its CA is the fix. Capture the chain the
proxy presents -- `s_client` prints it without verifying, so this works whether or not the host
trusts it either:

```bash
openssl s_client -connect files.pythonhosted.org:443 -showcerts </dev/null 2>/dev/null \
  | awk '/BEGIN CERT/,/END CERT/' > backend/ca/proxy.crt

python3 scripts/workshop.py up --count 2 --host <host> --base-port 3200
```

Copying the host's own store -- `cp /etc/ssl/certs/ca-certificates.crt backend/ca/host-bundle.crt` --
also works, but only if the host trusts the proxy. `curl -sI https://files.pythonhosted.org/` says
whether it does.

Anything in `backend/ca/` is installed and trusted during the build, and the directory is gitignored
so a site's certificates stay on that site's box.

## Choose how participants reach it

This decides the provisioning command, so settle it first. `config.py` accepts a plain-HTTP origin
only for localhost and RFC1918 addresses:

```python
if not local and origin.scheme == "http" and not (self.allow_private_lan_http and private_lan):
    raise ValueError("Remote exposure requires HTTPS or explicit private LAN HTTP opt-in")
```

`workshop.py` checks the same rule before provisioning, so a doomed run stops rather than leaving
fifty dead containers.

### A. Private network, plain HTTP — no DNS, no certificates

The short path when participants are on a network that routes to the instance: a corporate LAN, a
VPN, or the same VPC. **Test it from one participant's machine before building fifty**, because
reachability is the whole assumption.

```bash
echo 'ALLOW_PRIVATE_LAN_HTTP=true' >> .env
PRIVATE_IP=$(hostname -I | awk '{print $1}')

python3 scripts/workshop.py up --count 50 --host "$PRIVATE_IP"
```

Participant 7 is then `http://<private-ip>:3107`. Omit `--origin-template`: the default
`http://HOST:PORT` is what you want, and `SESSION_COOKIE_SECURE` is set to match automatically.
Open the port range in the security group from wherever participants sit.

**What you are accepting.** Step 2 of the lab has each participant paste their own Galileo API key
into the portal, and on plain HTTP that key crosses the network in cleartext. The synthetic banking
data does not matter and the demo passwords are read aloud anyway — the keys are the reason the rule
exists. On a trusted internal network for ninety minutes that is usually a fair trade; over the
public internet it is not.

Cookies ignore ports, so anyone visiting two instances shares one cookie jar. Each participant uses
one port and is unaffected, but you will be logged out as you move between instances helping
people. Use a separate browser profile for that.

### B. Public address, HTTPS — a domain and a proxy

Required when participants come over the internet. Point a wildcard record at the instance, run a
TLS proxy, and give each participant a subdomain:

```bash
python3 scripts/workshop.py up --count 50 \
  --host demo.example.com \
  --origin-template 'https://p{n:02d}.demo.example.com' \
  --bind 127.0.0.1
```

`--bind 127.0.0.1` keeps the stacks off the public interface so the proxy is the only listener.
`scripts/Caddyfile.workshop` has the configuration and the loop that generates fifty blocks.

Subdomains rather than paths or ports: `APP_ORIGIN` must have an empty path, so
`https://demo.example.com/p07` is rejected, and separate hostnames give each participant their own
cookie jar.

**No domain, and you do not want one.** Terminate TLS on the bare IP with a self-signed
certificate. The application only checks the *scheme* of `APP_ORIGIN`, so HTTPS on a public address
is accepted whether or not a public CA signed the certificate — no code change, no DNS, no ACME.

```bash
IP=<public-ip>
python3 scripts/workshop.py up --count 50 \
  --host "$IP" --base-port 4100 --bind 127.0.0.1 \
  --origin-template "https://$IP:31{n:02d}"
```

Participant 7 browses `https://<ip>:3107`, which the proxy forwards to `127.0.0.1:4107`.
`scripts/Caddyfile.selfsigned` has the configuration and the loop that generates fifty blocks.

Participants get a certificate warning once and click through — **tell them beforehand**, or the
first five minutes go on it. A self-signed certificate stops passive sniffing, which is the real
risk on shared wifi; it does not prove the server's identity. For synthetic data that is a
reasonable place to stop.

`sslip.io` is the other option if you would rather have a publicly trusted certificate without
owning a domain: it resolves any IP-shaped hostname, so a proxy can complete an ACME challenge for
`<ip>.sslip.io`. Use one hostname and a port per participant rather than fifty subdomains, because
Let's Encrypt counts certificates per registered domain and that one is shared.

## Provision

Take the command from the section above for whichever access path you chose. Either way, rehearse
with two stacks before building fifty:

```bash
python3 scripts/workshop.py up --count 2 --host <host> --base-port 3200
python3 scripts/workshop.py list
```

Then open one, sign in, and walk it through [docs/workshop-lab.md](workshop-lab.md) end to end —
including creating the Agent Control agent, which is the step most likely to catch participants.
`python3 scripts/workshop.py down --count 2 --purge` clears it.

`APP_ORIGIN` is matched exactly on every mutating request, so an origin that does not match what
the browser sends fails every login with a CSRF error rather than anything naming the real problem.
That is the one value worth checking twice.

The script builds the images once, then starts each stack in turn with a two-second gap, because fifty Next.js and uvicorn processes starting simultaneously is the one real CPU spike in the whole exercise. First run on a fresh box spends a few minutes building; after that `--skip-build` starts everything immediately.

Useful flags:

| Flag | Effect |
| --- | --- |
| `--dry-run` | Print the commands, change nothing |
| `--base-port` | Default 3100, so participant N is 3100+N |
| `--bind` | Host address to bind, default `0.0.0.0` |
| `--stagger` | Seconds between starts, default 2 |
| `--origin-template` | Per-participant origin, e.g. `https://p{n:02d}.demo.example.com` |
| `--skip-build` | Images already built |

## Deploy a new version

```bash
cd splunky-finance
git fetch --tags
git checkout v0.6.0
git describe --tags                      # confirm before touching the stacks

python3 scripts/workshop.py up --count 50 \
  --host demo.example.com \
  --origin-template 'https://p{n:02d}.demo.example.com' \
  --bind 127.0.0.1
```

Re-running `up` with the same arguments is the update: it rebuilds the images and recreates every
container whose image changed. No `down` first — stopping them only lengthens the outage.

What survives, because it lives in each participant's `runtime-data` volume rather than in the
image: their Galileo credentials, model endpoints and active backend, their dataset, and any
transfers they made. A dataset whose shape changed is migrated on startup from the same seed, so
the figures on their lab sheet do not move.

What does not: conversations, which are in-memory by design. Participants carry on with a fresh
one.

Their **login sessions do** survive, because a session secret already generated for a participant
is reused rather than rotated. That was not true at first — every re-provision issued a new secret
and logged the whole room out.

Budget a few minutes: the image build is once, then the stacks restart at `--stagger` seconds
apart. For a mid-workshop update, say so before you start rather than letting fifty people watch a
restart.

## Manage

```bash
python3 scripts/workshop.py list                 # what is running, and on which URL
python3 scripts/workshop.py down --count 50      # stop, keep datasets
python3 scripts/workshop.py down --purge         # stop, delete volumes and env files
```

`down` without `--count` stops every `sf-pNN` project it finds.

## What participants get

Each is handed one URL, an account number and two passwords. In their own instance they:

1. Sign in to banking, and to `/demo-admin` in another tab of the same browser profile — linking is automatic within one profile
2. Create their own Galileo API key, project and log stream in the console — this comes first, because the app cannot connect to a project that does not exist
3. Open the **Setup** tab, choose a model endpoint and save it, then paste their Galileo details and press **Save and connect**
4. Build the evaluators themselves in the Galileo console: enable Context Adherence and create the three custom judges, each boolean, trace-level, `gpt-4.1-mini`, three voters
5. Build and bind the two guardrail controls themselves — one per gated tool, both `pre`-stage, both deny-lists rather than match-everything
6. Work through the scenarios and read their own traces

Steps 4 and 5 are the lab, so **Set up my project** — which would do both for them — is hidden in workshop mode. [docs/workshop-lab.md](workshop-lab.md) is the participant guide and carries the judge prompts and the control definition ready to paste.

**Custom metrics are tenant-wide.** Fifty people each creating `SplunkyRightCustomer` will collide in one namespace, so the lab guide tells them to suffix every metric with their initials. Worth repeating out loud before they start.

Generated env files live in `workshop/` with mode 0600, and the directory is gitignored. They hold both passwords and a session secret, but **no API keys**: the provider and Galileo credentials are blanked so a participant starts from an empty Setup tab rather than inheriting yours.

## Rehearse before the day

The two-stack run under **Provision** is the rehearsal. What matters is that a human follows
[docs/workshop-lab.md](workshop-lab.md) rather than that the containers start:

1. Create an agent in the Agent Control console, then the two controls, then **attach** them to it.
   Binding to a stream is not attaching to an agent, and a control that is bound but not attached
   never evaluates — the gate fails closed and the guardrail looks like it worked.
2. Add a model endpoint and connect Galileo from the portal.
3. Build the four evaluators by hand.
4. Run every scenario, including both transfer directions and the guardrail.
5. Read `action_decisions` and confirm it says `verified: true`, not `unavailable`.

Steps 1 and 5 are the ones that only fail against a real tenant, and they are the reason to do this
at all. **Set up my project** does steps 1–3 in one click but is hidden unless `DEMO_SETUP_BUTTON`
is set, because doing it for participants skips the lab.

## Things that bite

**Cookies ignore ports.** `host:3101` and `host:3102` share a cookie jar. Each participant using one port is unaffected, but moving between instances to help people will log you out repeatedly. Use a separate browser profile, or put a reverse proxy with subdomains in front if you have DNS.

**Check the endpoint can drive the agent before the day.** Answering a chat request is not enough: every scenario depends on the model emitting a tool call, and some reasoning models return their text in `reasoning_content` leaving `content` empty. Both look like a healthy endpoint from a plain request.

```bash
python3 scripts/check_endpoint.py --base-url <url> --model <model> --api-key <key>
```

Pass the key without any `Bearer ` prefix; the client adds it. A provider config that hands you a full header value such as `"Bearer tv-pat-..."` needs the prefix stripped, or you get a doubled header and a 401.

**Every participant needs an Agent in Agent Control, and it cannot be created from the SDK.** The
runtime evaluation route looks the agent up by name, and returns 404 if it does not exist — at
which point the application fails closed. The guardrail then blocks correctly and reports
`decision: "unavailable"`, which looks like success and is not. Each participant creates an agent
in the Agent Control console and uses that name; the lab sheet says so, and it is worth repeating
out loud because nothing in the app surfaces the problem.

**One LLM endpoint for fifty people** is the most likely thing to spoil the session — well ahead of anything about instance sizing. Check the endpoint's rate limits against fifty concurrent turns of roughly 2,500 input tokens each, and confirm it handles tool calling properly: this agent depends entirely on well-formed tool calls, and an endpoint that is chat-compatible but weak on tools fails every scenario.

**Evaluation cost** runs about $0.035 per turn across the four enabled metrics. Fifty participants at eight turns each is roughly $14.

**The completeness judge is the flakiest part of the lab.** It scored correctly on 8 of 10 runs in
testing, with the faulty answer verified faulty beforehand. Expect a few participants to see a green
where they expect red, and tell them to re-run rather than debug their prompt. The other two judges
were unanimous throughout. [docs/evaluators.md](evaluators.md) has the detail if someone digs.

**Resetting the dataset.** Participants use **Reset balance** on the DATASET card, which reuses the current seed and reference date so the figures in the lab sheet keep matching. The fuller reset control lower down allows changing the seed, which moves every number they have been given.
