#!/usr/bin/env bash
# One-command install for a single-stack instance.
#
#   sudo ./scripts/install.sh --host demo.example.com --cert /path/fullchain.pem --key /path/key.pem
#   sudo ./scripts/install.sh                      # EC2, public IP, self-signed
#   sudo ./scripts/install.sh --host 192.168.1.50  # home lab, self-signed
#
# Does everything a fresh Debian or Ubuntu box needs: Docker, Caddy, configuration, the image build,
# the self-update units, TLS, and a verification pass. Safe to re-run -- every step checks before it
# acts, so a failed run can be fixed and the script run again rather than unpicked.
#
# Where it is reached:
#   --host <addr>   Hostname or IP participants browse to. Default: this instance's public IP from
#                   EC2 metadata. Required anywhere without EC2 metadata, such as a home lab
#   --port <n>      Public HTTPS port. Default 443
#
# How TLS is terminated -- pick one. Self-signed is the default because it needs nothing:
#   --cert <f> --key <f>  Serve an existing certificate. The one to use with a wildcard: no
#                         issuance step, no rate limit, and no warning if a public CA signed it
#   --acme                Fetch a free certificate from Let's Encrypt. Needs a hostname that
#                         resolves publicly to this box, and port 80 or 443 reachable from the
#                         internet. Never attempted unless asked, so a private name cannot hang on it
#   --email <addr>        ACME account address, recommended with --acme for expiry notices
#   (default)             Self-signed from Caddy's own local authority. Browsers warn once and
#                         proceed. Fine for synthetic data; no DNS or CA involved
#   --lan-http            No TLS at all, plain HTTP. Only for an RFC1918 address on a trusted
#                         network, which the application enforces
#   --no-tls              No proxy at all, for a box already behind one. --host must then be the
#                         full origin that proxy serves
#
# Other:
#   --channel <c>   Self-update channel: tags (default), branch, off
#   --skip-build    Install everything but do not build or start the stack
set -euo pipefail

HOST=""
PORT=443
CHANNEL="tags"
CERT=""
KEY=""
EMAIL=""
ACME=0
LAN_HTTP=0
WITH_PROXY=1
BUILD=1
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

say() { printf '\n\033[1m==> %s\033[0m\n' "$*"; }
note() { printf '    %s\n' "$*"; }
warn() { printf '    \033[1;33m%s\033[0m\n' "$*"; }
die() { printf '\n\033[1;31mFAILED: %s\033[0m\n' "$*" >&2; exit 1; }

is_ip() { case "$1" in *:*) return 0 ;; *[!0-9.]*) return 1 ;; *) return 0 ;; esac; }
is_private_lan() {
  case "$1" in
    10.*|192.168.*) return 0 ;;
    172.1[6-9].*|172.2[0-9].*|172.3[01].*) return 0 ;;
    *) return 1 ;;
  esac
}

while [ $# -gt 0 ]; do
  case "$1" in
    --host) HOST="${2:?--host needs a value}"; shift 2 ;;
    --port) PORT="${2:?--port needs a value}"; shift 2 ;;
    --channel) CHANNEL="${2:?--channel needs a value}"; shift 2 ;;
    --cert) CERT="${2:?--cert needs a path}"; shift 2 ;;
    --key) KEY="${2:?--key needs a path}"; shift 2 ;;
    --email) EMAIL="${2:?--email needs an address}"; shift 2 ;;
    --acme) ACME=1; shift ;;
    --lan-http) LAN_HTTP=1; shift ;;
    --no-tls) WITH_PROXY=0; shift ;;
    --skip-build) BUILD=0; shift ;;
    -h|--help) sed -n '2,50p' "${BASH_SOURCE[0]}"; exit 0 ;;
    *) die "Unknown option: $1" ;;
  esac
done

case "$CHANNEL" in tags|branch|off) ;; *) die "--channel must be tags, branch or off" ;; esac
case "$PORT" in ''|*[!0-9]*) die "--port must be a number" ;; esac
if { [ -n "$CERT" ] && [ -z "$KEY" ]; } || { [ -z "$CERT" ] && [ -n "$KEY" ]; }; then
  die "--cert and --key go together"
fi
if [ -n "$CERT" ] && [ "$ACME" -eq 1 ]; then die "--cert and --acme are alternatives"; fi
if [ "$LAN_HTTP" -eq 1 ] && { [ -n "$CERT" ] || [ "$ACME" -eq 1 ]; }; then
  die "--lan-http means no TLS, so it cannot be combined with --cert or --acme"
fi
if [ "$LAN_HTTP" -eq 1 ] && [ "$WITH_PROXY" -eq 0 ]; then die "--lan-http and --no-tls are alternatives"; fi

