# One instance per demo

One stack on its own instance, reached at `https://<public-ip>` on port 443. Use this for a partner
demo, and for a workshop where each participant gets their own box rather than a port on a shared one.

It is simpler than the fifty-stacks-on-one-box path in [workshop.md](workshop.md), and worth choosing
for one reason above the others: **it needs only port 443.** No port range to have opened, no port
arithmetic, no per-participant origin template. A perimeter that publishes one port is enough.

The trade-off is fifty instances to launch and terminate instead of one. [Bake an
AMI](#bake-an-ami-before-the-second-one) and that becomes a launch template rather than fifty
builds.

## Instance

| | |
| --- | --- |
| Type | `t3.medium` — 2 vCPU, 4 GiB |
| Disk | **30 GB gp3**, not the 8 GB default |
| OS | Ubuntu 24.04 |
| Security group | Inbound TCP 443 from wherever the audience sits. Port 80 is not needed — a local CA issues the certificate, so there is no HTTP challenge |

Sizing: one stack is about 1 GiB with the host — the backend measured 181 MiB idle and roughly 400 MiB
warm, the frontend 48 MiB. The model runs elsewhere, so the box is almost entirely IO-wait and memory
is never the constraint at runtime.

**The build sets the floor, not the running app.** `npm ci` and `next build` peak around 2 GiB, from
494 MB of `node_modules` producing a 157 MB `.next` output. That is why 4 GiB rather than 2: a
`t3.small` runs the stack fine and dies during the build. If you bake an AMI, the clones never build
and `t3.small` becomes reasonable.

Disk is the easy mistake. The two images are only ~700 MB, but build cache takes Docker's footprint to
about 4 GB and Ubuntu 24.04 already uses 2.5 GB. The 8 GB default root leaves a few hundred MB.

Burstable is fine here. The advice against it in [workshop.md](workshop.md) is about fifty stacks on
one box; a single stack idles far below baseline, and launch credits cover a one-off build.

## Before you build

`scripts/install.sh` runs the on-box checks itself and stops with a reason rather than continuing on
a wrong assumption, so the only one worth doing by hand first is the one the box cannot do:

```bash
# From a machine outside the network, not from the instance.
timeout 6 bash -c 'cat < /dev/null > /dev/tcp/<public-ip>/443' && echo open || echo blocked
```

`blocked` before the security group is opened is expected. `blocked` *after* means the perimeter
does not publish the port, and a managed lab environment may publish only one — in which case check
what already owns it, because something is answering on it:

```bash
sudo ss -ltnp | grep ':443 ' ; sudo iptables-save -t nat | grep -- '--dport 443'
```

A listener, or a `REDIRECT`/`DNAT` rule, means the platform's own proxy has that port. A redirect in
`PREROUTING` catches traffic arriving on *any* interface, so a proxy of your own on 443 would bind
successfully and never receive a packet. Either remove the rule, if the box is yours to change, or
pass `--port <n>` and use a high port.

## Install

```bash
sudo apt-get update && sudo apt-get install -y git
git clone --branch v0.6.8 https://github.com/roadtrip123/splunky-finance.git
cd splunky-finance
sudo ./scripts/install.sh
```

That installs Docker and Caddy, reads this instance's public IP from EC2 metadata, writes the
configuration, builds the images, installs the self-update units, terminates TLS on 443, and verifies
the result. It is safe to re-run: every step checks before acting, so a failed run is fixed and the
script run again rather than unpicked.

It stops with a reason rather than continuing on a wrong assumption when the public IP cannot be
read, when something already holds port 443, when a firewall rule redirects that port elsewhere, or
when containers cannot reach the internet — the last of which it first tries to fix, since the cause
is usually a redirect of container egress that Docker's bridges can be exempted from.

Two things it cannot do, and says so at the end:

- **Open inbound TCP 443** to the instance in its security group.
- **Test from another machine.** An EC2 instance cannot reach its own public IP, so a check from the
  box proves nothing about whether anyone else can connect.

Then set the model endpoint in the presenter portal, not in `.env`.

### How TLS gets terminated

The script picks nothing for you beyond the default. Pass the mode that matches where this box lives:

| Mode | When | Warning in the browser? |
| --- | --- | --- |
| `--cert <f> --key <f>` | A certificate is already available, such as an organisation wildcard | **None**, if a public CA signed it |
| `--acme` | A hostname that resolves publicly, and no certificate in hand | **None** |
| *(default)* | Anything else — a bare IP, a home lab, a private name | Once per visitor |
| `--lan-http` | A trusted private network where TLS is not wanted | No TLS at all |

**`--cert` is the one to reach for wherever a wildcard exists.** It is the only mode with no issuance
step: nothing is fetched at boot, there is no rate limit, and a clone of the image serves immediately.
With a wildcard such as `*.example.com`, every box can carry the same certificate and serve its own
hostname.

`--acme` is **never attempted unless you ask for it**, which matters on a private network: a hostname
that does not resolve publicly would otherwise hang trying to reach Let's Encrypt. It also refuses an
IP address, because no public authority will issue for one.

A wildcard matches **one label only**. `*.example.com` covers `demo.example.com` but not
`demo.lab.example.com`. When asking for per-box hostnames, ask for single-label names.

Other options: `--host <addr>` wherever EC2 metadata is unavailable — a home lab needs it —
`--port <n>`, `--channel branch` to follow the branch tip rather than releases, `--email` with
`--acme`, `--no-tls` for a box already behind a proxy, and `--skip-build`. `--help` lists them.

### A hostname and a certificate

The best-behaved deployment, and the one to use when an organisation wildcard is available:

```bash
sudo ./scripts/install.sh --host demo.example.com \
  --cert /opt/certs/wildcard.example.com.crt \
  --key /opt/certs/example.com.key
```

Everything that existed to cope with a bare IP disappears: no `tls internal`, no `default_sni`, no
accepted warning, and `http://` redirects to `https://` for free. Check the certificate before
trusting it — four things can be wrong and three are silent:

```bash
sudo openssl x509 -in /opt/certs/wildcard.example.com.crt -noout -subject -issuer -dates -ext subjectAltName
```

```bash
echo "certs in file: $(sudo grep -c 'BEGIN CERTIFICATE' /opt/certs/wildcard.example.com.crt)"
```

Wanted: a `subjectAltName` covering the hostname, an issuer that is a public CA rather than an
internal one, an expiry comfortably ahead, and **two or more certificates in the file**. One means
leaf-only with no intermediate, which is the classic "works in curl, fails in Safari" bug. Confirm
the key matches the certificate:

```bash
sudo bash -c 'diff <(openssl x509 -in /opt/certs/wildcard.example.com.crt -noout -pubkey) <(openssl pkey -in /opt/certs/example.com.key -pubout) >/dev/null && echo match || echo MISMATCH'
```

The files are copied to `/etc/caddy/tls.{crt,key}` with ownership the proxy can read, because a
certificate is usually root-owned and `0600`. If yours renews on disk, point the Caddyfile at the live
path instead so a renewal is picked up.

### A home lab

No EC2 metadata, so the address has to be given:

```bash
sudo ./scripts/install.sh --host 192.168.1.50
```

That serves HTTPS with a self-signed certificate — one accepted warning, no DNS and no CA involved.
If a real hostname points at the box and port 80 or 443 reaches it from the internet, `--acme` gets a
trusted certificate instead. `--lan-http` drops TLS altogether, and works only for an RFC1918 address
because the application refuses plain HTTP anywhere else; anything pasted into the portal, including a
participant's own API keys, then crosses the network in cleartext.

## Installing by hand

The script is the recommended path. This is what it does, for a box where some step has to differ.

```bash
sudo apt-get update && sudo apt-get install -y docker.io docker-compose-v2 git
sudo usermod -aG docker $USER && newgrp docker

sudo apt-get install -y debian-keyring debian-archive-keyring apt-transport-https curl
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | sudo gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' | sudo tee /etc/apt/sources.list.d/caddy-stable.list >/dev/null
sudo apt-get update && sudo apt-get install -y caddy

git clone --branch v0.6.8 https://github.com/roadtrip123/splunky-finance.git
cd splunky-finance
python3 scripts/setup_env.py --origin <public-ip>
```

`--origin` takes a bare address or a full origin and writes `APP_ORIGIN` with the matching
`SESSION_COOKIE_SECURE`. The two are validated together — HTTPS without secure cookies, or the
reverse, and the backend refuses to start.

Nothing else in `.env` needs editing. `FRONTEND_BIND_ADDRESS=127.0.0.1` and `FRONTEND_PORT=3000` are
already the defaults and should stay, because the proxy is the only thing that should be public. If
the box belongs to a workshop participant rather than a presenter, hide the troubleshooting tab and
the project setup control with `sed -i 's|^DEMO_MODE=.*|DEMO_MODE=workshop|' .env`.

Then build, install the units, and terminate TLS:

```bash
sudo python3 scripts/install_service.py --build

IP=<public-ip>
printf '{\n\tauto_https disable_redirects\n\tdefault_sni %s\n\tskip_install_trust\n}\n%s:443 {\n\ttls internal\n\treverse_proxy 127.0.0.1:3000\n}\n' "$IP" "$IP" | sudo tee /etc/caddy/Caddyfile >/dev/null
sudo caddy validate --config /etc/caddy/Caddyfile && sudo systemctl restart caddy
```

`default_sni` is required, not optional. TLS forbids sending SNI for an IP address, so browsers and
curl send no server name; without a default, Caddy has nothing to select a certificate by and aborts
every handshake with an internal error — after logging that it obtained the certificate and bound the
port. Nothing in the logs points at it.

The Caddy package starts the service on install and owns `/etc/caddy/Caddyfile` and port 2019: edit
that file and use `systemctl`, rather than `caddy run` by hand, which fails to bind the admin port.

Audiences see a certificate warning once and click through. **Tell them beforehand**, or the first
five minutes go on it. A self-signed certificate stops passive sniffing, which is the real risk on
shared wifi; it does not prove the server's identity. For synthetic data that is a reasonable place
to stop.

## Update itself on boot

An instance spun up for a workshop should not be running whatever was baked into the AMI weeks
earlier, and rebuilding the AMI for every fix is the thing this avoids. Install the unit and the box
updates itself each time it starts:

```bash
sudo python3 scripts/install_service.py --build
```

That installs all three units, substituting the repository's real path and the account that invoked
`sudo` — the units ship with defaults for a stock Ubuntu AMI, and a box whose user or path differs
would install them, report success and never work. It also creates `runtime/update/` owned by the uid
the backend container runs as, which is what the portal's install button needs. `--build` then runs
the first update in the foreground so the image build's output is visible rather than buried in the
journal.

`sudo python3 scripts/install_service.py --dry-run` prints the units it would write, without root.

`systemctl start splunky-finance` updates now without rebooting, and
`journalctl -u splunky-finance` is the record of what the last boot decided.

### Updating from the presenter portal

The Troubleshooting tab gets a **Software updates** card showing the running release, the newest
published one, and an **Install** button when they differ. Install two more units for it, and give the
shared directory to the backend's user:

`scripts/install_service.py` above sets this up. If the stack was already running when you installed
the units, restart it so it picks up the new bind mount:

```bash
docker compose up -d
```

`runtime/update/` is written by two different identities and needs both: the host account that runs
the updater writes the state file, and the container writes the request. The installer gives it to
`<owner>:10001` with mode `0770` — user for the host, group for the container, which runs as uid and
gid 10001. Handing it to the container outright locks the host out of its own directory, and the
symptom is the updater reporting that it could not record what it did. If the card reports versions
but offers no install button, it says which half is missing.

The container does not perform the update. It writes a request file into `runtime/update/`, a
systemd path unit notices, and the host does the work. That boundary is deliberate: the presenter
password is published in this repository, read aloud at workshops and identical on every box, so a
container holding the Docker socket would mean anyone with that password owns the instance. Writing
one file is the whole capability it has, and the worst case is a pull of a tag from this repository.

The card is presenter-only — the Troubleshooting tab is hidden in workshop mode, so participants
cannot restart their own box mid-exercise.

### What it will and will not do

Two properties matter more than being current, because this runs with nobody watching on the morning
of a workshop:

- **It never leaves the box worse than it started.** The build runs before anything is recreated, so a
  build that fails leaves the running stack untouched. A stack that comes up unhealthy within
  `UPDATE_TIMEOUT` is rolled back to the commit that was checked out on entry, rebuilt, and restarted.
- **It never blocks on the network.** A failed fetch is logged and skipped, and the stack starts on
  the code already present.

It also refuses to update when tracked files are modified, because that means somebody edited the box
by hand and updating would discard their work.

### Which channel

`UPDATE_CHANNEL` in `.env`:

| | |
| --- | --- |
| `tags` | Newest `v*` tag. **The default** |
| `branch` | Tip of `UPDATE_BRANCH` |
| `off` | Start without updating |

`tags` rather than branch HEAD is deliberate. A tag is a decision someone made; a branch tip is
whatever was pushed last, and fifty boxes pulling it at nine in the morning is fifty boxes inheriting
an unfinished commit. Use `branch` when you are iterating and want the boxes to follow along —
then **tag before the workshop and switch back**.

Either way, publishing a fix means pushing it and restarting the instances, with no AMI rebuild:

```bash
git tag -a v0.6.8 -m "..." && git push origin v0.6.8   # then, on each box:
sudo systemctl restart splunky-finance
```

## Check it

In this order. Each failure looks like the next one if taken out of order.

```bash
sudo ss -ltn | grep ':443 '
curl -s  -o /dev/null -w 'stack=%{http_code}\n' http://127.0.0.1:3000/
curl -sk -o /dev/null -w 'proxy=%{http_code}\n' --connect-to <public-ip>:443:127.0.0.1:443 https://<public-ip>/
```

`--connect-to` rather than `--resolve`: curl ignores `--resolve` when the host is already an IP literal
and quietly tries the real address, which hangs — an EC2 instance cannot reach its own public IP,
because AWS translates it rather than putting it on the interface. **The browser test has to come from
somewhere else.**

Last, open `https://<public-ip>` from a machine outside, accept the warning, and sign in with the
customer number and shared password. Then walk [workshop-lab.md](workshop-lab.md) once, including
creating the Agent Control agent — the step most likely to catch people.

## Bake an AMI

Instance-per-demo otherwise repeats the build, and the egress and firewall checks, on every box.

### First, remove your own credentials

**Clearing fields in the portal is not good enough.** Credentials live in `galileo-settings.json`
inside the runtime volume, and a field you forget to clear is a field every clone inherits — a
hundred people holding your API key. Destroy the volume rather than editing it:

```bash
sudo ./scripts/reset_for_snapshot.sh --confirm
```

Run it without `--confirm` first and it prints exactly what it will delete. It stops the stack,
destroys the runtime volume, starts clean, then **proves** `galileo-settings.json` is gone rather
than assuming it, and lists what the image will still carry. It also warns if a provider key is set
in `.env`, which is not in the volume and would survive.

Then confirm by eye: open the portal, check the Setup tab lists no endpoint and no observability
credentials, and that the app still answers on its public address from another machine.

### Then snapshot

1. `aws ec2 create-image --instance-id <id> --name splunky-finance-<version>`, or the console
2. Launch the rest through a launch template carrying the instance type, the 30 GB volume and the
   security group

### Every clone needs three things rewritten

A clone carries the address of the box it was baked from, in `.env` and in the proxy's config, and a
session secret shared with every other clone. This is the whole of a `cloud-init` `runcmd` block,
for a **hostname with a wildcard certificate** — the shape that scales, because the certificate is
identical on every box and only the site name differs:

```bash
HOST="$(hostname -f)"
cd /home/ubuntu/splunky-finance
sudo -u ubuntu python3 scripts/setup_env.py --origin "$HOST" --rotate-secret
printf '%s {\n\ttls /etc/caddy/tls.crt /etc/caddy/tls.key\n\treverse_proxy 127.0.0.1:3000\n}\n' "$HOST"   > /etc/caddy/Caddyfile
systemctl restart caddy
systemctl restart splunky-finance
```

Substitute however the platform tells a box its own name; `hostname -f` works when it is set from
DHCP or cloud-init. For a **bare IP with a self-signed certificate**, read the address from instance
metadata instead and generate that form of config:

```bash
TOKEN=$(curl -sX PUT http://169.254.169.254/latest/api/token -H 'X-aws-ec2-metadata-token-ttl-seconds: 60')
HOST=$(curl -s -H "X-aws-ec2-metadata-token: $TOKEN" http://169.254.169.254/latest/meta-data/public-ipv4)
printf '{\n\tauto_https disable_redirects\n\tskip_install_trust\n\tdefault_sni %s\n}\n%s {\n\ttls internal\n\treverse_proxy 127.0.0.1:3000\n}\n' "$HOST" "$HOST" > /etc/caddy/Caddyfile
```

The token request is the IMDSv2 handshake; new instances commonly have IMDSv1 disabled, where the
plain request returns nothing and `--origin` is handed an empty string.

`systemctl restart splunky-finance` rather than `docker compose up -d`, so a clone picks up any
release published since the image was baked. `--rotate-secret` issues a new cookie signing key:
without it a session cookie minted on one box is valid on all of them.

Two things a clone block cannot cover:

- **The container egress `iptables` rule**, if the platform redirects container traffic. It does not
  survive a reboot, let alone an image, so add it to the same block.
- **A certificate expiry baked into the image.** Clones launched after that date serve an expired
  certificate. Record the expiry wherever the image is recorded —
  `openssl x509 -in /etc/caddy/tls.crt -noout -enddate` prints it.

## Why not one instance with fifty stacks

Both paths are supported. Choose by what your network allows and what you would rather operate:

| | Instance per demo | Fifty stacks on one box |
| --- | --- | --- |
| Ports needed | 443 only | 3101–3150 inbound |
| Infrastructure | 50 instances, a launch template, an AMI | 1 instance |
| Cost, 4 hours | ~$8 plus a few dollars of EBS | ~$2 |
| Blast radius | One person | Everyone |
| Updating mid-session | Per instance | One `workshop.py up` |
| Cookie collisions | None — separate hosts | Ports share a cookie jar; moving between stacks logs you out |

The fifty-stack path is in [workshop.md](workshop.md).
