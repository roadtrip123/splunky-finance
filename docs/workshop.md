# Workshop deployment

One isolated Splunky Finance stack per participant, provisioned by a single script on one EC2 instance. Participants need a browser and nothing else: no SSH, no shell, no file editing.

Each participant gets their own compose project, so their dataset, sessions and Galileo configuration are separate. That separation is not cosmetic — the money-transfer scenario writes to the ledger, so on a shared instance one participant's transfer would move everyone's balance.

## Instance

| | |
| --- | --- |
| Type | `r7i.2xlarge` (8 vCPU, 64 GiB) for 50 participants |
| Disk | 50 GB gp3 — not the 8 GB default |
| OS | Ubuntu 24.04 |
| Security group | SSH from your address; TCP 3101-3150 from wherever participants sit |

Sizing: each stack measured 229 MiB idle (frontend 48, backend 181), and roughly 500 MiB after an hour of use. Fifty stacks plus the host is about 26.5 GB, leaving 2.4× headroom. The app is almost entirely IO-wait because the model runs elsewhere, so memory rather than CPU is the binding constraint. Avoid burstable instance types: a workshop is exactly when CPU credits run out.

Ports are `base + N`, so participant 7 is `3107` with the default base of 3100.

## Bootstrap on a fresh box

```bash
sudo apt-get update && sudo apt-get install -y docker.io docker-compose-v2 git
sudo usermod -aG docker $USER && newgrp docker

git clone https://github.com/roadtrip123/splunky-finance.git
cd splunky-finance
python3 scripts/setup_env.py
```

`setup_env.py` writes a private `.env` with random passwords. Edit it once to set the shared LLM endpoint and credentials. Those two passwords are the ones every participant will use — they are handed out, so choose something you are comfortable saying aloud.

Leave the Galileo values blank. Participants supply their own from the portal.

## Provision

```bash
python3 scripts/workshop.py up --count 50 --host <PUBLIC_IP_OR_DNS>
```

`--host` is required and must be the address participants type into a browser. It becomes each stack's `APP_ORIGIN`, which is matched exactly on every mutating request — get it wrong and every login fails with a CSRF error rather than anything that names the real problem.

The script builds the images once, then starts each stack in turn with a two-second gap, because fifty Next.js and uvicorn processes starting simultaneously is the one real CPU spike in the whole exercise. First run on a fresh box spends a few minutes building; after that `--skip-build` starts everything immediately.

Useful flags:

| Flag | Effect |
| --- | --- |
| `--dry-run` | Print the commands, change nothing |
| `--base-port` | Default 3100, so participant N is 3100+N |
| `--bind` | Host address to bind, default `0.0.0.0` |
| `--stagger` | Seconds between starts, default 2 |
| `--skip-build` | Images already built |

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
2. Connect their own Galileo project from the portal
3. Work through the scenarios and read their own traces

Generated env files live in `workshop/` with mode 0600. They contain the LLM key and both passwords, and the directory is gitignored. Do not commit it.

## Things that bite

**Cookies ignore ports.** `host:3101` and `host:3102` share a cookie jar. Each participant using one port is unaffected, but moving between instances to help people will log you out repeatedly. Use a separate browser profile, or put a reverse proxy with subdomains in front if you have DNS.

**One LLM endpoint for fifty people** is the most likely thing to spoil the session — well ahead of anything about instance sizing. Check the endpoint's rate limits against fifty concurrent turns of roughly 2,500 input tokens each, and confirm it handles tool calling properly: this agent depends entirely on well-formed tool calls, and an endpoint that is chat-compatible but weak on tools fails every scenario.

**Evaluation cost** runs about $0.035 per turn across the four enabled metrics. Fifty participants at eight turns each is roughly $14.

**Resetting the dataset.** Participants use **Reset balance** on the DATASET card, which reuses the current seed and reference date so the figures in the lab sheet keep matching. The fuller reset control lower down allows changing the seed, which moves every number they have been given.