[ "$(id -u)" -eq 0 ] || die "Needs root. Re-run with sudo."
command -v apt-get >/dev/null || die "Only Debian and Ubuntu are supported here; see docs/single-instance.md"

# The account that will own the repository and run the units. Running them as root would mean a
# web-reachable service with a published password sitting one step from the host.
OWNER="${SUDO_USER:-}"
[ -n "$OWNER" ] && [ "$OWNER" != "root" ] \
  || die "Run with sudo from the account that owns this repository, not as root directly."

say "Installing packages"
if command -v docker >/dev/null && docker compose version >/dev/null 2>&1; then
  note "Docker and Compose already present"
else
  apt-get update -qq
  apt-get install -y -qq docker.io docker-compose-v2 git
fi
if [ "$WITH_PROXY" -eq 1 ] && [ "$LAN_HTTP" -eq 0 ]; then
  if command -v caddy >/dev/null; then
    note "Caddy already present"
  else
    apt-get install -y -qq debian-keyring debian-archive-keyring apt-transport-https curl gpg
    curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' \
      | gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
    curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' \
      > /etc/apt/sources.list.d/caddy-stable.list
    apt-get update -qq && apt-get install -y -qq caddy
  fi
fi
# sudo reads group membership from the group database at process start, so this takes effect for the
# build below without the owner logging out and back in.
if id -nG "$OWNER" | tr ' ' '\n' | grep -qx docker; then
  note "$OWNER is already in the docker group"
else
  usermod -aG docker "$OWNER"
  note "added $OWNER to the docker group (they must reconnect before using docker by hand)"
fi

say "Finding the address"
if [ -z "$HOST" ]; then
  # IMDSv2. New instances commonly have v1 disabled, where the plain request returns nothing.
  TOKEN="$(curl -sX PUT http://169.254.169.254/latest/api/token \
    -H 'X-aws-ec2-metadata-token-ttl-seconds: 60' --max-time 3 || true)"
  HOST="$(curl -s -H "X-aws-ec2-metadata-token: $TOKEN" --max-time 3 \
    http://169.254.169.254/latest/meta-data/public-ipv4 || true)"
  [ -n "$HOST" ] || die "No EC2 metadata here, so there is no address to detect.
       Pass the address participants will browse to, for example:
         --host demo.example.com      a hostname
         --host 192.168.1.50          a home lab address"
  note "detected $HOST from EC2 metadata"
else
  note "using $HOST"
fi

# Decide the TLS mode once, here, so every later step reads one variable rather than re-deriving it.
if [ "$WITH_PROXY" -eq 0 ]; then
  MODE="external"
elif [ "$LAN_HTTP" -eq 1 ]; then
  MODE="lan-http"
elif [ -n "$CERT" ]; then
  MODE="cert"
elif [ "$ACME" -eq 1 ]; then
  MODE="acme"
else
  MODE="internal"
fi
note "TLS: $MODE"

if [ "$MODE" = "acme" ] && is_ip "$HOST"; then
  die "--acme needs a hostname, not an IP: a public certificate authority will not issue for one.
       Use a hostname, or drop --acme for a self-signed certificate."
fi
if [ "$MODE" = "lan-http" ] && ! is_private_lan "$HOST"; then
  die "--lan-http only applies to a private address (10.x, 192.168.x, 172.16-31.x).
       $HOST is not one, and the application refuses plain HTTP anywhere else."
fi
if [ "$MODE" != "lan-http" ] && [ "$MODE" != "external" ] && [ "$PORT" = "80" ]; then
  die "Caddy will not serve TLS on port 80, which it treats as the plaintext port. Use 443."
fi
for FILE in "$CERT" "$KEY"; do
  [ -z "$FILE" ] || [ -f "$FILE" ] || die "No such file: $FILE"
done

case "$MODE" in
  external) case "$HOST" in http://*|https://*) ORIGIN="$HOST" ;; *) ORIGIN="https://$HOST" ;; esac ;;
  lan-http) if [ "$PORT" = "80" ]; then ORIGIN="http://$HOST"; else ORIGIN="http://$HOST:$PORT"; fi ;;
  *)        if [ "$PORT" = "443" ]; then ORIGIN="https://$HOST"; else ORIGIN="https://$HOST:$PORT"; fi ;;
esac

