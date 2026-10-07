#!/usr/bin/env bash
# One-command install for a single-stack instance reached over HTTPS.
#
#   sudo ./scripts/install.sh
#
# Does everything a fresh Debian or Ubuntu box needs: Docker, Caddy, configuration, the image build,
# the self-update units, TLS, and a verification pass. Safe to re-run -- every step checks before it
# acts, so a failed run can be fixed and the script run again rather than unpicked.
#
# Options:
#   --host <addr>   Public address participants browse to. Default: this instance's public IP from
#                   EC2 metadata, which is almost always what you want
#   --port <n>      Public HTTPS port. Default 443. Use a high port where something already owns 443
#   --channel <c>   Self-update channel: tags (default), branch, off
#   --no-tls        Skip Caddy. Only for a box already behind a TLS proxy; --host must then be the
#                   address that proxy serves, including https://
#   --skip-build    Install everything but do not build or start the stack
set -euo pipefail

HOST=""
PORT=443
CHANNEL="tags"
WITH_TLS=1
BUILD=1
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

say() { printf '\n\033[1m==> %s\033[0m\n' "$*"; }
note() { printf '    %s\n' "$*"; }
die() { printf '\n\033[1;31mFAILED: %s\033[0m\n' "$*" >&2; exit 1; }

while [ $# -gt 0 ]; do
  case "$1" in
    --host) HOST="${2:?--host needs a value}"; shift 2 ;;
    --port) PORT="${2:?--port needs a value}"; shift 2 ;;
    --channel) CHANNEL="${2:?--channel needs a value}"; shift 2 ;;
    --no-tls) WITH_TLS=0; shift ;;
    --skip-build) BUILD=0; shift ;;
    -h|--help) sed -n '2,20p' "${BASH_SOURCE[0]}"; exit 0 ;;
    *) die "Unknown option: $1" ;;
  esac
done

case "$CHANNEL" in tags|branch|off) ;; *) die "--channel must be tags, branch or off" ;; esac
case "$PORT" in ''|*[!0-9]*) die "--port must be a number" ;; esac

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
if [ "$WITH_TLS" -eq 1 ]; then
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

say "Finding the public address"
if [ -z "$HOST" ]; then
  # IMDSv2. New instances commonly have v1 disabled, where the plain request returns nothing.
  TOKEN="$(curl -sX PUT http://169.254.169.254/latest/api/token \
    -H 'X-aws-ec2-metadata-token-ttl-seconds: 60' --max-time 5 || true)"
  HOST="$(curl -s -H "X-aws-ec2-metadata-token: $TOKEN" --max-time 5 \
    http://169.254.169.254/latest/meta-data/public-ipv4 || true)"
  [ -n "$HOST" ] || die "Could not read this instance's public IP. Pass --host <address>."
  note "detected $HOST"
else
  note "using $HOST"
fi
# --no-tls hands the origin over verbatim, because the proxy in front decides the scheme and port.
if [ "$WITH_TLS" -eq 1 ]; then
  if [ "$PORT" = "443" ]; then ORIGIN="https://$HOST"; else ORIGIN="https://$HOST:$PORT"; fi
else
  case "$HOST" in http://*|https://*) ORIGIN="$HOST" ;; *) ORIGIN="https://$HOST" ;; esac
fi

if [ "$WITH_TLS" -eq 1 ]; then
  say "Checking port $PORT is free"
  if ss -ltn "sport = :$PORT" | grep -q LISTEN; then
    die "Something already listens on $PORT. Use --port <n>, or stop that service."
  fi
  if iptables-save -t nat 2>/dev/null | grep -q -- "--dport $PORT .*REDIRECT"; then
    die "A firewall rule redirects port $PORT elsewhere, so this proxy would never receive traffic.
       Inspect it with: sudo iptables-save -t nat | grep -- '--dport $PORT'
       Then either remove that rule or pick a different port with --port <n>."
  fi
  note "port $PORT is free"
fi

say "Writing configuration"
sudo -u "$OWNER" python3 "$ROOT/scripts/setup_env.py" --origin "$ORIGIN" \
  || die "setup_env.py failed"
# As the owner, not as root: `sed -i` replaces the file rather than editing in place, so running it
# as root would leave a 0600 root-owned .env that the account running compose cannot read.
# Idempotent -- delete then append, so re-running does not stack duplicate lines.
sudo -u "$OWNER" sed -i '/^UPDATE_CHANNEL=/d' "$ROOT/.env"
printf 'UPDATE_CHANNEL=%s\n' "$CHANNEL" | sudo -u "$OWNER" tee -a "$ROOT/.env" >/dev/null
note "APP_ORIGIN=$ORIGIN, UPDATE_CHANNEL=$CHANNEL"

