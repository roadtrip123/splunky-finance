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
does not publish the port, and a managed lab environment may publish only one. Check what already
owns it, because something is answering on it:

```bash
sudo ss -ltnp | grep ':443 ' ; sudo iptables-save -t nat | grep -- '--dport 443'
```

A listener means the platform's own proxy has that port, and there is nothing to do but pass
`--port <n>` and use a high port.

A `REDIRECT` rule is a different thing and is handled. It catches traffic arriving on *any*
interface, so a proxy of your own on 443 binds successfully and never receives a packet. Rather than
fight it, `install.sh` reads the destination out of the rule and serves that port as well as 443, so
the box answers whether the rule is present or not. The address participants browse does not change.
This is the arrangement to prefer on a shared lab image, where the rule is restored on every boot by
something outside the box. A unit that deletes the rule at boot is installed as well, as insurance
rather than as the mechanism; see [Update itself on boot](#update-itself-on-boot).

## Install

```bash
sudo apt-get update && sudo apt-get install -y git
git clone --branch v1.0.0 https://github.com/roadtrip123/splunky-finance.git
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

### A platform that names every instance

Some lab platforms assign each instance its own name when it boots, such as
`i-0abc123def456.example.com`, and give you no `cloud-init` and no SSH for participants. The name
cannot be baked into an image, and nothing on the box knows it until it is running. A boot-time unit
that writes the address is the obvious answer and the wrong one: the unit that already exists for the
port redirect did not run on the first box this was tried on, and a hundred boxes is the wrong place
to find that out.

So configure no address at all. Two things make one image work on every name:

```bash
sudo ./scripts/install.sh --host '*.example.com' --cert /path/fullchain.pem --key /path/key.pem
```

- **The proxy serves by port, not by name.** The site block becomes `:443, :8443` with no hostname
  in it, so Caddy answers whatever `Host` arrives. A wildcard certificate covers every instance, and
  because TLS is terminated with a supplied certificate there is no issuance step per name. This is
  why `--acme` is refused for a wildcard: a public CA needs a DNS challenge, which this script does
  not do.
- **`APP_ORIGIN` becomes `https://*.example.com`.** The one place the application used the address
  is an Origin check on mutating requests, which now accepts exactly one label under that domain.
  `https://*.com` and `https://a.*.example.com` are both refused at startup, as is anything deeper
  than one label at runtime, including a name that merely ends with the domain.

What that check is worth is unchanged for everything else: session cookies stay host-scoped,
`HttpOnly`, `Secure` and `SameSite=Strict`, so a page on a sibling instance sends no cookie at all,
and every mutating request still carries the session's own CSRF token. The Origin comparison is the
third layer, and the wildcard widens it to your own lab domain rather than to the internet.

The install verifies it with a name it was never told about, which is the right test: a request for
`probe.example.com` must be served, on the public port and on the redirect's destination.

Nothing is left to do per instance, so a snapshot taken here comes up working on whatever name the
platform hands the clone. The one thing lost is the per-clone `SESSION_SECRET` rotation, which has
to run somewhere; with it shared, a session cookie minted on one box is accepted by another. For
synthetic data behind a password published in this repository that is a fair trade, and
`python3 scripts/setup_env.py --rotate-secret` is there if you would rather not take it.

### When the redirect hijacks the containers too

`PREROUTING` catches traffic arriving on *any* interface, the Docker bridges included, so the same
rule that hides the box from a browser also redirects every container's own outbound HTTPS. It
leaves the backend bound for an observability tenant and lands on whatever listens on 8443 locally,
which, since the proxy was made to serve both ports, is this application. The SDK reports

```
[SSL: CERTIFICATE_VERIFY_FAILED] Hostname mismatch, certificate is not valid for
'api.multitenant.galileocloud.io'
```

which carries no status code, so it reads as a generic connection failure and sends a presenter to
check credentials that were always fine. One script, no arguments:

```bash
sudo python3 scripts/allow_container_egress.py --dry-run
sudo python3 scripts/allow_container_egress.py
```

It inserts a `RETURN` for `docker0` and `br+` ahead of the redirect, writes them into
`/etc/iptables/rules.v4` **above** the redirect line, since `iptables-restore` applies the file top
to bottom and a bypass after the redirect is never reached, then probes from inside the backend
container. That last part matters: traffic the host originates goes through `OUTPUT` and never meets
`PREROUTING`, so a probe run on the host passes whether or not containers are affected, which is
exactly what made this fault look like a credential problem.

Persisting into the saved ruleset rather than a boot unit was the first fix, and it is not enough on
its own. **Presence is not precedence.** A lab instance was found carrying both bypasses, live and
saved, with the backend still hijacked:

```
-A PREROUTING -p tcp -m tcp --dport 443 -j REDIRECT --to-ports 8443
-A PREROUTING -i docker0 -p tcp -m tcp --dport 443 -j RETURN
-A PREROUTING -i br+ -p tcp -m tcp --dport 443 -j RETURN
```

The platform inserts its redirect at position 1, and it does so after `netfilter-persistent` has
restored the saved ruleset, so both RETURN rules end up below it and are never read. Writing the
rules once cannot win against something that re-inserts at the top whenever it likes, and the script
made it worse by reporting "already bypassed" on finding them present.

So the check compares positions rather than membership, repairs by deleting and re-inserting at
position 1, and runs repeatedly for as long as the box is up:

```bash
systemctl list-timers splunky-finance-egress.timer
journalctl -u splunky-finance-egress -b
sudo iptables -t nat -S PREROUTING        # both RETURNs must print above the REDIRECT
```

`splunky-finance-egress.timer` runs 45 seconds after boot and every three minutes after that, which
heals a redirect inserted at any point, mid-workshop included. The check is one `iptables -S`, so
running it often costs nothing. `netfilter-persistent` is still ridden for the saved file, because it
demonstrably runs on these images: it is what restores the redirect every boot. The timer is what
settles the order afterwards.

### A box that is already running

`install.sh` writes the proxy's config at install time and nothing in the update path touches that
file again, so a box built from an older image does not get either arrangement from a release. One
script each, and neither needs arguments:

```bash
sudo python3 scripts/serve_redirect_port.py --dry-run     # add the redirect's destination port
sudo python3 scripts/serve_redirect_port.py

sudo python3 scripts/serve_any_host.py --dry-run          # also stop matching on the hostname
sudo python3 scripts/serve_any_host.py
```

Use the second one where the platform names every instance, as above. It does what the first does
and drops the hostname as well, sets `APP_ORIGIN` to the wildcard, restarts the stack, which is what
applies it, and then checks two names the proxy has never been told about plus the Origin check
behind them. The domain comes from the current `APP_ORIGIN` unless `--domain` says otherwise.

It reads the destination out of the rule, in the live nat table and in the saved file, defaults to
8443 when there is no rule to read, adds that address to every site serving the public port, keeps a
`.bak`, validates before restarting Caddy, puts the old file back if Caddy rejects or will not start,
and then checks both the direct and the redirected path. Running it twice changes nothing the second
time. It leaves alone a workshop config serving a port per participant, and a plain-HTTP LAN config,
because a redirect of 443 is not those boxes' problem.

Make the same edit in the image before snapshotting, or every clone needs it by hand.

## Installing by hand

The script is the recommended path. This is what it does, for a box where some step has to differ.

```bash
sudo apt-get update && sudo apt-get install -y docker.io docker-compose-v2 git
sudo usermod -aG docker $USER && newgrp docker

sudo apt-get install -y debian-keyring debian-archive-keyring apt-transport-https curl
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | sudo gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' | sudo tee /etc/apt/sources.list.d/caddy-stable.list >/dev/null
sudo apt-get update && sudo apt-get install -y caddy

git clone --branch v1.0.0 https://github.com/roadtrip123/splunky-finance.git
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
printf '{\n\tauto_https disable_redirects\n\tdefault_sni %s\n\tskip_install_trust\n}\n%s:443, %s:8443 {\n\ttls internal\n\treverse_proxy 127.0.0.1:3000\n}\n' "$IP" "$IP" "$IP" | sudo tee /etc/caddy/Caddyfile >/dev/null
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

That installs all four units, substituting the repository's real path and the account that invoked
`sudo` — the units ship with defaults for a stock Ubuntu AMI, and a box whose user or path differs
would install them, report success and never work. It also creates `runtime/update/` owned by the uid
the backend container runs as, which is what the portal's install button needs. `--build` then runs
the first update in the foreground so the image build's output is visible rather than buried in the
journal.

One of the four is not about updates. `splunky-finance-ports.service` runs
[`scripts/fix_ports.py`](../scripts/fix_ports.py) on every boot to remove a redirect of port 443,
which shared lab images carry in `/etc/iptables/rules.v4` so that an unprivileged web server can sit
on 8443. The unit is ordered `After=netfilter-persistent.service`, because that is what replays the
saved rules at boot and would otherwise undo an earlier fix. It only ever deletes, only matches a
REDIRECT of 443, and exits cleanly when there is nothing to do, so it is inert on a box that does
not have the fault.

**It is insurance rather than the mechanism.** The proxy serves 8443 as well as 443, so the box
answers whether the rule is removed or not, and this unit failing to run no longer takes the portal
down. Leave it installed anyway: it is free, and a box that serves 443 directly is one less thing
depending on a rule nobody here controls.

`sudo python3 scripts/install_service.py --dry-run` prints the units it would write, without root.

`sudo systemctl restart splunky-finance` updates now without rebooting, and
`journalctl -u splunky-finance` is the record of what the last boot decided.

**`restart`, not `start`.** The unit is `Type=oneshot` with `RemainAfterExit=yes`, so once it has
run it sits in `active (exited)` — and `systemctl start` on an active unit does nothing and says
nothing. It is the quietest way to believe you applied a change that you did not: an `.env` edit
stays unapplied, and the symptom is the application rejecting requests for an origin it has never
been told about.

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
git tag -a v1.0.1 -m "..." && git push origin v1.0.1   # then, on each box:
sudo systemctl restart splunky-finance
```

## Check it

In this order. Each failure looks like the next one if taken out of order.

```bash
sudo ss -ltn | grep -E ':(443|8443) '
curl -s  -o /dev/null -w 'stack=%{http_code}\n' http://127.0.0.1:3000/
curl -sk -o /dev/null -w 'direct=%{http_code}\n'    --connect-to <public-ip>:443:127.0.0.1:443  https://<public-ip>/
curl -sk -o /dev/null -w 'redirected=%{http_code}\n' --connect-to <public-ip>:443:127.0.0.1:8443 https://<public-ip>/
```

Two listeners is correct, not a conflict. The fourth line is the one that matters on a lab image: it
sends the `Host` header a browser sends, with no port in it, into the listener the redirect lands on.
That is the exact shape of arriving traffic there, and it is the only check that proves the second
address is *matched* rather than merely bound. Both should answer 200.

**A local check cannot see the redirect at all.** It lives in `PREROUTING`, which only traffic
arriving on an interface traverses; anything this box originates goes through `OUTPUT` and reaches
443 directly. So `curl https://127.0.0.1/` passes on a box that is unreachable from a browser, which
is what made this fault look intermittent. Name the port you mean, and finish from somewhere else.

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
than assuming it, and lists what the image will still carry.

It also clears the same values from `.env`, which is not in the volume and is deliberately kept for
the address and the demo passwords, so destroying the volume does not touch it. Every provider and
observability key is blanked, and so is `GALILEO_PROJECT`: not a credential, but the lab has each
participant create their own project, and a field arriving pre-filled with somebody else's name
either fails with "project not found" or, worse, succeeds and sends their traces into a project that
is not theirs. `GALILEO_LOG_STREAM` is blanked with them, so the form arrives as the lab
describes it, with step 10 telling the participant to type the name. Blanked rather than deleted:
present and empty overrides the application default, while deleting the line restores
`my-bank-agent` and puts a value back in the field. Tenant URLs are kept and reported, since they
are not credentials and save the instructor reading them out; `--blank-urls` clears those too. The
script then re-reads `.env` and **fails** rather than warning if anything is still set, because a
warning only works if somebody reads it.

Then confirm by eye: open the portal, check the Setup tab lists no endpoint and no observability
credentials, and that the app still answers on its public address from another machine.

### Check the saved firewall rules before you snapshot

A redirect of port 443 saved in `/etc/iptables/rules.v4` is baked into the image and replayed on
every clone. Serving 8443 as well is what makes that survivable, so what to check before snapshotting
is that the proxy holds both ports, not that the rule is gone:

```bash
sudo ss -ltn | grep -E ':(443|8443) '
grep ':8443' /etc/caddy/Caddyfile
systemctl is-enabled splunky-finance-ports
sudo python3 scripts/fix_ports.py --dry-run
```

And the container's way out, which is a different rule and a different failure. Both RETURNs must
print **above** the REDIRECT, and the timer that keeps them there must be enabled, or every clone
comes up with observability broken and no browser-only participant able to fix it:

```bash
sudo iptables -t nat -S PREROUTING
systemctl is-enabled splunky-finance-egress.timer
docker compose exec -T backend python3 -c "import httpx; print(httpx.get('https://api.github.com', timeout=10).status_code)"
```

A status code from inside the container is the proof. A certificate hostname mismatch there means
the bypass is below the redirect, whatever `iptables -C` would say about it being present.

Then prove it on this box, before it becomes a hundred boxes. Put the rule back and confirm the same
URL is served with it present and with it absent:

```bash
IP=<public-ip>
sudo iptables -t nat -A PREROUTING -p tcp -m tcp --dport 443 -j REDIRECT --to-ports 8443
curl -sk -o /dev/null -w 'redirected=%{http_code}\n' --connect-to "$IP:443:127.0.0.1:8443" "https://$IP/"
sudo iptables -t nat -D PREROUTING -p tcp -m tcp --dport 443 -j REDIRECT --to-ports 8443
curl -sk -o /dev/null -w 'direct=%{http_code}\n'     --connect-to "$IP:443:127.0.0.1:443"  "https://$IP/"
```

Two 200s and the image is immune to the rule either way. Leave whichever state you like in the
snapshot; it no longer decides whether a clone comes up reachable.

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