if [ "$WITH_PROXY" -eq 1 ]; then
  say "Checking port $PORT is free"
  if ss -ltn "sport = :$PORT" | grep -q LISTEN; then
    # The Caddy package serves a welcome page on 80 from the moment it installs, so the listener
    # found here is often the proxy this script is about to configure.
    if ss -ltnp "sport = :$PORT" 2>/dev/null | grep -q '"caddy"'; then
      note "caddy already holds $PORT; its configuration will be replaced"
    else
      die "Something other than caddy already listens on $PORT. Use --port <n>, or stop that service."
    fi
  fi
  if iptables-save -t nat 2>/dev/null | grep -q -- "--dport $PORT .*REDIRECT"; then
    die "A firewall rule redirects port $PORT elsewhere, so this proxy would never receive traffic.
       Inspect it with: sudo iptables-save -t nat | grep -- '--dport $PORT'
       Then either remove that rule or pick a different port with --port <n>."
  fi
  note "port $PORT is free"
  # A rule removed by hand is still in the persisted ruleset, and comes back on the next boot. On a
  # box destined to become an AMI that means every clone starts with the port broken.
  for FILE in /etc/iptables/rules.v4 /etc/rc.local; do
    if [ -f "$FILE" ] && grep -q -- "--dport $PORT" "$FILE" 2>/dev/null; then
      warn "WARNING: $FILE still mentions port $PORT, so a reboot may undo this."
      warn "         Inspect with: grep -n -- '--dport $PORT' $FILE"
    fi
  done
fi

say "Writing configuration"
sudo -u "$OWNER" python3 "$ROOT/scripts/setup_env.py" --origin "$ORIGIN" || die "setup_env.py failed"
# As the owner, not as root: `sed -i` replaces the file rather than editing in place, so running it
# as root would leave a 0600 root-owned .env that the account running compose cannot read.
# Idempotent -- delete then append, so re-running does not stack duplicate lines.
set_env() {
  sudo -u "$OWNER" sed -i "/^$1=/d" "$ROOT/.env"
  printf '%s=%s\n' "$1" "$2" | sudo -u "$OWNER" tee -a "$ROOT/.env" >/dev/null
}
set_env UPDATE_CHANNEL "$CHANNEL"
if [ "$MODE" = "lan-http" ]; then
  # The application refuses plain HTTP for anything but localhost unless this is set, and refuses it
  # even then for an address outside RFC1918. Checked above.
  set_env ALLOW_PRIVATE_LAN_HTTP true
  warn "Plain HTTP: anything a participant pastes into the portal, including their own API keys,"
  warn "crosses the network in cleartext. Only do this on a network you trust."
fi
note "APP_ORIGIN=$ORIGIN, UPDATE_CHANNEL=$CHANNEL"

say "Checking containers can reach the internet"
PROBE="import urllib.request;print(urllib.request.urlopen('https://api.openai.com/v1/models',timeout=15).status)"
EGRESS="$(docker run --rm python:3.12-slim python -c "$PROBE" 2>&1 || true)"
if printf '%s' "$EGRESS" | grep -qiE 'certificate|SSLError|hostname mismatch'; then
  note "outbound HTTPS from containers is being redirected; exempting Docker's bridges"
  for IFACE in docker0 br+; do
    iptables -t nat -C PREROUTING -i "$IFACE" -p tcp --dport 443 -j RETURN 2>/dev/null \
      || iptables -t nat -I PREROUTING 1 -i "$IFACE" -p tcp --dport 443 -j RETURN
  done
  EGRESS="$(docker run --rm python:3.12-slim python -c "$PROBE" 2>&1 || true)"
  if printf '%s' "$EGRESS" | grep -qiE 'certificate|SSLError|hostname mismatch'; then
    die "Container egress is still redirected. See docs/workshop.md, 'When containers cannot reach the internet'."
  fi
  warn "fixed -- this does NOT survive a reboot; see docs/workshop.md"
fi
# A 401 is the expected answer: the request arrived and was rejected for having no key.
printf '%s' "$EGRESS" | grep -qE '401|200' || die "Containers cannot reach api.openai.com:
$EGRESS"
note "reached api.openai.com (401 = arrived, no key supplied)"

say "Installing the self-update units"
INSTALL_ARGS=()
if [ "$BUILD" -eq 1 ]; then INSTALL_ARGS+=(--build); fi
python3 "$ROOT/scripts/install_service.py" "${INSTALL_ARGS[@]}" || die "install_service.py failed"