say "Checking containers can reach the internet"
EGRESS="$(docker run --rm python:3.12-slim python -c \
  "import urllib.request;print(urllib.request.urlopen('https://api.openai.com/v1/models',timeout=15).status)" 2>&1 || true)"
if printf '%s' "$EGRESS" | grep -qiE 'certificate|SSLError|hostname mismatch'; then
  note "outbound HTTPS from containers is being redirected; exempting Docker's bridges"
  for IFACE in docker0 br+; do
    iptables -t nat -C PREROUTING -i "$IFACE" -p tcp --dport 443 -j RETURN 2>/dev/null \
      || iptables -t nat -I PREROUTING 1 -i "$IFACE" -p tcp --dport 443 -j RETURN
  done
  EGRESS="$(docker run --rm python:3.12-slim python -c \
    "import urllib.request;print(urllib.request.urlopen('https://api.openai.com/v1/models',timeout=15).status)" 2>&1 || true)"
  if printf '%s' "$EGRESS" | grep -qiE 'certificate|SSLError|hostname mismatch'; then
    die "Container egress is still redirected. See docs/workshop.md, 'When containers cannot reach the internet'."
  fi
  note "fixed -- note this does NOT survive a reboot; see docs/workshop.md"
fi
# A 401 is the expected answer: the request arrived and was rejected for having no key.
printf '%s' "$EGRESS" | grep -qE '401|200' || die "Containers cannot reach api.openai.com:
$EGRESS"
note "reached api.openai.com (401 = arrived, no key supplied)"

say "Installing the self-update units"
INSTALL_ARGS=()
if [ "$BUILD" -eq 1 ]; then INSTALL_ARGS+=(--build); fi
python3 "$ROOT/scripts/install_service.py" "${INSTALL_ARGS[@]}" \
  || die "install_service.py failed"

if [ "$WITH_TLS" -eq 1 ]; then
  say "Terminating TLS on port $PORT"
  # default_sni is required, not optional: TLS forbids sending SNI for an IP address, so browsers
  # send no server name and Caddy would otherwise abort every handshake with an internal error --
  # after logging that it obtained the certificate and bound the port.
  printf '{\n\tauto_https disable_redirects\n\tdefault_sni %s\n\tskip_install_trust\n}\n%s:%s {\n\ttls internal\n\treverse_proxy 127.0.0.1:3000\n}\n' \
    "$HOST" "$HOST" "$PORT" > /etc/caddy/Caddyfile
  caddy validate --config /etc/caddy/Caddyfile >/dev/null 2>&1 \
    || die "Caddy rejected the generated config; see /etc/caddy/Caddyfile"
  systemctl restart caddy
  note "wrote /etc/caddy/Caddyfile and restarted caddy"
fi

if [ "$BUILD" -eq 1 ]; then
  say "Verifying"
  STACK="$(curl -s -o /dev/null -w '%{http_code}' --max-time 10 http://127.0.0.1:3000/ || true)"
  note "stack on 127.0.0.1:3000 -> $STACK"
  [ "$STACK" = "200" ] || die "The application is not answering. Check: docker compose ps; docker compose logs backend"
  if [ "$WITH_TLS" -eq 1 ]; then
    PROXY="$(curl -sk -o /dev/null -w '%{http_code}' --max-time 10 \
      --connect-to "$HOST:$PORT:127.0.0.1:$PORT" "https://$HOST:$PORT/" || true)"
    note "proxy on $PORT -> $PROXY"
    [ "$PROXY" = "200" ] || die "Caddy is not serving. Check: journalctl -u caddy -n 30"
  fi
fi

URL="$ORIGIN"
cat <<EOF

$(printf '\033[1;32mInstalled.\033[0m')

  Open            $URL
  Presenter       $URL/demo-admin
  Customer login  12345678

Still to do, and neither can be done from this box:

  1. Open inbound TCP $PORT to this instance in its security group.
  2. Browse the address above from another machine and accept the certificate
     warning once. This instance cannot reach its own public IP, so testing
     from here proves nothing.

Then set the model endpoint in the presenter portal -- not in .env.

  Update now        sudo systemctl start splunky-finance
  What it decided   journalctl -u splunky-finance -n 30
  Channel           UPDATE_CHANNEL=$CHANNEL in .env
EOF