if [ "$WITH_PROXY" -eq 1 ]; then
  say "Configuring the proxy on port $PORT"
  # The port is left off the site address when it is the default for the scheme, so the generated
  # config reads the way someone would write it by hand.
  DEFAULT_PORT=443
  if [ "$MODE" = "lan-http" ]; then DEFAULT_PORT=80; fi
  if [ "$PORT" = "$DEFAULT_PORT" ]; then SITE="$HOST"; else SITE="$HOST:$PORT"; fi
  {
    case "$MODE" in
      cert)
        # Copied rather than referenced: Caddy runs as its own user and a certificate is usually
        # root-owned and unreadable to it. A certificate that renews on disk should instead be
        # referenced in place -- edit the Caddyfile to point at the live path.
        install -o caddy -g caddy -m 0600 "$CERT" /etc/caddy/tls.crt
        install -o caddy -g caddy -m 0600 "$KEY" /etc/caddy/tls.key
        # default_sni only matters for a bare IP: TLS forbids sending SNI for one, so without a
        # default there is no name to select a certificate by and every handshake is aborted.
        if is_ip "$HOST"; then printf '{\n\tdefault_sni %s\n}\n' "$HOST"; fi
        printf '%s {\n\ttls /etc/caddy/tls.crt /etc/caddy/tls.key\n\treverse_proxy 127.0.0.1:3000\n}\n' "$SITE"
        ;;
      acme)
        if [ -n "$EMAIL" ]; then printf '{\n\temail %s\n}\n' "$EMAIL"; fi
        printf '%s {\n\treverse_proxy 127.0.0.1:3000\n}\n' "$SITE"
        ;;
      lan-http)
        printf '{\n\tauto_https off\n}\nhttp://%s {\n\treverse_proxy 127.0.0.1:3000\n}\n' "$SITE"
        ;;
      internal)
        printf '{\n\tauto_https disable_redirects\n\tskip_install_trust\n'
        if is_ip "$HOST"; then printf '\tdefault_sni %s\n' "$HOST"; fi
        printf '}\n%s {\n\ttls internal\n\treverse_proxy 127.0.0.1:3000\n}\n' "$SITE"
        ;;
    esac
  } > /etc/caddy/Caddyfile
  caddy validate --config /etc/caddy/Caddyfile >/dev/null 2>&1 \
    || die "Caddy rejected the generated config. Inspect /etc/caddy/Caddyfile and run:
       sudo caddy validate --config /etc/caddy/Caddyfile"
  systemctl restart caddy
  note "wrote /etc/caddy/Caddyfile and restarted caddy"
fi

if [ "$BUILD" -eq 1 ]; then
  say "Verifying"
  STACK="$(curl -s -o /dev/null -w '%{http_code}' --max-time 10 http://127.0.0.1:3000/ || true)"
  note "stack on 127.0.0.1:3000 -> $STACK"
  [ "$STACK" = "200" ] || die "The application is not answering. Check: docker compose ps; docker compose logs backend"
  if [ "$WITH_PROXY" -eq 1 ]; then
    # Retried, not sampled once: Caddy provisions certificates and binds after systemd reports the
    # restart done, so an immediate check fails on a proxy that is about to work.
    SCHEME="https"
    if [ "$MODE" = "lan-http" ]; then SCHEME="http"; fi
    PROXY="000"
    for _ in 1 2 3 4 5 6 7 8 9 10; do
      PROXY="$(curl -sk -o /dev/null -w '%{http_code}' --max-time 5 \
        --connect-to "$HOST:$PORT:127.0.0.1:$PORT" "$SCHEME://$HOST:$PORT/" || true)"
      # `if`, not `[ ... ] && break`: an AND-list whose test fails returns non-zero and `set -e`
      # would take the script down on the first retry.
      if [ "$PROXY" = "200" ]; then break; fi
      sleep 2
    done
    note "proxy on $PORT -> $PROXY"
    if [ "$PROXY" != "200" ]; then
      note "this check goes through loopback, and the proxy may still be serving correctly."
      note "Confirm from another machine before treating it as broken:  curl -I $ORIGIN/"
      die "Could not verify the proxy locally. Check: journalctl -u caddy -n 30"
    fi
  fi
fi

say "Installed"
cat <<EOF

  Open            $ORIGIN
  Presenter       $ORIGIN/demo-admin
  Customer login  12345678

EOF
case "$MODE" in
  cert)     note "Serving the certificate you supplied. No warning if a public CA signed it." ;;
  acme)     note "Certificate from Let's Encrypt, renewed automatically. No warning." ;;
  internal) note "Self-signed: every visitor accepts a warning once. Tell them beforehand." ;;
  lan-http) note "Plain HTTP on a trusted private network. Not encrypted." ;;
  external) note "No proxy installed; the one in front of this box terminates TLS." ;;
esac
cat <<EOF

Still to do, and neither can be done from this box:

  1. Allow inbound TCP $PORT to this machine, in its security group or firewall.
  2. Browse the address above from another machine. A cloud instance cannot reach
     its own public address, so testing from here proves nothing.

Then set the model endpoint in the presenter portal -- not in .env.

  Update now        sudo systemctl start splunky-finance
  What it decided   journalctl -u splunky-finance -n 30
EOF
